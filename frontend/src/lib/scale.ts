// How a district gets its colour.
//
// Two variables have to reach the eye at once: whether a district is inside
// the commute limit, and how much of its market the budget reaches. They
// are encoded differently on purpose.
//
// The commute limit is a gate, not a quantity. A district beyond it is not
// a worse answer, it is not an answer, so it is drawn in a flat recessive
// grey that is plainly not part of the data. Shading it dark blue would
// invite the eye to compare it with the places that qualify.
//
// Affordability is the quantity, so it gets the colour: one hue, five
// steps, light to dark. Five discrete bins rather than a continuous ramp,
// because a legend with five labelled steps can be read exactly and a
// continuous gradient can only be read approximately, and the underlying
// figure is an estimate from three published quartiles rather than a
// measurement that deserves a smooth scale.
//
// A third state exists and matters: no rent figures published. ONS
// suppresses small samples, and the City and the West End have almost no
// rental housing to publish. Those districts are drawn in grey with a
// diagonal hatch, so "we cannot say" never looks like "too far" and never
// looks like "nothing in budget". The hatch is doing real work: the two
// greys alone fail a normal-vision separation check, so the difference
// cannot rest on colour.
//
// Every value below was chosen by running the palette validator rather
// than by eye. See docs/design-notes.md.

/** The five bins, as the lower bound of each. */
export const BINS = [0, 0.1, 0.25, 0.5, 0.75] as const

export const BIN_LABELS = [
  'under 10%',
  '10 to 25%',
  '25 to 50%',
  '50 to 75%',
  '75% or more',
] as const

/**
 * Blue, light to dark.
 *
 * Light mode uses steps 300 to 700 of the blue ramp. The paler steps were
 * tried first and rejected: against this page's surface the lightest of
 * them sits at 1.4:1, so a district with nothing in budget would have
 * faded into the background and been indistinguishable from one that was
 * never measured.
 */
export const RAMP_LIGHT = ['#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'] as const

/**
 * The same hue stepped for the dark surface, selected rather than flipped.
 *
 * Steps 150 to 550, so the brightest step is the most choice. On a dark
 * page the eye reads bright as more, which is the opposite of the light
 * mode ordering and the reason this is a separate list rather than the
 * first one reversed.
 */
export const RAMP_DARK = ['#1c5cab', '#2a78d6', '#5598e7', '#86b6ef', '#b7d3f6'] as const

export type Mode = 'light' | 'dark'

/**
 * What the colour on the map means.
 *
 * Two questions share one picture. "How much of this district can I
 * afford" is the one the site opens on, and "how long does it take to get
 * there" is the one every visitor asks next, out loud, while looking at
 * the first. The journey times are already in the browser, so answering
 * the second costs a repaint.
 *
 * They are separate hues rather than two shades of the same one. Two blue
 * maps that differ only in which blue would look like the same map, and a
 * visitor who missed the switch would read minutes as money.
 */
export type View = 'budget' | 'time'

/** The journey-time bins, as the lower bound of each, in minutes. */
export const TIME_BINS = [0, 15, 30, 45, 60] as const

/**
 * The highest time bin that can actually occur, given the visitor's limit.
 *
 * The bins are fixed quarter hours, but the limit is a slider, and the two
 * have to agree or the key stops describing the map. At a 60 minute limit
 * the "over 60 min" bin can hold only a journey of exactly 60, which would
 * have printed a legend entry sitting next to the grey "over 60 min away"
 * and meaning something different by the same words.
 *
 * So the top bin is the one containing the limit, and anything that lands
 * above it is drawn in it.
 */
export function topTimeBin(maxMinutes: number): number {
  let top = 0
  for (let i = 0; i < TIME_BINS.length; i++) {
    if ((TIME_BINS[i] ?? 0) < maxMinutes) top = i
  }
  return top
}

/**
 * The legend's labels, cut off at the limit.
 *
 * The last one is phrased against the limit rather than against the bin,
 * so a 60 minute journey at a 60 minute limit reads as "45 to 60 min"
 * rather than falling into an "over 60 min" bucket the visitor has
 * excluded by definition.
 */
export function timeLabels(maxMinutes: number): string[] {
  const top = topTimeBin(maxMinutes)
  const labels: string[] = []

  for (let i = 0; i <= top; i++) {
    const lower = TIME_BINS[i] ?? 0
    const upper = TIME_BINS[i + 1] ?? Infinity
    const capped = Math.min(upper, maxMinutes)

    if (i === 0) labels.push(`under ${capped} min`)
    else labels.push(`${lower} to ${capped} min`)
  }

  return labels
}

