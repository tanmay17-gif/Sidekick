import { describe, expect, it } from 'vitest'
import { Chess } from 'chess.js'
import {
  interpretChessVoiceCommand,
  getAiLegalResponse,
  normalizeChessSpokenText,
} from '@/lib/games/chessEngine'

describe('Chess Voice Command Interpreter', () => {
  it('normalizes speech artifacts', () => {
    expect(normalizeChessSpokenText('move see four')).toBe('move c4')
    expect(normalizeChessSpokenText('knight to bee three')).toBe('knight to b3')
    expect(normalizeChessSpokenText('pawn to e for')).toBe('pawn to e4')
  })

  it('interprets opening pawn moves', () => {
    const chess = new Chess()
    const result = interpretChessVoiceCommand('move the pawn in front of the king two squares', chess)
    expect(result.kind).toBe('move')
    if (result.kind === 'move') {
      expect(result.move.from).toBe('e2')
      expect(result.move.to).toBe('e4')
    }
  })

  it('interprets knight moves like "move my knight to f3"', () => {
    const chess = new Chess()
    const result = interpretChessVoiceCommand('move my knight to f3', chess)
    expect(result.kind).toBe('move')
    if (result.kind === 'move') {
      expect(result.move.from).toBe('g1')
      expect(result.move.to).toBe('f3')
    }
  })

  it('interprets bishop moves like "move the bishop to c4" once opened', () => {
    const chess = new Chess()
    chess.move('e4')
    chess.move('e5')
    const result = interpretChessVoiceCommand('move the bishop to c4', chess)
    expect(result.kind).toBe('move')
    if (result.kind === 'move') {
      expect(result.move.from).toBe('f1')
      expect(result.move.to).toBe('c4')
    }
  })

  it('interprets queen moves like "move the queen to h5"', () => {
    const chess = new Chess()
    chess.move('e4')
    chess.move('e5')
    const result = interpretChessVoiceCommand('move the queen to h5', chess)
    expect(result.kind).toBe('move')
    if (result.kind === 'move') {
      expect(result.move.from).toBe('d1')
      expect(result.move.to).toBe('h5')
    }
  })

  it('handles castling kingside', () => {
    const chess = new Chess()
    chess.move('e4')
    chess.move('e5')
    chess.move('Nf3')
    chess.move('Nc6')
    chess.move('Bc4')
    chess.move('Bc5')
    const result = interpretChessVoiceCommand('castle kingside', chess)
    expect(result.kind).toBe('move')
    if (result.kind === 'move') {
      expect(result.move.san).toBe('O-O')
    }
  })

  it('rejects illegal moves and explains why', () => {
    const chess = new Chess()
    // Bishop cannot move through pawns
    const result = interpretChessVoiceCommand('move bishop to c4', chess)
    expect(result.kind).toBe('illegal')
    if (result.kind === 'illegal') {
      expect(result.reason).toContain('No bishop can legally move to C4')
    }
  })

  it('detects ambiguity when multiple pieces of the same type can reach target', () => {
    // Set up position where both knights can reach d2: Nbd2 or Nfd2 (with d2 vacant)
    const chess = new Chess('rnbqkbnr/pppppppp/8/8/3P4/5N2/PPP1PPPP/RNBQKB1R w KQkq - 0 1')
    const result = interpretChessVoiceCommand('move knight to d2', chess)
    expect(result.kind).toBe('ambiguous')
    if (result.kind === 'ambiguous') {
      expect(result.prompt).toContain('Multiple knights can reach D2')
      expect(result.candidateMoves.length).toBe(2)
    }
  })

  it('opponent AI always returns a legal move', () => {
    const chess = new Chess()
    chess.move('e4')
    const aiMove = getAiLegalResponse(chess)
    expect(aiMove).not.toBeNull()
    const legalMoves = chess.moves({ verbose: true }).map((m) => m.san)
    expect(legalMoves).toContain(aiMove!.move.san)
  })

  it('handles reset and help commands', () => {
    const chess = new Chess()
    expect(interpretChessVoiceCommand('new game', chess).kind).toBe('reset')
    expect(interpretChessVoiceCommand('help', chess).kind).toBe('help')
    expect(interpretChessVoiceCommand('undo move', chess).kind).toBe('undo')
  })
})
