"""What gets published, and why it is shaped this way.

The site has no server. Everything the visitor's browser needs is a static
file on a CDN, so the shape of these files is the whole performance story
and most of the design.

The payload splits in two.

What loads once
---------------
  meta.json          the district order, the bedroom categories, the data
                     vintages, the attributions, the limits
  districts.geojson  274 polygons, simplified for drawing
  boundary.geojson   the city outline
  cells.json         2,895 grid cell centres, for snapping a workplace
  rents.json         every fitted distribution
  gazetteer.json     every searchable place name

Together a few hundred kilobytes, downloaded once and cached.

What loads per answer
---------------------
  times/<cell>.bin   274 journey times, two bytes each

548 bytes. That is the file fetched when the visitor changes where they
work, and it is why the map redraws instantly instead of waiting on a
routing request. Two workplaces mean two of them.

The alternative was a single file holding the whole 274 by 2,895 matrix,
which is 1.6MB. That would be one download rather than two, but it would
be 1.6MB before the visitor sees anything, to use 548 bytes of it. Splitting
by destination means the first paint waits on nothing it does not need.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from pipeline.config import (
    ATTRIBUTIONS,
    LOW_RENT_SAMPLE,
    MAX_JOURNEY_MINUTES,
    MAX_RENT_SIGMA_NOTE,
    MAX_WALK_MINUTES,
    MIN_RENT_SAMPLE,
    UNREACHABLE,
    City,
)
from pipeline.gazetteer import Place
from pipeline.geography import Geography, cell_centroids_wgs84, write_geojson
from pipeline.names import check_coverage, load_district_names
from pipeline.rent import RentReport

logger = logging.getLogger(__name__)

# How much detail the drawn boundaries keep, in metres. The polygons come
# from a map drawn for postal delivery and carry far more vertices than a
# district outline deserves. At 25m the shapes are visually identical at
# every zoom the site offers and the file is a fraction of the size, which
# the visitor pays for on first load.
SIMPLIFY_METRES = 25

# The format version, published in meta.json. If the shape of these files
# changes, this changes with it, and the site can say "this build is older
# than the code" rather than failing to parse something and showing a blank
# map.
FORMAT_VERSION = 1


def export_all(
    geography: Geography,
    rents: RentReport,
    district_minutes: np.ndarray,
    places: list[Place],
    out_dir: Path,
    data_vintages: dict[str, str] | None = None,
) -> dict[str, int]:
    """Write everything the site reads. Returns the byte size of each file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "times").mkdir(exist_ok=True)

    sizes: dict[str, int] = {}

    sizes["districts.geojson"] = _write_districts(geography, out_dir)
    sizes["boundary.geojson"] = _write_boundary(geography, out_dir)
    sizes["cells.json"] = _write_cells(geography, out_dir)
    sizes["rents.json"] = _write_rents(geography, rents, out_dir)
    sizes["gazetteer.json"] = _write_gazetteer(places, out_dir)
    sizes["times/"] = _write_times(geography, district_minutes, out_dir)
    sizes["meta.json"] = _write_meta(
        geography, rents, district_minutes, places, out_dir, data_vintages or {}
    )

    total = sum(sizes.values())
    first_load = total - sizes["times/"]
    logger.info("")
    logger.info("Published to %s", out_dir)
    # Decimal kB, matching Vite's build log, Lighthouse, the browser's
    # network panel and scripts/measure.mjs. This divided by 1024 and
    # called it KB, so the pipeline and the README quoted different
    # numbers for the same file and neither was wrong.
    for name, size in sizes.items():
        logger.info("  %-20s %8.1f kB", name, size / 1000)
    logger.info("  %-20s %8.1f kB", "first load", first_load / 1000)
    # In bytes, because this one is small enough that rounding it to a
    # tenth of a kilobyte throws away the thing worth saying about it.
    logger.info("  %-20s %8d bytes", "per answer", len(geography.district_ids) * 2)
    return sizes


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def _write_districts(geography: Geography, out_dir: Path) -> int:
    """The polygons, simplified, carrying only what the map needs.

    Simplification is done in metres and with topology preserved, so
    neighbouring districts keep their shared edge and the map has no gaps
    along it.
    """
    frame = geography.districts[["district", "share_in_city", "geometry"]].copy()
    metric = frame.to_crs(geography.cells.crs)
    metric["geometry"] = metric.geometry.simplify(SIMPLIFY_METRES, preserve_topology=True)

    path = out_dir / "districts.geojson"
    write_geojson(metric, path)

    before = geography.districts.to_crs(geography.cells.crs).geometry
    kept = metric.area.sum() / before.area.sum()
    logger.info(
        "Districts simplified at %dm, retaining %.2f%% of the total area.",
        SIMPLIFY_METRES, kept * 100,
    )
    return path.stat().st_size


