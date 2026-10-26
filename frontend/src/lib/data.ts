// Loading the published data.
//
// Two tiers, which is the whole performance design. The first tier loads
// once: the polygons, the grid, the rents, the gazetteer. The second is one
// 548 byte file per workplace, fetched when the visitor changes where they
// work.
//
// The format version is checked rather than assumed. A site deployed from
// newer code than its data would otherwise read a journey time array
// against the wrong district order and draw a map that looked plausible and
// was wrong everywhere.

import { rewindCollection } from './geo'
import type { Cells, Dataset, DistrictCollection, Gazetteer, Meta, Place, Rents } from './types'

/** The format this code knows how to read. Must match export.py. */
export const SUPPORTED_FORMAT_VERSION = 1

const BASE = `${import.meta.env.BASE_URL}data`

export class DataError extends Error {}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}/${path}`)
  if (!response.ok) {
    throw new DataError(
      `Could not load ${path} (${response.status}). The site's data may not have been built yet.`,
    )
  }
  return (await response.json()) as T
}

export async function loadDataset(): Promise<Dataset> {
  const [meta, districts, boundary, cells, rents, gazetteer] = await Promise.all([
    getJson<Meta>('meta.json'),
    getJson<DistrictCollection>('districts.geojson'),
    getJson<GeoJSON.FeatureCollection>('boundary.geojson'),
    getJson<Cells>('cells.json'),
    getJson<Rents>('rents.json'),
    getJson<Gazetteer>('gazetteer.json'),
  ])

  if (meta.format_version !== SUPPORTED_FORMAT_VERSION) {
    throw new DataError(
      `This site reads data format ${SUPPORTED_FORMAT_VERSION} but the published data is ` +
        `format ${meta.format_version}. Rebuild the data with scripts/build.py, or deploy ` +
        `the version of the site that goes with it.`,
    )
  }

  // The district order is the key to every journey time array. If the
  // polygons and the order disagree, the map colours the wrong districts,
  // and it does it silently.
  const districtIndex = new Map(meta.districts.map((code, i) => [code, i]))
  const missing = districts.features
    .map((f) => f.properties.district)
    .filter((code) => !districtIndex.has(code))
  if (missing.length > 0) {
    throw new DataError(
      `${missing.length} districts are drawn but absent from the published order ` +
        `(${missing.slice(0, 5).join(', ')}). The polygons and the journey times came from ` +
        `different builds.`,
    )
  }

  const places: Place[] = gazetteer.places.map(([name, kind, cell, lon, lat]) => ({
    name,
    kind,
    cell,
    lon,
    lat,
  }))

  // The files are RFC 7946, which winds exterior rings counter-clockwise.
  // d3-geo uses the opposite convention, and reads a counter-clockwise ring
  // as the whole sphere minus that shape. Turned round once here rather
  // than every time the map re-renders. See lib/geo.ts.
  return {
    meta,
    districts: rewindCollection(districts),
    boundary: rewindCollection(boundary),
    cells,
    rents,
    places,
    districtIndex,
  }
}

// ---------------------------------------------------------------------------
// Journey times
// ---------------------------------------------------------------------------

// Keyed by cell id. A visitor comparing two or three possible offices
// refetches nothing, and the cache is bounded by how many workplaces a
// person is willing to type.
const timesCache = new Map<string, Uint16Array>()

/**
 * Journey times from every district to one destination cell.
 *
 * The file is a bare array of little endian unsigned 16 bit integers, in the
 * district order published in meta.json. There is no header: the length is
 * the district count and the endianness is fixed, both stated in meta.json,
 * so a header would only be a second place for them to disagree.
 *
 * Read through a DataView rather than by pointing a Uint16Array at the
 * buffer. The latter would be shorter and would use the platform's own
 * endianness, which is little endian on every browser anybody will use this
 * on and would therefore work, right up until it did not.
 */
export async function loadTimes(cellId: string, districtCount: number): Promise<Uint16Array> {
  const cached = timesCache.get(cellId)
  if (cached) return cached

  const response = await fetch(`${BASE}/times/${cellId}.bin`)
  if (!response.ok) {
    throw new DataError(
      `No journey times for grid cell ${cellId} (${response.status}). ` +
        `The workplace may sit outside the area the data covers.`,
    )
  }

  const buffer = await response.arrayBuffer()
  const expected = districtCount * 2
  if (buffer.byteLength !== expected) {
    throw new DataError(
      `Journey times for ${cellId} are ${buffer.byteLength} bytes but ${expected} were ` +
        `expected for ${districtCount} districts. The data and the site are out of step.`,
    )
  }

  const view = new DataView(buffer)
  const minutes = new Uint16Array(districtCount)
  for (let i = 0; i < districtCount; i++) {
    minutes[i] = view.getUint16(i * 2, true)
  }

  timesCache.set(cellId, minutes)
  return minutes
}

/** Only for tests, which must not inherit another test's cache. */
export function clearTimesCache(): void {
  timesCache.clear()
}
