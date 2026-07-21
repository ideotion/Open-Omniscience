"""
Tests for the REAL source-tag-assignment job wiring (same chassis as
``test_triage_job.py``). Proves: the job starts/reports progress/completes,
cancel mid-run leaves a valid partial JSONL log, an Ollama outage mid-run is an
honest 'error', and -- the honesty rail specific to this run -- the catalog's
ASSERTED ``Source.tags`` is read (to build the vocabulary) but NEVER written;
every proposed tag lives ONLY in the JSONL log, labelled 'ai-proposed'.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import source_tags_job as J
from src.database.models import Article, Base, Keyword, KeywordMention, Source


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
    """Tags the real source 'sports' (in-vocabulary); ignores canaries whose
    expected tags are not in this tiny corpus's vocabulary."""

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        lines = []
        for ln in prompt.splitlines():
            ln = ln.strip()
            if ln.startswith("- "):
                domain = ln[2:].split("  [")[0]
                if domain == "espn.test":
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


def _seed(db):
    src = Source(name="ESPN", domain="espn.test", tags="sports")
    db.add(src)
    db.flush()
    kw = Keyword(term="football", normalized_term="football", language="en")
    db.add(kw)
    db.flush()
    for i in range(5):
        a = Article(
            url=f"https://espn.test/{i}",
            canonical_url=f"https://espn.test/{i}",
            source_id=src.id,
            title="T",
            content="football",
            hash=f"h{i}",
        )
        db.add(a)
        db.flush()
        db.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=3, source_id=src.id))
    db.commit()
    return src


def _patch_session(monkeypatch, db):
    from contextlib import contextmanager

    @contextmanager
    def fake_scope():
        yield db
        db.commit()

    monkeypatch.setattr("src.database.session.session_scope", fake_scope)


def test_job_starts_reports_progress_and_completes(db, monkeypatch, tmp_path):
    _seed(db)
    _patch_session(monkeypatch, db)
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: FakeClient())

    ctx = FakeCtx()
    res = J.run_source_tags_job(ctx, model="stub:test", top_n=50, min_articles=1, batch_size=10)

    assert res["state"] == "done"
    assert res["totals"]["assigned_count"] == 1  # espn.test -> sports
    assert ctx.progress[0][2] == "starting"
    with open(res["path"], encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    assert recs[0]["schema"] == "oo-source-tags-run-1"
    assert recs[-1]["schema"] == "oo-source-tags-run-summary-1"
    assert recs[-1]["state"] == "done"


def test_cancel_mid_run_leaves_a_valid_partial_log(db, monkeypatch, tmp_path):
    _seed(db)
    _patch_session(monkeypatch, db)
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: FakeClient())

    ctx = FakeCtx(stop_after=0)  # stop before the first (only) batch even starts
    res = J.run_source_tags_job(ctx, model="stub:test", top_n=50, min_articles=1, batch_size=1)

    assert res["state"] == "cancelled"
    with open(res["path"], encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    assert recs[-1]["schema"] == "oo-source-tags-run-summary-1"
    assert recs[-1]["state"] == "cancelled"


def test_ollama_outage_mid_run_is_an_honest_error(db, monkeypatch, tmp_path):
    _seed(db)
    _patch_session(monkeypatch, db)
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: RaisingClient())

    ctx = FakeCtx()
    res = J.run_source_tags_job(ctx, model="stub:test", top_n=50, min_articles=1, batch_size=10)

    assert res["state"] == "error"
    assert res["error"] and "simulated outage" in res["error"]


