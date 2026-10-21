import { describe, expect, it, vi } from 'vitest'
import { chunkForSpeech, pickVoice, Speaker, waitForVoices } from '@/lib/voice/synthesis'
import {
  isSpeechRecognitionSupported,
  isSpeechSynthesisSupported,
  queryMicrophonePermission,
} from '@/lib/voice/recognition'

describe('chunkForSpeech', () => {
  it('keeps short text in one chunk', () => {
    expect(chunkForSpeech('Hello there.')).toEqual(['Hello there.'])
  })

  it('splits long text on sentence boundaries', () => {
    const text =
      'This is the first sentence and it is reasonably long. This is the second sentence which is also long enough to matter.'
    const chunks = chunkForSpeech(text, 60)
    expect(chunks.length).toBeGreaterThan(1)
    expect(chunks.join(' ')).toBe(text)
  })

  it('hard-splits a single very long sentence on word boundaries', () => {
    const text = 'word '.repeat(120).trim()
    const chunks = chunkForSpeech(text, 100)
    expect(chunks.length).toBeGreaterThan(1)
    for (const chunk of chunks) expect(chunk.length).toBeLessThanOrEqual(101)
  })

  it('returns nothing for empty text', () => {
    expect(chunkForSpeech('   ')).toEqual([])
  })
})

describe('speech capability detection', () => {
  it('reports the synthesis API as available in jsdom (installed by the test setup)', () => {
    expect(isSpeechSynthesisSupported()).toBe(true)
  })

  it('reports the recognition API as unavailable in jsdom', () => {
    expect(isSpeechRecognitionSupported()).toBe(false)
  })

  it('returns null when the browser cannot report microphone permission', async () => {
    await expect(queryMicrophonePermission()).resolves.toBeTypeOf('object')
  })

  it('resolves the voice list without hanging', async () => {
    await expect(waitForVoices(50)).resolves.toBeInstanceOf(Array)
  })

  it('returns null when there is no voice to use', () => {
    expect(pickVoice()).toBeNull()
  })
})

describe('Speaker', () => {
  it('settles when the engine never starts instead of staying stuck on "speaking"', async () => {
    const speaker = new Speaker()
    const onError = vi.fn()
    const onEnd = vi.fn()

    // The default test double never fires `onstart`.
    await speaker.speak('This should not hang the interface.', { onError, onEnd })

    expect(onError).toHaveBeenCalledWith(
      expect.stringContaining('No speech voice is available'),
    )
    expect(onEnd).toHaveBeenCalled()
    expect(speaker.isSpeaking).toBe(false)
  })

  it('reports a missing synthesis API instead of failing silently', async () => {
    const original = window.speechSynthesis
    // @ts-expect-error - removing a browser global on purpose
    delete window.speechSynthesis
    try {
      const speaker = new Speaker()
      const onError = vi.fn()
      await speaker.speak('hello', { onError })
      expect(onError).toHaveBeenCalledWith(
        expect.stringContaining('Speech output is not available'),
      )
    } finally {
      Object.defineProperty(window, 'speechSynthesis', {
        writable: true,
        configurable: true,
        value: original,
      })
    }
  })
})
