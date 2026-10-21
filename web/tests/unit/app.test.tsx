import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { App } from '@/App'
import type { CapabilitiesResponse, SidekickResponse } from '@/lib/api/types'

const SRT = readFileSync(resolve(process.cwd(), 'public/media/letter-v/letter-v.srt'), 'utf8')

const capabilities: CapabilitiesResponse = {
  contract_version: 'v1',
  mode: 'stub',
  capabilities: [
    { id: 'voice.stt', state: 'live' },
    { id: 'music.play', state: 'unconfigured' },
    { id: 'game.chess', state: 'simulated' },
  ],
  tools: [{ tool: 'coding.execute', status: 'NOT_CONFIGURED', status_detail: 'no provider configured' }],
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
        tool: 'music.play',
        arguments: { provider: 'Spotify', query: 'a song' },
        approval_required: false,
        state: 'succeeded',
        superseded_by: null,
        result: { track: 'Example' },
        timestamps: { created: '2026-01-01T00:00:00Z', updated: '2026-01-01T00:00:01Z' },
      },
    ],
    risk_level: 'low',
    decision_model: { provider: 'test', model: 'deterministic-rules', fallback_used: false },
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
    return new Response(JSON.stringify(response()), {
      headers: { 'content-type': 'application/json' },
    })
  })
}

