"""Tests for the routing module.

The routing engine itself is not exercised here. It is a Java program over
a 70MB street network extract, and a test suite that needs those is a test
suite nobody runs. What is tested is everything around it: the aggregation
from cells to districts, the weighting, the handling of journeys that do
not exist, and the parsing of whatever the engine hands back.

That split is deliberate. The engine is somebody else's well tested code.
The aggregation is mine, it is where the interesting decisions are, and it
is where a mistake would be invisible in the output.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.config import UNREACHABLE
from pipeline.routing import (
    TravelTimes,
    _fill_from_long_form,
    combine_two_workplaces,
    district_times,
    weighted_median,
)

# ---------------------------------------------------------------------------
# The weighted median
# ---------------------------------------------------------------------------


def test_equal_weights_give_the_ordinary_median():
    values = np.array([[10], [20], [30]], dtype=np.uint16)
    weights = np.ones(3)

    assert weighted_median(values, weights)[0] == 20


def test_the_lower_median_is_taken_on_an_even_count():
    """Journey times are whole minutes. Interpolating between 30 and 40 to
    report 35 describes a journey nobody takes, so the lower of the two
    middle values is used."""
    values = np.array([[10], [20], [30], [40]], dtype=np.uint16)

    assert weighted_median(values, np.ones(4))[0] == 20


def test_weight_moves_the_median():
    """The whole reason weighting exists. Three cells of a district at ten
    minutes and one at sixty: if the one at sixty holds most of the housing,
    the district is a sixty minute district."""
    values = np.array([[10], [10], [10], [60]], dtype=np.uint16)

    assert weighted_median(values, np.array([1.0, 1.0, 1.0, 1.0]))[0] == 10
    assert weighted_median(values, np.array([1.0, 1.0, 1.0, 10.0]))[0] == 60


def test_a_cell_with_almost_no_weight_is_almost_ignored():
    """A grid cell covering a reservoir should not drag a district's journey
    time toward a journey nobody makes."""
    values = np.array([[25], [27], [26], [95]], dtype=np.uint16)
    weights = np.array([40.0, 55.0, 38.0, 0.01])

    assert weighted_median(values, weights)[0] in (26, 27)


def test_every_column_is_medianed_independently():
    values = np.array(
        [
            [10, 90, 5],
            [20, 80, 5],
            [30, 70, 5],
        ],
        dtype=np.uint16,
    )

    assert list(weighted_median(values, np.ones(3))) == [20, 80, 5]


def test_a_single_sample_is_its_own_median():
    """Fifty five districts are smaller than one grid cell and have exactly
    one sample. They must still produce a number."""
    values = np.array([[42]], dtype=np.uint16)

    assert weighted_median(values, np.array([1.0]))[0] == 42


def test_the_median_is_a_value_that_actually_occurs():
    rng = np.random.default_rng(3)
    values = rng.integers(5, 90, size=(9, 50)).astype(np.uint16)
    weights = rng.random(9) + 0.1

    medians = weighted_median(values, weights)

    for column in range(values.shape[1]):
        assert medians[column] in set(values[:, column].tolist())


def test_the_median_matches_a_direct_calculation():
    """An independent check: sort, accumulate, pick. Written out longhand so
    it cannot share a mistake with the vectorised version."""
    rng = np.random.default_rng(5)
    values = rng.integers(0, 120, size=(7, 30)).astype(np.uint16)
    weights = rng.random(7) + 0.05

    medians = weighted_median(values, weights)

    for column in range(values.shape[1]):
        pairs = sorted(zip(values[:, column], weights, strict=True))
        running, target = 0.0, weights.sum() / 2
        expected = None
        for value, weight in pairs:
            running += weight
            if running >= target:
                expected = value
                break
        assert medians[column] == expected


@pytest.mark.parametrize(
    "values, weights, message",
    [
        (np.array([1, 2, 3], dtype=np.uint16), np.ones(3), "two dimensional"),
        (np.array([[1], [2]], dtype=np.uint16), np.ones(3), "one entry per sample"),
        (np.array([[1], [2]], dtype=np.uint16), np.array([-1.0, 2.0]), "negative"),
        (np.array([[1], [2]], dtype=np.uint16), np.zeros(2), "sum to zero"),
    ],
)
def test_the_median_refuses_bad_input(values, weights, message):
    with pytest.raises(ValueError, match=message):
        weighted_median(values, weights)


# ---------------------------------------------------------------------------
# Journeys that do not exist
# ---------------------------------------------------------------------------


def test_a_district_mostly_unable_to_reach_a_place_reads_as_unreachable():
    """The principle the whole pipeline turns on: a journey that does not
    exist is not a fast journey. Excluding unreachable cells from the median
    would make a district whose better third has a train look uniformly
    well connected."""
    values = np.array([[30], [UNREACHABLE], [UNREACHABLE]], dtype=np.uint16)

    assert weighted_median(values, np.ones(3))[0] == UNREACHABLE


def test_a_district_mostly_able_to_reach_a_place_keeps_a_real_time():
    values = np.array([[30], [34], [UNREACHABLE]], dtype=np.uint16)

    assert weighted_median(values, np.ones(3))[0] == 34


def test_the_sentinel_is_the_largest_value_in_the_range():
    """The sentinel has to sort above every real journey time for the median
    to behave. If it were, say, zero, an unreachable cell would pull a
    district's time down rather than up."""
    assert np.iinfo(np.uint16).max == UNREACHABLE
    assert np.uint16(UNREACHABLE) > np.uint16(120)


