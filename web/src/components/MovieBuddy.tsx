import { useEffect, useMemo, useRef, useState } from 'react'
import type { MediaAsset, MediaCue } from '@/lib/api/types'
import { loadMediaLibrary } from '@/lib/media/catalog'
import { parseSubtitles } from '@/lib/media/subtitles'
import { useMovieBuddy } from '@/lib/media/useMovieBuddy'
import { formatClock } from '@/lib/media/subtitles'
import { BUDDY_CAPABILITY_NOTE } from '@/lib/movie/commands'
import { NOOP_BUDDY_CONTROLLER, type BuddyController } from '@/lib/movie/controller'
import type { CommentaryProvider } from '@/lib/movie/provider'
import type { Speaker } from '@/lib/voice/synthesis'
import { Companion } from './Companion'
import { FilmIcon } from './icons'
import { EmptyState, Notice } from './ui'

export interface MovieBuddyProps {
  speaker: Speaker
  speechEnabled: boolean
  /** True when the buddy should start switched on (a voice command did it). */
  startActive?: boolean
  onSay?: (text: string) => void
  controllerRef?: React.MutableRefObject<BuddyController>
  /** Overrides the commentary provider - used by the tests. */
  provider?: CommentaryProvider
}

export function MovieBuddy({
  speaker,
  speechEnabled,
  startActive,
  onSay,
  controllerRef,
  provider,
}: MovieBuddyProps) {
  const [assets, setAssets] = useState<MediaAsset[]>([])
  const [assetId, setAssetId] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [showWhy, setShowWhy] = useState(false)
  const [subtitleNotice, setSubtitleNotice] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const subtitleInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    let cancelled = false
    void loadMediaLibrary().then((result) => {
      if (cancelled) return
      setAssets(result.assets)
      setWarnings(result.warnings)
      setAssetId((current) => current ?? result.assets[0]?.id ?? null)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const asset = useMemo(
    () => assets.find((entry) => entry.id === assetId) ?? null,
    [assets, assetId],
  )

  const buddy = useMovieBuddy({ asset, speaker, speechEnabled, onSay, provider })

  // A voice command can switch the buddy on before a film is chosen.
  useEffect(() => {
    if (startActive) buddy.activate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startActive])

  useEffect(() => {
    const controller: BuddyController = {
      activate: () => buddy.activate(),
      deactivate: () => buddy.deactivate(),
      quiet: (ms) => buddy.quiet(ms),
      resume: () => buddy.resumeBuddy(),
      askWhatHappened: () => {
        buddy.askWhatHappened()
      },
      askExplain: () => {
        buddy.askExplain()
      },
      togglePlay: () => buddy.togglePlay(),
      pause: () => {
        const video = buddy.videoRef.current
        if (video && !video.paused) video.pause()
      },
      seekBack: (seconds) => buddy.seekBy(-seconds),
    }
    if (controllerRef) controllerRef.current = controller
    return () => {
      if (controllerRef && controllerRef.current === controller) {
        controllerRef.current = NOOP_BUDDY_CONTROLLER
      }
    }
  }, [buddy, controllerRef])

  const onPickVideo = (file: File | undefined) => {
    if (!file) return
    const url = URL.createObjectURL(file)
    const custom: MediaAsset = {
      id: `custom-${file.name}-${file.size}`,
      title: file.name,
      credit: 'Your own file - played from this browser, never uploaded',
      license: 'yours',
      src: url,
      mime_type: file.type || 'video/mp4',
      subtitle_src: '',
      subtitle_label: 'no captions loaded yet',
      cues: [],
      companion_rules: [],
    }
    setAssets((current) => [custom, ...current])
    setAssetId(custom.id)
    setSubtitleNotice(
      'Load a subtitle file (.srt or .vtt) for this video and the companion can read it.',
    )
    buddy.activate()
  }

  const onPickSubtitles = async (file: File | undefined) => {
    if (!file) return
    const text = await file.text()
    const cues = parseSubtitles(text)
    if (cues.length === 0) {
      setSubtitleNotice(
        'That subtitle file did not contain any line I could read. A SubRip (.srt) or WebVTT (.vtt) file is expected.',
      )
      return
    }
    setSubtitleNotice(
      `Loaded ${cues.length} caption lines from ${file.name}. The companion is reading those now.`,
    )
    buddy.handleCueChange(cues)
  }

  if (loading) {
    return (
      <EmptyState
        title="Loading the film library"
        body="Fetching the openly licensed films and their caption tracks."
        glyph={<FilmIcon size={32} />}
      />
    )
  }

  if (!asset) {
    return (
      <EmptyState
        title="No film is available"
        body="Movie Buddy needs a video it can play. Open one from this device, and load a subtitle file so the companion has something to read."
        glyph={<FilmIcon size={32} />}
        action={
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => fileInputRef.current?.click()}
          >
            Choose a video
          </button>
        }
      />
    )
  }

  const companionState =
    buddy.buddy.mode === 'off'
      ? 'off'
      : buddy.buddy.speaking
        ? 'speaking'
        : buddy.buddy.mode === 'quiet'
          ? 'quiet'
          : buddy.player.paused
            ? 'idle'
            : 'acting'

  const sourceLabel =
    buddy.buddy.source === 'model'
      ? 'model'
      : buddy.buddy.source === 'local'
        ? 'local heuristic'
        : 'unavailable'

  return (
    <div className="buddy">
      <div className="buddy__intro">
        <div>
          <p className="surface__eyebrow">Movie Buddy</p>
          <h2 className="surface__title">Watch together</h2>
          <p className="surface__lede">{BUDDY_CAPABILITY_NOTE}</p>
        </div>
        <div className="buddy__source">
          <label className="field__label" htmlFor="buddy-source">
            Film
          </label>
          <select
            id="buddy-source"
            className="input"
            value={assetId ?? ''}
            onChange={(event) => setAssetId(event.target.value)}
          >
            {assets.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.title} - {entry.license}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn--sm"
            onClick={() => fileInputRef.current?.click()}
          >
            Open a video
          </button>
          <button
            type="button"
            className="btn btn--sm"
            onClick={() => subtitleInputRef.current?.click()}
          >
            Load subtitles
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*"
            className="sr-only"
            aria-label="Choose a video file from this device"
            onChange={(event) => onPickVideo(event.target.files?.[0])}
          />
          <input
            ref={subtitleInputRef}
            type="file"
            accept=".srt,.vtt,text/vtt,application/x-subrip"
            className="sr-only"
            aria-label="Choose a subtitle file for the current video"
            onChange={(event) => void onPickSubtitles(event.target.files?.[0])}
          />
        </div>
      </div>

      {warnings.map((warning) => (
        <Notice key={warning} tone="warn">
          {warning}
        </Notice>
      ))}

      {subtitleNotice ? (
        <Notice tone="warn">
          {subtitleNotice}
        </Notice>
      ) : null}

      {buddy.buddy.alignment.status === 'mismatch' ? (
        <Notice tone="danger">
          {buddy.buddy.alignment.detail}
        </Notice>
      ) : null}

      {buddy.buddy.alignment.status === 'no-cues' ? (
        <Notice tone="warn">
          {buddy.buddy.alignment.detail}
        </Notice>
      ) : null}

      <div className="buddy__grid">
        <div className="buddy__stage">
          <div
            className="stage"
            style={{ aspectRatio: buddy.stageAspect }}
            data-buffering={buddy.player.buffering || undefined}
          >
            <video
              ref={buddy.attachVideo}
              controls
              preload="metadata"
              playsInline
              onTimeUpdate={buddy.handleTimeUpdate}
              onLoadedMetadata={buddy.handleLoadedMetadata}
              onError={buddy.handleError}
              onWaiting={buddy.handleWaiting}
              onPlaying={buddy.handlePlaying}
              onEnded={buddy.handleEnded}
              onSeeked={buddy.handleTimeUpdate}
            >
              {(asset.sources ?? [{ src: asset.src, mime_type: asset.mime_type, label: 'video' }]).map(
                (source) => (
                  <source key={source.src} src={source.src} type={source.mime_type} />
                ),
              )}
              {buddy.trackUrl ? (
                <track
                  kind="subtitles"
                  src={buddy.trackUrl}
                  srcLang="en"
                  label="English captions"
                  default
                />
              ) : null}
              Your browser cannot play this video element.
            </video>

            <div className="stage__badge">
              <span className="badge badge--quiet">{asset.title}</span>
              <span className="badge badge--quiet">{asset.license}</span>
              {asset.bundled ? <span className="badge badge--live">bundled</span> : null}
            </div>

            <div className="stage__overlay" data-empty={buddy.activeCueText.length === 0}>
              {buddy.activeCueText}
            </div>

            {buddy.player.mediaError ? (
              <div className="stage__error">
                <div style={{ textAlign: 'center', padding: '24px 16px' }}>
                  <p style={{ color: 'var(--ink)', fontWeight: 600, marginBottom: 8 }}>
                    ⚠️ {buddy.player.mediaError}
                  </p>
                  <p className="hint" style={{ marginBottom: 16 }}>
                    Your browser couldn&apos;t play that format. Try loading a video from your device, or open a streaming film directly.
                  </p>
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      className="btn btn--primary btn--sm"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      📂 Open a local video
                    </button>
                    <a
                      href="https://archive.org/download/Tears-of-Steel/tears_of_steel_720p.mp4"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn btn--sm"
                    >
                      🎬 Open Tears of Steel (CC)
                    </a>
                  </div>
                </div>
              </div>
            ) : null}

            {buddy.player.buffering ? (
              <div className="stage__buffering" role="status">
                buffering
              </div>
            ) : null}
          </div>

          <div className="buddy__transport">
            <button type="button" className="btn btn--sm" onClick={buddy.togglePlay}>
              {buddy.player.paused ? 'Play' : 'Pause'}
            </button>
            <button type="button" className="btn btn--sm" onClick={() => buddy.seekBy(-30)}>
              -30s
            </button>
            <button type="button" className="btn btn--sm" onClick={() => buddy.seekBy(30)}>
              +30s
            </button>
            <button
              type="button"
              className="btn btn--sm"
              onClick={() =>
                buddy.setRate(buddy.player.rate === 1 ? 1.5 : buddy.player.rate === 1.5 ? 2 : 1)
              }
            >
              {buddy.player.rate}x
            </button>
            <span className="timeline__time">
              {formatClock(buddy.player.currentTime)} / {formatClock(buddy.player.duration)}
            </span>
          </div>

          <BuddyTimeline cues={buddy.cues} currentTime={buddy.player.currentTime} />
        </div>

        <aside className="buddy__panel">
          <div className="buddy__companion">
            <Companion
              state={companionState}
              size={104}
              label={
                buddy.buddy.mode === 'off'
                  ? 'off'
                  : buddy.buddy.mode === 'quiet'
                    ? `quiet ${Math.ceil(buddy.buddy.quietRemainingMs / 1000)}s`
                    : buddy.player.paused
                      ? 'on - paused'
                      : 'on'
              }
            />
            <div className="buddy__status">
              <p className="buddy__status-line">
                {buddy.buddy.mode === 'off'
                  ? 'Movie Buddy is off. Ask to turn it on whenever you like.'
                  : buddy.buddy.mode === 'quiet'
                    ? `Staying quiet for ${Math.ceil(buddy.buddy.quietRemainingMs / 1000)} more seconds.`
                    : buddy.player.paused
                      ? 'Movie Buddy is on and waiting with you.'
                      : 'Movie Buddy is on and following the captions.'}
              </p>
              <p className="hint">
                {buddy.buddy.alignment.status === 'no-cues'
                  ? 'No caption track is loaded, so the companion has nothing to read.'
                  : `Reading ${asset.subtitle_label}.`}
              </p>
            </div>
          </div>

          <div className="buddy__source-note">
            <span className="buddy__source-label">
              Commentary source: <b>{sourceLabel}</b>
            </span>
            <span className="hint">
              {buddy.buddy.source === 'model'
                ? 'Remarks are written by the configured model provider, from the caption lines it was shown.'
                : buddy.buddy.source === 'local'
                  ? 'No model provider is configured, so Sidekick uses a local heuristic that only reports what it can observe in the captions.'
                  : 'No commentary source is available.'}
            </span>
          </div>

          <div className="buddy__commands">
            <p className="field__label">Say or type</p>
            <div className="row row--wrap">
              <button
                type="button"
                className="btn btn--sm"
                onClick={() =>
                  buddy.buddy.mode === 'off' ? buddy.activate() : buddy.deactivate()
                }
              >
                {buddy.buddy.mode === 'off' ? 'Turn on Movie Buddy' : 'Turn off Movie Buddy'}
              </button>
              <button type="button" className="btn btn--sm" onClick={() => buddy.quiet()}>
                Be quiet for a bit
              </button>
              <button type="button" className="btn btn--sm" onClick={buddy.resumeBuddy}>
                Resume Movie Buddy
              </button>
              <button type="button" className="btn btn--sm" onClick={() => buddy.askWhatHappened()}>
                What just happened?
              </button>
              <button type="button" className="btn btn--sm" onClick={() => buddy.askExplain()}>
                Explain that moment
              </button>
              <button type="button" className="btn btn--sm" onClick={() => buddy.seekBy(-30)}>
                Go back 30 seconds
              </button>
            </div>
          </div>

          {buddy.buddy.lastAnswer ? (
            <div className="buddy__answer">
              <p className="field__label">Sidekick said</p>
              <p className="buddy__answer-text">{buddy.buddy.lastAnswer.say}</p>
              <p className="hint">
                {buddy.buddy.lastAnswer.unavailable
                  ? `Not available: ${buddy.buddy.lastAnswer.reason ?? 'no caption context'}.`
                  : `Grounded in ${buddy.buddy.lastAnswer.basis.length} caption line${
                      buddy.buddy.lastAnswer.basis.length === 1 ? '' : 's'
                    }.`}
              </p>
            </div>
          ) : null}

          <div className="buddy__why">
            <button
              type="button"
              className="btn btn--sm btn--ghost"
              aria-expanded={showWhy}
              onClick={() => setShowWhy((value) => !value)}
            >
              Why did Sidekick react?
            </button>
            {showWhy ? (
              <div className="buddy__why-body">
                {buddy.buddy.lastRemark ? (
                  <>
                    <p className="buddy__why-line">{buddy.buddy.lastRemark.reason}</p>
                    <p className="hint">
                      Grounded in the caption at {formatClock(buddy.buddy.lastRemark.cue.start)}: &ldquo;
                      {buddy.buddy.lastRemark.cue.text}&rdquo;
                    </p>
                    <p className="hint">
                      Written by: <b>{sourceLabel}</b>. It saw{' '}
                      {buddy.buddy.lastRemark.grounded_in.length} caption line
                      {buddy.buddy.lastRemark.grounded_in.length === 1 ? '' : 's'}.
                    </p>
                  </>
                ) : (
                  <p className="hint">
                    Sidekick has not said anything yet. A remark only happens when a real caption
                    line says something worth noticing - never on a timer.
                  </p>
                )}
                {buddy.buddy.lastDecision ? (
                  <p className="hint">
                    Right now it would hold back:{' '}
                    {buddy.buddy.lastDecision.kind === 'speak'
                      ? 'it has something to say.'
                      : buddy.buddy.lastDecision.reason}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="buddy__log">
            <p className="field__label">Remarks</p>
            {buddy.buddy.remarks.length === 0 ? (
              <p className="hint">
                Nothing yet. Sidekick is being selective on purpose.
              </p>
            ) : (
              <ul className="buddy__log-list">
                {buddy.buddy.remarks
                  .slice()
                  .reverse()
                  .map((remark) => (
                    <li key={remark.id} className="buddy__log-item">
                      <span className="buddy__log-time">{formatClock(remark.at)}</span>
                      <span className="buddy__log-say">{remark.say}</span>
                      <span className="buddy__log-rule">
                        {remark.source === 'model' ? 'model' : 'local'}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}

function BuddyTimeline({
  cues,
  currentTime,
}: {
  cues: MediaCue[]
  currentTime: number
}) {
  const total = cues.length > 0 ? (cues[cues.length - 1]?.end ?? 1) : 1

  return (
    <div className="buddy__timeline" role="group" aria-label="Caption timeline">
      <div className="buddy__timeline-track">
        <div
          className="buddy__timeline-played"
          style={{ width: `${(currentTime / total) * 100}%` }}
        />
        {cues.map((cue: MediaCue) => (
          <span
            key={cue.index}
            className="buddy__timeline-cue"
            style={{ left: `${(cue.start / total) * 100}%` }}
            title={`${formatClock(cue.start)} ${cue.text}`}
          />
        ))}
      </div>
      <p className="hint">
        {cues.length} caption lines over {formatClock(total)}. The playhead follows the real
        media clock.
      </p>
    </div>
  )
}
