"""The persisted columnar store has a memory bound and offloads only into a folder the app owns (open-on-main row 48).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before this, ``_persisted_config`` set neither ``memory_limit`` nor ``threads`` nor ``temp_directory``: DuckDB took its
documented defaults, 80% of the machine's RAM, one thread per core, and ``.tmp`` in the process's WORKING directory (a
folder the app neither owns nor removes). The in-memory store has been bounded since S1.1; the persisted one is the store
an encrypted library serves from once the secure backend is bundled. That it offloads into the named folder, encrypted,
and never beside the process is measured in tests/test_columnar_spill_never_plaintext.py.
"""

from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")

from src.analytics import columnar  # noqa: E402

_SNAP = {"duckdb_limit_mb": 40, "duckdb_threads": 1}


def _setting(con, name: str) -> str:
    return con.execute(f"SELECT current_setting('{name}')").fetchone()[0]


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # DuckDB's default offload folder is relative to the working directory
    return tmp_path


def test_the_persisted_config_carries_the_budget_and_no_default_offload(work):
    """The budget's limit and threads, and with no folder named, no offload at all (never ``./.tmp``)."""
    con = duckdb.connect(config=columnar._persisted_config(snapshot=_SNAP))
    try:
        assert _setting(con, "memory_limit") == "38.1 MiB"  # 40 MB as DuckDB prints it (1.4.0 and 2.0.0)
        assert int(_setting(con, "threads")) == 1
        assert _setting(con, "temp_directory") == ""
    finally:
        con.close()


def test_the_persisted_config_reads_the_budget_when_given_none(monkeypatch):
    monkeypatch.setattr(columnar, "budget_snapshot", lambda: {"duckdb_limit_mb": 123.0, "duckdb_threads": 2})
    cfg = columnar._persisted_config()
    assert (cfg["memory_limit"], cfg["threads"]) == ("123MB", 2)
    assert cfg["temp_directory"] == ""
    assert cfg["temp_file_encryption"] is True


def test_open_store_hands_the_persisted_folder_to_the_persisted_connection_only(monkeypatch, tmp_path):
    """``persisted_spill`` is for the encrypted file's connection; an in-memory store handed back instead must never
    inherit it (that folder would hold an encrypted library's rows in plaintext)."""
    seen: dict = {}
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: False)
    real_offline = columnar._offline_config

    def offline(spill=None, snapshot=None):
        seen["memory_spill"] = spill
        return real_offline(spill, snapshot)

    monkeypatch.setattr(columnar, "_offline_config", offline)
    opened = columnar.open_store("pass", persisted_spill=str(tmp_path / "p"), snapshot=_SNAP)
    try:
        assert opened.kind == "memory"
        assert seen["memory_spill"] is None
        assert _setting(opened.con, "temp_directory") == ""
    finally:
        opened.con.close()


def test_open_store_forwards_the_folder_and_the_budget_to_the_persisted_connection(monkeypatch, tmp_path):
    """Every stub elsewhere swallows these arguments: here the chain open_store -> _attach_persisted -> _persisted_connection
    is followed to the config the connection is made with."""
    made: list[dict] = []

    class _Con:
        def execute(self, *_a, **_k):
            return self

        def close(self):
            pass

    def connection(spill=None, snapshot=None):
        made.append(columnar._persisted_config(spill, snapshot))
        return _Con()

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(columnar, "secure_crypto_available", lambda: True)
    monkeypatch.setattr(columnar, "encryption_gate", lambda _p: True)
    monkeypatch.setattr(columnar, "_persisted_connection", connection)
    monkeypatch.setattr(columnar, "read_store_meta", lambda _c: None)
    monkeypatch.setattr(columnar, "ensure_store_meta", lambda _c: None)
    opened = columnar.open_store("pass", persisted_spill=str(tmp_path / "own"), snapshot=_SNAP)
    assert opened.kind == "persisted"
    assert len(made) == 1
    assert (made[0]["temp_directory"], made[0]["memory_limit"], made[0]["threads"]) == (str(tmp_path / "own"), "40MB", 1)
