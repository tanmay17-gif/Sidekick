import { expect, test } from '@playwright/test'

/**
 * End-to-end tests.
 *
 * Scope: these run the real production build in a real browser and talk to the
 * Sidekick *development stub* over HTTP. They therefore prove the browser
 * client, the HTTP transport, the session header, the rendering of real
 * contract payloads and real media playback. They do NOT prove the real
 * Sidekick backend (owned by the Core/Execution agents) - see
 * docs/EXPERIENCE.md for the claim levels.
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

test('shows the companion and the real current task', async ({ page }) => {
  const companion = page.locator('.hero__companion .companion')
  await expect(companion).toHaveAttribute('data-state', 'idle')
  await expect(companion).toHaveAttribute('aria-label', /here when you need me/i)
  await expect(page.getByText('Ready', { exact: true })).toBeVisible()
})

test('resolves a typed request and renders the real action plan', async ({ page }) => {
  await page.getByLabel('Your request').fill('play a song on spotify')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.locator('.turn__utterance')).toHaveText('play a song on spotify')
  const plan = page.locator('.plan__item').first()
  await expect(plan.locator('.plan__tool')).toHaveText('music.play')
})

test('shows a decision trace built from the real response', async ({ page }) => {
  await page.getByLabel('Your request').fill('play a song on spotify')
  await page.getByRole('button', { name: 'Send' }).click()

  const trace = page.locator('.trace')
  await expect(trace).toBeVisible()
  await expect(trace.getByText('Heard')).toBeVisible()
  await expect(trace.getByText('Understood')).toBeVisible()
  await expect(trace.getByText('Decided')).toBeVisible()
  await expect(trace.getByText('Planned')).toBeVisible()
  // The provenance the backend reported is shown verbatim.
  await expect(trace).toContainText('deterministic-rules')
})

test('exposes the raw payload in the developer inspection mode', async ({ page }) => {
  await page.getByLabel('Your request').fill('play a song on spotify')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.trace')).toBeVisible()

  await page.getByRole('button', { name: 'Raw payload' }).click()
  const raw = page.getByLabel('Raw response payload')
  await expect(raw).toContainText('"request_id"')
})

test('applies a mid-request correction before anything executes', async ({ page }) => {
  await page.getByLabel('Your request').fill('open youtube and play a song')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.plan__item').first()).toBeVisible()

  await page.getByLabel('Your request').fill('no wait, spotify')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByText('Correction detected').first()).toBeVisible()
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

/* ------------------------------------------------------------------ *
 * Movie Buddy
 * ------------------------------------------------------------------ */

test('states what Movie Buddy can and cannot observe', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie Buddy' }).click()
  await expect(page.getByText(/cannot see other browser tabs/i)).toBeVisible()
  await expect(page.getByText(/does not analyse the picture/i)).toBeVisible()
})

test('turns Movie Buddy on from a typed command, without naming a film', async ({ page }) => {
  await page.getByLabel('Your request').fill('Turn on Movie Buddy.')
  await page.getByRole('button', { name: 'Send' }).click()

  // The surface switched and the companion is on.
  await expect(page.getByRole('heading', { name: 'Watch together' })).toBeVisible()
  await expect(page.getByText(/Movie Buddy is on and waiting with you/i)).toBeVisible()
})

test('really plays the bundled film and syncs the captions to the media clock', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie Buddy' }).click()

  const video = page.locator('video')
  await expect(video).toBeVisible()
  await expect(page.locator('video source[src*="letter-v.mp4"]')).toHaveCount(1)

  // The media really loads: the browser knows its duration.
  await page.waitForFunction(
    () => {
      const element = document.querySelector('video')
      return element instanceof HTMLVideoElement && element.readyState >= 1 && element.duration > 0
    },
    undefined,
    { timeout: 30_000 },
  )
  const duration = await video.evaluate((element) => (element as HTMLVideoElement).duration)
  expect(duration).toBeGreaterThan(100)
  expect(duration).toBeLessThan(200)

  // Play it for real and let the media clock advance.
  await video.evaluate((element) => {
    const media = element as HTMLVideoElement
    media.muted = true
    return media.play()
  })
  await page.waitForFunction(
    () => {
      const element = document.querySelector('video')
      return element instanceof HTMLVideoElement && element.currentTime > 1
    },
    undefined,
    { timeout: 30_000 },
  )

  // The caption shown is the cue at the real playback position.
  const overlay = page.locator('.stage__overlay')
  await expect(overlay).not.toHaveAttribute('data-empty', 'true')
  const spoken = await overlay.innerText()
  expect(spoken.length).toBeGreaterThan(0)
})

