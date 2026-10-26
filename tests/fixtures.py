"""Synthetic inputs, so the pipeline is testable without the real files.

Three of the four inputs are large downloads behind a licence click, and a
test suite that needs a 70MB street network extract is a test suite nobody
runs. More importantly, the rent workbook is an ad hoc ONS release whose
layout has moved between editions, so the parser has to be tested against
several plausible layouts rather than against the one that happened to be
current when it was written.

Everything here is generated from a known lognormal, which means the tests
can assert that the fit recovers parameters it was never told.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import openpyxl

from pipeline.rent import Z_QUARTILE


def lognormal_quantiles(mu: float, sigma: float) -> tuple[float, float, float]:
    """The exact lower quartile, median and upper quartile of a lognormal.

    Generating fixtures from these means a test can fit a curve to three
    numbers and check it recovers the mu and sigma that produced them. A
    fixture of invented round numbers could not do that.
    """
    return (
        math.exp(mu - sigma * Z_QUARTILE),
        math.exp(mu),
        math.exp(mu + sigma * Z_QUARTILE),
    )


def sample_rows() -> list[dict]:
    """A handful of districts with known distributions.

    The parameters are chosen to look like real London rents: a median
    around £1,200 to £2,400 and an interquartile spread of roughly 30% to
    60% of the median.
    """
    specification = [
        # district, bedrooms, mu, sigma, sample
        ("SE10", "1", math.log(1650), 0.22, 410),
        ("SE10", "2", math.log(2150), 0.25, 530),
        ("E14", "1", math.log(1900), 0.20, 880),
        ("E14", "2", math.log(2500), 0.24, 740),
        ("N4", "1", math.log(1500), 0.19, 260),
        ("N4", "2", math.log(1850), 0.21, 310),
        ("CR0", "1", math.log(1150), 0.17, 190),
        ("CR0", "2", math.log(1400), 0.18, 420),
        # Deliberately below the sample floor, so a test can assert it is
        # rejected rather than published.
        ("EC2R", "1", math.log(2800), 0.30, 7),
    ]
    rows = []
    for district, bedrooms, mu, sigma, sample in specification:
        lq, median, uq = lognormal_quantiles(mu, sigma)
        rows.append(
            {
                "district": district,
                "bedrooms": bedrooms,
                "count": sample,
                "mean": round(math.exp(mu + sigma**2 / 2), 0),
                "median": round(median, 0),
                "lower_quartile": round(lq, 0),
                "upper_quartile": round(uq, 0),
                "mu": mu,
                "sigma": sigma,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Workbook layouts
# ---------------------------------------------------------------------------

BEDROOM_LABELS = {
    "1": "One bedroom",
    "2": "Two bedrooms",
    "3": "Three bedrooms",
    "all": "All categories",
}


def write_workbook_bedrooms_as_column(path: Path, title_rows: int = 2) -> Path:
    """The layout where one sheet holds every bedroom category.

    A block of title and note rows sits above the table, because every
    accessible ONS workbook has one and a parser that assumes row 1 is the
    header fails on all of them.
    """
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Postcode district"

    for i in range(title_rows):
        sheet.append(["Private rental market in London, April 2025 to March 2026"] if i == 0 else [])
    sheet.append(
        ["Postcode district", "Bedroom category", "Count of rents", "Mean", "Median",
         "Lower quartile", "Upper quartile"]
    )
    for row in sample_rows():
        sheet.append(
            [row["district"], BEDROOM_LABELS[row["bedrooms"]], row["count"], row["mean"],
             row["median"], row["lower_quartile"], row["upper_quartile"]]
        )

    book.save(path)
    return path


def write_workbook_bedrooms_as_sheets(path: Path) -> Path:
    """The layout where each bedroom category is its own sheet.

    Earlier editions of the England release did it this way, so the parser
    has to take the category from the sheet name when there is no column
    for it.
    """
    book = openpyxl.Workbook()
    book.remove(book.active)

    rows = sample_rows()
    for key, label in BEDROOM_LABELS.items():
        sheet = book.create_sheet(label)
        sheet.append([f"Private rents by postcode district: {label}"])
        sheet.append([])
        sheet.append(["Postcode", "Count", "Mean", "Median", "LQ", "UQ"])
        for row in rows:
            if row["bedrooms"] != key:
                continue
            sheet.append([row["district"], row["count"], row["mean"], row["median"],
                          row["lower_quartile"], row["upper_quartile"]])

    book.save(path)
    return path


def write_workbook_with_distractions(path: Path) -> Path:
    """A workbook with borough and region sheets alongside the district one,
    suppression markers, money formatting and a blank row inside the table.

    This is the realistic case. The real release carries region, borough and
    postcode district tables in one file, and the parser has to find the one
    it wants without being told which sheet it is.
    """
    book = openpyxl.Workbook()
    book.remove(book.active)

    notes = book.create_sheet("Notes")
    notes.append(["Notes"])
    notes.append(["Figures are suppressed where the count is below 5."])

    region = book.create_sheet("Region")
    region.append(["Region", "Bedroom category", "Count of rents", "Mean", "Median",
                   "Lower quartile", "Upper quartile"])
    region.append(["London", "One bedroom", 40123, 1850, 1750, 1500, 2100])
    region.append(["Inner London", "One bedroom", 21000, 2050, 1950, 1700, 2350])

    borough = book.create_sheet("Borough")
    borough.append(["Borough", "Bedroom category", "Count of rents", "Mean", "Median",
                    "Lower quartile", "Upper quartile"])
    borough.append(["Greenwich", "One bedroom", 1420, 1690, 1650, 1480, 1850])
    borough.append(["Tower Hamlets", "One bedroom", 2310, 1960, 1900, 1700, 2150])

    district = book.create_sheet("Postcode district")
    district.append(["Private rents by postcode district"])
    district.append(["April 2025 to March 2026"])
    district.append([])
    district.append(["Postcode district", "Bedroom category", "Count of rents", "Mean",
                     "Median", "Lower quartile", "Upper quartile"])
    for row in sample_rows():
        district.append(
            [row["district"], BEDROOM_LABELS[row["bedrooms"]], row["count"],
             f"£{row['mean']:,.0f}", row["median"], row["lower_quartile"], row["upper_quartile"]]
        )
    district.append([])  # a blank row inside the table
    # A district where everything but the count is withheld.
    district.append(["W1B", "One bedroom", 3, "..", "..", "..", ".."])
    # A district with a published count and a suppressed upper quartile only.
    district.append(["SW1H", "Two bedrooms", 46, 3100, 2950, 2600, ":"])

    book.save(path)
    return path


# ---------------------------------------------------------------------------
# A synthetic travel time matrix
# ---------------------------------------------------------------------------


def fake_travel_matrix(n_cells: int, seed: int = 7) -> np.ndarray:
    """A plausible cell to cell travel time matrix.

    Not a routing engine. It produces a symmetric matrix whose times grow
    with distance between cell indices, which is enough to test the
    aggregation, the export and the front end without a 70MB download and
    several gigabytes of heap.
    """
    rng = np.random.default_rng(seed)
    side = int(math.isqrt(n_cells)) + 1
    xs = np.arange(n_cells) % side
    ys = np.arange(n_cells) // side

    dx = xs[:, None] - xs[None, :]
    dy = ys[:, None] - ys[None, :]
    straight = np.sqrt(dx**2 + dy**2)

    # Roughly three minutes per cell, a fixed overhead at each end, and a
    # little noise so medians are not degenerate.
    minutes = 8 + straight * 3.0 + rng.normal(0, 2.0, size=straight.shape)
    minutes = (minutes + minutes.T) / 2
    np.fill_diagonal(minutes, 0.0)
    return np.clip(minutes, 0, None)
