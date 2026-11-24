"""Row 405 (R824 step 1): the carry records the stage version and where carried rows came from, and says WHY a stamp did not match.

Built on R412/R415, which already made the engine id a hash of a hand-bumped version per stage (``INDEXER_VERSION``,
``WWW_INDEXER_VERSION``). What R824 adds and these tests pin:

* every stamp records its stage version, and a carried stamp the batch that carried it (``carried_from_batch``); a re-index on this
  machine writes NULL there again, so no surface counts carried rows as extracted here;
* a recorded stage version other than this machine's, or one that is not a number, is not matching: nothing is carried on a guess;
* ``index_engines`` records what each engine id is a hash of, and the carry report names EVERY component an incoming stamp differs in,
  with article counts, and counts a stamp it cannot explain as "could not be read", never under a guessed component;
* the re-index backlog gives three counts per stage: carried, extracted here, awaiting.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from sqlalchemy import text

from src.analytics.engine_identity import (
    INDEXER_VERSION,
    STAGE_VERSIONS,
    STAMP_PREFIX,
    WWW_INDEXER_VERSION,
    baseline_engine_id,
    component_differences,
    engine_components,
    recorded_components,
    www_engine_id,
)
from src.analytics.extract import get_extractor
from src.analytics.store import index_article
from src.backup.merge import _BACKLOG_SQL, _STATUS_MERGED, _stage_counts
from src.database.models import Article
from tests import test_derived_carry as _dc
from tests.test_derived_carry import _N, _merge_only, _restore, _scalar, _schema, _session, _variant

#: The module fixture, used by name (assigned rather than imported, so a test's ``backup`` parameter does not read as a redefinition).
backup = _dc.backup


def test_the_stage_versions_are_the_two_hand_bumped_constants():
    assert STAGE_VERSIONS == {"kw": INDEXER_VERSION, "www": WWW_INDEXER_VERSION}


def test_every_stamp_records_its_stage_version_and_its_engine(backup):
    assert _scalar(backup, "SELECT COUNT(*) FROM article_index_stamps WHERE stage_version = ?", INDEXER_VERSION) == _N
    assert _scalar(backup, "SELECT COUNT(*) FROM article_www_stamps WHERE stage_version = ?", WWW_INDEXER_VERSION) == _N
    assert _scalar(backup, "SELECT COUNT(*) FROM article_index_stamps WHERE carried_from_batch IS NOT NULL") == 0
    con = sqlite3.connect(backup)
    try:
        rows = dict(con.execute("SELECT engine, components FROM index_engines").fetchall())
        stages = dict(con.execute("SELECT engine, stage FROM index_engines").fetchall())
    finally:
        con.close()
    assert set(rows) == {baseline_engine_id(), www_engine_id()}
    assert stages == {baseline_engine_id(): "kw", www_engine_id(): "www"}
    for engine, blob in rows.items():
        assert recorded_components(engine, blob) is not None, "a recorded row recomputes to its own id"


def test_a_carried_stamp_names_its_batch_and_a_re_index_here_clears_it(backup, tmp_path, monkeypatch):
    counts, batch_id, working = _merge_only(backup, tmp_path, monkeypatch)
    assert counts["_derived_carry"]["carried"]["articles"] == _N
    for table, version in (("article_index_stamps", INDEXER_VERSION), ("article_www_stamps", WWW_INDEXER_VERSION)):
        assert _scalar(working, f"SELECT COUNT(*) FROM {table} WHERE carried_from_batch = ? AND stage_version = ?", batch_id, version) == _N  # noqa: S608
    engine, s = _session(working)
    try:
        aid = int(s.execute(text("SELECT MIN(article_id) FROM article_index_stamps")).scalar())
        index_article(s, s.get(Article, aid), extractor=get_extractor("baseline"))
    finally:
        s.close()
        engine.dispose()
    for table in ("article_index_stamps", "article_www_stamps"):
        assert _scalar(working, f"SELECT carried_from_batch FROM {table} WHERE article_id = ?", aid) is None  # noqa: S608
        assert _scalar(working, f"SELECT COUNT(*) FROM {table} WHERE carried_from_batch = ?", batch_id) == _N - 1  # noqa: S608


def test_another_recorded_stage_version_is_not_carried(backup, tmp_path, monkeypatch):
    variant = _variant(backup, tmp_path, "v.db", f"UPDATE article_index_stamps SET stage_version = {INDEXER_VERSION + 1}")
    out = _restore(variant, _empty(tmp_path), tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    plan = out["counts"]["_derived_carry"]
    assert plan["refused"]["stage_version"] == _N
    assert plan["planned"] == 0 and plan["www_planned"] == _N, "the places and entities still carry on their own stamp"


def test_an_unreadable_stage_version_is_not_carried(backup, tmp_path, monkeypatch):
    variant = _variant(backup, tmp_path, "v.db", "UPDATE article_www_stamps SET stage_version = 'three'")
    out = _restore(variant, _empty(tmp_path), tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    plan = out["counts"]["_derived_carry"]
    assert plan["refused"]["www_stage_version"] == _N
    assert plan["www_planned"] == 0 and plan["planned"] == _N


def test_a_stamp_from_before_the_column_still_carries_through_its_engine_id(backup, tmp_path, monkeypatch):
    variant = _variant(
        backup, tmp_path, "v.db",
        "UPDATE article_index_stamps SET stage_version = NULL", "UPDATE article_www_stamps SET stage_version = NULL",
    )
    out = _restore(variant, _empty(tmp_path), tmp_path / "w.db", carry=True, monkeypatch=monkeypatch)
    assert out["counts"]["_derived_carry"]["carried"]["articles"] == _N


def _empty(tmp_path: Path) -> Path:
    target = tmp_path / "empty.db"
    if not target.exists():
        _schema(target)
    return target


def _foreign_record(**changes) -> tuple[str, str]:
    """An engine id and the components it is a hash of, for this machine's keyword engine with ``changes`` applied."""
    comps = engine_components(extractor_name="baseline")
    for key, value in changes.items():
        if ":" in key:
            outer, inner = key.split(":", 1)
            comps[outer] = {**comps[outer], inner: value}
        else:
            comps[key] = value
    blob = json.dumps(comps, sort_keys=True, separators=(",", ":"))
    return STAMP_PREFIX + hashlib.sha256(blob.encode()).hexdigest()[:32], blob


