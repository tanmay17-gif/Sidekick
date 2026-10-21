import type { MediaAsset } from '@/lib/api/types'
import { parseSubtitles } from './subtitles'

/**
 * The movie companion ships with one openly licensed film whose official
 * English subtitle track is included in the repository, so cue timings are
 * real and verifiable rather than invented.
 *
 * Tears of Steel (2012) - Blender Foundation / MPEG, CC BY 3.0.
 * Video: Internet Archive derivative `tears_of_steel_720p.mp4` (faststart H.264).
 * Subtitles: official `TOS-en.srt` from download.blender.org.
 */
export const DEFAULT_MEDIA: MediaAsset = {
  id: 'tears-of-steel',
  title: 'Tears of Steel',
  credit: 'Tears of Steel - Blender Foundation / MPEG (CC BY 3.0)',
  license: 'CC BY 3.0',
  src: 'https://archive.org/download/Tears-of-Steel/tears_of_steel_720p.mp4',
  mime_type: 'video/mp4',
  subtitle_src: `${import.meta.env.BASE_URL}media/tears-of-steel/TOS-en.srt`,
  subtitle_label: 'official English subtitles',
  cues: [],
  companion_rules: [
    {
      pattern: '\\brobot\\b',
      title: 'Robotics mentioned',
      reason:
        'A character talks about a robotic hand. Fired on the real timestamp of that subtitle line.',
    },
    {
      pattern: '\\bspace\\b',
      title: 'Space ambition',
      reason:
        'Dialogue about going to space. Fired on the real timestamp of that subtitle line.',
    },
    {
      pattern: '\\bmemory\\b|\\boverwrite\\b',
      title: 'Memory theme',
      reason:
        'The film returns to memory and identity. Fired on the real timestamp of that subtitle line.',
    },
    {
      pattern: '\\blesson\\b',
      title: 'Closing reflection',
      reason:
        'A reflective closing line. Fired on the real timestamp of that subtitle line.',
    },
  ],
}

export interface LoadCatalogResult {
  asset: MediaAsset
  /** Non-fatal problems (e.g. subtitle file could not be fetched). */
  warnings: string[]
}

/**
 * Load the shipped media descriptor and its subtitle cues.
 * A subtitle failure is reported, never silently ignored - without cues the
 * companion cannot claim to understand anything.
 */
export async function loadDefaultMedia(
  fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
): Promise<LoadCatalogResult> {
  const warnings: string[] = []
  let cues = DEFAULT_MEDIA.cues

  try {
    const response = await fetchImpl(DEFAULT_MEDIA.subtitle_src)
    if (!response.ok) {
      warnings.push(
        `Subtitle track could not be loaded (HTTP ${response.status}). Companion events are disabled.`,
      )
    } else {
      const parsed = parseSubtitles(await response.text())
      if (parsed.length === 0) {
        warnings.push('Subtitle track contained no readable cues. Companion events are disabled.')
      } else {
        cues = parsed
      }
    }
  } catch (cause) {
    warnings.push(
      `Subtitle track could not be read: ${cause instanceof Error ? cause.message : 'unknown error'}.`,
    )
  }

  return { asset: { ...DEFAULT_MEDIA, cues }, warnings }
}
