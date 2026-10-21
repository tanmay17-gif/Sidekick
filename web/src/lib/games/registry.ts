import type { ComponentType } from 'react'
import { Game2048 } from '@/components/Game2048'
import { TicTacToe } from '@/components/TicTacToe'

/**
 * Local activities.
 *
 * These run entirely in the browser: the rules, the opponent and the state are
 * real. They are deliberately separated from the backend-reported games so
 * that a local game is never mistaken for a service-backed one.
 */
export interface LocalActivity {
  id: string
  name: string
  /** One line explaining that it needs no backend. */
  summary: string
  Component: ComponentType
}

export const LOCAL_ACTIVITIES: LocalActivity[] = [
  {
    id: 'tic-tac-toe',
    name: 'Tic-Tac-Toe',
    summary: 'Plays locally against a minimax opponent. No account, no backend.',
    Component: TicTacToe,
  },
  {
    id: '2048',
    name: '2048',
    summary: 'The real merge rules, running locally in the browser.',
    Component: Game2048,
  },
]
