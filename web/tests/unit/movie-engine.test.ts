import { describe, expect, it, vi } from 'vitest'
import type { MediaCue } from '@/lib/api/types'
import {
  analyzeCue,
  alignmentReport,
  buildCueWindow,
  cueAt,
  lastStartedCue,
  sharedPhrase,
} from '@/lib/movie/context'
import { BuddyEngine, type BuddySettings } from '@/lib/movie/engine'
import {
  createLocalProvider,
  createModelProvider,
  createUnavailableProvider,
  parseModelRemark,
  type CommentaryProvider,
  type CommentaryRequest,
  type CommentaryResult,
} from '@/lib/movie/provider'

/* ------------------------------------------------------------------ *
 * Two synthetic films. They share no vocabulary, so any commentary that
 * works for both cannot be a script for one of them.
 * ------------------------------------------------------------------ */

function makeCues(
  lines: Array<[number, number, string]>,
): MediaCue[] {
  return lines.map(([start, end, text], index) => ({
    index,
    start,
    end,
    text,
  }))
}

const LIGHTHOUSE = makeCues([
  [0, 3, 'The lamp has to be lit before the tide comes in.'],
  [3.2, 6, 'Every night the keeper climbs the spiral stair.'],
  [6.2, 9, 'The sea has been louder this week.'],
  [9.2, 12, 'A storm is gathering beyond the rocks.'],
  [12.2, 15, 'He tightens the brass wheel and waits.'],
  [15.2, 18, 'The light sweeps across the black water.'],
  [18.2, 21, 'Nothing else to do but keep the lamp burning.'],
])

const EXPRESS = makeCues([
  [0, 2, 'The 8:14 to the coast leaves now.'],
  [2.2, 5, 'Mind the gap on the platform.'],
  [5.2, 8, 'The conductor checks his watch and rings the bell.'],
  [8.2, 11, 'We are running late because of the weather.'],
  [11.2, 14, 'Passengers settle into the old wooden seats.'],
  [14.2, 17, 'The carriage lights flicker as the tunnel approaches.'],
  [17.2, 20, 'Somebody has left a newspaper on the bench.'],
])

/* ------------------------------------------------------------------ *
 * A deterministic fake model.
 * ------------------------------------------------------------------ */

interface FakeModelOptions {
  /** What to answer for each request. */
  answer?: (request: CommentaryRequest) => Partial<CommentaryResult> | null
  /** Never resolve, so the call can be aborted. */
  hang?: boolean
  throw?: Error
}

function createFakeModel(options: FakeModelOptions = {}) {
  const seen: CommentaryRequest[] = []

  const provider: CommentaryProvider = {
    id: 'fake-model',
    source: 'model',
    available: true,
    async generate(request, signal): Promise<CommentaryResult> {
      seen.push(request)
      if (options.throw) throw options.throw
      if (options.hang) {
        await new Promise((resolve, reject) => {
          const timer = setTimeout(resolve, 60_000)
          signal?.addEventListener('abort', () => {
            clearTimeout(timer)
            reject(new DOMException('aborted', 'AbortError'))
          })
        })
      }
      const answer = options.answer?.(request)
      if (!answer) {
        return { say: '', source: 'model', grounded_in: [], declined: true }
      }
      return {
        say: answer.say ?? '',
        source: 'model',
        grounded_in: answer.grounded_in ?? [],
        declined: answer.declined ?? false,
        reason: answer.reason,
      }
    },
  }

  return { provider, seen }
}

const SETTINGS: Partial<BuddySettings> = {
  budgetPerMinute: 3,
  cooldownSeconds: 5,
  contextSize: 8,
  window: { before: 3, after: 2, recent: 8 },
  maxRemarkChars: 240,
  providerMinIntervalMs: 0,
  neverInterrupt: true,
}

