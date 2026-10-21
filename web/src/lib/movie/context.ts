import type { MediaCue } from '@/lib/api/types'

/**
 * Subtitle context for the movie companion.
 *
 * Everything here is about the film that is *actually* playing: the cue under
 * the playhead, the lines just before it, the lines just after it, and a
 * bounded recent window. Nothing in this file knows anything about a specific
 * film.
 */

export interface CueWindow {
  /** The cue under the playhead, if any. */
  current: MediaCue | null
  /** The cues immediately before the current one. */
  previous: MediaCue[]
  /** The cues immediately after the current one. */
  upcoming: MediaCue[]
  /** A bounded window of recent dialogue, oldest first. */
  recent: MediaCue[]
}

export interface CueWindowOptions {
  /** How many cues to look back. */
  before?: number
  /** How many cues to look ahead. */
  after?: number
  /** How many recent cues to keep for context. */
  recent?: number
}

export const DEFAULT_WINDOW: Required<CueWindowOptions> = {
  before: 3,
  after: 2,
  recent: 8,
}

/** Every cue that ends at or before `time`. */
export function cuesBefore(cues: MediaCue[], time: number): MediaCue[] {
  return cues.filter((cue) => cue.end <= time)
}

/** Every cue that starts at or after `time`. */
export function cuesAfter(cues: MediaCue[], time: number): MediaCue[] {
  return cues.filter((cue) => cue.start >= time)
}

/** The cue under the playhead, or null in a gap between lines. */
export function cueAt(cues: MediaCue[], time: number): MediaCue | null {
  for (const cue of cues) {
    if (time >= cue.start && time <= cue.end) return cue
  }
  return null
}

/**
 * The most recent line that has started - including the one that is playing
 * right now.
 *
 * This is the line the companion talks *about*: it is what the viewer has
 * just heard, whether it is still on screen or has just finished.
 */
export function lastStartedCue(cues: MediaCue[], time: number): MediaCue | null {
  let latest: MediaCue | null = null
  for (const cue of cues) {
    if (cue.start <= time) latest = cue
    else break
  }
  return latest
}

/**
 * Build the context around the playhead.
 *
 * The look-ahead is deliberate: the next line often tells you what the
 * current line was about, and it keeps the companion from commenting on a
 * question that the next line answers.
 */
export function buildCueWindow(
  cues: MediaCue[],
  currentTime: number,
  options: CueWindowOptions = {},
): CueWindow {
  const before = options.before ?? DEFAULT_WINDOW.before
  const after = options.after ?? DEFAULT_WINDOW.after
  const recentSize = options.recent ?? DEFAULT_WINDOW.recent

  const past = cuesBefore(cues, currentTime)
  const future = cuesAfter(cues, currentTime)
  const current = cueAt(cues, currentTime)

  return {
    current,
    previous: past.slice(Math.max(0, past.length - before)),
    upcoming: future.slice(0, after),
    recent: past.slice(Math.max(0, past.length - recentSize)),
  }
}

/**
 * How well do the subtitles line up with the media?
 *
 * A subtitle file that does not match the copy of the film is a real
 * possibility, and it is the difference between "I can read this" and "I am
 * making it up".
 */
export type AlignmentStatus = 'ok' | 'no-cues' | 'mismatch' | 'unknown'

export interface AlignmentReport {
  status: AlignmentStatus
  detail: string
  /** The last moment the subtitles cover. */
  covered_until: number
}

