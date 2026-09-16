"""Exports carry the country in BOTH forms for one release (Q313 = a, gate row K).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE SHAPE, and why it is not symmetrical. ``country`` is the STORED form and is what an
import reads; ``country_iso3`` is DERIVED from it on the way out. Two independently
editable columns for one fact would let a spreadsheet arrive saying ``fr`` in one and
``DEU`` in the other, and picking a winner silently is how an operator's edit gets
discarded -- so a disagreement is refused BY NAME instead.

MEASURED SCOPE, so nobody later reads this file as covering more than it does. Two
surfaces in the tree emit a source's country: the sources CSV (``/api/catalog/export.csv``)
and the sources JSON listing (``/api/catalog/sources``) -- Q313 = a names "CSV/JSON
exports" and both are here. The YAML/JSON export at ``/api/sources/export`` carries no
country at all, neither branch of ``/api/articles/export`` emits one, and the
qualification overlay does not either. Diagnostics payloads are explicitly OUT: Q313
switches those "in the same release as storage", which is 0.5.
``test_every_export_that_carries_country_carries_both_forms`` pins the PROPERTY rather
than that list, so the next export to grow a country column cannot ship with only the
old form.
"""

from __future__ import annotations

import csv
import io

import pytest

from src.catalog.csv_io import (
    EXPORT_COLUMNS,
    IMPORT_COLUMNS,
    parse_sources_csv,
    template_csv,
    write_csv,
)


def _header(text: str) -> list[str]:
    return next(csv.reader(io.StringIO(text)))


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


# --------------------------------------------------------------------------- #
#  The export carries both
# --------------------------------------------------------------------------- #
def test_the_sources_csv_carries_both_country_columns():
    text = write_csv([{"name": "X", "domain": "x.example", "country": "fr",
                       "country_iso3": "FRA"}])

    header = _header(text)
    assert "country" in header and "country_iso3" in header
    row = _rows(text)[0]
    assert (row["country"], row["country_iso3"]) == ("fr", "FRA")


def test_the_export_endpoint_derives_the_alpha3_column(client_sources):
    """Derived from the stored value at the row builder, so the two can never disagree
    in an export -- there is one fact and one place it is read from."""
    text = client_sources
    row = next(r for r in _rows(text) if r["domain"] == "iso3.example")
    assert (row["country"], row["country_iso3"]) == ("fr", "FRA")


@pytest.fixture()
def client_sources(tmp_path):
    from src.api.source_io import _source_to_row
    from src.database.models import Source

    src = Source(name="Z", domain="iso3.example", country="fr")
    return write_csv([_source_to_row(src)])


def test_an_unconvertible_country_yields_NO_alpha3_rather_than_a_guess():
    """``to_iso3`` fails closed. An aggregate or a junk code has no alpha-3, and an
    empty cell is the honest answer -- inventing one would be the fabrication this
    project refuses everywhere else."""
    from src.api.source_io import _source_to_row
    from src.database.models import Source

    text = write_csv([
        _source_to_row(Source(name="A", domain="a.example", country="WLD")),
        _source_to_row(Source(name="B", domain="b.example", country=None)),
    ])

    got = {r["domain"]: r["country_iso3"] for r in _rows(text)}
    assert got == {"a.example": "", "b.example": ""}


# --------------------------------------------------------------------------- #
#  The JSON half of "CSV/JSON exports"
# --------------------------------------------------------------------------- #
def _listing_client(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.main import app
    from src.database.models import Base, Source
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'j.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add_all([
            Source(name="Alpha", domain="alpha.test", country="fr"),
            Source(name="Bulk", domain="bulk.test", country="WLD"),
            Source(name="Nowhere", domain="nowhere.test", country=None),
        ])
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app, TestClient(app)


def test_the_sources_LISTING_carries_both_forms(tmp_path):
    """The JSON half of Q313 = a. The listing is the payload that carries a source's
    country out of the app in JSON, and S04-05 reads it -- so it gains the derived form
    in the SAME release as the CSV, from the same converter."""
    app, client = _listing_client(tmp_path)
    try:
        with client:
            rows = {s["domain"]: s for s in client.get("/api/catalog/sources").json()["sources"]}
    finally:
        app.dependency_overrides.clear()

    assert (rows["alpha.test"]["country"], rows["alpha.test"]["country_iso3"]) == ("fr", "FRA")
    assert rows["bulk.test"]["country_iso3"] is None, "an aggregate was given an alpha-3"
    assert rows["nowhere.test"]["country_iso3"] is None


# --------------------------------------------------------------------------- #
#  The import contract
# --------------------------------------------------------------------------- #
def test_the_template_documents_only_what_an_import_READS():
    """Offering an operator a blank ``country_iso3`` column to fill in would be
    offering them a way to be refused."""
    assert "country_iso3" not in _header(template_csv())
    assert "country_iso3" not in IMPORT_COLUMNS
    assert "country_iso3" in EXPORT_COLUMNS


def test_an_export_round_trips_through_the_import():
    """The property that matters for a one-release dual column: an operator exports,
    changes nothing, re-imports, and their data is unchanged."""
    text = write_csv([{"name": "X", "domain": "x.example", "country": "fr",
                       "country_iso3": "FRA"}])

    rows, errors = parse_sources_csv(text)

    assert errors == []
    assert rows == [{"name": "X", "domain": "x.example", "country": "fr"}]


