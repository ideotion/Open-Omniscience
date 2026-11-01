"""A restore finds a law document under ANY spelling of its jurisdiction, so an old backup and a new paste are one row.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists. The restore matched a law document by the EXACT text of its jurisdiction and its url. The staged copy is converted toward the
store's country form first, but that conversion refuses the app's own codes (``uk``, ``eu``, ``int``), and a store written by the route that pasted
a document by url (before PR #1679) held whatever the operator typed (``gb``, ``gbr``, ``fra``, ``euu``). So two spellings of one jurisdiction stayed
two strings to the match and a restore added a second row. PR #1679 makes the route store the catalogue's own spelling for what is written from then
on; it cannot reach what the old route already wrote, and a backup is a byte copy of that. Measured through the real merge on its head: of the
two- and three-letter spellings of one jurisdiction, an old route's backup restored over a store written by the new route went from one row to two
for 6 pairs (alpha-2 store) and 8 (alpha-3 store, every new install), among them the UK typed ``gb`` or ``gbr``. The merge now compares the two
sides through ``law_jurisdiction_key`` (``src/backup/country_codes.py``): the catalogue's form for a code, the string as stored for anything else.

What it pins:
* every pair of stored spellings of one jurisdiction, across the four combinations of source and target store form, is ONE row: the target's row
  is untouched, nothing is inserted, and one duplicate is counted (the old-backup-over-a-new-paste case among them, by name);
* two jurisdictions stay two rows, and a WORD is never guessed into a code (``france`` is not ``fr``: the country-name index chooses between a
  country and a US state, and between the two Congos);
* the revisions of a matched document land on the working copy's row, and where that copy holds the identity under two spellings the row spelled
  as the staged document is, else the oldest, is the home;
* a backup that holds two spellings of one document is restored as it always was (both rows), and restoring it again finds both;
* an alternate recorded under one spelling finds its revision under another, both when the restore places it and when the app later resolves
  it to show or swap it;
* where the working copy, or the backup itself, holds one document under two spellings, an alternate stays with the sibling it was recorded
  against: the recorded spelling first, then the store's form, then the oldest document, in the restore's placing and in the app's lookup, and
  an identity whose document kept its spelling through the staged conversion is not converted on its own;
* a carried alternate is the same item as one the store keeps when it lands on the same local row (same origin, same field set), whatever
  spelling either was recorded under: the same backup restored twice adds nothing, an alternate recorded against each of two siblings is two
  records, and the result does not depend on the order two backups are restored in;
* the key itself, for every spelling and for the strings that are not codes.
* the route that pastes a document and the restore read the code shape and the canonical spelling from the one module, so the writer and the
  reader cannot drift apart again.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup import alternates  # noqa: E402
from src.backup import merge as merge_mod  # noqa: E402
from src.backup.country_codes import (  # noqa: E402
    convert_alternate_countries,
    law_jurisdiction_key,
    normalise_staged_country_codes,
)
from src.backup.merge import merge_corpus  # noqa: E402
from src.backup.provenance import ALTERNATE_SPECS  # noqa: E402
from src.database import country_form as cf  # noqa: E402
from src.database.models import Base  # noqa: E402

_META = {"artifact_kind": "oo-backup-3", "origin_fingerprint": "machine-B", "app_version": "0.5.0", "alembic_rev": "head", "manifest": None}
_URL = "https://law.example/canonical"


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    """The schema once; each case copies the file (building it per case costs 0.4 s)."""
    path = tmp_path_factory.mktemp("law-template") / "template.db"
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


def _store(
    template: Path, path: Path, form: str, held: list[str], revisions: list[tuple[int, str]] = (), url: str = _URL,
    summaries: list[tuple[int, str, str]] = (), urls: list[str] | None = None,
) -> Path:
    """A store file as an install in ``form`` holds it, with one law document per entry of ``held`` (the STORED spelling, written byte for byte;
    all on ``url``, or on ``urls[i]`` where ``urls`` is given), a revision per ``(index of its document in held, content hash)`` and a summary
    per ``(index of its revision in revisions, model, text)``."""
    shutil.copy(template, path)
    con = sqlite3.connect(path)
    try:
        if form == "alpha3":
            cf.write_form(con, "alpha3", by="test")
        ids = []
        for n, j in enumerate(held):
            cur = con.execute(
                "INSERT INTO law_documents (jurisdiction, title, url, watched) VALUES (?, 'Loi', ?, 1)", (j, urls[n] if urls else url)
            )
            ids.append(cur.lastrowid)
        revision_ids = []
        for at, content_hash in revisions:
            cur = con.execute("INSERT INTO law_revisions (document_id, content_hash) VALUES (?, ?)", (ids[at], content_hash))
            revision_ids.append(cur.lastrowid)
        for at, model, summary in summaries:
            con.execute(
                "INSERT INTO law_revision_summaries (revision_id, summary, model, prompt_version, prompt_text, created_at)"
                " VALUES (?, ?, ?, 'v1', 'p', '2026-01-01 00:00:00')",
                (revision_ids[at], summary, model),
            )
        con.commit()
    finally:
        con.close()
    return path


def _merge(monkeypatch, src: Path, tgt: Path, tform: str) -> dict:
    monkeypatch.setattr(cf, "store_form", lambda: tform)
    counts, _ = merge_corpus(src, tgt, _META)
    return counts


def _jurisdictions(path: Path) -> list[str]:
    con = sqlite3.connect(path)
    try:
        return [j for (j,) in con.execute("SELECT jurisdiction FROM law_documents ORDER BY id")]
    finally:
        con.close()


def _revisions(path: Path) -> list[tuple[str, str]]:
    """(the jurisdiction of the document a revision belongs to, its hash), in id order."""
    con = sqlite3.connect(path)
    try:
        return con.execute(
            "SELECT d.jurisdiction, r.content_hash FROM law_revisions r JOIN law_documents d ON d.id = r.document_id ORDER BY r.id"
        ).fetchall()
    finally:
        con.close()


def _summaries(path: Path) -> list[tuple[str, str]]:
    """(the jurisdiction of the document a summary belongs to, its text), in id order."""
    con = sqlite3.connect(path)
    try:
        return con.execute(
            "SELECT d.jurisdiction, s.summary FROM law_revision_summaries s JOIN law_revisions r ON r.id = s.revision_id"
            " JOIN law_documents d ON d.id = r.document_id ORDER BY s.id"
        ).fetchall()
    finally:
        con.close()


_FORMS = [("alpha2", "alpha2"), ("alpha3", "alpha3"), ("alpha2", "alpha3"), ("alpha3", "alpha2")]
#: Spellings of one jurisdiction as a store can hold them: the catalogue's (``uk``), the alpha-2 an old route stored in an alpha-2 store (``gb``),
#: what an operator typed that no store converts (``gbr``), and the alpha-3 an alpha-3 store wrote for it (``GBR``).
_GROUPS = {
    "uk": ["uk", "gb", "gbr", "GBR"],
    "fr": ["fr", "fra", "FRA"],
    "eu": ["eu", "euu", "EUU"],
    "int": ["int", "INT"],
}
_PAIRS = [(x, y) for spellings in _GROUPS.values() for x in spellings for y in spellings]


# --------------------------------------------------------------------------- #
#  one jurisdiction, any two spellings: one row
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sform, tform", _FORMS)
@pytest.mark.parametrize("backup, target", _PAIRS)
def test_any_two_spellings_of_one_jurisdiction_are_one_row(monkeypatch, tmp_path, template, sform, tform, backup, target):
    src = _store(template, tmp_path / "src.db", sform, [backup])
    tgt = _store(template, tmp_path / "tgt.db", tform, [target])
    law = _merge(monkeypatch, src, tgt, tform)["law_documents"]
    assert _jurisdictions(tgt) == [target], "the working copy's row is untouched and nothing is inserted beside it"
    assert (law["new"], law["duplicate"]) == (0, 1)


@pytest.mark.parametrize(
    "backup_held, target_held, sform, tform",
    [
        # the interface shows the UK as GBR; an old route stored what was typed, and a new route stores the catalogue's `uk`
        ("gb", "uk", "alpha2", "alpha2"),
        ("GBR", "uk", "alpha3", "alpha3"),
        ("GBR", "uk", "alpha3", "alpha2"),
        ("gb", "uk", "alpha2", "alpha3"),
        ("gbr", "uk", "alpha2", "alpha3"),
        # the four other aliases the route now converts, which an alpha-3 store could not place either
        ("euu", "eu", "alpha3", "alpha3"),
        ("ant", "an", "alpha3", "alpha3"),
        ("uae", "ae", "alpha3", "alpha3"),
        ("drc", "cd", "alpha3", "alpha3"),
    ],
)
def test_a_backup_an_old_route_wrote_restored_over_a_document_a_new_paste_wrote_stays_one_row(
    monkeypatch, tmp_path, template, backup_held, target_held, sform, tform
):
    src = _store(template, tmp_path / "src.db", sform, [backup_held])
    tgt = _store(template, tmp_path / "tgt.db", tform, [target_held])
    law = _merge(monkeypatch, src, tgt, tform)["law_documents"]
    assert _jurisdictions(tgt) == [target_held]
    assert (law["new"], law["duplicate"]) == (0, 1)


def test_the_other_direction_is_one_row_too(monkeypatch, tmp_path, template):
    """A backup a new route wrote, restored over a document an old route stored: the old spelling is the working copy's, and stays."""
    src = _store(template, tmp_path / "src.db", "alpha3", ["uk"])
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["GBR"])
    law = _merge(monkeypatch, src, tgt, "alpha3")["law_documents"]
    assert _jurisdictions(tgt) == ["GBR"] and (law["new"], law["duplicate"]) == (0, 1)


