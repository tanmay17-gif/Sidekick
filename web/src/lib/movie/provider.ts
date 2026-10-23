import { analyzeCue, type CueWindow } from './context'

/**
 * Where a remark came from.
 *
 * This is surfaced in the interface: a remark that was written by a local
 * heuristic is never presented as if a model wrote it.
 */
export type CommentarySource = 'model' | 'local' | 'unavailable'

export interface CommentaryRequest {
  /** The film that is playing. */
  film: { id: string; title: string }
  /** The cue window around the playhead. */
  window: CueWindow
  /** The question the user asked, when the request came from one. */
  question?: string
  /** How long the remark may be. */
  maxLength: number
}

export interface CommentaryResult {
  /** What Sidekick says. Empty when it declined. */
  say: string
  source: CommentarySource
  /** The indexes of the cues the statement is grounded in. */
  grounded_in: number[]
  /** True when the provider chose not to comment. */
  declined: boolean
  /** Why it declined, or why it failed. */
  reason?: string
}

export interface CommentaryProvider {
  readonly id: string
  readonly source: CommentarySource
  /** True when this provider can produce commentary at all. */
  readonly available: boolean
  generate(request: CommentaryRequest, signal?: AbortSignal): Promise<CommentaryResult>
}

/* ------------------------------------------------------------------ *
 * The model provider.
 *
 * It talks to any OpenAI-compatible chat completions endpoint that the team
 * configures. It is given a *window* of cues - never the whole subtitle file -
 * and every remark it returns must be grounded in the cues it was shown.
 * ------------------------------------------------------------------ */

export interface ModelProviderConfig {
  /** An OpenAI-compatible chat completions URL. */
  endpoint: string
  model: string
  apiKey?: string
  /** Abort a request that has not answered within this many milliseconds. */
  timeoutMs?: number
  fetchImpl?: typeof fetch
}

const MAX_REMARK_CHARS = 240

export function createModelProvider(config: ModelProviderConfig): CommentaryProvider {
  const fetchImpl = config.fetchImpl ?? globalThis.fetch.bind(globalThis)

  return {
    id: `model:${config.model}`,
    source: 'model',
    available: Boolean(config.endpoint),

    async generate(request, signal): Promise<CommentaryResult> {
      if (!config.endpoint) {
        return {
          say: '',
          source: 'unavailable',
          grounded_in: [],
          declined: true,
          reason: 'No model provider is configured.',
        }
      }

      const controller = new AbortController()
      const timer = setTimeout(
        () => controller.abort('timeout'),
        config.timeoutMs ?? 8000,
      )
      const onAbort = () => controller.abort('interrupted')
      signal?.addEventListener('abort', onAbort)

      try {
        const response = await fetchImpl(config.endpoint, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            ...(config.apiKey ? { authorization: `Bearer ${config.apiKey}` } : {}),
          },
          body: JSON.stringify({
            model: config.model,
            temperature: 0.3,
            max_tokens: 120,
            messages: [
              { role: 'system', content: systemInstruction },
              { role: 'user', content: buildPrompt(request) },
            ],
          }),
          signal: controller.signal,
        })

        if (!response.ok) {
          return {
            say: '',
            source: 'model',
            grounded_in: [],
            declined: true,
            reason: `The model provider answered with HTTP ${response.status}.`,
          }
        }

        const payload = (await response.json()) as {
          choices?: Array<{ message?: { content?: string } }>
        }
        const content = payload.choices?.[0]?.message?.content
        if (typeof content !== 'string' || content.trim().length === 0) {
          return {
            say: '',
            source: 'model',
            grounded_in: [],
            declined: true,
            reason: 'The model provider returned an empty answer.',
          }
        }

        return parseModelRemark(content, request)
      } catch (cause) {
        const aborted = signal?.aborted
        return {
          say: '',
          source: 'model',
          grounded_in: [],
          declined: true,
          reason: aborted
            ? 'The request was interrupted.'
            : `The model provider could not be reached: ${
                cause instanceof Error ? cause.message : 'unknown error'
              }`,
        }
      } finally {
        clearTimeout(timer)
        signal?.removeEventListener('abort', onAbort)
      }
    },
  }
}

const systemInstruction = [
  'You are Sidekick, an enthusiastic, witty, and perceptive movie-watching buddy sitting on the couch next to the viewer.',
  'Your goal is to make watching movies fun, conversational, and engaging like a real friend.',
  'Rules:',
  '- Speak naturally, warmly, and casually. React to what just happened with personality, quick humor, or genuine interest.',
  '- Do NOT just summarize or recite the caption words. Give a real companion reaction.',
  '- Say nothing when the movie is in an intense or self-explanatory stretch. Silence is great too.',
  '- Reply with a single JSON object: {"say": string, "grounded_in": number[]}.',
  '"say" is at most one lively, conversational sentence, or an empty string if you have nothing worth saying.',
  '"grounded_in" lists the indexes of the subtitle lines your sentence relates to.',
].join('\n')

