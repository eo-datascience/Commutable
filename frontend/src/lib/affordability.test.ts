// The browser's affordability calculation, checked against the pipeline's.
//
// The fixtures in parity.json were written by pipeline/rent.py. These tests
// assert this code reproduces them. CI regenerates the fixtures and fails
// if they differ from the committed file, so the two implementations cannot
// drift apart without a build going red.

import { describe, expect, it } from 'vitest'

import {
  budgetForShare,
  inverseNormalCdf,
  normalCdf,
  quantile,
  shareUnder,
  spread,
  Z_QUARTILE,
  type RentFigures,
} from './affordability'
import parity from './parity.json'

// Python uses math.erf; this uses Hart's rational approximation. Both are
// accurate to around 1e-15, so this is not set at the accuracy of either.
//
// It is set by what the fixtures can promise. They are rounded on the way
// out, because the last bits of a double are not portable and CI compares
// the file byte for byte against a freshly generated one. Shares are
// written to 1e-10, so an assertion tighter than that would be testing the
// rounding rather than the implementation.
//
// 1e-9 is still a hundred times tighter than the mistake this exists to
// catch: swapping Hart's approximation for Abramowitz and Stegun 7.1.26
// moves a share by about 1.5e-7, which this would fail on immediately.
const SHARE_TOLERANCE = 1e-9

// Budgets are shown to the nearest pound, so agreement within a penny is
// far tighter than anything a visitor could see.
const MONEY_TOLERANCE = 0.01

describe('parity with the pipeline', () => {
  it('uses the same quartile constant', () => {
    expect(Z_QUARTILE).toBe(parity.z_quartile)
  })

  it('has fixtures to check against', () => {
    expect(parity.cases.length).toBeGreaterThanOrEqual(5)
  })

  for (const testCase of parity.cases) {
    const figures = testCase.figures as RentFigures

    describe(testCase.label, () => {
      it('reproduces every share the pipeline computed', () => {
        for (const probe of testCase.shareUnder) {
          expect(shareUnder(figures, probe.budget)).toBeCloseTo(probe.share, 6)
          expect(Math.abs(shareUnder(figures, probe.budget) - probe.share)).toBeLessThan(
            SHARE_TOLERANCE,
          )
        }
      })

      it('reproduces every budget the pipeline computed', () => {
        for (const probe of testCase.budgetForShare) {
          expect(Math.abs(budgetForShare(figures, probe.share) - probe.budget)).toBeLessThan(
            MONEY_TOLERANCE,
          )
        }
      })

      it('puts half the market under the published median', () => {
        // Half to the nearest shown percentage, which is what a visitor
        // sees, rather than half to machine precision.
        //
        // The two are not the same, and the gap is largest exactly where
        // the spread is narrowest. mu comes from a least squares fit to
        // three published quartiles, which are rounded before they are
        // published, so it lands a few parts in a million from the log of
        // the median. Dividing that by a small sigma amplifies it: the
        // district at the spread floor reports 50.002% rather than 50%.
        //
        // It never reaches the screen, because the median shown on the
        // site is the one ONS published and not one implied by the curve.
        // It is asserted at the precision the site actually displays so
        // that a real divergence between the two implementations still
        // fails, which is what these fixtures are for.
        const share = shareUnder(figures, figures.median)

        expect(Math.round(share * 100)).toBe(50)
        expect(share).toBeCloseTo(0.5, 4)
      })

      it('puts a quarter of the market under the published lower quartile', () => {
        // Not exactly a quarter, because the fit is to all three quantiles
        // and real quartiles are rounded to the penny before fitting. Close
        // enough that a visitor would never see the difference.
        expect(shareUnder(figures, figures.lowerQuartile)).toBeCloseTo(0.25, 3)
        expect(shareUnder(figures, figures.upperQuartile)).toBeCloseTo(0.75, 3)
      })
    })
  }
})

