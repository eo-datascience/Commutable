"""Journey times, computed once, offline.

Why it is done this way
-----------------------
The obvious implementation is to ask a journey planner for a route when the
visitor asks for one. That cannot work here. A single answer needs a
journey time from every residential postcode district, and there are 274 of
them. TfL's journey planner permits roughly fifty requests a minute, so one
visitor's single question would take five and a half minutes and the second
visitor would have to queue behind them.

So every journey is computed in advance by a routing engine running locally
over published timetables, and the published site does nothing at run time
but read a small file and colour a map. The arithmetic moves from the
visitor's wait to a batch job that runs when the timetable is refreshed.

What is computed
----------------
A full cell to cell matrix: the journey time from every grid cell in the
city to every other. For London at 750m that is about 2,900 cells and 8.4
million journeys, which R5 computes in a few minutes on a laptop.

The matrix is deliberately larger than what the site needs. The site needs
journey times from districts, and a district's time is derived from its
cells afterwards. Keeping the cell matrix means the derivation can be
changed, or the weighting improved, without routing anything again, and
routing is the one step that takes real time.

Departure times
---------------
Every journey is computed across a window of departures rather than at a
single instant, and the median is kept. A single departure time measures
the timetable's luck rather than the journey: leave Crystal Palace at
08:00 and you catch the 08:02, leave at 08:04 and you wait until 08:17.
The median over an hour of departures is the figure a person actually lives
with across a working week.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import geopandas as gpd
import numpy as np

from pipeline.config import (
    CRS_WGS84,
    MAX_JOURNEY_MINUTES,
    MAX_WALK_MINUTES,
    UNREACHABLE,
    City,
)
from pipeline.geography import Geography

logger = logging.getLogger(__name__)

# How many origins are routed at once. R5 returns results in long form, one
# row per origin and destination pair, so a full 2,900 by 2,900 run would
# materialise 8.4 million rows in a single DataFrame. Chunking keeps peak
# memory in the hundreds of megabytes instead of the gigabytes, and gives
# the run something to report while it works, which for a job that takes
# minutes is not a small thing.
ORIGIN_CHUNK = 250


@dataclass
class TravelTimes:
    """Journey times between grid cells, in whole minutes.

    Stored as unsigned 16 bit integers because that is what gets published
    and because the full matrix at 64 bit floating point would be 67MB of
    precision the data does not have. A journey time from a timetable is
    accurate to the minute at best.

    UNREACHABLE marks a pair with no journey inside the ceiling. It is a
    distinct value rather than a missing one so that it survives the
    arithmetic: a district half of which cannot reach a workplace should
    read as unreachable, not as the average of the half that can.
    """

    cell_ids: list[str]
    minutes: np.ndarray  # (n_cells, n_cells), uint16, [origin, destination]

    def __post_init__(self) -> None:
        n = len(self.cell_ids)
        if self.minutes.shape != (n, n):
            raise ValueError(
                f"Matrix is {self.minutes.shape} but there are {n} cells."
            )
        if self.minutes.dtype != np.uint16:
            raise ValueError(f"Matrix must be uint16, got {self.minutes.dtype}.")

    @property
    def reachable_share(self) -> float:
        return float((self.minutes != UNREACHABLE).mean())

    def save(self, path: Path) -> None:
        """Keep the matrix so the slow step need not be repeated.

        Compressed because the matrix is mostly smooth and compresses to
        roughly a tenth of its size, and because it is the one artefact
        worth keeping between runs.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, cell_ids=np.array(self.cell_ids), minutes=self.minutes)
        logger.info("Saved the cell matrix to %s (%.1f MB).", path, path.stat().st_size / 1e6)

    @classmethod
    def load(cls, path: Path) -> TravelTimes:
        with np.load(path, allow_pickle=False) as archive:
            return cls(
                cell_ids=[str(c) for c in archive["cell_ids"]],
                minutes=archive["minutes"].astype(np.uint16),
            )


# ---------------------------------------------------------------------------
# Running the routing engine
# ---------------------------------------------------------------------------


def _travel_time_matrix_class():
    """Find r5py's matrix class across versions.

    r5py renamed this between 0.x and 1.x, from TravelTimeMatrixComputer to
    TravelTimeMatrix, and the project is still moving. Checking for both and
    naming the installed version in the failure is considerably kinder than
    an AttributeError from inside a library the reader has never opened.
    """
    import r5py  # noqa: PLC0415  (heavy, and only needed when actually routing)

    for name in ("TravelTimeMatrix", "TravelTimeMatrixComputer"):
        if hasattr(r5py, name):
            return getattr(r5py, name), name

    raise RuntimeError(
        f"r5py {getattr(r5py, '__version__', 'unknown')} exposes neither "
        f"TravelTimeMatrix nor TravelTimeMatrixComputer. The installed version is "
        f"not one this pipeline knows how to drive. Pin r5py to 1.1.x in "
        f"requirements.txt, or open pipeline/routing.py and add the new name."
    )


