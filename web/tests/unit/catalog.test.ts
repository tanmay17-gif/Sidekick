import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { DEFAULT_MEDIA, loadMediaCatalog } from '@/lib/media/catalog'

const SRT = readFileSync(
  resolve(process.cwd(), 'public/media/tears-of-steel/TOS-en.srt'),
  'utf8',
)

describe('media catalog', () => {
  it('falls back to the bundled film when the backend has no catalog', async () => {
    const fetchImpl = vi.fn(async (url: string) => {
      if (url.includes('/api/v1/media/catalog')) {
        return new Response('not found', { status: 404 })
      }
      return new Response(SRT, { headers: { 'content-type': 'text/plain' } })
    })

    const result = await loadMediaCatalog({
      catalogUrl: '/api/v1/media/catalog',
      fetchImpl: fetchImpl as never,
    })

    expect(result.source).toBe('bundled')
    expect(result.asset.id).toBe(DEFAULT_MEDIA.id)
    expect(result.asset.cues.length).toBeGreaterThan(50)
    // A missing optional endpoint is a supported configuration, not a warning.
    expect(result.warnings).toHaveLength(0)
  })

  it('uses a backend catalog entry when its subtitles actually load', async () => {
    const fetchImpl = vi.fn(async (url: string) => {
      if (url.includes('/api/v1/media/catalog')) {
        return new Response(
          JSON.stringify({
            assets: [
              {
                id: 'backend-film',
                title: 'Backend Film',
                src: 'https://example.invalid/backend.mp4',
                subtitle_src: '/media/backend.srt',
                companion_rules: [{ pattern: '\\bhello\\b', title: 'Greeting', reason: 'matched' }],
              },
            ],
          }),
          { headers: { 'content-type': 'application/json' } },
        )
      }
      return new Response(SRT, { headers: { 'content-type': 'text/plain' } })
    })

    const result = await loadMediaCatalog({
      catalogUrl: '/api/v1/media/catalog',
      fetchImpl: fetchImpl as never,
    })

    expect(result.source).toBe('backend')
    expect(result.asset.title).toBe('Backend Film')
    expect(result.asset.cues.length).toBeGreaterThan(50)
  })

  it('keeps the bundled film when the backend entry has no readable subtitles', async () => {
    const fetchImpl = vi.fn(async (url: string) => {
      if (url.includes('/api/v1/media/catalog')) {
        return new Response(
          JSON.stringify({
            assets: [
              {
                id: 'broken',
                title: 'Broken',
                src: 'https://example.invalid/broken.mp4',
                subtitle_src: '/media/broken.srt',
              },
            ],
          }),
          { headers: { 'content-type': 'application/json' } },
        )
      }
      if (url.includes('broken.srt')) return new Response('nope', { status: 404 })
      return new Response(SRT, { headers: { 'content-type': 'text/plain' } })
    })

    const result = await loadMediaCatalog({
      catalogUrl: '/api/v1/media/catalog',
      fetchImpl: fetchImpl as never,
    })

    expect(result.source).toBe('bundled')
    expect(result.warnings.join(' ')).toMatch(/subtitle track/i)
  })

  it('reports a subtitle failure instead of pretending to understand the film', async () => {
    const fetchImpl = vi.fn(async () => new Response('nope', { status: 404 }))
    const result = await loadMediaCatalog({ fetchImpl: fetchImpl as never })
    expect(result.asset.cues).toHaveLength(0)
    expect(result.warnings.join(' ')).toMatch(/subtitle track could not be loaded/i)
  })
})
