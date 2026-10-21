import type { MediaCue } from '@/lib/api/types'

/**
 * An imperative handle the app uses to drive the Movie Buddy surface.
 *
 * The companion lives inside the movie surface, but the voice commands that
 * control it arrive on the talk surface. The surface registers its
 * controller here so a spoken command can act on the player without a global
 * store.
 */
export interface BuddyController {
  activate(): void
  deactivate(): void
  quiet(ms?: number): void
  resume(): void
  askWhatHappened(): void
  askExplain(): void
  togglePlay(): void
  pause(): void
  seekBack(seconds: number): void
}

export const NOOP_BUDDY_CONTROLLER: BuddyController = {
  activate: () => {},
  deactivate: () => {},
  quiet: () => {},
  resume: () => {},
  askWhatHappened: () => {},
  askExplain: () => {},
  togglePlay: () => {},
  pause: () => {},
  seekBack: () => {},
}

/** The recent caption context the companion keeps. Bounded on purpose. */
export const CONTEXT_LIMIT = 8

export function boundedContext(context: MediaCue[], limit = CONTEXT_LIMIT): MediaCue[] {
  return context.length > limit ? context.slice(context.length - limit) : context
}
