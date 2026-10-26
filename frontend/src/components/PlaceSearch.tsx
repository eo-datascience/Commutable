import { useEffect, useId, useRef, useState } from 'react'

import { LookupError, looksLikePostcode, lookupPostcode, searchPlaces } from '../lib/search'
import type { Cells, Place } from '../lib/types'

interface Props {
  places: Place[]
  cells: Cells
  value: Place | null
  label: string
  placeholder: string
  onChange: (place: Place | null) => void
  autoFocus?: boolean
}

/**
 * Where you work.
 *
 * A station name, a postcode district or a full postcode. The first two are
 * matched against the gazetteer shipped with the site, so they answer as
 * fast as the visitor can type. A full postcode goes to postcodes.io, which
 * takes a moment and can fail, so it is only attempted on submit rather
 * than on every keystroke.
 */
export function PlaceSearch({
  places,
  cells,
  value,
  label,
  placeholder,
  onChange,
  autoFocus,
}: Props) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [looking, setLooking] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const listId = useId()

  const suggestions = open && text.trim().length > 0 ? searchPlaces(places, text) : []

  // Clicking away closes the list. Without this it stays open over the map
  // and swallows the first click on a district.
  useEffect(() => {
    if (!open) return
    const away = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])

  const choose = (place: Place) => {
    onChange(place)
    setText('')
    setOpen(false)
    setError(null)
  }

  const submit = async () => {
    const typed = text.trim()
    if (typed.length === 0) return

    const best = suggestions[0]
    if (best && !looksLikePostcode(typed)) {
      choose(best)
      return
    }

    if (looksLikePostcode(typed)) {
      setLooking(true)
      setError(null)
      try {
        const { place } = await lookupPostcode(cells, typed)
        choose(place)
      } catch (caught) {
        setError(
          caught instanceof LookupError
            ? caught.message
            : 'Something went wrong looking that up. Try a station name instead.',
        )
      } finally {
        setLooking(false)
      }
      return
    }

    if (best) {
      choose(best)
      return
    }
    setError(`Nothing called "${typed}". Try a station, a postcode district like SE10, or a full postcode.`)
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      setHighlight((h) => Math.min(h + 1, Math.max(suggestions.length - 1, 0)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlight((h) => Math.max(h - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const picked = suggestions[highlight]
      if (picked) choose(picked)
      else void submit()
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  if (value) {
    return (
      <div className="field field-chosen">
        <span className="field-label">{label}</span>
        <button
          type="button"
          className="chosen"
          onClick={() => {
            onChange(null)
            setText('')
          }}
          aria-label={`${value.name}. Press to change.`}
        >
          <span className="chosen-name">{value.name}</span>
          <span className="chosen-clear" aria-hidden="true">
            change
          </span>
        </button>
      </div>
    )
  }

  return (
    <div className="field" ref={box}>
      <label className="field-label" htmlFor={listId}>
        {label}
      </label>
      <div className="combo">
        <input
          id={listId}
          type="text"
          value={text}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          role="combobox"
          aria-expanded={suggestions.length > 0}
          aria-controls={`${listId}-list`}
          aria-autocomplete="list"
          autoFocus={autoFocus}
          onChange={(event) => {
            setText(event.target.value)
            setOpen(true)
            setHighlight(0)
            setError(null)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {looking ? <span className="combo-busy">looking…</span> : null}

        {suggestions.length > 0 ? (
          <ul className="combo-list" id={`${listId}-list`} role="listbox">
            {suggestions.map((place, index) => (
              <li key={`${place.kind}-${place.name}`} role="option" aria-selected={index === highlight}>
                <button
                  type="button"
                  className={index === highlight ? 'is-highlighted' : undefined}
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => choose(place)}
                >
                  <span className="combo-name">{place.name}</span>
                  <span className="combo-kind">{place.kind}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {error ? <p className="field-error">{error}</p> : null}
    </div>
  )
}
