/**
 * Sidekick API contract v1 - browser-side types.
 *
 * These mirror `.sidekick/API_CONTRACTS.md` (owner: Agent 1). Field names are
 * deliberately identical to the document so the wire format never drifts.
 *
 * Reference: .sidekick/API_CONTRACTS.md @ 1b80a0d
 */

/** Session identity precedence: header wins, then validated body field. */
export const SESSION_HEADER = 'x-sidekick-session-id'

export type InputSource = 'voice' | 'text'

export type RiskLevel = 'low' | 'medium' | 'high' | 'irreversible'

export type ActionState =
  | 'pending'
  | 'awaiting_confirmation'
  | 'running'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'superseded'

export interface ContractError {
  code: string
  message: string
  retryable: boolean
  timeout: boolean
}

export interface CorrectionContext {
  /** Free-form correction signal extracted from the utterance or UI. */
  signal?: string
  /** Action id the correction targets, when known. */
  supersedes?: string
  [key: string]: unknown
}

export interface ContinuationContext {
  /** Follow-up to a previous request in the same session. */
  previous_request_id?: string
  [key: string]: unknown
}

export interface SidekickRequest {
  request_id: string
  session_id: string
  utterance: string
  input_source: InputSource
  utterance_finalized: boolean
  correction_context?: CorrectionContext
  continuation_context?: ContinuationContext
}

export interface Intent {
  normalized: string
  confidence: number
  ambiguous: boolean
  entities: unknown[]
}

export interface DecisionModel {
  provider: string
  model: string
  fallback_used: boolean
}

export interface ActionTimestamps {
  created: string
  updated: string
}

export interface Action {
  action_id: string
  tool: string
  arguments: Record<string, unknown>
  approval_required: boolean
  state: ActionState
  superseded_by: string | null
  result?: unknown
  error?: ContractError
  timestamps: ActionTimestamps
}

export interface Clarification {
  question: string
  options: string[]
}

export type ProgressEventKind =
  | 'progress'
  | 'log'
  | 'action_update'
  | 'diff'
  | 'result'
  | 'error'

export interface ProgressEvent {
  /** Monotonic sequence number assigned by the backend. */
  seq?: number
  kind?: ProgressEventKind
  /** Human readable status line. */
  message?: string
  /** Tool / action this event belongs to. */
  action_id?: string
  tool?: string
  /** Structured payload (e.g. a diff for a coding job). */
  data?: unknown
  /** ISO timestamp when the event was produced. */
  at?: string
}

export interface SidekickResponse {
  request_id: string
  session_id: string
  intent: Intent
  action_plan: Action[]
  risk_level: RiskLevel
  decision_model: DecisionModel
  status: ActionState
  clarification: Clarification | null
  events: ProgressEvent[]
  /** Optional spoken/summary text produced by the backend. */
  speech?: string | null
}

/* ------------------------------------------------------------------ *
 * Capabilities
 * Agent 1 owns the canonical schema; this is the shape the UI consumes.
 * `state` drives the live / simulated / unavailable badges in the UI.
 * ------------------------------------------------------------------ */

export type CapabilityState =
  | 'live'
  | 'simulated'
  | 'unavailable'
  | 'unconfigured'
  | 'disconnected'

export interface Capability {
  id: string
  state: CapabilityState
  /** Short, truthful explanation of the current state. */
  detail?: string
}

export interface GameDescriptor {
  id: string
  name: string
  state: CapabilityState
  detail?: string
}

export interface ProviderDescriptor {
  id: string
  name: string
  state: CapabilityState
  detail?: string
  /** True when the provider needs a user login / subscription we do not have. */
  requires_user_action?: boolean
}

export interface CapabilitiesResponse {
  contract_version: string
  /** `live` = talking to the real backend, `stub` = local development double. */
  mode: 'live' | 'stub'
  capabilities: Capability[]
  games?: GameDescriptor[]
  providers?: ProviderDescriptor[]
}

/* ------------------------------------------------------------------ *
 * Media catalog (movie companion)
 * ------------------------------------------------------------------ */

export interface CompanionRule {
  /** Regular expression source matched against the cue text. */
  pattern: string
  title: string
  /** Why this event surfaced - shown verbatim in the UI. */
  reason: string
}

export interface MediaAsset {
  id: string
  title: string
  /** Attribution line, e.g. author + license. */
  credit: string
  license: string
  /** Streamable source. */
  src: string
  mime_type: string
  /** Subtitle source (local file shipped with the app). */
  subtitle_src: string
  subtitle_label: string
  /** Inline cue data, parsed from the shipped subtitle file. */
  cues: MediaCue[]
  /** Rules that map subtitle cues to companion events. */
  companion_rules: CompanionRule[]
  duration_hint_seconds?: number
}

export interface MediaCue {
  index: number
  start: number
  end: number
  text: string
}
