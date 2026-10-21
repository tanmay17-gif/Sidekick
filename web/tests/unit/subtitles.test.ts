import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { formatClock, parseSubtitles, parseTimestamp, stripCueMarkup, toWebVtt } from '@/lib/media/subtitles'

const SRT_PATH = resolve(process.cwd(), 'public/media/tears-of-steel/TOS-en.srt')

describe('parseSubtitles', () => {
  it('parses the shipped Tears of Steel subtitle track into real timed cues', () => {
    const source = readFileSync(SRT_PATH, 'utf8')
    const cues = parseSubtitles(source)

    expect(cues.length).toBeGreaterThan(50)
    expect(cues[0]?.start).toBeCloseTo(23, 3)
    expect(cues[0]?.end).toBeCloseTo(24.5, 3)
    expect(cues[0]?.text).toBe("You're a jerk, Thom.")
    expect(cues[cues.length - 1]?.end).toBeCloseTo(567, 3)
  })

  it('keeps cues ordered and indexes them contiguously', () => {
    const cues = parseSubtitles(readFileSync(SRT_PATH, 'utf8'))
    for (let index = 1; index < cues.length; index += 1) {
      const previous = cues[index - 1]
      const current = cues[index]
      expect(previous).toBeDefined()
      expect(current).toBeDefined()
      expect(current!.start).toBeGreaterThanOrEqual(previous!.start)
      expect(current!.index).toBe(index)
    }
  })

  it('parses WebVTT with a header and cue identifiers', () => {
    const vtt = ['WEBVTT', '', 'intro', '00:00:01.500 --> 00:00:04.000', 'Hello there'].join('\n')
    const cues = parseSubtitles(vtt)
    expect(cues).toHaveLength(1)
    expect(cues[0]?.start).toBeCloseTo(1.5, 3)
    expect(cues[0]?.end).toBeCloseTo(4, 3)
    expect(cues[0]?.text).toBe('Hello there')
  })

  it('drops cues with unreadable timings instead of guessing', () => {
    const broken = ['1', 'not-a-time --> also-not-a-time', 'Nope'].join('\n')
    expect(parseSubtitles(broken)).toHaveLength(0)
  })

  it('ignores NOTE and STYLE blocks', () => {
    const source = [
      'WEBVTT',
      '',
      'NOTE this is a comment',
      '',
      'STYLE',
      '::cue { color: red }',
      '',
      '00:00:02.000 --> 00:00:03.000',
      'Real line',
    ].join('\n')
    const cues = parseSubtitles(source)
    expect(cues).toHaveLength(1)
    expect(cues[0]?.text).toBe('Real line')
  })

  it('strips inline markup but keeps the words', () => {
    expect(stripCueMarkup('<i>Hello</i> <b>world</b>')).toBe('Hello world')
  })
})

describe('parseTimestamp', () => {
  it('reads SRT comma decimals', () => {
    expect(parseTimestamp('00:01:02,500')).toBeCloseTo(62.5, 3)
  })

  it('reads WebVTT dot decimals', () => {
    expect(parseTimestamp('00:01:02.500')).toBeCloseTo(62.5, 3)
  })

  it('reads short timestamps', () => {
    expect(parseTimestamp('01:02.500')).toBeCloseTo(62.5, 3)
  })

  it('returns null for junk', () => {
    expect(parseTimestamp('later')).toBeNull()
  })
})

describe('toWebVtt', () => {
  it('round-trips cues through WebVTT', () => {
    const cues = parseSubtitles(
      ['1', '00:00:01,000 --> 00:00:02,500', 'First line', '', '2', '00:00:03,000 --> 00:00:04,000', 'Second line'].join('\n'),
    )
    const reparsed = parseSubtitles(toWebVtt(cues))
    expect(reparsed).toHaveLength(2)
    expect(reparsed[0]?.start).toBeCloseTo(1, 3)
    expect(reparsed[0]?.text).toBe('First line')
    expect(reparsed[1]?.text).toBe('Second line')
  })
})

describe('formatClock', () => {
  it('formats minutes and seconds', () => {
    expect(formatClock(65)).toBe('1:05')
  })

  it('formats hours', () => {
    expect(formatClock(3725)).toBe('1:02:05')
  })

  it('clamps negatives', () => {
    expect(formatClock(-4)).toBe('0:00')
  })
})
