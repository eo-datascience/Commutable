"""Rent, and the one piece of real statistics in the project.

The source is the ONS release of private rents for London, which publishes
for each postcode district and each bedroom category a count of observed
tenancies and five figures: mean, median, lower quartile and upper
quartile.

A map that only used the median would answer the wrong question. "The
median two bedroom flat in SE4 is £1,750" does not tell someone with
£1,600 whether to look there, because half the market is below the median
and some of that half is below £1,600. What they want to know is how much
of the market their budget actually reaches, and that is a question about
the shape of the distribution, not its midpoint.

So a distribution is fitted to the published quantiles and the site reports
the share of the market under the visitor's budget. Three quantiles is thin
evidence, which is why the fit is validated against the data it was fitted
to and the residual is published rather than hidden.

Why lognormal
-------------
Rents cannot be negative, cluster around a typical value and have a long
right tail: a handful of very expensive properties and no correspondingly
cheap ones. That is the standard shape for prices and incomes, and the
lognormal is the standard two parameter family for it. Two parameters is
also all three quantiles can honestly support; fitting anything richer
would be reading detail into the data that is not there.

The fit is checked rather than assumed. For every district the fitted
curve is compared against all three published quantiles and the largest
relative error is recorded. Districts where that error is large are
published with the flag set, so the site can say the estimate is rougher
there instead of presenting it with the same confidence as everywhere else.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.config import (
    BEDROOM_CATEGORIES,
    LOW_RENT_SAMPLE,
    MAX_MEDIAN_FIT_ERROR,
    MIN_RENT_SAMPLE,
    MIN_RENT_SIGMA,
)

logger = logging.getLogger(__name__)

# The standard normal quantile at 0.25. Hard coded rather than pulled from
# scipy because it is a constant, and because it keeps scipy out of the
# dependency list for the sake of one number.
Z_QUARTILE = 0.6744897501960817

# The three quantiles the fit uses, with their standard normal positions.
FIT_QUANTILES: tuple[tuple[str, float], ...] = (
    ("lower_quartile", -Z_QUARTILE),
    ("median", 0.0),
    ("upper_quartile", Z_QUARTILE),
)

# A postcode district: one or two letters, a digit, then optionally another
# digit or a letter. Matches SE1, SE10, EC1A, W1. Used to recognise which
# column of a spreadsheet holds the geography, which is more robust than
# trusting a column heading to be spelled the way it was last year.
DISTRICT_PATTERN = re.compile(r"^[A-Z]{1,2}[0-9][A-Z0-9]?$")

# What ONS writes where a figure is suppressed or absent. A count of five
# tenancies is withheld to protect the tenants, which is right, and means
# the parser must distinguish "withheld" from "zero".
# The real release uses ".." for not available and "." for not
# applicable, both documented on its Notes sheet. The rest are markers
# other editions and other ONS releases have used.
SUPPRESSED = {"..", ".", ":", "-", "–", "—", "c", "x", "z", "n/a", "na", ""}

# Column headings seen across editions of this release, normalised to the
# names used in the rest of the pipeline. Matching is on a squashed form of
# the heading, so "Lower quartile" and "lower_quartile" both land.
COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "district": ("postcodedistrict", "postcode", "postcodearea", "district", "geography",
                 "geographyname", "areaname", "pcd"),
    "bedrooms": ("bedroomcategory", "bedrooms", "bedroom", "category", "propertytype",
                 "numberofbedrooms"),
    "count": ("count", "countofrents", "numberofrents", "sample", "samplesize",
              "countofrentalprices", "numberofobservations"),
    "mean": ("mean", "meanrent", "average", "averagerent"),
    "median": ("median", "medianrent"),
    "lower_quartile": ("lowerquartile", "lq", "lowerquartilerent", "q1", "percentile25",
                       "lower25", "25thpercentile"),
    "upper_quartile": ("upperquartile", "uq", "upperquartilerent", "q3", "percentile75",
                       "upper75", "75thpercentile"),
}

REQUIRED_COLUMNS = ("district", "count", "median", "lower_quartile", "upper_quartile")


# ---------------------------------------------------------------------------
# The fitted distribution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RentDistribution:
    """A fitted lognormal for one district and one bedroom category."""

    district: str
    bedrooms: str
    sample: int
    # Published figures, kept verbatim. The site shows these rather than
    # anything derived, so that a visitor who checks against the ONS
    # release sees the same numbers.
    median: float
    lower_quartile: float
    upper_quartile: float
    mean: float | None
    # The fit.
    mu: float
    sigma: float
    # The largest relative error between the fitted curve and the three
    # published quantiles. Published, not hidden.
    max_fit_error: float

    @property
    def well_fitted(self) -> bool:
        return self.max_fit_error <= MAX_MEDIAN_FIT_ERROR

    @property
    def thin_sample(self) -> bool:
        """Real figures, but drawn from few enough tenancies that the site
        should say so rather than present them like the rest."""
        return self.sample < LOW_RENT_SAMPLE

    def share_under(self, budget: float) -> float:
        """The share of this market at or below a monthly budget.

        The lognormal cumulative distribution, which for a lognormal is the
        normal cumulative distribution of the log. math.erf is used rather
        than scipy for the same reason as above: it is in the standard
        library and this is one formula.
        """
        if budget <= 0:
            return 0.0
        z = (math.log(budget) - self.mu) / self.sigma
        return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

    def quantile(self, p: float) -> float:
        """The rent at a given percentile of this market."""
        if not 0.0 < p < 1.0:
            raise ValueError(f"A percentile must be between 0 and 1, not {p}")
        return math.exp(self.mu + self.sigma * _inverse_normal_cdf(p))

    def budget_for_share(self, share: float) -> float:
        """The budget needed to reach a given share of this market.

        The inverse of share_under, and the more useful direction for a
        visitor who wants to know what it would take rather than what they
        can get.
        """
        return self.quantile(share)


def fit_lognormal(
    district: str,
    bedrooms: str,
    sample: int,
    median: float,
    lower_quartile: float,
    upper_quartile: float,
    mean: float | None = None,
) -> RentDistribution:
    """Fit a lognormal to three published quantiles by least squares.

    For a lognormal, the log of the rent at percentile p is mu + sigma * z,
    where z is the standard normal quantile. So in log space the three
    published quantiles should lie on a straight line against z, and the
    fit is an ordinary least squares line through three points.

    Because the three z values are symmetric about zero and sum to zero,
    the two parameters separate and there is nothing to iterate:

        mu    = the mean of the three log quantiles
        sigma = (log(UQ) - log(LQ)) / (2 * z_quartile)

    That is worth saying plainly because it means there is no optimiser to
    fail to converge, no starting point to choose and no hidden tolerance.
    The same two lines of arithmetic produce the same answer every time.
    """
    if not (lower_quartile > 0 and median > 0 and upper_quartile > 0):
        raise ValueError(
            f"{district} {bedrooms}: rents must be positive, got "
            f"LQ={lower_quartile}, median={median}, UQ={upper_quartile}"
        )
    if not lower_quartile <= median <= upper_quartile:
        # Not a rounding artefact. If the quartiles straddle the median the
        # wrong way round, the columns have been read in the wrong order,
        # and silently fitting a curve to them would produce confident
        # nonsense for that district.
        raise ValueError(
            f"{district} {bedrooms}: quartiles are out of order "
            f"(LQ={lower_quartile}, median={median}, UQ={upper_quartile}). "
            f"The columns have probably been matched to the wrong headings."
        )

    logs = np.log([lower_quartile, median, upper_quartile])
    zs = np.array([z for _, z in FIT_QUANTILES])

    mu = float(logs.mean())
    sigma = float((logs @ zs) / (zs @ zs))

    if sigma < MIN_RENT_SIGMA:
        # The quartiles are the same figure, or so close to it that the
        # spread is a rounding artefact. Fitting anyway would publish a
        # step function: every rent in the district at exactly the median.
        raise ValueError(
            f"{district} {bedrooms}: the quartiles are too close together to describe a "
            f"market (LQ={lower_quartile:.0f}, UQ={upper_quartile:.0f}, which implies a "
            f"spread of {sigma:.4f} against a floor of {MIN_RENT_SIGMA}). "
            f"There is no distribution to fit. Sample size was {sample}."
        )

    fitted = np.exp(mu + sigma * zs)
    published = np.array([lower_quartile, median, upper_quartile])
    max_error = float(np.max(np.abs(fitted - published) / published))

    return RentDistribution(
        district=district,
        bedrooms=bedrooms,
        sample=sample,
        median=float(median),
        lower_quartile=float(lower_quartile),
        upper_quartile=float(upper_quartile),
        mean=float(mean) if mean is not None and not pd.isna(mean) else None,
        mu=mu,
        sigma=sigma,
        max_fit_error=max_error,
    )


def _inverse_normal_cdf(p: float) -> float:
    """The standard normal quantile function.

    Acklam's rational approximation, accurate to about 1.15e-9 across the
    whole range, which is several orders of magnitude finer than rent data
    published to the nearest pound. Included rather than importing scipy
    because scipy is a large dependency and this is the only thing that
    would be used from it.
    """
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    low, high = 0.02425, 1 - 0.02425

    if p < low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


# ---------------------------------------------------------------------------
# Reading the workbook
# ---------------------------------------------------------------------------


@dataclass
class SheetLayout:
    """Where the data is in one sheet of the workbook."""

    sheet: str
    header_row: int
    columns: dict[str, str]          # canonical name -> actual heading
    bedrooms_from_sheet: str | None  # set when the sheet is one bedroom category

    @property
    def usable(self) -> bool:
        have = set(self.columns)
        if not set(REQUIRED_COLUMNS) <= have:
            return False
        return "bedrooms" in have or self.bedrooms_from_sheet is not None


def _squash(value: object) -> str:
    """Reduce a heading to letters and digits, lower case.

    'Lower Quartile (£)' and 'lower_quartile' both become 'lowerquartile',
    so a change of punctuation or capitalisation between editions does not
    break the parser.
    """
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _match_columns(headings: list[object]) -> dict[str, str]:
    """Match a row of headings against the known synonyms.

    Exact match on the squashed form first, then prefix match, so that
    'Median rent (£ per month)' finds 'median' without 'median' also
    claiming 'medianrentannual' when a better candidate exists.
    """
    squashed = [(i, _squash(h)) for i, h in enumerate(headings) if str(h).strip() not in ("", "nan")]
    matched: dict[str, str] = {}
    taken: set[int] = set()

    for canonical, synonyms in COLUMN_SYNONYMS.items():
        for synonym in synonyms:
            for i, text in squashed:
                if i in taken:
                    continue
                if text == synonym:
                    matched[canonical] = str(headings[i])
                    taken.add(i)
                    break
            if canonical in matched:
                break
        if canonical in matched:
            continue
        for synonym in synonyms:
            for i, text in squashed:
                if i in taken:
                    continue
                if text.startswith(synonym) or synonym in text:
                    matched[canonical] = str(headings[i])
                    taken.add(i)
                    break
            if canonical in matched:
                break

    return matched


def _bedrooms_from_text(text: object) -> str | None:
    """Map whatever the workbook says to one of the site's categories.

    A value that is already a category key passes through unchanged, so
    the function is safe to apply twice. Without that, '4+' would be
    squashed to '4' and matched against nothing.
    """
    if isinstance(text, str) and text in BEDROOM_CATEGORIES:
        return text

    squashed = _squash(text)
    if not squashed:
        return None
    # Longest synonyms first, so 'twobedroom' is not claimed by 'two'.
    candidates = sorted(
        ((key, _squash(s)) for key, syns in BEDROOM_CATEGORIES.items() for s in syns),
        key=lambda pair: -len(pair[1]),
    )
    for key, synonym in candidates:
        if squashed == synonym or squashed.startswith(synonym):
            return key
    return None


def _bedrooms_from_sheet_name(name: object) -> str | None:
    """A bedroom category taken from a sheet name, or nothing.

    Stricter than reading one from a cell, and it has to be. The real ONS
    release names its three data sheets "1", "2" and "3", meaning worksheet
    one, two and three. Read as cell values those are the category keys for
    one, two and three bedrooms, so the sheet holding every postcode
    district in London announces itself as the three bedroom sheet.

    It did no damage, because that sheet carries its own Bedroom Category
    column and the sheet name is only consulted for rows the column fails
    to resolve. But it was one unrecognised label away from silently
    relabelling a row as three bedrooms, which would have been invisible in
    the output and wrong on the map.

    So a bare number is never a bedroom category. A sheet actually named
    for one says "One Bedroom" or "Two Bedrooms", never "2".
    """
    squashed = _squash(name)
    if not squashed or squashed.rstrip("+").isdigit():
        return None
    return _bedrooms_from_text(name)


def describe_workbook(path: Path, max_rows: int = 25) -> str:
    """Report what is actually in the workbook.

    This exists because the release is an ad hoc publication whose layout
    has changed between editions, and because a parser that guesses wrong
    about a column is worse than one that refuses. Run this first, read the
    output, and the failure messages elsewhere in this module will make
    sense.

        python scripts/describe_workbook.py data/raw/<file>.xlsx
    """
    import openpyxl  # noqa: PLC0415  (only needed by this function)

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    lines = [f"{path.name}", f"{len(book.sheetnames)} sheet(s)", ""]

    for name in book.sheetnames:
        sheet = book[name]
        bedrooms = _bedrooms_from_sheet_name(name)
        lines.append(f"--- sheet {name!r}"
                     + (f"  (reads as bedroom category {bedrooms!r})" if bedrooms else ""))
        for row_number, row in enumerate(sheet.iter_rows(max_row=max_rows, values_only=True), 1):
            cells = ["" if c is None else str(c) for c in row]
            if not any(cells):
                continue
            matched = _match_columns(list(row))
            flag = f"\n           ^ matches {sorted(matched)}" if len(matched) >= 3 else ""
            # Cells are shown at a width that keeps a column heading intact.
            # The first version cut them to 22 characters, which turned
            # "Lower quartile of monthly rent" into "Lower quartile of mont"
            # and made the output useless for the one job it has, which is
            # telling a reader which heading the parser should be matching.
            shown = [c if len(c) <= 48 else c[:45] + "..." for c in cells[:12]]
            lines.append(f"  row {row_number:>3}: " + " | ".join(shown) + flag)
        lines.append("")

    book.close()
    return "\n".join(lines)


def find_layouts(path: Path, max_header_row: int = 20) -> list[SheetLayout]:
    """Work out where the data is in each sheet.

    The header row is found by scoring every early row against the known
    column names and taking the best, rather than by assuming a row number.
    Editions of this release have put the table under one title row, under
    four, and under a block of notes.
    """
    import openpyxl  # noqa: PLC0415

    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    layouts: list[SheetLayout] = []

    for name in book.sheetnames:
        sheet = book[name]
        best: tuple[int, dict[str, str]] | None = None
        for row_number, row in enumerate(sheet.iter_rows(max_row=max_header_row, values_only=True), 1):
            matched = _match_columns(list(row))
            score = len(set(matched) & set(REQUIRED_COLUMNS))
            if best is None or score > len(set(best[1]) & set(REQUIRED_COLUMNS)):
                best = (row_number, matched)

        if best is not None:
            layouts.append(
                SheetLayout(
                    sheet=name,
                    header_row=best[0],
                    columns=best[1],
                    bedrooms_from_sheet=_bedrooms_from_sheet_name(name),
                )
            )

    book.close()
    return layouts


def load_rents(path: Path, districts: set[str] | None = None) -> pd.DataFrame:
    """Read every usable sheet and return one tidy table.

    Columns: district, bedrooms, count, mean, median, lower_quartile,
    upper_quartile.

    Rows whose geography is not a postcode district are dropped, which is
    how the borough and region tables in the same workbook are skipped
    without needing to know their sheet names.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"No rent workbook at {path}.\n"
            f"See docs/data-sources.md. It is a single .xlsx from the ONS ad hoc "
            f"release 'Private rental market in London'."
        )

    layouts = find_layouts(path)
    usable = [layout for layout in layouts if layout.usable]

    if not usable:
        raise ValueError(
            f"No sheet in {path.name} has the columns this pipeline needs.\n"
            f"Required: {', '.join(REQUIRED_COLUMNS)}, plus a bedroom category either as a "
            f"column or as the sheet name.\n"
            f"What was found:\n"
            + "\n".join(
                f"  sheet {layout.sheet!r}: header looked like row {layout.header_row}, "
                f"matched {sorted(layout.columns) or 'nothing'}"
                for layout in layouts
            )
            + f"\n\nRun scripts/describe_workbook.py {path} to see the actual layout."
        )

    frames: list[pd.DataFrame] = []
    for layout in usable:
        frame = pd.read_excel(path, sheet_name=layout.sheet, header=layout.header_row - 1)
        rename = {actual: canonical for canonical, actual in layout.columns.items()}
        frame = frame.rename(columns=rename)

        keep = [c for c in ("district", "bedrooms", "count", "mean", "median",
                            "lower_quartile", "upper_quartile") if c in frame.columns]
        frame = frame[keep].copy()

        frame["district"] = frame["district"].astype(str).str.strip().str.upper()
        frame = frame[frame["district"].str.match(DISTRICT_PATTERN)]
        if frame.empty:
            logger.debug("Sheet %r holds no postcode districts, skipping.", layout.sheet)
            continue

        # The category comes from the column when there is one, and from the
        # sheet name otherwise. Mapping the sheet name once here, rather than
        # writing it into the column and mapping the column, matters: the
        # sheet name has already been translated into a category key by
        # find_layouts, and translating a key a second time finds nothing.
        if "bedrooms" in frame.columns:
            category = frame["bedrooms"].map(_bedrooms_from_text)
        else:
            category = pd.Series(None, index=frame.index, dtype="object")
        if layout.bedrooms_from_sheet is not None:
            category = category.fillna(layout.bedrooms_from_sheet)
        frame["bedrooms"] = category
        frame = frame[frame["bedrooms"].notna()]
        if frame.empty:
            logger.debug("Sheet %r holds no recognised bedroom category, skipping.", layout.sheet)
            continue

        for column in ("count", "mean", "median", "lower_quartile", "upper_quartile"):
            if column in frame.columns:
                frame[column] = frame[column].map(_to_number)
            else:
                frame[column] = np.nan

        frames.append(frame)
        logger.info(
            "Sheet %r: %d postcode district rows from header row %d.",
            layout.sheet, len(frame), layout.header_row,
        )

    if not frames:
        raise ValueError(
            f"{path.name} parsed, but no sheet contained rows whose geography looked like a "
            f"postcode district. The workbook may be a borough level edition."
        )

    rents = pd.concat(frames, ignore_index=True)

    # The same district and bedroom category appearing twice would mean two
    # sheets covering the same ground, and quietly keeping both would double
    # count it in every aggregate.
    duplicated = rents.duplicated(["district", "bedrooms"], keep=False)
    if duplicated.any():
        examples = rents.loc[duplicated, ["district", "bedrooms"]].drop_duplicates().head(5)
        logger.warning(
            "%d rows repeat a district and bedroom category, for example:\n%s\n"
            "Keeping the row with the larger sample.",
            int(duplicated.sum()), examples.to_string(index=False),
        )
        rents = (
            rents.sort_values("count", ascending=False)
            .drop_duplicates(["district", "bedrooms"], keep="first")
        )

    if districts is not None:
        before = len(rents)
        rents = rents[rents["district"].isin(districts)]
        logger.info(
            "Kept %d of %d rows after restricting to the %d districts in the city.",
            len(rents), before, len(districts),
        )

    return rents.sort_values(["district", "bedrooms"]).reset_index(drop=True)


