import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CapabilitiesResponse, SidekickResponse } from '@/lib/api/types'
import { useVoiceInput } from '@/lib/voice/useVoiceInput'
import { Speaker } from '@/lib/voice/synthesis'
import { useSidekick, type Phase } from '@/state/useSidekick'
import { CapabilityBar } from './components/CapabilityBar'
import { Composer } from './components/Composer'
import { Conversation, LiveProgress } from './components/Conversation'
import { GamesPanel } from './components/GamesPanel'
import { MovieCompanion } from './components/MovieCompanion'
import { MusicPanel } from './components/MusicPanel'
import { ChatIcon, FilmIcon, GameIcon, MusicIcon, RefreshIcon, SidekickMark } from './components/icons'
import { EmptyState, Notice } from './components/ui'

type Surface = 'talk' | 'movie' | 'music' | 'games'

const SURFACES: Array<{ id: Surface; label: string; icon: typeof ChatIcon }> = [
  { id: 'talk', label: 'Talk', icon: ChatIcon },
  { id: 'movie', label: 'Movie', icon: FilmIcon },
  { id: 'music', label: 'Music', icon: MusicIcon },
  { id: 'games', label: 'Games', icon: GameIcon },
]

export function App() {
  const sidekick = useSidekick()
  const speaker = useMemo(() => new Speaker(), [])
  const [surface, setSurface] = useState<Surface>('talk')
  const voice = useVoiceInput({
    onFinal: (transcript) => {
      void sidekick.send(transcript, 'voice')
    },
  })

  const lastResponse = useMemo(() => {
    for (let index = sidekick.turns.length - 1; index >= 0; index -= 1) {
      const turn = sidekick.turns[index]
      if (turn?.role === 'assistant' && turn.response) return turn.response
    }
    return null
  }, [sidekick.turns])

  const spokenRef = useRef<string | null>(null)
  const [speaking, setSpeaking] = useState(false)
  const [speechNotice, setSpeechNotice] = useState<string | null>(null)

  // Speak the newest assistant response once, when speech output is enabled.
  useEffect(() => {
    if (!sidekick.speakEnabled) return
    const turn = sidekick.turns[sidekick.turns.length - 1]
    if (!turn || turn.role !== 'assistant' || !turn.response) return
    const text = summariseResponse(turn.response)
    if (!text || spokenRef.current === turn.id) return
    spokenRef.current = turn.id
    void speaker.speak(text, {
      onStart: () => {
        setSpeaking(true)
        setSpeechNotice(null)
      },
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

  const handleSubmit = useCallback(
    (text: string, source: 'voice' | 'text') => {
      speaker.cancel()
      void sidekick.send(text, source)
    },
    [sidekick, speaker],
  )

  const busy = sidekick.phase === 'thinking' || sidekick.phase === 'executing'

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>

      <aside className="shell__rail">
        <div className="brand">
          <span className="brand__mark">
            <SidekickMark size={17} />
          </span>
          <span>
            <span className="brand__name">Sidekick</span>
            <span className="brand__tag" style={{ display: 'block' }}>
              Voice companion
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
              onSubmit={handleSubmit}
              onChooseOption={(option) => handleSubmit(option, 'text')}
            />
          ) : null}

          {surface === 'movie' ? (
            <>
              <SurfaceHeader
                eyebrow="Movie companion"
                title="Watch together"
                lede="Real playback with the film's official subtitle track. Companion events fire on real media time."
              />
              <MovieCompanion speaker={speaker} speechEnabled={sidekick.speakEnabled} />
            </>
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
                lastResponse={lastResponse}
                onRequest={(text) => handleSubmit(text, 'text')}
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
                onRequest={(text) => handleSubmit(text, 'text')}
              />
            </>
          ) : null}
        </div>
      </main>

      <div className="shell__dock">
        <div className="shell__dock-inner">
          <Composer
            voice={voice}
            busy={busy}
            speaking={speaking}
            speechNotice={speechNotice}
            speechEnabled={sidekick.speakEnabled}
            onToggleSpeech={sidekick.setSpeakEnabled}
            onSubmit={handleSubmit}
            onInterrupt={interrupt}
          />
        </div>
      </div>
    </div>
  )
}

function TalkSurface({
  sidekick,
  busy,
  onSubmit,
  onChooseOption,
}: {
  sidekick: ReturnType<typeof useSidekick>
  busy: boolean
  onSubmit: (text: string, source: 'voice' | 'text') => void
  onChooseOption: (option: string) => void
}) {
  const { turns, phase } = sidekick

  return (
    <>
      <SurfaceHeader
        eyebrow="Talk"
        title="What should Sidekick do?"
        lede="Speak or type. The request is resolved by the backend decision engine and the real outcome is shown here."
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

      {busy && sidekick.liveEvents.length > 0 ? (
        <div style={{ marginTop: 'var(--space-4)' }}>
          <LiveProgress events={sidekick.liveEvents} />
        </div>
      ) : null}

      {busy ? (
        <p className="hint" role="status" style={{ marginTop: 'var(--space-4)' }}>
          Resolving the request with the backend...
        </p>
      ) : null}
    </>
  )
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
    executing: { label: 'executing', tone: 'executing' },
    awaiting_confirmation: { label: 'needs confirmation', tone: 'confirm' },
    speaking: { label: 'speaking', tone: 'executing' },
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

/** Short spoken summary built from the real backend result. */
export function summariseResponse(response: SidekickResponse): string {
  if (response.speech) return response.speech
  if (response.clarification) return response.clarification.question

  const failed = response.action_plan.find((action) => action.state === 'failed')
  if (failed) {
    return failed.error
      ? `${failed.tool} failed: ${failed.error.message}`
      : `${failed.tool} failed.`
  }

  const waiting = response.action_plan.find((action) => action.state === 'awaiting_confirmation')
  if (waiting) {
    return `${waiting.tool} needs your confirmation before it runs.`
  }

  const done = response.action_plan.find((action) => action.state === 'succeeded')
  if (done) {
    return `${done.tool} completed.`
  }

  if (response.action_plan.length === 0) {
    return 'I did not find an action to take.'
  }

  return `Working on ${response.action_plan.map((action) => action.tool).join(', ')}.`
}

export type { CapabilitiesResponse }
