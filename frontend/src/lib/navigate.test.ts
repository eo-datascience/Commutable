import { describe, expect, it } from 'vitest'

import { ARROWS, nearestInDirection, type Point } from './navigate'

/**
 * A nine district grid, 100 apart, in SVG coordinates where y runs down.
 *
 *     NW  N  NE
 *     W   C  E
 *     SW  S  SE
 */
const GRID = new Map<string, Point>([
  ['NW', [0, 0]],
  ['N', [100, 0]],
  ['NE', [200, 0]],
  ['W', [0, 100]],
  ['C', [100, 100]],
  ['E', [200, 100]],
  ['SW', [0, 200]],
  ['S', [100, 200]],
  ['SE', [200, 200]],
])

const step = (from: string, key: string) =>
  nearestInDirection(GRID, from, ARROWS[key]?.[0] ?? 0, ARROWS[key]?.[1] ?? 0)

describe('arrow keys from the middle', () => {
  it('go where the key points', () => {
    expect(step('C', 'ArrowLeft')).toBe('W')
    expect(step('C', 'ArrowRight')).toBe('E')
    expect(step('C', 'ArrowUp')).toBe('N')
    expect(step('C', 'ArrowDown')).toBe('S')
  })
})

describe('at the edge', () => {
  it('gives null rather than wrapping round', () => {
    // Wrapping would teleport you across the city for a key press that
    // looks like a nudge.
    expect(step('W', 'ArrowLeft')).toBeNull()
    expect(step('N', 'ArrowUp')).toBeNull()
    expect(step('SE', 'ArrowDown')).toBeNull()
    expect(step('SE', 'ArrowRight')).toBeNull()
  })

  it('still moves along the edge', () => {
    expect(step('NW', 'ArrowRight')).toBe('N')
    expect(step('NW', 'ArrowDown')).toBe('W')
  })
})

describe('the cone', () => {
  // The reason this is not simply "the nearest point with a greater x".
  it('does not let a sideways neighbour win a forward press', () => {
    const points = new Map<string, Point>([
      ['from', [0, 0]],
      // Barely to the right but mostly above: closer, and not what the
      // right arrow appears to promise.
      ['above', [10, -200]],
      ['right', [300, 0]],
    ])

    expect(nearestInDirection(points, 'from', 1, 0)).toBe('right')
  })

  it('accepts a diagonal that leans the right way', () => {
    const points = new Map<string, Point>([
      ['from', [0, 0]],
      ['leaning', [100, 60]],
    ])

    expect(nearestInDirection(points, 'from', 1, 0)).toBe('leaning')
  })

  it('rejects a perfect diagonal, which leans neither way', () => {
    // On the cone's own boundary. Excluded rather than included so that
    // pressing right and then left returns you to where you started.
    const points = new Map<string, Point>([
      ['from', [0, 0]],
      ['corner', [100, 100.0001]],
    ])

    expect(nearestInDirection(points, 'from', 1, 0)).toBeNull()
  })
})

describe('bad input', () => {
  it('gives null for a district that is not on the map', () => {
    expect(nearestInDirection(GRID, 'ZZ9', 1, 0)).toBeNull()
  })

  it('ignores a centroid that could not be computed', () => {
    // d3 returns NaN for a degenerate ring, and a NaN centroid compared
    // with < is always false, which would silently make that district
    // unreachable rather than skipped.
    const points = new Map<string, Point>([
      ['from', [0, 0]],
      ['broken', [NaN, NaN]],
      ['real', [100, 0]],
    ])

    expect(nearestInDirection(points, 'from', 1, 0)).toBe('real')
    expect(nearestInDirection(points, 'broken', 1, 0)).toBeNull()
  })

  it('never returns the district it started from', () => {
    for (const key of Object.keys(ARROWS)) {
      for (const from of GRID.keys()) {
        expect(step(from, key)).not.toBe(from)
      }
    }
  })
})

describe('moving and coming back', () => {
  it('returns to where it started', () => {
    // The property that makes the keys feel like a map rather than a
    // list: left then right is where you were.
    const opposite: Record<string, string> = {
      ArrowLeft: 'ArrowRight',
      ArrowRight: 'ArrowLeft',
      ArrowUp: 'ArrowDown',
      ArrowDown: 'ArrowUp',
    }

    for (const from of GRID.keys()) {
      for (const [key, back] of Object.entries(opposite)) {
        const there = step(from, key)
        if (there === null) continue
        expect(step(there, back)).toBe(from)
      }
    }
  })
})
