"""
Tests for the B5 (2026-07-24 Session B) PROGRESSIVE keyword-triage sweep --
run_progressive_triage_job. Mirrors test_triage_job.py's fixture pattern (no
network, an in-memory sqlite db, a FakeCtx). Covers what the brief names
explicitly: cursor resume (across separate calls, simulating a process
restart), toggle stop/start, log append integrity across resumed calls, and
the EXPORT-ONLY no-trusted-index-writes contract re-pinned for the progressive
path too.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import triage_job as J
from src.database.models import Article, Base, Keyword, KeywordMention, Source


class FakeCtx:
    """A JobContext stand-in: cooperative stop + progress capture."""

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
    """Answers every echoed keyword 'content', canaries 'junk' -- happy path."""

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        lines = []
        for ln in prompt.splitlines():
            ln = ln.strip()
            if ln.startswith("- "):
                term = ln[2:].split("  [")[0]
                verdict = "junk" if term in J.CANARY_EXPECTED else "content"
                lines.append(f"{term} :: {verdict} :: other")
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
    src = Source(name="Src", domain="src.test", tags="news")
    db.add(src)
    db.flush()
    for i in range(n):
        a = Article(
            url=f"https://src.test/{i}",
            canonical_url=f"https://src.test/{i}",
            source_id=src.id,
            title="T",
            content="c",
            hash=f"h{i}",
        )
        db.add(a)
        db.flush()
        # descending article_count so the head-scope order is deterministic and
        # every keyword clears min_articles=1 with room to spare.
        k = Keyword(
            term=f"topic{i}",
            normalized_term=f"topic{i}",
            language="en",
            article_count=n - i,
            mention_count=10,
        )
        db.add(k)
        db.flush()
        db.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=3, source_id=src.id))
    db.commit()


def _session_factory(db):
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        yield db

    return _scope


def _row_counts(db):
    return (
        db.query(Keyword).count(),
        db.query(KeywordMention).count(),
        db.query(Article).count(),
        db.query(Source).count(),
    )


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_progressive_sweep_completes_covering_every_head_scope_keyword(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)

    ctx = FakeCtx()
    res = J.run_progressive_triage_job(
        ctx,
        model="stub:test",
        batch_size=3,
        min_articles=1,
        session_factory=scope,
        client=FakeClient(),
        state_path=tmp_path / "state.json",
    )
    assert res["complete"] is True
    assert res["batches_completed"] == 3  # ceil(7/3)
    # every real keyword got a verdict + the 2 canaries ride EVERY batch
    assert res["totals"]["verdicts_out"] == 7 + 2 * 3
    assert "paused_reason" not in res

    recs = _read_jsonl(res["path"])
    assert recs[0]["schema"] == "oo-keyword-triage-run-1"
    assert recs[-1]["schema"] == "oo-keyword-triage-run-summary-1"
    assert recs[-1]["state"] == "done"


def test_progressive_sweep_resumes_from_a_persisted_cursor_across_calls(db, tmp_path):
    """Simulates a process restart: the SECOND call is a totally fresh invocation
    (a new FakeCtx, no in-memory state carried over) that must resume from the
    on-disk cursor, not re-triage what the first call already logged."""
    _seed(db, n=7)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx()
    res1 = J.run_progressive_triage_job(
        ctx1, model="stub:test", batch_size=3, min_articles=1,
        max_batches=1,  # only ONE batch this call -- an early stop, not a cancel
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res1["complete"] is False
    assert res1["batches_completed"] == 1

    # "restart the process": a brand-new FakeCtx, same state_path on disk.
    ctx2 = FakeCtx()
    res2 = J.run_progressive_triage_job(
        ctx2, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res2["complete"] is True
    assert res2["path"] == res1["path"], "a resumed sweep must APPEND to the SAME log file"
    assert res2["batches_completed"] == 3  # 1 (call 1) + 2 more (call 2) = ceil(7/3)

    # log append integrity: every line across BOTH calls parses, a resume marker
    # is present, and there is exactly ONE run header + ONE summary footer (never
    # a second header from a wrongly-fresh restart).
    recs = _read_jsonl(res2["path"])
    schemas = [r["schema"] for r in recs]
    assert schemas.count("oo-keyword-triage-run-1") == 1
    assert schemas.count("oo-keyword-triage-run-summary-1") == 1
    assert "oo-keyword-triage-resume-1" in schemas

    # no keyword was ever triaged twice (batch verdicts across the whole sweep
    # cover each real term exactly once).
    seen_terms = set()
    for r in recs:
        if r.get("schema") == "oo-keyword-triage-verdicts-1":
            for term in r.get("verdicts", {}):
                if term.startswith("topic"):
                    assert term not in seen_terms, f"{term} was triaged more than once"
                    seen_terms.add(term)
    assert seen_terms == {f"topic{i}" for i in range(7)}


def test_toggle_stop_then_start_honors_the_cursor(db, tmp_path):
    """A genuine CANCEL (ctx.stopping) leaves complete=False + a paused_reason;
    starting the toggle again (a fresh FakeCtx, same state) must continue instead
    of restarting from scratch."""
    _seed(db, n=7)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx(stop_after=1)  # stopping() true from the 2nd check onward
    res1 = J.run_progressive_triage_job(
        ctx1, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res1["complete"] is False
    assert res1["paused_reason"] and "cancelled" in res1["paused_reason"]
    assert res1["batches_completed"] == 1

    ctx2 = FakeCtx()  # "start" again
    res2 = J.run_progressive_triage_job(
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
    res1 = J.run_progressive_triage_job(
        ctx1, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=RaisingClient(), state_path=state_path,
    )
    assert res1["complete"] is False
    assert res1["paused_reason"] and "unavailable" in res1["paused_reason"]
    assert res1["batches_completed"] == 0  # the very first batch failed

    ctx2 = FakeCtx()
    res2 = J.run_progressive_triage_job(
        ctx2, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res2["complete"] is True
    assert res2["batches_completed"] == 2  # ceil(4/2), the earlier failed attempt never counted


def test_restart_true_discards_the_cursor_and_starts_a_fresh_log(db, tmp_path):
    _seed(db, n=4)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx()
    res1 = J.run_progressive_triage_job(
        ctx1, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res1["complete"] is True

    ctx2 = FakeCtx()
    res2 = J.run_progressive_triage_job(
        ctx2, model="stub:test", batch_size=2, min_articles=1, restart=True,
        session_factory=scope, client=FakeClient(), state_path=state_path,
    )
    assert res2["path"] != res1["path"], "restart=True must start a brand-new log file"
    assert res2["complete"] is True
    assert res2["batches_completed"] == 2  # re-swept from scratch, not "0 more to do"


def test_export_only_zero_trusted_index_writes_across_the_whole_progressive_sweep(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)
    before = _row_counts(db)

    ctx = FakeCtx()
    J.run_progressive_triage_job(
        ctx, model="stub:test", batch_size=3, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=tmp_path / "state.json",
    )
    assert _row_counts(db) == before


def test_progress_reports_batches_and_a_growing_verdict_count(db, tmp_path):
    _seed(db, n=5)
    scope = _session_factory(db)

    ctx = FakeCtx()
    J.run_progressive_triage_job(
        ctx, model="stub:test", batch_size=2, min_articles=1,
        session_factory=scope, client=FakeClient(), state_path=tmp_path / "state.json",
    )
    assert ctx.progress[0][2] == "starting…"
    # every subsequent call reports a strictly-nondecreasing "done" count
    dones = [d for d, _t, _detail in ctx.progress if d is not None]
    assert dones == sorted(dones)
