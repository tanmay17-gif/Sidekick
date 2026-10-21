import { describe, expect, it } from 'vitest'
import type { MediaCue } from '@/lib/api/types'
import { answerWhatJustHappened, explainTheMoment } from '@/lib/movie/buddy'

const CUES: MediaCue[] = [
  { index: 0, start: 0, end: 3, text: 'The lamp has to be lit before the tide comes in.' },
  { index: 1, start: 3.2, end: 6, text: 'Every night the keeper climbs the spiral stair.' },
  { index: 2, start: 6.2, end: 9, text: 'The sea has been louder this week.' },
  { index: 3, start: 9.2, end: 12, text: 'A storm is gathering beyond the rocks.' },
]

describe('grounded answers', () => {
  it('quotes the caption lines for "what just happened"', () => {
    const answer = answerWhatJustHappened(CUES, 10)
    expect(answer.unavailable).toBe(false)
    expect(answer.say).toContain('storm is gathering')
    expect(answer.basis.length).toBeGreaterThan(0)
  })

  it('says plainly when there is nothing to quote', () => {
    const answer = answerWhatJustHappened(CUES, 600)
    expect(answer.unavailable).toBe(true)
    expect(answer.say).toMatch(/cannot say what happened/i)
    expect(answer.reason).toMatch(/no caption cue/i)
  })

  it('explains a moment from the captions and says it is reading subtitles', () => {
    const answer = explainTheMoment(CUES, 10)
    expect(answer.unavailable).toBe(false)
    expect(answer.say).toContain('storm is gathering')
    expect(answer.say).toMatch(/reading the subtitle track, not the picture/i)
  })

  it('refuses to explain a moment with no captions', () => {
    const answer = explainTheMoment(CUES, 600)
    expect(answer.unavailable).toBe(true)
    expect(answer.say).toMatch(/do not analyse the picture/i)
  })

  it('does not claim to have seen anything', () => {
    const answer = explainTheMoment(CUES, 10)
    expect(answer.say).not.toMatch(/i can see|the shot|camera/i)
  })
})
