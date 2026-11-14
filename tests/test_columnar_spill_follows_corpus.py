"""The map serve and the source-coverage benchmark offload the way the keyword rollup does.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before this, only the keyword rollup chose DuckDB's offload folder (``rollup_serve._spill_setting``): none for an
encrypted corpus, a per-connection folder under the data directory for a plaintext one. The map serve and the
source-coverage benchmark took DuckDB's default, a ``.tmp`` beside the working directory, written in plaintext
whatever the corpus (OPEN_QUEUE, the rollup build's memory fix, item (1)). One test per store for each caller, plus the
folder being removed when the connection is retired, fails, or is closed by the memory ladder.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar, map_serve, rollup_serve
from src.database.models import Article, Base, Source

pytestmark = pytest.mark.skipif(not columnar.duckdb_available(), reason="duckdb not installed (optional [columnar] extra)")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(id=1, name="S1", domain="a.test", country="FR"))
    s.add(Article(url="https://a.test/1", canonical_url="https://a.test/1", source_id=1, title="T", content="x", hash="h1",
                  language="fr", published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC)))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def seen(monkeypatch, tmp_path):
    """The data directory is a temp folder; every columnar connection records the offload it was given and DuckDB's
    own reading of it."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_OWN_SPILL_SWEPT", False)
    out: list[dict] = []
    real = columnar.connect

    def connect(*a, **k):
        con = real(*a, **k)
        temp = con.execute("SELECT current_setting('temp_directory')").fetchone()[0] if con is not None else None
        out.append({"spill": k.get("spill", "<not passed>"), "temp_directory": temp, "con": con})
        return con

    monkeypatch.setattr(columnar, "connect", connect)
    return out


def _map_build(monkeypatch, db) -> None:
    monkeypatch.setattr("src.analytics.serve_gate.exclusive_verdict", lambda: None)
    monkeypatch.setattr("src.api.boot_sequence.heavy_step_verdict", lambda: None)
    monkeypatch.setattr("src.database.session.session_scope", lambda: contextlib.nullcontext(db))
    assert map_serve._BUILD_LOCK.acquire(blocking=False)
    map_serve._build_and_swap()


@pytest.fixture
def clean_map_state(monkeypatch):
    for key in ("con", "spill", "built_at", "rows", "bind", "token", "pending"):
        monkeypatch.setitem(map_serve._STATE, key, map_serve._STATE.get(key))
    monkeypatch.setitem(map_serve._STATE, "con", None)
    monkeypatch.setitem(map_serve._STATE, "spill", None)
    yield
    con = map_serve._STATE.get("con")
    if con is not None:
        with contextlib.suppress(Exception):
            con.close()
    rollup_serve._remove_spill(map_serve._STATE.get("spill"))


def test_the_map_serve_never_offloads_an_encrypted_corpus(monkeypatch, db, seen, tmp_path, clean_map_state):
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: True)
    _map_build(monkeypatch, db)
    assert seen and seen[0]["spill"] == "", "the map serve took DuckDB's default offload for an encrypted corpus"
    assert seen[0]["temp_directory"] == "", "DuckDB was left free to offload"
    assert map_serve._STATE["con"] is not None, "the map rollup was not built"
    assert map_serve._STATE["spill"] is None
    assert not any((tmp_path / "duckdb_tmp").glob("*")), "an offload folder was made for an encrypted corpus"


def test_the_map_serve_offloads_a_plaintext_corpus_under_the_data_directory_and_retires_the_folder(
    monkeypatch, db, seen, tmp_path, clean_map_state
):
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)
    _map_build(monkeypatch, db)
    first = seen[0]["spill"]
    root = (tmp_path / "duckdb_tmp").resolve()
    assert first and str(root) in first, f"the offload is not under the data directory: {first!r}"
    assert seen[0]["temp_directory"] == first, "DuckDB was not told to offload there"
    assert map_serve._STATE["spill"] == first
    _map_build(monkeypatch, db)  # a rebuild retires the first connection, and its folder with it
    second = seen[1]["spill"]
    assert second != first and map_serve._STATE["spill"] == second
    assert not (tmp_path / "duckdb_tmp" / first.rsplit("/", 1)[-1]).exists(), "the retired connection's folder was left"


def test_a_failed_map_build_closes_its_connection_and_removes_its_folder(monkeypatch, db, seen, tmp_path, clean_map_state):
    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: False)

    def boom(con, s):
        raise RuntimeError("the build died")

    monkeypatch.setattr(columnar, "build_source_coverage", boom)
    _map_build(monkeypatch, db)
    assert map_serve._STATE["con"] is None and not map_serve._BUILD_LOCK.locked()
    with pytest.raises(Exception):  # noqa: B017 - DuckDB's class for "connection already closed" differs across versions
        seen[0]["con"].execute("SELECT 1")
    assert not any((tmp_path / "duckdb_tmp").glob("*")), "a failed build left its offload folder"


@pytest.mark.parametrize("encrypted", [True, False])
def test_the_source_coverage_benchmark_offloads_by_the_same_rule_and_cleans_up(monkeypatch, db, seen, tmp_path, encrypted):
    from src.monitoring.source_coverage_benchmark import run_source_coverage_benchmark

    monkeypatch.setattr(rollup_serve, "_corpus_encrypted", lambda: encrypted)
    out = run_source_coverage_benchmark(db, repeats=1)
    assert out["available"] is True
    spill = seen[0]["spill"]
    if encrypted:
        assert spill == "", "the benchmark took DuckDB's default offload for an encrypted corpus"
    else:
        assert spill and str((tmp_path / "duckdb_tmp").resolve()) in spill
    root = tmp_path / "duckdb_tmp"
    assert not (root.exists() and any(root.glob("*"))), "the benchmark left its offload folder"


def test_the_memory_ladder_removes_a_closed_serves_folder(monkeypatch, tmp_path):
    from src.scheduler import release

    folder = tmp_path / "duckdb_tmp" / "123-abc"
    folder.mkdir(parents=True)

    class _Con:
        def close(self):
            pass

    monkeypatch.setitem(map_serve._STATE, "con", _Con())
    monkeypatch.setitem(map_serve._STATE, "spill", str(folder))
    monkeypatch.setitem(map_serve._STATE, "built_at", 1.0)
    monkeypatch.setitem(rollup_serve._STATE, "con", None)
    rec = release._close_serves(wait=False)
    assert "map_serve" in rec["closed"] and map_serve._STATE["spill"] is None
    assert not folder.exists(), "the closed serve's offload folder was left behind"
