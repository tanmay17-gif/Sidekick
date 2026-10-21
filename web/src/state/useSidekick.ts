import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { SidekickClient } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { describeApiError, SidekickApiError } from '@/lib/api/errors'
import type {
  Action,
  ActionState,
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
 * The state the interface shows for an action.
 *
 * `timed_out` is not a separate state in the contract - it is a failure whose
 * error says it timed out. Deriving it here keeps the distinction the product
 * needs without inventing a backend state.
 */
export type ActionViewState =
  | 'pending'
  | 'awaiting_confirmation'
  | 'running'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'timed_out'
  | 'cancelled'
  | 'superseded'
  | 'unknown'

export function deriveActionState(action: Action): ActionViewState {
  if (action.state === 'failed' && action.error?.timeout) return 'timed_out'
  if (action.state === 'failed') return 'failed'
  return action.state as ActionViewState
}

/**
 * One action, and where it came from.
 *
 * The contract's `Action` has no request id, so the client records which
 * request produced each action. An action that the backend carried over from
 * an earlier turn of the same session is flagged `inherited` and is never
 * presented as part of the current request.
 */
export interface ActionRecord {
  action: Action
  request_id: string
  session_id: string
  /** True when this action was produced by an earlier request. */
  inherited: boolean
  state: ActionViewState
}

/** One request as the whole product sees it. */
export interface RequestRecord {
  request_id: string
  session_id: string
  utterance: string
  input_source: 'voice' | 'text'
  started_at: string
  finished_at: string | null
  status: 'in_flight' | 'answered' | 'failed'
  response: SidekickResponse | null
  /** The actions this request is responsible for, in plan order. */
  actions: ActionRecord[]
  /** Actions the backend carried over from an earlier turn. */
  inheritedActions: ActionRecord[]
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
export function liveActionOf(record: RequestRecord | null): ActionRecord | null {
  if (!record) return null
  const moving = record.actions.find(
    (entry) => entry.state === 'running' || entry.state === 'pending',
  )
  return moving ?? null
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
  /** Actions with an approval or cancellation in flight. */
  const [busyActions, setBusyActions] = useState<string[]>([])
  /** A friendly, user-facing failure per action. */
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({})

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
  /** action_id -> the request that produced it. */
  const actionOwnerRef = useRef<Map<string, string>>(new Map())

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

  /** Split a plan into the actions this request owns and the ones it inherited. */
  const attributeActions = useCallback(
    (response: SidekickResponse, requestId: string, session: string) => {
      const owned: ActionRecord[] = []
      const inherited: ActionRecord[] = []
      for (const action of response.action_plan ?? []) {
        const owner = actionOwnerRef.current.get(action.action_id)
        const isInherited = owner !== undefined && owner !== requestId
        if (!isInherited) actionOwnerRef.current.set(action.action_id, requestId)
        const record: ActionRecord = {
          action,
          request_id: isInherited ? owner : requestId,
          session_id: session,
          inherited: isInherited,
          state: deriveActionState(action),
        }
        if (isInherited) inherited.push(record)
        else owned.push(record)
      }
      return { owned, inherited }
    },
    [],
  )

  /** Replace one action everywhere it appears, keeping its ownership. */
  const replaceAction = useCallback((action: Action) => {
    setRequests((existing) =>
      existing.map((record) => {
        const patch = (entry: ActionRecord): ActionRecord =>
          entry.action.action_id === action.action_id
            ? { ...entry, action, state: deriveActionState(action) }
            : entry
        return {
          ...record,
          actions: record.actions.map(patch),
          inheritedActions: record.inheritedActions.map(patch),
        }
      }),
    )
  }, [])

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
        actions: [],
        inheritedActions: [],
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
        const { owned, inherited } = attributeActions(response, requestId, sessionId)
        setRequests((existing) =>
          existing.map((entry) =>
            entry.request_id === requestId
              ? {
                  ...entry,
                  status: 'answered',
                  response,
                  actions: owned,
                  inheritedActions: inherited,
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
    [attributeActions, client, sessionId],
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
    setPhase('idle')
    setActionErrors({})
    setBusyActions([])
    setFollowedAction(null)
    actionOwnerRef.current = new Map()
    lastResponseRef.current = null
    void refreshCapabilities()
  }, [cancel, options.baseUrl, options.fetchImpl, refreshCapabilities])

  /* ---------------------------------------------------------------- *
   * Approval and cancellation.
   *
   * The action is re-read after the call, so the interface always shows the
   * state the backend reports - never an optimistic guess.
   * ---------------------------------------------------------------- */
  const approve = useCallback(
    async (actionId: string, planHash: string | null, approved: boolean) => {
      if (busyActions.includes(actionId)) return null
      setBusyActions((current) => [...current, actionId])
      setActionErrors((current) => {
        const next = { ...current }
        delete next[actionId]
        return next
      })
      try {
        const envelope = await client.approveAction(
          actionId,
          sessionId,
          planHash,
          approved,
        )
        replaceAction(envelope.action)
        // Re-read the action so the shown state is the backend's, not ours.
        try {
          const fresh = await client.actionState(actionId, sessionId)
          replaceAction(fresh.action)
        } catch {
          /* the envelope already carries the authoritative action */
        }
        return envelope.action
      } catch (cause) {
        const message = describeApiError(cause)
        setActionErrors((current) => ({ ...current, [actionId]: message }))
        return null
      } finally {
        setBusyActions((current) => current.filter((id) => id !== actionId))
      }
    },
    [busyActions, client, replaceAction, sessionId],
  )

  const cancelAction = useCallback(
    async (actionId: string) => {
      if (busyActions.includes(actionId)) return null
      setBusyActions((current) => [...current, actionId])
      setActionErrors((current) => {
        const next = { ...current }
        delete next[actionId]
        return next
      })
      try {
        const envelope = await client.cancelAction(actionId, sessionId)
        replaceAction(envelope.action)
        try {
          const fresh = await client.actionState(actionId, sessionId)
          replaceAction(fresh.action)
        } catch {
          /* the envelope already carries the authoritative action */
        }
        return envelope.action
      } catch (cause) {
        const message = describeApiError(cause)
        setActionErrors((current) => ({ ...current, [actionId]: message }))
        return null
      } finally {
        setBusyActions((current) => current.filter((id) => id !== actionId))
      }
    },
    [busyActions, client, replaceAction, sessionId],
  )

  /** Re-read one action - used after a reconnect or a manual refresh. */
  const refreshAction = useCallback(
    async (actionId: string) => {
      try {
        const fresh = await client.actionState(actionId, sessionId)
        replaceAction(fresh.action)
        return fresh.action
      } catch (cause) {
        const message = describeApiError(cause)
        setActionErrors((current) => ({ ...current, [actionId]: message }))
        return null
      }
    },
    [client, replaceAction, sessionId],
  )

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
    setFollowedAction(actionToFollow.action.action_id)

    let cancelled = false
    let controller: AbortController | null = null
    let lastSeq = 0
    let attempt = 0

    const run = async () => {
      while (!cancelled) {
        controller = new AbortController()
        try {
          const events = await client.actionEvents(
            actionToFollow.action.action_id,
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
            // The stream may have carried the action's final state.
            if (events.some((event) => event.status === 'succeeded' || event.status === 'failed')) {
              await refreshAction(actionToFollow.action.action_id)
            }
          }
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
  }, [actionToFollow, client, refreshAction, requests.length])

  const liveRequest = useMemo(() => requests[requests.length - 1] ?? null, [requests])

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
    busyActions,
    actionErrors,
    send,
    cancel,
    resetSession,
    refreshCapabilities,
    approve,
    cancelAction,
    refreshAction,
    mediaCatalogPath: ENDPOINTS.mediaCatalog,
  }
}

export type { ActionState }