# --------------------------------------------------------------------------- #
#  what must NOT merge
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "backup, target",
    [("fr", "uk"), ("uk", "eu"), ("fra", "gbr"), ("int", "eu"), ("de", "at"), ("GBR", "FRA")],
)
@pytest.mark.parametrize("sform, tform", _FORMS)
def test_two_jurisdictions_stay_two_rows(monkeypatch, tmp_path, template, sform, tform, backup, target):
    src = _store(template, tmp_path / "src.db", sform, [backup])
    tgt = _store(template, tmp_path / "tgt.db", tform, [target])
    law = _merge(monkeypatch, src, tgt, tform)["law_documents"]
    assert len(_jurisdictions(tgt)) == 2 and (law["new"], law["duplicate"]) == (1, 0)


@pytest.mark.parametrize(
    "backup, target",
    [("france", "fr"), ("fr", "france"), ("georgia", "ge"), ("congo", "cd"), ("england", "uk"), ("uk", "scotland"), ("mali", "ml")],
)
def test_a_word_is_never_guessed_into_a_code(monkeypatch, tmp_path, template, backup, target):
    src = _store(template, tmp_path / "src.db", "alpha2", [backup])
    tgt = _store(template, tmp_path / "tgt.db", "alpha2", [target])
    law = _merge(monkeypatch, src, tgt, "alpha2")["law_documents"]
    assert len(_jurisdictions(tgt)) == 2 and (law["new"], law["duplicate"]) == (1, 0)


def test_the_same_word_is_still_one_row(monkeypatch, tmp_path, template):
    src = _store(template, tmp_path / "src.db", "alpha2", ["france"])
    tgt = _store(template, tmp_path / "tgt.db", "alpha2", ["france"])
    law = _merge(monkeypatch, src, tgt, "alpha2")["law_documents"]
    assert _jurisdictions(tgt) == ["france"] and (law["new"], law["duplicate"]) == (0, 1)


def test_another_url_under_the_same_jurisdiction_is_a_new_document(monkeypatch, tmp_path, template):
    src = _store(template, tmp_path / "src.db", "alpha3", ["GBR"], url="https://law.example/other")
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"])
    law = _merge(monkeypatch, src, tgt, "alpha3")["law_documents"]
    assert len(_jurisdictions(tgt)) == 2 and (law["new"], law["duplicate"]) == (1, 0)


# --------------------------------------------------------------------------- #
#  the revisions follow the document that matched
# --------------------------------------------------------------------------- #
def test_the_revisions_of_a_matched_document_land_on_the_working_copys_row(monkeypatch, tmp_path, template):
    src = _store(template, tmp_path / "src.db", "alpha3", ["GBR"], [(0, "hash-a"), (0, "hash-b")])
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"], [(0, "hash-a")])
    counts = _merge(monkeypatch, src, tgt, "alpha3")
    assert _jurisdictions(tgt) == ["uk"]
    assert _revisions(tgt) == [("uk", "hash-a"), ("uk", "hash-b")], "the new revision is the working copy's document's, the old one is not doubled"
    assert (counts["law_revisions"]["new"], counts["law_revisions"]["duplicate"]) == (1, 1)


def test_a_document_that_is_new_brings_its_revisions_with_it(monkeypatch, tmp_path, template):
    src = _store(template, tmp_path / "src.db", "alpha3", ["GBR"], [(0, "hash-a")])
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["FRA"])
    counts = _merge(monkeypatch, src, tgt, "alpha3")
    assert _jurisdictions(tgt) == ["FRA", "GBR"] and _revisions(tgt) == [("GBR", "hash-a")]
    assert counts["law_documents"]["new"] == 1


def test_where_the_working_copy_holds_two_spellings_the_one_spelled_like_the_staged_document_is_the_home(monkeypatch, tmp_path, template):
    """The unique index lets `uk` and `GBR` sit side by side for one url (the state the old route made); the staged `GBR` is that row's, as an exact match found."""
    src = _store(template, tmp_path / "src.db", "alpha3", ["GBR"], [(0, "hash-a")])
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk", "GBR"])
    law = _merge(monkeypatch, src, tgt, "alpha3")["law_documents"]
    assert _jurisdictions(tgt) == ["uk", "GBR"] and (law["new"], law["duplicate"]) == (0, 1)
    assert _revisions(tgt) == [("GBR", "hash-a")]


