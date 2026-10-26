// The share of a district's rental market that a budget reaches.
//
// This is the same calculation as RentDistribution.share_under in
// pipeline/rent.py, and it lives in two languages for the same reason the
// scoring did in the last project: the pipeline needs it to rank and
// validate, and the browser needs it to answer a new budget without asking
// the server anything, because there is no server.
//
// Two implementations of one formula is a liability. It is handled the same
// way: the Python side writes out fixtures from its own implementation, and
// the tests here assert this code reproduces them exactly. The fixtures are
// regenerated in CI, so the two cannot drift without a build going red.
//
// See src/lib/affordability.test.ts and scripts/make_parity_fixtures.py.

/** The standard normal quantile at 0.25, to match the pipeline exactly. */
export const Z_QUARTILE = 0.6744897501960817

export interface RentFigures {
  /** Published by ONS and shown verbatim. */
  median: number
  lowerQuartile: number
  upperQuartile: number
  /** Tenancies the figures are drawn from. */
  sample: number
  /** The fitted lognormal. */
  mu: number
  sigma: number
  /** False where the fitted curve misses a published quartile by over 5%. */
  wellFitted: boolean
}

/**
 * The standard normal cumulative distribution.
 *
 * Hart's rational approximation, which is accurate to roughly 1e-15 across
 * the whole range. JavaScript has no Math.erf and the alternative is a
 * dependency for one function.
 *
 * The obvious cheaper choice is Abramowitz and Stegun 7.1.26, which is five
 * lines rather than twenty. It was the first implementation here and it was
 * replaced, because at an accuracy of about 1.5e-7 it does not return
 * exactly a half at zero, and it put the agreement with Python's math.erf
 * at the mercy of an approximation error rather than of the formula. That
 * is a bad trade when the whole point of the parity fixtures is to detect a
 * disagreement between the two implementations: a tolerance loose enough to
 * absorb the approximation is also loose enough to absorb a real mistake.
 *
 * With this version the two sides agree to within about 1e-15, so the
 * fixtures can be asserted at a tolerance that only a genuine divergence
 * could cross.
 */
export function normalCdf(z: number): number {
  const y = Math.abs(z)

  // Beyond 37 standard deviations the tail is smaller than the smallest
  // double, and the polynomial below would be evaluated for nothing.
  if (y > 37) return z > 0 ? 1 : 0

  const e = Math.exp(-(y * y) / 2)
  let p: number

  if (y < 7.071067811865475) {
    let b = 0.0352624965998911 * y + 0.700383064443688
    b = b * y + 6.37396220353165
    b = b * y + 33.912866078383
    b = b * y + 112.079291497871
    b = b * y + 221.213596169931
    b = b * y + 220.206867912376

    let c = 0.0883883476483184 * y + 1.75566716318264
    c = c * y + 16.064177579207
    c = c * y + 86.7807322029461
    c = c * y + 296.564248779674
    c = c * y + 637.333633378831
    c = c * y + 793.826512519948
    c = c * y + 440.413735824752

    p = (e * b) / c
  } else {
    // A continued fraction for the far tail, where the ratio above loses
    // precision.
    let b = y + 0.65
    b = y + 4 / b
    b = y + 3 / b
    b = y + 2 / b
    b = y + 1 / b
    p = e / (b * 2.506628274631)
  }

  return z > 0 ? 1 - p : p
}

/**
 * The share of this market at or below a monthly budget, from 0 to 1.
 *
 * A budget of nothing reaches nothing. There is no upper clamp because the
 * cumulative distribution cannot exceed 1.
 */
export function shareUnder(figures: RentFigures, budget: number): number {
  if (!(budget > 0)) return 0
  if (!(figures.sigma > 0)) return 0
  return normalCdf((Math.log(budget) - figures.mu) / figures.sigma)
}

/** The rent at a given percentile of this market. */
export function quantile(figures: RentFigures, p: number): number {
  if (!(p > 0 && p < 1)) throw new Error(`A percentile must be between 0 and 1, not ${p}`)
  return Math.exp(figures.mu + figures.sigma * inverseNormalCdf(p))
}

/**
 * What it would take to reach a given share of this market.
 *
 * The more useful direction when a budget reaches almost nothing: rather
 * than showing a wall of 3% figures, the site can say what a district
 * actually costs.
 */
export function budgetForShare(figures: RentFigures, share: number): number {
  return quantile(figures, share)
}

/**
 * The standard normal quantile function.
 *
 * Acklam's rational approximation, the same one the pipeline uses, so that
 * budgetForShare agrees with budget_for_share.
 */
export function inverseNormalCdf(p: number): number {
  const a = [
    -3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2,
    -3.066479806614716e1, 2.506628277459239,
  ]
  const b = [
    -5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1,
    -1.328068155288572e1,
  ]
  const c = [
    -7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734,
    4.374664141464968, 2.938163982698783,
  ]
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416]
  const low = 0.02425
  const high = 1 - low

  // Non-null assertions: the arrays above are literals of known length, and
  // noUncheckedIndexedAccess would otherwise require a guard per element.
  if (p < low) {
    const q = Math.sqrt(-2 * Math.log(p))
    return (
      (((((c[0]! * q + c[1]!) * q + c[2]!) * q + c[3]!) * q + c[4]!) * q + c[5]!) /
      ((((d[0]! * q + d[1]!) * q + d[2]!) * q + d[3]!) * q + 1)
    )
  }
  if (p > high) {
    const q = Math.sqrt(-2 * Math.log(1 - p))
    return (
      -(((((c[0]! * q + c[1]!) * q + c[2]!) * q + c[3]!) * q + c[4]!) * q + c[5]!) /
      ((((d[0]! * q + d[1]!) * q + d[2]!) * q + d[3]!) * q + 1)
    )
  }
  const q = p - 0.5
  const r = q * q
  return (
    ((((((a[0]! * r + a[1]!) * r + a[2]!) * r + a[3]!) * r + a[4]!) * r + a[5]!) * q) /
    (((((b[0]! * r + b[1]!) * r + b[2]!) * r + b[3]!) * r + b[4]!) * r + 1)
  )
}

/**
 * The interquartile range as a share of the median.
 *
 * Shown in the panel because it is the honest answer to "how much does this
 * one number tell me". A district whose middle half spans £1,400 to £2,600
 * is not described by its median.
 */
export function spread(figures: RentFigures): number {
  if (figures.median <= 0) return 0
  return (figures.upperQuartile - figures.lowerQuartile) / figures.median
}