test('the companion reacts at a real caption and explains why', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie Buddy' }).click()
  await page.getByRole('button', { name: 'Turn on Movie Buddy' }).click()

  const video = page.locator('video')
  await page.waitForFunction(
    () => {
      const element = document.querySelector('video')
      return element instanceof HTMLVideoElement && element.readyState >= 1
    },
    undefined,
    { timeout: 30_000 },
  )

  // Move the real media clock onto the first caption line.
  await video.evaluate((element) => {
    const media = element as HTMLVideoElement
    media.currentTime = 1.5
    media.dispatchEvent(new Event('timeupdate'))
  })

  await expect(page.locator('.buddy__log-item').first()).toBeVisible()
  await page.getByRole('button', { name: 'Why did Sidekick react?' }).click()
  await expect(page.getByText(/first line in the caption track/i)).toBeVisible()
})

test('goes quiet on request and resumes', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie Buddy' }).click()
  await page.getByRole('button', { name: 'Be quiet for a bit' }).click()
  await expect(page.getByText(/Staying quiet for \d+ more seconds/i)).toBeVisible()

  await page.getByRole('button', { name: 'Resume Movie Buddy' }).click()
  await expect(page.getByText(/Movie Buddy is on and waiting with you|Movie Buddy is on and following/i)).toBeVisible()
})

test('seeks backwards with the real media clock', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie Buddy' }).click()
  const video = page.locator('video')
  await page.waitForFunction(
    () => {
      const element = document.querySelector('video')
      return element instanceof HTMLVideoElement && element.readyState >= 1
    },
    undefined,
    { timeout: 30_000 },
  )
  await video.evaluate((element) => {
    ;(element as HTMLVideoElement).currentTime = 60
  })
  await page.getByRole('button', { name: '-30s' }).click()
  const time = await video.evaluate((element) => (element as HTMLVideoElement).currentTime)
  expect(time).toBeGreaterThanOrEqual(29)
  expect(time).toBeLessThanOrEqual(31)
})

test('answers what just happened from the captions', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie Buddy' }).click()
  const video = page.locator('video')
  await page.waitForFunction(
    () => {
      const element = document.querySelector('video')
      return element instanceof HTMLVideoElement && element.readyState >= 1
    },
    undefined,
    { timeout: 30_000 },
  )
  await video.evaluate((element) => {
    const media = element as HTMLVideoElement
    media.currentTime = 22
    media.dispatchEvent(new Event('timeupdate'))
  })
  await page.getByRole('button', { name: 'What just happened?' }).click()
  await expect(page.getByText('Sidekick said')).toBeVisible()
  await expect(page.locator('.buddy__answer')).toContainText(/caption/i)
})

test('recovers when the media resource cannot be loaded', async ({ page }) => {
  await page.route('**/media/letter-v/*', (route) => route.abort('failed'))
  await page.getByRole('button', { name: 'Movie Buddy' }).click()

  const video = page.locator('video')
  await expect(video).toBeVisible()
  await expect(page.getByText(/not supported or the network blocked it|cannot decode|none of the available video formats/i)).toBeVisible()
  // The rest of the surface keeps working.
  await expect(page.locator('.buddy__panel')).toBeVisible()
  await expect(page.getByText('Say or type')).toBeVisible()
})

/* ------------------------------------------------------------------ *
 * Session behaviour
 * ------------------------------------------------------------------ */

test('isolates two concurrent sessions', async ({ browser }) => {
  const contextA = await browser.newContext()
  const contextB = await browser.newContext()
  const pageA = await contextA.newPage()
  const pageB = await contextB.newPage()

  await pageA.goto('/')
  await pageB.goto('/')

  const sessionA = await pageA.locator('.session__id').innerText()
  const sessionB = await pageB.locator('.session__id').innerText()
  expect(sessionA).not.toEqual(sessionB)

  await pageA.getByLabel('Your request').fill('play a song on spotify')
  await pageA.getByRole('button', { name: 'Send' }).click()
  await expect(pageA.locator('.plan__item').first()).toBeVisible()

  await expect(pageB.locator('.turn')).toHaveCount(0)
  await expect(pageB.getByText('Nothing asked yet')).toBeVisible()

  await contextA.close()
  await contextB.close()
})

test('recovers from a disconnect and starts a clean session on demand', async ({ page }) => {
  await page.getByLabel('Your request').fill('play a song on spotify')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.plan__item').first()).toBeVisible()

  const before = await page.locator('.session__id').innerText()
  await page.getByRole('button', { name: 'New session' }).click()

  const after = await page.locator('.session__id').innerText()
  expect(after).not.toEqual(before)
  await expect(page.getByText('Nothing asked yet')).toBeVisible()
})
