"""The damaged-store helpers find the same pages with ``dbstat`` and without it.

``damaged_store_helpers.leaf_pages`` chooses the pages the repair and salvage tests overwrite. Where the SQLite build has no
``dbstat`` (python.org's macOS build) it reads the b-tree off the file instead, so those tests run on every OS. This holds the
file-format walk equal to ``dbstat`` on a build that has both, for a table, an index, the full-text data, the schema and both
page kinds, so a walk that drifted would fail here rather than quietly damage the wrong pages elsewhere.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

from tests import damaged_store_helpers as H


def _has_dbstat() -> bool:
    con = sqlite3.connect(":memory:")
    try:
        con.execute("SELECT count(*) FROM dbstat").fetchone()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    if not _has_dbstat():
        if os.getenv("CI") and sys.platform.startswith("linux"):
            pytest.fail("the Linux CI lane has dbstat; without it this comparison asserts nothing")
        pytest.skip("this SQLite build has no dbstat virtual table to compare the file-format walk with")
    path = tmp_path_factory.mktemp("helpers") / "plain.db"
    H.build_app_store(path, articles=1500)
    return path


def test_the_file_format_walk_finds_the_pages_dbstat_finds(store):
    con = sqlite3.connect(store)
    index = con.execute(
        "SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='articles' AND sql IS NOT NULL ORDER BY name"
    ).fetchone()[0]
    con.close()
    for name in ("articles", "article_fts_data", index, "sqlite_schema"):
        for kind in ("leaf", "internal"):
            assert H.btree_pages(store, name, kind) == H.leaf_pages(store, name, kind), (name, kind)
    assert len(H.btree_pages(store, "articles")) > 3 and H.btree_pages(store, "articles", "internal"), "a tree with depth"


def test_a_name_with_no_tree_has_no_pages(store):
    assert H.btree_pages(store, "no_such_table") == []


@pytest.mark.parametrize("encrypted", [pytest.param(False, id="plaintext"), pytest.param(True, id="sqlcipher")])
def test_the_store_the_helper_builds_is_in_the_apps_journal_mode(tmp_path, encrypted):
    """Row 320: the helper's stores are written through the app's pragmas, so they are WAL files like the app's own library, and the
    builder leaves no log behind (its last step folds the log in and the last close removes it)."""
    if encrypted:
        H.needs_sqlcipher()
    path = tmp_path / "s.db"
    H.build_app_store(path, articles=20, encrypted=encrypted)
    assert not os.path.exists(str(path) + "-wal")
    con = H.open_store(path, key=H.KEY if encrypted else None)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        con.close()
