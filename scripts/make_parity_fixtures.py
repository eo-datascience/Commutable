"""Write fixtures from the Python implementation so the browser's copy can be
checked against it.

The affordability calculation exists twice: once in pipeline/rent.py, which
fits and validates it, and once in the browser, which has to answer a new
budget with no server to ask. Two implementations of one formula drift, and
the drift would be invisible: both would return a plausible percentage and
only one would be right.

So the Python side writes its own answers here, the TypeScript tests assert
they are reproduced, and CI regenerates this file and fails if it differs
from the committed one. Neither side can move without the other.

    python scripts/make_parity_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.rent import Z_QUARTILE, fit_lognormal  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "frontend" / "src" / "lib" / "parity.json"

# Chosen to span the range the site will actually meet, plus the edges.
# A median under a thousand and over six, spreads from tight to very wide.
CASES: tuple[tuple[str, float, float], ...] = (
    # label, median, sigma
    ("cheap and tight", 950.0, 0.12),
    ("typical outer", 1400.0, 0.18),
    ("typical inner", 1850.0, 0.24),
    ("expensive", 2900.0, 0.30),
    ("very expensive", 4800.0, 0.22),
    ("very wide spread", 1700.0, 0.45),
    ("narrow, at the floor", 1500.0, 0.011),
)

# The budgets each case is probed at, as multiples of its median, so the
# probes land on the interesting part of every curve rather than only on
# the cheap ones.
BUDGET_MULTIPLES = (0.5, 0.7, 0.85, 0.95, 1.0, 1.05, 1.2, 1.5, 2.0, 3.0)

SHARES = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)

# How many decimal places survive into the file.
#
# The last two bits of a double are not portable. CPython on Windows and on
# Linux disagree about the final digits of exp() and erf(), and CI compares
# this file byte for byte against a freshly generated one. Written on a
# Windows laptop and regenerated on a Linux runner, it differed in places
# like 1479.0003490991685 against 1479.0003490991671: the same number to
# thirteen significant figures, and a failed build.
#
# So every figure is rounded on the way out. The gap matters in both
# directions. Too coarse and the fixture stops being a real check; too fine
# and a value can sit near a rounding boundary and fall either side of it
# on different machines, which is the same failure again with extra steps.
#
# Budgets are asserted to a penny and rounded to a hundredth of one, a
# hundred times tighter than the assertion and a hundred million times
# coarser than the noise. Shares are rounded to 1e-10, against erf noise
# around 1e-16, and asserted to 1e-9. That tolerance is three orders of
# magnitude looser than the old 1e-12 and still a hundred times tighter
# than any real disagreement between two implementations of this formula:
# swapping Hart's approximation for Abramowitz and Stegun 7.1.26, the
# mistake this fixture exists to catch, moves a share by about 1.5e-7.
#
# Z_QUARTILE is deliberately not rounded. It is a literal constant in both
# implementations rather than a computed value, and the TypeScript side
# asserts it is exactly equal.
MONEY_DP = 4
UNIT_DP = 10


def main() -> int:
    cases = []

    for label, median, sigma in CASES:
        mu = math.log(median)
        lq = round(math.exp(mu - sigma * Z_QUARTILE), 2)
        uq = round(math.exp(mu + sigma * Z_QUARTILE), 2)

        fitted = fit_lognormal(
            district="FIXTURE",
            bedrooms="1",
            sample=500,
            median=median,
            lower_quartile=lq,
            upper_quartile=uq,
        )

        # Round the fit before using it, not after.
        #
        # mu and sigma are not expectations, they are the inputs the browser
        # reads back, so the expectations below have to be computed from the
        # values that actually reach the file. Rounding afterwards broke the
        # narrowest case: at a sigma of 0.011 the curve is so steep that a
        # change of 1e-10 in mu moves the share by nearly 2e-9, and the
        # fixture then asked the browser to reproduce a figure derived from
        # a mu it had never seen.
        fitted = replace(
            fitted,
            mu=round(fitted.mu, UNIT_DP),
            sigma=round(fitted.sigma, UNIT_DP),
        )

        cases.append(
            {
                "label": label,
                "figures": {
                    "median": round(fitted.median, MONEY_DP),
                    "lowerQuartile": round(fitted.lower_quartile, MONEY_DP),
                    "upperQuartile": round(fitted.upper_quartile, MONEY_DP),
                    "sample": fitted.sample,
                    # Already rounded above, so these are the same two
                    # numbers every expectation below was computed from.
                    "mu": fitted.mu,
                    "sigma": fitted.sigma,
                    "wellFitted": fitted.well_fitted,
                },
                "shareUnder": [
                    {
                        "budget": round(median * m, 2),
                        "share": round(fitted.share_under(median * m), UNIT_DP),
                    }
                    for m in BUDGET_MULTIPLES
                ],
                "budgetForShare": [
                    {"share": s, "budget": round(fitted.budget_for_share(s), MONEY_DP)}
                    for s in SHARES
                ],
                "maxFitError": round(fitted.max_fit_error, UNIT_DP),
            }
        )

    payload = {
        "generated_by": "scripts/make_parity_fixtures.py",
        "note": (
            "Written by the Python implementation in pipeline/rent.py. The TypeScript "
            "tests in frontend/src/lib/affordability.test.ts assert the browser "
            "reproduces these. Regenerate with python scripts/make_parity_fixtures.py; "
            "CI regenerates and fails if the result differs from the committed file."
        ),
        "z_quartile": Z_QUARTILE,
        "cases": cases,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(cases)} cases to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