def test_deduced_tags_never_touch_the_asserted_source_tags_column(db, monkeypatch, tmp_path):
    """The honesty rail: Source.tags (ASSERTED, catalog-owned) is read to build the
    closed vocabulary but is NEVER mutated by this run -- the proposed tag lives
    ONLY in the JSONL log's 'ai-proposed' channel. This is the two-class
    asserted-vs-deduced separation FOR THIS SESSION (export-only; the future
    apply step is explicitly out of scope, see the module docstring)."""
    src = _seed(db)
    asserted_tags_before = src.tags
    row_count_before = db.query(Source).count()

    _patch_session(monkeypatch, db)
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: FakeClient())

    ctx = FakeCtx()
    res = J.run_source_tags_job(ctx, model="stub:test", top_n=50, min_articles=1, batch_size=10)
    assert res["totals"]["assigned_count"] == 1  # a tag WAS proposed this run

    # The catalog row is untouched, byte-for-byte.
    db.expire_all()
    src_after = db.query(Source).filter_by(domain="espn.test").one()
    assert src_after.tags == asserted_tags_before == "sports"
    assert db.query(Source).count() == row_count_before

    # The proposed tag lives ONLY in the JSONL, explicitly labelled 'ai-proposed'.
    with open(res["path"], encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    detail = [
        r
        for r in recs
        if r.get("schema") == "oo-source-tags-detail-1" and r.get("domain") == "espn.test"
    ]
    assert detail and detail[0]["provenance"] == "ai-proposed"
    assert detail[0]["proposed_tags"] == ["sports"]


def test_empty_vocabulary_is_an_honest_no_op_never_sent_to_the_model(db, monkeypatch, tmp_path):
    # No source in this tiny corpus carries an asserted tag yet -- the closed
    # vocabulary is empty. The job must skip the model entirely (never burn a real
    # inference call to prove nothing) and say so honestly.
    src = Source(name="Untagged", domain="untagged.test", tags=None)
    db.add(src)
    db.flush()
    a = Article(
        url="https://untagged.test/0",
        canonical_url="https://untagged.test/0",
        source_id=src.id,
        title="T",
        content="c",
        hash="u-h0",
    )
    db.add(a)
    db.flush()
    kw = Keyword(term="widget", normalized_term="widget", language="en")
    db.add(kw)
    db.flush()
    db.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=5, source_id=src.id))
    db.commit()

    called = []

    class SpyClient(FakeClient):
        def generate(self, prompt, *, model, system=None, keep_alive=None):
            called.append(prompt)
            return super().generate(prompt, model=model, system=system, keep_alive=keep_alive)

    _patch_session(monkeypatch, db)
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: SpyClient())

    ctx = FakeCtx()
    res = J.run_source_tags_job(ctx, model="stub:test", top_n=50, min_articles=1, batch_size=10)

    assert res["state"] == "done"
    assert res["batches_total"] == 0
    assert called == []  # the model was NEVER called
    with open(res["path"], encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    assert recs[0]["vocabulary"] == []
    assert recs[-1]["schema"] == "oo-source-tags-run-summary-1"
    assert recs[-1]["state"] == "done"


def test_evidence_floor_skip_is_logged_and_never_sent_to_the_model(db, monkeypatch, tmp_path):
    # A second, thin source below the floor must be logged as skipped, and its
    # domain must never appear in a batch prompt sent to the (spying) client.
    src2 = Source(name="Thin", domain="thin.test", tags=None)
    db.add(src2)
    db.flush()
    a = Article(
        url="https://thin.test/0",
        canonical_url="https://thin.test/0",
        source_id=src2.id,
        title="T",
        content="c",
        hash="thin-h0",
    )
    db.add(a)
    db.flush()
    kw = Keyword(term="stub", normalized_term="stub", language="en")
    db.add(kw)
    db.flush()
    db.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1, source_id=src2.id))
    db.commit()
    _seed(db)

    seen_prompts = []

    class SpyClient(FakeClient):
        def generate(self, prompt, *, model, system=None, keep_alive=None):
            seen_prompts.append(prompt)
            return super().generate(prompt, model=model, system=system, keep_alive=keep_alive)

    _patch_session(monkeypatch, db)
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: SpyClient())

    ctx = FakeCtx()
    res = J.run_source_tags_job(ctx, model="stub:test", top_n=50, min_articles=3, batch_size=10)

    assert res["skipped_evidence_floor"] == 1
    assert not any("thin.test" in p for p in seen_prompts)  # never sent to the model

    with open(res["path"], encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    skips = [r for r in recs if r.get("status") == "skipped" and r.get("domain") == "thin.test"]
    assert skips and skips[0]["reason"] == "insufficient evidence"
