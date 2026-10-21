import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { App } from '@/App'
import type { CapabilitiesResponse, SidekickResponse } from '@/lib/api/types'

const SRT_PATH = resolve(process.cwd(), 'public/media/tears-of-steel/TOS-en.srt')

const capabilities: CapabilitiesResponse = {
  contract_version: 'v1',
  mode: 'stub',
  capabilities: [
    { id: 'voice.stt', state: 'live' },
    { id: 'music.play', state: 'unconfigured' },
    { id: 'game.chess', state: 'simulated' },
  ],
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

describe('Sidekick app integration', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the capability inventory reported by the backend', async () => {
    installFetch((url) =>
      url.includes('/capabilities')
        ? new Response(JSON.stringify(capabilities), {
            headers: { 'content-type': 'application/json' },
          })
        : new Response('{}', { headers: { 'content-type': 'application/json' } }),
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('music.play')).toBeInTheDocument()
    })
    // The stub mode is labelled, never presented as live.
    expect(screen.getByText('dev stub')).toBeInTheDocument()
    expect(screen.getByText('unconfigured')).toBeInTheDocument()
  })

  it('sends a typed request and renders the real action outcome', async () => {
    const user = userEvent.setup()
    installFetch((url) =>
      url.includes('/capabilities')
        ? new Response(JSON.stringify(capabilities), {
            headers: { 'content-type': 'application/json' },
          })
        : new Response(JSON.stringify(response()), {
            headers: { 'content-type': 'application/json' },
          }),
    )

    render(<App />)
    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    const input = screen.getByLabelText('Your request')
    await user.type(input, 'play a song on spotify')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText('play a song on spotify')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getAllByText('music.play').length).toBeGreaterThan(0)
    })
    // The result comes from the response payload, not from a local timer.
    expect(screen.getByText(/Example/)).toBeInTheDocument()
    // Decision metadata is surfaced truthfully.
    expect(screen.getByText('deterministic-rules')).toBeInTheDocument()
    expect(screen.getByText('91%')).toBeInTheDocument()
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

    const input = screen.getByLabelText('Your request')
    await user.type(input, 'hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(screen.getByText(/Could not reach the Sidekick backend/i)).toBeInTheDocument()
    })
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
      expect(screen.getByText('Which provider did you mean?')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: 'Spotify' })).toBeInTheDocument()
  })

  it('labels an unavailable music provider instead of faking a player', async () => {
    installFetch((url) =>
      url.includes('/capabilities')
        ? new Response(JSON.stringify(capabilities), {
            headers: { 'content-type': 'application/json' },
          })
        : new Response('{}', { headers: { 'content-type': 'application/json' } }),
    )

    render(<App />)
    await waitFor(() => expect(screen.getByText('music.play')).toBeInTheDocument())

    await userEvent.setup().click(screen.getByRole('button', { name: 'Music' }))

    const musicPanel = await screen.findByText('Providers')
    expect(musicPanel).toBeInTheDocument()
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
    expect(board).toBeInTheDocument()
    // 32 pieces on the starting position.
    expect(within(board).getAllByText(/[♔-♟]/)).toHaveLength(32)
  })
})

describe('movie companion', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the shipped subtitle cue in sync with playback time', async () => {
    const srt = readFileSync(SRT_PATH, 'utf8')
    installFetch((url) => {
      if (url.includes('.srt')) {
        return new Response(srt, { headers: { 'content-type': 'text/plain' } })
      }
      return new Response(JSON.stringify(capabilities), {
        headers: { 'content-type': 'application/json' },
      })
    })

    const { MovieCompanion } = await import('@/components/MovieCompanion')
    const { Speaker } = await import('@/lib/voice/synthesis')
    render(<MovieCompanion speaker={new Speaker()} speechEnabled={false} />)

    const video = await waitFor(() => {
      const element = document.querySelector('video')
      expect(element).not.toBeNull()
      return element as HTMLVideoElement
    })

    // Move the media clock to a real cue and fire the real media event.
    Object.defineProperty(video, 'currentTime', { value: 23.2, writable: true, configurable: true })
    video.dispatchEvent(new Event('timeupdate'))

    await waitFor(() => {
      expect(screen.getByText("You're a jerk, Thom.")).toBeInTheDocument()
    })
  })

  it('raises a companion event at the real timestamp of a matching cue', async () => {
    const srt = readFileSync(SRT_PATH, 'utf8')
    installFetch((url) => {
      if (url.includes('.srt')) {
        return new Response(srt, { headers: { 'content-type': 'text/plain' } })
      }
      return new Response(JSON.stringify(capabilities), {
        headers: { 'content-type': 'application/json' },
      })
    })

    const { MovieCompanion } = await import('@/components/MovieCompanion')
    const { Speaker } = await import('@/lib/voice/synthesis')
    render(<MovieCompanion speaker={new Speaker()} speechEnabled={false} />)

    const video = await waitFor(() => {
      const element = document.querySelector('video')
      expect(element).not.toBeNull()
      return element as HTMLVideoElement
    })
    // The "robot hand" line starts at 30.8s in the official track.
    Object.defineProperty(video, 'currentTime', { value: 31, writable: true, configurable: true })
    video.dispatchEvent(new Event('timeupdate'))

    await waitFor(() => {
      expect(screen.getByText('Robotics mentioned')).toBeInTheDocument()
    })
    expect(screen.getAllByText(/real timestamp/i).length).toBeGreaterThan(0)
  })

  it('reports a subtitle failure instead of pretending to understand the film', async () => {
    installFetch((url) => {
      if (url.includes('.srt')) return new Response('nope', { status: 404 })
      return new Response(JSON.stringify(capabilities), {
        headers: { 'content-type': 'application/json' },
      })
    })

    const { MovieCompanion } = await import('@/components/MovieCompanion')
    const { Speaker } = await import('@/lib/voice/synthesis')
    render(<MovieCompanion speaker={new Speaker()} speechEnabled={false} />)

    await waitFor(() => {
      expect(screen.getByText(/Subtitle track could not be loaded/i)).toBeInTheDocument()
    })
  })
})
