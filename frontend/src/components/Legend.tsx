import { BIN_LABELS, timeLabels, type View } from '../lib/scale'

interface Props {
  /** The bedroom category in words, for the legend's own sentence. */
  size: string
  budget: string
  maxMinutes: number
  hasNoData: boolean
  view: View
  onView: (view: View) => void
}

/**
 * The key, over the map, and the switch for what the map is keyed on.
 *
 * It is a sentence with swatches in it rather than a titled block of
 * squares, because the thing being encoded takes a sentence to say: the
 * colour is not "rent" or "price", it is the share of one district's homes
 * of one size that one budget reaches.
 *
 * The view switch lives here rather than up in the controls because this
 * is where the page says what the colour means, and a control that changes
 * what the colour means belongs beside that sentence rather than three
 * inches away among the inputs that change the data.
 */
export function Legend({ size, budget, maxMinutes, hasNoData, view, onView }: Props) {
  const time = view === 'time'
  const labels: readonly string[] = time ? timeLabels(maxMinutes) : BIN_LABELS

  return (
    <div className="legend">
      <div className="legend-views" role="group" aria-label="What the colours show">
        <button
          type="button"
          className={time ? undefined : 'is-on'}
          aria-pressed={!time}
          onClick={() => onView('budget')}
        >
          In budget
        </button>
        <button
          type="button"
          className={time ? 'is-on' : undefined}
          aria-pressed={time}
          onClick={() => onView('time')}
        >
          Journey time
        </button>
      </div>

      <p className="legend-lead">
        {time ? 'How long the journey takes' : `Share of ${size} at or under ${budget}`}
      </p>

      <ol className={`legend-ramp${time ? ' is-time' : ''}`}>
        {labels.map((label, bin) => (
          <li key={label}>
            <span className="swatch" data-bin={bin} aria-hidden="true" />
            <span className="legend-label">{label}</span>
          </li>
        ))}
      </ol>

      <ul className="legend-rest">
        <li>
          <span className="swatch swatch-out" aria-hidden="true" />
          {/* In the time view the steps are already phrased against the
              limit, so repeating the number here would put the same words
              on two different colours. */}
          {time ? 'beyond your limit' : `over ${maxMinutes} min away`}
        </li>
        {/* The time view has no missing state to explain. A district with
            no published rent still has a journey, so nothing is hatched
            and saying otherwise would invent a gap. */}
        {hasNoData && !time ? (
          <li>
            <span className="swatch swatch-nodata" aria-hidden="true" />
            no figures published
          </li>
        ) : null}
      </ul>
    </div>
  )
}
