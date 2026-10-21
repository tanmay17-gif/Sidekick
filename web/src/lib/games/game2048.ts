/**
 * 2048 - a genuinely playable local puzzle.
 *
 * The merge rules here are the real 2048 rules; the board is real state, not
 * an animation of a number that the backend pretended to produce.
 */

export type Tile = number | null
export type Board2048 = Tile[]

export const SIZE = 4
export const EMPTY_2048: Board2048 = Array.from({ length: SIZE * SIZE }, () => null)

export interface MoveResult {
  board: Board2048
  score: number
  moved: boolean
  /** Cells that were created or merged, for the movement animation. */
  changed: number[]
}

export function createBoard(): Board2048 {
  const board = [...EMPTY_2048]
  addTile(board)
  addTile(board)
  return board
}

function addTile(board: Board2048): number | null {
  const empty = board.map((tile, index) => (tile === null ? index : -1)).filter((i) => i >= 0)
  if (empty.length === 0) return null
  const index = empty[Math.floor(Math.random() * empty.length)] ?? null
  if (index === null) return null
  board[index] = Math.random() < 0.9 ? 2 : 4
  return index
}

/**
 * The pure slide-and-merge rule. It never spawns a tile, so it can be tested
 * deterministically.
 */
export function slide(
  board: Board2048,
  direction: 'left' | 'right' | 'up' | 'down',
): MoveResult {
  const next: Board2048 = [...board]
  const changed: number[] = []
  let score = 0

  for (let line = 0; line < SIZE; line += 1) {
    const indices = lineIndices(line, direction)
    const values = indices.map((index) => next[index] ?? 0)

    const compacted: number[] = []
    for (const value of values) {
      if (value !== 0) compacted.push(value)
    }

    const merged: number[] = []
    for (let index = 0; index < compacted.length; index += 1) {
      const current = compacted[index] ?? 0
      const nextValue = compacted[index + 1]
      if (nextValue !== undefined && nextValue === current) {
        merged.push(current * 2)
        score += current * 2
        index += 1
      } else {
        merged.push(current)
      }
    }

    while (merged.length < SIZE) merged.push(0)

    indices.forEach((target, position) => {
      const source = merged[position] ?? 0
      const value = source === 0 ? null : source
      if (next[target] !== value) changed.push(target)
      next[target] = value
    })
  }

  return { board: next, score, moved: changed.length > 0, changed }
}

/** A full turn: the pure rule plus the random tile that appears after it. */
export function move(board: Board2048, direction: 'left' | 'right' | 'up' | 'down'): MoveResult {
  const result = slide(board, direction)
  if (!result.moved) return result
  const next = [...result.board]
  addTile(next)
  return { ...result, board: next }
}

function lineIndices(line: number, direction: 'left' | 'right' | 'up' | 'down'): number[] {
  const indices: number[] = []
  for (let position = 0; position < SIZE; position += 1) {
    if (direction === 'left') indices.push(line * SIZE + position)
    else if (direction === 'right') indices.push(line * SIZE + (SIZE - 1 - position))
    else if (direction === 'up') indices.push(position * SIZE + line)
    else indices.push((SIZE - 1 - position) * SIZE + line)
  }
  return indices
}

export function canMove(board: Board2048): boolean {
  if (board.some((tile) => tile === null)) return true
  for (let row = 0; row < SIZE; row += 1) {
    for (let column = 0; column < SIZE; column += 1) {
      const index = row * SIZE + column
      const current = board[index] ?? null
      if (column < SIZE - 1) {
        const right = board[index + 1] ?? null
        if (right !== null && current === right) return true
      }
      if (row < SIZE - 1) {
        const below = board[index + SIZE] ?? null
        if (below !== null && current === below) return true
      }
    }
  }
  return false
}

export function highestTile(board: Board2048): number {
  return board.reduce<number>((best, tile) => (tile !== null && tile > best ? tile : best), 0)
}
