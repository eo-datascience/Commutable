// The visitor's question, kept in the URL.
//
// This is how sharing works, and it is why there are no accounts. A link
// carries the whole question — both workplaces, the budget, the bedroom
// count, the time limit — so sending somebody your answer is copying the
// address bar. No sign-up, no saved searches to lose, no database holding
// where strangers work.
//
// The parameters are short because the URL gets pasted into messages, and
// they are validated on the way in because a URL is the one input anybody
// can edit.

import type { Query } from './types'

export const DEFAULT_QUERY: Query = {
  workplace: null,
  workplace2: null,
  workplaceName: null,
  workplaceName2: null,
  maxMinutes: 45,
  budget: 1600,
  bedrooms: '1',
  selected: null,
  view: 'budget',
}

// Bounds, applied to anything arriving from the URL. A budget of a billion
// would colour every district identically and a limit of six hours would
// make the commute filter meaningless, so both are held inside the range
// the controls offer.
export const MIN_MINUTES = 10
export const MAX_MINUTES = 120
export const MIN_BUDGET = 300
export const MAX_BUDGET = 10_000

const CELL_PATTERN = /^\d{6}$/

function clampInt(raw: string | null, low: number, high: number, fallback: number): number {
  if (raw === null) return fallback
  const value = Number.parseInt(raw, 10)
  if (!Number.isFinite(value)) return fallback
  return Math.min(high, Math.max(low, value))
}

function cell(raw: string | null): string | null {
  return raw !== null && CELL_PATTERN.test(raw) ? raw : null
}

function label(raw: string | null): string | null {
  if (raw === null) return null
  // A name arriving from the URL is rendered as text. React escapes it, so
  // this is a length guard rather than a safety one: a shared link with a
  // thousand character name should not push the controls off the screen.
  const trimmed = raw.trim().slice(0, 60)
  return trimmed.length > 0 ? trimmed : null
}

/**
 * Which size of home to show when the URL does not say.
 *
 * Not simply the first published category. They sort with rooms and
 * studios ahead of the bedroom counts, and those are the two ONS publishes
 * least often: in London, rooms are published for 49 districts against 195
 * for one bedroom. Landing on rooms made a well covered city open on four
 * shaded districts and twenty-five hatched ones, which reads as a broken
 * map rather than a thin statistic.
 *
 * One bedroom is both the commonest tenancy and the best covered category,
 * so it is preferred wherever it is published, with the first category as
 * the fallback for a city where it is not.
 */
function pickBedrooms(raw: string | null, categories: string[]): string {
  if (raw !== null && categories.includes(raw)) return raw
  if (categories.includes(DEFAULT_QUERY.bedrooms)) return DEFAULT_QUERY.bedrooms
  return categories[0] ?? DEFAULT_QUERY.bedrooms
}

export function parseQuery(search: string, bedroomCategories: string[]): Query {
  const params = new URLSearchParams(search)

  const bedrooms = params.get('bed')
  const workplace = cell(params.get('w'))

  return {
    workplace,
    // A second workplace without a first is meaningless, and would show the
    // partner's commute as though it were the only one.
    workplace2: workplace === null ? null : cell(params.get('w2')),
    workplaceName: label(params.get('wn')),
    workplaceName2: workplace === null ? null : label(params.get('wn2')),
    maxMinutes: clampInt(params.get('t'), MIN_MINUTES, MAX_MINUTES, DEFAULT_QUERY.maxMinutes),
    budget: clampInt(params.get('b'), MIN_BUDGET, MAX_BUDGET, DEFAULT_QUERY.budget),
    bedrooms: pickBedrooms(bedrooms, bedroomCategories),
    selected: params.get('d'),
    // Anything other than the one alternative is the default, so a
    // mistyped link opens on the view the site opens on.
    view: params.get('v') === 'time' ? 'time' : 'budget',
  }
}

export function toSearch(query: Query): string {
  const params = new URLSearchParams()

  if (query.workplace) params.set('w', query.workplace)
  if (query.workplaceName) params.set('wn', query.workplaceName)
  if (query.workplace2) params.set('w2', query.workplace2)
  if (query.workplaceName2) params.set('wn2', query.workplaceName2)
  params.set('t', String(query.maxMinutes))
  params.set('b', String(query.budget))
  params.set('bed', query.bedrooms)
  if (query.selected) params.set('d', query.selected)
  // Only when it is not the default, to keep a shared link short.
  if (query.view !== 'budget') params.set('v', query.view)

  return `?${params.toString()}`
}

/**
 * Write the query to the address bar without adding a history entry.
 *
 * replaceState rather than pushState: dragging a budget slider would
 * otherwise bury the visitor's previous page under forty entries, and the
 * back button would walk them through every intermediate value.
 */
export function syncUrl(query: Query): void {
  const next = `${window.location.pathname}${toSearch(query)}`
  if (next !== `${window.location.pathname}${window.location.search}`) {
    window.history.replaceState(null, '', next)
  }
}
