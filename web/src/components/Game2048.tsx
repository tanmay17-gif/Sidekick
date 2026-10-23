import { useCallback, useEffect, useState } from 'react'
import {
  canMove,
  createBoard,
  highestTile,
  move,
  type Board2048,
  type MoveResult,
} from '@/lib/games/game2048'
import { interpret2048VoiceCommand } from '@/lib/games/voiceGames'
import { useVoiceInput } from '@/lib/voice/useVoiceInput'

const DIRECTIONS = ['left', 'right', 'up', 'down'] as const
type Direction = (typeof DIRECTIONS)[number]

const KEY_DIRECTIONS: Record<string, Direction> = {
  ArrowLeft: 'left',
  ArrowRight: 'right',
  ArrowUp: 'up',
  ArrowDown: 'down',
  a: 'left',
  d: 'right',
  w: 'up',
  s: 'down',
}

export interface Game2048Props {
  speakText?: (text: string) => void
}

/** 2048 - a local puzzle with real merge rules and voice control. */
export function Game2048({ speakText }: Game2048Props = {}) {
  const [state, setState] = useState<MoveResult>(() => {
    const board = createBoard()
    return { board, score: 0, moved: true, changed: [] }
  })
  const [voiceNotice, setVoiceNotice] = useState<string | null>(null)

  const apply = useCallback(
    (direction: Direction) => {
      setState((current) => {
        const result = move(current.board, direction)
        if (result.moved) {
          if (!canMove(result.board)) {
            speakText?.(`Game over! Final score: ${result.score}`)
          }
          return result
        }
        return current
      })
    },
    [speakText],
  )

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return
      const direction = KEY_DIRECTIONS[event.key]
      if (!direction) return
      event.preventDefault()
      apply(direction)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [apply])

  const reset = useCallback(() => {
    setState({ board: createBoard(), score: 0, moved: true, changed: [] })
    setVoiceNotice(null)
    speakText?.('2048 board reset. New game!')
  }, [speakText])

  const handleVoiceCommand = useCallback(
    (transcript: string) => {
      const result = interpret2048VoiceCommand(transcript, state.board)
      if (result.kind === 'action') {
        apply(result.direction)
        setVoiceNotice(result.description)
      } else if (result.kind === 'control' && result.action === 'reset') {
        reset()
      } else {
        setVoiceNotice(`Say "Left", "Right", "Up", or "Down".`)
      }
    },
    [apply, reset, state.board],
  )

  const voice = useVoiceInput({
    onFinal: (transcript) => {
      handleVoiceCommand(transcript)
    },
  })

  const board: Board2048 = state.board
  const over = !canMove(board)

  return (
    <div className="stack stack--tight" style={{ maxWidth: 360, margin: '0 auto' }}>
      <div className="row row--wrap" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <button
          type="button"
          className={`btn btn--sm ${voice.status === 'listening' ? 'btn--primary' : 'btn--ghost'}`}
          onClick={() => (voice.status === 'listening' ? voice.stop() : voice.start())}
          title="Speak move (e.g. 'Swipe left', 'Up')"
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

      <div className="row row--wrap">
        <span className="badge badge--quiet">score {state.score}</span>
        <span className="badge badge--quiet">best tile {highestTile(board)}</span>
        {over ? <span className="badge badge--danger">no moves left</span> : null}
      </div>

      <div className="tiles" role="grid" aria-label="2048 board">
        {board.map((tile, index) => (
          <div
            key={index}
            role="gridcell"
            className="tiles__cell"
            data-tile={tile ?? undefined}
            data-changed={state.changed.includes(index) || undefined}
            aria-label={tile === null ? 'Empty' : `Tile ${tile}`}
          >
            {tile ?? ''}
          </div>
        ))}
      </div>

      <div className="row row--wrap">
        {DIRECTIONS.map((direction) => (
          <button
            type="button"
            key={direction}
            className="btn btn--sm"
            onClick={() => apply(direction)}
          >
            {direction}
          </button>
        ))}
      </div>
      <p className="hint">
        Arrow keys or voice ("Slide left", "Up", "Right", "Down") move the board.
      </p>
    </div>
  )
}
