import type { Action, ActionState } from '@/lib/api/types'
import { ExecutionResultView } from './ExecutionResult'
import { Dot } from './ui'

/**
 * A context-aware card for one action.
 *
 * It shows what the action was, what it needed, and what actually came
 * back - including the real diff, the changed files and the test result.
 */

const STATE_TONE: Record<ActionState, Parameters<typeof Dot>[0]['tone']> = {
  pending: 'muted',
  awaiting_confirmation: 'confirm',
  running: 'executing',
  paused: 'muted',
  succeeded: 'success',
  failed: 'danger',
  cancelled: 'muted',
  superseded: 'muted',
}

const STATE_LABEL: Record<ActionState, string> = {
  pending: 'pending',
  awaiting_confirmation: 'needs confirmation',
  running: 'running',
  paused: 'paused',
  succeeded: 'done',
  failed: 'failed',
  cancelled: 'cancelled',
  superseded: 'superseded',
}

export function ActionCard({ action }: { action: Action }) {
  return (
    <article className="action-card" data-state={action.state}>
      <header className="action-card__head">
        <span className="action-card__tool">{action.tool}</span>
        <span className="action-card__state">
          <Dot tone={STATE_TONE[action.state] ?? 'muted'} />
          {STATE_LABEL[action.state] ?? action.state}
        </span>
      </header>

      {action.description ? <p className="action-card__desc">{action.description}</p> : null}

      {Object.keys(action.arguments).length > 0 ? (
        <p className="action-card__args">
          {Object.entries(action.arguments)
            .map(([key, value]) => `${key}=${typeof value === 'string' ? value : JSON.stringify(value)}`)
            .join('   ')}
        </p>
      ) : null}

      {action.approval_required ? (
        <p className="action-card__approval">
          This action needs approval before it can run.
        </p>
      ) : null}

      {typeof action.progress === 'number' && action.progress > 0 ? (
        <div className="action-card__progress" aria-hidden="true">
          <span style={{ width: `${Math.round(action.progress * 100)}%` }} />
        </div>
      ) : null}

      <ExecutionResultView action={action} />
    </article>
  )
}
