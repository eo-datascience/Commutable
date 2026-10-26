import { describe, expect, it } from 'vitest'

import { isClockwise, rewindCollection, rewindGeometry, signedArea } from './geo'

// A unit square, counter-clockwise in longitude and latitude.
const CCW = [
  [0, 0],
  [1, 0],
  [1, 1],
  [0, 1],
  [0, 0],
]
const CW = [...CCW].reverse()

describe('winding', () => {
  it('tells the two directions apart', () => {
    expect(isClockwise(CW)).toBe(true)
    expect(isClockwise(CCW)).toBe(false)
  })

  it('gives opposite signs for the two directions', () => {
    expect(signedArea(CW)).toBeCloseTo(-signedArea(CCW), 12)
  })

  it('is unmoved by where the ring starts', () => {
    const rotated = [...CCW.slice(1, -1), CCW[0]!, CCW[1]!]
    expect(isClockwise(rotated)).toBe(false)
  })
})

describe('rewindGeometry', () => {
  it('turns a counter-clockwise exterior ring clockwise for d3', () => {
    const out = rewindGeometry({ type: 'Polygon', coordinates: [CCW] })
    expect(isClockwise(out.coordinates[0]!)).toBe(true)
  })

  it('leaves a ring that is already clockwise alone', () => {
    const out = rewindGeometry({ type: 'Polygon', coordinates: [CW] })
    expect(out.coordinates[0]).toEqual(CW)
  })

  it('winds holes the opposite way to the exterior', () => {
    const hole = [
      [0.2, 0.2],
      [0.4, 0.2],
      [0.4, 0.4],
      [0.2, 0.4],
      [0.2, 0.2],
    ]
    const out = rewindGeometry({ type: 'Polygon', coordinates: [CCW, hole] })

    expect(isClockwise(out.coordinates[0]!)).toBe(true)
    expect(isClockwise(out.coordinates[1]!)).toBe(false)
  })

  it('handles every part of a multipolygon', () => {
    const out = rewindGeometry({
      type: 'MultiPolygon',
      coordinates: [[CCW], [CW]],
    })
    for (const polygon of out.coordinates as number[][][][]) {
      expect(isClockwise(polygon[0]!)).toBe(true)
    }
  })

  it('leaves a geometry it does not understand untouched', () => {
    const line = { type: 'LineString', coordinates: CCW }
    expect(rewindGeometry(line)).toEqual(line)
  })

  it('does not modify its input', () => {
    const original = { type: 'Polygon', coordinates: [CCW] }
    const before = JSON.stringify(original)

    rewindGeometry(original)

    expect(JSON.stringify(original)).toBe(before)
  })
})

describe('rewindCollection', () => {
  it('rewinds every feature', () => {
    const collection = {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', properties: { district: 'A' }, geometry: { type: 'Polygon', coordinates: [CCW] } },
        { type: 'Feature', properties: { district: 'B' }, geometry: { type: 'Polygon', coordinates: [CCW] } },
      ],
    }

    const out = rewindCollection(collection)

    for (const feature of out.features) {
      expect(isClockwise((feature.geometry.coordinates as number[][][])[0]!)).toBe(true)
    }
  })

  it('keeps the properties', () => {
    const collection = {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', properties: { district: 'SE10' }, geometry: { type: 'Polygon', coordinates: [CCW] } },
      ],
    }

    expect(rewindCollection(collection).features[0]?.properties).toEqual({ district: 'SE10' })
  })
})
