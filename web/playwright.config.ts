import { defineConfig, devices } from '@playwright/test'

const PORT = Number(process.env.SIDECKICK_E2E_PORT ?? 4174)
const STUB_PORT = Number(process.env.SIDECKICK_STUB_PORT ?? 8011)

/**
 * End-to-end configuration.
 *
 * The E2E suite runs the real Vite build against the development stub server.
 * That makes it an *integration* check of the browser client plus HTTP
 * transport - it is explicitly NOT a check of the real Sidekick backend, which
 * lives in the Core/Execution agents' services.
 */
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command: `node dev/stub-server.mjs`,
      port: STUB_PORT,
      reuseExistingServer: !process.env.CI,
      env: { SIDECKICK_STUB_PORT: String(STUB_PORT) },
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // Bind explicitly to 127.0.0.1: on CI runners `localhost` can resolve to
      // ::1 only, which makes the IPv4 base URL fail with ECONNREFUSED.
      command: `npm run build && npx vite preview --port ${PORT} --strictPort --host 127.0.0.1`,
      port: PORT,
      reuseExistingServer: !process.env.CI,
      env: { SIDECKICK_API_TARGET: `http://127.0.0.1:${STUB_PORT}` },
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