def test_the_report_names_every_component_that_differs_with_counts(backup, tmp_path, monkeypatch):
    engine, blob = _foreign_record(indexer=INDEXER_VERSION - 1, **{"distributions:simplemma": None})
    variant = _variant(
        backup, tmp_path, "v.db",
        f"UPDATE article_index_stamps SET engine = '{engine}'",
        "DELETE FROM index_engines WHERE stage = 'kw'",
    )
    con = sqlite3.connect(variant)
    con.execute("INSERT INTO index_engines (engine, stage, components) VALUES (?, 'kw', ?)", (engine, blob))
    con.commit()
    con.close()
    counts, _b, _w = _merge_only(variant, tmp_path, monkeypatch)
    diff = counts["_derived_carry"]["differences"]
    assert diff == {
        "available": True, "articles": _N, "could_not_be_read": 0,
        "components": {"indexer": _N, "distributions:simplemma": _N},
    }
    assert counts["_derived_carry"]["www_differences"]["articles"] == 0
    assert "2.0" not in json.dumps(diff), "a component's value never rides the report, only its name"


def test_a_stamp_the_backup_cannot_explain_is_could_not_be_read(backup, tmp_path, monkeypatch):
    engine, blob = _foreign_record(indexer=INDEXER_VERSION - 1)
    forged = blob.replace(f'"indexer":{INDEXER_VERSION - 1}', f'"indexer":{INDEXER_VERSION - 2}')
    for name, statements in (
        ("norecord.db", (f"UPDATE article_index_stamps SET engine = '{engine}'", "DROP TABLE index_engines")),
        ("forged.db", (f"UPDATE article_index_stamps SET engine = '{engine}'",
                       f"INSERT INTO index_engines (engine, stage, components) VALUES ('{engine}', 'kw', '{forged}')")),
        ("garbage.db", (f"UPDATE article_index_stamps SET engine = '{engine}'",
                        f"INSERT INTO index_engines (engine, stage, components) VALUES ('{engine}', 'kw', 'not json')")),
    ):
        variant = _variant(backup, tmp_path, name, *statements)
        counts, _b, _w = _merge_into(variant, tmp_path, name, monkeypatch)
        diff = counts["_derived_carry"]["differences"]
        assert diff["could_not_be_read"] == _N and diff["components"] == {}, (name, diff)


