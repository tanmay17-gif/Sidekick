#!/usr/bin/env node
/**
 * Sidekick development stub server.
 *
 * SIMULATED_TEST_ONLY - this is a development double, not the real Sidekick
 * backend. It implements the v1 contract closely enough that the browser
 * client can be developed, demonstrated and tested against it:
 *
 *   POST /api/v1/requests                  one user turn (JSON or SSE)
 *   GET  /api/v1/capabilities              the capability inventory
 *   GET  /api/v1/media/catalog             empty - the client falls back
 *   GET  /api/v1/actions/{id}              one action and its events
 *   GET  /api/v1/actions/{id}/events       SSE stream of that action
 *   POST /api/v1/actions/{id}/approve      approve or refuse (plan_hash bound)
 *   POST /api/v1/actions/{id}/cancel       cancel one action
 *   GET  /v1/sessions/{id}                 session state
 *
 * Everything it executes is labelled SIMULATED in the capability report and in
 * every result, so the interface can never present it as a live action.
 */

import { createServer } from 'node:http'
import { randomUUID } from 'node:crypto'

const PORT = Number(process.env.SIDECKICK_STUB_PORT ?? 8000)
const HOST = process.env.SIDECKICK_STUB_HOST ?? '127.0.0.1'
const STEP_MS = Number(process.env.SIDECKICK_STUB_STEP_MS ?? 120)

/** sessionId -> { actions: Map, events: [], lastPlan: [] } */
const sessions = new Map()

const CAPABILITY_TOOLS = [
  {
    tool: 'note.write',
    description: 'Write a note into the workspace',
    arguments_schema: { content: { name: 'content', type: 'string', required: true } },
    approval_required: false,
    risk_level: 'low',
    status: 'SIMULATED',
    status_detail: 'development stub - writes a simulated note',
  },
  {
    tool: 'note.read',
    description: 'Read the notes in the workspace',
    arguments_schema: { name: { name: 'name', type: 'string', required: false } },
    approval_required: false,
    risk_level: 'low',
    status: 'SIMULATED',
    status_detail: 'development stub - reads simulated notes',
  },
  {
    tool: 'timer.set',
    description: 'Set a timer',
    arguments_schema: { seconds: { name: 'seconds', type: 'number', required: true } },
    approval_required: false,
    risk_level: 'low',
    status: 'SIMULATED',
    status_detail: 'development stub - a simulated timer',
  },
  {
    tool: 'timer.list',
    description: 'List the timers',
    arguments_schema: {},
    approval_required: false,
    risk_level: 'low',
    status: 'SIMULATED',
    status_detail: 'development stub - a simulated timer list',
  },
  {
    tool: 'media.open',
    description: 'Open a media source',
    arguments_schema: { query: { name: 'query', type: 'string', required: true } },
    approval_required: false,
    risk_level: 'low',
    status: 'SIMULATED',
    status_detail: 'development stub - opens a simulated media source',
  },
  {
    tool: 'game.chess',
    description: 'Start or continue a chess game',
    arguments_schema: { command: { name: 'command', type: 'string', required: true } },
    approval_required: false,
    risk_level: 'low',
    status: 'SIMULATED',
    status_detail: 'development stub - a simulated board, no rules engine',
  },
  {
    tool: 'music.play',
    description: 'Play a track on a music provider',
    arguments_schema: { query: { name: 'query', type: 'string', required: true } },
    approval_required: false,
    risk_level: 'low',
    status: 'NOT_CONFIGURED',
    status_detail: 'no music provider credentials are configured',
  },
  {
    tool: 'workspace.delete',
    description: 'Delete a file from the workspace',
    arguments_schema: { path: { name: 'path', type: 'string', required: true } },
    approval_required: true,
    risk_level: 'high',
    status: 'SIMULATED',
    status_detail: 'development stub - a simulated destructive action',
  },
]

const SIMULATED_PROVIDER = {
  name: 'dev-stub',
  level: 'SIMULATED',
  simulated: true,
  available: true,
  reason: 'development stub',
  model: 'rule-engine-stub',
  latency_ms: 12,
}

