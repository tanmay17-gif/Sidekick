import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { App } from '@/App'
import type { SidekickResponse } from '@/lib/api/types'
import {
  createFakeBackend,
  installFakeBackend,
  installSpeechRecognition,
  makeAction,
  type FakeBackend,
} from './support/fake-backend'

const SRT = readFileSync(
  resolve(process.cwd(), 'public/media/duck-and-cover/duck-and-cover.srt'),
  'utf8',
)

function installDefaultFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/capabilities')) {
        return new Response(
          JSON.stringify({
            contract_version: 'v1',
            mode: 'stub',
            capabilities: [{ id: 'note.write', state: 'live' }],
            tools: [{ tool: 'note.write', status: 'REAL' }],
            tool_count: 1,
            games: [],
            providers: [],
          }),
          { headers: { 'content-type': 'application/json' } },
        )
      }
      if (url.includes('.srt')) {
        return new Response(SRT, { headers: { 'content-type': 'text/plain' } })
      }
      if (url.includes('/events')) {
        return new Response('', { headers: { 'content-type': 'text/event-stream' } })
      }
      if (url.includes('/api/v1/requests')) {
        throw new TypeError('Failed to fetch')
      }
      return new Response(
        JSON.stringify({
          request_id: 'req-1',
          session_id: 'sess-1',
          intent: { normalized: 'write a note', confidence: 0.9, ambiguous: false, entities: [] },
          action_plan: [],
          risk_level: 'low',
          decision_model: { provider: 'fake', model: 'fake-model', fallback_used: false },
          status: 'succeeded',
          clarification: null,
          events: [],
        }),
        { headers: { 'content-type': 'application/json' } },
      )
    }),
  )
}

describe('Interface A - the conversational surface', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('leads with the companion and the real state', async () => {
    installDefaultFetch()
    const { container } = render(<App />)

    const companion = container.querySelector('.voice-surface__orb .companion')
    expect(companion).not.toBeNull()
    expect(companion?.getAttribute('data-state')).toBe('idle')
    expect(companion?.getAttribute('aria-label')).toMatch(/here when you need it/i)
    expect(screen.getByText('Ask me anything, or say "Turn on Movie Buddy".')).toBeInTheDocument()
  })

  it('offers a prominent microphone and a clear text alternative', async () => {
    installDefaultFetch()
    installSpeechRecognition(true)
    render(<App />)

    const mic = screen.getByRole('button', { name: /Start voice input/i })
    expect(mic).toBeInTheDocument()
    expect(screen.getByText('Tap to speak')).toBeInTheDocument()
    expect(screen.getByLabelText('Your request')).toBeInTheDocument()
  })

  it('shows the request and a plain-language answer without internal detail', async () => {
    const user = userEvent.setup()
    const backend = createFakeBackend()
    backend.nextResponse = (_utterance, sessionId, requestId) => ({
      request_id: requestId,
      session_id: sessionId,
      intent: { normalized: 'write a note', confidence: 0.91, ambiguous: false, entities: [] },
      action_plan: [
        makeAction({
          tool: 'note.write',
          state: 'succeeded',
          description: 'write a note',
          result: { outcome: 'succeeded', path: '/tmp/note.txt' },
        }),
      ],
      risk_level: 'low',
      decision_model: {
        provider: 'sidekick',
        model: 'rule-engine-v1',
        source: 'rules',
        fallback_used: true,
      },
      status: 'succeeded',
      clarification: null,
      events: [],
    })
    installFakeBackend(backend)

    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'write a note')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText('write a note')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText(/Done with your notes/)).toBeInTheDocument()
    })

    // Nothing technical leaks into the normal experience.
    const exchange = screen.getByText('write a note').closest('.exchange') as HTMLElement
    expect(exchange.textContent).not.toContain('note.write')
    expect(exchange.textContent).not.toContain('rule-engine')
    expect(exchange.textContent).not.toContain('0.91')
    expect(exchange.textContent).not.toContain('req-')
    expect(exchange.textContent).not.toContain('/tmp/note.txt')
  })

  it('offers a text fallback when the browser has no speech engine', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    const original = (window as unknown as Record<string, unknown>).SpeechRecognition
    installSpeechRecognition(false)
    try {
      render(<App />)
      const mic = screen.getByRole('button', { name: /Voice input is not available/i })
      expect(mic).toBeDisabled()
      expect(screen.getByText(/Voice input is not available here/i)).toBeInTheDocument()
      await user.type(screen.getByLabelText('Your request'), 'still works')
      expect(screen.getByLabelText('Your request')).toHaveValue('still works')
    } finally {
      if (original) {
        ;(window as unknown as Record<string, unknown>).SpeechRecognition = original
      }
    }
  })

  it('shows a recoverable failure rather than a raw error', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.type(screen.getByLabelText('Your request'), 'hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText(/I could not reach the backend/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /Try again/i })).toBeInTheDocument()
  })
})

