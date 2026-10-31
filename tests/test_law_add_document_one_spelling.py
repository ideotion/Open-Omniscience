"""A law document pasted by URL is stored under the ONE spelling the catalogue's rows use, so a later restore finds one row, not two.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists (R399, the WAL lane's measurement of 2026-10-29, ``wal-lane/measure-law-jurisdiction-restore-2026-10-29.md``).
``POST /api/law/documents`` lowercased the typed jurisdiction and stored it; the catalogue's loader runs the same field through
``law_jurisdiction`` (``FRA``/``fra``/``FR`` -> ``fr``, ``GBR``/``gb``/``uk`` -> ``uk``). The two paths put different spellings of one
jurisdiction in the same column, and a restore matches law rows by the exact string (``m.jurisdiction = i.jurisdiction AND m.url = i.url``):

- **H** (a store that predates the country marker, alpha-2): ``FRA`` typed by the operator was stored as ``fra`` ("an alpha-2 store is
  written exactly as it always was"), and the restore of a backup holding ``fr`` for the URL added a second row;
- **J** (every store, so every new install): ``uk`` and ``GBR`` are one jurisdiction to the app and two strings to the merge, and the
  duplicate scan lists ``uk`` as unresolved instead of counting it.

What it pins: the stored string for every spelling of a jurisdiction CODE in both store forms, and that a WORD (``france``, ``georgia``,
``congo``) is stored as typed and never guessed into a code; that the document's own ``country`` takes the catalogue loader's conversion
for a code and is left alone for a word; that a document re-added in another spelling is still a duplicate, including against rows stored
before this change (codes and words) and against an unwatched row, which is reactivated and not duplicated; that another URL under the same
jurisdiction is a new document; and, end to end through the real merge, that the same URL typed two ways on two installs of any two forms
is ONE row after a restore. Every store here is a scratch file
and the route is served by a router of its own on a session bound to that file: no network, no shared store.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.merge import merge_corpus  # noqa: E402
from src.database import country_form as cf  # noqa: E402
from src.database.models import Base  # noqa: E402
from src.database.session import get_db  # noqa: E402

_META = {"artifact_kind": "oo-backup-3", "origin_fingerprint": "machine-B", "app_version": "0.5.0", "alembic_rev": "head", "manifest": None}
_URL = "https://law.example/one-spelling"


class _Blocked:
    """A fetcher that is refused by robots.txt: the route stores the row and answers the honest verdict, which is all these tests need."""

    def fetch(self, url: str, **_kw):
        from src.ingest import RobotsDisallowed

        raise RobotsDisallowed(f"robots.txt disallows {url}")


def _install(path: Path, form: str) -> Path:
    """A store file as an install in ``form`` holds it: the schema, and (for alpha-3) the marker a new store is stamped with."""
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    if form == "alpha3":
        con = sqlite3.connect(path)
        try:
            cf.write_form(con, "alpha3", by="test")
            con.commit()
        finally:
            con.close()
    return path


def _post(monkeypatch, path: Path, form: str, **body):
    """``POST /api/law/documents`` as the install whose store is ``path`` (country form ``form``) would answer it."""
    monkeypatch.setattr(cf, "store_form", lambda: form)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: _Blocked())
    engine = create_engine(f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False})
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    from src.api.law import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _db
    try:
        payload = {"title": "Loi", "url": _URL, **body}
        return TestClient(app, raise_server_exceptions=False).post("/api/law/documents", json=payload)
    finally:
        engine.dispose()


def _stored(path: Path) -> list[tuple]:
    """What the file holds, byte for byte (the ORM would read an alpha-3 value back as alpha-2)."""
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT jurisdiction, country FROM law_documents ORDER BY id").fetchall()
    finally:
        con.close()


def _seed(path: Path, form: str, held: str, *, watched: bool = True, url: str = _URL) -> None:
    """A row as an earlier version of the app (or the catalogue's loader) stored it: ``held`` is the stored spelling, written in ``form``."""
    from src.database.models import LawDocument

    engine = create_engine(f"sqlite:///{path}", future=True)
    with cf.writing_in(form), sessionmaker(bind=engine, future=True)() as s:
        s.add(LawDocument(jurisdiction=held, title="Loi", url=url, watched=watched))
        s.commit()
    engine.dispose()


def _watched(path: Path) -> list[int]:
    con = sqlite3.connect(path)
    try:
        return [w for (w,) in con.execute("SELECT watched FROM law_documents ORDER BY id")]
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  the stored spelling of the jurisdiction
# --------------------------------------------------------------------------- #
# typed -> (stored in an alpha-2 store, stored in an alpha-3 store). The three codes the app keeps for itself (`uk`, `eu`, `int`) have no
# alpha-3 meaning, so an alpha-3 store holds them as they are; every other code is written in the store's own form.
_SPELLINGS = [
    ("fr", "fr", "FRA"), ("FR", "fr", "FRA"), ("fra", "fr", "FRA"), ("FRA", "fr", "FRA"),
    ("uk", "uk", "uk"), ("gb", "uk", "uk"), ("GB", "uk", "uk"), ("gbr", "uk", "uk"), ("GBR", "uk", "uk"),
    ("eu", "eu", "eu"), ("euu", "eu", "eu"), ("EUU", "eu", "eu"),
    ("int", "int", "int"), ("INT", "int", "int"),
    # A code nothing can place is stored as typed (lowercased, as it always was), never guessed; a sub-national code with a hyphen is not a
    # country code either.
    ("zz", "zz", "zz"), ("XYZ", "xyz", "xyz"), ("us-ca", "us-ca", "us-ca"),
    # A NAME is not a code, and the country-name index guesses (`georgia` is the country, not the US state; `congo` is the DR Congo, not the
    # Republic; `england` is `uk` and `scotland` is not): a jurisdiction typed as a word is stored as typed, as it always was. `mali` and `chad`
    # are names of four letters that a wider "looks like a code" rule would convert.
    ("France", "france", "france"), ("georgia", "georgia", "georgia"), ("Congo", "congo", "congo"), ("America", "america", "america"),
    ("england", "england", "england"), ("Scotland", "scotland", "scotland"), ("mali", "mali", "mali"), ("Chad", "chad", "chad"),
]


@pytest.mark.parametrize("form", ["alpha2", "alpha3"])
def test_every_spelling_of_a_jurisdiction_is_stored_as_the_catalogue_stores_it(monkeypatch, tmp_path, form):
    for i, (typed, in_alpha2, in_alpha3) in enumerate(_SPELLINGS):
        store = _install(tmp_path / f"{form}-{i}.db", form)
        r = _post(monkeypatch, store, form, jurisdiction=typed)
        assert r.status_code == 200, (typed, r.text)
        assert _stored(store) == [(in_alpha2 if form == "alpha2" else in_alpha3, None)], (form, typed)


def test_a_spelling_with_spaces_around_it_is_stored_like_the_one_without(monkeypatch, tmp_path):
    # `GBR` is placed whatever surrounds it; ` XYZ ` is not a code anything can place, so only the route's own strip and lowercase reach it
    for i, (typed, kept) in enumerate([("  GBR ", "uk"), (" XYZ ", "xyz")]):
        store = _install(tmp_path / f"legacy{i}.db", "alpha2")
        assert _post(monkeypatch, store, "alpha2", jurisdiction=typed).status_code == 200
        assert _stored(store) == [(kept, None)], typed


# --------------------------------------------------------------------------- #
#  the document's own country
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("form", ["alpha2", "alpha3"])
def test_the_documents_own_country_is_stored_in_the_stores_form_whatever_was_typed(monkeypatch, tmp_path, form):
    wrote = {"alpha2": "fr", "alpha3": "FRA"}[form]
    for i, typed in enumerate(["fr", "FR", "fra", "FRA", " fr "]):
        store = _install(tmp_path / f"{form}-{i}.db", form)
        r = _post(monkeypatch, store, form, jurisdiction="fr", country=typed)
        assert r.status_code == 200, (typed, r.text)
        assert _stored(store)[0][1] == wrote, (form, typed)


@pytest.mark.parametrize("form, wrote", [("alpha2", "gb"), ("alpha3", "GBR")])
def test_the_app_own_code_for_the_uk_is_the_isos_in_the_country_column(monkeypatch, tmp_path, form, wrote):
    """``uk`` is a JURISDICTION the rows keep for themselves; the document's COUNTRY is an ISO country, as the catalogue's loader reads it."""
    store = _install(tmp_path / "s.db", form)
    assert _post(monkeypatch, store, form, jurisdiction="uk", country="uk").status_code == 200
    assert _stored(store) == [("uk", wrote)]


def test_a_country_nothing_can_place_a_name_and_no_country_are_stored_as_they_always_were(monkeypatch, tmp_path):
    # a name is never guessed into a code (`Congo` would be the DR Congo): the same rule as the jurisdiction's
    for i, (typed, kept) in enumerate([("zz", "zz"), (None, None), ("", ""), ("France", "France"), ("Congo", "Congo")]):
        store = _install(tmp_path / f"s{i}.db", "alpha3")
        assert _post(monkeypatch, store, "alpha3", jurisdiction="fr", country=typed).status_code == 200
        assert _stored(store) == [("FRA", kept)], typed


# --------------------------------------------------------------------------- #
#  a re-add in another spelling is one document
# --------------------------------------------------------------------------- #
# Both writes reach the same stored string now, so these cases pass over a lookup narrowed to the typed spelling as well: what pins the
# WIDENED lookup (a row stored before this change under another spelling is still found) is the group below.
@pytest.mark.parametrize("form", ["alpha2", "alpha3"])
@pytest.mark.parametrize("first, again", [("GBR", "uk"), ("uk", "gbr"), ("FRA", "fr"), ("fr", "FRA"), ("gb", "GBR")])
def test_a_document_added_again_in_another_spelling_is_still_a_duplicate(monkeypatch, tmp_path, form, first, again):
    store = _install(tmp_path / "s.db", form)
    assert _post(monkeypatch, store, form, jurisdiction=first).status_code == 200
    r = _post(monkeypatch, store, form, jurisdiction=again)
    assert r.status_code == 409, r.text
    assert len(_stored(store)) == 1


@pytest.mark.parametrize(
    "form, held, again",
    [
        ("alpha2", "fra", "FR"), ("alpha2", "fra", "fra"), ("alpha2", "gb", "uk"), ("alpha2", "gbr", "GBR"), ("alpha3", "GBR", "uk"), ("alpha3", "GBR", "gb"),
        # a row typed as a name before this change: the name is not converted now either, so it is found as it always was
        ("alpha2", "france", "France"), ("alpha3", "france", "france"), ("alpha2", "georgia", "georgia"),
    ],
)
def test_a_row_stored_before_this_change_in_another_spelling_is_still_found_by_a_re_add(monkeypatch, tmp_path, form, held, again):
    """Rows already in a store stay as they were written (a cleanup is the country migration's, not this route's); the duplicate check
    keeps matching them through every spelling, so the fix does not turn their re-adds into second rows."""
    store = _install(tmp_path / "s.db", form)
    _seed(store, form, held)
    before = _stored(store)
    r = _post(monkeypatch, store, form, jurisdiction=again)
    assert r.status_code == 409, r.text
    assert _stored(store) == before


@pytest.mark.parametrize(
    "form, held, again",
    [("alpha2", "fra", "fr"), ("alpha3", "GBR", "uk"), ("alpha3", "uk", "GBR"), ("alpha2", "france", "france"), ("alpha3", "france", "France")],
)
def test_an_unwatched_row_is_reactivated_by_adding_it_again_not_duplicated(monkeypatch, tmp_path, form, held, again):
    """The UI's "watch again" posts the jurisdiction exactly as the listing returned it (a name stays a name), so the lookup has to find
    the unwatched row whatever spelling it holds, and put it back to watched instead of filing a second row beside its history."""
    store = _install(tmp_path / "s.db", form)
    _seed(store, form, held, watched=False)
    before = _stored(store)
    r = _post(monkeypatch, store, form, jurisdiction=again)
    assert r.status_code == 200, r.text
    assert _stored(store) == before, "a second row was filed beside the unwatched one"
    assert _watched(store) == [1]


def test_another_url_under_the_same_jurisdiction_is_a_new_document(monkeypatch, tmp_path):
    store = _install(tmp_path / "s.db", "alpha3")
    assert _post(monkeypatch, store, "alpha3", jurisdiction="FRA").status_code == 200
    assert _post(monkeypatch, store, "alpha3", jurisdiction="fr", url="https://law.example/another").status_code == 200
    assert _stored(store) == [("FRA", None), ("FRA", None)]


# --------------------------------------------------------------------------- #
#  end to end: the restore finds ONE row
# --------------------------------------------------------------------------- #
# the same URL typed by two operators on two installs: (typed on the install the backup comes from, typed on the install restoring it)
_TWO_WAYS = [("fr", "FRA"), ("FRA", "fr"), ("gbr", "uk"), ("uk", "GBR"), ("GB", "gbr")]


@pytest.mark.parametrize("target_form", ["alpha2", "alpha3"])
@pytest.mark.parametrize("source_form", ["alpha2", "alpha3"])
@pytest.mark.parametrize("typed_there, typed_here", _TWO_WAYS)
def test_one_document_typed_two_ways_on_two_installs_is_one_row_after_a_restore(
    monkeypatch, tmp_path, source_form, target_form, typed_there, typed_here
):
    source = _install(tmp_path / "backup.db", source_form)
    assert _post(monkeypatch, source, source_form, jurisdiction=typed_there).status_code == 200
    target = _install(tmp_path / "live.db", target_form)
    assert _post(monkeypatch, target, target_form, jurisdiction=typed_here).status_code == 200
    held = _stored(target)

    monkeypatch.setattr(cf, "store_form", lambda: target_form)  # the live store is the one being restored into
    counts, _batch = merge_corpus(source, target, _META)

    assert _stored(target) == held, "the restore added a row for a document the store already tracked"
    assert (counts["law_documents"]["new"], counts["law_documents"]["duplicate"]) == (0, 1), counts["law_documents"]
