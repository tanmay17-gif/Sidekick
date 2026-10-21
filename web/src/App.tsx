import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useVoiceInput } from '@/lib/voice/useVoiceInput'
import { Speaker } from '@/lib/voice/synthesis'
import { parseBuddyCommand, containsActivation } from '@/lib/movie/commands'
import { NOOP_BUDDY_CONTROLLER, type BuddyController } from '@/lib/movie/controller'
import { useSidekick, type Phase } from '@/state/useSidekick'
import { CapabilityBar } from './components/CapabilityBar'
import { Companion, type CompanionState } from './components/Companion'
import { Composer } from './components/Composer'
import { Conversation } from './components/Conversation'
import { DecisionTrace } from './components/DecisionTrace'
import { GamesPanel } from './components/GamesPanel'
import { MovieBuddy } from './components/MovieBuddy'
import { MusicPanel } from './components/MusicPanel'
import { ChatIcon, FilmIcon, GameIcon, MusicIcon, RefreshIcon, SidekickMark } from './components/icons'
import { EmptyState, Notice } from './components/ui'

type Surface = 'talk' | 'movie' | 'music' | 'games'

const SURFACES: Array<{ id: Surface; label: string; icon: typeof ChatIcon }> = [
  { id: 'talk', label: 'Talk', icon: ChatIcon },
  { id: 'movie', label: 'Movie Buddy', icon: FilmIcon },
  { id: 'music', label: 'Music', icon: MusicIcon },
  { id: 'games', label: 'Games', icon: GameIcon },
]

