import { geoMercator, geoPath } from 'd3-geo'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { districtLabel, districtName } from '../lib/districts'
import { ARROWS, nearestInDirection } from '../lib/navigate'
import { fillFor, type Mode, type View } from '../lib/scale'
import type { Dataset, DistrictResult, Meta, Place } from '../lib/types'

// Why this is an SVG and not a map library
// ---------------------------------------
// There is no basemap. The city is drawn from its own 274 postcode
// districts and its outline, and nothing else: no tiles, no attribution
// bar, no API key, no request to anybody else's server.
//
// That makes a tile library the wrong tool. MapLibre is some 800KB
// compressed and exists to stitch raster or vector tiles together under an
// interactive camera. With no tiles to stitch, all that is needed is 274
// paths, and 274 paths in an SVG is nothing: it draws in a frame, every
// shape is a DOM node that can be hovered and focused with no hit testing
// of our own, and the whole thing is styled in CSS and themes with the
// rest of the page.
//
// The cost is that panning and zooming have to be written here. They are
// one transform and about forty lines.

interface Props {
  dataset: Dataset
  results: DistrictResult[]
  maxMinutes: number
  mode: Mode
  selected: string | null
  /**
   * Districts to label on the map, best first. The order matters: when two
   * labels collide the earlier one survives, so this must be rank order and
   * not the order the polygons happen to be drawn in.
   */
  labelled: string[]
  workplaces: Place[]
  /** Hovered in the ranked list beside the map, so the two stay in step. */
  highlighted: string | null
  /** What the colours mean: the share in budget, or the journey time. */
  view: View
  onSelect: (district: string | null) => void
}

const MIN_SCALE = 1
const MAX_SCALE = 8

/** Wide enough for "No rent figures published for this size" on two lines. */
const TIP_WIDTH = 230

const money = new Intl.NumberFormat('en-GB', {
  style: 'currency',
  currency: 'GBP',
  maximumFractionDigits: 0,
})