function capabilitiesPayload() {
  return {
    contract_version: 'v1',
    mode: 'stub',
    capabilities: CAPABILITY_TOOLS.map((tool) => ({
      id: tool.tool,
      state: tool.status === 'REAL' ? 'live' : tool.status === 'SIMULATED' ? 'simulated' : 'unconfigured',
      detail: tool.status_detail,
    })),
    tools: CAPABILITY_TOOLS,
    tool_count: CAPABILITY_TOOLS.length,
    status_counts: CAPABILITY_TOOLS.reduce((counts, tool) => {
      counts[tool.status] = (counts[tool.status] ?? 0) + 1
      return counts
    }, {}),
    any_simulated: true,
    games: [{ id: 'chess', name: 'Chess', state: 'simulated', detail: 'development stub board' }],
    providers: [
      {
        id: 'spotify',
        name: 'Spotify',
        state: 'unconfigured',
        detail: 'no provider credentials are configured',
        requires_user_action: true,
      },
    ],
  }
}

function sessionFor(sessionId) {
  let session = sessions.get(sessionId)
  if (!session) {
    session = { actions: new Map(), events: [], turns: [] }
    sessions.set(sessionId, session)
  }
  return session
}

function nowIso() {
  return new Date().toISOString()
}

function makeAction(tool, args, extra = {}) {
  const now = nowIso()
  return {
    action_id: randomUUID(),
    tool,
    arguments: args,
    approval_required: Boolean(extra.approval_required),
    state: extra.state ?? 'pending',
    superseded_by: null,
    description: extra.description ?? '',
    plan_hash: `stub-${tool}-${Math.random().toString(36).slice(2, 10)}`,
    job_id: extra.job_id ?? null,
    progress: null,
    result: null,
    error: null,
    timestamps: { created: now, updated: now },
    ...(extra.description ? {} : {}),
  }
}

function recordEvent(session, action, { type, kind, message, status, seq }) {
  const event = {
    type,
    kind,
    seq,
    ts: nowIso(),
    at: nowIso(),
    action_id: action ? action.action_id : undefined,
    job_id: action ? action.job_id ?? action.action_id : undefined,
    tool: action ? action.tool : undefined,
    status: status ?? (action ? action.state : undefined),
    message,
    data: {},
  }
  session.events.push(event)
  return event
}

/* ------------------------------------------------------------------ *
 * Intent resolution - deterministic, and clearly a stub.
 * ------------------------------------------------------------------ */

const DESTINATIONS = [
  // The core maps every media destination onto `media.open`; the stub does
  // the same so the development experience matches the real backend.
  { key: 'spotify', tool: 'media.open' },
  { key: 'youtube', tool: 'media.open' },
  { key: 'youtube video', tool: 'media.open' },
  { key: 'netflix', tool: 'media.open' },
  { key: 'apple music', tool: 'media.open' },
]

const RISKY = /\b(delete|remove|drop|terminate|revoke|wipe|erase)\b/i

function detectTool(text) {
  const lower = text.toLowerCase()
  const found = DESTINATIONS.filter((entry) => lower.includes(entry.key)).sort(
    (a, b) => b.key.length - a.key.length,
  )
  if (found.length > 0) return found[0]
  if (/\b(chess|game)\b/i.test(lower)) return { key: 'chess', tool: 'game.chess' }
  if (/\b(timer|alarm)\b/i.test(lower)) return { key: 'timer', tool: 'timer.set' }
  if (/\b(note|memo|remember)\b/i.test(lower)) return { key: 'note', tool: 'note.write' }
  return null
}

function splitActions(text) {
  return text
    .split(/\s+(?:and then|and also|then)\s+/i)
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
}

/**
 * Build the plan for one turn. A correction replaces the earlier destination
 * before anything executes, exactly as the contract requires.
 */
