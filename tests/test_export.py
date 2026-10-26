"""Tests for the export module.

What is published is a data format with a consumer in another language, so
the things worth testing are the ones a reader of the TypeScript would
assume without checking: that the district order in meta.json is the order
every binary array is indexed by, that a journey time file is exactly two
bytes per district, that the bytes are little endian.

Those assumptions are the contract between the two halves of the project,
and nothing else enforces them.
"""

from __future__ import annotations

import json
import struct

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from pipeline.config import LONDON, MAX_JOURNEY_MINUTES, UNREACHABLE
from pipeline.export import FORMAT_VERSION, export_all
from pipeline.gazetteer import Place
from pipeline.geography import Geography, build_grid
from pipeline.rent import RentReport, fit_lognormal


@pytest.fixture
def geography() -> Geography:
    """A small square city, so the export can be checked by hand."""
    outline = gpd.GeoSeries([box(-0.16, 51.48, -0.10, 51.52)], crs="EPSG:4326")

    districts = gpd.GeoDataFrame(
        {
            "district": ["AA1", "AA2", "AA3"],
            "share_in_city": [1.0, 1.0, 0.5],
            "area_km2": [4.0, 4.0, 4.0],
        },
        geometry=[
            box(-0.16, 51.48, -0.14, 51.52),
            box(-0.14, 51.48, -0.12, 51.52),
            box(-0.12, 51.48, -0.10, 51.52),
        ],
        crs="EPSG:4326",
    )

    grid = build_grid(outline, 750)
    grid["district"] = "AA1"
    grid["weight"] = 1.0

    return Geography(city=LONDON, boundary=outline, districts=districts, cells=grid)


@pytest.fixture
def rents() -> RentReport:
    report = RentReport()
    for district, median in (("AA1", 1400.0), ("AA2", 1850.0)):
        for bedrooms in ("1", "2"):
            report.distributions[(district, bedrooms)] = fit_lognormal(
                district=district,
                bedrooms=bedrooms,
                sample=250,
                median=median,
                lower_quartile=median * 0.85,
                upper_quartile=median * 1.18,
            )
    return report


def _minutes(geography: Geography, fill: int = 30) -> np.ndarray:
    return np.full((len(geography.district_ids), len(geography.cell_ids)), fill, dtype=np.uint16)


def _export(geography, rents, out_dir, minutes=None, places=None):
    return export_all(
        geography=geography,
        rents=rents,
        district_minutes=_minutes(geography) if minutes is None else minutes,
        places=places if places is not None else [],
        out_dir=out_dir,
    )


# ---------------------------------------------------------------------------
# The contract between the pipeline and the browser
# ---------------------------------------------------------------------------


def test_a_journey_time_file_is_two_bytes_per_district(geography, rents, tmp_path):
    _export(geography, rents, tmp_path)

    for cell in geography.cell_ids:
        payload = (tmp_path / "times" / f"{cell}.bin").read_bytes()
        assert len(payload) == len(geography.district_ids) * 2


def test_the_bytes_are_little_endian_in_the_published_district_order(geography, rents, tmp_path):
    """The browser reads these with a DataView and an explicit little endian
    flag. If the pipeline ever wrote them the other way round every journey
    time would be wrong by a factor of 256 and still look like a number."""
    minutes = _minutes(geography)
    minutes[:, 0] = [11, 22, 33]

    _export(geography, rents, tmp_path, minutes=minutes)

    first_cell = geography.cell_ids[0]
    payload = (tmp_path / "times" / f"{first_cell}.bin").read_bytes()
    values = struct.unpack(f"<{len(geography.district_ids)}H", payload)

    assert list(values) == [11, 22, 33]


def test_the_district_order_in_the_metadata_indexes_the_arrays(geography, rents, tmp_path):
    minutes = _minutes(geography)
    minutes[:, 2] = [5, 50, UNREACHABLE]

    _export(geography, rents, tmp_path, minutes=minutes)

    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    payload = (tmp_path / "times" / f"{geography.cell_ids[2]}.bin").read_bytes()
    values = struct.unpack(f"<{len(meta['districts'])}H", payload)

    by_district = dict(zip(meta["districts"], values, strict=True))
    assert by_district["AA1"] == 5
    assert by_district["AA2"] == 50
    assert by_district["AA3"] == UNREACHABLE


def test_the_unreachable_sentinel_survives_the_round_trip(geography, rents, tmp_path):
    """It has to come back as the same number the browser is told to expect,
    not as a very long journey."""
    minutes = _minutes(geography, fill=UNREACHABLE)

    _export(geography, rents, tmp_path, minutes=minutes)

    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    payload = (tmp_path / "times" / f"{geography.cell_ids[0]}.bin").read_bytes()

    assert set(struct.unpack("<3H", payload)) == {meta["times"]["unreachable"]}
    assert meta["times"]["unreachable"] == UNREACHABLE


def test_a_matrix_of_the_wrong_shape_is_refused(geography, rents, tmp_path):
    """It would mean the geography and the routing came from different runs,
    and the result would be a map that coloured the wrong districts."""
    wrong = np.zeros((2, len(geography.cell_ids)), dtype=np.uint16)

    with pytest.raises(ValueError, match="different runs"):
        _export(geography, rents, tmp_path, minutes=wrong)


def test_a_matrix_of_the_wrong_type_is_refused(geography, rents, tmp_path):
    wrong = np.zeros((len(geography.district_ids), len(geography.cell_ids)), dtype=np.float64)

    with pytest.raises(ValueError, match="uint16"):
        _export(geography, rents, tmp_path, minutes=wrong)


