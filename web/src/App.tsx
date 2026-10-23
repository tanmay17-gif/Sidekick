import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { containsActivation, parseBuddyCommand } from '@/lib/movie/commands'
import { NOOP_BUDDY_CONTROLLER, type BuddyController } from '@/lib/movie/controller'
import { spokenSummary } from '@/lib/ui/language'
import { useVoiceInput } from '@/lib/voice/useVoiceInput'
import { Speaker } from '@/lib/voice/synthesis'
import { useSidekick, type ActionRecord, type RequestRecord } from '@/state/useSidekick'
import { ControlRoom } from './components/ControlRoom'
import { GamesPanel } from './components/GamesPanel'
import { MovieBuddy } from './components/MovieBuddy'
import { SidekickMark } from './components/icons'
import { VoiceSurface } from './components/VoiceSurface'
import { AlexaPlusSimulator } from './components/AlexaPlusSimulator'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type { SidekickResponse } from '@/lib/api/types'

/**
 * Destinations the browser opens locally (execution_target=="client").
 * Kept in sync with sidekick/tools/local.py:MEDIA_DESTINATIONS.
 */
const CLIENT_DESTINATIONS: Record<string, string> = {
  spotify: 'https://open.spotify.com',
  youtube: 'https://www.youtube.com',
  netflix: 'https://www.netflix.com',
  apple_music: 'https://music.apple.com',
  twitch: 'https://www.twitch.tv',
  vlc: 'https://www.videolan.org/vlc',
  wikipedia: 'https://www.wikipedia.org',
  google: 'https://www.google.com',
}

/** Report a client-executed action back to the backend. */
async function reportClientAction(
  actionId: string,
  sessionId: string,
  ok: boolean,
  url?: string,
) {
  try {
    await fetch(ENDPOINTS.complete(actionId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-sidekick-session-id': sessionId },
      body: JSON.stringify({ action_id: actionId, ok, url }),
    })
  } catch {
    // Non-critical: the backend will time the action out if we don't report
  }
}

/** Execute any client-side actions in a response (media.open, etc.). */
function dispatchClientActions(response: SidekickResponse, sessionId: string) {
  for (const action of response.action_plan ?? []) {
    const result = action.result as Record<string, unknown> | null | undefined
    if (!result || result['execution_target'] !== 'client') continue
    if (action.tool === 'media.open') {
      const dest = String((action.arguments as Record<string, unknown>)?.destination ?? '')
      const url = CLIENT_DESTINATIONS[dest] ?? null
      if (url) {
        window.open(url, '_blank', 'noopener,noreferrer')
        void reportClientAction(action.action_id, sessionId, true, url)
      } else {
        void reportClientAction(action.action_id, sessionId, false)
      }
    }
  }
}

type View = 'ask' | 'alexa-plus' | 'movie' | 'games' | 'control'

