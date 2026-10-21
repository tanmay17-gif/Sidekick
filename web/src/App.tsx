import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { SidekickClient } from '@/lib/api/client'
import { containsActivation, parseBuddyCommand } from '@/lib/movie/commands'
import { NOOP_BUDDY_CONTROLLER, type BuddyController } from '@/lib/movie/controller'
import { useVoiceInput } from '@/lib/voice/useVoiceInput'
import { Speaker } from '@/lib/voice/synthesis'
import { useSidekick, type RequestRecord } from '@/state/useSidekick'
import { ControlRoom } from './components/ControlRoom'
import { MovieBuddy } from './components/MovieBuddy'
import { SidekickMark } from './components/icons'
import { VoiceSurface } from './components/VoiceSurface'
import type { Action } from '@/lib/api/types'

/**
 * Sidekick has two interfaces and one session.
 *
 * Interface A (Ask / Movie Buddy) is the conversational surface a person talks
 * to. Interface B (Control room) is the developer view of the same work. Both
 * read the same request list, the same session id and the same event stream -
 * they are two views of one real session, not two demos.
 */

type View = 'ask' | 'movie' | 'control'

export function App() {
  const sidekick = useSidekick()
  const speaker = useMemo(() => new Speaker(), [])
  const [view, setView] = useState<View>('ask')
  const [speaking, setSpeaking] = useState(false)
  const [speechNotice, setSpeechNotice] = useState<string | null>(null)
  const [buddyNote, setBuddyNote] = useState<string | null>(null)
  const [controlMessage, setControlMessage] = useState<string | null>(null)
  const buddyRef = useRef<BuddyController>(NOOP_BUDDY_CONTROLLER)
  const spokenRef = useRef<string | null>(null)

  const handleUtterance = useCallback(
    (text: string, source: 'voice' | 'text') => {
      const trimmed = text.trim()
      if (!trimmed) return

      const command = parseBuddyCommand(trimmed)
      if (!command) {
        speaker.cancel()
        void sidekick.send(trimmed, source)
        return
      }

      const controller = buddyRef.current

      switch (command.kind) {
        case 'activate':
          setView('movie')
          controller.activate()
          setBuddyNote('Movie Buddy is on.')
          return
        case 'deactivate':
          controller.deactivate()
          setBuddyNote('Movie Buddy is off.')
          return
        case 'resume-buddy':
          setView('movie')
          controller.resume()
          setBuddyNote('Movie Buddy is back.')
          return
        case 'quiet':
          setView('movie')
          controller.quiet()
          setBuddyNote('Sidekick will stay quiet for a minute.')
          return
        case 'what-happened':
          setView('movie')
          controller.askWhatHappened()
          return
        case 'explain':
          setView('movie')
          controller.askExplain()
          return
        case 'pause':
          setView('movie')
          controller.pause()
          setBuddyNote('Paused.')
          return
        case 'resume-playback':
          setView('movie')
          controller.togglePlay()
          return
        case 'seek-back':
          setView('movie')
          controller.seekBack(command.seconds ?? 30)
          setBuddyNote(`Back ${command.seconds ?? 30} seconds.`)
          return
        case 'seek-forward':
          setView('movie')
          controller.seekBack(-(command.seconds ?? 30))
          return
        case 'play-a-movie': {
          const remainder = command.remainder.replace(/,?\s*and\s+turn on movie buddy/i, '')
          setView('movie')
          buddyRef.current.activate()
          if (remainder.trim().length > 0) void sidekick.send(remainder.trim(), source)
          return
        }
        default:
          break
      }

      if (containsActivation(trimmed)) {
        setView('movie')
        buddyRef.current.activate()
      }
      void sidekick.send(trimmed, source)
    },
    [sidekick, speaker],
  )

  const voice = useVoiceInput({
    onFinal: (transcript) => {
      handleUtterance(transcript, 'voice')
    },
  })

  // Speak the newest assistant response once, when speech output is enabled.
  useEffect(() => {
    if (!sidekick.speakEnabled) return
    const record = sidekick.requests[sidekick.requests.length - 1]
    if (!record || record.status !== 'answered' || !record.response) return
    const text = summariseResponse(record.response)
    if (!text || spokenRef.current === record.request_id) return
    spokenRef.current = record.request_id
    void speaker.speak(text, {
      onStart: () => setSpeaking(true),
      onEnd: () => setSpeaking(false),
      onError: (message) => {
        setSpeaking(false)
        setSpeechNotice(message)
      },
    })
  }, [sidekick.requests, sidekick.speakEnabled, speaker])

  const interrupt = useCallback(() => {
    speaker.cancel()
    setSpeaking(false)
    sidekick.cancel()
  }, [sidekick, speaker])

  const busy = sidekick.phase === 'thinking' || sidekick.phase === 'executing'

  const approve = useCallback(
    async (action: Action, approved: boolean) => {
      setControlMessage(null)
      try {
        const client = new SidekickClient({ sessionId: sidekick.sessionId })
        await client.approveAction(action.action_id, action.plan_hash ?? null, approved)
        await sidekick.refreshCapabilities()
      } catch (cause) {
        setControlMessage(
          cause instanceof Error ? cause.message : 'The approval could not be sent.',
        )
      }
    },
    [sidekick],
  )

  const cancelAction = useCallback(
    async (action: Action) => {
      setControlMessage(null)
      try {
        const client = new SidekickClient({ sessionId: sidekick.sessionId })
        await client.cancelAction(action.action_id)
      } catch (cause) {
        setControlMessage(
          cause instanceof Error ? cause.message : 'The cancellation could not be sent.',
        )
      }
    },
    [sidekick.sessionId],
  )

  return (
    <div className="app" data-view={view}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <header className="app__bar">
        <div className="app__brand">
          <span className="brand__mark">
            <SidekickMark size={18} />
          </span>
          <span>
            <span className="brand__name">Sidekick</span>
          </span>
        </div>

        <nav className="app__views" aria-label="Interfaces">
          <button
            type="button"
            className="app__view"
            aria-current={view === 'ask' ? 'page' : undefined}
            onClick={() => setView('ask')}
          >
            Ask Sidekick
          </button>
          <button
            type="button"
            className="app__view"
            aria-current={view === 'movie' ? 'page' : undefined}
            onClick={() => setView('movie')}
          >
            Movie Buddy
          </button>
          <span className="app__divider" aria-hidden="true" />
          <button
            type="button"
            className="app__view app__view--tech"
            aria-current={view === 'control' ? 'page' : undefined}
            onClick={() => setView('control')}
          >
            Control room
          </button>
        </nav>

        <div className="app__status">
          <span className={`badge badge--${sidekick.connection === 'connected' ? 'live' : 'danger'}`}>
            {sidekick.connection === 'connected'
              ? sidekick.capabilities?.mode === 'stub'
                ? 'dev stub'
                : 'backend live'
              : 'offline'}
          </span>
          <span className="app__session" title={sidekick.sessionId}>
            {sidekick.sessionId.slice(0, 8)}
          </span>
          <button
            type="button"
            className="btn btn--sm btn--ghost"
            onClick={sidekick.resetSession}
            title="Start a new session"
          >
            New session
          </button>
        </div>
      </header>

      <main className="app__main" id="main-content">
        {view === 'ask' ? (
          <VoiceSurface
            requests={sidekick.requests}
            liveEvents={sidekick.liveEvents}
            phase={sidekick.phase}
            voice={voice}
            speaking={speaking}
            speechNotice={speechNotice}
            speechEnabled={sidekick.speakEnabled}
            busy={busy}
            connection={sidekick.connection}
            connectionError={sidekick.capabilityError}
            onSubmit={handleUtterance}
            onToggleSpeech={sidekick.setSpeakEnabled}
            onInterrupt={interrupt}
            onCancel={sidekick.cancel}
            onRetry={() => void sidekick.refreshCapabilities()}
            onChooseOption={(option) => handleUtterance(option, 'text')}
          />
        ) : null}

        {view === 'movie' ? (
          <div className="app__movie">
            <MovieBuddy
              speaker={speaker}
              speechEnabled={sidekick.speakEnabled}
              startActive
              controllerRef={buddyRef}
              onSay={(text) => setBuddyNote(text)}
            />
            {buddyNote ? (
              <p className="app__note" role="status">
                {buddyNote}
              </p>
            ) : null}
          </div>
        ) : null}

        {view === 'control' ? (
          <ControlRoom
            sessionId={sidekick.sessionId}
            requests={sidekick.requests}
            liveEvents={sidekick.liveEvents}
            followedAction={sidekick.followedAction}
            capabilities={sidekick.capabilities}
            connection={sidekick.connection}
            connectionError={sidekick.capabilityError}
            voiceUnavailable={voice.status === 'unsupported'}
            onRefresh={() => void sidekick.refreshCapabilities()}
            onApprove={approve}
            onCancelAction={cancelAction}
          />
        ) : null}
      </main>

      {controlMessage ? (
        <p className="app__error" role="alert">
          {controlMessage}
        </p>
      ) : null}
    </div>
  )
}

/** Short spoken summary built from the real backend result. */
export function summariseResponse(response: {
  speech?: string | null
  clarification: { question: string } | null
  action_plan: Array<{ tool: string; state: string; error?: { message: string } | null }>
}): string {
  if (response.speech) return response.speech
  if (response.clarification) return response.clarification.question

  const failed = response.action_plan.find((action) => action.state === 'failed')
  if (failed) {
    return failed.error
      ? `${failed.tool} failed: ${failed.error.message}`
      : `${failed.tool} failed.`
  }

  const waiting = response.action_plan.find((action) => action.state === 'awaiting_confirmation')
  if (waiting) return `${waiting.tool} needs your confirmation before it runs.`

  const done = response.action_plan.find((action) => action.state === 'succeeded')
  if (done) return `${done.tool} completed.`

  if (response.action_plan.length === 0) return 'I did not find an action to take.'

  return `Working on ${response.action_plan.map((action) => action.tool).join(', ')}.`
}

export type { RequestRecord }
