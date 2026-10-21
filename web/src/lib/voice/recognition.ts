/**
 * Real speech recognition wrapper.
 *
 * Uses the browser's Web Speech API (`SpeechRecognition` / `webkitSpeechRecognition`).
 * This is genuine microphone input where the browser supports it, and it is
 * explicitly *not* an Alexa+ integration - see docs/EXPERIENCE.md.
 */

export type RecognitionErrorCode =
  | 'not-allowed'
  | 'service-not-allowed'
  | 'audio-capture'
  | 'no-speech'
  | 'network'
  | 'aborted'
  | 'language-not-supported'
  | 'unknown'

export interface RecognitionFailure {
  code: RecognitionErrorCode
  message: string
  /** True when the user can fix it by granting permission. */
  recoverable: boolean
}

export interface RecognitionResult {
  transcript: string
  isFinal: boolean
  confidence: number
}

export interface RecognitionCallbacks {
  onStart?: () => void
  onResult?: (result: RecognitionResult) => void
  onError?: (failure: RecognitionFailure) => void
  onEnd?: () => void
}

export interface RecognitionOptions {
  lang?: string
  /** Stop after this many seconds without any speech. */
  inactivityTimeoutMs?: number
  callbacks?: RecognitionCallbacks
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

interface SpeechRecognitionLike extends EventTarget {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start(): void
  stop(): void
  abort(): void
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: ((event: { error: string; message?: string }) => void) | null
  onend: (() => void) | null
  onstart: (() => void) | null
  onaudiostart: (() => void) | null
  onnomatch: (() => void) | null
}

interface SpeechRecognitionEventLike {
  resultIndex: number
  results: ArrayLike<{
    isFinal: boolean
    length: number
    [index: number]: { transcript: string; confidence: number }
  }>
}

const FAILURES: Record<RecognitionErrorCode, RecognitionFailure> = {
  'not-allowed': {
    code: 'not-allowed',
    message: 'Microphone access was denied. Allow it in the browser address bar, then try again.',
    recoverable: true,
  },
  'service-not-allowed': {
    code: 'service-not-allowed',
    message:
      'The browser blocked the speech service. It is often caused by a private window or a blocked third-party script.',
    recoverable: true,
  },
  'audio-capture': {
    code: 'audio-capture',
    message: 'No microphone was found. Connect an input device and try again.',
    recoverable: true,
  },
  'no-speech': {
    code: 'no-speech',
    message: 'Nothing was heard. Try again, or type the request instead.',
    recoverable: true,
  },
  network: {
    code: 'network',
    message: 'The speech service could not be reached. The request was not sent.',
    recoverable: true,
  },
  aborted: {
    code: 'aborted',
    message: 'Listening was cancelled.',
    recoverable: true,
  },
  'language-not-supported': {
    code: 'language-not-supported',
    message: 'This language is not supported by the browser speech service.',
    recoverable: true,
  },
  unknown: {
    code: 'unknown',
    message: 'Speech recognition failed for an unknown reason.',
    recoverable: true,
  },
}

export function isSpeechRecognitionSupported(): boolean {
  if (typeof window === 'undefined') return false
  return 'SpeechRecognition' in window || 'webkitSpeechRecognition' in window
}

export function isSpeechSynthesisSupported(): boolean {
  if (typeof window === 'undefined') return false
  return 'speechSynthesis' in window && typeof window.speechSynthesis.speak === 'function'
}

/**
 * Ask for the current microphone permission state when the browser exposes
 * the Permissions API. Returns null when the browser cannot answer.
 */
export async function queryMicrophonePermission(): Promise<PermissionState | null> {
  if (typeof navigator === 'undefined' || !navigator.permissions?.query) return null
  try {
    const status = await navigator.permissions.query({
      name: 'microphone' as PermissionName,
    })
    return status.state
  } catch {
    // Firefox and Safari do not expose the microphone descriptor.
    return null
  }
}

/** A live recognition session. */
export class Recognizer {
  private recognition: SpeechRecognitionLike | null = null
  private inactivityTimer: ReturnType<typeof setTimeout> | null = null
  private stopped = false
  private started = false

  constructor(private readonly options: RecognitionOptions = {}) {}

  start(): void {
    if (this.started) return
    const ctor = getRecognitionCtor()
    if (!ctor) {
      this.options.callbacks?.onError?.({
        code: 'unknown',
        message:
          'This browser does not expose a speech recognition engine. Use the text field instead.',
        recoverable: false,
      })
      return
    }

    this.started = true
    this.stopped = false

    const recognition = new ctor()
    recognition.lang = this.options.lang ?? pickLanguage()
    recognition.continuous = false
    recognition.interimResults = true
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      this.options.callbacks?.onStart?.()
      this.armInactivityTimer()
    }

    recognition.onresult = (event) => {
      this.armInactivityTimer()
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index]
        if (!result) continue
        const alternative = result[0]
        if (!alternative) continue
        this.options.callbacks?.onResult?.({
          transcript: alternative.transcript,
          isFinal: result.isFinal,
          confidence: alternative.confidence,
        })
      }
    }

    recognition.onerror = (event) => {
      const code = normaliseErrorCode(event.error)
      this.options.callbacks?.onError?.(FAILURES[code])
    }

    recognition.onend = () => {
      this.clearInactivityTimer()
      this.started = false
      if (!this.stopped) {
        this.options.callbacks?.onEnd?.()
      }
      this.stopped = false
    }

    this.recognition = recognition
    try {
      recognition.start()
    } catch {
      // start() throws when a previous session is still running.
      this.started = false
      this.options.callbacks?.onError?.({
        code: 'unknown',
        message: 'The microphone is already in use by another application.',
        recoverable: true,
      })
    }
  }

  /** Stop cleanly and keep whatever was recognised. */
  stop(): void {
    this.stopped = true
    this.clearInactivityTimer()
    try {
      this.recognition?.stop()
    } catch {
      /* already stopped */
    }
  }

  /** Cancel and discard the session. */
  abort(): void {
    this.stopped = true
    this.clearInactivityTimer()
    try {
      this.recognition?.abort()
    } catch {
      /* already stopped */
    }
  }

  private armInactivityTimer(): void {
    this.clearInactivityTimer()
    const limit = this.options.inactivityTimeoutMs
    if (!limit) return
    this.inactivityTimer = setTimeout(() => {
      this.stop()
      this.options.callbacks?.onError?.({
        code: 'no-speech',
        message: `No speech detected within ${Math.round(limit / 1000)} seconds.`,
        recoverable: true,
      })
    }, limit)
  }

  private clearInactivityTimer(): void {
    if (this.inactivityTimer !== null) {
      clearTimeout(this.inactivityTimer)
      this.inactivityTimer = null
    }
  }
}

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null
  const w = window as unknown as Record<string, unknown>
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null) as SpeechRecognitionCtor | null
}

function normaliseErrorCode(raw: string): RecognitionErrorCode {
  switch (raw) {
    case 'not-allowed':
    case 'service-not-allowed':
    case 'audio-capture':
    case 'no-speech':
    case 'network':
    case 'aborted':
    case 'language-not-supported':
      return raw
    default:
      return 'unknown'
  }
}

/** Prefer the user's language, but only if the browser likely supports it. */
export function pickLanguage(): string {
  if (typeof navigator === 'undefined') return 'en-US'
  return navigator.language || 'en-US'
}
