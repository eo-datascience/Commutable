// Ring winding, and the one place these two standards disagree.
//
// The published GeoJSON follows RFC 7946: an exterior ring runs
// counter-clockwise, a hole runs clockwise. That is what the specification
// says and what QGIS, Leaflet and anything else reading these files will
// expect, so it is what the pipeline writes.
//
// d3-geo is the exception, and it is a deliberate one. It treats a polygon
// as a region on a sphere rather than a shape on a plane, and on a sphere
// every ring divides the surface into two parts of which neither is
// obviously the inside. d3 resolves that with the opposite convention to
// RFC 7946: the exterior ring runs clockwise.
//
// Get it the wrong way round and nothing warns you. A counter-clockwise
// ring is not drawn backwards, it is drawn as the entire earth except that
// district, so the map fills with one flat colour and every shape is
// 185,000 pixels wide. That is exactly what happened here the first time:
// the city outline came out right, because unioning the boroughs happened
// to produce a clockwise ring, and all 274 districts came out wrong, so
// the page showed a correct outline over a sheet of grey.
//
// So the files stay standards-compliant and the rings are turned round
// here, once, on load.

type Ring = number[][]
type PolygonCoords = Ring[]

/** The signed area of a ring. Negative is clockwise in longitude-latitude. */
export function signedArea(ring: Ring): number {
  let total = 0
  for (let i = 0; i < ring.length - 1; i++) {
    const a = ring[i]
    const b = ring[i + 1]
    if (!a || !b) continue
    total += ((b[0] ?? 0) - (a[0] ?? 0)) * ((b[1] ?? 0) + (a[1] ?? 0))
  }
  return total
}

export function isClockwise(ring: Ring): boolean {
  return signedArea(ring) > 0
}

function windRing(ring: Ring, clockwise: boolean): Ring {
  return isClockwise(ring) === clockwise ? ring : [...ring].reverse()
}

function windPolygon(polygon: PolygonCoords): PolygonCoords {
  return polygon.map((ring, index) =>
    // The exterior ring clockwise, every hole the other way.
    windRing(ring, index === 0),
  )
}

/**
 * Turn a GeoJSON geometry's rings round for d3-geo.
 *
 * Returns a new geometry; the input is not modified, so the published data
 * and the drawable data can both be held without one quietly becoming the
 * other.
 */
export function rewindGeometry<T extends { type: string }>(geometry: T): T {
  // A GeometryCollection has no coordinates of its own and nothing here
  // produces one, so it falls through untouched along with points and
  // lines, which have no inside to get the wrong way round.
  const coordinates = (geometry as { coordinates?: unknown }).coordinates

  if (geometry.type === 'Polygon' && coordinates) {
    return { ...geometry, coordinates: windPolygon(coordinates as PolygonCoords) }
  }
  if (geometry.type === 'MultiPolygon' && coordinates) {
    return { ...geometry, coordinates: (coordinates as PolygonCoords[]).map(windPolygon) }
  }
  return geometry
}

/** The same, for a whole FeatureCollection. */
export function rewindCollection<C extends { features: { geometry: { type: string } }[] }>(
  collection: C,
): C {
  return {
    ...collection,
    features: collection.features.map((feature) => ({
      ...feature,
      geometry: rewindGeometry(feature.geometry),
    })),
  }
}