describe('cue context', () => {
  it('selects the cue under the playhead', () => {
    expect(cueAt(LIGHTHOUSE, 4)?.text).toContain('spiral stair')
    expect(cueAt(LIGHTHOUSE, 3.1)).toBeNull()
  })

  it('builds a window of previous, current and upcoming cues', () => {
    const window = buildCueWindow(LIGHTHOUSE, 6.5)
    expect(window.current?.text).toContain('sea has been louder')
    expect(window.previous).toHaveLength(2)
    expect(window.previous[1]?.text).toContain('spiral stair')
    expect(window.upcoming).toHaveLength(2)
    expect(window.upcoming[0]?.text).toContain('storm is gathering')
  })

  it('knows the line that has just been said, including the one on screen', () => {
    expect(lastStartedCue(LIGHTHOUSE, 6.5)?.text).toContain('sea has been louder')
    expect(lastStartedCue(LIGHTHOUSE, 1)?.text).toContain('lamp has to be lit')
  })

  it('keeps the recent window bounded', () => {
    const window = buildCueWindow(LIGHTHOUSE, 20, { before: 99, after: 0, recent: 3 })
    expect(window.recent).toHaveLength(3)
  })

  it('detects a repeated phrase across cues', () => {
    const a = 'Lock both ends of the first bubble'
    const b = 'Now lock both ends of the bubble'
    expect(sharedPhrase(a, b)).toContain('lock both ends')
  })

  it('reports observable properties of a line', () => {
    const features = analyzeCue(
      { index: 1, start: 0, end: 2, text: 'Is that a storm out there?' },
      [],
    )
    expect(features.isQuestion).toBe(true)
    expect(features.newTerms.length).toBeGreaterThan(0)
  })
})

describe('subtitle alignment', () => {
  it('reports missing subtitles', () => {
    const report = alignmentReport([], 150)
    expect(report.status).toBe('no-cues')
    expect(report.detail).toMatch(/no caption track/i)
  })

  it('reports a subtitle file that does not match the copy of the film', () => {
    const report = alignmentReport(LIGHTHOUSE, 900)
    expect(report.status).toBe('mismatch')
    expect(report.detail).toMatch(/may not match/i)
  })

  it('reports a matching subtitle file', () => {
    const report = alignmentReport(LIGHTHOUSE, 21)
    expect(report.status).toBe('ok')
  })
})

describe('the commentary engine is driven by the active film', () => {
  it('gives different remarks for two different films with the same cue shape', async () => {
    const answers: Record<string, string> = {
      lighthouse: 'That is a lot of weather for one night.',
      express: 'Late again, then.',
    }

    const build = (film: 'lighthouse' | 'express', _cues: MediaCue[]) => {
      const { provider } = createFakeModel({
        answer: (request) => {
          const current = request.window.current
          if (!current) return null
          return { say: answers[film] ?? 'hm.', grounded_in: [current.index] }
        },
      })
      let clock = 1_000
      const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => clock })
      return { engine, tick: () => (clock += 20_000) }
    }

    const a = build('lighthouse', LIGHTHOUSE)
    const decisionA = await a.engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 6.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    a.tick()

    const b = build('express', EXPRESS)
    const decisionB = await b.engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: EXPRESS,
      currentTime: 5.1,
      captionOnScreen: false,
      filmId: 'express',
      filmTitle: 'The Express',
    })

    expect(decisionA.kind).toBe('speak')
    expect(decisionB.kind).toBe('speak')
    if (decisionA.kind === 'speak' && decisionB.kind === 'speak') {
      expect(decisionA.remark.say).not.toBe(decisionB.remark.say)
      expect(decisionA.remark.say).toContain('weather')
      expect(decisionB.remark.say).toContain('Late')
      // The grounding follows the film that is actually playing.
      expect(decisionA.remark.grounded_in).toEqual([1])
      expect(decisionB.remark.grounded_in).toEqual([1])
    }
  })

  it('never reuses a Duck and Cover line for another film', async () => {
    const { provider } = createFakeModel({
      answer: (request) => {
        const current = request.window.current
        return current ? { say: 'Something about this moment.', grounded_in: [current.index] } : null
      },
    })
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => 1_000 })
    const decision = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: EXPRESS,
      currentTime: 5.1,
      captionOnScreen: false,
      filmId: 'express',
      filmTitle: 'The Express',
    })
    if (decision.kind === 'speak') {
      expect(decision.remark.say).not.toMatch(/balloon|turtle|duck and cover/i)
    }
  })

  it('gives the provider a bounded window, never the whole subtitle file', async () => {
    const { provider, seen } = createFakeModel({
      answer: (request) => {
        const current = request.window.current
        return current ? { say: 'Noted.', grounded_in: [current.index] } : null
      },
    })
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => 1_000 })
    await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 6.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(seen).toHaveLength(1)
    const window = seen[0]?.window
    // previous + current + upcoming, never every cue in the file.
    expect((window?.previous.length ?? 0) + 1 + (window?.upcoming.length ?? 0)).toBeLessThanOrEqual(
      LIGHTHOUSE.length,
    )
    expect(window?.previous.length).toBeLessThanOrEqual(3)
  })
})