def test_where_no_spelling_is_exact_the_oldest_row_is_the_home(monkeypatch, tmp_path, template):
    src = _store(template, tmp_path / "src.db", "alpha3", ["eu"], [(0, "hash-a")])
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["euu", "EUU"])
    _merge(monkeypatch, src, tgt, "alpha3")
    assert _jurisdictions(tgt) == ["euu", "EUU"] and _revisions(tgt) == [("euu", "hash-a")]


# --------------------------------------------------------------------------- #
#  a backup that holds two spellings of one document
# --------------------------------------------------------------------------- #
def test_a_backup_holding_two_spellings_of_one_document_is_restored_as_it_always_was(monkeypatch, tmp_path, template):
    src = _store(template, tmp_path / "src.db", "alpha3", ["uk", "GBR"])
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", [])
    law = _merge(monkeypatch, src, tgt, "alpha3")["law_documents"]
    assert _jurisdictions(tgt) == ["uk", "GBR"] and (law["new"], law["duplicate"]) == (2, 0)
    # the second restore of the same backup finds both
    again = _merge(monkeypatch, src, tgt, "alpha3")["law_documents"]
    assert _jurisdictions(tgt) == ["uk", "GBR"] and (again["new"], again["duplicate"]) == (0, 2)


def test_a_backup_holding_two_spellings_is_restored_as_it_always_was_over_a_copy_that_holds_the_document(monkeypatch, tmp_path, template):
    """The backup watched `uk` and `GBR` and fetched the same page for both, so each has a revision with the same hash. The working copy holds the
    document (a fresh install's catalogue `uk`, no revisions). Mapping both staged rows onto the one working-copy row would insert the same
    (document, hash) twice: the restore would fail whole. A sibling is matched by its exact spelling, as it always was."""
    src = _store(template, tmp_path / "src.db", "alpha3", ["uk", "GBR"], [(0, "hash-a"), (1, "hash-a")])
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"])
    counts = _merge(monkeypatch, src, tgt, "alpha3")
    assert (counts["law_documents"]["new"], counts["law_documents"]["duplicate"]) == (1, 1)
    assert _jurisdictions(tgt) == ["uk", "GBR"]
    assert _revisions(tgt) == [("uk", "hash-a"), ("GBR", "hash-a")]
    again = _merge(monkeypatch, src, tgt, "alpha3")
    assert (again["law_documents"]["new"], again["law_documents"]["duplicate"]) == (0, 2)
    assert _revisions(tgt) == [("uk", "hash-a"), ("GBR", "hash-a")]


def test_each_summary_of_a_backup_holding_two_spellings_stays_on_its_own_document(monkeypatch, tmp_path, template):
    """Two summaries by one model on one revision hash would be two rows for one (revision, model); each stays with the document it was made on."""
    src = _store(
        template, tmp_path / "src.db", "alpha3", ["uk", "GBR"], [(0, "hash-a"), (1, "hash-a")], summaries=[(0, "m", "one"), (1, "m", "two")]
    )
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"], [(0, "hash-a")])
    _merge(monkeypatch, src, tgt, "alpha3")
    assert _summaries(tgt) == [("uk", "one"), ("GBR", "two")]


@pytest.mark.parametrize("live", [["uk"], ["GBR"], ["gb"], ["uk", "GBR"], ["gbr", "uk"], []])
@pytest.mark.parametrize("staged", [["uk", "GBR"], ["gb", "GBR"], ["gbr", "uk", "GBR"], ["GBR", "uk"]])
def test_a_backup_holding_several_spellings_never_maps_two_of_them_onto_one_row(monkeypatch, tmp_path, template, staged, live):
    """The id map is one-to-one on the staged side AND on the working-copy side: whatever the backup holds under one identity, whatever the working
    copy holds, the restore completes, and the staged documents that no working-copy row is spelled like come in as their own rows."""
    src = _store(template, tmp_path / "src.db", "alpha3", staged, [(i, "hash-a") for i in range(len(staged))])
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", live)
    _merge(monkeypatch, src, tgt, "alpha3")
    assert _jurisdictions(tgt) == live + [j for j in staged if j not in live]
    assert sorted(j for j, _ in _revisions(tgt)) == sorted(staged), "one revision per staged document, each on a document of its own"


def test_a_sibling_is_held_only_by_a_working_copy_row_of_its_own_url(monkeypatch, tmp_path, template):
    """The exact match of a sibling is on (jurisdiction, url), as it always was: a `uk` of ANOTHER url holds nothing."""
    src = _store(template, tmp_path / "src.db", "alpha3", ["uk", "GBR"], [(0, "hash-a"), (1, "hash-a")], url=_URL)
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"], url="https://law.example/another")
    law = _merge(monkeypatch, src, tgt, "alpha3")["law_documents"]
    assert (law["new"], law["duplicate"]) == (2, 0) and _jurisdictions(tgt) == ["uk", "uk", "GBR"]


def test_two_documents_of_one_jurisdiction_on_two_urls_are_not_siblings(monkeypatch, tmp_path, template):
    """Siblings share the identity (key AND url). `gb` and `GBR` on two urls are two documents, each held by the key of its own url."""
    a, b = "https://law.example/a", "https://law.example/b"
    src = _store(template, tmp_path / "src.db", "alpha3", ["gb", "GBR"], urls=[a, b])
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk", "uk"], urls=[a, b])
    law = _merge(monkeypatch, src, tgt, "alpha3")["law_documents"]
    assert (law["new"], law["duplicate"]) == (0, 2) and _jurisdictions(tgt) == ["uk", "uk"]


def test_two_jurisdictions_on_one_url_are_not_siblings(monkeypatch, tmp_path, template):
    """Siblings share the identity (key AND url). `gb` and `fr` on one url are two jurisdictions: `gb` is held by the key of the `uk` on that url."""
    src = _store(template, tmp_path / "src.db", "alpha3", ["gb", "fr"])
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"])
    law = _merge(monkeypatch, src, tgt, "alpha3")["law_documents"]
    assert (law["new"], law["duplicate"]) == (1, 1) and _jurisdictions(tgt) == ["uk", "FRA"]


# --------------------------------------------------------------------------- #
#  an alternate recorded under one spelling finds its revision under another
# --------------------------------------------------------------------------- #
def _alternate_home(path: Path, jurisdiction: str | None, content_hash: str = "hash-a"):
    identity = {"document_url": _URL, "revision_content_hash": content_hash, "model": "m"}
    if jurisdiction is not None:
        identity["jurisdiction"] = jurisdiction
    con = sqlite3.connect(path)
    try:
        return merge_mod._alternate_local_match(con, ALTERNATE_SPECS["law_revision_summaries"], identity)
    finally:
        con.close()


@pytest.mark.parametrize("recorded", ["GBR", "gb", "gbr", "uk"])
def test_an_alternate_recorded_under_any_spelling_finds_the_revision(template, tmp_path, recorded):
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"], [(0, "hash-a")])
    where, params = _alternate_home(tgt, recorded)
    assert where is not None and params[0] == 1


def test_an_alternate_of_another_jurisdiction_finds_nothing(template, tmp_path):
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"], [(0, "hash-a")])
    assert _alternate_home(tgt, "FRA") == (None, [])


