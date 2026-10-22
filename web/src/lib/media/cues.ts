import type { MediaCue } from '@/lib/api/types'

/**
 * Cue lookup for real playback time.
 *
 * All lookups are pure functions over the cue list, so seeking, pausing and
 * resuming always recompute from `video.currentTime` rather than from a timer.
 */

/** Index of the cue that is active at `time`, or -1. */
export function findCueIndex(cues: MediaCue[], time: number): number {
  if (cues.length === 0) return -1
  let low = 0
  let high = cues.length - 1
  let candidate = -1
  while (low <= high) {
    const mid = (low + high) >> 1
    const cue = cues[mid]
    if (!cue) break
    if (cue.start <= time) {
      candidate = mid
      low = mid + 1
    } else {
      high = mid - 1
    }
  }
  if (candidate === -1) return -1
  const cue = cues[candidate]
  return cue && time <= cue.end ? candidate : -1
}

export function cueAt(cues: MediaCue[], time: number): MediaCue | null {
  const index = findCueIndex(cues, time)
  if (index === -1) return null
  return cues[index] ?? null
}

/** The cue that follows `time` (used to schedule the next companion event). */
export function nextCueAfter(cues: MediaCue[], time: number): MediaCue | null {
  for (const cue of cues) {
    if (cue.start > time) return cue
  }
  return null
}

export function cueDuration(cues: MediaCue[]): number {
  if (cues.length === 0) return 0
  const last = cues[cues.length - 1]
  return last ? last.end : 0
}

/** Progress through the cued portion of the media, 0..1. */
export function cueProgress(cues: MediaCue[], time: number): number {
  const total = cueDuration(cues)
  if (total <= 0) return 0
  return Math.min(1, Math.max(0, time / total))
}
