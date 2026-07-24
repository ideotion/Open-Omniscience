"""
Transient-failure resilience + auto-start for AI language detection
(2026-07-24 field-feedback Session A §1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Root cause (maintainer field report): ``OllamaClient.generate`` maps ANY ``httpx.HTTPError``
-- including its own 120s per-call read timeout -- to ``LLMUnavailable``, and the continuous
run's worker loop treated that identically to a genuine "Ollama is down": it hard-aborted into
a benign-looking ``done``, so a single slow response silently ended a "keep going until none
are left" run. These tests pin the fix: a transient outage retries with backoff and the run
stays alive; only after ``_LANGDETECT_MAX_CONSECUTIVE_FAILURES`` in a row does it give up, and
it does so LOUDLY (the outer BackgroundJob state genuinely becomes ``error``, not ``done``).
Also covers the auto-start ride-along and the persisted last-run state file.
"""

from __future__ import annotations

import contextlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.ai_layer import langdetect_llm as ld
from src.api import ai as ai_api
from src.llm import backend as llm_backend
from src.database.models import AiKeyword, Article, Base, Source
from src.llm.ollama import GenerationResult, LLMUnavailable

_ROOT = Path(__file__).resolve().parents[1]


class _FakeCtx:
    """Mirrors test_ai_langdetect_continuous.py's stand-in for JobContext."""

    def __init__(self, *, stop_after_iterations: int | None = None):
        self._stop_after = stop_after_iterations
        self._iterations = 0
        self.progress_calls: list[dict] = []

    @property
    def stopping(self) -> bool:
        self._iterations += 1
        return self._stop_after is not None and self._iterations > self._stop_after

    def set_progress(self, *, done=None, total=None, detail=None):
        self.progress_calls.append({"done": done, "total": total, "detail": detail})


class _FlakyOllama:
    """Raises LLMUnavailable on the first ``fail_times`` generate() calls, then answers
    normally (or forever, if ``fail_times`` exceeds the number of calls the test makes)."""

    def __init__(self, reply, *, fail_times: int):
        self.base_url = "http://127.0.0.1:11434"
        self._reply = reply
        self._fail_times = fail_times
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise LLMUnavailable("simulated transient outage")
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
    a.content = f"marker-{tag}-{a.id} un texte"
    session.flush()
    return a.id


def _fast_backoff(monkeypatch):
    """Tests must not really sleep for seconds -- shrink the backoff to milliseconds."""
    monkeypatch.setattr(ai_api, "_LANGDETECT_BACKOFF_BASE_S", 0.01)
    monkeypatch.setattr(ai_api, "_LANGDETECT_BACKOFF_CAP_S", 0.02)


def test_a_transient_outage_retries_and_the_run_stays_alive(db, monkeypatch, tmp_path):
    """One simulated timeout on the ONLY candidate must NOT abort the run: the same
    article is retried (never dropped, never double-counted as a separate candidate)
    and ends up stored once the backend recovers."""
    a1 = _seed(db, tag="A")
    db.commit()

    def _reply(prompt: str) -> str:
        assert f"marker-A-{a1}" in prompt
        return "fr"

    @contextlib.contextmanager
    def _scope():
        yield db

    monkeypatch.setattr(ai_api, "session_scope", _scope)
    monkeypatch.setattr(ld, "session_scope", _scope)
    flaky = _FlakyOllama(_reply, fail_times=1)
    monkeypatch.setattr(
        llm_backend, "get_client_with_name", lambda *a, **kw: ("ollama", flaky)
    )
    monkeypatch.setattr(ai_api, "_langdetect_state_path", lambda: tmp_path / "state.json")
    _fast_backoff(monkeypatch)

    ctx = _FakeCtx(stop_after_iterations=2000)  # generous; a real retry loop is quick
    tally = ai_api._langdetect_worker(ctx, model="m", limit=10, continuous=True)

    assert not tally.get("aborted"), "a transient outage must never read as a user cancel"
    assert "error" not in tally, "the run must not give up after recovering"
    assert tally["stored"] == 1
    assert flaky.calls == 2, "exactly one retry after the one simulated failure"
    row = db.query(AiKeyword).filter_by(article_id=a1, kind="language").one()
    assert row.term == "fr"


