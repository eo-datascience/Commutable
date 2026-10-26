import { describe, expect, it } from 'vitest'

import { combineJourneys, computeResults, rankDistricts, summarise, toFigures } from './results'
import type { Dataset, Meta, Query, RentRow } from './types'

const UNREACHABLE = 65535

/** A lognormal with a given median and spread, as rents.json would hold it. */
function row(median: number, sigma = 0.22, sample = 400): RentRow {
  const z = 0.6744897501960817
  const mu = Math.log(median)
  return [
    median,
    Math.round(Math.exp(mu - sigma * z)),
    Math.round(Math.exp(mu + sigma * z)),
    sample,
    mu,
    sigma,
    1,
  ]
}

function dataset(districts: string[], rents: Record<string, RentRow>): Dataset {
  const meta = {
    districts,
    times: { unreachable: UNREACHABLE },
  } as unknown as Meta

  return {
    meta,
    districts: { type: 'FeatureCollection', features: [] },
    boundary: { type: 'FeatureCollection', features: [] },
    cells: { cell_metres: 750, ids: [], lon: [], lat: [] },
    rents: { fields: [], note: '', min_sample: 30, categories: { '1': rents } },
    places: [],
    districtIndex: new Map(districts.map((d, i) => [d, i])),
  } as unknown as Dataset
}

const QUERY = {
  workplace: '000000',
  workplace2: null,
  workplaceName: null,
  workplaceName2: null,
  maxMinutes: 45,
  budget: 1600,
  bedrooms: '1',
  selected: null,
  view: 'budget',
} satisfies Query

// ---------------------------------------------------------------------------
// Two workplaces
// ---------------------------------------------------------------------------

describe('combineJourneys', () => {
  it('takes the worse of two journeys', () => {
    // A district works for a couple only if it works for both of them.
    expect(combineJourneys([20, 50])).toBe(50)
    expect(combineJourneys([50, 20])).toBe(50)
  })

  it('treats unreachable for one person as unreachable for the household', () => {
    expect(combineJourneys([15, null])).toBeNull()
    expect(combineJourneys([null, 15])).toBeNull()
  })

  it('passes a single journey through', () => {
    expect(combineJourneys([32])).toBe(32)
  })

  it('has nothing to say about no workplaces', () => {
    expect(combineJourneys([])).toBeNull()
  })

  it('never averages', () => {
    // The mistake worth guarding against: a mean would offer up a district
    // that is 40 minutes for one person and 90 for the other as though it
    // were 65 minutes for both, which is true of nobody.
    expect(combineJourneys([40, 90])).toBe(90)
  })
})

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

