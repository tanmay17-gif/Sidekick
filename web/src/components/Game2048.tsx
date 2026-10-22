import { useCallback, useEffect, useState } from 'react'
import {
  canMove,
  createBoard,
  highestTile,
  move,
  type Board2048,
  type MoveResult,
} from '@/lib/games/game2048'

const DIRECTIONS = ['left', 'right', 'up', 'down'] as const
type Direction = (typeof DIRECTIONS)[number]

const KEY_DIRECTIONS: Record<string, Direction> = {
  ArrowLeft: 'left',
  ArrowRight: 'right',
  ArrowUp: 'up',
  ArrowDown: 'down',
  a: 'left',
  d: 'right',
  w: 'up',
  s: 'down',
}

/** 2048 - a local puzzle with the real merge rules. */
export function Game2048() {
  const [state, setState] = useState<MoveResult>(() => {
    const board = createBoard()
    return { board, score: 0, moved: true, changed: [] }
  })

  const apply = useCallback((direction: Direction) => {
    setState((current) => {
      const result = move(current.board, direction)
      return result.moved ? result : current
    })
  }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return
      const direction = KEY_DIRECTIONS[event.key]
      if (!direction) return
      event.preventDefault()
      apply(direction)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [apply])

  const board: Board2048 = state.board
  const over = !canMove(board)

  return (
    <div className="stack stack--tight">
      <div className="row row--wrap">
        <span className="badge badge--quiet">score {state.score}</span>
        <span className="badge badge--quiet">best tile {highestTile(board)}</span>
        {over ? <span className="badge badge--danger">no moves left</span> : null}
        <button
          type="button"
          className="btn btn--sm"
          onClick={() => setState({ board: createBoard(), score: 0, moved: true, changed: [] })}
        >
          New game
        </button>
      </div>

      <div className="tiles" role="grid" aria-label="2048 board">
        {board.map((tile, index) => (
          <div
            key={index}
            role="gridcell"
            className="tiles__cell"
            data-tile={tile ?? undefined}
            data-changed={state.changed.includes(index) || undefined}
            aria-label={tile === null ? 'Empty' : `Tile ${tile}`}
          >
            {tile ?? ''}
          </div>
        ))}
      </div>

      <div className="row row--wrap">
        {DIRECTIONS.map((direction) => (
          <button
            type="button"
            key={direction}
            className="btn btn--sm"
            onClick={() => apply(direction)}
          >
            {direction}
          </button>
        ))}
      </div>
      <p className="hint">
        Arrow keys move the board. The merge rules are the real ones - two equal tiles combine
        once per move, exactly as in 2048.
      </p>
    </div>
  )
}
