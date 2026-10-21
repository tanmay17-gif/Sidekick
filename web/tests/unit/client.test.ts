import { describe, expect, it, vi } from 'vitest'
import { SidekickClient, parseSseFrame } from '@/lib/api/client'
import { SidekickApiError } from '@/lib/api/errors'
import { SESSION_HEADER, type SidekickRequest, type SidekickResponse } from '@/lib/api/types'

const request: SidekickRequest = {
  request_id: 'req-1',
  session_id: 'sess-1',
  utterance: 'play a song on spotify',
  input_source: 'text',
  utterance_finalized: true,
}

function makeResponse(overrides: Partial<SidekickResponse> = {}): SidekickResponse {
  return {
    request_id: 'req-1',
    session_id: 'sess-1',
    intent: { normalized: 'play a song', confidence: 0.9, ambiguous: false, entities: [] },
    action_plan: [
      {
        action_id: 'a-1',
        tool: 'music.play',
        arguments: { provider: 'Spotify' },
        approval_required: false,
        state: 'succeeded',
        superseded_by: null,
        timestamps: { created: '2026-01-01T00:00:00Z', updated: '2026-01-01T00:00:01Z' },
      },
    ],
    risk_level: 'low',
    decision_model: { provider: 'test', model: 'test-model', fallback_used: false },
    status: 'succeeded',
    clarification: null,
    events: [],
    ...overrides,
  }
}

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
    ...init,
  })
}

describe('SidekickClient', () => {
  it('sends the session id in the header and the body', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(makeResponse()))
    const client = new SidekickClient({ sessionId: 'sess-1', fetchImpl: fetchImpl as never })

    await client.interpret(request)

    expect(fetchImpl).toHaveBeenCalledTimes(1)
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('/api/v1/requests')
    const headers = init.headers as Record<string, string>
    expect(headers[SESSION_HEADER]).toBe('sess-1')
    const body = JSON.parse(init.body as string)
    expect(body.session_id).toBe('sess-1')
    expect(body.request_id).toBe('req-1')
    expect(body.utterance_finalized).toBe(true)
  })

  it('returns the parsed contract response', async () => {
    const client = new SidekickClient({
      sessionId: 'sess-1',
      fetchImpl: (async () => jsonResponse(makeResponse())) as never,
    })
    const { response } = await client.interpret(request)
    expect(response.request_id).toBe('req-1')
    expect(response.action_plan[0]?.tool).toBe('music.play')
  })

  it('streams progress events and a final response over SSE', async () => {
    const body = [
      'data: {"seq":1,"kind":"progress","message":"Job queued"}',
      '',
      'data: {"seq":2,"kind":"progress","message":"Working"}',
      '',
      `data: ${JSON.stringify(makeResponse({ status: 'succeeded' }))}`,
      '',
    ].join('\n')

    const fetchImpl = vi.fn(async () =>
      new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
    )
    const client = new SidekickClient({ sessionId: 'sess-1', fetchImpl: fetchImpl as never })

    const seen: string[] = []
    const { response, events } = await client.interpret(request, {
      onEvent: (event) => seen.push(event.message ?? ''),
    })

    expect(seen).toEqual(['Job queued', 'Working'])
    expect(events).toHaveLength(2)
    expect(response.status).toBe('succeeded')
  })

  it('reports a network failure instead of pretending it succeeded', async () => {
    const client = new SidekickClient({
      sessionId: 'sess-1',
      fetchImpl: (async () => {
        throw new TypeError('Failed to fetch')
      }) as never,
    })

    await expect(client.interpret(request)).rejects.toBeInstanceOf(SidekickApiError)
    await expect(client.interpret(request)).rejects.toMatchObject({
      code: 'network_unreachable',
      retryable: true,
    })
  })

  it('reports an HTTP error using the contract error body', async () => {
    const client = new SidekickClient({
      sessionId: 'sess-1',
      fetchImpl: (async () =>
        new Response(
          JSON.stringify({
            error: { code: 'session_conflict', message: 'Session is busy', retryable: false },
          }),
          { status: 409, headers: { 'content-type': 'application/json' } },
        )) as never,
    })

    await expect(client.interpret(request)).rejects.toMatchObject({
      code: 'session_conflict',
      message: 'Session is busy',
      status: 409,
    })
  })

  it('rejects a body that does not match the contract', async () => {
    const client = new SidekickClient({
      sessionId: 'sess-1',
      fetchImpl: (async () => jsonResponse({ nope: true })) as never,
    })
    await expect(client.interpret(request)).rejects.toMatchObject({ code: 'contract_violation' })
  })

  it('rejects a capabilities payload that is not a list', async () => {
    const client = new SidekickClient({
      sessionId: 'sess-1',
      fetchImpl: (async () => jsonResponse({ capabilities: 'nope' })) as never,
    })
    await expect(client.capabilities()).rejects.toMatchObject({ code: 'contract_violation' })
  })

  it('reads the capabilities inventory', async () => {
    const client = new SidekickClient({
      sessionId: 'sess-1',
      fetchImpl: (async () =>
        jsonResponse({
          contract_version: 'v1',
          mode: 'stub',
          capabilities: [{ id: 'music.play', state: 'unconfigured' }],
        })) as never,
    })
    const capabilities = await client.capabilities()
    expect(capabilities.mode).toBe('stub')
    expect(capabilities.capabilities[0]?.state).toBe('unconfigured')
  })
})

describe('parseSseFrame', () => {
  it('parses a JSON data frame', () => {
    expect(parseSseFrame('data: {"seq":1,"message":"hi"}')).toMatchObject({ seq: 1, message: 'hi' })
  })

  it('ignores comment and DONE frames', () => {
    expect(parseSseFrame(': keep-alive')).toBeNull()
    expect(parseSseFrame('data: [DONE]')).toBeNull()
  })

  it('surfaces a non-JSON frame as a message instead of dropping it', () => {
    expect(parseSseFrame('data: plain text')).toEqual({ message: 'plain text' })
  })
})
