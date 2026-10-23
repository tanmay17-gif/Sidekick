import type { Board } from '@/lib/games/tictactoe'
import type { Board2048 } from '@/lib/games/game2048'

export type TicTacToeVoiceResult =
  | { kind: 'action'; action: 'play'; cellIndex: number; description: string }
  | { kind: 'control'; action: 'reset' | 'restart'; description: string }
  | { kind: 'invalid'; reason: string }
  | { kind: 'unrecognized' }

export type Game2048VoiceResult =
  | { kind: 'action'; action: 'move'; direction: 'left' | 'right' | 'up' | 'down'; description: string }
  | { kind: 'control'; action: 'reset' | 'restart'; description: string }
  | { kind: 'unrecognized' }

const TTT_POSITIONS: Record<string, number> = {
  'top left': 0,
  'upper left': 0,
  'top middle': 1,
  'top center': 1,
  'top right': 2,
  'upper right': 2,
  'middle left': 3,
  'center left': 3,
  center: 4,
  middle: 4,
  'middle middle': 4,
  'middle right': 5,
  'center right': 5,
  'bottom left': 6,
  'lower left': 6,
  'bottom middle': 7,
  'bottom center': 7,
  'bottom right': 8,
  'lower right': 8,
}

/**
 * Interprets a voice command for Tic-Tac-Toe.
 */
export function interpretTicTacToeVoiceCommand(
  utterance: string,
  board: Board,
  turn: 'X' | 'O',
): TicTacToeVoiceResult {
  const text = utterance.toLowerCase().trim()

  if (/^(new game|restart|reset|start over)\b/.test(text)) {
    return { kind: 'control', action: 'reset', description: 'Resetting Tic-Tac-Toe.' }
  }

  if (turn !== 'X') {
    return { kind: 'invalid', reason: 'It is Sidekick’s turn to move.' }
  }

  // Numbered cells: "cell 1" to "cell 9" (1-indexed for humans)
  const cellMatch = /\bcell\s*([1-9])\b/.exec(text) || /\b(square|spot|number)\s*([1-9])\b/.exec(text)
  if (cellMatch && cellMatch[1]) {
    const idx = parseInt(cellMatch[1], 10) - 1
    if (board[idx] !== null) {
      return { kind: 'invalid', reason: `Cell ${idx + 1} is already occupied by ${board[idx]}.` }
    }
    return {
      kind: 'action',
      action: 'play',
      cellIndex: idx,
      description: `Played X in cell ${idx + 1}.`,
    }
  }

  // Positional phrases: "top left", "center", "bottom right", etc.
  for (const [posName, idx] of Object.entries(TTT_POSITIONS)) {
    if (text.includes(posName)) {
      if (board[idx] !== null) {
        return { kind: 'invalid', reason: `The ${posName} square is already taken.` }
      }
      return {
        kind: 'action',
        action: 'play',
        cellIndex: idx,
        description: `Played X in the ${posName}.`,
      }
    }
  }

  // Digits alone e.g. "one", "two", "five"
  const wordDigits: Record<string, number> = {
    one: 0,
    two: 1,
    three: 2,
    four: 3,
    five: 4,
    six: 5,
    seven: 6,
    eight: 7,
    nine: 8,
  }
  for (const [word, idx] of Object.entries(wordDigits)) {
    if (text === word || text === `play ${word}`) {
      if (board[idx] !== null) {
        return { kind: 'invalid', reason: `Cell ${idx + 1} is already taken.` }
      }
      return {
        kind: 'action',
        action: 'play',
        cellIndex: idx,
        description: `Played X in cell ${idx + 1}.`,
      }
    }
  }

  return { kind: 'unrecognized' }
}

/**
 * Interprets a voice command for 2048.
 */
export function interpret2048VoiceCommand(
  utterance: string,
  _board: Board2048,
): Game2048VoiceResult {
  const text = utterance.toLowerCase().trim()

  if (/^(new game|restart|reset|start over)\b/.test(text)) {
    return { kind: 'control', action: 'reset', description: 'Resetting 2048.' }
  }

  if (/\b(left|slide left|swipe left|move left|go left)\b/.test(text)) {
    return { kind: 'action', action: 'move', direction: 'left', description: 'Slide left' }
  }
  if (/\b(right|slide right|swipe right|move right|go right)\b/.test(text)) {
    return { kind: 'action', action: 'move', direction: 'right', description: 'Slide right' }
  }
  if (/\b(up|slide up|swipe up|move up|go up)\b/.test(text)) {
    return { kind: 'action', action: 'move', direction: 'up', description: 'Slide up' }
  }
  if (/\b(down|slide down|swipe down|move down|go down)\b/.test(text)) {
    return { kind: 'action', action: 'move', direction: 'down', description: 'Slide down' }
  }

  return { kind: 'unrecognized' }
}
