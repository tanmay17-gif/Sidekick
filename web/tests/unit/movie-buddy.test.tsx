import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { MovieBuddy } from '@/components/MovieBuddy'
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

/** Move the media clock and fire the real media event. */
function seekTo(video: HTMLVideoElement, seconds: number): void {
  Object.defineProperty(video, 'currentTime', { value: seconds, writable: true, configurable: true })
  video.dispatchEvent(new Event('timeupdate'))
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
    })
    expect(screen.getByText(/does not analyse the picture/i)).toBeInTheDocument()
    expect(screen.getByText(/subtitle-based understanding, no picture analysis/i)).toBeInTheDocument()
  })

  it('can be switched on without choosing a film first', async () => {
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} startActive />)

    await waitFor(() => {
      expect(screen.getByText(/Movie Buddy is on and waiting with you/i)).toBeInTheDocument()
    })
  })

  it('offers the bundled film and a way to open another one', async () => {
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    await waitFor(() => {
      expect(screen.getByLabelText('Film')).toBeInTheDocument()
    })
    const select = screen.getByLabelText('Film') as HTMLSelectElement
    expect(within(select).getByText(/Duck and Cover/)).toBeInTheDocument()
    expect(within(select).getByText(/Letter V/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open a file' })).toBeInTheDocument()
  })

  it('shows the caption track of the film and follows the real media clock', async () => {
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    const video = (await waitFor(() => {
      const element = document.querySelector('video')
      expect(element).not.toBeNull()
      return element as HTMLVideoElement
    }))
    expect(video).toBeInTheDocument()
    expect(document.querySelectorAll('video track')).toHaveLength(1)

    seekTo(video, 34)
    await waitFor(() => {
      expect(screen.getByText(/Bert the Turtle/i)).toBeInTheDocument()
    })
  })

  it('reacts at a real caption and explains why', async () => {
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} startActive />)

    const video = (await waitFor(() => {
      const element = document.querySelector('video')
      expect(element).not.toBeNull()
      return element as HTMLVideoElement
    }))

    // The first caption line of the film.
    seekTo(video, 1.5)
    await waitFor(() => {
      expect(screen.getByText(/Watching with you/i)).toBeInTheDocument()
    })
  })

  it('goes quiet immediately and reports the remaining time', async () => {
    const user = userEvent.setup()
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    await waitFor(() => expect(screen.getByLabelText('Film')).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Be quiet for a bit' }))

    await waitFor(() => {
      expect(screen.getByText(/Staying quiet for \d+ more seconds/i)).toBeInTheDocument()
    })
  })

  it('answers "what just happened" from the captions and says when it cannot', async () => {
    const user = userEvent.setup()
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    const video = (await waitFor(() => {
      const element = document.querySelector('video')
      expect(element).not.toBeNull()
      return element as HTMLVideoElement
    }))
    seekTo(video, 31)

    await user.click(screen.getByRole('button', { name: 'What just happened?' }))

    await waitFor(() => {
      expect(screen.getByText('Sidekick said')).toBeInTheDocument()
    })
    const answer = screen.getByText('Sidekick said').parentElement as HTMLElement
    expect(answer.textContent).toMatch(/caption/i)
  })

  it('offers the reason a reaction fired', async () => {
    const user = userEvent.setup()
    installFetch()
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} startActive />)

    const video = (await waitFor(() => {
      const element = document.querySelector('video')
      expect(element).not.toBeNull()
      return element as HTMLVideoElement
    }))
    seekTo(video, 1.5)
    await waitFor(() => expect(screen.getByText('Remarks')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Why did Sidekick react?' }))
    expect(screen.getByText(/first line in the caption track/i)).toBeInTheDocument()
  })

  it('reports a media failure instead of pretending the film plays', async () => {
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
    render(<MovieBuddy speaker={new Speaker()} speechEnabled={false} />)

    const video = (await waitFor(() => {
      const element = document.querySelector('video')
      expect(element).not.toBeNull()
      return element as HTMLVideoElement
    }))
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
