import type { CompanionRule, MediaAsset, MediaCue } from '@/lib/api/types'

/**
 * Companion events are derived from the *real subtitle track* of the media.
 *
 * There is no vision pipeline in this build, so every event is explicitly
 * subtitle-based: it fires on the timestamp of a real cue whose text matches a
 * rule. Nothing here analyses picture content.
 */

export interface CompanionEvent {
  id: string
  /** Real media time (seconds) the event belongs to. */
  at: number
  title: string
  reason: string
  /** The exact subtitle line that triggered the event. */
  quote: string
  cue: MediaCue
  /** Set once playback has reached the event. */
  reached: boolean
}

export interface BuildEventsOptions {
  rules: CompanionRule[]
  cues: MediaCue[]
  /** Include events that fired in the past (default true). */
  includePast?: boolean
}

/**
 * Build companion events from the shipped rules and the real cue list.
 * Events are ordered by media time; duplicates on the same cue are collapsed.
 */
export function buildCompanionEvents(
  options: BuildEventsOptions,
): CompanionEvent[] {
  const { rules, cues } = options
  const events: CompanionEvent[] = []
  const seen = new Set<number>()

  for (const rule of rules) {
    let pattern: RegExp
    try {
      pattern = new RegExp(rule.pattern, 'i')
    } catch {
      // A malformed rule must not break playback.
      continue
    }
    for (const cue of cues) {
      if (seen.has(cue.index)) continue
      if (!pattern.test(cue.text)) continue
      seen.add(cue.index)
      events.push({
        id: `${cue.index}-${slug(rule.title)}`,
        at: cue.start,
        title: rule.title,
        reason: rule.reason,
        quote: cue.text,
        cue,
        reached: false,
      })
      break // one event per rule keeps the companion selective
    }
  }

  return events.sort((a, b) => a.at - b.at)
}

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
}

/**
 * Only the events whose real timestamp has already been reached.
 * Pure: the caller supplies the real `currentTime`.
 */
export function eventsReached(events: CompanionEvent[], currentTime: number): CompanionEvent[] {
  return events
    .filter((event) => event.at <= currentTime)
    .map((event) => ({ ...event, reached: true }))
}

/** The most recent reached event, used for the "now showing" card. */
export function activeEvent(
  events: CompanionEvent[],
  currentTime: number,
): CompanionEvent | null {
  let latest: CompanionEvent | null = null
  for (const event of events) {
    if (event.at <= currentTime) latest = { ...event, reached: true }
    else break
  }
  return latest
}

/**
 * Whether it is a good moment to speak: no cue is currently on screen.
 * Speaking over dialogue is exactly what the companion must avoid.
 */
export function isSpeechSafe(cues: MediaCue[], currentTime: number): boolean {
  return findActiveCue(cues, currentTime) === null
}

function findActiveCue(cues: MediaCue[], currentTime: number): MediaCue | null {
  for (const cue of cues) {
    if (currentTime >= cue.start && currentTime <= cue.end) return cue
  }
  return null
}

export interface MediaCatalog {
  assets: MediaAsset[]
}

/** Human-readable summary of how the companion understands the media. */
export function understandingLabel(asset: MediaAsset): string {
  return `Subtitle-based understanding - no visual analysis (${asset.subtitle_label})`
}