describe('Priority 1 - action state regressions', () => {
  let backend: FakeBackend

  beforeEach(() => {
    vi.restoreAllMocks()
    backend = createFakeBackend()
    installFakeBackend(backend)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const respondWith = (options: {
    utterance: string
    actions: ReturnType<typeof makeAction>[]
    status?: string
    clarification?: { question: string; options: string[] } | null
  }) => {
    backend.nextResponse = (_utterance, sessionId, requestId) => ({
      request_id: requestId,
      session_id: sessionId,
      intent: { normalized: options.utterance, confidence: 0.8, ambiguous: false, entities: [] },
      action_plan: options.actions,
      risk_level: 'low',
      decision_model: {
        provider: 'sidekick',
        model: 'rule-engine-v1',
        source: 'rules',
        fallback_used: false,
      },
      status: options.status ?? 'running',
      clarification: options.clarification ?? null,
      events: [],
    })
  }

  it('does not carry an old pending action into a new request', async () => {
    const user = userEvent.setup()
    const chess = makeAction({
      tool: 'game.chess',
      state: 'pending',
      description: 'start a chess game',
    })
    const music = makeAction({
      tool: 'media.open',
      state: 'succeeded',
      description: 'play a song on spotify',
    })
    respondWith({ utterance: 'chess', actions: [chess] })

    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'start a chess game')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(screen.getByText(/Getting ready to work on the chess board/)).toBeInTheDocument()
    })

    // The next request must not inherit the chess action.
    respondWith({ utterance: 'music', actions: [music] })
    await user.type(screen.getByLabelText('Your request'), 'open youtube and play a song - no wait, spotify')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText(/Done with the media player/)).toBeInTheDocument()
    })
    // The chess card belongs to the earlier exchange, not to the new one.
    const exchanges = document.querySelectorAll('.exchange')
    const latest = exchanges[exchanges.length - 1] as HTMLElement
    expect(latest.textContent).not.toContain('chess board')
  })

  it('does not present the previous session state as current', async () => {
    const user = userEvent.setup()
    const action = makeAction({ tool: 'game.chess', state: 'pending', description: 'start a chess game' })
    respondWith({ utterance: 'chess', actions: [action] })

    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'start a chess game')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(screen.getByText(/Getting ready to work on the chess board/)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'New session' }))

    await waitFor(() => {
      expect(screen.queryByText(/chess board/)).not.toBeInTheDocument()
    })
    expect(screen.getByText('Ask me anything, or say "Turn on Movie Buddy".')).toBeInTheDocument()
  })

  it('cancels an action and the UI agrees with the backend', async () => {
    const user = userEvent.setup()
    const action = makeAction({
      tool: 'media.open',
      state: 'running',
      description: 'play a song on spotify',
    })
    respondWith({ utterance: 'music', actions: [action] })

    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'play a song on spotify')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(screen.getByText(/Working on the media player/)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /^Cancel$/ }))

    await waitFor(() => {
      expect(screen.getByText(/Cancelled - the media player were left alone/)).toBeInTheDocument()
    })
    // The cancel call carried the session id, as the contract requires.
    const cancelCall = backend.requests.find((entry) => entry.url.endsWith('/cancel'))
    expect(cancelCall).toBeDefined()
    expect(cancelCall?.method).toBe('POST')
    expect((cancelCall?.body as { session_id?: string }).session_id).toBeTruthy()
    expect(backend.actions.get(action.action_id)?.state).toBe('cancelled')
  })

  it('approves an action with the exact plan hash that came back', async () => {
    const user = userEvent.setup()
    const action = makeAction({
      tool: 'workspace.delete',
      state: 'awaiting_confirmation',
      approval_required: true,
      description: 'delete the playlist',
    })
    respondWith({ utterance: 'delete', actions: [action], status: 'awaiting_confirmation' })

    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'delete the playlist')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText(/I need your OK before I touch your workspace/)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /Yes, go ahead/ }))

    await waitFor(() => {
      const approveCall = backend.requests.find((entry) => entry.url.endsWith('/approve'))
      expect(approveCall).toBeDefined()
    })
    const approveCall = backend.requests.find((entry) => entry.url.endsWith('/approve'))
    const body = approveCall?.body as { plan_hash?: string; approved?: boolean; session_id?: string }
    expect(body.plan_hash).toBe(action.plan_hash)
    expect(body.approved).toBe(true)
    expect(body.session_id).toBeTruthy()
  })

  it('shows a failed action as a failure and never as a success', async () => {
    const user = userEvent.setup()
    const action = makeAction({
      tool: 'media.open',
      state: 'failed',
      description: 'play a song on spotify',
      error: {
        code: 'tool_unavailable',
        message: 'media.open is not configured on this backend',
        retryable: false,
        timeout: false,
      },
    })
    respondWith({ utterance: 'music', actions: [action], status: 'failed' })

    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'play a song on spotify')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText(/the media player is not set up on this backend yet/)).toBeInTheDocument()
    })
    expect(screen.queryByText(/Done with/)).not.toBeInTheDocument()
  })

  it('shows a timed-out action distinctly from a plain failure', async () => {
    const user = userEvent.setup()
    const action = makeAction({
      tool: 'media.open',
      state: 'failed',
      description: 'play a song on spotify',
      error: {
        code: 'timeout',
        message: 'the request timed out',
        retryable: true,
        timeout: true,
      },
    })
    respondWith({ utterance: 'music', actions: [action], status: 'failed' })

    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'play a song on spotify')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText(/the media player took too long and I stopped waiting/)).toBeInTheDocument()
    })
    expect(screen.getAllByText('took too long', { exact: true }).length).toBeGreaterThan(0)
  })

  it('surfaces a failed cancellation instead of pretending it worked', async () => {
    const user = userEvent.setup()
    const action = makeAction({ tool: 'media.open', state: 'running', description: 'play a song' })
    respondWith({ utterance: 'music', actions: [action] })
    backend.failNextActionCall = {
      urlSuffix: '/cancel',
      method: 'POST',
      status: 409,
      code: 'conflict',
      message: 'the action already finished',
    }

    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'play a song on spotify')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(screen.getByText(/Working on the media player/)).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /^Cancel$/ }))

    await waitFor(() => {
      expect(screen.getByText(/the action already finished/)).toBeInTheDocument()
    })
    // The action is not shown as cancelled.
    expect(screen.queryByText(/Cancelled - the media player/)).not.toBeInTheDocument()
  })

  it('keeps two requests that finish in a different order apart', async () => {
    const user = userEvent.setup()
    const first = makeAction({ tool: 'timer.set', state: 'running', description: 'set a timer' })
    const second = makeAction({ tool: 'note.write', state: 'succeeded', description: 'write a note' })

    respondWith({ utterance: 'timer', actions: [first] })
    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'set a timer')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    respondWith({ utterance: 'note', actions: [second] })
    await user.type(screen.getByLabelText('Your request'), 'write a note')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText(/Done with your notes/)).toBeInTheDocument()
    })

    // The earlier timer is still shown as running - in its own exchange.
    const exchanges = document.querySelectorAll('.exchange')
    expect(exchanges.length).toBeGreaterThanOrEqual(2)
    const earlier = exchanges[0] as HTMLElement
    const later = exchanges[exchanges.length - 1] as HTMLElement
    expect(earlier.textContent).toContain('timers')
    expect(later.textContent).toContain('notes')
    expect(later.textContent).not.toContain('timers')
  })
})

