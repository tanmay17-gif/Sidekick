/**
 * Session identity.
 *
 * Session ids are stored per browser tab so two tabs (or a tab plus another
 * client) never share task state. The id is sent in both the request body and
 * the `x-sidekick-session-id` header; the server decides precedence.
 */

const STORAGE_KEY = 'sidekick.session-id.v1'

export function createId(): string {
  const cryptoRef = globalThis.crypto
  if (cryptoRef && typeof cryptoRef.randomUUID === 'function') {
    return cryptoRef.randomUUID()
  }
  if (cryptoRef && typeof cryptoRef.getRandomValues === 'function') {
    const bytes = cryptoRef.getRandomValues(new Uint8Array(16))
    bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40
    bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  return `sid-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function getOrCreateSessionId(storage?: Storage): string {
  const store = storage ?? safeSessionStorage()
  if (!store) return createId()
  try {
    const existing = store.getItem(STORAGE_KEY)
    if (existing && existing.length > 0) return existing
    const created = createId()
    store.setItem(STORAGE_KEY, created)
    return created
  } catch {
    return createId()
  }
}

export function resetSessionId(storage?: Storage): string {
  const store = storage ?? safeSessionStorage()
  const created = createId()
  try {
    store?.setItem(STORAGE_KEY, created)
  } catch {
    /* storage unavailable */
  }
  return created
}

function safeSessionStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage : null
  } catch {
    return null
  }
}

export function shortId(value: string, length = 8): string {
  return value.length <= length ? value : value.slice(0, length)
}
