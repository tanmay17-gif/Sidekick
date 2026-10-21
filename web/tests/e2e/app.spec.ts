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
  await expect(page.getByRole('button', { name: 'Ask Sidekick' })).toBeVisible()
})

/* ------------------------------------------------------------------ *
 * Interface A - the conversational surface
 * ------------------------------------------------------------------ */

test('leads with the companion and shows the real state', async ({ page }) => {
  const companion = page.locator('.voice-surface__orb .companion')
  await expect(companion).toHaveAttribute('data-state', 'idle')
  await expect(companion).toHaveAttribute('aria-label', /here when you need me/i)
  await expect(page.getByText('Ask me anything, or say "Turn on Movie Buddy".')).toBeVisible()
})

test('resolves a typed request and renders the real action plan', async ({ page }) => {
  await page.getByLabel('Your request').fill('play a song on spotify')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.locator('.exchange__you')).toHaveText('play a song on spotify')
  await expect(page.locator('.action-card__tool').first()).toHaveText('music.play')
})

test('shows a clarification with answerable options', async ({ page }) => {
  await page.getByLabel('Your request').fill('play something')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.exchange__ask')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Spotify' })).toBeVisible()
})

test('applies a mid-request correction before anything executes', async ({ page }) => {
  await page.getByLabel('Your request').fill('open youtube and play a song')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.action-card').first()).toBeVisible()

  await page.getByLabel('Your request').fill('no wait, spotify')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.action-card').last()).toBeVisible()

  // The correction is recorded in the shared timeline.
  await page.getByRole('button', { name: 'Control room' }).click()
  await expect(page.locator('.timeline__message', { hasText: 'Correction detected' }).first()).toBeVisible()
})

test('handles a multi-action request', async ({ page }) => {
  await page.getByLabel('Your request').fill('play a song on spotify and then start a chess game')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.action-card')).toHaveCount(2)
})

test('asks for confirmation on a risky action', async ({ page }) => {
  await page.getByLabel('Your request').fill('delete the playlist on spotify')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.exchange__ask')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Yes, do it' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'No, cancel' })).toBeVisible()
})

test('surfaces a backend failure instead of an empty answer', async ({ page }) => {
  await page.route('**/api/v1/requests', (route) => route.abort('failed'))
  await page.getByLabel('Your request').fill('play something')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.exchange--error')).toBeVisible()
})

test('offers a text fallback when the browser has no speech engine', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addInitScript(() => {
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

/* ------------------------------------------------------------------ *
 * Interface B - the control room
 * ------------------------------------------------------------------ */

test('switches between the two interfaces', async ({ page }) => {
  await page.getByRole('button', { name: 'Control room' }).click()
  await expect(page.getByRole('heading', { name: 'Control room' })).toBeVisible()
  await expect(page.getByLabel('System architecture')).toBeVisible()

  await page.getByRole('button', { name: 'Ask Sidekick' }).click()
  await expect(page.locator('.voice-surface')).toBeVisible()
})

test('both interfaces share the same session and the same real request', async ({ page }) => {
  await page.getByLabel('Your request').fill('play a song on spotify')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.exchange__you')).toHaveText('play a song on spotify')

  const sessionBefore = await page.locator('.app__session').innerText()

  await page.getByRole('button', { name: 'Control room' }).click()
  await expect(page.getByRole('heading', { name: 'Control room' })).toBeVisible()

  // The same utterance and the same action are in the inspector.
  await expect(page.locator('.control-room__request-text').first()).toHaveText(
    'play a song on spotify',
  )
  await expect(page.locator('.action-card__tool').first()).toHaveText('music.play')
  // The same session.
  await expect(page.locator('.control-room__session')).toContainText(sessionBefore)
})

test('the architecture diagram reports real states, not planned ones', async ({ page }) => {
  await page.getByRole('button', { name: 'Control room' }).click()
  const diagram = page.getByLabel('System architecture')
  await expect(diagram).toBeVisible()
  await expect(diagram.getByText('Core decision engine')).toBeVisible()
  await expect(diagram.getByText('Execution service')).toBeVisible()
  // With no request yet, nothing that does work is drawn as connected.
  const execution = diagram.locator('.arch__node', { hasText: 'Execution service' })
  await expect(execution).toHaveAttribute('data-state', 'idle')
  await expect(diagram.locator('.arch__node', { hasText: 'Core decision engine' })).toHaveAttribute(
    'data-state',
    'idle',
  )
})

test('the capability health table shows the true statuses', async ({ page }) => {
  await page.getByRole('button', { name: 'Control room' }).click()
  const table = page.getByRole('table')
  await expect(table).toBeVisible()
  await expect(table.getByText('music.play')).toBeVisible()
  await expect(table.getByText('UNCONFIGURED')).toBeVisible()
})

test('the task timeline shows real events and never invents them', async ({ page }) => {
  await page.getByRole('button', { name: 'Control room' }).click()
  await expect(page.getByText('Task timeline')).toBeVisible()
  await expect(page.getByText(/No events yet/i)).toBeVisible()

  // Ask something, and the events the backend produced appear in the timeline.
  await page.getByRole('button', { name: 'Ask Sidekick' }).click()
  await page.getByLabel('Your request').fill('play a song on spotify')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.exchange__you')).toHaveText('play a song on spotify')

  await page.getByRole('button', { name: 'Control room' }).click()
  await expect(page.locator('.control-room__request').first()).toBeVisible()
})

/* ------------------------------------------------------------------ *
 * Movie Buddy
 * ------------------------------------------------------------------ */

test('states what Movie Buddy can and cannot observe', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie Buddy', exact: true }).click()
  await expect(page.getByText(/cannot see other browser tabs/i)).toBeVisible()
  await expect(page.getByText(/does not analyse the picture/i)).toBeVisible()
})

test('turns Movie Buddy on from a typed command, without naming a film', async ({ page }) => {
  await page.getByLabel('Your request').fill('Turn on Movie Buddy.')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByRole('heading', { name: 'Watch together' })).toBeVisible()
  await expect(page.getByText(/Movie Buddy is on and waiting with you/i)).toBeVisible()
})

test('really plays the bundled film and syncs the captions to the media clock', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie Buddy', exact: true }).click()

  const video = page.locator('video')
  await expect(video).toBeVisible()
  await expect(page.locator('video source[src*="duck-and-cover.mp4"]')).toHaveCount(1)

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
  expect(duration).toBeGreaterThan(140)
  expect(duration).toBeLessThan(160)

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

  const overlay = page.locator('.stage__overlay')
  await expect(overlay).not.toHaveAttribute('data-empty', 'true')
  expect((await overlay.innerText()).length).toBeGreaterThan(0)
})

