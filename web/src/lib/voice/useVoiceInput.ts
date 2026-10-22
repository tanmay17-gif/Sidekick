import { useCallback, useEffect, useRef, useState } from 'react'
import {
  isSpeechRecognitionSupported,
  queryMicrophonePermission,
  Recognizer,
  type RecognitionFailure,
} from './recognition'

export type VoiceStatus =
  | 'unsupported'
  | 'idle'
  | 'requesting'
  | 'listening'
  | 'denied'
  | 'error'

export interface UseVoiceInputOptions {
  /** Called once the recogniser produces a final transcript. */
  onFinal?: (transcript: string) => void
  lang?: string
  inactivityTimeoutMs?: number
}

export interface VoiceInputState {
  status: VoiceStatus
  supported: boolean
  /** Best guess of the current permission state, when the browser reports it. */
  permission: PermissionState | null
  /** Interim (still changing) transcript. */
  interim: string
  /** Last final transcript. */
  final: string
  error: RecognitionFailure | null
  start: () => void
  stop: () => void
  reset: () => void
}

export function useVoiceInput(options: UseVoiceInputOptions = {}): VoiceInputState {
  const supported = isSpeechRecognitionSupported()
  const [status, setStatus] = useState<VoiceStatus>(supported ? 'idle' : 'unsupported')
  const [permission, setPermission] = useState<PermissionState | null>(null)
  const [interim, setInterim] = useState('')
  const [final, setFinal] = useState('')
  const [error, setError] = useState<RecognitionFailure | null>(null)
  const recognizerRef = useRef<Recognizer | null>(null)
  const finalRef = useRef(options.onFinal)
  finalRef.current = options.onFinal

  useEffect(() => {
    if (!supported) return
    let cancelled = false
    void queryMicrophonePermission().then((state) => {
      if (!cancelled) setPermission(state)
    })
    return () => {
      cancelled = true
    }
  }, [supported])

  const stop = useCallback(() => {
    recognizerRef.current?.stop()
    recognizerRef.current = null
    setStatus((current) => (current === 'listening' ? 'idle' : current))
  }, [])

  const start = useCallback(() => {
    if (!supported) return
    setError(null)
    setStatus('requesting')
    setInterim('')

    const recognizer = new Recognizer({
      lang: options.lang,
      inactivityTimeoutMs: options.inactivityTimeoutMs ?? 12_000,
      callbacks: {
        onStart: () => setStatus('listening'),
        onResult: (result) => {
          if (result.isFinal) {
            const transcript = result.transcript.trim()
            setFinal(transcript)
            setInterim('')
            if (transcript) finalRef.current?.(transcript)
          } else {
            setInterim(result.transcript)
          }
        },
        onError: (failure) => {
          setError(failure)
          if (failure.code === 'not-allowed' || failure.code === 'service-not-allowed') {
            setStatus('denied')
            setPermission('denied')
          } else {
            setStatus('error')
          }
        },
        onEnd: () => {
          setStatus((current) => (current === 'listening' ? 'idle' : current))
        },
      },
    })
    recognizerRef.current = recognizer
    recognizer.start()
  }, [options.lang, options.inactivityTimeoutMs, supported])

  const reset = useCallback(() => {
    setError(null)
    setInterim('')
    setFinal('')
    setStatus(supported ? 'idle' : 'unsupported')
  }, [supported])

  useEffect(() => {
    return () => {
      recognizerRef.current?.abort()
      recognizerRef.current = null
    }
  }, [])

  return { status, supported, permission, interim, final, error, start, stop, reset }
}