def _origins_frame(cells: gpd.GeoDataFrame, ids: list[str]) -> gpd.GeoDataFrame:
    """R5 wants points with an id column, in WGS84.

    The centroid is taken in metres before reprojecting, for the same
    reason as everywhere else: a centroid computed in degrees lands about
    forty metres off in London.
    """
    subset = cells[cells["cell_id"].isin(ids)].copy()
    subset["geometry"] = subset.geometry.centroid
    subset = subset.to_crs(CRS_WGS84)
    return gpd.GeoDataFrame(
        {"id": subset["cell_id"].to_numpy(), "geometry": subset.geometry.to_numpy()},
        crs=CRS_WGS84,
    )


def compute_cell_matrix(
    geography: Geography,
    raw_dir: Path,
    city: City,
    origin_chunk: int = ORIGIN_CHUNK,
) -> TravelTimes:
    """Route every grid cell to every other and return the matrix.

    This is the expensive step. Everything else in the pipeline runs in
    seconds; this one takes minutes and wants several gigabytes of heap for
    the Java engine underneath.
    """
    from r5py import TransportMode, TransportNetwork  # noqa: PLC0415

    osm = raw_dir / city.osm_file
    if not osm.exists():
        raise FileNotFoundError(
            f"No street network extract at {osm}. See docs/data-sources.md."
        )

    feeds = [raw_dir / name for name in city.gtfs_files]
    missing = [f for f in feeds if not f.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing timetable feed(s): "
            + ", ".join(str(f) for f in missing)
            + ". See docs/data-sources.md for where to get each one."
        )

    matrix_class, class_name = _travel_time_matrix_class()
    cells = geography.cells
    cell_ids = list(cells["cell_id"])
    n = len(cell_ids)

    logger.info(
        "Routing %d cells to %d cells, which is %.1f million journeys. "
        "Departures every minute from %s for %d minutes, median kept.",
        n, n, n * n / 1e6, city.departure_datetime.isoformat(timespec="minutes"),
        city.departure_window_minutes,
    )
    logger.info(
        "Building the transport network from %s and %d timetable feed(s): %s.",
        osm.name, len(feeds), ", ".join(f.name for f in feeds),
    )

    network = TransportNetwork(str(osm), [str(f) for f in feeds])
    destinations = _origins_frame(cells, cell_ids)

    # Preallocated and filled in place. Building this by concatenating
    # chunks would hold two copies of a 17MB array at the seam, which is
    # harmless, but it would also hold every intermediate DataFrame, which
    # is not.
    minutes = np.full((n, n), UNREACHABLE, dtype=np.uint16)
    position = {cell: i for i, cell in enumerate(cell_ids)}

    for start in range(0, n, origin_chunk):
        batch = cell_ids[start : start + origin_chunk]
        logger.info(
            "  origins %d to %d of %d", start + 1, min(start + origin_chunk, n), n
        )

        result = matrix_class(
            network,
            origins=_origins_frame(cells, batch),
            destinations=destinations,
            departure=city.departure_datetime,
            departure_time_window=timedelta(minutes=city.departure_window_minutes),
            percentiles=[50],
            transport_modes=[TransportMode.TRANSIT, TransportMode.WALK],
            max_time=timedelta(minutes=MAX_JOURNEY_MINUTES),
            max_time_walking=timedelta(minutes=MAX_WALK_MINUTES),
            snap_to_network=True,
        )
        if class_name == "TravelTimeMatrixComputer":
            result = result.compute_travel_times()

        _fill_from_long_form(result, minutes, position)

    found = float((minutes != UNREACHABLE).mean())
    logger.info(
        "Matrix complete. %.1f%% of cell pairs have a journey inside %d minutes.",
        found * 100, MAX_JOURNEY_MINUTES,
    )
    if found < 0.2:
        # Far too low for a city with a dense network. Almost always the
        # departure date sitting outside the timetable feed's validity, in
        # which case R5 finds walking routes only and the matrix looks like
        # a map of walking distance.
        logger.warning(
            "Only %.1f%% of pairs are reachable, which is too few for a city with a "
            "dense public transport network. The usual cause is DEPARTURE_DATE (%s) "
            "falling outside the validity period of one of %s, which leaves R5 routing "
            "on foot alone. Check calendar.txt inside each feed.",
            found * 100, city.departure_date, ", ".join(f.name for f in feeds),
        )

    return TravelTimes(cell_ids=cell_ids, minutes=minutes)


