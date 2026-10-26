import { useEffect, useRef } from 'react'

import type { Meta } from '../lib/types'

interface Props {
  meta: Meta
  onClose: () => void
}

const DATE = new Intl.DateTimeFormat('en-GB', { dateStyle: 'long' })

function when(iso: string | undefined): string {
  if (!iso) return 'not recorded'
  const parsed = new Date(iso)
  return Number.isNaN(parsed.valueOf()) ? iso : DATE.format(parsed)
}

/**
 * How it works, what it is made of, and what it cannot tell you.
 *
 * The limitations come from the published metadata rather than being
 * written here, so they are generated from the same configuration that
 * produced the numbers and cannot describe a version of the site that no
 * longer exists.
 */
export function Notes({ meta, onClose }: Props) {
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    panel.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="How this works"
        tabIndex={-1}
        ref={panel}
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <h2>How this works</h2>
          <button type="button" onClick={onClose}>
            close
          </button>
        </header>

        <section>
          <h3>The journey</h3>
          <p>
            Every journey on this map was computed in advance by a routing engine running
            over the real street network and the published timetables for rail, tube, DLR,
            tram and bus. Nothing is estimated from distance, and nothing is left out: a
            route that is quickest by bus is found as readily as one by train.
          </p>
          <p>
            A journey time here is the <strong>median across {meta.times.departure_window}</strong>{' '}
            on a weekday, not a single departure. One departure measures the timetable's luck:
            leave four minutes later and you can wait a quarter of an hour. The median is the
            figure you live with across a week.
          </p>
          <p>
            A district's time is the median across the {meta.grid.cell_metres}m squares inside
            it, weighted by how much housing each square holds, so a district is not judged by
            whichever single point happened to be picked.
          </p>
          <p>
            {/* reachable_share is measured over district-to-square pairs,
                not over the full cell matrix. The first version of this
                paragraph quoted it against the 8.4 million square-to-square
                journeys, which is a different and lower figure. The two are
                a dozen points apart, so the sentence has to say which one
                it is quoting. */}
            The matrix behind this is {meta.grid.cells.toLocaleString('en-GB')} squares routed
            against every other, which is{' '}
            {(meta.grid.cells ** 2 / 1_000_000).toFixed(1)} million journeys. Collapsed to what
            the site serves, a time from every square to each of the{' '}
            {meta.districts.length} districts,{' '}
            <strong>
              {Math.round(meta.times.reachable_share * 100)}% of those pairs have a route
            </strong>{' '}
            inside the {meta.times.max_minutes} minute ceiling.
            {Math.round(meta.times.reachable_share * 100) < 100 ? (
              <>
                {' '}
                The rest are places you cannot get between on public transport in under two
                hours, which in a city this size is mostly one edge to the opposite edge.
              </>
            ) : null}
          </p>
        </section>

        <section>
          <h3>The rent</h3>
          <p>{meta.rent.sigma_note}</p>
          <p>
            The median and the quartile range shown for a district are the figures ONS
            published. Nothing on this site replaces them with an estimate.
          </p>
          <p>
            Figures are published only where enough tenancies were recorded. A district with
            fewer than {meta.rent.min_sample} is shown as having no figures rather than being
            coloured from a handful of lettings.
          </p>
        </section>

        <section>
          <h3>What it cannot tell you</h3>
          <ul className="limits">
            {meta.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </section>

        <section>
          <h3>Where the data comes from</h3>
          <table className="sources">
            <tbody>
              {meta.attributions.map((source) => (
                <tr key={source.name}>
                  <th scope="row">{source.name}</th>
                  <td>
                    <a href={source.url} target="_blank" rel="noreferrer noopener">
                      {source.source}
                    </a>
                    <span className="licence">{source.licence}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <dl className="vintages">
            <div>
              <dt>Rent figures obtained</dt>
              <dd>{when(meta.data_vintages.rent)}</dd>
            </div>
            <div>
              <dt>Timetable obtained</dt>
              <dd>{when(meta.data_vintages.timetable)}</dd>
            </div>
            <div>
              <dt>Journeys computed for</dt>
              <dd>{when(meta.times.departure_date)}</dd>
            </div>
            <div>
              <dt>This data built</dt>
              <dd>{when(meta.built)}</dd>
            </div>
          </dl>
        </section>

        <section>
          <h3>Your question stays in the address bar</h3>
          <p>
            There are no accounts and no server. Where you work, what you can pay and the size
            of home you want are held in the URL and nowhere else, which is why copying the
            link shares the exact answer you are looking at. Nothing about your search is sent
            anywhere, with one exception: typing a full postcode looks it up at postcodes.io,
            which is how the coordinates are found.
          </p>
        </section>
      </div>
    </div>
  )
}
