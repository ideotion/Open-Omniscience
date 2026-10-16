"""The export carries ONE country column, alpha-3 (Q313 = a, gate row B / S05-02 S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE SHAPE. Through 0.4 an export carried the country in BOTH forms for one release: the
stored alpha-2 in ``country`` and a derived ``country_iso3`` beside it (Q313 = a), so an
operator's spreadsheet kept working across the move. This is the release that collapses
the pair: ``country`` now carries the alpha-3 and the second column is gone from the
OUTPUT. The old alpha-2 value is what dropped, as the ruling said; the surviving header
is ``country`` (Q304: "``country`` becomes alpha-3 everywhere"), proposed in the PR body
because Q313 names the value that goes, not the header that stays.

THE IMPORT KEEPS READING THE OLD COLUMN, FOREVER. A sheet exported by 0.4 carries
``country`` = ``fr`` and ``country_iso3`` = ``FRA``; it must import (the same promise the
restore path makes to old backups). A row where the two disagree is still refused BY
NAME -- picking a winner silently is how an operator's edit gets discarded.

MEASURED SCOPE, so nobody later reads this file as covering more than it does. Two
surfaces in the tree emit a source's country: the sources CSV
(``/api/catalog/export.csv``) and the sources JSON listing (``/api/catalog/sources``).
The YAML/JSON export at ``/api/sources/export`` carries no country at all, neither
branch of ``/api/articles/export`` emits one, and the qualification overlay does not
either. Every other JSON payload leaves through the wire boundary
(``src/api/country_wire.py``; ``tests/test_country_wire.py``).
"""

from __future__ import annotations

import csv
import io

import pytest

from src.catalog.csv_io import (
    EXPORT_COLUMNS,
    IMPORT_COLUMNS,
    LEGACY_IMPORT_COLUMNS,
    parse_sources_csv,
    template_csv,
    write_csv,
)


def _header(text: str) -> list[str]:
    return next(csv.reader(io.StringIO(text)))


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


# --------------------------------------------------------------------------- #
#  The export carries one column, alpha-3
# --------------------------------------------------------------------------- #
def test_the_sources_csv_has_exactly_one_country_column():
    text = write_csv([{"name": "X", "domain": "x.example", "country": "FRA"}])

    header = _header(text)
    assert header.count("country") == 1
    assert "country_iso3" not in header and "country_iso3" not in EXPORT_COLUMNS
    assert _rows(text)[0]["country"] == "FRA"


@pytest.fixture()
def exported_text():
    from src.api.source_io import _source_to_row
    from src.database.models import Source

    return write_csv([
        _source_to_row(Source(name="Z", domain="iso3.example", country="fr")),
        _source_to_row(Source(name="U", domain="uk.example", country="uk")),
        _source_to_row(Source(name="E", domain="eu.example", country="eu")),
    ])


def test_the_export_row_builder_writes_the_alpha3(exported_text):
    """Chosen at the row builder, because a CSV is not a JSON response and never passes
    the wire boundary -- so this is the one place the export's form is decided."""
    got = {r["domain"]: r["country"] for r in _rows(exported_text)}
    assert got == {"iso3.example": "FRA", "uk.example": "GBR", "eu.example": "EUU"}


def test_an_unrecognised_country_is_kept_as_stored_and_an_empty_one_stays_empty():
    """The export is not a place to lose data. A value with no alpha-3 travels as the
    store holds it (the migration itself refuses to drop it, R100) and nothing is
    invented for a source with no country. An aggregate is NOT promoted to a nation."""
    from src.api.source_io import _source_to_row
    from src.database.models import Source

    text = write_csv([
        _source_to_row(Source(name="A", domain="a.example", country="WLD")),
        _source_to_row(Source(name="B", domain="b.example", country=None)),
        _source_to_row(Source(name="C", domain="c.example", country="floop")),
    ])

    got = {r["domain"]: r["country"] for r in _rows(text)}
    assert got == {"a.example": "WLD", "b.example": "", "c.example": "floop"}


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


def test_the_sources_LISTING_carries_one_alpha3_country(tmp_path):
    app, client = _listing_client(tmp_path)
    try:
        with client:
            rows = {s["domain"]: s for s in client.get("/api/catalog/sources").json()["sources"]}
    finally:
        app.dependency_overrides.clear()

    assert rows["alpha.test"]["country"] == "FRA"
    assert all("country_iso3" not in r for r in rows.values()), "the companion field came back"
    assert rows["bulk.test"]["country"] == "WLD", "an aggregate was given an alpha-3 it does not have"
    assert rows["nowhere.test"]["country"] is None


# --------------------------------------------------------------------------- #
#  The import contract
# --------------------------------------------------------------------------- #
def test_the_template_documents_only_what_an_import_is_OFFERED():
    """The legacy column is READ, never offered: handing an operator a blank column that
    can only get them refused would be a trap."""
    assert "country_iso3" not in _header(template_csv())
    assert "country_iso3" not in IMPORT_COLUMNS
    assert "country_iso3" in LEGACY_IMPORT_COLUMNS
    assert _rows(template_csv())[0]["country"] == "USA"


