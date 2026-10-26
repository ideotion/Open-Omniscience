"""Confirmed host-mismatch pairs (R193), their API and their restore-merge rule (R195).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

An operator can say "this source legitimately publishes on that other site". The pair is kept in a side
table keyed by (source_id, article site), never as a tag on the source; the host-mismatch report then
shows the pair as CONFIRMED instead of hiding it, and still marks nothing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import quarantine_job as qj
from src.backup.merge import merge_corpus
from src.database.models import Article, Base, HostMismatchConfirmed, Source

_BODY = "Real article text. " * 30
_META = {
    "artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0",
    "alembic_rev": "head", "manifest": None,
}


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    with Session() as s:
        own = Source(name="Own", domain="example.com")
        s.add(own)
        s.commit()
        for i, url in enumerate(
            ["https://www.example.com/a", "https://cdn.example.net/b", "https://wire.example.org/c"]
        ):
            s.add(Article(url=url, canonical_url=url, source_id=own.id, content=_BODY, hash=f"h{i}",
                          word_count=90, language="en", title=f"T{i}"))
        s.commit()
    return Session


def _client(monkeypatch, world, mgr=None):
    from src.api.quarantine import router

    monkeypatch.setattr(qj, "_default_session", lambda: world())
    if mgr is not None:
        monkeypatch.setattr(qj, "get_quarantine_manager", lambda: mgr)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _sid(world) -> int:
    with world() as s:
        return int(s.query(Source.id).filter_by(domain="example.com").scalar())


# ------------------------------------------------------------------ the API
def test_confirm_list_and_withdraw(world, monkeypatch):
    c, sid = _client(monkeypatch, world), _sid(world)
    r = c.post("/api/quarantine/host-pairs", json={"source_id": sid, "article_site": "CDN.example.net", "note": "our CDN"})
    assert r.status_code == 200, r.text
    assert r.json()["article_site"] == "example.net" and r.json()["note"] == "our CDN"
    first = r.json()["confirmed_at"]
    again = c.post("/api/quarantine/host-pairs", json={"source_id": sid, "article_site": "example.net"}).json()
    assert again["confirmed_at"] == first and again["note"] == "our CDN"  # first time and note are kept
    renoted = c.post("/api/quarantine/host-pairs", json={"source_id": sid, "article_site": "example.net", "note": "x"}).json()
    assert renoted["confirmed_at"] == first and renoted["note"] == "x"
    listed = c.get(f"/api/quarantine/host-pairs?source_id={sid}").json()
    assert listed["confirmed"] == 1 and listed["rows"][0]["article_site"] == "example.net"
    assert c.delete(f"/api/quarantine/host-pairs?source_id={sid}&article_site=example.net").json() == {"removed": 1}
    assert c.delete(f"/api/quarantine/host-pairs?source_id={sid}&article_site=example.net").json() == {"removed": 0}
    assert c.get("/api/quarantine/host-pairs").json()["confirmed"] == 0


def test_refusals(world, monkeypatch):
    c, sid = _client(monkeypatch, world), _sid(world)
    assert c.post("/api/quarantine/host-pairs", json={"source_id": 9999, "article_site": "example.net"}).status_code == 404
    assert c.post("/api/quarantine/host-pairs", json={"source_id": sid, "article_site": "foo.invalidtld"}).status_code == 422
    # no stored article of this source lives there
    assert c.post("/api/quarantine/host-pairs", json={"source_id": sid, "article_site": "nowhere.org"}).status_code == 409
    # the source's own site is never a mismatch
    assert c.post("/api/quarantine/host-pairs", json={"source_id": sid, "article_site": "example.com"}).status_code == 409
    assert c.get("/api/quarantine/host-pairs").json()["confirmed"] == 0


# --------------------------------------------------------- the job and samples
def _run(world, tmp_path):
    mgr = qj.QuarantineJobManager(state_path=tmp_path / "q.json")
    mgr.start(_session_factory=world, include_host_mismatch=True, write=True)
    mgr._thread.join(30)
    assert mgr.status()["state"] == "done", mgr.status()
    return mgr


def test_a_confirmed_pair_is_shown_as_confirmed_not_hidden_and_nothing_is_marked(world, tmp_path, monkeypatch):
    sid = _sid(world)
    with world() as s:
        s.add(HostMismatchConfirmed(source_id=sid, article_site="example.net",
                                    confirmed_at=datetime(2026, 10, 1), note="ours"))
        s.commit()
    mgr = _run(world, tmp_path)
    tally = mgr.status()["tally"]
    assert tally["host:mismatch"] == 1 and tally["host:confirmed"] == 1
    assert not any(k.startswith("reason:") for k in tally)
    with world() as s:
        assert s.query(Article).filter(Article.quarantined.is_(True)).count() == 0
    c = _client(monkeypatch, world, mgr)
    sigs = c.get("/api/quarantine/samples?signal=host_confirmed").json()["signals"]["host_confirmed"]
    assert sigs["candidates"] == 1
    row = sigs["rows"][0]
    assert (row["article_site"], row["state"], row["note"]) == ("example.net", "confirmed", "ours")
    still = c.get("/api/quarantine/samples?signal=host_mismatch").json()["signals"]["host_mismatch"]
    assert [r["article_site"] for r in still["rows"]] == ["example.org"]


def test_a_confirmation_made_during_a_pause_is_seen_by_the_next_batch(world):
    sid = _sid(world)
    before = qj.default_quarantine_candidates_batch(world(), after_id=0, limit=50, include_host_mismatch=True)
    assert before["host_mismatch"] == {"mismatch": 2, "confirmed": 0, "unknown": 0}
    with world() as s:
        s.add(HostMismatchConfirmed(source_id=sid, article_site="example.org", confirmed_at=datetime(2026, 10, 2)))
        s.commit()
    after = qj.default_quarantine_candidates_batch(world(), after_id=0, limit=50, include_host_mismatch=True)
    assert after["host_mismatch"] == {"mismatch": 1, "confirmed": 1, "unknown": 0}


# ------------------------------------------------------------- the merge rule
def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _src(s, domain: str) -> int:
    src = Source(name=domain, domain=domain)
    s.add(src)
    s.flush()
    return int(src.id)


def _pair(s, sid, site, at, note=None):
    s.add(HostMismatchConfirmed(source_id=sid, article_site=site, confirmed_at=at, note=note))


def _rows(path: Path):
    with _corpus(path)() as s:
        return [(r.article_site, r.confirmed_at, r.note) for r in
                s.query(HostMismatchConfirmed).order_by(HostMismatchConfirmed.article_site)]


T1, T2 = datetime(2026, 9, 1), datetime(2026, 10, 1)


def test_an_incoming_pair_arrives_on_the_remapped_source_and_is_tracked(tmp_path):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(live)() as s:
        _src(s, "pad.example")  # shifts ids so a raw copy would point at the wrong source
        s.commit()
    with _corpus(inc)() as s:
        sid = _src(s, "example.com")
        _pair(s, sid, "example.net", T1, "ours")
        s.commit()
    results, batch = merge_corpus(inc, live, _META)
    assert results["host_mismatch_confirmed"]["new"] == 1
    with _corpus(live)() as s:
        want = s.query(Source.id).filter_by(domain="example.com").scalar()
        got = s.query(HostMismatchConfirmed).one()
        # an incoming note always carries its provenance, even when it arrives alone
        assert got.source_id == want and got.note == f"[from merge batch {batch}] ours" and got.confirmed_at == T1
        n = s.execute(text("SELECT COUNT(*) FROM merged_rows WHERE batch_id=:b AND table_name='host_mismatch_confirmed'"),
                      {"b": batch}).scalar()
        assert n == 1


def test_both_have_it_earliest_wins_and_notes_are_joined_in_order_and_a_rerestore_changes_nothing(tmp_path):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(live)() as s:
        sid = _src(s, "example.com")
        _pair(s, sid, "example.net", T2, "local words")
        s.commit()
    with _corpus(inc)() as s:
        sid = _src(s, "example.com")
        _pair(s, sid, "example.net", T1, "older words")
        s.commit()
    _res, batch = merge_corpus(inc, live, _META)
    (site, at, note), = _rows(live)
    assert (site, at) == ("example.net", T1)
    assert note == f"[from merge batch {batch}] older words\nlocal words"
    merge_corpus(inc, live, _META)
    assert _rows(live) == [(site, at, note)]


def test_two_incoming_sources_collapsing_onto_one_leave_one_row(tmp_path):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(live)() as s:
        _src(s, "example.com")
        s.commit()
    with _corpus(inc)() as s:
        a = _src(s, "example.com")
        b = _src(s, "www.example.com")
        _pair(s, a, "example.net", T2, "b")
        _pair(s, b, "example.net", T1, "a")
        s.commit()
    merge_corpus(inc, live, _META)
    with _corpus(live)() as s:
        rows = s.query(HostMismatchConfirmed).all()
        # one row per (local source, site) whatever the collapse did to the incoming ids
        assert len({(r.source_id, r.article_site) for r in rows}) == len(rows)


def test_a_backup_from_before_the_table_existed_merges_cleanly(tmp_path):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(live)() as s:
        sid = _src(s, "example.com")
        _pair(s, sid, "example.net", T1, "mine")
        s.commit()
    with _corpus(inc)() as s:
        _src(s, "example.com")
        s.commit()
    with _corpus(inc)() as s:
        s.execute(text("DROP TABLE host_mismatch_confirmed"))
        s.commit()
    results, _batch = merge_corpus(inc, live, _META)
    assert results["host_mismatch_confirmed"]["new"] == 0
    assert _rows(live) == [("example.net", T1, "mine")]
