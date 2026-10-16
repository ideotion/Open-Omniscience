"""The in-app scaling benchmark (maintainer-asked 2026-06-19).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the benchmark instrument itself behaves: it times this session's optimized
paths (grouped top-terms + super-groups via the denormalised counters; associations
+ the mind-map graph via the de-N+1), reports cold/warm aggregates with a self-
describing context, stays READ-ONLY (never reconciles the counters it measures), and
carries no composite score. The numbers it produces are the operator's to send back.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.database.models import Article, Base, Keyword, Source
from src.monitoring.benchmark import run_benchmark

# Field-name fragments that would imply a composite quality/trust score — banned
# anywhere in the benchmark payload (the honesty non-negotiable). "basis" (exact/
# estimated) is a DISCLOSURE, not a score, and is allowed.
_BANNED = ("trust_score", "credibility", "quality_score", "veracity",
           "reliability_score", "bias_score", "verdict")
_BANNED_NAMES = {"score", "rating", "rank", "trust"}


def _assert_no_score(obj, path="") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            assert kl not in _BANNED_NAMES, f"score-like key {path}.{k}"
            assert not any(b in kl for b in _BANNED), f"score-like key {path}.{k}"
            _assert_no_score(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_no_score(v, f"{path}[{i}]")


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ex = BaselineExtractor()
    texts = [
        "The Senate debated sanctions on Russia over the federal budget crisis.",
        "Russia responded to the sanctions while the budget debate continued.",
        "Sanctions and the budget dominated the Senate session on Russia.",
        "Climate policy entered the budget debate in the Senate today.",
    ]
    for i, t in enumerate(texts):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
            title="T", content=t, hash=f"h{i}", country="fr", language="en",
            published_at=datetime(2024, 3, 1, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.commit()
        index_article(s, a, extractor=ex)
    return s


def test_benchmark_payload_shape_and_context(db):
    out = run_benchmark(db, repeats=2)
    # Self-describing: corpus size, freshness, engine mode, host facts all present.
    for k in ("started_at", "repeats", "host", "store", "corpus",
              "scaling_context", "summary", "results", "method", "caveat"):
        assert k in out, f"missing top-level key {k}"
    assert out["repeats"] == 2
    assert out["corpus"]["articles"] == 4
    assert out["corpus"]["keyword_mentions"] > 0
    # Counter freshness is disclosed as a basis (exact|estimated), not a score.
    assert out["scaling_context"]["keyword_counters"]["basis"] in ("exact", "estimated")
    # The columnar engine mode is disclosed honestly.
    assert "mode" in out["scaling_context"]["columnar"]
    assert out["scaling_context"]["busiest_keyword"]["term"]  # a corpus with keywords


def test_benchmark_times_the_optimized_paths(db):
    out = run_benchmark(db, repeats=3)
    by_case = {r["case"]: r for r in out["results"]}
    # The headline optimized cases this session touched are present and ran.
    for case in ("top_terms_grouped", "supergroups", "sources_by_country", "associations",
                 "layered_graph_keyword"):
        assert case in by_case, f"missing benchmark case {case}"
        r = by_case[case]
        assert r["optimized_this_session"] is True
        assert r["ok"] is True, f"{case} failed: {r.get('error')}"
        # Cold + warm aggregates from the repeats.
        assert len(r["runs_ms"]) == 3
        assert "cold_ms" in r and "median_ms" in r
        assert "warm_median_ms" in r and "warm_min_ms" in r and "warm_max_ms" in r
        assert r["min_ms"] <= r["median_ms"] <= r["max_ms"]


def test_benchmark_single_run_has_no_warm_aggregate(db):
    out = run_benchmark(db, repeats=1)
    r = next(r for r in out["results"] if r["case"] == "top_terms_grouped")
    assert len(r["runs_ms"]) == 1
    assert r["cold_ms"] == r["median_ms"]
    assert "warm_median_ms" not in r  # one run is cold-only — no honest warm number


def test_benchmark_is_read_only(db):
    # Snapshot the rows + the counter watermark (a fresh corpus has none).
    arts = db.query(func.count(Article.id)).scalar()
    mentions = db.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar()
    watermarks_before = db.query(func.count(Keyword.last_reconciled_at)).scalar()

    run_benchmark(db, repeats=2)

    assert db.query(func.count(Article.id)).scalar() == arts
    assert db.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar() == mentions
    # The benchmark must NOT reconcile (that would stamp last_reconciled_at) — it only
    # REPORTS the counters' current freshness.
    assert db.query(func.count(Keyword.last_reconciled_at)).scalar() == watermarks_before


def test_benchmark_carries_no_score(db):
    _assert_no_score(run_benchmark(db, repeats=1), "benchmark")


def test_benchmark_summary_counts(db):
    out = run_benchmark(db, repeats=1)
    s = out["summary"]
    assert s["cases_run"] == len(out["results"])
    assert s["cases_ok"] + s["cases_failed"] == s["cases_run"]
    assert s["total_wall_ms"] >= 0


def _cases(order, ran, on_first=None):
    from src.monitoring import benchmark as bm

    def make(key):
        def fn():
            ran.append(key)
            if on_first and len(ran) == 1:
                on_first()
            return {"rows": [1]}
        return bm._Case(key, key, fn)

    return [make(k) for k in order]


def test_the_slow_trending_cases_run_last(db, monkeypatch):
    from src.monitoring import benchmark as bm

    ran: list[str] = []
    monkeypatch.setattr(bm, "_build_cases", lambda s: _cases(["trending", "map_data", "trending_windows", "who_aggregate"], ran))
    out = run_benchmark(db, repeats=1)
    assert ran == ["map_data", "who_aggregate", "trending", "trending_windows"]
    assert [r["case"] for r in out["results"]] == ran


def test_cases_after_the_deadline_are_reported_not_run_with_the_time_left(db, monkeypatch):
    import time as _t

    from src.database.maintenance import _DEADLINE_KEY
    from src.monitoring import benchmark as bm

    ran: list[str] = []
    db.info[_DEADLINE_KEY] = _t.monotonic() + 3600  # a deadline an hour away

    def pass_the_deadline():
        db.info[_DEADLINE_KEY] = _t.monotonic() - 1

    monkeypatch.setattr(bm, "_build_cases", lambda s: _cases(["a", "b", "c"], ran, on_first=pass_the_deadline))
    out = run_benchmark(db, repeats=1)
    assert ran == ["a"], "nothing is started after the deadline"
    rows = {r["case"]: r for r in out["results"]}
    assert rows["a"]["ok"] is True
    for key in ("b", "c"):
        assert rows[key]["not_run"] is True and rows[key]["error"].startswith("not run:") and "interrupted" not in rows[key]["error"]
        assert rows[key]["deadline_left_ms"] <= 0
    s = out["summary"]
    assert s["cases_run"] == 1 and s["cases_not_run"] == 2 and s["cases_failed"] == 0
    assert s["deadline"]["active"] and s["deadline"]["not_run"] == ["b", "c"] and s["deadline"]["reached_after_ms"] is not None
    assert s["deadline"]["left_ms_at_start"] > 0


def test_a_statement_stopped_by_the_deadline_says_so_not_interrupted(db, monkeypatch):
    import time as _t

    from src.database.maintenance import _DEADLINE_KEY
    from src.monitoring import benchmark as bm

    db.info[_DEADLINE_KEY] = _t.monotonic() + 3600

    def fn():
        db.info[_DEADLINE_KEY] = _t.monotonic() - 1
        raise RuntimeError("interrupted")

    monkeypatch.setattr(bm, "_build_cases", lambda s: [bm._Case("slow", "slow", fn)])
    row = run_benchmark(db, repeats=1)["results"][0]
    assert row["stopped_by_deadline"] is True and "deadline" in row["error"]


def test_without_a_deadline_nothing_is_reported_not_run(db, monkeypatch):
    from src.monitoring import benchmark as bm

    monkeypatch.setattr(bm, "_build_cases", lambda s: _cases(["a", "b"], []))
    out = run_benchmark(db, repeats=1)
    assert out["summary"]["cases_not_run"] == 0 and out["summary"]["deadline"]["active"] is False


def test_the_case_that_opens_its_own_deadline_runs_after_the_trending_cases(db, monkeypatch):
    from src.monitoring import benchmark as bm

    ran: list[str] = []
    monkeypatch.setattr(bm, "_build_cases", lambda s: _cases(["framing", "trending", "map_data", "trending_windows"], ran))
    run_benchmark(db, repeats=1)
    assert ran == ["map_data", "trending", "trending_windows", "framing"]


def test_an_error_that_is_not_the_deadlines_keeps_its_text_even_after_the_deadline(db, monkeypatch):
    import time as _t

    from src.database.maintenance import _DEADLINE_KEY
    from src.monitoring import benchmark as bm

    db.info[_DEADLINE_KEY] = _t.monotonic() + 3600

    def fn():
        db.info[_DEADLINE_KEY] = _t.monotonic() - 1
        raise KeyError("a real bug in the case")

    monkeypatch.setattr(bm, "_build_cases", lambda s: [bm._Case("x", "x", fn)])
    row = run_benchmark(db, repeats=1)["results"][0]
    assert "real bug" in row["error"] and not row.get("stopped_by_deadline")


def test_a_deadline_between_repeats_keeps_the_runs_taken_and_says_so(db, monkeypatch):
    import time as _t

    from src.database.maintenance import _DEADLINE_KEY
    from src.monitoring import benchmark as bm

    db.info[_DEADLINE_KEY] = _t.monotonic() + 3600
    ran: list[str] = []

    def first_run_passes_the_deadline():
        db.info[_DEADLINE_KEY] = _t.monotonic() - 1

    monkeypatch.setattr(bm, "_build_cases", lambda s: _cases(["a"], ran, on_first=first_run_passes_the_deadline))
    out = run_benchmark(db, repeats=3)
    row = out["results"][0]
    assert ran == ["a"] and row["ok"] is True and row["stopped_by_deadline"] is True
    assert row["runs_completed"] == 1 and row["runs_asked"] == 3
    assert out["summary"]["cases_failed"] == 0 and out["summary"]["deadline"]["reached_after_ms"] is not None


def test_an_interrupt_on_a_later_repeat_keeps_the_earlier_runs(db, monkeypatch):
    import time as _t

    from src.database.maintenance import _DEADLINE_KEY
    from src.monitoring import benchmark as bm

    db.info[_DEADLINE_KEY] = _t.monotonic() + 3600
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 2:
            db.info[_DEADLINE_KEY] = _t.monotonic() - 1
            raise RuntimeError("interrupted")
        return {"rows": [1]}

    monkeypatch.setattr(bm, "_build_cases", lambda s: [bm._Case("a", "a", fn)])
    row = run_benchmark(db, repeats=3)["results"][0]
    assert row["ok"] is True and row["runs_completed"] == 1 and row["stopped_by_deadline"] is True
