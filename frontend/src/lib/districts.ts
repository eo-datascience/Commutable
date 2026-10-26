// Putting a place name next to a postcode district.
//
// The map was labelled in codes alone until somebody who has lived in
// London for years pointed out that he could read about six of them. A
// district code is an address. It identifies the data and it is what the
// rents are published against, so it cannot be dropped, but on its own it
// makes the reader translate before they can read, and most readers
// cannot.
//
// So the code stays and the name joins it. The name is published in
// meta.json, which means a city without one still works: everything here
// falls back to the bare code rather than to an empty string.

import type { Meta } from './types'

/** The district's place name, or null if the published data has none. */
export function districtName(meta: Meta, district: string): string | null {
  return meta.district_names?.[district] ?? null
}

/**
 * Code and name together, for a single line of text.
 *
 * "E11 Leytonstone" rather than "Leytonstone (E11)": the code is the
 * stable identifier and the thing a reader scans a list for, so it leads.
 */
export function districtLabel(meta: Meta, district: string): string {
  const name = districtName(meta, district)
  return name === null ? district : `${district} ${name}`
}
