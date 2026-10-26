# The four inputs

One downloads itself. The other three cannot, for three different reasons, and
each has to be fetched by hand once.

Everything goes in `data/raw/`. The filenames the pipeline expects are set in
`pipeline/config.py` under `LONDON`, so if a release changes its name, change
it there rather than renaming the file.

---

## 1. Boundaries — automatic

```bash
python scripts/fetch_boundaries.py
```

Downloads the 33 London borough outlines and the postcode district polygons for
the 20 postcode areas that reach into Greater London. About 1.4 MB in total.
Both are small enough to live in the repository, which is why the tests can run
against real London shapes rather than invented ones.

The district polygons come from Wikipedia under CC BY-SA 3.0 and are indicative
rather than authoritative: they were drawn for a reference article, not surveyed.
They are good enough here because the rent figures underneath are themselves
published per district, so boundary precision is nowhere near the binding
constraint. If you want better, a set derived from Ordnance Survey's Code-Point
Open can be dropped into `data/raw/postcode_districts/` in the same shape and
nothing else changes.

---

## 2. Rents — one spreadsheet

**ONS, _Private rental market in London_**

<https://www.ons.gov.uk/economy/inflationandpriceindices/adhocs/3389privaterentalmarketinlondonapril2025tomarch2026>

Download the `.xlsx` and save it to `data/raw/`. Set `rent_file` in
`pipeline/config.py` to its name.

This cannot be scripted because it is an **ad hoc release**: ONS publishes it on
request rather than on a schedule, each edition gets its own page and its own
URL, and the previous England-wide series it descends from was discontinued in
December 2023. There is no stable address to fetch.

It is also why the parser is written to discover the layout rather than assume
it. Editions of this release have put the table under one title row and under
four, have used a bedroom column and a sheet per bedroom category, and have
carried the region, borough and postcode district tables together in one file.
The parser scores every early row against the column names it knows, finds the
geography column by the shape of its values rather than its heading, and fails
with a message naming what it actually found.

If it fails, run this first and read the output:

```bash
python scripts/build.py --describe-rents
```

It prints every sheet, the first rows of each, and which columns were matched.

**What the pipeline needs from it:** a postcode district, a bedroom category, a
count of rents, a median, a lower quartile and an upper quartile. The mean is
used if present and not required.

---

## 3. Street network — one extract

**Geofabrik, Greater London**

<https://download.geofabrik.de/europe/united-kingdom/england/greater-london-latest.osm.pbf>

Save to `data/raw/greater-london-latest.osm.pbf`. About 70 MB.

Not scripted because an OpenStreetMap extract is a choice rather than a fixed
file: the region, the provider and the date all vary, and a pipeline that picks
one for you will sooner or later pick the wrong one. Any `.osm.pbf` covering
Greater London will do.

It is used twice. R5 needs it to route walking at both ends of every journey.
The pipeline also reads residential building footprints out of it to weight the
grid cells inside each district, so a district's journey time describes where
people live rather than where the parks are. That second use needs
[osmium](https://pypi.org/project/osmium/), which is in `requirements.txt`; if
it is unavailable the weighting falls back to an unweighted median and says so
in the log.

---

## 4. Timetables — two GTFS feeds

This is the one that needed correcting. **TfL does not publish GTFS.** It
publishes XML, and its journey planner timetables are TransXChange, which R5
cannot read. So the feeds come from two places, and between them they cover
the network.

### 4a. Rail, tube, DLR and trams

**planarnetwork/gb-transit**, nightly releases

<https://github.com/planarnetwork/gb-transit/releases>

Open the most recent release and download **`gtfs-rail-and-tfl.zip`**. Save it
to `data/raw/gtfs-rail-and-tfl.zip`.

This is a conversion of National Rail's timetables plus TfL's tube, DLR, trams,
river boats and cable car, published as GTFS and rebuilt every night. National
Rail covers the Overground and the Elizabeth line, so between them that is
every rail-like mode in London.

It is a third-party conversion rather than an official feed, which is worth
knowing and worth saying on the site. The upside is that it needs no
registration and it is current. The downside is that it depends on somebody
else's nightly job: at the time of writing the release notes record that TfL
"turned the download away" on one occasion and the feed was rebuilt from a
cached copy a few days old. Check the release notes on the one you download.

### 4b. Buses

**Bus Open Data Service**, run by the Department for Transport

<https://data.bus-data.dft.gov.uk/downloads/>

Choose the **Timetables data** download and the **GTFS** format, then take the
London region file. Save it to `data/raw/london-buses-gtfs.zip`. A free account
may be required.

Buses are not optional here, and it is worth being clear why. Outer London is
where the rents are lowest, and large parts of it are badly served by rail and
well served by buses. A routing engine given only the rail feed would find no
way out of those districts inside the time limit and grey them out. The map
would be systematically pessimistic about exactly the places the visitor most
wants to know about, and it would look entirely plausible while doing it.

### If the bus feed defeats you

The pipeline takes any number of feeds, listed in `gtfs_files` in
`pipeline/config.py`. Dropping to the rail feed alone is one line:

```python
gtfs_files=("gtfs-rail-and-tfl.zip",)
```

Do that if you want to see the map working today, but treat it as temporary and
put a note on the site, because the bias it introduces is real and it points in
one direction.

### Check the dates, whichever feeds you use

`DEPARTURE_DATE` in `pipeline/config.py` must be a weekday falling inside the
validity period of **every** feed, which is in each one's `calendar.txt`. If it
falls outside one of them, R5 silently finds no services on that feed and
routes those journeys on foot. The result is a map of walking distance that
looks superficially reasonable. The routing step warns when fewer than 20% of
cell pairs are reachable, which is what that failure looks like from outside.

## Checking what you have

```bash
python scripts/build.py --synthetic   # builds with fabricated numbers, works with no inputs
python scripts/build.py               # the real thing
```

The real build fails with a message naming the missing file and pointing back
here. Routing is the only slow stage; once it has run the matrix is saved to
`data/derived/`, and `--reuse-matrix` skips it while you change anything else.
