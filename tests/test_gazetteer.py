"""Tests for the gazetteer, which turns what a visitor types into a grid cell.

The search box is built from the timetable feeds, and London needs more than
one of them: rail, tube, DLR and trams come from one publisher and the buses
from another. That makes the bus feed the thing to be careful about. It
carries about nineteen thousand stops, none of which anybody searches for by
name, and all of which are parentless stops that the fallback path would
otherwise pull in wholesale.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from pipeline.config import LONDON
from pipeline.gazetteer import _is_bus_only, build_gazetteer, nearest_cell
from pipeline.geography import Geography, build_grid


@pytest.fixture
def geography() -> Geography:
    outline = gpd.GeoSeries([box(-0.16, 51.48, -0.10, 51.52)], crs="EPSG:4326")
    districts = gpd.GeoDataFrame(
        {"district": ["AA1", "AA2"], "share_in_city": [1.0, 1.0], "area_km2": [4.0, 4.0]},
        geometry=[box(-0.16, 51.48, -0.13, 51.52), box(-0.13, 51.48, -0.10, 51.52)],
        crs="EPSG:4326",
    )
    grid = build_grid(outline, 750)
    grid["district"] = "AA1"
    grid["weight"] = 1.0
    return Geography(city=LONDON, boundary=outline, districts=districts, cells=grid)


def write_feed(
    path: Path,
    stops: list[dict],
    route_types: list[str],
) -> Path:
    """A minimal GTFS feed: just the two files the gazetteer reads."""
    with zipfile.ZipFile(path, "w") as archive:
        stops_csv = io.StringIO()
        writer = csv.DictWriter(
            stops_csv,
            fieldnames=["stop_id", "stop_name", "stop_lat", "stop_lon",
                        "location_type", "parent_station"],
        )
        writer.writeheader()
        for stop in stops:
            writer.writerow({"location_type": "", "parent_station": "", **stop})
        archive.writestr("stops.txt", stops_csv.getvalue())

        routes_csv = io.StringIO()
        routes = csv.DictWriter(routes_csv, fieldnames=["route_id", "route_type"])
        routes.writeheader()
        for i, route_type in enumerate(route_types):
            routes.writerow({"route_id": f"r{i}", "route_type": route_type})
        archive.writestr("routes.txt", routes_csv.getvalue())
    return path


RAIL_STOPS = [
    {"stop_id": "1", "stop_name": "Waterloo", "stop_lat": "51.503", "stop_lon": "-0.113",
     "location_type": "1"},
    {"stop_id": "2", "stop_name": "Waterloo Platform 1", "stop_lat": "51.503",
     "stop_lon": "-0.113", "location_type": "0", "parent_station": "1"},
    {"stop_id": "3", "stop_name": "Vauxhall", "stop_lat": "51.486", "stop_lon": "-0.123",
     "location_type": "1"},
]

BUS_STOPS = [
    {"stop_id": "b1", "stop_name": "Lambeth Road", "stop_lat": "51.496", "stop_lon": "-0.115"},
    {"stop_id": "b2", "stop_name": "Kennington Lane", "stop_lat": "51.488", "stop_lon": "-0.118"},
]


# ---------------------------------------------------------------------------
# Telling a bus feed apart
# ---------------------------------------------------------------------------


def test_a_feed_of_buses_only_is_recognised(tmp_path):
    feed = write_feed(tmp_path / "buses.zip", BUS_STOPS, route_types=["3", "3", "3"])

    assert _is_bus_only(feed) is True


def test_a_rail_feed_is_not(tmp_path):
    feed = write_feed(tmp_path / "rail.zip", RAIL_STOPS, route_types=["2", "1", "0"])

    assert _is_bus_only(feed) is False


def test_a_mixed_feed_is_not(tmp_path):
    """The combined rail and TfL feed carries replacement buses alongside
    tube and tram. It must not be thrown away for that."""
    feed = write_feed(tmp_path / "mixed.zip", RAIL_STOPS, route_types=["2", "1", "3"])

    assert _is_bus_only(feed) is False


def test_a_feed_with_no_routes_file_gets_the_benefit_of_the_doubt(tmp_path):
    path = tmp_path / "odd.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon\n1,A,51.5,-0.12\n")

    assert _is_bus_only(path) is False


def test_an_unreadable_feed_does_not_raise(tmp_path):
    path = tmp_path / "broken.zip"
    path.write_bytes(b"not a zip file at all")

    assert _is_bus_only(path) is False


# ---------------------------------------------------------------------------
# Building the gazetteer from several feeds
# ---------------------------------------------------------------------------


def test_stations_from_a_rail_feed_reach_the_search_box(geography, tmp_path):
    feed = write_feed(tmp_path / "rail.zip", RAIL_STOPS, route_types=["2", "1"])

    places = build_gazetteer(geography, [feed])
    names = {p.name for p in places}

    assert "Waterloo" in names
    assert "Vauxhall" in names


def test_platforms_are_left_out(geography, tmp_path):
    """A visitor typing Waterloo wants one result, not eleven."""
    feed = write_feed(tmp_path / "rail.zip", RAIL_STOPS, route_types=["2"])

    names = [p.name for p in build_gazetteer(geography, [feed])]

    assert "Waterloo Platform 1" not in names
    assert names.count("Waterloo") == 1


def test_a_bus_feed_adds_no_names(geography, tmp_path):
    """The whole point of the bus-only check. Nineteen thousand bus stops in
    the search box would bury every station in it, and nobody describes
    where they work by naming a bus stop."""
    rail = write_feed(tmp_path / "rail.zip", RAIL_STOPS, route_types=["2"])
    buses = write_feed(tmp_path / "buses.zip", BUS_STOPS, route_types=["3"])

    with_buses = {p.name for p in build_gazetteer(geography, [rail, buses])}
    without = {p.name for p in build_gazetteer(geography, [rail])}

    assert with_buses == without
    assert "Lambeth Road" not in with_buses


def test_districts_and_boroughs_are_there_with_no_feed_at_all(geography):
    places = build_gazetteer(geography, [])
    names = {p.name for p in places}

    assert "AA1" in names
    assert "AA2" in names
    assert all(p.kind in {"district", "borough"} for p in places)


def test_a_missing_feed_is_skipped_rather_than_fatal(geography, tmp_path):
    """One feed arriving and the other not should still produce a usable
    search box, because the build is worth finishing."""
    rail = write_feed(tmp_path / "rail.zip", RAIL_STOPS, route_types=["2"])

    places = build_gazetteer(geography, [rail, tmp_path / "never-downloaded.zip"])

    assert "Waterloo" in {p.name for p in places}


def test_a_station_wins_a_name_clash_with_a_borough(geography, tmp_path):
    """Somebody typing Richmond means the station they get off at."""
    stops = [{"stop_id": "1", "stop_name": "AA1", "stop_lat": "51.50",
              "stop_lon": "-0.14", "location_type": "1"}]
    feed = write_feed(tmp_path / "rail.zip", stops, route_types=["2"])

    places = build_gazetteer(geography, [feed])
    matching = [p for p in places if p.name == "AA1"]

    assert len(matching) == 1
    assert matching[0].kind == "station"


def test_every_place_resolves_to_a_real_grid_cell(geography, tmp_path):
    feed = write_feed(tmp_path / "rail.zip", RAIL_STOPS, route_types=["2"])

    places = build_gazetteer(geography, [feed])
    cells = set(geography.cell_ids)

    assert places
    assert all(p.cell_id in cells for p in places)


def test_a_station_well_outside_the_city_is_dropped(geography, tmp_path):
    """A national feed reaches far beyond London. Offering Manchester would
    hand the visitor a journey measured from somewhere else entirely."""
    stops = RAIL_STOPS + [
        {"stop_id": "9", "stop_name": "Manchester Piccadilly", "stop_lat": "53.477",
         "stop_lon": "-2.231", "location_type": "1"},
    ]
    feed = write_feed(tmp_path / "rail.zip", stops, route_types=["2"])

    names = {p.name for p in build_gazetteer(geography, [feed])}

    assert "Manchester Piccadilly" not in names
    assert "Waterloo" in names


# ---------------------------------------------------------------------------
# Snapping
# ---------------------------------------------------------------------------


def test_nearest_cell_returns_a_cell_and_a_distance(geography):
    cells = geography.cells
    centres = cells.geometry.centroid
    xs, ys = centres.x.to_numpy(), centres.y.to_numpy()

    cell_id, metres = nearest_cell(-0.13, 51.50, cells, xs, ys)

    assert cell_id in set(geography.cell_ids)
    assert metres < 1500
