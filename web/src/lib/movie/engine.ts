import type { MediaCue } from '@/lib/api/types'
import {
  analyzeCue,
  buildCueWindow,
  lastStartedCue,
  type CueWindowOptions,
} from './context'
import type { CommentaryProvider, CommentarySource } from './provider'

/**
 * The Movie Buddy engine.
 *
 * It is deliberately film-agnostic: it knows about subtitle cues, a window
 * of dialogue, a model provider and a speaking policy, and it knows nothing
 * about any particular film's plot or vocabulary.
 *
 * The path from playback to a spoken remark is:
 *
 *   playback time -> the cue under the playhead -> a window of dialogue
 *     -> a usefulness decision -> the provider -> a grounded remark
 *     -> the speaking gate -> speech
 */

export type BuddyMode = 'off' | 'active' | 'quiet'

export interface BuddySettings {
  /** Maximum remarks per minute of playback. */
  budgetPerMinute: number
  /** Minimum media seconds between two remarks. */
  cooldownSeconds: number
  /** How many recent cues are remembered. */
  contextSize: number
  /** The window of dialogue handed to the provider. */
  window: CueWindowOptions
  /** The longest remark Sidekick may say. */
  maxRemarkChars: number
  /** Minimum provider calls per second - a hard rate limit. */
  providerMinIntervalMs: number
  /** Do not comment while a line is on screen. */
  neverInterrupt: boolean
}

export const DEFAULT_SETTINGS: BuddySettings = {
  budgetPerMinute: 3,
  cooldownSeconds: 12,
  contextSize: 8,
  window: { before: 3, after: 2, recent: 8 },
  maxRemarkChars: 240,
  providerMinIntervalMs: 4000,
  neverInterrupt: true,
}

export interface BuddyRemark {
  id: string
  /** The cue the remark is about. */
  cue: MediaCue
  /** Where the words came from. */
  source: CommentarySource
  /** What Sidekick says. */
  say: string
  /** The cues the remark is grounded in. */
  grounded_in: number[]
  /** The media time the remark belongs to. */
  at: number
  /** Why the companion decided to speak - shown in the interface. */
  reason: string
}

export type RemarkDecision =
  | { kind: 'speak'; remark: BuddyRemark }
  | { kind: 'silent'; reason: string }
  | { kind: 'declined'; reason: string; source: CommentarySource }

/** How the engine is allowed to describe the moment. */
export interface EngineOptions {
  provider: CommentaryProvider
  settings?: Partial<BuddySettings>
  /** Injected clock, so the behaviour is deterministic in tests. */
  now?: () => number
}

export class BuddyEngine {
  private provider: CommentaryProvider
  private readonly settings: BuddySettings
  private readonly now: () => number

  private seen = new Set<string>()
  private lastCueIndex = -1
  private lastSpokeAt: number | null = null
  private lastProviderCallAt = 0
  private spokenInWindow = 0
  private windowStart = 0

  constructor(options: EngineOptions) {
    this.provider = options.provider
    this.settings = { ...DEFAULT_SETTINGS, ...options.settings }
    this.now = options.now ?? (() => Date.now())
    this.windowStart = this.now()
  }

  get source(): CommentarySource {
    return this.provider.source
  }

  get providerId(): string {
    return this.provider.id
  }

  /** Forget everything - used when the film or the subtitle track changes. */
  reset(): void {
    this.seen.clear()
    this.lastCueIndex = -1
    this.lastSpokeAt = null
    this.lastProviderCallAt = 0
    this.spokenInWindow = 0
    this.windowStart = this.now()
  }

  /**
   * Swap the commentary provider.
   *
   * Used when the film has no usable subtitles: the companion then has
   * nothing to read, and the interface says so instead of guessing.
   */
  setProvider(provider: CommentaryProvider): void {
    this.provider = provider
    this.reset()
  }

