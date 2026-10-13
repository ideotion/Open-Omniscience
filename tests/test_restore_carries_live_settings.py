"""A restore carries the live settings into the copy it swaps in, so a later write is never thrown away.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``app_state`` is not merged on restore (local wins entirely), so the settings that come out of a
swap were whatever the SNAPSHOT held. A write made to the live file after the snapshot (a legacy
settings file migrated by a read, a setting saved during a long import, or anything since the first
item's snapshot in a checkpoint group, whose working copy is CARRIED and takes none) was thrown away
by the swap. ``_carry_live_settings`` reads the live rows just before the swap and writes them over
the working copy's: upsert only, a failure changes nothing and says its class.
"""

from __future__ import annotations

import ast
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import src.backup.merge as merge
import src.backup.sqlite_backup as sqlite_backup

_MERGE_PY = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"


def _file(path: Path, rows: dict[str, str] | None) -> Path:
    con = sqlite3.connect(path)
    try:
        if rows is not None:
            con.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)")
            for k, v in rows.items():
                con.execute("INSERT INTO app_state VALUES (?, ?, '2026-10-13 00:00:00')", (k, v))
        else:
            con.execute("CREATE TABLE other (x)")
        con.commit()
    finally:
        con.close()
    return path


def _rows(path: Path) -> dict[str, str]:
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT key, value FROM app_state"))
    finally:
        con.close()


@pytest.fixture
def live_at(monkeypatch):
    def point(path: Path) -> None:
        monkeypatch.setattr(sqlite_backup, "live_db_path", lambda: path)

    return point


def test_a_row_written_to_the_live_file_after_the_snapshot_reaches_the_copy(tmp_path, live_at):
    working = _file(tmp_path / "working.db", {"settings.app": '{"v": 1}'})
    live = _file(tmp_path / "live.db", {"settings.app": '{"v": 1}', "settings.migrated": '{"m": 1}'})
    live_at(live)

    out = merge._carry_live_settings(working)

    assert out == {"carried": 1, "of": 2}
    assert _rows(working) == {"settings.app": '{"v": 1}', "settings.migrated": '{"m": 1}'}


def test_a_setting_saved_since_the_snapshot_replaces_the_snapshots_value(tmp_path, live_at):
    working = _file(tmp_path / "working.db", {"settings.app": '{"v": "old"}'})
    live_at(_file(tmp_path / "live.db", {"settings.app": '{"v": "new"}'}))

    assert merge._carry_live_settings(working) == {"carried": 1, "of": 1}
    assert _rows(working) == {"settings.app": '{"v": "new"}'}


def test_a_key_only_the_copy_has_is_kept_never_deleted(tmp_path, live_at):
    """Upsert only: a partial or failed read must never wipe a setting."""
    working = _file(tmp_path / "working.db", {"settings.gone": "1", "settings.app": "a"})
    live_at(_file(tmp_path / "live.db", {"settings.app": "a"}))

    assert merge._carry_live_settings(working) == {"carried": 0, "of": 1}
    assert _rows(working) == {"settings.gone": "1", "settings.app": "a"}


def test_a_key_that_describes_corpus_tables_is_left_as_the_snapshot_has_it_and_named(tmp_path, live_at):
    """The spell-index note and the repair records are about tables the swap takes from the snapshot: carrying the note over
    the snapshot's table would make the record disagree with the data."""
    working = _file(tmp_path / "working.db", {"search.spell_index": "snap", "settings.app": "a"})
    live_at(_file(tmp_path / "live.db", {
        "search.spell_index": "live-build", "qualification.repairs": "r", "settings.app": "a2"}))

    out = merge._carry_live_settings(working)

    assert out == {"carried": 1, "of": 1, "left_as_snapshot": ["qualification.repairs", "search.spell_index"]}
    assert _rows(working) == {"search.spell_index": "snap", "settings.app": "a2"}


def test_a_copy_that_lacks_the_table_gets_it(tmp_path, live_at):
    working = _file(tmp_path / "working.db", None)
    live_at(_file(tmp_path / "live.db", {"settings.app": "a"}))

    assert merge._carry_live_settings(working) == {"carried": 1, "of": 1}
    assert _rows(working) == {"settings.app": "a"}


def test_a_live_file_without_settings_changes_nothing(tmp_path, live_at):
    working = _file(tmp_path / "working.db", {"settings.app": "a"})
    live_at(_file(tmp_path / "live.db", None))

    assert merge._carry_live_settings(working) == {"carried": 0, "of": 0}
    assert _rows(working) == {"settings.app": "a"}


def test_a_missing_live_file_is_reported_and_changes_nothing(tmp_path, live_at):
    working = _file(tmp_path / "working.db", {"settings.app": "a"})
    live_at(tmp_path / "absent.db")

    assert merge._carry_live_settings(working) == {"carried": 0, "of": 0, "why": "no live corpus file"}
    assert _rows(working) == {"settings.app": "a"}


