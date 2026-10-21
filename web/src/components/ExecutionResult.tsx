import type { Action, ExecutionResult } from '@/lib/api/types'
import { AlertIcon, CheckIcon } from './icons'

/**
 * The result of an action.
 *
 * Agent 2's issue #6: when a diff is present the changed-file list and the
 * test result must still be shown, because a job that applied real changes
 * and then failed its tests must never look like a success. The exit code is
 * rendered; a count of "passing tests" is only rendered when the runner
 * actually printed one.
 */

export interface ExecutionResultViewProps {
  action: Action
}

function asExecutionResult(action: Action): ExecutionResult | null {
  const candidates: unknown[] = [action.result]
  const details = (action.error as { details?: unknown } | undefined)?.details
  if (details && typeof details === 'object') {
    const record = details as Record<string, unknown>
    if (record.outcome || record.diff || record.changed_files) candidates.push(record)
    if (record.result && typeof record.result === 'object') candidates.push(record.result)
  }
  for (const candidate of candidates) {
    if (candidate && typeof candidate === 'object') {
      const record = candidate as Record<string, unknown>
      if (record.diff || record.changed_files || record.outcome || record.test_result) {
        return record as ExecutionResult
      }
    }
  }
  return null
}

export function ExecutionResultView({ action }: ExecutionResultViewProps) {
  const result = asExecutionResult(action)

  if (!result) {
    if (action.error) {
      return (
        <div className="exec exec--error">
          <div className="exec__row">
            <AlertIcon size={13} />
            <span className="exec__code">{action.error.code}</span>
            <span className="exec__message">{action.error.message}</span>
          </div>
          {action.error.retryable ? (
            <p className="exec__note">This failure is marked retryable by the backend.</p>
          ) : null}
        </div>
      )
    }
    if (typeof action.result === 'string' && action.result.length > 0) {
      return <pre className="exec__raw">{action.result}</pre>
    }
    if (action.result !== undefined && action.result !== null) {
      // A result that is not an execution payload is still shown, verbatim.
      try {
        return <pre className="exec__raw">{JSON.stringify(action.result, null, 2)}</pre>
      } catch {
        return <pre className="exec__raw">{String(action.result)}</pre>
      }
    }
    return null
  }

  const outcome = result.outcome
  const partial = outcome === 'partial'
  const failed = outcome === 'failed' || action.state === 'failed'
  const cancelled = outcome === 'cancelled'
  const provider = result.provider

  return (
    <div className="exec" data-outcome={outcome ?? 'unknown'}>
      <div className="exec__row">
        {failed ? <AlertIcon size={13} /> : <CheckIcon size={13} />}
        <span className="exec__outcome">
          {partial
            ? 'partial - changes were applied but the required tests failed'
            : cancelled
              ? 'cancelled'
              : failed
                ? 'failed'
                : (outcome ?? 'completed')}
        </span>
        {provider ? (
          <span className="exec__provider">
            provider {provider.name ?? 'unknown'} · {provider.level ?? provider.reason ?? 'unknown'}
            {provider.simulated ? ' · simulated' : ''}
          </span>
        ) : null}
      </div>

      {result.summary ? <p className="exec__summary">{result.summary}</p> : null}

      {result.changed_files && result.changed_files.length > 0 ? (
        <div className="exec__files">
          <span className="exec__files-label">
            {result.changed_files.length} file{result.changed_files.length === 1 ? '' : 's'} changed
          </span>
          <ul>
            {result.changed_files.map((file) => (
              <li key={file.path}>
                <code>{file.path}</code>
                {file.status ? <span className="exec__file-status">{file.status}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {result.test_result ? (
        <div className="exec__tests" data-passed={result.test_result.passed ? 'true' : 'false'}>
          <span className="exec__tests-title">
            {result.test_result.passed ? 'tests passed' : 'tests failed'}
          </span>
          {typeof result.test_result.exit_code === 'number' ? (
            <span className="exec__exit">exit {result.test_result.exit_code}</span>
          ) : null}
          {result.test_result.counts_available && result.test_result.counts ? (
            <span className="exec__counts">
              {Object.entries(result.test_result.counts)
                .map(([key, value]) => `${key} ${value}`)
                .join(' · ')}
            </span>
          ) : (
            <span className="exec__counts exec__counts--absent">
              no counts reported by the runner
            </span>
          )}
          {result.test_result.summary ? (
            <span className="exec__tests-summary">{result.test_result.summary}</span>
          ) : null}
          {result.test_result.argv && result.test_result.argv.length > 0 ? (
            <code className="exec__argv">{result.test_result.argv.join(' ')}</code>
          ) : null}
        </div>
      ) : null}

      {result.diff ? (
        <div className="exec__diff">
          <div className="exec__diff-head">
            unified diff
            {result.diff_truncated ? <span className="exec__truncated">truncated</span> : null}
          </div>
          <pre className="exec__diff-body">
            {result.diff.split('\n').map((line, index) => {
              const variant = line.startsWith('+++') || line.startsWith('---')
                ? 'ctx'
                : line.startsWith('@@')
                  ? 'hunk'
                  : line.startsWith('+')
                    ? 'add'
                    : line.startsWith('-')
                      ? 'del'
                      : 'ctx'
              return (
                <div key={index} className={`exec__line exec__line--${variant}`}>
                  {line || ' '}
                </div>
              )
            })}
          </pre>
        </div>
      ) : null}

      {action.error ? (
        <div className="exec__row exec__row--error">
          <AlertIcon size={13} />
          <span className="exec__code">{action.error.code}</span>
          <span className="exec__message">{action.error.message}</span>
        </div>
      ) : null}
    </div>
  )
}
