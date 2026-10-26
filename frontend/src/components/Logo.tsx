/**
 * The mark.
 *
 * Two open rings around a dot. The dot is the workplace, drawn in the same
 * accent the map uses for its pins, and the rings are the reach around it,
 * stepped in the same blue as the affordability ramp and fading outward
 * the way the answer does. The opening on the right turns the pair into a
 * C, which is the letter the name starts with.
 *
 * It is one shape at three sizes rather than a logo and a separate icon:
 * nothing is drawn under 2px, there is no text in it, and the gap and
 * stroke stay proportional, so the same geometry survives being shrunk to
 * a 16px favicon.
 *
 * The arcs are explicit paths rather than dashed circles. A dash pattern
 * would have put the gap wherever the stroke happened to start, and would
 * have had to be recomputed for each radius to keep the opening the same
 * angle at both.
 */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg
      className="logo"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      {/* Outer ring: a 70 degree opening centred on the right, drawn
          anticlockwise so the long way round is the one that is painted. */}
      <path
        className="logo-far"
        d="M 26.65 8.54 A 13 13 0 1 0 26.65 23.46"
        fill="none"
        strokeWidth="3.1"
        strokeLinecap="round"
      />
      <path
        className="logo-near"
        d="M 22.55 11.41 A 8 8 0 1 0 22.55 20.59"
        fill="none"
        strokeWidth="3.1"
        strokeLinecap="round"
      />
      <circle className="logo-here" cx="16" cy="16" r="3.4" />
    </svg>
  )
}
