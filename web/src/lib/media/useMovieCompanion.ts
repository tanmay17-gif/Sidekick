import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MediaAsset } from '@/lib/api/types'
import { activeEvent, buildCompanionEvents, eventsReached, isSpeechSafe } from '@/lib/media/companion'
import { cueDuration, cueProgress, findCueIndex } from '@/lib/media/cues'
import { formatClock, toWebVtt } from '@/lib/media/subtitles'
import { Speaker } from '@/lib/voice/synthesis'

export type CompanionMode = 'quiet' | 'spoken' | 'cards'

export interface MovieState {
  currentTime: number
  duration: number
  paused: boolean
  ready: boolean
  mediaError: string | null
  activeCueIndex: number
  activeCueText: string
  reachedEvents: ReturnType<typeof eventsReached>
  currentEvent: ReturnType<typeof activeEvent>
  progress: number
  spokenNotice: string | null
}

export interface UseMovieCompanionOptions {
  asset: MediaAsset
  mode: CompanionMode
  speechEnabled: boolean
  speaker: Speaker
  onEventReached?: (event: { title: string; at: number; reason: string; quote: string }) => void
}

export function useMovieCompanion(options: UseMovieCompanionOptions) {
  const { asset, mode, speechEnabled, speaker } = options
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [paused, setPaused] = useState(true)
  const [ready, setReady] = useState(false)
  const [mediaError, setMediaError] = useState<string | null>(null)
  const [activeCueIndex, setActiveCueIndex] = useState(-1)
  const [spokenNotice, setSpokenNotice] = useState<string | null>(null)
  const firedRef = useRef<Set<string>>(new Set())
  const pendingSpeechRef = useRef<string | null>(null)
  const speakingRef = useRef(false)

  const events = useMemo(
    () => buildCompanionEvents({ rules: asset.companion_rules, cues: asset.cues }),
    [asset],
  )

  // Reset per-asset state when the asset changes.
  useEffect(() => {
    firedRef.current = new Set()
    pendingSpeechRef.current = null
    setCurrentTime(0)
    setActiveCueIndex(-1)
    setMediaError(null)
    setReady(false)
  }, [asset.id])

  const syncFromElement = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    const time = video.currentTime
    setCurrentTime(time)
    setPaused(video.paused)
    setActiveCueIndex(findCueIndex(asset.cues, time))
  }, [asset.cues])

  // `timeupdate` fires ~4x/second and is the real clock for the companion.
  const handleTimeUpdate = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    syncFromElement()

    const time = video.currentTime
    for (const event of events) {
      if (event.at > time) break
      if (firedRef.current.has(event.id)) continue
      firedRef.current.add(event.id)
      options.onEventReached?.(event)

      if (mode === 'spoken' && speechEnabled) {
        pendingSpeechRef.current = `${event.title}. ${event.quote}`
      }
    }

    // Only speak when no subtitle line is on screen - never talk over dialogue.
    if (pendingSpeechRef.current && !speakingRef.current && isSpeechSafe(asset.cues, time)) {
      const text = pendingSpeechRef.current
      pendingSpeechRef.current = null
      speakingRef.current = true
      setSpokenNotice(text)
      void speaker.speak(text, {
        onEnd: () => {
          speakingRef.current = false
          setSpokenNotice(null)
        },
        onError: () => {
          speakingRef.current = false
          setSpokenNotice(null)
        },
      })
    }
  }, [asset.cues, events, mode, options, speechEnabled, speaker, syncFromElement])

  const handleLoadedMetadata = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    setDuration(Number.isFinite(video.duration) ? video.duration : 0)
    setReady(true)
    setMediaError(null)
  }, [])

  const handleError = useCallback(() => {
    const video = videoRef.current
    const code = video?.error?.code
    setMediaError(
      code === 3
        ? 'The video file could not be decoded by this browser.'
        : code === 4
          ? 'The video source is not supported or the network blocked it.'
          : 'The video could not be loaded.',
    )
    setReady(false)
  }, [])

  const seekTo = useCallback((seconds: number) => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = Math.max(0, seconds)
    syncFromElement()
  }, [syncFromElement])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      void video.play().catch(() => {
        setMediaError('Playback was blocked by the browser. Press play to start.')
      })
    } else {
      video.pause()
    }
  }, [])

  // Native caption track built from the same cue data the companion uses.
  const trackUrl = useMemo(() => {
    if (asset.cues.length === 0) return null
    const vtt = toWebVtt(asset.cues)
    return URL.createObjectURL(new Blob([vtt], { type: 'text/vtt' }))
  }, [asset.cues])

  useEffect(() => {
    return () => {
      if (trackUrl) URL.revokeObjectURL(trackUrl)
    }
  }, [trackUrl])

  const reachedEvents = useMemo(() => eventsReached(events, currentTime), [events, currentTime])
  const currentEvent = useMemo(() => activeEvent(events, currentTime), [events, currentTime])
  const activeCue = activeCueIndex >= 0 ? (asset.cues[activeCueIndex] ?? null) : null
  const progress = useMemo(() => cueProgress(asset.cues, currentTime), [asset.cues, currentTime])

  return {
    videoRef,
    state: {
      currentTime,
      duration,
      paused,
      ready,
      mediaError,
      activeCueIndex,
      activeCueText: activeCue?.text ?? '',
      reachedEvents,
      currentEvent,
      progress,
      spokenNotice,
    } satisfies MovieState,
    events,
    trackUrl,
    seekTo,
    togglePlay,
    handleTimeUpdate,
    handleLoadedMetadata,
    handleError,
    totalCueTime: cueDuration(asset.cues),
    formatClock,
  }
}
