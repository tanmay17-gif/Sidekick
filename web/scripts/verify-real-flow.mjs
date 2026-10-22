import { chromium } from '@playwright/test'

/**
 * Verify the exact sequence from the milestone brief against a REAL backend.
 *
 *   1. Start an unrelated action.
 *   2. Submit "Open YouTube and play a song - no wait, Spotify."
 *   3. Confirm the music request does not inherit the other action.
 *   4. Cancel an action and verify the backend response and the UI agree.
 *   5. Start a new session and confirm the previous state is not shown as current.
 *   6. Capture the normal experience.
 *
 * The utterances here are the ones the real core actually declares
 * (`note.write`, `timer.set`, `media.open`). The core has no chess tool and
 * no tool that requires approval, so those two cases are covered against the
 * development stub instead - see tests/unit/app.test.tsx.
 *
 * Usage:
 *   node scripts/verify-real-flow.mjs [clientUrl] [apiUrl]
 */

const clientUrl = process.argv[2] ?? 'http://127.0.0.1:4179'
const apiUrl = process.argv[3] ?? 'http://127.0.0.1:8050'

const failures = []
const check = (label, condition, detail = '') => {
  const status = condition ? 'PASS' : 'FAIL'
  if (!condition) failures.push(label)
  console.log(`${status}  ${label}${detail ? ` - ${detail}` : ''}`)
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const cancelCalls = []
page.on('response', (response) => {
  const url = response.url()
  if (url.includes('/api/v1/actions/') && response.request().method() === 'POST') {
    cancelCalls.push({ url, status: response.status() })
  }
})

await page.goto(clientUrl, { waitUntil: 'networkidle' })
await page.waitForSelector('.voice-surface')

/* -- 1. start an unrelated action ------------------------------------ */
console.log('\n1. start an unrelated action')
await page.getByLabel('Your request').fill('take a note that the chess game started')
await page.getByRole('button', { name: 'Send' }).click()
await page.waitForSelector('.task-card', { timeout: 30_000 })
await page.waitForTimeout(800)
const firstCard = await page.locator('.task-card').first().innerText()
check(
  'the first action is shown in its own exchange',
  /notes/i.test(firstCard),
  firstCard.replace(/\n/g, ' | '),
)

/* -- 2. submit the corrected music request -------------------------- */
console.log('\n2. submit "Open YouTube and play a song - no wait, Spotify."')
await page.getByLabel('Your request').fill('Open YouTube and play a song - no wait, Spotify.')
await page.getByRole('button', { name: 'Send' }).click()
await page.waitForTimeout(1500)

const exchanges = page.locator('.exchange')
const exchangeCount = await exchanges.count()
check('the new request produced its own exchange', exchangeCount >= 2, `${exchangeCount} exchanges`)

/* -- 3. the music request must not inherit the other action ---------- */
console.log('\n3. the music request does not inherit the other action')
const latest = exchanges.nth(exchangeCount - 1)
const latestText = await latest.innerText()
check(
  'the latest exchange does not mention the earlier action',
  !/notes/i.test(latestText),
  latestText.replace(/\n/g, ' | '),
)

const latestCards = latest.locator('.task-card')
const cardCount = await latestCards.count()
let inherited = false
for (let index = 0; index < cardCount; index += 1) {
  const text = await latestCards.nth(index).innerText()
  if (/notes/i.test(text)) inherited = true
}
check('no earlier action is shown inside the music exchange', !inherited)

/* -- 4. cancel an action and compare the backend and the UI ---------- */
console.log('\n4. cancel an action and compare the backend and the UI')
await page.getByLabel('Your request').fill('set a timer for 300 seconds')
await page.getByRole('button', { name: 'Send' }).click()
await page.waitForTimeout(1200)

const cancelCard = page.locator('.task-card').last()
const beforeCancel = await cancelCard.innerText()
const hasCancel = (await cancelCard.getByRole('button', { name: /^Cancel$/ }).count()) > 0
check('the running action offers a cancel control', hasCancel, beforeCancel.replace(/\n/g, ' | '))

if (hasCancel) {
  await cancelCard.getByRole('button', { name: /^Cancel$/ }).click()
  await page.waitForTimeout(1500)

  const afterCancel = await cancelCard.innerText()
  const cancelCall = cancelCalls[cancelCalls.length - 1]
  check('the backend was actually asked to cancel', Boolean(cancelCall), JSON.stringify(cancelCall))

  const actionId = cancelCall?.url.match(/actions\/([^/?]+)/)?.[1]
  if (actionId) {
    const backendState = await (
      await fetch(`${apiUrl}/api/v1/actions/${actionId}`)
    ).json()
    const backendActionState = backendState?.action?.state ?? 'unknown'
    const uiCancelled = /cancelled/i.test(afterCancel)
    check(
      'the interface and the backend agree on the state',
      uiCancelled === (backendActionState === 'cancelled'),
      `ui=${uiCancelled ? 'cancelled' : 'not cancelled'} backend=${backendActionState}`,
    )
    check(
      'the interface shows the cancellation',
      uiCancelled,
      afterCancel.replace(/\n/g, ' | '),
    )
  }
}

/* -- 5. a new session starts clean ----------------------------------- */
console.log('\n5. a new session does not present the previous state as current')
const sessionBefore = await page.locator('.app__session').innerText()
await page.getByRole('button', { name: 'New session' }).click()
await page.waitForTimeout(900)
const sessionAfter = await page.locator('.app__session').innerText()
check('the session id changed', sessionBefore !== sessionAfter, `${sessionBefore} -> ${sessionAfter}`)
check('no action from the previous session is shown', (await page.locator('.task-card').count()) === 0)
check(
  'the interface is back to its ready state',
  (await page.getByText('Ask me anything, or say "Turn on Movie Buddy".').count()) === 1,
)

/* -- 6. the normal experience ---------------------------------------- */
console.log('\n6. the normal experience')
await page.getByRole('button', { name: 'Ask Sidekick' }).click()
await page.waitForTimeout(400)
const orb = page.locator('.voice-surface__orb .companion')
check('the companion is the centre of the screen', (await orb.count()) === 1)
check('the companion has an accessible state label', Boolean(await orb.getAttribute('aria-label')))
check(
  'there is one prominent microphone',
  (await page.getByRole('button', { name: /Start voice input/i }).count()) === 1,
)
check('there is a text input alternative', (await page.getByLabel('Your request').count()) === 1)
await page.screenshot({ path: 'screenshots/real-flow-ask.png' })

await page.getByRole('button', { name: 'Developer' }).click()
await page.waitForTimeout(600)
await page.screenshot({ path: 'screenshots/real-flow-developer.png' })

await browser.close()

console.log('')
if (failures.length > 0) {
  console.error(`FAILED (${failures.length}): ${failures.join('; ')}`)
  process.exit(1)
}
console.log('All real-flow checks passed.')