export function App() {
  const sidekick = useSidekick()
  const speaker = useMemo(() => new Speaker(), [])
  const [surface, setSurface] = useState<Surface>('talk')
  const [speaking, setSpeaking] = useState(false)
  const [speechNotice, setSpeechNotice] = useState<string | null>(null)
  const [buddyActivateToken, setBuddyActivateToken] = useState(0)
  const [buddyNote, setBuddyNote] = useState<string | null>(null)
  const [buddySaid, setBuddySaid] = useState<string | null>(null)
  const buddyRef = useRef<BuddyController>(NOOP_BUDDY_CONTROLLER)

  const spokenRef = useRef<string | null>(null)

  const lastResponse = useMemo(() => {
    for (let index = sidekick.turns.length - 1; index >= 0; index -= 1) {
      const turn = sidekick.turns[index]
      if (turn?.role === 'assistant' && turn.response) return turn.response
    }
    return null
  }, [sidekick.turns])

  /**
   * Route an utterance. Movie Buddy commands are interface commands and are
   * answered by the player; everything else goes to the decision engine.
   */
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
          setSurface('movie')
          setBuddyActivateToken((token) => token + 1)
          setBuddyNote('Movie Buddy is on.')
          controller.activate()
          return
        case 'deactivate':
          controller.deactivate()
          setBuddyNote('Movie Buddy is off.')
          return
        case 'resume-buddy':
          setSurface('movie')
          setBuddyActivateToken((token) => token + 1)
          setBuddyNote('Movie Buddy is back.')
          controller.resume()
          return
        case 'quiet':
          controller.quiet()
          setSurface('movie')
          setBuddyNote('Sidekick will stay quiet for a minute.')
          return
        case 'what-happened':
          setSurface('movie')
          controller.askWhatHappened()
          return
        case 'explain':
          setSurface('movie')
          controller.askExplain()
          return
        case 'pause':
          controller.pause()
          setSurface('movie')
          setBuddyNote('Paused.')
          return
        case 'resume-playback':
          controller.togglePlay()
          setSurface('movie')
          return
        case 'seek-back':
          controller.seekBack(command.seconds ?? 30)
          setSurface('movie')
          setBuddyNote(`Back ${command.seconds ?? 30} seconds.`)
          return
        case 'seek-forward':
          controller.seekBack(-(command.seconds ?? 30))
          setSurface('movie')
          return
        case 'play-a-movie': {
          // The request still belongs to the decision engine; the companion
          // switches on alongside it.
          const remainder = command.remainder.replace(/,?\s*and\s+turn on movie buddy/i, '')
          setSurface('movie')
          setBuddyActivateToken((token) => token + 1)
          buddyRef.current.activate()
          if (remainder.trim().length > 0) {
            void sidekick.send(remainder.trim(), source)
          }
          return
        }
        default:
          break
      }

      // "play me a movie and turn on movie buddy" can also arrive without the
      // exact pattern above.
      if (containsActivation(trimmed)) {
        setSurface('movie')
        setBuddyActivateToken((token) => token + 1)
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
    const turn = sidekick.turns[sidekick.turns.length - 1]
    if (!turn || turn.role !== 'assistant' || !turn.response) return
    const text = summariseResponse(turn.response)
    if (!text || spokenRef.current === turn.id) return
    spokenRef.current = turn.id
    void speaker.speak(text, {
      onStart: () => setSpeaking(true),
      onEnd: () => setSpeaking(false),
      onError: (message) => {
        setSpeaking(false)
        setSpeechNotice(message)
      },
    })
  }, [sidekick.turns, sidekick.speakEnabled, speaker])

  const interrupt = useCallback(() => {
    speaker.cancel()
    setSpeaking(false)
    sidekick.cancel()
  }, [sidekick, speaker])

  const busy = sidekick.phase === 'thinking' || sidekick.phase === 'executing'
  const companionState = companionStateFor(sidekick.phase, voice.status, speaking)

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <aside className="shell__rail">
        <div className="brand">
          <span className="brand__mark">
            <SidekickMark size={18} />
          </span>
          <span>
            <span className="brand__name">Sidekick</span>
            <span className="brand__tag" style={{ display: 'block' }}>
              A companion, not a console
            </span>
          </span>
        </div>

        <nav className="nav" aria-label="Surfaces">
          {SURFACES.map((entry) => {
            const Icon = entry.icon
            const active = surface === entry.id
            return (
              <button
                type="button"
                key={entry.id}
                className="nav__item"
                aria-current={active ? 'page' : undefined}
                onClick={() => setSurface(entry.id)}
              >
                <Icon size={16} className="nav__glyph" />
                {entry.label}
              </button>
            )
          })}
        </nav>

        <div className="rail__footer">
          <CapabilityBar capabilities={sidekick.capabilities} connection={sidekick.connection} />
          <div className="session">
            <span className="session__label">Session</span>
            <span className="session__id" title={sidekick.sessionId}>
              {sidekick.sessionId}
            </span>
            <button
              type="button"
              className="btn btn--sm btn--ghost"
              onClick={sidekick.resetSession}
              style={{ alignSelf: 'flex-start' }}
            >
              New session
            </button>
          </div>
        </div>
      </aside>

      <main className="shell__main" id="main-content">
        <div className="surface">
          {surface === 'talk' ? (
            <TalkSurface
              sidekick={sidekick}
              busy={busy}
              companionState={companionState}
              onSubmit={handleUtterance}
              onChooseOption={(option) => handleUtterance(option, 'text')}
            />
          ) : null}

          {surface === 'movie' ? (
            <MovieBuddy
              speaker={speaker}
              speechEnabled={sidekick.speakEnabled}
              startActive={buddyActivateToken > 0}
              onSay={(text) => setBuddySaid(text)}
              controllerRef={buddyRef}
            />
          ) : null}

          {surface === 'music' ? (
            <>
              <SurfaceHeader
                eyebrow="Music"
                title="Playback"
                lede="Only providers the backend reports are shown, with their real connection state."
              />
              <MusicPanel
                providers={sidekick.capabilities?.providers ?? []}
                capabilities={sidekick.capabilities?.capabilities ?? []}
                tools={sidekick.capabilities?.tools ?? []}
                lastResponse={lastResponse}
                onRequest={(text) => handleUtterance(text, 'text')}
              />
            </>
          ) : null}

          {surface === 'games' ? (
            <>
              <SurfaceHeader
                eyebrow="Games"
                title="Play"
                lede="Chess is one of several games - the list comes from the backend, not from a hard-coded menu."
              />
              <GamesPanel
                games={sidekick.capabilities?.games ?? []}
                lastResponse={lastResponse}
                onRequest={(text) => handleUtterance(text, 'text')}
              />
            </>
          ) : null}
        </div>
      </main>

      <div className="shell__dock">
        <div className="shell__dock-inner">
          <div className="dock">
            <div className="dock__companion">
              <Companion state={companionState} size={54} />
            </div>
            <div className="dock__composer">
              <Composer
                voice={voice}
                busy={busy}
                speaking={speaking}
                speechNotice={speechNotice}
                speechEnabled={sidekick.speakEnabled}
                onToggleSpeech={sidekick.setSpeakEnabled}
                onSubmit={handleUtterance}
                onInterrupt={interrupt}
              />
            </div>
          </div>
          {buddyNote ? (
            <p className="dock__note" role="status">
              {buddyNote}
            </p>
          ) : null}
          {buddySaid ? (
            <p className="dock__note dock__note--said" role="status">
              Movie Buddy: {buddySaid}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function TalkSurface({
  sidekick,
  busy,
  companionState,
  onSubmit,
  onChooseOption,
}: {
  sidekick: ReturnType<typeof useSidekick>
  busy: boolean
  companionState: CompanionState
  onSubmit: (text: string, source: 'voice' | 'text') => void
  onChooseOption: (option: string) => void
}) {
  const { turns, phase } = sidekick

  const lastAssistant = useMemo(() => {
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      const turn = turns[index]
      if (turn?.role === 'assistant') return turn
    }
    return null
  }, [turns])

  return (
    <>
      <SurfaceHeader
        eyebrow="Talk"
        title="What should Sidekick do?"
        lede="Speak or type. The decision engine resolves it, the tools run it, and you can watch exactly why."
        actions={<PhaseBadge phase={phase} />}
      />

      {sidekick.connection === 'disconnected' ? (
        <div style={{ marginBottom: 'var(--space-5)' }}>
          <Notice tone="danger">
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <div style={{ flex: 1 }}>
                <strong>The backend is not reachable.</strong>{' '}
                {sidekick.capabilityError ?? 'The capability check failed.'} Requests cannot be
                resolved until it is back.
              </div>
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => void sidekick.refreshCapabilities()}
              >
                <RefreshIcon size={13} />
                Retry
              </button>
            </div>
          </Notice>
        </div>
      ) : null}

      <section className="hero" aria-label="Sidekick right now">
        <div className="hero__companion">
          <Companion state={companionState} size={132} />
        </div>
        <div className="hero__body">
          <CurrentTask
            busy={busy}
            phase={phase}
            utterance={lastAssistant ? '' : ''}
            response={lastAssistant?.response ?? null}
            events={sidekick.liveEvents}
            hasTurns={turns.length > 0}
          />
        </div>
      </section>

      {lastAssistant?.response ? (
        <DecisionTrace
          response={lastAssistant.response}
          utterance={lastAssistant.utterance}
          inputSource={lastAssistant.inputSource}
          liveEvents={sidekick.liveEvents}
          busy={busy}
        />
      ) : null}

      {turns.length === 0 ? (
        <EmptyState
          title="Nothing asked yet"
          body="Try a request with a correction in it, for example: open YouTube and play a song - no wait, Spotify."
        />
      ) : (
        <Conversation
          turns={turns}
          onChooseOption={onChooseOption}
          onRetry={() => {
            const lastUser = [...turns].reverse().find((turn) => turn.role === 'user')
            if (lastUser) onSubmit(lastUser.utterance, lastUser.inputSource)
          }}
        />
      )}

      {busy ? (
        <div className="row" style={{ marginTop: 'var(--space-4)', gap: 'var(--space-3)' }}>
          <p className="hint" role="status" style={{ margin: 0 }}>
            Resolving the request with the backend...
          </p>
          <button type="button" className="btn btn--sm" onClick={sidekick.cancel}>
            Cancel request
          </button>
        </div>
      ) : null}
    </>
  )
}

