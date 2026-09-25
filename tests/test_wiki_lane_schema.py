"""The Wikipedia lane creates its lane WITH its schema, on the paths production takes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Found by S04-08's S5 walk (2026-09-25). Every wiki path opened its lane with
``lane_session("wiki", create=True)``, which brings the FILE into existence and nothing
else; only ``create_lane`` makes the tables (``src/law/lane_sync.py`` says so and calls
it). The lane tests all create the lane in a fixture first, so none of them could see
that on a fresh install going online left an EMPTY ``wiki.db``: every drain, hot-set
build and pin then failed on "no such table: versioned_entities", and the lane status
and the briefing answered 500. The same call also stepped around ``create_lane``'s
refusal to write a plaintext lane beside an encrypted corpus (Q1005).

These tests start from a data folder where NOTHING has created the lane.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from src.versioned import store

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from src.database.session import init_db

    init_db()
    assert not store.lane_exists("wiki"), "the fixture must start with no lane at all"
    try:
        yield tmp_path
    finally:
        store.dispose_all()


def _tables(path: Path) -> set[str]:
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    finally:
        con.close()


def test_the_first_drain_on_a_fresh_install_finds_a_lane_with_its_schema(fresh):
    from src.wiki.service import _hot_sets

    sets = _hot_sets()  # the drain's first lane read; it raised "no such table" before
    assert sets is not None
    tables = _tables(store.lane_path("wiki"))
    assert "versioned_entities" in tables and "lane_meta" in tables, tables


def test_pinning_a_page_on_a_fresh_install_stores_it(fresh):
    from src.api.wiki import _pin_to_hot
    from src.versioned.models import VersionedEntity

    out = _pin_to_hot("oo", "Fixture Alpha", 101)
    assert out.get("ok") is True, out
    with store.lane_session("wiki") as lane:
        assert lane.query(VersionedEntity).count() == 1


def test_an_EMPTY_lane_file_an_earlier_build_left_is_repaired(fresh):
    """Installs that went online on the old code carry a wiki.db with no tables."""
    from src.wiki.service import wiki_lane_session

    with store.lane_session("wiki", create=True):
        pass  # exactly what the old paths did
    assert "versioned_entities" not in _tables(store.lane_path("wiki")), "no empty file to repair"
    with wiki_lane_session() as lane:
        from src.versioned.models import VersionedEntity

        assert lane.query(VersionedEntity).count() == 0
    assert "versioned_entities" in _tables(store.lane_path("wiki"))


def test_the_wiki_paths_REFUSE_a_plaintext_lane_beside_an_encrypted_corpus(tmp_path, monkeypatch):
    """Q1005: no per-lane plaintext. ``create_lane`` refuses this; the old wiki paths,
    going through ``lane_session(create=True)``, never asked it."""
    from src.database.connect import connect, is_encrypted_file
    from src.wiki.service import wiki_lane_session

    passphrase = "a lane shares the corpus passphrase"
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setattr("src.database.connect._passphrase", passphrase, raising=False)
    con = connect(str(tmp_path / "open_omniscience.db"), key=passphrase, create_encrypted=True)
    con.execute("CREATE TABLE t(a)")
    con.close()
    assert is_encrypted_file(tmp_path / "open_omniscience.db") is True
    try:
        with pytest.raises(store.PlaintextLaneRefused), wiki_lane_session():
            pass
        assert not store.lane_exists("wiki"), "a refused lane still left a file"
    finally:
        store.dispose_all()


def test_no_module_brings_a_lane_file_into_existence_without_its_schema():
    """``create=True`` makes the FILE and nothing else, and skips ``create_lane``'s
    refusals. Only the store itself may use it; everything else calls ``create_lane``."""
    offenders = []
    for path in sorted((_ROOT / "src").rglob("*.py")):
        if path == _ROOT / "src" / "versioned" / "store.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in ("lane_session", "lane_engine"):
                continue
            for kw in node.keywords:
                if kw.arg == "create" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                    offenders.append(f"{path.relative_to(_ROOT)}:{node.lineno}")
    assert not offenders, f"lane opened with create=True outside the store: {offenders}"
