/**
 * Endpoint paths for the Sidekick backend.
 *
 * The request/response *shapes* are owned by Agent 1
 * (`.sidekick/API_CONTRACTS.md`). The URL paths below are the browser
 * client's expectation; they are all overridable with `VITE_SIDECKICK_*`
 * environment variables so a server-side path change is a one-line fix here
 * rather than a change spread across the UI.
 */

const env = (import.meta.env ?? {}) as Record<string, string | undefined>

const pick = (name: string, fallback: string): string => {
  const value = env[name]
  return value && value.length > 0 ? value : fallback
}

export const ENDPOINTS = {
  /** Submit an utterance; returns the v1 response (JSON or SSE stream). */
  interpret: pick('VITE_SIDECKICK_INTERPRET_PATH', '/api/v1/requests'),
  /** Live/simulated capability inventory. */
  capabilities: pick('VITE_SIDECKICK_CAPABILITIES_PATH', '/api/v1/capabilities'),
  /** Media catalog for the movie companion. */
  mediaCatalog: pick('VITE_SIDECKICK_MEDIA_PATH', '/api/v1/media/catalog'),
  /** Action status polling (used when streaming is unavailable). */
  action: (actionId: string) =>
    pick('VITE_SIDECKITCH_ACTION_PATH', '/api/v1/actions/:id').replace(':id', actionId),
  /** The live event stream of one action; `after` resumes it after a gap. */
  actionEvents: (actionId: string, afterSeq: number | null) => {
    const base = pick('VITE_SIDECKICK_ACTION_EVENTS_PATH', '/api/v1/actions/:id/events').replace(
      ':id',
      actionId,
    )
    return afterSeq === null ? base : `${base}?after=${afterSeq}`
  },
  /** Approve or refuse a pending action. */
  approve: (actionId: string) =>
    pick('VITE_SIDECKICK_APPROVE_PATH', '/api/v1/actions/:id/approve').replace(':id', actionId),
  /** Cancel a pending or running action. */
  cancel: (actionId: string) =>
    pick('VITE_SIDECKICK_CANCEL_PATH', '/api/v1/actions/:id/cancel').replace(':id', actionId),
} as const

/**
 * Base URL for the API. Empty string means "same origin", which is what the
 * Vite dev proxy uses. A cross-origin URL is allowed for deployed setups.
 */
export const API_BASE = pick('VITE_SIDECKICK_API_BASE', '')
