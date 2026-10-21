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

export interface Turn {
  id: string
  role: 'user' | 'assistant'
  inputSource: 'voice' | 'text'
  utterance: string
  response?: SidekickResponse
  error?: { code: string; message: string; retryable: boolean; timeout: boolean }
  events: ProgressEvent[]
  createdAt: string
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

/** The most recent assistant response contained in the turn list. */
export function latestResponse(turns: Turn[]): SidekickResponse | null {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const turn = turns[index]
    if (turn?.role === 'assistant' && turn.response) return turn.response
  }
  return null
}

export function useSidekick(options: UseSidekickOptions = {}) {
  const [sessionId, setSessionId] = useState(() => getOrCreateSessionId())
  const [turns, setTurns] = useState<Turn[]>([])
  const [phase, setPhase] = useState<Phase>('idle')
  const [connection, setConnection] = useState<ConnectionState>('checking')
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(null)
  const [capabilityError, setCapabilityError] = useState<string | null>(null)
  const [liveEvents, setLiveEvents] = useState<ProgressEvent[]>([])
  const [speakEnabled, setSpeakEnabled] = useState(true)

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
      if (!trimmed) return

      const requestId = createId()
      const userTurn: Turn = {
        id: requestId,
        role: 'user',
        inputSource,
        utterance: trimmed,
        events: [],
        createdAt: new Date().toISOString(),
      }
      setTurns((previous) => [...previous, userTurn])
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
        const assistantTurn: Turn = {
          id: response.request_id ?? requestId,
          role: 'assistant',
          inputSource,
          utterance: trimmed,
          response,
          events,
          createdAt: new Date().toISOString(),
        }
        setTurns((existing) => [...existing, assistantTurn])
        setPhase(
          response.status === 'awaiting_confirmation'
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
        const assistantTurn: Turn = {
          id: requestId,
          role: 'assistant',
          inputSource,
          utterance: trimmed,
          error,
          events: [],
          createdAt: new Date().toISOString(),
        }
        setTurns((existing) => [...existing, assistantTurn])
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
    setTurns([])
    setLiveEvents([])
    lastResponseRef.current = null
    void refreshCapabilities()
  }, [cancel, options.baseUrl, options.fetchImpl, refreshCapabilities])

  const pendingAction = useMemo(() => {
    const response = latestResponse(turns)
    if (!response) return null
    return (
      response.action_plan.find((action) =>
        ['pending', 'awaiting_confirmation', 'running', 'paused'].includes(action.state),
      ) ?? null
    )
  }, [turns])

  return {
    sessionId,
    turns,
    phase,
    connection,
    capabilities,
    capabilityError,
    liveEvents,
    speakEnabled,
    setSpeakEnabled,
    pendingAction,
    send,
    cancel,
    resetSession,
    refreshCapabilities,
    mediaCatalogPath: ENDPOINTS.mediaCatalog,
  }
}
