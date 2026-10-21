/**
 * Tic-Tac-Toe with a real opponent.
 *
 * The rules engine and the AI are both local and deterministic - this is a
 * genuinely playable game, not a simulation of one. It is labelled as a local
 * activity in the interface so it is never confused with a backend-backed
 * game.
 */

export type Cell = 'X' | 'O' | null
export type Board = Cell[]

export const EMPTY_BOARD: Board = Array.from({ length: 9 }, () => null)

export const LINES: number[][] = [
  [0, 1, 2],
  [3, 4, 5],
  [6, 7, 8],
  [0, 3, 6],
  [1, 4, 7],
  [2, 5, 8],
  [0, 4, 8],
  [2, 4, 6],
]

export type Outcome = 'ongoing' | 'x-win' | 'o-win' | 'draw'

export function winnerOf(board: Board): Outcome {
  for (const line of LINES) {
    const [a, b, c] = line
    if (a === undefined || b === undefined || c === undefined) continue
    if (board[a] !== null && board[a] === board[b] && board[b] === board[c]) {
      return board[a] === 'X' ? 'x-win' : 'o-win'
    }
  }
  return board.every((cell) => cell !== null) ? 'draw' : 'ongoing'
}

export function legalMoves(board: Board): number[] {
  if (winnerOf(board) !== 'ongoing') return []
  return board.map((cell, index) => (cell === null ? index : -1)).filter((index) => index >= 0)
}

export function applyMove(board: Board, index: number, player: Exclude<Cell, null>): Board {
  if (index < 0 || index > 8) return board
  if (board[index] !== null) return board
  const next = [...board]
  next[index] = player
  return next
}

/** Minimax with a small preference for fast wins and slow losses. */
export function minimax(board: Board, player: Exclude<Cell, null>, depth = 0): number {
  const outcome = winnerOf(board)
  if (outcome === 'x-win') return 10 - depth
  if (outcome === 'o-win') return depth - 10
  if (outcome === 'draw') return 0

  const moves = legalMoves(board)
  if (moves.length === 0) return 0

  let best = player === 'X' ? -Infinity : Infinity
  for (const move of moves) {
    const next = applyMove(board, move, player)
    const value = minimax(next, player === 'X' ? 'O' : 'X', depth + 1)
    best = player === 'X' ? Math.max(best, value) : Math.min(best, value)
  }
  return best
}

/** Pick the AI move. Ties are broken deterministically by cell order. */
export function bestMove(board: Board, player: Exclude<Cell, null> = 'O'): number | null {
  const moves = legalMoves(board)
  if (moves.length === 0) return null

  let bestScore = player === 'X' ? -Infinity : Infinity
  let best: number | null = null

  for (const move of moves) {
    const next = applyMove(board, move, player)
    const score = minimax(next, player === 'X' ? 'O' : 'X')
    if (player === 'X') {
      if (score > bestScore) {
        bestScore = score
        best = move
      }
    } else if (score < bestScore) {
      bestScore = score
      best = move
    }
  }
  return best
}

export function describeOutcome(outcome: Outcome): string {
  switch (outcome) {
    case 'x-win':
      return 'You win.'
    case 'o-win':
      return 'Sidekick wins this one.'
    case 'draw':
      return 'It is a draw.'
    default:
      return 'Your move.'
  }
}
