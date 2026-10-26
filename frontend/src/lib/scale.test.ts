import { describe, expect, it } from 'vitest'

import { binOfTime, fillFor, timeLabels, topTimeBin, TIME_RAMP_DARK } from './scale'

const ask = (over: Partial<Parameters<typeof fillFor>[0]> = {}) =>
  fillFor({ minutes: 20, maxMinutes: 60, share: 0.5, mode: 'dark', ...over })

describe('the time bins and the limit', () => {
  // The bins are fixed quarter hours and the limit is a slider, so the two
  // have to be reconciled somewhere. The legend used to print "over 60
  // min" directly above the grey "over 60 min away", which were different
  // colours meaning different things by identical words.
  it('stop at the bin containing the limit', () => {
    expect(timeLabels(60)).toEqual([
      'under 15 min',
      '15 to 30 min',
      '30 to 45 min',
      '45 to 60 min',
    ])
  })

  it('phrase the last step against the limit, not the bin', () => {
    expect(timeLabels(50)).toEqual(['under 15 min', '15 to 30 min', '30 to 45 min', '45 to 50 min'])
    expect(timeLabels(40)).toEqual(['under 15 min', '15 to 30 min', '30 to 40 min'])
  })

  it('keep the open ended step only when the limit is past it', () => {
    expect(timeLabels(90)).toEqual([
      'under 15 min',
      '15 to 30 min',
      '30 to 45 min',
      '45 to 60 min',
      '60 to 90 min',
    ])
  })

  it('survive a limit inside the first bin', () => {
    expect(timeLabels(10)).toEqual(['under 10 min'])
    expect(topTimeBin(10)).toBe(0)
  })
})

describe('the colour and the key agree', () => {
  it('never paints a district in a step the legend has dropped', () => {
    // The failure this guards against: at a 60 minute limit a journey of
    // exactly 60 falls in the fifth bin, which the legend does not show,
    // so the map would carry a colour with no explanation on it.
    for (const maxMinutes of [10, 30, 45, 50, 60, 75, 90, 120]) {
      const steps = timeLabels(maxMinutes).length

      for (let minutes = 0; minutes <= maxMinutes; minutes++) {
        const fill = ask({ minutes, maxMinutes, view: 'time' })
        expect(fill.bin).not.toBeNull()
        expect(fill.bin!).toBeLessThan(steps)
        expect(fill.fill).toBe(TIME_RAMP_DARK[fill.bin!])
      }
    }
  })

  it('puts a journey in the step its own label describes', () => {
    expect(binOfTime(0)).toBe(0)
    expect(binOfTime(14)).toBe(0)
    expect(binOfTime(15)).toBe(1)
    expect(binOfTime(44)).toBe(2)
    expect(binOfTime(45)).toBe(3)
    expect(binOfTime(200)).toBe(4)
  })
})

describe('what the two views disagree about', () => {
  it('hatches a district with no rent figures in the budget view', () => {
    const fill = ask({ share: null, view: 'budget' })

    expect(fill.hatched).toBe(true)
    expect(fill.state).toBe('no data')
  })

  it('colours the same district in the time view', () => {
    // The whole point of the view. The hole over the City in the budget
    // map is a gap in the rent statistics, not a gap in the timetable,
    // and the time view is where that becomes obvious.
    const fill = ask({ share: null, view: 'time' })

    expect(fill.hatched).toBe(false)
    expect(fill.bin).toBe(binOfTime(20))
  })

  it('still greys out what is beyond the limit in both', () => {
    for (const view of ['budget', 'time'] as const) {
      expect(ask({ minutes: 90, view }).state).toBe('too far')
      expect(ask({ minutes: null, view }).state).toBe('too far')
    }
  })

  it('still waits for a workplace in both', () => {
    for (const view of ['budget', 'time'] as const) {
      expect(ask({ asked: false, view }).state).toBe('waiting')
    }
  })
})