/**
 * Orange, strongest first.
 *
 * The direction is the opposite of the blue ramp's and deliberately so.
 * For affordability more is better, so the strongest colour is the
 * highest share. For journey time less is better, so the strongest colour
 * is the shortest trip. The invariant the two share is the one that
 * matters: the strongest colour is always the better answer.
 *
 * Held to the same standard as the blue. The palest step sits at 2.4:1
 * against the light surface, against the blue ramp's 2.2:1, and no two
 * neighbouring steps are closer in luminance than the closest blue pair.
 */
export const TIME_RAMP_LIGHT = ['#7c2d0c', '#a0390e', '#bd4b17', '#cd6a30', '#d68b55'] as const

/** The same, stepped for the dark surface. Brightest is the shortest trip. */
export const TIME_RAMP_DARK = ['#fcd4b4', '#f6a97c', '#ee6f3b', '#c55526', '#a0471c'] as const

export interface Fill {
  /** A CSS colour, or a reference to the hatch pattern. */
  fill: string
  /** Set when the fill is the hatch, so the renderer can add the pattern. */
  hatched: boolean
  /** What this district is, in words, for the title attribute and the panel. */
  state: 'affordable' | 'too far' | 'no data' | 'waiting'
  /** Which bin, for the legend's hover highlighting. Null when not in play. */
  bin: number | null
}

export const GREY = {
  light: { tooFar: '#cfcdc6', noData: '#e4e3dd', waiting: '#dfe4ea' },
  dark: { tooFar: '#3a3d44', noData: '#262a31', waiting: '#1d242e' },
} as const

export const ACCENT = { light: '#d2541f', dark: '#eb6834' } as const

/** Which of the five bins a share falls in. */
export function binOf(share: number): number {
  for (let i = BINS.length - 1; i >= 0; i--) {
    if (share >= (BINS[i] ?? 0)) return i
  }
  return 0
}

/** Which of the five bins a journey time falls in. */
export function binOfTime(minutes: number): number {
  for (let i = TIME_BINS.length - 1; i >= 0; i--) {
    if (minutes >= (TIME_BINS[i] ?? 0)) return i
  }
  return 0
}

/**
 * The fill for one district.
 *
 * Order matters. A district can be both beyond the limit and missing rent
 * figures, and in that case "too far" wins: it is excluded by the
 * visitor's own choice, so saying "we have no figures" would be answering
 * a question they did not ask.
 */
export interface FillRequest {
  minutes: number | null
  maxMinutes: number
  share: number | null
  mode: Mode
  /** False before any workplace is chosen. */
  asked?: boolean
  /** What the colour means. Defaults to the share of the market. */
  view?: View
}

export function fillFor({
  minutes,
  maxMinutes,
  share,
  mode,
  asked = true,
  view = 'budget',
}: FillRequest): Fill {
  const grey = GREY[mode]

  // Before a workplace is chosen there is no journey to be too long. The
  // first version painted the whole city in the "too far" grey, which is
  // the colour for a place the visitor has ruled out, and so the opening
  // screen said no to a question nobody had asked yet. This is a quieter
  // grey that reads as a map waiting for input.
  if (!asked) {
    return { fill: grey.waiting, hatched: false, state: 'waiting', bin: null }
  }

  if (minutes === null || minutes > maxMinutes) {
    return { fill: grey.tooFar, hatched: false, state: 'too far', bin: null }
  }

  // The time view answers from the journey alone, so a district with no
  // published rent still has an answer and is coloured rather than
  // hatched. This is the one place the two views disagree about which
  // districts count as missing, and it is the whole reason the view is
  // worth having: the hatched hole over the City in the budget view is
  // not a hole in the timetable.
  if (view === 'time') {
    // Clamped to the top bin the legend shows, so nothing on the map is
    // painted in a colour the key does not explain.
    const bin = Math.min(binOfTime(minutes), topTimeBin(maxMinutes))
    const ramp = mode === 'dark' ? TIME_RAMP_DARK : TIME_RAMP_LIGHT
    return { fill: ramp[bin] ?? ramp[0], hatched: false, state: 'affordable', bin }
  }

  if (share === null) {
    return { fill: grey.noData, hatched: true, state: 'no data', bin: null }
  }

  const bin = binOf(share)
  const ramp = mode === 'dark' ? RAMP_DARK : RAMP_LIGHT
  return {
    fill: ramp[bin] ?? ramp[0],
    hatched: false,
    state: 'affordable',
    bin,
  }
}
