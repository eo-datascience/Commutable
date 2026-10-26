import { describe, expect, it } from 'vitest'

import { choiceLabel, collectiveLabel } from './labels'

// Every category the pipeline can publish, from pipeline/export.py.
const PUBLISHED = ['room', 'studio', '1', '2', '3', '4+', 'all']

describe('choiceLabel', () => {
  it('words each published category as something you pick', () => {
    expect(PUBLISHED.map(choiceLabel)).toEqual([
      'a room',
      'a studio',
      '1 bedroom',
      '2 bedrooms',
      '3 bedrooms',
      '4+ bedrooms',
      'any size',
    ])
  })
})

describe('collectiveLabel', () => {
  it('words each published category as a collection', () => {
    expect(PUBLISHED.map(collectiveLabel)).toEqual([
      'rooms',
      'studios',
      '1 bedroom homes',
      '2 bedroom homes',
      '3 bedroom homes',
      '4+ bedroom homes',
      'homes of any size',
    ])
  })

  // The bug this file exists to prevent. The dropdown wording was being
  // dropped into the sentences, which rendered "72% of its a room homes
  // are in budget" and "Share of a room homes at or under £900".
  it('never produces an article inside a sentence', () => {
    for (const category of PUBLISHED) {
      const sentence = `72% of its ${collectiveLabel(category)} are in budget`
      expect(sentence).not.toMatch(/\ba\s/)
    }
  })

  it('reads as a plural after a share', () => {
    expect(`72% of its ${collectiveLabel('room')}`).toBe('72% of its rooms')
    expect(`Share of ${collectiveLabel('2')}`).toBe('Share of 2 bedroom homes')
  })
})

describe('an unrecognised category', () => {
  // ONS has renamed its categories before. A label that comes out blank
  // would leave a hole in the middle of a sentence; one that comes out
  // awkward still says which size of home it means.
  it('still says which size it means', () => {
    expect(choiceLabel('5 to 6')).toBe('5 to 6')
    expect(collectiveLabel('5 to 6')).toBe('5 to 6 homes')
  })

  it('handles a bedroom count nobody has published yet', () => {
    expect(choiceLabel('7')).toBe('7 bedrooms')
    expect(collectiveLabel('7')).toBe('7 bedroom homes')
    expect(collectiveLabel('10+')).toBe('10+ bedroom homes')
  })

  it('is never empty', () => {
    for (const category of [...PUBLISHED, '', '5 to 6', 'bedsit']) {
      expect(collectiveLabel(category).length).toBeGreaterThan(0)
      expect(choiceLabel(category).length).toBeGreaterThan(0)
    }
  })
})
