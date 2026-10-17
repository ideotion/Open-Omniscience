"""
A bounded, read-only sample per quarantine signal (source-qualification follow-on, 2026-10-17).

The dry run reports counts per signal; an operator cannot judge a rule from counts alone, so the job
keeps up to SAMPLE_PER_SIGNAL article IDS per signal (never titles, URLs or text in its state file)
and ``GET /api/quarantine/samples`` joins them to title + URL at read time. A sample is a spot-check,
not an error rate; it never starts a run, writes or fetches.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import quarantine_job as qj
from src.database.models import Article, Base, Source

MENU = "\n\n".join(
    ["Hopp til Hovedinnhold", "Nyhende", "Sport", "Kultur", "Meiningar", "Eigedom", "Næringsliv",
     "Cruise", "Skipstrafikken", "eAvis", "Nattmodus", "På", "Auto", "Av", "Søk", "Seksjonar"]
)
PAYWALL = "Rubriken\n\nRedan prenumerant?\n\nLogga in"


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    with Session() as s:
        src = Source(name="S", domain="example.no")
        s.add(src)
        s.commit()
        n = qj.SAMPLE_PER_SIGNAL + 5  # more menu stubs than the sample keeps
        for i in range(n):
            url = f"https://example.no/menu-{i}"
            s.add(Article(url=url, canonical_url=url, source_id=src.id, content=MENU, hash=f"m{i}",
                          word_count=len(MENU.split()), language="no", title=f"Menu title {i}"))
        for i in range(3):
            url = f"https://example.no/wall-{i}"
            s.add(Article(url=url, canonical_url=url, source_id=src.id, content=PAYWALL, hash=f"p{i}",
                          word_count=len(PAYWALL.split()), language="sv", title=f"Wall title {i}"))
        s.commit()
    return Session


def _run_dry(Session, tmp_path):
    mgr = qj.QuarantineJobManager(state_path=tmp_path / "q.json")
    mgr.start(_session_factory=Session, include_stubs=True, write=False)
    assert mgr._thread is not None
    mgr._thread.join(30)
    assert mgr.status()["state"] == "done", mgr.status()
    return mgr


def test_the_sample_is_the_smallest_hashes_whatever_order_the_chunks_arrive_in():
    ids = list(range(1, 200))
    want = sorted(ids, key=lambda i: qj._sample_rank("menu_stub", i))[: qj.SAMPLE_PER_SIGNAL]
    forward = {}
    for k in range(0, len(ids), 7):
        forward = qj.merge_samples(forward, {"menu_stub": ids[k : k + 7]})
    backward = {}
    for k in range(len(ids) - 7, -8, -7):
        backward = qj.merge_samples(backward, {"menu_stub": ids[max(k, 0) : k + 7]})
    assert forward["menu_stub"] == want == backward["menu_stub"]
    assert len(forward["menu_stub"]) == qj.SAMPLE_PER_SIGNAL


def test_a_signal_with_fewer_candidates_than_the_bound_keeps_all_of_them():
    assert sorted(qj.merge_samples({}, {"paywall_stub": [4, 9, 2]})["paywall_stub"]) == [2, 4, 9]


def test_the_batch_returns_its_candidates_per_signal_matching_its_counts(world):
    with world() as s:
        r = qj.default_quarantine_candidates_batch(s, include_stubs=True)
    assert {k: len(v) for k, v in r["ids_by_reason"].items()} == r["by_reason"]
    assert set(r["by_reason"]) == {"menu_stub", "paywall_stub"}


def test_a_dry_run_keeps_a_bounded_sample_and_writes_nothing(world, tmp_path):
    mgr = _run_dry(world, tmp_path)
    kept = mgr.sample_ids()
    assert len(kept["menu_stub"]) == qj.SAMPLE_PER_SIGNAL and len(kept["paywall_stub"]) == 3
    assert mgr.status()["tally"]["reason:menu_stub"] == qj.SAMPLE_PER_SIGNAL + 5
    with world() as s:
        assert s.query(Article).filter(Article.quarantined.is_(True)).count() == 0


def test_the_state_file_holds_ids_only_never_a_title_a_url_or_text(world, tmp_path):
    mgr = _run_dry(world, tmp_path)
    mgr._save()  # a finished run clears its file; a running or paused one writes it every chunk
    raw = (tmp_path / "q.json").read_text(encoding="utf-8")
    assert json.loads(raw)["samples"]["menu_stub"], "the sample was not persisted"
    for needle in ("Menu title", "example.no", "Hopp til", "Rubriken"):
        assert needle not in raw, needle


def test_a_paused_run_restored_after_a_restart_keeps_its_sample_and_a_resume_does_not_lose_it(world, tmp_path):
    first = _run_dry(world, tmp_path)
    first._state = "paused"
    first._save()
    again = qj.QuarantineJobManager(state_path=tmp_path / "q.json")
    assert again.sample_ids() == first.sample_ids() != {}
    again._work_fn = None
    again._session_factory = world
    again.resume()  # continues from the saved cursor, over the rest of the corpus (nothing left)
    again._thread.join(30)
    assert again.sample_ids() == first.sample_ids()


def test_a_fresh_run_starts_with_an_empty_sample(world, tmp_path):
    mgr = _run_dry(world, tmp_path)
    mgr.start(_session_factory=world, include_stubs=False, write=False)
    mgr._thread.join(30)
    assert mgr.sample_ids() == {}


def _client(monkeypatch, world, mgr):
    from src.api.quarantine import router

    monkeypatch.setattr(qj, "get_quarantine_manager", lambda: mgr)
    monkeypatch.setattr(qj, "_default_session", lambda: world())
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_endpoint_returns_titles_and_urls_only_and_marks_nothing(world, tmp_path, monkeypatch):
    mgr = _run_dry(world, tmp_path)
    c = _client(monkeypatch, world, mgr)
    r = c.get("/api/quarantine/samples", params={"signal": "menu_stub", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    sig = body["signals"]["menu_stub"]
    assert sig["shown"] == 5 and sig["candidates"] == qj.SAMPLE_PER_SIGNAL + 5
    for row in sig["rows"]:
        assert set(row) == {"id", "title", "url", "already_marked"}
        assert row["title"].startswith("Menu title") and row["url"].startswith("https://example.no/menu-")
    assert "Hopp til" not in r.text and "content" not in r.text
    assert body["run"]["dry_run"] is True and "not an error rate" in body["method"]
    with world() as s:
        assert s.query(Article).filter(Article.quarantined.is_(True)).count() == 0


def test_without_a_signal_every_signal_is_listed_and_a_limit_above_the_bound_is_clamped(world, tmp_path, monkeypatch):
    c = _client(monkeypatch, world, _run_dry(world, tmp_path))
    body = c.get("/api/quarantine/samples", params={"limit": 500}).json()
    assert set(body["signals"]) == {"menu_stub", "paywall_stub"}
    assert body["clamped"] is True and body["limit"] == qj.SAMPLE_PER_SIGNAL
    assert body["signals"]["paywall_stub"]["shown"] == 3


def test_a_sampled_article_deleted_since_reads_as_no_longer_present(world, tmp_path, monkeypatch):
    mgr = _run_dry(world, tmp_path)
    gone = mgr.sample_ids()["paywall_stub"][0]
    with world() as s:
        s.query(Article).filter(Article.id == gone).delete()
        s.commit()
    rows = _client(monkeypatch, world, mgr).get(
        "/api/quarantine/samples", params={"signal": "paywall_stub"}
    ).json()["signals"]["paywall_stub"]["rows"]
    assert {"id": gone, "present": False} in rows


def test_an_unknown_signal_or_no_run_reads_as_nothing_not_an_error(world, tmp_path, monkeypatch):
    mgr = qj.QuarantineJobManager(state_path=tmp_path / "none.json")
    body = _client(monkeypatch, world, mgr).get("/api/quarantine/samples", params={"signal": "nope"}).json()
    assert body["signals"]["nope"] == {"candidates": 0, "shown": 0, "rows": []}


def test_the_endpoint_is_a_read_that_selects_no_body():
    import inspect

    from src.api import quarantine

    src = inspect.getsource(quarantine.quarantine_samples)
    assert "Article.content" not in src and ".commit(" not in src and ".update(" not in src
    routes = [r for r in quarantine.router.routes if getattr(r, "path", "") == "/api/quarantine/samples"]
    assert routes and all(r.methods == {"GET"} for r in routes)


def test_the_batch_still_returns_everything_it_returned_before(world):
    """Additive: the new key is added, none is removed or renamed."""
    with world() as s:
        r = qj.default_quarantine_candidates_batch(s, include_stubs=True)
    assert {"scanned", "quarantined", "quarantined_ids", "already_quarantined", "newly_written",
            "by_reason", "last_id", "done", "write"} <= set(r)
