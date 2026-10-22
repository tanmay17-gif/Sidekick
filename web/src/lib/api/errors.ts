import type { ContractError } from './types'

/**
 * A transport or contract failure, normalised to the v1 error model.
 * `code` mirrors `ContractError.code` so the UI can branch on stable codes.
 */
export class SidekickApiError extends Error {
  readonly code: string
  readonly retryable: boolean
  readonly timeout: boolean
  readonly status: number | null
  readonly details: unknown

  constructor(init: {
    code: string
    message: string
    retryable?: boolean
    timeout?: boolean
    status?: number | null
    details?: unknown
  }) {
    super(init.message)
    this.name = 'SidekickApiError'
    this.code = init.code
    this.retryable = init.retryable ?? false
    this.timeout = init.timeout ?? false
    this.status = init.status ?? null
    this.details = init.details ?? null
  }

  toContractError(): ContractError {
    return {
      code: this.code,
      message: this.message,
      retryable: this.retryable,
      timeout: this.timeout,
    }
  }
}

export const isApiError = (value: unknown): value is SidekickApiError =>
  value instanceof SidekickApiError

/** Human readable, non-technical wording for common failures. */
export function describeApiError(error: unknown): string {
  if (!isApiError(error)) {
    return error instanceof Error ? error.message : 'Something went wrong.'
  }
  switch (error.code) {
    case 'network_unreachable':
      return 'Could not reach the Sidekick backend. Check that it is running, then retry.'
    case 'timeout':
      return 'The backend took too long to respond. The request was cancelled.'
    case 'not_found':
      return 'The backend does not expose this endpoint yet.'
    case 'session_conflict':
      return 'This session id is already in use by another client.'
    case 'contract_violation':
      return 'The backend response did not match the Sidekick contract.'
    default:
      return error.message
  }
}
