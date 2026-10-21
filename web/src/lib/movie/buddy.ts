import type { MediaCue } from '@/lib/api/types'

/**
 * The Movie Buddy brain.
 *
 * Everything here is grounded in the real subtitle cues of the media that is
 * actually playing. There is no scene analysis and no script: a reaction is
 * only produced when a real cue satisfies a real rule, and the rule that fired
 * is recorded so the interface can show *why* Sidekick reacted.
 *
 * The companion is deliberately quiet. It has a speaking budget, a cooldown
 * between reactions, and it never speaks while a caption is on screen.
 */

export type BuddyMode = 'off' | 'active' | 'quiet'

export type ReactionRule =
  | 'first-words'
  | 'stated-plan'
  | 'sound'
  | 'instruction'
  | 'variation'
  | 'final-cue'

export interface BuddyReaction {
  id: string
  /** The cue that triggered the reaction. */
  cue: MediaCue
  /** The rule that fired - shown in the "why did Sidekick react?" panel. */
  rule: ReactionRule
  /** Human readable explanation of the actual trigger. */
  reason: string
  /** What Sidekick says. Short, and never invented plot. */
  say: string
  /** The media time the reaction belongs to. */
  at: number
}

export interface BuddySettings {
  /** Maximum reactions per minute of playback. */
  budgetPerMinute: number
  /** Minimum media seconds between two reactions. */
  cooldownSeconds: number
  /** How many recent cues are remembered. */
  contextSize: number
}

export const DEFAULT_BUDGET: BuddySettings = {
  budgetPerMinute: 3,
  cooldownSeconds: 12,
  contextSize: 8,
}

const IMPERATIVE = /^(inflate|twist|lock|take|cut|pour|push|pull|hold|place|put|add|remove|blow|turn|fold|open|close|press|drop|fill|stick|wrap|squeeze|poke|listen|look|make|start|begin|now|first|then|next|and)\b/i

const SOUND = /^\s*[([][^)\]]+[)\]]\s*$/

/**
 * Decide whether a cue should produce a reaction.
 *
 * Returns `null` when nothing should be said - which is the common case.
 */
export function reactToCue(
  cue: MediaCue,
  context: MediaCue[],
  isLast: boolean,
): BuddyReaction | null {
  const text = cue.text.trim()
  if (!text) return null

  if (context.length === 0) {
    return {
      id: `${cue.index}-first-words`,
      cue,
      rule: 'first-words',
      reason: 'This is the first line in the caption track, so Sidekick greeted you.',
      say: 'Hi. Watching with you.',
      at: cue.start,
    }
  }

  if (SOUND.test(text)) {
    return {
      id: `${cue.index}-sound`,
      cue,
      rule: 'sound',
      reason: 'The caption track marked this line as a sound, not speech.',
      say: 'Listen to that.',
      at: cue.start,
    }
  }

  if (/\bwe are going to\b|\bwe'll\b|\blet's\b/i.test(text)) {
    return {
      id: `${cue.index}-stated-plan`,
      cue,
      rule: 'stated-plan',
      reason: 'The narration states what is about to happen.',
      say: 'Right - here is the plan.',
      at: cue.start,
    }
  }

  if (IMPERATIVE.test(text)) {
    const repeated = context.some((previous) => sameSubject(previous.text, text))
    if (repeated) {
      return {
        id: `${cue.index}-variation`,
        cue,
        rule: 'variation',
        reason: 'This step repeats one from a few lines ago, with a variation.',
        say: 'Same idea again, slightly different.',
        at: cue.start,
      }
    }
    return {
      id: `${cue.index}-instruction`,
      cue,
      rule: 'instruction',
      reason: 'The narration is giving a step.',
      say: 'Step by step.',
      at: cue.start,
    }
  }

  if (isLast) {
    return {
      id: `${cue.index}-final-cue`,
      cue,
      rule: 'final-cue',
      reason: 'This is the last line in the caption track.',
      say: 'That is the end of it.',
      at: cue.start,
    }
  }

  return null
}

/** True when two cue lines are about the same thing (same leading noun). */
function sameSubject(a: string, b: string): boolean {
  const words = (value: string) =>
    value
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, ' ')
      .split(/\s+/)
      .filter((word) => word.length > 3)
  const first = words(a)
  const second = words(b)
  if (first.length === 0 || second.length === 0) return false
  const shared = first.filter((word) => second.includes(word))
  return shared.length >= 2
}

/**
 * The speaking budget.
 *
 * A reaction is only spoken when the companion is active, the budget for the
 * current window is not spent, the cooldown has elapsed, and no caption is on
 * screen.
 */
export interface SpeakingGate {
  allowed: boolean
  reason: string
}

export function canSpeak(options: {
  mode: BuddyMode
  quietUntil: number
  now: number
  lastSpokeAt: number | null
  spokenInWindow: number
  settings: BuddySettings
  captionOnScreen: boolean
}): SpeakingGate {
  const { mode, quietUntil, now, lastSpokeAt, spokenInWindow, settings, captionOnScreen } = options

  if (mode === 'off') return { allowed: false, reason: 'Movie Buddy is not on.' }
  if (mode === 'quiet') return { allowed: false, reason: 'Movie Buddy is in quiet mode.' }
  if (now < quietUntil) {
    const seconds = Math.ceil((quietUntil - now) / 1000)
    return { allowed: false, reason: `Quiet for another ${seconds}s.` }
  }
  if (captionOnScreen) {
    return { allowed: false, reason: 'A caption is on screen, so Sidekick stays quiet.' }
  }
  if (spokenInWindow >= settings.budgetPerMinute) {
    return { allowed: false, reason: 'The speaking budget for this minute is spent.' }
  }
  if (lastSpokeAt !== null && now - lastSpokeAt < settings.cooldownSeconds * 1000) {
    return { allowed: false, reason: 'Sidekick is cooling down after the last remark.' }
  }
  return { allowed: true, reason: 'Sidekick has something worth saying.' }
}

/**
 * Ground an answer in the recent dialogue.
 *
 * When there is no accessible caption context the answer says exactly that -
 * it never guesses at what happened on screen.
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

export function answerWhatJustHappened(
  context: MediaCue[],
  currentTime: number,
  windowSeconds = 45,
): GroundedAnswer {
  const recent = context.filter((cue) => currentTime - cue.end <= windowSeconds && cue.end > 0)

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
      ? `the last thing said was "${last.text}"`
      : `it went from "${first.text}" to "${last.text}"`

  return {
    say: `Just before now, ${span}. That is what the captions show.`,
    basis: spoken,
    unavailable: false,
  }
}

export function explainTheMoment(
  context: MediaCue[],
  currentTime: number,
  windowSeconds = 20,
): GroundedAnswer {
  const recent = context.filter((cue) => currentTime - cue.end <= windowSeconds && cue.end > 0)
  const spoken = recent.filter((cue) => cue.text.trim().length > 0)

  if (spoken.length === 0) {
    return {
      say: 'I cannot explain that moment. There is no caption line covering it, and I do not analyse the picture.',
      basis: recent,
      unavailable: true,
      reason: 'No caption cue covers the moment, and this build has no visual analysis.',
    }
  }

  const lines = spoken.map((cue) => cue.text.trim())
  return {
    say: `From the captions: ${lines.join(' ')} I am reading the subtitle track, not the picture.`,
    basis: spoken,
    unavailable: false,
  }
}

/** Keeps the most recent cues, bounded. */
export function pushContext(context: MediaCue[], cue: MediaCue, size: number): MediaCue[] {
  const next = [...context, cue]
  return next.length > size ? next.slice(next.length - size) : next
}
