import type { View } from './scale'

// The shape of the published data, mirroring what pipeline/export.py writes.
//
// These are declarations of what the site expects rather than of what it
// receives. loadDataset checks the format version and the invariants that
// would otherwise fail later and further away.

export interface Meta {
  format_version: number
  built: string
  city: { id: string; name: string; timezone: string }
  /** The order every journey time array is indexed by. */
  districts: string[]
  districts_with_rent: string[]
  /**
   * District code to place name, as data/reference/<city>_district_names.json
   * holds it. Optional: a city that ships no names is published without
   * this key and the site falls back to showing bare codes.
   */
  district_names?: Record<string, string>
  bedroom_categories: string[]
  /**
   * A readable name per category, so the published dataset stands on its
   * own for anyone who downloads it. The site does not read this: it words
   * each size itself in lib/labels.ts, because a sentence needs two forms
   * of the label and a wording fix should not need a rebuild.
   */
  bedroom_labels: Record<string, string>
  grid: { cell_metres: number; cells: number }
  times: {
    encoding: string
    unreachable: number
    max_minutes: number
    max_walk_minutes: number
    departure_date: string
    departure_window: string
    statistic: string
    reachable_share: number
  }
  rent: {
    min_sample: number
    low_sample: number
    fitted: number
    poorly_fitted: number
    sigma_note: string
  }
  gazetteer: { places: number }
  data_vintages: Partial<Record<'rent' | 'timetable' | 'street_network' | 'boundaries', string>>
  attributions: { name: string; source: string; licence: string; url: string }[]
  limitations: string[]
  /** Set only by a synthetic build. Makes the site say every number is invented. */
  synthetic?: boolean
  synthetic_warning?: string
}

export interface Cells {
  cell_metres: number
  ids: string[]
  lon: number[]
  lat: number[]
}

/** One row of rents.json: the published figures plus the fitted parameters. */
export type RentRow = [
  median: number,
  lowerQuartile: number,
  upperQuartile: number,
  sample: number,
  mu: number,
  sigma: number,
  wellFitted: 0 | 1,
]

export interface Rents {
  fields: string[]
  note: string
  min_sample: number
  /** bedroom category -> district -> row */
  categories: Record<string, Record<string, RentRow>>
}

export type PlaceKind = 'station' | 'district' | 'borough' | 'postcode'

export interface Place {
  name: string
  kind: PlaceKind
  cell: string
  lon: number
  lat: number
}

export interface Gazetteer {
  fields: string[]
  places: [string, PlaceKind, string, number, number][]
}

export interface DistrictFeature {
  type: 'Feature'
  properties: { district: string; share_in_city: number }
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon
}

export interface DistrictCollection {
  type: 'FeatureCollection'
  features: DistrictFeature[]
}

/** Everything loaded once, on first paint. */
export interface Dataset {
  meta: Meta
  districts: DistrictCollection
  boundary: GeoJSON.FeatureCollection
  cells: Cells
  rents: Rents
  places: Place[]
  /** district code -> its position in meta.districts, built once. */
  districtIndex: Map<string, number>
}

/** What the visitor has asked for. Everything here lives in the URL. */
export interface Query {
  /** Grid cell of the first workplace, or null before one is chosen. */
  workplace: string | null
  /** An optional second workplace, for a partner or a second job. */
  workplace2: string | null
  /** Labels for the two workplaces, so a shared link reads as a place. */
  workplaceName: string | null
  workplaceName2: string | null
  maxMinutes: number
  budget: number
  bedrooms: string
  /** The district whose panel is open, if any. */
  selected: string | null
  /** What the map's colour means. Shared in the link like the rest. */
  view: View
}

/** One district, with everything the map and the panel need about it. */
export interface DistrictResult {
  district: string
  /** Minutes from this district to the workplace, or null if unreachable. */
  minutes: number | null
  /** Minutes to each workplace separately, when there are two. */
  minutesEach: (number | null)[]
  /** Share of this district's market under the budget, or null with no data. */
  share: number | null
  rent: RentRow | null
  /** Within the commute limit and has rent data. */
  inPlay: boolean
}
