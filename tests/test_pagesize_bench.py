"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

DB-10 §1b page-size A/B bench: the rebuild honors the CREATE-time pragmas and
SELF-VERIFIES (the ruled verify-before-trust probe made permanent), the
workload reports honest side-by-side numbers with no composite verdict, disk
preflight refuses up front, cancel leaves no stage file, and the saved report
round-trips. Pure plaintext-SQLite tests (the encrypted path shares the code
shape and self-verifies at runtime; sqlcipher3 is CI/operator territory).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.monitoring import pagesize_bench as pb


def _make_corpus(path: Path, articles: int = 800) -> None:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, content TEXT)")
    con.execute(
        "CREATE TABLE keyword_mentions (id INTEGER PRIMARY KEY, observed_on TEXT)"
    )
    con.execute("CREATE INDEX ix_km_observed ON keyword_mentions(observed_on)")
    con.executemany(
        "INSERT INTO articles (content) VALUES (?)",
        [("body " * 120,) for _ in range(articles)],
    )
    con.executemany(
        "INSERT INTO keyword_mentions (observed_on) VALUES (?)",
        [(f"2026-07-{(i % 28) + 1:02d}",) for i in range(2000)],
    )
    con.commit()
    con.close()


@pytest.fixture()
def corpus(tmp_path):
    src = tmp_path / "corpus.db"
    _make_corpus(src)
    return src


def test_rebuild_honors_pragmas_and_rows_and_self_verifies(corpus, tmp_path):
    """The empirical probe, pinned: VACUUM INTO inherits page_size + auto_vacuum
    set on the source connection, keeps every row, and the self-verify echoes
    the target's REAL pragmas (never the requested ones)."""
    dst = tmp_path / "rebuilt.db"
    out = pb.rebuild_at_pragmas(corpus, dst, page_size=16384, auto_vacuum=2)
    assert out["verified"]["page_size"] == 16384
    assert out["verified"]["auto_vacuum"] == 2
    assert out["verified"]["articles_rebuilt"] == out["verified"]["articles_source"] == 800
    assert out["seconds"] >= 0 and out["file_bytes"] > 0 and out["encrypted"] is False
    con = sqlite3.connect(str(dst))
    assert con.execute("PRAGMA page_size").fetchone()[0] == 16384
    con.close()


def test_rebuild_refuses_a_bad_page_size(corpus, tmp_path):
    with pytest.raises(pb.BenchRefused):
        pb.rebuild_at_pragmas(corpus, tmp_path / "x.db", page_size=5000)


def test_rebuild_refuses_a_target_that_reads_back_wrong(corpus, tmp_path, monkeypatch):
    """The never-assert rule: if the target does NOT read back the requested
    pragmas (the encrypted-driver risk this sandbox cannot exercise), the bench
    REFUSES that size — a structured error, never a silent mis-measurement."""
    import src.database.connect as dbc

    real_connect = dbc.connect
    dst = tmp_path / "rebuilt.db"

    class _WrongPragma:
        def __init__(self, conn):
            self._c = conn

        def execute(self, sql, *a):
            if "PRAGMA page_size" in sql:
                class _R:
                    @staticmethod
                    def fetchone():
                        return (4096,)  # lies: reports the default, not the request
                return _R()
            return self._c.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._c, name)

    def fake_connect(path, **kw):
        conn = real_connect(path, **kw)
        return _WrongPragma(conn) if Path(path) == dst else conn

    monkeypatch.setattr(dbc, "connect", fake_connect)
    with pytest.raises(pb.BenchVerifyError):
        pb.rebuild_at_pragmas(corpus, dst, page_size=16384, auto_vacuum=2)


def _walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}"
            yield from _walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v, path)


def test_ab_run_reports_side_by_side_and_cleans_its_stages(corpus, tmp_path):
    work = tmp_path / "stage"
    report = pb.run_pagesize_ab(corpus, work, page_sizes=(4096, 16384))
    assert report["schema"] == pb.PAGESIZE_BENCH_SCHEMA
    assert report["cancelled"] is False
    assert [s["page_size"] for s in report["sizes"]] == [4096, 16384]
    for s in report["sizes"]:
        assert s["rebuild"]["verified"]["page_size"] == s["page_size"]
        for cls in ("point_lookup", "index_window", "content_band"):
            st = s["workload"]["first_pass"][cls]
            assert st["n"] > 0 and st["p50_ms"] <= st["p95_ms"]
        assert "second_pass_warm" in s["workload"]
    # No composite verdict/winner, and no banned score-family key anywhere.
    banned = ("score", "ranking", "rating", "grade", "winner")
    for key in _walk_keys(report):
        assert not any(b in key.lower() for b in banned), key
    # Sequential staging: every rebuild deleted afterwards.
    assert list(work.glob(pb._STAGE_PREFIX + "*")) == []
    assert report["caveats"] and "TREND" in " ".join(report["caveats"])


def test_ab_disk_preflight_refuses_honestly(corpus, tmp_path, monkeypatch):
    import collections

    Usage = collections.namedtuple("Usage", "total used free")
    monkeypatch.setattr(pb.shutil, "disk_usage", lambda p: Usage(100, 90, 10))
    with pytest.raises(pb.BenchRefused, match="free space"):
        pb.run_pagesize_ab(corpus, tmp_path / "stage", page_sizes=(4096,))


def test_ab_cancel_between_phases_leaves_no_stage(corpus, tmp_path):
    calls = {"n": 0}

    def stop_after_first_size():
        calls["n"] += 1
        return calls["n"] > 2  # let size 1 rebuild+bench, stop before size 2

    report = pb.run_pagesize_ab(
        corpus, tmp_path / "stage", page_sizes=(4096, 16384), should_stop=stop_after_first_size
    )
    assert report["cancelled"] is True
    done = [s for s in report["sizes"] if "workload" in s]
    assert len(done) == 1 and done[0]["page_size"] == 4096
    assert list((tmp_path / "stage").glob(pb._STAGE_PREFIX + "*")) == []


def test_stale_stages_from_a_crashed_run_are_swept(corpus, tmp_path):
    work = tmp_path / "stage"
    work.mkdir()
    (work / (pb._STAGE_PREFIX + "9999.db")).write_bytes(b"junk from a crashed run")
    report = pb.run_pagesize_ab(corpus, work, page_sizes=(4096,))
    assert report["stale_stages_swept"] >= 1
    assert not (work / (pb._STAGE_PREFIX + "9999.db")).exists()


def test_last_report_is_an_honest_stub_then_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "_report_dir", lambda: tmp_path)
    stub = pb.last_pagesize_bench_report()
    assert stub["available"] is False and "note" in stub
    pb.save_pagesize_bench_report({"schema": pb.PAGESIZE_BENCH_SCHEMA, "sizes": []})
    assert pb.last_pagesize_bench_report()["schema"] == pb.PAGESIZE_BENCH_SCHEMA