def test_an_alternate_with_no_jurisdiction_still_finds_the_oldest_revision(template, tmp_path):
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"], [(0, "hash-a")])
    where, params = _alternate_home(tgt, None)
    assert where is not None and params[0] == 1


def test_an_alternate_prefers_the_row_spelled_as_it_says(template, tmp_path):
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk", "GBR"], [(0, "hash-a"), (1, "hash-a")])
    where, params = _alternate_home(tgt, "GBR")
    assert where is not None and params[0] == 2, "the revision of the `GBR` document, not the older `uk` one"


def _resolved(path: Path, jurisdiction: str | None, summaries: list[tuple[int, str]]):
    """``alternates._local_row_id`` (how the app finds, later, the row an alternate differs from) over a store that holds ``summaries``:
    (the revision it belongs to, its model). The identity names the revision of ``_URL`` with hash ``hash-a`` and the model ``m1``."""
    con = sqlite3.connect(path)
    try:
        for revision_id, model in summaries:
            con.execute(
                "INSERT INTO law_revision_summaries (revision_id, summary, model, prompt_version, prompt_text, created_at)"
                " VALUES (?, 's', ?, 'v1', 'p', '2026-01-01 00:00:00')",
                (revision_id, model),
            )
        con.commit()
    finally:
        con.close()
    identity = {"document_url": _URL, "revision_content_hash": "hash-a", "model": "m1"}
    if jurisdiction is not None:
        identity["jurisdiction"] = jurisdiction
    engine = create_engine(f"sqlite:///{path}", future=True)
    try:
        with sessionmaker(bind=engine, future=True)() as session:
            return alternates._local_row_id(session, "law_revision_summaries", identity)
    finally:
        engine.dispose()


@pytest.mark.parametrize("recorded", ["GBR", "gb", "gbr", "uk"])
def test_the_app_finds_the_row_an_alternate_differs_from_under_any_spelling(monkeypatch, template, tmp_path, recorded):
    monkeypatch.setattr(cf, "store_form", lambda: "alpha3")
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"], [(0, "hash-a")])
    assert _resolved(tgt, recorded, [(1, "m1")]) == 1


def test_the_app_does_not_find_a_row_of_another_jurisdiction(monkeypatch, template, tmp_path):
    monkeypatch.setattr(cf, "store_form", lambda: "alpha3")
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"], [(0, "hash-a")])
    assert _resolved(tgt, "FRA", [(1, "m1")]) is None


def test_an_alternate_with_no_jurisdiction_is_still_found_by_the_app(monkeypatch, template, tmp_path):
    monkeypatch.setattr(cf, "store_form", lambda: "alpha3")
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk"], [(0, "hash-a")])
    assert _resolved(tgt, None, [(1, "m1")]) == 1


def test_the_app_takes_the_row_of_the_document_spelled_as_the_identity_says(monkeypatch, template, tmp_path):
    """Two documents for one url (the old route's `GBR` beside the catalogue's `uk`), the same revision hash and model on both: the identity's own spelling decides."""
    monkeypatch.setattr(cf, "store_form", lambda: "alpha3")
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", ["uk", "GBR"], [(0, "hash-a"), (1, "hash-a")])
    assert _resolved(tgt, "GBR", [(1, "m1"), (2, "m1")]) == 2


def _merge_side_row(path: Path, jurisdiction: str):
    """The summary row ``_alternate_local_match`` (the merge placing an alternate) points at."""
    identity = {"jurisdiction": jurisdiction, "document_url": _URL, "revision_content_hash": "hash-a", "model": "m1"}
    con = sqlite3.connect(path)
    try:
        where, params = merge_mod._alternate_local_match(con, ALTERNATE_SPECS["law_revision_summaries"], identity)
        return con.execute(f"SELECT MIN(rowid) FROM law_revision_summaries WHERE {where}", tuple(params)).fetchone()[0]  # noqa: S608  # nosec B608 - test
    finally:
        con.close()


@pytest.mark.parametrize(
    "identity, held, revisions, expected",
    [
        # the exact spelling wins on both sides, even where the other document's summary is the newer one
        ("uk", ["uk", "GBR"], [(0, "hash-a"), (1, "hash-a")], 1),
        ("GBR", ["uk", "GBR"], [(0, "hash-a"), (1, "hash-a")], 2),
        # no spelling is exact: the oldest DOCUMENT, on both sides, even where the other document's revision was written first
        ("eu", ["euu", "EUU"], [(1, "hash-a"), (0, "hash-a")], 2),
        ("eu", ["euu", "EUU"], [(0, "hash-a"), (1, "hash-a")], 1),
    ],
)
def test_the_merge_and_the_app_resolve_an_alternate_to_the_same_summary(monkeypatch, template, tmp_path, identity, held, revisions, expected):
    """The merge's placing of an alternate and the app's later lookup take the document spelled exactly as the identity says, else (the store's form
    aside, pinned below) the oldest document. Two rules would show the operator the review of one document and swap another's summary."""
    monkeypatch.setattr(cf, "store_form", lambda: "alpha3")
    summaries = [(i, "m1", f"text-{i}") for i in range(len(revisions))]
    tgt = _store(template, tmp_path / "tgt.db", "alpha3", held, revisions, summaries=summaries)
    engine = create_engine(f"sqlite:///{tgt}", future=True)
    try:
        with sessionmaker(bind=engine, future=True)() as session:
            app_row = alternates._local_row_id(
                session, "law_revision_summaries",
                {"jurisdiction": identity, "document_url": _URL, "revision_content_hash": "hash-a", "model": "m1"},
            )
    finally:
        engine.dispose()
    assert _merge_side_row(tgt, identity) == app_row == expected


def _app_side_row(path: Path, jurisdiction: str):
    """The summary row ``alternates._local_row_id`` (the app, later, showing or swapping an alternate) points at."""
    engine = create_engine(f"sqlite:///{path}", future=True)
    try:
        with sessionmaker(bind=engine, future=True)() as session:
            return alternates._local_row_id(
                session, "law_revision_summaries",
                {"jurisdiction": jurisdiction, "document_url": _URL, "revision_content_hash": "hash-a", "model": "m1"},
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "form, held, recorded, expected",
    [
        # the spelling the alternate was RECORDED with is the document it was captured against, not the one its store-form conversion names
        ("alpha2", ["gbr", "gb"], "gbr", 1),
        ("alpha2", ["gbr", "gb"], "gb", 2),
        ("alpha3", ["gb", "GBR"], "gb", 1),
        ("alpha3", ["gb", "GBR"], "GBR", 2),
        # the recorded spelling is not held: the document spelled in the store's form
        ("alpha3", ["uk", "GBR"], "gb", 2),
        ("alpha2", ["uk", "gb"], "gbr", 2),
        # neither is held: the oldest document
        ("alpha3", ["gb", "uk"], "gbr", 1),
        ("alpha3", ["uk", "gb"], "gbr", 1),
    ],
)
def test_an_alternate_is_resolved_to_the_document_it_was_recorded_against(monkeypatch, template, tmp_path, form, held, recorded, expected):
    """Recorded spelling first, then the store form, then the oldest document, in the merge's placing of an alternate AND in the app's later lookup
    (``_alternate_local_match`` is handed the identity as the restore leaves it: as recorded, where its document kept the spelling). Converting the
    recorded spelling to the store's form first sent an alternate captured from `gbr` to the `gb` document of an alpha-2 store."""
    monkeypatch.setattr(cf, "store_form", lambda: form)
    revisions = [(i, "hash-a") for i in range(len(held))]
    tgt = _store(template, tmp_path / "tgt.db", form, held, revisions, summaries=[(i, "m1", f"text-{i}") for i in range(len(held))])
    assert _merge_side_row(tgt, recorded) == _app_side_row(tgt, recorded) == expected


