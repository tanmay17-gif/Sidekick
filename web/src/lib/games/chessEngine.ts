import { Chess, type Move, type PieceSymbol, type Square } from 'chess.js'

export interface ChessEngineState {
  fen: string
  turn: 'w' | 'b'
  isCheck: boolean
  isCheckmate: boolean
  isStalemate: boolean
  isDraw: boolean
  isGameOver: boolean
  history: string[]
  lastMove: string[]
  statusText: string
}

export type VoiceParseResult =
  | { kind: 'move'; move: Move; description: string }
  | { kind: 'ambiguous'; prompt: string; candidateMoves: Move[] }
  | { kind: 'illegal'; reason: string }
  | { kind: 'reset'; description: string }
  | { kind: 'undo'; description: string }
  | { kind: 'help'; message: string }
  | { kind: 'unrecognized'; utterance: string }

const PIECE_NAME_MAP: Record<string, PieceSymbol> = {
  pawn: 'p',
  knight: 'n',
  horse: 'n',
  night: 'n',
  bishop: 'b',
  rook: 'r',
  castle: 'r',
  queen: 'q',
  king: 'k',
}

const PIECE_FULL_NAMES: Record<PieceSymbol, string> = {
  p: 'pawn',
  n: 'knight',
  b: 'bishop',
  r: 'rook',
  q: 'queen',
  k: 'king',
}

/**
 * Normalizes speech recognition text into standard chess coordinates.
 * Handles spoken artifacts like "see for" -> "c4", "before" -> "b4", "to" / "two" -> 2.
 */
export function normalizeChessSpokenText(raw: string): string {
  let text = raw.toLowerCase().trim()

  // Word numbers to digits
  text = text
    .replace(/\bzero\b/g, '0')
    .replace(/\bone\b/g, '1')
    .replace(/\btwo\b/g, '2')
    .replace(/\bthree\b/g, '3')
    .replace(/\bfour\b/g, '4')
    .replace(/\bfive\b/g, '5')
    .replace(/\bsix\b/g, '6')
    .replace(/\bseven\b/g, '7')
    .replace(/\beight\b/g, '8')

  // Common speech-to-text misheard squares
  text = text
    .replace(/\bsee\s*(\d)\b/g, 'c$1')
    .replace(/\bsea\s*(\d)\b/g, 'c$1')
    .replace(/\bbee\s*(\d)\b/g, 'b$1')
    .replace(/\bday\s*(\d)\b/g, 'd$1')
    .replace(/\be\s*to\b/g, 'e2')
    .replace(/\be\s*too\b/g, 'e2')
    .replace(/\be\s*for\b/g, 'e4')
    .replace(/\bcolonel\b/g, 'c')
    .replace(/\bnight\b/g, 'knight')
    .replace(/\bhorses?\b/g, 'knight')

  return text
}

/**
 * Parses natural language commands into structured chess moves.
 */
