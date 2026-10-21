import { useState } from 'react'
import type {
  Action,
  ActionState,
  ProgressEvent,
  SidekickResponse,
} from '@/lib/api/types'
import { ExecutionResultView } from './ExecutionResult'
import { AlertIcon, CheckIcon, SparkIcon } from './icons'

/**
 * The Decision Trace.
 *
 * Every step shows data the backend actually produced. Where the backend does
 * not say *why*, the trace shows the observed facts and says the reason is not
 * available - it never invents a rationale.
 */

export interface DecisionTraceProps {
  response: SidekickResponse | null
  utterance: string
  inputSource: 'voice' | 'text'
  /** Live events, shown while the request is still running. */
  liveEvents?: ProgressEvent[]
  busy?: boolean
}

type StepKey = 'heard' | 'understood' | 'decided' | 'planned' | 'asked' | 'acted' | 'result'

const STEP_ORDER: StepKey[] = ['heard', 'understood', 'decided', 'planned', 'asked', 'acted', 'result']

export function DecisionTrace({
  response,
  utterance,
  inputSource,
  liveEvents = [],
  busy,
}: DecisionTraceProps) {
  const [showRaw, setShowRaw] = useState(false)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const events = response?.events?.length ? response.events : liveEvents
  const steps = buildSteps({ response, utterance, inputSource, events, busy })

  return (
    <section className="trace" aria-label="Decision trace">
      <header className="trace__head">
        <div>
          <h3 className="trace__title">Decision trace</h3>
          <p className="trace__sub">
            {steps.length} step{steps.length === 1 ? '' : 's'} from what you said to what happened.
          </p>
        </div>
        <button
          type="button"
          className="btn btn--sm btn--ghost"
          aria-pressed={showRaw}
          onClick={() => setShowRaw((value) => !value)}
          title="Show the raw response payload"
        >
          {showRaw ? 'Hide raw' : 'Raw payload'}
        </button>
      </header>

      <ol className="trace__steps">
        {steps.map((step) => {
          const isOpen = expanded[step.key] ?? true
          return (
            <li className="trace__step" key={step.key} data-tone={step.tone}>
              <span className="trace__marker" aria-hidden="true">
                {step.tone === 'error' ? <AlertIcon size={12} /> : null}
                {step.tone === 'ok' ? <CheckIcon size={12} /> : null}
                {step.tone === 'busy' ? <span className="trace__pulse" /> : null}
              </span>
              <div className="trace__body">
                <div className="trace__row">
                  <h4 className="trace__step-title">{step.title}</h4>
                  {step.summary ? <span className="trace__summary">{step.summary}</span> : null}
                </div>
                {step.detail ? <p className="trace__detail">{step.detail}</p> : null}
                {step.facts.length > 0 ? (
                  <dl className="trace__facts">
                    {step.facts.map((fact) => (
                      <div className="trace__fact" key={fact.label}>
                        <dt>{fact.label}</dt>
                        <dd>{fact.value}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
                {step.note ? <p className="trace__note">{step.note}</p> : null}
                {step.children}
                {step.expandable ? (
                  <button
                    type="button"
                    className="btn btn--sm btn--ghost"
                    aria-expanded={isOpen}
                    onClick={() =>
                      setExpanded((current) => ({ ...current, [step.key]: !isOpen }))
                    }
                  >
                    {isOpen ? 'Hide detail' : 'Show detail'}
                  </button>
                ) : null}
              </div>
            </li>
          )
        })}
      </ol>

      {showRaw && response ? (
        <pre className="trace__raw" aria-label="Raw response payload">
          {JSON.stringify(response, null, 2)}
        </pre>
      ) : null}
    </section>
  )
}

interface TraceStep {
  key: StepKey
  title: string
  summary?: string
  detail?: string
  note?: string
  facts: Array<{ label: string; value: string }>
  tone: 'ok' | 'busy' | 'muted' | 'error'
  children?: React.ReactNode
  expandable?: boolean
}

function buildSteps(input: {
  response: SidekickResponse | null
  utterance: string
  inputSource: 'voice' | 'text'
  events: ProgressEvent[]
  busy?: boolean
}): TraceStep[] {
  const { response, utterance, inputSource, events, busy } = input
  const steps: TraceStep[] = []

  steps.push({
    key: 'heard',
    title: 'Heard',
    summary: inputSource === 'voice' ? 'voice' : 'text',
    detail: utterance,
    facts: [{ label: 'input', value: inputSource }],
    tone: 'ok',
  })

  if (!response) {
    if (busy) {
      steps.push({
        key: 'understood',
        title: 'Working',
        summary: 'waiting for the backend',
        detail: 'The request is with the decision engine.',
        facts: [],
        tone: 'busy',
      })
    }
    return steps
  }

  const intent = response.intent
  steps.push({
    key: 'understood',
    title: 'Understood',
    summary: `${Math.round(intent.confidence * 100)}% confidence`,
    detail: intent.normalized || 'No normalized intent was reported.',
    facts: [
      { label: 'confidence', value: `${Math.round(intent.confidence * 100)}%` },
      { label: 'ambiguous', value: intent.ambiguous ? 'yes' : 'no' },
      ...(intent.entities.length > 0
        ? [{ label: 'entities', value: String(intent.entities.length) }]
        : []),
    ],
    note: intent.ambiguous
      ? 'The backend marked this as ambiguous, so it asked rather than guessed.'
      : undefined,
    tone: intent.ambiguous ? 'muted' : 'ok',
  })

  const model = response.decision_model
  steps.push({
    key: 'decided',
    title: 'Decided',
    summary: model.model,
    detail: model.fallback_used
      ? 'The primary decision model was not used, so this came from the fallback path.'
      : undefined,
    facts: [
      { label: 'provider', value: model.provider || 'not reported' },
      { label: 'model', value: model.model || 'not reported' },
      ...(model.source ? [{ label: 'source', value: model.source }] : []),
      { label: 'fallback', value: model.fallback_used ? 'yes' : 'no' },
      { label: 'risk', value: response.risk_level },
    ],
    tone: model.fallback_used ? 'muted' : 'ok',
  })

  if (response.action_plan.length > 0) {
    steps.push({
      key: 'planned',
      title: 'Planned',
      summary: `${response.action_plan.length} action${response.action_plan.length === 1 ? '' : 's'}`,
      facts: response.action_plan.map((action) => ({
        label: action.tool,
        value: actionStateLabel(action),
      })),
      note: response.action_plan.some((action) => action.approval_required)
        ? 'One of these actions needs your approval before it can run.'
        : undefined,
      children: (
        <ul className="trace__plan">
          {response.action_plan.map((action) => (
            <TraceAction key={action.action_id} action={action} />
          ))}
        </ul>
      ),
      tone: 'ok',
    })
  }

  if (response.clarification) {
    steps.push({
      key: 'asked',
      title: 'Asked',
      summary: 'needed one more detail',
      detail: response.clarification.question,
      facts: response.clarification.options.map((option) => ({
        label: 'option',
        value: option,
      })),
      note: 'The backend reported the question but not the internal reason for it.',
      tone: 'muted',
    })
  }

  if (events.length > 0) {
    steps.push({
      key: 'acted',
      title: 'Acted',
      summary: `${events.length} event${events.length === 1 ? '' : 's'}`,
      facts: events
        .slice(-4)
        .map((event) => ({
          label: event.type ?? event.kind ?? 'event',
          value: `${event.seq ?? ''} ${event.message ?? ''}`.trim(),
        })),
      children: <EventTable events={events} />,
      expandable: events.length > 4,
      tone: busy ? 'busy' : 'ok',
    })
  }

  const finished = response.action_plan.filter((action) => action.state !== 'pending')
  if (finished.length > 0) {
    steps.push({
      key: 'result',
      title: 'Result',
      summary: finished.map((action) => actionStateLabel(action)).join(', '),
      facts: finished.map((action) => ({
        label: action.tool,
        value: action.error ? `${action.error.code}` : 'no error',
      })),
      children: (
        <div className="trace__results">
          {finished.map((action) => (
            <ExecutionResultView key={action.action_id} action={action} />
          ))}
        </div>
      ),
      tone: finished.some((action) => action.state === 'failed') ? 'error' : 'ok',
    })
  }

  return steps.sort((a, b) => STEP_ORDER.indexOf(a.key) - STEP_ORDER.indexOf(b.key))
}

function actionStateLabel(action: Action): string {
  const labels: Record<ActionState, string> = {
    pending: 'pending',
    awaiting_confirmation: 'awaiting confirmation',
    running: 'running',
    paused: 'paused',
    succeeded: 'done',
    failed: 'failed',
    cancelled: 'cancelled',
    superseded: 'superseded',
  }
  const base = labels[action.state] ?? action.state
  return action.approval_required && action.state === 'awaiting_confirmation'
    ? `${base} (approval required)`
    : base
}

function TraceAction({ action }: { action: Action }) {
  return (
    <li className="trace__plan-item" data-state={action.state}>
      <span className="trace__plan-tool">{action.tool}</span>
      {action.description ? (
        <span className="trace__plan-desc">{action.description}</span>
      ) : null}
      {Object.keys(action.arguments).length > 0 ? (
        <code className="trace__plan-args">
          {Object.entries(action.arguments)
            .map(([key, value]) => `${key}=${typeof value === 'string' ? value : JSON.stringify(value)}`)
            .join('  ')}
        </code>
      ) : null}
      <span className="trace__plan-state">{actionStateLabel(action)}</span>
    </li>
  )
}

function EventTable({ events }: { events: ProgressEvent[] }) {
  return (
    <ol className="trace__events">
      {events.map((event, index) => (
        <li key={`${event.seq ?? index}`} className="trace__event">
          <span className="trace__event-seq">{event.seq ?? index + 1}</span>
          <span className="trace__event-type">{event.type ?? event.kind ?? 'event'}</span>
          <span className="trace__event-message">{event.message ?? ''}</span>
          <span className="trace__event-time">
            {event.ts ?? event.at ? new Date((event.ts ?? event.at)!).toLocaleTimeString() : ''}
          </span>
        </li>
      ))}
    </ol>
  )
}

export { SparkIcon }
