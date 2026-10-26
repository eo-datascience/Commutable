// Render the two images that cannot be SVG.
//
// The favicon is an SVG and themes itself, which every current browser
// understands. Two things still need a bitmap: the card that goes out
// attached to a shared link, because no social platform renders SVG, and
// the iOS home screen icon, for the same reason.
//
// Both are generated from files in the repository rather than drawn by
// hand in an image editor, so the mark exists once and a change to it
// reaches everywhere.
//
//     npm install --no-save playwright
//     node scripts/make_images.mjs
//
// Playwright is not a dependency of the site. It is needed to regenerate
// these two files and nothing else, so it is installed for the run and
// left out of package.json.

import { mkdir } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { chromium } from 'playwright'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const out = join(root, 'frontend', 'public')

const browser = await chromium.launch()

try {
  await mkdir(out, { recursive: true })

  // The share card, at the size every platform crops from.
  const card = await browser.newPage({
    viewport: { width: 1200, height: 630 },
    deviceScaleFactor: 1,
  })
  await card.goto(pathToFileURL(join(root, 'docs', 'share-card.html')).href, {
    waitUntil: 'networkidle',
  })
  // The card is set in a web font. Screenshotting before it loads
  // silently produces a card in the fallback face, which looks like a
  // different product.
  await card.evaluate(() => document.fonts.ready)
  await card.screenshot({ path: join(out, 'share.png') })
  console.log('share.png        1200x630')

  // The home screen icon. iOS does not honour transparency and does not
  // read prefers-color-scheme, so this one is drawn on a solid dark
  // ground rather than left to the system.
  const icon = await browser.newPage({
    viewport: { width: 180, height: 180 },
    deviceScaleFactor: 1,
  })
  await icon.setContent(`
    <body style="margin:0;width:180px;height:180px;background:#11161d;
                 display:flex;align-items:center;justify-content:center">
      <svg width="124" height="124" viewBox="0 0 32 32">
        <path d="M 26.65 8.54 A 13 13 0 1 0 26.65 23.46" fill="none"
              stroke="#2a78d6" stroke-width="3.1" stroke-linecap="round"/>
        <path d="M 22.55 11.41 A 8 8 0 1 0 22.55 20.59" fill="none"
              stroke="#86b6ef" stroke-width="3.1" stroke-linecap="round"/>
        <circle cx="16" cy="16" r="3.4" fill="#eb6834"/>
      </svg>
    </body>
  `)
  await icon.screenshot({ path: join(out, 'apple-touch-icon.png') })
  console.log('apple-touch-icon.png  180x180')
} finally {
  await browser.close()
}
