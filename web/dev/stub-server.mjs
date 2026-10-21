#!/usr/bin/env node
/**
 * Sidekick development stub server.
 *
 * SIMULATED_TEST_ONLY - this is a development double, not the real Sidekick
 * backend. It implements the v1 request/response contract so the web client
 * can be developed, demonstrated and tested before the Core/Execution agents
 * land their services.
 *
 * The capabilities endpoint reports `mode: "stub"` so the browser can label
 * every capability honestly instead of pretending it is live.
 *
 * Run:  node dev/stub-server.mjs           (listens on 127.0.0.1:8000)
 */

import { createServer } from 'node:http'
import { randomUUID } from 'node:crypto'

const PORT = Number(process.env.SIDECKICK_STUB_PORT ?? 8000)
const HOST = process.env.SIDECKICK_STUB_HOST ?? '127.0.0.1'

/** sessionId -> { lastPlan, lastRequestId, pendingAction } */
const sessions = new Map()

const CAPABILITIES = {
  contract_version: 'v1',
  mode: 'stub',
  capabilities: [
    { id: 'voice.stt', state: 'live', detail: 'Browser Web Speech API (not Alexa+).' },
    { id: 'voice.tts', state: 'live', detail: 'Browser Speech Synthesis API.' },
    { id: 'intent.resolve', state: 'simulated', detail: 'Deterministic rule-based stub resolver.' },
    { id: 'coding.run', state: 'simulated', detail: 'Stub job that streams a canned diff.' },
    { id: 'music.play', state: 'unconfigured', detail: 'No music provider credentials configured.' },
    { id: 'game.chess', state: 'simulated', detail: 'Stub board, no rules engine.' },
    { id: 'media.play', state: 'live', detail: 'Local media manifest with shipped subtitle cues.' },
  ],
  games: [
    { id: 'chess', name: 'Chess', state: 'simulated', detail: 'Stub position, no rules engine.' },
  ],
  providers: [
    {
      id: 'spotify',
      name: 'Spotify',
      state: 'unconfigured',
      detail: 'Requires a Spotify developer app id and a user access token.',
      requires_user_action: true,
    },
    {
      id: 'youtube',
      name: 'YouTube Music',
      state: 'unconfigured',
      detail: 'Requires an OAuth client and a user account with playback access.',
      requires_user_action: true,
    },
  ],
}

const DESTINATIONS = [
  { key: 'spotify', tool: 'music.play', label: 'Spotify' },
  { key: 'youtube', tool: 'music.play', label: 'YouTube' },
  { key: 'apple music', tool: 'music.play', label: 'Apple Music' },
  { key: 'netflix', tool: 'media.play', label: 'Netflix' },
  { key: 'youtube video', tool: 'media.play', label: 'YouTube video' },
]

const RISKY = /\b(delete|remove|drop|terminate|revoke|format|wipe)\b/i

function detectDestination(text) {
  const lower = text.toLowerCase()
  const found = DESTINATIONS.filter((destination) => lower.includes(destination.key)).sort(
    (a, b) => b.key.length - a.key.length,
  )
  return found[0] ?? null
}

function splitActions(text) {
  return text
    .split(/\s+(?:and then|and also|then)\s+/i)
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
}

function buildAction(tool, args, extra = {}) {
  const now = new Date().toISOString()
  return {
    action_id: randomUUID(),
    tool,
    arguments: args,
    approval_required: Boolean(extra.approval_required),
    state: extra.state ?? 'pending',
    superseded_by: null,
    ...(extra.result !== undefined ? { result: extra.result } : {}),
    ...(extra.error ? { error: extra.error } : {}),
    timestamps: { created: now, updated: now },
  }
}

/**
 * Deterministic intent resolution. This is a stand-in for the real decision
 * engine - it does not call a model and it does not claim to.
 */