export function MapView({
  dataset,
  results,
  maxMinutes,
  mode,
  selected,
  labelled,
  workplaces,
  highlighted,
  view,
  onSelect,
}: Props) {
  const wrap = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 900, height: 700 })
  // The pan and zoom transform. Named for what it is, so it does not
  // collide with the `view` prop, which is what the colours mean.
  const [camera, setCamera] = useState({ scale: 1, x: 0, y: 0 })
  const [pointed, setPointed] = useState<string | null>(null)
  // Where to put the tooltip. Set once when the pointer enters a district
  // rather than tracked on every move: a tooltip that follows the cursor
  // around inside one shape is harder to read than one that stays put, and
  // this is one state update per district rather than one per frame.
  const [tipAt, setTipAt] = useState<{ x: number; y: number } | null>(null)
  // Either pointing at the map or at the list beside it. Both mean the same
  // thing to the map, so they are resolved to one value here.
  const hovered = pointed ?? highlighted
  const drag = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null)

  // The SVG fills whatever space the layout gives it, so the projection has
  // to be refitted when that changes. A ResizeObserver rather than a window
  // listener, because the panel beside it can open and close without the
  // window changing size at all.
  useEffect(() => {
    const element = wrap.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setSize({ width, height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const { paths, labelPoints, pins } = useMemo(() => {
    // Mercator because it is what every map of a city is drawn in, so the
    // shapes match the ones people already know. Over 40km the distortion
    // is a fraction of a per cent and nothing here is measured off the
    // picture.
    //
    // Fitted to the districts rather than the city outline, because the
    // districts are what is drawn. Postcode districts were drawn for
    // delivery rounds and spill past the administrative boundary, so
    // fitting to the outline clipped ten pixels off the top and bottom of
    // the map: not enough to look broken, just enough to shave the edge
    // off Enfield and Croydon.
    const projection = geoMercator().fitExtent(
      [
        [16, 16],
        [Math.max(size.width - 16, 32), Math.max(size.height - 16, 32)],
      ],
      dataset.districts as Parameters<ReturnType<typeof geoMercator>['fitExtent']>[1],
    )
    const path = geoPath(projection)

    return {
      paths: dataset.districts.features.map((feature) => ({
        district: feature.properties.district,
        d: path(feature) ?? '',
      })),
      labelPoints: new Map(
        dataset.districts.features.map((feature) => [
          feature.properties.district,
          path.centroid(feature),
        ]),
      ),
      pins: workplaces.map((place) => ({
        place,
        at: projection([place.lon, place.lat]),
      })),
    }
  }, [dataset, size.width, size.height, workplaces])

  // Nothing has been asked until a workplace is chosen, and the map says so
  // rather than greying the city out as though everywhere had been ruled out.
  const asked = workplaces.length > 0

  const byPath = useMemo(() => new Map(paths.map((p) => [p.district, p])), [paths])

  // Hovered first, so it survives any collision with a better ranked label.
  const labelOrder = useMemo(() => {
    const order = hovered ? [hovered, ...labelled.filter((d) => d !== hovered)] : labelled
    return order
  }, [labelled, hovered])

  const byDistrict = useMemo(() => {
    const map = new Map<string, DistrictResult>()
    for (const result of results) map.set(result.district, result)
    return map
  }, [results])

  // Which district currently holds the map's single tab stop.
  //
  // It follows the selection when there is one, so tabbing back to the map
  // after reading a district's panel lands on that district rather than
  // somewhere across the city. Otherwise it is the best ranked district,
  // which is the one a visitor is most likely to want, and before any
  // workplace is chosen it is simply the first in the published order so
  // that the map is reachable at all.
  const [keyboardAt, setKeyboardAt] = useState<string | null>(null)
  const active = useRef<SVGPathElement>(null)

  const atNow =
    keyboardAt ?? selected ?? labelled[0] ?? dataset.meta.districts[0] ?? null

  // Focus follows the arrow keys. Without this the browser keeps focus on
  // the element that was tabbed to, so the outline stops moving and a
  // screen reader never announces the district the visitor moved onto.
  const moveTo = useCallback((district: string) => {
    setKeyboardAt(district)
    // After the re-render that gives this district the tab stop.
    requestAnimationFrame(() => active.current?.focus())
  }, [])

  const neighbour = useCallback(
    (from: string, dx: number, dy: number) => nearestInDirection(labelPoints, from, dx, dy),
    [labelPoints],
  )

  const onKey = useCallback(
    (event: React.KeyboardEvent, district: string, isSelected: boolean) => {
      const direction = ARROWS[event.key]
      if (direction) {
        const next = neighbour(district, direction[0], direction[1])
        // Swallowed either way: an arrow press on the map that scrolled
        // the page instead would be worse than one that did nothing.
        event.preventDefault()
        if (next) moveTo(next)
        return
      }

      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        onSelect(isSelected ? null : district)
        return
      }

      if (event.key === 'Escape' && isSelected) {
        event.preventDefault()
        onSelect(null)
      }
    },
    [neighbour, moveTo, onSelect],
  )

  const onWheel = useCallback((event: React.WheelEvent) => {
    event.preventDefault()
    setCamera((current) => {
      const factor = Math.exp(-event.deltaY * 0.0015)
      const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, current.scale * factor))
      if (scale === current.scale) return current

      // Zoom toward the pointer rather than the centre, so the thing the
      // visitor is looking at stays where they are looking.
      const box = wrap.current?.getBoundingClientRect()
      const px = box ? event.clientX - box.left : size.width / 2
      const py = box ? event.clientY - box.top : size.height / 2
      const ratio = scale / current.scale

      return {
        scale,
        x: px - (px - current.x) * ratio,
        y: py - (py - current.y) * ratio,
      }
    })
  }, [size.width, size.height])

  const onPointerDown = (event: React.PointerEvent) => {
    if (event.button !== 0) return
    drag.current = { x: camera.x, y: camera.y, startX: event.clientX, startY: event.clientY }
    ;(event.target as Element).setPointerCapture?.(event.pointerId)
  }

  const onPointerMove = (event: React.PointerEvent) => {
    const start = drag.current
    if (!start) return
    setCamera((current) => ({
      ...current,
      x: start.x + (event.clientX - start.startX),
      y: start.y + (event.clientY - start.startY),
    }))
  }

  const onPointerUp = () => {
    drag.current = null
  }

  const moved = (event: React.MouseEvent) =>
    drag.current !== null &&
    (Math.abs(event.clientX - drag.current.startX) > 3 ||
      Math.abs(event.clientY - drag.current.startY) > 3)

  const reset = () => setCamera({ scale: 1, x: 0, y: 0 })

  return (
    <div className="map" ref={wrap}>
      <svg
        width={size.width}
        height={size.height}
        role="img"
        aria-label={
          view === 'time'
            ? `Map of ${dataset.meta.city.name} postcode districts, shaded by how long the journey takes. Use the arrow keys to move between districts and Enter to open one.`
            : `Map of ${dataset.meta.city.name} postcode districts, shaded by how much of each district's rental market the chosen budget reaches. Use the arrow keys to move between districts and Enter to open one.`
        }
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className={drag.current ? 'is-dragging' : undefined}
      >
        <defs>
          {/* The hatch for districts with no published rent figures. It
              carries real meaning rather than decoration: the two greys it
              has to be told apart from are too close in lightness to rely
              on colour alone. */}
          <pattern
            id="no-data"
            width="7"
            height="7"
            patternTransform="rotate(45)"
            patternUnits="userSpaceOnUse"
          >
            <rect width="7" height="7" className="hatch-ground" />
            <line x1="0" y1="0" x2="0" y2="7" className="hatch-line" />
          </pattern>
        </defs>

        <g transform={`translate(${camera.x} ${camera.y}) scale(${camera.scale})`}>
          {paths.map(({ district, d }) => {
            const result = byDistrict.get(district)
            const fill = fillFor({
              minutes: result?.minutes ?? null,
              maxMinutes,
              share: result?.share ?? null,
              mode,
              asked,
              view,
            })
            const isSelected = district === selected
            return (
              <path
                key={district}
                d={d}
                fill={fill.hatched ? 'url(#no-data)' : fill.fill}
                className={[
                  'district',
                  isSelected ? 'is-selected' : '',
                  district === hovered ? 'is-hovered' : '',
                  fill.state === 'too far' || fill.state === 'waiting' ? 'is-out' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                strokeWidth={1 / camera.scale}
                // Roving tabindex: exactly one district is in the tab
                // order at a time. Every district used to be tabbable,
                // which made the map a 274 stop detour between the
                // controls and the answer beside it. Now the map is one
                // stop and the arrow keys move within it.
                tabIndex={district === atNow ? 0 : -1}
                role="button"
                aria-label={describe(districtLabel(dataset.meta, district), result, fill.state)}
                onMouseEnter={(event) => {
                  setPointed(district)
                  const box = wrap.current?.getBoundingClientRect()
                  setTipAt(
                    box
                      ? { x: event.clientX - box.left, y: event.clientY - box.top }
                      : null,
                  )
                }}
                onMouseLeave={() => {
                  setPointed((h) => (h === district ? null : h))
                  setTipAt(null)
                }}
                onFocus={() => setPointed(district)}
                onBlur={() => setPointed((h) => (h === district ? null : h))}
                onClick={(event) => {
                  if (moved(event)) return
                  onSelect(isSelected ? null : district)
                }}
                ref={district === atNow ? active : null}
                onKeyDown={(event) => onKey(event, district, isSelected)}
              />
            )
          })}

          {/* Labels last, so they sit above every fill. Only the ranked
              districts and whatever is hovered or selected are labelled: a
              code on all 274 would be unreadable and would hide the data
              it was describing. */}
          {placeLabels(
            labelOrder.map((district) => byPath.get(district)).filter((p) => p !== undefined),
            labelPoints,
            hovered,
            camera.scale,
          )
            .map(({ district }) => {
              const point = labelPoints.get(district)
              if (!point || !Number.isFinite(point[0])) return null
              const name = districtName(dataset.meta, district)
              return (
                <text
                  key={district}
                  x={point[0]}
                  y={point[1]}
                  className="district-label"
                  fontSize={11 / camera.scale}
                  strokeWidth={3 / camera.scale}
                >
                  <tspan x={point[0]}>{district}</tspan>
                  {/* The name is what most people can actually read, but
                      the code is what the rents are published against, so
                      neither replaces the other. The name is set smaller
                      and is dropped entirely once the labels are small
                      enough that two lines would collide. */}
                  {name ? (
                    <tspan
                      x={point[0]}
                      dy={11 / camera.scale}
                      className="district-label-name"
                      fontSize={9 / camera.scale}
                    >
                      {name}
                    </tspan>
                  ) : null}
                </text>
              )
            })}

          {pins.map(({ place, at }) =>
            at === null ? null : (
              <g key={`${place.cell}-${place.name}`} className="pin" transform={`translate(${at[0]} ${at[1]})`}>
                <circle r={7 / camera.scale} className="pin-halo" />
                <circle r={4 / camera.scale} className="pin-dot" />
              </g>
            ),
          )}
        </g>
      </svg>

      {pointed !== null && tipAt !== null && drag.current === null ? (
        <Tip
          meta={dataset.meta}
          district={pointed}
          result={byDistrict.get(pointed)}
          maxMinutes={maxMinutes}
          asked={asked}
          at={tipAt}
          within={size}
        />
      ) : null}

      {camera.scale !== 1 || camera.x !== 0 || camera.y !== 0 ? (
        <button type="button" className="map-reset" onClick={reset}>
          Reset view
        </button>
      ) : null}
    </div>
  )
}

/**
 * Drop labels that would sit on top of one another.
 *
 * The ranked districts are often neighbours, and in south east London six
 * of them fit inside a thumb. Drawn as they come, the codes overlap into an
 * unreadable smear, which is worse than showing four of them.
 *
 * A greedy pass in rank order: keep a label if nothing already kept is
 * within a label's width of it. Rank order rather than position means the
 * one that survives a collision is the better answer, not the one that
 * happened to be drawn first. Whatever is hovered always survives, because
 * it is the one the visitor is pointing at.
 *
 * The threshold shrinks as the map is zoomed in, since the labels do not
 * grow with it and the districts move apart.
 */
function placeLabels(
  candidates: { district: string; d: string }[],
  points: Map<string, [number, number]>,
  hovered: string | null,
  scale: number,
): { district: string; d: string }[] {
  const apart = 46 / scale
  const kept: { district: string; d: string }[] = []
  const placed: [number, number][] = []

  for (const candidate of candidates) {
    const point = points.get(candidate.district)
    if (!point || !Number.isFinite(point[0])) continue

    if (candidate.district !== hovered) {
      const collides = placed.some(
        ([x, y]) => Math.abs(x - point[0]) < apart && Math.abs(y - point[1]) < apart / 2.2,
      )
      if (collides) continue
    }

    kept.push(candidate)
    placed.push(point)
  }

  return kept
}

function describe(
  district: string,
  result: DistrictResult | undefined,
  state: string,
): string {
  if (state === 'waiting') return district
  if (!result || state === 'too far') return `${district}, beyond your time limit`
  if (state === 'no data') return `${district}, no published rent figures`
  const minutes = result.minutes === null ? 'unreachable' : `${result.minutes} minutes`
  const share = result.share === null ? '' : `, ${Math.round(result.share * 100)}% within budget`
  return `${district}, ${minutes}${share}`
}

/**
 * What the pointer is on, in words.
 *
 * The map answers in colour, which is quick to scan and imprecise by
 * design: five bins cannot tell you that a district is 38% rather than
 * 44%. Hovering is where the exact figures belong, so this carries the
 * name, the journey, the share and the median rather than repeating the
 * colour the reader can already see.
 *
 * It is positioned in the map's own box and flipped near the right and
 * bottom edges, so a district on the edge of the city does not get a
 * tooltip hanging off the edge of the page.
 */
function Tip({
  meta,
  district,
  result,
  maxMinutes,
  asked,
  at,
  within,
}: {
  meta: Meta
  district: string
  result: DistrictResult | undefined
  maxMinutes: number
  asked: boolean
  at: { x: number; y: number }
  within: { width: number; height: number }
}) {
  const name = districtName(meta, district)
  const flipX = at.x > within.width - TIP_WIDTH - 24
  const flipY = at.y > within.height - 120

  const minutes = result?.minutes ?? null
  const tooFar = asked && (minutes === null || minutes > maxMinutes)

  return (
    <div
      className="tip"
      role="presentation"
      style={{
        left: flipX ? undefined : at.x + 14,
        right: flipX ? within.width - at.x + 14 : undefined,
        top: flipY ? undefined : at.y + 14,
        bottom: flipY ? within.height - at.y + 14 : undefined,
        maxWidth: TIP_WIDTH,
      }}
    >
      <p className="tip-name">
        <strong>{district}</strong>
        {name ? <span>{name}</span> : null}
      </p>

      {!asked ? (
        <p className="tip-line tip-hint">Say where you work to see the journey</p>
      ) : tooFar ? (
        <p className="tip-line">Over {maxMinutes} min away</p>
      ) : (
        <p className="tip-line">
          <span>Journey</span>
          <strong>{minutes} min</strong>
        </p>
      )}

      {result?.rent ? (
        <>
          {result.share !== null ? (
            <p className="tip-line">
              <span>In budget</span>
              <strong>{Math.round(result.share * 100)}%</strong>
            </p>
          ) : null}
          <p className="tip-line">
            <span>Median rent</span>
            <strong>{money.format(result.rent[0])}</strong>
          </p>
        </>
      ) : (
        <p className="tip-line tip-hint">No rent figures published for this size</p>
      )}
    </div>
  )
}
