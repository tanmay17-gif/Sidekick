import { describe, expect, it } from 'vitest'
import {
  applyMove,
  bestMove,
  EMPTY_BOARD,
  legalMoves,
  minimax,
  winnerOf,
  type Board,
} from '@/lib/games/tictactoe'
import {
  canMove,
  createBoard,
  highestTile,
  move,
  slide,
  SIZE,
  type Board2048,
} from '@/lib/games/game2048'
import { parseFen } from '@/lib/games/chess'

describe('tic-tac-toe rules', () => {
  it('detects every winning line', () => {
    const rows = [
      [0, 1, 2],
      [3, 4, 5],
      [6, 7, 8],
      [0, 3, 6],
      [1, 4, 7],
      [2, 5, 8],
      [0, 4, 8],
      [2, 4, 6],
    ]
    for (const line of rows) {
      const board = [...EMPTY_BOARD]
      for (const index of line) board[index] = 'X'
      expect(winnerOf(board)).toBe('x-win')
    }
  })

  it('detects a draw', () => {
    const board = ['X', 'O', 'X', 'X', 'O', 'O', 'O', 'X', 'X']
    expect(winnerOf(board as never)).toBe('draw')
  })

  it('refuses to overwrite an occupied cell', () => {
    const board = applyMove(EMPTY_BOARD, 4, 'X')
    expect(applyMove(board, 4, 'O')).toEqual(board)
  })

  it('lists only the empty cells as legal', () => {
    const board = applyMove(EMPTY_BOARD, 0, 'X')
    expect(legalMoves(board)).toHaveLength(8)
    expect(legalMoves(board)).not.toContain(0)
  })

  it('has no legal moves once the game is over', () => {
    const board = ['X', 'X', 'X', 'O', 'O', null, null, null, null] as unknown as Board
    expect(legalMoves(board)).toHaveLength(0)
  })
})

describe('tic-tac-toe opponent', () => {
  it('takes the winning move when one exists', () => {
    // O owns 0 and 1, so 2 completes the top row.
    const board = applyMove(applyMove(EMPTY_BOARD, 0, 'O'), 1, 'O')
    expect(bestMove(board, 'O')).toBe(2)
  })

  it('blocks an immediate loss', () => {
    // X threatens index 8 (diagonal 0-4-8); O must take 4.
    const board = applyMove(applyMove(EMPTY_BOARD, 0, 'X'), 1, 'O')
    const threatening = applyMove(board, 8, 'X')
    const reply = bestMove(threatening, 'O')
    expect(reply).toBe(4)
  })

  it('plays a legal move in every reachable position', () => {
    const board = applyMove(applyMove(applyMove(EMPTY_BOARD, 4, 'X'), 0, 'O'), 8, 'X')
    const move = bestMove(board, 'O')
    expect(move).not.toBeNull()
    expect(legalMoves(board)).toContain(move)
  })

  it('never loses from an empty board (the minimax value is a draw)', () => {
    // With perfect play the empty board is a draw, so the value is 0.
    expect(minimax(EMPTY_BOARD, 'O')).toBe(0)
  })
})

describe('2048 rules', () => {
  const row = (values: (number | null)[]): Board2048 => values

  it('merges equal tiles once per move', () => {
    const board = row([2, 2, 4, null, null, null, null, null, null, null, null, null, null, null, null, null])
    const result = slide(board, 'left')
    expect(result.board.slice(0, 2)).toEqual([4, 4])
    expect(result.score).toBe(4)
  })

  it('does not merge a tile twice in one move', () => {
    const board = row([2, 2, 2, 2, null, null, null, null, null, null, null, null, null, null, null, null])
    const result = slide(board, 'left')
    // 2+2 -> 4, then 2+2 -> 4. The result is [4, 4], not [8].
    expect(result.board.slice(0, 2)).toEqual([4, 4])
    expect(result.score).toBe(8)
  })

  it('moves tiles to the left edge', () => {
    const board = row([null, null, null, 2, null, null, null, null, null, null, null, null, null, null, null, null])
    const result = slide(board, 'left')
    expect(result.board[0]).toBe(2)
    expect(result.board[3]).toBeNull()
  })

  it('moves tiles to the right edge', () => {
    const board = row([2, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null])
    const result = slide(board, 'right')
    expect(result.board[3]).toBe(2)
  })

  it('moves tiles vertically', () => {
    const board = row([2, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null])
    const result = slide(board, 'down')
    expect(result.board[12]).toBe(2)
  })

  it('reports no legal move on a full blocked board', () => {
    const blocked: Board2048 = [2, 4, 2, 4, 4, 2, 4, 2, 2, 4, 2, 4, 4, 2, 4, 2]
    expect(canMove(blocked)).toBe(false)
  })

  it('starts with two tiles', () => {
    const board = createBoard()
    const filled = board.filter((tile) => tile !== null)
    expect(filled).toHaveLength(2)
    expect(filled.every((tile) => tile === 2 || tile === 4)).toBe(true)
  })

  it('reports the highest tile', () => {
    const board = row([1024, 4, null, null, null, null, null, null, null, null, null, null, null, null, null, null])
    expect(highestTile(board)).toBe(1024)
  })

  it('keeps the board the right size', () => {
    expect(createBoard()).toHaveLength(SIZE * SIZE)
  })

  it('spawns exactly one new tile after a real move', () => {
    const board = row([
      null, null, null, 2, null, null, null, null, null, null, null, null, null, null, null, null,
    ])
    const result = move(board, 'left')
    expect(result.moved).toBe(true)
    expect(result.board[0]).toBe(2)
    const filled = result.board.filter((tile) => tile !== null)
    expect(filled).toHaveLength(2)
  })

  it('does not move when the direction changes nothing', () => {
    const board = row([
      4, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null,
    ])
    // The tile is already in the leftmost column of its row.
    const result = move(board, 'up')
    expect(result.moved).toBe(false)
  })
})

describe('chess position parsing', () => {
  it('parses the starting position', () => {
    const position = parseFen('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
    expect(position.squares).toHaveLength(64)
    expect(position.turn).toBe('w')
    const pieces = position.squares.filter((square) => square.piece !== null)
    expect(pieces).toHaveLength(32)
  })

  it('reports the side to move', () => {
    expect(parseFen('8/8/8/8/8/8/8/4k3 b - - 0 1').turn).toBe('b')
  })
})
