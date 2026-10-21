import { vi } from 'vitest'

/**
 * A controllable fake backend for the browser client tests.
 *
 * It implements the contract endpoints the client uses - including the exact
 * approve/cancel contract (session id in the body, plan hash bound to the
 * approval) - so the regression cases exercise the real request shapes.
 */

export interface FakeAction {
  action_id: string
  tool: string
  arguments: Record<string, unknown>
  approval_required: boolean
  state: string
  superseded_by: string | null
  description: string
  plan_hash: string
  job_id: string | null
  progress: number | null
  result: unknown
  error: { code: string; message: string; retryable: boolean; timeout: boolean } | null
  timestamps: { created: string; updated: string }
}

export interface FakeResponse {
  request_id: string
  session_id: string
  intent: { normalized: string; confidence: number; ambiguous: boolean; entities: unknown[] }
  action_plan: FakeAction[]
  risk_level: 'low' | 'medium' | 'high' | 'irreversible'
  decision_model: {
    provider: string
    model: string
    source?: string
    fallback_used: boolean
  }
  status: string
  clarification: { question: string; options: string[] } | null
  events: Array<Record<string, unknown>>
  speech?: string | null
}

export interface FakeBackend {
  /** Actions the backend knows about, keyed by action id. */
  actions: Map<string, FakeAction>
  /** Every request the client sent, in order. */
  requests: Array<{ url: string; method: string; body: unknown }>
  /** The next response for POST /api/v1/requests. */
  nextResponse: (utterance: string, sessionId: string, requestId: string) => FakeResponse
  /** The capability inventory. */
  capabilities: Record<string, unknown>
  /** When set, the next matching action call fails with this status. */
  failNextActionCall: {
    /** Only fail a call whose url ends with this. */
    urlSuffix?: string
    /** Only fail a call with this method. */
    method?: string
    status: number
    code: string
    message: string
  } | null
}

const now = () => new Date().toISOString()

export function makeAction(overrides: Partial<FakeAction> = {}): FakeAction {
  return {
    action_id: `act-${Math.random().toString(36).slice(2, 10)}`,
    tool: 'note.write',
    arguments: {},
    approval_required: false,
    state: 'pending',
    superseded_by: null,
    description: '',
    plan_hash: `plan-${Math.random().toString(36).slice(2, 10)}`,
    job_id: null,
    progress: null,
    result: null,
    error: null,
    timestamps: { created: now(), updated: now() },
    ...overrides,
  }
}

export function createFakeBackend(): FakeBackend {
  const backend: FakeBackend = {
    actions: new Map(),
    requests: [],
    nextResponse: (utterance, sessionId, requestId) => ({
      request_id: requestId,
      session_id: sessionId,
      intent: { normalized: utterance, confidence: 0.9, ambiguous: false, entities: [] },
      action_plan: [],
      risk_level: 'low',
      decision_model: { provider: 'fake', model: 'fake-model', source: 'rules', fallback_used: false },
      status: 'succeeded',
      clarification: null,
      events: [],
      speech: null,
    }),
    capabilities: {
      contract_version: 'v1',
      mode: 'stub',
      capabilities: [{ id: 'note.write', state: 'live', detail: 'backed by a real adapter' }],
      tools: [{ tool: 'note.write', status: 'REAL', status_detail: 'backed by a real adapter' }],
      tool_count: 1,
      games: [],
      providers: [],
    },
    failNextActionCall: null,
  }
  return backend
}

/** Install the fake backend as the global fetch. */
/** A minimal SpeechRecognition stand-in so the supported path can be tested. */
export class FakeSpeechRecognition {
  lang = 'en-US'
  continuous = false
  interimResults = false
  maxAlternatives = 1
  onresult: ((event: unknown) => void) | null = null
  onerror: ((event: { error: string }) => void) | null = null
  onend: (() => void) | null = null
  onstart: (() => void) | null = null
  onaudiostart: (() => void) | null = null
  onnomatch: (() => void) | null = null

