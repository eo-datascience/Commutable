"""Tests for the geography module.

These run against the real London boundary files, which the fetch script
downloads and which are small enough to live in the repository. Running
against real geometry rather than invented squares is the point: the two
bugs this module has had were both about real shapes, one about districts
smaller than a grid cell and one about ring winding, and neither would
have appeared against a test fixture made of rectangles.
"""

from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from pipeline.config import LONDON, RAW
from pipeline.geography import (
    assign_cells_to_districts,
    build_geography,
    build_grid,
    cell_centroids_wgs84,
    cell_id,
    district_cell_index,
    district_sort_key,
    load_city_boundary,
    load_postcode_districts,
    orient_rfc7946,
    uniform_weights,
    write_geojson,
)

HAVE_BOUNDARIES = (RAW / LONDON.boundary_file).exists() and (
    RAW / "postcode_districts" / "SE.geojson"
).exists()

needs_boundaries = pytest.mark.skipif(
    not HAVE_BOUNDARIES,
    reason="Run scripts/fetch_boundaries.py first. These tests use the real London shapes.",
)


@pytest.fixture(scope="module")
def geography():
    if not HAVE_BOUNDARIES:
        pytest.skip("boundaries not downloaded")
    # Building weights need the street network extract, which is a 70MB
    # download. The weighting itself is tested separately.
    return build_geography(LONDON, RAW, weight_by_buildings=False)


# ---------------------------------------------------------------------------
# Ring winding
# ---------------------------------------------------------------------------


def test_a_clockwise_ring_is_turned_counter_clockwise():
    """RFC 7946 requires a counter-clockwise exterior ring, and anything
    drawing GeoJSON on a sphere reads the winding as the definition of
    which side is inside."""
    clockwise = Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])
    assert clockwise.exterior.is_ccw is False

    assert orient_rfc7946(clockwise).exterior.is_ccw is True


def test_an_already_correct_ring_is_left_alone():
    counter_clockwise = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    assert counter_clockwise.exterior.is_ccw is True

    assert orient_rfc7946(counter_clockwise).exterior.is_ccw is True


def test_holes_are_wound_the_opposite_way():
    shell = [(0, 0), (0, 4), (4, 4), (4, 0)]
    hole = [(1, 1), (2, 1), (2, 2), (1, 2)]

    oriented = orient_rfc7946(Polygon(shell, [hole]))

    assert oriented.exterior.is_ccw is True
    assert all(ring.is_ccw is False for ring in oriented.interiors)


def test_every_part_of_a_multipolygon_is_wound():
    multi = MultiPolygon(
        [
            Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
            Polygon([(3, 3), (3, 4), (4, 4), (4, 3)]),
        ]
    )

    oriented = orient_rfc7946(multi)

    assert all(part.exterior.is_ccw for part in oriented.geoms)


@needs_boundaries
def test_every_published_district_is_wound_for_the_standard(geography, tmp_path):
    """The bug this guards against was invisible in the data and total on
    screen. A clockwise exterior ring does not draw the district backwards,
    it draws the entire earth except that district, so one wrongly wound
    polygon turns the whole map into a single flat field of colour.

    All 274 came out of the source wound the wrong way. The city outline
    did not, because unioning the boroughs happened to produce the right
    winding, so the map drew an outline that looked correct over a sheet of
    grey that was not.
    """
    path = tmp_path / "districts.geojson"
    write_geojson(geography.districts[["district", "geometry"]], path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["features"]) == len(geography.districts)

    for feature in payload["features"]:
        geometry = feature["geometry"]
        rings = (
            [geometry["coordinates"]]
            if geometry["type"] == "Polygon"
            else geometry["coordinates"]
        )
        for polygon in rings:
            exterior, *holes = polygon
            assert _is_counter_clockwise(exterior), (
                f"{feature['properties']['district']} has a clockwise exterior ring"
            )
            for hole in holes:
                assert not _is_counter_clockwise(hole)


def _is_counter_clockwise(ring: list[list[float]]) -> bool:
    """The shoelace formula, written out rather than taken from shapely.

    The point of the test is to check the published file, so it should not
    be verified with the same library that produced it.
    """
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        total += (x2 - x1) * (y2 + y1)
    return total < 0


# ---------------------------------------------------------------------------
# Districts
# ---------------------------------------------------------------------------


@needs_boundaries
def test_the_city_boundary_is_one_shape_of_about_the_right_size(geography):
    outline = geography.boundary.to_crs("EPSG:27700").iloc[0]
    area_km2 = outline.area / 1e6

    # Greater London is 1,572 square kilometres. A simplified union of
    # borough boundaries should land within a few per cent of that, and a
    # figure far off would mean boroughs are missing or doubled.
    assert 1500 < area_km2 < 1650


