"""The alpha-3 DISPLAY layer: ruling Q301 = c step 1, Q302's note, Q303, Q306.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE PARITY TESTS ARE THE POINT OF THIS FILE. The alpha-3 and ISO 639 tables exist
TWICE -- once in Python and once in `app-core.js` -- because the browser cannot read
a `.py` and the UI must work with no request. The ledger records what a comment
saying "kept in sync manually" is worth: a mirrored copy fails in the
safe-looking direction, and the sentence claiming it is maintained is the one to
distrust. So the copies are compared TEXT to TEXT here, and a drift fails naming
the pairs that differ.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.catalog.countries import (
    _SPECIAL_ALPHA3_TO_CODE,
    ISO3_TO_ISO2,
    NON_ISO_ALPHA3,
    SPECIAL_ALPHA3,
    country_display,
    country_display_code,
    normalize_country,
    to_iso2,
    to_iso3,
)
from src.catalog.languages import ISO1_TO_ISO3, language_display_code, language_storage_code

_ROOT = Path(__file__).resolve().parent.parent
_CORE = _ROOT / "src" / "static" / "app-core.js"


def _js_table(name: str) -> str:
    js = _CORE.read_text(encoding="utf-8")
    m = re.search(r"const " + name + r" = `\n(.*?)\n    `;", js, re.S)
    assert m, f"{name} is not in app-core.js in the shape this guard reads"
    return " ".join(m.group(1).split())


def _py_table(path: Path, name: str) -> str:
    m = re.search(name + r' = """(.*?)"""', path.read_text(encoding="utf-8"), re.S)
    assert m, f"{name} is not in {path.name} in the shape this guard reads"
    return " ".join(m.group(1).split())


# ---- the two copies agree ------------------------------------------------- #

def test_the_alpha3_table_is_identical_on_both_sides() -> None:
    py = _py_table(_ROOT / "src" / "catalog" / "countries.py", "_ISO3_TO_2_TEXT")
    js = _js_table("_OO_ISO3_TO_2_TEXT")
    assert py, "the Python alpha-3 table parsed empty -- this guard would pass for free"
    assert len(py.split()) == 216, f"expected 216 pairs, parsed {len(py.split())}"
    if py != js:
        a, b = set(py.split()), set(js.split())
        raise AssertionError(
            "the alpha-3 table has drifted between countries.py and app-core.js. "
            f"only in Python: {sorted(a - b)} · only in JS: {sorted(b - a)}"
        )


def test_the_language_table_is_identical_on_both_sides() -> None:
    py = _py_table(_ROOT / "src" / "catalog" / "languages.py", "_ISO1_TO_3_TEXT")
    js = _js_table("_OO_ISO1_TO_3_TEXT")
    assert py, "the Python 639-1 table parsed empty -- this guard would pass for free"
    assert len(py.split()) == 183, f"expected 183 pairs, parsed {len(py.split())}"
    if py != js:
        a, b = set(py.split()), set(js.split())
        raise AssertionError(
            "the ISO 639 table has drifted between languages.py and app-core.js. "
            f"only in Python: {sorted(a - b)} · only in JS: {sorted(b - a)}"
        )


def test_the_parity_guard_would_notice_a_single_changed_pair() -> None:
    """MUTATION-CHECK, in the file. A comparison of two empty strings is equal, so
    the guard above needs to be shown capable of failing."""
    py = _py_table(_ROOT / "src" / "catalog" / "countries.py", "_ISO3_TO_2_TEXT")
    drifted = py.replace("fra:fr", "fra:zz", 1)
    assert drifted != py, "the mutation did not apply -- the run below means nothing"
    assert set(drifted.split()) != set(py.split())


# ---- Q302: the code is what is displayed ---------------------------------- #

@pytest.mark.parametrize(
    "stored,code",
    [("fr", "FRA"), ("FR", "FRA"), ("de", "DEU"), ("us", "USA"), ("gb", "GBR"),
     ("uk", "GBR"), ("United States", "USA"), ("united-states", "USA"), ("FRA", "FRA")],
)
def test_every_form_a_caller_holds_renders_the_same_alpha3(stored: str, code: str) -> None:
    assert country_display_code(stored) == code
    assert country_display(stored)["code"] == code


def test_the_name_is_available_for_the_hover_and_is_not_the_code() -> None:
    d = country_display("fr")
    assert d["code"] == "FRA"
    assert d["name"] == "France", "the hover needs the NAME beside the code (Q302)"
    assert d["kind"] == "iso"
    assert d["note"] is None


# ---- Q303: the four non-ISO codes, each disclosed ------------------------- #

@pytest.mark.parametrize(
    "stored,code", [("eu", "EUU"), ("int", "INT"), ("xk", "XKX"), ("an", "ANT")]
)
def test_the_non_iso_codes_render_and_disclose(stored: str, code: str) -> None:
    d = country_display(stored)
    assert d["code"] == code
    assert d["kind"] == "non-iso", f"{stored} must be disclosed, not passed off as ISO"
    assert d["note"], f"{stored} must carry a REASON, not just a flag"
    assert code in NON_ISO_ALPHA3


def test_an_ordinary_country_is_not_labelled_non_iso() -> None:
    """The mirror. Without it the disclosure could be printed on everything and every
    assertion above would still pass -- an over-eager disclosure is as dishonest as a
    missing one."""
    for stored in ("fr", "de", "us", "gb", "jp"):
        d = country_display(stored)
        assert d["kind"] == "iso"
        assert d["note"] is None


def test_the_two_special_tables_are_exact_inverses() -> None:
    """One table would be tidier; two that a test proves cannot disagree is what
    actually holds when somebody edits one of them."""
    assert {v: k for k, v in SPECIAL_ALPHA3.items()} == _SPECIAL_ALPHA3_TO_CODE
    assert set(SPECIAL_ALPHA3.values()) == set(NON_ISO_ALPHA3)


# ---- the negative space --------------------------------------------------- #

@pytest.mark.parametrize("junk", ["HIC", "WLD", "XD", "Z4", "1W", "ZZZ", "floop"])
def test_an_aggregate_or_a_junk_value_never_becomes_a_country(junk: str) -> None:
    d = country_display(junk)
    assert d["kind"] == "unresolved", f"{junk} must not read as a country"
    assert d["note"] is None, "unreadable is not the same fact as disclosed-non-ISO"
    assert d["code"] == junk, "an unreadable value renders AS ITSELF, never blanked"


def test_absent_and_unreadable_are_different_answers() -> None:
    for empty in ("", "   ", None):
        d = country_display(empty)
        assert d["code"] is None and d["name"] is None
    d = country_display("WLD")
    assert d["code"] == "WLD" and d["name"] == "WLD"


def test_none_stays_none_through_every_entry_point() -> None:
    assert country_display_code(None) is None
    assert country_display_code("") is None
    assert normalize_country(None) is None
    assert language_display_code(None) is None
    assert language_storage_code(None) is None


# ---- the boundary: parameters accept both forms (Q301 step 1) ------------- #

@pytest.mark.parametrize(
    "given,expected",
    [("FRA", "fr"), ("fra", "fr"), ("DEU", "de"), ("GBR", "gb"), ("USA", "us"),
     ("EUU", "eu"), ("INT", "int"), ("XKX", "xk"), ("ANT", "an"),
     ("fr", "fr"), ("uk", "gb"), ("United States", "us")],
)
def test_normalize_country_accepts_both_forms(given: str, expected: str) -> None:
    assert normalize_country(given) == expected


@pytest.mark.parametrize("junk", ["HIC", "WLD", "XD", "Z4", "ZZZ", "abcd", "floop", ""])
def test_normalize_country_is_still_fail_closed(junk: str) -> None:
    """The widening must not widen what is ACCEPTED, only the spellings of what
    already was. An aggregate becoming a country is the inversion the guard exists
    to prevent."""
    assert normalize_country(junk) is None


def test_the_statistics_guard_is_untouched() -> None:
    """`to_iso2`/`to_iso3` answer "is this a COUNTRY?" and must stay closed against
    every aggregate -- including `eu`, which `normalize_country` deliberately accepts
    because in a corpus row it is EUR-Lex's country and in a `ref_area` it is the
    World Bank's aggregate. The two disagreeing is the design."""
    for agg in ("EUU", "WLD", "HIC", "XD", "eu"):
        assert to_iso2(agg) is None
        assert to_iso3(agg) is None
    assert normalize_country("eu") == "eu"


