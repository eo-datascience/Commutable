import { describe, expect, it } from 'vitest'

import {
  DEFAULT_QUERY,
  MAX_BUDGET,
  MAX_MINUTES,
  MIN_BUDGET,
  MIN_MINUTES,
  parseQuery,
  toSearch,
} from './urlState'

const CATEGORIES = ['1', '2', '3']

describe('parseQuery', () => {
  it('reads a complete question', () => {
    const query = parseQuery(
      '?w=079051&wn=Canary%20Wharf&w2=070054&wn2=Bank&t=40&b=2200&bed=2&d=SE10',
      CATEGORIES,
    )

    expect(query).toEqual({
      workplace: '079051',
      workplaceName: 'Canary Wharf',
      workplace2: '070054',
      workplaceName2: 'Bank',
      maxMinutes: 40,
      budget: 2200,
      bedrooms: '2',
      selected: 'SE10',
      view: 'budget',
    })
  })

  it('falls back to the defaults on an empty query', () => {
    expect(parseQuery('', CATEGORIES)).toEqual({ ...DEFAULT_QUERY, bedrooms: '1' })
  })

  // A URL is the one input anybody can edit, so everything arriving through
  // it is bounded rather than trusted.
  it('clamps a time limit outside the range the controls offer', () => {
    expect(parseQuery('?t=9999', CATEGORIES).maxMinutes).toBe(MAX_MINUTES)
    expect(parseQuery('?t=1', CATEGORIES).maxMinutes).toBe(MIN_MINUTES)
    expect(parseQuery('?t=-50', CATEGORIES).maxMinutes).toBe(MIN_MINUTES)
  })

  it('clamps a budget outside the range', () => {
    expect(parseQuery('?b=99999999', CATEGORIES).budget).toBe(MAX_BUDGET)
    expect(parseQuery('?b=0', CATEGORIES).budget).toBe(MIN_BUDGET)
  })

  it('ignores a value that is not a number', () => {
    expect(parseQuery('?t=soon&b=lots', CATEGORIES).maxMinutes).toBe(DEFAULT_QUERY.maxMinutes)
    expect(parseQuery('?t=soon&b=lots', CATEGORIES).budget).toBe(DEFAULT_QUERY.budget)
  })

  it('ignores a grid cell that is not a grid cell', () => {
    for (const bad of ['abc', '12345', '1234567', '../../etc/passwd', '']) {
      expect(parseQuery(`?w=${encodeURIComponent(bad)}`, CATEGORIES).workplace).toBeNull()
    }
  })

  it('ignores a bedroom category the data does not have', () => {
    expect(parseQuery('?bed=7', CATEGORIES).bedrooms).toBe('1')
    expect(parseQuery('?bed=2', CATEGORIES).bedrooms).toBe('2')
  })

  it('drops a second workplace that arrives without a first', () => {
    // Otherwise the partner's commute would be shown as though it were the
    // only one, which is a different and wrong answer.
    const query = parseQuery('?w2=070054&wn2=Bank', CATEGORIES)

    expect(query.workplace).toBeNull()
    expect(query.workplace2).toBeNull()
    expect(query.workplaceName2).toBeNull()
  })

  it('trims a workplace name and caps its length', () => {
    const long = 'x'.repeat(500)
    const query = parseQuery(`?w=079051&wn=${long}`, CATEGORIES)

    expect(query.workplaceName).toHaveLength(60)
  })

  // Categories sort with rooms and studios ahead of the bedroom counts, and
  // those are the two ONS publishes least often. Falling back to the first
  // one opened the map on the thinnest category in the dataset.
  it('defaults to one bedroom rather than the first published category', () => {
    const query = parseQuery('', ['room', 'studio', '1', '2', '3'])

    expect(query.bedrooms).toBe('1')
  })

  it('still honours a size asked for in the URL', () => {
    expect(parseQuery('?bed=room', ['room', '1', '2']).bedrooms).toBe('room')
  })

  it('falls back to the first category where one bedroom is not published', () => {
    expect(parseQuery('', ['studio', '2', '3']).bedrooms).toBe('studio')
  })

  it('opens on the default view when the URL asks for one that does not exist', () => {
    expect(parseQuery('?v=heatmap', CATEGORIES).view).toBe('budget')
    expect(parseQuery('', CATEGORIES).view).toBe('budget')
    expect(parseQuery('?v=time', CATEGORIES).view).toBe('time')
  })

  it('treats a blank name as absent', () => {
    expect(parseQuery('?w=079051&wn=%20%20', CATEGORIES).workplaceName).toBeNull()
  })
})

describe('toSearch', () => {
  it('round trips a question', () => {
    const original = {
      workplace: '079051',
      workplaceName: "King's Cross",
      workplace2: '070054',
      workplaceName2: 'Bank',
      maxMinutes: 55,
      budget: 1850,
      bedrooms: '2',
      selected: 'E14',
      view: 'time' as const,
    }

    expect(parseQuery(toSearch(original), CATEGORIES)).toEqual(original)
  })

  it('leaves out what has not been chosen', () => {
    // Checked as parameter names rather than as substrings: 'bed=1' contains
    // 'd=', and the first version of this test failed on exactly that.
    const params = new URLSearchParams(toSearch({ ...DEFAULT_QUERY, bedrooms: '1' }))

    expect([...params.keys()].sort()).toEqual(['b', 'bed', 't'])
    expect(params.get('t')).toBe('45')
    expect(params.get('b')).toBe('1600')
  })

  it('carries the view only when it is not the default', () => {
    // A shared link is pasted into a message, so every parameter that can
    // be left out is left out.
    expect(toSearch(DEFAULT_QUERY)).not.toContain('v=')
    expect(toSearch({ ...DEFAULT_QUERY, view: 'time' })).toContain('v=time')
  })

  it('escapes a name with a space or an apostrophe', () => {
    const search = toSearch({ ...DEFAULT_QUERY, workplace: '079051', workplaceName: "King's Cross" })

    expect(search).not.toContain(' ')
    expect(parseQuery(search, CATEGORIES).workplaceName).toBe("King's Cross")
  })

  it('produces the same string for the same question', () => {
    const query = { ...DEFAULT_QUERY, workplace: '079051', bedrooms: '2' }

    expect(toSearch(query)).toBe(toSearch({ ...query }))
  })
})
