import type { ReactNode } from 'react'
import {
  applyMove,
  bestMove,
  describeOutcome,
  EMPTY_BOARD,
  legalMoves,
  winnerOf,
  type Board,
} from '@/lib/games/tictactoe'
import { useState } from 'react'

/**
 * Tic-Tac-Toe against the local minimax engine.
 * The AI is a real opponent - it is not a random pick dressed up as one.
 */
export function TicTacToe() {
  const [board, setBoard] = useState<Board>(EMPTY_BOARD)
  const [turn, setTurn] = useState<'X' | 'O'>('X')
  const [lastMove, setLastMove] = useState<number | null>(null)

  const outcome = winnerOf(board)

  const play = (index: number) => {
    if (outcome !== 'ongoing' || turn !== 'X') return
    if (board[index] !== null) return

    const afterPlayer = applyMove(board, index, 'X')
    setBoard(afterPlayer)
    setLastMove(index)
    setTurn('O')

    if (winnerOf(afterPlayer) !== 'ongoing') return

    // The engine answers immediately; the rules are the real 2048-style
    // minimax search, not a random move.
    const reply = bestMove(afterPlayer, 'O')
    if (reply === null) return
    setBoard(applyMove(afterPlayer, reply, 'O'))
    setLastMove(reply)
    setTurn('X')
  }

  const reset = () => {
    setBoard(EMPTY_BOARD)
    setTurn('X')
    setLastMove(null)
  }

  const moves = legalMoves(board)

  return (
    <div className="stack stack--tight">
      <div className="ttt" role="grid" aria-label="Tic tac toe board">
        {board.map((cell, index) => (
          <button
            type="button"
            key={index}
            role="gridcell"
            className="ttt__cell"
            data-player={cell ?? undefined}
            data-last={lastMove === index || undefined}
            aria-label={`Cell ${index + 1}: ${cell ?? 'empty'}`}
            disabled={cell !== null || outcome !== 'ongoing' || turn !== 'X'}
            onClick={() => play(index)}
          >
            {cell ?? ''}
          </button>
        ))}
      </div>
      <div className="row row--wrap">
        {outcome !== 'ongoing' ? (
          <span className="badge badge--quiet">{describeOutcome(outcome)}</span>
        ) : null}
        <span className="badge badge--quiet">
          {turn === 'X' ? 'your move' : 'sidekick is thinking'}
        </span>
        <button type="button" className="btn btn--sm" onClick={reset}>
          New game
        </button>
      </div>
      <p className="hint">
        {moves.length} cell{moves.length === 1 ? '' : 's'} left. The opponent uses a real
        minimax search over the rules, so it does not play randomly.
      </p>
    </div>
  )
}

/** Placeholder used by the registry when an activity has no dedicated view. */
export function LocalActivityFrame({ children }: { children: ReactNode }) {
  return <div className="local-activity">{children}</div>
}
