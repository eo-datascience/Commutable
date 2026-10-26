"""Readable names for postcode districts.

A postcode district is an address, not a place. Almost nobody can read a
map labelled E11, SE13, N4 without translating first, and a map that has to
be translated is not answering the question it was opened for. So every
district carries a name beside its code.

The names are a committed reference file rather than a download. Choosing
which of a district's places to name it after is an editorial judgement:
E16 covers Victoria Docks, Canning Town, Silvertown and London City
Airport, and only one of those belongs on a label. A judgement belongs
under review in the repository, not in a scraper that could quietly change
the map's labels on a Tuesday.

Two districts may share a name. That is not a defect to fix: Kingston
upon Thames really is both KT1 and KT2, and the code is always shown
beside the name, so the pair identifies the district even where the name
alone does not.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pipeline.config import REFERENCE, City

logger = logging.getLogger(__name__)


class NamesError(Exception):
    """The names file is named in the config but cannot be used."""


def load_district_names(city: City, directory: Path | None = None) -> dict[str, str]:
    """The name for each district code, or an empty mapping if the city has none.

    A city with no names file configured is fine: the site falls back to
    showing the bare code. A city whose names file is configured and
    missing or malformed is not, because that is a deployment that would
    silently ship a map nobody can read.
    """
    if city.district_names_file is None:
        return {}

    path = (directory or REFERENCE) / city.district_names_file
    if not path.exists():
        raise NamesError(
            f"{path} is missing. It is a committed file, so this usually means "
            f"the repository is incomplete rather than that a download failed."
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        names = payload["names"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise NamesError(f"{path} is not a district names file: {error}") from error

    if not isinstance(names, dict):
        raise NamesError(f"{path} has a 'names' that is not an object")

    cleaned: dict[str, str] = {}
    for code, name in names.items():
        if not isinstance(name, str) or not name.strip():
            raise NamesError(f"{path} has a blank name for {code}")
        cleaned[str(code).strip().upper()] = name.strip()

    return cleaned


def check_coverage(districts: list[str], names: dict[str, str]) -> list[str]:
    """Which districts have no name, logged rather than raised.

    A boundary file that gains a district should not stop a build. It
    should, though, say so: an unnamed district falls back to its bare code
    on screen, and that is the kind of gap that is invisible unless
    somebody happens to scroll to it. The test suite is where this is a
    failure; here it is a warning with the codes named.
    """
    if not names:
        return []

    unnamed = [d for d in districts if d not in names]
    if unnamed:
        logger.warning(
            "%d districts have no name and will show their code: %s",
            len(unnamed),
            ", ".join(unnamed[:12]) + (" ..." if len(unnamed) > 12 else ""),
        )
    return unnamed