def test_an_alpha3_never_changes_an_answer_the_name_index_already_gave() -> None:
    """Measured, not assumed, and in both directions: the alpha-3 branch sits AFTER
    the name index so a name always wins. Three 3-letter keys exist there today and
    only `usa` is also an alpha-3 -- so the order is currently unobservable, and it
    is written down because the name index is hand-edited."""
    for alias, expected in (("drc", "cd"), ("uae", "ae"), ("usa", "us")):
        assert normalize_country(alias) == expected
    disagreements = [
        (a3, normalize_country(a3), a2)
        for a3, a2 in ISO3_TO_ISO2.items()
        if normalize_country(a3) not in (a2, None)
    ]
    assert not disagreements, f"an alpha-3 resolves to the wrong country: {disagreements}"


# ---- Q306: the language display step -------------------------------------- #

@pytest.mark.parametrize(
    "stored,shown",
    [("fr", "fra"), ("de", "deu"), ("zh", "zho"), ("en", "eng"),
     ("en-US", "eng"), ("pt_BR", "por"), ("EN", "eng"), ("fra", "fra")],
)
def test_language_codes_display_as_639_2_or_3(stored: str, shown: str) -> None:
    assert language_display_code(stored) == shown


def test_the_language_table_is_terminological_not_bibliographic() -> None:
    """The ruling's own worked example is `fra`, which is the T code (`fre` is B).
    Asserted for the three UI locales where the two sets disagree, because that is
    where a silent flip would be visible to a user."""
    assert ISO1_TO_ISO3["fr"] == "fra" and ISO1_TO_ISO3["fr"] != "fre"
    assert ISO1_TO_ISO3["de"] == "deu" and ISO1_TO_ISO3["de"] != "ger"
    assert ISO1_TO_ISO3["zh"] == "zho" and ISO1_TO_ISO3["zh"] != "chi"


