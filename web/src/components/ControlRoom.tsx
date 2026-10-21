import { useMemo, useState } from 'react'
import type { ProgressEvent } from '@/lib/api/types'
import type { ActionRecord, RequestRecord } from '@/state/useSidekick'
import { ArchitectureDiagram } from './ArchitectureDiagram'
import { ActionCard } from './ActionCard'
import { ExecutionResultView } from './ExecutionResult'
import { RefreshIcon } from './icons'

/**
 * Interface B - Sidekick Live Control Room.
 *
 * This is the developer and demo view of the same session the conversational
 * surface uses. Every row it shows comes from the backend: the architecture
 * nodes reflect reported capability states, the timeline reflects real events
 * with their sequence numbers and timestamps, and the inspector shows the real
 * request, plan and result.
 */

export interface ControlRoomProps {
  sessionId: string
  requests: RequestRecord[]
  liveEvents: ProgressEvent[]
  followedAction: string | null
  capabilities: Parameters<typeof ArchitectureDiagram>[0]['capabilities']
  connection: 'checking' | 'connected' | 'disconnected'
  connectionError: string | null
  voiceUnavailable: boolean
  busyActions: string[]
  actionErrors: Record<string, string>
  onRefresh: () => void
  onApprove: (record: ActionRecord) => void
  onCancelAction: (record: ActionRecord) => void
}

export function ControlRoom(props: ControlRoomProps) {
  const {
    sessionId,
    requests,
    liveEvents,
    followedAction,
    capabilities,
    connection,
    connectionError,
    voiceUnavailable,
    busyActions,
    actionErrors,
    onRefresh,
    onApprove,
    onCancelAction,
  } = props

  const [selectedId, setSelectedId] = useState<string | null>(null)

  const selected = useMemo(() => {
    if (selectedId) {
      const found = requests.find((request) => request.request_id === selectedId)
      if (found) return found
    }
    return requests[requests.length - 1] ?? null
  }, [requests, selectedId])

  const selectedTool = selected?.actions?.[0]?.action.tool ?? null

  return (
    <div className="control-room">
      <header className="control-room__head">
        <div>
          <p className="control-room__eyebrow">Sidekick Live</p>
          <h1 className="control-room__title">Control room</h1>
        </div>
        <div className="control-room__meta">
          <span className="control-room__session" title={sessionId}>
            session {sessionId.slice(0, 8)}
          </span>
          <span className={`badge badge--${connection === 'connected' ? 'live' : 'danger'}`}>
            {connection === 'connected'
              ? capabilities?.mode === 'stub'
                ? 'dev stub'
                : 'backend live'
              : 'backend unreachable'}
          </span>
          <button type="button" className="btn btn--sm" onClick={onRefresh}>
            <RefreshIcon size={13} />
            Refresh capabilities
          </button>
        </div>
      </header>

      <ArchitectureDiagram
        capabilities={capabilities}
        response={selected?.response ?? null}
        tool={selectedTool}
        disconnected={connection === 'disconnected'}
        voiceUnavailable={voiceUnavailable}
      />

      <div className="control-room__grid">
        <section className="control-room__panel">
          <header className="control-room__panel-head">
            <h2>Request inspector</h2>
            <span className="control-room__panel-sub">
              {requests.length} request{requests.length === 1 ? '' : 's'} in this session
            </span>
          </header>

          {requests.length === 0 ? (
            <p className="control-room__empty">
              Nothing has been asked yet. A request made in the conversational surface appears here
              immediately - both surfaces share one session.
            </p>
          ) : (
            <>
              <ul className="control-room__requests">
                {requests
                  .slice()
                  .reverse()
                  .map((request) => (
                    <li key={request.request_id}>
                      <button
                        type="button"
                        className="control-room__request"
                        data-selected={request.request_id === selected?.request_id || undefined}
                        onClick={() => setSelectedId(request.request_id)}
                      >
                        <span className="control-room__request-state" data-state={request.status}>
                          {request.status.replace('_', ' ')}
                        </span>
                        <span className="control-room__request-text">{request.utterance}</span>
                        <span className="control-room__request-time">
                          {new Date(request.started_at).toLocaleTimeString()}
                        </span>
                      </button>
                    </li>
                  ))}
              </ul>

              {selected ? (
                <RequestDetail
                  record={selected}
                  busyActions={busyActions}
                  actionErrors={actionErrors}
                  onApprove={onApprove}
                  onCancelAction={onCancelAction}
                />
              ) : null}
            </>
          )}
        </section>

        <section className="control-room__panel">
          <header className="control-room__panel-head">
            <h2>Task timeline</h2>
            <span className="control-room__panel-sub">
              {followedAction
                ? (selected?.events.length ?? 0) > 0
                  ? `following ${followedAction.slice(0, 8)}`
                  : `no events received for ${followedAction.slice(0, 8)}`
                : 'no action running'}
            </span>
          </header>
          <Timeline events={selected?.events ?? []} live={liveEvents} />

          <header className="control-room__panel-head control-room__panel-head--second">
            <h2>Capability health</h2>
            <span className="control-room__panel-sub">
              {capabilities ? `${capabilities.tool_count ?? capabilities.capabilities.length} tools` : 'unavailable'}
            </span>
          </header>
          <CapabilityHealth capabilities={capabilities} error={connectionError} />
        </section>
      </div>
    </div>
  )
}

