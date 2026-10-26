// Moving around the map with the arrow keys.
//
// The map used to put all 274 districts in the tab order, which made it a
// 274 press detour between the controls above it and the answer beside it.
// It is now a single tab stop, and the arrow keys move within it, which
// means something has to decide what "the district to the left" is.
//
// Stepping through the published order would be simpler and would also be
// nonsense: that order is alphabetical, so pressing right in Bromley would
// land in Croydon. This works on the drawn centroids instead, so the keys
// do what they appear to promise.

export type Point = [number, number]

/**
 * The nearest district in the direction pressed, or null at the edge.
 *
 * Candidates have to lie inside a 90 degree cone around the direction:
 * the distance travelled along it must beat the sideways drift. A plain
 * "nearest point with a greater x" would let a press of the right arrow
 * jump almost vertically, because a district directly above and slightly
 * to the right is closer than the one actually to the right.
 *
 * Ties break on the district's own name, so the same press from the same
 * place always goes to the same district. Two centroids in a real city
 * are never exactly equidistant, but a deterministic answer costs one
 * comparison and removes the question.
 *
 * Coordinates are the SVG's, so y increases downward and up the map is
 * dy of -1.
 */
export function nearestInDirection(
  points: Map<string, Point>,
  from: string,
  dx: number,
  dy: number,
): string | null {
  const origin = points.get(from)
  if (!origin || !Number.isFinite(origin[0]) || !Number.isFinite(origin[1])) return null

  let best: string | null = null
  let bestDistance = Infinity

  for (const [district, point] of points) {
    if (district === from) continue
    if (!Number.isFinite(point[0]) || !Number.isFinite(point[1])) continue

    const ox = point[0] - origin[0]
    const oy = point[1] - origin[1]

    const along = ox * dx + oy * dy
    if (along <= 0) continue

    const across = Math.abs(ox * -dy + oy * dx)
    if (across > along) continue

    const distance = Math.hypot(ox, oy)
    if (distance < bestDistance || (distance === bestDistance && best !== null && district < best)) {
      bestDistance = distance
      best = district
    }
  }

  return best
}

/** The four arrow keys, as directions in SVG coordinates. */
export const ARROWS: Record<string, Point> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
}
