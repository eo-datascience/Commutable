import { districtName } from '../lib/districts'
import { collectiveLabel } from '../lib/labels'
import { toFigures, type Ranked, type Summary } from '../lib/results'
import { binOf, type Mode } from '../lib/scale'
import type { DistrictResult, Meta, Place, Query } from '../lib/types'

const money = new Intl.NumberFormat('en-GB', {
  style: 'currency',
  currency: 'GBP',
  maximumFractionDigits: 0,
})

const percent = (share: number) => `${Math.round(share * 100)}%`

interface Props {
  meta: Meta
  query: Query
  workplaces: Place[]
  results: DistrictResult[]
  ranked: Ranked[]
  summary: Summary
  mode: Mode
  selected: DistrictResult | null
  onSelect: (district: string | null) => void
  onHover: (district: string | null) => void
}

/**
 * The answer in words, beside the answer in colour.
 *
 * The map shows the shape of the answer; this says what it is. Somebody who
 * does not want to read a map should be able to get what they came for from
 * the first two lines here, which is why the headline is a sentence rather
 * than a figure with a caption.
 */
export function Answer({
  meta,
  query,
  workplaces,
  ranked,
  summary,
  selected,
  onSelect,
  onHover,
}: Props) {
  // Clicking the map is the first thing most people try, and until a
  // workplace is set there is no journey to report. There is still rent,
  // though, and rent is half the answer, so the district opens with what it
  // costs and the invitation moves to one line above it.
  if (workplaces.length === 0) {
    return (
      <div className="answer answer-empty">
        <h2>Where can you actually afford to live?</h2>
        {selected ? (
          <>
            <p>
              Here is what {selected.district} rents for. Say where you work above and every
              district gets shaded by how much of its market {money.format(query.budget)}{' '}
              reaches, with everywhere out of reach greyed out.
            </p>
            <DistrictDetail
              meta={meta}
              result={selected}
              query={query}
              workplaces={workplaces}
              lowSample={meta.rent.low_sample}
              onClose={() => onSelect(null)}
            />
          </>
        ) : (
          <>
            <p>
              Say where you work and what you can pay. The map shades every postcode district
              in {meta.city.name} by how much of its rental market your budget reaches, and
              greys out everywhere you could not get to in time.
            </p>
            <p className="answer-note">
              Journeys are measured on the published timetable, not as the crow flies.
            </p>
          </>
        )}
      </div>
    )
  }

  const size = collectiveLabel(query.bedrooms)

  // The same districts in both views, ordered by whichever question the
  // map is currently answering. Deliberately a reordering of `ranked`
  // rather than a second filter: the list and the headline above it have
  // to be the same set, and that was already got wrong once.
  const shown =
    query.view === 'time' ? [...ranked].sort((a, b) => a.minutes - b.minutes) : ranked

  return (
    <div className="answer">
      <Headline
        summary={summary}
        query={query}
        size={size}
        workplaceCount={workplaces.length}
      />

      {selected ? (
        <DistrictDetail
          meta={meta}
          result={selected}
          query={query}
          workplaces={workplaces}
          lowSample={meta.rent.low_sample}
          onClose={() => onSelect(null)}
        />
      ) : null}

      {shown.length > 0 ? (
        <section className="ranked">
          <h3>
            {query.view === 'time'
              ? 'Quickest within your budget'
              : 'Most choice within your budget'}
          </h3>
          <ol>
            {shown.map((entry) => (
              <li key={entry.district}>
                <button
                  type="button"
                  className={entry.district === selected?.district ? 'is-selected' : undefined}
                  onClick={() => onSelect(entry.district)}
                  onMouseEnter={() => onHover(entry.district)}
                  onMouseLeave={() => onHover(null)}
                >
                  <span className="ranked-district">
                    {entry.district}
                    {districtName(meta, entry.district) ? (
                      <span className="ranked-name">{districtName(meta, entry.district)}</span>
                    ) : null}
                  </span>
                  <span className="ranked-share">
                    <span
                      className="swatch"
                      data-bin={binOf(entry.share)}
                      aria-hidden="true"
                    />
                    {percent(entry.share)}
                  </span>
                  <span className="ranked-minutes">{entry.minutes} min</span>
                  <span className="ranked-median">{money.format(entry.rent[0])}</span>
                </button>
              </li>
            ))}
          </ol>
          <p className="ranked-legend">
            Share of {size} at or under {money.format(query.budget)}, then the journey
            and the district's median rent.
          </p>
        </section>
      ) : null}
    </div>
  )
}