@needs_boundaries
def test_london_has_the_expected_number_of_postcode_districts(geography):
    # 274 at the 10% threshold. The figure is asserted loosely because the
    # upstream boundaries can be edited, and tightly enough that losing a
    # whole postcode area would fail.
    assert 250 <= len(geography.districts) <= 300
    for expected in ("SE10", "E14", "N1", "SW1A", "W1D", "CR0", "HA9"):
        assert expected in geography.district_ids


@needs_boundaries
def test_districts_mostly_outside_the_city_are_dropped(geography):
    kept = set(geography.district_ids)
    # Deep in Surrey, Essex and Hertfordshire respectively.
    for outside in ("KT22", "RM17", "WD3"):
        assert outside not in kept


@needs_boundaries
def test_the_share_inside_the_city_is_recorded_rather_than_discarded(geography):
    shares = geography.districts["share_in_city"]

    assert shares.min() >= LONDON.min_district_in_city
    assert shares.max() <= 1.0
    # Most of London's districts are wholly inside it.
    assert (shares > 0.99).mean() > 0.7


def test_a_district_appearing_twice_is_an_error(tmp_path):
    """A duplicate would be counted twice in every aggregate downstream and
    is far easier to catch here than to explain later."""
    directory = tmp_path / "postcode_districts"
    directory.mkdir()
    frame = gpd.GeoDataFrame(
        {"name": ["ZZ1", "ZZ1"]},
        geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)],
        crs="EPSG:4326",
    )
    frame.to_file(directory / "ZZ.geojson", driver="GeoJSON")

    with pytest.raises(ValueError, match="more than once"):
        load_postcode_districts(directory, ("ZZ",))


def test_a_missing_postcode_area_file_names_the_area(tmp_path):
    directory = tmp_path / "postcode_districts"
    directory.mkdir()

    with pytest.raises(FileNotFoundError, match="SE, SW"):
        load_postcode_districts(directory, ("SE", "SW"))


