import { useCallback, useEffect, useMemo, useState } from 'react'

import { Answer } from './components/Answer'
import { Controls } from './components/Controls'
import { Legend } from './components/Legend'
import { Logo } from './components/Logo'
import { MapView } from './components/MapView'
import { Notes } from './components/Notes'
import { DataError, loadDataset, loadTimes } from './lib/data'
import { collectiveLabel } from './lib/labels'
import { computeResults, rankDistricts, summarise } from './lib/results'
import type { Mode } from './lib/scale'
import type { Dataset, Place, Query } from './lib/types'
import { DEFAULT_QUERY, parseQuery, syncUrl, toSearch } from './lib/urlState'

const money = new Intl.NumberFormat('en-GB', {
  style: 'currency',
  currency: 'GBP',
  maximumFractionDigits: 0,
})

export function App() {
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [query, setQuery] = useState<Query>(DEFAULT_QUERY)
  const [timeArrays, setTimeArrays] = useState<Uint16Array[]>([])
  const [loadingTimes, setLoadingTimes] = useState(false)
  const [hovered, setHovered] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>(preferredMode)
  const [notesOpen, setNotesOpen] = useState(false)

  // Written to the root element rather than to the wrapper below, so that
  // `body`, which sits above the wrapper and sets the inherited text
  // colour, resolves the themed variables too. See styles.css.
  useEffect(() => {
    document.documentElement.dataset.theme = mode
    return () => {
      delete document.documentElement.dataset.theme
    }
  }, [mode])

  // The two workplaces, kept beside the query because the query holds only
  // what fits in a URL: a grid cell and a name. The full place is needed to
  // draw the pin.
  const [workplaces, setWorkplaces] = useState<(Place | null)[]>([null, null])

  useEffect(() => {
    loadDataset()
      .then((loaded) => {
        setDataset(loaded)
        const fromUrl = parseQuery(window.location.search, loaded.meta.bedroom_categories)
        setQuery(fromUrl)
        // A shared link carries a cell and a label but no coordinates, so
        // the pin is placed from the gazetteer where the label matches and
        // from the grid cell's own centre otherwise.
        setWorkplaces([
          placeFromQuery(loaded, fromUrl.workplace, fromUrl.workplaceName),
          placeFromQuery(loaded, fromUrl.workplace2, fromUrl.workplaceName2),
        ])
      })
      .catch((caught: unknown) => {
        setFailure(
          caught instanceof DataError
            ? caught.message
            : 'The map data could not be loaded. Reloading the page may fix it.',
        )
      })
  }, [])

  // Journey times follow whichever workplaces are set. Both are fetched
  // together so the map never renders with one workplace applied and the
  // other not, which would show places that suit one person and not the
  // other as though they suited both.
  useEffect(() => {
    if (!dataset) return
    const cells = [query.workplace, query.workplace2].filter((c): c is string => c !== null)
    if (cells.length === 0) {
      setTimeArrays([])
      return
    }

    let cancelled = false
    setLoadingTimes(true)
    Promise.all(cells.map((cell) => loadTimes(cell, dataset.meta.districts.length)))
      .then((arrays) => {
        if (!cancelled) setTimeArrays(arrays)
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        setTimeArrays([])
        setFailure(
          caught instanceof DataError
            ? caught.message
            : 'Journey times for that workplace could not be loaded.',
        )
      })
      .finally(() => {
        if (!cancelled) setLoadingTimes(false)
      })

    return () => {
      cancelled = true
    }
  }, [dataset, query.workplace, query.workplace2])

  useEffect(() => {
    if (dataset) syncUrl(query)
  }, [dataset, query])

  const onQuery = useCallback((patch: Partial<Query>) => {
    setQuery((current) => ({ ...current, ...patch }))
  }, [])

  const onWorkplace = useCallback((which: 1 | 2, place: Place | null) => {
    setWorkplaces((current) => {
      const next = [...current]
      next[which - 1] = place
      // Dropping the first workplace promotes the second, rather than
      // leaving a gap that would make the remaining journey look like a
      // second person's.
      if (which === 1 && place === null && next[1]) {
        next[0] = next[1]
        next[1] = null
      }
      return next
    })
    setQuery((current) => {
      if (which === 1 && place === null) {
        return current.workplace2 !== null
          ? {
              ...current,
              workplace: current.workplace2,
              workplaceName: current.workplaceName2,
              workplace2: null,
              workplaceName2: null,
            }
          : { ...current, workplace: null, workplaceName: null }
      }
      return which === 1
        ? { ...current, workplace: place?.cell ?? null, workplaceName: place?.name ?? null }
        : { ...current, workplace2: place?.cell ?? null, workplaceName2: place?.name ?? null }
    })
  }, [])

  const chosen = useMemo(
    () => workplaces.filter((place): place is Place => place !== null),
    [workplaces],
  )

  // Rents do not depend on a journey, so results are computed before any
  // workplace is chosen: clicking a district on the opening screen should
  // say what it costs rather than silently do nothing.
  //
  // A workplace whose times are still downloading is the opposite case.
  // Half an answer is worse than none there, because every journey would
  // read as null, the map would paint the whole city as too far and the
  // panel would announce that nowhere is within reach.
  const results = useMemo(() => {
    if (!dataset) return []
    const wanted = (query.workplace ? 1 : 0) + (query.workplace2 ? 1 : 0)
    if (timeArrays.length !== wanted) return []
    return computeResults({ dataset, query, timeArrays })
  }, [dataset, query, timeArrays])

  const ranked = useMemo(() => rankDistricts(results), [results])
  const summary = useMemo(() => summarise(results, ranked, query.maxMinutes), [
    results,
    ranked,
    query.maxMinutes,
  ])

  // In rank order, because the map drops labels that collide and keeps the
  // earlier one. The selected district goes first: it is the one the visitor
  // asked about, so it should never lose a collision to a better ranked
  // neighbour.
  const labelled = useMemo(() => {
    const order = ranked.slice(0, 8).map((entry) => entry.district)
    if (query.selected && !order.includes(query.selected)) order.push(query.selected)
    return query.selected
      ? [query.selected, ...order.filter((d) => d !== query.selected)]
      : order
  }, [ranked, query.selected])

  const selected = useMemo(
    () => results.find((result) => result.district === query.selected) ?? null,
    [results, query.selected],
  )

  const hasNoData = useMemo(
    () => results.some((result) => result.rent === null && result.minutes !== null),
    [results],
  )

  if (failure) {
    return (
      <main className="shell shell-failed">
        <h1>Commutable</h1>
        <p className="failure">{failure}</p>
      </main>
    )
  }

  if (!dataset) {
    return (
      <main className="shell shell-loading">
        <h1>Commutable</h1>
        <p>Loading the map…</p>
      </main>
    )
  }

  const size = collectiveLabel(query.bedrooms)

  return (
    <div className="shell">
      {/* Visible only once focused. The map is one tab stop rather than
          274 now, but it is still between the controls and the answer,
          and somebody who wants the figures should not have to pass
          through a picture to reach them. */}
      <a className="skip" href="#answer">
        Skip to the results
      </a>

      {dataset.meta.synthetic ? (
        <p className="synthetic" role="alert">
          <strong>These numbers are invented.</strong> {dataset.meta.synthetic_warning}
        </p>
      ) : null}

      <header className="top">
        <div className="brand">
          <Logo />
          <div>
            <h1>Commutable</h1>
            <p>Where your rent reaches, measured in minutes</p>
          </div>
        </div>
        <div className="top-actions">
          <ShareButton query={query} />
          <button
            type="button"
            className="ghost"
            onClick={() => setNotesOpen(true)}
            aria-expanded={notesOpen}
          >
            How this works
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => setMode(mode === 'dark' ? 'light' : 'dark')}
            aria-label={`Switch to ${mode === 'dark' ? 'light' : 'dark'} colours`}
          >
            {mode === 'dark' ? 'Light' : 'Dark'}
          </button>
        </div>
      </header>

      <Controls
        meta={dataset.meta}
        places={dataset.places}
        cells={dataset.cells}
        query={query}
        workplace={workplaces[0] ?? null}
        workplace2={workplaces[1] ?? null}
        onQuery={onQuery}
        onWorkplace={onWorkplace}
      />

      <div className="stage">
        <div className="stage-map">
          <MapView
            dataset={dataset}
            results={results}
            maxMinutes={query.maxMinutes}
            mode={mode}
            selected={query.selected}
            view={query.view}
            labelled={labelled}
            highlighted={hovered}
            workplaces={chosen}
            onSelect={(district) => onQuery({ selected: district })}
          />
          {chosen.length > 0 && !loadingTimes ? (
            <Legend
              size={size}
              budget={money.format(query.budget)}
              maxMinutes={query.maxMinutes}
              hasNoData={hasNoData}
              view={query.view}
              onView={(view) => onQuery({ view })}
            />
          ) : null}
          {loadingTimes ? <p className="map-busy">Working out journeys…</p> : null}
        </div>

        <aside className="stage-answer" id="answer" tabIndex={-1}>
          <Answer
            meta={dataset.meta}
            query={query}
            workplaces={chosen}
            results={results}
            ranked={ranked}
            summary={summary}
            mode={mode}
            selected={selected}
            onSelect={(district) => onQuery({ selected: district })}
            onHover={setHovered}
          />
        </aside>
      </div>

      {notesOpen ? <Notes meta={dataset.meta} onClose={() => setNotesOpen(false)} /> : null}
    </div>
  )
}

