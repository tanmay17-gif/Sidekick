import { useEffect, useMemo, useRef } from 'react'
import type { Action } from '@/lib/api/types'
import type { RequestRecord } from '@/state/useSidekick'
import { Companion, type CompanionState } from './Companion'
import { Composer } from './Composer'
import { ActionCard } from './ActionCard'
import { MicIcon, StopIcon } from './icons'

/**
 * Interface A - the conversational surface.
 *
 * The shape is deliberately simple, like a voice assistant: one large
 * companion, the exchange underneath, one input. Everything that is not the
 * conversation lives in the control room.
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
  onSubmit: (text: string, source: 'voice' | 'text') => void
  onToggleSpeech: (next: boolean) => void
  onInterrupt: () => void
  onCancel: () => void
  onRetry: () => void
  onChooseOption: (option: string) => void
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
    onSubmit,
    onToggleSpeech,
    onInterrupt,
    onCancel,
    onRetry,
    onChooseOption,
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
    if (connection === 'disconnected') return 'The backend is not reachable.'
    if (voice.status === 'listening') return 'Listening.'
    if (phase === 'thinking') return 'Working out what you meant.'
    if (phase === 'executing') return 'Working on it.'
    if (phase === 'awaiting_confirmation') return 'Waiting for you to confirm.'
    if (speaking) return 'Speaking.'
    if (phase === 'error') return 'That did not work.'
    return 'Ask me anything, or say "Turn on Movie Buddy".'
  }, [connection, phase, speaking, voice.status])

  return (
    <div className="voice-surface">
      <div className="voice-surface__stage">
        <div className="voice-surface__orb">
          <Companion state={companionState} size={196} />
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

        {previous ? <Exchange record={previous} onChooseOption={onChooseOption} /> : null}
        {latest ? <Exchange record={latest} onChooseOption={onChooseOption} live /> : null}

        {busy && liveEvents.length > 0 ? (
          <div className="voice-surface__live" aria-live="polite">
            {liveEvents.slice(-3).map((event, index) => (
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
          <strong>The backend is not reachable.</strong> {connectionError ?? ''}
          <button type="button" className="btn btn--sm" onClick={onRetry}>
            Retry
          </button>
        </div>
      ) : null}

      <div className="voice-surface__composer">
        <Composer
          voice={voice}
          busy={busy}
          speaking={speaking}
          speechNotice={speechNotice}
          speechEnabled={speechEnabled}
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
  )
}

function Exchange({
  record,
  onChooseOption,
  live,
}: {
  record: RequestRecord
  onChooseOption: (option: string) => void
  live?: boolean
}) {
  if (record.error) {
    return (
      <div className="exchange exchange--error">
        <p className="exchange__said">{record.error.message}</p>
        <p className="exchange__meta">error {record.error.code}</p>
      </div>
    )
  }

  const response = record.response
  if (!response) {
    return (
      <div className="exchange exchange--pending">
        <p className="exchange__said">Working on it...</p>
      </div>
    )
  }

  const actions = response.action_plan

  return (
    <div className={`exchange${live ? ' exchange--live' : ''}`}>
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
          {actions.map((action: Action) => (
            <ActionCard key={action.action_id} action={action} />
          ))}
        </div>
      ) : null}

      {response.speech ? <p className="exchange__said">{response.speech}</p> : null}
    </div>
  )
}

export { MicIcon }
