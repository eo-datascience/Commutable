"""The shapes the whole project hangs off.

Three things come out of this module: the postcode districts that count as
London, a uniform grid of cells covering the city, and the relationship
between the two. Everything downstream is a lookup against one of them.

The grid is the part worth understanding. Rent is published per postcode
district and nothing finer exists, so the district is the unit a visitor
chooses between. But a district is a large, awkward shape: SE9 is nine
square kilometres and the walk from one end to a station is not the walk
from the other. Measuring a journey from a single point inside it, however
that point is chosen, is a coin toss dressed as a measurement.

So journeys are measured between grid cells, and a district's journey time
is the median across the cells inside it. That turns one arbitrary choice
into a distribution, and it means the figure degrades honestly: a district
with one well connected corner and a badly connected rest reads as what it
is rather than as whichever corner the centroid happened to land in.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPolygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from pipeline.config import (
    CRS_BRITISH_NATIONAL_GRID,
    CRS_WGS84,
    MIN_CELL_COVERAGE,
    City,
)

logger = logging.getLogger(__name__)

# The grid is anchored to a fixed British National Grid coordinate rather
# than to the city's bounding box. Anchoring to the bounding box would move
# every cell, and so change every cell id and every published filename, the
# moment a boundary file was updated by a metre. This anchor sits southwest
# of London so that every column and row index is a small positive number.
GRID_ANCHOR_EASTING = 480_000
GRID_ANCHOR_NORTHING = 140_000


@dataclass(frozen=True)
class Geography:
    """The districts, the grid, and how they overlap.

    districts: one row per postcode district, with the share of its area
        inside the city boundary.
    cells: one row per grid cell, with its id, centroid and the district it
        sits in.
    """

    city: City
    boundary: gpd.GeoSeries          # a single row, the city outline
    districts: gpd.GeoDataFrame      # district, share_in_city, geometry
    cells: gpd.GeoDataFrame          # cell_id, col, row, district, weight, geometry

    @property
    def district_ids(self) -> list[str]:
        """Districts in a fixed, documented order.

        Every exported travel time array is indexed by position in this
        list, so the order is part of the published data format. Sorted by
        area then number so that SE9 precedes SE10, which is how a person
        reads them and makes a hand check of the output possible.
        """
        return list(self.districts["district"])

    @property
    def cell_ids(self) -> list[str]:
        return list(self.cells["cell_id"])

    def cells_of(self, district: str) -> gpd.GeoDataFrame:
        return self.cells[self.cells["district"] == district]


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def district_sort_key(code: str) -> tuple[str, int, str]:
    """Sort SE1, SE2, SE10 in that order rather than SE1, SE10, SE2.

    The trailing letters in central London codes such as EC1A are kept as a
    third component so that EC1A, EC1M, EC1N stay together and in order.
    """
    i = 0
    while i < len(code) and code[i].isalpha():
        i += 1
    area = code[:i]
    j = i
    while j < len(code) and code[j].isdigit():
        j += 1
    number = int(code[i:j]) if j > i else 0
    return (area, number, code[j:])


# ---------------------------------------------------------------------------
# The city boundary
# ---------------------------------------------------------------------------


def load_city_boundary(path: Path) -> gpd.GeoSeries:
    """The city outline, as the union of its constituent areas.

    The input is a file of boroughs rather than a single outline because a
    single outline is not published in a convenient form, and because
    unioning boroughs is a check in itself: if the file is wrong or partial
    the resulting area will be obviously off.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"No city boundary at {path}. Run scripts/fetch_boundaries.py, which "
            f"downloads it, or see docs/data-sources.md to supply your own."
        )

    parts = gpd.read_file(path)
    if parts.empty:
        raise ValueError(f"{path} contains no features.")

    # Some published boundary files carry no CRS at all. They are in
    # practice WGS84, but assuming that silently would be the kind of thing
    # that produces a map of London in the Atlantic, so it is logged.
    if parts.crs is None:
        logger.warning("%s declares no coordinate system. Assuming WGS84.", path.name)
        parts = parts.set_crs(CRS_WGS84)
    parts = parts.to_crs(CRS_WGS84)

    outline = unary_union(parts.geometry.values)
    return gpd.GeoSeries([outline], crs=CRS_WGS84, name="boundary")


# ---------------------------------------------------------------------------
# Postcode districts
# ---------------------------------------------------------------------------


