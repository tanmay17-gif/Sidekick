import { chromium } from '@playwright/test'

/**
 * Capture reference screenshots of the main surfaces at desktop size.
 * Usage: node scripts/screenshots.mjs [baseUrl] [outDir]
 */

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:4177'
const outDir = process.argv[3] ?? 'screenshots'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

await page.goto(baseUrl)
await page.waitForSelector('.caps__item')
await page.waitForTimeout(400)
await page.screenshot({ path: `${outDir}/01-talk-empty.png` })

await page.getByLabel('Your request').fill('play a song on spotify and then start a chess game')
await page.getByRole('button', { name: 'Send' }).click()
await page.waitForSelector('.trace')
await page.waitForTimeout(500)
await page.screenshot({ path: `${outDir}/02-talk-decision-trace.png` })
await page.screenshot({ path: `${outDir}/02b-talk-full.png`, fullPage: true })

await page.getByRole('button', { name: 'Movie Buddy' }).click()
await page.waitForSelector('video')
await page.waitForTimeout(900)
await page.screenshot({ path: `${outDir}/03-movie-buddy.png` })

// Turn the companion on and let it meet the first caption line.
await page.getByRole('button', { name: 'Turn on Movie Buddy' }).click()
await page.waitForTimeout(400)
const video = page.locator('video')
await video.evaluate((element) => {
  element.currentTime = 1.5
})
await video.evaluate((element) => element.dispatchEvent(new Event('timeupdate')))
await page.waitForTimeout(600)
await page.screenshot({ path: `${outDir}/03b-movie-buddy-reacting.png` })

await page.getByRole('button', { name: 'Why did Sidekick react?' }).click()
await page.waitForTimeout(300)
await page.screenshot({ path: `${outDir}/03c-movie-buddy-why.png` })

await page.getByRole('button', { name: 'Music' }).click()
await page.waitForTimeout(400)
await page.screenshot({ path: `${outDir}/04-music.png` })

await page.getByRole('button', { name: 'Games' }).click()
await page.waitForTimeout(400)
await page.screenshot({ path: `${outDir}/05-games.png` })

await page.setViewportSize({ width: 430, height: 900 })
await page.getByRole('button', { name: 'Talk' }).click()
await page.waitForTimeout(400)
await page.screenshot({ path: `${outDir}/06-talk-mobile.png` })

await browser.close()
console.log(`screenshots written to ${outDir}`)