def _write_boundary(geography: Geography, out_dir: Path) -> int:
    """The city outline, for the frame of the map.

    Simplified harder than the districts because it is drawn as a single
    line and nobody is reading its detail.
    """
    import geopandas as gpd  # noqa: PLC0415

    metric = geography.boundary.to_crs(geography.cells.crs)
    simplified = metric.simplify(SIMPLIFY_METRES * 4, preserve_topology=True)
    frame = gpd.GeoDataFrame({"name": [geography.city.name]}, geometry=simplified.to_numpy(),
                             crs=geography.cells.crs)

    path = out_dir / "boundary.geojson"
    write_geojson(frame, path)
    return path.stat().st_size


def _write_cells(geography: Geography, out_dir: Path) -> int:
    """Grid cell centres, as parallel arrays.

    Parallel arrays rather than a list of objects. The same 2,895 cells as
    {"id": ..., "lon": ..., "lat": ...} objects is roughly three times the
    bytes for identical information, and the browser wants them as arrays
    anyway to do the nearest neighbour search.
    """
    centroids = cell_centroids_wgs84(geography.cells)

    payload = {
        "cell_metres": geography.city.grid_cell_metres,
        "ids": list(centroids["cell_id"]),
        "lon": [float(v) for v in centroids["lon"]],
        "lat": [float(v) for v in centroids["lat"]],
    }
    path = out_dir / "cells.json"
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


# ---------------------------------------------------------------------------
# Rent
# ---------------------------------------------------------------------------


def _write_rents(geography: Geography, rents: RentReport, out_dir: Path) -> int:
    """Every fitted distribution, grouped by bedroom category.

    Both the published figures and the two fitted parameters are sent. The
    published figures are what the site shows; the parameters are what it
    computes with. Sending both means the browser can answer "what share of
    this market is under my budget" for any budget without another request,
    and the number it shows as the median is the one ONS published rather
    than one implied by a curve.
    """
    districts = geography.district_ids

    by_category: dict[str, dict] = {}
    for category in sorted(rents.bedroom_categories, key=_bedroom_sort_key):
        rows: dict[str, list] = {}
        for district in districts:
            fitted = rents.get(district, category)
            if fitted is None:
                continue
            rows[district] = [
                round(fitted.median),
                round(fitted.lower_quartile),
                round(fitted.upper_quartile),
                fitted.sample,
                round(fitted.mu, 5),
                round(fitted.sigma, 5),
                1 if fitted.well_fitted else 0,
            ]
        by_category[category] = rows
        logger.info("Rent: %s bedroom data for %d of %d districts.",
                    category, len(rows), len(districts))

    payload = {
        # Documented in the file itself, because a published data file that
        # needs the repository open to read is a worse file.
        "fields": ["median", "lower_quartile", "upper_quartile", "sample",
                   "mu", "sigma", "well_fitted"],
        "note": (
            "median, lower_quartile and upper_quartile are published by ONS and shown "
            "verbatim. mu and sigma are a lognormal fitted to those three figures by "
            "least squares, used to estimate the share of a district's market under a "
            "budget. well_fitted is 0 where the fitted curve misses one of the three "
            "published figures by more than 5 per cent."
        ),
        "min_sample": MIN_RENT_SAMPLE,
        "categories": by_category,
    }
    path = out_dir / "rents.json"
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


def _bedroom_sort_key(category: str) -> tuple[int, str]:
    order = {"room": 0, "studio": 1, "1": 2, "2": 3, "3": 4, "4+": 5, "all": 6}
    return (order.get(category, 9), category)


# ---------------------------------------------------------------------------
# Journey times
# ---------------------------------------------------------------------------


def _write_times(geography: Geography, district_minutes: np.ndarray, out_dir: Path) -> int:
    """One file per destination cell, holding one journey time per district.

    Little endian unsigned 16 bit integers, in the district order published
    in meta.json. No header: the length is the district count and the
    endianness is fixed, both stated in meta.json, so a header would only
    be a second place for them to disagree.
    """
    districts = geography.district_ids
    cells = geography.cell_ids

    expected = (len(districts), len(cells))
    if district_minutes.shape != expected:
        raise ValueError(
            f"Journey times are {district_minutes.shape} but there are "
            f"{len(districts)} districts and {len(cells)} cells, so {expected} was "
            f"expected. The geography and the matrix came from different runs."
        )
    if district_minutes.dtype != np.uint16:
        raise ValueError(f"Journey times must be uint16, got {district_minutes.dtype}.")

    times_dir = out_dir / "times"
    # A rebuild with a smaller grid would otherwise leave the old files in
    # place, and the site would happily serve a journey time computed from
    # a different timetable and a different district order.
    for stale in times_dir.glob("*.bin"):
        stale.unlink()

    total = 0
    # Written transposed so each destination's column is contiguous, which
    # turns 2,895 gather operations into 2,895 slice copies.
    by_cell = np.ascontiguousarray(district_minutes.T)
    for position, cell in enumerate(cells):
        payload = by_cell[position].astype("<u2").tobytes()
        (times_dir / f"{cell}.bin").write_bytes(payload)
        total += len(payload)

    logger.info(
        "Journey times: %d files of %d bytes, %.1f MB in total, of which a visitor "
        "downloads %d bytes per workplace.",
        len(cells), len(districts) * 2, total / 1e6, len(districts) * 2,
    )
    return total