def test_an_export_round_trips_through_the_import():
    """An operator exports, changes nothing, re-imports, and their data is unchanged:
    the alpha-3 in the file is read back to the form the app speaks inside."""
    text = write_csv([{"name": "X", "domain": "x.example", "country": "FRA"}])

    rows, errors = parse_sources_csv(text)

    assert errors == []
    assert rows == [{"name": "X", "domain": "x.example", "country": "fr"}]


def test_a_sheet_exported_by_the_previous_release_still_imports():
    """THE PROMISE: 0.4 wrote ``country`` = ``fr`` and ``country_iso3`` = ``FRA``."""
    rows, errors = parse_sources_csv("name,domain,country,country_iso3\nX,x.example,fr,FRA\n")

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
    for country, iso3 in (("fr", "FRA"), ("FRA", "FRA"), ("FR", "fra")):
        rows, errors = parse_sources_csv(
            f"name,domain,country,country_iso3\nX,x.example,{country},{iso3}\n"
        )
        assert errors == [], (country, iso3)
        assert rows[0]["country"] == "fr"


def test_only_the_alpha3_column_is_honoured_when_it_is_the_only_one_given():
    """An old sheet an operator trimmed down to ``country_iso3`` alone. Getting this
    wrong would silently drop the operator's only statement of the country."""
    rows, errors = parse_sources_csv("name,domain,country_iso3\nX,x.example,DEU\n")

    assert errors == []
    assert rows[0]["country"] == "de"


def test_an_UNREADABLE_country_falls_back_to_the_alpha3_column():
    """The branch an ``elif`` would have swallowed: the fall-back is keyed on "is there a
    country NOW", not on "was a country column present"."""
    rows, errors = parse_sources_csv(
        "name,domain,country,country_iso3\nX,x.example,Freedonia,DEU\n"
    )

    assert errors == []
    assert rows[0]["country"] == "de", (
        "a readable country_iso3 was discarded because an unreadable `country` cell "
        "was present in the same row"
    )


def test_an_unreadable_country_with_an_unreadable_alpha3_yields_no_country():
    """The negative-space twin: the fall-back must not invent a country either."""
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
def test_every_country_the_source_export_module_emits_goes_through_the_one_helper():
    """Pinned as a PROPERTY over the module that owns the catalog's exports: every dict
    literal there that carries a ``country`` builds it with ``country_payload``, so the
    next row builder added to it cannot ship the stored alpha-2. Parsed, not listed."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent / "src" / "api" / "source_io.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    offenders, checked = [], 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "country":
                checked += 1
                if not (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "country_payload"
                ):
                    offenders.append(key.lineno)
    assert checked >= 2, (
        f"the guard found only {checked} payload(s) carrying a country in source_io.py; "
        "it is looking in the wrong place and an empty search passes for free"
    )
    assert not offenders, f"src/api/source_io.py lines {offenders} carry `country` without `country_payload`"


def test_the_import_reader_is_NOT_where_the_legacy_column_is_stored():
    """The one-fact rule: the legacy column never reaches the DB. ``upsert_sources`` writes
    what ``parse_sources_csv`` returns, and that parser RESOLVES the alpha-3 into
    ``country`` rather than passing it through."""
    rows, errors = parse_sources_csv("name,domain,country_iso3\nX,x.example,DEU\n")

    assert errors == []
    assert "country_iso3" not in rows[0]


def test_the_articles_export_carries_no_country_at_all():
    """MEASURED, not assumed. If a future change adds a country to the articles export,
    this guard reddens and points at Q313/Q304 rather than letting it ship in the
    stored form."""
    import inspect

    from src.api.main import export_articles

    body = inspect.getsource(export_articles)
    assert '"Language"' in body, "the CSV header moved; re-anchor this guard"
    assert '"Country"' not in body and "a.country" not in body, (
        "the articles export grew a country column; Q304 says it carries the alpha-3 "
        "(through `country_payload`), and Q313 allows one country column only"
    )


# --------------------------------------------------------------------------- #
#  The Opus read's M2 / L2: the four codes that are not ISO countries
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("country", "alpha3"), [("eu", "INT"), ("int", "WLD"), ("eu", "XKX")])
def test_two_columns_that_name_different_non_iso_codes_are_a_conflict_not_agreement(country, alpha3):
    """``to_iso3`` answers None for ``eu``/``int``/``xk``/``an`` and for any unknown code, and None == None read as agreement: the
    operator's edit was dropped without a word."""
    rows, errors = parse_sources_csv(f"name,domain,country,country_iso3\nX,x.example,{country},{alpha3}\n")

    assert rows == [] and len(errors) == 1 and "disagree" in errors[0], (country, alpha3)


@pytest.mark.parametrize(("alpha3", "stored"), [("EUU", "eu"), ("INT", "int"), ("ANT", "an"), ("XKX", "xk")])
def test_a_previous_release_alpha3_for_a_non_iso_code_is_still_read(alpha3, stored):
    """Values the 0.4 export itself wrote: an unreadable ``country`` beside them must not discard them (``to_iso2`` refused all four)."""
    rows, errors = parse_sources_csv(f"name,domain,country,country_iso3\nX,x.example,floop,{alpha3}\n")

    assert errors == [] and rows[0]["country"] == stored
