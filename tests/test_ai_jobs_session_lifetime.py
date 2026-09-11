"""No AI batch job holds a DB session across an LLM call (C1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics 2026-09-11. `storage_composition.last_checkpoint.readers` reported
`oldest_age_s 62500.007` -- a read transaction open **17.4 hours** -- on thread
"AnyIO worker thread", with `wal_bytes_before == wal_bytes_after == 918880`: the
checkpoint reclaimed NOTHING, because that reader pinned the WAL.

The three candidates the field brief named (`source_manager.py:76`,
`backup_v2.py:395`, `ai_check.py:367`) were each checked and each closes correctly. The
actual holders were the two AI batch jobs, which wrapped their dedup read AND their
whole slow loop in ONE `session_scope()`.

WHY PER-ARTICLE COMMITS DID NOT SAVE IT, the part worth keeping: a commit ends the
transaction, but every NON-STORING outcome -- `skipped`, `failed`, and in the language
job `none` and `vetoed` -- `continue`s without writing anything. A run made of those
(exactly what the language job does chewing repeatedly through the residue it cannot
classify) never commits at all, so the snapshot taken by the opening dedup SELECT stays
open for the whole run. Both are also GENERATORS, so a consumer that stops iterating
suspends the frame with the `with` block still entered -- the "streamed/generator
response" escape from `get_db()`'s `finally`.

Asserted STRUCTURALLY, against a stubbed `session_scope`, rather than against a live
pool: the property under test is "is a session open at this instant", which is exactly
what a counting context manager answers, and it needs no database, no threads, and no
timing -- so it cannot go flaky on a shared CI box.
"""

from __future__ import annotations

import contextlib

import pytest

from src.ai_layer.jobs import ArticleWork


class _ScopeTracker:
    """Stands in for `session_scope`, recording how deep we are at any moment."""

    def __init__(self):
        self.depth = 0
        self.opened = 0
        self.violations: list[str] = []

    @contextlib.contextmanager
    def scope(self):
        self.depth += 1
        self.opened += 1
        try:
            yield _FakeSession()
        finally:
            self.depth -= 1

    def assert_closed(self, where: str) -> None:
        if self.depth:
            self.violations.append(f"{where}: {self.depth} session(s) still open")


class _FakeSession:
    def execute(self, *_a, **_k):
        return _FakeResult()

    def commit(self):
        pass


class _FakeResult:
    def all(self):
        return []


def _work(n: int) -> list[ArticleWork]:
    return [
        ArticleWork(article_id=i, title=f"T{i}", content=f"body {i}", language="en")
        for i in range(1, n + 1)
    ]


# --------------------------------------------------------------------------- #
#  the keyword-extraction job
# --------------------------------------------------------------------------- #


def test_extract_holds_no_session_across_the_llm_call(monkeypatch):
    """The load-bearing assertion: at the instant the model is called, NO session is
    open. This fails on the shared-session shape the field bundle measured."""
    from src.ai_layer import jobs

    tracker = _ScopeTracker()
    monkeypatch.setattr(jobs, "session_scope", tracker.scope)
    monkeypatch.setattr(jobs, "sweep_text_budget", lambda *_a, **_k: None, raising=False)

    def _fake_extract(_client, _title, _content, **_kw):
        tracker.assert_closed("extract_terms (the LLM call)")
        return ["alpha", "beta"]

    monkeypatch.setattr(jobs, "extract_terms", _fake_extract)
    monkeypatch.setattr(jobs.ai_store, "record_keywords", lambda *_a, **_k: 2)

    events = list(jobs.extract_for_articles(_work(3), object(), model="m"))

    assert events[0]["event"] == "start"
    assert events[-1]["event"] == "done" and events[-1]["stored"] == 3
    assert not tracker.violations, (
        "a DB session was open across the LLM call -- the 17.4-hour read-transaction "
        f"shape C1 removed: {tracker.violations}"
    )
    # The dedup read plus one short write scope per stored article -- never one long one.
    assert tracker.opened == 4, f"expected 1 read + 3 writes, got {tracker.opened}"
    assert tracker.depth == 0


