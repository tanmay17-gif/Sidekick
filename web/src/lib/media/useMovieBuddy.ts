import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MediaAsset, MediaCue } from '@/lib/api/types'
import { answerWhatJustHappened, explainTheMoment, type GroundedAnswer } from '@/lib/movie/buddy'
import { alignmentReport, type AlignmentReport } from '@/lib/movie/context'
import { BuddyEngine, type BuddyMode, type BuddyRemark, type RemarkDecision } from '@/lib/movie/engine'
import {
  createLocalProvider,
  createModelProvider,
  createUnavailableProvider,
  type CommentaryProvider,
  type CommentarySource,
} from '@/lib/movie/provider'
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
  remarks: BuddyRemark[]
  lastRemark: BuddyRemark | null
  lastDecision: RemarkDecision | null
  /** The answer to the viewer's last question, if any. */
  lastAnswer: GroundedAnswer | null
  /** Where the remarks come from. */
  source: CommentarySource
  providerId: string
  speaking: boolean
  /** How well the subtitles line up with this copy of the film. */
  alignment: AlignmentReport
}

export interface UseMovieBuddyOptions {
  asset: MediaAsset | null
  speaker: Speaker
  speechEnabled: boolean
  /** Overrides the provider - used by the tests. */
  provider?: CommentaryProvider
  onSay?: (text: string) => void
}

export interface UseMovieBuddyResult {
  videoRef: React.MutableRefObject<HTMLVideoElement | null>
  /** Attach this to the <video> element. */
  attachVideo: (element: HTMLVideoElement | null) => void
  player: PlayerState
  buddy: MovieBuddyState
  activeCueIndex: number
  activeCueText: string
  /** The caption cues that are actually loaded right now. */
  cues: MediaCue[]
  trackUrl: string | null
  trySpeak: (text: string) => void
  activate: () => void
  deactivate: () => void
  quiet: (ms?: number) => void
  resumeBuddy: () => void
  askWhatHappened: () => void
  askExplain: () => void
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
  handleCueChange: (cues: MediaCue[]) => void
  stageAspect: string
}

const QUIET_DEFAULT_MS = 60_000

/**
 * The model provider, if the team configured one.
 *
 * Without configuration the companion falls back to the local heuristic and
 * says so in the interface - it never claims a model wrote a remark.
 */
export function resolveProvider(override?: CommentaryProvider): CommentaryProvider {
  if (override) return override
  if (import.meta.env.MODE === 'test') {
    return createLocalProvider()
  }
  const endpoint =
    import.meta.env.VITE_SIDECKICK_COMMENTARY_ENDPOINT ||
    (import.meta.env.VITE_GROQ_API_KEY
      ? (import.meta.env.VITE_GROQ_API_ENDPOINT || 'https://api.groq.com/openai/v1/chat/completions')
      : undefined)
  if (endpoint) {
    return createModelProvider({
      endpoint,
      model:
        import.meta.env.VITE_SIDECKICK_COMMENTARY_MODEL ||
        import.meta.env.VITE_GROQ_MODEL ||
        'openai/gpt-oss-120b',
      apiKey: import.meta.env.VITE_SIDECKICK_COMMENTARY_API_KEY || import.meta.env.VITE_GROQ_API_KEY,
      timeoutMs: Number(import.meta.env.VITE_SIDECKICK_COMMENTARY_TIMEOUT_MS || 8000),
    })
  }
  return createLocalProvider()
}

