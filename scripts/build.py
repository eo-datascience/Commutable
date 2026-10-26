"""Run the pipeline.

    python scripts/build.py                    everything, from the real inputs
    python scripts/build.py --reuse-matrix     skip routing, reuse the saved matrix
    python scripts/build.py --describe-rents   print the workbook's layout and stop

Routing is the only slow stage. Once it has run, the matrix is saved and
--reuse-matrix skips it, which is what you want while changing the rent
handling or the export format.

There is also a mode that fabricates journey times and rents so the site
can be built and looked at before the real inputs are in place. It is
deliberately hard to use by accident: it prints a warning on every run and
it writes a flag into the published metadata that makes the site display a
banner over the map saying the numbers are invented. A screenshot of
fabricated figures is worse than no screenshot.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.config import (  # noqa: E402
    DERIVED,
    RAW,
    SITE_DATA,
    UNREACHABLE,
)
from pipeline.config import (
    city as get_city,
)
from pipeline.export import export_all  # noqa: E402
from pipeline.gazetteer import build_gazetteer  # noqa: E402
from pipeline.geography import build_geography, district_cell_index  # noqa: E402
from pipeline.rent import describe_workbook, fit_all, load_rents  # noqa: E402
from pipeline.routing import TravelTimes, compute_cell_matrix, district_times  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)-20s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("build")

MATRIX_PATH = DERIVED / "cell_travel_times.npz"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the published data")
    parser.add_argument("--city", default=None)
    parser.add_argument("--raw-dir", type=Path, default=RAW)
    parser.add_argument("--out-dir", type=Path, default=SITE_DATA)
    parser.add_argument(
        "--reuse-matrix", action="store_true",
        help="Load the saved cell matrix instead of routing again",
    )
    parser.add_argument(
        "--no-building-weights", action="store_true",
        help="Take an unweighted median over a district's cells",
    )
    parser.add_argument(
        "--describe-rents", action="store_true",
        help="Print the rent workbook's layout and exit",
    )
    parser.add_argument(
        "--feeds", nargs="+", metavar="FILE",
        help="Timetable feeds to route over, overriding the city's own list. Useful for "
             "proving the pipeline on one small feed before adding a large one.",
    )
    parser.add_argument(
        "--max-memory", default="70%",
        help="Memory limit for the Java engine R5 runs on. A plain size such as 12G, or "
             "a share of total RAM such as 70%%. Only the routing stage uses it.",
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Fabricate journey times and rents. For looking at the site before the "
             "real inputs exist. Marks the output as invented.",
    )
    args = parser.parse_args()

    city = get_city(args.city)
    if args.feeds:
        # dataclasses.replace rather than mutation, because City is frozen
        # and the rest of the pipeline is entitled to assume it does not
        # change underneath it.
        city = dataclasses.replace(city, gtfs_files=tuple(args.feeds))
        logger.warning(
            "Routing over %d of the city's %d timetable feeds: %s. The journey times "
            "will be missing whatever the others carry.",
            len(city.gtfs_files), len(get_city(args.city).gtfs_files),
            ", ".join(city.gtfs_files),
        )

    if args.describe_rents:
        print(describe_workbook(args.raw_dir / city.rent_file))
        return 0

    if args.synthetic:
        logger.warning("=" * 72)
        logger.warning("SYNTHETIC BUILD. The journey times and rents below are invented.")
        logger.warning("The site will show a banner saying so. Do not screenshot it.")
        logger.warning("=" * 72)

    # --- geography -------------------------------------------------------
    logger.info("Stage 1 of 5: geography")
    geography = build_geography(
        city, args.raw_dir, weight_by_buildings=not args.no_building_weights
    )
    cells_by_district = district_cell_index(geography.districts, geography.cells)

    # --- rent ------------------------------------------------------------
    logger.info("")
    logger.info("Stage 2 of 5: rent")
    if args.synthetic:
        rents = _synthetic_rents(geography)
    else:
        table = load_rents(args.raw_dir / city.rent_file, districts=set(geography.district_ids))
        rents = fit_all(table)

    # --- routing ---------------------------------------------------------
    logger.info("")
    logger.info("Stage 3 of 5: routing")
    if args.synthetic:
        times = _synthetic_matrix(geography)
    elif args.reuse_matrix:
        if not MATRIX_PATH.exists():
            logger.error("No saved matrix at %s. Run without --reuse-matrix first.", MATRIX_PATH)
            return 1
        times = TravelTimes.load(MATRIX_PATH)
        if times.cell_ids != geography.cell_ids:
            logger.error(
                "The saved matrix covers %d cells but the geography has %d, so they were "
                "built from different inputs. Delete %s and route again.",
                len(times.cell_ids), len(geography.cell_ids), MATRIX_PATH,
            )
            return 1
        logger.info("Reused the saved matrix: %d cells, %.1f%% of pairs reachable.",
                    len(times.cell_ids), times.reachable_share * 100)
    else:
        # R5 runs on a Java virtual machine, which claims a fixed maximum
        # heap at startup and dies rather than growing past it. The default
        # is a quarter of total memory, which is not enough to build a
        # network from a street extract and a city's bus timetables
        # together, and the failure arrives several minutes in.
        #
        # r5py takes this setting from its own command line, so it is passed
        # by appending to sys.argv before r5py is first imported. That looks
        # peculiar and it is what the library expects. Doing it here rather
        # than in a config file spares anyone running this from hunting for
        # an AppData folder on Windows or a dotfile on Linux.
        if "--max-memory" not in sys.argv:
            sys.argv.extend(["--max-memory", args.max_memory])
        logger.info("Giving the routing engine a memory limit of %s.", args.max_memory)

        times = compute_cell_matrix(geography, args.raw_dir, city)
        times.save(MATRIX_PATH)

    # --- aggregate -------------------------------------------------------
    logger.info("")
    logger.info("Stage 4 of 5: aggregating cells to districts")
    minutes = district_times(
        times, cells_by_district, geography.district_ids,
        geography.cells["weight"].to_numpy(),
    )

    # --- export ----------------------------------------------------------
    logger.info("")
    logger.info("Stage 5 of 5: export")
    places = build_gazetteer(geography, [args.raw_dir / n for n in city.gtfs_files])
    export_all(
        geography=geography,
        rents=rents,
        district_minutes=minutes,
        places=places,
        out_dir=args.out_dir,
        data_vintages=_vintages(args.raw_dir, city),
    )

    if args.synthetic:
        _mark_synthetic(args.out_dir)
        logger.warning("")
        logger.warning("This build is synthetic. The site will say so over the map.")

    logger.info("")
    logger.info("Done.")
    return 0


# ---------------------------------------------------------------------------
# Data vintages
# ---------------------------------------------------------------------------


def _vintages(raw_dir: Path, city) -> dict[str, str]:  # noqa: ANN001
    """When each input was last changed on disk.

    A modification time is not the publication date, which is why the site
    labels it as when the file was obtained. It is still the honest thing to
    show: a visitor deserves to know whether the timetable is from this
    month or from eighteen months ago.
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    vintages: dict[str, str] = {}
    pairs = [("rent", city.rent_file)]
    # Each feed dated separately, since they come from different publishers
    # and one can be months staler than the other without it showing.
    for i, feed in enumerate(city.gtfs_files):
        pairs.append(("timetable" if i == 0 else f"timetable_{i + 1}", feed))

    for label, name in (
        *pairs,
        ("street_network", city.osm_file),
        ("boundaries", city.boundary_file),
    ):
        path = raw_dir / name
        if path.exists():
            when = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            vintages[label] = when.date().isoformat()
    return vintages