/** The actual current task - never a decorative placeholder. */
function CurrentTask({
  busy,
  phase,
  response,
  events,
  hasTurns,
}: {
  busy: boolean
  phase: Phase
  utterance: string
  response: SidekickResponseLike | null
  events: Array<{ message?: string; seq?: number; type?: string; kind?: string }>
  hasTurns: boolean
}) {
  if (busy) {
    return (
      <div className="task">
        <p className="task__label">Working on it</p>
        <p className="task__headline">
          {events.length > 0
            ? (events[events.length - 1]?.message ?? 'The request is with the decision engine.')
            : 'The request is with the decision engine.'}
        </p>
        {events.length > 0 ? (
          <ul className="task__events">
            {events.slice(-4).map((event, index) => (
              <li key={event.seq ?? index}>
                <span className="task__event-seq">{event.seq ?? index + 1}</span>
                {event.message ?? event.type ?? event.kind ?? 'update'}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    )
  }

  if (!response) {
    return (
      <div className="task">
        <p className="task__label">Ready</p>
        <p className="task__headline">
          {hasTurns
            ? 'Ask for something, or turn on Movie Buddy and watch a film together.'
            : 'Ask for something, or turn on Movie Buddy and watch a film together.'}
        </p>
        <p className="task__note">
          Try: &ldquo;play a song on spotify and then start a chess game&rdquo;, or &ldquo;turn on
          Movie Buddy&rdquo;.
        </p>
      </div>
    )
  }

  const actions = response.action_plan
  const waiting = response.status === 'awaiting_confirmation' || response.status === 'needs_clarification'

  return (
    <div className="task">
      <p className="task__label">
        {waiting ? 'Waiting for you' : phase === 'error' ? 'Did not work' : 'Last task'}
      </p>
      <p className="task__headline">
        {response.clarification
          ? response.clarification.question
          : actions.length > 0
            ? actions.map((action) => action.tool).join(' then ')
            : 'Nothing to run'}
      </p>
      <ul className="task__chips">
        <li className="chip">{Math.round(response.intent.confidence * 100)}% confident</li>
        <li className="chip">risk {response.risk_level}</li>
        <li className="chip">
          {response.decision_model.model}
          {response.decision_model.fallback_used ? ' (fallback)' : ''}
        </li>
        {actions.some((action) => action.approval_required) ? (
          <li className="chip chip--warn">approval required</li>
        ) : null}
      </ul>
    </div>
  )
}

type SidekickResponseLike = {
  intent: { confidence: number }
  action_plan: Array<{ tool: string; approval_required: boolean }>
  risk_level: string
  status: string
  decision_model: { model: string; fallback_used: boolean }
  clarification: { question: string } | null
}

function SurfaceHeader({
  eyebrow,
  title,
  lede,
  actions,
}: {
  eyebrow: string
  title: string
  lede: string
  actions?: React.ReactNode
}) {
  return (
    <header className="surface__header">
      <div className="surface__heading">
        <div className="surface__eyebrow-row">
          <p className="surface__eyebrow">{eyebrow}</p>
          {actions}
        </div>
        <h1 className="surface__title">{title}</h1>
        <p className="surface__lede">{lede}</p>
      </div>
    </header>
  )
}

function PhaseBadge({ phase }: { phase: Phase }) {
  const map: Record<Phase, { label: string; tone: string }> = {
    idle: { label: 'ready', tone: 'muted' },
    listening: { label: 'listening', tone: 'listen' },
    thinking: { label: 'thinking', tone: 'thinking' },
    executing: { label: 'working', tone: 'executing' },
    awaiting_confirmation: { label: 'needs you', tone: 'confirm' },
    speaking: { label: 'speaking', tone: 'speaking' },
    error: { label: 'error', tone: 'danger' },
  }
  const entry = map[phase]
  return (
    <span className="badge badge--quiet">
      <span className="dot" data-tone={entry.tone} />
      {entry.label}
    </span>
  )
}

function companionStateFor(
  phase: Phase,
  voiceStatus: string,
  speaking: boolean,
): CompanionState {
  if (speaking) return 'speaking'
  if (voiceStatus === 'listening') return 'listening'
  if (phase === 'thinking') return 'thinking'
  if (phase === 'executing') return 'acting'
  if (phase === 'awaiting_confirmation') return 'waiting'
  if (phase === 'error') return 'error'
  return 'idle'
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
