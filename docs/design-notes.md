# Design notes

The decisions that are not obvious from the code, and the bugs worth
remembering.

---

## Why a precomputed matrix

The obvious design asks a journey planner for a route when the visitor asks for
one. It cannot work here. A single answer needs a journey time from all 274
residential postcode districts, and TfL's journey planner allows roughly fifty
requests a minute. One visitor's one question would take five and a half
minutes, and the second visitor would queue behind the first.

So everything is computed in advance by a routing engine running locally over
published timetables, and the published site does nothing at run time but fetch
a small file and colour a map. The arithmetic moves from the visitor's wait to a
batch job that runs when the timetable is refreshed.

### The shape of the published data

| File | Size | When |
|---|---|---|
| `districts.geojson` | ~380 KB | once |
| `cells.json` | ~75 KB | once |
| `rents.json` | ~36 KB | once |
| `gazetteer.json` | ~14 KB | once |
| `boundary.geojson` | ~10 KB | once |
| `meta.json` | ~8 KB | once |
| `times/<cell>.bin` | **548 bytes** | per workplace |

The alternative was one file holding the whole 274 × 2,895 matrix, which is
1.6 MB. That would be one request rather than two, but it would be 1.6 MB
before the visitor sees anything, to use 548 bytes of it. Splitting by
destination means the first paint waits on nothing it does not need, and
changing a budget or a bedroom count fetches nothing at all.

The binary files have no header. The length is the district count and the
endianness is fixed, both stated in `meta.json`, so a header would only be a
second place for them to disagree.

---

## Why 750 metres

The grid cell size is the single most consequential number in the project
because it sets three things at once: the precision of the workplace a visitor
types, the sampling resolution inside a postcode district, and the cost of the
whole thing, which grows with the square.

At 750 m, Greater London is about 2,900 cells, the matrix is 8.4 million
journeys, and a cell is roughly a nine-minute walk across — inside the noise of
a forty-minute commute. At 400 m the matrix is three and a half times larger for
precision the data underneath cannot support, because rents are published per
postcode district and a district is far coarser than any of this.

### Districts smaller than a cell

Fifty-five districts contain only one cell, and twenty-nine contain no cell
centre at all. They are the central ones — EC3V, W1B and their neighbours are a
few streets each, drawn for sorting-office rounds. Those districts borrow the
cell they sit inside.

That is the right answer rather than a patch. A person renting in EC3V has the
City's journey times because they are standing in the City. Omitting the
district instead would leave holes in the middle of the map at exactly the
postcodes people recognise.

---

## Why a lognormal, fitted to three numbers

ONS publishes, per district and bedroom count, a count and five figures: mean,
median, lower quartile, upper quartile. A map built on the median alone answers
the wrong question, because half the market is below the median and some of
that half is inside a budget the median rules out.

Rents cannot be negative, cluster around a typical value and have a long right
tail. That is the standard shape for prices, and the lognormal is the standard
two-parameter family for it. Two parameters is also all three quantiles can
honestly support.

In log space the three published quantiles should lie on a straight line
against the standard normal quantile, so the fit is ordinary least squares
through three points. Because the three z-values are symmetric about zero and
sum to zero, the parameters separate and there is nothing to iterate:

```
mu    = the mean of the three log quantiles
sigma = (log UQ − log LQ) / (2 × 0.6744897501960817)
```

No optimiser to fail to converge, no starting point, no hidden tolerance.

**The fit is checked against the data it was fitted to.** The largest relative
error across the three published quantiles is recorded and published, and
districts above 5% are flagged on the site as rough rather than presented with
the same confidence as the rest.

**The published median is never replaced.** The site shows the ONS median and
quartiles verbatim, so a visitor who checks against the release sees the same
numbers. The fitted curve answers only "what share is under this budget".

### The spread floor

Three identical quartiles give a sigma of about 5 × 10⁻¹⁶, not zero. It is
positive, it passes any test for zero, and it turns the share under a budget
into a step function: a pound under the median reaches none of the market and a
pound over reaches all of it. The guard is therefore a floor of 0.01 — an
interquartile range of about 1.4% of the median — not a comparison with zero.

---

## Colour