def test_a_639_3_code_with_no_639_1_refuses_rather_than_inventing_one() -> None:
    """`pcm`, `yue` and `tet` are real values in the shipped catalogues. There is no
    two-letter answer and guessing one would assert a language the standard does not
    name."""
    for only3 in ("pcm", "yue", "tet"):
        assert language_display_code(only3) == only3
        assert language_storage_code(only3) is None


def test_every_language_in_the_shipped_catalogues_resolves() -> None:
    """The table is sized to the real population, not to the twelve UI locales --
    measured against the catalogues rather than asserted from the standard."""
    codes: set[str] = set()
    for path in (_ROOT / "configs").rglob("*.y*ml"):
        for m in re.finditer(r"^\s*language:\s*['\"]?([A-Za-z-]+)", path.read_text(
            encoding="utf-8", errors="replace"), re.M):
            codes.add(m.group(1).strip().lower())
    assert len(codes) > 50, f"only {len(codes)} language codes found -- the sweep broke"
    # The catalogues carry three codes that are ALREADY ISO 639-3 and have no 639-1
    # equivalent at all. Named here rather than hidden behind a wider predicate: they
    # are the population this rule cannot convert, and stating them is how a fourth
    # one arriving becomes a decision rather than a silent pass-through.
    known_639_3_only = {"pcm", "tet", "yue"}
    unresolved = sorted(
        c for c in codes
        if language_display_code(c) == c
        and c not in ISO1_TO_ISO3.values()
        and c not in known_639_3_only
    )
    assert unresolved == [], f"catalogue languages with no 639-2/3 code: {unresolved}"
    # And the three are real rather than a stale exemption: each must still be in the
    # catalogues, or this set is quietly excusing nothing.
    assert known_639_3_only <= codes, (
        "an exempted language code has left the catalogues; drop it from the set "
        f"rather than leaving a permanent excuse: {sorted(known_639_3_only - codes)}"
    )


def test_the_browser_helper_is_driven_for_real_in_node() -> None:
    """The half no source grep can do.

    ``tests/country_display_node_test.js`` EXECUTES the shipped helpers and reads the
    rendered HTML back, because a source guard cannot tell "the code is visible and
    the name is in the title" from its exact inverse -- ``ooCountryCell`` mentions
    both whichever way round it puts them. Two real defects in this slice's own code
    were found by that run and by nothing else: ``ISO3_TO_ISO2`` is keyed lowercase,
    so the first cut filed every real country as ``unresolved``; and ``ooCountryFlag``
    dropped ``agFlag``'s empty guard, which would have drawn a globe -- "an entity
    with no flag" -- on every row that simply has no country.
    """
    import subprocess

    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "country_display_node_test.js")],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "country_display_node_test.js: OK" in proc.stdout, proc.stdout
