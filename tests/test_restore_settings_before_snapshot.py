"""A restore reads the settings BEFORE it snapshots the live corpus, never after.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``run_restore`` resolves the trust-fetch-history answer with ``resolve_trust_fetch_history``,
which with no per-import override calls ``load_settings()``. On a corpus whose settings were
never read that migrates a legacy ``app_settings.json`` into the ``app_state`` row: a WRITE on
the LIVE file. Made after ``snapshot_working_copy`` it is thrown away by the swap and it
contradicts "nothing touches the live file between the snapshot and the swap"; made before it,
the snapshot carries it into the working copy and the swap keeps it. The read is the only
settings read in that region (``run_restore`` reads no other setting between the two).
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

_MERGE_PY = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"


def _run_restore_node() -> ast.FunctionDef:
    tree = ast.parse(_MERGE_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run_restore":
            return node
    raise AssertionError("run_restore not found")


def _call_lines(node: ast.AST, name: str) -> list[int]:
    return sorted(
        c.lineno
        for c in ast.walk(node)
        if isinstance(c, ast.Call)
        and (getattr(c.func, "id", None) == name or getattr(c.func, "attr", None) == name)
    )


def test_the_settings_are_resolved_once_and_before_the_snapshot_in_the_source():
    node = _run_restore_node()
    reads = _call_lines(node, "resolve_trust_fetch_history")
    snaps = _call_lines(node, "snapshot_preserving")
    assert len(reads) == 1, "the answer is resolved ONCE per restore"
    assert snaps, "anti-vacuity: the snapshot call was not found"
    assert reads[0] < min(snaps), "the settings read must precede every snapshot of the live file"
    # No other settings read hides between the snapshot and the swap.
    swap = _call_lines(node, "swap_in_corpus")
    assert len(swap) == 1
    for name in ("load_settings", "get_settings", "_read_raw", "kv_get_json", "kv_set_json"):
        between = [ln for ln in _call_lines(node, name) if min(snaps) < ln < swap[0]]
        assert not between, f"{name} is called between the snapshot and the swap"


def test_a_restore_resolves_the_settings_before_it_takes_the_snapshot(tmp_path, monkeypatch):
    """Behavioural twin: drive ``run_restore`` to its snapshot and record the order of the two
    calls (the snapshot raises a sentinel, so nothing after it runs)."""
    import src.backup.merge as merge
    import src.backup.sqlite_backup as sqlite_backup
    import src.database.connect as connect

    order: list[str] = []

    class _Stop(Exception):
        pass

    def fake_resolve(override):
        order.append("settings")
        return bool(override)

    def fake_snapshot(*_a, **_k):
        order.append("snapshot")
        raise _Stop

    monkeypatch.setattr(merge, "resolve_trust_fetch_history", fake_resolve)
    monkeypatch.setattr(merge, "prepare_staged_corpus", lambda *a, **k: "head")
    monkeypatch.setattr(connect, "snapshot_preserving", fake_snapshot)
    monkeypatch.setattr(sqlite_backup, "live_db_path", lambda: tmp_path / "live.db")
    staged = SimpleNamespace(
        kind="oo-backup-3", staging_dir=tmp_path / "stage", stage_a_timings={},
        manifest=None, origin_fingerprint="x", corpus_path=tmp_path / "in.db",
    )
    with pytest.raises(_Stop):
        merge.run_restore(staged, commit=True, exclusive=True)
    assert order == ["settings", "snapshot"]