def _carry(path: Path, jurisdiction: str, summary: str = "Z-text", url: str | None = _URL, origin: str = "machine-Z") -> None:
    """An alternate another machine recorded, as a backup carries it: against the summary of ``_URL``'s ``hash-a`` revision by model ``m1``,
    its identity naming the document under ``jurisdiction`` exactly as that machine stored it."""
    con = sqlite3.connect(path)
    try:
        con.execute(
            "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at)"
            " VALUES (1, 'law_revision_summaries', ?, 1, ?, ?, ?, 'pending', '2026-01-01')",
            (
                json.dumps({"jurisdiction": jurisdiction, "document_url": url, "revision_content_hash": "hash-a", "model": "m1"}, separators=(",", ":")),
                json.dumps({"summary": summary, "prompt_version": "v1"}, separators=(",", ":")),  # as the exporter's json_object writes them
                json.dumps({"v": 1, "kind": "model", "producer": "m1"}),
                origin,
            ),
        )
        con.commit()
    finally:
        con.close()


def _where_alternates_went(path: Path, origin: str = "machine-Z") -> list[tuple[str, str | None, str | None]]:
    """For each alternate the backup CARRIED (origin ``machine-Z``; the merge records its own for a summary that differs): the jurisdiction
    its identity now names, the jurisdiction of the document the merge placed it on (``local_row_id``), and that of the document the app
    resolves it to later (``alternates._local_row_id`` over the stored identity)."""
    con = sqlite3.connect(path)
    try:
        rows = con.execute("SELECT identity, local_row_id FROM metadata_alternates WHERE origin = ? ORDER BY id", (origin,)).fetchall()
        placed = dict(
            con.execute(
                "SELECT s.rowid, d.jurisdiction FROM law_revision_summaries s JOIN law_revisions r ON r.id = s.revision_id"
                " JOIN law_documents d ON d.id = r.document_id"
            )
        )
    finally:
        con.close()
    out = []
    engine = create_engine(f"sqlite:///{path}", future=True)
    try:
        with sessionmaker(bind=engine, future=True)() as session:
            for identity, local_row_id in rows:
                ident = json.loads(identity)
                app_row = alternates._local_row_id(session, "law_revision_summaries", ident)
                out.append((ident["jurisdiction"], placed.get(local_row_id), placed.get(app_row)))
    finally:
        engine.dispose()
    return out


def _backup_with_two_spellings(template: Path, tmp_path: Path, form: str, held: list[str], recorded: str, live: list[str]):
    src = _store(
        template, tmp_path / "src.db", form, held, [(i, "hash-a") for i in range(len(held))],
        summaries=[(i, "m1", f"A{i + 1}") for i in range(len(held))],
    )
    _carry(src, recorded)
    tgt = _store(
        template, tmp_path / "tgt.db", form, live, [(i, "hash-a") for i in range(len(live))],
        summaries=[(i, "m1", f"C{i + 1}") for i in range(len(live))],
    )
    return src, tgt


@pytest.mark.parametrize(
    "form, held, recorded, live",
    [
        # a backup that holds ONE document under two spellings, an alternate recorded against either, over an empty copy and over one that
        # already holds the store-form spelling (the sibling that is not held is the one the restore adds)
        ("alpha2", ["gbr", "gb"], "gbr", []),
        ("alpha2", ["gbr", "gb"], "gb", []),
        ("alpha2", ["gbr", "gb"], "gbr", ["gb"]),
        ("alpha2", ["gb", "gbr"], "gbr", []),
        ("alpha3", ["gb", "GBR"], "gb", []),
        ("alpha3", ["gb", "GBR"], "GBR", []),
        ("alpha3", ["gb", "GBR"], "gb", ["GBR"]),
        ("alpha3", ["GBR", "gb"], "gb", []),
    ],
)
def test_a_restored_alternate_stays_with_the_sibling_it_was_recorded_against(monkeypatch, template, tmp_path, form, held, recorded, live):
    """The staged copy converts every identity toward the store's form, but a document whose column conversion collides with its sibling keeps
    the spelling it had. An identity converted on its own then named the OTHER sibling: the restore placed the alternate on it and the app showed
    and swapped it there. The identity follows its document: placed on the recorded sibling, resolved there by the app, identity as recorded."""
    src, tgt = _backup_with_two_spellings(template, tmp_path, form, held, recorded, live)
    _merge(monkeypatch, src, tgt, form)
    assert _where_alternates_went(tgt) == [(recorded, recorded, recorded)]


@pytest.mark.parametrize(
    "form, held, recorded, live, converted",
    [
        # no sibling in the backup: the identity is converted toward the store, as it always was, and lands on the store-form document
        ("alpha2", ["gbr"], "gbr", ["gb"], "gb"),
        ("alpha2", ["gbr"], "gbr", [], "gb"),
        ("alpha3", ["gb"], "gb", ["GBR"], "GBR"),
        ("alpha3", ["gb"], "gb", [], "GBR"),
        # the recorded spelling is not the one the backup holds: converted, and it finds the document by its key
        ("alpha2", ["gb"], "gbr", ["gb"], "gb"),
    ],
)
def test_an_alternate_whose_document_was_converted_is_converted_with_it(monkeypatch, template, tmp_path, form, held, recorded, live, converted):
    src, tgt = _backup_with_two_spellings(template, tmp_path, form, held, recorded, live)
    _merge(monkeypatch, src, tgt, form)
    went = _where_alternates_went(tgt)
    assert [w[0] for w in went] == [converted]
    assert went[0][1] == went[0][2] == converted


def test_a_backup_holding_two_spellings_restored_twice_carries_its_alternate_once(monkeypatch, template, tmp_path):
    src, tgt = _backup_with_two_spellings(template, tmp_path, "alpha2", ["gbr", "gb"], "gbr", [])
    again = shutil.copy(src, tmp_path / "src-again.db")  # a restore normalises the attached file in place: the second one starts from a pristine copy
    _merge(monkeypatch, src, tgt, "alpha2")
    counts = _merge(monkeypatch, Path(again), tgt, "alpha2")
    assert _where_alternates_went(tgt) == [("gbr", "gbr", "gbr")]
    assert counts["metadata_alternates"]["new"] == 0


