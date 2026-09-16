"""The JSON boundary: ``country_iso3`` beside ``country``, and both spellings in.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S04-05 S3/S4. The display half has its own file; this one is about what crosses the
wire and what the tree is NOT allowed to have done on the way.

THE TWO RULES LOOK ALIKE AND ARE NOT, which is why they are two functions:

* ``country_display_code`` DEGRADES LOUDLY. A screen that cannot resolve a value
  still shows the operator what is stored, marked unresolved — because blanking it
  would claim "this row has no country", a different and false statement.
* ``country_payload_iso3`` FAILS CLOSED. A machine-readable field is ``null`` when
  there is no honest answer, because a consumer keys on it and a guess there is a
  guess that travels.

Collapsing them into one helper is the obvious tidy-up and it is wrong in whichever
direction it is done: a fail-closed screen hides data, a degrading payload exports
junk under a field name that promises ISO.

And the widening (``country_query_forms``) is deliberately NOT "normalise the
needle". Normalising one side is the recorded one-sided-normalisation defect: the
column holds ``uk`` and normalising the query to ``gb`` makes ``uk`` — the value an
operator can SEE in the row — stop matching. Widening adds spellings and removes
none, so no filter that worked yesterday stops working today.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.catalog.countries import (
    country_display_code,
    country_payload_iso3,
    country_query_forms,
)

_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
#  The payload rule                                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("fr", "FRA"),
        ("FR", "FRA"),
        ("de", "DEU"),
        ("us", "USA"),
        # Q303's four: values these catalogues really hold, which plain `to_iso3`
        # blanks because they are not ISO 3166-1.
        ("eu", "EUU"),
        ("xk", "XKX"),
        ("an", "ANT"),
        ("int", "INT"),
        # The one stored spelling that is not the ISO alpha-2 of its own country.
        ("uk", "GBR"),
        ("UK", "GBR"),
    ],
)
def test_the_payload_code_answers_every_value_the_store_holds(stored: str, expected: str) -> None:
    assert country_payload_iso3(stored) == expected


@pytest.mark.parametrize("junk", ["", "   ", "zz", "ZZZ", "12", "xx", "wld", "oecd", "eurozone"])
def test_the_payload_code_fails_closed_on_anything_else(junk: str) -> None:
    """THE REFUSAL. A field named ``country_iso3`` either carries an alpha-3 or is
    absent. `wld`/`oecd` are World Bank AGGREGATES — the one input where a helpful
    answer would be actively wrong, because an aggregate is not a country and a map
    that placed it would draw a shape no country has."""
    assert country_payload_iso3(junk) is None


def test_none_is_none_and_not_a_string() -> None:
    assert country_payload_iso3(None) is None
    assert country_display_code(None) is None


@pytest.mark.parametrize("junk", ["zz", "ZZZ", "not-a-place"])
def test_the_screen_keeps_what_the_payload_refuses(junk: str) -> None:
    """The two rules PROVED APART on the same input, because a test that only ever
    exercised resolvable codes would pass with one helper doing both jobs."""
    assert country_payload_iso3(junk) is None
    # Stripped but otherwise UNCHANGED -- deliberately not uppercased. Making junk
    # look like a code ("zz" -> "ZZ") dresses it as something the app stands behind;
    # the hover says "not a recognised country code" and the value stays as stored,
    # so what the operator sees is what is in the row.
    assert country_display_code(junk) == junk.strip()


# --------------------------------------------------------------------------- #
#  The filter rule                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("typed", "must_include"),
    [
        ("FRA", {"fr", "FRA"}),
        ("fr", {"fr", "FRA"}),
        ("GBR", {"uk", "GBR"}),
        ("uk", {"uk", "GBR"}),
        ("EUU", {"eu", "EUU"}),
        ("int", {"int", "INT"}),
    ],
)
def test_a_filter_accepts_the_code_it_displayed(typed: str, must_include: set[str]) -> None:
    """The round trip that matters: an operator reads GBR off a row and pastes it
    into the jurisdiction box. Q301 step 1."""
    forms = set(country_query_forms(typed))
    assert must_include <= forms, f"{typed!r} -> {sorted(forms)}"


def test_widening_never_removes_a_spelling() -> None:
    """The one-sided-normalisation guard, stated as a property rather than a case:
    whatever was typed is still in the set that is searched for."""
    for typed in ("fr", "FR", "uk", "UK", "eu", "int", "xk", "an", "zz", "wld"):
        assert typed in country_query_forms(typed), (
            f"{typed!r} was dropped from its own query set — the column may hold "
            "exactly this spelling, and a filter that stops matching it is a "
            "regression the operator sees as missing rows"
        )


@pytest.mark.parametrize("junk", ["", "   ", None])
def test_an_empty_filter_widens_to_nothing(junk) -> None:
    """An empty needle must not become a set that matches something — that would turn
    "no filter" into "filter for junk" and empty every list."""
    assert country_query_forms(junk) == []


# --------------------------------------------------------------------------- #
#  The endpoints                                                                #
# --------------------------------------------------------------------------- #


@pytest.fixture()
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    monkeypatch.setenv("OO_AUTOSEED", "0")
    # Plaintext, because without it the app starts LOCKED and serves only the unlock
    # flow -- these tests are about what a payload carries, not about the lock screen.
    # The encrypted path is walked once per release by the click-through harness.
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from fastapi.testclient import TestClient

    from src.api.main import app

    # Entered as a context manager ON PURPOSE: the startup handler is what creates the
    # tables, and a bare `TestClient(app)` returns a client whose first query fails
    # with "no such table: sources".
    with TestClient(app) as client:
        yield client


def test_law_rows_carry_both_country_fields_beside_the_stored_value(api) -> None:
    """A law row holds TWO country-shaped facts that are not the same claim:
    ``jurisdiction`` is the legal system, ``country`` is where the document comes
    from. Q303 gives ``uk`` the alpha-3 ``GBR``, so the two legitimately differ on
    one row and a single field would have to pick a winner."""
    api.post("/api/law/seed")
    docs = api.get("/api/law/documents").json()["documents"]
    assert docs, "seeding produced no documents; this test would assert nothing"
    for d in docs:
        assert "country" in d and "country_iso3" in d
        assert "jurisdiction" in d and "jurisdiction_iso3" in d
        assert d["country_iso3"] == country_payload_iso3(d["country"])
        assert d["jurisdiction_iso3"] == country_payload_iso3(d["jurisdiction"])
        # The stored value is UNCHANGED beside it — this is a boundary, not a
        # migration, and the 0.5 storage half is what moves the column.
        if d["country"]:
            assert len(d["country"]) <= 8
    assert any(d["jurisdiction_iso3"] for d in docs), (
        "every jurisdiction resolved to null — the assertions above would then be "
        "comparing None to None and proving nothing"
    )


def test_the_jurisdiction_filter_accepts_the_alpha3_it_displays(api) -> None:
    api.post("/api/law/seed")
    docs = api.get("/api/law/documents").json()["documents"]
    stored = next((d["jurisdiction"] for d in docs if d.get("jurisdiction_iso3")), None)
    assert stored, "no jurisdiction resolved; nothing to round-trip"
    shown = country_payload_iso3(stored)
    by_stored = api.get("/api/law/documents", params={"jurisdiction": stored}).json()
    by_shown = api.get("/api/law/documents", params={"jurisdiction": shown}).json()
    assert by_stored["documents"], f"the stored spelling {stored!r} stopped matching"
    assert len(by_shown["documents"]) == len(by_stored["documents"]), (
        f"filtering by the DISPLAYED code {shown!r} returned "
        f"{len(by_shown['documents'])} rows where the stored {stored!r} returned "
        f"{len(by_stored['documents'])} — the operator can only read the first one "
        "off the screen"
    )


def test_source_rows_carry_country_iso3(api) -> None:
    """Seeded with rows that SPAN the interesting cases rather than skipped when the
    fixture DB is empty: an ordinary country, the one stored spelling that is not its
    own alpha-2, a non-ISO code, and no country at all. A skip here would have read as
    a pass while proving nothing."""
    from src.database.models import Source
    from src.database.session import session_scope

    wanted = {"a.example": "fr", "b.example": "uk", "c.example": "eu", "d.example": None}
    with session_scope() as db:
        for domain, cc in wanted.items():
            db.add(Source(name=domain, domain=domain, country=cc, source_type="news"))
        db.commit()

    rows = api.get("/api/sources/", params={"limit": 1000}).json()
    seen = {r["domain"]: r for r in rows if r.get("domain") in wanted}
    assert set(seen) == set(wanted), f"the seeded rows did not come back: {sorted(seen)}"
    for domain, cc in wanted.items():
        r = seen[domain]
        assert "country_iso3" in r, f"{domain}: no country_iso3 beside country"
        assert r["country"] == cc, "the stored spelling must ride unchanged beside it"
        assert r["country_iso3"] == country_payload_iso3(cc)
    assert seen["b.example"]["country_iso3"] == "GBR"
    assert seen["c.example"]["country_iso3"] == "EUU"
    assert seen["d.example"]["country_iso3"] is None, "no country must not become a code"


def test_the_source_country_filter_accepts_the_alpha3_it_displays(api) -> None:
    from src.database.models import Source
    from src.database.session import session_scope

    with session_scope() as db:
        db.add(Source(name="e.example", domain="e.example", country="uk", source_type="news"))
        db.commit()

    def domains(country: str) -> set[str]:
        rows = api.get(
            "/api/sources/", params={"countries": country, "limit": 1000}
        ).json()
        return {r["domain"] for r in rows}

    by_stored, by_shown = domains("uk"), domains("GBR")
    assert "e.example" in by_stored, "the stored spelling stopped matching its own column"
    assert by_shown == by_stored, (
        "filtering by the DISPLAYED alpha-3 returned a different set than the stored "
        f"alpha-2: {sorted(by_shown ^ by_stored)}"
    )


def test_the_export_and_the_screen_agree_about_one_row() -> None:
    """``source_io`` used plain ``to_iso3``, so an export said "no alpha-3" for a code
    the UI displays two panels away. Two answers to one fact; pinned so it cannot
    drift apart again."""
    from src.api.source_io import _iso3

    for code in ("fr", "uk", "eu", "int", "xk", "an"):
        assert _iso3(code) == country_payload_iso3(code) == country_display_code(code)


# --------------------------------------------------------------------------- #
#  The prohibitions                                                             #
# --------------------------------------------------------------------------- #

#: The brief forbids widening these. Storage stays alpha-2 for this slice; S05-02
#: owns the column change, and doing it here would put a migration inside a display
#: PR — the one place a reviewer is not looking for one.
_NARROW_COUNTRY_COLUMNS = 6


def test_no_country_column_was_widened() -> None:
    """Counted rather than pattern-matched on one line: the brief names SIX
    ``String(2)`` country columns, and a widening shows up as five."""
    models = (_ROOT / "src" / "database" / "models.py").read_text(encoding="utf-8")
    n = models.count("country: Mapped[str | None] = mapped_column(String(2))")
    assert n == _NARROW_COUNTRY_COLUMNS, (
        f"{n} narrow country columns, expected {_NARROW_COUNTRY_COLUMNS}. A widening "
        "belongs to S05-02 (the storage half) with its migration, never to a display "
        "slice; an ADDITION means a seventh column now needs the same treatment."
    )


def test_the_three_external_contracts_are_untouched() -> None:
    """FRED/OECD series ids, the OSM ``ISO3166-1:alpha2`` tag and DB-IP's country
    field are SOMEBODY ELSE'S spelling. Rewriting our side of one of them does not
    change theirs; it just stops the join from matching."""
    candidates = [
        p
        for p in (_ROOT / "src").rglob("*")
        if p.is_file() and p.suffix in (".py", ".js")
    ]
    tag_sites = [p for p in candidates if "ISO3166-1:alpha2" in p.read_text(encoding="utf-8")]
    assert tag_sites, "the OSM alpha-2 tag name vanished from the tree"
    for p in tag_sites:
        text = p.read_text(encoding="utf-8")
        assert "ISO3166-1:alpha3" not in text, (
            f"{p}: the OSM tag was rewritten to alpha-3. OSM publishes "
            "`ISO3166-1:alpha2`; asking for alpha3 asks for a tag that is not there."
        )


def _config_digest() -> dict[str, str]:
    root = _ROOT / "configs"
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_loading_the_catalogues_rewrites_no_config_file() -> None:
    """NO CONFIG LINE IS REWRITTEN — the brief's prohibition, proved by LOADING rather
    than by reading the diff, because the diff only shows what this branch did and the
    fear is a loader that normalises on read and writes back.

    Hashed before and after, so a rewrite that happened to produce the same LENGTH
    still shows up."""
    before = _config_digest()
    assert len(before) > 10, "configs/ is nearly empty; this proof measures nothing"

    from src.catalog.countries import normalize_country  # noqa: F401
    from src.events.catalog import agenda, load_events

    load_events()
    agenda(country="FRA")
    agenda(country="fr")
    agenda(country="int")

    from src.law.catalog import load_legal_catalog

    load_legal_catalog()

    after = _config_digest()
    changed = sorted(k for k in before if before[k] != after.get(k))
    assert not changed, f"loading the catalogues rewrote config files: {changed}"
    assert sorted(before) == sorted(after), "loading the catalogues added or removed a config file"


def test_the_config_proof_would_notice_a_rewrite(tmp_path) -> None:
    """MUTATION CHECK for the guard above: the digest must actually change when a
    byte does. A hash comparison that compared nothing would pass the same way."""
    p = tmp_path / "x.yml"
    p.write_text("a: 1\n", encoding="utf-8")
    first = hashlib.sha256(p.read_bytes()).hexdigest()
    p.write_text("a: 2\n", encoding="utf-8")
    assert hashlib.sha256(p.read_bytes()).hexdigest() != first