export function alignmentReport(
  cues: MediaCue[],
  mediaDuration: number | null,
): AlignmentReport {
  if (cues.length === 0) {
    return {
      status: 'no-cues',
      detail:
        'This film has no caption track, so the companion has nothing to read. Load a subtitle file to switch it on.',
      covered_until: 0,
    }
  }

  const last = cues[cues.length - 1]
  const coveredUntil = last ? last.end : 0

  if (!mediaDuration || mediaDuration <= 0) {
    return {
      status: 'unknown',
      detail: `${cues.length} caption lines are loaded; the media length is not known yet.`,
      covered_until: coveredUntil,
    }
  }

  const gap = mediaDuration - coveredUntil
  // A caption track that stops long before the film ends is not this cut.
  if (gap > Math.max(30, mediaDuration * 0.25)) {
    return {
      status: 'mismatch',
      detail: `The captions end at ${formatTime(coveredUntil)} but the film runs to ${formatTime(
        mediaDuration,
      )}. These subtitles may not match this copy of the film.`,
      covered_until: coveredUntil,
    }
  }

  return {
    status: 'ok',
    detail: `${cues.length} caption lines, covering up to ${formatTime(coveredUntil)}.`,
    covered_until: coveredUntil,
  }
}

function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return `${minutes}:${String(rest).padStart(2, '0')}`
}

/* ------------------------------------------------------------------ *
 * Observable properties of a line of dialogue.
 *
 * These are deliberately generic. They look at the shape of the text, not
 * at any particular film's vocabulary.
 * ------------------------------------------------------------------ */

export interface CueFeatures {
  isQuestion: boolean
  isEmphasis: boolean
  isSound: boolean
  isShort: boolean
  isLong: boolean
  /** Content words that have not appeared in the recent window. */
  newTerms: string[]
  /** A phrase from this cue that also appears in the recent window. */
  repeats: string[]
  /** The most contentful words in the line. */
  keywords: string[]
}

const STOP_WORDS = new Set([
  'the', 'and', 'that', 'this', 'with', 'from', 'have', 'has', 'had', 'was', 'were', 'you',
  'your', 'they', 'them', 'their', 'there', 'here', 'but', 'not', 'all', 'can', 'will', 'would',
  'should', 'could', 'for', 'are', 'its', "it's", 'his', 'her', 'she', 'him', 'she', 'out', 'off',
  'about', 'into', 'over', 'than', 'when', 'what', 'who', 'how', 'why', 'just', 'like', 'some',
  'more', 'very', 'much', 'many', 'been', 'being', 'does', 'did', 'doing', 'goes', 'going',
])

const SOUND_ONLY = /^\s*[[(][^)\]]+[)\]]\s*$/

export function analyzeCue(cue: MediaCue, recent: MediaCue[]): CueFeatures {
  const text = cue.text.trim()
  const words = tokenize(text)
  const recentWords = new Set(recent.flatMap((entry) => tokenize(entry.text)))

  const repeated = recent
    .map((entry) => sharedPhrase(entry.text, text))
    .filter((phrase): phrase is string => phrase !== null)

  return {
    isQuestion: text.includes('?'),
    isEmphasis: text.includes('!') || /\b(never|always|everyone|nobody|everything|nothing)\b/i.test(text),
    isSound: SOUND_ONLY.test(text),
    isShort: words.length <= 4,
    isLong: words.length >= 14,
    newTerms: words.filter((word) => !recentWords.has(word) && word.length > 3).slice(0, 3),
    repeats: repeated,
    keywords: contentWords(text).slice(0, 5),
  }
}

export function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9'\s]/g, ' ')
    .split(/\s+/)
    .filter((word) => word.length > 0)
}

export function contentWords(text: string): string[] {
  return tokenize(text).filter((word) => !STOP_WORDS.has(word) && word.length > 2)
}

/**
 * The longest phrase (at least two words) that appears in both lines.
 * Used to notice that a line is repeating something from a moment ago.
 */
export function sharedPhrase(a: string, b: string): string | null {
  const wordsA = tokenize(a)
  const wordsB = new Set(tokenize(b))
  if (wordsA.length < 2) return null
  for (let length = Math.min(6, wordsA.length); length >= 2; length -= 1) {
    const phrase = wordsA.slice(0, length)
    if (phrase.every((word) => wordsB.has(word))) {
      return phrase.join(' ')
    }
  }
  return null
}