describe('computeResults', () => {
  const data = dataset(['A1', 'A2', 'A3'], { A1: row(1400), A2: row(2600), A3: row(1200) })

  it('returns one result per district, in the published order', () => {
    const results = computeResults({
      dataset: data,
      query: QUERY,
      timeArrays: [new Uint16Array([20, 30, 40])],
    })

    expect(results.map((r) => r.district)).toEqual(['A1', 'A2', 'A3'])
  })

  it('turns the sentinel into no journey rather than a very long one', () => {
    const results = computeResults({
      dataset: data,
      query: QUERY,
      timeArrays: [new Uint16Array([20, UNREACHABLE, 40])],
    })

    expect(results[1]?.minutes).toBeNull()
    expect(results[1]?.inPlay).toBe(false)
  })

  it('takes the worse journey when there are two workplaces', () => {
    const results = computeResults({
      dataset: data,
      query: QUERY,
      timeArrays: [new Uint16Array([20, 30, 40]), new Uint16Array([50, 10, 10])],
    })

    expect(results.map((r) => r.minutes)).toEqual([50, 30, 40])
    expect(results[0]?.minutesEach).toEqual([20, 50])
  })

  it('puts a district beyond the limit out of play but keeps its journey', () => {
    const results = computeResults({
      dataset: data,
      query: { ...QUERY, maxMinutes: 25 },
      timeArrays: [new Uint16Array([20, 30, 40])],
    })

    expect(results[0]?.inPlay).toBe(true)
    expect(results[1]?.inPlay).toBe(false)
    expect(results[1]?.minutes).toBe(30)
  })

  it('keeps districts with no rent figures, with a null share', () => {
    // Omitting them would leave a hole in the map with no explanation,
    // which reads as a fault in the site rather than a gap in the data.
    const sparse = dataset(['A1', 'A2'], { A1: row(1400) })
    const results = computeResults({
      dataset: sparse,
      query: QUERY,
      timeArrays: [new Uint16Array([20, 25])],
    })

    expect(results[1]?.share).toBeNull()
    expect(results[1]?.rent).toBeNull()
    expect(results[1]?.inPlay).toBe(false)
    expect(results[1]?.minutes).toBe(25)
  })

  it('gives a cheaper district a larger share of the market', () => {
    const results = computeResults({
      dataset: data,
      query: QUERY,
      timeArrays: [new Uint16Array([20, 20, 20])],
    })

    expect(results[2]!.share!).toBeGreaterThan(results[0]!.share!)
    expect(results[0]!.share!).toBeGreaterThan(results[1]!.share!)
  })

  it('returns nothing for a bedroom category with no data at all', () => {
    const results = computeResults({
      dataset: data,
      query: { ...QUERY, bedrooms: '4+' },
      timeArrays: [new Uint16Array([20, 30, 40])],
    })

    expect(results.every((r) => r.share === null)).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Ranking
// ---------------------------------------------------------------------------

describe('rankDistricts', () => {
  it('puts the most choice first', () => {
    const data = dataset(['A1', 'A2', 'A3'], { A1: row(1400), A2: row(2600), A3: row(1200) })
    const ranked = rankDistricts(
      computeResults({ dataset: data, query: QUERY, timeArrays: [new Uint16Array([20, 20, 20])] }),
    )

    expect(ranked.map((r) => r.district)).toEqual(['A3', 'A1', 'A2'])
  })

  it('breaks a tie at the shown precision on the shorter journey', () => {
    // Two districts both displayed as the same percentage can differ in the
    // ninth decimal. Sorting on that puts the slower one first for a reason
    // nobody can see on screen.
    const data = dataset(['FAR', 'NEAR'], { FAR: row(900, 0.2001), NEAR: row(900, 0.2) })
    const ranked = rankDistricts(
      computeResults({ dataset: data, query: QUERY, timeArrays: [new Uint16Array([40, 15])] }),
    )

    expect(ranked.map((r) => r.district)).toEqual(['NEAR', 'FAR'])
    expect(Math.round(ranked[0]!.share * 100)).toBe(Math.round(ranked[1]!.share * 100))
  })

  it('leaves out districts beyond the limit', () => {
    const data = dataset(['A1', 'A2'], { A1: row(1200), A2: row(1200) })
    const ranked = rankDistricts(
      computeResults({
        dataset: data,
        query: { ...QUERY, maxMinutes: 30 },
        timeArrays: [new Uint16Array([20, 40])],
      }),
    )

    expect(ranked.map((r) => r.district)).toEqual(['A1'])
  })

  it('is stable between identical runs', () => {
    const data = dataset(['A1', 'A2', 'A3'], { A1: row(1300), A2: row(1300), A3: row(1300) })
    const results = computeResults({
      dataset: data,
      query: QUERY,
      timeArrays: [new Uint16Array([20, 20, 20])],
    })

    expect(rankDistricts(results).map((r) => r.district)).toEqual(
      rankDistricts(results).map((r) => r.district),
    )
  })

  it('honours the limit on how many it returns', () => {
    const codes = Array.from({ length: 40 }, (_, i) => `A${i}`)
    const rents = Object.fromEntries(codes.map((c, i) => [c, row(1000 + i * 10)]))
    const data = dataset(codes, rents)

    const ranked = rankDistricts(
      computeResults({
        dataset: data,
        query: QUERY,
        timeArrays: [new Uint16Array(codes.map(() => 20))],
      }),
      5,
    )

    expect(ranked).toHaveLength(5)
  })
})

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

describe('summarise', () => {
  it('narrows in three stages so a poor answer can say where it fell', () => {
    const data = dataset(['NEAR', 'FAR', 'NODATA', 'DEAR'], {
      NEAR: row(1200),
      FAR: row(1200),
      DEAR: row(9000, 0.1),
    })
    const results = computeResults({
      dataset: data,
      query: QUERY,
      timeArrays: [new Uint16Array([20, 90, 25, 25])],
    })
    const summary = summarise(results, rankDistricts(results), QUERY.maxMinutes)

    expect(summary.withinLimit).toBe(3) // NEAR, NODATA, DEAR
    expect(summary.withData).toBe(2) // NEAR, DEAR
    expect(summary.worthLooking).toBe(1) // NEAR alone
  })

  it('names the district with the most choice and the closest one', () => {
    const data = dataset(['CLOSE', 'CHEAP'], { CLOSE: row(1550), CHEAP: row(1000) })
    const results = computeResults({
      dataset: data,
      query: QUERY,
      timeArrays: [new Uint16Array([12, 40])],
    })
    const summary = summarise(results, rankDistricts(results), QUERY.maxMinutes)

    expect(summary.best?.district).toBe('CHEAP')
    expect(summary.nearest?.district).toBe('CLOSE')
  })

  it('offers the cheapest median only when nothing is in budget', () => {
    const data = dataset(['A1', 'A2'], { A1: row(5200, 0.1), A2: row(6400, 0.1) })
    const results = computeResults({
      dataset: data,
      query: QUERY,
      timeArrays: [new Uint16Array([20, 25])],
    })
    const summary = summarise(results, rankDistricts(results), QUERY.maxMinutes)

    expect(summary.worthLooking).toBe(0)
    expect(summary.cheapestMedian).toEqual({ district: 'A1', median: 5200, minutes: 20 })
  })

  it('does not offer it when something is in budget', () => {
    const data = dataset(['A1'], { A1: row(1200) })
    const results = computeResults({
      dataset: data,
      query: QUERY,
      timeArrays: [new Uint16Array([20])],
    })

    expect(summarise(results, rankDistricts(results), QUERY.maxMinutes).cheapestMedian).toBeNull()
  })

  it('counts nothing when nothing is within reach', () => {
    const data = dataset(['A1'], { A1: row(1200) })
    const results = computeResults({
      dataset: data,
      query: QUERY,
      timeArrays: [new Uint16Array([UNREACHABLE])],
    })
    const summary = summarise(results, rankDistricts(results), QUERY.maxMinutes)

    expect(summary.withinLimit).toBe(0)
    expect(summary.best).toBeNull()
  })
})

describe('toFigures', () => {
  it('reads the published row in the documented order', () => {
    const figures = toFigures([1650, 1480, 1850, 410, 7.4085, 0.22, 1])

    expect(figures.median).toBe(1650)
    expect(figures.lowerQuartile).toBe(1480)
    expect(figures.upperQuartile).toBe(1850)
    expect(figures.sample).toBe(410)
    expect(figures.wellFitted).toBe(true)
  })

  it('reads the poorly fitted flag', () => {
    expect(toFigures([1650, 1480, 1850, 410, 7.4085, 0.22, 0]).wellFitted).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Before a workplace is chosen
// ---------------------------------------------------------------------------

describe('computeResults with no workplace', () => {
  // Clicking the map is the first thing most people try. Rent does not
  // depend on a commute, so a district clicked on the opening screen has an
  // answer to give even though no journey has been asked for.
  const data = dataset(['E1', 'SE10'], { E1: row(1400), SE10: row(2100) })
  const results = computeResults({
    dataset: data,
    query: { ...QUERY, workplace: null },
    timeArrays: [],
  })

  it('still works out what each district costs', () => {
    const e1 = results.find((r) => r.district === 'E1')

    expect(e1?.rent?.[0]).toBe(1400)
    expect(e1?.share).toBeGreaterThan(0.5)
  })

  it('reports no journey rather than a journey of zero', () => {
    for (const result of results) {
      expect(result.minutes).toBeNull()
      expect(result.minutesEach).toEqual([])
    }
  })

  it('puts nothing in play, so nothing is ranked or shaded', () => {
    expect(results.every((r) => !r.inPlay)).toBe(true)
    expect(rankDistricts(results)).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// The headline and the list are the same districts
// ---------------------------------------------------------------------------

describe('a district the budget barely reaches', () => {
  // The threshold was applied in two places and they disagreed. The
  // headline counted districts above a sliver, the list below it did not,
  // and the page read "7 districts work on £750" over a list of eight whose
  // last row was SW7 at 0%, under a heading saying "Most choice within your
  // budget".
  const data = dataset(['E1', 'SW7'], {
    E1: row(700),
    // A median of £3,000 against a budget of £1,600: a fraction of a per
    // cent of the market, which displays as 0%.
    SW7: row(3000, 0.18),
  })
  const results = computeResults({ dataset: data, query: QUERY, timeArrays: [new Uint16Array([20, 20])] })
  const ranked = rankDistricts(results)
  const summary = summarise(results, ranked, QUERY.maxMinutes)

  it('leaves it out of the list', () => {
    expect(ranked.map((r) => r.district)).toEqual(['E1'])
  })

  it('counts the list and the headline the same', () => {
    expect(summary.worthLooking).toBe(ranked.length)
  })

  it('still counts it as inside the limit and as having figures', () => {
    // It is not hidden, only not offered. The map still shades it and the
    // panel still opens it, because "almost nothing here" is an answer.
    expect(summary.withinLimit).toBe(2)
    expect(summary.withData).toBe(2)
    expect(results.find((r) => r.district === 'SW7')?.share).toBeLessThan(0.01)
  })

  it('falls back to the cheapest median when every district is a sliver', () => {
    const thin = dataset(['SW7'], { SW7: row(3000, 0.18) })
    const only = computeResults({ dataset: thin, query: QUERY, timeArrays: [new Uint16Array([20])] })
    const nothing = summarise(only, rankDistricts(only), QUERY.maxMinutes)

    expect(nothing.worthLooking).toBe(0)
    expect(nothing.cheapestMedian).toEqual({ district: 'SW7', median: 3000, minutes: 20 })
  })
})