describe('shareUnder', () => {
  const figures: RentFigures = {
    median: 1850,
    lowerQuartile: 1573.51,
    upperQuartile: 2175.08,
    sample: 500,
    mu: 7.522941904757055,
    sigma: 0.24000116578360853,
    wellFitted: true,
  }

  it('reaches nothing on no budget', () => {
    expect(shareUnder(figures, 0)).toBe(0)
    expect(shareUnder(figures, -500)).toBe(0)
  })

  it('never decreases as the budget rises', () => {
    let previous = -1
    for (let budget = 100; budget <= 10000; budget += 25) {
      const share = shareUnder(figures, budget)
      expect(share).toBeGreaterThanOrEqual(previous)
      previous = share
    }
  })

  it('stays between nothing and everything', () => {
    for (const budget of [1, 100, 1850, 50_000, 1e9]) {
      const share = shareUnder(figures, budget)
      expect(share).toBeGreaterThanOrEqual(0)
      expect(share).toBeLessThanOrEqual(1)
    }
  })

  it('returns nothing rather than a division by zero when there is no spread', () => {
    // The pipeline refuses to publish a district with no spread, so this
    // should be unreachable. It is guarded anyway, because a NaN would
    // propagate into the fill colour and paint the district as transparent
    // with no indication of why.
    expect(shareUnder({ ...figures, sigma: 0 }, 1850)).toBe(0)
  })

  it('is monotonic in the median at a fixed budget', () => {
    const cheap = { ...figures, mu: Math.log(1200) }
    const dear = { ...figures, mu: Math.log(2600) }
    expect(shareUnder(cheap, 1500)).toBeGreaterThan(shareUnder(dear, 1500))
  })

  it('gives a wider market more cheap stock at the same median', () => {
    // mu is set to the log of the median exactly here. In the published
    // data mu comes from a least squares fit to three rounded quartiles, so
    // it sits a hair off the log of the median, and at the median itself
    // the two spreads would then differ by a few parts in a million. That
    // is correct behaviour rather than error, but it would make this test
    // about the fit instead of about the spread.
    const narrow = { ...figures, mu: Math.log(figures.median), sigma: 0.12 }
    const wide = { ...figures, mu: Math.log(figures.median), sigma: 0.4 }

    expect(shareUnder(wide, 1400)).toBeGreaterThan(shareUnder(narrow, 1400))
    expect(shareUnder(wide, figures.median)).toBeCloseTo(0.5, 12)
    expect(shareUnder(narrow, figures.median)).toBeCloseTo(0.5, 12)
  })
})

describe('the normal distribution helpers', () => {
  it('is symmetric about zero', () => {
    expect(normalCdf(0)).toBeCloseTo(0.5, 9)
    for (const z of [0.25, 1, 1.96, 3]) {
      expect(normalCdf(z) + normalCdf(-z)).toBeCloseTo(1, 7)
    }
  })

  it('matches the values everyone knows', () => {
    expect(normalCdf(1.6448536269514722)).toBeCloseTo(0.95, 6)
    expect(normalCdf(1.959963984540054)).toBeCloseTo(0.975, 6)
    expect(normalCdf(-Z_QUARTILE)).toBeCloseTo(0.25, 6)
  })

  it('inverts itself', () => {
    for (const p of [0.001, 0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 0.999]) {
      expect(normalCdf(inverseNormalCdf(p))).toBeCloseTo(p, 6)
    }
  })
})

describe('quantile', () => {
  const figures: RentFigures = {
    median: 1850,
    lowerQuartile: 1573.51,
    upperQuartile: 2175.08,
    sample: 500,
    mu: 7.522941904757055,
    sigma: 0.24000116578360853,
    wellFitted: true,
  }

  it('refuses a percentile outside the range', () => {
    for (const bad of [0, 1, -0.5, 1.5]) {
      expect(() => quantile(figures, bad)).toThrow('between 0 and 1')
    }
  })

  it('inverts shareUnder', () => {
    for (const share of [0.05, 0.25, 0.5, 0.75, 0.95]) {
      expect(shareUnder(figures, quantile(figures, share))).toBeCloseTo(share, 6)
    }
  })
})

describe('spread', () => {
  it('is the interquartile range over the median', () => {
    const figures: RentFigures = {
      median: 2000,
      lowerQuartile: 1600,
      upperQuartile: 2600,
      sample: 100,
      mu: Math.log(2000),
      sigma: 0.2,
      wellFitted: true,
    }
    expect(spread(figures)).toBeCloseTo(0.5, 9)
  })

  it('returns nothing rather than dividing by zero', () => {
    const figures: RentFigures = {
      median: 0,
      lowerQuartile: 0,
      upperQuartile: 0,
      sample: 0,
      mu: 0,
      sigma: 0.2,
      wellFitted: false,
    }
    expect(spread(figures)).toBe(0)
  })
})
