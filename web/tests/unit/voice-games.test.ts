import { describe, expect, it } from 'vitest'
import {
  interpretTicTacToeVoiceCommand,
  interpret2048VoiceCommand,
} from '@/lib/games/voiceGames'
import { EMPTY_BOARD } from '@/lib/games/tictactoe'
import { createBoard } from '@/lib/games/game2048'

describe('Tic-Tac-Toe Voice Commands', () => {
  it('parses positional cell commands', () => {
    const resCenter = interpretTicTacToeVoiceCommand('play center', EMPTY_BOARD, 'X')
    expect(resCenter.kind).toBe('action')
    if (resCenter.kind === 'action') {
      expect(resCenter.cellIndex).toBe(4)
    }

    const resTopLeft = interpretTicTacToeVoiceCommand('top left', EMPTY_BOARD, 'X')
    expect(resTopLeft.kind).toBe('action')
    if (resTopLeft.kind === 'action') {
      expect(resTopLeft.cellIndex).toBe(0)
    }
  })

  it('parses numbered cell commands', () => {
    const resCell5 = interpretTicTacToeVoiceCommand('cell 5', EMPTY_BOARD, 'X')
    expect(resCell5.kind).toBe('action')
    if (resCell5.kind === 'action') {
      expect(resCell5.cellIndex).toBe(4)
    }
  })

  it('rejects moves on already occupied cells', () => {
    const board = [...EMPTY_BOARD]
    board[4] = 'X'
    const res = interpretTicTacToeVoiceCommand('center', board, 'X')
    expect(res.kind).toBe('invalid')
    if (res.kind === 'invalid') {
      expect(res.reason).toContain('already taken')
    }
  })

  it('rejects moves when not player turn', () => {
    const res = interpretTicTacToeVoiceCommand('top left', EMPTY_BOARD, 'O')
    expect(res.kind).toBe('invalid')
    if (res.kind === 'invalid') {
      expect(res.reason).toContain('Sidekick’s turn')
    }
  })

  it('handles reset commands', () => {
    const res = interpretTicTacToeVoiceCommand('new game', EMPTY_BOARD, 'X')
    expect(res.kind).toBe('control')
  })
})

describe('2048 Voice Commands', () => {
  it('parses directional swipe commands', () => {
    const board = createBoard()
    expect(interpret2048VoiceCommand('swipe left', board)).toEqual({
      kind: 'action',
      action: 'move',
      direction: 'left',
      description: 'Slide left',
    })
    expect(interpret2048VoiceCommand('move right', board)).toEqual({
      kind: 'action',
      action: 'move',
      direction: 'right',
      description: 'Slide right',
    })
    expect(interpret2048VoiceCommand('up', board)).toEqual({
      kind: 'action',
      action: 'move',
      direction: 'up',
      description: 'Slide up',
    })
    expect(interpret2048VoiceCommand('slide down', board)).toEqual({
      kind: 'action',
      action: 'move',
      direction: 'down',
      description: 'Slide down',
    })
  })

  it('handles reset command for 2048', () => {
    const board = createBoard()
    expect(interpret2048VoiceCommand('restart', board)).toEqual({
      kind: 'control',
      action: 'reset',
      description: 'Resetting 2048.',
    })
  })
})