def _merge_into(variant: Path, tmp_path: Path, name: str, monkeypatch) -> tuple:
    sub = tmp_path / ("m-" + name.split(".")[0])
    sub.mkdir()
    return _merge_only(variant, sub, monkeypatch)


def test_component_differences_name_inner_keys_and_every_top_level_key():
    a = {"indexer": 3, "distributions": {"jieba": "1", "simplemma": None}, "python": "3.13"}
    b = {"indexer": 2, "distributions": {"jieba": "1", "simplemma": "2"}, "python": "3.13", "unicode": "15"}
    assert component_differences(a, b) == ["distributions:simplemma", "indexer", "unicode"]


def test_a_name_only_the_backup_holds_is_never_copied_into_the_report():
    local = {"indexer": 3, "distributions": {"jieba": "1"}}
    incoming = {"indexer": 3, "distributions": {"jieba": "1", "<b>x</b>": "1"}, "](http://x)": 1}
    assert component_differences(incoming, local) == ["distributions:unrecognised", "unrecognised"]


def test_the_backlog_counts_carried_extracted_here_and_awaiting_per_stage(backup, tmp_path, monkeypatch):
    variant = _variant(backup, tmp_path, "half.db", "DELETE FROM article_www_stamps")
    _counts, batch_id, working = _merge_only(variant, tmp_path, monkeypatch)
    con = sqlite3.connect(working)
    try:
        row = con.execute(
            _BACKLOG_SQL,
            {"s": _STATUS_MERGED, "engine": baseline_engine_id(), "kw_legacy": baseline_engine_id(), "www_engine": www_engine_id()},
        ).fetchone()
    finally:
        con.close()
    assert row[0] == batch_id and row[2] == _N and row[3] == 0
    assert _stage_counts(row) == {
        "kw": {"carried": _N, "extracted_here": 0, "not_recorded": 0, "awaiting": 0},
        "www": {"carried": 0, "extracted_here": 0, "not_recorded": 0, "awaiting": _N},
    }
    assert _stage_counts(row, lost=2)["www"]["awaiting"] == _N - 2, "a stand-in is never re-indexed, so it never awaits"


def test_a_stamp_older_than_the_record_is_not_claimed_as_extracted_here(backup, tmp_path, monkeypatch):
    # The www half is left out so the batch stays pending (a batch carried whole is complete and leaves the backlog).
    variant = _variant(backup, tmp_path, "half.db", "DELETE FROM article_www_stamps")
    _counts, _batch_id, working = _merge_only(variant, tmp_path, monkeypatch)
    con = sqlite3.connect(working)
    try:
        con.execute("UPDATE article_index_stamps SET stage_version = NULL, carried_from_batch = NULL")
        con.commit()
        row = con.execute(
            _BACKLOG_SQL,
            {"s": _STATUS_MERGED, "engine": baseline_engine_id(), "kw_legacy": baseline_engine_id(), "www_engine": www_engine_id()},
        ).fetchone()
    finally:
        con.close()
    assert _stage_counts(row) == {
        "kw": {"carried": 0, "extracted_here": 0, "not_recorded": _N, "awaiting": 0},
        "www": {"carried": 0, "extracted_here": 0, "not_recorded": 0, "awaiting": _N},
    }