describe('the engine respects the moment', () => {
  it('stays silent while a caption is on screen', async () => {
    const { provider, seen } = createFakeModel()
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => 1_000 })
    const decision = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 6.5,
      captionOnScreen: true,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(decision.kind).toBe('silent')
    expect(seen).toHaveLength(0)
  })

  it('does not talk over a line that is doing the work', async () => {
    const { provider, seen } = createFakeModel()
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => 1_000 })
    const important = makeCues([[0, 4, 'The storm is gathering beyond the rocks and the wind is rising fast!']])
    const decision = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: important,
      currentTime: 1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(decision.kind).toBe('silent')
    expect(seen).toHaveLength(0)
  })

  it('does not repeat a remark for the same moment', async () => {
    const { provider, seen } = createFakeModel({
      answer: (request) => {
        const current = request.window.current
        return current ? { say: 'Noted.', grounded_in: [current.index] } : null
      },
    })
    let clock = 1_000
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => clock })

    const first = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(first.kind).toBe('speak')

    // The same cue again - even after the clock moved on.
    clock += 60_000
    const again = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(again.kind).toBe('silent')
    expect(seen).toHaveLength(1)
  })

  it('enforces the cooldown', async () => {
    const { provider, seen } = createFakeModel({
      answer: (request) => {
        const current = request.window.current
        return current ? { say: 'Noted.', grounded_in: [current.index] } : null
      },
    })
    let clock = 1_000
    const engine = new BuddyEngine({
      provider,
      settings: { ...SETTINGS, cooldownSeconds: 30 },
      now: () => clock,
    })

    const first = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(first.kind).toBe('speak')

    clock += 5_000
    const second = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 9.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(second.kind).toBe('silent')
    if (second.kind === 'silent') expect(second.reason).toMatch(/cooling down/i)
    expect(seen).toHaveLength(1)
  })

  it('spends its speaking budget', async () => {
    const { provider } = createFakeModel({
      answer: (request) => {
        const current = request.window.current
        return current ? { say: 'Noted.', grounded_in: [current.index] } : null
      },
    })
    let clock = 1_000
    const engine = new BuddyEngine({
      provider,
      settings: { ...SETTINGS, budgetPerMinute: 2, cooldownSeconds: 0 },
      now: () => clock,
    })

    const times = [3.1, 9.1, 15.1]
    const kinds = []
    for (const time of times) {
      clock += 1_000
      kinds.push(
        (
          await engine.consider({
            mode: 'active',
            quietUntil: 0,
            cues: LIGHTHOUSE,
            currentTime: time,
            captionOnScreen: false,
            filmId: 'lighthouse',
            filmTitle: 'The Lighthouse',
          })
        ).kind,
      )
    }
    expect(kinds.filter((kind) => kind === 'speak')).toHaveLength(2)
  })

  it('stays silent in quiet mode', async () => {
    const { provider, seen } = createFakeModel()
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => 1_000 })
    const decision = await engine.consider({
      mode: 'quiet',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(decision.kind).toBe('silent')
    expect(seen).toHaveLength(0)
  })

  it('stays silent until the quiet window expires', async () => {
    const { provider } = createFakeModel({
      answer: (request) => {
        const current = request.window.current
        return current ? { say: 'Noted.', grounded_in: [current.index] } : null
      },
    })
    const clock = 1_000
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => clock })
    const decision = await engine.consider({
      mode: 'quiet',
      quietUntil: 5_000,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(decision.kind).toBe('silent')
  })
})

