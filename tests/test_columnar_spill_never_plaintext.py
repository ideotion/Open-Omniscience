"""The columnar engine never spills plaintext into the working directory (open-on-main row 24).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured on DuckDB 1.4.0 and 2.0.0 before the fix:

* an IN-MEMORY store opened with no offload folder (``map_serve`` and the source-coverage benchmark open it that way)
  used DuckDB's own default, ``./.tmp`` in the process's working directory, and a sort past the memory limit wrote the
  rows' text there in plaintext, whatever the corpus's encryption;
* the PERSISTED encrypted store spilled its attached tables' blocks encrypted, but anything in the connection's
  in-memory or temporary catalog (a ``TEMP TABLE``, an intermediate) in plaintext into the same ``./.tmp``, because
  ``temp_file_encryption`` is off by default.

Each test runs the real engine with the app's own config, a small memory limit and a marker string, and reads every
file the engine left beside it while the query runs.
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from src.analytics import columnar  # noqa: E402

MARK = "PLAINTEXTMARKERZQX"
_SNAP = {"duckdb_limit_mb": 40, "duckdb_threads": 1}


def _watched(con, work: Path, sql: str) -> tuple[list[str], BaseException | None]:
    """Run ``sql`` while watching ``work``: the files that held the marker at any moment, and what the engine raised."""
    found: set[str] = set()
    stop = threading.Event()

    def watch() -> None:
        while not stop.is_set():
            for p in work.rglob("*"):
                if p.is_file() and not p.name.startswith("store.duckdb"):
                    try:
                        if MARK.encode() in p.read_bytes():
                            found.add(str(p.relative_to(work)))
                    except OSError:
                        pass
            time.sleep(0.02)

    th = threading.Thread(target=watch, daemon=True)
    th.start()
    raised: BaseException | None = None
    try:
        con.execute(sql).fetchmany(3)
    except duckdb.Error as exc:
        raised = exc
    finally:
        stop.set()
        th.join(5)
    return sorted(found), raised


def _fill_sql(table: str) -> str:
    return f"CREATE TABLE {table} AS SELECT i, '{MARK}' || i::VARCHAR || repeat('x', 200) AS s FROM range(600000) r(i)"


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # DuckDB's default offload folder is relative to the working directory
    return tmp_path


def test_an_in_memory_store_with_no_offload_folder_writes_nothing_beside_it(work):
    """~130 MB of rows against a 40 MB limit: with no offload the engine must REFUSE (out of memory), and nothing it
    wrote while trying may hold the rows. Before the fix it spilled them into ``./.tmp`` in plaintext and succeeded."""
    con = duckdb.connect(":memory:", config=columnar._offline_config(snapshot=_SNAP))
    try:
        found, raised = _watched(con, work, _fill_sql("t"))
        assert found == []
        assert isinstance(raised, duckdb.OutOfMemoryException), raised  # the limit was reached and offload refused
    finally:
        con.close()


def test_the_persisted_config_encrypts_what_it_spills_from_the_temporary_catalog(work):
    """The persisted store is opened by ``_persisted_config`` with the bundled httpfs LOADed. httpfs is not bundled
    here, so DuckDB's built-in module stands in (allowed for writes on 1.4.x; on later versions only under
    ``force_mbedtls_unsafe``): what is under test is whether a spill from the TEMPORARY catalog is encrypted at all."""
    cfg = dict(columnar._persisted_config(), memory_limit="40MB", threads=1)
    con = duckdb.connect(config=cfg)
    try:
        with contextlib.suppress(duckdb.Error):  # 1.4.x: the option does not exist and the built-in module writes
            con.execute("SET force_mbedtls_unsafe = true")
        try:
            con.execute(f"ATTACH '{(work / 'store.duckdb').as_posix()}' AS oo (ENCRYPTION_KEY ?)", ["0" * 64])
        except duckdb.Error as exc:
            pytest.skip(f"no writable crypto module in this DuckDB: {type(exc).__name__}")
        con.execute("USE oo")
        for table in ("memory.main.m", "oo.main.t"):  # the temporary catalog (a TEMP TABLE, an intermediate), then the file's own
            found, raised = _watched(con, work, _fill_sql(table))
            assert (found, raised) == ([], None)
            found, raised = _watched(con, work, f"SELECT s FROM {table} ORDER BY s DESC")
            assert (found, raised) == ([], None)
        assert any(p.is_file() for p in (work / ".tmp").rglob("*")), "the engine spilled: the files above were really read"
    finally:
        con.close()


def test_the_persisted_config_names_temp_file_encryption():
    """The setting itself, so the config cannot lose it on a version where the stand-in module refuses to write."""
    assert columnar._persisted_config()["temp_file_encryption"] is True
