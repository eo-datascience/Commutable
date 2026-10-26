import { describe, expect, it } from 'vitest'

import { districtLabel, districtName } from './districts'
import type { Meta } from './types'

const named = {
  district_names: { E11: 'Leytonstone', SE13: 'Lewisham', KT1: 'Kingston upon Thames' },
} as unknown as Meta

const unnamed = {} as unknown as Meta

describe('districtName', () => {
  it('gives the name the data publishes', () => {
    expect(districtName(named, 'E11')).toBe('Leytonstone')
  })

  it('gives null for a district with no name rather than an empty string', () => {
    // The difference matters: null is a missing name and renders nothing,
    // an empty string renders an empty element with its own spacing.
    expect(districtName(named, 'ZZ9')).toBeNull()
  })

  it('gives null when the data has no names at all', () => {
    // A city published before the names existed, or one that ships none.
    expect(districtName(unnamed, 'E11')).toBeNull()
  })
})

describe('districtLabel', () => {
  it('leads with the code, because that is what a list is scanned for', () => {
    expect(districtLabel(named, 'E11')).toBe('E11 Leytonstone')
  })

  it('falls back to the bare code', () => {
    expect(districtLabel(named, 'ZZ9')).toBe('ZZ9')
    expect(districtLabel(unnamed, 'E11')).toBe('E11')
  })

  it('never renders a trailing separator when the name is missing', () => {
    // The first version was `${district} ${name ?? ''}`, which published
    // "ZZ9 " and showed as a code with an unexplained gap after it.
    expect(districtLabel(named, 'ZZ9')).toBe(districtLabel(named, 'ZZ9').trim())
  })
})