def _to_number(value: object) -> float:
    """Parse a cell that might be a number, a suppression marker or money."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.lower() in SUPPRESSED:
        return float("nan")
    cleaned = re.sub(r"[£,\s]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return float("nan")


# ---------------------------------------------------------------------------
# From the table to fitted distributions
# ---------------------------------------------------------------------------


@dataclass
class RentReport:
    """Every fitted distribution, plus what was rejected and why.

    The rejections are the point of the dataclass. A district missing from
    the map should be missing for a reason the site can state, not because
    a row quietly failed to parse.
    """

    distributions: dict[tuple[str, str], RentDistribution] = field(default_factory=dict)
    rejected: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def districts(self) -> set[str]:
        return {district for district, _ in self.distributions}

    @property
    def bedroom_categories(self) -> set[str]:
        return {bedrooms for _, bedrooms in self.distributions}

    @property
    def poorly_fitted(self) -> list[RentDistribution]:
        return [d for d in self.distributions.values() if not d.well_fitted]

    def get(self, district: str, bedrooms: str) -> RentDistribution | None:
        return self.distributions.get((district, bedrooms))


def fit_all(rents: pd.DataFrame, min_sample: int = MIN_RENT_SAMPLE) -> RentReport:
    """Fit a distribution for every district and bedroom category with enough data."""
    report = RentReport()

    for row in rents.itertuples(index=False):
        district, bedrooms = row.district, row.bedrooms

        if pd.isna(row.count):
            report.rejected.append((district, bedrooms, "no sample size published"))
            continue
        sample = int(row.count)
        if sample < min_sample:
            report.rejected.append(
                (district, bedrooms, f"sample of {sample} is below the minimum of {min_sample}")
            )
            continue
        if any(pd.isna(getattr(row, c)) for c in ("median", "lower_quartile", "upper_quartile")):
            report.rejected.append((district, bedrooms, "a quartile or the median is suppressed"))
            continue

        try:
            report.distributions[(district, bedrooms)] = fit_lognormal(
                district=district,
                bedrooms=bedrooms,
                sample=sample,
                median=float(row.median),
                lower_quartile=float(row.lower_quartile),
                upper_quartile=float(row.upper_quartile),
                mean=getattr(row, "mean", None),
            )
        except ValueError as error:
            report.rejected.append((district, bedrooms, str(error)))

    logger.info(
        "Fitted %d district and bedroom combinations across %d districts. "
        "Rejected %d.",
        len(report.distributions), len(report.districts), len(report.rejected),
    )
    if report.poorly_fitted:
        worst = max(report.poorly_fitted, key=lambda d: d.max_fit_error)
        logger.info(
            "%d combinations fit the lognormal worse than %.0f%% and are flagged on the site. "
            "The worst is %s %s at %.1f%%.",
            len(report.poorly_fitted), MAX_MEDIAN_FIT_ERROR * 100,
            worst.district, worst.bedrooms, worst.max_fit_error * 100,
        )
    return report
