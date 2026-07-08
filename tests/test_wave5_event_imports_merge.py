"""
Wave 5 L (backend): ``event_imports`` restore parity + the post-swap durable-mirror refresh.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Imported calendar events have TWO representations of the SAME data:
  * the authoritative ``calendar_feed_imports.json`` side-file (the merge target), and
  * the durable, encrypted, backup-carried ``event_imports`` TABLE — a FULL-REPLACE mirror.

DESIGN DECISION proven here (Wave 5 L, the deferred D1 follow-up): ``event_imports`` STAYS
side-file-authoritative (``_MERGE_IGNORED``) instead of gaining a native ``_MERGE_HANDLED``
table handler. A table handler would (1) DOUBLE-ACCOUNT the same events in a restore report
(once in ``plan`` as rows, once in ``side_files`` as JSON entries) and (2) apply ``local-wins``
row semantics that DIVERGE from the side-file's ``union sources/uids`` semantics — which wins
regardless, being the source of truth. Restore correctness is sacred: honest deferral beats a
double-count bug. The TRUE native merge is the larger D1 follow-up that retires the JSON.

What Wave 5 L DOES add is ``merge._refresh_event_mirror`` in the restore commit path: the
side-file merge unions the JSON with ``mirror=False`` PRE-swap (the still-live OLD DB must stay
byte-identical — torture T1/T7), so without a refresh the durable table would stay STALE after
a restore until the next calendar write. The refresh full-replaces the table from the merged
JSON POST-swap, so the table converges to the authoritative JSON with zero double-count.

Isolation: monkeypatched ``feeds.data_dir`` / ``event_store._db_path`` / throwaway SQLite
corpora, and a subprocess round-trip with its own ``OO_DATA_DIR``. Never ``SessionLocal``
(the cross-test-pollution rule).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.backup.merge as merge
from src.database.models import Base, EventImport, SourceCandidate

_REPO = Path(__file__).resolve().parents[1]
_HELPER = _REPO / "tests" / "torture_helper.py"

# A holidays family (system) + a user calendar; the two representations flatten to 3 rows.
_LOCAL = {
    "holidays": {
        "name": "Holidays", "imported_at": "2026-01-01T00:00:00",
        "events": {
            "fp-shared": {"title": "New Year", "date": "2026-01-01",
                          "sources": ["feedA"], "uids": ["uA"]},
            "fp-A": {"title": "Only A day", "date": "2026-07-01",
                     "sources": ["feedA"], "uids": []},
        },
    },
    "user-A": {
        "name": "My calendar", "user": True, "imported_at": "2026-02-02T00:00:00",
        "events": {
            "fp-mine": {"title": "Dentist", "date": "2026-03-03",
                        "sources": ["user-A"], "uids": []},
        },
    },
}
# The incoming corpus shares fp-shared (with a DIFFERENT title/date + a new source/uid),
# adds fp-B, and knows nothing of the user calendar.
_INCOMING = {
    "holidays": {
        "name": "Holidays", "imported_at": "2026-01-05T00:00:00",
        "events": {
            "fp-shared": {"title": "NYE variant (incoming)", "date": "2025-12-31",
                          "sources": ["feedB"], "uids": ["uB"]},
            "fp-B": {"title": "Only B day", "date": "2026-08-01",
                     "sources": ["feedB"], "uids": []},
        },
    },
}

_MERGED_ACTION = {"state": {"calendar_feed_imports.json": {"action": "merged"}}}


@pytest.fixture()
def isolated_stores(tmp_path, monkeypatch):
    """Point BOTH representations at throwaway locations: the JSON side-file at ``tmp_path``
    and the durable mirror table at an isolated SQLite file (self-heal creates the table)."""
    from src.events import event_store, feeds

    monkeypatch.setattr(feeds, "data_dir", lambda: tmp_path)
    db = tmp_path / "corpus.db"
    monkeypatch.setattr(event_store, "_db_path", lambda: str(db))
    return feeds, event_store


# --------------------------------------------------------------------------- #
#  A. The side-file UNION-merge: additive, zero-dup, zero-loss, local wins.
# --------------------------------------------------------------------------- #
def test_incoming_events_merge_additively_zero_dup_zero_loss(isolated_stores):
    feeds, _ = isolated_stores
    feeds._save_json("calendar_feed_imports.json", _LOCAL, mirror=False)  # seed local JSON

    res = feeds.merge_imported_store("calendar_feed_imports.json", _INCOMING)

    # fp-B is genuinely new; fp-shared is kept-local but its incoming source enriches it.
    assert res == {"action": "merged", "added": 1, "enriched": 1, "kept_local": 1}

    merged = feeds.load_imports()
    # Zero loss: every local family + event survives, plus the incoming addition.
    assert set(merged["holidays"]["events"]) == {"fp-shared", "fp-A", "fp-B"}
    assert set(merged["user-A"]["events"]) == {"fp-mine"}
    # Zero dup: fp-shared appears exactly once (keyed by fingerprint, not summed).
    assert list(merged["holidays"]["events"]).count("fp-shared") == 1


def test_local_wins_on_a_shared_event_but_sources_and_uids_union(isolated_stores):
    feeds, _ = isolated_stores
    feeds._save_json("calendar_feed_imports.json", _LOCAL, mirror=False)

    feeds.merge_imported_store("calendar_feed_imports.json", _INCOMING)
    shared = feeds.load_imports()["holidays"]["events"]["fp-shared"]

    # Local title/date WIN (the incoming variant is never adopted).
    assert shared["title"] == "New Year"
    assert shared["date"] == "2026-01-01"
    # Sources + uids are the additive UNION (more provenance is never a conflict).
    assert sorted(shared["sources"]) == ["feedA", "feedB"]
    assert sorted(shared["uids"]) == ["uA", "uB"]


# --------------------------------------------------------------------------- #
#  B. The post-swap durable-mirror refresh: convergence, no double-count, guards.
# --------------------------------------------------------------------------- #
def test_side_file_merge_leaves_the_durable_table_stale_then_refresh_fixes_it(isolated_stores):
    """Reproduces the wart AND the fix in one flow: the side-file union does NOT touch the
    durable table (mirror=False, pre-swap), so it stays stale; the refresh converges it."""
    feeds, event_store = isolated_stores
    feeds._save_json("calendar_feed_imports.json", _LOCAL, mirror=True)  # live machine: JSON+table
    assert event_store.count() == 3  # fp-shared, fp-A, fp-mine

    # The restore's side-file union (mirror=False) advances the JSON but NOT the table.
    feeds.merge_imported_store("calendar_feed_imports.json", _INCOMING)
    assert event_store.count() == 3, "side-file merge must not touch the durable table pre-swap"

    # The post-swap refresh full-replaces the mirror from the authoritative merged JSON.
    status = merge._refresh_event_mirror(_MERGED_ACTION)
    assert status == {"synced": True, "rows": 4}  # + fp-B (fp-mine/fp-shared/fp-A already there)
    # PARITY / CONVERGENCE: the durable table now equals the authoritative JSON exactly.
    assert event_store.load_imports() == feeds.load_imports()
    assert event_store.count() == 4


def test_refresh_is_idempotent_and_never_double_counts(isolated_stores):
    feeds, event_store = isolated_stores
    feeds._save_json("calendar_feed_imports.json", _LOCAL, mirror=True)
    feeds.merge_imported_store("calendar_feed_imports.json", _INCOMING)

    first = merge._refresh_event_mirror(_MERGED_ACTION)
    snapshot = event_store.load_imports()
    # Re-merging the SAME incoming is a no-op union; a second refresh must converge, not grow.
    again = feeds.merge_imported_store("calendar_feed_imports.json", _INCOMING)
    assert again["added"] == 0
    second = merge._refresh_event_mirror(_MERGED_ACTION)

    assert first == second == {"synced": True, "rows": 4}
    assert event_store.count() == 4
    assert event_store.load_imports() == snapshot  # bit-for-bit stable, no double-count


def test_refresh_is_a_no_op_when_no_calendar_side_file_was_merged(isolated_stores):
    # None keeps the report from growing an ``event_mirror`` field when it does not apply.
    assert merge._refresh_event_mirror({}) is None
    assert merge._refresh_event_mirror({"state": {}}) is None
    assert merge._refresh_event_mirror(
        {"state": {"app_settings.json": {"action": "kept-local"}}}
    ) is None
    # Present but not actually merged (e.g. unreadable in the artifact) -> still a no-op.
    assert merge._refresh_event_mirror(
        {"state": {"calendar_feed_imports.json": {"action": "skipped"}}}
    ) is None


def test_refresh_never_empties_a_populated_table_on_a_read_hiccup(isolated_stores, monkeypatch):
    """A JSON read that fails returns {} — the refresh must NOT then DELETE a populated
    mirror (the JSON stays authoritative; the mirror re-syncs on the next calendar write)."""
    feeds, event_store = isolated_stores
    event_store.sync_imports(_LOCAL)
    assert event_store.count() == 3

    monkeypatch.setattr(feeds, "load_imports", lambda: {})  # simulate an unreadable side-file
    status = merge._refresh_event_mirror(_MERGED_ACTION)

    assert status == {"synced": False, "reason": "empty read guarded"}
    assert event_store.count() == 3, "a read hiccup must never wipe the durable mirror"


# --------------------------------------------------------------------------- #
#  C. The restore report stays clean, and the deferral decision is pinned.
# --------------------------------------------------------------------------- #
def _build_corpus(path: Path, *, events: list[dict], candidates: list[dict]) -> None:
    """A throwaway plaintext SQLite corpus with the full schema + the given rows."""
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with sessionmaker(bind=engine, future=True)() as s:
        for e in events:
            s.add(EventImport(
                family_key=e["family_key"], fingerprint=e["fingerprint"],
                family_name=e.get("family_name"), title=e.get("title"),
                date=e.get("date"), sources=e.get("sources"), uids=e.get("uids"),
                updated_at=now,
            ))
        for c in candidates:
            s.add(SourceCandidate(
                domain=c["domain"], channel=c.get("channel", "citation"),
                suggested_name=c.get("suggested_name"), status=c.get("status", "candidate"),
            ))
        s.commit()
    engine.dispose()


def _count_rows(path: Path, table: str) -> int:
    engine = create_engine(f"sqlite:///{path}", future=True)
    try:
        with engine.connect() as c:
            from sqlalchemy import text
            return int(c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
    finally:
        engine.dispose()


def test_merge_does_not_report_event_imports_as_unmerged_even_with_incoming_rows(tmp_path):
    """The incoming corpus's ``event_imports`` mirror rows must never surface as an
    ``_unmerged_tables`` entry (they are redundant with the side-file). A handled sibling
    table (``source_candidates``) merging proves the report is live, not vacuously empty."""
    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"
    _build_corpus(working, events=[], candidates=[])
    _build_corpus(
        staged,
        events=[{"family_key": "holidays", "fingerprint": "fp-B", "title": "Only B",
                 "date": "2026-08-01", "sources": "[\"feedB\"]", "uids": "[]"}],
        candidates=[{"domain": "incoming.example", "suggested_name": "Incoming"}],
    )
    assert _count_rows(staged, "event_imports") == 1  # the rows really are present in inc

    counts, _batch = merge.merge_corpus(
        staged, working,
        {"artifact_kind": "oo-backup-2", "origin_fingerprint": "test",
         "app_version": "0.1.0", "alembic_rev": "head", "manifest": None},
    )

    # Report is CLEAN: event_imports is neither a merged domain nor an "unmerged table".
    assert "event_imports" not in counts.get("_unmerged_tables", {})
    assert "event_imports" not in counts
    # The merge is genuinely live: a handled sibling table merged its new row.
    assert counts["source_candidates"]["new"] == 1
    # And the ignored table was left untouched in the working copy (side-file-authoritative).
    assert _count_rows(working, "event_imports") == 0


def test_event_imports_stays_side_file_authoritative_by_design():
    # The Wave 5 L decision, pinned: ignored (side-file-authoritative), NOT a native handler.
    assert "event_imports" in merge._MERGE_IGNORED
    assert "event_imports" not in merge._MERGE_HANDLED


def test_ignoring_event_imports_does_not_blind_the_unmerged_tables_safety_net(tmp_path):
    """Stretch guard: ``event_imports`` being ignored must NOT punch a hole in the report's
    safety net — a genuinely-unhandled table (neither handled nor ignored) with rows is still
    LOUDLY reported, so nothing is ever silently dropped by a restore."""
    import sqlite3

    working = tmp_path / "working.db"
    staged = tmp_path / "staged.db"
    _build_corpus(working, events=[], candidates=[])
    _build_corpus(
        staged,
        events=[{"family_key": "holidays", "fingerprint": "fp-X", "title": "X"}],
        candidates=[],
    )
    # A table the merge knows nothing about, with a row, planted in the incoming corpus.
    con = sqlite3.connect(staged)
    try:
        con.execute("CREATE TABLE zzz_unhandled (id INTEGER PRIMARY KEY, payload TEXT)")
        con.execute("INSERT INTO zzz_unhandled (payload) VALUES ('surprise')")
        con.commit()
    finally:
        con.close()

    counts, _batch = merge.merge_corpus(
        staged, working,
        {"artifact_kind": "oo-backup-2", "origin_fingerprint": "test",
         "app_version": "0.1.0", "alembic_rev": "head", "manifest": None},
    )

    unmerged = counts.get("_unmerged_tables", {})
    assert unmerged.get("zzz_unhandled") == 1, "an unknown table with rows must be reported"
    assert "event_imports" not in unmerged, "the ignored mirror table must stay out of the report"


# --------------------------------------------------------------------------- #
#  D. Full run_restore round-trip (subprocess, its own OO_DATA_DIR).
# --------------------------------------------------------------------------- #
def _helper(data_dir: Path, *args: str) -> dict:
    env = dict(os.environ, OO_DATA_DIR=str(data_dir), OO_NO_SCHEDULER="1", OO_DB_PLAINTEXT="1")
    proc = subprocess.run(
        [sys.executable, str(_HELPER), *args],
        capture_output=True, text=True, cwd=str(_REPO), env=env, timeout=180,
    )
    assert proc.returncode == 0, f"helper failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _inspect_events(data_dir: Path) -> dict:
    """Read the JSON side-file + the durable mirror table in the SAME OO_DATA_DIR."""
    code = (
        "import json, os;"
        "from src.events.event_store import load_imports, count;"
        "p=os.path.join(os.environ['OO_DATA_DIR'],'calendar_feed_imports.json');"
        "js=json.load(open(p)) if os.path.exists(p) else {};"
        "print(json.dumps({'json_events': sorted(js.get('holidays',{}).get('events',{}).keys()),"
        "'shared_sources': sorted(js.get('holidays',{}).get('events',{}).get('fp-shared',{}).get('sources',[])),"
        "'table_count': count(), 'table_equals_json': load_imports()==js}))"
    )
    env = dict(os.environ, OO_DATA_DIR=str(data_dir), OO_NO_SCHEDULER="1", OO_DB_PLAINTEXT="1")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(_REPO), env=env, timeout=120)
    assert proc.returncode == 0, f"inspect failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(
    sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness"
)
def test_full_restore_round_trip_refreshes_the_durable_event_table(tmp_path):
    """End-to-end through the REAL commit path (build A + build B artifact + restore): the
    events merge additively via the side-file AND the durable mirror is fresh (== JSON)
    afterwards, the report is clean, and a second restore is idempotent."""
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    art = tmp_path / "corpusB.oobak.ooenc"
    assert _helper(b, "build", "B", "--artifact", str(art), "--passphrase", "pw-w5",
                   "--custody", "ok").get("artifact")
    _helper(a, "build", "A", "--custody", "ok")

    report = _helper(a, "merge", str(art), "--passphrase", "pw-w5", "--commit")["report"]
    assert report["committed"] is True
    # The side-file merged the incoming events, and the post-swap refresh synced the mirror.
    assert report["side_files"]["state"]["calendar_feed_imports.json"]["action"] == "merged"
    assert report["event_mirror"]["synced"] is True
    # Clean report: the mirror table is never an "unmerged table".
    assert "event_imports" not in report["plan"].get("_unmerged_tables", {})

    got = _inspect_events(a)
    # Additive union in the authoritative JSON (both corpora's unique days + the shared one).
    assert got["json_events"] == ["fp-A", "fp-B", "fp-shared"]
    assert got["shared_sources"] == ["feedA", "feedB"]  # local wins + sources unioned
    # The durable, backup-carried table is FRESH after restore and equals the JSON (parity).
    assert got["table_count"] == 3
    assert got["table_equals_json"] is True

    # Idempotent: a second restore of the same artifact converges (no growth, table stable).
    report2 = _helper(a, "merge", str(art), "--passphrase", "pw-w5", "--commit")["report"]
    news = {k: v["new"] for k, v in report2["plan"].items()
            if isinstance(v, dict) and v.get("new")}
    assert news == {}, f"a re-restore created rows: {news}"
    got2 = _inspect_events(a)
    assert got2 == got, "the durable mirror must be stable across an idempotent re-restore"
