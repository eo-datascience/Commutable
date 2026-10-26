"""The district names, and the gaps they must not have."""

from __future__ import annotations

import json

import pytest

from pipeline.config import LONDON, REFERENCE
from pipeline.names import NamesError, check_coverage, load_district_names


@pytest.fixture(scope="module")
def names() -> dict[str, str]:
    return load_district_names(LONDON)


# ---------------------------------------------------------------------------
# The shipped file
# ---------------------------------------------------------------------------


def test_every_london_district_has_a_name(names: dict[str, str]) -> None:
    """The point of the file.

    A district with no name falls back to its bare code on screen, which is
    exactly the state this file exists to end. The build only warns about
    it, because a new boundary should not stop a deploy, so this is where
    it is a failure.
    """
    # Checked against the district list the site actually ships rather than
    # by rebuilding the geography, which needs the raw inputs and several
    # minutes. meta.json is the published answer to "which districts exist",
    # so it is the right list to hold the names against.
    published = REFERENCE.parent.parent / "frontend" / "public" / "data" / "meta.json"
    if not published.exists():
        pytest.skip("no published data yet; run scripts/build.py")

    districts = json.loads(published.read_text(encoding="utf-8"))["districts"]

    assert check_coverage(districts, names) == []


def test_names_file_records_where_it_came_from() -> None:
    """Provenance is part of the data, not a comment in a commit message.

    The names are editorial choices drawn from a licensed source. A
    reference file that does not say which source, under which licence, is
    one nobody can check or re-derive later.
    """
    payload = json.loads(
        (REFERENCE / "london_district_names.json").read_text(encoding="utf-8")
    )
    source = payload["_source"]

    for field in ("what", "why", "from", "licence", "rule", "retrieved"):
        assert source.get(field), f"the names file does not say {field!r}"


def test_no_name_is_blank_or_padded(names: dict[str, str]) -> None:
    for code, name in names.items():
        assert name == name.strip()
        assert name, f"{code} has a blank name"


def test_no_name_is_just_the_code_again(names: dict[str, str]) -> None:
    """A name equal to the code is a gap wearing a name's clothes."""
    for code, name in names.items():
        assert name.upper() != code, f"{code} is named after itself"


def test_codes_are_normalised(names: dict[str, str]) -> None:
    for code in names:
        assert code == code.strip().upper()


def test_two_districts_may_share_a_name(names: dict[str, str]) -> None:
    """Not a defect. Kingston upon Thames is genuinely both KT1 and KT2.

    This is asserted rather than left implicit because the obvious
    'tidy-up' is to make every name unique, which would mean inventing
    distinctions the places themselves do not have.
    """
    assert names["KT1"] == names["KT2"]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_a_city_with_no_names_file_is_fine(tmp_path) -> None:  # noqa: ANN001
    from dataclasses import replace  # noqa: PLC0415

    nameless = replace(LONDON, district_names_file=None)

    assert load_district_names(nameless, tmp_path) == {}


def test_a_configured_file_that_is_missing_is_not(tmp_path) -> None:  # noqa: ANN001
    with pytest.raises(NamesError, match="missing"):
        load_district_names(LONDON, tmp_path)


def test_a_blank_name_is_rejected(tmp_path) -> None:  # noqa: ANN001
    # Quietly dropping it would publish a map with one district showing a
    # code among 273 showing names, which reads as a rendering bug.
    path = tmp_path / LONDON.district_names_file
    path.write_text(json.dumps({"names": {"E1": "Whitechapel", "E2": "   "}}))

    with pytest.raises(NamesError, match="blank name for E2"):
        load_district_names(LONDON, tmp_path)


def test_a_file_that_is_not_a_names_file_is_rejected(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / LONDON.district_names_file
    path.write_text(json.dumps({"districts": ["E1"]}))

    with pytest.raises(NamesError, match="not a district names file"):
        load_district_names(LONDON, tmp_path)


def test_check_coverage_names_what_is_missing() -> None:
    missing = check_coverage(["E1", "E2", "ZZ9"], {"E1": "Whitechapel", "E2": "Bethnal Green"})

    assert missing == ["ZZ9"]


def test_check_coverage_says_nothing_when_there_are_no_names() -> None:
    """A city that ships no names has no gaps, it has no names."""
    assert check_coverage(["E1", "E2"], {}) == []
