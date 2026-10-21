import type { Action, ActionState } from '@/lib/api/types'
import type { ActionViewState } from '@/state/useSidekick'

/**
 * The user-facing language layer.
 *
 * The normal experience never shows a tool name, a request id, a session id,
 * a confidence number or a model name. This module is the only place that
 * knows how to say what the backend did in plain words - and it only says
 * what the backend actually reported.
 */

/** How each capability is described to a person. */
const TOOL_PHRASES: Record<string, string> = {
  'music.play': 'your music app',
  'media.open': 'the media player',
  'note.write': 'your notes',
  'note.read': 'your notes',
  'timer.set': 'your timers',
  'timer.list': 'your timers',
  'game.chess': 'the chess board',
  'workspace.delete': 'your workspace',
}

/** The subject of the sentence, without ever naming the tool. */
export function subjectFor(action: Action): string {
  const phrase = TOOL_PHRASES[action.tool]
  if (phrase) return phrase
  // An unknown tool is described by what it was asked to do, never by name.
  const description = action.description?.trim()
  if (description) return 'that'
  return 'it'
}

/** A short, human status line for one action. */
export function actionStatusLine(action: Action, state: ActionViewState): string {
  const subject = subjectFor(action)
  switch (state) {
    case 'pending':
      return `Getting ready to work on ${subject}.`
    case 'awaiting_confirmation':
      return `I need your OK before I touch ${subject}.`
    case 'running':
      return `Working on ${subject}.`
    case 'paused':
      return `Paused while I was working on ${subject}.`
    case 'succeeded':
      return `Done with ${subject}.`
    case 'failed':
      return 'That did not work.'
    case 'timed_out':
      return 'That took too long.'
    case 'cancelled':
      return `Cancelled - ${subject} were left alone.`
    case 'superseded':
      return `Replaced by a newer request.`
    default:
      return `Working on ${subject}.`
  }
}

/** The headline a person sees while an action is moving. */
export function workingLine(action: Action, state: ActionViewState): string | null {
  const subject = subjectFor(action)
  if (state === 'running') {
    const description = action.description?.trim()
    if (description && description.length > 3) {
      const sentence = description.charAt(0).toUpperCase() + description.slice(1)
      return `${sentence}…`
    }
    return `Working on ${subject}…`
  }
  if (state === 'awaiting_confirmation') return 'I need your OK first.'
  if (state === 'pending') return `Getting ready for ${subject}…`
  return null
}

/**
 * A failure a person can act on. The technical detail stays in the developer
 * area.
 */
export function friendlyFailure(action: Action, state: ActionViewState): {
  message: string
  recovery: string | null
} {
  const subject = subjectFor(action)
  if (state === 'timed_out') {
    return {
      message: `${subject} took too long and I stopped waiting.`,
      recovery: 'Try again with a smaller request.',
    }
  }
  if (action.error?.code === 'tool_unavailable') {
    return {
      message: `${subject} is not set up on this backend yet.`,
      recovery: 'Ask for something else, or configure the provider.',
    }
  }
  if (action.error?.code === 'test_failed') {
    return {
      message: `${subject} was changed, but the tests it runs did not pass.`,
      recovery: 'Open the developer view to see the diff and the test output.',
    }
  }
  if (state === 'failed') {
    return {
      message: `${subject} did not work.`,
      recovery: action.error?.retryable ? 'Try again.' : 'Try asking for it a different way.',
    }
  }
  if (state === 'cancelled') {
    return { message: `I stopped working on ${subject}.`, recovery: null }
  }
  return { message: `Something went wrong with ${subject}.`, recovery: 'Try again.' }
}

/** The spoken summary of a turn, in the assistant's voice. */
export function spokenSummary(response: {
  speech?: string | null
  clarification: { question: string } | null
  action_plan: Action[]
}): string {
  if (response.speech) return response.speech
  if (response.clarification) return response.clarification.question

  const actions = response.action_plan ?? []
  if (actions.length === 0) return 'I did not find anything to do there.'

  const awaiting = actions.find((action) => action.state === 'awaiting_confirmation')
  if (awaiting) return `I need your OK before I touch ${subjectFor(awaiting)}.`

  const failed = actions.find((action) => action.state === 'failed')
  if (failed) return `That did not work on ${subjectFor(failed)}.`

  const cancelled = actions.find((action) => action.state === 'cancelled')
  if (cancelled) return `I stopped - ${subjectFor(cancelled)} was left alone.`

  const done = actions.filter((action) => action.state === 'succeeded')
  if (done.length > 0) {
    if (done.length === 1) return `Done with ${subjectFor(done[0]!)}.`
    return `Done with ${done.map((action) => subjectFor(action)).join(' and ')}.`
  }

  const running = actions.find((action) => action.state === 'running')
  if (running) return `Working on ${subjectFor(running)}.`

  return 'On it.'
}

/** The short label used on a state chip. */
export function stateChipLabel(state: ActionViewState): string {
  const labels: Record<ActionViewState, string> = {
    pending: 'getting ready',
    awaiting_confirmation: 'needs your OK',
    running: 'working',
    paused: 'paused',
    succeeded: 'done',
    failed: 'did not work',
    timed_out: 'took too long',
    cancelled: 'cancelled',
    superseded: 'replaced',
    unknown: 'unknown',
  }
  return labels[state]
}

export type { ActionState }
