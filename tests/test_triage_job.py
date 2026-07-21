"""
Tests for the REAL keyword-triage job wiring (Section 8, 2026-07-20 ruling).

Drives ``run_keyword_triage_job`` directly with a ``FakeCtx`` (mirrors
``test_p0_validation.py``'s pattern) + a fake Ollama client -- no network, no
thread join needed. Proves: the job starts/reports progress/completes, a
cancelled run leaves a valid, self-describing partial JSONL log, an Ollama
outage mid-run is an honest 'error' (never a fabricated completion), and the
whole run performs ZERO writes to the trusted keyword index (the EXPORT-ONLY
contract).
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


def _seed(db, n=3):
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
        k = Keyword(
            term=f"topic{i}",
            normalized_term=f"topic{i}",
            language="en",
            article_count=5,
            mention_count=10,
        )
        db.add(k)
        db.flush()
        db.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=3, source_id=src.id))
    db.commit()


def _patch_session(monkeypatch, db):
    from contextlib import contextmanager

    @contextmanager
    def fake_scope():
        yield db
        db.commit()

    monkeypatch.setattr("src.database.session.session_scope", fake_scope)


def _row_counts(db):
    return (
        db.query(Keyword).count(),
        db.query(KeywordMention).count(),
        db.query(Article).count(),
        db.query(Source).count(),
    )


def test_job_starts_reports_progress_and_completes(db, monkeypatch, tmp_path):
    _seed(db, n=3)
    _patch_session(monkeypatch, db)
    monkeypatch.setattr(J, "_triage_dir", lambda: tmp_path)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: FakeClient())

    before = _row_counts(db)
    ctx = FakeCtx()
    res = J.run_keyword_triage_job(ctx, model="stub:test", limit=10, min_articles=1, batch_size=5)

    assert res["state"] == "done"
    assert res["batches_total"] == res["batches_completed"] == 1
    assert res["totals"]["verdicts_out"] == 5  # 3 real + 2 canaries, all valid
    assert res["canary_ok_overall"] is True
    # progress was reported at least at start and completion.
    assert ctx.progress[0] == (0, 1, "starting")
    assert ctx.progress[-1] == (1, 1, "batch 1/1")

    # EXPORT-ONLY: zero writes to the trusted keyword index.
    assert _row_counts(db) == before

    with open(res["path"], encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    schemas = [r["schema"] for r in recs]
    assert schemas == [
        "oo-keyword-triage-run-1",
        "oo-keyword-triage-batch-1",
        "oo-keyword-triage-verdicts-1",
        "oo-keyword-triage-run-summary-1",
    ]
    assert recs[-1]["state"] == "done"


def test_cancel_mid_run_leaves_a_valid_partial_log(db, monkeypatch, tmp_path):
    _seed(db, n=3)
    _patch_session(monkeypatch, db)
    monkeypatch.setattr(J, "_triage_dir", lambda: tmp_path)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: FakeClient())

    ctx = FakeCtx(stop_after=1)  # stopping() is checked once per batch iteration
    res = J.run_keyword_triage_job(ctx, model="stub:test", limit=10, min_articles=1, batch_size=1)

    assert res["state"] == "cancelled"
    assert res["batches_completed"] < res["batches_total"]
    with open(res["path"], encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]  # every line parses -> valid JSONL
    assert recs[0]["schema"] == "oo-keyword-triage-run-1"
    assert recs[-1]["schema"] == "oo-keyword-triage-run-summary-1"
    assert recs[-1]["state"] == "cancelled"


def test_ollama_outage_mid_run_is_an_honest_error_never_a_fabricated_completion(
    db, monkeypatch, tmp_path
):
    _seed(db, n=2)
    _patch_session(monkeypatch, db)
    monkeypatch.setattr(J, "_triage_dir", lambda: tmp_path)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: RaisingClient())

    ctx = FakeCtx()
    res = J.run_keyword_triage_job(ctx, model="stub:test", limit=10, min_articles=1, batch_size=5)

    assert res["state"] == "error"
    assert res["error"] and "simulated outage" in res["error"]
    with open(res["path"], encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    assert recs[-1]["schema"] == "oo-keyword-triage-run-summary-1"
    assert recs[-1]["state"] == "error"
    assert recs[-1]["batches_completed"] == 0


def test_last_report_reads_header_and_footer_from_the_newest_file(db, monkeypatch, tmp_path):
    _seed(db, n=2)
    _patch_session(monkeypatch, db)
    monkeypatch.setattr("src.llm.ollama.OllamaClient", lambda *a, **kw: FakeClient())
    monkeypatch.setattr(J, "_triage_dir", lambda: tmp_path)

    assert J.last_keyword_triage_report()["available"] is False  # honest stub, nothing run yet

    ctx = FakeCtx()
    J.run_keyword_triage_job(ctx, model="stub:test", limit=10, min_articles=1, batch_size=5)

    last = J.last_keyword_triage_report()
    assert last["available"] is True
    assert last["run_header"]["model"] == "stub:test"
    assert last["summary"]["state"] == "done"