export function interpretChessVoiceCommand(
  utterance: string,
  game: Chess,
): VoiceParseResult {
  const normalized = normalizeChessSpokenText(utterance)

  if (/^(reset|restart|new game|start over)\b/i.test(normalized)) {
    return { kind: 'reset', description: 'Reset the chess game.' }
  }

  if (/^(undo|take back|takeback)\b/i.test(normalized)) {
    return { kind: 'undo', description: 'Undo the last move.' }
  }

  if (/^(help|how do i play|what can i say|valid moves)\b/i.test(normalized)) {
    return {
      kind: 'help',
      message:
        'You can say commands like: "Move knight to F3", "Pawn to E4", "Move the pawn in front of the king two squares", or "Castle kingside".',
    }
  }

  const legalMoves = game.moves({ verbose: true })
  if (legalMoves.length === 0) {
    return { kind: 'illegal', reason: 'Game is already over. Say "new game" to play again.' }
  }

  // 1. Castling commands
  if (
    /\b(castle\s+kingside|kingside\s+castle|castle\s+short|o-o)\b/i.test(normalized) ||
    (normalized.includes('castle') && normalized.includes('king'))
  ) {
    const castleKingside = legalMoves.find(
      (m) => m.flags.includes('k') || m.san === 'O-O',
    )
    if (castleKingside) {
      return { kind: 'move', move: castleKingside, description: 'Castle kingside' }
    }
    return { kind: 'illegal', reason: 'Kingside castling is not legal in this position.' }
  }

  if (
    /\b(castle\s+queenside|queenside\s+castle|castle\s+long|o-o-o)\b/i.test(normalized) ||
    (normalized.includes('castle') && normalized.includes('queen'))
  ) {
    const castleQueenside = legalMoves.find(
      (m) => m.flags.includes('q') || m.san === 'O-O-O',
    )
    if (castleQueenside) {
      return { kind: 'move', move: castleQueenside, description: 'Castle queenside' }
    }
    return { kind: 'illegal', reason: 'Queenside castling is not legal in this position.' }
  }

  // 2. Relative pawn phrases
  // "move the pawn in front of the king two squares" / "king pawn two squares"
  if (
    normalized.includes('pawn in front of the king') ||
    normalized.includes('king pawn') ||
    normalized.includes("king's pawn")
  ) {
    const isTwo = normalized.includes('two') || normalized.includes('2')
    const targetSquare = game.turn() === 'w' ? (isTwo ? 'e4' : 'e3') : (isTwo ? 'e5' : 'e6')
    const candidate = legalMoves.find(
      (m) => m.piece === 'p' && m.to === targetSquare,
    )
    if (candidate) {
      return {
        kind: 'move',
        move: candidate,
        description: `Pawn to ${targetSquare.toUpperCase()}`,
      }
    }
    return {
      kind: 'illegal',
      reason: `Moving the king's pawn to ${targetSquare.toUpperCase()} is not legal.`,
    }
  }

  // "move the pawn in front of the queen two squares" / "queen pawn two squares"
  if (
    normalized.includes('pawn in front of the queen') ||
    normalized.includes('queen pawn') ||
    normalized.includes("queen's pawn")
  ) {
    const isTwo = normalized.includes('two') || normalized.includes('2')
    const targetSquare = game.turn() === 'w' ? (isTwo ? 'd4' : 'd3') : (isTwo ? 'd5' : 'd6')
    const candidate = legalMoves.find(
      (m) => m.piece === 'p' && m.to === targetSquare,
    )
    if (candidate) {
      return {
        kind: 'move',
        move: candidate,
        description: `Pawn to ${targetSquare.toUpperCase()}`,
      }
    }
    return {
      kind: 'illegal',
      reason: `Moving the queen's pawn to ${targetSquare.toUpperCase()} is not legal.`,
    }
  }

  // 3. Coordinate-to-coordinate phrases: "e2 to e4", "move e2 to e4", "from b1 to c3"
  const fromToMatch = /\b(?:from\s+)?([a-h][1-8])\s+(?:to\s+)?([a-h][1-8])\b/i.exec(normalized)
  if (fromToMatch && fromToMatch[1] && fromToMatch[2]) {
    const from = fromToMatch[1].toLowerCase() as Square
    const to = fromToMatch[2].toLowerCase() as Square
    const candidate = legalMoves.find((m) => m.from === from && m.to === to)
    if (candidate) {
      return {
        kind: 'move',
        move: candidate,
        description: `${candidate.piece.toUpperCase()} from ${from.toUpperCase()} to ${to.toUpperCase()}`,
      }
    }
    return {
      kind: 'illegal',
      reason: `Move from ${from.toUpperCase()} to ${to.toUpperCase()} is not legal.`,
    }
  }

  // 4. Piece to destination: "move (the/my) [piece] to [square]" or "[piece] to [square]"
  // e.g. "move the bishop to c4", "knight to f3", "queen to h5", "pawn to e4"
  const pieceDestMatch =
    /\b(?:move\s+(?:the\s+|my\s+)?)?(pawn|knight|bishop|rook|queen|king)\s+(?:to\s+|into\s+)?([a-h][1-8])\b/i.exec(
      normalized,
    )

  if (pieceDestMatch && pieceDestMatch[1] && pieceDestMatch[2]) {
    const pieceWord = pieceDestMatch[1].toLowerCase()
    const targetSquare = pieceDestMatch[2].toLowerCase() as Square
    const pieceChar = PIECE_NAME_MAP[pieceWord]

    const matchingMoves = legalMoves.filter(
      (m) => m.piece === pieceChar && m.to === targetSquare,
    )

    if (matchingMoves.length === 0) {
      return {
        kind: 'illegal',
        reason: `No ${pieceWord} can legally move to ${targetSquare.toUpperCase()} in this position.`,
      }
    }

    if (matchingMoves.length === 1) {
      const selected = matchingMoves[0]!
      return {
        kind: 'move',
        move: selected,
        description: `${pieceWord.charAt(0).toUpperCase() + pieceWord.slice(1)} to ${targetSquare.toUpperCase()}`,
      }
    }

    // Ambiguity resolution: multiple pieces of the same type can reach target
    const origins = matchingMoves.map((m) => m.from.toUpperCase()).join(' or ')
    return {
      kind: 'ambiguous',
      prompt: `Multiple ${pieceWord}s can reach ${targetSquare.toUpperCase()} (from ${origins}). Which one would you like to move?`,
      candidateMoves: matchingMoves,
    }
  }

  // 5. Bare destination or standard notation: "e4", "nf3", "bc4", "qh5", "c4"
  const bareSan = normalized.replace(/\bmove\b/g, '').trim().replace(/\s+/g, '')
  const sanCandidate = legalMoves.find(
    (m) =>
      m.san.toLowerCase() === bareSan.toLowerCase() ||
      m.to.toLowerCase() === bareSan.toLowerCase() && m.piece === 'p',
  )
  if (sanCandidate) {
    return {
      kind: 'move',
      move: sanCandidate,
      description: `${PIECE_FULL_NAMES[sanCandidate.piece]} to ${sanCandidate.to.toUpperCase()}`,
    }
  }

  return { kind: 'unrecognized', utterance }
}