def test_the_carry_records_this_machines_own_engines(backup, tmp_path, monkeypatch):
    counts, _batch_id, working = _merge_only(backup, tmp_path, monkeypatch)
    assert counts["_derived_carry"]["carried"]["articles"] == _N
    con = sqlite3.connect(working)
    try:
        rows = dict(con.execute("SELECT engine, components FROM index_engines").fetchall())
    finally:
        con.close()
    assert set(rows) == {baseline_engine_id(), www_engine_id()}
    for engine, blob in rows.items():
        assert recorded_components(engine, blob) is not None


def test_a_hostile_engine_record_never_fails_the_merge(backup, tmp_path, monkeypatch):
    """Invalid UTF-8, a BLOB, an oversized text: each is "could not be read", and the restore goes on (security read A, MUST)."""
    engine, _blob = _foreign_record(indexer=INDEXER_VERSION - 1)
    for name, value in (
        ("badutf8.db", "CAST(X'7B22696E6465786572223AFF7D' AS TEXT)"),
        ("blob.db", "X'7B7D'"),
        ("huge.db", "'{\"x\":\"' || hex(zeroblob(40000)) || '\"}'"),
    ):
        variant = _variant(
            backup, tmp_path, name,
            f"UPDATE article_index_stamps SET engine = '{engine}'",
            f"INSERT INTO index_engines (engine, stage, components) VALUES ('{engine}', 'kw', {value})",
        )
        counts, _b, _w = _merge_into(variant, tmp_path, name, monkeypatch)
        diff = counts["_derived_carry"]["differences"]
        assert diff["could_not_be_read"] == _N and diff["components"] == {}, (name, diff)


def test_an_old_schema_store_gains_the_columns_and_indexes(backup, tmp_path):
    """The live store never goes through alembic: boot's self-heal adds the two columns, and index_article then stamps (security read B)."""
    import shutil

    from src.database.maintenance import ensure_stamp_provenance_columns

    path = tmp_path / "old.db"
    shutil.copyfile(backup, path)
    con = sqlite3.connect(path)
    for table in ("article_index_stamps", "article_www_stamps"):
        con.execute(f"ALTER TABLE {table} DROP COLUMN stage_version")  # noqa: S608
        con.execute(f"ALTER TABLE {table} DROP COLUMN carried_from_batch")  # noqa: S608
    con.commit()
    con.close()
    engine, s = _session(path)
    try:
        assert sorted(ensure_stamp_provenance_columns(engine)) == [
            "article_index_stamps.carried_from_batch", "article_index_stamps.stage_version",
            "article_www_stamps.carried_from_batch", "article_www_stamps.stage_version",
        ]
        assert ensure_stamp_provenance_columns(engine) == [], "idempotent"
        aid = int(s.execute(text("SELECT MIN(id) FROM articles")).scalar())
        index_article(s, s.get(Article, aid), extractor=get_extractor("baseline"))
    finally:
        s.close()
        engine.dispose()
    assert _scalar(path, "SELECT stage_version FROM article_index_stamps WHERE article_id = ?", aid) == INDEXER_VERSION
    assert _scalar(path, "SELECT COUNT(*) FROM article_index_stamps WHERE stage_version IS NULL") == _N - 1, "no backfill"


def test_a_hostile_stamp_engine_never_fails_the_merge_nor_reaches_the_plan(backup, tmp_path, monkeypatch):
    """A stamp engine that is not UTF-8, or is long, once stopped the restore in the engine mix (row 405's delta read): now counted."""
    for name, value in (("badengine.db", "CAST(X'FFFE41' AS TEXT)"), ("longengine.db", "'e1-' || hex(zeroblob(5000))")):
        variant = _variant(backup, tmp_path, name, f"UPDATE article_index_stamps SET engine = {value}")
        counts, _b, _w = _merge_into(variant, tmp_path, name, monkeypatch)
        plan = counts["_derived_carry"]
        assert plan["incoming_engines"] == [] and plan["incoming_engines_unreadable"] == _N, (name, plan)
        assert plan["differences"]["could_not_be_read"] == _N, (name, plan["differences"])
        assert "zeroblob" not in json.dumps(plan) and "0000000000" not in json.dumps(plan)