function Headline({
  summary,
  query,
  size,
  workplaceCount,
}: {
  summary: Summary
  query: Query
  size: string
  workplaceCount: number
}) {
  const both = workplaceCount > 1 ? ' of both workplaces' : ''

  if (summary.withinLimit === 0) {
    return (
      <div className="headline">
        <h2>Nowhere is within {query.maxMinutes} minutes{both}.</h2>
        <p>Try a longer journey.</p>
      </div>
    )
  }

  if (summary.withData === 0) {
    return (
      <div className="headline">
        <h2>
          {summary.withinLimit} districts are within {query.maxMinutes} minutes{both}, but none
          has published rent figures for {size}.
        </h2>
        <p>
          Rents are only published where enough tenancies were recorded. Try a different size
          of home.
        </p>
      </div>
    )
  }

  if (summary.worthLooking === 0) {
    return (
      <div className="headline">
        <h2>
          {money.format(query.budget)} does not reach {size} anywhere within{' '}
          {query.maxMinutes} minutes{both}.
        </h2>
        {summary.cheapestMedian ? (
          <p>
            The cheapest is {summary.cheapestMedian.district} at{' '}
            {money.format(summary.cheapestMedian.median)} a month, {summary.cheapestMedian.minutes}{' '}
            minutes away. Raising the budget or the time limit will open things up.
          </p>
        ) : (
          <p>Try a longer journey, or a larger budget.</p>
        )}
      </div>
    )
  }

  const best = summary.best
  return (
    <div className="headline">
      <h2>
        {summary.worthLooking} {summary.worthLooking === 1 ? 'district works' : 'districts work'} on{' '}
        {money.format(query.budget)} within {query.maxMinutes} minutes{both}.
      </h2>
      {best ? (
        <p>
          {best.district} has the most choice: {percent(best.share)} of its {size} are in
          budget, {best.minutes} minutes away.
          {summary.nearest && summary.nearest.district !== best.district ? (
            <>
              {' '}
              The closest is {summary.nearest.district} at {summary.nearest.minutes} minutes,
              with {percent(summary.nearest.share)}.
            </>
          ) : null}
        </p>
      ) : null}
      {summary.withData < summary.withinLimit ? (
        <p className="answer-note">
          {summary.withinLimit - summary.withData} districts inside your limit have no published
          figures for {size} and are hatched on the map.
        </p>
      ) : null}
    </div>
  )
}

function DistrictDetail({
  meta,
  result,
  query,
  workplaces,
  lowSample,
  onClose,
}: {
  meta: Meta
  result: DistrictResult
  query: Query
  workplaces: Place[]
  lowSample: number
  onClose: () => void
}) {
  const row = result.rent
  const figures = row ? toFigures(row) : null

  return (
    <section className="detail">
      <header>
        <h3>
          {result.district}
          {districtName(meta, result.district) ? (
            <span className="detail-name">{districtName(meta, result.district)}</span>
          ) : null}
        </h3>
        <button type="button" onClick={onClose} aria-label="Close this district">
          close
        </button>
      </header>

      <dl>
        {workplaces.length === 1 ? (
          <div>
            <dt>Journey</dt>
            <dd>
              {result.minutes === null
                ? `over ${query.maxMinutes} minutes`
                : `${result.minutes} min`}
            </dd>
          </div>
        ) : (
          workplaces.map((place, index) => (
            <div key={`${place.cell}-${index}`}>
              <dt>To {place.name}</dt>
              <dd>
                {result.minutesEach[index] === null
                  ? 'no journey found'
                  : `${result.minutesEach[index]} min`}
              </dd>
            </div>
          ))
        )}

        {figures && result.share !== null ? (
          <>
            <div>
              <dt>In your budget</dt>
              <dd>
                <span className="swatch" data-bin={binOf(result.share)} aria-hidden="true" />
                {percent(result.share)}
              </dd>
            </div>
            <div>
              <dt>Median rent</dt>
              <dd>{money.format(figures.median)}</dd>
            </div>
            <div>
              <dt>Middle half of the market</dt>
              <dd>
                {money.format(figures.lowerQuartile)} to {money.format(figures.upperQuartile)}
              </dd>
            </div>
            <div>
              <dt>
                {query.budget >= figures.median ? 'Your budget is above the median by' : 'Short of the median by'}
              </dt>
              <dd>{money.format(Math.abs(query.budget - figures.median))}</dd>
            </div>
            <div>
              <dt>Based on</dt>
              <dd>{figures.sample.toLocaleString('en-GB')} tenancies</dd>
            </div>
          </>
        ) : (
          <div>
            <dt>Rent</dt>
            <dd>No figures published for this size of home here.</dd>
          </div>
        )}
      </dl>

      {figures && figures.sample < lowSample ? (
        <p className="detail-caveat">
          Thin evidence here. These figures come from {figures.sample} recorded tenancies, so
          treat them as a rough guide rather than a market rate. They are published figures
          either way, not estimates.
        </p>
      ) : null}

      {figures && !figures.wellFitted ? (
        <p className="detail-caveat">
          The share in budget is rougher here than elsewhere: the published quartiles for this
          district do not sit neatly on the curve used to estimate it. The median and the
          quartile range above are published figures and are unaffected.
        </p>
      ) : null}
    </section>
  )
}
