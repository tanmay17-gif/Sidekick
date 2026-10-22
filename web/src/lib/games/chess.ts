/**
 * Minimal FEN handling for rendering a chess position returned by the backend.
 *
 * The browser never decides moves - it only renders the position the backend
 * reports. `lastMove` is used to highlight the squares that changed.
 */

export type PieceChar = 'p' | 'n' | 'b' | 'r' | 'q' | 'k' | 'P' | 'N' | 'B' | 'R' | 'Q' | 'K'

export interface ChessSquare {
  file: number // 0 = a-file
  rank: number // 0 = rank 1
  piece: PieceChar | null
}

export interface ChessPosition {
  squares: ChessSquare[]
  turn: 'w' | 'b'
  /** File/rank of the king in check, if any. */
  checkSquare: { file: number; rank: number } | null
}

export const PIECE_GLYPHS: Record<PieceChar, string> = {
  p: '♟',
  n: '♞',
  b: '♝',
  r: '♜',
  q: '♛',
  k: '♚',
  P: '♙',
  N: '♘',
  B: '♗',
  R: '♖',
  Q: '♕',
  K: '♔',
}

export function emptyPosition(): ChessPosition {
  return { squares: Array.from({ length: 64 }, () => ({ file: 0, rank: 0, piece: null })), turn: 'w', checkSquare: null }
}

/** Parse the first two fields of a FEN string ("placement" and "side to move"). */
export function parseFen(fen: string): ChessPosition {
  const fields = fen.trim().split(/\s+/)
  const placement = fields[0] ?? ''
  const turn = fields[1] === 'b' ? 'b' : 'w'

  const squares: ChessSquare[] = []
  let rank = 7
  let file = 0

  for (const char of placement) {
    if (char === '/') {
      rank -= 1
      file = 0
      continue
    }
    if (char >= '1' && char <= '8') {
      file += Number(char)
      continue
    }
    const piece = char as PieceChar
    squares.push({ file, rank, piece })
    file += 1
  }

  // Fill any missing squares (malformed FEN) so the board still renders.
  while (squares.length < 64) {
    squares.push({ file: (squares.length % 8) + 8, rank: 0, piece: null })
  }

  const kingInCheck = squares.find((square) => square.piece === (turn === 'w' ? 'K' : 'k'))
  return {
    squares: squares.slice(0, 64),
    turn,
    checkSquare: kingInCheck && turn === 'w' ? { file: kingInCheck.file, rank: kingInCheck.rank } : null,
  }
}

export function squareName(file: number, rank: number): string {
  const letters = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
  return `${letters[file] ?? '?'}${rank + 1}`
}

export function parseSquareName(name: string): { file: number; rank: number } | null {
  const match = /^([a-h])([1-8])$/.exec(name.trim().toLowerCase())
  if (!match) return null
  const file = (match[1] ?? 'a').charCodeAt(0) - 97
  const rank = Number(match[2]) - 1
  return { file, rank }
}

/** Squares covered by the most recent move, for highlighting. */
export function lastMoveSquares(move: { from?: string; to?: string } | null): string[] {
  if (!move) return []
  const result: string[] = []
  if (move.from) result.push(move.from)
  if (move.to) result.push(move.to)
  return result
}