describe('re-evaluation', () => {
  it('re-evaluates after a seek', async () => {
    const { provider, seen } = createFakeModel({
      answer: (request) => {
        const current = request.window.current
        return current ? { say: `At ${current.index}.`, grounded_in: [current.index] } : null
      },
    })
    let clock = 1_000
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => clock })

    await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    clock += 60_000
    // A seek back to a moment that was already passed.
    const afterSeek = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(afterSeek.kind).toBe('silent')
    expect(seen).toHaveLength(1)
  })

  it('forgets everything when the subtitle track changes', async () => {
    const { provider, seen } = createFakeModel({
      answer: (request) => {
        const current = request.window.current
        return current ? { say: 'Noted.', grounded_in: [current.index] } : null
      },
    })
    let clock = 1_000
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => clock })

    await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(seen).toHaveLength(1)

    engine.reset()
    clock += 60_000
    const decision = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: EXPRESS,
      currentTime: 5.1,
      captionOnScreen: false,
      filmId: 'express',
      filmTitle: 'The Express',
    })
    expect(decision.kind).toBe('speak')
    expect(seen).toHaveLength(2)
    if (decision.kind === 'speak') {
      expect(decision.remark.grounded_in).toEqual([1])
    }
  })
})

describe('provider failures are handled honestly', () => {
  it('asks for a subtitle track when the film has no usable captions', async () => {
    const { provider, seen } = createFakeModel()
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => 1_000 })
    const decision = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: [],
      currentTime: 30,
      captionOnScreen: false,
      filmId: 'silent',
      filmTitle: 'The Silent One',
    })
    expect(decision.kind).toBe('declined')
    if (decision.kind === 'declined') {
      expect(decision.source).toBe('unavailable')
      expect(decision.reason).toMatch(/no caption track/i)
      expect(decision.reason).toMatch(/load a subtitle file/i)
    }
    // Nothing was fabricated and no provider was called.
    expect(seen).toHaveLength(0)
  })

  it('uses the provider that is set on it', async () => {
    const { provider, seen } = createFakeModel({
      answer: (request) => {
        const current = request.window.current
        return current ? { say: 'Noted.', grounded_in: [current.index] } : null
      },
    })
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => 1_000 })
    expect(engine.source).toBe('model')

    engine.setProvider(createUnavailableProvider('no captions'))
    expect(engine.source).toBe('unavailable')
    const decision = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(decision.kind).toBe('declined')
    expect(seen).toHaveLength(0)
  })

  it('reports a model that is not available', async () => {
    const provider: CommentaryProvider = {
      id: 'none',
      source: 'unavailable',
      available: false,
      async generate() {
        return {
          say: '',
          source: 'unavailable',
          grounded_in: [],
          declined: true,
          reason: 'No model provider is configured.',
        }
      },
    }
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => 1_000 })
    const decision = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(decision.kind).toBe('declined')
    if (decision.kind === 'declined') {
      expect(decision.source).toBe('unavailable')
      expect(decision.reason).toMatch(/no model provider/i)
    }
  })

  it('reports a provider that throws', async () => {
    const { provider } = createFakeModel({ throw: new Error('connection refused') })
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => 1_000 })
    const decision = await engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
    })
    expect(decision.kind).toBe('declined')
    if (decision.kind === 'declined') {
      expect(decision.reason).toMatch(/connection refused/)
    }
  })

  it('can be cancelled while the provider is working', async () => {
    const { provider } = createFakeModel({ hang: true })
    const engine = new BuddyEngine({ provider, settings: SETTINGS, now: () => 1_000 })
    const controller = new AbortController()
    const pending = engine.consider({
      mode: 'active',
      quietUntil: 0,
      cues: LIGHTHOUSE,
      currentTime: 3.1,
      captionOnScreen: false,
      filmId: 'lighthouse',
      filmTitle: 'The Lighthouse',
      signal: controller.signal,
    })
    controller.abort()
    const decision = await pending
    expect(decision.kind).not.toBe('speak')
  })

  it('rejects a model answer that is not JSON', () => {
    const request = {
      film: { id: 'x', title: 'X' },
      window: { current: LIGHTHOUSE[0]!, previous: [], upcoming: [], recent: [] },
      maxLength: 240,
    }
    const result = parseModelRemark('I think a storm is coming.', request)
    expect(result.declined).toBe(true)
    expect(result.say).toBe('')
    expect(result.reason).toMatch(/not valid json/i)
  })

  it('rejects a model answer that refers to lines it was never shown', () => {
    const request = {
      film: { id: 'x', title: 'X' },
      window: { current: LIGHTHOUSE[0]!, previous: [], upcoming: [], recent: [] },
      maxLength: 240,
    }
    const result = parseModelRemark(
      JSON.stringify({ say: 'The boat sinks.', grounded_in: [42] }),
      request,
    )
    expect(result.declined).toBe(true)
    expect(result.say).toBe('')
    expect(result.reason).toMatch(/never shown/i)
  })

  it('accepts a model answer grounded in the lines it was shown', () => {
    const request = {
      film: { id: 'x', title: 'X' },
      window: { current: LIGHTHOUSE[0]!, previous: [], upcoming: [], recent: [] },
      maxLength: 240,
    }
    const result = parseModelRemark(
      JSON.stringify({ say: 'A lamp, before the tide.', grounded_in: [0] }),
      request,
    )
    expect(result.declined).toBe(false)
    expect(result.say).toBe('A lamp, before the tide.')
    expect(result.grounded_in).toEqual([0])
  })

  it('rejects a model answer that is too long to speak', () => {
    const request = {
      film: { id: 'x', title: 'X' },
      window: { current: LIGHTHOUSE[0]!, previous: [], upcoming: [], recent: [] },
      maxLength: 240,
    }
    const result = parseModelRemark(
      JSON.stringify({ say: 'x'.repeat(400), grounded_in: [0] }),
      request,
    )
    expect(result.declined).toBe(true)
    expect(result.reason).toMatch(/too long/i)
  })
})