export function useMovieBuddy(options: UseMovieBuddyOptions): UseMovieBuddyResult {
  const { asset, speaker, speechEnabled, provider, onSay } = options

  const videoRef = useRef<HTMLVideoElement | null>(null)
  /** A callback ref, so the video element is always reachable. */
  const attachVideo = useCallback((element: HTMLVideoElement | null) => {
    videoRef.current = element
  }, [])
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
  const [remarks, setRemarks] = useState<BuddyRemark[]>([])
  const [lastRemark, setLastRemark] = useState<BuddyRemark | null>(null)
  const [lastDecision, setLastDecision] = useState<RemarkDecision | null>(null)
  const [speaking, setSpeaking] = useState(false)
  const [cues, setCues] = useState<MediaCue[]>([])
  const [lastAnswer, setLastAnswer] = useState<GroundedAnswer | null>(null)
  /** Where the remarks come from - kept in state so the label stays honest. */
  const [source, setSource] = useState<CommentarySource>(() => resolveProvider(provider).source)
  const [providerId, setProviderId] = useState<string>(() => resolveProvider(provider).id)
  const inFlightRef = useRef<AbortController | null>(null)

  const engineRef = useRef<BuddyEngine | null>(null)
  if (engineRef.current === null) {
    engineRef.current = new BuddyEngine({ provider: resolveProvider(provider) })
  }
  const engine = engineRef.current

  // A new provider means a new engine.
  useEffect(() => {
    engineRef.current = new BuddyEngine({ provider: resolveProvider(provider) })
  }, [provider])

  // Load the film's captions. A film without a caption track gets a provider
  // that refuses, with the reason shown in the interface.
  useEffect(() => {
    const loaded = asset?.cues ?? []
    setCues(loaded)
    engine.reset()
    setRemarks([])
    setLastRemark(null)
    setLastDecision(null)
  }, [asset, engine])

  /**
   * A film with no usable subtitles gets a provider that refuses, so the
   * interface reports "unavailable" instead of pretending to have something
   * to say.
   */
  useEffect(() => {
    engine.setProvider(
      cues.length > 0
        ? resolveProvider(provider)
        : createUnavailableProvider(
            'This film has no caption track, so there is nothing to read. Load a subtitle file to switch the companion on.',
          ),
    )
    setSource(engine.source)
    setProviderId(engine.providerId)
  }, [cues, engine, provider])

  // A tick that keeps the quiet countdown honest.
  useEffect(() => {
    if (mode !== 'quiet') return
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [mode])

  const activeCueIndex = useMemo(
    () => findCueIndex(cues, player.currentTime),
    [cues, player.currentTime],
  )
  const activeCue = activeCueIndex >= 0 ? (cues[activeCueIndex] ?? null) : null
  const alignment = useMemo(
    () => alignmentReport(cues, player.duration),
    [cues, player.duration],
  )

  const trySpeak = useCallback(
    (text: string) => {
      if (!speechEnabled) return false
      setSpeaking(true)
      const video = videoRef.current
      if (video) video.volume = 0.2
      onSay?.(text)
      void speaker.speak(text, {
        onStart: () => {
          setSpeaking(true)
          if (videoRef.current) videoRef.current.volume = 0.2
        },
        onEnd: () => {
          setSpeaking(false)
          if (videoRef.current) videoRef.current.volume = 1.0
        },
        onError: () => {
          setSpeaking(false)
          if (videoRef.current) videoRef.current.volume = 1.0
        },
      })
      return true
    },
    [onSay, speaker, speechEnabled],
  )

  /**
   * Re-evaluate the moment.
   *
   * Called on every media time update, and again after a seek, a pause, a
   * resume or a subtitle change, so the companion is never reasoning about a
   * moment that has moved on.
   */
  const evaluate = useCallback(
    async (question?: string) => {
      const video = videoRef.current
      const currentTime = video ? video.currentTime : player.currentTime
      const captionOnScreen = findCueIndex(cues, currentTime) !== -1
      const controller = new AbortController()
      inFlightRef.current?.abort()
      inFlightRef.current = controller

      const decision = await engine.consider({
        mode,
        quietUntil,
        cues,
        currentTime,
        captionOnScreen,
        question,
        filmId: asset?.id,
        filmTitle: asset?.title,
        signal: controller.signal,
      })
      setLastDecision(decision)

      if (decision.kind === 'speak') {
        setRemarks((current) => [...current, decision.remark].slice(-24))
        setLastRemark(decision.remark)
        trySpeak(decision.remark.say)
      }
      return decision
    },
    [asset, cues, engine, mode, player.currentTime, quietUntil, trySpeak],
  )

  // The latest evaluator, without making the effects below depend on every
  // playback tick.
  const evaluateRef = useRef(evaluate)
  evaluateRef.current = evaluate

  /**
   * When the caption track changes the moment has to be looked at again, with
   * the new provider in place.
   */
  useEffect(() => {
    void evaluateRef.current()
  }, [cues])

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
    void evaluate()
  }, [evaluate, mode])

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

  const seekTo = useCallback(
    (seconds: number) => {
      const video = videoRef.current
      if (!video) return
      video.currentTime = Math.max(0, seconds)
      setPlayer((current) => ({ ...current, currentTime: video.currentTime }))
      // The moment moved: re-evaluate rather than reason about the old one.
      void evaluate()
    },
    [evaluate],
  )

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
    inFlightRef.current?.abort()
    speaker.cancel()
    setSpeaking(false)
  }, [speaker])

  const quiet = useCallback(
    (ms: number = QUIET_DEFAULT_MS) => {
      setMode('quiet')
      setQuietUntil(Date.now() + ms)
      setNow(Date.now())
      inFlightRef.current?.abort()
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

  const askWhatHappened = useCallback(async () => {
    const video = videoRef.current
    const currentTime = video ? video.currentTime : player.currentTime
    const fallback = answerWhatJustHappened(cues, currentTime)

    if (engine.source === 'model') {
      const decision = await evaluate('What just happened in this scene? Answer in a warm, lively buddy tone.')
      if (decision.kind === 'speak' && decision.remark.say) {
        setLastAnswer({
          say: decision.remark.say,
          basis: fallback.basis,
          unavailable: false,
        })
        return fallback
      }
    }

    setLastAnswer(fallback)
    const speakable = fallback.say.replace(/\s*That is what the captions show\.?/i, '')
    trySpeak(speakable)
    return fallback
  }, [cues, engine.source, evaluate, player.currentTime, trySpeak])

  const askExplain = useCallback(async () => {
    const video = videoRef.current
    const currentTime = video ? video.currentTime : player.currentTime
    const fallback = explainTheMoment(cues, currentTime)

    if (engine.source === 'model') {
      const decision = await evaluate('Explain what is happening in this moment in a cozy, fun, friendly way.')
      if (decision.kind === 'speak' && decision.remark.say) {
        setLastAnswer({
          say: decision.remark.say,
          basis: fallback.basis,
          unavailable: false,
        })
        return fallback
      }
    }

    setLastAnswer(fallback)
    const speakable = fallback.say.replace(/\s*I am reading the subtitle track, not the picture\.?/i, '')
    trySpeak(speakable)
    return fallback
  }, [cues, engine.source, evaluate, player.currentTime, trySpeak])

  /** Replace the caption track - used when the viewer loads their own file. */
  const handleCueChange = useCallback(
    (next: MediaCue[]) => {
      setCues(next)
      engine.reset()
      setRemarks([])
      setLastRemark(null)
      setLastDecision(null)
      void evaluate()
    },
    [engine, evaluate],
  )

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

  const buddy: MovieBuddyState = {
    mode,
    quietUntil,
    quietRemainingMs,
    remarks,
    lastRemark,
    lastDecision,
    lastAnswer,
    source,
    providerId,
    speaking,
    alignment,
  }

  return {
    videoRef,
    attachVideo,
    player,
    buddy,
    activeCueIndex,
    activeCueText: activeCue?.text ?? '',
    cues,
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
    handleCueChange,
    stageAspect: asset?.aspect_ratio ?? '16 / 9',
  }
}
