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
* the key itself, for every spelling and for the strings that are not codes.
* the route that pastes a document and the restore read the code shape and the canonical spelling from the one module, so the writer and the
  reader cannot drift apart again.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup import alternates  # noqa: E402
from src.backup import merge as merge_mod  # noqa: E402
from src.backup.country_codes import law_jurisdiction_key  # noqa: E402
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
    """The same ordering in three places (the merge's id map, its placing of an alternate, the app's later lookup): the document spelled exactly as the
    identity says, else the oldest document. Two rules would show the operator the review of one document and swap another's summary."""
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
