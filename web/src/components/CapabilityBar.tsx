import type { Capability, CapabilitiesResponse } from '@/lib/api/types'
import type { ConnectionState } from '@/state/useSidekick'

export interface CapabilityBarProps {
  capabilities: CapabilitiesResponse | null
  connection: ConnectionState
}

const TONE_BY_STATE = {
  live: 'live',
  simulated: 'simulated',
  unavailable: 'unavailable',
  unconfigured: 'confirm',
  disconnected: 'danger',
  client: 'live',
} as const

/**
 * The honest inventory strip. Each capability shows the state the backend
 * reported - nothing here is inferred in the browser.
 */
export function CapabilityBar({ capabilities, connection }: CapabilityBarProps) {
  if (connection === 'disconnected') {
    return (
      <div className="caps">
        <span className="caps__item" data-state="disconnected">
          <span className="dot" data-tone="danger" />
          <span className="caps__name">backend</span>
          <span className="caps__state">disconnected</span>
        </span>
      </div>
    )
  }

  if (connection === 'checking') {
    return (
      <div className="caps">
        <span className="caps__item">
          <span className="dot" data-tone="muted" />
          <span className="caps__name">backend</span>
          <span className="caps__state">checking</span>
        </span>
      </div>
    )
  }

  const items: Capability[] = capabilities?.capabilities ?? []

  return (
    <div className="caps">
      {capabilities?.mode === 'stub' ? (
        <span className="caps__item" data-state="simulated">
          <span className="dot" data-tone="simulated" />
          <span className="caps__name">backend</span>
          <span className="caps__state">dev stub</span>
        </span>
      ) : (
        <span className="caps__item" data-state="live">
          <span className="dot" data-tone="live" />
          <span className="caps__name">backend</span>
          <span className="caps__state">live</span>
        </span>
      )}

      {items.map((capability) => (
        <span className="caps__item" key={capability.id} data-state={capability.state}>
          <span className="dot" data-tone={TONE_BY_STATE[capability.state]} />
          <span className="caps__name">{capability.id}</span>
          <span className="caps__state">{capability.state}</span>
        </span>
      ))}
    </div>
  )
}