def test_a_boundary_file_without_a_name_column_says_what_it_found(tmp_path):
    directory = tmp_path / "postcode_districts"
    directory.mkdir()
    gpd.GeoDataFrame(
        {"colour": ["red"]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:4326"
    ).to_file(directory / "ZZ.geojson", driver="GeoJSON")

    with pytest.raises(ValueError, match="colour"):
        load_postcode_districts(directory, ("ZZ",))


def test_a_missing_city_boundary_points_at_the_fetch_script(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch_boundaries"):
        load_city_boundary(tmp_path / "absent.geojson")


@pytest.mark.parametrize(
    "codes, expected",
    [
        (["SE10", "SE1", "SE2"], ["SE1", "SE2", "SE10"]),
        (["W12", "W1A", "W2"], ["W1A", "W2", "W12"]),
        (["EC1V", "EC1A", "EC1M"], ["EC1A", "EC1M", "EC1V"]),
        (["N1", "E1", "SE1"], ["E1", "N1", "SE1"]),
    ],
)
def test_districts_sort_the_way_a_person_reads_them(codes, expected):
    """SE1, SE2, SE10, not SE1, SE10, SE2. The order is published as the
    index of every journey time array, so it has to be stable and it may as
    well be readable."""
    assert sorted(codes, key=district_sort_key) == expected


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------


@needs_boundaries
def test_the_grid_covers_the_city_at_the_configured_size(geography):
    cells = geography.cells

    assert 2000 < len(cells) < 4000
    # Each cell should be the stated size, to the millimetre.
    areas = cells.geometry.area
    assert np.allclose(areas, LONDON.grid_cell_metres**2)


def test_the_grid_is_anchored_rather_than_fitted_to_the_bounding_box():
    """Anchoring to a fixed coordinate means a boundary file updated by a
    metre does not shift every cell and rename every published file."""
    small = gpd.GeoSeries([box(-0.2, 51.45, -0.1, 51.52)], crs="EPSG:4326")
    larger = gpd.GeoSeries([box(-0.3, 51.40, -0.05, 51.55)], crs="EPSG:4326")

    shared = set(build_grid(small, 750)["cell_id"]) & set(build_grid(larger, 750)["cell_id"])

    assert len(shared) > 0
    # A cell id must mean the same square in both grids.
    a = build_grid(small, 750).set_index("cell_id")
    b = build_grid(larger, 750).set_index("cell_id")
    for key in list(shared)[:20]:
        assert a.loc[key, "geometry"].equals(b.loc[key, "geometry"])


def test_a_cell_id_decodes_back_to_its_position():
    assert cell_id(41, 72) == "041072"
    assert cell_id(0, 0) == "000000"
    assert cell_id(999, 999) == "999999"


def test_a_cell_outside_the_addressable_grid_is_an_error():
    for bad in ((-1, 0), (1000, 0), (0, -1), (0, 1000)):
        with pytest.raises(ValueError, match="addressable grid"):
            cell_id(*bad)


def test_cells_barely_touching_the_city_are_trimmed():
    """Without a coverage threshold the grid grows a fringe of cells almost
    entirely outside the city, each costing a published file and describing
    a journey from somewhere nobody works."""
    outline = gpd.GeoSeries([box(-0.20, 51.45, -0.10, 51.52)], crs="EPSG:4326")

    generous = build_grid(outline, 750, min_coverage=0.01)
    strict = build_grid(outline, 750, min_coverage=0.9)

    assert len(strict) < len(generous)
    assert strict["coverage"].min() >= 0.9


@needs_boundaries
def test_every_cell_centre_lands_inside_the_city_or_close_to_it(geography):
    centres = cell_centroids_wgs84(geography.cells)

    assert centres["lon"].between(-0.55, 0.35).all()
    assert centres["lat"].between(51.25, 51.72).all()
    assert len(centres) == len(geography.cells)


# ---------------------------------------------------------------------------
# Districts and cells
# ---------------------------------------------------------------------------


@needs_boundaries
def test_every_district_gets_at_least_one_cell(geography):
    """Fifty five districts are smaller than one 750m cell, and about thirty
    are small enough that no cell centre falls inside them at all. They are
    the central ones people recognise, so omitting them would leave holes in
    the middle of the map at exactly the postcodes a visitor looks for."""
    index = district_cell_index(geography.districts, geography.cells)

    assert set(index) == set(geography.district_ids)
    assert all(len(cells) >= 1 for cells in index.values())


@needs_boundaries
def test_a_tiny_central_district_borrows_the_cell_it_sits_in(geography):
    index = district_cell_index(geography.districts, geography.cells)

    # EC3V is a few streets inside the City. It cannot contain a cell
    # centre, so it takes the journey times of the cell covering it, which
    # is the honest measurement for somebody standing there.
    borrowed = index["EC3V"]
    assert len(borrowed) == 1

    cell = geography.cells.iloc[int(borrowed[0])]
    district = geography.districts.set_index("district").loc["EC3V", "geometry"]
    assert cell.geometry.intersects(
        gpd.GeoSeries([district], crs=geography.districts.crs)
        .to_crs(geography.cells.crs)
        .iloc[0]
    )


@needs_boundaries
def test_cells_outside_every_district_are_kept_as_destinations(geography):
    """People work in places nobody lives, and central London is full of
    them. Those cells must still be routable even though they are not
    offered as somewhere to live."""
    unassigned = geography.cells["district"].isna().sum()

    assert unassigned > 0
    assert unassigned < len(geography.cells) * 0.1


def test_a_district_in_no_grid_cell_is_an_error():
    """That would mean the grid does not cover the city, which is a bug in
    the grid rather than a quirk of the postal geography."""
    districts = gpd.GeoDataFrame(
        {"district": ["ZZ1"]},
        geometry=[box(20.0, 60.0, 20.1, 60.1)],  # nowhere near the grid
        crs="EPSG:4326",
    )
    grid = build_grid(gpd.GeoSeries([box(-0.2, 51.45, -0.1, 51.5)], crs="EPSG:4326"), 750)
    cells = assign_cells_to_districts(grid, districts)

    with pytest.raises(ValueError, match="does not cover the city"):
        district_cell_index(districts, cells)


def test_a_cell_on_a_shared_edge_lands_in_exactly_one_district():
    """Deterministically, rather than depending on the spatial index's
    internal ordering, so two builds of the same data agree."""
    districts = gpd.GeoDataFrame(
        {"district": ["AA1", "AA2"]},
        geometry=[box(-0.2, 51.45, -0.15, 51.50), box(-0.15, 51.45, -0.10, 51.50)],
        crs="EPSG:4326",
    )
    grid = build_grid(gpd.GeoSeries([box(-0.2, 51.45, -0.1, 51.5)], crs="EPSG:4326"), 750)

    first = assign_cells_to_districts(grid, districts)
    second = assign_cells_to_districts(grid, districts)

    assert first["cell_id"].is_unique
    assert first["district"].equals(second["district"])


def test_uniform_weights_give_every_cell_the_same_say():
    grid = build_grid(gpd.GeoSeries([box(-0.2, 51.45, -0.1, 51.5)], crs="EPSG:4326"), 750)

    weights = uniform_weights(grid)

    assert len(weights) == len(grid)
    assert weights.nunique() == 1
    assert weights.iloc[0] == 1.0
