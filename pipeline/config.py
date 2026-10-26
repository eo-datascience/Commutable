"""Every number and path the pipeline depends on, in one place.

Two reasons this is a module rather than constants scattered through the
code. The first is that London is the only city built today but the design
is meant to take others later, so anything city specific is gathered here
and a second city becomes a second config rather than a rewrite. The
second is that a reader who wants to know how coarse the grid is, or which
hour of the morning the journeys are measured over, should find it in one
file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------

# The repository root, derived from this file rather than the working
# directory, so the pipeline behaves the same however it is invoked.
ROOT = Path(__file__).resolve().parent.parent

# Inputs that have to be downloaded by hand live in data/raw. Anything the
# pipeline produces lives in data/derived and is safe to delete.
RAW = Path(os.environ.get("COMMUTABLE_RAW_DIR") or ROOT / "data" / "raw")
# Committed inputs, as opposed to downloaded ones. These are in the
# repository and under review, so they are not configurable by environment.
REFERENCE = ROOT / "data" / "reference"
DERIVED = Path(os.environ.get("COMMUTABLE_DERIVED_DIR") or ROOT / "data" / "derived")

# What the published site reads. Written by the export step.
SITE_DATA = Path(os.environ.get("COMMUTABLE_SITE_DATA_DIR") or ROOT / "frontend" / "public" / "data")


# ---------------------------------------------------------------------------
# Coordinate systems
# ---------------------------------------------------------------------------

# Everything is stored and published in WGS84, because that is what the
# browser and GeoJSON expect.
CRS_WGS84 = "EPSG:4326"

# Anything measured in metres is done in British National Grid. Areas,
# distances and the grid itself are meaningless in degrees, and London is
# far enough north that the distortion is not a rounding error: a degree of
# longitude here is about 62% of a degree of latitude.
CRS_BRITISH_NATIONAL_GRID = "EPSG:27700"


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------

# The side of a grid cell in metres. This is the single most consequential
# number in the project, so it is worth saying why it is 750.
#
# It sets three things at once. It is the precision of the workplace the
# visitor types, since their address snaps to the cell containing it. It is
# the sampling resolution within a postcode district, since a district's
# journey time is the median over the cells inside it. And it sets the cost
# of the whole thing, because the routing engine computes a full cell to
# cell matrix and that grows with the square.
#
# At 750m Greater London is about 2,800 cells, the matrix is about 8 million
# journeys, and a cell is roughly a nine minute walk across, which is inside
# the noise of a forty minute commute. At 400m the matrix is three and a
# half times larger for precision the data underneath does not support,
# because the rent figures are published per postcode district and a
# district is far coarser than any of this.
GRID_CELL_METRES = 750

# A cell is kept if this much of it falls inside the city boundary. Without
# a threshold the grid grows a fringe of cells that are almost entirely
# outside London, each of which costs a file on the published site and
# describes a journey from somewhere nobody works.
MIN_CELL_COVERAGE = 0.25


# ---------------------------------------------------------------------------
# Which postcode districts count as London
# ---------------------------------------------------------------------------

# The postal geography and the administrative one disagree, which is a fact
# about Britain rather than a problem with the data. Postcode districts were
# drawn for delivery rounds and cross the Greater London boundary freely:
# KT and TW reach well into Surrey, RM into Essex, DA into Kent.
#
# A district is treated as London if at least this much of its area lies
# inside Greater London. At 0.10 the result is 274 districts. Raising it to
# 0.50 drops eight, among them KT8 and DA1, which contain real London
# commuter housing and real ONS rent figures. Lowering it to 0.01 adds
# nineteen slivers whose rent figures describe Surrey or Essex rather than
# London.
MIN_DISTRICT_IN_CITY = 0.10

# The postcode areas worth loading at all. Every district in Greater London
# begins with one of these, so the others need never be downloaded.
LONDON_POSTCODE_AREAS = (
    # The London postal district proper
    "E", "EC", "N", "NW", "SE", "SW", "W", "WC",
    # Outer areas that reach into Greater London
    "BR", "CR", "DA", "EN", "HA", "IG", "KT", "RM", "SM", "TW", "UB", "WD",
)


# ---------------------------------------------------------------------------
# When the journeys are measured
# ---------------------------------------------------------------------------

# A single departure time is a lottery. Leave at 08:00 and you may catch a
# train that leaves at 08:01 or one that leaves at 08:19, and the second
# makes a district look twenty minutes worse than it is. So every journey
# is computed repeatedly across a window of departures and the median is
# kept, which is the figure a person actually experiences over a working
# week.
#
# The date is a plain Tuesday chosen to sit inside the timetable feed's
# validity period and away from school holidays and bank holidays. It must
# be changed when the feed is refreshed, and the routing step fails loudly
# rather than silently if it falls outside the feed's range.
DEPARTURE_DATE = "2026-10-13"
DEPARTURE_WINDOW_START = "08:00"
DEPARTURE_WINDOW_MINUTES = 60

# How far a person will walk to a stop at each end. Generous enough to
# reach a station from most of a cell, short of the distance at which
# walking stops being a realistic part of a daily commute.
MAX_WALK_MINUTES = 20

# Journeys longer than this are recorded as unreachable. Nobody choosing
# where to live is weighing up a two hour each way commute, and a ceiling
# keeps the published numbers in two bytes.
MAX_JOURNEY_MINUTES = 120

# The value that means "no journey found within the ceiling". Chosen to be
# the largest unsigned 16 bit integer so it survives the binary export
# without a separate mask.
UNREACHABLE = 65535


# ---------------------------------------------------------------------------
# Rent
# ---------------------------------------------------------------------------

# ONS suppresses cells built on very few observations, but it still
# publishes some built on a handful. A median drawn from six tenancies is
# not a market rate, so anything below this is treated as absent rather
# than shown as if it were known. Unknown is not the same as expensive, and
# a district with too little data is marked as such on the map instead of
# being coloured as though it had been measured.
MIN_RENT_SAMPLE = 20

# Above this, the sample is thick enough that the site presents the figures
# without qualification. Below it the district is still shown, because the
# figures are real, but the panel says how thin the evidence is.
#
# The two numbers together replace what was a single floor of 30, chosen
# before the real release had been seen. Three things in the published data
# argue for the lower floor. ONS suppresses any statistic drawn from fewer
# than five tenancies, so the data has already censored itself. Counts are
# rounded to the nearest ten, so the floor cannot be finer than that anyway.
# And where the evidence is genuinely too thin, ONS withholds the quartiles
# rather than the count, which this pipeline already treats as missing.
#
# At 30 the pipeline was discarding 280 rows for which ONS had published a
# complete set of quartiles, and greying out roughly a third of London on
# the map. A district hatched as "no figures" tells a visitor nothing. A
# median drawn from twenty lettings, labelled as such, tells them something
# true. The second is the better failure.
LOW_RENT_SAMPLE = 50

# The bedroom categories the site offers. The keys are what appears in the
# URL and the published files; the values are matched against whatever
# wording the ONS workbook uses, case insensitively.
BEDROOM_CATEGORIES: dict[str, tuple[str, ...]] = {
    "room": ("room", "room only"),
    "studio": ("studio",),
    "1": ("one bedroom", "1 bedroom", "one bed", "1 bed"),
    "2": ("two bedroom", "two bedrooms", "2 bedroom", "2 bedrooms", "two bed", "2 bed"),
    "3": ("three bedroom", "three bedrooms", "3 bedroom", "3 bedrooms", "three bed", "3 bed"),
    "4+": ("four", "four or more", "4+", "four bedroom", "four or more bedrooms"),
    "all": ("all categories", "all", "total", "all properties"),
}

# The narrowest spread that is treated as a real market.
#
# sigma is the standard deviation of the log of the rent, so it reads as a
# proportion: 0.01 corresponds to an interquartile range of about 1.4% of
# the median, which would mean three quarters of a district's flats letting
# within twenty pounds of each other. Where the published quartiles are
# that close together, or identical, the figures are a rounding artefact of
# a thin sample rather than a measurement of spread.
#
# A floor is needed rather than a check for zero because the arithmetic
# does not produce an exact zero. Three identical quartiles give a sigma of
# about 5e-16, which is positive, passes any test for zero, and turns the
# published share of the market into a step function: a pound under the
# median reaches none of it and a pound over reaches all of it.
MIN_RENT_SIGMA = 0.01

# The fitted rent distribution is checked against the published median. If
# the fit implies a median this far off the real one, the district is
# flagged rather than quietly published. See pipeline/rent.py for why a
# lognormal is the shape being fitted.
MAX_MEDIAN_FIT_ERROR = 0.05

# Published with the site so the method is stated where the numbers are,
# rather than only in the repository.
MAX_RENT_SIGMA_NOTE = (
    "The share of a district's market under a budget is estimated by fitting a "
    "lognormal to the three rent figures ONS publishes for that district: the lower "
    "quartile, the median and the upper quartile. Two parameters is all three points "
    "can support. Where the fitted curve misses one of those three by more than "
    "5 per cent the estimate is marked as rough."
)


@dataclass(frozen=True)
class City:
    """Everything that would differ for a second city.

    London is the only one implemented. The point of the dataclass is that
    adding Manchester should mean adding one of these and four input files,
    not editing the pipeline.
    """

    id: str
    name: str
    postcode_areas: tuple[str, ...]
    # Filenames inside data/raw. Deliberately not URLs: three of the four
    # inputs cannot be fetched without agreeing to a licence or picking an
    # extract, so the pipeline asks for files and says where to get them.
    boundary_file: str
    rent_file: str
    osm_file: str
    # More than one timetable feed, because no single publisher covers a
    # whole city. London's rail, tube, DLR and tram services come from one
    # feed and its buses from another, and a routing engine given only the
    # first would be systematically pessimistic about exactly the outer
    # districts where the rents are lowest. R5 takes any number of feeds and
    # merges them.
    gtfs_files: tuple[str, ...]
    # A readable name per postcode district, committed rather than fetched.
    # A district code is an address, not a place: a map labelled only in
    # codes asks the reader to translate before they can read it. The names
    # are editorial choices made from a published source, so they are
    # reviewed and committed like any other text in the site rather than
    # scraped on every build.
    district_names_file: str | None = None
    timezone: str = "Europe/London"
    grid_cell_metres: int = GRID_CELL_METRES
    min_district_in_city: float = MIN_DISTRICT_IN_CITY
    departure_date: str = DEPARTURE_DATE
    departure_window_start: str = DEPARTURE_WINDOW_START
    departure_window_minutes: int = DEPARTURE_WINDOW_MINUTES

    @property
    def departure_datetime(self) -> datetime:
        return datetime.fromisoformat(f"{self.departure_date}T{self.departure_window_start}:00")


LONDON = City(
    id="london",
    name="London",
    postcode_areas=LONDON_POSTCODE_AREAS,
    boundary_file="london_boroughs.geojson",
    rent_file="londonrentalstatsaccessibleq12026.xlsx",
    osm_file="greater-london-latest.osm.pbf",
    gtfs_files=("gtfs-rail-and-tfl.zip", "london-buses-gtfs.zip"),
    district_names_file="london_district_names.json",
)

CITIES: dict[str, City] = {LONDON.id: LONDON}
DEFAULT_CITY = LONDON.id


@dataclass(frozen=True)
class Attribution:
    """Each input's source and licence.

    Published with the site rather than kept in a comment. Two of the four
    inputs are share alike, so the attribution is a licence condition, not
    a courtesy.
    """

    name: str
    source: str
    licence: str
    url: str


ATTRIBUTIONS: tuple[Attribution, ...] = (
    Attribution(
        name="Postcode district boundaries",
        source="Wikipedia contributors, via missinglink/uk-postcode-polygons",
        licence="CC BY-SA 3.0",
        url="https://github.com/missinglink/uk-postcode-polygons",
    ),
    Attribution(
        name="Postcode district names",
        source="Wikipedia contributors, from the coverage tables of the London "
               "postcode area articles",
        licence="CC BY-SA 3.0",
        url="https://en.wikipedia.org/wiki/London_postal_district",
    ),
    Attribution(
        name="London borough boundaries",
        source="Office for National Statistics",
        licence="Open Government Licence v3.0",
        url="https://geoportal.statistics.gov.uk/",
    ),
    Attribution(
        name="Private rents",
        source="Office for National Statistics, Private rental market in London",
        licence="Open Government Licence v3.0",
        url="https://www.ons.gov.uk/economy/inflationandpriceindices/adhocs/3389privaterentalmarketinlondonapril2025tomarch2026",
    ),
    Attribution(
        name="Street network",
        source="OpenStreetMap contributors",
        licence="ODbL 1.0",
        url="https://www.openstreetmap.org/copyright",
    ),
    Attribution(
        name="Timetables, rail and tube",
        source="National Rail and Transport for London, converted to GTFS by "
               "planarnetwork/gb-transit",
        licence="Powered by TfL Open Data",
        url="https://github.com/planarnetwork/gb-transit",
    ),
    Attribution(
        name="Timetables, buses",
        source="Bus Open Data Service, Department for Transport",
        licence="Open Government Licence v3.0",
        url="https://data.bus-data.dft.gov.uk/",
    ),
)


def city(city_id: str | None = None) -> City:
    key = city_id or DEFAULT_CITY
    try:
        return CITIES[key]
    except KeyError:
        raise KeyError(f"No such city: {key!r}. Known cities: {sorted(CITIES)}") from None