def test_n_consecutive_failures_gives_up_loudly_never_as_done(db, monkeypatch, tmp_path):
    """A backend that never recovers must not spin forever: after the configured
    consecutive-failure budget, the worker RAISES (so the outer BackgroundJob state
    genuinely becomes 'error', not a benign-looking 'done') -- proven at the direct-call
    level here, and at the real BackgroundJob-thread level below."""
    _seed(db, tag="A")
    db.commit()

    @contextlib.contextmanager
    def _scope():
        yield db

    monkeypatch.setattr(ai_api, "session_scope", _scope)
    monkeypatch.setattr(ld, "session_scope", _scope)
    monkeypatch.setattr(
        llm_backend, "get_client_with_name", lambda *a, **kw: ("ollama", _FlakyOllama("fr", fail_times=10_000))
    )
    monkeypatch.setattr(ai_api, "_langdetect_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(ai_api, "_LANGDETECT_MAX_CONSECUTIVE_FAILURES", 3)
    _fast_backoff(monkeypatch)

    ctx = _FakeCtx(stop_after_iterations=2000)
    with pytest.raises(RuntimeError, match="3 consecutive"):
        ai_api._langdetect_worker(ctx, model="m", limit=10, continuous=True)

    # the persisted state file records the honest terminal reason too (§1 item 3).
    state_path = ai_api._langdetect_state_path()
    assert state_path.exists()
    persisted = ai_api._load_langdetect_state()
    assert persisted["state"] == "error"
    assert "3 consecutive" in persisted["error"]


def test_a_genuine_cancel_still_stops_immediately_no_retry(db, monkeypatch, tmp_path):
    """Cancellation must never be mistaken for a transient outage and retried."""
    _seed(db, tag="A")
    db.commit()

    @contextlib.contextmanager
    def _scope():
        yield db

    monkeypatch.setattr(ai_api, "session_scope", _scope)
    monkeypatch.setattr(ld, "session_scope", _scope)
    monkeypatch.setattr(
        llm_backend, "get_client_with_name", lambda *a, **kw: ("ollama", _FlakyOllama("fr", fail_times=10_000))
    )
    monkeypatch.setattr(ai_api, "_langdetect_state_path", lambda: tmp_path / "state.json")
    _fast_backoff(monkeypatch)

    # stopping flips True after the pre-batch check + the item-level should_stop call inside
    # detect_for_articles's first (failing) attempt -- well before any retry budget matters.
    ctx = _FakeCtx(stop_after_iterations=1)
    tally = ai_api._langdetect_worker(ctx, model="m", limit=10, continuous=True)
    assert tally.get("aborted") is True
    assert "error" not in tally


def test_langdetect_job_reaches_error_state_after_repeated_transient_failures(
    monkeypatch, tmp_path
):
    """Unlike the keyword-triage job's documented 'done, result.state=error' wrinkle, the
    langdetect job's OUTER BackgroundJob state must genuinely read 'error' -- the generic
    /api/jobs task-manager list has no langdetect-specific knowledge, so raising is the
    only way it can see the outage without special-casing. Exercises the REAL
    BackgroundJob.start() (a thread, joined), the wiring an operator actually hits."""
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    src = Source(name="s", domain="x.example", language="en")
    session.add(src)
    session.flush()
    session.add(
        Article(
            url="https://x/1", canonical_url="https://x/1", source_id=src.id, title="T",
            content="marker text", language=None, detected_language=None,
            hash=uuid.uuid4().hex + uuid.uuid4().hex,
        )
    )
    session.commit()

    @contextlib.contextmanager
    def fake_scope():
        yield session
        session.commit()

    # BOTH must be patched: _langdetect_worker (src.api.ai) opens its own session_scope
    # for the pre-batch worklist query, but detect_for_articles (src.ai_layer.langdetect_llm)
    # resolves session_scope from ITS OWN module namespace for the per-article write --
    # each did `from src.database.session import session_scope` at MODULE load time, so
    # patching the origin module after the fact does not reach either copied binding.
    monkeypatch.setattr(ai_api, "session_scope", fake_scope)
    monkeypatch.setattr(ld, "session_scope", fake_scope)
    monkeypatch.setattr(
        llm_backend, "get_client_with_name", lambda *a, **kw: ("ollama", _FlakyOllama("fr", fail_times=10_000))
    )
    monkeypatch.setattr(ai_api, "_langdetect_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(ai_api, "_LANGDETECT_MAX_CONSECUTIVE_FAILURES", 2)
    _fast_backoff(monkeypatch)

    # a stale prior run from another test module may still be registered — reset it
    with ai_api._LANGDETECT_JOB._lock:
        ai_api._LANGDETECT_JOB._state = "idle"
        ai_api._LANGDETECT_JOB._thread = None

    ai_api._LANGDETECT_JOB.start(model="stub:test", limit=10, continuous=True)
    ai_api._LANGDETECT_JOB._thread.join(10)

    st = ai_api._LANGDETECT_JOB.status()
    assert st["state"] == "error", "the outer job state must genuinely say error, never 'done'"
    assert "consecutive" in (st.get("error") or "").lower()


def test_advance_langdetect_auto_start_respects_the_setting(db, monkeypatch, tmp_path):
    """The ride-along is a named skip, never a silent no-op, at every gate."""
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)

    class _Settings:
        ai_langdetect_auto = False

    monkeypatch.setattr(
        "src.config.app_settings.load_settings", lambda: _Settings()
    )
    out = ai_api.advance_langdetect_auto_start(db)
    assert out == {"enabled": False}


def test_advance_langdetect_auto_start_skips_when_already_running(db, monkeypatch, tmp_path):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)

    class _Settings:
        ai_langdetect_auto = True

    monkeypatch.setattr("src.config.app_settings.load_settings", lambda: _Settings())
    monkeypatch.setattr(
        ai_api._LANGDETECT_JOB, "status", lambda: {"state": "running"}
    )
    out = ai_api.advance_langdetect_auto_start(db)
    assert out == {"enabled": True, "skipped": "already running"}


