import type { MediaCue } from '@/lib/api/types'

/**
 * Subtitle parsing for SubRip (`.srt`) and WebVTT (`.vtt`).
 *
 * The parser is deliberately strict about timestamps - a cue whose timing
 * cannot be read is dropped rather than guessed, because the movie companion
 * uses these timings to drive real playback events.
 */

/**
 * `HH:MM:SS.mmm` or `MM:SS.mmm`. The hours group is optional, so both the
 * SubRip and the WebVTT short forms are accepted.
 */
const TIMESTAMP = /^(\d{1,4}):(\d{1,2}):(\d{2})[.,](\d{1,3})/
const SHORT_TIMESTAMP = /^(\d{1,3}):(\d{2})[.,](\d{1,3})/

function toSeconds(match: RegExpMatchArray, minutesIndex: number): number {
  const minutes = Number(match[minutesIndex])
  const seconds = Number(match[minutesIndex + 1])
  const rawMillis = match[minutesIndex + 2] ?? '0'
  // "3" means 300ms, "03" means 30ms, "003" means 3ms.
  const millis = Number(rawMillis.padEnd(3, '0').slice(0, 3))
  return minutes * 60 + seconds + millis / 1000
}

export function parseTimestamp(line: string): number | null {
  const trimmed = line.trim()
  const long = TIMESTAMP.exec(trimmed)
  if (long) return toSeconds(long, 2)
  const short = SHORT_TIMESTAMP.exec(trimmed)
  if (short) return toSeconds(short, 1)
  return null
}

const CUE_ARROW = /-->/

/** Strip WebVTT/SRT inline markup while keeping the readable words. */
export function stripCueMarkup(text: string): string {
  return text
    .replace(/<\/?(c|v|i|b|u|ruby|rt|lang|voice)>/gi, '')
    .replace(/<[^>]+>/g, '')
    .replace(/\{\\[^}]*\}/g, '')
    .trim()
}

/**
 * Parse a subtitle document into ordered cues.
 * Supports both `.srt` (comma decimals, numbered blocks) and `.vtt`
 * (WEBVTT header, optional cue identifiers, dot decimals).
 */
export function parseSubtitles(source: string): MediaCue[] {
  const text = source.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n')
  const blocks = text.split(/\n{2,}/)
  const cues: MediaCue[] = []

  for (const rawBlock of blocks) {
    const block = rawBlock.trim()
    if (!block) continue
    if (block.startsWith('WEBVTT')) continue
    if (block.startsWith('NOTE')) continue
    if (block.startsWith('STYLE') || block.startsWith('REGION')) continue

    const lines = block.split('\n')
    const arrowIndex = lines.findIndex((line) => CUE_ARROW.test(line))
    if (arrowIndex === -1) continue

    const timingLine = lines[arrowIndex] ?? ''
    const [rawStart, rawEnd] = timingLine.split(CUE_ARROW)
    if (!rawStart || !rawEnd) continue

    const start = parseTimestamp(rawStart)
    // The end token may carry WebVTT cue settings after it; take the first.
    const endToken = rawEnd.trim().split(/\s+/)[0] ?? ''
    const end = parseTimestamp(endToken)
    if (start === null || end === null) continue
    if (end < start) continue

    const body = lines
      .slice(arrowIndex + 1)
      .join('\n')
      .trim()

    cues.push({
      index: cues.length,
      start,
      end,
      text: stripCueMarkup(body),
    })
  }

  return sortCues(cues)
}

export function sortCues(cues: MediaCue[]): MediaCue[] {
  const sorted = [...cues].sort((a, b) => a.start - b.start || a.end - b.end)
  return sorted.map((cue, index) => ({ ...cue, index }))
}

/** Serialise cues as WebVTT (used for the native `<track>` element). */
export function toWebVtt(cues: MediaCue[]): string {
  const lines = ['WEBVTT', '']
  cues.forEach((cue, index) => {
    lines.push(String(index + 1))
    lines.push(`${formatVttTime(cue.start)} --> ${formatVttTime(cue.end)}`)
    lines.push(cue.text)
    lines.push('')
  })
  return lines.join('\n')
}

export function formatVttTime(seconds: number): string {
  const safe = Math.max(0, seconds)
  const hours = Math.floor(safe / 3600)
  const minutes = Math.floor((safe % 3600) / 60)
  const secs = Math.floor(safe % 60)
  const millis = Math.round((safe - Math.floor(safe)) * 1000)
  return `${pad(hours, 2)}:${pad(minutes, 2)}:${pad(secs, 2)}.${pad(millis, 3)}`
}

function pad(value: number, width: number): string {
  return String(value).padStart(width, '0')
}

/** `mm:ss` / `h:mm:ss` for compact timeline readouts. */
export function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const total = Math.floor(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  if (hours > 0) return `${hours}:${pad(minutes, 2)}:${pad(secs, 2)}`
  return `${minutes}:${pad(secs, 2)}`
}
