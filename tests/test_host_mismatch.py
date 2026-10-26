"""
Host mismatch: an article stored on a site other than its source's own (qualification lane,
2026-10-25). It is a FACT about where a page lives, not a verdict, so it is counted and sampled for
the operator and NEVER marks an article, even with write=True. Unknown (no readable site) is its
own answer and is never counted as a mismatch.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import quarantine_job as qj
from src.database.models import Article, Base, Source
from src.ingest.host_mismatch import check_host

# (article url, source domain, expected state): the false-positive cases the plan named.
CASES = [
    ("https://www.bbc.co.uk/news/1", "news.bbc.co.uk", "same"),       # subdomain / www, multi-label suffix
    ("https://amp.example.com/a", "www.example.com", "same"),         # amp / www
    ("https://m.example.com/a", "example.com", "same"),
    ("https://a.blogspot.com/x", "b.blogspot.com", "same"),           # private suffix read as the platform
    ("https://cdn.example.net/a", "example.com", "mismatch"),         # a CDN host: a fact, not a verdict
    ("https://wire.example.org/a", "paper.example.com", "mismatch"),  # wire feed
    ("https://example.com/a", "", "unknown"),                         # empty source domain
    ("https://example.com/a", None, "unknown"),
    ("not a url", "example.com", "unknown"),
    ("http://1.2.3.4/a", "1.2.3.4", "unknown"),                       # an IP names no site
    ("https://co.uk/a", "bbc.co.uk", "unknown"),                      # a bare public suffix names no registrant
    ("", "example.com", "unknown"),
    ("https://xn--mnchen-3ya.de/a", "münchen.de", "same"),            # Unicode vs punycode spelling of one site
    ("https://münchen.de/a", "xn--mnchen-3ya.de", "same"),
    ("https://foo.invalidtld/a", "bbc.co.uk", "unknown"),             # a TLD the list has no rule for
    ("https://a.b.c.local/x", "b.local", "unknown"),
]


@pytest.mark.parametrize("url,domain,state", CASES)
def test_check_host_states(url, domain, state):
    assert check_host(url, domain).state == state


def test_the_mismatching_sites_are_named_and_unknown_names_none():
    got = check_host("https://cdn.example.net/a", "example.com")
    assert (got.source_site, got.article_site) == ("example.com", "example.net")
    assert check_host("https://example.com/a", "").source_site is None


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    with Session() as s:
        own = Source(name="Own", domain="example.com")
        other = Source(name="Other", domain="paper.example.org")
        bare = Source(name="Bare", domain="")
        s.add_all([own, other, bare])
        s.commit()
        rows = [
            (own, "https://www.example.com/a", "same"),
            (own, "https://cdn.example.net/b", "mismatch"),
            (other, "https://wire.example.com/c", "mismatch"),
            (other, "https://paper.example.org/d", "same"),
            (bare, "https://example.com/e", "unknown"),
        ]
        for i, (src, url, _) in enumerate(rows):
            s.add(Article(url=url, canonical_url=url, source_id=src.id, content="Real article text. " * 30,
                          hash=f"h{i}", word_count=90, language="en", title=f"T{i}"))
        s.commit()
    return Session


def _run(Session, tmp_path, *, write, hosts=True):
    mgr = qj.QuarantineJobManager(state_path=tmp_path / "q.json")
    mgr.start(_session_factory=Session, include_host_mismatch=hosts, write=write)
    assert mgr._thread is not None
    mgr._thread.join(30)
    assert mgr.status()["state"] == "done", mgr.status()
    return mgr


def test_counts_and_sample_are_reported_and_unknown_is_not_a_mismatch(world, tmp_path):
    mgr = _run(world, tmp_path, write=False)
    tally = mgr.status()["tally"]
    assert tally["host:mismatch"] == 2 and tally["host:unknown"] == 1
    assert len(mgr.sample_ids()["host_mismatch"]) == 2


def test_it_marks_nothing_even_with_write_true(world, tmp_path):
    mgr = _run(world, tmp_path, write=True)
    assert mgr.status()["tally"].get("quarantined", 0) == 0
    assert not any(k.startswith("reason:") for k in mgr.status()["tally"])
    with world() as s:
        assert s.query(Article).filter(Article.quarantined.is_(True)).count() == 0


def test_the_default_run_does_no_host_work_and_reports_no_host_keys(world, tmp_path):
    mgr = _run(world, tmp_path, write=False, hosts=False)
    assert not any(k.startswith("host:") for k in mgr.status()["tally"])
    assert "host_mismatch" not in mgr.sample_ids()
    r = qj.default_quarantine_candidates_batch(world(), after_id=0, limit=50)
    assert "host_mismatch" not in r


def test_the_option_survives_a_pause_and_a_restart(world, tmp_path):
    mgr = _run(world, tmp_path, write=False)
    mgr._state = "paused"
    mgr._save()
    again = qj.QuarantineJobManager(state_path=tmp_path / "q.json")
    assert again.status()["include_host_mismatch"] is True


def _client(monkeypatch, world, mgr):
    from src.api.quarantine import router

    monkeypatch.setattr(qj, "get_quarantine_manager", lambda: mgr)
    monkeypatch.setattr(qj, "_default_session", lambda: world())
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_samples_endpoint_names_both_sites_and_says_it_is_a_fact_not_a_verdict(world, tmp_path, monkeypatch):
    mgr = _run(world, tmp_path, write=False)
    body = _client(monkeypatch, world, mgr).get("/api/quarantine/samples?signal=host_mismatch").json()
    sig = body["signals"]["host_mismatch"]
    assert sig["candidates"] == 2 and sig["unknown"] == 1 and "not a verdict" in sig["note"]
    pairs = {(r["source_site"], r["article_site"]) for r in sig["rows"]}
    assert pairs == {("example.com", "example.net"), ("example.org", "example.com")}
    assert all(r["already_marked"] is False for r in sig["rows"])
    assert all("source_domain" in r for r in sig["rows"])


def test_start_forwards_the_option_only_when_asked(monkeypatch):
    from src.api.quarantine import router

    calls = []

    class Fake:
        def start(self, **kw):
            calls.append(kw)
            return {}

    monkeypatch.setattr(qj, "get_quarantine_manager", lambda: Fake())
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    c.post("/api/quarantine/start")
    c.post("/api/quarantine/start?include_host_mismatch=true")
    assert "include_host_mismatch" not in calls[0]
    assert calls[1]["include_host_mismatch"] is True


def test_a_run_that_did_not_ask_reports_not_measured_never_a_zero(world, tmp_path, monkeypatch):
    mgr = _run(world, tmp_path, write=False, hosts=False)
    sig = _client(monkeypatch, world, mgr).get("/api/quarantine/samples?signal=host_mismatch").json()[
        "signals"]["host_mismatch"]
    assert sig["candidates"] is None and sig["unknown"] is None and "not measured" in sig["note"]


def test_the_source_domains_are_read_with_one_query_per_batch(world):
    from sqlalchemy import event

    session = world()
    seen: list[str] = []
    event.listen(session.get_bind(), "before_cursor_execute",
                 lambda conn, cur, stmt, *a: seen.append(stmt))
    seen.clear()
    r = qj.default_quarantine_candidates_batch(session, after_id=0, limit=50, include_host_mismatch=True)
    assert r["host_mismatch"] == {"mismatch": 2, "unknown": 1}
    assert sum("FROM sources" in q and "articles" not in q for q in seen) == 1, seen