function buildPrompt(request: CommentaryRequest): string {
  const lines: string[] = []
  const window = request.window
  for (const cue of [...window.previous, ...(window.current ? [window.current] : [])]) {
    lines.push(`[${cue.index}] ${cue.text}`)
  }
  const upcoming = window.upcoming.map((cue) => `[${cue.index}] ${cue.text}`).join('\n')
  const body = [
    `Film: ${request.film.title}`,
    '',
    'Subtitle lines so far:',
    ...lines,
  ]
  if (upcoming) {
    body.push('', 'The next lines (do not comment as if they already happened):', upcoming)
  }
  if (request.question) {
    body.push('', `The viewer asked: "${request.question}"`)
  }
  body.push('', `Maximum length: ${request.maxLength} characters.`)
  return body.join('\n')
}

/**
 * Parse and validate what the model returned.
 *
 * A remark that claims to be based on a line it was not shown is rejected:
 * that is exactly the failure mode that turns a companion into a fabricator.
 */
export function parseModelRemark(
  content: string,
  request: CommentaryRequest,
): CommentaryResult {
  let payload: unknown
  try {
    payload = JSON.parse(stripFence(content))
  } catch {
    return {
      say: '',
      source: 'model',
      grounded_in: [],
      declined: true,
      reason: 'The model answer was not valid JSON, so it was not used.',
    }
  }

  if (!payload || typeof payload !== 'object') {
    return {
      say: '',
      source: 'model',
      grounded_in: [],
      declined: true,
      reason: 'The model answer was not an object, so it was not used.',
    }
  }

  const record = payload as { say?: unknown; grounded_in?: unknown }
  const say = typeof record.say === 'string' ? record.say.trim() : ''
  if (say.length === 0) {
    return { say: '', source: 'model', grounded_in: [], declined: true }
  }
  if (say.length > MAX_REMARK_CHARS) {
    return {
      say: '',
      source: 'model',
      grounded_in: [],
      declined: true,
      reason: 'The model answer was too long to speak, so it was not used.',
    }
  }

  const available = new Set<number>([
    ...request.window.previous.map((cue) => cue.index),
    ...(request.window.current ? [request.window.current.index] : []),
  ])
  const claimed = Array.isArray(record.grounded_in)
    ? record.grounded_in.filter((value): value is number => typeof value === 'number')
    : []
  const unsupported = claimed.filter((index) => !available.has(index))
  if (unsupported.length > 0) {
    return {
      say: '',
      source: 'model',
      grounded_in: [],
      declined: true,
      reason:
        'The model referred to subtitle lines it was never shown, so the answer was rejected.',
    }
  }

  return { say, source: 'model', grounded_in: claimed, declined: false }
}

function stripFence(content: string): string {
  const trimmed = content.trim()
  if (!trimmed.startsWith('```')) return trimmed
  return trimmed.replace(/^```[a-zA-Z]*\n?/, '').replace(/```$/, '').trim()
}

/* ------------------------------------------------------------------ *
 * The local fallback.
 *
 * It is a deterministic observation of the dialogue, not a script and not a
 * summary. It only speaks when the dialogue does something observable, and
 * it says what it observed.
 * ------------------------------------------------------------------ */

export function createLocalProvider(): CommentaryProvider {
  return {
    id: 'local-heuristic',
    source: 'local',
    available: true,

    async generate(request): Promise<CommentaryResult> {
      const { current, previous, recent } = request.window
      if (!current) {
        return {
          say: '',
          source: 'local',
          grounded_in: [],
          declined: true,
          reason: 'No caption line is on screen.',
        }
      }

      if (request.question) {
        const quoted = current.text.trim()
        const answer = quoted
          ? `The caption line here reads: "${quoted}".`
          : 'There is no caption line at this moment.'
        return {
          say: answer,
          source: 'local',
          grounded_in: [current.index],
          declined: false,
        }
      }

      const features = analyzeCue(current, recent)

      if (features.isSound) {
        return {
          say: 'That was a sound rather than speech.',
          source: 'local',
          grounded_in: [current.index],
          declined: false,
        }
      }

      if (features.repeats.length > 0) {
        return {
          say: `They keep coming back to "${features.repeats[0]}".`,
          source: 'local',
          grounded_in: [current.index],
          declined: false,
        }
      }

      if (features.isQuestion && previous.length === 0) {
        return {
          say: 'That is a question - and the answer comes next.',
          source: 'local',
          grounded_in: [current.index],
          declined: false,
        }
      }

      if (features.newTerms.length >= 2 && !features.isShort) {
        return {
          say: `New words just came up: ${features.newTerms.join(', ')}.`,
          source: 'local',
          grounded_in: [current.index],
          declined: false,
        }
      }

      // Nothing observable enough to be worth saying.
      return { say: '', source: 'local', grounded_in: [], declined: true }
    },
  }
}


/* ------------------------------------------------------------------ *
 * The provider used when the film has no usable subtitles.
 * ------------------------------------------------------------------ */

export function createUnavailableProvider(reason: string): CommentaryProvider {
  return {
    id: 'unavailable',
    source: 'unavailable',
    available: false,
    async generate(): Promise<CommentaryResult> {
      return { say: '', source: 'unavailable', grounded_in: [], declined: true, reason }
    },
  }
}