describe('Sidekick app integration', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the capability inventory reported by the backend', async () => {
    installDefaultFetch()
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('music.play')).toBeInTheDocument()
    })
    expect(screen.getByText('dev stub')).toBeInTheDocument()
    expect(screen.getByText('unconfigured')).toBeInTheDocument()
  })

  it('shows the companion and the actual current task on the first screen', async () => {
    installDefaultFetch()
    const { container } = render(<App />)

    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    // The companion is present and labelled by its real state.
    const companion = container.querySelector('.companion')
    expect(companion).not.toBeNull()
    expect(companion?.getAttribute('data-state')).toBe('idle')
    expect(companion?.getAttribute('aria-label')).toMatch(/here when you need me/i)

    // The task panel shows a real instruction, not a decorative card.
    expect(screen.getByText('Ready')).toBeInTheDocument()
  })

  it('sends a typed request and renders the real action outcome', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)
    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Your request'), 'play a song on spotify')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getAllByText('play a song on spotify').length).toBeGreaterThan(0)
    })
    await waitFor(() => {
      expect(screen.getAllByText('music.play').length).toBeGreaterThan(0)
    })
    // The result comes from the response payload.
    expect(screen.getAllByText(/Example/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('deterministic-rules').length).toBeGreaterThan(0)
  })

  it('shows a decision trace from the real response', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)
    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Your request'), 'play a song on spotify')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText('Decision trace')).toBeInTheDocument()
    })
    expect(screen.getByText('Heard')).toBeInTheDocument()
    expect(screen.getByText('Understood')).toBeInTheDocument()
    expect(screen.getByText('Decided')).toBeInTheDocument()
    expect(screen.getByText('Planned')).toBeInTheDocument()
  })

  it('exposes the raw payload in the developer inspection mode', async () => {
    const user = userEvent.setup()
    installDefaultFetch()
    render(<App />)
    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Your request'), 'play a song on spotify')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(screen.getByText('Decision trace')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Raw payload' }))
    const raw = screen.getByLabelText('Raw response payload')
    expect(raw.textContent).toContain('"request_id"')
    expect(raw.textContent).toContain('music.play')
  })

  it('shows an honest error state when the backend cannot be reached', async () => {
    const user = userEvent.setup()
    installFetch(() => {
      throw new TypeError('Failed to fetch')
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/backend is not reachable/i)).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText('Your request'), 'hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText(/Could not reach the Sidekick backend/i)).toBeInTheDocument()
    })
  })

  it('lets the user cancel a request that is still in flight', async () => {
    const user = userEvent.setup()
    let release: (() => void) | undefined
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })

    installFetch((url) => {
      if (url.includes('/capabilities')) {
        return new Response(JSON.stringify(capabilities), {
          headers: { 'content-type': 'application/json' },
        })
      }
      return pending.then(
        () =>
          new Response(JSON.stringify(response()), {
            headers: { 'content-type': 'application/json' },
          }),
      )
    })

    render(<App />)
    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Your request'), 'play something')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    const cancel = await screen.findByRole('button', { name: 'Cancel request' })
    await user.click(cancel)

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Cancel request' })).not.toBeInTheDocument()
    })
    release?.()
  })

  it('renders a clarification with selectable options', async () => {
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
    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Your request'), 'play something')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getAllByText('Which provider did you mean?').length).toBeGreaterThan(0)
    })
    expect(screen.getByRole('button', { name: 'Spotify' })).toBeInTheDocument()
  })

  it('handles the ratified turn-level status and the event timestamp field', async () => {
    const user = userEvent.setup()
    installFetch((url) =>
      url.includes('/capabilities')
        ? new Response(JSON.stringify(capabilities), {
            headers: { 'content-type': 'application/json' },
          })
        : new Response(
            JSON.stringify(
              response({
                status: 'needs_clarification',
                decision_model: {
                  provider: 'sidekick',
                  model: 'rule-engine-v1',
                  fallback_used: true,
                  source: 'rules',
                },
                events: [
                  {
                    seq: 1,
                    kind: 'progress',
                    message: 'interpreted with the rule engine',
                    ts: '2026-01-01T10:00:00Z',
                  },
                ],
                action_plan: [
                  {
                    action_id: 'a-1',
                    tool: 'note.write',
                    arguments: {},
                    approval_required: false,
                    state: 'pending',
                    superseded_by: null,
                    description: 'Write the note to the workspace',
                    progress: 0.4,
                    timestamps: { created: '2026-01-01T00:00:00Z', updated: '2026-01-01T00:00:01Z' },
                  },
                ],
              }),
            ),
            { headers: { 'content-type': 'application/json' } },
          ),
    )

    const { container } = render(<App />)
    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Your request'), 'take a note')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText(/needs clarification/)).toBeInTheDocument()
    })
    const metaText = container.querySelector('.bubble__meta')?.textContent ?? ''
    expect(metaText).toContain('rule-engine-v1')
    expect(metaText).toContain('(fallback)')
    expect(metaText).toContain('rules')
    expect(screen.getAllByText('Write the note to the workspace').length).toBeGreaterThan(0)
    expect(screen.getAllByText('interpreted with the rule engine').length).toBeGreaterThan(0)
  })

  it('labels an unavailable music provider instead of faking a player', async () => {
    installDefaultFetch()
    render(<App />)
    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    await userEvent.setup().click(screen.getByRole('button', { name: 'Music' }))

    const musicPanel = await screen.findByText('Providers')
    const list = musicPanel.closest('.panel') as HTMLElement
    expect(within(list).getByText('Spotify')).toBeInTheDocument()
    expect(within(list).getAllByText('not configured').length).toBeGreaterThan(0)
  })

  it('renders the chess board from the position the backend reports', async () => {
    const user = userEvent.setup()
    installFetch((url) =>
      url.includes('/capabilities')
        ? new Response(JSON.stringify(capabilities), {
            headers: { 'content-type': 'application/json' },
          })
        : new Response(
            JSON.stringify(
              response({
                action_plan: [
                  {
                    action_id: 'g-1',
                    tool: 'game.chess',
                    arguments: {},
                    approval_required: false,
                    state: 'succeeded',
                    superseded_by: null,
                    result: {
                      position: {
                        fen: 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
                        turn: 'w',
                      },
                    },
                    timestamps: { created: '2026-01-01T00:00:00Z', updated: '2026-01-01T00:00:01Z' },
                  },
                ],
              }),
            ),
            { headers: { 'content-type': 'application/json' } },
          ),
    )

    render(<App />)
    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Your request'), 'start a chess game')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(screen.getAllByText('game.chess').length).toBeGreaterThan(0))

    await user.click(screen.getByRole('button', { name: 'Games' }))
    const board = await screen.findByRole('img', { name: /Chess position/ })
    expect(within(board).getAllByText(/[♔-♟]/)).toHaveLength(32)
  })
})