  start(): void {
    this.onstart?.()
  }
  stop(): void {
    this.onend?.()
  }
  abort(): void {
    this.onend?.()
  }
}

/** Install (or remove) the Web Speech recognition API in the test window. */
export function installSpeechRecognition(present = true): void {
  const target = window as unknown as Record<string, unknown>
  if (present) {
    target.SpeechRecognition = FakeSpeechRecognition
    delete target.webkitSpeechRecognition
  } else {
    delete target.SpeechRecognition
    delete target.webkitSpeechRecognition
  }
}

export function installFakeBackend(backend: FakeBackend): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = (init?.method ?? 'GET').toUpperCase()
      let body: unknown = null
      if (typeof init?.body === 'string') {
        try {
          body = JSON.parse(init.body)
        } catch {
          body = init.body
        }
      }
      backend.requests.push({ url, method, body })

      const json = (payload: unknown, status = 200) =>
        new Response(JSON.stringify(payload), {
          status,
          headers: { 'content-type': 'application/json' },
        })

      if (url.includes('/capabilities')) {
        return json(backend.capabilities)
      }

      if (url.includes('/api/v1/requests') && method === 'POST') {
        const payload = body as {
          request_id?: string
          session_id?: string
          utterance?: string
        }
        const requestId = payload?.request_id ?? 'req-1'
        const sessionId = payload?.session_id ?? 'session-1'
        const utterance = payload?.utterance ?? ''
        const response = backend.nextResponse(utterance, sessionId, requestId)
        for (const action of response.action_plan) backend.actions.set(action.action_id, action)
        return json(response)
      }

      const actionMatch = /\/api\/v1\/actions\/([^/?]+)/.exec(url)
      if (actionMatch) {
        if (
          backend.failNextActionCall &&
          (!backend.failNextActionCall.urlSuffix ||
            url.endsWith(backend.failNextActionCall.urlSuffix)) &&
          (!backend.failNextActionCall.method ||
            method === backend.failNextActionCall.method)
        ) {
          const failure = backend.failNextActionCall
          backend.failNextActionCall = null
          return json(
            {
              error: {
                code: failure.code,
                message: failure.message,
                retryable: false,
                timeout: false,
                details: {},
              },
            },
            failure.status,
          )
        }
        const actionId = decodeURIComponent(actionMatch[1] ?? '')
        const action = backend.actions.get(actionId)
        if (!action) {
          return json(
            { error: { code: 'not_found', message: `unknown action: ${actionId}`, retryable: false, timeout: false, details: {} } },
            404,
          )
        }
        const payload = body as { session_id?: string; approved?: boolean; plan_hash?: string }

        if (url.endsWith('/approve') && method === 'POST') {
          if (action.state !== 'awaiting_confirmation') {
            return json(
              { error: { code: 'conflict', message: 'the action is not waiting for confirmation', retryable: false, timeout: false, details: {} } },
              409,
            )
          }
          if (payload?.plan_hash && payload.plan_hash !== action.plan_hash) {
            return json(
              { error: { code: 'conflict', message: 'the plan changed before the confirmation arrived', retryable: false, timeout: false, details: {} } },
              409,
            )
          }
          action.state = payload?.approved === false ? 'cancelled' : 'running'
          action.timestamps.updated = now()
          return json({ action })
        }

        if (url.endsWith('/cancel') && method === 'POST') {
          if (!payload?.session_id) {
            return json(
              { error: { code: 'invalid_request', message: 'the request payload is not valid', retryable: false, timeout: false, details: {} } },
              422,
            )
          }
          if (['succeeded', 'failed', 'cancelled'].includes(action.state)) {
            return json(
              { error: { code: 'conflict', message: 'the action already finished', retryable: false, timeout: false, details: {} } },
              409,
            )
          }
          action.state = 'cancelled'
          action.timestamps.updated = now()
          return json({ action })
        }

        return json({ action, events: [] })
      }

      return json(
        { error: { code: 'not_found', message: `No route for ${method} ${url}`, retryable: false, timeout: false, details: {} } },
        404,
      )
    }),
  )
}
