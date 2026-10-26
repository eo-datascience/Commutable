"""Tests for the rent module.

The fit is tested by generating quantiles from a known lognormal and
asserting the fit recovers the parameters it was never given. The parser is
tested against three different workbook layouts, because the real release
has used more than one and the whole point of the tolerant parser is that
it survives the next change.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from pipeline.rent import (
    Z_QUARTILE,
    RentDistribution,
    _bedrooms_from_text,
    _match_columns,
    _to_number,
    describe_workbook,
    fit_all,
    fit_lognormal,
    load_rents,
)
from tests import fixtures

# ---------------------------------------------------------------------------
# The fit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "median, sigma",
    [(1200, 0.15), (1650, 0.22), (2500, 0.30), (900, 0.40), (4000, 0.12)],
)
def test_the_fit_recovers_the_distribution_it_was_generated_from(median, sigma):
    """Given the exact quartiles of a lognormal, the fit must return that
    lognormal. If this fails, nothing downstream means anything."""
    mu = math.log(median)
    lq, med, uq = fixtures.lognormal_quantiles(mu, sigma)

    fitted = fit_lognormal("SE1", "1", 500, median=med, lower_quartile=lq, upper_quartile=uq)

    assert fitted.mu == pytest.approx(mu, rel=1e-12)
    assert fitted.sigma == pytest.approx(sigma, rel=1e-12)
    assert fitted.max_fit_error == pytest.approx(0.0, abs=1e-12)


def test_a_perfect_fit_reproduces_all_three_published_quantiles():
    mu, sigma = math.log(1800), 0.25
    lq, med, uq = fixtures.lognormal_quantiles(mu, sigma)

    fitted = fit_lognormal("E1", "2", 400, median=med, lower_quartile=lq, upper_quartile=uq)

    assert fitted.quantile(0.25) == pytest.approx(lq, rel=1e-9)
    assert fitted.quantile(0.50) == pytest.approx(med, rel=1e-9)
    assert fitted.quantile(0.75) == pytest.approx(uq, rel=1e-9)


def test_half_the_market_sits_under_the_median():
    """The sanity check a reader would do first."""
    mu, sigma = math.log(1750), 0.23
    lq, med, uq = fixtures.lognormal_quantiles(mu, sigma)
    fitted = fit_lognormal("N1", "1", 300, median=med, lower_quartile=lq, upper_quartile=uq)

    assert fitted.share_under(med) == pytest.approx(0.50, abs=1e-6)
    assert fitted.share_under(lq) == pytest.approx(0.25, abs=1e-6)
    assert fitted.share_under(uq) == pytest.approx(0.75, abs=1e-6)


def test_the_fitted_share_matches_a_simulated_market():
    """An independent check of share_under.

    Draw a hundred thousand rents from the same lognormal, count how many
    fall under a budget, and compare. This catches an error in the
    cumulative distribution that the analytical tests above would not,
    because they and share_under could be wrong in the same direction.
    """
    mu, sigma = math.log(1600), 0.26
    lq, med, uq = fixtures.lognormal_quantiles(mu, sigma)
    fitted = fit_lognormal("SE4", "1", 500, median=med, lower_quartile=lq, upper_quartile=uq)

    drawn = np.random.default_rng(11).lognormal(mu, sigma, size=100_000)
    for budget in (1200, 1400, 1600, 1800, 2200):
        simulated = float((drawn <= budget).mean())
        assert fitted.share_under(budget) == pytest.approx(simulated, abs=0.01)


def test_share_under_never_decreases_as_the_budget_rises():
    mu, sigma = math.log(1500), 0.3
    lq, med, uq = fixtures.lognormal_quantiles(mu, sigma)
    fitted = fit_lognormal("SE5", "1", 200, median=med, lower_quartile=lq, upper_quartile=uq)

    shares = [fitted.share_under(b) for b in range(400, 6000, 50)]
    assert shares == sorted(shares)
    assert 0.0 <= shares[0] < shares[-1] <= 1.0


def test_a_budget_of_nothing_reaches_nothing():
    mu, sigma = math.log(1500), 0.3
    lq, med, uq = fixtures.lognormal_quantiles(mu, sigma)
    fitted = fit_lognormal("SE5", "1", 200, median=med, lower_quartile=lq, upper_quartile=uq)

    assert fitted.share_under(0) == 0.0
    assert fitted.share_under(-100) == 0.0


def test_budget_for_share_inverts_share_under():
    mu, sigma = math.log(2000), 0.28
    lq, med, uq = fixtures.lognormal_quantiles(mu, sigma)
    fitted = fit_lognormal("W2", "2", 600, median=med, lower_quartile=lq, upper_quartile=uq)

    for share in (0.05, 0.25, 0.5, 0.75, 0.95):
        budget = fitted.budget_for_share(share)
        assert fitted.share_under(budget) == pytest.approx(share, abs=1e-6)


def test_a_wider_spread_puts_more_of_the_market_below_a_low_budget():
    """Two districts with the same median are not the same market. The one
    with the wider spread has more cheap stock, and the site should say so."""
    med = 1800.0
    narrow = fit_lognormal("A1", "1", 300, median=med,
                           **dict(zip(("lower_quartile", "upper_quartile"),
                                      (fixtures.lognormal_quantiles(math.log(med), 0.12)[0],
                                       fixtures.lognormal_quantiles(math.log(med), 0.12)[2]),
                                      strict=True)))
    wide = fit_lognormal("A2", "1", 300, median=med,
                         **dict(zip(("lower_quartile", "upper_quartile"),
                                    (fixtures.lognormal_quantiles(math.log(med), 0.35)[0],
                                     fixtures.lognormal_quantiles(math.log(med), 0.35)[2]),
                                    strict=True)))

    assert wide.share_under(1400) > narrow.share_under(1400)
    assert wide.share_under(med) == pytest.approx(narrow.share_under(med), abs=1e-9)


# ---------------------------------------------------------------------------
# The fit refuses bad input rather than producing confident nonsense
# ---------------------------------------------------------------------------


def test_quartiles_in_the_wrong_order_are_rejected():
    """The most likely real failure is that the columns were matched to the
    wrong headings. That must stop, not produce a curve."""
    with pytest.raises(ValueError, match="out of order"):
        fit_lognormal("SE1", "1", 500, median=1500, lower_quartile=1800, upper_quartile=1200)


def test_identical_quartiles_are_rejected():
    with pytest.raises(ValueError, match="no distribution to fit"):
        fit_lognormal("SE1", "1", 6, median=1500, lower_quartile=1500, upper_quartile=1500)


def test_quartiles_within_a_few_pounds_are_rejected_too():
    """The guard cannot be a test for zero. Three identical quartiles give a
    spread of about 5e-16 rather than 0, which is positive, and a spread
    that small turns the published share of the market into a step
    function: a pound under the median reaches none of it, a pound over
    reaches all of it."""
    with pytest.raises(ValueError, match="too close together"):
        fit_lognormal("SE1", "1", 40, median=1500, lower_quartile=1499, upper_quartile=1501)


def test_the_spread_floor_is_not_so_high_that_it_rejects_a_real_market():
    """A genuinely tight district must still be publishable. An
    interquartile range of 5% of the median is tight for London but real."""
    fitted = fit_lognormal("SE1", "1", 300, median=1500, lower_quartile=1463, upper_quartile=1538)

    assert fitted.sigma > 0.01
    assert 0.0 < fitted.share_under(1500) < 1.0


@pytest.mark.parametrize(
    "median, lq, uq",
    [(0, 900, 1200), (1500, 0, 1800), (1500, 1200, 0), (-1500, 1200, 1800)],
)
def test_non_positive_rents_are_rejected(median, lq, uq):
    with pytest.raises(ValueError, match="must be positive"):
        fit_lognormal("SE1", "1", 500, median=median, lower_quartile=lq, upper_quartile=uq)


def test_a_poor_fit_is_recorded_rather_than_rejected():
    """Real rent distributions are not exactly lognormal. A district whose
    quantiles do not sit on the curve is still published, flagged."""
    fitted = fit_lognormal("SE1", "1", 500, median=1500, lower_quartile=1400, upper_quartile=2600)

    assert fitted.max_fit_error > 0.05
    assert fitted.well_fitted is False
    # Still usable.
    assert 0.0 < fitted.share_under(1500) < 1.0


def test_an_invalid_percentile_is_rejected():
    mu, sigma = math.log(1500), 0.2
    lq, med, uq = fixtures.lognormal_quantiles(mu, sigma)
    fitted = fit_lognormal("SE1", "1", 500, median=med, lower_quartile=lq, upper_quartile=uq)

    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="between 0 and 1"):
            fitted.quantile(bad)


# ---------------------------------------------------------------------------
# Reading the workbook
# ---------------------------------------------------------------------------


def test_reads_the_layout_with_bedrooms_as_a_column(tmp_path):
    path = fixtures.write_workbook_bedrooms_as_column(tmp_path / "rents.xlsx")

    rents = load_rents(path)

    assert set(rents["district"]) == {"SE10", "E14", "N4", "CR0", "EC2R"}
    assert set(rents["bedrooms"]) <= {"1", "2"}
    row = rents[(rents["district"] == "SE10") & (rents["bedrooms"] == "1")].iloc[0]
    assert row["count"] == 410
    assert row["median"] == pytest.approx(1650, abs=1)


def test_reads_the_layout_with_bedrooms_as_sheet_names(tmp_path):
    """No bedroom column at all. The category comes from the sheet name."""
    path = fixtures.write_workbook_bedrooms_as_sheets(tmp_path / "rents.xlsx")

    rents = load_rents(path)

    assert set(rents["bedrooms"]) == {"1", "2"}
    assert len(rents) == 9
    assert rents[(rents.district == "E14") & (rents.bedrooms == "2")]["count"].iloc[0] == 740


def test_borough_and_region_sheets_are_skipped(tmp_path):
    """The real workbook holds all three geographies. Only the postcode
    district table should reach the pipeline, and it is identified by the
    shape of its geography values rather than by a sheet name."""
    path = fixtures.write_workbook_with_distractions(tmp_path / "rents.xlsx")

    rents = load_rents(path)

    assert "London" not in set(rents["district"])
    assert "Greenwich" not in set(rents["district"])
    assert "SE10" in set(rents["district"])


def test_suppressed_figures_become_missing_rather_than_zero(tmp_path):
    """A withheld median is not a median of nothing. Treating '..' as 0
    would paint W1B as the cheapest place in London."""
    path = fixtures.write_workbook_with_distractions(tmp_path / "rents.xlsx")

    rents = load_rents(path)
    w1b = rents[rents["district"] == "W1B"].iloc[0]

    assert w1b["count"] == 3
    assert pd.isna(w1b["median"])
    assert pd.isna(w1b["lower_quartile"])


def test_money_formatting_is_parsed(tmp_path):
    path = fixtures.write_workbook_with_distractions(tmp_path / "rents.xlsx")

    rents = load_rents(path)
    row = rents[(rents.district == "SE10") & (rents.bedrooms == "1")].iloc[0]

    assert row["mean"] > 1000


def test_restricting_to_a_district_set_drops_the_rest(tmp_path):
    path = fixtures.write_workbook_bedrooms_as_column(tmp_path / "rents.xlsx")

    rents = load_rents(path, districts={"SE10", "E14"})

    assert set(rents["district"]) == {"SE10", "E14"}


def test_a_workbook_with_no_usable_sheet_says_what_it_found(tmp_path):
    """The failure a user will actually hit if the release changes shape.
    The message has to name the sheets and the columns, not just fail."""
    import openpyxl

    path = tmp_path / "wrong.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "Cover"
    book.active.append(["Some unrelated spreadsheet"])
    book.active.append(["Colour", "Shape"])
    book.active.append(["red", "square"])
    book.save(path)

    with pytest.raises(ValueError) as error:
        load_rents(path)

    message = str(error.value)
    assert "Cover" in message
    assert "describe_workbook" in message


def test_a_missing_workbook_points_at_the_documentation(tmp_path):
    with pytest.raises(FileNotFoundError, match="data-sources.md"):
        load_rents(tmp_path / "absent.xlsx")


def test_describe_workbook_reports_the_sheets_and_the_header_row(tmp_path):
    path = fixtures.write_workbook_with_distractions(tmp_path / "rents.xlsx")

    description = describe_workbook(path)

    assert "Postcode district" in description
    assert "Borough" in description
    assert "matches" in description


# ---------------------------------------------------------------------------
# Column and category matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "heading, canonical",
    [
        ("Lower quartile", "lower_quartile"),
        ("lower_quartile", "lower_quartile"),
        ("Lower Quartile (£)", "lower_quartile"),
        ("LQ", "lower_quartile"),
        ("Upper quartile", "upper_quartile"),
        ("Median rent", "median"),
        ("Count of rents", "count"),
        ("Postcode district", "district"),
        ("Bedroom category", "bedrooms"),
    ],
)
def test_column_headings_are_matched_through_punctuation_and_case(heading, canonical):
    matched = _match_columns([heading, "Something else entirely"])
    assert canonical in matched
    assert matched[canonical] == heading


def test_each_heading_is_claimed_by_only_one_canonical_column():
    """Without this, 'Median' can satisfy both 'median' and 'mean' through
    the loose prefix match and one real column goes missing."""
    headings = ["Postcode district", "Bedroom category", "Count of rents", "Mean",
                "Median", "Lower quartile", "Upper quartile"]
    matched = _match_columns(headings)

    assert sorted(matched) == ["bedrooms", "count", "district", "lower_quartile",
                               "mean", "median", "upper_quartile"]
    assert len(set(matched.values())) == len(matched)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("One bedroom", "1"),
        ("1 bedroom", "1"),
        ("Two bedrooms", "2"),
        ("two bed", "2"),
        ("Three bedrooms", "3"),
        ("Four or more bedrooms", "4+"),
        ("Studio", "studio"),
        ("Room only", "room"),
        ("All categories", "all"),
        ("Greenwich", None),
        ("", None),
    ],
)
def test_bedroom_categories_are_recognised(text, expected):
    assert _bedrooms_from_text(text) == expected


@pytest.mark.parametrize("key", ["room", "studio", "1", "2", "3", "4+", "all"])
def test_mapping_a_category_key_a_second_time_leaves_it_alone(key):
    """The layout where each sheet is a bedroom category translates the
    sheet name once. Translating the result again used to return nothing,
    because '4+' squashes to '4' and 'Two bedrooms' to 'twobedrooms', and
    neither matches a key. That silently emptied every sheet."""
    assert _bedrooms_from_text(key) == key
    assert _bedrooms_from_text(_bedrooms_from_text("Two bedrooms")) == "2"


@pytest.mark.parametrize(
    "cell, expected",
    [
        (1500, 1500.0),
        (1500.5, 1500.5),
        ("1500", 1500.0),
        ("£1,500", 1500.0),
        ("1,500 ", 1500.0),
        ("..", None),
        (":", None),
        ("-", None),
        ("", None),
        ("not a number", None),
        (None, None),
    ],
)
def test_suppression_markers_and_money_are_parsed(cell, expected):
    result = _to_number(cell)
    if expected is None:
        assert math.isnan(result)
    else:
        assert result == expected


# ---------------------------------------------------------------------------
# Fitting the whole table
# ---------------------------------------------------------------------------


def test_fit_all_rejects_thin_samples_and_says_why(tmp_path):
    path = fixtures.write_workbook_bedrooms_as_column(tmp_path / "rents.xlsx")
    rents = load_rents(path)

    report = fit_all(rents, min_sample=30)

    assert ("EC2R", "1") not in report.distributions
    reasons = {(d, b): why for d, b, why in report.rejected}
    assert "below the minimum" in reasons[("EC2R", "1")]


def test_fit_all_rejects_rows_with_a_suppressed_quartile(tmp_path):
    path = fixtures.write_workbook_with_distractions(tmp_path / "rents.xlsx")
    rents = load_rents(path)

    report = fit_all(rents, min_sample=30)

    reasons = {(d, b): why for d, b, why in report.rejected}
    # SW1H has a published count of 46 and a withheld upper quartile.
    assert ("SW1H", "2") in reasons
    assert "suppressed" in reasons[("SW1H", "2")]


def test_fit_all_keeps_the_published_median_verbatim(tmp_path):
    """A visitor who looks the district up in the ONS release must see the
    same median. Nothing derived is allowed to replace it."""
    path = fixtures.write_workbook_bedrooms_as_column(tmp_path / "rents.xlsx")
    rents = load_rents(path)

    report = fit_all(rents)

    for row in rents.itertuples(index=False):
        fitted = report.get(row.district, row.bedrooms)
        if fitted is None:
            continue
        assert fitted.median == row.median


def test_fit_all_covers_the_districts_with_enough_data(tmp_path):
    path = fixtures.write_workbook_bedrooms_as_column(tmp_path / "rents.xlsx")
    rents = load_rents(path)

    report = fit_all(rents)

    assert report.districts == {"SE10", "E14", "N4", "CR0"}
    assert report.bedroom_categories == {"1", "2"}
    assert report.get("SE10", "1") is not None
    assert report.get("SE10", "9") is None


def test_a_duplicated_district_and_category_keeps_the_larger_sample(tmp_path):
    """Two sheets covering the same ground would otherwise be counted twice."""
    import openpyxl

    path = tmp_path / "dupes.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Postcode district"
    sheet.append(["Postcode district", "Bedroom category", "Count of rents", "Mean",
                  "Median", "Lower quartile", "Upper quartile"])
    sheet.append(["SE10", "One bedroom", 100, 1700, 1650, 1480, 1850])
    sheet.append(["SE10", "One bedroom", 900, 1710, 1660, 1490, 1860])
    book.save(path)

    rents = load_rents(path)

    assert len(rents) == 1
    assert rents.iloc[0]["count"] == 900


# ---------------------------------------------------------------------------
# The distribution object itself
# ---------------------------------------------------------------------------


def test_a_distribution_is_immutable():
    """These are published values. Nothing downstream should be able to
    adjust a median in passing."""
    mu, sigma = math.log(1500), 0.2
    lq, med, uq = fixtures.lognormal_quantiles(mu, sigma)
    fitted = fit_lognormal("SE1", "1", 500, median=med, lower_quartile=lq, upper_quartile=uq)

    assert isinstance(fitted, RentDistribution)
    # A frozen dataclass raises FrozenInstanceError, which is a subclass of
    # AttributeError. Named rather than caught blind, so the test fails if
    # the dataclass stops being frozen and starts raising something else.
    with pytest.raises(dataclasses.FrozenInstanceError):
        fitted.median = 1  # type: ignore[misc]


def test_the_quartile_constant_is_the_standard_normal_quantile():
    """Z_QUARTILE is hard coded, so it is worth one test that it is right.
    The standard normal lies within one lower quartile of its median with
    probability 0.25 by definition."""
    from pipeline.rent import _inverse_normal_cdf

    assert _inverse_normal_cdf(0.75) == pytest.approx(Z_QUARTILE, abs=1e-7)
    assert _inverse_normal_cdf(0.25) == pytest.approx(-Z_QUARTILE, abs=1e-7)
    assert _inverse_normal_cdf(0.5) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("p", [0.001, 0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99, 0.999])
def test_the_normal_quantile_approximation_is_accurate(p):
    """Acklam's approximation is claimed accurate to about 1e-9. Checked
    against the error function, which comes from the standard library and is
    an independent implementation."""
    from pipeline.rent import _inverse_normal_cdf

    z = _inverse_normal_cdf(p)
    recovered = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    assert recovered == pytest.approx(p, abs=1e-8)


# ---------------------------------------------------------------------------
# Reading the real release
# ---------------------------------------------------------------------------


def test_a_numbered_sheet_is_not_a_bedroom_category():
    """The real ONS release names its three data sheets '1', '2' and '3',
    meaning worksheet one, two and three. Read as cell values those are the
    keys for one, two and three bedrooms, so the sheet holding every
    postcode district in London announced itself as the three bedroom
    sheet. It did no damage only because that sheet carries its own Bedroom
    Category column, and it was one unrecognised label away from silently
    relabelling rows."""
    from pipeline.rent import _bedrooms_from_sheet_name

    for numbered in ("1", "2", "3", "4", "4+"):
        assert _bedrooms_from_sheet_name(numbered) is None


def test_a_sheet_actually_named_for_a_category_still_works():
    from pipeline.rent import _bedrooms_from_sheet_name

    assert _bedrooms_from_sheet_name("One Bedroom") == "1"
    assert _bedrooms_from_sheet_name("Two Bedrooms") == "2"
    assert _bedrooms_from_sheet_name("Studio") == "studio"
    assert _bedrooms_from_sheet_name("Cover sheet") is None


def test_the_release_marks_not_applicable_with_a_full_stop():
    """Note 6 of the real release: values denoted by '.' are not
    applicable, and '..' are not available. Both must read as missing
    rather than as a rent of nothing."""
    assert math.isnan(_to_number("."))
    assert math.isnan(_to_number(".."))


def test_the_real_release_layout_is_recognised(tmp_path):
    """Built to match the April 2025 to March 2026 edition exactly: three
    data sheets named by number, two rows of preamble above the header, the
    geography only on the third sheet, and the quartiles either side of the
    median rather than after it."""
    import openpyxl

    path = tmp_path / "ons.xlsx"
    book = openpyxl.Workbook()
    book.remove(book.active)

    region = book.create_sheet("1")
    region.append(["Summary of monthly rents recorded between April 2025 and March 2026"])
    region.append(["This worksheet contains one table."])
    region.append(["Bedroom Category", "Count of rents", "Mean", "Lower quartile",
                   "Median", "Upper quartile"])
    region.append(["One Bedroom", 17310, 1714, 1350, 1600, 1910])

    borough = book.create_sheet("2")
    borough.append(["Summary of monthly rents recorded between April 2025 and March 2026"])
    borough.append(["This worksheet contains one table."])
    borough.append(["Borough", "Bedroom Category", "Count of rents", "Mean",
                    "Lower quartile", "Median", "Upper quartile"])
    borough.append(["Barking and Dagenham", "One Bedroom", 240, 1348, 1250, 1350, 1472])

    district = book.create_sheet("3")
    district.append(["Summary of monthly rents recorded between April 2025 and March 2026"])
    district.append(["This worksheet contains one table."])
    district.append(["Postcode District", "Bedroom Category", "Count of rents", "Mean",
                     "Lower quartile", "Median", "Upper quartile"])
    district.append(["BR1", "One Bedroom", 170, 1369, 1300, 1400, 1450])
    district.append(["BR1", "Two Bedrooms", 230, 1657, 1500, 1650, 1800])
    district.append(["BR2", "Room", "..", "..", "..", "..", ".."])
    district.append(["SE10", "One Bedroom", 170, 1800, 1650, 1800, 1900])
    book.save(path)

    rents = load_rents(path)

    # Only the postcode district sheet, found by the shape of its values
    # rather than by its name, which is simply "3".
    assert set(rents["district"]) == {"BR1", "BR2", "SE10"}
    assert "Barking and Dagenham" not in set(rents["district"])

    # BR2 is suppressed throughout. It survives loading as a row of missing
    # values and is refused at fitting with a reason, rather than being
    # dropped silently here or treated as a rent of nothing later.
    br2 = rents[rents.district == "BR2"].iloc[0]
    assert pd.isna(br2["count"])
    assert pd.isna(br2["median"])

    report = fit_all(rents)
    assert report.get("BR2", "room") is None
    assert any(d == "BR2" for d, _, _ in report.rejected)

    # The quartiles sit either side of the median in this layout, so a
    # parser matching by position rather than by heading would read them
    # the wrong way round and every fitted curve would be nonsense.
    row = rents[(rents.district == "BR1") & (rents.bedrooms == "1")].iloc[0]
    assert row["lower_quartile"] == 1300
    assert row["median"] == 1400
    assert row["upper_quartile"] == 1450
    assert row["count"] == 170


def test_a_thin_sample_is_published_but_flagged():
    """Below the comfortable threshold the figures are still real and still
    shown. The site says how thin they are rather than hiding them."""
    mu, sigma = math.log(1500), 0.2
    lq, med, uq = fixtures.lognormal_quantiles(mu, sigma)

    thin = fit_lognormal("SE1", "1", 20, median=med, lower_quartile=lq, upper_quartile=uq)
    thick = fit_lognormal("SE1", "1", 300, median=med, lower_quartile=lq, upper_quartile=uq)

    assert thin.thin_sample is True
    assert thick.thin_sample is False
    assert thin.share_under(1500) == pytest.approx(thick.share_under(1500), abs=1e-9)
