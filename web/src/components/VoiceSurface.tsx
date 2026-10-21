import { useEffect, useMemo, useRef } from 'react'
import type { ActionRecord, RequestRecord } from '@/state/useSidekick'
import { Companion, type CompanionState } from './Companion'
import { ActionCard } from './ActionCard'
import { Composer } from './Composer'
import { AlertIcon, MicIcon, StopIcon } from './icons'

/**
 * Interface A - the conversational surface.
 *
 * The shape is deliberately simple, like a voice assistant: one large
 * companion, the exchange underneath, one input. Everything technical lives in
 * the developer view.
 */

export interface VoiceSurfaceProps {
  requests: RequestRecord[]
  liveEvents: Array<{ seq?: number; message?: string; type?: string; kind?: string }>
  phase: string
  voice: Parameters<typeof Composer>[0]['voice']
  speaking: boolean
  speechNotice: string | null
  speechEnabled: boolean
  busy: boolean
  connection: 'checking' | 'connected' | 'disconnected'
  connectionError: string | null
  busyActions: string[]
  actionErrors: Record<string, string>
  onSubmit: (text: string, source: 'voice' | 'text') => void
  onToggleSpeech: (next: boolean) => void
  onInterrupt: () => void
  onCancel: () => void
  onRetry: () => void
  onChooseOption: (option: string) => void
  onApprove: (record: ActionRecord) => void
  onCancelAction: (record: ActionRecord) => void
}

