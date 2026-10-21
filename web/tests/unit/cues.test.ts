import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { MediaCue } from '@/lib/api/types'
import {
  activeEvent,
  buildCompanionEvents,
  eventsReached,
  isSpeechSafe,
} from '@/lib/media/companion'
import { cueAt, cueDuration, cueProgress, findCueIndex, nextCueAfter } from '@/lib/media/cues'
import { parseSubtitles } from '@/lib/media/subtitles'

const SRT_PATH = resolve(process.cwd(), 'public/media/tears-of-steel/TOS-en.srt')
const realCues = parseSubtitles(readFileSync(SRT_PATH, 'utf8'))

const sampleCues: MediaCue[] = [
  { index: 0, start: 0, end: 2, text: 'First line' },
  { index: 1, start: 2, end: 4, text: 'Second line' },
  { index: 2, start: 4, end: 6, text: 'Third line' },
]

describe('cue lookup', () => {
  it('finds the active cue from real playback time', () => {
    expect(findCueIndex(sampleCues, 0)).toBe(0)
    expect(findCueIndex(sampleCues, 1.9)).toBe(0)
    expect(findCueIndex(sampleCues, 2)).toBe(1)
    expect(findCueIndex(sampleCues, 5.5)).toBe(2)
  })

  it('returns -1 in a gap between cues', () => {
    const spaced: MediaCue[] = [
      { index: 0, start: 0, end: 1, text: 'a' },
      { index: 1, start: 5, end: 6, text: 'b' },
    ]
    expect(findCueIndex(spaced, 3)).toBe(-1)
    expect(cueAt(spaced, 3)).toBeNull()
  })

  it('returns the next cue after a time', () => {
    expect(nextCueAfter(sampleCues, 1)?.index).toBe(1)
    expect(nextCueAfter(sampleCues, 10)).toBeNull()
  })

  it('reports duration and progress of the cued region', () => {
    expect(cueDuration(sampleCues)).toBe(6)
    expect(cueProgress(sampleCues, 3)).toBeCloseTo(0.5, 5)
    expect(cueProgress(sampleCues, 99)).toBe(1)
  })

  it('locates the real robot line in the shipped track', () => {
    const index = realCues.findIndex((cue) => /robot/i.test(cue.text))
    expect(index).toBeGreaterThanOrEqual(0)
    const cue = realCues[index]
    expect(cue).toBeDefined()
    expect(findCueIndex(realCues, cue!.start + 0.05)).toBe(index)
  })
})

describe('companion events', () => {
  const rules = [
    { pattern: '\\brobot\\b', title: 'Robotics mentioned', reason: 'because the line mentions a robot' },
    { pattern: '\\bspace\\b', title: 'Space ambition', reason: 'because the line mentions space' },
  ]

  it('derives events at the real timestamp of a matching cue', () => {
    const events = buildCompanionEvents({ rules, cues: realCues })
    expect(events.length).toBeGreaterThan(0)

    for (const event of events) {
      const cue = realCues.find((candidate) => candidate.index === event.cue.index)
      expect(cue).toBeDefined()
      // The event timestamp is the cue's real start time, not a timer.
      expect(event.at).toBe(cue!.start)
      expect(event.reason).toBeTruthy()
      expect(event.quote.length).toBeGreaterThan(0)
    }
  })

  it('orders events by media time', () => {
    const events = buildCompanionEvents({ rules, cues: realCues })
    for (let index = 1; index < events.length; index += 1) {
      expect(events[index]!.at).toBeGreaterThanOrEqual(events[index - 1]!.at)
    }
  })

  it('marks events as reached only once playback passes them', () => {
    const events = buildCompanionEvents({ rules, cues: realCues })
    const first = events[0]!
    expect(eventsReached(events, first.at - 1)).toHaveLength(0)
    expect(eventsReached(events, first.at)).toHaveLength(1)
    expect(eventsReached(events, first.at)[0]?.reached).toBe(true)
  })

  it('reports the active event for the current time', () => {
    const events = buildCompanionEvents({ rules, cues: realCues })
    const first = events[0]!
    expect(activeEvent(events, first.at - 1)).toBeNull()
    expect(activeEvent(events, first.at)?.id).toBe(first.id)
  })

  it('ignores a malformed rule instead of breaking playback', () => {
    const events = buildCompanionEvents({
      rules: [{ pattern: '([unclosed', title: 'Broken', reason: 'x' }],
      cues: realCues,
    })
    expect(events).toHaveLength(0)
  })

  it('knows when it is safe to speak (no dialogue on screen)', () => {
    expect(isSpeechSafe(sampleCues, 1)).toBe(false)
    expect(isSpeechSafe(sampleCues, 3)).toBe(false)
    const spaced: MediaCue[] = [
      { index: 0, start: 0, end: 1, text: 'a' },
      { index: 1, start: 5, end: 6, text: 'b' },
    ]
    expect(isSpeechSafe(spaced, 3)).toBe(true)
  })
})