Two variables have to reach the eye at once, and they are encoded differently on
purpose.

The commute limit is a **gate**, not a quantity. A district beyond it is not a
worse answer, it is not an answer, so it is drawn in a flat recessive grey that
is plainly not part of the data. Shading it dark blue would invite the eye to
compare it with the places that qualify.

Affordability is the quantity, so it gets the colour: one hue, five discrete
bins, light to dark. Discrete rather than continuous because a legend with five
labelled steps can be read exactly and a gradient can only be read
approximately, and the figure underneath is an estimate from three published
quartiles rather than a measurement that deserves a smooth scale.

Every value was chosen by running a palette validator rather than by eye:

- **Light mode** uses blue ramp steps 300–700. The paler steps were tried first
  and rejected: against this page's surface the lightest sat at 1.4 : 1, so a
  district with nothing in budget faded into the background and could not be
  told apart from one that was never measured.
- **Dark mode** uses steps 150–550, selected for the dark surface rather than
  flipped from the light ramp. On a dark page the eye reads bright as *more*,
  which is the opposite ordering.
- The workplace marker is `#d2541f` on light and `#eb6834` on dark, both above
  3 : 1. It is the only warm colour anywhere and it appears once or twice.

**The two grey states are separated by texture, not colour.** "Too far" and "no
figures published" are both recessive greys, and as colours alone they fail a
normal-vision separation check at ΔE 6.4. So "no data" carries a diagonal hatch.
The texture is doing real work rather than decorating.

---

## Two bugs that were invisible in the data and total on screen

**Ring winding.** The first map rendered as a single flat grey rectangle. The
published GeoJSON was correct and every coordinate was right. d3-geo treats a
polygon as a region on a sphere, where a ring divides the surface into two parts
and the winding order says which one is inside — and its convention is the
*opposite* of RFC 7946. A counter-clockwise exterior ring is therefore not drawn
backwards; it is drawn as the entire earth minus that district. All 274
districts were wound one way and the city outline, which came from unioning the
boroughs, happened to be wound the other, so the page showed a correct outline
over a sheet of grey.

The fix keeps the published files standards-compliant — other tools will read
them — and turns the rings round once in the browser, in `frontend/src/lib/geo.ts`.
A pipeline test now checks the winding of every published polygon with a
shoelace calculation written out longhand, rather than with the library that
produced the file.

**A grid with three rows and four children.** `.shell` was a CSS grid with
`grid-template-rows: auto auto minmax(0, 1fr)`. That was right until a fourth
child appeared — the banner a synthetic build puts at the top. The stage then
landed on an implicit row, the controls inherited the flexible one and collapsed
to 32 px, and the input fields spilled over the map. It is a flex column now,
which takes however many children it is given.

Both were found by taking a screenshot and looking at it.

---

## What is deliberately not here

**Accounts.** The site has no server, so accounts would mean a database, session
handling and a duty of care over a table of where strangers work. The whole
question lives in the URL instead, which means sharing an answer is copying the
address bar, and there is nothing to sign up for, nothing to lose and nothing
held about anybody. If saved searches ever become worth having, the URL is
already the serialisation format and browser storage is the obvious next step.

**A basemap.** The city is drawn from its own 274 district polygons and nothing
else: no tiles, no API key, no request to anybody else's server, no attribution
bar. That also makes a tile library the wrong tool — MapLibre is around 800 KB
compressed and exists to stitch tiles under an interactive camera. With no tiles
to stitch, 274 SVG paths draw in a frame, every shape is a DOM node that hovers
and focuses without hit-testing of our own, and the whole thing themes with the
rest of the page in CSS. The cost is writing pan and zoom, which is one
transform and about forty lines.

**A second city.** Everything city-specific is gathered in one dataclass in
`pipeline/config.py`. Adding Manchester should mean adding one of those and four
input files, not editing the pipeline. That is a claim the code is arranged to
support, not one that has been tested.

**The Thames.** A river would make the map more recognisable. The OSM extract
has one, and it could be drawn as a cut through the districts in the surface
colour. It is not here because it could not be verified end to end in the
environment this was written in, and shipping a map feature that has never been
looked at is worse than shipping without it.