  /**
   * Decide what to do at the current playback position.
   *
   * Returns a decision, never a remark on its own, so the caller can show
   * the reason even when Sidekick stays silent.
   */
  async consider(options: {
    mode: BuddyMode
    quietUntil: number
    cues: MediaCue[]
    currentTime: number
    /** True while a caption line is on screen. */
    captionOnScreen: boolean
    /** The question the viewer asked, if any. */
    question?: string
    filmId?: string
    filmTitle?: string
    signal?: AbortSignal
  }): Promise<RemarkDecision> {
    const {
      mode,
      quietUntil,
      cues,
      currentTime,
      captionOnScreen,
      question,
      filmId,
      filmTitle,
      signal,
    } = options

    if (mode === 'off') {
      return { kind: 'silent', reason: 'Movie Buddy is switched off.' }
    }
    if (mode === 'quiet') {
      return { kind: 'silent', reason: 'Movie Buddy is in quiet mode.' }
    }
    if (this.now() < quietUntil) {
      const seconds = Math.ceil((quietUntil - this.now()) / 1000)
      return { kind: 'silent', reason: `Quiet for another ${seconds}s.` }
    }

    const onScreen = captionOnScreen

    // No usable subtitles: say what the limitation is and ask for a track,
    // rather than inventing a scene.
    if (cues.length === 0) {
      this.lastCueIndex = -1
      return {
        kind: 'declined',
        reason:
          'There is no caption track for this film, so there is nothing to read. Load a subtitle file to switch the companion on.',
        source: 'unavailable',
      }
    }

    // The line the companion is talking about: the most recent one that has
    // started. It may still be on screen, or it may have just finished - and
    // the gap between lines is exactly when a remark fits.
    const focus = lastStartedCue(cues, currentTime)
    if (!focus) {
      this.lastCueIndex = -1
      return { kind: 'silent', reason: 'No caption line has been said yet.' }
    }

    const window = buildCueWindow(
      cues,
      focus.start + 0.001,
      {
        ...this.settings.window,
        recent: this.settings.contextSize,
      },
    )

    const current = window.current ?? focus

    if (current.index === this.lastCueIndex) {
      return { kind: 'silent', reason: 'This line was already considered.' }
    }

    // Never talk over a line. The line is *not* marked as considered here, so
    // the companion can still remark on it once it finishes.
    if (onScreen && this.settings.neverInterrupt && !question) {
      return { kind: 'silent', reason: 'A caption is on screen, so Sidekick stays quiet.' }
    }

    // A line that is being said right now is not a good moment, unless the
    // viewer asked a question about it.
    if (!question && this.isImportant(current, window.recent)) {
      return {
        kind: 'silent',
        reason: 'That line is doing the work - Sidekick will not talk over it.',
      }
    }

    // The same moment is never commented on twice, even after a seek back.
    const key = `${current.index}`
    if (this.seen.has(key)) {
      return { kind: 'silent', reason: 'Sidekick already commented on this moment.' }
    }

    const gate = this.speakingGate()
    if (!gate.allowed) {
      return { kind: 'silent', reason: gate.reason }
    }

    // From here on the line is spent, whatever the provider does.
    this.lastCueIndex = current.index

    // A hard rate limit on the provider, independent of the speaking budget.
    const now = this.now()
    if (now - this.lastProviderCallAt < this.settings.providerMinIntervalMs) {
      return { kind: 'silent', reason: 'Sidekick checked a moment ago; waiting.' }
    }
    this.lastProviderCallAt = now

    let result
    try {
      result = await this.provider.generate(
        {
          film: { id: filmId ?? 'film', title: filmTitle ?? 'this film' },
          window,
          question,
          maxLength: this.settings.maxRemarkChars,
        },
        signal,
      )
    } catch (cause) {
      return {
        kind: 'declined',
        reason: `The commentary provider failed: ${
          cause instanceof Error ? cause.message : 'unknown error'
        }`,
        source: this.provider.source,
      }
    }

    if (result.declined || result.say.trim().length === 0) {
      this.seen.add(key)
      return {
        kind: 'declined',
        reason: result.reason ?? 'Sidekick had nothing worth saying here.',
        source: result.source,
      }
    }

    this.seen.add(key)
    this.spokenInWindow += 1
    this.lastSpokeAt = now

    return {
      kind: 'speak',
      remark: {
        id: `${current.index}-${this.lastSpokeAt}`,
        cue: current,
        source: result.source,
        say: result.say,
        grounded_in: result.grounded_in.length > 0 ? result.grounded_in : [current.index],
        at: current.start,
        reason: this.reasonFor(current, window.recent),
      },
    }
  }

  /**
   * Is this line carrying the scene?
   *
   * A long line, an emphatic line, or a line that answers the question
   * before it is the wrong moment to talk.
   */
  private isImportant(cue: MediaCue, recent: MediaCue[]): boolean {
    const features = analyzeCue(cue, recent)
    if (features.isLong) return true
    if (features.isEmphasis) return true
    // A question that the next line answers is important, but we cannot know
    // that from the previous lines alone, so we treat a bare question as
    // important only when it is long.
    if (features.isQuestion && features.keywords.length >= 3) return true
    return false
  }

  private reasonFor(cue: MediaCue, recent: MediaCue[]): string {
    const features = analyzeCue(cue, recent)
    if (features.isSound) return 'The caption track marked this line as a sound.'
    if (features.repeats.length > 0) {
      return `The line repeats "${features.repeats[0]}" from a moment ago.`
    }
    if (features.newTerms.length >= 2) {
      return `New vocabulary appeared: ${features.newTerms.join(', ')}.`
    }
    if (features.isQuestion) return 'A question was asked in the dialogue.'
    return 'The dialogue changed in a way worth noticing.'
  }

  private speakingGate(): { allowed: boolean; reason: string } {
    const now = this.now()
    if (now - this.windowStart > 60_000) {
      this.windowStart = now
      this.spokenInWindow = 0
    }
    if (this.spokenInWindow >= this.settings.budgetPerMinute) {
      return { allowed: false, reason: 'The speaking budget for this minute is spent.' }
    }
    if (this.lastSpokeAt !== null && now - this.lastSpokeAt < this.settings.cooldownSeconds * 1000) {
      return { allowed: false, reason: 'Sidekick is cooling down after the last remark.' }
    }
    return { allowed: true, reason: '' }
  }
}
