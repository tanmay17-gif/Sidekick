import { chromium } from '@playwright/test'

/**
 * Verify the browser client against a REAL Sidekick backend.
 *
 * This is a cross-agent integration check. It is not part of `npm run test:e2e`
 * because it needs the Python backend to be running.
 *
 * Usage:
 *   # terminal 1 - the real backend
 *   python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8040
 *   # terminal 2 - the built client
 *   SIDECKICK_API_TARGET=http://127.0.0.1:8040 npx vite preview --port 4178
 *   # terminal 3
 *   node scripts/verify-real-backend.mjs http://127.0.0.1:4178 http://127.0.0.1:8040
 */

const clientUrl = process.argv[2] ?? 'http://127.0.0.1:4178'
const apiUrl = process.argv[3] ?? 'http://127.0.0.1:8040'

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
await page.waitForSelector('.app__bar')

/* ---- The capability inventory comes from the backend ---------------- */
const apiCaps = await (await fetch(`${apiUrl}/api/v1/capabilities`)).json()
const toolIds = (apiCaps.capabilities ?? []).map((capability) => capability.id)

const modeBadge = await page.locator('.app__status .badge').innerText()
check(
  'the backend mode is reported verbatim',
  apiCaps.mode === 'stub' ? /dev stub/i.test(modeBadge) : /backend live/i.test(modeBadge),
  modeBadge,
)

await page.getByRole('button', { name: 'Control room' }).click()
await page.waitForSelector('.health')

const healthText = await page.locator('.health').innerText()
const missing = toolIds.filter((id) => !healthText.includes(id))
check('every backend capability is shown', missing.length === 0, missing.join(', '))

/* ---- A real request, answered by the real engine -------------------- */
await page.getByRole('button', { name: 'Ask Sidekick' }).click()
await page.getByLabel('Your request').fill('take a note that the integration check ran')
await page.getByRole('button', { name: 'Send' }).click()

await page.waitForSelector('.action-card', { timeout: 30_000 })
await page.waitForFunction(
  () => !document.querySelector('.exchange--pending'),
  undefined,
  { timeout: 30_000 },
)

const errorCount = await page.locator('.exchange--error').count()
check('the request was answered without a client-side error', errorCount === 0)

const planTools = await page.locator('.action-card__tool').allInnerTexts()
check(
  'the action plan uses the tool the backend chose',
  planTools.length > 0,
  planTools.join(', '),
)

/* ---- Both interfaces describe the same work ------------------------- */
await page.getByRole('button', { name: 'Control room' }).click()
await page.waitForSelector('.control-room__detail')

const inspector = await page.locator('.control-room__detail').innerText()
check('the control room shows the same action', planTools.some((tool) => inspector.includes(tool)))

const requestRows = await page.locator('.control-room__request-text').allInnerTexts()
check(
  'the control room shows the same utterance',
  requestRows.some((row) => row.includes('take a note that the integration check ran')),
)

const facts = await page.locator('.control-room__facts').innerText()
check('the real model and provider are shown', /rule-engine|sidekick/.test(facts), facts.replace(/\n/g, ' '))
check('the real confidence is shown', /\d+%/.test(facts))

/* ---- The architecture diagram reflects reality ----------------------- */
const diagram = await page.locator('.arch').innerText()
check('the architecture diagram names the real engine', diagram.includes('Core decision engine'))
const resultNode = page.locator('.arch__node', { hasText: 'Result' })
check(
  'the result node reflects the action that really finished',
  (await resultNode.getAttribute('data-state')) === 'connected',
  (await resultNode.innerText()).replace(/\n/g, ' '),
)
const executionNode = page.locator('.arch__node', { hasText: 'Execution service' })
const executionState = await executionNode.getAttribute('data-state')
check(
  'the execution node is not drawn as live unless an adapter says so',
  executionState !== 'connected' || /REAL/.test(await executionNode.innerText()),
  (await executionNode.innerText()).replace(/\n/g, ' '),
)

/* ---- The film really plays ------------------------------------------ */
await page.getByRole('button', { name: 'Movie Buddy', exact: true }).click()
await page.waitForSelector('video')
const mediaOk = await page
  .waitForFunction(
    () => {
      const element = document.querySelector('video')
      return element instanceof HTMLVideoElement && element.readyState >= 1 && element.duration > 0
    },
    undefined,
    { timeout: 30_000 },
  )
  .then(() => true)
  .catch(() => false)
check('the bundled film really loads', mediaOk)

/* ---- No uncaught client errors --------------------------------------- */
check('no uncaught client errors', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '))

await page.screenshot({ path: 'screenshots/real-backend.png' })
await browser.close()

console.log('')
if (failures.length > 0) {
  console.error(`FAILED (${failures.length}): ${failures.join('; ')}`)
  process.exit(1)
}
console.log('All real-backend integration checks passed.')
