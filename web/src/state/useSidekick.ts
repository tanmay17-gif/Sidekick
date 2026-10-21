import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { SidekickClient } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { describeApiError, SidekickApiError } from '@/lib/api/errors'
import type {
  CapabilitiesResponse,
  ProgressEvent,
  SidekickRequest,
  SidekickResponse,
} from '@/lib/api/types'
import { createId, getOrCreateSessionId, resetSessionId } from '@/lib/session/session'

export type Phase =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'executing'
  | 'awaiting_confirmation'
  | 'speaking'
  | 'error'

export type ConnectionState = 'checking' | 'connected' | 'disconnected'

/**
 * One request as the whole product sees it.
 *
 * Both surfaces read this list, so the conversation and the control room are
 * always describing the same real work.
 */
export interface RequestRecord {
  request_id: string
  session_id: string
  utterance: string
  input_source: 'voice' | 'text'
  started_at: string
  finished_at: string | null
  status: 'in_flight' | 'answered' | 'failed'
  response: SidekickResponse | null
  events: ProgressEvent[]
  error: { code: string; message: string; retryable: boolean; timeout: boolean } | null
}

export interface UseSidekickOptions {
  baseUrl?: string
  fetchImpl?: typeof fetch
  client?: SidekickClient
}

const CORRECTION_MARKERS = [
  /\bno[, ]?wait\b/i,
  /\bactually\b/i,
  /\bsorry\b/i,
  /\bscratch that\b/i,
  /\binstead\b/i,
  /\bchange (that|it)\b/i,
  /\bnever ?mind\b/i,
]

export function looksLikeCorrection(text: string): boolean {
  return CORRECTION_MARKERS.some((marker) => marker.test(text))
}

/** The action the control room should follow: the first one still moving. */
export function liveActionOf(record: RequestRecord | null): string | null {
  if (!record) return null
  const running = record.response?.action_plan?.find(
    (action) => action.state === 'running' || action.state === 'pending',
  )
  if (running) return running.job_id ?? running.action_id
  return null
}