function resolve({ utterance, sessionId, requestId, previous }) {
  const lower = utterance.toLowerCase()
  const events = []
  const isCorrection = /\b(no[ ,]?wait|actually|instead|scratch that|sorry)\b/.test(lower)

  let segments = splitActions(utterance)
  if (isCorrection && previous?.segments?.length) {
    // A correction replaces the earlier destination before anything executes.
    const corrected = previous.segments.map((segment) => {
      const destination = detectDestination(segment)
      return destination ? segment.replace(destination.key, 'spotify') : segment
    })
    segments = corrected
    events.push({
      seq: 1,
      kind: 'log',
      message: 'Correction detected - the earlier destination was replaced before execution.',
      at: new Date().toISOString(),
    })
  }

  const actions = []
  let clarification = null
  let risk = 'low'

  for (const segment of segments) {
    const destination = detectDestination(segment)
    if (destination) {
      const action = buildAction(destination.tool, {
        query: segment,
        provider: destination.label,
      })
      if (RISKY.test(segment)) {
        action.approval_required = true
        action.state = 'awaiting_confirmation'
        risk = 'high'
      }
      actions.push(action)
      continue
    }

    if (/\b(chess|game)\b/i.test(segment)) {
      actions.push(
        buildAction('game.chess', { command: segment }, {
          result: {
            position: {
              fen: 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
              turn: 'w',
              last_move: null,
              selected: null,
              legal_targets: [],
            },
          },
        }),
      )
      continue
    }

    if (/\b(write|refactor|fix|implement|add a function|patch)\b/i.test(segment)) {
      actions.push(buildAction('coding.run', { task: segment }, { state: 'running' }))
      continue
    }

    if (/\b(hello|hi|who are you|help)\b/i.test(segment)) {
      actions.push(buildAction('assistant.reply', { message: segment }))
      continue
    }

    clarification = {
      question: `I am not sure what you mean by "${segment}". Which of these did you want?`,
      options: ['Play it on Spotify', 'Play it on YouTube', 'Start a chess game'],
    }
    break
  }

  if (actions.length === 0 && !clarification) {
    clarification = {
      question: 'I did not find an action in that request. What should I do?',
      options: ['Play music on Spotify', 'Watch a film', 'Start a chess game'],
    }
  }

  const status = actions.some((action) => action.state === 'awaiting_confirmation')
    ? 'awaiting_confirmation'
    : actions.length > 0
      ? 'running'
      : 'failed'

  if (actions.some((action) => action.state === 'awaiting_confirmation')) {
    clarification = {
      question: `This will ${RISKY.test(utterance) ? 'permanently change something' : 'run an action'} on your system. Confirm?`,
      options: ['Yes, do it', 'No, cancel'],
    }
  }

  return {
    response: {
      request_id: requestId,
      session_id: sessionId,
      intent: {
        normalized: utterance.trim(),
        confidence: clarification ? 0.45 : 0.88,
        ambiguous: Boolean(clarification),
        entities: [],
      },
      action_plan: actions,
      risk_level: risk,
      decision_model: {
        provider: 'sidekick-dev-stub',
        model: 'deterministic-rules',
        fallback_used: false,
      },
      status,
      clarification,
      events,
      speech: null,
    },
    segments,
  }
}

const CODING_DIFF = `@@ -1,6 +1,8 @@
 export function greet(name) {
-  return 'Hello ' + name
+  const trimmed = name.trim()
+  if (!trimmed) return 'Hello'
+  return \`Hello \${trimmed}\`
 }
`

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
    sendJson(response, 200, CAPABILITIES)
    return
  }

  if (url.pathname === '/api/v1/requests' && request.method === 'POST') {
    const body = await readBody(request)
    const sessionId =
      request.headers['x-sidekick-session-id'] ?? body.session_id ?? `anon-${randomUUID()}`
    const requestId = body.request_id ?? randomUUID()
    const utterance = typeof body.utterance === 'string' ? body.utterance : ''

    if (!utterance.trim()) {
      sendJson(response, 400, {
        error: { code: 'invalid_request', message: 'utterance must not be empty', retryable: false },
      })
      return
    }

    const state = sessions.get(sessionId) ?? { segments: [], pendingAction: null }
    const { response: payload, segments } = resolve({
      utterance,
      sessionId,
      requestId,
      previous: state,
    })
    sessions.set(sessionId, { segments, pendingAction: null })

    const streaming = url.searchParams.get('stream') === '1'

    if (!streaming) {
      sendJson(response, 200, payload)
      return
    }

    response.writeHead(200, {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
      connection: 'keep-alive',
      'access-control-allow-origin': '*',
    })

    const coding = payload.action_plan.find((action) => action.tool === 'coding.run')
    if (coding) {
      sse(response, { seq: 1, kind: 'progress', message: 'Job queued', at: new Date().toISOString() })
      sse(response, {
        seq: 2,
        kind: 'progress',
        message: 'Reading the workspace',
        at: new Date().toISOString(),
      })
      sse(response, {
        seq: 3,
        kind: 'diff',
        message: 'Patch produced',
        action_id: coding.action_id,
        data: { files: [{ path: 'src/greet.ts', diff: CODING_DIFF }] },
        at: new Date().toISOString(),
      })
      sse(response, {
        seq: 4,
        kind: 'result',
        message: 'Job finished',
        action_id: coding.action_id,
        at: new Date().toISOString(),
      })
      coding.state = 'succeeded'
      coding.result = { files: [{ path: 'src/greet.ts', diff: CODING_DIFF }] }
      payload.status = 'succeeded'
    }

    sse(response, payload)
    response.end()
    return
  }

  sendJson(response, 404, {
    error: { code: 'not_found', message: `No route for ${request.method} ${url.pathname}`, retryable: false },
  })
})

server.listen(PORT, HOST, () => {
  console.log(`[sidekick-stub] SIMULATED_TEST_ONLY backend on http://${HOST}:${PORT}`)
  console.log('[sidekick-stub] Try: curl -s http://127.0.0.1:8000/api/v1/capabilities')
})
