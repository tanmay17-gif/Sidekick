import { useMemo } from 'react'
import {
  emptyPosition,
  parseFen,
  parseSquareName,
  PIECE_GLYPHS,
  squareName,
  type PieceChar,
} from '@/lib/games/chess'

export interface ChessBoardProps {
  /** Position reported by the backend. */
  fen?: string | null
  /** Squares involved in the last move, e.g. ["e2", "e4"]. */
  lastMove?: string[]
  /** Squares the backend marks as legal targets for the selected piece. */
  legalTargets?: string[]
  /** Square the backend reports as the selected piece. */
  selected?: string | null
}

export function ChessBoard({ fen, lastMove = [], legalTargets = [], selected }: ChessBoardProps) {
  const position = useMemo(() => {
    if (!fen) return emptyPosition()
    try {
      return parseFen(fen)
    } catch {
      return emptyPosition()
    }
  }, [fen])

  const lastMoveSet = useMemo(
    () =>
      new Set(
        lastMove
          .map((name) => parseSquareName(name))
          .filter((value): value is { file: number; rank: number } => value !== null)
          .map((value) => squareName(value.file, value.rank)),
      ),
    [lastMove],
  )

  const legalSet = useMemo(
    () =>
      new Set(
        legalTargets
          .map((name) => parseSquareName(name))
          .filter((value): value is { file: number; rank: number } => value !== null)
          .map((value) => squareName(value.file, value.rank)),
      ),
    [legalTargets],
  )

  const selectedSquare = useMemo(() => {
    const parsed = selected ? parseSquareName(selected) : null
    return parsed ? squareName(parsed.file, parsed.rank) : null
  }, [selected])

  const cells = useMemo(() => {
    const result: Array<{ file: number; rank: number; piece: PieceChar | null; light: boolean }> = []
    for (let rank = 7; rank >= 0; rank -= 1) {
      for (let file = 0; file < 8; file += 1) {
        const square = position.squares.find((s) => s.file === file && s.rank === rank)
        result.push({
          file,
          rank,
          piece: square?.piece ?? null,
          light: (file + rank) % 2 === 0,
        })
      }
    }
    return result
  }, [position])

  if (!fen) {
    return (
      <p className="hint">
        No position has been reported by the backend yet. Start a chess game and the board will
        render the real position.
      </p>
    )
  }

  return (
    <div className="board" role="img" aria-label={`Chess position, ${position.turn} to move`}>
      {cells.map((cell) => {
        const name = squareName(cell.file, cell.rank)
        const isWhite = cell.piece !== null && cell.piece === cell.piece.toUpperCase()
        return (
          <div
            key={name}
            className="board__sq"
            data-light={cell.light}
            data-sel={selectedSquare === name}
            data-legal={legalSet.has(name)}
            title={name}
          >
            {cell.piece ? (
              <span className={`board__piece--${isWhite ? 'w' : 'b'}`} aria-hidden="true">
                {PIECE_GLYPHS[cell.piece]}
              </span>
            ) : null}
            {lastMoveSet.has(name) ? (
              <span
                aria-hidden="true"
                style={{
                  position: 'absolute',
                  inset: 0,
                  boxShadow: 'inset 0 0 0 2px color-mix(in srgb, var(--state-executing) 70%, transparent)',
                  pointerEvents: 'none',
                }}
              />
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
