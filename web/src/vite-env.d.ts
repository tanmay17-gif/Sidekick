/// <reference types="vite/client" />
/// <reference types="vitest/globals" />

interface ImportMetaEnv {
  readonly VITE_SIDECKICK_API_BASE?: string
  readonly VITE_SIDECKICK_INTERPRET_PATH?: string
  readonly VITE_SIDECKICK_CAPABILITIES_PATH?: string
  readonly VITE_SIDECKICK_MEDIA_PATH?: string
  readonly VITE_SIDECKICK_ACTION_PATH?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
