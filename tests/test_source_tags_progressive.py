"""
Tests for the B5 (2026-07-24 Session B) PROGRESSIVE source-tag sweep --
run_progressive_source_tags_job. Mirrors test_triage_progressive.py's shape and
test_source_tags_job.py's fixtures. Covers cursor resume across separate calls
(simulating a process restart), toggle stop/start, log append integrity, and
Source.tags staying untouched throughout (the two-class honesty rail).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import source_tags_job as J
from src.database.models import Article, Base, KeywordMention, Source


class FakeCtx:
    def __init__(self, stop_after: int | None = None) -> None:
        self._stop_after = stop_after
        self._calls = 0
        self.progress: list[tuple] = []

    @property
    def stopping(self) -> bool:
        self._calls += 1
        return self._stop_after is not None and self._calls > self._stop_after

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        self.progress.append((done, total, detail))


class FakeResult:
    def __init__(self, text: str):
        self.text = text
        self.total_duration = 500_000_000
        self.load_duration = 100_000_000
        self.prompt_eval_count = 20
        self.prompt_eval_duration = 50_000_000
        self.eval_count = 5
        self.eval_duration = 300_000_000


class FakeClient:
    """Tags every candidate 'sports' (the only vocabulary tag in this fixture)."""

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        lines = []
        for ln in prompt.splitlines():
            ln = ln.strip()
            if ln.startswith("- ") and ".test" in ln:
                domain = ln[2:].split("  [")[0]
                lines.append(f"{domain} :: sports")
        return FakeResult("\n".join(lines))


class RaisingClient:
    def generate(self, prompt, *, model, system=None, keep_alive=None):
        from src.llm.ollama import LLMUnavailable

        raise LLMUnavailable("Ollama not reachable (simulated outage)")


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db, n=7):
    """N sources, each with enough evidence (>=1 article + mention) to clear
    min_articles=1, all carrying the ASSERTED tag 'sports' (a non-empty
    vocabulary) -- and a DIFFERENT article_count each so the head-scope order is
    deterministic (the same descending-count convention triage uses)."""
    from src.database.models import Keyword

    kw = Keyword(term="football", normalized_term="football", language="en")
    db.add(kw)
    db.flush()
    for i in range(n):
        src = Source(name=f"S{i}", domain=f"s{i}.test", tags="sports", language="en")
        db.add(src)
        db.flush()
        for j in range(n - i):  # descending article_count across sources
            a = Article(
                url=f"https://s{i}.test/{j}",
                canonical_url=f"https://s{i}.test/{j}",
                source_id=src.id,
                title="T",
                content="football",
                hash=f"h{i}-{j}",
            )
            db.add(a)
            db.flush()
            db.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=3, source_id=src.id))
    db.commit()


def _session_factory(db):
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        yield db

    return _scope


def _tags_snapshot(db):
    return {s.domain: s.tags for s in db.query(Source).all()}


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_progressive_sweep_completes_covering_every_source(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)

    ctx = FakeCtx()
    res = J.run_progressive_source_tags_job(
        ctx, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=tmp_path / "state.json",
    )
    assert res["complete"] is True
    assert res["batches_completed"] == 3  # ceil(7/3)
    assert res["totals"]["sources_in"] == 7 + 2 * 3  # + the 2 canaries riding every batch
    assert res["totals"]["assigned_count"] == 7  # every REAL source got 'sports'
    assert "paused_reason" not in res

    recs = _read_jsonl(res["path"])
    assert recs[0]["schema"] == "oo-source-tags-run-1"
    assert recs[-1]["schema"] == "oo-source-tags-run-summary-1"
    assert recs[-1]["state"] == "done"


def test_progressive_sweep_resumes_from_a_persisted_cursor_across_calls(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx()
    res1 = J.run_progressive_source_tags_job(
        ctx1, model="stub:test", batch_size=3, min_articles=1,
        max_batches=1, session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res1["complete"] is False
    assert res1["batches_completed"] == 1

    ctx2 = FakeCtx()  # "restart the process"
    res2 = J.run_progressive_source_tags_job(
        ctx2, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res2["complete"] is True
    assert res2["path"] == res1["path"], "a resumed sweep must APPEND to the SAME log file"
    assert res2["batches_completed"] == 3
    assert res2["totals"]["sources_in"] == 7 + 2 * 3

    recs = _read_jsonl(res2["path"])
    schemas = [r["schema"] for r in recs]
    assert schemas.count("oo-source-tags-run-1") == 1
    assert schemas.count("oo-source-tags-run-summary-1") == 1
    assert "oo-source-tags-resume-1" in schemas

    seen_domains = set()
    for r in recs:
        if r.get("schema") == "oo-source-tags-detail-1" and r.get("status") == "tagged":
            assert r["domain"] not in seen_domains, f"{r['domain']} was tagged more than once"
            seen_domains.add(r["domain"])
    assert seen_domains == {f"s{i}.test" for i in range(7)}


def test_toggle_stop_then_start_honors_the_cursor(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx(stop_after=1)
    res1 = J.run_progressive_source_tags_job(
        ctx1, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res1["complete"] is False
    assert res1["paused_reason"] and "cancelled" in res1["paused_reason"]

    ctx2 = FakeCtx()
    res2 = J.run_progressive_source_tags_job(
        ctx2, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res2["complete"] is True
    assert res2["batches_completed"] == 3


def test_a_local_model_outage_pauses_never_errors_and_a_later_start_recovers(db, tmp_path):
    _seed(db, n=4)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx()
    res1 = J.run_progressive_source_tags_job(
        ctx1, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=RaisingClient(), state_path=state_path,
    )
    assert res1["complete"] is False
    assert res1["paused_reason"] and "unavailable" in res1["paused_reason"]
    assert res1["batches_completed"] == 0

    ctx2 = FakeCtx()
    res2 = J.run_progressive_source_tags_job(
        ctx2, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res2["complete"] is True
    assert res2["batches_completed"] == 2  # ceil(4/2); the failed attempt never counted


def test_restart_true_discards_the_cursor_and_starts_a_fresh_log(db, tmp_path):
    _seed(db, n=4)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx()
    res1 = J.run_progressive_source_tags_job(
        ctx1, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res1["complete"] is True

    ctx2 = FakeCtx()
    res2 = J.run_progressive_source_tags_job(
        ctx2, model="stub:test", batch_size=2, min_articles=1, restart=True,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res2["path"] != res1["path"]
    assert res2["complete"] is True
    assert res2["batches_completed"] == 2


def test_source_tags_column_never_written_across_the_whole_progressive_sweep(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)
    before = _tags_snapshot(db)

    ctx = FakeCtx()
    J.run_progressive_source_tags_job(
        ctx, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=tmp_path / "state.json",
    )
    assert _tags_snapshot(db) == before, "Source.tags must NEVER be written by this job"


def test_evidence_floor_skips_advance_the_cursor_without_a_model_call(db, tmp_path):
    """A page that is ENTIRELY below the evidence floor must still advance the
    cursor (never re-visit the same all-skipped page forever) and must never
    invoke the model at all."""
    from src.database.models import Keyword, Source as _Source

    kw = Keyword(term="x", normalized_term="x", language="en")
    db.add(kw)
    db.flush()
    for i in range(3):
        db.add(_Source(name=f"thin{i}", domain=f"thin{i}.test", tags="sports", language="en"))
    db.commit()
    scope = _session_factory(db)

    class _NeverCallMe:
        def generate(self, *a, **kw):
            raise AssertionError("the model must never be called for an all-skipped page")

    ctx = FakeCtx()
    res = J.run_progressive_source_tags_job(
        ctx, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=_NeverCallMe(), state_path=tmp_path / "state.json",
    )
    assert res["complete"] is True
    assert res["totals"]["sources_in"] == 0
    assert res["skipped_evidence_floor"] == 3


def test_empty_vocabulary_is_an_honest_no_op(db, tmp_path):
    from src.database.models import Source as _Source

    db.add(_Source(name="untagged", domain="untagged.test", tags=None, language="en"))
    db.commit()
    scope = _session_factory(db)

    ctx = FakeCtx()
    res = J.run_progressive_source_tags_job(
        ctx, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=tmp_path / "state.json",
    )
    assert res["complete"] is True
    assert res["batches_completed"] == 0
    assert res["totals"]["sources_in"] == 0
    assert "note" in res
