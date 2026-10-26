import { describe, expect, it } from 'vitest'

// Vite's raw import rather than node:fs, so this needs no Node types and
// the tsconfig can keep excluding them.
import CSS from '../styles.css?raw'
import { GREY, RAMP_DARK, RAMP_LIGHT, TIME_RAMP_DARK, TIME_RAMP_LIGHT } from './scale'

// The palette exists twice and has to. The map paints SVG paths, so its
// fills are set in JavaScript from scale.ts. The swatches in the legend and
// the ranked list are DOM elements, so theirs come from CSS custom
// properties that follow the theme without a re-render.
//
// Nothing in the type system connects the two. If one is edited and the
// other is not, the key stops describing the map: a district drawn in the
// second step of the ramp would sit beside a legend swatch of a different
// colour, and the page would be quietly lying about its own data. That is
// invisible in a screenshot and invisible in a unit test of either file, so
// it is asserted here.

/** The custom properties declared in one selector's block. */
function variablesIn(selector: string): Record<string, string> {
  const start = CSS.indexOf(selector)
  expect(start, `${selector} should be in styles.css`).toBeGreaterThan(-1)

  const open = CSS.indexOf('{', start)
  const close = CSS.indexOf('}', open)
  const block = CSS.slice(open + 1, close)

  const found: Record<string, string> = {}
  for (const match of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    const name = match[1]
    const value = match[2]
    if (name !== undefined && value !== undefined) found[name] = value.trim().toLowerCase()
  }
  return found
}

const LIGHT = variablesIn(':root {')
const DARK = variablesIn(":root[data-theme='dark']")

describe('the five affordability steps', () => {
  it('match the light ramp the map paints with', () => {
    expect(RAMP_LIGHT.map((_, i) => LIGHT[`--bin-${i}`])).toEqual(
      RAMP_LIGHT.map((c) => c.toLowerCase()),
    )
  })

  it('match the dark ramp the map paints with', () => {
    expect(RAMP_DARK.map((_, i) => DARK[`--bin-${i}`])).toEqual(
      RAMP_DARK.map((c) => c.toLowerCase()),
    )
  })
})

describe('the five journey-time steps', () => {
  it('match the light ramp the map paints with', () => {
    expect(TIME_RAMP_LIGHT.map((_, i) => LIGHT[`--time-${i}`])).toEqual(
      TIME_RAMP_LIGHT.map((c) => c.toLowerCase()),
    )
  })

  it('match the dark ramp the map paints with', () => {
    expect(TIME_RAMP_DARK.map((_, i) => DARK[`--time-${i}`])).toEqual(
      TIME_RAMP_DARK.map((c) => c.toLowerCase()),
    )
  })

  it('are a different hue from the affordability ramp', () => {
    // Two views that differ only in which blue would look like the same
    // map, and somebody who missed the switch would read minutes as money.
    const shared = RAMP_LIGHT.filter((c) => (TIME_RAMP_LIGHT as readonly string[]).includes(c))
    expect(shared).toEqual([])
  })
})

describe('the three states that are not a share', () => {
  it('match in light mode', () => {
    expect(LIGHT['--out']).toBe(GREY.light.tooFar.toLowerCase())
    expect(LIGHT['--waiting']).toBe(GREY.light.waiting.toLowerCase())
    expect(LIGHT['--nodata']).toBe(GREY.light.noData.toLowerCase())
  })

  it('match in dark mode', () => {
    expect(DARK['--out']).toBe(GREY.dark.tooFar.toLowerCase())
    expect(DARK['--waiting']).toBe(GREY.dark.waiting.toLowerCase())
    expect(DARK['--nodata']).toBe(GREY.dark.noData.toLowerCase())
  })
})

describe('the ramps themselves', () => {
  // Five steps that a visitor is asked to tell apart. Two identical ones
  // would make two different answers look like the same answer.
  it('have five distinct steps each', () => {
    for (const ramp of [RAMP_LIGHT, RAMP_DARK, TIME_RAMP_LIGHT, TIME_RAMP_DARK]) {
      expect(new Set(ramp).size).toBe(5)
    }
  })

  it('run light to dark, and dark to light, in the right direction', () => {
    const luminance = (hex: string) => {
      const n = Number.parseInt(hex.slice(1), 16)
      // Rough relative brightness is enough here: the assertion is about
      // ordering, not about contrast ratios.
      return 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)
    }

    // On a pale page more of the market reads as darker ink.
    const light = RAMP_LIGHT.map(luminance)
    expect(light).toEqual([...light].sort((a, b) => b - a))

    // On a dark page the eye reads brighter as more, which is why this is a
    // separate list rather than the first one reversed.
    const dark = RAMP_DARK.map(luminance)
    expect(dark).toEqual([...dark].sort((a, b) => a - b))

    // The time ramps run the other way round, because for a journey less
    // is better. Both ramps therefore put the strongest colour on the
    // better answer, which is the thing a reader actually learns once.
    const timeLight = TIME_RAMP_LIGHT.map(luminance)
    expect(timeLight).toEqual([...timeLight].sort((a, b) => a - b))

    const timeDark = TIME_RAMP_DARK.map(luminance)
    expect(timeDark).toEqual([...timeDark].sort((a, b) => b - a))
  })

  it('keep every step clear of the surface it is painted on', () => {
    // The pale end of a ramp is where this goes wrong: a step that sits
    // too close to the page reads as "no data" rather than as "a little".
    // The blue ramp's weakest step is the standard the orange one was
    // built to, so the floor is stated rather than left to judgement.
    const contrast = (a: string, b: string) => {
      const channel = (hex: string, at: number) => {
        const c = Number.parseInt(hex.slice(at, at + 2), 16) / 255
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
      }
      const lum = (hex: string) =>
        0.2126 * channel(hex, 1) + 0.7152 * channel(hex, 3) + 0.0722 * channel(hex, 5)
      const [x, y] = [lum(a), lum(b)]
      return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
    }

    const FLOOR = 2.1
    for (const colour of [...RAMP_LIGHT, ...TIME_RAMP_LIGHT]) {
      expect(contrast(colour, LIGHT['--surface'] ?? '#ffffff')).toBeGreaterThan(FLOOR)
    }
    for (const colour of [...RAMP_DARK, ...TIME_RAMP_DARK]) {
      expect(contrast(colour, DARK['--surface'] ?? '#000000')).toBeGreaterThan(FLOOR)
    }
  })
})
