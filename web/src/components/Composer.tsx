import { useEffect, useRef, useState } from 'react'
import type { VoiceInputState } from '@/lib/voice/useVoiceInput'
import { MicIcon, MicOffIcon, SendIcon, SpeakIcon, StopIcon } from './icons'

export interface ComposerProps {
  voice: VoiceInputState
  /** True while a request is in flight. */
  busy: boolean
  /** True while the app is speaking; the mic then acts as an interrupt. */
  speaking: boolean
  /** Message from the speech engine, shown honestly instead of being swallowed. */
  speechNotice?: string | null
  speechEnabled: boolean
  onToggleSpeech: (next: boolean) => void
  onSubmit: (text: string, source: 'voice' | 'text') => void
  onInterrupt: () => void
  disabled?: boolean
  /**
   * Hide the composer's own microphone. Interface A shows one large,
   * prominent microphone of its own, and two of them is confusing.
   */
  showMic?: boolean
}

export function Composer({
  voice,
  busy,
  speaking,
  speechNotice,
  speechEnabled,
  onToggleSpeech,
  onSubmit,
  onInterrupt,
  disabled,
  showMic = true,
}: ComposerProps) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  // Grow the composer with its content, up to a maximum height.
  useEffect(() => {
    const node = textareaRef.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${Math.min(node.scrollHeight, 180)}px`
  }, [text])

  const submit = () => {
    const value = text.trim()
    if (!value || disabled) return
    onSubmit(value, 'text')
    setText('')
  }

  const micMode = speaking ? 'speaking' : voice.status === 'listening' ? 'listening' : 'idle'
  const micDisabled = disabled || voice.status === 'unsupported'

  const micLabel = speaking
    ? 'Interrupt speech output'
    : voice.status === 'listening'
      ? 'Stop listening'
      : voice.status === 'unsupported'
        ? 'Voice input is not available in this browser'
        : 'Start voice input'

  return (
    <div className="composer-block">
      <form
        className="composer"
        data-listening={voice.status === 'listening'}
        data-busy={busy}
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        {showMic ? (
          <button
            type="button"
            className="mic"
            data-mode={voice.status === 'unsupported' ? 'unavailable' : micMode}
            disabled={micDisabled}
            aria-label={micLabel}
            title={micLabel}
            onClick={() => {
              if (speaking) {
                onInterrupt()
                return
              }
              if (voice.status === 'listening') voice.stop()
              else voice.start()
            }}
          >
            <span className="mic__pulse" aria-hidden="true" />
            {voice.status === 'unsupported' ? <MicOffIcon size={18} /> : <MicIcon size={18} />}
          </button>
        ) : null}

        <label className="sr-only" htmlFor="composer-input">
          Your request
        </label>
        <textarea
          id="composer-input"
          ref={textareaRef}
          className="composer__input"
          rows={1}
          value={text}
          placeholder={
            voice.status === 'unsupported'
              ? 'Voice input unavailable here - type your request'
              : 'Speak or type your request'
          }
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
        />

        <button type="submit" className="btn btn--primary" disabled={!text.trim() || disabled}>
          <SendIcon size={15} />
          Send
        </button>
      </form>

      <div className="composer__meta">
        <span
          className="composer__transcript"
          data-interim={voice.interim.length > 0}
          aria-live="polite"
        >
          {voice.interim
            ? voice.interim
            : voice.final
              ? voice.final
              : voice.status === 'listening'
                ? 'Listening...'
                : ''}
        </span>

        <span className="row" style={{ gap: 'var(--space-2)' }}>
          <span className="badge badge--quiet">
            {voice.status === 'unsupported' ? 'text only' : 'voice + text'}
          </span>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            aria-pressed={speechEnabled}
            onClick={() => onToggleSpeech(!speechEnabled)}
            title={speechEnabled ? 'Spoken responses on' : 'Spoken responses off'}
          >
            <SpeakIcon size={14} />
            {speechEnabled ? 'Voice on' : 'Voice off'}
          </button>
        </span>
      </div>

      {voice.error ? (
        <p className="hint hint--warn" role="status" style={{ marginTop: 'var(--space-2)' }}>
          {voice.error.message}
        </p>
      ) : null}

      {speechNotice ? (
        <p className="hint hint--warn" role="status" style={{ marginTop: 'var(--space-2)' }}>
          {speechNotice} Responses are shown as text instead.
        </p>
      ) : null}

      {speaking ? (
        <p className="hint" role="status" style={{ marginTop: 'var(--space-2)' }}>
          Speaking - press the microphone button to interrupt.
        </p>
      ) : null}
    </div>
  )
}

export function BusyIndicator({ busy }: { busy: boolean }) {
  if (!busy) return null
  return (
    <span className="row" style={{ gap: 'var(--space-2)', fontSize: 'var(--text-xs)' }}>
      <StopIcon size={12} />
      <span>Working</span>
    </span>
  )
}
