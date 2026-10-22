import type { ActionRecord } from '@/state/useSidekick'
import { actionStatusLine, friendlyFailure, stateChipLabel } from '@/lib/ui/language'
import { AlertIcon, CheckIcon, StopIcon } from './icons'

/**
 * The action card as a person sees it.
 *
 * It never shows a tool name, a request id or a raw payload: it says what
 * Sidekick is doing, what state the backend reported, and what can be done
 * about it. The technical detail lives in the developer view.
 */

export interface ActionCardProps {
  record: ActionRecord
  /** True while an approval or a cancellation is in flight. */
  busy?: boolean
  /** A user-facing failure for this action. */
  error?: string
  onApprove?: (record: ActionRecord) => void
  onCancel?: (record: ActionRecord) => void
  onRetry?: (record: ActionRecord) => void
}

export function ActionCard({
  record,
  busy = false,
  error,
  onApprove,
  onCancel,
  onRetry,
}: ActionCardProps) {
  const { action, state } = record
  const cancellable = state === 'running' || state === 'pending'
  const needsApproval = state === 'awaiting_confirmation'
  const failure = friendlyFailure(action, state)
  const simulated = isSimulated(action)

  return (
    <article className="task-card" data-state={state}>
      <div className="task-card__row">
        <span className="task-card__chip" data-state={state}>
          <TaskCardDot state={state} />
          {stateChipLabel(state)}
        </span>
        {simulated ? (
          <span className="task-card__simulated" title="The backend reports this result as simulated">
            simulated
          </span>
        ) : null}
        {cancellable && onCancel ? (
          <button
            type="button"
            className="btn btn--sm btn--ghost"
            disabled={busy}
            onClick={() => onCancel(record)}
          >
            <StopIcon size={12} />
            Cancel
          </button>
        ) : null}
      </div>

      <p className="task-card__line">{actionStatusLine(action, state)}</p>

      {needsApproval && onApprove ? (
        <div className="task-card__approval">
          <p className="task-card__approval-text">
            This one changes something, so I will not do it until you say so.
          </p>
          <div className="row row--wrap">
            <button
              type="button"
              className="btn btn--sm btn--primary"
              disabled={busy}
              onClick={() => onApprove(record)}
            >
              {busy ? 'Working…' : 'Yes, go ahead'}
            </button>
            <button
              type="button"
              className="btn btn--sm"
              disabled={busy}
              onClick={() => onCancel?.(record)}
            >
              No, leave it
            </button>
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="task-card__error" role="alert">
          <AlertIcon size={13} />
          <span>{error}</span>
        </div>
      ) : null}

      {state === 'failed' || state === 'timed_out' ? (
        <div className="task-card__failure">
          <p className="task-card__failure-text">{failure.message}</p>
          {failure.recovery ? (
            <p className="task-card__recovery">{failure.recovery}</p>
          ) : null}
          {failure.recovery && onRetry ? (
            <button type="button" className="btn btn--sm" onClick={() => onRetry?.(record)}>
              Try again
            </button>
          ) : null}
        </div>
      ) : null}
    </article>
  )
}

function TaskCardDot({ state }: { state: ActionRecord['state'] }) {
  if (state === 'succeeded') return <CheckIcon size={11} />
  if (state === 'failed' || state === 'timed_out') return <AlertIcon size={11} />
  return <span className="task-card__pulse" aria-hidden="true" />
}

/**
 * True when the backend itself says the result was simulated. A simulated
 * result is never presented as a live one.
 */
function isSimulated(action: ActionRecord['action']): boolean {
  const result = action.result as
    | { simulated?: boolean; provider?: { simulated?: boolean; level?: string } }
    | null
    | undefined
  if (!result || typeof result !== 'object') return false
  if (result.simulated === true) return true
  if (result.provider?.simulated === true) return true
  return (result.provider?.level ?? '').toUpperCase() === 'SIMULATED'
}
