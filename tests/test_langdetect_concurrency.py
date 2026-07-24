"""B3 (2026-07-24 Session B): the continuous langdetect job adopts the bounded
concurrency helper. Exercises ``detect_for_articles`` directly with
``max_workers`` -- order preservation, real overlap, and per-item error
isolation -- without going through the BackgroundJob machinery."""

from __future__ import annotations

import threading
import time
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer.jobs import ArticleWork
from src.ai_layer.langdetect_llm import LANG_KIND, detect_for_articles
from src.database.models import AiKeyword, Base, Source
from src.llm.ollama import GenerationResult, LLMError


class _TrackingClient:
    def __init__(self, delay: float = 0.02):
        self._delay = delay
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(self._delay)
        finally:
            with self._lock:
                self._active -= 1
        # deterministic reply keyed on which marker is present
        for code in ("fr", "de", "hu", "es", "it", "nl"):
            if f"[{code}]" in prompt:
                return GenerationResult(model=model, text=code)
        return GenerationResult(model=model, text="unknown")


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _work(codes: list[str]) -> list[ArticleWork]:
    return [
        ArticleWork(i + 1, f"title {i}", f"marker text [{code}]", None)
        for i, code in enumerate(codes)
    ]


def test_detect_for_articles_preserves_order_under_real_concurrency(monkeypatch):
    session = _db()
    src = Source(name="s", domain=f"{uuid.uuid4().hex[:8]}.ex", language="en")
    session.add(src)
    session.commit()

    import contextlib

    from src.ai_layer import langdetect_llm as ld

    @contextlib.contextmanager
    def _scope():
        yield session

    monkeypatch.setattr(ld, "session_scope", _scope)

    codes = ["fr", "de", "hu", "es", "it", "nl"]
    work = _work(codes)
    client = _TrackingClient(delay=0.02)
    events = list(
        detect_for_articles(work, client, model="m", skip_existing=False, max_workers=6)
    )
    items = [e for e in events if e["event"] == "item"]
    assert [i["article_id"] for i in items] == [w.article_id for w in work]
    assert [i["language"] for i in items] == codes
    assert events[-1]["event"] == "done" and events[-1]["stored"] == 6
    # proves REAL overlap, not a disguised serial loop
    assert client.max_active > 1


def test_detect_for_articles_default_is_serial(monkeypatch):
    session = _db()
    src = Source(name="s", domain=f"{uuid.uuid4().hex[:8]}.ex", language="en")
    session.add(src)
    session.commit()

    import contextlib

    from src.ai_layer import langdetect_llm as ld

    @contextlib.contextmanager
    def _scope():
        yield session

    monkeypatch.setattr(ld, "session_scope", _scope)

    codes = ["fr", "de", "hu"]
    work = _work(codes)
    client = _TrackingClient(delay=0.01)
    events = list(
        detect_for_articles(work, client, model="m", skip_existing=False)  # max_workers default
    )
    items = [e for e in events if e["event"] == "item"]
    assert [i["article_id"] for i in items] == [w.article_id for w in work]
    assert client.max_active == 1


def test_detect_for_articles_isolates_a_failure_under_concurrency(monkeypatch):
    session = _db()
    src = Source(name="s", domain=f"{uuid.uuid4().hex[:8]}.ex", language="en")
    session.add(src)
    session.commit()

    import contextlib

    from src.ai_layer import langdetect_llm as ld

    @contextlib.contextmanager
    def _scope():
        yield session

    monkeypatch.setattr(ld, "session_scope", _scope)

    class _FlakyOnce:
        def __init__(self):
            self.calls = 0

        def is_available(self):
            return True

        def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
            self.calls += 1
            if self.calls == 2:
                raise LLMError("transient")
            for code in ("fr", "de", "hu"):
                if f"[{code}]" in prompt:
                    return GenerationResult(model=model, text=code)
            return GenerationResult(model=model, text="unknown")

    work = _work(["fr", "de", "hu"])
    events = list(
        detect_for_articles(
            work, _FlakyOnce(), model="m", skip_existing=False, max_workers=3
        )
    )
    items = [e for e in events if e["event"] == "item"]
    assert {i["status"] for i in items} == {"stored", "failed"}
    assert sum(1 for i in items if i["status"] == "failed") == 1
    done = events[-1]
    assert done["event"] == "done" and not done["aborted"]
    assert done["stored"] == 2 and done["failed"] == 1
    # sibling successes in the SAME concurrent chunk must have been stored
    assert session.query(AiKeyword).filter_by(kind=LANG_KIND).count() == 2