export function App() {
  const sidekick = useSidekick()
  const speaker = useMemo(() => new Speaker(), [])
  const [view, setView] = useState<View>('ask')
  const [speaking, setSpeaking] = useState(false)
  const [speechNotice, setSpeechNotice] = useState<string | null>(null)
  const [buddyNote, setBuddyNote] = useState<string | null>(null)
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
      } else if (/\b(play|start|open|show)\s+(a\s+game\s+of\s+|a\s+game\s+|the\s+game\s+of\s+|the\s+)?(chess|tic\s*tac\s*toe|2048|games?)\b/i.test(trimmed)) {
        setView('games')
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

  // Dispatch client-side actions (media.open → window.open) as responses arrive.
  useEffect(() => {
    const record = sidekick.requests[sidekick.requests.length - 1]
    if (!record || record.status !== 'answered' || !record.response) return
    dispatchClientActions(record.response, sidekick.sessionId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sidekick.requests])

  // Speak the newest assistant response once, when speech output is enabled.
  useEffect(() => {
    if (!sidekick.speakEnabled) return
    const record = sidekick.requests[sidekick.requests.length - 1]
    if (!record || record.status !== 'answered' || !record.response) return
    const text = spokenSummary(record.response)
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

  /** A new session starts from silence, with nothing carried over. */
  const newSession = useCallback(() => {
    speaker.cancel()
    setSpeaking(false)
    setSpeechNotice(null)
    sidekick.resetSession()
  }, [sidekick, speaker])

  const busy = sidekick.phase === 'thinking' || sidekick.phase === 'executing'

  const approve = useCallback(
    async (record: ActionRecord) => {
      await sidekick.approve(
        record.action.action_id,
        record.action.plan_hash ?? null,
        true,
      )
    },
    [sidekick],
  )

  const cancelAction = useCallback(
    async (record: ActionRecord) => {
      await sidekick.cancelAction(record.action.action_id)
    },
    [sidekick],
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
            aria-current={view === 'alexa-plus' ? 'page' : undefined}
            onClick={() => setView('alexa-plus')}
          >
            Alexa+ Simulator
          </button>
          <button
            type="button"
            className="app__view app__view--tech"
            aria-current={view === 'control' ? 'page' : undefined}
            onClick={() => setView('control')}
          >
            Developer
          </button>
          <span className="app__divider" aria-hidden="true" />
          <button
            type="button"
            className="app__view"
            aria-current={view === 'movie' ? 'page' : undefined}
            onClick={() => setView('movie')}
          >
            Movie Buddy
          </button>
          <button
            type="button"
            className="app__view"
            aria-current={view === 'games' ? 'page' : undefined}
            onClick={() => setView('games')}
          >
            Games
          </button>
        </nav>

        <div className="app__status">
          <EnvironmentChip
            connection={sidekick.connection}
            mode={sidekick.capabilities?.mode ?? null}
          />
          <span className="app__session" title={sidekick.sessionId}>
            {sidekick.sessionId.slice(0, 8)}
          </span>
          <button
            type="button"
            className="btn btn--sm btn--ghost"
            onClick={newSession}
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
            busyActions={sidekick.busyActions}
            actionErrors={sidekick.actionErrors}
            onSubmit={handleUtterance}
            onToggleSpeech={sidekick.setSpeakEnabled}
            onInterrupt={interrupt}
            onCancel={sidekick.cancel}
            onRetry={() => void sidekick.refreshCapabilities()}
            onChooseOption={(option) => handleUtterance(option, 'text')}
            onApprove={approve}
            onCancelAction={cancelAction}
          />
        ) : null}

        {view === 'alexa-plus' ? (
          <AlexaPlusSimulator speaker={speaker} speechEnabled={sidekick.speakEnabled} />
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

        {view === 'games' ? (
          <div style={{ maxWidth: 760, margin: '0 auto', width: '100%', padding: 'var(--space-4)' }}>
            <GamesPanel
              games={sidekick.capabilities?.games ?? [{ id: 'chess', name: 'Chess', state: 'live', detail: 'Interactive Board' }]}
              lastResponse={sidekick.liveRequest?.response ?? null}
              onRequest={(text) => handleUtterance(text, 'text')}
              speakText={(text) => {
                if (sidekick.speakEnabled) void speaker.speak(text)
              }}
            />
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
            busyActions={sidekick.busyActions}
            actionErrors={sidekick.actionErrors}
            onRefresh={() => void sidekick.refreshCapabilities()}
            onApprove={approve}
            onCancelAction={cancelAction}
          />
        ) : null}
      </main>
    </div>
  )
}

/**
 * The environment chip.
 *
 * A development stub must be identifiable, but it must not dominate the
 * product - so it is a small, quiet marker rather than a banner.
 */
function EnvironmentChip({
  connection,
  mode,
}: {
  connection: 'checking' | 'connected' | 'disconnected'
  mode: string | null
}) {
  if (connection === 'disconnected') {
    return (
      <span className="env-chip env-chip--off" title="The backend is not reachable">
        <span className="dot" data-tone="danger" />
        offline
      </span>
    )
  }
  if (connection === 'checking') {
    return (
      <span className="env-chip" title="Checking the backend">
        <span className="dot" data-tone="muted" />
        connecting
      </span>
    )
  }
  if (mode === 'stub') {
    return (
      <span
        className="env-chip env-chip--stub"
        title="This is the development stub backend, not the real Sidekick core. Everything it runs is labelled simulated."
      >
        <span className="dot" data-tone="simulated" />
        dev stub
      </span>
    )
  }
  return (
    <span className="env-chip env-chip--live" title="Connected to the real backend">
      <span className="dot" data-tone="live" />
      live
    </span>
  )
}


export type { RequestRecord }