function ShareButton({ query }: { query: Query }) {
  const [said, setSaid] = useState(false)

  if (query.workplace === null) return null

  return (
    <button
      type="button"
      className="ghost"
      onClick={() => {
        const url = `${window.location.origin}${window.location.pathname}${toSearch(query)}`
        navigator.clipboard
          ?.writeText(url)
          .then(() => {
            setSaid(true)
            window.setTimeout(() => setSaid(false), 2200)
          })
          .catch(() => {
            // Clipboard access can be refused. The address bar already holds
            // the same link, so saying nothing is wrong and apologising is
            // worse than pointing at it.
            setSaid(false)
            window.prompt('Copy this link', url)
          })
      }}
    >
      {said ? 'Link copied' : 'Copy link'}
    </button>
  )
}

function preferredMode(): Mode {
  // The OS setting, read once. There is deliberately no stored preference:
  // the toggle is for this visit, and a site that remembers one thing in
  // local storage tends to grow to remembering several.
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function placeFromQuery(dataset: Dataset, cell: string | null, name: string | null): Place | null {
  if (cell === null) return null

  const named = name
    ? dataset.places.find((place) => place.name === name && place.cell === cell)
    : undefined
  if (named) return named

  const index = dataset.cells.ids.indexOf(cell)
  if (index === -1) return null

  return {
    name: name ?? 'your workplace',
    kind: 'postcode',
    cell,
    lon: dataset.cells.lon[index] ?? 0,
    lat: dataset.cells.lat[index] ?? 0,
  }
}
