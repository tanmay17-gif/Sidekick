import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { MovieBuddy } from '@/components/MovieBuddy'
import type { CommentaryProvider, CommentaryRequest, CommentaryResult } from '@/lib/movie/provider'
import { Speaker } from '@/lib/voice/synthesis'

const SRT = readFileSync(resolve(process.cwd(), 'public/media/duck-and-cover/duck-and-cover.srt'), 'utf8')

function installFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('.srt')) {
        return new Response(SRT, { headers: { 'content-type': 'text/plain' } })
      }
      return new Response('{}', { headers: { 'content-type': 'application/json' } })
    }),
  )
}

/** A deterministic provider: it answers from the caption it was shown. */
function createEchoProvider(): CommentaryProvider & { seen: CommentaryRequest[] } {
  const seen: CommentaryRequest[] = []
  return {
    id: 'echo-model',
    source: 'model',
    available: true,
    seen,
    async generate(request): Promise<CommentaryResult> {
      seen.push(request)
      const current = request.window.current
      if (!current) {
        return { say: '', source: 'model', grounded_in: [], declined: true }
      }
      return {
        say: `Remark about line ${current.index}.`,
        source: 'model',
        grounded_in: [current.index],
        declined: false,
      }
    },
  }
}

/** Move the media clock and fire the real media event. */
function seekTo(video: HTMLVideoElement, seconds: number): void {
  Object.defineProperty(video, 'currentTime', { value: seconds, writable: true, configurable: true })
  video.dispatchEvent(new Event('timeupdate'))
}

async function waitForVideo(): Promise<HTMLVideoElement> {
  return await waitFor(() => {
    const element = document.querySelector('video')
    expect(element).not.toBeNull()
    return element as HTMLVideoElement
  })
}

describe('Movie Buddy', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('states what it can and cannot observe', async () => {
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    await waitFor(() => {
      expect(screen.getByText(/cannot see other browser tabs/i)).toBeInTheDocument()
    }, { timeout: 5000 })
    expect(screen.getByText(/does not analyse the picture/i)).toBeInTheDocument()
  })

  it('can be switched on without choosing a film first', async () => {
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} startActive />)

    await waitFor(() => {
      expect(screen.getByText(/Movie Buddy is on and waiting with you/i)).toBeInTheDocument()
    }, { timeout: 5000 })
  })

  it('offers the bundled films and a way to open another one', async () => {
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    await waitFor(() => {
      expect(screen.getByLabelText('Film')).toBeInTheDocument()
    })
    const select = screen.getByLabelText('Film') as HTMLSelectElement
    expect(within(select).getByText(/Duck and Cover/)).toBeInTheDocument()
    expect(within(select).getByText(/Letter V/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open a video' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Load subtitles' })).toBeInTheDocument()
  })

  it('shows the caption track of the film and follows the real media clock', async () => {
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    const video = await waitForVideo()
    expect(video).toBeInTheDocument()

    // The caption track has to be parsed before the media clock can be read
    // against it - the file is fetched asynchronously.
    await waitFor(
      () => {
        expect(screen.getByText(/caption lines over/i)).toBeInTheDocument()
      },
      { timeout: 5000 },
    )
    expect(document.querySelectorAll('video track')).toHaveLength(1)

    seekTo(video, 34)
    await waitFor(
      () => {
        expect(screen.getByText(/Bert the Turtle/i)).toBeInTheDocument()
      },
      { timeout: 5000 },
    )
  })

  it('says honestly that no model provider is configured', async () => {
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    // The source settles once the caption track has been parsed.
    await waitFor(
      () => {
        expect(screen.getByText('local heuristic', { exact: true })).toBeInTheDocument()
      },
      { timeout: 5000 },
    )
    expect(screen.getByText(/Commentary source:/i)).toBeInTheDocument()
    expect(screen.getByText(/No model provider is configured/i)).toBeInTheDocument()
  })

  it('says what it said was written by the model when a model provider is used', async () => {
    installFetch()
    const provider = createEchoProvider()
    render(
      <MovieBuddy speaker={new Speaker()} speechEnabled={false} startActive provider={provider} />,
    )

    await waitFor(() => {
      expect(screen.getByText('model')).toBeInTheDocument()
    }, { timeout: 5000 })
    expect(
      screen.getByText(/Remarks are written by the configured model provider/i),
    ).toBeInTheDocument()
  })

  it('remarks on the caption that just finished and shows why', async () => {
    installFetch()
    const provider = createEchoProvider()
    const user = userEvent.setup()
    render(
      <MovieBuddy speaker={new Speaker()} speechEnabled={false} startActive provider={provider} />,
    )

    const video = await waitForVideo()
    await waitFor(
      () => {
        expect(screen.getByText(/caption lines over/i)).toBeInTheDocument()
      },
      { timeout: 5000 },
    )

    // Move into a gap between two caption lines: that is where the companion
    // is allowed to speak.
    seekTo(video, 31)
    await waitFor(
      () => {
        expect(screen.getByText(/Remark about line \d+/i)).toBeInTheDocument()
      },
      { timeout: 5000 },
    )

    await user.click(screen.getByRole('button', { name: 'Why did Sidekick react?' }))
    expect(screen.getByText(/Grounded in the caption at/i)).toBeInTheDocument()
    expect(screen.getByText(/Written by:/i)).toBeInTheDocument()
  })

  it('never shows the old hardcoded reaction lines', async () => {
    installFetch()
    const provider = createEchoProvider()
    render(
      <MovieBuddy speaker={new Speaker()} speechEnabled={false} startActive provider={provider} />,
    )

    const video = await waitForVideo()
    await waitFor(() => expect(screen.getByText(/caption lines over/i)).toBeInTheDocument(), {
      timeout: 5000,
    })
    seekTo(video, 31)

    await waitFor(() => expect(screen.getByText('Remarks')).toBeInTheDocument(), { timeout: 5000 })
    expect(screen.queryByText(/Watching with you/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Step by step/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/That is the end of it/i)).not.toBeInTheDocument()
  })

  it('goes quiet immediately and reports the remaining time', async () => {
    const user = userEvent.setup()
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    await waitFor(() => expect(screen.getByLabelText('Film')).toBeInTheDocument(), { timeout: 5000 })
    await user.click(screen.getByRole('button', { name: 'Be quiet for a bit' }))

    await waitFor(() => {
      expect(screen.getByText(/Staying quiet for \d+ more seconds/i)).toBeInTheDocument()
    }, { timeout: 5000 })
  })

  it('answers "what just happened" from the captions and says when it cannot', async () => {
    const user = userEvent.setup()
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    const video = await waitForVideo()
    seekTo(video, 31)

    await user.click(screen.getByRole('button', { name: 'What just happened?' }))

    await waitFor(() => {
      expect(screen.getByText('Sidekick said')).toBeInTheDocument()
    }, { timeout: 5000 })
    const answer = screen.getByText('Sidekick said').parentElement as HTMLElement
    expect(answer.textContent).toMatch(/caption/i)
  })

  it('reports a media failure instead of pretending the film plays', async () => {
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    const video = await waitForVideo()
    Object.defineProperty(video, 'error', {
      value: { code: 4 },
      configurable: true,
    })
    video.dispatchEvent(new Event('error'))

    await waitFor(() => {
      expect(screen.getByText(/not supported or the network blocked it/i)).toBeInTheDocument()
    })
  })
})
