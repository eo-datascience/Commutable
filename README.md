# Commutable

**Where your rent reaches in London, measured in minutes.**

Say where you work and what you can pay. Every postcode district in London is
shaded by how much of its rental market your budget actually reaches, and
everywhere you could not get to in time is greyed out. Add a second workplace
for a partner or a second job and the map answers for both.

Live site: _(add the URL once deployed)_

![Commutable showing where a £1,200 budget reaches within 60 minutes of Canary Wharf. Districts within reach are shaded blue by the share of their one bedroom market the budget covers, everywhere beyond the time limit is grey, and districts with no published rent figures are hatched. The panel on the right has SE2 Abbey Wood open: 55 minutes away, 50% of its market in budget, a median of £1,250, and a warning that the figures rest on only 30 recorded tenancies.](docs/screenshot.png)

---

## The question it answers

"Can I afford to live here" is usually answered with a median: the middle rent
in a district. That is the wrong number. Half the market is below the median,
and some of that half is within a budget the median says is out of reach.

So this asks a different question. Given a budget, what **share** of a
district's homes of a given size does it reach? That is a question about the
shape of the market rather than its midpoint, and it is answered by fitting a
distribution to the three figures ONS publishes per district, then reporting
the probability mass below the budget.

The other half is journey time. Distance is useless in London: Stratford is
further from Bank than Camden is, and faster. So every journey is computed by
a routing engine over the real street network and the published timetable.

## How it works

```
  ONS rents          OpenStreetMap     Two timetable feeds    Boundaries
  per district       street network    rail, tube and buses   (postcode districts)
       │                    │                   │                   │
       │                    └─────────┬─────────┘                   │
       │                              ▼                             │
       │                      R5 routing engine                     │
       │                   2,895 × 2,895 journeys                   │
       │                              │                             │
       ▼                              ▼                             ▼
  lognormal fit            median over a departure        750 m grid over
  to the quartiles         window, then over each          Greater London
       │                   district's own cells                     │
       └──────────────────────────────┴─────────────────────────────┘
                                      ▼
                          one 548-byte file per
                          destination, on a CDN
```

Nothing is computed when a visitor asks, because it could not be. The matrix
is 2,895 origins against 2,895 destinations, which is 8.4 million journeys,
and it takes the better part of an hour on a laptop with 10 GB given to the
JVM. So it is computed once, offline, and the published site does a lookup.

That is also why the whole thing deploys as static files. Netlify cannot run a
routing engine, so the answers are committed alongside the code.

### What it costs to load

Measured rather than described, because "small" survives a dependency that
doubles the bundle and nobody notices. Run `node scripts/measure.mjs` after a
build to reproduce these.

| | raw | gzipped |
|---|---|---|
| HTML | 2.0 kB | 0.8 kB |
| CSS | 14.5 kB | 3.9 kB |
| JavaScript | 279.4 kB | 89.0 kB |

The whole application is React, d3-geo and this project's own code. There is
no map library, no tile layer, no charting library and no icon font, which is
what a 274 path SVG buys.

On top of that the first paint pulls the data it draws from:

| | raw | gzipped |
|---|---|---|
| `districts.geojson` | 422.1 kB | 85.9 kB |
| `cells.json` | 76.7 kB | 23.3 kB |
| `gazetteer.json` | 63.5 kB | 17.6 kB |
| `rents.json` | 33.1 kB | 11.7 kB |
| `meta.json` | 15.7 kB | 4.8 kB |
| `boundary.geojson` | 9.1 kB | 2.6 kB |
| total | 620.3 kB | 145.9 kB |

**First load is 239.6 kB over the wire**, application and data together, and
less than that in practice because Netlify serves brotli where gzip is
measured here. The district boundaries are more than half of it, simplified to
25 m, which keeps 99.99% of the total area.

**Every answer after that is 548 bytes.** One unsigned 16-bit integer for each
of the 274 districts, fetched once per workplace, out of 2,895 such files, one
per grid cell. Moving the budget slider or changing the bedroom count fetches
nothing at all: the share in budget is recomputed in the browser from the same
three published quartiles the pipeline fitted, which is why the map redraws
under your finger.

## Three decisions worth defending

**A district's journey time is a weighted median, not a centroid.** SE9 is nine
square kilometres; the walk to a station from one end is not the walk from the
other. Measuring from a single point is a coin toss dressed as a measurement.
Instead a 750 m grid is laid over the city, every cell is routed to every other
cell, and a district's time is the median across its own cells, weighted by how
many homes each one holds. The weighting comes from building footprints in the
OpenStreetMap extract that routing already needs, so a district half covered by
a reservoir is not judged by the half nobody lives in.

**A journey that does not exist is not a fast journey.** Cells with no route
inside the ceiling keep a sentinel that sorts above every real time, so a
district whose better half cannot reach a workplace reads as unreachable rather
than as the time of its worse half. The same principle governs rent: a
suppressed figure is drawn as "no data", never as zero.

