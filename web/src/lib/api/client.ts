import { API_BASE, ENDPOINTS } from './endpoints'
import { SidekickApiError } from './errors'
import {
  SESSION_HEADER,
  type ActionEnvelope,
  type CapabilitiesResponse,
  type ProgressEvent,
  type SidekickRequest,
  type SidekickResponse,
} from './types'

export interface ClientOptions {
  baseUrl?: string
  sessionId: string
  fetchImpl?: typeof fetch
  /** Abort a request that has not answered within this many milliseconds. */
  timeoutMs?: number
}

export interface InterpretHandlers {
  /** Called for every streamed progress event, in order. */
  onEvent?: (event: ProgressEvent) => void
  /** Called once the final response arrives. */
  onResponse?: (response: SidekickResponse) => void
}

export interface InterpretResult {
  response: SidekickResponse
  events: ProgressEvent[]
}

const DEFAULT_TIMEOUT_MS = 30_000

function isJsonResponse(contentType: string | null): boolean {
  return !!contentType && contentType.includes('application/json')
}

function isEventStream(contentType: string | null): boolean {
  return !!contentType && contentType.includes('text/event-stream')
}

/** Parse one SSE frame ("event:"/"data:" lines) into a progress event. */
export function parseSseFrame(frame: string): ProgressEvent | null {
  const dataLines: string[] = []
  for (const rawLine of frame.split(/\r?\n/)) {
    if (rawLine.startsWith(':')) continue
    if (rawLine.startsWith('data:')) {
      dataLines.push(rawLine.slice(5).replace(/^ /, ''))
    }
  }
  if (dataLines.length === 0) return null
  const payload = dataLines.join('\n')
  if (payload === '[DONE]') return null
  try {
    const parsed: unknown = JSON.parse(payload)
    if (parsed && typeof parsed === 'object') return parsed as ProgressEvent
    return null
  } catch {
    // A non-JSON data frame is surfaced as a plain message so the UI still
    // shows that *something* happened rather than silently dropping it.
    return { message: payload }
  }
}

/**
 * Thin, contract-faithful client for the Sidekick backend.
 *
 * It never invents a successful outcome: a transport failure, a timeout or a
 * malformed body all surface as `SidekickApiError`.
 */
export class SidekickClient {
  private readonly baseUrl: string
  private readonly sessionId: string
  private readonly fetchImpl: typeof fetch
  private readonly timeoutMs: number

