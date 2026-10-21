import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { ExecutionResultView } from '@/components/ExecutionResult'
import type { Action } from '@/lib/api/types'

function action(overrides: Partial<Action> = {}): Action {
  return {
    action_id: 'a-1',
    tool: 'coding.execute',
    arguments: {},
    approval_required: false,
    state: 'succeeded',
    superseded_by: null,
    result: undefined,
    error: undefined,
    timestamps: { created: '2026-01-01T00:00:00Z', updated: '2026-01-01T00:00:01Z' },
    ...overrides,
  }
}

const DIFF = [
  '@@ -1,3 +1,4 @@',
  ' export function greet(name) {',
  "-  return 'Hello ' + name",
  '+  return `Hello ${name.trim()}`',
  ' }',
].join('\n')

describe('execution result rendering', () => {
  it('shows the diff, the changed files and the test result together', () => {
    render(
      <ExecutionResultView
        action={action({
          result: {
            outcome: 'succeeded',
            changed_files: [{ path: 'src/app.py', status: 'modified' }],
            diff: DIFF,
            provider: { name: 'http_api', level: 'REAL', simulated: false },
            test_result: {
              argv: ['python', '-m', 'unittest', 'discover'],
              exit_code: 0,
              passed: true,
              counts_available: false,
              counts: {},
              summary: 'All executed tests passed.',
            },
          },
        })}
      />,
    )

    // The diff is rendered.
    expect(screen.getByText('unified diff')).toBeInTheDocument()
    // The changed file list is NOT hidden behind the diff.
    expect(screen.getByText('src/app.py')).toBeInTheDocument()
    expect(screen.getByText('1 file changed')).toBeInTheDocument()
    // The test result is rendered too.
    expect(screen.getByText('tests passed')).toBeInTheDocument()
    expect(screen.getByText('exit 0')).toBeInTheDocument()
    expect(screen.getByText('All executed tests passed.')).toBeInTheDocument()
  })

  it('renders the exit code and not an invented count of passing tests', () => {
    render(
      <ExecutionResultView
        action={action({
          result: {
            outcome: 'succeeded',
            test_result: { exit_code: 0, passed: true, counts_available: false, counts: {} },
          },
        })}
      />,
    )

    expect(screen.getByText('no counts reported by the runner')).toBeInTheDocument()
    expect(screen.queryByText(/passed \d+/)).not.toBeInTheDocument()
  })

  it('renders the counts when the runner actually reported them', () => {
    render(
      <ExecutionResultView
        action={action({
          result: {
            outcome: 'succeeded',
            test_result: { exit_code: 0, passed: true, counts_available: true, counts: { passed: 12 } },
          },
        })}
      />,
    )

    expect(screen.getByText('passed 12')).toBeInTheDocument()
    expect(screen.queryByText('no counts reported by the runner')).not.toBeInTheDocument()
  })

  it('never renders a partial result as a success', () => {
    render(
      <ExecutionResultView
        action={action({
          state: 'failed',
          result: {
            outcome: 'partial',
            changed_files: [{ path: 'src/app.py', status: 'modified' }],
            diff: DIFF,
          },
          error: {
            code: 'test_failed',
            message: 'the required tests failed',
            retryable: false,
            timeout: false,
          },
        })}
      />,
    )

    const container = screen.getByText(/partial/i).closest('.exec')
    expect(container).not.toBeNull()
    expect(container).toHaveAttribute('data-outcome', 'partial')
    // The failure is visible, and the changes are still visible.
    expect(screen.getByText('test_failed')).toBeInTheDocument()
    expect(screen.getByText('src/app.py')).toBeInTheDocument()
    expect(screen.getByText('unified diff')).toBeInTheDocument()
  })

  it('shows the failure that carries the result inside error.details', () => {
    render(
      <ExecutionResultView
        action={action({
          state: 'failed',
          result: undefined,
          error: {
            code: 'test_failed',
            message: 'the required tests failed',
            retryable: false,
            timeout: false,
            details: {
              outcome: 'partial',
              changed_files: [{ path: 'src/other.py', status: 'modified' }],
              diff: DIFF,
            },
          },
        })}
      />,
    )

    expect(screen.getByText('src/other.py')).toBeInTheDocument()
    expect(screen.getByText('unified diff')).toBeInTheDocument()
    expect(screen.getByText('test_failed')).toBeInTheDocument()
  })

  it('labels a simulated provider as simulated', () => {
    render(
      <ExecutionResultView
        action={action({
          result: {
            outcome: 'succeeded',
            provider: { name: 'simulated', level: 'SIMULATED', simulated: true },
          },
        })}
      />,
    )

    const provider = screen.getByText(/provider simulated/i)
    expect(provider).toBeInTheDocument()
    expect(provider.textContent).toContain('simulated')
  })

  it('shows a plain error when there is no result payload', () => {
    render(
      <ExecutionResultView
        action={action({
          state: 'failed',
          error: {
            code: 'tool_unavailable',
            message: 'no adapter is wired up for this tool',
            retryable: false,
            timeout: false,
          },
        })}
      />,
    )

    const container = screen.getByText('tool_unavailable').closest('.exec')
    expect(container).not.toBeNull()
    expect(within(container as HTMLElement).getByText(/no adapter is wired up/)).toBeInTheDocument()
  })
})
