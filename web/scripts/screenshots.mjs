import { chromium } from '@playwright/test'

/**
 * Capture reference screenshots of the main surfaces at desktop size.
 * Usage: node scripts/screenshots.mjs [baseUrl] [outDir]
 */

const baseUrl = process.argv[2] ?? 'http://127.0.0.1:4174'
const outDir = process.argv[3] ?? 'screenshots'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

await page.goto(baseUrl)
await page.waitForSelector('.caps__item')
await page.screenshot({ path: `${outDir}/01-talk-empty.png` })

await page.getByLabel('Your request').fill('play a song on spotify and then start a chess game')
await page.getByRole('button', { name: 'Send' }).click()
await page.waitForSelector('.plan__item')
await page.waitForTimeout(400)
await page.screenshot({ path: `${outDir}/02-talk-plan.png` })

await page.getByRole('button', { name: 'Movie' }).click()
await page.waitForSelector('video')
await page.waitForTimeout(1200)
await page.screenshot({ path: `${outDir}/03-movie.png` })

await page.getByRole('button', { name: 'Music' }).click()
await page.waitForTimeout(400)
await page.screenshot({ path: `${outDir}/04-music.png` })

await page.getByRole('button', { name: 'Games' }).click()
await page.waitForTimeout(400)
await page.screenshot({ path: `${outDir}/05-games.png` })

// Expand the local activities so they are visible in the reference set.
const summaries = page.locator('.activity__summary')
const count = await summaries.count()
for (let index = 0; index < count; index += 1) {
  await summaries.nth(index).click()
}
await page.locator('.activity').first().scrollIntoViewIfNeeded()
await page.waitForTimeout(400)
await page.screenshot({ path: `${outDir}/05b-games-local.png` })

await page.setViewportSize({ width: 430, height: 860 })
await page.getByRole('button', { name: 'Talk' }).click()
await page.waitForTimeout(400)
await page.screenshot({ path: `${outDir}/06-talk-mobile.png` })

await browser.close()
console.log(`screenshots written to ${outDir}`)