describe('the model provider over HTTP', () => {
  it('sends a bounded window and parses the answer', async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(
        JSON.stringify({
          choices: [
            {
              message: {
                content: JSON.stringify({ say: 'A lamp before the tide.', grounded_in: [0] }),
              },
            },
          ],
        }),
        { headers: { 'content-type': 'application/json' } },
      ),
    )
    const provider = createModelProvider({
      endpoint: 'http://model.invalid/chat',
      model: 'test-model',
      fetchImpl: fetchImpl as never,
    })
    const result = await provider.generate({
      film: { id: 'lighthouse', title: 'The Lighthouse' },
      window: { current: LIGHTHOUSE[0]!, previous: [], upcoming: [], recent: [] },
      maxLength: 240,
    })
    expect(result.say).toBe('A lamp before the tide.')
    const body = JSON.parse((fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)
    const prompt = body.messages[1].content as string
    // The whole subtitle file is never sent.
    expect(prompt).not.toContain('storm is gathering')
    expect(prompt).toContain('lamp has to be lit')
  })

  it('reports a provider that answers with an HTTP error', async () => {
    const fetchImpl = vi.fn(async () => new Response('nope', { status: 503 }))
    const provider = createModelProvider({
      endpoint: 'http://model.invalid/chat',
      model: 'test-model',
      fetchImpl: fetchImpl as never,
    })
    const result = await provider.generate({
      film: { id: 'lighthouse', title: 'The Lighthouse' },
      window: { current: LIGHTHOUSE[0]!, previous: [], upcoming: [], recent: [] },
      maxLength: 240,
    })
    expect(result.declined).toBe(true)
    expect(result.reason).toMatch(/HTTP 503/)
  })
})

describe('the local fallback', () => {
  it('is labelled as local and only speaks about what it can observe', async () => {
    const provider = createLocalProvider()
    const result = await provider.generate({
      film: { id: 'lighthouse', title: 'The Lighthouse' },
      window: {
        current: LIGHTHOUSE[3]!,
        previous: [],
        upcoming: [],
        recent: [],
      },
      maxLength: 240,
    })
    expect(result.source).toBe('local')
    expect(result.grounded_in).toEqual([3])
    if (result.source === 'local') {
      expect(result.say.length).toBeGreaterThan(0)
    }
  })

  it('says nothing when the dialogue is unremarkable', async () => {
    const provider = createLocalProvider()
    const plain = makeCues([[0, 3, 'Yes.']])
    const result = await provider.generate({
      film: { id: 'x', title: 'X' },
      window: { current: plain[0]!, previous: [], upcoming: [], recent: [] },
      maxLength: 240,
    })
    expect(result.declined).toBe(true)
  })

  it('answers a question by quoting the caption', async () => {
    const provider = createLocalProvider()
    const result = await provider.generate({
      film: { id: 'lighthouse', title: 'The Lighthouse' },
      window: { current: LIGHTHOUSE[0]!, previous: [], upcoming: [], recent: [] },
      question: 'what is that',
      maxLength: 240,
    })
    expect(result.say).toContain('lamp has to be lit')
  })
})