/**
 * Calculates a legal response for the AI opponent.
 * Prefers capturing high-value pieces or advancing center pawns/knights.
 */
export function getAiLegalResponse(game: Chess): { move: Move; description: string } | null {
  const legalMoves = game.moves({ verbose: true })
  if (legalMoves.length === 0) return null

  // Value mapping for captures
  const pieceValues: Record<string, number> = {
    p: 10,
    n: 30,
    b: 30,
    r: 50,
    q: 90,
    k: 900,
  }

  // Score candidate moves
  let bestMove: Move = legalMoves[0]!
  let bestScore = -9999

  for (const move of legalMoves) {
    let score = 0
    // Captures get points
    if (move.captured) {
      score += (pieceValues[move.captured] ?? 0) * 10 - (pieceValues[move.piece] ?? 0)
    }
    // Checks get points
    if (move.san.includes('+')) {
      score += 15
    }
    // Center control (d4, d5, e4, e5)
    if (['d4', 'd5', 'e4', 'e5'].includes(move.to)) {
      score += 5
    }

    // Small random tie-breaker
    score += Math.random() * 2

    if (score > bestScore) {
      bestScore = score
      bestMove = move
    }
  }

  const pieceName = PIECE_FULL_NAMES[bestMove.piece]
  const capText = bestMove.captured ? ` takes ${PIECE_FULL_NAMES[bestMove.captured]}` : ''
  const description = `${pieceName.charAt(0).toUpperCase() + pieceName.slice(1)}${capText} to ${bestMove.to.toUpperCase()}`

  return { move: bestMove, description }
}
