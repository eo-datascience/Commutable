// Turning what the visitor types into a grid cell.
//
// Two sources, in this order.
//
// The gazetteer, shipped with the site, holds every station in the
// timetable, every postcode district and every borough. It answers
// instantly, works offline and needs no key. Almost everybody in London
// describes where they work by the station they get off at, so this covers
// most of what gets typed.
//
// postcodes.io answers a full postcode, which the gazetteer cannot: there
// are about 1.8 million of them and shipping that would dwarf everything
// else on the site. It is free, open and needs no key. It is a convenience
// on top of the gazetteer rather than a dependency: if it is down, the
// visitor types a station instead and the site does not notice.

import type { Cells, Place } from './types'

/** A full UK postcode, with or without the space. */
const FULL_POSTCODE = /^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$/i

const POSTCODES_IO = 'https://api.postcodes.io/postcodes'

export function looksLikePostcode(text: string): boolean {
  return FULL_POSTCODE.test(text.trim())
}

/**
 * Rank the gazetteer against what has been typed.
 *
 * A prefix match beats a word-start match beats a match anywhere, so typing
 * "king" puts King's Cross above Barking. Within a tier, a station beats a
 * district beats a borough, because somebody typing "Richmond" means the
 * station.
 */
export function searchPlaces(places: Place[], text: string, limit = 8): Place[] {
  const needle = text.trim().toLowerCase()
  if (needle.length === 0) return []

  const kindRank: Record<string, number> = { station: 0, district: 1, borough: 2, postcode: 3 }

  const scored: { place: Place; score: number }[] = []
  for (const place of places) {
    const name = place.name.toLowerCase()
    let tier: number

    if (name === needle) tier = 0
    else if (name.startsWith(needle)) tier = 1
    else if (wordStarts(name, needle)) tier = 2
    else if (name.includes(needle)) tier = 3
    else continue

    // Shorter names first within a tier, so "Bank" beats "Bank of England
    // Museum" and "E1" beats "E14" on an exact prefix.
    scored.push({
      place,
      score: tier * 1000 + (kindRank[place.kind] ?? 9) * 100 + Math.min(name.length, 99),
    })
  }

  scored.sort((a, b) => a.score - b.score || a.place.name.localeCompare(b.place.name))
  return scored.slice(0, limit).map((s) => s.place)
}

function wordStarts(haystack: string, needle: string): boolean {
  let from = 0
  for (;;) {
    const at = haystack.indexOf(needle, from)
    if (at === -1) return false
    if (at === 0 || /[\s'(,./-]/.test(haystack[at - 1] ?? '')) return true
    from = at + 1
  }
}

// ---------------------------------------------------------------------------
// Snapping a coordinate to a grid cell
// ---------------------------------------------------------------------------

/**
 * The grid cell nearest a longitude and latitude.
 *
 * A linear scan over about 2,900 cells, which at this size beats building
 * an index: the whole search is well under a millisecond and runs once per
 * postcode lookup.
 *
 * Distances are computed on an equirectangular approximation with the
 * longitude scaled by the cosine of the latitude. Over a city that is
 * accurate to a fraction of a per cent, and only the ordering matters. The
 * returned distance is in kilometres so the caller can reject a point that
 * is nowhere near the city.
 */
export function nearestCell(
  cells: Cells,
  lon: number,
  lat: number,
): { cell: string; km: number } | null {
  if (cells.ids.length === 0) return null

  const kmPerDegreeLat = 111.32
  const kmPerDegreeLon = kmPerDegreeLat * Math.cos((lat * Math.PI) / 180)

  let bestIndex = -1
  let bestSquared = Infinity

  for (let i = 0; i < cells.ids.length; i++) {
    const dx = ((cells.lon[i] ?? 0) - lon) * kmPerDegreeLon
    const dy = ((cells.lat[i] ?? 0) - lat) * kmPerDegreeLat
    const squared = dx * dx + dy * dy
    if (squared < bestSquared) {
      bestSquared = squared
      bestIndex = i
    }
  }

  const id = cells.ids[bestIndex]
  if (id === undefined) return null
  return { cell: id, km: Math.sqrt(bestSquared) }
}

/**
 * A workplace further than this from any grid cell is not in the city.
 *
 * Two kilometres is about three grid cells. Beyond that the nearest cell's
 * journey times describe somewhere else, and offering them would be worse
 * than saying no.
 */
export const MAX_SNAP_KM = 2

export class LookupError extends Error {}

/** Look a full postcode up and snap it to a grid cell. */
export async function lookupPostcode(
  cells: Cells,
  postcode: string,
): Promise<{ place: Place; km: number }> {
  const tidy = postcode.trim().toUpperCase()

  let response: Response
  try {
    response = await fetch(`${POSTCODES_IO}/${encodeURIComponent(tidy)}`)
  } catch {
    throw new LookupError(
      'Could not reach the postcode service. Try a station or a postcode district instead.',
    )
  }

  if (response.status === 404) {
    throw new LookupError(`${tidy} is not a postcode we can find. Check it and try again.`)
  }
  if (!response.ok) {
    throw new LookupError(
      'The postcode service is not responding. Try a station or a postcode district instead.',
    )
  }

  const body = (await response.json()) as {
    result?: { longitude: number | null; latitude: number | null; postcode: string }
  }
  const result = body.result
  if (!result || result.longitude === null || result.latitude === null) {
    throw new LookupError(`${tidy} has no location on record.`)
  }

  const snapped = nearestCell(cells, result.longitude, result.latitude)
  if (snapped === null || snapped.km > MAX_SNAP_KM) {
    throw new LookupError(
      `${result.postcode} is outside the area this map covers. It only covers Greater London.`,
    )
  }

  return {
    place: {
      name: result.postcode,
      kind: 'postcode',
      cell: snapped.cell,
      lon: result.longitude,
      lat: result.latitude,
    },
    km: snapped.km,
  }
}