function RequestDetail({
  record,
  busyActions,
  actionErrors,
  onApprove,
  onCancelAction,
}: {
  record: RequestRecord
  busyActions: string[]
  actionErrors: Record<string, string>
  onApprove: (record: ActionRecord) => void
  onCancelAction: (record: ActionRecord) => void
}) {
  const response = record.response
  return (
    <div className="control-room__detail">
      <dl className="control-room__facts">
        <div>
          <dt>request id</dt>
          <dd>{record.request_id}</dd>
        </div>
        <div>
          <dt>session id</dt>
          <dd>{record.session_id}</dd>
        </div>
        <div>
          <dt>input</dt>
          <dd>{record.input_source}</dd>
        </div>
        <div>
          <dt>started</dt>
          <dd>{new Date(record.started_at).toLocaleTimeString()}</dd>
        </div>
        {response ? (
          <>
            <div>
              <dt>intent</dt>
              <dd>{response.intent.normalized || 'n/a'}</dd>
            </div>
            <div>
              <dt>confidence</dt>
              <dd>
                {Math.round(response.intent.confidence * 100)}%
                {response.intent.ambiguous ? ' · ambiguous' : ''}
              </dd>
            </div>
            <div>
              <dt>model</dt>
              <dd>
                {response.decision_model.provider}/{response.decision_model.model}
                {response.decision_model.fallback_used ? ' (fallback)' : ''}
              </dd>
            </div>
            {response.decision_model.source ? (
              <div>
                <dt>source</dt>
                <dd>{response.decision_model.source}</dd>
              </div>
            ) : null}
            <div>
              <dt>risk</dt>
              <dd>{response.risk_level}</dd>
            </div>
            <div>
              <dt>status</dt>
              <dd>{response.status}</dd>
            </div>
          </>
        ) : null}
      </dl>

      {record.error ? (
        <p className="control-room__error">
          {record.error.code}: {record.error.message}
        </p>
      ) : null}

      {record.actions.length > 0 ? (
        <div className="control-room__plan">
          {record.actions.map((entry) => (
            <div className="control-room__plan-item" key={entry.action.action_id}>
              <ActionCard
                record={entry}
                busy={busyActions.includes(entry.action.action_id)}
                error={actionErrors[entry.action.action_id]}
                onApprove={onApprove}
                onCancel={onCancelAction}
              />
              <div className="control-room__plan-actions">
                <span className="control-room__ids">
                  <code>{entry.action.tool}</code> · action {entry.action.action_id.slice(0, 8)}
                  {entry.action.job_id ? ` · job ${entry.action.job_id.slice(0, 8)}` : ''}
                  {entry.action.plan_hash ? ` · plan ${entry.action.plan_hash.slice(0, 8)}` : ''}
                  {` · ${entry.state}`}
                </span>
                {entry.state === 'awaiting_confirmation' ? (
                  <>
                    <button
                      type="button"
                      className="btn btn--sm btn--primary"
                      disabled={busyActions.includes(entry.action.action_id)}
                      onClick={() => onApprove(entry)}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm btn--danger"
                      disabled={busyActions.includes(entry.action.action_id)}
                      onClick={() => onCancelAction(entry)}
                    >
                      Refuse
                    </button>
                  </>
                ) : null}
                {entry.state === 'running' || entry.state === 'pending' ? (
                  <button
                    type="button"
                    className="btn btn--sm btn--danger"
                    disabled={busyActions.includes(entry.action.action_id)}
                    onClick={() => onCancelAction(entry)}
                  >
                    Cancel action
                  </button>
                ) : null}
              </div>
              {entry.action.error ? (
                <p className="control-room__error">
                  {entry.action.error.code}: {entry.action.error.message}
                </p>
              ) : null}
              {entry.action.result !== undefined && entry.action.result !== null ? (
                <ExecutionResultView action={entry.action} />
              ) : null}
            </div>
          ))}
        </div>
      ) : null}

      {record.inheritedActions.length > 0 ? (
        <details className="control-room__inherited">
          <summary>
            {record.inheritedActions.length} action(s) carried over from an earlier turn
          </summary>
          <ul>
            {record.inheritedActions.map((entry) => (
              <li key={entry.action.action_id}>
                <code>{entry.action.tool}</code> - {entry.state} (from{' '}
                {entry.request_id.slice(0, 8)})
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {response ? (
        <details className="control-room__raw">
          <summary>Raw response payload</summary>
          <pre aria-label="Raw response payload">{JSON.stringify(response, null, 2)}</pre>
        </details>
      ) : null}
    </div>
  )
}

function Timeline({ events, live }: { events: ProgressEvent[]; live: ProgressEvent[] }) {
  const all = [...events, ...live.filter((event) => !events.includes(event))]
  if (all.length === 0) {
    return (
      <p className="control-room__empty">
        No events yet. The timeline is filled by the backend event stream - never by a timer.
      </p>
    )
  }
  return (
    <ol className="timeline">
      {all.map((event, index) => (
        <li className="timeline__row" key={`${event.seq ?? index}-${event.message ?? ''}`}>
          <span className="timeline__seq">{event.seq ?? index + 1}</span>
          <span className="timeline__type">{event.type ?? event.kind ?? 'event'}</span>
          <span className="timeline__message">{event.message ?? ''}</span>
          <span className="timeline__time">
            {event.ts ?? event.at ? new Date((event.ts ?? event.at)!).toLocaleTimeString() : ''}
          </span>
        </li>
      ))}
    </ol>
  )
}

function CapabilityHealth({
  capabilities,
  error,
}: {
  capabilities: Parameters<typeof ArchitectureDiagram>[0]['capabilities']
  error: string | null
}) {
  if (!capabilities) {
    return (
      <p className="control-room__empty">
        {error ?? 'The capability inventory could not be read.'}
      </p>
    )
  }

  const tools = capabilities.tools ?? []
  const rows = tools.length > 0 ? tools : capabilities.capabilities.map((capability) => ({
    tool: capability.id,
    status: capability.state.toUpperCase(),
    status_detail: capability.detail,
  }))

  return (
    <table className="health">
      <thead>
        <tr>
          <th scope="col">tool</th>
          <th scope="col">status</th>
          <th scope="col">detail</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.tool}>
            <td>
              <code>{row.tool}</code>
            </td>
            <td>
              <span className="health__status" data-status={row.status}>
                {row.status}
              </span>
            </td>
            <td className="health__detail">{row.status_detail ?? ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
