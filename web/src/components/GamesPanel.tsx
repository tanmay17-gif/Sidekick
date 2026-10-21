import type { GameDescriptor, SidekickResponse } from '@/lib/api/types'
import { LOCAL_ACTIVITIES } from '@/lib/games/registry'
import { ChessBoard } from './ChessBoard'
import { GameIcon } from './icons'
import { EmptyState, Notice, Panel, StateBadge } from './ui'

export interface GamesPanelProps {
  games: GameDescriptor[]
  lastResponse: SidekickResponse | null
  onRequest: (utterance: string) => void
}

interface ChessState {
  fen: string | null
  lastMove: string[]
  selected: string | null
  legalTargets: string[]
  turn: string | null
}

export function GamesPanel({ games, lastResponse, onRequest }: GamesPanelProps) {
  const chess = extractChessState(lastResponse)
  const hasLocalActivities = LOCAL_ACTIVITIES.length > 0

  if (games.length === 0 && !hasLocalActivities) {
    return (
      <EmptyState
        title="No games are available"
        body="The backend did not report any playable game and no local activity is bundled. Nothing is listed because no move could actually be made."
        glyph={<GameIcon size={32} />}
      />
    )
  }

  return (
    <div className="stack">
      {games.length > 0 ? (
        <Panel
          title="Backend games"
          hint="Reported by the backend - the browser only renders what the service sends"
          flush
        >
          <div className="list">
            {games.map((game) => (
              <div className="list__row" key={game.id}>
                <div className="list__main">
                  <div className="list__title">{game.name}</div>
                  {game.detail ? <div className="list__sub">{game.detail}</div> : null}
                </div>
                <StateBadge state={game.state} detail={game.detail} />
              </div>
            ))}
          </div>
        </Panel>
      ) : (
        <Notice tone="warn">
          The backend did not report any games. The activities below run locally in this browser
          and need no service.
        </Notice>
      )}

      {games.some((game) => game.state !== 'live') ? (
        <Notice tone="warn">
          A game that is not live cannot accept moves. The board below shows whatever the backend
          last reported - it is never simulated locally.
        </Notice>
      ) : null}

      {games.some((game) => game.id === 'chess') ? (
        <Panel
          title="Chess"
          hint={
            chess.fen
              ? `Position reported by the backend - ${chess.turn ?? 'w'} to move`
              : 'No position reported yet'
          }
        >
          <div className="row row--wrap" style={{ alignItems: 'flex-start', gap: 'var(--space-5)' }}>
            <ChessBoard
              fen={chess.fen}
              lastMove={chess.lastMove}
              selected={chess.selected}
              legalTargets={chess.legalTargets}
            />
            <div className="stack stack--tight" style={{ flex: 1, minWidth: 220 }}>
              <div className="row row--wrap">
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={() => onRequest('Start a new chess game')}
                >
                  New game
                </button>
                <button type="button" className="btn" onClick={() => onRequest('Make a chess move')}>
                  Make a move
                </button>
                <button type="button" className="btn" onClick={() => onRequest('Show the chess board')}>
                  Show board
                </button>
              </div>
              <p className="hint">
                Move selection and legality are decided by the backend. This board only renders the
                position it reports.
              </p>
            </div>
          </div>
        </Panel>
      ) : null}

      {hasLocalActivities ? (
        <Panel
          title="Local activities"
          hint="Shipped with the client - the rules, the opponent and the state are real and need no backend"
        >
          <div className="stack">
            {LOCAL_ACTIVITIES.map((activity) => {
              const Activity = activity.Component
              return (
                <details className="activity" key={activity.id}>
                  <summary className="activity__summary">
                    <span className="activity__name">{activity.name}</span>
                    <span className="badge badge--quiet">local</span>
                    <span className="activity__hint">{activity.summary}</span>
                  </summary>
                  <div className="activity__body">
                    <Activity />
                  </div>
                </details>
              )
            })}
          </div>
        </Panel>
      ) : null}
    </div>
  )
}

function extractChessState(response: SidekickResponse | null): ChessState {
  const empty: ChessState = { fen: null, lastMove: [], selected: null, legalTargets: [], turn: null }
  if (!response) return empty

  for (const action of response.action_plan) {
    if (!action.tool.startsWith('game.')) continue
    const result = action.result
    if (!result || typeof result !== 'object') continue
    const record = result as Record<string, unknown>
    const position = (record.position ?? record) as Record<string, unknown>
    const fen = typeof position.fen === 'string' ? position.fen : null
    if (!fen) continue

    const move = position.last_move ?? position.lastMove
    const lastMove: string[] = []
    if (move && typeof move === 'object') {
      const moveRecord = move as Record<string, unknown>
      if (typeof moveRecord.from === 'string') lastMove.push(moveRecord.from)
      if (typeof moveRecord.to === 'string') lastMove.push(moveRecord.to)
    }

    return {
      fen,
      lastMove,
      selected: typeof position.selected === 'string' ? position.selected : null,
      legalTargets: Array.isArray(position.legal_targets)
        ? position.legal_targets.filter((value): value is string => typeof value === 'string')
        : Array.isArray(position.legalTargets)
          ? position.legalTargets.filter((value): value is string => typeof value === 'string')
          : [],
      turn: typeof position.turn === 'string' ? position.turn : null,
    }
  }

  return empty
}
