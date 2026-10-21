import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { App } from '@/App'
import type { CapabilitiesResponse, SidekickResponse } from '@/lib/api/types'

const SRT = readFileSync(
  resolve(process.cwd(), 'public/media/duck-and-cover/duck-and-cover.srt'),
  'utf8',
)

const capabilities: CapabilitiesResponse = {
  contract_version: 'v1',
  mode: 'stub',
  capabilities: [
    { id: 'voice.stt', state: 'live', detail: 'browser Web Speech API' },
    { id: 'music.play', state: 'unconfigured' },
    { id: 'game.chess', state: 'simulated' },
  ],
  tools: [
    {
      tool: 'coding.execute',
      status: 'NOT_CONFIGURED',
      status_detail: 'no model provider configured',
      simulated: false,
    },
    { tool: 'note.write', status: 'REAL', status_detail: 'backed by a real adapter' },
  ],
  tool_count: 2,
  games: [{ id: 'chess', name: 'Chess', state: 'simulated' }],
  providers: [{ id: 'spotify', name: 'Spotify', state: 'unconfigured', detail: 'No token configured.' }],
}

function response(overrides: Partial<SidekickResponse> = {}): SidekickResponse {
  return {
    request_id: 'req-1',
    session_id: 'sess-1',
    intent: { normalized: 'play a song', confidence: 0.91, ambiguous: false, entities: [] },
    action_plan: [
      {
        action_id: 'a-1',
        tool: 'note.write',
        arguments: { content: 'a note' },
        approval_required: false,
        state: 'succeeded',
        superseded_by: null,
        result: { path: '/tmp/note.txt' },
        timestamps: { created: '2026-01-01T00:00:00Z', updated: '2026-01-01T00:00:01Z' },
      },
    ],
    risk_level: 'low',
    decision_model: { provider: 'sidekick', model: 'rule-engine-v1', fallback_used: false, source: 'rules' },
    status: 'succeeded',
    clarification: null,
    events: [],
    ...overrides,
  }
}

function installFetch(
  handler: (url: string, init?: RequestInit) => Response | Promise<Response>,
): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init)),
  )
}