export function VoiceSurface(props: VoiceSurfaceProps) {
  const {
    requests,
    liveEvents,
    phase,
    voice,
    speaking,
    speechNotice,
    speechEnabled,
    busy,
    connection,
    connectionError,
    busyActions,
    actionErrors,
    onSubmit,
    onToggleSpeech,
    onInterrupt,
    onCancel,
    onRetry,
    onChooseOption,
    onApprove,
    onCancelAction,
  } = props

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const latest = requests[requests.length - 1] ?? null
  const previous = requests.length > 1 ? requests[requests.length - 2] : null

  useEffect(() => {
    const node = scrollRef.current
    if (!node) return
    node.scrollTo({ top: node.scrollHeight, behavior: 'smooth' })
  }, [requests.length, liveEvents.length])

  const companionState: CompanionState = useMemo(() => {
    if (speaking) return 'speaking'
    if (voice.status === 'listening') return 'listening'
    if (phase === 'thinking') return 'thinking'
    if (phase === 'executing') return 'acting'
    if (phase === 'awaiting_confirmation') return 'waiting'
    if (phase === 'error') return 'error'
    return 'idle'
  }, [phase, speaking, voice.status])

  const statusLine = useMemo(() => {
    if (connection === 'disconnected') return 'I cannot reach the backend right now.'
    if (voice.status === 'listening') return 'I am listening.'
    if (phase === 'thinking') return 'Working out what you meant.'
    if (phase === 'executing') return 'On it.'
    if (phase === 'awaiting_confirmation') return 'I need your OK before I continue.'
    if (speaking) return 'Here is what I found.'
    if (phase === 'error') return 'That did not work.'
    return 'Ask me anything, or say "Turn on Movie Buddy".'
  }, [connection, phase, speaking, voice.status])

  return (
    <div className="voice-surface">
      <div className="voice-surface__stage">
        <div className="voice-surface__orb">
          <Companion state={companionState} size={264} />
          <p className="voice-surface__status" role="status">
            {statusLine}
          </p>
          {voice.status === 'listening' ? (
            <p className="voice-surface__heard">
              {voice.interim || voice.final ? `“${voice.interim || voice.final}”` : ''}
            </p>
          ) : null}
        </div>
      </div>

      <div className="voice-surface__exchange" ref={scrollRef}>
        {requests.length === 0 ? (
          <div className="voice-surface__intro">
            <p className="voice-surface__intro-title">Try one of these</p>
            <ul>
              {[
                'Play a song on Spotify',
                'Open YouTube and play a song - no wait, Spotify',
                'Turn on Movie Buddy',
                'What just happened?',
              ].map((suggestion) => (
                <li key={suggestion}>
                  <button
                    type="button"
                    className="voice-surface__suggestion"
                    onClick={() => onSubmit(suggestion, 'text')}
                  >
                    {suggestion}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {previous ? (
          <Exchange
            record={previous}
            busyActions={busyActions}
            actionErrors={actionErrors}
            onChooseOption={onChooseOption}
            onApprove={onApprove}
            onCancelAction={onCancelAction}
          />
        ) : null}
        {latest ? (
          <Exchange
            record={latest}
            busyActions={busyActions}
            actionErrors={actionErrors}
            onChooseOption={onChooseOption}
            onApprove={onApprove}
            onCancelAction={onCancelAction}
          />
        ) : null}

        {busy && liveEvents.length > 0 ? (
          <div className="voice-surface__live" aria-live="polite">
            {liveEvents.slice(-2).map((event, index) => (
              <p key={event.seq ?? index}>
                <span className="voice-surface__live-dot" aria-hidden="true" />
                {event.message ?? event.type ?? event.kind ?? 'update'}
              </p>
            ))}
          </div>
        ) : null}
      </div>

      {connection === 'disconnected' ? (
        <div className="voice-surface__offline" role="alert">
          <AlertIcon size={15} />
          <span>
            <strong>I cannot reach the backend.</strong> {connectionError ?? ''}
          </span>
          <button type="button" className="btn btn--sm" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : null}

      <div className="voice-surface__composer">
        <div className="voice-surface__mic">
          <button
            type="button"
            className="mic-button"
            data-mode={
              speaking ? 'speaking' : voice.status === 'listening' ? 'listening' : 'idle'
            }
            disabled={voice.status === 'unsupported' || busy}
            aria-label={
              speaking
                ? 'Stop speaking'
                : voice.status === 'listening'
                  ? 'Stop listening'
                  : voice.status === 'unsupported'
                    ? 'Voice input is not available in this browser'
                    : 'Start voice input'
            }
            title={
              speaking
                ? 'Stop speaking'
                : voice.status === 'listening'
                  ? 'Stop listening'
                  : 'Start voice input'
            }
            onClick={() => {
              if (speaking) {
                onInterrupt()
                return
              }
              if (voice.status === 'listening') voice.stop()
              else voice.start()
            }}
          >
            <span className="mic-button__pulse" aria-hidden="true" />
            <MicIcon size={24} />
          </button>
          <span className="voice-surface__mic-label">
            {voice.status === 'unsupported'
              ? 'Voice input is not available here'
              : speaking
                ? 'Speaking - press to stop'
                : voice.status === 'listening'
                  ? 'Listening - press to stop'
                  : 'Tap to speak'}
          </span>
        </div>

        <div className="voice-surface__input">
          <Composer
            voice={voice}
            busy={busy}
            speaking={speaking}
            speechNotice={speechNotice}
            speechEnabled={speechEnabled}
            showMic={false}
            onToggleSpeech={onToggleSpeech}
            onSubmit={onSubmit}
            onInterrupt={onInterrupt}
          />
          {busy ? (
            <button type="button" className="btn btn--sm btn--ghost" onClick={onCancel}>
              <StopIcon size={13} />
              Stop
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function Exchange({
  record,
  busyActions,
  actionErrors,
  onChooseOption,
  onApprove,
  onCancelAction,
}: {
  record: RequestRecord
  busyActions: string[]
  actionErrors: Record<string, string>
  onChooseOption: (option: string) => void
  onApprove: (record: ActionRecord) => void
  onCancelAction: (record: ActionRecord) => void
}) {
  if (record.error) {
    return (
      <div className="exchange exchange--error">
        <p className="exchange__said">
          {record.error.code === 'network_unreachable'
            ? 'I could not reach the backend, so nothing happened.'
            : 'That did not work.'}
        </p>
        <p className="exchange__meta">
          {record.error.retryable ? 'You can ask me again.' : 'Try asking for it a different way.'}
        </p>
      </div>
    )
  }

  const response = record.response
  if (!response) {
    return (
      <div className="exchange exchange--pending">
        <p className="exchange__said">Working on it…</p>
      </div>
    )
  }

  // Only the actions this request is responsible for. Actions the backend
  // carried over from an earlier turn are deliberately not shown here.
  const actions = record.actions

  return (
    <div className="exchange">
      <p className="exchange__you">{record.utterance}</p>

      {response.clarification ? (
        <div className="exchange__ask">
          <p className="exchange__said">{response.clarification.question}</p>
          <div className="exchange__options">
            {response.clarification.options.map((option) => (
              <button
                type="button"
                key={option}
                className="btn btn--sm"
                onClick={() => onChooseOption(option)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {actions.length > 0 ? (
        <div className="exchange__cards">
          {actions.map((entry) => (
            <ActionCard
              key={entry.action.action_id}
              record={entry}
              busy={busyActions.includes(entry.action.action_id)}
              error={actionErrors[entry.action.action_id]}
              onApprove={onApprove}
              onCancel={onCancelAction}
            />
          ))}
        </div>
      ) : null}

      {response.speech ? <p className="exchange__said">{response.speech}</p> : null}
    </div>
  )
}