export function useSidekick(options: UseSidekickOptions = {}) {
  const [sessionId, setSessionId] = useState(() => getOrCreateSessionId())
  const [requests, setRequests] = useState<RequestRecord[]>([])
  const [phase, setPhase] = useState<Phase>('idle')
  const [connection, setConnection] = useState<ConnectionState>('checking')
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(null)
  const [capabilityError, setCapabilityError] = useState<string | null>(null)
  const [speakEnabled, setSpeakEnabled] = useState(true)
  /** Live events for the request that is currently in flight. */
  const [liveEvents, setLiveEvents] = useState<ProgressEvent[]>([])
  /** The action whose event stream the control room is following. */
  const [followedAction, setFollowedAction] = useState<string | null>(null)

  const clientRef = useRef<SidekickClient | null>(null)
  if (clientRef.current === null) {
    clientRef.current =
      options.client ??
      new SidekickClient({
        baseUrl: options.baseUrl,
        sessionId,
        fetchImpl: options.fetchImpl,
      })
  }
  const client = clientRef.current

  const lastResponseRef = useRef<SidekickResponse | null>(null)
  const inFlightRef = useRef<AbortController | null>(null)

  const refreshCapabilities = useCallback(async () => {
    setConnection('checking')
    try {
      const result = await client.capabilities()
      setCapabilities(result)
      setCapabilityError(null)
      setConnection('connected')
    } catch (cause) {
      setCapabilities(null)
      setCapabilityError(describeApiError(cause))
      setConnection('disconnected')
    }
  }, [client])

  useEffect(() => {
    void refreshCapabilities()
  }, [refreshCapabilities])

  const send = useCallback(
    async (utterance: string, inputSource: 'voice' | 'text') => {
      const trimmed = utterance.trim()
      if (!trimmed) return null

      const requestId = createId()
      const startedAt = new Date().toISOString()
      const record: RequestRecord = {
        request_id: requestId,
        session_id: sessionId,
        utterance: trimmed,
        input_source: inputSource,
        started_at: startedAt,
        finished_at: null,
        status: 'in_flight',
        response: null,
        events: [],
        error: null,
      }
      setRequests((previous) => [...previous, record])
      setPhase('thinking')
      setLiveEvents([])

      const previous = lastResponseRef.current
      const hasPendingAction =
        previous !== null &&
        previous.action_plan.some((action) =>
          ['pending', 'awaiting_confirmation', 'running', 'paused'].includes(action.state),
        )

      const request: SidekickRequest = {
        request_id: requestId,
        session_id: sessionId,
        utterance: trimmed,
        input_source: inputSource,
        utterance_finalized: true,
      }
      if (previous) {
        request.continuation_context = { previous_request_id: previous.request_id }
      }
      if (hasPendingAction && looksLikeCorrection(trimmed)) {
        // The backend owns correction resolution; we only surface the signal.
        request.correction_context = { signal: trimmed }
      }

      const controller = new AbortController()
      inFlightRef.current = controller

      try {
        const { response, events } = await client.interpret(
          request,
          {
            onEvent: (event) => {
              setLiveEvents((existing) => [...existing, event])
              setPhase((current) => (current === 'thinking' ? 'executing' : current))
            },
          },
          controller.signal,
        )

        lastResponseRef.current = response
        setRequests((existing) =>
          existing.map((entry) =>
            entry.request_id === requestId
              ? {
                  ...entry,
                  status: 'answered',
                  response,
                  events,
                  finished_at: new Date().toISOString(),
                }
              : entry,
          ),
        )
        setPhase(
          response.status === 'awaiting_confirmation' ||
            response.status === 'needs_clarification'
            ? 'awaiting_confirmation'
            : response.status === 'failed'
              ? 'error'
              : 'idle',
        )
        setConnection('connected')
        return response
      } catch (cause) {
        const error =
          cause instanceof SidekickApiError
            ? cause.toContractError()
            : {
                code: 'unknown',
                message: cause instanceof Error ? cause.message : 'Request failed.',
                retryable: false,
                timeout: false,
              }
        setRequests((existing) =>
          existing.map((entry) =>
            entry.request_id === requestId
              ? {
                  ...entry,
                  status: 'failed',
                  error,
                  finished_at: new Date().toISOString(),
                }
              : entry,
          ),
        )
        setPhase('error')
        if (error.code === 'network_unreachable' || error.code === 'timeout') {
          setConnection('disconnected')
        }
        return null
      } finally {
        inFlightRef.current = null
      }
    },
    [client, sessionId],
  )

  const cancel = useCallback(() => {
    inFlightRef.current?.abort()
    inFlightRef.current = null
    setPhase('idle')
  }, [])

  const resetSession = useCallback(() => {
    cancel()
    const next = resetSessionId()
    setSessionId(next)
    clientRef.current = new SidekickClient({
      baseUrl: options.baseUrl,
      sessionId: next,
      fetchImpl: options.fetchImpl,
    })
    setRequests([])
    setLiveEvents([])
    lastResponseRef.current = null
    void refreshCapabilities()
  }, [cancel, options.baseUrl, options.fetchImpl, refreshCapabilities])

  /* ---------------------------------------------------------------- *
   * The control room follows the real event stream of the running
   * action. It resumes with ?after=<seq> so a reconnect never
   * duplicates an event and never invents one.
   * ---------------------------------------------------------------- */
  const latest = requests[requests.length - 1] ?? null
  const actionToFollow = liveActionOf(latest)

  useEffect(() => {
    if (!actionToFollow) {
      setFollowedAction(null)
      return
    }
    setFollowedAction(actionToFollow)

    let cancelled = false
    let controller: AbortController | null = null
    let lastSeq = 0
    let attempt = 0

    const run = async () => {
      while (!cancelled) {
        controller = new AbortController()
        try {
          const events = await client.actionEvents(
            actionToFollow,
            lastSeq > 0 ? lastSeq : null,
            {
              onEvent: (event) => {
                if (cancelled) return
                if (typeof event.seq === 'number') {
                  if (event.seq <= lastSeq) return // never duplicate
                  lastSeq = event.seq
                }
                setLiveEvents((existing) => [...existing, event])
              },
            },
            controller.signal,
          )
          if (events.length > 0) {
            attempt = 0
          }
          // A finished stream stays open for the next request to follow.
          break
        } catch {
          attempt += 1
          if (cancelled || attempt > 3) break
          await new Promise((resolve) => setTimeout(resolve, 800 * attempt))
        }
      }
    }

    void run()
    return () => {
      cancelled = true
      controller?.abort()
    }
  }, [actionToFollow, client, requests.length])

  const liveRequest = useMemo(
    () => requests[requests.length - 1] ?? null,
    [requests],
  )

  return {
    sessionId,
    requests,
    liveRequest,
    liveEvents,
    followedAction,
    phase,
    connection,
    capabilities,
    capabilityError,
    speakEnabled,
    setSpeakEnabled,
    send,
    cancel,
    resetSession,
    refreshCapabilities,
    mediaCatalogPath: ENDPOINTS.mediaCatalog,
  }
}
