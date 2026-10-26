"""Turning what a visitor types into a grid cell.

The visitor types "Canary Wharf" or "King's Cross" or "SE10" or a full
postcode. Something has to turn that into a point on the ground, and then
into the grid cell whose journey times get downloaded.

There is no server, so this cannot be a geocoding service of our own. It is
two things instead.

The first is a gazetteer shipped with the site: every station in the
timetable feed, every postcode district, every borough. That covers how
people actually describe where they work, because almost everybody in
London describes it by the station they get off at. It is built from inputs
the pipeline already has, so it costs no new data source and no API key,
and it keeps working if every external service is down.

The second, in the browser, is a lookup against postcodes.io for a full
postcode, which is free, open and needs no key. That is a convenience on
top of the gazetteer rather than a dependency: with it the visitor can
type their office postcode, without it they type the nearest station.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np

from pipeline.config import CRS_BRITISH_NATIONAL_GRID, CRS_WGS84
from pipeline.geography import Geography

logger = logging.getLogger(__name__)

# GTFS stops include individual platforms, bus stops and entrances as well
# as stations. Only the parent stations are wanted: a visitor typing
# "Waterloo" does not want eleven platforms offered to them.
#
# location_type 1 is a station, 0 is a stop or platform. Feeds vary in how
# diligently they set it, so a feed with no stations at all falls back to
# stops with no parent, which is the same set by another route.
GTFS_STATION_LOCATION_TYPE = "1"

# Bus stops outnumber rail stations about thirty to one and nobody searches
# for one by name, so a feed's bus stops are excluded by route type where
# the feed says, and by a name heuristic where it does not.
BUS_STOP_HINTS = re.compile(
    r"\b(bus (stop|station)|stop [A-Z]{1,2}\b|\(stop [A-Z]{1,2}\))", re.IGNORECASE
)


@dataclass(frozen=True)
class Place:
    """One searchable place."""

    name: str
    kind: str  # station, district, borough
    cell_id: str
    lon: float
    lat: float


def build_gazetteer(geography: Geography, gtfs_paths: list[Path] | None = None) -> list[Place]:
    """Every place a visitor can search for, each resolved to a grid cell."""
    places: list[Place] = []
    places.extend(_district_places(geography))
    places.extend(_borough_places(geography))

    present = [p for p in (gtfs_paths or []) if p.exists()]
    for path in present:
        places.extend(_station_places(geography, path))

    if not present:
        logger.warning(
            "No timetable feed found, so the gazetteer will hold districts and boroughs "
            "but no station names. Visitors will have to type a postcode or a district."
        )

    # A name appearing twice would show the visitor two identical options.
    # Stations win over districts and boroughs, because a person searching
    # "Richmond" means the station rather than the borough.
    order = {"station": 0, "district": 1, "borough": 2}
    places.sort(key=lambda p: (p.name.lower(), order.get(p.kind, 9)))
    deduplicated: list[Place] = []
    seen: set[str] = set()
    for place in places:
        key = place.name.lower()
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(place)

    by_kind: dict[str, int] = {}
    for place in deduplicated:
        by_kind[place.kind] = by_kind.get(place.kind, 0) + 1
    logger.info("Gazetteer: %d places (%s).", len(deduplicated),
                ", ".join(f"{n} {k}s" for k, n in sorted(by_kind.items())))
    return deduplicated


def _cell_lookup(geography: Geography) -> tuple[gpd.GeoDataFrame, np.ndarray, np.ndarray]:
    """The grid cells, their centres in metres, ready for nearest neighbour."""
    cells = geography.cells
    centres = cells.geometry.centroid
    return cells, centres.x.to_numpy(), centres.y.to_numpy()


def nearest_cell(
    lon: float,
    lat: float,
    cells: gpd.GeoDataFrame,
    xs: np.ndarray,
    ys: np.ndarray,
) -> tuple[str, float]:
    """The grid cell nearest a longitude and latitude, and how far away.

    Nearest centre rather than containing cell. A workplace just outside
    the grid, in a cell trimmed for sitting mostly outside the city, still
    gets the sensible answer rather than nothing. The distance is returned
    so the caller can reject a point that is nowhere near the city.
    """
    point = (
        gpd.GeoSeries(gpd.points_from_xy([lon], [lat]), crs=CRS_WGS84)
        .to_crs(CRS_BRITISH_NATIONAL_GRID)
        .iloc[0]
    )
    distances = np.hypot(xs - point.x, ys - point.y)
    index = int(np.argmin(distances))
    return str(cells.iloc[index]["cell_id"]), float(distances[index])


def _district_places(geography: Geography) -> list[Place]:
    """Each postcode district, placed at a point inside itself.

    A representative point rather than a centroid, because a centroid can
    fall outside a concave district and placing SE9 in SE12 would be worse
    than useless.
    """
    cells, xs, ys = _cell_lookup(geography)
    metric = geography.districts.to_crs(geography.cells.crs)

    places = []
    for row in metric.itertuples(index=False):
        point = row.geometry.representative_point()
        wgs = (
            gpd.GeoSeries([point], crs=geography.cells.crs).to_crs(CRS_WGS84).iloc[0]
        )
        cell_id, _ = nearest_cell(wgs.x, wgs.y, cells, xs, ys)
        places.append(
            Place(name=row.district, kind="district", cell_id=cell_id,
                  lon=round(wgs.x, 5), lat=round(wgs.y, 5))
        )
    return places


def _borough_places(geography: Geography) -> list[Place]:
    """Boroughs, so that "Camden" and "Croydon" resolve to somewhere.

    Read back from the boundary file rather than carried through, because
    the Geography keeps only the unioned outline.
    """
    from pipeline.config import RAW  # noqa: PLC0415  (avoids a circular import at module load)

    path = RAW / geography.city.boundary_file
    if not path.exists():
        return []

    boroughs = gpd.read_file(path)
    if boroughs.crs is None:
        boroughs = boroughs.set_crs(CRS_WGS84)
    name_column = next(
        (c for c in ("name", "Name", "NAME", "lad11nm", "borough") if c in boroughs.columns),
        None,
    )
    if name_column is None:
        logger.warning("Boundary file has no recognisable name column, skipping boroughs.")
        return []

    cells, xs, ys = _cell_lookup(geography)
    places = []
    for row in boroughs.to_crs(CRS_WGS84).itertuples(index=False):
        point = row.geometry.representative_point()
        cell_id, _ = nearest_cell(point.x, point.y, cells, xs, ys)
        places.append(
            Place(name=str(getattr(row, name_column)).strip(), kind="borough",
                  cell_id=cell_id, lon=round(point.x, 5), lat=round(point.y, 5))
        )
    return places


#: GTFS route_type 3 is a bus. The other values are rail, tram, metro,
#: ferry, cable car and so on.
GTFS_BUS_ROUTE_TYPE = "3"


def _is_bus_only(gtfs_path: Path) -> bool:
    """Does this feed carry nothing but buses?

    Decided from routes.txt alone, which is a few hundred kilobytes, rather
    than from stop_times.txt, which for a city feed runs to millions of
    rows. A feed with no routes.txt is given the benefit of the doubt.
    """
    try:
        with zipfile.ZipFile(gtfs_path) as archive:
            name = next((n for n in archive.namelist() if n.endswith("routes.txt")), None)
            if name is None:
                return False
            with archive.open(name) as handle:
                types = {
                    (row.get("route_type") or "").strip()
                    for row in csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig"))
                }
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, StopIteration):
        return False

    types.discard("")
    return bool(types) and types <= {GTFS_BUS_ROUTE_TYPE}


def _station_places(geography: Geography, gtfs_path: Path) -> list[Place]:
    """Station names and positions, read out of the timetable feed.

    The feed is already a required input for routing, so the station list is
    free. It is also the right list by construction: a station that is in
    the timetable is a station the routing engine can actually use, which a
    separately sourced list would not guarantee.
    """
    try:
        with zipfile.ZipFile(gtfs_path) as archive:
            name = next(
                (n for n in archive.namelist() if n.endswith("stops.txt")), None
            )
            if name is None:
                logger.warning("%s contains no stops.txt.", gtfs_path.name)
                return []
            with archive.open(name) as handle:
                rows = list(csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig")))
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as error:
        logger.warning("Could not read stops from %s: %s", gtfs_path.name, error)
        return []

    if not rows:
        return []

    # A bus only feed contributes nothing worth searching for. London has
    # about nineteen thousand bus stops, none of which anybody types into a
    # search box to say where they work, and all of which are parentless
    # stops that the fallback below would otherwise hoover up. Skipping the
    # whole feed is one small read of routes.txt and it settles the matter.
    if _is_bus_only(gtfs_path):
        logger.info(
            "%s carries bus services only, so its stops are left out of the search box. "
            "Its timetables are still used for routing.",
            gtfs_path.name,
        )
        return []

    stations = [r for r in rows if (r.get("location_type") or "").strip() == GTFS_STATION_LOCATION_TYPE]
    if not stations:
        # A feed that does not mark stations. Stops with no parent are the
        # same set reached differently: a platform always has a parent.
        stations = [r for r in rows if not (r.get("parent_station") or "").strip()]
        logger.info(
            "%s marks no stations, so %d parentless stops are used instead.",
            gtfs_path.name, len(stations),
        )

    cells, xs, ys = _cell_lookup(geography)
    places: list[Place] = []
    skipped_far = 0

    for row in stations:
        name = (row.get("stop_name") or "").strip()
        if not name or BUS_STOP_HINTS.search(name):
            continue
        try:
            lat = float(row["stop_lat"])
            lon = float(row["stop_lon"])
        except (KeyError, TypeError, ValueError):
            continue

        cell_id, distance = nearest_cell(lon, lat, cells, xs, ys)
        # A feed covering the whole region includes stations well outside
        # the city. One more than a couple of kilometres from any grid cell
        # is not in London, and offering it would hand the visitor a
        # journey time measured from somewhere else entirely.
        if distance > 2_000:
            skipped_far += 1
            continue

        places.append(
            Place(name=name, kind="station", cell_id=cell_id,
                  lon=round(lon, 5), lat=round(lat, 5))
        )

    if skipped_far:
        logger.info("Skipped %d stations more than 2km outside the grid.", skipped_far)
    return places