@pytest.mark.parametrize(
    "docs, identity_url, keep, expected",
    [
        # the staged copy still holds the document under the recorded spelling (its column conversion collided): the identity stays with it
        ([("gbr", _URL)], _URL, True, "gbr"),
        # the same, when not asked (the migration's call): converted
        ([("gbr", _URL)], _URL, False, "gb"),
        # a document of that spelling at ANOTHER url is not this identity's document
        ([("gbr", "https://law.example/other")], _URL, True, "gb"),
        # the document was converted (it holds the store's spelling now), or is not in the staged copy at all, or the identity names no url
        ([("gb", _URL)], _URL, True, "gb"),
        ([], _URL, True, "gb"),
        ([("gbr", _URL)], None, True, "gb"),
    ],
)
def test_an_identity_stays_with_a_staged_document_that_kept_its_spelling_only_when_asked(template, tmp_path, docs, identity_url, keep, expected):
    path = _store(template, tmp_path / "a.db", "alpha2", [j for j, _ in docs], urls=[u for _, u in docs])
    _carry(path, "gbr", url=identity_url)
    con = sqlite3.connect(path)
    try:
        out = convert_alternate_countries(con, schema="main", form="alpha2", keep_with_unconverted_document=keep)
        assert json.loads(con.execute("SELECT identity FROM metadata_alternates").fetchone()[0])["jurisdiction"] == expected
        assert out.get("kept_with_document") == (1 if expected == "gbr" else None), "a kept identity is counted, and the count is absent when none was kept"
    finally:
        con.close()


