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

/**
 * Turn level states. The action lifecycle states above apply to a single
 * action; these two describe the turn as a whole.
 */
export type ResponseStatus = ActionState | 'needs_clarification' | 'awaiting_transcript'

export interface ContractError {
  code: string
  message: string
  retryable: boolean
  timeout: boolean
  /** Optional structured context, added in the ratified contract. */
  details?: unknown
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
  /** Where the interpretation came from (for example `rules` or a model id). */
  source?: string
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
  /** Human readable description of the action. */
  description?: string
  /** Fingerprint of the tool plus its arguments; a confirmation binds to it. */
  plan_hash?: string
  /** The execution job that carries this action, when there is one. */
  job_id?: string
  /** Progress between 0 and 1, when the backend reports it. */
  progress?: number
  result?: unknown
  error?: ContractError
  timestamps: ActionTimestamps
}

/* ------------------------------------------------------------------ *
 * Execution results
 * ------------------------------------------------------------------ */

export interface ChangedFile {
  path: string
  status?: string
}

export interface TestResult {
  argv?: string[]
  exit_code?: number
  passed?: boolean
  /** Populated only when the runner actually printed counts. */
  counts?: Record<string, number>
  counts_available?: boolean
  summary?: string
  duration_ms?: number
  timed_out?: boolean
  cancelled?: boolean
  truncated?: boolean
}

export interface ExecutionResult {
  /** `partial` means real changes were applied but the required tests failed. */
  outcome?: 'succeeded' | 'partial' | 'failed' | 'cancelled'
  summary?: string
  workspace?: string
  changed_files?: ChangedFile[]
  diff?: string
  diff_truncated?: boolean
  head_sha?: string
  provider?: {
    name?: string
    level?: string
    simulated?: boolean
    available?: boolean
    reason?: string
    model?: string
    latency_ms?: number
  }
  test_result?: TestResult
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
  /** Coarse category the UI switches on. */
  kind?: ProgressEventKind
  /** The execution service's own category. */
  type?: string
  /** Human readable status line. */
  message?: string
  /** Tool / action this event belongs to. */
  action_id?: string
  tool?: string
  /** The execution job that carries the action, when there is one. */
  job_id?: string
  /** The action state at the time of the event. */
  status?: string
  /** Structured payload (e.g. a diff for a coding job). */
  data?: unknown
  /** ISO timestamp when the event was produced. */
  ts?: string
  /** ISO timestamp when the event was produced (client-side alias). */
  at?: string
}

export interface SidekickResponse {
  request_id: string
  session_id: string
  intent: Intent
  action_plan: Action[]
  risk_level: RiskLevel
  decision_model: DecisionModel
  status: ResponseStatus
  clarification: Clarification | null
  events: ProgressEvent[]
  /** Optional spoken/summary text produced by the backend. */
  speech?: string | null
}

/**
 * The envelope the action endpoints return: one action plus its events.
 * `POST /api/v1/actions/{id}/approve`, `POST .../cancel` and
 * `GET /api/v1/actions/{id}` all answer with this shape - not with a
 * `SidekickResponse`.
 */
export interface ActionEnvelope {
  action: Action
  events?: ProgressEvent[]
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
  | 'client'

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

/**
 * The execution service's vocabulary for the same capability. Rendered
 * verbatim - the browser never converts one vocabulary into the other.
 */
export type ToolStatus =
  | 'REAL'
  | 'SIMULATED'
  | 'NOT_CONFIGURED'
  | 'NOT_IMPLEMENTED'
  | 'UNAVAILABLE'

export interface ToolDescriptor {
  tool: string
  description?: string
  arguments_schema?: Record<string, unknown>
  approval_required?: boolean
  risk_level?: string
  status: ToolStatus
  status_detail?: string
  simulated?: boolean
}

export interface CapabilitiesResponse {
  contract_version: string
  /** `live` = talking to the real backend, `stub` = local development double. */
  mode: 'live' | 'stub'
  capabilities: Capability[]
  /** The execution service's own status vocabulary. */
  tools?: ToolDescriptor[]
  tool_count?: number
  status_counts?: Record<string, number>
  any_simulated?: boolean
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

export interface MediaSource {
  src: string
  mime_type: string
  label: string
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
  /**
   * Alternative encodes of the same film. The player offers them in order and
   * the browser picks the first one it can decode - a codec-limited browser
   * still gets the film.
   */
  sources?: MediaSource[]
  /** Subtitle source (local file shipped with the app). */
  subtitle_src: string
  subtitle_label: string
  /** Inline cue data, parsed from the shipped subtitle file. */
  cues: MediaCue[]
  /** Rules that map subtitle cues to companion events. */
  companion_rules: CompanionRule[]
  /** True when the media file ships with the app. */
  bundled?: boolean
  /** The shape of the picture, so the player does not pillarbox the film. */
  aspect_ratio?: string
  duration_hint_seconds?: number
}

export interface MediaCue {
  index: number
  start: number
  end: number
  text: string
}
