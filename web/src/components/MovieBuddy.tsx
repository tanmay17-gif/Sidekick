import { useEffect, useMemo, useRef, useState } from 'react'
import type { MediaAsset } from '@/lib/api/types'
import { loadMediaLibrary } from '@/lib/media/catalog'
import { useMovieBuddy } from '@/lib/media/useMovieBuddy'
import { formatClock } from '@/lib/media/subtitles'
import { BUDDY_CAPABILITY_NOTE } from '@/lib/movie/commands'
import { NOOP_BUDDY_CONTROLLER, type BuddyController } from '@/lib/movie/controller'
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
  /** The app registers the controller so voice commands can drive the player. */
  controllerRef?: React.MutableRefObject<BuddyController>
}

export function MovieBuddy({
  speaker,
  speechEnabled,
  startActive,
  onSay,
  controllerRef,
}: MovieBuddyProps) {
  const [assets, setAssets] = useState<MediaAsset[]>([])
  const [assetId, setAssetId] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [showWhy, setShowWhy] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

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

  const buddy = useMovieBuddy({ asset, speaker, speechEnabled, onSay })

  // The native caption track stays attached for assistive technology and the
  // player's own caption menu, but hidden so it does not double up with the
  // app's styled captions.
  const trackElementRef = useRef<HTMLTrackElement | null>(null)
  useEffect(() => {
    const track = trackElementRef.current
    if (track?.track && track.track.mode !== 'hidden') track.track.mode = 'hidden'
  }, [buddy.trackUrl, asset?.id])

  // Register the controller so the talk surface can drive this one.
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

  // A voice command can switch the buddy on before a film is chosen.
  useEffect(() => {
    if (startActive) buddy.activate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startActive])

  const onPickFile = (file: File | undefined) => {
    if (!file) return
    const url = URL.createObjectURL(file)
    const custom: MediaAsset = {
      id: `custom-${file.name}`,
      title: file.name,
      credit: 'Your own file - played from this browser, never uploaded',
      license: 'yours',
      src: url,
      mime_type: file.type || 'video/mp4',
      subtitle_src: '',
      subtitle_label: 'no captions supplied',
      cues: [],
      companion_rules: [],
    }
    setAssets((current) => [custom, ...current])
    setAssetId(custom.id)
    buddy.activate()
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
        body="Movie Buddy needs a video it can play. Add one of the bundled open-licensed films, or choose a file from this device."
        glyph={<FilmIcon size={32} />}
        action={
          <button type="button" className="btn btn--primary" onClick={() => fileInputRef.current?.click()}>
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
            Open a file
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*"
            className="sr-only"
            aria-label="Choose a video file from this device"
            onChange={(event) => onPickFile(event.target.files?.[0])}
          />
        </div>
      </div>

      {warnings.map((warning) => (
        <Notice key={warning} tone="warn">
          {warning}
        </Notice>
      ))}

      <div className="buddy__grid">
        <div className="buddy__stage">
          <div className="stage" style={{ aspectRatio: buddy.stageAspect }} data-buffering={buddy.player.buffering || undefined}>
            <video
              ref={buddy.videoRef}
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
              {/* The browser takes the first encode it can decode. */}
              {(asset.sources ?? [{ src: asset.src, mime_type: asset.mime_type, label: 'video' }]).map(
                (source) => (
                  <source key={source.src} src={source.src} type={source.mime_type} />
                ),
              )}
              {buddy.trackUrl ? (
                <track
                  ref={(element) => {
                    trackElementRef.current = element
                    if (element?.track && element.track.mode !== 'hidden') element.track.mode = 'hidden'
                  }}
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
                <div>
                  <p style={{ color: 'var(--ink)' }}>{buddy.player.mediaError}</p>
                  <p className="hint" style={{ marginTop: 'var(--space-2)' }}>
                    Choose another film - the rest of the interface keeps working.
                  </p>
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
              onClick={() => buddy.setRate(buddy.player.rate === 1 ? 1.5 : buddy.player.rate === 1.5 ? 2 : 1)}
            >
              {buddy.player.rate}x
            </button>
            <span className="timeline__time">
              {formatClock(buddy.player.currentTime)} / {formatClock(buddy.player.duration)}
            </span>
          </div>

          <BuddyTimeline asset={asset} currentTime={buddy.player.currentTime} />
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
                {asset.cues.length > 0
                  ? `${asset.cues.length} caption lines · subtitle-based understanding, no picture analysis.`
                  : 'This source has no captions, so the companion has nothing to ground a comment in.'}
              </p>
            </div>
          </div>

          <div className="buddy__commands">
            <p className="field__label">Say or type</p>
            <div className="row row--wrap">
              <button
                type="button"
                className="btn btn--sm"
                onClick={() => (buddy.buddy.mode === 'off' ? buddy.activate() : buddy.deactivate())}
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
                {buddy.buddy.lastReaction ? (
                  <>
                    <p className="buddy__why-line">{buddy.buddy.lastReaction.reason}</p>
                    <p className="hint">
                      Triggered by the caption at {formatClock(buddy.buddy.lastReaction.at)}: &ldquo;
                      {buddy.buddy.lastReaction.cue.text}&rdquo;
                    </p>
                  </>
                ) : (
                  <p className="hint">
                    Sidekick has not reacted yet. A reaction happens when a real caption line
                    satisfies one of its rules - never on a timer.
                  </p>
                )}
                {buddy.lastGate ? (
                  <p className="hint">
                    Right now it would hold back: {buddy.lastGate.reason}
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="buddy__log">
            <p className="field__label">Remarks</p>
            {buddy.buddy.reactions.length === 0 ? (
              <p className="hint">Nothing yet. Sidekick is being selective on purpose.</p>
            ) : (
              <ul className="buddy__log-list">
                {buddy.buddy.reactions
                  .slice()
                  .reverse()
                  .map((reaction) => (
                    <li key={reaction.id} className="buddy__log-item">
                      <span className="buddy__log-time">{formatClock(reaction.at)}</span>
                      <span className="buddy__log-say">{reaction.say}</span>
                      <span className="buddy__log-rule">{reaction.rule}</span>
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
  asset,
  currentTime,
}: {
  asset: MediaAsset
  currentTime: number
}) {
  const total = asset.cues.length > 0 ? (asset.cues[asset.cues.length - 1]?.end ?? 1) : 1

  return (
    <div className="buddy__timeline" role="group" aria-label="Caption timeline">
      <div className="buddy__timeline-track">
        <div className="buddy__timeline-played" style={{ width: `${(currentTime / total) * 100}%` }} />
        {asset.cues.map((cue) => (
          <span
            key={cue.index}
            className="buddy__timeline-cue"
            style={{ left: `${(cue.start / total) * 100}%` }}
            title={`${formatClock(cue.start)} ${cue.text}`}
          />
        ))}
      </div>
      <p className="hint">
        {asset.cues.length} caption lines over {formatClock(total)}. The playhead follows the real
        media clock.
      </p>
    </div>
  )
}