def test_advance_langdetect_auto_start_skips_when_model_unavailable(db, monkeypatch, tmp_path):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)

    class _Settings:
        ai_langdetect_auto = True

    monkeypatch.setattr("src.config.app_settings.load_settings", lambda: _Settings())
    monkeypatch.setattr(ai_api._LANGDETECT_JOB, "status", lambda: {"state": "idle"})

    class _Down:
        def is_available(self):
            return False

    monkeypatch.setattr(
        llm_backend, "get_client_with_name", lambda *a, **kw: ("ollama", _Down())
    )
    out = ai_api.advance_langdetect_auto_start(db)
    assert out == {"enabled": True, "skipped": "the local model is unavailable"}


def test_advance_langdetect_auto_start_skips_when_no_candidates(db, monkeypatch, tmp_path):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)

    class _Settings:
        ai_langdetect_auto = True

    monkeypatch.setattr("src.config.app_settings.load_settings", lambda: _Settings())
    monkeypatch.setattr(ai_api._LANGDETECT_JOB, "status", lambda: {"state": "idle"})

    class _Up:
        def is_available(self):
            return True

    monkeypatch.setattr(
        llm_backend, "get_client_with_name", lambda *a, **kw: ("ollama", _Up())
    )
    # db is empty -- zero unknown-language candidates
    out = ai_api.advance_langdetect_auto_start(db)
    assert out == {"enabled": True, "skipped": "no unknown-language candidates"}


def test_advance_langdetect_auto_start_starts_the_job_when_due(db, monkeypatch, tmp_path):
    _seed(db, tag="A")
    db.commit()
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)

    class _Settings:
        ai_langdetect_auto = True

    monkeypatch.setattr("src.config.app_settings.load_settings", lambda: _Settings())
    monkeypatch.setattr(ai_api._LANGDETECT_JOB, "status", lambda: {"state": "idle"})

    class _Up:
        def is_available(self):
            return True

    monkeypatch.setattr(
        llm_backend, "get_client_with_name", lambda *a, **kw: ("ollama", _Up())
    )
    started = {}
    monkeypatch.setattr(
        ai_api._LANGDETECT_JOB, "start",
        lambda **kw: (started.update(kw), {"state": "running"})[1],
    )
    out = ai_api.advance_langdetect_auto_start(db)
    assert out == {"enabled": True, "started": True}
    assert started == {"continuous": True}


def test_persisted_state_survives_and_status_merges_it_when_idle(db, monkeypatch, tmp_path):
    """§1 item 3: after a run, the status line must stay honest even in a FRESH process
    (no in-memory result) -- the persisted file is merged into /detect-language/status
    additively, without disturbing the live-run 'state'/'result' contract."""
    monkeypatch.setattr(ai_api, "_langdetect_state_path", lambda: tmp_path / "state.json")
    assert ai_api._load_langdetect_state() is None  # nothing persisted yet

    ai_api._save_langdetect_state({"stored": 3, "none": 1, "total": 4, "state": "done"})
    persisted = ai_api._load_langdetect_state()
    assert persisted is not None
    assert persisted["stored"] == 3 and persisted["state"] == "done"

    with ai_api._LANGDETECT_JOB._lock:
        ai_api._LANGDETECT_JOB._state = "idle"
        ai_api._LANGDETECT_JOB._result = None
        ai_api._LANGDETECT_JOB._thread = None
        ai_api._LANGDETECT_JOB._error = None
    resp = ai_api.ai_detect_language_status()
    assert resp["state"] == "idle"
    assert resp["last_run"]["stored"] == 3


def test_scheduler_ride_along_wiring():
    """Source-level guard (the world-discovery/qualification precedent): the ride-along
    must actually be called from the scheduler's post-pass housekeeping, best-effort
    (never breaking a scrape), and its opt-out setting must exist on AppSettings + the
    PUT /api/settings schema — so the 'default ON, background, automated' ruling cannot
    silently regress."""
    runner_src = (_ROOT / "src" / "scheduler" / "runner.py").read_text("utf-8")
    app_settings_src = (_ROOT / "src" / "config" / "app_settings.py").read_text("utf-8")
    settings_api_src = (_ROOT / "src" / "api" / "settings.py").read_text("utf-8")

    assert "advance_langdetect_auto_start(session)" in runner_src
    assert '"langdetect_auto"] = _ld' in runner_src
    assert "never fail the scrape on the AI-layer watchdog" in runner_src
    assert "ai_langdetect_auto: bool = True" in app_settings_src  # default ON (the ruling)
    assert "ai_langdetect_auto: bool | None = None" in settings_api_src  # PUT parity
