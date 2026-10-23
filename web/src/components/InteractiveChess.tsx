import { useState, useMemo, useCallback, useRef } from 'react'
import { Chess, type Square } from 'chess.js'
import {
  parseFen,
  parseSquareName,
  squareName,
  type PieceChar,
  PIECE_GLYPHS,
} from '@/lib/games/chess'
import {
  interpretChessVoiceCommand,
  getAiLegalResponse,
  type VoiceParseResult,
} from '@/lib/games/chessEngine'
import { useVoiceInput } from '@/lib/voice/useVoiceInput'

export interface InteractiveChessProps {
  initialFen?: string | null
  onMoveMade?: (move: { from: string; to: string; fen: string }) => void
  speakText?: (text: string) => void
}

export function InteractiveChess({
  initialFen,
  onMoveMade,
  speakText,
}: InteractiveChessProps) {
  // Authoritative chess instance
  const chessRef = useRef<Chess>(new Chess(initialFen || undefined))
  const [fen, setFen] = useState<string>(() => chessRef.current.fen())
  const [selectedSquare, setSelectedSquare] = useState<string | null>(null)
  const [lastMove, setLastMove] = useState<string[]>([])
  const [history, setHistory] = useState<string[]>([])
  const [status, setStatus] = useState<string>('Your move (White)')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [aiThinking, setAiThinking] = useState(false)

  const chess = chessRef.current

  const position = useMemo(() => {
    try {
      return parseFen(fen)
    } catch {
      return parseFen(chess.fen())
    }
  }, [fen, chess])

  // Get legal target squares for selected piece using authoritative chess.js
  const legalTargets = useMemo(() => {
    if (!selectedSquare) return []
    const square = selectedSquare.toLowerCase() as Square
    const moves = chess.moves({ square, verbose: true })
    return moves.map((m) => m.to.toLowerCase())
  }, [chess, selectedSquare, fen])

  const announce = useCallback(
    (text: string) => {
      setStatus(text)
      speakText?.(text)
    },
    [speakText],
  )

  const executeMove = useCallback(
    (from: string, to: string, description?: string) => {
      try {
        const move = chess.move({
          from: from.toLowerCase() as Square,
          to: to.toLowerCase() as Square,
          promotion: 'q',
        })

        if (!move) {
          setErrorMessage(`Illegal move: ${from} to ${to}`)
          return false
        }

        const newFen = chess.fen()
        setFen(newFen)
        setLastMove([from.toLowerCase(), to.toLowerCase()])
        setHistory((prev) => [...prev, move.san])
        setSelectedSquare(null)
        setErrorMessage(null)

        const moveText = description || `${move.piece.toUpperCase()} to ${to.toUpperCase()}`
        onMoveMade?.({ from, to, fen: newFen })

        // Check if game is over
        if (chess.isCheckmate()) {
          announce(`Checkmate! You win!`)
          return true
        }
        if (chess.isDraw() || chess.isStalemate()) {
          announce(`Game over: Draw by ${chess.isStalemate() ? 'stalemate' : 'draw'}.`)
          return true
        }

        if (chess.isCheck()) {
          setStatus(`${moveText}. Check! Sidekick is thinking…`)
        } else {
          setStatus(`${moveText}. Sidekick is thinking…`)
        }

        // Trigger AI opponent legal turn
        setAiThinking(true)
        setTimeout(() => {
          const aiResponse = getAiLegalResponse(chess)
          if (!aiResponse) {
            setAiThinking(false)
            return
          }

          chess.move(aiResponse.move)
          const afterAiFen = chess.fen()
          setFen(afterAiFen)
          setLastMove([aiResponse.move.from, aiResponse.move.to])
          setHistory((prev) => [...prev, aiResponse.move.san])
          setAiThinking(false)

          if (chess.isCheckmate()) {
            announce(`Sidekick played ${aiResponse.description}. Checkmate! Sidekick wins.`)
          } else if (chess.isDraw() || chess.isStalemate()) {
            announce(`Sidekick played ${aiResponse.description}. Game over: Draw.`)
          } else if (chess.isCheck()) {
            announce(`Sidekick played ${aiResponse.description}. Check! Your turn.`)
          } else {
            announce(`Sidekick played ${aiResponse.description}. Your turn.`)
          }
        }, 600)

        return true
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Illegal move'
        setErrorMessage(msg)
        return false
      }
    },
    [announce, chess, onMoveMade],
  )

  const handleSquareClick = useCallback(
    (name: string) => {
      if (aiThinking || chess.isGameOver()) return

      const parsed = parseSquareName(name)
      if (!parsed) return

      const clickedSquare = position.squares.find(
        (s) => s.file === parsed.file && s.rank === parsed.rank,
      )

      // If already selected and clicking a valid legal target
      if (selectedSquare && legalTargets.includes(name.toLowerCase())) {
        executeMove(selectedSquare, name)
        return
      }

      // Select piece if it belongs to White (player turn)
      if (clickedSquare?.piece) {
        const isWhite = clickedSquare.piece === clickedSquare.piece.toUpperCase()
        if (isWhite && chess.turn() === 'w') {
          setSelectedSquare(name)
          setErrorMessage(null)
          return
        }
      }

      setSelectedSquare(null)
    },
    [aiThinking, chess, executeMove, legalTargets, position.squares, selectedSquare],
  )

  const handleVoiceCommand = useCallback(
    (transcript: string) => {
      setErrorMessage(null)
      const parsed: VoiceParseResult = interpretChessVoiceCommand(transcript, chess)

      switch (parsed.kind) {
        case 'move':
          executeMove(parsed.move.from, parsed.move.to, parsed.description)
          break
        case 'ambiguous':
          setErrorMessage(parsed.prompt)
          announce(parsed.prompt)
          break
        case 'illegal':
          setErrorMessage(parsed.reason)
          announce(parsed.reason)
          break
        case 'reset':
          chess.reset()
          setFen(chess.fen())
          setSelectedSquare(null)
          setLastMove([])
          setHistory([])
          setErrorMessage(null)
          announce('Chess game reset. Your turn (White).')
          break
        case 'undo':
          chess.undo() // undo black AI
          chess.undo() // undo white player
          setFen(chess.fen())
          setSelectedSquare(null)
          setLastMove([])
          announce('Move undone. Your turn.')
          break
        case 'help':
          setErrorMessage(parsed.message)
          announce(parsed.message)
          break
        case 'unrecognized':
          setErrorMessage(`Could not recognize chess move: "${transcript}". Say e.g. "Move knight to F3".`)
          break
      }
    },
    [announce, chess, executeMove],
  )

  const voice = useVoiceInput({
    onFinal: (transcript) => {
      handleVoiceCommand(transcript)
    },
  })

  const resetGame = () => {
    chess.reset()
    setFen(chess.fen())
    setSelectedSquare(null)
    setLastMove([])
    setHistory([])
    setErrorMessage(null)
    announce('Game reset. Your turn (White).')
  }

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

  const lastMoveSet = useMemo(() => new Set(lastMove), [lastMove])
  const legalSet = useMemo(() => new Set(legalTargets), [legalTargets])

  return (
    <div className="stack stack--tight" style={{ maxWidth: 460, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className={`badge ${chess.isCheck() ? 'badge--danger' : 'badge--live'}`}>
          {status}
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            type="button"
            className={`btn btn--sm ${voice.status === 'listening' ? 'btn--primary' : 'btn--ghost'}`}
            onClick={() => (voice.status === 'listening' ? voice.stop() : voice.start())}
            title="Speak chess command (e.g. 'Knight to F3')"
            aria-label="Speak chess move"
          >
            {voice.status === 'listening' ? '🎙️ Listening…' : '🎙️ Speak move'}
          </button>
          <button type="button" className="btn btn--sm btn--ghost" onClick={resetGame}>
            Reset
          </button>
        </div>
      </div>

      {errorMessage && (
        <div
          role="alert"
          style={{
            fontSize: 'var(--text-xs)',
            padding: '6px 10px',
            borderRadius: 6,
            background: 'hsl(0 80% 95%)',
            color: 'hsl(0 75% 35%)',
            border: '1px solid hsl(0 70% 85%)',
          }}
        >
          {errorMessage}
        </div>
      )}

      <div
        className="board"
        role="img"
        aria-label={`Interactive Chess board, ${chess.turn() === 'w' ? 'White' : 'Black'} to move`}
      >
        {cells.map((cell) => {
          const name = squareName(cell.file, cell.rank)
          const isWhite = cell.piece !== null && cell.piece === cell.piece.toUpperCase()
          const isSelected = selectedSquare === name
          const isLegal = legalSet.has(name)

          return (
            <div
              key={name}
              className="board__sq"
              data-light={cell.light}
              data-sel={isSelected}
              data-legal={isLegal}
              title={name}
              onClick={() => handleSquareClick(name)}
              style={{
                cursor: (cell.piece && isWhite) || isLegal ? 'pointer' : 'default',
                position: 'relative',
                background: isSelected
                  ? 'hsl(50 90% 80%)'
                  : isLegal
                    ? 'hsl(140 70% 85%)'
                    : undefined,
              }}
            >
              {cell.piece ? (
                <span
                  className={`board__piece--${isWhite ? 'w' : 'b'}`}
                  aria-hidden="true"
                  style={{ fontSize: '1.75rem' }}
                >
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

      {history.length > 0 && (
        <div
          style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--ink-faint)',
            overflowX: 'auto',
            whiteSpace: 'nowrap',
          }}
        >
          Moves: {history.join(', ')}
        </div>
      )}
    </div>
  )
}
