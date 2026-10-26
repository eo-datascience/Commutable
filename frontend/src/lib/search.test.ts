import { describe, expect, it } from 'vitest'

import { looksLikePostcode, nearestCell, searchPlaces } from './search'
import type { Cells, Place } from './types'

const PLACES: Place[] = [
  { name: "King's Cross St Pancras", kind: 'station', cell: '000001', lon: -0.124, lat: 51.53 },
  { name: 'Kingsbury', kind: 'station', cell: '000002', lon: -0.279, lat: 51.584 },
  { name: 'Barking', kind: 'station', cell: '000003', lon: 0.081, lat: 51.539 },
  { name: 'Bank', kind: 'station', cell: '000004', lon: -0.089, lat: 51.513 },
  { name: 'Bank of England Museum', kind: 'station', cell: '000005', lon: -0.088, lat: 51.514 },
  { name: 'Richmond', kind: 'station', cell: '000006', lon: -0.301, lat: 51.463 },
  { name: 'Richmond upon Thames', kind: 'borough', cell: '000007', lon: -0.32, lat: 51.45 },
  { name: 'E1', kind: 'district', cell: '000008', lon: -0.06, lat: 51.516 },
  { name: 'E14', kind: 'district', cell: '000009', lon: -0.018, lat: 51.505 },
  { name: 'Camden', kind: 'borough', cell: '000010', lon: -0.15, lat: 51.54 },
]

describe('searchPlaces', () => {
  it('has nothing to offer on an empty query', () => {
    expect(searchPlaces(PLACES, '')).toEqual([])
    expect(searchPlaces(PLACES, '   ')).toEqual([])
  })

  it('puts a prefix match above a match in the middle', () => {
    const names = searchPlaces(PLACES, 'king').map((p) => p.name)

    expect(names.indexOf("King's Cross St Pancras")).toBeLessThan(names.indexOf('Barking'))
    expect(names.indexOf('Kingsbury')).toBeLessThan(names.indexOf('Barking'))
  })

  it('prefers the shorter name when both start the same way', () => {
    expect(searchPlaces(PLACES, 'bank')[0]?.name).toBe('Bank')
  })

  it('prefers a station to a borough of the same name', () => {
    // Somebody typing "Richmond" means the station they get off at.
    expect(searchPlaces(PLACES, 'richmond')[0]?.kind).toBe('station')
  })

  it('matches the start of a word inside a name', () => {
    expect(searchPlaces(PLACES, 'cross').map((p) => p.name)).toContain("King's Cross St Pancras")
  })

  it('ignores case', () => {
    expect(searchPlaces(PLACES, 'CAMDEN')[0]?.name).toBe('Camden')
    expect(searchPlaces(PLACES, 'camden')[0]?.name).toBe('Camden')
  })

  it('finds a postcode district typed directly', () => {
    expect(searchPlaces(PLACES, 'E14')[0]?.name).toBe('E14')
    // E1 is a prefix of E14, and the shorter exact match wins.
    expect(searchPlaces(PLACES, 'E1')[0]?.name).toBe('E1')
  })

  it('returns nothing for a name that is not there', () => {
    expect(searchPlaces(PLACES, 'Aberdeen')).toEqual([])
  })

  it('honours the limit', () => {
    expect(searchPlaces(PLACES, 'a', 3)).toHaveLength(3)
  })

  it('is deterministic', () => {
    expect(searchPlaces(PLACES, 'b').map((p) => p.name)).toEqual(
      searchPlaces(PLACES, 'b').map((p) => p.name),
    )
  })
})

describe('looksLikePostcode', () => {
  it.each(['SE10 8EW', 'se10 8ew', 'SE108EW', 'E1 6AN', 'W1A 1AA', 'EC2R 8AH'])(
    'recognises %s',
    (text) => {
      expect(looksLikePostcode(text)).toBe(true)
    },
  )

  it.each(['SE10', 'E14', 'Canary Wharf', '', 'SW1', '12345'])(
    'does not mistake %s for a full postcode',
    (text) => {
      expect(looksLikePostcode(text)).toBe(false)
    },
  )
})

describe('nearestCell', () => {
  const cells: Cells = {
    cell_metres: 750,
    ids: ['000001', '000002', '000003'],
    lon: [-0.1246, -0.0194, -0.3012],
    lat: [51.5074, 51.5054, 51.4633],
  }

  it('finds the closest cell', () => {
    expect(nearestCell(cells, -0.125, 51.508)?.cell).toBe('000001')
    expect(nearestCell(cells, -0.02, 51.506)?.cell).toBe('000002')
  })

  it('reports how far away it is, in kilometres', () => {
    const result = nearestCell(cells, -0.1246, 51.5074)
    expect(result?.km).toBeCloseTo(0, 3)

    // Roughly 7.3km from Charing Cross to Canary Wharf.
    const far = nearestCell(cells, -0.1246, 51.5074)
    expect(far?.km).toBeLessThan(0.1)
  })

  it('measures longitude at the right scale for the latitude', () => {
    // A degree of longitude in London is about 62% of a degree of latitude.
    // Treating them as equal would pick the wrong cell near the midpoint.
    const twoCells: Cells = {
      cell_metres: 750,
      ids: ['east', 'north'],
      lon: [0.0, -0.1246],
      lat: [51.5074, 51.59],
    }
    // 0.1 degrees east of Charing Cross is about 6.9km; 0.05 north is 5.6km.
    const result = nearestCell(twoCells, -0.1246, 51.5574)
    expect(result?.cell).toBe('north')
  })

  it('has nothing to return when there are no cells', () => {
    expect(nearestCell({ cell_metres: 750, ids: [], lon: [], lat: [] }, 0, 51.5)).toBeNull()
  })

  it('still answers for a point far outside, so the caller can reject it', () => {
    const result = nearestCell(cells, -4.25, 55.86) // Glasgow
    expect(result).not.toBeNull()
    expect(result!.km).toBeGreaterThan(500)
  })
})