def _fill_from_long_form(
    result,  # noqa: ANN001  (a GeoDataFrame from r5py)
    minutes: np.ndarray,
    position: dict[str, int],
) -> None:
    """Copy one chunk of R5's long form output into the matrix.

    R5 returns a row per origin and destination pair with the travel time in
    minutes, and omits or nulls the pairs it found no route for. Those stay
    at UNREACHABLE because that is what the preallocated array holds.
    """
    column = next(
        (c for c in ("travel_time", "travel_time_p50", "travel_time_50") if c in result.columns),
        None,
    )
    if column is None:
        raise RuntimeError(
            f"r5py returned columns {sorted(result.columns)}, none of which looks like a "
            f"travel time. The library's output format has changed."
        )

    frame = result[["from_id", "to_id", column]].dropna(subset=[column])
    rows = frame["from_id"].map(position).to_numpy()
    cols = frame["to_id"].map(position).to_numpy()
    values = np.clip(np.rint(frame[column].to_numpy()), 0, MAX_JOURNEY_MINUTES)

    keep = ~(np.isnan(rows.astype(float)) | np.isnan(cols.astype(float)))
    minutes[rows[keep].astype(np.int32), cols[keep].astype(np.int32)] = values[keep].astype(np.uint16)


# ---------------------------------------------------------------------------
# From cells to districts
# ---------------------------------------------------------------------------


def weighted_median(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """The weighted median of each column of values.

    values is (k, m): k samples for each of m destinations. weights is (k,).
    Returns (m,).

    The lower weighted median is used: the smallest value at which the
    cumulative weight reaches half the total. It is a value that actually
    occurs in the data rather than an interpolation between two, which
    matters because the values are whole minutes and an interpolated
    journey time of 34.5 minutes describes no journey anybody takes.
    """
    if values.ndim != 2:
        raise ValueError(f"values must be two dimensional, got shape {values.shape}")
    if weights.shape != (values.shape[0],):
        raise ValueError(
            f"weights must have one entry per sample: expected {(values.shape[0],)}, "
            f"got {weights.shape}"
        )
    if not np.all(weights >= 0):
        raise ValueError("weights must not be negative")

    total = float(weights.sum())
    if total <= 0:
        raise ValueError("weights sum to zero, so there is no median to take")

    order = np.argsort(values, axis=0, kind="stable")
    sorted_values = np.take_along_axis(values, order, axis=0)
    sorted_weights = weights[order]

    cumulative = np.cumsum(sorted_weights, axis=0)
    # The first position where the running weight reaches half the total.
    # A strict comparison would skip the midpoint when the weights are
    # equal and the sample count is even.
    reached = cumulative >= total / 2.0
    index = np.argmax(reached, axis=0)

    return np.take_along_axis(sorted_values, index[None, :], axis=0)[0]


def district_times(
    times: TravelTimes,
    cells_by_district: dict[str, np.ndarray],
    district_order: list[str],
    weights: np.ndarray,
) -> np.ndarray:
    """Journey time from each district to each cell.

    Returns (n_districts, n_cells), uint16, indexed by position in
    district_order and in times.cell_ids.

    A district's journey time is the weighted median over its own cells,
    weighted by how much housing each cell contains. Unreachable cells take
    part in the median at their sentinel value, which is the largest number
    in the range, so they sort to the end and a district whose better half
    cannot reach a destination reads as unreachable rather than as the time
    of its worse half.

    That is the same principle as refusing to treat a suppressed rent as
    zero. A journey that does not exist is not a fast journey.
    """
    if weights.shape != (len(times.cell_ids),):
        raise ValueError(
            f"Expected one weight per cell: {(len(times.cell_ids),)}, got {weights.shape}"
        )

    out = np.full((len(district_order), len(times.cell_ids)), UNREACHABLE, dtype=np.uint16)

    for row, district in enumerate(district_order):
        cell_positions = cells_by_district.get(district)
        if cell_positions is None or len(cell_positions) == 0:
            raise KeyError(
                f"District {district} has no grid cells. build_geography guarantees every "
                f"district at least one, so the geography and the matrix were built from "
                f"different inputs."
            )
        out[row] = weighted_median(
            times.minutes[cell_positions, :].astype(np.uint16),
            weights[cell_positions],
        )

    reachable = float((out != UNREACHABLE).mean())
    logger.info(
        "Aggregated to %d districts. %.1f%% of district and destination pairs are "
        "reachable within %d minutes.",
        len(district_order), reachable * 100, MAX_JOURNEY_MINUTES,
    )
    return out


def combine_two_workplaces(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """The journey time that matters when a household has two workplaces.

    The worse of the two. A district works for a couple only if it works
    for both of them, so the binding constraint is whoever has the longer
    journey, and taking the mean would quietly offer up places that are
    forty minutes for one person and ninety for the other.

    Taken here rather than in the browser only for testing; the published
    site does the same thing on two downloaded arrays.
    """
    if first.shape != second.shape:
        raise ValueError(f"Shapes differ: {first.shape} and {second.shape}")
    return np.maximum(first, second)
