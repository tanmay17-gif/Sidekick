import { chromium } from '@playwright/test'

/**
 * Capture reference screenshots of both interfaces at desktop size.
 * Usage: node scripts/screenshots.mjs [baseUrl] [outDir]
 */

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:4177'
const outDir = process.argv[3] ?? 'screenshots'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

await page.goto(baseUrl)
await page.waitForSelector('.voice-surface')
await page.waitForTimeout(500)
await page.screenshot({ path: `${outDir}/01-ask.png` })

await page.getByLabel('Your request').fill('take a note that the screenshot check ran')
await page.getByRole('button', { name: 'Send' }).click()
await page.waitForSelector('.task-card')
await page.waitForTimeout(500)
await page.screenshot({ path: `${outDir}/02-ask-answer.png` })

await page.getByRole('button', { name: 'Developer' }).click()
await page.waitForSelector('.arch, .control-room')
await page.waitForTimeout(500)
await page.screenshot({ path: `${outDir}/03-control-room.png` })
await page.screenshot({ path: `${outDir}/03b-control-room-full.png`, fullPage: true })

await page.getByRole('button', { name: 'Movie Buddy', exact: true }).click()
await page.waitForSelector('video')
await page.waitForTimeout(900)
await page.screenshot({ path: `${outDir}/04-movie-buddy.png` })

const video = page.locator('video')
// A gap between two caption lines: that is where the companion speaks.
await video.evaluate((element) => {
  const media = element
  media.currentTime = 15.5
  media.dispatchEvent(new Event('timeupdate'))
})
await page.waitForTimeout(700)
await page.screenshot({ path: `${outDir}/05-movie-buddy-reacting.png` })

await page.getByRole('button', { name: 'Why did Sidekick react?' }).click()
await page.waitForTimeout(500)
await page.screenshot({ path: `${outDir}/05b-movie-buddy-why.png` })

await page.setViewportSize({ width: 430, height: 900 })
await page.getByRole('button', { name: 'Ask Sidekick' }).click()
await page.waitForTimeout(400)
await page.screenshot({ path: `${outDir}/06-ask-mobile.png` })

await browser.close()
console.log(`screenshots written to ${outDir}`)