def test_a_rebuild_removes_journey_times_from_the_previous_grid(geography, rents, tmp_path):
    """Otherwise the site would happily serve a file computed from a
    different timetable, against a different district order."""
    stale = tmp_path / "times"
    stale.mkdir(parents=True)
    (stale / "999999.bin").write_bytes(b"\x00\x00")

    _export(geography, rents, tmp_path)

    assert not (stale / "999999.bin").exists()
    assert len(list(stale.glob("*.bin"))) == len(geography.cell_ids)


# ---------------------------------------------------------------------------
# Rents
# ---------------------------------------------------------------------------


def test_the_rent_rows_are_in_the_order_the_file_documents(geography, rents, tmp_path):
    _export(geography, rents, tmp_path)

    published = json.loads((tmp_path / "rents.json").read_text(encoding="utf-8"))
    assert published["fields"] == [
        "median", "lower_quartile", "upper_quartile", "sample", "mu", "sigma", "well_fitted",
    ]

    row = published["categories"]["1"]["AA1"]
    assert row[0] == 1400          # median
    assert row[1] < row[0] < row[2]  # quartiles either side
    assert row[3] == 250           # sample
    assert row[6] in (0, 1)


def test_the_published_median_is_the_one_that_was_given(geography, rents, tmp_path):
    """A visitor who checks the ONS release must see the same figure."""
    _export(geography, rents, tmp_path)

    published = json.loads((tmp_path / "rents.json").read_text(encoding="utf-8"))

    for (district, bedrooms), fitted in rents.distributions.items():
        assert published["categories"][bedrooms][district][0] == round(fitted.median)


def test_a_district_with_no_figures_is_absent_rather_than_zero(geography, rents, tmp_path):
    _export(geography, rents, tmp_path)

    published = json.loads((tmp_path / "rents.json").read_text(encoding="utf-8"))

    assert "AA3" not in published["categories"]["1"]
    assert "AA1" in published["categories"]["1"]


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_the_metadata_declares_the_format_version(geography, rents, tmp_path):
    """The site refuses to read a version it does not know, rather than
    misreading an array against the wrong district order."""
    _export(geography, rents, tmp_path)

    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["format_version"] == FORMAT_VERSION


def test_the_metadata_carries_the_limitations_and_the_attributions(geography, rents, tmp_path):
    """They are published with the data rather than left in a readme,
    because the site shows them and two of the licences require it."""
    _export(geography, rents, tmp_path)

    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))

    assert len(meta["limitations"]) >= 4
    assert len(meta["attributions"]) >= 4
    for attribution in meta["attributions"]:
        assert attribution["licence"]
        assert attribution["url"].startswith("http")


def test_the_metadata_says_how_the_journeys_were_measured(geography, rents, tmp_path):
    _export(geography, rents, tmp_path)

    times = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["times"]

    assert "little endian" in times["encoding"]
    assert times["max_minutes"] == MAX_JOURNEY_MINUTES
    assert "median" in times["statistic"]
    assert times["departure_date"] == LONDON.departure_date


def test_the_metadata_lists_only_the_districts_that_have_rent_figures(geography, rents, tmp_path):
    _export(geography, rents, tmp_path)

    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))

    assert meta["districts"] == ["AA1", "AA2", "AA3"]
    assert meta["districts_with_rent"] == ["AA1", "AA2"]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_every_drawn_district_is_in_the_published_order(geography, rents, tmp_path):
    """The site refuses to start if these disagree, because the alternative
    is a map that colours the wrong districts and looks fine."""
    _export(geography, rents, tmp_path)

    drawn = {
        feature["properties"]["district"]
        for feature in json.loads((tmp_path / "districts.geojson").read_text(encoding="utf-8"))["features"]
    }
    order = set(json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["districts"])

    assert drawn == order


def test_simplification_keeps_almost_all_of_the_area(geography, rents, tmp_path):
    _export(geography, rents, tmp_path)

    drawn = gpd.read_file(tmp_path / "districts.geojson").to_crs("EPSG:27700")
    original = geography.districts.to_crs("EPSG:27700")

    assert drawn.area.sum() == pytest.approx(original.area.sum(), rel=0.01)


def test_the_cell_centres_are_published_as_parallel_arrays(geography, rents, tmp_path):
    """Objects would be about three times the bytes for the same
    information, and the browser wants arrays anyway for the nearest
    neighbour search."""
    _export(geography, rents, tmp_path)

    cells = json.loads((tmp_path / "cells.json").read_text(encoding="utf-8"))

    assert len(cells["ids"]) == len(cells["lon"]) == len(cells["lat"])
    assert cells["ids"] == geography.cell_ids
    assert cells["cell_metres"] == LONDON.grid_cell_metres


# ---------------------------------------------------------------------------
# Gazetteer
# ---------------------------------------------------------------------------


def test_the_gazetteer_is_published_as_rows_with_a_field_list(geography, rents, tmp_path):
    places = [
        Place(name="Somewhere", kind="station", cell_id=geography.cell_ids[0], lon=-0.13, lat=51.5),
        Place(name="AA1", kind="district", cell_id=geography.cell_ids[1], lon=-0.15, lat=51.5),
    ]

    _export(geography, rents, tmp_path, places=places)

    published = json.loads((tmp_path / "gazetteer.json").read_text(encoding="utf-8"))

    assert published["fields"] == ["name", "kind", "cell", "lon", "lat"]
    assert published["places"][0][0] == "Somewhere"
    assert published["places"][0][2] == geography.cell_ids[0]


# ---------------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------------


def test_the_per_answer_payload_stays_small(geography, rents, tmp_path):
    """The whole architecture rests on this number. If a journey time file
    ever grows past a couple of kilobytes, the design has drifted."""
    sizes = _export(geography, rents, tmp_path)

    per_answer = len(geography.district_ids) * 2
    assert per_answer < 2048
    assert sizes["times/"] == per_answer * len(geography.cell_ids)
