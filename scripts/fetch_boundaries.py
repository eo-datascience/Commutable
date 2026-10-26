"""Download the boundary files, which are the only inputs that can be fetched
without a human in the loop.

The other three inputs cannot. The ONS rent workbook is a one off ad hoc
release whose URL changes with each edition, the OpenStreetMap extract has
to be chosen by region, and the timetable feed sits behind a licence
acceptance. Those are listed in docs/data-sources.md with what to click.

Run from the repository root:

    python scripts/fetch_boundaries.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.config import RAW, city  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("fetch")

POSTCODE_POLYGONS = (
    "https://raw.githubusercontent.com/missinglink/uk-postcode-polygons/master/geojson"
)
BOROUGHS = (
    "https://raw.githubusercontent.com/radoi90/housequest-data/master/london_boroughs.geojson"
)

# Below this a response is certainly an error page or a truncated download
# rather than a boundary file, and writing it would produce a confusing
# failure two steps later instead of here.
MIN_PLAUSIBLE_BYTES = 2_000


def download(url: str, destination: Path, force: bool = False) -> bool:
    if destination.exists() and not force:
        logger.info("%-28s already present", destination.name)
        return True

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
            body = response.read()
    except (urllib.error.URLError, TimeoutError) as error:
        logger.error("%-28s FAILED (%s)", destination.name, error)
        return False

    if len(body) < MIN_PLAUSIBLE_BYTES:
        logger.error(
            "%-28s FAILED (only %d bytes, which is not a boundary file)",
            destination.name, len(body),
        )
        return False

    # Parsing before writing means a malformed download never reaches disk
    # and never gets mistaken for a cached success on the next run.
    try:
        parsed = json.loads(body)
        feature_count = len(parsed.get("features", []))
    except json.JSONDecodeError as error:
        logger.error("%-28s FAILED (not valid JSON: %s)", destination.name, error)
        return False

    if feature_count == 0:
        logger.error("%-28s FAILED (no features)", destination.name)
        return False

    destination.write_bytes(body)
    logger.info("%-28s %6d bytes, %3d features", destination.name, len(body), feature_count)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Download boundary files")
    parser.add_argument("--city", default=None, help="City id (default: london)")
    parser.add_argument("--force", action="store_true", help="Re-download files already present")
    args = parser.parse_args()

    target = city(args.city)
    failures: list[str] = []

    logger.info("Boroughs")
    if not download(BOROUGHS, RAW / target.boundary_file, args.force):
        failures.append(target.boundary_file)

    logger.info("")
    logger.info("Postcode districts (%d areas)", len(target.postcode_areas))
    district_dir = RAW / "postcode_districts"
    for area in target.postcode_areas:
        if not download(f"{POSTCODE_POLYGONS}/{area}.geojson", district_dir / f"{area}.geojson", args.force):
            failures.append(f"{area}.geojson")

    logger.info("")
    if failures:
        logger.error("%d file(s) failed: %s", len(failures), ", ".join(failures))
        logger.error("Re-run to retry. Only the missing files will be fetched.")
        return 1

    logger.info("Boundaries ready in %s", RAW)
    logger.info("The three remaining inputs are listed in docs/data-sources.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