def test_the_live_file_and_its_leftover_log_are_read_and_never_touched(tmp_path, live_at):
    """The read is read-only: a leftover ``-wal`` with no connection open is read from, and neither it nor the file is changed
    (a read-write open would fold and delete it). Fails if ``read_only=True`` is dropped from the live open."""
    import shutil

    work = tmp_path / "w"
    work.mkdir()
    orig = work / "orig.db"
    con = sqlite3.connect(orig)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)")
    con.commit()
    con.execute("INSERT INTO app_state VALUES ('settings.only_in_wal', 'w', '2026-10-13 00:00:00')")
    con.commit()
    live = tmp_path / "live.db"
    shutil.copy(orig, live)
    shutil.copy(str(orig) + "-wal", str(live) + "-wal")
    con.close()
    wal = Path(str(live) + "-wal")
    assert wal.exists() and wal.stat().st_size > 0, "precondition: a leftover log with the row in it"
    before = (live.read_bytes(), wal.read_bytes())
    working = _file(tmp_path / "working.db", {"settings.app": "a"})
    live_at(live)

    out = merge._carry_live_settings(working)

    assert out == {"carried": 1, "of": 1}, "the row that only the log holds is read"
    assert (live.read_bytes(), wal.read_bytes()) == before, "the live file and its log are byte-identical"


def test_a_failure_is_reported_by_class_only_and_changes_nothing(tmp_path, live_at, caplog):
    marker = "SECRET-PASSPHRASE-MARKER"
    working = _file(tmp_path / "working.db", {"settings.app": "a"})
    live = tmp_path / "live.db"
    live.write_bytes(marker.encode() * 64)  # not a database: the driver's own words must not travel
    live_at(live)

    out = merge._carry_live_settings(working)

    assert out["carried"] == 0 and set(out) == {"carried", "skipped"}
    assert marker not in repr(out) and out["skipped"].isidentifier()
    assert any("settings carry skipped" in r.getMessage() for r in caplog.records), "a skip is never silent"
    assert marker not in caplog.text
    assert _rows(working) == {"settings.app": "a"}


def _run_restore_node() -> ast.FunctionDef:
    tree = ast.parse(_MERGE_PY.read_text(encoding="utf-8"))
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_restore")


def _lines(node: ast.AST, name: str) -> list[int]:
    return sorted(
        c.lineno
        for c in ast.walk(node)
        if isinstance(c, ast.Call)
        and (getattr(c.func, "id", None) == name or getattr(c.func, "attr", None) == name)
    )


def test_the_carry_runs_once_after_the_checkpoint_and_right_before_the_swap():
    node = _run_restore_node()
    carry, quiet, ckpt, swap = (
        _lines(node, "_carry_live_settings"),
        _lines(node, "wait_for_quiescence"),
        _lines(node, "_checkpoint_before_swap"),
        _lines(node, "swap_in_corpus"),
    )
    assert len(carry) == len(quiet) == len(ckpt) == len(swap) == 1
    assert quiet[0] < ckpt[0] < carry[0] < swap[0], "as late as the swap allows: the checkpoint can take a minute"
    # and it is reported, never silent
    assert 'report["settings_carry"] = _carry_live_settings(working)' in _MERGE_PY.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  end to end: a checkpoint group, whose working copy is CARRIED and takes no snapshot
# --------------------------------------------------------------------------- #
_REPO = Path(__file__).resolve().parents[1]
_HELPER = _REPO / "tests" / "torture_helper.py"


def _env(data_dir: Path) -> dict:
    return dict(os.environ, OO_DATA_DIR=str(data_dir), OO_NO_SCHEDULER="1", OO_DB_PLAINTEXT="1")


def _helper(data_dir: Path, *args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(_HELPER), *args],
        capture_output=True, text=True, cwd=str(_REPO), env=_env(data_dir), timeout=300,
    )
    assert proc.returncode == 0, f"helper failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _py(data_dir: Path, code: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(_REPO),
        env=_env(data_dir), timeout=120,
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout.strip().splitlines()[-1]


@pytest.mark.skipif(
    sys.platform == "win32", reason="subprocess round-trip mirrors the POSIX torture harness"
)
def test_a_setting_saved_between_the_items_of_a_group_survives_the_checkpoint(tmp_path):
    """The R100 case: item 1 takes the group's only snapshot; a setting saved afterwards is in the live file and in no copy
    of it, and the checkpoint's swap used to replace the live file with the copy and lose it."""
    a = tmp_path / "A"
    a.mkdir()
    arts = {}
    for role in ("one", "two"):
        d = tmp_path / f"src-{role}"
        d.mkdir()
        art = tmp_path / f"{role}.oobak.ooenc"
        assert _helper(d, "build-scoped", "--role", role, "--artifact", str(art), "--passphrase", "pw-s").get("artifact")
        arts[role] = art
    _helper(a, "build-scoped", "--role", "live")
    group = tmp_path / "group"
    group.mkdir()
    working = group / "working.db"

    held = _helper(a, "merge", str(arts["one"]), "--passphrase", "pw-s", "--commit",
                   "--working-copy", str(working), "--hold")["report"]
    assert held["held"] is True

    _py(a, "from src.config.kv_store import kv_set_json; kv_set_json('settings.saved_between_items', {'v': 7}); print('ok')")

    rep = _helper(a, "merge", str(arts["two"]), "--passphrase", "pw-s", "--commit",
                  "--working-copy", str(working))["report"]
    assert rep["committed"] is True
    assert rep["settings_carry"]["carried"] >= 1, rep.get("settings_carry")

    got = _py(a, "import json; from src.config.kv_store import kv_get_json;"
                 " print(json.dumps(kv_get_json('settings.saved_between_items')))")
    assert got == '{"v": 7}', "the setting saved after the group's snapshot was thrown away by the swap"