**The published median is never replaced.** The site shows exactly the median
and quartiles ONS published. The fitted curve is used only to answer "what
share is under this budget", and where it fits the published quartiles badly
the district is flagged as rough rather than quietly presented like the rest.

**A district code is an address, not a place.** Rents are published against
E11 and SE13, so the codes cannot be dropped, but almost nobody can read a
map labelled only in them. Every district carries a name as well, taken
from the published coverage tables and committed as a reviewed reference
file rather than scraped on each build, because choosing which of E16's
four places belongs on a label is an editorial judgement and judgements
belong under review.

**The map answers two questions, in two hues.** The colour is the share of a
district's market your budget reaches. Switching the key to journey time
repaints the same 274 paths in orange, stepped so the strongest colour is
always the better answer: the most choice in one view, the shortest trip in
the other. Nothing is fetched to do it, because the journey times are already
in the browser, and it is worth having for one reason beyond curiosity. The
budget view hatches the City and the West End, which have almost no rental
housing to publish, and the time view shows that the hole is in the rent
statistics and not in the timetable.

### Reaching it without a mouse

The map was a keyboard trap. Every one of the 274 districts was a tab stop,
so getting from the controls above it to the answer beside it meant 274
presses. It is now a single tab stop, and the arrow keys move from the
district you are on to the nearest one in that direction, picked from a 90
degree cone around the key so that right goes right rather than mostly up.
Enter opens a district, Escape closes it, and a skip link gets past the map
entirely. None of this is visible when it works, which is why it went
unnoticed until somebody tried.

More, including the colour choices and the two bugs that were invisible in the
data and total on screen, in [docs/design-notes.md](docs/design-notes.md).

## Running it

```bash
pip install -r requirements.txt
python scripts/fetch_boundaries.py      # the only inputs that download themselves
# then fetch the other three — see docs/data-sources.md
python scripts/build.py                 # routing takes a few minutes
cd frontend && npm install && npm run dev
```

Routing needs Java 21 or newer and about 8 GB of memory. The site needs Node
22.12 or newer, which is what `netlify.toml` and CI both build on. npm will
refuse to install on anything older rather than warning and leaving you with
a half-installed toolchain. Everything else runs in seconds.

To look at the site before the real data is in place:

```bash
python scripts/build.py --synthetic
```

That fabricates journey times and rents, and marks the output so the site
displays a banner over the map saying every number on it is invented.

## Tests

```bash
pytest                      # 209 tests
cd frontend && npm test     # 174 tests
```

The affordability calculation exists in Python and in TypeScript, because the
pipeline needs it to validate and the browser needs it to answer a new budget
with no server to ask. Two implementations of one formula drift, so the Python
side writes fixtures from its own answers, the TypeScript tests assert they are
reproduced, and CI regenerates the fixtures and fails if they differ from the
committed file.

The fixtures are rounded on the way out, which is not fussiness. The first CI
run failed because the file had been generated on Windows and regenerated on
Linux, and the two disagreed in the last two bits of a double: 1479.0003490991685
against 1479.0003490991671. Shares are now written to 1e-10 and asserted to
1e-9, budgets to a hundredth of a penny and asserted to a penny. Both are
several orders of magnitude tighter than the mistake the fixtures exist to
catch, since swapping Hart's approximation for Abramowitz and Stegun 7.1.26
moves a share by about 1.5e-7, and the measured disagreement between the two
implementations is nothing but that rounding.

The geography tests run against the real London boundaries rather than invented
squares. Both bugs this project has had were about real shapes, and neither
would have shown up against a fixture made of rectangles.

## What it cannot tell you

Rents are published per postcode district, and a district is large. Journey
times come from the timetable, so they know nothing about delays, engineering
work or how full the train is. Walking is capped at 20 minutes at each end;
driving and cycling are not modelled. And rent and journey time are two things
among many that decide where somebody wants to live.

The site says all of this itself, under "How this works", generated from the
same configuration that produced the numbers.

## Data

| What | Source | Licence |
|---|---|---|
| Rents | ONS, Private rental market in London | OGL v3.0 |
| Street network | OpenStreetMap contributors | ODbL 1.0 |
| Timetables, rail and tube | National Rail and TfL, via planarnetwork/gb-transit | Powered by TfL Open Data |
| Timetables, buses | Bus Open Data Service, Department for Transport | OGL v3.0 |
| Borough boundaries | Office for National Statistics | OGL v3.0 |
| Postcode districts | Wikipedia contributors | CC BY-SA 3.0 |
| Postcode district names | Wikipedia contributors | CC BY-SA 3.0 |

## Who built this

Emmanuel Olusolade — [GitHub](https://github.com/eo-datascience)
