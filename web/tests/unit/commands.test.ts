import { describe, expect, it } from 'vitest'
import { containsActivation, parseBuddyCommand } from '@/lib/movie/commands'

describe('Movie Buddy commands', () => {
  it('activates the companion on its own, without naming a film', () => {
    const command = parseBuddyCommand('Turn on Movie Buddy.')
    expect(command?.kind).toBe('activate')
  })

  it('accepts a few natural ways of asking for it', () => {
    for (const phrase of [
      'turn on movie buddy',
      'please switch on the movie buddy',
      'start movie buddy',
      'enable movie buddy',
    ]) {
      expect(parseBuddyCommand(phrase)?.kind).toBe('activate')
    }
  })

  it('recognises playing a film and turning the companion on', () => {
    const command = parseBuddyCommand('Play me a movie and turn on Movie Buddy.')
    expect(command?.kind).toBe('play-a-movie')
    expect(containsActivation('Play me a movie and turn on Movie Buddy.')).toBe(true)
  })

  it('goes quiet', () => {
    expect(parseBuddyCommand('Be quiet for a bit.')?.kind).toBe('quiet')
    expect(parseBuddyCommand('shut up')?.kind).toBe('quiet')
    expect(parseBuddyCommand('stop talking')?.kind).toBe('quiet')
  })

  it('answers what just happened', () => {
    expect(parseBuddyCommand('What just happened?')?.kind).toBe('what-happened')
  })

  it('explains a moment', () => {
    expect(parseBuddyCommand('Explain that moment.')?.kind).toBe('explain')
  })

  it('pauses the movie', () => {
    expect(parseBuddyCommand('Pause the movie.')?.kind).toBe('pause')
  })

  it('goes back a number of seconds', () => {
    expect(parseBuddyCommand('Go back 30 seconds.')).toMatchObject({
      kind: 'seek-back',
      seconds: 30,
    })
    expect(parseBuddyCommand('Go back 10 seconds.')).toMatchObject({
      kind: 'seek-back',
      seconds: 10,
    })
  })

  it('defaults a vague rewind to thirty seconds', () => {
    expect(parseBuddyCommand('rewind a bit')).toMatchObject({
      kind: 'seek-back',
      seconds: 30,
    })
  })

  it('resumes the companion', () => {
    expect(parseBuddyCommand('Resume Movie Buddy.')?.kind).toBe('resume-buddy')
  })

  it('turns the companion off', () => {
    expect(parseBuddyCommand('turn off movie buddy')?.kind).toBe('deactivate')
  })

  it('does not swallow ordinary requests', () => {
    for (const phrase of [
      'play a song on spotify',
      'write a function that greets the user',
      'start a chess game',
      'what is the weather',
    ]) {
      expect(parseBuddyCommand(phrase)).toBeNull()
    }
  })

  it('ignores empty input', () => {
    expect(parseBuddyCommand('   ')).toBeNull()
  })
})
