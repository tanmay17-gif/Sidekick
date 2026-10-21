import type { CompanionRule, MediaAsset, MediaCue } from '@/lib/api/types'
import { parseSubtitles } from './subtitles'

/**
 * The media the movie companion can play.
 *
 * Both films are openly licensed and both ship their caption track with the
 * app, so the companion has real, verifiable cue timings.
 *
 * `letter-v`
 *   "Letter V" - Internet Archive item `LetterV`.
 *   The copy is released under CC0 1.0 (a public domain dedication) by its
 *   creator; the item metadata records the creator as "Langerman
 *   www.fewdoit.com" and describes it as a "balloon twisting de vA-deo
 *   instruction ... public domain dedication".
 *   Runtime 2:29, with a hand-authored English caption track that covers the
 *   whole film. Bundled in the app (15.6 MB) so the demo never depends on a
 *   third-party host being up.
 *
 * `tears-of-steel`
 *   "Tears of Steel" (2012), Blender Foundation / MPEG, CC BY 3.0.
 *   Streamed from the Internet Archive derivative (faststart H.264, HTTP
 *   range support). The official English subtitle file is bundled.
 *
 * See docs/MOVIE_SOURCES.md for the full rights evidence and the limitations.
 */

export const DEFAULT_MEDIA: MediaAsset = {
  id: 'letter-v',
  title: 'Letter V',
  credit: 'Letter V - public domain dedication (CC0 1.0), Internet Archive item LetterV',
  license: 'CC0 1.0',
  src: `${import.meta.env.BASE_URL}media/letter-v/letter-v.mp4`,
  mime_type: 'video/mp4',
  // The WebM (VP9 + Opus) is the same film, transcoded for browsers without
  // H.264 - notably the Chromium build that ships with Playwright. The browser
  // picks whichever it can decode.
  sources: [
    {
      src: `${import.meta.env.BASE_URL}media/letter-v/letter-v.mp4`,
      mime_type: 'video/mp4',
      label: 'MP4 (H.264)',
    },
    {
      src: `${import.meta.env.BASE_URL}media/letter-v/letter-v.webm`,
      mime_type: 'video/webm',
      label: 'WebM (VP9)',
    },
  ],
  subtitle_src: `${import.meta.env.BASE_URL}media/letter-v/letter-v.srt`,
  subtitle_label: 'hand-authored English captions',
  cues: [],
  companion_rules: [],
  bundled: true,
}

export const ALTERNATE_MEDIA: MediaAsset = {
  id: 'tears-of-steel',
  title: 'Tears of Steel',
  credit: 'Tears of Steel - Blender Foundation / MPEG (CC BY 3.0)',
  license: 'CC BY 3.0',
  src: 'https://archive.org/download/Tears-of-Steel/tears_of_steel_720p.mp4',
  mime_type: 'video/mp4',
  subtitle_src: `${import.meta.env.BASE_URL}media/tears-of-steel/TOS-en.srt`,
  subtitle_label: 'official English subtitles',
  cues: [],
  companion_rules: [],
  bundled: false,
}

export const MEDIA_LIBRARY: MediaAsset[] = [DEFAULT_MEDIA, ALTERNATE_MEDIA]

export interface LoadCatalogResult {
  asset: MediaAsset
  /** Non-fatal problems (e.g. subtitle file could not be fetched). */
  warnings: string[]
  /** Where the catalog came from. */
  source: 'backend' | 'bundled'
}

export interface BackendCatalogEntry {
  id: string
  title: string
  credit?: string
  license?: string
  src: string
  mime_type?: string
  subtitle_src: string
  subtitle_label?: string
  companion_rules?: CompanionRule[]
}

interface BackendCatalogResponse {
  assets?: BackendCatalogEntry[]
}

/**
 * Load the catalog, preferring a backend-provided one and falling back to the
 * films shipped in the repository.
 *
 * The backend entry is only used when its media and subtitle actually load -
 * a half-working catalog entry must not replace a working local one.
 */
export async function loadMediaCatalog(
  options: {
    catalogUrl?: string | null
    fetchImpl?: typeof fetch
  } = {},
): Promise<LoadCatalogResult> {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis)
  const warnings: string[] = []

  if (options.catalogUrl) {
    try {
      const response = await fetchImpl(options.catalogUrl)
      if (response.ok) {
        const payload = (await response.json()) as BackendCatalogResponse
        const entry = payload.assets?.[0]
        if (entry) {
          const result = await hydrate({ ...DEFAULT_MEDIA, ...entry, cues: [] }, fetchImpl, warnings)
          if (result.cues.length > 0) {
            return { asset: result.asset, warnings, source: 'backend' }
          }
          warnings.push(
            'The backend catalog entry had no readable subtitle track, so a bundled film was used instead.',
          )
        }
      } else if (response.status !== 404) {
        // 404 simply means the backend does not offer a catalog - that is a
        // supported configuration, not a problem worth shouting about.
        warnings.push(
          `Backend media catalog returned HTTP ${response.status}. Using a bundled film.`,
        )
      }
    } catch (cause) {
      warnings.push(
        `Backend media catalog unavailable (${cause instanceof Error ? cause.message : 'unknown error'}); using a bundled film.`,
      )
    }
  }

  const result = await hydrate(DEFAULT_MEDIA, fetchImpl, warnings)
  return { asset: result.asset, warnings, source: 'bundled' }
}

/**
 * Load every bundled film with its caption track parsed.
 * A subtitle failure is reported, never silently ignored.
 */
export async function loadMediaLibrary(
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<{ assets: MediaAsset[]; warnings: string[] }> {
  const warnings: string[] = []
  const assets: MediaAsset[] = []
  for (const asset of MEDIA_LIBRARY) {
    const result = await hydrate(asset, fetchImpl, warnings)
    assets.push(result.asset)
  }
  return { assets, warnings }
}

/** Load the subtitle track for one asset and parse it into real cues. */
async function hydrate(
  asset: MediaAsset,
  fetchImpl: typeof fetch,
  warnings: string[],
): Promise<{ asset: MediaAsset; cues: MediaCue[] }> {
  let cues = asset.cues

  try {
    const response = await fetchImpl(asset.subtitle_src)
    if (!response.ok) {
      warnings.push(
        `Captions for "${asset.title}" could not be loaded (HTTP ${response.status}). Companion events are disabled for it.`,
      )
    } else {
      const parsed = parseSubtitles(await response.text())
      if (parsed.length === 0) {
        warnings.push(
          `The caption track for "${asset.title}" contained no readable cues. Companion events are disabled for it.`,
        )
      } else {
        cues = parsed
      }
    }
  } catch (cause) {
    warnings.push(
      `Captions for "${asset.title}" could not be read: ${cause instanceof Error ? cause.message : 'unknown error'}.`,
    )
  }

  return { asset: { ...asset, cues }, cues }
}
