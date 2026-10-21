import type { ReactNode } from 'react'
import type { Action, ActionState, ProgressEvent, SidekickResponse } from '@/lib/api/types'
import { AlertIcon, CheckIcon, ChatIcon, MicIcon } from './icons'
import { Dot } from './ui'

const STATE_TONE: Record<ActionState, Parameters<typeof Dot>[0]['tone']> = {
  pending: 'muted',
  awaiting_confirmation: 'confirm',
  running: 'executing',
  paused: 'muted',
  succeeded: 'success',
  failed: 'danger',
  cancelled: 'muted',
  superseded: 'muted',
}

const STATE_LABEL: Record<ActionState, string> = {
  pending: 'pending',
  awaiting_confirmation: 'needs confirmation',
  running: 'running',
  paused: 'paused',
  succeeded: 'done',
  failed: 'failed',
  cancelled: 'cancelled',
  superseded: 'superseded',
}

/** Turn level states, added to the contract alongside the action lifecycle. */
const RESPONSE_LABEL: Record<string, { label: string; tone: Parameters<typeof Dot>[0]['tone'] }> = {
  needs_clarification: { label: 'needs clarification', tone: 'confirm' },
  awaiting_transcript: { label: 'awaiting transcript', tone: 'thinking' },
}

export function StatusDot({ tone }: { tone: Parameters<typeof Dot>[0]['tone'] }) {
  return <Dot tone={tone} />
}

function toneForAction(state: string): Parameters<typeof Dot>[0]['tone'] {
  return (STATE_TONE as Record<string, Parameters<typeof Dot>[0]['tone']>)[state] ?? 'muted'
}

function labelForAction(state: string): string {
  return (STATE_LABEL as Record<string, string>)[state] ?? state
}

export interface ConversationProps {
  turns: Array<{
    id: string
    role: 'user' | 'assistant'
    inputSource: 'voice' | 'text'
    utterance: string
    response?: SidekickResponse
    error?: { code: string; message: string; retryable: boolean; timeout: boolean }
    events: ProgressEvent[]
    createdAt: string
  }>
  onChooseOption?: (option: string) => void
  onRetry?: () => void
}

export function Conversation({ turns, onChooseOption, onRetry }: ConversationProps) {
  return (
    <div className="turns">
      {turns.map((turn) =>
        turn.role === 'user' ? (
          <article className="turn" key={turn.id}>
            <div className="turn__who">
              {turn.inputSource === 'voice' ? <MicIcon size={12} /> : <ChatIcon size={12} />}
              You
              <span style={{ textTransform: 'none', letterSpacing: 0 }}>
                · {turn.inputSource}
              </span>
            </div>
            <p className={`turn__utterance${turn.inputSource === 'voice' ? ' turn__utterance--voice' : ''}`}>
              {turn.utterance}
            </p>
          </article>
        ) : (
          <AssistantTurn
            key={turn.id}
            turn={turn}
            onChooseOption={onChooseOption}
            onRetry={onRetry}
          />
        ),
      )}
    </div>
  )
}