def load_postcode_districts(directory: Path, areas: tuple[str, ...]) -> gpd.GeoDataFrame:
    """Load one GeoJSON per postcode area and concatenate the districts.

    The files are per area (one file holds every SE district) because that
    is how the upstream source publishes them. A missing area is an error
    rather than a warning: silently omitting SE would leave a hole in south
    east London that looked like genuinely missing rent data.
    """
    frames: list[gpd.GeoDataFrame] = []
    missing: list[str] = []

    for area in areas:
        path = directory / f"{area}.geojson"
        if not path.exists():
            missing.append(area)
            continue
        frame = gpd.read_file(path)
        if frame.crs is None:
            frame = frame.set_crs(CRS_WGS84)
        name_column = _find_name_column(frame, path)
        frame = frame[[name_column, "geometry"]].rename(columns={name_column: "district"})
        frame["district"] = frame["district"].astype(str).str.strip().str.upper()
        frames.append(frame.to_crs(CRS_WGS84))

    if missing:
        raise FileNotFoundError(
            f"Missing postcode area files for {', '.join(missing)} in {directory}. "
            f"Run scripts/fetch_boundaries.py."
        )

    districts = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=CRS_WGS84)

    # A district appearing twice would be counted twice in every aggregate
    # downstream and is far easier to catch here than to explain later.
    duplicated = districts.loc[districts["district"].duplicated(), "district"].unique()
    if len(duplicated):
        raise ValueError(f"Districts appear more than once: {sorted(duplicated)}")

    return districts


def _find_name_column(frame: gpd.GeoDataFrame, path: Path) -> str:
    """Find the column holding the district code.

    Boundary files are published by several different people and none of
    them agree on a column name. Rather than hard coding one and breaking
    on the next source, the plausible names are tried in order and the
    failure message lists what was actually there.
    """
    for candidate in ("name", "Name", "NAME", "district", "postdist", "pc_district", "pcd"):
        if candidate in frame.columns:
            return candidate
    raise ValueError(
        f"Cannot find a district name column in {path.name}. "
        f"Columns present: {sorted(c for c in frame.columns if c != 'geometry')}"
    )


def districts_in_city(
    districts: gpd.GeoDataFrame,
    boundary: gpd.GeoSeries,
    min_share: float,
) -> gpd.GeoDataFrame:
    """Keep the districts that are meaningfully inside the city.

    Postcode districts were drawn for delivery rounds and ignore the
    administrative boundary, so the question is not whether a district
    touches London but how much of it is London. The share is kept on the
    output rather than discarded, because a district that is 15% London is
    a different thing from one that is 100% London and the site says so.

    Areas are measured in British National Grid. Measuring them in degrees
    would weight the north of the city differently from the south.
    """
    metric = districts.to_crs(CRS_BRITISH_NATIONAL_GRID)
    outline = boundary.to_crs(CRS_BRITISH_NATIONAL_GRID).iloc[0]

    total = metric.area
    inside = metric.geometry.intersection(outline).area
    share = np.where(total > 0, inside / total, 0.0)

    kept = districts.loc[share >= min_share].copy()
    kept["share_in_city"] = np.round(share[share >= min_share], 4)
    kept["area_km2"] = np.round(total[share >= min_share].to_numpy() / 1e6, 3)

    kept = kept.sort_values("district", key=lambda s: s.map(district_sort_key)).reset_index(drop=True)

    logger.info(
        "Kept %d of %d postcode districts at a %.0f%% in-city threshold.",
        len(kept), len(districts), min_share * 100,
    )
    return kept


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------


def build_grid(
    boundary: gpd.GeoSeries,
    cell_metres: int,
    min_coverage: float = MIN_CELL_COVERAGE,
) -> gpd.GeoDataFrame:
    """A uniform grid of square cells covering the city.

    Built in British National Grid so the cells are genuinely square and
    genuinely the stated size. Anchored to a fixed coordinate so that cell
    ids survive a change of boundary file.
    """
    outline = boundary.to_crs(CRS_BRITISH_NATIONAL_GRID).iloc[0]
    min_x, min_y, max_x, max_y = outline.bounds

    first_col = int(np.floor((min_x - GRID_ANCHOR_EASTING) / cell_metres))
    last_col = int(np.ceil((max_x - GRID_ANCHOR_EASTING) / cell_metres))
    first_row = int(np.floor((min_y - GRID_ANCHOR_NORTHING) / cell_metres))
    last_row = int(np.ceil((max_y - GRID_ANCHOR_NORTHING) / cell_metres))

    records = []
    for col in range(first_col, last_col + 1):
        x0 = GRID_ANCHOR_EASTING + col * cell_metres
        for row in range(first_row, last_row + 1):
            y0 = GRID_ANCHOR_NORTHING + row * cell_metres
            records.append(
                {
                    "cell_id": cell_id(col, row),
                    "col": col,
                    "row": row,
                    "geometry": box(x0, y0, x0 + cell_metres, y0 + cell_metres),
                }
            )

    grid = gpd.GeoDataFrame(records, crs=CRS_BRITISH_NATIONAL_GRID)

    # Trimming by coverage rather than by intersection keeps the cells
    # square. Clipping them to the boundary would produce ragged shapes
    # whose centroids drift outside the city.
    cell_area = float(cell_metres) ** 2
    coverage = grid.geometry.intersection(outline).area / cell_area
    grid = grid.loc[coverage >= min_coverage].copy()
    grid["coverage"] = np.round(coverage[coverage >= min_coverage], 4)

    grid = grid.sort_values(["col", "row"]).reset_index(drop=True)
    logger.info("Grid: %d cells of %dm covering the city.", len(grid), cell_metres)
    return grid


