import type { ReactNode } from 'react'
import {
  applyMove,
  bestMove,
  describeOutcome,
  EMPTY_BOARD,
  legalMoves,
  winnerOf,
  type Board,
} from '@/lib/games/tictactoe'
import { interpretTicTacToeVoiceCommand } from '@/lib/games/voiceGames'
import { useVoiceInput } from '@/lib/voice/useVoiceInput'
import { useState, useCallback } from 'react'

export interface TicTacToeProps {
  speakText?: (text: string) => void
}

/**
 * Tic-Tac-Toe against the local minimax engine with voice and touch interaction.
 */
export function TicTacToe({ speakText }: TicTacToeProps = {}) {
  const [board, setBoard] = useState<Board>(EMPTY_BOARD)
  const [turn, setTurn] = useState<'X' | 'O'>('X')
  const [lastMove, setLastMove] = useState<number | null>(null)
  const [voiceNotice, setVoiceNotice] = useState<string | null>(null)

  const outcome = winnerOf(board)

  const play = useCallback(
    (index: number) => {
      if (outcome !== 'ongoing' || turn !== 'X') return
      if (board[index] !== null) return

      const afterPlayer = applyMove(board, index, 'X')
      setBoard(afterPlayer)
      setLastMove(index)
      setTurn('O')
      setVoiceNotice(null)

      const outcomeAfterPlayer = winnerOf(afterPlayer)
      if (outcomeAfterPlayer !== 'ongoing') {
        speakText?.(describeOutcome(outcomeAfterPlayer))
        return
      }

      // Minimax AI responds
      setTimeout(() => {
        const reply = bestMove(afterPlayer, 'O')
        if (reply === null) return
        const afterAi = applyMove(afterPlayer, reply, 'O')
        setBoard(afterAi)
        setLastMove(reply)
        setTurn('X')

        const outcomeAfterAi = winnerOf(afterAi)
        if (outcomeAfterAi !== 'ongoing') {
          speakText?.(`Sidekick played. ${describeOutcome(outcomeAfterAi)}`)
        } else {
          speakText?.(`Sidekick played in cell ${reply + 1}. Your turn.`)
        }
      }, 350)
    },
    [board, outcome, speakText, turn],
  )

  const reset = useCallback(() => {
    setBoard(EMPTY_BOARD)
    setTurn('X')
    setLastMove(null)
    setVoiceNotice(null)
    speakText?.('Tic-Tac-Toe reset. Your move.')
  }, [speakText])

  const handleVoiceCommand = useCallback(
    (transcript: string) => {
      const result = interpretTicTacToeVoiceCommand(transcript, board, turn)
      if (result.kind === 'action') {
        play(result.cellIndex)
        setVoiceNotice(result.description)
      } else if (result.kind === 'control' && result.action === 'reset') {
        reset()
      } else if (result.kind === 'invalid') {
        setVoiceNotice(result.reason)
        speakText?.(result.reason)
      } else {
        setVoiceNotice(`Could not recognize: "${transcript}". Say e.g. "Play center" or "Cell 5".`)
      }
    },
    [board, play, reset, speakText, turn],
  )

  const voice = useVoiceInput({
    onFinal: (transcript) => {
      handleVoiceCommand(transcript)
    },
  })

  const moves = legalMoves(board)

  return (
    <div className="stack stack--tight" style={{ maxWidth: 360, margin: '0 auto' }}>
      <div className="row row--wrap" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <button
          type="button"
          className={`btn btn--sm ${voice.status === 'listening' ? 'btn--primary' : 'btn--ghost'}`}
          onClick={() => (voice.status === 'listening' ? voice.stop() : voice.start())}
          title="Speak move (e.g. 'Play center' or 'Top left')"
          aria-label="Speak move"
        >
          {voice.status === 'listening' ? '🎙️ Listening…' : '🎙️ Speak move'}
        </button>
        <button type="button" className="btn btn--sm" onClick={reset}>
          New game
        </button>
      </div>

      {voiceNotice && (
        <div
          role="status"
          style={{
            fontSize: 'var(--text-xs)',
            padding: '4px 8px',
            borderRadius: 6,
            background: 'hsl(210 30% 95%)',
            color: 'hsl(210 50% 30%)',
          }}
        >
          {voiceNotice}
        </div>
      )}

      <div className="ttt" role="grid" aria-label="Tic tac toe board">
        {board.map((cell, index) => (
          <button
            type="button"
            key={index}
            role="gridcell"
            className="ttt__cell"
            data-player={cell ?? undefined}
            data-last={lastMove === index || undefined}
            aria-label={`Cell ${index + 1}: ${cell ?? 'empty'}`}
            disabled={cell !== null || outcome !== 'ongoing' || turn !== 'X'}
            onClick={() => play(index)}
          >
            {cell ?? ''}
          </button>
        ))}
      </div>
      <div className="row row--wrap">
        {outcome !== 'ongoing' ? (
          <span className="badge badge--quiet">{describeOutcome(outcome)}</span>
        ) : null}
        <span className="badge badge--quiet">
          {turn === 'X' ? 'your move' : 'sidekick is thinking'}
        </span>
      </div>
      <p className="hint">
        {moves.length} cell{moves.length === 1 ? '' : 's'} left. Say "Play center" or "Top left", or click a cell.
      </p>
    </div>
  )
}

/** Placeholder used by the registry when an activity has no dedicated view. */
export function LocalActivityFrame({ children }: { children: ReactNode }) {
  return <div className="local-activity">{children}</div>
}
