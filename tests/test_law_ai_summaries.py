"""AI change-summary layer for law revisions (2026-07-24 field-feedback Session A §3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

No network: OllamaClient is duck-typed with a fake exposing ``is_available``/
``generate`` (summarize_revision/advance_law_summaries never isinstance-check the
client). Covers: the honest no-diff/unavailable/empty degrades, full provenance on
success, the auto-eligible worklist (UI-language-floor + never-summarized +
genuine-change-only), the bounded best-effort ride-along, the adaptive per-pass
tracking budget, and the API surface (id + ai_summary on list/detail, the on-demand
endpoint, negative space).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision, LawRevisionSummary
from src.law.summarize import (
    SUMMARY_PROMPT_VERSION,
    advance_law_summaries,
    pending_ai_summaries,
    summarize_revision,
)
from src.law.track import adaptive_track_budget, auto_track_due


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


class _FakeOllama:
    """A duck-typed stand-in — summarize_revision never isinstance-checks it."""

    def __init__(self, *, available=True, text="This section now requires annual filing.", model="test-model"):
        self.available = available
        self.text = text
        self.model = model
        self.calls: list[dict] = []

    def is_available(self):
        return self.available

    def generate(self, prompt, *, model, system=None, **_kw):
        self.calls.append({"prompt": prompt, "model": model, "system": system})
        from src.llm.ollama import GenerationResult

        return GenerationResult(model=self.model, text=self.text)


def _doc(**kw):
    kw.setdefault("jurisdiction", "fr")
    kw.setdefault("title", "Loi test")
    kw.setdefault("url", "https://law.example/fr")
    kw.setdefault("watched", True)
    return LawDocument(**kw)


_REV_COUNTER = iter(range(1_000_000))


def _changed_revision(doc, **kw):
    # A counter, never id() -- this house's own lesson list warns id() reuse can
    # collide across short-lived objects; the uniqueness constraint is per-document
    # anyway, but an explicit counter keeps the fixture unambiguous regardless.
    kw.setdefault("observed_at", datetime.now(UTC))
    kw.setdefault("content_hash", f"h{next(_REV_COUNTER)}")
    kw.setdefault("delta_bytes", 40)
    kw.setdefault("diff", "+Section 4 bis added.\n-Section 4 (old) removed.")
    kw.setdefault("full_text", "the whole new text")
    kw.setdefault("flagged", False)
    return LawRevision(document_id=doc.id, **kw)


# --------------------------------------------------------------------------- #
# summarize_revision: honest degrades + full provenance on success.
# --------------------------------------------------------------------------- #


def test_summarize_revision_refuses_a_baseline_with_no_diff(db):
    doc = _doc()
    db.add(doc)
    db.commit()
    baseline = LawRevision(
        document_id=doc.id, observed_at=datetime.now(UTC), content_hash="h0",
        delta_bytes=0, diff=None, full_text="baseline text", flagged=False,
    )
    db.add(baseline)
    db.commit()

    res = summarize_revision(db, doc, baseline, _FakeOllama())
    assert res["status"] == "no_diff"
    assert db.query(LawRevisionSummary).count() == 0  # never fabricated


def test_summarize_revision_degrades_honestly_when_model_unavailable(db):
    doc = _doc()
    db.add(doc)
    db.commit()
    rev = _changed_revision(doc)
    db.add(rev)
    db.commit()

    res = summarize_revision(db, doc, rev, _FakeOllama(available=False))
    assert res["status"] == "unavailable"
    assert db.query(LawRevisionSummary).count() == 0


def test_summarize_revision_degrades_honestly_on_llm_error(db):
    doc = _doc()
    db.add(doc)
    db.commit()
    rev = _changed_revision(doc)
    db.add(rev)
    db.commit()

    class _RaisingClient(_FakeOllama):
        def generate(self, *a, **kw):
            from src.llm.ollama import LLMUnavailable

            raise LLMUnavailable("Ollama not reachable")

    res = summarize_revision(db, doc, rev, _RaisingClient())
    assert res["status"] == "unavailable" and "detail" in res
    assert db.query(LawRevisionSummary).count() == 0


def test_summarize_revision_stores_with_full_provenance(db):
    doc = _doc()
    db.add(doc)
    db.commit()
    rev = _changed_revision(doc)
    db.add(rev)
    db.commit()

    client = _FakeOllama(text="Filing deadline moved from June to September.", model="granite4:micro")
    res = summarize_revision(db, doc, rev, client)
    assert res["status"] == "ok"
    row = db.query(LawRevisionSummary).filter_by(id=res["summary_id"]).one()
    assert row.revision_id == rev.id
    assert row.summary == "Filing deadline moved from June to September."
    assert row.model == "granite4:micro"
    assert row.prompt_version == SUMMARY_PROMPT_VERSION
    assert row.prompt_text  # the EXACT system prompt used, recorded verbatim
    # the diff (not the whole document) is what actually reached the model
    assert "Section 4 bis added" in client.calls[0]["prompt"]


def test_summarize_revision_a_document_may_be_re_summarized_append_only(db):
    """Two summaries for the same revision must coexist (a later, better prompt) --
    never an in-place overwrite (mirrors ArticleAnalysis's append-only convention)."""
    doc = _doc()
    db.add(doc)
    db.commit()
    rev = _changed_revision(doc)
    db.add(rev)
    db.commit()

    summarize_revision(db, doc, rev, _FakeOllama(text="first summary"))
    summarize_revision(db, doc, rev, _FakeOllama(text="second, improved summary"))
    rows = db.query(LawRevisionSummary).filter_by(revision_id=rev.id).all()
    assert len(rows) == 2
    assert {r.summary for r in rows} == {"first summary", "second, improved summary"}


# --------------------------------------------------------------------------- #
# pending_ai_summaries: the auto-eligible worklist.
# --------------------------------------------------------------------------- #


def test_pending_ai_summaries_only_ui_language_never_summarized_genuine_changes(db):
    ui_doc = _doc(jurisdiction="fr", language="fr")
    non_ui_doc = _doc(jurisdiction="th", language="th", url="https://law.example/th")  # not a UI language
    unknown_lang_doc = _doc(jurisdiction="kh", language=None, url="https://law.example/kh")
    already_summarized_doc = _doc(jurisdiction="de", language="de", url="https://law.example/de")
    db.add_all([ui_doc, non_ui_doc, unknown_lang_doc, already_summarized_doc])
    db.commit()

    eligible = _changed_revision(ui_doc)
    non_ui_rev = _changed_revision(non_ui_doc)
    unknown_lang_rev = _changed_revision(unknown_lang_doc)
    already_summarized_rev = _changed_revision(already_summarized_doc)
    baseline_on_ui_doc = LawRevision(
        document_id=ui_doc.id, observed_at=datetime.now(UTC), content_hash="baseline-hash",
        delta_bytes=0, diff=None, full_text="baseline", flagged=False,
    )
    db.add_all([eligible, non_ui_rev, unknown_lang_rev, already_summarized_rev, baseline_on_ui_doc])
    db.commit()
    db.add(LawRevisionSummary(
        revision_id=already_summarized_rev.id, summary="already done", model="m",
        prompt_version=SUMMARY_PROMPT_VERSION,
    ))
    db.commit()

    pending = pending_ai_summaries(db, limit=10)
    ids = {rev.id for rev, _doc in pending}
    assert ids == {eligible.id}  # exactly the one genuinely-eligible revision


def test_pending_ai_summaries_respects_the_limit(db):
    doc = _doc(language="fr")
    db.add(doc)
    db.commit()
    for i in range(5):
        db.add(_changed_revision(doc, content_hash=f"h{i}"))
    db.commit()
    assert len(pending_ai_summaries(db, limit=2)) == 2
    assert len(pending_ai_summaries(db, limit=100)) == 5


# --------------------------------------------------------------------------- #
# advance_law_summaries: the scheduler ride-along (mirrors run_auto_on_ingest).
# --------------------------------------------------------------------------- #


def test_advance_law_summaries_no_op_when_model_unavailable(db):
    doc = _doc(language="fr")
    db.add(doc)
    db.commit()
    db.add(_changed_revision(doc))
    db.commit()

    out = advance_law_summaries(db, _FakeOllama(available=False))
    assert out["ran"] is False and out["stored"] == 0
    assert db.query(LawRevisionSummary).count() == 0


def test_advance_law_summaries_disabled_at_zero_limit(db):
    doc = _doc(language="fr")
    db.add(doc)
    db.commit()
    db.add(_changed_revision(doc))
    db.commit()

    out = advance_law_summaries(db, _FakeOllama(), limit=0)
    assert out == {"ran": False, "stored": 0, "skipped": 0, "failed": 0}


def test_advance_law_summaries_bounded_per_pass_and_stores(db):
    doc = _doc(language="fr")
    db.add(doc)
    db.commit()
    for i in range(3):
        db.add(_changed_revision(doc, content_hash=f"h{i}"))
    db.commit()

    out = advance_law_summaries(db, _FakeOllama(), limit=2)
    assert out["ran"] is True and out["stored"] == 2
    assert db.query(LawRevisionSummary).count() == 2  # bounded, not all 3


def test_advance_law_summaries_one_bad_revision_never_breaks_the_batch(db):
    doc = _doc(language="fr")
    db.add(doc)
    db.commit()
    good1 = _changed_revision(doc, content_hash="good1")
    bad = _changed_revision(doc, content_hash="bad", diff="+TRIGGER_FAILURE marker line.")
    good2 = _changed_revision(doc, content_hash="good2")
    db.add_all([good1, bad, good2])
    db.commit()

    class _FlakyClient(_FakeOllama):
        def generate(self, prompt, **kw):
            if "TRIGGER_FAILURE" in prompt:
                raise RuntimeError("an unexpected failure, not an LLM-layer error")
            return super().generate(prompt, **kw)

    out = advance_law_summaries(db, _FlakyClient(), limit=10)
    assert out["ran"] is True
    assert out["stored"] == 2 and out["failed"] == 1
    assert db.query(LawRevisionSummary).count() == 2


def test_advance_law_summaries_stops_when_the_model_goes_down_mid_batch(db):
    doc = _doc(language="fr")
    db.add(doc)
    db.commit()
    for i in range(3):
        db.add(_changed_revision(doc, content_hash=f"h{i}"))
    db.commit()

    class _DiesAfterOne(_FakeOllama):
        def generate(self, prompt, **kw):
            if self.calls:
                from src.llm.ollama import LLMUnavailable

                raise LLMUnavailable("down")
            return super().generate(prompt, **kw)

    out = advance_law_summaries(db, _DiesAfterOne(), limit=10)
    assert out["stored"] == 1 and out["skipped"] == 1  # stopped, never hammered the rest
    assert db.query(LawRevisionSummary).count() == 1


def test_advance_law_summaries_resolves_the_active_backend_when_no_client_given(db, monkeypatch):
    """B3 (2026-07-24 Session B): omitting ``client`` must resolve through the
    dual-backend seam (vLLM on a GPU machine, Ollama otherwise) instead of
    hardcoding Ollama -- so this ride-along benefits from vLLM too."""
    from src.llm import backend as llm_backend

    doc = _doc(language="fr")
    db.add(doc)
    db.commit()
    db.add(_changed_revision(doc, content_hash="hseam"))
    db.commit()

    fake = _FakeOllama()
    seen: list[str] = []

    def _fake_get_client_with_name(*, backend=None):
        seen.append("resolved")
        return "ollama", fake

    monkeypatch.setattr(llm_backend, "get_client_with_name", _fake_get_client_with_name)

    out = advance_law_summaries(db)  # NO client argument
    assert seen == ["resolved"], "must resolve through the backend seam, not OllamaClient()"
    assert out["stored"] == 1
    assert db.query(LawRevisionSummary).count() == 1


# --------------------------------------------------------------------------- #
# adaptive_track_budget + auto_track_due's new adaptive default.
# --------------------------------------------------------------------------- #


def test_adaptive_track_budget_bounded_both_ways():
    assert adaptive_track_budget(0) == 5
    assert adaptive_track_budget(23) == 5  # today's real corpus -- unchanged from the old default
    assert adaptive_track_budget(100) == 5
    assert adaptive_track_budget(300) == 15  # 300 // 20
    assert adaptive_track_budget(1000) == 25  # capped, never floods a single pass


def test_auto_track_due_default_batch_is_now_adaptive_not_hardcoded_five(db):
    """A small watched set still resolves to the SAME 5/pass the old hardcoded
    default gave -- byte-identical behaviour on a typical install."""
    for i in range(3):
        db.add(LawDocument(jurisdiction="uk", title=f"Act {i}", url=f"https://example.test/act{i}", watched=True))
    db.commit()

    class _StubFetcher:
        def fetch(self, url, *, require_html=True, **_kw):
            from src.ingest import FetchResult

            return FetchResult(
                requested_url=url, final_url=url, status_code=200,
                content="<html><body>" + ("word " * 60) + "</body></html>",
                content_type="text/html", fetched_at=datetime.now(UTC),
            )

    r = auto_track_due(db, _StubFetcher())  # no explicit batch -> adaptive
    assert r["documents"] == 3  # all 3 fit under the min_batch=5 floor


# --------------------------------------------------------------------------- #
# API surface: id + ai_summary on list/detail, the on-demand endpoint.
# --------------------------------------------------------------------------- #


def _law_client(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    monkeypatch.setenv("OO_AUTOSEED", "0")
    from fastapi.testclient import TestClient

    from src.api.main import app

    return TestClient(app)


class _ApiStubFetcher:
    def __init__(self, body):
        self.body = body

    def fetch(self, url, *, require_html=True, **_kw):
        from src.ingest import FetchResult

        return FetchResult(
            requested_url=url, final_url=url, status_code=200,
            content=f"<html><body>{self.body}</body></html>",
            content_type="text/html", fetched_at=datetime.now(UTC),
        )


def test_summarize_endpoint_stores_and_law_changes_then_shows_it(monkeypatch, tmp_path):
    c = _law_client(monkeypatch, tmp_path)
    body_v1 = "word " * 60
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: _ApiStubFetcher(body_v1))
    with c:
        add = c.post("/api/law/documents", json={
            "jurisdiction": "fr", "title": "Loi API test", "url": "https://law.example/api-fr",
            "language": "fr",
        })
        assert add.status_code == 200
        doc_id = add.json()["id"]

        # A second, DIFFERENT fetch produces a genuine change (delta_bytes != 0).
        # Calls track_document DIRECTLY on this ONE document rather than the bulk
        # /api/law/track (whose default limit_documents=25, ordered by ascending id,
        # would MISS a just-added document once the shared TestClient DB has
        # accumulated >= 25 earlier watched documents from other tests in a full
        # run -- test_law.py's own test_law_api comment documents this exact
        # shared-DB hazard).
        from src.database.session import SessionLocal
        from src.law.track import track_document

        body_v2 = body_v1 + " plus a whole new amended paragraph right here."
        with SessionLocal() as s:
            doc = s.query(LawDocument).filter_by(id=doc_id).one()
            track_document(s, _ApiStubFetcher(body_v2), doc)

        changes = c.get("/api/law/changes").json()["changes"]
        mine = [ch for ch in changes if ch["document_id"] == doc_id]
        assert mine, "the change must be visible in the feed"
        assert "id" in mine[0] and mine[0]["ai_summary"] is None  # not summarized yet

        rev_id = mine[0]["id"]

        fake = _FakeOllama(text="A new paragraph was added to the statute.", model="stub-model")
        monkeypatch.setattr("src.law.summarize.OllamaClient", lambda: fake)
        r = c.post(f"/api/law/revisions/{rev_id}/summarize")
        assert r.status_code == 200
        out = r.json()
        assert out["status"] == "ok"
        assert out["ai_summary"]["summary"] == "A new paragraph was added to the statute."
        assert out["ai_summary"]["model"] == "stub-model"

        # law_changes and the document detail both now surface it.
        changes2 = c.get("/api/law/changes").json()["changes"]
        mine2 = [ch for ch in changes2 if ch["id"] == rev_id][0]
        assert mine2["ai_summary"]["summary"] == "A new paragraph was added to the statute."

        detail = c.get(f"/api/law/documents/{doc_id}").json()
        det_rev = [r_ for r_ in detail["revisions"] if r_["id"] == rev_id][0]
        assert det_rev["ai_summary"]["summary"] == "A new paragraph was added to the statute."


def test_summarize_endpoint_404s_on_an_unknown_revision(monkeypatch, tmp_path):
    c = _law_client(monkeypatch, tmp_path)
    with c:
        r = c.post("/api/law/revisions/999999/summarize")
        assert r.status_code == 404


def test_summarize_endpoint_422s_on_a_baseline_with_no_diff(monkeypatch, tmp_path):
    c = _law_client(monkeypatch, tmp_path)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: _ApiStubFetcher("word " * 60))
    with c:
        add = c.post("/api/law/documents", json={
            "jurisdiction": "es", "title": "Baseline only", "url": "https://law.example/api-es",
        })
        doc_id = add.json()["id"]
        detail = c.get(f"/api/law/documents/{doc_id}").json()
        baseline_rev_id = detail["revisions"][0]["id"]  # the just-captured baseline, no diff yet

        r = c.post(f"/api/law/revisions/{baseline_rev_id}/summarize")
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Scheduler wiring (mirrors test_world_discovery_job.py's own precedent).
# --------------------------------------------------------------------------- #


def test_scheduler_ride_along_wiring():
    from pathlib import Path

    runner_src = (Path(__file__).resolve().parents[1] / "src" / "scheduler" / "runner.py").read_text("utf-8")
    assert "AI CHANGE SUMMARIES" in runner_src
    assert "from src.law.summarize import advance_law_summaries" in runner_src
    assert "sum_res = advance_law_summaries(session)" in runner_src
    # gated the SAME opt-out as tracking itself (appears twice: once for
    # auto_track_due, once for the new summarize ride-along).
    assert runner_src.count('getattr(settings, "auto_track_law", True)') >= 2
