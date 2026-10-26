// Measure what the site actually costs to load.
//
// The README used to describe the payload in adjectives. Adjectives rot:
// "small" survives a dependency that doubles the bundle, and nobody
// notices. These are the numbers instead, printed as the table the README
// carries, so the claim can be re-checked rather than believed.
//
//     cd frontend && npm run build && cd ..
//     node scripts/measure.mjs
//
// Gzip at its default level, which is what Vite's own build log reports,
// so the two agree. Netlify serves brotli, so the figures a visitor
// actually pays are smaller than these.

import { gzipSync } from 'node:zlib'
import { readdir, readFile, stat } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dist = join(root, 'frontend', 'dist')
const data = join(root, 'frontend', 'public', 'data')

// Decimal kB, which is what Vite, Lighthouse and the browser's network
// panel all report. Using 1024 here produced a README that disagreed with
// the build log about the size of the same file.
const kb = (bytes) => `${(bytes / 1000).toFixed(1)} kB`

async function sizes(path) {
  const body = await readFile(path)
  return { raw: body.length, gz: gzipSync(body).length }
}

async function total(paths) {
  let raw = 0
  let gz = 0
  for (const path of paths) {
    const one = await sizes(path)
    raw += one.raw
    gz += one.gz
  }
  return { raw, gz }
}

// ---------------------------------------------------------------- the app

const assets = join(dist, 'assets')
let app
try {
  const names = await readdir(assets)
  const js = names.filter((n) => n.endsWith('.js')).map((n) => join(assets, n))
  const css = names.filter((n) => n.endsWith('.css')).map((n) => join(assets, n))

  app = {
    html: await sizes(join(dist, 'index.html')),
    js: await total(js),
    css: await total(css),
  }
} catch {
  console.error('No build found. Run `npm run build` in frontend/ first.')
  process.exit(1)
}

// --------------------------------------------------------------- the data

// Everything the first paint needs. The journey times are not in here:
// they are fetched per workplace, which is the whole point of the format.
const FIRST_LOAD = [
  'meta.json',
  'districts.geojson',
  'boundary.geojson',
  'cells.json',
  'rents.json',
  'gazetteer.json',
]

const first = {}
for (const name of FIRST_LOAD) first[name] = await sizes(join(data, name))
const firstTotal = Object.values(first).reduce(
  (acc, one) => ({ raw: acc.raw + one.raw, gz: acc.gz + one.gz }),
  { raw: 0, gz: 0 },
)

const times = join(data, 'times')
const timeFiles = await readdir(times)
const oneAnswer = (await stat(join(times, timeFiles[0]))).size

// ----------------------------------------------------------------- report

console.log('\nThe app\n')
console.log(`  HTML            ${kb(app.html.raw).padStart(9)}   ${kb(app.html.gz).padStart(9)} gzipped`)
console.log(`  CSS             ${kb(app.css.raw).padStart(9)}   ${kb(app.css.gz).padStart(9)} gzipped`)
console.log(`  JavaScript      ${kb(app.js.raw).padStart(9)}   ${kb(app.js.gz).padStart(9)} gzipped`)

console.log('\nThe data the first paint needs\n')
for (const [name, one] of Object.entries(first)) {
  console.log(`  ${name.padEnd(18)}${kb(one.raw).padStart(9)}   ${kb(one.gz).padStart(9)} gzipped`)
}
console.log(`  ${'total'.padEnd(18)}${kb(firstTotal.raw).padStart(9)}   ${kb(firstTotal.gz).padStart(9)} gzipped`)

const loadGz = app.html.gz + app.css.gz + app.js.gz + firstTotal.gz
console.log(`\n  First load, everything, gzipped:  ${kb(loadGz)}`)

console.log('\nEvery answer after that\n')
console.log(`  one destination   ${oneAnswer} bytes, uncompressed`)
console.log(`  ${timeFiles.length.toLocaleString('en-GB')} of them, one per grid cell`)
console.log(
  `  changing the budget or the bedroom count costs nothing: it is the same file, re-read\n`,
)