# ---------------------------------------------------------------------------
# The matrix object
# ---------------------------------------------------------------------------


def test_a_matrix_must_be_square_and_match_its_cell_list():
    with pytest.raises(ValueError, match="but there are"):
        TravelTimes(cell_ids=["a", "b"], minutes=np.zeros((3, 3), dtype=np.uint16))


def test_a_matrix_must_be_sixteen_bit_integers():
    """Floating point would silently double the published payload and add
    precision the timetables do not have."""
    with pytest.raises(ValueError, match="uint16"):
        TravelTimes(cell_ids=["a"], minutes=np.zeros((1, 1), dtype=np.float64))


def test_a_matrix_survives_a_save_and_load(tmp_path):
    rng = np.random.default_rng(1)
    original = TravelTimes(
        cell_ids=[f"{i:06d}" for i in range(40)],
        minutes=rng.integers(0, 120, size=(40, 40)).astype(np.uint16),
    )

    original.save(tmp_path / "matrix.npz")
    restored = TravelTimes.load(tmp_path / "matrix.npz")

    assert restored.cell_ids == original.cell_ids
    assert np.array_equal(restored.minutes, original.minutes)


def test_reachable_share_counts_the_pairs_with_a_journey():
    minutes = np.full((4, 4), UNREACHABLE, dtype=np.uint16)
    minutes[:2, :2] = 20

    assert TravelTimes(cell_ids=list("abcd"), minutes=minutes).reachable_share == 0.25


# ---------------------------------------------------------------------------
# Aggregating to districts
# ---------------------------------------------------------------------------


def _small_matrix() -> TravelTimes:
    """Four cells, hand written so the expected answers can be read off."""
    minutes = np.array(
        [
            [0, 10, 20, 30],
            [10, 0, 15, 25],
            [20, 15, 0, 12],
            [30, 25, 12, 0],
        ],
        dtype=np.uint16,
    )
    return TravelTimes(cell_ids=["c0", "c1", "c2", "c3"], minutes=minutes)


def test_a_district_of_two_cells_takes_the_median_of_both():
    times = _small_matrix()
    # District A is cells 0 and 1, district B is cells 2 and 3.
    result = district_times(
        times,
        cells_by_district={"A": np.array([0, 1]), "B": np.array([2, 3])},
        district_order=["A", "B"],
        weights=np.ones(4),
    )

    assert result.shape == (2, 4)
    # From A to cell 3: the two cells are 30 and 25, lower median is 25.
    assert result[0, 3] == 25
    # From B to cell 0: 20 and 30, lower median is 20.
    assert result[1, 0] == 20


def test_district_order_sets_the_row_order():
    """The published arrays are indexed by position, so this ordering is
    part of the data format rather than an implementation detail."""
    times = _small_matrix()
    index = {"A": np.array([0]), "B": np.array([3])}

    forwards = district_times(times, index, ["A", "B"], np.ones(4))
    backwards = district_times(times, index, ["B", "A"], np.ones(4))

    assert np.array_equal(forwards[0], backwards[1])
    assert np.array_equal(forwards[1], backwards[0])


