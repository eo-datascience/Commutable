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

        cases.append(
            {
                "label": label,
                "figures": {
                    "median": fitted.median,
                    "lowerQuartile": fitted.lower_quartile,
                    "upperQuartile": fitted.upper_quartile,
                    "sample": fitted.sample,
                    "mu": fitted.mu,
                    "sigma": fitted.sigma,
                    "wellFitted": fitted.well_fitted,
                },
                "shareUnder": [
                    {"budget": round(median * m, 2), "share": fitted.share_under(median * m)}
                    for m in BUDGET_MULTIPLES
                ],
                "budgetForShare": [
                    {"share": s, "budget": fitted.budget_for_share(s)} for s in SHARES
                ],
                "maxFitError": fitted.max_fit_error,
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
