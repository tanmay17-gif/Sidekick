import { expect, test } from '@playwright/test'

/**
 * End-to-end tests.
 *
 * Scope: these run the real production build in a real browser and talk to the
 * Sidekick *development stub* over HTTP. They therefore prove the browser
 * client, the HTTP transport, the session header and the rendering of real
 * contract payloads. They do NOT prove the real backend (owned by the
 * Core/Execution agents) - see docs/EXPERIENCE.md for the claim levels.
 */

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'What should Sidekick do?' })).toBeVisible()
})

test('reports the backend capability inventory with honest state labels', async ({ page }) => {
  const caps = page.locator('.caps')
  await expect(caps.getByText('dev stub')).toBeVisible()
  await expect(caps.getByText('voice.stt')).toBeVisible()
  await expect(caps.getByText('music.play')).toBeVisible()
  await expect(caps.getByText('unconfigured')).toBeVisible()
})

test('resolves a typed request and renders the real action plan', async ({ page }) => {
  await page.getByLabel('Your request').fill('play a song on spotify')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.locator('.turn__utterance')).toHaveText('play a song on spotify')
  const plan = page.locator('.plan__item').first()
  await expect(plan.locator('.plan__tool')).toHaveText('music.play')
  await expect(page.locator('.bubble__meta').first()).toContainText('deterministic-rules')
})

test('applies a mid-request correction before anything executes', async ({ page }) => {
  await page.getByLabel('Your request').fill('open youtube and play a song')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.plan__item').first()).toBeVisible()

  await page.getByLabel('Your request').fill('no wait, spotify')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByText('Correction detected')).toBeVisible()
  await expect(page.locator('.plan__item').last().locator('.plan__tool')).toHaveText('music.play')
})

test('handles a multi-action request', async ({ page }) => {
  await page.getByLabel('Your request').fill('play a song on spotify and then start a chess game')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.locator('.plan__item')).toHaveCount(2)
  await expect(page.locator('.plan__tool').nth(0)).toHaveText('music.play')
  await expect(page.locator('.plan__tool').nth(1)).toHaveText('game.chess')
})

test('asks for confirmation on a risky action', async ({ page }) => {
  await page.getByLabel('Your request').fill('delete the playlist on spotify')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.locator('.ask__question')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Yes, do it' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'No, cancel' })).toBeVisible()
})

test('surfaces a backend failure instead of an empty answer', async ({ page }) => {
  await page.route('**/api/v1/requests', (route) => route.abort('failed'))
  await page.getByLabel('Your request').fill('play something')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.locator('.bubble--error')).toBeVisible()
  await expect(page.locator('.bubble--error')).toContainText(/could not reach|network/i)
})

test('streams live progress and renders the real diff for a coding job', async ({ page }) => {
  await page.getByLabel('Your request').fill('write a function that greets the user')
  await page.getByRole('button', { name: 'Send' }).click()

  // Progress arrives over the event stream, not from a local timer.
  await expect(page.getByText('Live progress')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Job queued')).toBeVisible()

  // The patch is the one the backend sent.
  await expect(page.getByText('unified diff')).toBeVisible()
  await expect(page.locator('.diff__line--add').first()).toBeVisible()
  await expect(page.getByText(/const trimmed = name\.trim\(\)/)).toBeVisible()
})

test('offers a text fallback when the browser has no speech engine', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addInitScript(() => {
    // Simulate a browser without the Web Speech recognition API.
    // @ts-expect-error - deleting a browser global on purpose
    delete window.SpeechRecognition
    // @ts-expect-error - deleting a browser global on purpose
    delete window.webkitSpeechRecognition
  })
  const page = await context.newPage()
  await page.goto('/')

  const mic = page.getByRole('button', { name: /Voice input is not available/i })
  await expect(mic).toBeDisabled()
  await expect(page.getByText('text only')).toBeVisible()
  await expect(page.getByLabel('Your request')).toBeVisible()
  await context.close()
})

test('shows the movie companion with a real subtitle track', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie' }).click()

  const video = page.locator('video')
  await expect(video).toBeVisible()
  await expect(video).toHaveAttribute('src', /tears_of_steel_720p\.mp4/)

  const track = page.locator('video track')
  await expect(track).toHaveCount(1)
  await expect(track).toHaveAttribute('kind', 'subtitles')
  await expect(page.getByText(/Subtitle-based/)).toBeVisible()
  await expect(page.getByText('76 timed lines')).toBeVisible()
})

test('recovers when the media resource cannot be loaded', async ({ page }) => {
  await page.route('**/*.mp4', (route) => route.abort('failed'))
  await page.getByRole('button', { name: 'Movie' }).click()

  const video = page.locator('video')
  await expect(video).toBeVisible()
  await expect(page.getByText(/could not be loaded|not supported|blocked/i)).toBeVisible()
  // The rest of the surface keeps working.
  await expect(page.getByRole('heading', { name: 'Companion' })).toBeVisible()
})

test('keeps the music surface honest about an unconfigured provider', async ({ page }) => {
  await page.getByRole('button', { name: 'Music' }).click()
  await expect(page.locator('.list__title', { hasText: 'Spotify' })).toBeVisible()
  await expect(page.locator('.list__row').first().getByText('not configured')).toBeVisible()
  await expect(page.getByText(/requires a spotify developer app id/i)).toBeVisible()
})

test('shows the games the backend reports and renders the reported board', async ({ page }) => {
  await page.getByRole('button', { name: 'Games' }).click()
  await expect(page.locator('.list__title', { hasText: 'Chess' })).toBeVisible()
  await expect(page.locator('.list__row').first().getByText('simulated')).toBeVisible()
})