describe('Interface B - the control room', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads and can be switched to and back', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Developer' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Control room' })).toBeInTheDocument()
    })
    expect(screen.getByLabelText('System architecture')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Ask Sidekick' }))
    await waitFor(() => {
      expect(screen.getByText('Ask me anything, or say "Turn on Movie Buddy".')).toBeInTheDocument()
    })
  })

  it('shows the same real request in both interfaces', async () => {
    const user = userEvent.setup()
    const backend = createFakeBackend()
    backend.nextResponse = (_utterance, sessionId, requestId) => ({
      request_id: requestId,
      session_id: sessionId,
      intent: { normalized: 'write a note', confidence: 0.9, ambiguous: false, entities: [] },
      action_plan: [makeAction({ tool: 'note.write', state: 'succeeded', description: 'write a note' })],
      risk_level: 'low',
      decision_model: { provider: 'sidekick', model: 'rule-engine-v1', fallback_used: false },
      status: 'succeeded',
      clarification: null,
      events: [],
    })
    installFakeBackend(backend)

    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'write a note')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(screen.getByText('write a note')).toBeInTheDocument()
    })

    const sessionBefore = document.querySelector('.app__session')?.textContent

    await user.click(screen.getByRole('button', { name: 'Developer' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Control room' })).toBeInTheDocument()
    })

    const requestText = document.querySelector('.control-room__request-text')?.textContent
    expect(requestText).toBe('write a note')
    expect(screen.getByText('sidekick/rule-engine-v1')).toBeInTheDocument()
    expect(document.querySelector('.app__session')?.textContent).toBe(sessionBefore)
  })

  it('shows the capability health with the true statuses', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Developer' }))
    await waitFor(() => {
      expect(screen.getByText('Capability health')).toBeInTheDocument()
    })
    const table = screen.getByRole('table')
    expect(within(table).getByText('note.write')).toBeInTheDocument()
    expect(within(table).getByText('REAL')).toBeInTheDocument()
  })

  it('shows an empty timeline rather than inventing events', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Developer' }))
    await waitFor(() => {
      expect(screen.getByText('Task timeline')).toBeInTheDocument()
    })
    expect(screen.getByText(/No events yet/i)).toBeInTheDocument()
  })

  it('labels a development stub without letting it dominate', async () => {
    installDefaultFetch()
    render(<App />)
    await waitFor(() => {
      expect(screen.getByTitle(/development stub/i)).toBeInTheDocument()
    })
    expect(screen.getByTitle(/development stub/i).textContent).toMatch(/dev stub/i)
  })
})

export type { SidekickResponse }
