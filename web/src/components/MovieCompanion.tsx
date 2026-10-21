import { useEffect, useMemo, useState } from 'react'
import type { MediaAsset } from '@/lib/api/types'
import { loadDefaultMedia } from '@/lib/media/catalog'
import { understandingLabel } from '@/lib/media/companion'
import { useMovieCompanion, type CompanionMode } from '@/lib/media/useMovieCompanion'
import { formatClock } from '@/lib/media/subtitles'
import { Speaker } from '@/lib/voice/synthesis'
import { FilmIcon } from './icons'
import { EmptyState, Notice, Panel } from './ui'

const MODES: Array<{ id: CompanionMode; label: string; hint: string }> = [
  { id: 'quiet', label: 'Quiet', hint: 'Nothing is spoken and no cards are raised.' },
  { id: 'spoken', label: 'Brief', hint: 'Speaks short lines, only in the gaps between dialogue.' },
  { id: 'cards', label: 'Cards', hint: 'Raises a companion card for every matched subtitle line.' },
]

export interface MovieCompanionProps {
  speaker: Speaker
  speechEnabled: boolean
}

export function MovieCompanion({ speaker, speechEnabled }: MovieCompanionProps) {
  const [asset, setAsset] = useState<MediaAsset | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [mode, setMode] = useState<CompanionMode>('cards')

  useEffect(() => {
    let cancelled = false
    void loadDefaultMedia().then((result) => {
      if (cancelled) return
      setAsset(result.asset)
      setWarnings(result.warnings)
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (!asset) {
    return (
      <EmptyState
        title="Loading the companion"
        body="Fetching the open-licensed film and its official subtitle track."
        glyph={<FilmIcon size={32} />}
      />
    )
  }

  return (
    <MovieStage
      asset={asset}
      speaker={speaker}
      speechEnabled={speechEnabled}
      mode={mode}
      onModeChange={setMode}
      warnings={warnings}
    />
  )
}

function MovieStage({
  asset,
  speaker,
  speechEnabled,
  mode,
  onModeChange,
  warnings,
}: {
  asset: MediaAsset
  speaker: Speaker
  speechEnabled: boolean
  mode: CompanionMode
  onModeChange: (mode: CompanionMode) => void
  warnings: string[]
}) {
  const movie = useMovieCompanion({ asset, speaker, speechEnabled, mode })
  const { state } = movie

  const markers = useMemo(
    () =>
      movie.events.map((event) => ({
        id: event.id,
        left: `${(event.at / Math.max(1, movie.totalCueTime)) * 100}%`,
        title: `${formatClock(event.at)} - ${event.title}`,
      })),
    [movie.events, movie.totalCueTime],
  )

  return (
    <div className="stack">
      {warnings.map((warning) => (
        <Notice key={warning} tone="warn">
          {warning}
        </Notice>
      ))}

      <div className="movie">
        <div>
          <div className="stage">
            <video
              ref={movie.videoRef}
              src={asset.src}
              controls
              preload="metadata"
              playsInline
              onTimeUpdate={movie.handleTimeUpdate}
              onLoadedMetadata={movie.handleLoadedMetadata}
              onError={movie.handleError}
              onPlay={() => movie.handleTimeUpdate()}
              onPause={() => movie.handleTimeUpdate()}
              onSeeked={() => movie.handleTimeUpdate()}
            >
              {movie.trackUrl ? (
                <track
                  kind="subtitles"
                  src={movie.trackUrl}
                  srcLang="en"
                  label="English (official)"
                  default
                />
              ) : null}
              Your browser cannot play this video element.
            </video>

            <div className="stage__badge">
              <span className="badge badge--quiet">{asset.title}</span>
              <span className="badge badge--quiet">{asset.license}</span>
            </div>

            <div className="stage__overlay" data-empty={state.activeCueText.length === 0}>
              {state.activeCueText}
            </div>

            {state.mediaError ? (
              <div className="stage__error">
                <div>
                  <p style={{ color: 'var(--ink)' }}>{state.mediaError}</p>
                  <p className="hint" style={{ marginTop: 'var(--space-2)' }}>
                    The rest of the interface keeps working without the video.
                  </p>
                </div>
              </div>
            ) : null}
          </div>

          <div className="timeline">
            <span className="timeline__time">{formatClock(state.currentTime)}</span>
            <div
              className="timeline__track"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(state.progress * 100)}
              aria-label="Playback position within the subtitled section"
            >
              <div className="timeline__fill" style={{ width: `${state.progress * 100}%` }} />
              <div className="timeline__marks">
                {markers.map((marker) => (
                  <span
                    key={marker.id}
                    className="timeline__mark"
                    style={{ left: marker.left }}
                    title={marker.title}
                  />
                ))}
              </div>
            </div>
            <span className="timeline__time">
              {state.duration > 0 ? formatClock(state.duration) : '--:--'}
            </span>
          </div>
        </div>

        <div className="stack">
          <Panel
            title="Companion"
            hint={understandingLabel(asset)}
            actions={
              <div className="modes" role="group" aria-label="Companion mode">
                {MODES.map((entry) => (
                  <button
                    type="button"
                    key={entry.id}
                    className="modes__btn"
                    aria-pressed={mode === entry.id}
                    title={entry.hint}
                    onClick={() => onModeChange(entry.id)}
                  >
                    {entry.label}
                  </button>
                ))}
              </div>
            }
          >
            <p className="hint" style={{ marginBottom: 'var(--space-3)' }}>
              {MODES.find((entry) => entry.id === mode)?.hint}
            </p>
            <EventList
              events={state.reachedEvents}
              currentId={state.currentEvent?.id ?? null}
              onSeek={movie.seekTo}
            />
          </Panel>

          <Panel title="Source" hint="Openly licensed media shipped with the app">
            <dl className="stack stack--tight" style={{ fontSize: 'var(--text-sm)' }}>
              <div className="row">
                <dt style={{ color: 'var(--ink-muted)', minWidth: 92 }}>Title</dt>
                <dd style={{ margin: 0 }}>{asset.title}</dd>
              </div>
              <div className="row">
                <dt style={{ color: 'var(--ink-muted)', minWidth: 92 }}>License</dt>
                <dd style={{ margin: 0 }}>{asset.license}</dd>
              </div>
              <div className="row">
                <dt style={{ color: 'var(--ink-muted)', minWidth: 92 }}>Captions</dt>
                <dd style={{ margin: 0 }}>{asset.subtitle_label}</dd>
              </div>
              <div className="row">
                <dt style={{ color: 'var(--ink-muted)', minWidth: 92 }}>Cues</dt>
                <dd style={{ margin: 0 }}>{asset.cues.length} timed lines</dd>
              </div>
            </dl>
            <p className="hint" style={{ marginTop: 'var(--space-3)' }}>
              {asset.credit}
            </p>
          </Panel>
        </div>
      </div>

      {state.spokenNotice ? (
        <p className="hint" role="status">
          Spoken: {state.spokenNotice}
        </p>
      ) : null}
    </div>
  )
}

function EventList({
  events,
  currentId,
  onSeek,
}: {
  events: ReturnType<typeof useMovieCompanion>['state']['reachedEvents']
  currentId: string | null
  onSeek: (seconds: number) => void
}) {
  if (events.length === 0) {
    return (
      <p className="hint">
        Companion events appear when playback reaches the exact timestamp of a matching
        subtitle line.
      </p>
    )
  }
  return (
    <div className="events">
      {events
        .slice()
        .reverse()
        .map((event) => (
          <article className="event" key={event.id} data-current={event.id === currentId}>
            <div className="event__head">
              <span className="event__title">{event.title}</span>
              <span className="event__time">{formatClock(event.at)}</span>
            </div>
            <p className="event__why">{event.reason}</p>
            <p className="event__quote">{event.quote}</p>
            <button
              type="button"
              className="btn btn--sm"
              style={{ alignSelf: 'flex-start' }}
              onClick={() => onSeek(event.at)}
            >
              Jump to {formatClock(event.at)}
            </button>
          </article>
        ))}
    </div>
  )
}
