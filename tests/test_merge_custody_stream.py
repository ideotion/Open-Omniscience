"""A restore's custody import streams the foreign chains instead of loading them.

Field 2026-09-27: two imports of about one million articles each were killed at 5.6 and
6.0 GB on a 7 GB machine, both in ``side_files_and_custody``, with every thread snapshot
inside ``merge_custody``. It ``fetchall()``-ed every chain of the staged custody file and
then built a second list of parsed entries beside it; custody grows by one entry per
ingested article and every heir carries its ancestors' chains, so that was gigabytes.

These tests pin that the import still does exactly what it did (every row, its verdict,
duplicates ignored, a broken chain imported as unverified) and that its memory no longer
grows with the chain.
"""

from __future__ import annotations

import json
import sqlite3
import tracemalloc

import pytest

from src.backup import merge
from src.custody.log import CustodyAction, CustodyLog, verify_entries
from src.custody.signing import HybridSigner


def _real_chain(tmp_path, n: int = 12) -> tuple:
    """A staged custody file holding a real, signed chain of ``n`` entries."""
    signer = HybridSigner(ed25519_path=tmp_path / "ed.pem", mldsa_path=tmp_path / "ml.key")
    path = tmp_path / "staged_custody.db"
    log = CustodyLog(db_path=str(path), signer=signer)
    for i in range(n):
        log.record(f"article:{i}", f"{i:064x}", CustodyAction.INGEST, actor="pipeline")
    log.close()
    return path


def _imported(data_dir) -> list[tuple]:
    con = sqlite3.connect(data_dir / "custody_log.db")
    try:
        return con.execute(
            "SELECT chain_id, seq, entry_hash, verified, verify_note"
            " FROM custody_imported_entries ORDER BY chain_id, seq"
        ).fetchall()
    finally:
        con.close()


@pytest.fixture()
def live_dir(tmp_path, monkeypatch):
    d = tmp_path / "live"
    d.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    # Several slices per chain, so a slice boundary sits inside every chain below.
    monkeypatch.setattr(merge, "_CUSTODY_FETCH_ROWS", 5)
    return d


def test_every_row_imported_with_its_verdict_across_slices(tmp_path, live_dir):
    staged = _real_chain(tmp_path, n=12)
    # The staged corpus had itself imported a chain: it travels under its own id.
    con = sqlite3.connect(staged)
    con.execute(
        "CREATE TABLE custody_imported_entries AS SELECT 'ancestor' AS chain_id, *"
        " FROM custody_entries"
    )
    con.commit()
    con.close()

    out = merge.merge_custody(staged, "fp-origin")

    assert out["entries"] == 24 and out["imported"] == 24 and out["duplicate"] == 0
    assert out["verified"] is True
    assert {c["chain_id"]: c["entries"] for c in out["chains"]} == {
        "fp-origin": 12, "ancestor": 12,
    }
    rows = _imported(live_dir)
    assert len(rows) == 24
    assert [r[1] for r in rows if r[0] == "fp-origin"] == list(range(1, 13))
    assert all(r[3] == 1 and r[4] is None for r in rows)

    # A second import of the same file adds nothing: every row is a duplicate.
    again = merge.merge_custody(staged, "fp-origin")
    assert again["imported"] == 0 and again["duplicate"] == 24
    assert len(_imported(live_dir)) == 24


def test_a_broken_chain_is_still_imported_as_unverified(tmp_path, live_dir):
    staged = _real_chain(tmp_path, n=12)
    con = sqlite3.connect(staged)
    con.execute("UPDATE custody_entries SET item_hash = ? WHERE seq = 7", ("f" * 64,))
    con.commit()
    con.close()

    out = merge.merge_custody(staged, "fp-origin")

    assert out["verified"] is False and out["imported"] == 12
    assert any("seq 7" in p for p in out["problems"])
    rows = _imported(live_dir)
    assert len(rows) == 12
    assert all(r[3] == 0 and "seq 7" in r[4] for r in rows)


def test_an_empty_source_imports_nothing(tmp_path, live_dir):
    staged = tmp_path / "empty.db"
    sqlite3.connect(staged).close()
    assert merge.merge_custody(staged, "fp") == {
        "entries": 0, "imported": 0, "duplicate": 0, "chains": [],
    }
    assert not (live_dir / "custody_log.db").exists()


def test_memory_does_not_grow_with_the_chain(tmp_path, live_dir, monkeypatch):
    """The field's failure, at small scale: 20,000 entries of about 1 KB each.

    Unsigned rows fail verification, which costs the same walk as a valid chain and
    keeps the test fast; the point is what the import holds while it walks. The old
    code held every row twice (the fetched tuples and the parsed entries): 67 MB
    here; the streamed import holds one slice."""
    monkeypatch.setattr(merge, "_CUSTODY_FETCH_ROWS", 200)
    staged = tmp_path / "big.db"
    con = sqlite3.connect(staged)
    con.execute(
        "CREATE TABLE custody_entries (seq INTEGER PRIMARY KEY, item_id TEXT, item_hash TEXT,"
        " action TEXT, actor TEXT, metadata_json TEXT, prev_entry_hash TEXT,"
        " entry_hash TEXT, signature_json TEXT, timestamp_json TEXT)"
    )
    meta = json.dumps({"note": "x" * 900})
    con.executemany(
        "INSERT INTO custody_entries VALUES (?, ?, ?, 'ingest', 'pipeline', ?, ?, ?, '{}', '{}')",
        (
            (i, f"article:{i}", f"{i:064x}", meta, f"{i - 1:064x}", f"{i:064x}")
            for i in range(1, 20_001)
        ),
    )
    con.commit()
    con.close()

    tracemalloc.start()
    try:
        out = merge.merge_custody(staged, "fp-origin")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert out["entries"] == 20_000 and out["imported"] == 20_000
    assert out["verified"] is False
    assert peak < 8 * 1024 * 1024, f"peak {peak / 1e6:.1f} MB: the chain is being held"
    # The note stays bounded however broken the chain is.
    assert len(_imported(live_dir)[0][4]) <= 500


def test_verify_entries_bounds_its_issues_but_not_its_verdict():
    from src.custody.log import CustodyEntry

    def broken(n):
        for i in range(1, n + 1):
            yield CustodyEntry(
                seq=i, item_id="x", item_hash="0" * 64, action="ingest", actor=None,
                metadata={}, prev_entry_hash="bad", entry_hash="bad", signature={},
                timestamp={},
            )

    ok, issues = verify_entries(broken(1000), max_issues=10)
    assert ok is False
    assert len(issues) == 11 and issues[-1].startswith("... and ")
    ok_all, all_issues = verify_entries(broken(1000))
    assert ok_all is False and len(all_issues) > 1000
