import type { CapabilitiesResponse, SidekickResponse } from '@/lib/api/types'

/**
 * The live architecture diagram.
 *
 * Every node is either connected - because the backend actually reported the
 * thing it stands for - or it is marked unavailable or unconfigured. Nothing
 * that is merely planned is drawn as if it were running.
 */

export type NodeState = 'connected' | 'idle' | 'unavailable' | 'unconfigured' | 'simulated'

export interface DiagramNode {
  id: string
  label: string
  detail: string
  state: NodeState
}

export interface ArchitectureDiagramProps {
  capabilities: CapabilitiesResponse | null
  response: SidekickResponse | null
  /** The tool of the action being followed, when there is one. */
  tool: string | null
  /** True when the browser could not reach the backend. */
  disconnected: boolean
  /** True when the browser has no speech engine. */
  voiceUnavailable: boolean
}

export function ArchitectureDiagram({
  capabilities,
  response,
  tool,
  disconnected,
  voiceUnavailable,
}: ArchitectureDiagramProps) {
  const nodes = buildNodes({ capabilities, response, tool, disconnected, voiceUnavailable })

  return (
    <section className="arch" aria-label="System architecture">
      <ol className="arch__flow">
        {nodes.map((node, index) => (
          <li className="arch__step" key={node.id}>
            <div className="arch__node" data-state={node.state}>
              <span className="arch__node-label">{node.label}</span>
              <span className="arch__node-detail">{node.detail}</span>
              <span className="arch__node-state">{node.state}</span>
            </div>
            {index < nodes.length - 1 ? (
              <span className="arch__connector" aria-hidden="true" />
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  )
}
function buildNodes(input: {
  capabilities: CapabilitiesResponse | null
  response: SidekickResponse | null
  tool: string | null
  disconnected: boolean
  voiceUnavailable: boolean
}): DiagramNode[] {
  const { capabilities, response, tool, disconnected, voiceUnavailable } = input

  const engineState: NodeState = disconnected
    ? 'unavailable'
    : response
      ? 'connected'
      : 'idle'

  const safetyState: NodeState = disconnected
    ? 'unavailable'
    : response
      ? 'connected'
      : 'idle'

  const toolDescriptor = capabilities?.tools?.find((entry) => entry.tool === tool)

  const adapterState: NodeState = disconnected
    ? 'unavailable'
    : tool
      ? 'connected'
      : 'idle'

  const executionState: NodeState = disconnected
    ? 'unavailable'
    : !tool
      ? 'idle'
      : toolDescriptor
        ? toolDescriptor.status === 'REAL'
          ? 'connected'
          : toolDescriptor.status === 'SIMULATED'
            ? 'simulated'
            : toolDescriptor.status === 'NOT_CONFIGURED'
              ? 'unconfigured'
              : 'unavailable'
        : 'idle'

  const resultState: NodeState = disconnected
    ? 'unavailable'
    : response?.action_plan?.some(
        (action) => action.state === 'succeeded' || action.state === 'failed',
      )
      ? 'connected'
      : 'idle'

  return [
    {
      id: 'user',
      label: 'You',
      detail: response ? 'speaking or typing' : 'waiting',
      state: 'connected',
    },
    {
      id: 'voice',
      label: 'Voice UI',
      // The speech engine is a browser capability, not a backend one - the
      // backend says nothing about it, so the browser is the only honest
      // source for its state.
      detail: voiceUnavailable
        ? 'no speech engine in this browser'
        : 'browser speech recognition and synthesis',
      state: disconnected
        ? 'unavailable'
        : voiceUnavailable
          ? 'unavailable'
          : 'connected',
    },
    {
      id: 'core',
      label: 'Core decision engine',
      detail: response
        ? `${response.decision_model.provider} / ${response.decision_model.model}${
            response.decision_model.fallback_used ? ' (fallback)' : ''
          }`
        : 'no request yet',
      state: engineState,
    },
    {
      id: 'safety',
      label: 'Capability & safety',
      detail: response
        ? `risk ${response.risk_level}${
            response.action_plan.some((action) => action.approval_required)
              ? ' - approval required'
              : ''
          }`
        : 'no policy decision yet',
      state: safetyState,
    },
    {
      id: 'adapter',
      label: 'Tool adapter',
      detail: tool ?? 'no tool selected',
      state: adapterState,
    },
    {
      id: 'execution',
      label: 'Execution service',
      detail: toolDescriptor
        ? `${toolDescriptor.status} - ${toolDescriptor.status_detail ?? 'no detail reported'}`
        : tool
          ? 'no adapter status reported'
          : 'nothing running',
      state: executionState,
    },
    {
      id: 'result',
      label: 'Result',
      detail: describeResult(response),
      state: resultState,
    },
    {
      id: 'response',
      label: 'Spoken / UI response',
      detail: response
        ? response.speech
          ? 'spoken summary supplied by the backend'
          : 'rendered in the interface'
        : 'nothing yet',
      state: disconnected ? 'unavailable' : response ? 'connected' : 'idle',
    },
  ]
}

function describeResult(response: SidekickResponse | null): string {
  if (!response) return 'nothing yet'
  const finished = response.action_plan.filter(
    (action) => action.state === 'succeeded' || action.state === 'failed',
  )
  if (finished.length === 0) return 'no action has finished'
  const failed = finished.filter((action) => action.state === 'failed')
  if (failed.length > 0) return `${failed.length} action(s) failed`
  return `${finished.length} action(s) completed`
}
