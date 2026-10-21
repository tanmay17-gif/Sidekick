import { describe, expect, it } from 'vitest'
import type { MediaCue } from '@/lib/api/types'
import {
  answerWhatJustHappened,
  canSpeak,
  DEFAULT_BUDGET,
  explainTheMoment,
  pushContext,
  reactToCue,
  type BuddyReaction,
} from '@/lib/movie/buddy'

const cue = (index: number, start: number, end: number, text: string): MediaCue => ({
  index,
  start,
  end,
  text,
})

describe('reaction rules', () => {
  it('greets on the very first caption line', () => {
    const reaction = reactToCue(cue(0, 1.2, 2.2, 'Hello.'), [], false)
    expect(reaction?.rule).toBe('first-words')
    expect(reaction?.reason).toMatch(/first line/i)
  })

  it('reacts to a caption that is marked as a sound', () => {
    const reaction = reactToCue(cue(3, 5.7, 9.1, '(birds chirping)'), [cue(0, 1, 2, 'Hi')], false)
    expect(reaction?.rule).toBe('sound')
  })

  it('reacts when the narration states a plan', () => {
    const reaction = reactToCue(
      cue(1, 2.2, 4.4, 'We are going to make a letter V.'),
      [cue(0, 1.2, 2.2, 'Hello.')],
      false,
    )
    expect(reaction?.rule).toBe('stated-plan')
  })

  it('reacts to a step, and notices a repeated step', () => {
    const first = reactToCue(
      cue(1, 21.6, 24.8, 'Twist the first soft two inch bubble.'),
      [cue(0, 1, 2, 'Hello.')],
      false,
    )
    expect(first?.rule).toBe('instruction')

    const repeat = reactToCue(
      cue(5, 45.4, 47.1, 'Lock both ends of the third bubble in one lock twist.'),
      [cue(3, 21.6, 24.8, 'Twist the first soft two inch bubble.')],
      false,
    )
    expect(repeat?.rule).toBe('variation')
  })

  it('says nothing for a blank caption line', () => {
    expect(reactToCue(cue(6, 12.5, 21.6, ''), [cue(0, 1, 2, 'Hello.')], false)).toBeNull()
  })

  it('says nothing about an ordinary line', () => {
    expect(
      reactToCue(cue(2, 4.5, 6.5, 'Something ordinary happened.'), [cue(0, 1, 2, 'Hello.')], false),
    ).toBeNull()
  })

  it('closes on the last caption line', () => {
    const reaction = reactToCue(cue(9, 10, 12, 'The end.'), [cue(0, 1, 2, 'Hello.')], true)
    expect(reaction?.rule).toBe('final-cue')
  })

  it('never invents anything outside the caption', () => {
    const reaction = reactToCue(cue(0, 1, 2, 'Hello.'), [], false)
    expect(reaction?.cue.text).toBe('Hello.')
  })
})

describe('speaking budget', () => {
  const base = {
    mode: 'active' as const,
    quietUntil: 0,
    now: 100_000,
    lastSpokeAt: null,
    spokenInWindow: 0,
    settings: DEFAULT_BUDGET,
    captionOnScreen: false,
  }

  it('allows a remark when everything is in order', () => {
    expect(canSpeak(base).allowed).toBe(true)
  })

  it('stays quiet while the companion is off', () => {
    expect(canSpeak({ ...base, mode: 'off' }).allowed).toBe(false)
  })

  it('stays quiet in quiet mode', () => {
    expect(canSpeak({ ...base, mode: 'quiet' }).allowed).toBe(false)
  })

  it('stays quiet until the quiet window expires', () => {
    const gate = canSpeak({ ...base, mode: 'quiet', quietUntil: 130_000 })
    expect(gate.allowed).toBe(false)
    expect(gate.reason).toMatch(/quiet/i)
  })

  it('never talks over a caption', () => {
    const gate = canSpeak({ ...base, captionOnScreen: true })
    expect(gate.allowed).toBe(false)
    expect(gate.reason).toMatch(/caption/i)
  })

  it('spends its budget', () => {
    const gate = canSpeak({ ...base, spokenInWindow: DEFAULT_BUDGET.budgetPerMinute })
    expect(gate.allowed).toBe(false)
    expect(gate.reason).toMatch(/budget/i)
  })

  it('cools down after the last remark', () => {
    const gate = canSpeak({
      ...base,
      lastSpokeAt: base.now - DEFAULT_BUDGET.cooldownSeconds * 1000 + 1000,
    })
    expect(gate.allowed).toBe(false)
    expect(gate.reason).toMatch(/cool/i)
  })

  it('speaks again once the cooldown has passed', () => {
    const gate = canSpeak({
      ...base,
      lastSpokeAt: base.now - DEFAULT_BUDGET.cooldownSeconds * 1000 - 1000,
    })
    expect(gate.allowed).toBe(true)
  })
})

describe('grounded answers', () => {
  const context: MediaCue[] = [
    cue(0, 20, 22, 'Twist the first soft two inch bubble.'),
    cue(1, 24, 26, 'Lock both ends of the first bubble in one lock twist.'),
  ]

  it('answers "what just happened" from the recent captions', () => {
    const answer = answerWhatJustHappened(context, 27)
    expect(answer.unavailable).toBe(false)
    expect(answer.say).toContain('Lock both ends of the first bubble')
    expect(answer.basis.length).toBe(2)
  })

  it('says it cannot answer when no caption covers the moment', () => {
    const answer = answerWhatJustHappened(context, 300)
    expect(answer.unavailable).toBe(true)
    expect(answer.say).toMatch(/cannot/i)
    expect(answer.reason).toMatch(/no caption/i)
  })

  it('explains a moment from the captions and says what it is reading', () => {
    const answer = explainTheMoment(context, 27)
    expect(answer.unavailable).toBe(false)
    expect(answer.say).toMatch(/caption/i)
    expect(answer.say).toMatch(/not the picture/i)
  })

  it('refuses to explain a moment it cannot see', () => {
    const answer = explainTheMoment(context, 300)
    expect(answer.unavailable).toBe(true)
    expect(answer.say).toMatch(/do not analyse the picture/i)
  })

  it('reports silence honestly', () => {
    const silent: MediaCue[] = [cue(0, 20, 22, '')]
    const answer = answerWhatJustHappened(silent, 23)
    expect(answer.unavailable).toBe(false)
    expect(answer.say).toMatch(/no spoken lines/i)
  })
})

describe('context memory', () => {
  it('is bounded', () => {
    let context: MediaCue[] = []
    for (let index = 0; index < 20; index += 1) {
      context = pushContext(context, cue(index, index, index + 0.5, `line ${index}`), 8)
    }
    expect(context).toHaveLength(8)
    expect(context[context.length - 1]?.text).toBe('line 19')
  })
})

describe('reaction shape', () => {
  it('records the trigger so the interface can show why', () => {
    const reaction: BuddyReaction | null = reactToCue(cue(0, 1, 2, 'Hello.'), [], false)
    expect(reaction).not.toBeNull()
    expect(reaction?.reason.length).toBeGreaterThan(10)
    expect(reaction?.at).toBe(1)
  })
})