function installDefaultFetch(): void {
  installFetch((url) => {
    if (url.includes('/capabilities')) {
      return new Response(JSON.stringify(capabilities), {
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.includes('.srt')) {
      return new Response(SRT, { headers: { 'content-type': 'text/plain' } })
    }
    if (url.includes('/events')) {
      return new Response('', { headers: { 'content-type': 'text/event-stream' } })
    }
    return new Response(JSON.stringify(response()), {
      headers: { 'content-type': 'application/json' },
    })
  })
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
    expect(companion?.getAttribute('aria-label')).toMatch(/here when you need me/i)
    expect(screen.getByText('Ask me anything, or say "Turn on Movie Buddy".')).toBeInTheDocument()
  })

  it('sends a typed request and shows the real answer', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.type(screen.getByLabelText('Your request'), 'write a note')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText('write a note')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText('note.write')).toBeInTheDocument()
    })
    // The real result payload is rendered.
    expect(screen.getAllByText(/\/tmp\/note\.txt/).length).toBeGreaterThan(0)
  })

  it('shows a clarification with answerable options', async () => {
    const user = userEvent.setup()
    installFetch((url) =>
      url.includes('/capabilities')
        ? new Response(JSON.stringify(capabilities), {
            headers: { 'content-type': 'application/json' },
          })
        : new Response(
            JSON.stringify(
              response({
                status: 'awaiting_confirmation',
                clarification: {
                  question: 'Which provider did you mean?',
                  options: ['Spotify', 'YouTube'],
                },
              }),
            ),
            { headers: { 'content-type': 'application/json' } },
          ),
    )

    render(<App />)
    await user.type(screen.getByLabelText('Your request'), 'play something')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getAllByText('Which provider did you mean?').length).toBeGreaterThan(0)
    })
    expect(screen.getByRole('button', { name: 'Spotify' })).toBeInTheDocument()
  })

  it('offers a text fallback when the browser has no speech engine', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    const original = (window as unknown as Record<string, unknown>).SpeechRecognition
    delete (window as unknown as Record<string, unknown>).SpeechRecognition
    delete (window as unknown as Record<string, unknown>).webkitSpeechRecognition
    try {
      render(<App />)
      const mic = screen.getByRole('button', { name: /Voice input is not available/i })
      expect(mic).toBeDisabled()
      expect(screen.getByText('text only')).toBeInTheDocument()
      // The text field still works.
      await user.type(screen.getByLabelText('Your request'), 'still works')
      expect(screen.getByLabelText('Your request')).toHaveValue('still works')
    } finally {
      if (original) {
        ;(window as unknown as Record<string, unknown>).SpeechRecognition = original
      }
    }
  })

  it('switches to Movie Buddy from a spoken command, without naming a film', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.type(screen.getByLabelText('Your request'), 'Turn on Movie Buddy.')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Watch together' })).toBeInTheDocument()
    })
    expect(screen.getByText(/Movie Buddy is on and waiting with you/i)).toBeInTheDocument()
  })

  it('shows a recoverable error when the backend is unreachable', async () => {
    const user = userEvent.setup()
    installFetch(() => {
      throw new TypeError('Failed to fetch')
    })

    render(<App />)
    await waitFor(() => {
      expect(screen.getAllByText(/backend is not reachable/i).length).toBeGreaterThan(0)
    })

    await user.type(screen.getByLabelText('Your request'), 'hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getAllByText(/Could not reach the Sidekick backend/i).length).toBeGreaterThan(0)
    })
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

    await user.click(screen.getByRole('button', { name: 'Control room' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Control room' })).toBeInTheDocument()
    })
    expect(screen.getByLabelText('System architecture')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Ask Sidekick' }))
    await waitFor(() => {
      expect(screen.getByText('Ask me anything, or say "Turn on Movie Buddy".')).toBeInTheDocument()
    })
  })

  it('marks unconfigured components honestly in the architecture diagram', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Control room' }))
    const diagram = screen.getByLabelText('System architecture')
    await waitFor(() => {
      expect(within(diagram).getByText('Core decision engine')).toBeInTheDocument()
    })
    // Nothing is running yet, so the execution node is idle - not "live".
    const nodes = within(diagram).getAllByRole('listitem')
    const execution = nodes.find((node) => node.textContent?.includes('Execution service'))
    expect(execution?.querySelector('.arch__node')?.getAttribute('data-state')).toBe('idle')
  })

  it('shows the same real request in both interfaces', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.type(screen.getByLabelText('Your request'), 'write a note')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(screen.getByText('write a note')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Control room' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Control room' })).toBeInTheDocument()
    })
    // The same utterance and the same action are visible in the control room.
    expect(screen.getAllByText('write a note').length).toBeGreaterThan(0)
    expect(screen.getAllByText('note.write').length).toBeGreaterThan(0)
    expect(screen.getByText('sidekick/rule-engine-v1')).toBeInTheDocument()
  })

  it('shows the capability health with the true statuses', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Control room' }))
    await waitFor(() => {
      expect(screen.getByText('Capability health')).toBeInTheDocument()
    })
    const table = screen.getByRole('table')
    expect(within(table).getByText('coding.execute')).toBeInTheDocument()
    expect(within(table).getByText('NOT_CONFIGURED')).toBeInTheDocument()
    expect(within(table).getByText('REAL')).toBeInTheDocument()
    expect(within(table).getByText('no model provider configured')).toBeInTheDocument()
  })

  it('shows the real request metadata in the inspector', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.type(screen.getByLabelText('Your request'), 'write a note')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(screen.getByText('write a note')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Control room' }))
    await waitFor(() => {
      expect(screen.getByText('Request inspector')).toBeInTheDocument()
    })
    // The ids the client generated are the ones the backend received.
    expect(screen.getAllByText(/^[0-9a-f-]{36}$/).length).toBeGreaterThan(0)
    expect(screen.getByText('91%')).toBeInTheDocument()
    expect(screen.getByText('rules')).toBeInTheDocument()
  })

  it('offers the raw payload for inspection', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.type(screen.getByLabelText('Your request'), 'write a note')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(screen.getByText('write a note')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: 'Control room' }))
    await waitFor(() => {
      expect(screen.getByText('Raw response payload')).toBeInTheDocument()
    })
    const raw = screen.getByLabelText('Raw response payload')
    expect(raw.textContent).toContain('"request_id"')
  })

  it('shows an empty timeline rather than inventing events', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Control room' }))
    await waitFor(() => {
      expect(screen.getByText('Task timeline')).toBeInTheDocument()
    })
    expect(screen.getByText(/No events yet/i)).toBeInTheDocument()
  })
})