  constructor(options: ClientOptions) {
    this.baseUrl = (options.baseUrl ?? API_BASE).replace(/\/$/, '')
    this.sessionId = options.sessionId
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis)
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  }

  private url(path: string): string {
    return `${this.baseUrl}${path}`
  }

  private headers(extra?: Record<string, string>): Record<string, string> {
    return {
      'content-type': 'application/json',
      accept: 'application/json, text/event-stream',
      // Session identity precedence: header wins over the body field.
      [SESSION_HEADER]: this.sessionId,
      ...extra,
    }
  }

  /**
   * Stream the events of one action.
   *
   * `afterSeq` resumes a stream that was interrupted, using the contract's
   * `?after=<seq>` parameter. Every later event is delivered, with no
   * duplicates and no gaps.
   */
  async actionEvents(
    actionId: string,
    afterSeq: number | null,
    handlers: { onEvent?: (event: ProgressEvent) => void },
    signal?: AbortSignal,
  ): Promise<ProgressEvent[]> {
    const path = ENDPOINTS.actionEvents(actionId, afterSeq)
    const response = await this.request(path, { method: 'GET', signal })
    const contentType = response.headers.get('content-type')

    if (!isEventStream(contentType) || !response.body) {
      throw new SidekickApiError({
        code: 'contract_violation',
        message: 'The action event endpoint did not return an event stream.',
        status: response.status,
      })
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    const events: ProgressEvent[] = []
    let buffer = ''

    const flushFrame = (frame: string) => {
      const trimmed = frame.trim()
      if (!trimmed) return
      const event = parseSseFrame(trimmed)
      if (!event) return
      events.push(event)
      handlers.onEvent?.(event)
    }

    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let boundary = buffer.indexOf('\n\n')
        while (boundary !== -1) {
          flushFrame(buffer.slice(0, boundary))
          buffer = buffer.slice(boundary + 2)
          boundary = buffer.indexOf('\n\n')
        }
      }
      buffer += decoder.decode()
      flushFrame(buffer)
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        throw new SidekickApiError({
          code: 'timeout',
          message: 'The event stream was aborted.',
          timeout: true,
        })
      }
      throw cause
    }

    return events
  }

  /**
   * Approve or refuse a pending action.
   *
   * The confirmation binds to the exact action: the `plan_hash` that came with
   * it is sent back, and the API rejects the approval with `409 conflict` when
   * the plan changed in the meantime.
   *
   * The body carries `session_id` because that is where the backend looks the
   * action up - the header is not consulted by these endpoints.
   */
  async approveAction(
    actionId: string,
    sessionId: string,
    planHash: string | null,
    approved: boolean,
    signal?: AbortSignal,
  ): Promise<ActionEnvelope> {
    const body: Record<string, unknown> = { session_id: sessionId, approved }
    if (planHash) body.plan_hash = planHash
    const response = await this.request(ENDPOINTS.approve(actionId), {
      method: 'POST',
      body: JSON.stringify(body),
      signal,
    })
    return this.readActionEnvelope(response)
  }

  /** Cancel a pending or running action. */
  async cancelAction(
    actionId: string,
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<ActionEnvelope> {
    const response = await this.request(ENDPOINTS.cancel(actionId), {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
      signal,
    })
    return this.readActionEnvelope(response)
  }

  /** Report the outcome of a client-executed capability. */
  async completeAction(
    actionId: string,
    sessionId: string,
    status: 'succeeded' | 'failed' | 'cancelled',
    result?: Record<string, unknown> | null,
    error?: { code?: string; message?: string; retryable?: boolean; details?: unknown } | null,
    signal?: AbortSignal,
  ): Promise<ActionEnvelope> {
    const body: Record<string, unknown> = {
      session_id: sessionId,
      status,
      result: result ?? {},
    }
    if (error) body.error = error
    const response = await this.request(ENDPOINTS.complete(actionId), {
      method: 'POST',
      body: JSON.stringify(body),
      signal,
    })
    return this.readActionEnvelope(response)
  }

  /** Re-read one action and its events - used to refresh after a change. */
  async actionState(
    actionId: string,
    sessionId: string,
    signal?: AbortSignal,
  ): Promise<ActionEnvelope> {
    const path = `${ENDPOINTS.action(actionId)}?session_id=${encodeURIComponent(sessionId)}`
    const response = await this.request(path, { method: 'GET', signal })
    return this.readActionEnvelope(response)
  }

  private async readActionEnvelope(response: Response): Promise<ActionEnvelope> {
    const payload = (await response.json()) as Partial<ActionEnvelope>
    if (!payload || typeof payload !== 'object' || !payload.action) {
      throw new SidekickApiError({
        code: 'contract_violation',
        message: 'The action endpoint did not return an action.',
        status: response.status,
      })
    }
    return { action: payload.action, events: payload.events ?? [] }
  }

  /** GET /capabilities - the honest live/simulated/unavailable inventory. */
  async capabilities(signal?: AbortSignal): Promise<CapabilitiesResponse> {
    const response = await this.request(ENDPOINTS.capabilities, { method: 'GET', signal })
    const body = (await response.json()) as CapabilitiesResponse
    if (!body || !Array.isArray(body.capabilities)) {
      throw new SidekickApiError({
        code: 'contract_violation',
        message: 'Capabilities response did not match the Sidekick contract.',
        status: response.status,
      })
    }
    return body
  }

  /**
   * POST a request. Handles both a single JSON response and an SSE stream of
   * progress events terminated by the final response.
   */
  async interpret(
    request: SidekickRequest,
    handlers: InterpretHandlers = {},
    signal?: AbortSignal,
  ): Promise<InterpretResult> {
    const response = await this.request(ENDPOINTS.interpret, {
      method: 'POST',
      body: JSON.stringify(request),
      signal,
    })

    const contentType = response.headers.get('content-type')

    if (isEventStream(contentType) && response.body) {
      return this.readEventStream(response, handlers)
    }

    if (!isJsonResponse(contentType)) {
      const text = await response.text().catch(() => '')
      throw new SidekickApiError({
        code: 'contract_violation',
        message: `Unexpected content type "${contentType ?? 'unknown'}" from the backend.`,
        status: response.status,
        details: text.slice(0, 200),
      })
    }

    const body = (await response.json()) as SidekickResponse
    if (!body || typeof body !== 'object' || !Array.isArray(body.action_plan)) {
      throw new SidekickApiError({
        code: 'contract_violation',
        message: 'Response body did not match the Sidekick contract.',
        status: response.status,
      })
    }

    const events = Array.isArray(body.events) ? body.events : []
    for (const event of events) handlers.onEvent?.(event)
    handlers.onResponse?.(body)
    return { response: body, events }
  }

  private async readEventStream(
    response: Response,
    handlers: InterpretHandlers,
  ): Promise<InterpretResult> {
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    const events: ProgressEvent[] = []
    let buffer = ''
    let finalResponse: SidekickResponse | null = null

    const flushFrame = (frame: string) => {
      const trimmed = frame.trim()
      if (!trimmed) return
      const event = parseSseFrame(trimmed)
      if (!event) return
      // A frame that carries the full response terminates the stream.
      if (isSidekickResponse(event)) {
        finalResponse = event
        return
      }
      events.push(event)
      handlers.onEvent?.(event)
    }

    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let boundary = buffer.indexOf('\n\n')
        while (boundary !== -1) {
          flushFrame(buffer.slice(0, boundary))
          buffer = buffer.slice(boundary + 2)
          boundary = buffer.indexOf('\n\n')
        }
      }
      buffer += decoder.decode()
      flushFrame(buffer)
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        throw new SidekickApiError({ code: 'timeout', message: 'The request was aborted.', timeout: true })
      }
      throw cause
    }

    if (!finalResponse) {
      throw new SidekickApiError({
        code: 'contract_violation',
        message: 'The event stream ended without a final response.',
        status: response.status,
      })
    }

    handlers.onResponse?.(finalResponse)
    return { response: finalResponse, events }
  }

  /** Perform the HTTP call with timeout + error normalisation. */
  private async request(path: string, init: RequestInit): Promise<Response> {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort('timeout'), this.timeoutMs)
    const external = init.signal
    const onAbort = () => controller.abort('external')
    external?.addEventListener('abort', onAbort)

    let response: Response
    try {
      response = await this.fetchImpl(this.url(path), {
        ...init,
        headers: this.headers(init.headers as Record<string, string> | undefined),
        signal: controller.signal,
      })
    } catch (cause) {
      clearTimeout(timeout)
      external?.removeEventListener('abort', onAbort)
      if (controller.signal.aborted) {
        throw new SidekickApiError({
          code: 'timeout',
          message: 'The backend did not respond in time.',
          retryable: true,
          timeout: true,
        })
      }
      throw new SidekickApiError({
        code: 'network_unreachable',
        message: cause instanceof Error ? cause.message : 'Network request failed.',
        retryable: true,
      })
    }

    clearTimeout(timeout)
    external?.removeEventListener('abort', onAbort)

    if (!response.ok) {
      const payload = await response
        .clone()
        .json()
        .catch(() => null)
      const contractError = (payload as { error?: { code?: string; message?: string } } | null)?.error
      throw new SidekickApiError({
        code: contractError?.code ?? `http_${response.status}`,
        message: contractError?.message ?? `Backend responded with HTTP ${response.status}.`,
        retryable: response.status >= 500 || response.status === 429,
        status: response.status,
        details: payload ?? null,
      })
    }

    return response
  }
}

export function isSidekickResponse(value: unknown): value is SidekickResponse {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<SidekickResponse>
  return (
    typeof candidate.request_id === 'string' &&
    Array.isArray(candidate.action_plan) &&
    typeof candidate.status === 'string'
  )
}