function planFor(text, previousPlan) {
  const corrected = /\b(no[ ,]?wait|actually|instead|scratch that)\b/i.test(text)
  let segments = splitActions(text)

  if (corrected && previousPlan && previousPlan.length > 0) {
    segments = previousPlan.map((segment) =>
      segment.replace(/\b(youtube|netflix|spotify|apple music)\b/i, 'spotify'),
    )
  }

  const actions = []
  let clarification = null

  for (const segment of segments) {
    const detected = detectTool(segment)
    if (!detected) {
      clarification = {
        question: `I am not sure what you mean by "${segment}". Which of these did you want?`,
        options: ['Play it on Spotify', 'Open it on YouTube', 'Start a chess game', 'Write a note'],
      }
      break
    }

    const risky = RISKY.test(segment)
    const tool = risky ? 'workspace.delete' : detected.tool
    const action = makeAction(tool, { query: segment, path: segment }, {
      approval_required: risky,
      state: risky ? 'awaiting_confirmation' : 'pending',
      description: segment,
      job_id: randomUUID(),
    })
    actions.push(action)
  }

  if (actions.length === 0 && !clarification) {
    clarification = {
      question: 'I did not find an action in that request. What should I do?',
      options: ['Play music on Spotify', 'Open a video', 'Write a note', 'Start a chess game'],
    }
  }

  return { actions, clarification, segments }
}

/**
 * Execute one action through its lifecycle.
 *
 * The state machine is real: pending -> running -> succeeded | failed, with a
 * cancellation honoured while it is in flight. What it *produces* is labelled
 * SIMULATED, because that is what it is.
 */
function runAction(session, action) {
  if (action.state === 'awaiting_confirmation') return
  if (action.state === 'cancelled') return

  action.state = 'running'
  action.timestamps.updated = nowIso()
  recordEvent(session, action, {
    type: 'action.started',
    kind: 'progress',
    message: `${action.tool} started`,
    seq: session.events.length + 1,
  })

  // A timer genuinely keeps running until it is cancelled, so the interface
  // has something real to cancel.
  const duration = action.tool === 'timer.set' ? 8000 : STEP_MS

  setTimeout(() => {
    if (action.state !== 'running') return

    const tool = CAPABILITY_TOOLS.find((entry) => entry.tool === action.tool)
    if (tool && tool.status === 'NOT_CONFIGURED') {
      action.state = 'failed'
      action.error = {
        code: 'tool_unavailable',
        message: `${action.tool} is not configured on this backend`,
        retryable: false,
        timeout: false,
        details: { status_detail: tool.status_detail },
      }
      action.timestamps.updated = nowIso()
      recordEvent(session, action, {
        type: 'action.failed',
        kind: 'error',
        message: action.error.message,
        seq: session.events.length + 1,
      })
      return
    }

    action.state = 'succeeded'
    action.progress = 1
    action.result = {
      outcome: 'succeeded',
      summary: `${action.tool} completed in the development stub.`,
      provider: SIMULATED_PROVIDER,
      simulated: true,
    }
    action.timestamps.updated = nowIso()
    recordEvent(session, action, {
      type: 'action.succeeded',
      kind: 'result',
      message: `${action.tool} succeeded`,
      seq: session.events.length + 1,
    })
  }, duration)
}

/* ------------------------------------------------------------------ *
 * HTTP plumbing
 * ------------------------------------------------------------------ */

async function readBody(request) {
  const chunks = []
  for await (const chunk of request) chunks.push(chunk)
  if (chunks.length === 0) return {}
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'))
  } catch {
    return {}
  }
}

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload)
  response.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(body),
    'access-control-allow-origin': '*',
    'access-control-allow-headers': 'content-type, x-sidekick-session-id',
    'access-control-allow-methods': 'GET, POST, OPTIONS',
  })
  response.end(body)
}

function sendError(response, status, code, message, details = {}) {
  sendJson(response, status, {
    error: { code, message, retryable: false, timeout: false, details },
  })
}

