import type { ReactNode } from 'react'
import type { CapabilityState } from '@/lib/api/types'

export type Tone =
  | 'live'
  | 'simulated'
  | 'unavailable'
  | 'unconfigured'
  | 'disconnected'
  | 'muted'
  | 'success'
  | 'danger'
  | 'confirm'
  | 'executing'
  | 'thinking'
  | 'listen'

export function Dot({ tone = 'muted' }: { tone?: Tone }) {
  return <span className="dot" data-tone={tone} aria-hidden="true" />
}

const STATE_LABEL: Record<CapabilityState, string> = {
  live: 'live',
  simulated: 'simulated',
  unavailable: 'unavailable',
  unconfigured: 'not configured',
  disconnected: 'disconnected',
}

export function StateBadge({ state, detail }: { state: CapabilityState; detail?: string }) {
  return (
    <span className={`badge badge--${state}`} title={detail}>
      {STATE_LABEL[state]}
    </span>
  )
}

export function Panel({
  title,
  hint,
  actions,
  children,
  flush,
}: {
  title: ReactNode
  hint?: ReactNode
  actions?: ReactNode
  children: ReactNode
  flush?: boolean
}) {
  return (
    <section className="panel">
      <header className="panel__header">
        <div>
          <h3 className="panel__title">{title}</h3>
          {hint ? <p className="panel__hint">{hint}</p> : null}
        </div>
        {actions ? <div className="row">{actions}</div> : null}
      </header>
      <div className={flush ? 'panel__body panel__body--flush' : 'panel__body'}>{children}</div>
    </section>
  )
}

export function EmptyState({
  title,
  body,
  glyph,
  action,
}: {
  title: string
  body: string
  glyph?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty">
      {glyph ? <div className="empty__glyph">{glyph}</div> : null}
      <p className="empty__title">{title}</p>
      <p className="empty__body">{body}</p>
      {action ? <div style={{ marginTop: 'var(--space-5)' }}>{action}</div> : null}
    </div>
  )
}

export function Notice({
  tone = 'plain',
  children,
}: {
  tone?: 'plain' | 'warn' | 'danger'
  children: ReactNode
}) {
  const className = tone === 'plain' ? 'notice' : `notice notice--${tone}`
  return <div className={className}>{children}</div>
}
