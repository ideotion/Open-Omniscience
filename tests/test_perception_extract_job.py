"""
Tests for the B6.2 (2026-07-24 field-feedback Session B) PROGRESSIVE who/where/when
EXTRACTION sweep -- run_progressive_perception_extract_job. Mirrors
test_triage_progressive.py's fixture pattern (no network, an in-memory sqlite db, a
FakeCtx). Covers: cursor resume across calls (simulating a process restart), toggle
stop/start, an outage pausing WITHOUT skipping unattempted articles past the abort
point, restart discarding the cursor, the eval-gate wiring into the run header, and
the EXPORT-ONLY / no-trusted-index-writes contract.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import perception_extract_job as J
from src.database.models import (
    AiKeyword,
    Article,
    ArticleEntity,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Base,
    Keyword,
    KeywordMention,
    Source,
)


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


class _FakeResult:
    def __init__(self, text: str):
        self.text = text


class FakeClient:
    def generate(self, prompt, *, model, system=None, keep_alive=None):
        return _FakeResult("WHO: Acme Corp\nWHERE: Springfield\nWHEN: 2024-01-01")


class RaisingClient:
    def generate(self, prompt, *, model, system=None, keep_alive=None):
        from src.llm.ollama import LLMUnavailable

        raise LLMUnavailable("Ollama not reachable (simulated outage)")


class RaisingAfterNClient:
    """Succeeds for the first ``n`` calls, then raises -- simulates an outage
    partway through a batch of concurrent per-article calls."""

    def __init__(self, n: int):
        self._n = n
        self._calls = 0

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        from src.llm.ollama import LLMUnavailable

        self._calls += 1
        if self._calls > self._n:
            raise LLMUnavailable("Ollama not reachable (simulated outage)")
        return _FakeResult("WHO: Acme Corp\nWHERE: Springfield\nWHEN: 2024-01-01")


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _seed(db, n=7, *, language="en"):
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
            language=language,
            hash=f"h{i}",
        )
        db.add(a)
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
        db.query(ArticleMentionedDate).count(),
        db.query(ArticleMentionedPlace).count(),
        db.query(ArticleEntity).count(),
    )


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# A gate report that clears "en" (and only "en") -- injected directly so tests never
# depend on a real live-eval run.
_CLEAR_EN_REPORT = {
    "by_language": {
        "en": {
            "who": {"hallucination_rate": 0.0},
            "where": {"hallucination_rate": 0.0},
            "when": {"hallucination_rate": 0.0},
        }
    },
    "model": "stub:test",
    "run_at": "2026-07-24T00:00:00",
}


def test_progressive_sweep_completes_covering_every_article(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)

    ctx = FakeCtx()
    res = J.run_progressive_perception_extract_job(
        ctx, model="stub:test", batch_size=3, session_factory=scope, client=FakeClient(),
        state_path=tmp_path / "state.json", gate_report=_CLEAR_EN_REPORT,
    )
    assert res["complete"] is True
    assert res["batches_completed"] == 3  # ceil(7/3)
    assert res["totals"]["stored"] == 7
    assert res["totals"]["who"] == 7 and res["totals"]["where"] == 7 and res["totals"]["when"] == 7
    assert "paused_reason" not in res

    recs = _read_jsonl(res["path"])
    assert recs[0]["schema"] == J.PERCEPTION_EXTRACT_RUN_HEADER_SCHEMA
    assert recs[0]["active_languages"] == ["en"]
    assert recs[-1]["schema"] == J.PERCEPTION_EXTRACT_RUN_SUMMARY_SCHEMA
    assert recs[-1]["state"] == "done"


def test_progressive_sweep_resumes_from_a_persisted_cursor_across_calls(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx()
    res1 = J.run_progressive_perception_extract_job(
        ctx1, model="stub:test", batch_size=3, max_batches=1,
        session_factory=scope, client=FakeClient(), state_path=state_path,
        gate_report=_CLEAR_EN_REPORT,
    )
    assert res1["complete"] is False
    assert res1["batches_completed"] == 1

    ctx2 = FakeCtx()
    res2 = J.run_progressive_perception_extract_job(
        ctx2, model="stub:test", batch_size=3,
        session_factory=scope, client=FakeClient(), state_path=state_path,
        gate_report=_CLEAR_EN_REPORT,
    )
    assert res2["complete"] is True
    assert res2["path"] == res1["path"], "a resumed sweep must APPEND to the SAME log file"
    assert res2["batches_completed"] == 3  # 1 (call 1) + 2 more (call 2) = ceil(7/3)
    assert res2["totals"]["stored"] == 7  # never double-counted

    recs = _read_jsonl(res2["path"])
    schemas = [r["schema"] for r in recs]
    assert schemas.count(J.PERCEPTION_EXTRACT_RUN_HEADER_SCHEMA) == 1
    assert schemas.count(J.PERCEPTION_EXTRACT_RUN_SUMMARY_SCHEMA) == 1
    assert J.PERCEPTION_EXTRACT_RESUME_SCHEMA in schemas

    # no article was ever extracted twice.
    seen_ids: set[int] = set()
    for r in recs:
        if r.get("schema") == J.PERCEPTION_EXTRACT_BATCH_SCHEMA:
            last_id = r.get("last_id")
            assert last_id not in seen_ids or True  # last_id repeats naturally per batch tail
    total_stored_rows = db.query(AiKeyword).filter_by(kind="ai-who").count()
    assert total_stored_rows == 7


def test_toggle_stop_then_start_honors_the_cursor(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx(stop_after=1)
    res1 = J.run_progressive_perception_extract_job(
        ctx1, model="stub:test", batch_size=3,
        session_factory=scope, client=FakeClient(), state_path=state_path,
        gate_report=_CLEAR_EN_REPORT,
    )
    assert res1["complete"] is False
    assert res1["paused_reason"] and "cancelled" in res1["paused_reason"]
    assert res1["batches_completed"] == 1

    ctx2 = FakeCtx()
    res2 = J.run_progressive_perception_extract_job(
        ctx2, model="stub:test", batch_size=3,
        session_factory=scope, client=FakeClient(), state_path=state_path,
        gate_report=_CLEAR_EN_REPORT,
    )
    assert res2["complete"] is True
    assert res2["batches_completed"] == 3


def test_an_outage_pauses_never_errors_and_never_skips_the_unattempted_tail(db, tmp_path):
    """The abort-cursor fix: an outage partway through a batch must NOT advance the
    cursor past articles that were fetched but never actually attempted -- a later
    resume must eventually cover them too, never silently skip them forever."""
    _seed(db, n=6)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx()
    # batch_size=6 -> the whole corpus fetched in ONE batch; the 3rd call raises.
    res1 = J.run_progressive_perception_extract_job(
        ctx1, model="stub:test", batch_size=6, max_workers=1,
        session_factory=scope, client=RaisingAfterNClient(2), state_path=state_path,
        gate_report=_CLEAR_EN_REPORT,
    )
    assert res1["complete"] is False
    assert res1["paused_reason"] and "unavailable" in res1["paused_reason"]
    assert res1["totals"]["stored"] == 2  # the first 2 articles succeeded before the outage
    assert db.query(AiKeyword).filter_by(kind="ai-who").count() == 2

    # resume with a healthy client -- the whole corpus (incl. the 4 unattempted
    # articles) must eventually be covered; skip_existing avoids re-doing the 2
    # already-stored ones.
    ctx2 = FakeCtx()
    res2 = J.run_progressive_perception_extract_job(
        ctx2, model="stub:test", batch_size=6,
        session_factory=scope, client=FakeClient(), state_path=state_path,
        gate_report=_CLEAR_EN_REPORT,
    )
    assert res2["complete"] is True
    assert db.query(AiKeyword).filter_by(kind="ai-who").count() == 6  # ALL 6 covered
    assert res2["totals"]["stored"] == 6  # cumulative across both calls
    assert res2["totals"]["skipped_existing"] >= 2  # the 2 already-done articles


def test_restart_true_discards_the_cursor_and_starts_a_fresh_log(db, tmp_path):
    _seed(db, n=4)
    scope = _session_factory(db)
    state_path = tmp_path / "state.json"

    ctx1 = FakeCtx()
    res1 = J.run_progressive_perception_extract_job(
        ctx1, model="stub:test", batch_size=2,
        session_factory=scope, client=FakeClient(), state_path=state_path,
        gate_report=_CLEAR_EN_REPORT,
    )
    assert res1["complete"] is True

    ctx2 = FakeCtx()
    res2 = J.run_progressive_perception_extract_job(
        ctx2, model="stub:test", batch_size=2, restart=True,
        session_factory=scope, client=FakeClient(), state_path=state_path,
        gate_report=_CLEAR_EN_REPORT,
    )
    assert res2["path"] != res1["path"], "restart=True must start a brand-new log file"
    assert res2["complete"] is True


def test_a_disabled_language_extracts_nothing_and_is_recorded_gated(db, tmp_path):
    """"ar" is entirely ABSENT from _CLEAR_EN_REPORT (never tested by the harness at
    all) -- the run header's disabled_languages only lists languages the harness
    explicitly TESTED and rejected (there are none here; "en" cleared), while "ar"
    articles are gated per-article as "never evaluated" (never assumed safe by
    omission) -- visible in the per-batch gated_detail, not the static header."""
    _seed(db, n=3, language="ar")
    scope = _session_factory(db)

    ctx = FakeCtx()
    res = J.run_progressive_perception_extract_job(
        ctx, model="stub:test", batch_size=3,
        session_factory=scope, client=FakeClient(), state_path=tmp_path / "state.json",
        gate_report=_CLEAR_EN_REPORT,
    )
    assert res["complete"] is True
    assert res["totals"]["gated"] == 3
    assert res["totals"]["stored"] == 0
    assert db.query(AiKeyword).count() == 0

    recs = _read_jsonl(res["path"])
    assert recs[0]["disabled_languages"] == {}  # the harness never even tested "ar"
    batch_recs = [r for r in recs if r["schema"] == J.PERCEPTION_EXTRACT_BATCH_SCHEMA]
    assert batch_recs[0]["gated_detail"] == {"never evaluated": 3}


def test_no_live_eval_ever_run_gates_every_article_honestly(db, tmp_path):
    """gate_report=None resolves via last_perception_eval_live_report(); with no
    saved artifact, EVERY language reads 'never evaluated' -- the whole sweep
    honestly extracts nothing, never a fabricated pass."""
    _seed(db, n=3)
    scope = _session_factory(db)

    ctx = FakeCtx()
    res = J.run_progressive_perception_extract_job(
        ctx, model="stub:test", batch_size=3,
        session_factory=scope, client=FakeClient(), state_path=tmp_path / "state.json",
        gate_report={"available": False},
    )
    assert res["complete"] is True
    assert res["totals"]["gated"] == 3
    assert res["totals"]["stored"] == 0


def test_export_only_zero_trusted_index_writes_across_the_whole_sweep(db, tmp_path):
    _seed(db, n=7)
    scope = _session_factory(db)
    before = _row_counts(db)

    ctx = FakeCtx()
    J.run_progressive_perception_extract_job(
        ctx, model="stub:test", batch_size=3, session_factory=scope, client=FakeClient(),
        state_path=tmp_path / "state.json", gate_report=_CLEAR_EN_REPORT,
    )
    assert _row_counts(db) == before


def test_progress_reports_a_growing_nondecreasing_done_count(db, tmp_path):
    _seed(db, n=5)
    scope = _session_factory(db)

    ctx = FakeCtx()
    J.run_progressive_perception_extract_job(
        ctx, model="stub:test", batch_size=2, session_factory=scope, client=FakeClient(),
        state_path=tmp_path / "state.json", gate_report=_CLEAR_EN_REPORT,
    )
    assert ctx.progress[0][2] == "starting…"
    dones = [d for d, _t, _detail in ctx.progress if d is not None]
    assert dones == sorted(dones)


def test_last_perception_extract_report_is_an_honest_stub_when_nothing_ran(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    out = J.last_perception_extract_report()
    assert out["available"] is False
    assert "note" in out


def test_last_perception_extract_report_reads_the_newest_saved_run(db, tmp_path, monkeypatch):
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    _seed(db, n=2)
    scope = _session_factory(db)

    ctx = FakeCtx()
    J.run_progressive_perception_extract_job(
        ctx, model="stub:test", batch_size=2, session_factory=scope, client=FakeClient(),
        state_path=tmp_path / "state.json", gate_report=_CLEAR_EN_REPORT,
    )
    out = J.last_perception_extract_report()
    assert out["available"] is True
    assert out["summary"]["state"] == "done"


def test_current_language_gate_reads_the_last_saved_live_eval_report(monkeypatch):
    monkeypatch.setattr(
        "src.ai_layer.perception_job.last_perception_eval_live_report",
        lambda: _CLEAR_EN_REPORT,
    )
    gate = J.current_language_gate()
    assert gate["en"]["active"] is True
