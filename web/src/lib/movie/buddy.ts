import type { MediaCue } from '@/lib/api/types'
import { buildCueWindow, type CueWindowOptions } from './context'

/**
 * The grounded answers Movie Buddy gives when the viewer asks a question.
 *
 * These are generic: they quote the caption lines that are actually in the
 * context window and say plainly when there is nothing to quote. They never
 * infer anything that is not in the subtitles.
 */

export interface GroundedAnswer {
  /** What Sidekick would say. */
  say: string
  /** The cues the answer is based on. */
  basis: MediaCue[]
  /** True when the answer could not be grounded in captions. */
  unavailable: boolean
  /** Why it is unavailable, when it is. */
  reason?: string
}

const DEFAULT_HISTORY: CueWindowOptions = { before: 8, after: 0, recent: 8 }

export function answerWhatJustHappened(
  cues: MediaCue[],
  currentTime: number,
  windowSeconds = 45,
): GroundedAnswer {
  const window = buildCueWindow(cues, currentTime, DEFAULT_HISTORY)
  const spokenSoFar = window.current ? [...window.recent, window.current] : window.recent
  const recent = spokenSoFar.filter(
    (cue) => currentTime - cue.end <= windowSeconds && cue.end > 0,
  )

  if (recent.length === 0) {
    return {
      say: 'I do not have any caption lines for that moment, so I cannot say what happened.',
      basis: [],
      unavailable: true,
      reason: 'No caption cue covers the last 45 seconds of playback.',
    }
  }

  const spoken = recent.filter((cue) => cue.text.trim().length > 0)
  if (spoken.length === 0) {
    return {
      say: 'There were no spoken lines in that stretch - only silence and sound.',
      basis: recent,
      unavailable: false,
    }
  }

  const last = spoken[spoken.length - 1]
  const first = spoken[0]
  if (!last || !first) {
    return {
      say: 'I do not have any caption lines for that moment, so I cannot say what happened.',
      basis: [],
      unavailable: true,
      reason: 'No caption cue covers the last 45 seconds of playback.',
    }
  }

  const span =
    spoken.length === 1
      ? `we just heard "${last.text.trim()}".`
      : `the scene went from "${first.text.trim()}" to "${last.text.trim()}".`

  return {
    say: `Just now, ${span}`,
    basis: spoken,
    unavailable: false,
  }
}

export function explainTheMoment(
  cues: MediaCue[],
  currentTime: number,
  windowSeconds = 20,
): GroundedAnswer {
  const window = buildCueWindow(cues, currentTime, DEFAULT_HISTORY)
  const spokenSoFar = window.current ? [...window.recent, window.current] : window.recent
  const recent = spokenSoFar.filter(
    (cue) => currentTime - cue.end <= windowSeconds && cue.end > 0,
  )
  const spoken = recent.filter((cue) => cue.text.trim().length > 0)

  if (spoken.length === 0) {
    return {
      say: 'I cannot explain that moment because there is no dialogue playing, and I do not analyse the picture.',
      basis: recent,
      unavailable: true,
      reason: 'No dialogue cue covers the moment.',
    }
  }

  const lines = spoken.map((cue) => cue.text.trim())
  return {
    say: `${lines.join(' ')}. I am reading the subtitle track, not the picture.`,
    basis: spoken,
    unavailable: false,
  }
}