def test_a_district_with_no_cells_is_an_error_rather_than_a_blank_row():
    """build_geography guarantees every district a cell. If one arrives
    without, the geography and the matrix came from different runs, and a
    blank row would put a hole in the map with no explanation."""
    times = _small_matrix()

    with pytest.raises(KeyError, match="no grid cells"):
        district_times(times, {"A": np.array([0])}, ["A", "B"], np.ones(4))


def test_the_weights_must_cover_every_cell():
    times = _small_matrix()

    with pytest.raises(ValueError, match="one weight per cell"):
        district_times(times, {"A": np.array([0, 1])}, ["A"], np.ones(3))


def test_the_result_is_still_sixteen_bit():
    times = _small_matrix()

    result = district_times(times, {"A": np.array([0, 1])}, ["A"], np.ones(4))

    assert result.dtype == np.uint16


# ---------------------------------------------------------------------------
# Two workplaces
# ---------------------------------------------------------------------------


def test_two_workplaces_take_the_worse_journey():
    """A district works for a couple only if it works for both of them."""
    first = np.array([20, 40, 60], dtype=np.uint16)
    second = np.array([50, 30, 10], dtype=np.uint16)

    assert list(combine_two_workplaces(first, second)) == [50, 40, 60]


def test_unreachable_for_one_person_is_unreachable_for_the_household():
    first = np.array([15], dtype=np.uint16)
    second = np.array([UNREACHABLE], dtype=np.uint16)

    assert combine_two_workplaces(first, second)[0] == UNREACHABLE


def test_combining_is_order_independent():
    rng = np.random.default_rng(2)
    a = rng.integers(0, 120, size=50).astype(np.uint16)
    b = rng.integers(0, 120, size=50).astype(np.uint16)

    assert np.array_equal(combine_two_workplaces(a, b), combine_two_workplaces(b, a))


def test_mismatched_shapes_are_rejected():
    with pytest.raises(ValueError, match="Shapes differ"):
        combine_two_workplaces(np.zeros(3, dtype=np.uint16), np.zeros(4, dtype=np.uint16))


# ---------------------------------------------------------------------------
# Reading the engine's output
# ---------------------------------------------------------------------------


def test_pairs_the_engine_found_no_route_for_stay_unreachable():
    """R5 omits or nulls pairs with no journey. Those must keep the sentinel
    rather than becoming zero, which would read as 'you already live
    there'."""
    minutes = np.full((2, 2), UNREACHABLE, dtype=np.uint16)
    result = pd.DataFrame(
        {
            "from_id": ["a", "a", "b"],
            "to_id": ["a", "b", "a"],
            "travel_time": [0.0, 23.0, np.nan],
        }
    )

    _fill_from_long_form(result, minutes, {"a": 0, "b": 1})

    assert minutes[0, 0] == 0
    assert minutes[0, 1] == 23
    assert minutes[1, 0] == UNREACHABLE
    assert minutes[1, 1] == UNREACHABLE


@pytest.mark.parametrize("column", ["travel_time", "travel_time_p50", "travel_time_50"])
def test_the_travel_time_column_is_found_under_any_of_its_names(column):
    """r5py has used more than one name for this across versions."""
    minutes = np.full((1, 1), UNREACHABLE, dtype=np.uint16)
    result = pd.DataFrame({"from_id": ["a"], "to_id": ["a"], column: [17.0]})

    _fill_from_long_form(result, minutes, {"a": 0})

    assert minutes[0, 0] == 17


def test_an_unrecognised_output_format_fails_loudly():
    minutes = np.full((1, 1), UNREACHABLE, dtype=np.uint16)
    result = pd.DataFrame({"from_id": ["a"], "to_id": ["a"], "duration_seconds": [900]})

    with pytest.raises(RuntimeError, match="none of which looks like a travel time"):
        _fill_from_long_form(result, minutes, {"a": 0})


def test_times_are_rounded_and_capped():
    minutes = np.full((1, 3), UNREACHABLE, dtype=np.uint16)
    result = pd.DataFrame(
        {
            "from_id": ["a", "a", "a"],
            "to_id": ["x", "y", "z"],
            "travel_time": [22.4, 22.6, 500.0],
        }
    )

    _fill_from_long_form(result, minutes, {"a": 0, "x": 0, "y": 1, "z": 2})

    assert minutes[0, 0] == 22
    assert minutes[0, 1] == 23
    assert minutes[0, 2] == 120  # the ceiling, not an overflow