# ---------------------------------------------------------------------------
# Gazetteer
# ---------------------------------------------------------------------------


def _write_gazetteer(places: list[Place], out_dir: Path) -> int:
    payload = {
        "fields": ["name", "kind", "cell", "lon", "lat"],
        "places": [[p.name, p.kind, p.cell_id, p.lon, p.lat] for p in places],
    }
    path = out_dir / "gazetteer.json"
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def _write_meta(
    geography: Geography,
    rents: RentReport,
    district_minutes: np.ndarray,
    places: list[Place],
    out_dir: Path,
    data_vintages: dict[str, str],
) -> int:
    """The file that makes every other file readable.

    It carries the district order, which is the key to every journey time
    array, the data vintages, which are what lets the site say how old the
    numbers are, and the known limitations, which belong in the published
    data rather than in a comment nobody will read.
    """
    city: City = geography.city
    districts = geography.district_ids

    names = load_district_names(city)
    check_coverage(districts, names)

    reachable = district_minutes != UNREACHABLE
    with_rent = sorted({d for d, _ in rents.distributions})

    payload = {
        "format_version": FORMAT_VERSION,
        "built": datetime.now(UTC).isoformat(timespec="seconds"),
        "city": {"id": city.id, "name": city.name, "timezone": city.timezone},
        # The order is the data format. Every times/*.bin is this list.
        "districts": districts,
        "districts_with_rent": with_rent,
        # Code to place name. Absent for a city with no names file, in
        # which case the site shows the bare code.
        "district_names": {d: names[d] for d in districts if d in names},
        "bedroom_categories": sorted(rents.bedroom_categories, key=_bedroom_sort_key),
        "bedroom_labels": {
            "room": "a room", "studio": "a studio", "1": "1 bedroom",
            "2": "2 bedrooms", "3": "3 bedrooms", "4+": "4+ bedrooms",
            "all": "any size",
        },
        "grid": {
            "cell_metres": city.grid_cell_metres,
            "cells": len(geography.cell_ids),
        },
        "times": {
            "encoding": "uint16 little endian, one per district in the districts order",
            "unreachable": UNREACHABLE,
            "max_minutes": MAX_JOURNEY_MINUTES,
            "max_walk_minutes": MAX_WALK_MINUTES,
            "departure_date": city.departure_date,
            "departure_window": f"{city.departure_window_start} for "
                                f"{city.departure_window_minutes} minutes",
            "statistic": "median across the departure window",
            "reachable_share": round(float(reachable.mean()), 4),
        },
        "rent": {
            "min_sample": MIN_RENT_SAMPLE,
            "low_sample": LOW_RENT_SAMPLE,
            "fitted": len(rents.distributions),
            "poorly_fitted": len(rents.poorly_fitted),
            "sigma_note": MAX_RENT_SIGMA_NOTE,
        },
        "gazetteer": {"places": len(places)},
        "data_vintages": data_vintages,
        "attributions": [
            {"name": a.name, "source": a.source, "licence": a.licence, "url": a.url}
            for a in ATTRIBUTIONS
        ],
        # Said here so the site can show them, rather than only in a readme.
        # A tool that does not state its limits invites the reader to assume
        # it has none.
        "limitations": [
            "Rents are published per postcode district. A district is large, and "
            "within one of them the range is wide. The site shows the published "
            "quartiles alongside the median so that range is visible.",
            f"Journey times are the median of departures across a {city.departure_window_minutes}"
            f" minute window on a weekday morning, computed from the published timetable. "
            f"They do not account for delays, engineering work, or how full the train is.",
            f"A district's journey time is the median across the {city.grid_cell_metres}m grid "
            f"cells inside it, weighted by how much housing each contains. One end of a "
            f"district may be considerably better connected than the other.",
            f"Walking at each end is capped at {MAX_WALK_MINUTES} minutes and the whole "
            f"journey at {MAX_JOURNEY_MINUTES} minutes. Driving and cycling are not modelled.",
            "Rent and journey time are the two things measured here. They are not the only "
            "things that decide where somebody wants to live.",
        ],
    }

    path = out_dir / "meta.json"
    path.write_text(json.dumps(payload, indent=1, sort_keys=False), encoding="utf-8")
    return path.stat().st_size
