import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MediaAsset, MediaCue } from '@/lib/api/types'
import {
  answerWhatJustHappened,
  canSpeak,
  DEFAULT_BUDGET,
  pushContext,
  reactToCue,
  type BuddyMode,
  type BuddyReaction,
  type GroundedAnswer,
  type SpeakingGate,
} from '@/lib/movie/buddy'
import { findCueIndex } from '@/lib/media/cues'
import { toWebVtt } from '@/lib/media/subtitles'
import type { Speaker } from '@/lib/voice/synthesis'

export interface PlayerState {
  currentTime: number
  duration: number
  paused: boolean
  buffering: boolean
  ended: boolean
  rate: number
  ready: boolean
  mediaError: string | null
}

export interface MovieBuddyState {
  mode: BuddyMode
  quietUntil: number
  quietRemainingMs: number
  reactions: BuddyReaction[]
  lastReaction: BuddyReaction | null
  lastAnswer: GroundedAnswer | null
  /** Why the last reaction fired - the actual trigger, not a rationale. */
  lastTrigger: string | null
  speaking: boolean
  contextSize: number
}

export interface UseMovieBuddyOptions {
  asset: MediaAsset | null
  speaker: Speaker
  speechEnabled: boolean
  onSay?: (text: string) => void
}

export interface UseMovieBuddyResult {
  videoRef: React.RefObject<HTMLVideoElement>
  player: PlayerState
  buddy: MovieBuddyState
  activeCueIndex: number
  activeCueText: string
  trackUrl: string | null
  /** The aspect ratio the stage should use for this film. */
  stageAspect: string
  /** Speak a line now, honouring the budget, the cooldown and the captions. */
  trySpeak: (text: string) => void
  activate: () => void
  deactivate: () => void
  quiet: (ms?: number) => void
  resumeBuddy: () => void
  askWhatHappened: () => GroundedAnswer
  askExplain: () => GroundedAnswer
  togglePlay: () => void
  seekBy: (seconds: number) => void
  seekTo: (seconds: number) => void
  setRate: (rate: number) => void
  handleTimeUpdate: () => void
  handleLoadedMetadata: () => void
  handleError: () => void
  handleWaiting: () => void
  handlePlaying: () => void
  handleEnded: () => void
  lastGate: SpeakingGate | null
}

const QUIET_DEFAULT_MS = 60_000
const SPEECH_WINDOW_MS = 60_000

