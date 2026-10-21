/**
 * Movie Buddy control commands.
 *
 * These are *interface* commands, not intents: the browser owns the media
 * element, so "pause the movie" has to be answered by the player, not by the
 * decision engine. When an utterance also contains a real request ("play me a
 * movie and turn on Movie Buddy"), the remainder is forwarded to the backend
 * so the core still sees the actual intent.
 */

export type BuddyCommandKind =
  | 'activate'
  | 'deactivate'
  | 'quiet'
  | 'what-happened'
  | 'explain'
  | 'pause'
  | 'resume-playback'
  | 'seek-back'
  | 'seek-forward'
  | 'resume-buddy'
  | 'play-a-movie'

export interface BuddyCommand {
  kind: BuddyCommandKind
  /** Seconds for the seek commands. */
  seconds?: number
  /** The part of the utterance that should still go to the backend. */
  remainder: string
}

const PATTERNS: Array<{ kind: BuddyCommandKind; pattern: RegExp; seconds?: number }> = [
  {
    kind: 'activate',
    pattern:
      /^\s*(?:please\s+)?(?:turn on|switch on|start|enable|wake up)\s+(?:the\s+)?movie\s*buddy\b.*$/i,
  },
  { kind: 'activate', pattern: /^\s*(?:movie\s*buddy)\s*(?:on|please)\b.*$/i },
  {
    kind: 'deactivate',
    pattern: /^\s*(?:turn off|switch off|stop)\s+(?:the\s+)?movie\s*buddy\s*\.?\s*$/i,
  },
  {
    kind: 'resume-buddy',
    pattern:
      /^\s*(?:resume|continue|keep)\s+(?:the\s+)?movie\s*buddy\b.*$|^\s*(?:say something|talk to me again)\b.*$/i,
  },
  {
    kind: 'quiet',
    pattern:
      /^\s*(?:be\s+quiet|quiet down|shush|shut up|stop talking|say nothing|go quiet|be quiet for a (?:bit|while|second|moment))\b.*$/i,
  },
  { kind: 'what-happened', pattern: /^\s*what (?:just )?happened\b.*$/i },
  { kind: 'explain', pattern: /^\s*(?:explain (?:that|this)|what does that mean)\b.*$/i },
  { kind: 'pause', pattern: /^\s*(?:pause|hold) (?:the )?(?:movie|film|video|playback)\b.*$/i },
  { kind: 'pause', pattern: /^\s*pause\s*\.?\s*$/i },
  { kind: 'resume-playback', pattern: /^\s*(?:resume|continue|unpause|play) (?:the )?(?:movie|film|playback)\b.*$/i },
  {
    kind: 'seek-back',
    pattern: /^\s*go back (\d+) seconds?\b.*$/i,
  },
  {
    kind: 'seek-back',
    pattern: /^\s*(?:rewind|go back)\s+(?:a bit|some|ten|twenty|thirty)\b.*$/i,
  },
  { kind: 'seek-forward', pattern: /^\s*(?:skip|go forward) (\d+) seconds?\b.*$/i },
  {
    kind: 'play-a-movie',
    pattern: /^\s*(?:play me a movie|play a movie|start a movie|put on a movie|play a film)\b(.*)$/i,
  },
]

const DEFAULT_BACK_SECONDS = 30

/**
 * Parse an utterance for a Movie Buddy control command.
 *
 * Returns `null` when the utterance is not a companion command, in which case
 * it goes to the backend as an ordinary request.
 */
export function parseBuddyCommand(utterance: string): BuddyCommand | null {
  const text = utterance.trim()
  if (!text) return null

  for (const entry of PATTERNS) {
    const match = entry.pattern.exec(text)
    if (!match) continue

    if (entry.kind === 'seek-back' || entry.kind === 'seek-forward') {
      const explicit = Number(match[1])
      const seconds = Number.isFinite(explicit) && explicit > 0 ? explicit : DEFAULT_BACK_SECONDS
      return { kind: entry.kind, seconds, remainder: '' }
    }

    if (entry.kind === 'play-a-movie') {
      // "Play me a movie and turn on Movie Buddy" also contains an activation.
      const remainder = match[1] ?? ''
      return { kind: 'play-a-movie', remainder: remainder.trim() }
    }

    return { kind: entry.kind, remainder: '' }
  }

  return null
}

/**
 * Detect an activation that is attached to another request, for example
 * "play me a movie and turn on Movie Buddy".
 */
export function containsActivation(utterance: string): boolean {
  return /\b(?:turn on|switch on|start)\s+(?:the\s+)?movie\s*buddy\b/i.test(utterance)
}

/** The companion's own words for what it can and cannot observe. */
export const BUDDY_CAPABILITY_NOTE =
  'Movie Buddy reads the caption track of the video playing in this app. ' +
  'It cannot see other browser tabs, streaming services or system audio, and it does not analyse the picture.'