def test_the_two_columns_disagreeing_is_refused_BY_NAME():
    """Neither silently wins. The refusal names both values, because the operator has
    to know which of their two edits the file is asking them to reconcile."""
    rows, errors = parse_sources_csv(
        "name,domain,country,country_iso3\nX,x.example,fr,DEU\n"
    )

    assert rows == []
    assert len(errors) == 1
    assert "fr" in errors[0] and "DEU" in errors[0] and "disagree" in errors[0]


def test_the_same_country_in_two_forms_is_AGREEMENT_not_a_conflict():
    """The negative-space twin. A comparison that normalised only one side would refuse
    every export it just produced -- the recorded "normalise on both sides" rule."""
    rows, errors = parse_sources_csv(
        "name,domain,country,country_iso3\nX,x.example,fr,FRA\n"
    )

    assert errors == []
    assert rows[0]["country"] == "fr"


def test_only_the_alpha3_column_is_honoured_when_it_is_the_only_one_given():
    """Through ``to_iso2``, not ``normalize_country``: measured,
    ``normalize_country("DEU")`` is None, because it resolves codes, NAMES and slugs and
    alpha-3 is none of the three. Getting this wrong would silently drop the operator's
    only statement of the country."""
    rows, errors = parse_sources_csv("name,domain,country_iso3\nX,x.example,DEU\n")

    assert errors == []
    assert rows[0]["country"] == "de"


def test_an_UNREADABLE_country_falls_back_to_the_alpha3_column():
    """The branch an ``elif`` would have swallowed. ``country`` is dropped when it does
    not resolve (pre-existing behaviour, unchanged); if the fall-back were keyed on
    "was a country column present" rather than on "is there a country NOW", this row
    would end up with no country at all although the operator stated one in a form the
    app reads perfectly."""
    rows, errors = parse_sources_csv(
        "name,domain,country,country_iso3\nX,x.example,Freedonia,DEU\n"
    )

    assert errors == []
    assert rows[0]["country"] == "de", (
        "a readable country_iso3 was discarded because an unreadable `country` cell "
        "was present in the same row"
    )


def test_an_unreadable_country_with_an_unreadable_alpha3_yields_no_country():
    """The negative-space twin: the fall-back must not invent a country either. Both
    columns fail closed, so the honest result is no country, not a guess."""
    rows, errors = parse_sources_csv(
        "name,domain,country,country_iso3\nX,x.example,Freedonia,ZZZ\n"
    )

    assert errors == []
    assert "country" not in rows[0]


def test_an_aggregate_in_the_alpha3_column_yields_no_country():
    rows, errors = parse_sources_csv("name,domain,country_iso3\nX,x.example,WLD\n")

    assert errors == []
    assert "country" not in rows[0]


# --------------------------------------------------------------------------- #
#  The property, not the list
# --------------------------------------------------------------------------- #
def test_every_export_that_carries_country_carries_both_forms():
    """Pinned as a PROPERTY over the module that OWNS the catalog's two exports, so the
    next payload added there cannot ship with only the old form. Parsed, not listed: a
    list of today's two row builders would be complete exactly once.

    SCOPE, measured rather than assumed. 78 dict literals in ``src/`` carry a
    ``"country"`` key -- analytics rollups, map features, geo lookups, the briefing
    recipes. Q313 = a moves "CSV/JSON exports" now and says diagnostics payloads switch
    "in the same release as storage", which is 0.5; widening this guard to all 78 would
    be building S05-02 early and would drag surfaces Q313 never named. The catalog
    export module is the surface Q313 names, so that is what is pinned."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent / "src" / "api" / "source_io.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    offenders, checked = [], 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if "country" not in keys:
            continue
        checked += 1
        if "country_iso3" not in keys:
            offenders.append(node.lineno)
    assert checked >= 2, (
        f"the guard found only {checked} payload(s) carrying a country in source_io.py; "
        "it is looking in the wrong place and an empty search passes for free"
    )
    assert not offenders, (
        f"payloads at src/api/source_io.py lines {offenders} carry `country` without "
        "`country_iso3` (Q313 = a keeps both forms for one release)"
    )


def test_the_import_reader_is_NOT_where_the_alpha3_column_is_stored():
    """The other half of the one-fact rule: the derived column never reaches the DB.
    ``upsert_sources`` writes what ``parse_sources_csv`` returns, and that parser
    RESOLVES the alpha-3 into ``country`` rather than passing it through -- so a stored
    row can never carry two country columns that disagree."""
    rows, errors = parse_sources_csv("name,domain,country_iso3\nX,x.example,DEU\n")

    assert errors == []
    assert "country_iso3" not in rows[0], (
        "the parser passed the derived column through to the writer; storage would then "
        "hold two editable copies of one fact (that flip is 0.5, S05-02)"
    )


def test_the_articles_export_carries_no_country_at_all():
    """MEASURED, not assumed. This is the reason Q313's "CSV/JSON exports" touches one
    exporter rather than several -- and if a future change adds a country to the
    articles export, this guard reddens and points at Q313 rather than letting it ship
    with one form."""
    import inspect

    from src.api.main import export_articles

    body = inspect.getsource(export_articles)
    assert '"Language"' in body, "the CSV header moved; re-anchor this guard"
    assert '"Country"' not in body and "a.country" not in body, (
        "the articles export grew a country column; Q313 = a says an export carrying "
        "`country` carries `country_iso3` beside it for this release"
    )
