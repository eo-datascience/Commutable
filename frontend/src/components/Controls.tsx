import { useState } from 'react'

import { choiceLabel } from '../lib/labels'
import {
  MAX_BUDGET,
  MAX_MINUTES,
  MIN_BUDGET,
  MIN_MINUTES,
} from '../lib/urlState'
import type { Cells, Meta, Place, Query } from '../lib/types'
import { PlaceSearch } from './PlaceSearch'

interface Props {
  meta: Meta
  places: Place[]
  cells: Cells
  query: Query
  workplace: Place | null
  workplace2: Place | null
  onQuery: (patch: Partial<Query>) => void
  onWorkplace: (which: 1 | 2, place: Place | null) => void
}

/**
 * One row, above the map.
 *
 * The order matters and is the order the question is asked in: where you
 * work, what you can pay, what size of home, how long you will travel.
 * Nothing is hidden behind a menu, because every one of the four changes
 * the answer and the visitor should be able to see all four at once while
 * they move one.
 *
 * The second workplace is not shown until it is asked for. Most people
 * have one, and a second empty field sitting there suggests the first one
 * is not enough.
 */
export function Controls({
  meta,
  places,
  cells,
  query,
  workplace,
  workplace2,
  onQuery,
  onWorkplace,
}: Props) {
  const [wantsSecond, setWantsSecond] = useState(workplace2 !== null)
  const showSecond = wantsSecond || workplace2 !== null

  return (
    <div className="controls">
      <PlaceSearch
        places={places}
        cells={cells}
        value={workplace}
        label={showSecond ? 'First workplace' : 'Where you work'}
        placeholder="Station, postcode district or postcode"
        onChange={(place) => onWorkplace(1, place)}
        autoFocus={workplace === null}
      />

      {showSecond ? (
        <PlaceSearch
          places={places}
          cells={cells}
          value={workplace2}
          label="Second workplace"
          placeholder="A partner's work, or a second job"
          onChange={(place) => {
            onWorkplace(2, place)
            if (place === null) setWantsSecond(false)
          }}
        />
      ) : (
        <button
          type="button"
          className="add-second"
          onClick={() => setWantsSecond(true)}
          disabled={workplace === null}
          title={
            workplace === null
              ? 'Choose the first workplace first'
              : 'Add a second workplace, for a partner or a second job'
          }
        >
          Add a second workplace
        </button>
      )}

      <div className="field field-number">
        <label className="field-label" htmlFor="budget">
          Monthly rent you can pay
        </label>
        <div className="money">
          <span aria-hidden="true">£</span>
          <input
            id="budget"
            type="number"
            inputMode="numeric"
            min={MIN_BUDGET}
            max={MAX_BUDGET}
            step={50}
            value={query.budget}
            onChange={(event) => {
              const value = Number.parseInt(event.target.value, 10)
              if (Number.isFinite(value)) {
                onQuery({ budget: Math.min(MAX_BUDGET, Math.max(MIN_BUDGET, value)) })
              }
            }}
          />
        </div>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="bedrooms">
          Size of home
        </label>
        <select
          id="bedrooms"
          value={query.bedrooms}
          onChange={(event) => onQuery({ bedrooms: event.target.value })}
        >
          {meta.bedroom_categories.map((category) => (
            <option key={category} value={category}>
              {choiceLabel(category)}
            </option>
          ))}
        </select>
      </div>

      <div className="field field-slider">
        <label className="field-label" htmlFor="minutes">
          Longest journey{' '}
          <output htmlFor="minutes" className="slider-value">
            {query.maxMinutes} min
          </output>
        </label>
        <input
          id="minutes"
          type="range"
          min={MIN_MINUTES}
          max={Math.min(MAX_MINUTES, meta.times.max_minutes)}
          step={5}
          value={query.maxMinutes}
          onChange={(event) => onQuery({ maxMinutes: Number.parseInt(event.target.value, 10) })}
        />
      </div>
    </div>
  )
}