def test_a_carried_alternate_already_kept_for_the_local_row_it_resolves_to_is_not_stored_again(monkeypatch, template, tmp_path):
    """The identity text of one record depends on what else its backup holds (``gbr`` is kept beside a sibling, converted to ``gb`` without one)
    and on how the store spells the document, so the same record is the same ITEM when it lands on the same local row, whatever either spelling:
    a store whose old route kept ``gbr`` already holds this alternate for that document, and a backup that spells it ``gb`` brings nothing new."""
    src = _store(template, tmp_path / "src.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "A1")])
    _carry(src, "gb")
    tgt = _store(template, tmp_path / "tgt.db", "alpha2", ["gbr"], [(0, "hash-a")], summaries=[(0, "m1", "C1")])
    _carry(tgt, "gbr")  # kept for the only summary the store holds (rowid 1)
    counts = _merge(monkeypatch, src, tgt, "alpha2")
    assert counts["metadata_alternates"]["duplicate"] == 1 and counts["metadata_alternates"]["new"] == 0
    assert len(_where_alternates_went(tgt)) == 1


@pytest.mark.parametrize("what", ["origin", "fields"])
def test_an_alternate_of_another_origin_or_field_set_on_the_same_row_is_another_alternate(monkeypatch, template, tmp_path, what):
    """The row alone is not the item: what machine recorded it, and what it says, are part of it."""
    src = _store(template, tmp_path / "src.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "A1")])
    _carry(src, "gb", summary="Z-text" if what == "origin" else "Y-text", origin="machine-Y" if what == "origin" else "machine-Z")
    tgt = _store(template, tmp_path / "tgt.db", "alpha2", ["gbr"], [(0, "hash-a")], summaries=[(0, "m1", "C1")])
    _carry(tgt, "gbr")
    counts = _merge(monkeypatch, src, tgt, "alpha2")
    assert counts["metadata_alternates"]["new"] == 1 and counts["metadata_alternates"]["duplicate"] == 0


def test_one_record_spelled_two_ways_in_one_backup_is_stored_once(monkeypatch, template, tmp_path):
    """Two identities of one backup that name the same document (``uk`` is the catalogue's own spelling and is never converted; ``gb`` is a
    code) resolve to the same row: the second is the first again, within the one restore."""
    src = _store(template, tmp_path / "src.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "A1")])
    _carry(src, "uk")
    _carry(src, "gb")
    tgt = _store(template, tmp_path / "tgt.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "C1")])
    counts = _merge(monkeypatch, src, tgt, "alpha2")
    assert counts["metadata_alternates"]["new"] == 1 and counts["metadata_alternates"]["duplicate"] == 1
    assert len(_where_alternates_went(tgt)) == 1


@pytest.mark.parametrize("form, held, recorded", [("alpha2", ["gbr", "gb"], "gbr"), ("alpha3", ["gb", "GBR"], "gb")])
def test_an_alternate_recorded_against_each_sibling_stays_with_each(monkeypatch, template, tmp_path, form, held, recorded):
    """One document under two spellings is two rows, and a machine that recorded the same alternate (same origin, same field set) against each
    holds two records: both come back, each on the document it was recorded against, restored once or twice."""
    src = _store(template, tmp_path / "src.db", form, held, [(0, "hash-a"), (1, "hash-a")], summaries=[(0, "m1", "A1"), (1, "m1", "A2")])
    _carry(src, held[0])
    _carry(src, held[1])
    again = shutil.copy(src, tmp_path / "src-again.db")
    tgt = _store(template, tmp_path / "tgt.db", form, [])
    counts = _merge(monkeypatch, src, tgt, form)
    assert counts["metadata_alternates"]["new"] == 2 and counts["metadata_alternates"]["duplicate"] == 0
    assert sorted(_where_alternates_went(tgt)) == sorted((j, j, j) for j in held)
    counts = _merge(monkeypatch, Path(again), tgt, form)
    assert counts["metadata_alternates"]["new"] == 0
    assert len(_where_alternates_went(tgt)) == 2


@pytest.mark.parametrize("order", ["BA", "AB"])
def test_the_alternates_a_corpus_ends_with_do_not_depend_on_the_order_its_backups_were_restored(monkeypatch, template, tmp_path, order):
    """Backup B holds the document under two spellings and carries machine A's alternate recorded on the sibling ``gbr``; backup A is machine
    A's own, holding ``gbr`` alone (converted to the store's form, so its own summary lands on ``gb``). The store ends with one alternate on
    each of the two documents it holds, whichever backup came first."""
    tgt = _store(template, tmp_path / "tgt.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "C1")])
    b = _store(template, tmp_path / "b.db", "alpha2", ["gbr", "gb"], [(0, "hash-a"), (1, "hash-a")], summaries=[(0, "m1", "B1"), (1, "m1", "B2")])
    _carry(b, "gbr", summary="A-text", origin="machine-A")
    a = _store(template, tmp_path / "a.db", "alpha2", ["gbr"], [(0, "hash-a")], summaries=[(0, "m1", "A-text")])
    monkeypatch.setattr(cf, "store_form", lambda: "alpha2")
    for which in order:
        meta = {**_META, "origin_fingerprint": f"machine-{which}"}
        merge_corpus(b if which == "B" else a, tgt, meta)
    con = sqlite3.connect(tgt)
    try:
        held = con.execute(
            "SELECT json_extract(m.identity, '$.jurisdiction'), d.jurisdiction FROM metadata_alternates m"
            " JOIN law_revision_summaries s ON s.rowid = m.local_row_id JOIN law_revisions r ON r.id = s.revision_id"
            " JOIN law_documents d ON d.id = r.document_id WHERE m.fields LIKE '%A-text%' ORDER BY d.jurisdiction"
        ).fetchall()
    finally:
        con.close()
    assert sorted(tuple(row) for row in held) == [("gb", "gb"), ("gbr", "gbr")]


@pytest.mark.parametrize(
    "form, local, carried",
    [("alpha2", "gb", "uk"), ("alpha2", "uk", "gb"), ("alpha3", "GBR", "uk"), ("alpha3", "uk", "GBR"), ("alpha2", "gbr", "gb"), ("alpha2", "fra", "fr"), ("alpha2", "euu", "eu")],
)
@pytest.mark.parametrize("order", ["AB", "BA"])
def test_a_record_that_is_both_captured_and_carried_is_stored_once_whichever_arrives_first(monkeypatch, template, tmp_path, form, local, carried, order):
    """Machine A's alternate reaches the store twice: captured, when A's own backup brings a summary that differs from the store's (the capture
    writes the STORE's spelling of the document), and carried, by a third machine's backup (it keeps the spelling its own store used). Both
    name the same row for the same origin and field set, so the second to arrive is the first again, in either order."""
    tgt = _store(template, tmp_path / "c.db", form, [local], [(0, "hash-a")], summaries=[(0, "m1", "C1")])
    b = _store(template, tmp_path / "b.db", form, [carried], [(0, "hash-a")], summaries=[(0, "m1", "B1")])
    _carry(b, carried, summary="A-text", origin="machine-A")
    a = _store(template, tmp_path / "a.db", form, [carried], [(0, "hash-a")], summaries=[(0, "m1", "A-text")])
    monkeypatch.setattr(cf, "store_form", lambda: form)
    for which in order:
        merge_corpus(a if which == "A" else b, tgt, {**_META, "origin_fingerprint": f"machine-{which}"})
    con = sqlite3.connect(tgt)
    try:
        kept = con.execute("SELECT COUNT(*) FROM metadata_alternates WHERE origin = 'machine-A' AND fields LIKE '%A-text%'").fetchone()[0]
    finally:
        con.close()
    assert kept == 1


@pytest.mark.parametrize("what", ["origin", "fields"])
def test_a_summary_the_restore_captures_is_not_hidden_by_an_alternate_of_another_origin_or_field_set_on_the_same_row(monkeypatch, template, tmp_path, what):
    """What the restore captures from a summary that differs is compared with the alternates the store keeps for that row: only one of the
    same origin AND the same field set is the same record."""
    src = _store(template, tmp_path / "src.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "A-text")])
    tgt = _store(template, tmp_path / "tgt.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "C1")])
    _carry(tgt, "gb", summary="A-text" if what == "origin" else "Y-text", origin="machine-Y" if what == "origin" else _META["origin_fingerprint"])
    _merge(monkeypatch, src, tgt, "alpha2")
    con = sqlite3.connect(tgt)
    try:
        captured = con.execute(
            "SELECT COUNT(*) FROM metadata_alternates WHERE origin = ? AND fields LIKE '%A-text%'", (_META["origin_fingerprint"],)
        ).fetchone()[0]
    finally:
        con.close()
    assert captured == 1


def test_a_summary_the_restore_captures_is_not_hidden_by_another_tables_alternate_on_the_same_row_number(monkeypatch, template, tmp_path):
    """The kept alternates the capture compares with are those of the law summaries table: another table's row of the same origin and field
    text that points at the same row number is a different thing (damaged or crafted input; no two tables show the same fields)."""
    src = _store(template, tmp_path / "src.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "A-text")])
    tgt = _store(template, tmp_path / "tgt.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "C1")])
    con = sqlite3.connect(tgt)
    try:
        con.execute(
            "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at)"
            " VALUES (1, 'article_analyses', '{}', 1, ?, '{}', ?, 'pending', '2026-01-01')",
            (json.dumps({"summary": "A-text", "prompt_version": "v1"}, separators=(",", ":")), _META["origin_fingerprint"]),
        )
        con.commit()
    finally:
        con.close()
    _merge(monkeypatch, src, tgt, "alpha2")
    con = sqlite3.connect(tgt)
    try:
        captured = con.execute("SELECT COUNT(*) FROM metadata_alternates WHERE table_name = 'law_revision_summaries'").fetchone()[0]
    finally:
        con.close()
    assert captured == 1


def test_an_alternate_of_another_table_kept_for_the_same_row_number_is_no_duplicate(monkeypatch, template, tmp_path):
    """The kept alternates a law alternate is compared with are those of its own table: another table's row of the same origin and field text
    that points at the same row number is a different thing."""
    src = _store(template, tmp_path / "src.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "A1")])
    _carry(src, "uk")
    tgt = _store(template, tmp_path / "tgt.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "C1")])
    con = sqlite3.connect(tgt)
    try:
        con.execute(
            "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at)"
            " VALUES (1, 'article_analyses', '{}', 1, ?, '{}', 'machine-Z', 'pending', '2026-01-01')",
            (json.dumps({"summary": "Z-text", "prompt_version": "v1"}, separators=(",", ":")),),  # byte for byte the carried alternate's field text
        )
        con.commit()
    finally:
        con.close()
    counts = _merge(monkeypatch, src, tgt, "alpha2")
    assert counts["metadata_alternates"]["new"] == 1 and counts["metadata_alternates"]["duplicate"] == 0


@pytest.mark.parametrize(
    "form, held, recorded",
    [("alpha2", ["gbr", "gb"], "gbr"), ("alpha2", [" gb", "gb"], " gb"), ("alpha3", [" GBR", "GBR"], " GBR")],
)
def test_two_backups_of_one_machine_carry_its_alternate_once_per_document(monkeypatch, template, tmp_path, form, held, recorded):
    """Machine Z's first backup holds the document under two spellings and the alternate on the sibling; its second, after Z deleted the other
    sibling, holds the one spelling, converted to the store's form and so merged into the store-form document. The store holds both documents,
    so it holds the record once on each; the second backup restored again adds nothing."""
    first, tgt = _backup_with_two_spellings(template, tmp_path, form, held, recorded, [])
    _merge(monkeypatch, first, tgt, form)
    second = _store(template, tmp_path / "second.db", form, [recorded], [(0, "hash-a")], summaries=[(0, "m1", "A1")])
    _carry(second, recorded)
    again = shutil.copy(second, tmp_path / "second-again.db")
    _merge(monkeypatch, second, tgt, form)
    went = _where_alternates_went(tgt)
    assert sorted(went) == sorted([(recorded, recorded, recorded), (held[1], held[1], held[1])])
    counts = _merge(monkeypatch, Path(again), tgt, form)
    assert counts["metadata_alternates"]["new"] == 0 and len(_where_alternates_went(tgt)) == 2


def test_the_alternates_already_kept_are_read_once_per_restore_not_once_per_carried_alternate(monkeypatch, template, tmp_path):
    """A restore compares each carried law alternate with what the store keeps; reading the kept ones per carried alternate made a big backup
    over a big store quadratic (17 ms per alternate at 20,000 kept)."""
    src = _store(template, tmp_path / "src.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "A1")])
    for n in range(6):
        _carry(src, "gb", summary=f"Z-{n}")
    tgt = _store(template, tmp_path / "tgt.db", "alpha2", ["gb"], [(0, "hash-a")], summaries=[(0, "m1", "C1")])
    reads = []
    real = merge_mod._q

    def counting(con, sql, params=()):
        if "FROM main.metadata_alternates" in sql and "local_row_id IS NOT NULL" in sql:
            reads.append(sql)
        return real(con, sql, params)

    monkeypatch.setattr(merge_mod, "_q", counting)
    counts = _merge(monkeypatch, src, tgt, "alpha2")
    assert counts["metadata_alternates"]["new"] == 6
    assert len(reads) == 1


@pytest.mark.parametrize("form, held, recorded", [("alpha2", [" gb", "gb"], " gb"), ("alpha3", [" GBR", "GBR"], " GBR")])
def test_an_alternate_recorded_on_a_padded_spelling_stays_with_that_document(monkeypatch, template, tmp_path, form, held, recorded):
    """A padded spelling is a document of its own (it has its own key): the alternate recorded against it is placed on it, and the app finds it there."""
    src, tgt = _backup_with_two_spellings(template, tmp_path, form, held, recorded, [])
    _merge(monkeypatch, src, tgt, form)
    assert _where_alternates_went(tgt) == [(recorded, recorded, recorded)]


@pytest.mark.parametrize("recorded", [5, True, 1.5])
def test_a_carried_identity_whose_jurisdiction_is_not_text_does_not_fail_the_restore(monkeypatch, template, tmp_path, recorded):
    """The identity is untrusted input: a number or a boolean where the jurisdiction goes is no spelling, and is placed like an identity
    with none (the first matching revision), never an error out of the restore or of the app's later lookup."""
    src, tgt = _backup_with_two_spellings(template, tmp_path, "alpha2", ["gb"], "gb", [])
    con = sqlite3.connect(src)
    try:
        con.execute("UPDATE metadata_alternates SET identity = json_set(identity, '$.jurisdiction', ?)", (recorded,))
        con.commit()
    finally:
        con.close()
    counts = _merge(monkeypatch, src, tgt, "alpha2")
    assert counts["metadata_alternates"]["new"] == 1
    assert _where_alternates_went(tgt) == [(recorded, "gb", "gb")]


def test_the_normalise_report_counts_the_identities_kept_with_their_document(template, tmp_path):
    staged = _store(template, tmp_path / "staged.db", "alpha2", ["gbr", "gb"], [(0, "hash-a"), (1, "hash-a")])
    _carry(staged, "gbr")
    live = _store(template, tmp_path / "live.db", "alpha2", [])
    con = sqlite3.connect(live)
    try:
        con.execute("ATTACH DATABASE ? AS inc", (str(staged),))
        report = normalise_staged_country_codes(con, schema="inc")
        assert report["alternates"]["kept_with_document"] == 1 and report["alternates"]["converted"] == 0
    finally:
        con.close()


def test_only_a_law_identity_follows_its_document(template, tmp_path):
    """A country inside the VALUES an alternate shows is converted whatever the staged law documents hold: the rule is about the identity of a
    law item, not about every code that sits beside a url."""
    path = _store(template, tmp_path / "a.db", "alpha2", ["gbr"])
    con = sqlite3.connect(path)
    try:
        con.execute(
            "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at)"
            " VALUES (1, 'places', '{\"place_id\":\"node/1\"}', 1, ?, '{}', 'o', 'pending', '2026-09-01')",
            (json.dumps({"country": "gbr", "document_url": _URL}),),
        )
        convert_alternate_countries(con, schema="main", form="alpha2", keep_with_unconverted_document=True)
        assert json.loads(con.execute("SELECT fields FROM metadata_alternates").fetchone()[0])["country"] == "gb"
    finally:
        con.close()


@pytest.mark.parametrize("old_shape", ["no url column", "no table"])
def test_a_backup_whose_law_documents_cannot_be_asked_by_url_converts_the_identity_and_does_not_fail(tmp_path, old_shape):
    """The staged copy can be an old backup: a law_documents without a url column, or none at all, is answered 'not held' (the identity is
    converted, as before), never an error out of the restore's first step."""
    con = sqlite3.connect(tmp_path / "old.db")
    try:
        if old_shape == "no url column":
            con.execute("CREATE TABLE law_documents (id INTEGER PRIMARY KEY, jurisdiction TEXT)")
            con.execute("INSERT INTO law_documents (jurisdiction) VALUES ('gbr')")
        con.execute("CREATE TABLE metadata_alternates (id INTEGER PRIMARY KEY, table_name TEXT, identity TEXT, fields TEXT)")
        con.execute(
            "INSERT INTO metadata_alternates (table_name, identity, fields) VALUES ('law_revision_summaries', ?, '{}')",
            (json.dumps({"jurisdiction": "gbr", "document_url": _URL}),),
        )
        convert_alternate_countries(con, schema="main", form="alpha2", keep_with_unconverted_document=True)
        assert json.loads(con.execute("SELECT identity FROM metadata_alternates").fetchone()[0])["jurisdiction"] == "gb"
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  the key
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value, key",
    [
        ("fr", "fr"), ("FR", "fr"), ("fra", "fr"), ("FRA", "fr"), ("Fra", "fr"),
        ("uk", "uk"), ("UK", "uk"), ("gb", "uk"), ("GB", "uk"), ("gbr", "uk"), ("GBR", "uk"),
        ("eu", "eu"), ("euu", "eu"), ("EUU", "eu"), ("int", "int"), ("INT", "int"),
        ("zz", "zz"), ("XYZ", "xyz"),
    ],
)
def test_a_code_is_keyed_in_the_catalogues_form(value, key):
    assert law_jurisdiction_key(value) == key


@pytest.mark.parametrize(
    "value", ["france", "georgia", "congo", "england", "mali", "chad", "us-ca", "", " fr", "fr ", "f", "fr1", "é", "ÉU", "x_y"]
)
def test_anything_that_is_not_a_code_is_keyed_as_stored(value):
    assert law_jurisdiction_key(value) == value


def test_an_absent_jurisdiction_has_no_key():
    assert law_jurisdiction_key(None) is None


# --------------------------------------------------------------------------- #
#  ONE definition of "a code" and of its canonical spelling, shared by the writer and the reader
# --------------------------------------------------------------------------- #
def test_the_add_route_and_the_restore_share_one_canonicaliser():
    """A second copy of the shape or of the call is how the route and the restore come to disagree about one jurisdiction (the defect this file is
    about), so the route reads both from the module the restore reads them from."""
    src = (Path(__file__).resolve().parent.parent / "src" / "api" / "law.py").read_text(encoding="utf-8")
    assert "from src.backup.country_codes import LAW_JURISDICTION_CODE, law_jurisdiction_key" in src
    assert "law_jurisdiction_key(typed)" in src
    assert "re.compile" not in src, "the route must not carry a private copy of the code shape"
    assert "law_jurisdiction(" not in src, "the route must not call the catalogue's function beside the shared key"