def _mark_synthetic(out_dir: Path) -> None:
    path = out_dir / "meta.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["synthetic"] = True
    payload["synthetic_warning"] = (
        "These journey times and rents were fabricated so the site could be built "
        "before the real data was in place. Every number on this page is invented."
    )
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Synthetic inputs, for building the site before the real ones arrive
# ---------------------------------------------------------------------------


def _synthetic_matrix(geography) -> TravelTimes:  # noqa: ANN001
    """Journey times that look like a city without being one.

    Built so the map has structure to look at: times rise with distance
    from the centre and with distance between cells, so the shapes on the
    screen behave the way a real answer would and the colours and legend
    can be judged.
    """
    import geopandas as gpd  # noqa: PLC0415

    logger.warning("Fabricating a journey time matrix. These are not real journeys.")

    centres = geography.cells.geometry.centroid
    xs, ys = centres.x.to_numpy(), centres.y.to_numpy()

    # Roughly Charing Cross in British National Grid.
    centre = gpd.GeoSeries(gpd.points_from_xy([-0.1246], [51.5074]), crs="EPSG:4326").to_crs(
        geography.cells.crs
    ).iloc[0]

    straight = np.hypot(xs[:, None] - xs[None, :], ys[:, None] - ys[None, :]) / 1000.0
    from_centre = np.hypot(xs - centre.x, ys - centre.y) / 1000.0

    rng = np.random.default_rng(42)
    # A fixed overhead, time proportional to distance, a penalty for both
    # ends being far out (where you would have to come in and go back out),
    # and noise.
    minutes = (
        9
        + straight * 2.1
        + 0.45 * np.minimum(from_centre[:, None], from_centre[None, :])
        + rng.normal(0, 2.5, size=straight.shape)
    )
    minutes = (minutes + minutes.T) / 2
    np.fill_diagonal(minutes, 0.0)

    capped = np.where(minutes > 120, UNREACHABLE, np.clip(np.rint(minutes), 0, 120))
    return TravelTimes(cell_ids=geography.cell_ids, minutes=capped.astype(np.uint16))