test('the companion reacts at a real caption and explains why', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie Buddy', exact: true }).click()
  // The surface starts switched on; make sure it is.
  const toggle = page.getByRole('button', { name: /Turn (on|off) Movie Buddy/ })
  if ((await toggle.innerText()).includes('Turn off')) {
    await toggle.click()
    await page.getByRole('button', { name: 'Turn on Movie Buddy' }).click()
  }

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
  await page.getByRole('button', { name: 'Movie Buddy', exact: true }).click()
  await page.getByRole('button', { name: 'Be quiet for a bit' }).click()
  await expect(page.getByText(/Staying quiet for \d+ more seconds/i)).toBeVisible()

  await page.getByRole('button', { name: 'Resume Movie Buddy' }).click()
  await expect(
    page.getByText(/Movie Buddy is on and waiting with you|Movie Buddy is on and following/i),
  ).toBeVisible()
})

test('seeks backwards with the real media clock', async ({ page }) => {
  await page.getByRole('button', { name: 'Movie Buddy', exact: true }).click()
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
  await page.getByRole('button', { name: 'Movie Buddy', exact: true }).click()
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
    media.currentTime = 34
    media.dispatchEvent(new Event('timeupdate'))
  })
  await page.getByRole('button', { name: 'What just happened?' }).click()
  await expect(page.getByText('Sidekick said')).toBeVisible()
  await expect(page.locator('.buddy__answer')).toContainText(/caption/i)
})

test('recovers when the media resource cannot be loaded', async ({ page }) => {
  await page.route('**/media/duck-and-cover/*', (route) => route.abort('failed'))
  await page.getByRole('button', { name: 'Movie Buddy', exact: true }).click()

  const video = page.locator('video')
  await expect(video).toBeVisible()
  await expect(
    page.getByText(/not supported or the network blocked it|cannot decode|none of the available video formats/i),
  ).toBeVisible()
  // The rest of the surface keeps working.
  await expect(page.locator('.buddy__panel')).toBeVisible()
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

  const sessionA = await pageA.locator('.app__session').innerText()
  const sessionB = await pageB.locator('.app__session').innerText()
  expect(sessionA).not.toEqual(sessionB)

  await pageA.getByLabel('Your request').fill('play a song on spotify')
  await pageA.getByRole('button', { name: 'Send' }).click()
  await expect(pageA.locator('.exchange__you')).toHaveText('play a song on spotify')

  await expect(pageB.locator('.exchange')).toHaveCount(0)

  await contextA.close()
  await contextB.close()
})

test('recovers from a disconnect and starts a clean session on demand', async ({ page }) => {
  await page.getByLabel('Your request').fill('play a song on spotify')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('.action-card').first()).toBeVisible()

  const before = await page.locator('.app__session').innerText()
  await page.getByRole('button', { name: 'New session' }).click()

  const after = await page.locator('.app__session').innerText()
  expect(after).not.toEqual(before)
  // The conversation is gone and the control room agrees.
  await expect(page.locator('.exchange')).toHaveCount(0)
  await page.getByRole('button', { name: 'Control room' }).click()
  await expect(page.getByText(/Nothing has been asked yet/i)).toBeVisible()
})