def cell_id(col: int, row: int) -> str:
    """A stable, readable identifier for a grid cell.

    Six characters, three for each axis, derived from the fixed anchor.
    Readable matters more than it sounds: when a journey time looks wrong,
    being able to read the cell id back to a position on the ground is the
    difference between a five minute check and an afternoon.
    """
    if not (0 <= col < 1000 and 0 <= row < 1000):
        raise ValueError(f"Cell ({col}, {row}) falls outside the addressable grid.")
    return f"{col:03d}{row:03d}"


def assign_cells_to_districts(
    grid: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Give every cell the district its centre falls in.

    A cell straddling a district boundary belongs to one of them, decided
    by its centre. Splitting it proportionally would be more precise about
    a boundary that is itself approximate, and would complicate every
    aggregate downstream for no gain the rent data can support.

    Cells whose centre falls in no kept district keep a null district. They
    are still routed to, because people work in places nobody lives, and
    central London is full of them.

    A district smaller than a cell gets no cell centre of its own. Two
    dozen central districts are in that position: EC3V, W1B and their
    neighbours are a few streets each, drawn for sorting office rounds
    rather than for anybody's convenience. Those districts are handled
    separately in district_cell_index, which guarantees every district at
    least the cell it sits inside.
    """
    metric_districts = districts.to_crs(grid.crs)[["district", "geometry"]]

    centres = grid.copy()
    centres["geometry"] = grid.geometry.centroid

    joined = gpd.sjoin(centres, metric_districts, how="left", predicate="within")

    # A centre exactly on a shared edge can match two districts. Keeping the
    # first in district order makes the outcome deterministic rather than
    # dependent on the spatial index's internal ordering.
    joined = (
        joined.sort_values(["cell_id", "district"])
        .drop_duplicates("cell_id", keep="first")
        .set_index("cell_id")
    )

    out = grid.set_index("cell_id").copy()
    out["district"] = joined["district"]
    out = out.reset_index()

    unassigned = int(out["district"].isna().sum())
    logger.info(
        "Assigned %d of %d cells to a district. %d sit outside every kept district "
        "and are reachable as workplaces but not offered as places to live.",
        len(out) - unassigned, len(out), unassigned,
    )
    return out


def district_cell_index(
    districts: gpd.GeoDataFrame,
    cells: gpd.GeoDataFrame,
) -> dict[str, np.ndarray]:
    """For each district, the positions of its cells in the cells table.

    Positions rather than cell ids, because the travel time matrix is a
    plain array indexed by cell position and this is what indexes into it.

    Every district gets at least one cell. For the great majority that is
    the set of cells whose centre falls inside them. For the two dozen
    central districts smaller than a single cell it is the one cell their
    own representative point falls in, borrowed from a neighbour.

    That borrowing is the right answer rather than a patch. EC3V is four
    streets inside the City. A person renting there has the City's journey
    times because they are standing in the City, and the cell covering
    those streets is the honest measurement. Omitting the district instead
    would leave holes in the middle of the map at exactly the postcodes
    people recognise.
    """
    by_district: dict[str, np.ndarray] = {}
    position = {cell: i for i, cell in enumerate(cells["cell_id"])}

    grouped = cells.dropna(subset=["district"]).groupby("district").groups
    for district, index in grouped.items():
        by_district[str(district)] = np.asarray(
            [position[c] for c in cells.loc[index, "cell_id"]], dtype=np.int32
        )

    orphans = [d for d in districts["district"] if d not in by_district]
    if orphans:
        metric = districts.set_index("district").to_crs(cells.crs)
        points = gpd.GeoDataFrame(
            {"district": orphans},
            geometry=[metric.loc[d, "geometry"].representative_point() for d in orphans],
            crs=cells.crs,
        )
        located = gpd.sjoin(points, cells[["cell_id", "geometry"]], how="left", predicate="within")
        located = located.sort_values(["district", "cell_id"]).drop_duplicates("district")

        still_missing: list[str] = []
        for district, cell in zip(located["district"], located["cell_id"], strict=True):
            if isinstance(cell, str) and cell in position:
                by_district[district] = np.asarray([position[cell]], dtype=np.int32)
            else:
                still_missing.append(district)

        logger.info(
            "%d districts are smaller than one grid cell and borrow the cell they sit in: %s",
            len(orphans) - len(still_missing),
            ", ".join(sorted(d for d in orphans if d in by_district)[:8])
            + (" and others" if len(orphans) > 8 else ""),
        )
        if still_missing:
            # A district inside the city boundary that falls in no grid cell
            # would mean the grid does not cover the city, which is a bug in
            # the grid rather than a quirk of the postal geography.
            raise ValueError(
                f"These districts fall inside the city but in no grid cell, which means "
                f"the grid does not cover the city: {sorted(still_missing)}"
            )

    return by_district


# ---------------------------------------------------------------------------
# Weighting the cells inside a district
# ---------------------------------------------------------------------------


def uniform_weights(cells: gpd.GeoDataFrame) -> pd.Series:
    """Every cell counts the same.

    The fallback when building footprints are unavailable. It is wrong in a
    specific, known direction: a district half covered by a park or a
    reservoir has its journey time pulled toward the part of it nobody
    lives in.
    """
    return pd.Series(1.0, index=cells.index, name="weight")


def building_weights(cells: gpd.GeoDataFrame, osm_path: Path) -> pd.Series:
    """Weight each cell by how much housing is in it.

    The problem this solves: taking a plain median over a district's cells
    treats Richmond Park as equal to the streets beside it, and Richmond
    Park has no commute because nobody lives there. Weighting by the number
    of residential building footprints in each cell makes the median
    describe where people actually are.

    The street network extract is already a required input for routing, so
    this costs an extra pass over a file that has to be downloaded anyway
    rather than a new data source.

    Cells with no buildings keep a small non zero weight rather than zero,
    so that a district made entirely of unmapped buildings degrades to the
    uniform case instead of producing an empty median.
    """
    counts = count_residential_buildings(osm_path, cells)
    if counts is None:
        logger.warning(
            "Could not read buildings from %s, so district journey times will be an "
            "unweighted median over their cells. Install osmium to enable weighting.",
            osm_path.name,
        )
        return uniform_weights(cells)

    weights = cells["cell_id"].map(counts).fillna(0.0).astype(float)
    weights = weights + 0.01  # see docstring: never exactly zero
    weights.index = cells.index
    weights.name = "weight"

    mapped = int((weights > 0.01).sum())
    logger.info(
        "Weighted %d of %d cells by residential building count.", mapped, len(cells)
    )
    return weights


def count_residential_buildings(
    osm_path: Path,
    cells: gpd.GeoDataFrame,
) -> dict[str, int] | None:
    """Count residential building footprints per grid cell.

    Returns None rather than raising if the reader is unavailable or the
    file cannot be parsed, because weighting is an improvement to the
    median and not a precondition for producing one.
    """
    try:
        import osmium  # noqa: PLC0415  (optional dependency, imported where used)
    except ImportError:
        return None

    if not osm_path.exists():
        logger.warning("No street network extract at %s.", osm_path)
        return None

    # Tags that indicate somebody lives in the building. Everything else,
    # including the large commercial and industrial footprints that would
    # otherwise dominate parts of the centre, is ignored.
    residential = {
        "yes", "house", "residential", "apartments", "detached",
        "semidetached_house", "terrace", "bungalow", "dormitory",
        "static_caravan", "houseboat",
    }

    class Counter(osmium.SimpleHandler):
        def __init__(self) -> None:
            super().__init__()
            self.points: list[tuple[float, float]] = []

        def area(self, a) -> None:  # noqa: ANN001  (osmium's own type)
            kind = a.tags.get("building")
            if kind is None or kind not in residential:
                return
            try:
                centre = a.centroid
            except Exception:  # noqa: BLE001  (a malformed way must not stop the pass)
                return
            self.points.append((centre.lon, centre.lat))

    counter = Counter()
    try:
        counter.apply_file(str(osm_path), locations=True)
    except Exception as error:  # noqa: BLE001
        logger.warning("Reading buildings from %s failed: %s", osm_path.name, error)
        return None

    if not counter.points:
        return None

    points = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy(*zip(*counter.points, strict=True)),
        crs=CRS_WGS84,
    ).to_crs(cells.crs)

    joined = gpd.sjoin(points, cells[["cell_id", "geometry"]], how="inner", predicate="within")
    return joined["cell_id"].value_counts().to_dict()


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_geography(city: City, raw_dir: Path, weight_by_buildings: bool = True) -> Geography:
    """Load everything and return the assembled geography."""
    boundary = load_city_boundary(raw_dir / city.boundary_file)
    all_districts = load_postcode_districts(raw_dir / "postcode_districts", city.postcode_areas)
    districts = districts_in_city(all_districts, boundary, city.min_district_in_city)

    grid = build_grid(boundary, city.grid_cell_metres)
    cells = assign_cells_to_districts(grid, districts)

    if weight_by_buildings:
        cells["weight"] = building_weights(cells, raw_dir / city.osm_file)
    else:
        cells["weight"] = uniform_weights(cells)

    return Geography(city=city, boundary=boundary, districts=districts, cells=cells)


def cell_centroids_wgs84(cells: gpd.GeoDataFrame) -> pd.DataFrame:
    """Cell centres as longitude and latitude.

    This is what the browser receives. It snaps a visitor's workplace to
    the nearest of these rather than projecting the coordinate itself,
    which keeps a coordinate system library out of the front end and makes
    the snapping behaviour identical to the pipeline's by construction.
    """
    # The centroid is taken in metres and only then reprojected. Taking it
    # in degrees puts the centre of a London cell about forty metres north
    # of where it belongs, and geopandas rightly warns about it.
    centres = cells.geometry.centroid.to_crs(CRS_WGS84)
    return pd.DataFrame(
        {
            "cell_id": cells["cell_id"].to_numpy(),
            "lon": np.round(centres.x.to_numpy(), 5),
            "lat": np.round(centres.y.to_numpy(), 5),
        }
    )


def orient_rfc7946(geometry):  # noqa: ANN001, ANN201  (any shapely geometry)
    """Wind a polygon's rings the way the GeoJSON standard requires.

    RFC 7946 says an exterior ring runs counter-clockwise and a hole runs
    clockwise. Shapely does not enforce it and neither does the upstream
    boundary source, so published polygons can come out either way.

    This is not pedantry about a specification. Anything that draws GeoJSON
    on a sphere, d3-geo included, reads the winding as the definition of
    which side is inside. A clockwise exterior ring does not mean the same
    polygon drawn backwards; it means the whole of the earth except that
    polygon. A single district wound the wrong way therefore renders as a
    shape the size of the planet, and since every district is drawn in the
    same pass, the map becomes one flat field of colour with no hint of
    what went wrong.

    That is exactly what happened the first time this data was drawn. The
    city outline rendered correctly, because unioning the boroughs happened
    to produce a counter-clockwise ring, while all 274 districts did not.
    """
    if geometry is None or geometry.is_empty:
        return geometry
    if geometry.geom_type == "Polygon":
        return orient(geometry, sign=1.0)
    if geometry.geom_type == "MultiPolygon":
        return MultiPolygon([orient(part, sign=1.0) for part in geometry.geoms])
    return geometry


def write_geojson(frame: gpd.GeoDataFrame, path: Path, decimals: int = 4) -> None:
    """Write GeoJSON with coordinates rounded to a sensible precision.

    Four decimal places is about eleven metres in London, which is below
    the tolerance the shapes are already simplified at, so the rounding
    costs nothing visible and takes about a sixth off the largest file the
    visitor downloads. Writing full double precision would publish
    seventeen significant figures of a boundary drawn for postal rounds.

    Rounding both sides of a shared edge onto the same grid keeps them
    coincident, so neighbouring districts do not develop slivers of
    background between them.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    wgs84 = frame.to_crs(CRS_WGS84).copy()
    wgs84["geometry"] = wgs84.geometry.map(orient_rfc7946)
    payload = json.loads(wgs84.to_json())

    def round_coords(value):
        if isinstance(value, list):
            return [round_coords(v) for v in value]
        return round(value, decimals)

    for feature in payload["features"]:
        feature["geometry"]["coordinates"] = round_coords(feature["geometry"]["coordinates"])
        feature.pop("id", None)

    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
