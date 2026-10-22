/**
 * Real speech output wrapper built on the Web Speech Synthesis API.
 *
 * Handles the two failure modes that matter in practice:
 *  - Chrome stops long utterances after ~15s, so text is chunked by sentence.
 *  - Some browsers require a user gesture before the first utterance.
 */

export interface SpeakOptions {
  onStart?: () => void
  onEnd?: () => void
  onError?: (message: string) => void
  /** Preferred voice name or language tag. */
  voiceHint?: string
  rate?: number
  pitch?: number
}

export interface VoiceDescriptor {
  name: string
  lang: string
  default: boolean
}

export function listVoices(): VoiceDescriptor[] {
  if (typeof window === 'undefined' || !window.speechSynthesis) return []
  return window.speechSynthesis.getVoices().map((voice) => ({
    name: voice.name,
    lang: voice.lang,
    default: voice.default,
  }))
}

/**
 * Voices populate asynchronously in Chromium. Resolves once the list is
 * available or the timeout elapses.
 */
export function waitForVoices(timeoutMs = 1500): Promise<VoiceDescriptor[]> {
  if (typeof window === 'undefined' || !window.speechSynthesis) return Promise.resolve([])
  const immediate = window.speechSynthesis.getVoices()
  if (immediate.length > 0) return Promise.resolve(listVoices())

  return new Promise((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      window.speechSynthesis.removeEventListener('voiceschanged', finish)
      resolve(listVoices())
    }
    window.speechSynthesis.addEventListener('voiceschanged', finish)
    setTimeout(finish, timeoutMs)
  })
}

export function pickVoice(hint?: string): SpeechSynthesisVoice | null {
  if (typeof window === 'undefined' || !window.speechSynthesis) return null
  const voices = window.speechSynthesis.getVoices()
  if (voices.length === 0) return null
  if (hint) {
    const exact = voices.find((voice) => voice.name === hint)
    if (exact) return exact
    const byLang = voices.find((voice) => voice.lang === hint)
    if (byLang) return byLang
  }
  const preferredLangs = ['en-US', 'en-GB', 'en']
  for (const lang of preferredLangs) {
    const match = voices.find((voice) => voice.lang === lang && voice.default)
    if (match) return match
    const anyMatch = voices.find((voice) => voice.lang === lang)
    if (anyMatch) return anyMatch
  }
  return voices.find((voice) => voice.default) ?? voices[0] ?? null
}

/** Split text into utterance-sized chunks (<= ~180 characters). */
export function chunkForSpeech(text: string, maxChars = 180): string[] {
  const clean = text.replace(/\s+/g, ' ').trim()
  if (!clean) return []
  if (clean.length <= maxChars) return [clean]

  const sentences = clean.split(/(?<=[.!?])\s+/)
  const chunks: string[] = []
  let current = ''
  for (const sentence of sentences) {
    if (sentence.length > maxChars) {
      if (current) {
        chunks.push(current)
        current = ''
      }
      // Hard-split very long sentences on word boundaries.
      let remainder = sentence
      while (remainder.length > maxChars) {
        const cut = remainder.lastIndexOf(' ', maxChars)
        const safeCut = cut > 40 ? cut : maxChars
        chunks.push(remainder.slice(0, safeCut))
        remainder = remainder.slice(safeCut).trimStart()
      }
      if (remainder) current = remainder
      continue
    }
    if ((current + ' ' + sentence).trim().length > maxChars) {
      chunks.push(current.trim())
      current = sentence
    } else {
      current = (current + ' ' + sentence).trim()
    }
  }
  if (current.trim()) chunks.push(current.trim())
  return chunks
}

export class Speaker {
  private speaking = false
  private cancelled = false

  get isSpeaking(): boolean {
    return this.speaking
  }

  /** Speak text, chunked. Resolves when all chunks finish or `cancel()` runs. */
  speak(text: string, options: SpeakOptions = {}): Promise<void> {
    if (typeof window === 'undefined' || !window.speechSynthesis) {
      options.onError?.('Speech output is not available in this browser.')
      return Promise.resolve()
    }
    const chunks = chunkForSpeech(text)
    if (chunks.length === 0) return Promise.resolve()

    this.cancel()
    this.cancelled = false
    this.speaking = true
    options.onStart?.()

    const voice = pickVoice(options.voiceHint)
    const rate = options.rate ?? 1.02

    return new Promise<void>((resolve) => {
      let index = 0
      let started = false
      let settled = false

      const finish = () => {
        if (settled) return
        settled = true
        clearTimeout(startWatchdog)
        clearTimeout(endWatchdog)
        this.speaking = false
        options.onEnd?.()
        resolve()
      }

      // If the engine never starts (no installed voice, blocked by the OS) the
      // promise must still settle, otherwise the UI would stay stuck on
      // "speaking" forever.
      const startWatchdog = setTimeout(() => {
        if (started) return
        this.cancelled = true
        try {
          window.speechSynthesis.cancel()
        } catch {
          /* nothing queued */
        }
        options.onError?.('No speech voice is available in this browser.')
        finish()
      }, 1800)

      let endWatchdog: ReturnType<typeof setTimeout> = setTimeout(() => {
        /* replaced once speech starts */
      }, 0)
      clearTimeout(endWatchdog)

      const speakNext = () => {
        if (this.cancelled || settled) {
          finish()
          return
        }
        const chunk = chunks[index]
        if (chunk === undefined) {
          finish()
          return
        }
        index += 1
        const utterance = new SpeechSynthesisUtterance(chunk)
        if (voice) utterance.voice = voice
        utterance.rate = rate
        utterance.pitch = options.pitch ?? 1
        utterance.onstart = () => {
          started = true
          clearTimeout(startWatchdog)
          // Rough upper bound on how long the chunk can take, plus padding.
          const budget = Math.max(4000, (chunk.length / (12 * rate)) * 1000 + 3000)
          endWatchdog = setTimeout(() => {
            try {
              window.speechSynthesis.cancel()
            } catch {
              /* nothing queued */
            }
            finish()
          }, budget)
        }
        utterance.onerror = (event) => {
          const reason = (event as SpeechSynthesisErrorEvent).error
          // `interrupted`/`canceled` happen on purpose when we cancel.
          if (reason === 'interrupted' || reason === 'canceled') {
            finish()
            return
          }
          options.onError?.(`Speech output failed (${reason}).`)
          finish()
        }
        utterance.onend = () => {
          clearTimeout(endWatchdog)
          speakNext()
        }
        window.speechSynthesis.speak(utterance)
      }
      speakNext()
    })
  }

  /** Stop any in-flight speech (used for barge-in). */
  cancel(): void {
    if (typeof window === 'undefined' || !window.speechSynthesis) return
    this.cancelled = true
    try {
      window.speechSynthesis.cancel()
    } catch {
      /* nothing queued */
    }
    this.speaking = false
  }
}