function sse(response, event) {
  response.write(`data: ${JSON.stringify(event)}\n\n`)
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? '/', `http://${request.headers.host ?? 'localhost'}`)

  if (request.method === 'OPTIONS') {
    response.writeHead(204, {
      'access-control-allow-origin': '*',
      'access-control-allow-headers': 'content-type, x-sidekick-session-id',
      'access-control-allow-methods': 'GET, POST, OPTIONS',
    })
    response.end()
    return
  }

  if (url.pathname === '/api/v1/capabilities' && request.method === 'GET') {
    sendJson(response, 200, capabilitiesPayload())
    return
  }

  if (url.pathname === '/api/v1/media/catalog' && request.method === 'GET') {
    sendJson(response, 200, { contract_version: 'v1', assets: [] })
    return
  }

  /* ---- action endpoints ---------------------------------------- */

  // The action routes are: the action itself, its event stream, and the two
  // lifecycle calls. All four shapes have to match, otherwise the approval and
  // cancellation calls fall through to "no route" and the interface cannot
  // complete an action.
  const actionMatch = /^\/api\/v1\/actions\/([^/]+)(\/events|\/approve|\/cancel)?$/.exec(
    url.pathname,
  )
  if (actionMatch) {
    const actionId = decodeURIComponent(actionMatch[1])
    const actionRoute = actionMatch[2] ?? ''
    const isEvents = actionRoute === '/events'
    const body = request.method === 'POST' ? await readBody(request) : {}
    const sessionId =
      body.session_id ??
      url.searchParams.get('session_id') ??
      request.headers['x-sidekick-session-id'] ??
      null

    if (!sessionId) {
      sendError(response, 422, 'invalid_request', 'the request payload is not valid', {
        errors: [{ loc: ['body', 'session_id'], msg: 'field required' }],
      })
      return
    }

    const session = sessionFor(sessionId)
    const action = session.actions.get(actionId)
    if (!action) {
      sendError(response, 404, 'not_found', `unknown action: ${actionId}`)
      return
    }

    if (isEvents && request.method === 'GET') {
      const after = Number(url.searchParams.get('after') ?? 0)
      response.writeHead(200, {
        'content-type': 'text/event-stream',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
        'access-control-allow-origin': '*',
      })
      const relevant = session.events.filter(
        (event) => event.action_id === actionId && event.seq > after,
      )
      for (const event of relevant) sse(response, event)
      response.end()
      return
    }

    if (request.method === 'GET') {
      sendJson(response, 200, {
        action,
        events: session.events.filter((event) => event.action_id === actionId),
      })
      return
    }

    if (request.method === 'POST' && actionRoute === '/approve') {
      const approved = body.approved ?? body.confirmed ?? true
      if (action.state !== 'awaiting_confirmation') {
        sendError(response, 409, 'conflict', 'the action is not waiting for confirmation', {
          state: action.state,
        })
        return
      }
      if (body.plan_hash && body.plan_hash !== action.plan_hash) {
        sendError(response, 409, 'conflict', 'the plan changed before the confirmation arrived', {
          state: action.state,
        })
        return
      }
      if (!approved) {
        action.state = 'cancelled'
        action.timestamps.updated = nowIso()
        recordEvent(session, action, {
          type: 'action.cancelled',
          kind: 'action_update',
          message: 'the action was refused',
          seq: session.events.length + 1,
        })
        sendJson(response, 200, { action })
        return
      }
      action.state = 'pending'
      action.timestamps.updated = nowIso()
      recordEvent(session, action, {
        type: 'action.approved',
        kind: 'action_update',
        message: 'the action was approved',
        seq: session.events.length + 1,
      })
      runAction(session, action)
      sendJson(response, 200, { action })
      return
    }

    if (request.method === 'POST' && actionRoute === '/cancel') {
      if (['succeeded', 'failed', 'cancelled'].includes(action.state)) {
        sendError(response, 409, 'conflict', 'the action already finished', {
          state: action.state,
        })
        return
      }
      action.state = 'cancelled'
      action.timestamps.updated = nowIso()
      recordEvent(session, action, {
        type: 'action.cancelled',
        kind: 'action_update',
        message: 'the action was cancelled',
        seq: session.events.length + 1,
      })
      sendJson(response, 200, { action })
      return
    }
  }

  /* ---- the request endpoint -------------------------------------- */

  if (url.pathname === '/api/v1/requests' && request.method === 'POST') {
    const body = await readBody(request)
    const sessionId =
      request.headers['x-sidekick-session-id'] ?? body.session_id ?? `anon-${randomUUID()}`
    const requestId = body.request_id ?? randomUUID()
    const utterance = typeof body.utterance === 'string' ? body.utterance : ''

    if (!utterance.trim()) {
      sendError(response, 400, 'invalid_request', 'utterance must not be empty')
      return
    }

    const session = sessionFor(sessionId)
    const previousPlan = session.turns.length > 0 ? session.turns[session.turns.length - 1] : []
    const { actions, clarification, segments } = planFor(utterance, previousPlan)
    session.turns.push(segments)

    const events = []
    const push = (type, kind, message, action) => {
      const event = {
        type,
        kind,
        seq: events.length + 1,
        ts: nowIso(),
        at: nowIso(),
        action_id: action ? action.action_id : undefined,
        job_id: action ? action.job_id ?? action.action_id : undefined,
        tool: action ? action.tool : undefined,
        status: action ? action.state : undefined,
        message,
        data: {},
      }
      events.push(event)
      session.events.push(event)
      return event
    }

    push('turn.received', 'log', utterance, null)
    push('model.decided', 'log', 'interpreted with sidekick/rule-engine-stub', null)

    const corrected =
      /\b(no[ ,]?wait|actually|instead|scratch that)\b/i.test(utterance) &&
      previousPlan.length > 0
    if (corrected) {
      push(
        'plan.superseded',
        'log',
        'the earlier destination was replaced before execution',
        null,
      )
    }

    const awaiting = actions.filter((action) => action.state === 'awaiting_confirmation')
    if (clarification && actions.length === 0) {
      push('plan.created', 'log', 'the core asked for one more detail', null)
    } else {
      push('plan.created', 'log', `${actions.length} action(s) planned`, actions[0])
    }

    for (const action of actions) {
      session.actions.set(action.action_id, action)
      if (action.state !== 'awaiting_confirmation') runAction(session, action)
    }

    const status = awaiting.length > 0
      ? 'awaiting_confirmation'
      : clarification && actions.length === 0
        ? 'needs_clarification'
        : 'running'

    const payload = {
      request_id: requestId,
      session_id: sessionId,
      intent: {
        normalized: utterance.trim(),
        confidence: clarification ? 0.45 : 0.88,
        ambiguous: Boolean(clarification),
        entities: [],
      },
      action_plan: actions,
      risk_level: awaiting.length > 0 ? 'high' : 'low',
      decision_model: {
        provider: 'sidekick-dev-stub',
        model: 'rule-engine-stub',
        source: 'rules',
        fallback_used: false,
      },
      status,
      clarification,
      events,
      speech: null,
    }

    const accepts = String(request.headers.accept ?? '')
    const wantsStream = accepts.includes('text/event-stream')
    const longRunning = actions.some((action) => action.tool === 'workspace.delete')

    if (!wantsStream || !longRunning) {
      sendJson(response, 200, payload)
      return
    }

    response.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      connection: 'keep-alive',
      'access-control-allow-origin': '*',
    })
    for (const event of events) sse(response, event)
    sse(response, payload)
    response.end()
    return
  }

  /* ---- session view ---------------------------------------------- */

  const sessionMatch = /^\/v1\/sessions\/([^/]+)$/.exec(url.pathname)
  if (sessionMatch && request.method === 'GET') {
    const session = sessionFor(decodeURIComponent(sessionMatch[1]))
    sendJson(response, 200, {
      session: {
        session_id: decodeURIComponent(sessionMatch[1]),
        active_task_id: null,
        suspended_task_ids: [],
        turn_count: session.turns.length,
        last_intent: null,
        last_tool: null,
      },
      tasks: [],
      actions: [...session.actions.values()],
      events: session.events,
    })
    return
  }

  if (url.pathname === '/healthz' || url.pathname === '/api/v1/health') {
    sendJson(response, 200, { status: 'ok', mode: 'stub' })
    return
  }

  sendError(response, 404, 'not_found', `No route for ${request.method} ${url.pathname}`)
})

server.listen(PORT, HOST, () => {
  console.log(`[sidekick-stub] SIMULATED_TEST_ONLY backend on http://${HOST}:${PORT}`)
  console.log('[sidekick-stub] Try: curl -s http://127.0.0.1:8000/api/v1/capabilities')
})
