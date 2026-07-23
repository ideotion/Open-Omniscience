"""
Continuous-mode language detection (maintainer ask 2026-07-23): "the AI generated / deduced
language [job] should not be limited to 500 batches, it should be an 'on/off' switch that
allows for the continuous analysis of articles until none are left (or the leftovers are
those articles whose languages could not be deduced)".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Exercises ``src.api.ai._langdetect_worker`` directly (not through the BackgroundJob's
daemon thread — a synchronous call is deterministic and needs no polling) with a fake
Ollama client and an isolated in-memory DB. Proves the continuous loop actually chains
MULTIPLE internal batches, that classifiable and genuinely-unclassifiable articles are
both correctly accounted for, and — the load-bearing property, since a "none" result
writes no ai_keyword row — that the loop TERMINATES instead of spinning forever on the
unclassifiable residue (a real regression this file's own safety valve would catch loudly
rather than hang CI).
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import langdetect_llm as ld
from src.ai_layer.langdetect_llm import unknown_language_work
from src.api import ai as ai_api
from src.database.models import AiKeyword, Article, Base, Source
from src.llm.ollama import GenerationResult


class _FakeCtx:
    """Minimal stand-in for jobs.background.JobContext: a settable ``stopping`` flag +
    a no-op set_progress that just records calls (useful for asserting progress moved)."""

    def __init__(self, *, stop_after_iterations: int | None = None):
        self._stop_after = stop_after_iterations
        self._iterations = 0
        self.progress_calls: list[dict] = []

    @property
    def stopping(self) -> bool:
        # A SAFETY VALVE, not production logic: if the continuous loop ever regresses into
        # spinning forever on an unclassifiable residue, this trips after a generous bound
        # (reached in a fraction of a second, never by correct code for this test's small
        # fixture) so the test FAILS LOUDLY instead of hanging CI.
        self._iterations += 1
        return self._stop_after is not None and self._iterations > self._stop_after

    def set_progress(self, *, done=None, total=None, detail=None):
        self.progress_calls.append({"done": done, "total": total, "detail": detail})


class _FakeOllama:
    def __init__(self, reply):
        self.base_url = "http://127.0.0.1:11434"
        self._reply = reply

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
        text = self._reply(prompt) if callable(self._reply) else self._reply
        return GenerationResult(model=model, text=text)


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()


def _seed(session, *, tag):
    src = session.query(Source).first()
    if src is None:
        src = Source(name="s", domain=f"{uuid.uuid4().hex[:8]}.ex", language="en")
        session.add(src)
        session.flush()
    a = Article(
        url=f"https://x/{uuid.uuid4().hex}", canonical_url=f"https://x/{uuid.uuid4().hex}",
        source_id=src.id, title="T", content=f"placeholder-{tag}", language=None,
        detected_language=None, hash=uuid.uuid4().hex + uuid.uuid4().hex,
    )
    session.add(a)
    session.flush()
    # Bake the article's own id into its content so the fake client's reply function can
    # key on a marker that is guaranteed unique (autoincrement ids, not the caller-chosen tag).
    a.content = f"marker-{tag}-{a.id} un texte"
    session.flush()
    return a.id


def test_continuous_mode_chains_batches_and_terminates_on_the_residue(db, monkeypatch):
    """5 articles, an internal batch cap of 2 (limit=2) -> forces >=3 chained internal
    batches. 3 are classifiable, 2 are permanently unclassifiable ("none", no ai_keyword
    row ever written for them). continuous=True must still terminate — proving the
    exclude_ids seam, not the AI-label exclusion alone, drives the batch-to-batch
    exclusion — and every one of the 5 articles must have been attempted exactly once."""
    a1 = _seed(db, tag="A")
    a2 = _seed(db, tag="B")
    a3 = _seed(db, tag="C")
    poison1 = _seed(db, tag="P1")
    poison2 = _seed(db, tag="P2")
    db.commit()

    def _reply(prompt: str) -> str:
        if f"marker-A-{a1}" in prompt:
            return "fr"
        if f"marker-B-{a2}" in prompt:
            return "de"
        if f"marker-C-{a3}" in prompt:
            return "hu"
        # both poison articles are permanently unclassifiable: a chatty, ambiguous
        # non-answer that parse_lang rejects (never a fabricated code).
        return "I cannot tell what language this is, it seems mixed."

    @contextlib.contextmanager
    def _scope():
        yield db

    # BOTH must be patched: _langdetect_worker (src.api.ai) opens its own session_scope for
    # the pre-batch worklist query, but detect_for_articles (src.ai_layer.langdetect_llm)
    # resolves session_scope from ITS OWN module namespace for the per-article write.
    monkeypatch.setattr(ai_api, "session_scope", _scope)
    monkeypatch.setattr(ld, "session_scope", _scope)
    monkeypatch.setattr(ai_api, "OllamaClient", lambda: _FakeOllama(_reply))

    ctx = _FakeCtx(stop_after_iterations=200)  # generous; correct code never gets close
    tally = ai_api._langdetect_worker(ctx, model="m", limit=2, continuous=True)

    assert not tally.get("aborted"), "the safety valve fired -- the continuous loop never terminated"
    assert tally["ran"] is True
    assert tally["total"] == 5, "every one of the 5 seeded articles must have been attempted"
    assert tally["stored"] == 3
    assert tally["none"] == 2
    assert tally["remaining_unclassified"] == 2

    # the classifiable three landed real, distinct labels; the two poison ones stored nothing.
    for aid, code in ((a1, "fr"), (a2, "de"), (a3, "hu")):
        rows = db.query(AiKeyword).filter_by(article_id=aid, kind="language").all()
        assert len(rows) == 1 and rows[0].term == code
    for aid in (poison1, poison2):
        assert db.query(AiKeyword).filter_by(article_id=aid, kind="language").count() == 0

    # the worklist is now GENUINELY exhausted for this run (nothing left to attempt), even
    # though the two poison articles remain unlabelled in the DB -- exactly the "leftovers
    # are those whose language could not be deduced" state the maintainer described.
    remaining = {w.article_id for w in unknown_language_work(db, 10)}
    assert remaining == {poison1, poison2}


def test_non_continuous_mode_runs_exactly_one_batch_unchanged(db, monkeypatch):
    """Regression pin: continuous=False (the default) must behave BYTE-IDENTICAL to the
    pre-existing single-batch behaviour -- one bounded batch, then stop, even though
    candidates remain."""
    for i in range(5):
        _seed(db, tag=str(i))
    db.commit()

    @contextlib.contextmanager
    def _scope():
        yield db

    # BOTH must be patched: _langdetect_worker (src.api.ai) opens its own session_scope for
    # the pre-batch worklist query, but detect_for_articles (src.ai_layer.langdetect_llm)
    # resolves session_scope from ITS OWN module namespace for the per-article write.
    monkeypatch.setattr(ai_api, "session_scope", _scope)
    monkeypatch.setattr(ld, "session_scope", _scope)
    # Every article would classify if reached -- the point is that only `limit` of them are
    # ever ATTEMPTED in one non-continuous call.
    monkeypatch.setattr(ai_api, "OllamaClient", lambda: _FakeOllama(lambda _p: "fr"))

    ctx = _FakeCtx(stop_after_iterations=200)
    tally = ai_api._langdetect_worker(ctx, model="m", limit=2, continuous=False)

    assert tally["total"] == 2, "continuous=False must process exactly one bounded batch"
    assert tally["stored"] == 2
    assert not tally.get("aborted")
    remaining = {w.article_id for w in unknown_language_work(db, 10)}
    assert len(remaining) == 3, "3 of the 5 must remain untouched after one non-continuous batch"


def test_continuous_mode_stops_cleanly_on_cancel(db, monkeypatch):
    """A cancel between internal batches must stop the loop and mark the run aborted --
    the continuous loop must not treat cancellation as if the worklist were merely empty."""
    for i in range(6):
        _seed(db, tag=str(i))
    db.commit()

    @contextlib.contextmanager
    def _scope():
        yield db

    # BOTH must be patched: _langdetect_worker (src.api.ai) opens its own session_scope for
    # the pre-batch worklist query, but detect_for_articles (src.ai_layer.langdetect_llm)
    # resolves session_scope from ITS OWN module namespace for the per-article write.
    monkeypatch.setattr(ai_api, "session_scope", _scope)
    monkeypatch.setattr(ld, "session_scope", _scope)
    monkeypatch.setattr(ai_api, "OllamaClient", lambda: _FakeOllama(lambda _p: "fr"))

    # stopping becomes True immediately after the first internal batch completes (1 pre-batch
    # check + limit item-level checks inside detect_for_articles's own should_stop calls).
    ctx = _FakeCtx(stop_after_iterations=6)
    tally = ai_api._langdetect_worker(ctx, model="m", limit=2, continuous=True)

    assert tally.get("aborted") is True
    remaining = {w.article_id for w in unknown_language_work(db, 10)}
    assert len(remaining) >= 1, "cancellation must leave work genuinely unfinished"
