"""The law lane end to end on the synthetic jurisdiction, with no name resolved.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1018 = a asks for a synthetic edition, extract and jurisdiction "so every lane's
pipeline runs end-to-end in CI without a socket". The wiki lane has had that test since
S04-09 (``tests/test_wiki_lane_end_to_end.py``). The law lane had the fixture
(``tests/fixtures/law/synthetic/``, S04-10) and its analytics tests, but nothing
measured that a pass through it resolves no name; this is that test, for S04-08's S5.

It drives ``_lane_step_law`` -- the scheduler's own law step, not a helper beside it --
across two passes (the first capture, then the amendment) with the airplane socket
guard INSTALLED and the kill switch CLEAR, and counts resolutions rather than requests:
a DNS lookup is itself egress. The AI summary ride-along in the same step is stubbed as
unavailable. It is loopback-only by its own guard and has its own tests; left live, its
probe of the local model would count as a resolution here without being egress.

The second half is the refusal: the same step with a REAL fetcher and airplane mode on
must refuse by name and still resolve nothing.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision
from src.ingest import activate_kill_switch, clear_kill_switch
from src.versioned import store

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "law" / "synthetic"


class _Result:
    def __init__(self, body: bytes) -> None:
        self.raw_content = body
        self.content = body.decode("utf-8")
        self.content_type = "application/xml"


class _ScriptedFetcher:
    """Serves the fixture captures in order: the client half of the lane, recorded."""

    def __init__(self, names: list[str]) -> None:
        self._bodies = [(_FIXTURES / f"{n}.clml.xml").read_bytes() for n in names]
        self.calls = 0

    def fetch(self, _url, **_kw):
        body = self._bodies[min(self.calls, len(self._bodies) - 1)]
        self.calls += 1
        return _Result(body)


class _NoModel:
    def is_available(self) -> bool:
        return False


@pytest.fixture
def corpus(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'corpus.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, future=True)
    engine.dispose()


@pytest.fixture
def lane(tmp_path, monkeypatch):
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    for var in ("OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"):
        monkeypatch.delenv(var, raising=False)
    import src.llm.backend as backend

    monkeypatch.setattr(backend, "get_client_with_name", lambda *a, **k: ("stub", _NoModel()))
    try:
        store.create_lane("law")
        yield tmp_path
    finally:
        store.dispose_all()


@pytest.fixture
def resolutions(monkeypatch):
    """Every name resolution, counted beneath the INSTALLED airplane guard."""
    from src.ingest.airplane import install_airplane_socket_guard

    clear_kill_switch()
    install_airplane_socket_guard()
    seen: list[tuple] = []
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (seen.append(a), real(*a, **k))[1])
    try:
        yield seen
    finally:
        clear_kill_switch()


def _watched(session) -> LawDocument:
    doc = LawDocument(
        jurisdiction="ZZZ",
        title="Measurement Standards Act",
        url="https://gazette.zzz.test/act/2019/7/data.xml",
        official_url="https://gazette.zzz.test/act/2019/7",
        category="legislation",
        consolidated=True,
        language="zxx",
        watched=True,
    )
    session.add(doc)
    session.commit()
    return doc


def _pass(session, fetcher) -> dict:
    from src.scheduler.runner import _lane_step_law
    from src.scheduler.settings import SchedulerSettings

    return _lane_step_law(session, fetcher, SchedulerSettings())


def test_two_passes_record_the_baseline_and_the_amendment_and_resolve_ZERO_names(
    corpus, lane, resolutions
):
    with corpus() as session:
        doc = _watched(session)
        first = _pass(session, _ScriptedFetcher(["act.v1"]))
        # The step polls a document at most once a day; age the check rather than the
        # clock, so the second pass sees it as due exactly as a later day's pass would.
        doc.last_checked_at = datetime.now(UTC) - timedelta(days=2)
        session.commit()
        second = _pass(session, _ScriptedFetcher(["act.v2"]))
        revisions = session.query(LawRevision).filter(LawRevision.document_id == doc.id).count()

    # Anti-vacuity: the passes did the work, so "nothing resolved" is about real work.
    assert first["baselines"] == 1 and first["errors"] == 0, first
    assert second["changed"] == 1 and second["errors"] == 0, second
    assert revisions == 2
    assert resolutions == [], f"the law lane resolved {len(resolutions)} name(s): {resolutions}"


def test_the_same_pass_is_REFUSED_BY_NAME_in_airplane_mode_and_still_resolves_nothing(
    corpus, lane, resolutions
):
    """A real fetcher this time: the refusal is the fetch path's own, not a double's."""
    from src.safety.fetcher import make_fetcher

    fetcher = make_fetcher()
    activate_kill_switch()
    with corpus() as session:
        doc = _watched(session)
        out = _pass(session, fetcher)
        status = doc.last_status or ""

    assert out["errors"] == 1 and out["baselines"] == 0, out
    assert "kill switch" in status.lower(), (
        f"the refusal does not say it is airplane mode: {status!r} (invariant #14e's corollary)"
    )
    assert resolutions == [], f"airplane mode resolved {len(resolutions)} name(s): {resolutions}"