def test_extract_opens_no_write_session_when_nothing_is_stored(monkeypatch):
    """THE PRECISE FIELD MECHANISM. Every article fails, so nothing ever commits. Under
    the old shape the opening dedup SELECT's snapshot stayed open for the entire run;
    now the run ends holding nothing, and no write session is ever opened at all."""
    from src.ai_layer import jobs

    tracker = _ScopeTracker()
    monkeypatch.setattr(jobs, "session_scope", tracker.scope)
    monkeypatch.setattr(jobs, "sweep_text_budget", lambda *_a, **_k: None, raising=False)

    def _always_fails(_client, _title, _content, **_kw):
        tracker.assert_closed("extract_terms (the LLM call)")
        raise jobs.LLMError("model said no")

    monkeypatch.setattr(jobs, "extract_terms", _always_fails)

    events = list(jobs.extract_for_articles(_work(5), object(), model="m"))

    assert events[-1]["failed"] == 5 and events[-1]["stored"] == 0
    assert not tracker.violations, tracker.violations
    assert tracker.opened == 1, "only the worklist read should ever have opened a session"
    assert tracker.depth == 0


def test_abandoning_the_generator_leaves_no_session_open(monkeypatch):
    """Both jobs are GENERATORS. A consumer that walks away mid-stream (a client
    disconnecting) must not strand a session in a suspended frame -- that is how a
    reader survives for 17 hours."""
    from src.ai_layer import jobs

    tracker = _ScopeTracker()
    monkeypatch.setattr(jobs, "session_scope", tracker.scope)
    monkeypatch.setattr(jobs, "sweep_text_budget", lambda *_a, **_k: None, raising=False)
    monkeypatch.setattr(jobs, "extract_terms", lambda *_a, **_k: ["x"])
    monkeypatch.setattr(jobs.ai_store, "record_keywords", lambda *_a, **_k: 1)

    gen = jobs.extract_for_articles(_work(10), object(), model="m")
    for i, _ev in enumerate(gen):
        if i >= 2:
            break            # walk away mid-stream, exactly like a dropped client
    gen.close()

    assert tracker.depth == 0, (
        "the abandoned generator was suspended holding a session open"
    )


# --------------------------------------------------------------------------- #
#  the language-detection job -- the same defect, the same fix
# --------------------------------------------------------------------------- #


def test_langdetect_holds_no_session_across_the_llm_call(monkeypatch):
    """`skipped`, `none` and `vetoed` all continue WITHOUT writing, so this job reaches
    the never-commits state even more readily than the keyword one."""
    from src.ai_layer import langdetect_llm as ld

    tracker = _ScopeTracker()
    monkeypatch.setattr(ld, "session_scope", tracker.scope)

    def _fake_detect(_client, _title, _content, **_kw):
        tracker.assert_closed("detect_language_llm (the LLM call)")
        return "en"

    monkeypatch.setattr(ld, "detect_language_llm", _fake_detect)
    monkeypatch.setattr(ld.ai_store, "record_keywords", lambda *_a, **_k: 1)

    events = list(ld.detect_for_articles(_work(3), object(), model="m", max_workers=1))

    assert events[-1]["event"] == "done" and events[-1]["stored"] == 3
    assert not tracker.violations, tracker.violations
    assert tracker.opened == 4, f"expected 1 read + 3 writes, got {tracker.opened}"
    assert tracker.depth == 0


@pytest.mark.parametrize("answer", ["", None])
def test_langdetect_opens_no_write_session_for_an_unclassifiable_answer(monkeypatch, answer):
    """The residue case by name: an unusable answer stores NOTHING (miss over invent), so
    a whole run of them must open no write session and leave nothing open."""
    from src.ai_layer import langdetect_llm as ld

    tracker = _ScopeTracker()
    monkeypatch.setattr(ld, "session_scope", tracker.scope)
    monkeypatch.setattr(ld, "detect_language_llm", lambda *_a, **_k: answer)

    events = list(ld.detect_for_articles(_work(4), object(), model="m", max_workers=1))

    assert events[-1]["none"] == 4 and events[-1]["stored"] == 0
    assert tracker.opened == 1, "only the worklist read should ever have opened a session"
    assert tracker.depth == 0