function AssistantTurn({
  turn,
  onChooseOption,
  onRetry,
}: {
  turn: {
    response?: SidekickResponse
    error?: { code: string; message: string; retryable: boolean; timeout: boolean }
    events: ProgressEvent[]
    utterance: string
  }
  onChooseOption?: (option: string) => void
  onRetry?: () => void
}) {
  if (turn.error) {
    return (
      <article className="turn">
        <div className="turn__who">
          <AlertIcon size={12} />
          Sidekick
        </div>
        <div className="bubble bubble--error">
          <div className="bubble__body">{turn.error.message}</div>
          <div className="bubble__meta">
            <span>
              code <b>{turn.error.code}</b>
            </span>
            {turn.error.timeout ? <span>timed out</span> : null}
            {turn.error.retryable && onRetry ? (
              <button type="button" className="btn btn--sm" onClick={onRetry}>
                Retry
              </button>
            ) : null}
          </div>
        </div>
      </article>
    )
  }

  const response = turn.response
  if (!response) {
    return (
      <article className="turn">
        <div className="turn__who">
          <StatusDot tone="thinking" />
          Sidekick
        </div>
        <div className="bubble bubble--assistant">
          <p className="bubble__body">Working on it...</p>
        </div>
      </article>
    )
  }

  const responseStatus = RESPONSE_LABEL[response.status]
  const statusTone = responseStatus?.tone ?? toneForAction(response.status)
  const statusLabel = responseStatus?.label ?? labelForAction(response.status)

  return (
    <article className="turn">
      <div className="turn__who">
        <StatusDot tone={statusTone} />
        Sidekick
        <span style={{ textTransform: 'none', letterSpacing: 0 }}>· {statusLabel}</span>
      </div>

      {response.clarification ? (
        <div className="ask">
          <p className="ask__question">{response.clarification.question}</p>
          {response.clarification.options.length > 0 ? (
            <div className="ask__options">
              {response.clarification.options.map((option) => (
                <button
                  type="button"
                  key={option}
                  className="btn btn--sm"
                  onClick={() => onChooseOption?.(option)}
                >
                  {option}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {response.action_plan.length > 0 ? (
        <div className="plan">
          {response.action_plan.map((action, index) => (
            <ActionCard key={action.action_id} action={action} index={index} />
          ))}
        </div>
      ) : null}

      {turn.events.length > 0 ? <ProgressLog events={turn.events} /> : null}

      <div className="bubble__meta">
        <span>
          intent <b>{response.intent.normalized || 'n/a'}</b>
        </span>
        <span>
          confidence <b>{Math.round(response.intent.confidence * 100)}%</b>
        </span>
        <span>
          risk <b>{response.risk_level}</b>
        </span>
        <span>
          model <b>{response.decision_model.model}</b>
          {response.decision_model.fallback_used ? ' (fallback)' : ''}
        </span>
        {response.decision_model.provider ? (
          <span>
            provider <b>{response.decision_model.provider}</b>
          </span>
        ) : null}
        {response.decision_model.source ? (
          <span>
            source <b>{response.decision_model.source}</b>
          </span>
        ) : null}
      </div>
    </article>
  )
}

function ActionCard({ action, index }: { action: Action; index: number }) {
  return (
    <div className="plan__item" data-state={action.state}>
      <span className="plan__index">{index + 1}</span>
      <div className="plan__main">
        <div className="plan__tool">{action.tool}</div>
        {action.description ? <div className="plan__desc">{action.description}</div> : null}
        {Object.keys(action.arguments).length > 0 ? (
          <div className="plan__args">{formatArgs(action.arguments)}</div>
        ) : null}
        {typeof action.progress === 'number' && action.progress > 0 ? (
          <div className="plan__progress" aria-hidden="true">
            <span style={{ width: `${Math.round(action.progress * 100)}%` }} />
          </div>
        ) : null}
        {action.error ? (
          <div className="plan__args" style={{ color: 'var(--state-danger)' }}>
            {action.error.code}: {action.error.message}
          </div>
        ) : null}
        <ActionResult result={action.result} />
      </div>
      <span className="plan__state">
        <span className="badge badge--quiet">
          <Dot tone={STATE_TONE[action.state] ?? 'muted'} />
          {STATE_LABEL[action.state] ?? action.state}
        </span>
      </span>
    </div>
  )
}

function ActionResult({ result }: { result: unknown }) {
  if (result === undefined || result === null) return null
  const diff = extractDiff(result)
  if (diff) {
    return <DiffView diff={diff} />
  }
  if (typeof result === 'string') {
    return <pre className="plan__result">{result}</pre>
  }
  return <pre className="plan__result">{safeJson(result)}</pre>
}

function extractDiff(result: unknown): string | null {
  if (typeof result === 'string') {
    return result.includes('@@') ? result : null
  }
  if (result && typeof result === 'object') {
    const record = result as Record<string, unknown>
    if (typeof record.diff === 'string' && record.diff.includes('@@')) return record.diff
    const files = record.files
    if (Array.isArray(files)) {
      const chunks = files
        .map((file) => {
          if (!file || typeof file !== 'object') return ''
          const entry = file as Record<string, unknown>
          const path = typeof entry.path === 'string' ? entry.path : 'file'
          const patch = typeof entry.diff === 'string' ? entry.diff : ''
          return patch ? `--- a/${path}\n+++ b/${path}\n${patch}` : ''
        })
        .filter(Boolean)
        .join('\n')
      return chunks || null
    }
  }
  return null
}

export function DiffView({ diff }: { diff: string }) {
  const lines = diff.split('\n')
  return (
    <div className="diff">
      <div className="diff__file">
        <AlertIcon size={12} />
        unified diff
      </div>
      <pre className="diff__body">
        {lines.map((line, index) => {
          let variant = 'ctx'
          if (line.startsWith('+++') || line.startsWith('---')) variant = 'ctx'
          else if (line.startsWith('@@')) variant = 'hunk'
          else if (line.startsWith('+')) variant = 'add'
          else if (line.startsWith('-')) variant = 'del'
          return (
            <div key={index} className={`diff__line diff__line--${variant}`}>
              {line || ' '}
            </div>
          )
        })}
      </pre>
    </div>
  )
}

export function ProgressLog({ events }: { events: ProgressEvent[] }) {
  if (events.length === 0) return null
  return (
    <div className="progress" role="log" aria-label="Progress events">
      {events.map((event, index) => {
        const stamp = event.ts ?? event.at
        return (
          <div className="progress__row" key={`${event.seq ?? index}`}>
            <span className="progress__time">
              {stamp ? new Date(stamp).toLocaleTimeString() : `#${event.seq ?? index + 1}`}
            </span>
            <span className="progress__label">{event.message ?? describeEvent(event)}</span>
          </div>
        )
      })}
    </div>
  )
}

/**
 * Live progress, shown while a request is still in flight. The events come
 * from the backend stream - nothing here is generated on a timer.
 */
export function LiveProgress({ events }: { events: ProgressEvent[] }) {
  if (events.length === 0) return null
  return (
    <div className="bubble bubble--assistant" aria-live="polite">
      <div className="row" style={{ gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}>
        <StatusDot tone="executing" />
        <span className="turn__who" style={{ margin: 0 }}>
          Live progress
        </span>
      </div>
      <ProgressLog events={events} />
    </div>
  )
}

function describeEvent(event: ProgressEvent): string {
  if (event.kind === 'diff') return 'patch updated'
  if (event.kind === 'error') return 'error reported'
  if (event.kind === 'result') return 'result available'
  if (event.tool) return `${event.tool} update`
  return 'update'
}

export function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([key, value]) => `${key}=${typeof value === 'string' ? value : safeJson(value)}`)
    .join('  ')
}

export function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function CheckRow({ children }: { children: ReactNode }) {
  return (
    <span className="row" style={{ gap: 'var(--space-2)' }}>
      <CheckIcon size={13} />
      {children}
    </span>
  )
}
