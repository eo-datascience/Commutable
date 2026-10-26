// Turning the downloaded arrays into the answer on screen.
//
// This is the only place the three inputs meet: journey times from the
// binary file, rents from rents.json, and what the visitor asked for. The
// map, the panel and the ranked list all read the same results, so they
// cannot disagree with each other.

import { shareUnder, type RentFigures } from './affordability'
import type { Dataset, DistrictResult, Query, RentRow } from './types'

/** The published row as the affordability functions want it. */
export function toFigures(row: RentRow): RentFigures {
  return {
    median: row[0],
    lowerQuartile: row[1],
    upperQuartile: row[2],
    sample: row[3],
    mu: row[4],
    sigma: row[5],
    wellFitted: row[6] === 1,
  }
}

/**
 * The worse of two journeys, which is the one that decides a household.
 *
 * A district works for a couple only if it works for both of them, so the
 * binding constraint is whoever has the longer trip. Averaging would offer
 * up places that are forty minutes for one person and ninety for the other
 * and call them fine.
 *
 * Unreachable for either is unreachable for the household.
 */
export function combineJourneys(times: (number | null)[]): number | null {
  if (times.length === 0) return null
  let worst = 0
  for (const time of times) {
    if (time === null) return null
    worst = Math.max(worst, time)
  }
  return worst
}

export interface ResultsInput {
  dataset: Dataset
  query: Query
  /** One array per chosen workplace, in the same order. */
  timeArrays: Uint16Array[]
}

/**
 * One result per district, in the published district order.
 *
 * Districts with no rent data for the chosen bedroom count still appear,
 * with a null share. They are drawn as "not enough data" rather than
 * omitted, because a hole in the map with no explanation reads as an error
 * in the site rather than a gap in the statistics.
 */
export function computeResults({ dataset, query, timeArrays }: ResultsInput): DistrictResult[] {
  const { meta, rents } = dataset
  const unreachable = meta.times.unreachable
  const byDistrict = rents.categories[query.bedrooms] ?? {}

  return meta.districts.map((district, index) => {
    const minutesEach = timeArrays.map((array) => {
      const value = array[index]
      return value === undefined || value === unreachable ? null : value
    })
    const minutes = combineJourneys(minutesEach)

    const row = byDistrict[district] ?? null
    const share = row === null ? null : shareUnder(toFigures(row), query.budget)

    const withinLimit = minutes !== null && minutes <= query.maxMinutes

    return {
      district,
      minutes,
      minutesEach,
      share,
      rent: row,
      inPlay: withinLimit && share !== null,
    }
  })
}

export interface Ranked extends DistrictResult {
  share: number
  minutes: number
  rent: RentRow
}

/**
 * Below this share, a district is not an option.
 *
 * At under one per cent the fitted curve is describing its own tail rather
 * than a market anybody can shop in. The threshold lives here, applied
 * once, because it was applied in two places before: the headline counted
 * districts above it and the list below the headline did not, so the page
 * said "7 districts work" above a list of eight, the last of them at 0%,
 * under a heading reading "Most choice within your budget".
 */
export const SLIVER = 0.01

/**
 * The districts worth looking at, best first.
 *
 * Ranked by how much of the market the budget reaches, because that is the
 * question the visitor asked. Journey time is a filter rather than part of
 * the score: a district inside the limit is acceptable, and being eight
 * minutes closer does not make it a better answer than one with twice the
 * choice of homes.
 *
 * Ties break on the shorter journey, then on the district code, so the
 * order is stable between renders and between visitors.
 */
export function rankDistricts(results: DistrictResult[], limit = 12): Ranked[] {
  const inPlay = results.filter(
    (r): r is Ranked =>
      r.inPlay && r.share !== null && r.minutes !== null && r.rent !== null && r.share >= SLIVER,
  )

  // Compared at the precision the site shows, not at full precision.
  //
  // Two districts both displayed as 61% can differ in the ninth decimal,
  // and sorting on that puts the slower one first for a reason the visitor
  // cannot see. Rounding first means the list reads correctly: equal
  // shares, nearest first.
  const shown = (share: number) => Math.round(share * 100)

  inPlay.sort((a, b) => {
    if (shown(b.share) !== shown(a.share)) return shown(b.share) - shown(a.share)
    if (a.minutes !== b.minutes) return a.minutes - b.minutes
    return a.district.localeCompare(b.district)
  })

  return inPlay.slice(0, limit)
}

export interface Summary {
  /** Districts inside the commute limit, whether or not they have rent data. */
  withinLimit: number
  /** Of those, how many have rent figures for the chosen bedroom count. */
  withData: number
  /** Of those, how many the budget reaches more than a sliver of. */
  worthLooking: number
  /** The district with the most choice inside the limit. */
  best: Ranked | null
  /** The closest district inside the limit that the budget reaches. */
  nearest: Ranked | null
  /**
   * The cheapest median inside the commute limit.
   *
   * Shown only when the budget reaches almost nothing anywhere, because
   * "nothing works" is a worse answer than "the cheapest district inside
   * your limit has a median of £1,850". Null the rest of the time.
   */
  cheapestMedian: { district: string; median: number; minutes: number } | null
}

/**
 * The one line answer, and the numbers behind it.
 *
 * The three counts narrow in sequence: inside the commute limit, then with
 * rent figures published, then with something the budget actually reaches.
 * Showing all three means a disappointing answer can say which stage it
 * fell at, which is the difference between "nowhere works" and "nowhere
 * within 30 minutes has published figures for a 4 bedroom house".
 */
export function summarise(
  results: DistrictResult[],
  ranked: Ranked[],
  maxMinutes: number,
): Summary {
  const withinLimit = results.filter((r) => r.minutes !== null && r.minutes <= maxMinutes)
  const withData = withinLimit.filter((r) => r.rent !== null)

  // Already filtered: rankDistricts drops anything below SLIVER, so the
  // count here and the list on screen are the same districts by
  // construction rather than by two filters agreeing.
  const nearest = [...ranked].sort((a, b) => a.minutes - b.minutes)[0] ?? null

  let cheapestMedian: Summary['cheapestMedian'] = null
  if (ranked.length === 0 && withData.length > 0) {
    const cheapest = [...withData].sort(
      (a, b) => (a.rent?.[0] ?? Infinity) - (b.rent?.[0] ?? Infinity),
    )[0]
    if (cheapest?.rent && cheapest.minutes !== null) {
      cheapestMedian = {
        district: cheapest.district,
        median: cheapest.rent[0],
        minutes: cheapest.minutes,
      }
    }
  }

  return {
    withinLimit: withinLimit.length,
    withData: withData.length,
    worthLooking: ranked.length,
    best: ranked[0] ?? null,
    nearest,
    cheapestMedian,
  }
}