def _synthetic_rents(geography):  # noqa: ANN001
    """Rents that look like London without being London's.

    Expensive in the centre and the west, cheaper to the east and the outer
    south, with a plausible spread. Enough structure that the affordability
    colouring can be judged; not a number anybody should quote.
    """
    import math  # noqa: PLC0415

    import geopandas as gpd  # noqa: PLC0415

    from pipeline.rent import RentReport, fit_lognormal  # noqa: PLC0415

    logger.warning("Fabricating rents. These are not real rents.")

    metric = geography.districts.to_crs(geography.cells.crs)
    points = metric.geometry.representative_point()
    centre = gpd.GeoSeries(gpd.points_from_xy([-0.1246], [51.5074]), crs="EPSG:4326").to_crs(
        geography.cells.crs
    ).iloc[0]

    distance_km = np.hypot(points.x.to_numpy() - centre.x, points.y.to_numpy() - centre.y) / 1000
    westness = (centre.x - points.x.to_numpy()) / 1000

    rng = np.random.default_rng(7)
    report = RentReport()

    base = {"1": 1500.0, "2": 1900.0, "3": 2350.0}
    for position, district in enumerate(geography.district_ids):
        for category, anchor in base.items():
            median = anchor * (
                1.55
                - 0.055 * min(distance_km[position], 18.0)
                + 0.012 * westness[position]
            ) + rng.normal(0, 60)
            median = float(max(700.0, median))
            sigma = float(0.17 + rng.random() * 0.1)
            mu = math.log(median)
            from pipeline.rent import Z_QUARTILE  # noqa: PLC0415

            report.distributions[(district, category)] = fit_lognormal(
                district=district,
                bedrooms=category,
                sample=int(rng.integers(40, 900)),
                median=round(median),
                lower_quartile=round(math.exp(mu - sigma * Z_QUARTILE)),
                upper_quartile=round(math.exp(mu + sigma * Z_QUARTILE)),
                mean=round(math.exp(mu + sigma**2 / 2)),
            )

    logger.info("Fabricated %d district and category combinations.", len(report.distributions))
    return report


if __name__ == "__main__":
    sys.exit(main())
