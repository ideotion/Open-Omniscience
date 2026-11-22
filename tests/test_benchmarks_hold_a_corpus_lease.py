"""The two rollup benchmarks hold a corpus lease for the life of their offload folder (open-on-main row 56).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A benchmark's DuckDB offload folder is chosen when it starts (``rollup_serve._spill_setting``: a folder for a plaintext library)
and is not one the serves track, so the close after an encryption in place does not reach it. An encryption that ran beside a
benchmark left that folder's plaintext rows on disk until the benchmark ended. The encryption waits for corpus leases (or refuses,
by name): holding one is what makes it wait for the benchmark.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from src.analytics import columnar, rollup_serve
from src.database import corpus_lease
from src.database.models import Base
from tests._app_engine import app_sqlite_engine


@pytest.fixture
def session():
    engine = app_sqlite_engine(":memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


@pytest.fixture
def folder(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))  # the lease files live under the data directory
    made = tmp_path / "duckdb_tmp" / "123-abcd1234"
    made.mkdir(parents=True)
    monkeypatch.setattr(rollup_serve, "_spill_setting", lambda: str(made))

    class _Con:
        def close(self):
            pass

    monkeypatch.setattr(columnar, "connect", lambda *_a, **_k: _Con())
    return made


class _Stop(Exception):
    pass


def test_the_rollup_benchmark_holds_its_lease_while_its_folder_exists(monkeypatch, session, folder):
    from src.monitoring import rollup_benchmark

    seen: list[list[str]] = []

    def measure(*_a, **_k):
        seen.append(corpus_lease.active_leases())
        assert folder.exists()
        raise _Stop

    monkeypatch.setattr(rollup_benchmark, "_measure", measure)
    with pytest.raises(_Stop):
        rollup_benchmark._run_built(session, 1, columnar, {"duckdb_limit_mb": 40, "duckdb_threads": 1})
    assert seen and "rollup-benchmark" in seen[0], "an encryption in place would not wait for this run's plaintext folder"
    assert "rollup-benchmark" not in corpus_lease.active_leases() and not folder.exists()


def test_the_source_coverage_benchmark_holds_its_lease_while_its_folder_exists(monkeypatch, session, folder):
    from src.monitoring import source_coverage_benchmark

    seen: list[list[str]] = []

    def refresh(*_a, **_k):
        seen.append(corpus_lease.active_leases())
        assert folder.exists()
        raise _Stop

    monkeypatch.setattr(columnar, "duckdb_available", lambda: True)
    monkeypatch.setattr(columnar, "refresh_source_coverage", refresh)
    with pytest.raises(_Stop):
        source_coverage_benchmark.run_source_coverage_benchmark(session, repeats=1)
    assert seen and "source-coverage-benchmark" in seen[0], "an encryption in place would not wait for this run's plaintext folder"
    assert "source-coverage-benchmark" not in corpus_lease.active_leases() and not folder.exists()


@pytest.mark.parametrize("which", ["rollup", "source-coverage"])
def test_a_benchmark_started_inside_an_exclusive_window_declines_with_no_folder(monkeypatch, session, tmp_path, which):
    """The encryption looked for leases before this one existed: once the lease is held the benchmark asks again, and declines."""
    from src.monitoring import rollup_benchmark, source_coverage_benchmark
    from src.scheduler import runner

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(runner, "owns_the_machine", lambda: True)
    monkeypatch.setattr(rollup_serve, "_spill_setting", lambda: pytest.fail("a folder was taken inside the window"))
    monkeypatch.setattr(columnar, "duckdb_available", lambda: True)
    if which == "rollup":
        out = rollup_benchmark._run_built(session, 1, columnar, {"duckdb_limit_mb": 40, "duckdb_threads": 1})
    else:
        out = source_coverage_benchmark.run_source_coverage_benchmark(session, repeats=1)
    assert out["declined"] is True and out["reason"] == "exclusive-operation"
    assert corpus_lease.active_leases() == []
