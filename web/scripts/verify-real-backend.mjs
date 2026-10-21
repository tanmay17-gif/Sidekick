import { chromium } from '@playwright/test'

/**
 * Verify the browser client against a REAL Sidekick backend.
 *
 * This is a cross-agent integration check. It is not part of `npm run test:e2e`
 * because it needs the Python backend to be running.
 *
 * Usage:
 *   # terminal 1 - the real backend
 *   uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8033
 *   # terminal 2 - the built client
 *   SIDECKICK_API_TARGET=http://127.0.0.1:8033 npx vite preview --port 4175
 *   # terminal 3
 *   node scripts/verify-real-backend.mjs http://127.0.0.1:4175 http://127.0.0.1:8033
 */

const clientUrl = process.argv[2] ?? 'http://127.0.0.1:4175'
const apiUrl = process.argv[3] ?? 'http://127.0.0.1:8033'

const failures = []
const check = (label, condition, detail = '') => {
  const status = condition ? 'PASS' : 'FAIL'
  if (!condition) failures.push(label)
  console.log(`${status}  ${label}${detail ? ` - ${detail}` : ''}`)
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

const consoleErrors = []
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('pageerror', (error) => consoleErrors.push(error.message))

await page.goto(clientUrl, { waitUntil: 'networkidle' })

// 1. The capability strip must show the backend's own mode, not a stub.
await page.waitForSelector('.caps__item', { timeout: 20_000 })
const capsText = await page.locator('.caps').innerText()
check(
  'capability strip reports the real backend',
  /live/i.test(capsText) && !/dev stub/i.test(capsText),
  capsText.replace(/\n/g, ' '),
)
check('capability strip does not claim a dev stub', !/dev stub/i.test(capsText))

// 2. The capability ids must be the ones the backend actually publishes.
const apiCaps = await (await fetch(`${apiUrl}/api/v1/capabilities`)).json()
const toolIds = (apiCaps.capabilities ?? []).map((capability) => capability.id)
const shownIds = await page.locator('.caps__name').allInnerTexts()
const missing = toolIds.filter((id) => !shownIds.includes(id))
check('every backend capability is shown', missing.length === 0, missing.join(', '))

// 3. A real request must produce a real response from the real engine.
await page.getByLabel('Your request').fill('take a note that the integration check ran')
await page.getByRole('button', { name: 'Send' }).click()

await page.waitForSelector('.turn', { timeout: 20_000 })
await page.waitForSelector('.bubble__meta, .bubble--error', { timeout: 20_000 })

const errorText = await page.locator('.bubble--error').count()
check('the request was answered without a client-side error', errorText === 0)

const metaText = await page.locator('.bubble__meta').first().innerText()
check('the response carries a real model attribution', /model\s/i.test(metaText), metaText.replace(/\n/g, ' '))

const planTools = await page.locator('.plan__tool').allInnerTexts()
check(
  'the action plan uses the tool the backend chose',
  planTools.length > 0,
  planTools.join(', '),
)

// 4. The spoken summary must not be a fabricated success.
const bodyText = await page.locator('body').innerText()
check('no error state is displayed', !bodyText.includes('Could not reach the Sidekick backend'))

// 5. No uncaught client exceptions.
check('no uncaught client errors', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))

await page.screenshot({ path: 'screenshots/real-backend.png' })
await browser.close()

console.log('')
if (failures.length > 0) {
  console.error(`FAILED (${failures.length}): ${failures.join('; ')}`)
  process.exit(1)
}
console.log('All real-backend integration checks passed.')
