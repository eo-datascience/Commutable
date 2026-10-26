"""Report what dates each timetable feed actually covers.

This exists to prevent one specific, quiet failure. DEPARTURE_DATE has to
fall inside the validity period of every feed. If it falls outside one of
them, R5 finds no services on that feed and routes those journeys on foot
instead of failing, and the result is a map of walking distance that looks
entirely reasonable and is wrong everywhere.

Routing takes minutes and the error only shows up afterwards, as an
implausibly low share of reachable pairs. Reading calendar.txt first takes
a second.

    python scripts/check_feeds.py
    python scripts/check_feeds.py --date 2026-10-20
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.config import RAW  # noqa: E402
from pipeline.config import city as get_city  # noqa: E402

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _read(archive: zipfile.ZipFile, name: str) -> list[dict]:
    match = next((n for n in archive.namelist() if n.endswith(name)), None)
    if match is None:
        return []
    with archive.open(match) as handle:
        return list(csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig")))


def _as_date(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), "%Y%m%d").date()
    except (ValueError, AttributeError):
        return None


def services_on(feed: Path, when: date) -> int:
    """How many services run on a given date, by GTFS's own rules.

    calendar.txt gives a weekly pattern and a date range. calendar_dates.txt
    then adds services on particular dates (exception type 1) and removes
    them on others (type 2), which is how bank holidays are handled. A feed
    may use either file or both.
    """
    with zipfile.ZipFile(feed) as archive:
        calendar = _read(archive, "calendar.txt")
        exceptions = _read(archive, "calendar_dates.txt")

    weekday = DAYS[when.weekday()]
    running: set[str] = set()

    for row in calendar:
        start, end = _as_date(row.get("start_date", "")), _as_date(row.get("end_date", ""))
        if start is None or end is None or not (start <= when <= end):
            continue
        if (row.get(weekday) or "").strip() == "1":
            running.add(row.get("service_id", ""))

    for row in exceptions:
        if _as_date(row.get("date", "")) != when:
            continue
        kind = (row.get("exception_type") or "").strip()
        if kind == "1":
            running.add(row.get("service_id", ""))
        elif kind == "2":
            running.discard(row.get("service_id", ""))

    return len(running)


def describe(feed: Path) -> tuple[date | None, date | None]:
    with zipfile.ZipFile(feed) as archive:
        calendar = _read(archive, "calendar.txt")
        exceptions = _read(archive, "calendar_dates.txt")
        routes = _read(archive, "routes.txt")

    dates = [d for row in calendar for d in (_as_date(row.get("start_date", "")),
                                             _as_date(row.get("end_date", ""))) if d]
    dates += [d for row in exceptions if (d := _as_date(row.get("date", "")))]

    kinds = Counter((r.get("route_type") or "?").strip() for r in routes)
    names = {"0": "tram", "1": "metro", "2": "rail", "3": "bus", "4": "ferry",
             "5": "cable tram", "6": "aerial", "7": "funicular"}
    summary = ", ".join(f"{n} {names.get(k, 'type ' + k)}" for k, n in kinds.most_common())

    print(f"  routes:   {summary or 'none listed'}")
    if not dates:
        print("  calendar: no dates found, which is unusual and worth looking at")
        return None, None

    first, last = min(dates), max(dates)
    print(f"  covers:   {first} to {last}")
    return first, last


def main() -> int:
    parser = argparse.ArgumentParser(description="Check what the timetable feeds cover")
    parser.add_argument("--city", default=None)
    parser.add_argument("--raw-dir", type=Path, default=RAW)
    parser.add_argument(
        "--date", default=None,
        help="Date to test, as YYYY-MM-DD. Defaults to the city's DEPARTURE_DATE.",
    )
    args = parser.parse_args()

    city = get_city(args.city)
    when = date.fromisoformat(args.date or city.departure_date)
    print(f"Testing {when} ({DAYS[when.weekday()].title()})\n")

    ok = True
    for name in city.gtfs_files:
        feed = args.raw_dir / name
        print(name)
        if not feed.exists():
            print("  MISSING. See docs/data-sources.md.\n")
            ok = False
            continue
        try:
            describe(feed)
            running = services_on(feed, when)
        except (zipfile.BadZipFile, KeyError) as error:
            print(f"  Could not read it: {error}\n")
            ok = False
            continue

        if running == 0:
            print(f"  services: NONE on {when}.")
            print("            R5 would route every journey on this feed on foot, and the")
            print("            map would look plausible and be wrong. Pick another date.")
            ok = False
        else:
            print(f"  services: {running:,} running on {when}")
        print()

    if ok:
        print(f"Both feeds carry services on {when}. Set DEPARTURE_DATE to it in")
        print("pipeline/config.py if it is not already, then run scripts/build.py.")
        return 0

    print("Fix the above before routing. Suggestions:")
    _suggest(city, args.raw_dir)
    return 1


def _suggest(city, raw_dir: Path) -> None:  # noqa: ANN001
    """Find a weekday that works for every feed present."""
    feeds = [raw_dir / n for n in city.gtfs_files if (raw_dir / n).exists()]
    if not feeds:
        return

    start = date.today()
    for offset in range(1, 60):
        candidate = start + timedelta(days=offset)
        if candidate.weekday() > 4:
            continue
        try:
            if all(services_on(f, candidate) > 0 for f in feeds):
                print(f"  {candidate} ({DAYS[candidate.weekday()].title()}) works for "
                      f"every feed you have.")
                return
        except (zipfile.BadZipFile, KeyError):
            return
    print("  No weekday in the next two months works for every feed. Re-download them.")


if __name__ == "__main__":
    sys.exit(main())