export function useMovieBuddy(options: UseMovieBuddyOptions): UseMovieBuddyResult {
  const { asset, speaker, speechEnabled } = options

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [player, setPlayer] = useState<PlayerState>({
    currentTime: 0,
    duration: 0,
    paused: true,
    buffering: false,
    ended: false,
    rate: 1,
    ready: false,
    mediaError: null,
  })

  const [mode, setMode] = useState<BuddyMode>('off')
  const [quietUntil, setQuietUntil] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const [reactions, setReactions] = useState<BuddyReaction[]>([])
  const [lastReaction, setLastReaction] = useState<BuddyReaction | null>(null)
  const [lastAnswer, setLastAnswer] = useState<GroundedAnswer | null>(null)
  const [speaking, setSpeaking] = useState(false)
  const [lastGate, setLastGate] = useState<SpeakingGate | null>(null)

  const contextRef = useRef<MediaCue[]>([])
  const lastCueIndexRef = useRef(-1)
  const lastSpokeAtRef = useRef<number | null>(null)
  const spokenCountRef = useRef(0)
  const windowStartRef = useRef(Date.now())

  const cues = useMemo(() => asset?.cues ?? [], [asset])

  // Reset everything when the film changes.
  useEffect(() => {
    contextRef.current = []
    lastCueIndexRef.current = -1
    lastSpokeAtRef.current = null
    spokenCountRef.current = 0
    windowStartRef.current = Date.now()
    setReactions([])
    setLastReaction(null)
    setLastAnswer(null)
    setPlayer((current) => ({
      ...current,
      currentTime: 0,
      paused: true,
      ended: false,
      mediaError: null,
      ready: false,
    }))
  }, [asset?.id])

  // A tick that keeps the quiet countdown honest.
  useEffect(() => {
    if (mode !== 'quiet') return
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [mode])

  const activeCueIndex = useMemo(() => findCueIndex(cues, player.currentTime), [cues, player.currentTime])
  const activeCue = activeCueIndex >= 0 ? (cues[activeCueIndex] ?? null) : null

  const trySpeak = useCallback(
    (text: string) => {
      const timestamp = Date.now()
      // Keep the speaking window fresh.
      if (timestamp - windowStartRef.current > SPEECH_WINDOW_MS) {
        windowStartRef.current = timestamp
        spokenCountRef.current = 0
      }

      const gate = canSpeak({
        mode,
        quietUntil,
        now: timestamp,
        lastSpokeAt: lastSpokeAtRef.current,
        spokenInWindow: spokenCountRef.current,
        settings: DEFAULT_BUDGET,
        captionOnScreen: activeCue !== null,
      })
      setLastGate(gate)

      if (!gate.allowed) return false
      if (!speechEnabled) return false

      lastSpokeAtRef.current = timestamp
      spokenCountRef.current += 1
      setSpeaking(true)
      options.onSay?.(text)
      void speaker.speak(text, {
        onStart: () => setSpeaking(true),
        onEnd: () => setSpeaking(false),
        onError: () => setSpeaking(false),
      })
      return true
    },
    [activeCue, mode, options, quietUntil, speechEnabled, speaker],
  )

  const handleTimeUpdate = useCallback(() => {
    const video = videoRef.current
    if (!video) return

    const time = video.currentTime
    setPlayer((current) => ({
      ...current,
      currentTime: time,
      paused: video.paused,
      ended: video.ended,
      duration: Number.isFinite(video.duration) ? video.duration : current.duration,
    }))

    if (mode === 'off') return

    const index = findCueIndex(cues, time)
    if (index === -1 || index === lastCueIndexRef.current) return
    lastCueIndexRef.current = index

    const cue = cues[index]
    if (!cue) return

    contextRef.current = pushContext(contextRef.current, cue, DEFAULT_BUDGET.contextSize)

    const isLast = index === cues.length - 1
    const reaction = reactToCue(cue, contextRef.current.slice(0, -1), isLast)
    if (!reaction) return

    setReactions((current) => [...current, reaction].slice(-24))
    setLastReaction(reaction)
    trySpeak(reaction.say)
  }, [cues, mode, trySpeak])

  const handleLoadedMetadata = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    setPlayer((current) => ({
      ...current,
      duration: Number.isFinite(video.duration) ? video.duration : 0,
      ready: true,
      mediaError: null,
    }))
  }, [])

  const handleError = useCallback(() => {
    const video = videoRef.current
    const code = video?.error?.code
    // When the media element has <source> children the error is reported
    // through the network state, not through `error`.
    const noSource = video?.networkState === 3
    setPlayer((current) => ({
      ...current,
      ready: false,
      mediaError:
        code === 3
          ? 'This browser cannot decode that video file.'
          : code === 4
            ? 'The video source is not supported or the network blocked it.'
            : noSource
              ? 'None of the available video formats could be played.'
              : 'The video could not be loaded.',
    }))
  }, [])

  const handleWaiting = useCallback(() => {
    setPlayer((current) => ({ ...current, buffering: true }))
  }, [])

  const handlePlaying = useCallback(() => {
    setPlayer((current) => ({ ...current, buffering: false, paused: false, ended: false }))
  }, [])

  const handleEnded = useCallback(() => {
    setPlayer((current) => ({ ...current, ended: true, paused: true, buffering: false }))
  }, [])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      void video.play().catch(() => {
        setPlayer((current) => ({
          ...current,
          mediaError: 'Playback was blocked by the browser. Press play to start.',
        }))
      })
    } else {
      video.pause()
    }
  }, [])

  const seekTo = useCallback((seconds: number) => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = Math.max(0, seconds)
    setPlayer((current) => ({ ...current, currentTime: video.currentTime }))
    // A seek resets the cue tracker so the new position is evaluated fresh.
    lastCueIndexRef.current = -1
  }, [])

  const seekBy = useCallback(
    (seconds: number) => {
      const video = videoRef.current
      if (!video) return
      seekTo(video.currentTime + seconds)
    },
    [seekTo],
  )

  const setRate = useCallback((rate: number) => {
    const video = videoRef.current
    if (!video) return
    video.playbackRate = rate
    setPlayer((current) => ({ ...current, rate }))
  }, [])

  const activate = useCallback(() => {
    setMode('active')
    setQuietUntil(0)
    setNow(Date.now())
  }, [])

  const deactivate = useCallback(() => {
    setMode('off')
    setQuietUntil(0)
    speaker.cancel()
    setSpeaking(false)
  }, [speaker])

  const quiet = useCallback(
    (ms: number = QUIET_DEFAULT_MS) => {
      setMode('quiet')
      setQuietUntil(Date.now() + ms)
      setNow(Date.now())
      speaker.cancel()
      setSpeaking(false)
    },
    [speaker],
  )

  const resumeBuddy = useCallback(() => {
    setMode('active')
    setQuietUntil(0)
    setNow(Date.now())
  }, [])

  const askWhatHappened = useCallback(() => {
    const answer = answerWhatJustHappened(contextRef.current, player.currentTime)
    setLastAnswer(answer)
    trySpeak(answer.say)
    return answer
  }, [player.currentTime, trySpeak])

  const askExplain = useCallback(() => {
    const spoken = contextRef.current.filter(
      (cue) => player.currentTime - cue.end <= 20 && cue.end > 0 && cue.text.trim().length > 0,
    )
    const answer: GroundedAnswer =
      spoken.length === 0
        ? {
            say: 'I cannot explain that moment. There is no caption line covering it, and I do not analyse the picture.',
            basis: [],
            unavailable: true,
            reason: 'No caption cue covers the moment, and this build has no visual analysis.',
          }
        : {
            say: `From the captions: ${spoken.map((cue) => cue.text.trim()).join(' ')} I am reading the subtitle track, not the picture.`,
            basis: spoken,
            unavailable: false,
          }
    setLastAnswer(answer)
    trySpeak(answer.say)
    return answer
  }, [player.currentTime, trySpeak])

  const trackUrl = useMemo(() => {
    if (cues.length === 0) return null
    const vtt = toWebVtt(cues)
    return URL.createObjectURL(new Blob([vtt], { type: 'text/vtt' }))
  }, [cues])

  useEffect(() => {
    return () => {
      if (trackUrl) URL.revokeObjectURL(trackUrl)
    }
  }, [trackUrl])


  const quietRemainingMs = Math.max(0, quietUntil - now)

  return {
    videoRef,
    player,
    buddy: {
      mode,
      quietUntil,
      quietRemainingMs,
      reactions,
      lastReaction,
      lastAnswer,
      lastTrigger: lastReaction?.reason ?? null,
      speaking,
      contextSize: contextRef.current.length,
    },
    activeCueIndex,
    activeCueText: activeCue?.text ?? '',
    trackUrl,
    trySpeak,
    activate,
    deactivate,
    quiet,
    resumeBuddy,
    askWhatHappened,
    askExplain,
    togglePlay,
    seekBy,
    seekTo,
    setRate,
    handleTimeUpdate,
    handleLoadedMetadata,
    handleError,
    handleWaiting,
    handlePlaying,
    handleEnded,
    lastGate,
    stageAspect: asset?.aspect_ratio ?? '16 / 9',
  }
}
