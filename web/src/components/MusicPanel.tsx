import type { Capability, ProviderDescriptor, SidekickResponse, ToolDescriptor } from '@/lib/api/types'
import { MusicIcon } from './icons'
import { EmptyState, Notice, Panel, StateBadge } from './ui'

export interface MusicPanelProps {
  providers: ProviderDescriptor[]
  capabilities: Capability[]
  /** The execution service's own status vocabulary, rendered verbatim. */
  tools: ToolDescriptor[]
  /** The most recent action plan, used to show what the backend actually did. */
  lastResponse: SidekickResponse | null
  onRequest: (utterance: string) => void
}

export function MusicPanel({
  providers,
  capabilities,
  tools,
  lastResponse,
  onRequest,
}: MusicPanelProps) {
  const musicCaps = capabilities.filter((capability) => capability.id.startsWith('music.'))
  const musicActions = (lastResponse?.action_plan ?? []).filter((action) =>
    action.tool.startsWith('music.'),
  )

  if (providers.length === 0 && musicCaps.length === 0) {
    return (
      <EmptyState
        title="No music provider is connected"
        body="The backend did not report any music capability. Nothing is shown here because no playback can actually happen."
        glyph={<MusicIcon size={32} />}
      />
    )
  }

  return (
    <div className="stack">
      <Panel
        title="Providers"
        hint="Reported by the backend - the browser cannot connect to these services itself"
        flush
      >
        <div className="list">
          {providers.map((provider) => (
            <div className="list__row" key={provider.id}>
              <div className="list__main">
                <div className="list__title">{provider.name}</div>
                {provider.detail ? <div className="list__sub">{provider.detail}</div> : null}
              </div>
              <StateBadge state={provider.state} detail={provider.detail} />
            </div>
          ))}
          {musicCaps
            .filter((capability) => !providers.some((p) => p.id === capability.id))
            .map((capability) => (
              <div className="list__row" key={capability.id}>
                <div className="list__main">
                  <div className="list__title">{capability.id}</div>
                  {capability.detail ? <div className="list__sub">{capability.detail}</div> : null}
                </div>
                <StateBadge state={capability.state} detail={capability.detail} />
              </div>
            ))}
          {tools
            .filter((tool) => tool.tool.startsWith('music.'))
            .map((tool) => (
              <div className="list__row" key={tool.tool}>
                <div className="list__main">
                  <div className="list__title">{tool.tool}</div>
                  {tool.status_detail ? (
                    <div className="list__sub">{tool.status_detail}</div>
                  ) : null}
                </div>
                <span className="badge badge--quiet">{tool.status}</span>
              </div>
            ))}
        </div>
      </Panel>

      {providers.some((provider) => provider.state === 'unconfigured') ? (
        <Notice tone="warn">
          A provider that is not configured cannot play anything. Ask Sidekick for a track and the
          real error will be shown here rather than a fake player.
        </Notice>
      ) : null}

      <Panel title="Ask for a track" hint="The request goes through the real decision engine">
        <div className="row row--wrap">
          <button
            type="button"
            className="btn"
            onClick={() => onRequest('Play a track on the connected music provider')}
          >
            Play something
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => onRequest('Pause the music')}
          >
            Pause
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => onRequest('What is playing right now?')}
          >
            Now playing
          </button>
        </div>
      </Panel>

      {musicActions.length > 0 ? (
        <Panel title="Last music action" hint="Straight from the backend response">
          <div className="plan">
            {musicActions.map((action) => (
              <div className="plan__item" key={action.action_id} data-state={action.state}>
                <span className="plan__index">
                  <MusicIcon size={12} />
                </span>
                <div className="plan__main">
                  <div className="plan__tool">{action.tool}</div>
                  {action.error ? (
                    <div className="plan__args" style={{ color: 'var(--state-danger)' }}>
                      {action.error.code}: {action.error.message}
                    </div>
                  ) : action.result !== undefined ? (
                    <pre className="plan__result">{JSON.stringify(action.result, null, 2)}</pre>
                  ) : null}
                </div>
                <span className="plan__state">
                  <StateBadge state={stateForAction(action.state)} />
                </span>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}
    </div>
  )
}

function stateForAction(state: string): 'live' | 'simulated' | 'unavailable' | 'unconfigured' {
  if (state === 'succeeded') return 'live'
  if (state === 'running' || state === 'pending') return 'simulated'
  if (state === 'failed') return 'unavailable'
  return 'unconfigured'
}
