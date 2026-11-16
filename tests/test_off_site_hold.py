"""The off-site hold (R728 A and B, field test 2026-11-14).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A source whose recent pages were answered (after redirects) by ONE other site is held: disqualified with
an append-only attempt row, its off-site articles get the reversible quarantine mark, nothing is deleted,
and "this is the same outlet" (a confirmed R193 pair) re-admits it and lifts the marks.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import quarantine_job as qj
from src.catalog import off_site
from src.catalog.qualification import STATUS_DISQUALIFIED, STATUS_QUALIFIED
from src.database.models import (
    Article,
    Base,
    HostMismatchConfirmed,
    Source,
    SourceAdmissionEvent,
    SourceQualificationAttempt,
)

_BODY = "Real article text. " * 30


@pytest.fixture
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, autoflush=False)


_N = 0


def _source(s, domain: str, hosts: list[str | None], *, status: str = STATUS_QUALIFIED) -> int:
    """A qualified, enabled source whose articles (oldest first) were fetched from ``hosts``."""
    global _N
    src = Source(name=domain, domain=domain, enabled=True, status=status,
                 qualified_at=datetime(2026, 9, 10) if status == STATUS_QUALIFIED else None)
    s.add(src)
    s.commit()
    for h in hosts:
        _N += 1
        url = f"https://{domain}/p/{_N}"
        s.add(Article(url=url, canonical_url=url, source_id=src.id, content=_BODY, hash=f"h{_N}",
                      word_count=90, language="en", title=f"T{_N}", fetched_host=h))
    s.commit()
    return int(src.id)


# ------------------------------------------------------------------ the rule
def test_hijacked_source_is_held(Session):
    with Session() as s:
        sid = _source(s, "embassy.example.org", ["www.embassy.example.org"] * 5 + ["jackpot.example.com"] * 15)
        f = off_site.evaluate(s, sid, "embassy.example.org")
    assert f.state == off_site.HELD
    assert (f.source_site, f.other_site, f.n_known, f.n_other) == ("example.org", "example.com", 20, 15)


def test_no_verdict_below_the_minimum_sample(Session):
    # 9 known hosts, all off-site: below MIN_KNOWN = 10, so no verdict at all.
    with Session() as s:
        sid = _source(s, "a.example.org", [None] * 11 + ["other.example.com"] * 9)
        f = off_site.evaluate(s, sid, "a.example.org")
    assert f.state == off_site.TOO_FEW and f.n_known == 9


def test_only_the_newest_window_counts(Session):
    # The takeover is OLD: the newest 20 are all on the source's own site again.
    with Session() as s:
        sid = _source(s, "b.example.org", ["x.example.com"] * 30 + ["b.example.org"] * 20)
        assert off_site.evaluate(s, sid, "b.example.org").state == off_site.CLEAR


def test_many_other_sites_is_not_a_takeover(Session):
    # An aggregator: 16 off-site pages spread over 8 sites, no single site answers half.
    hosts = ["c.example.org"] * 4 + [f"pub{i}.example{i}.net" for i in range(8) for _ in range(2)]
    with Session() as s:
        sid = _source(s, "c.example.org", hosts)
        assert off_site.evaluate(s, sid, "c.example.org").state == off_site.CLEAR


def test_exactly_half_holds(Session):
    with Session() as s:
        sid = _source(s, "d.example.org", ["d.example.org"] * 10 + ["e.example.com"] * 10)
        assert off_site.evaluate(s, sid, "d.example.org").state == off_site.HELD


def test_subdomains_and_www_are_the_same_site(Session):
    with Session() as s:
        sid = _source(s, "news.example.co.uk", ["www.example.co.uk", "cdn.example.co.uk"] * 10)
        assert off_site.evaluate(s, sid, "news.example.co.uk").state == off_site.CLEAR


def test_listed_move_and_confirmed_pair_do_not_hold(Session):
    with Session() as s:
        moved = _source(s, "journal.revues.org", ["journals.openedition.org"] * 20)
        assert off_site.evaluate(s, moved, "journal.revues.org").state == off_site.CLEAR
        sid = _source(s, "f.example.org", ["f.example.com"] * 20)
        s.add(HostMismatchConfirmed(source_id=sid, article_site="example.com", confirmed_at=datetime(2026, 11, 1)))
        s.commit()
        assert off_site.evaluate(s, sid, "f.example.org").state == off_site.CLEAR


def test_every_listed_move_carries_evidence():
    assert off_site.LEGITIMATE_MOVES, "the list is small, not empty"
    for m in off_site.LEGITIMATE_MOVES:
        assert m.evidence.strip() and m.from_site != m.to_site
        assert off_site.site_of(m.from_site) == m.from_site and off_site.site_of(m.to_site) == m.to_site


# ------------------------------------------------------------------ the sweep, the hold, the marks
def test_sweep_holds_and_marks_only_the_off_site_articles(Session):
    with Session() as s:
        sid = _source(s, "g.example.org", ["g.example.org"] * 6 + ["jackpot.example.com"] * 14)
        ok = _source(s, "h.example.org", ["h.example.org"] * 20)
        out = off_site.sweep(s)
        assert out["held"] == 1 and out["articles_marked"] == 14 and out["checked"] >= 2
        held = s.get(Source, sid)
        assert held.status == STATUS_DISQUALIFIED and held.qualified_at is None and held.enabled is True
        att = s.query(SourceQualificationAttempt).filter_by(source_id=sid).one()
        assert (att.verdict, att.criteria_version) == (STATUS_DISQUALIFIED, off_site.CRITERIA_VERSION)
        rows = s.query(Article.fetched_host, Article.quarantined, Article.quarantine_reason).filter_by(source_id=sid).all()
        assert len(rows) == 20  # nothing deleted
        for host, q, reason in rows:
            if host == "g.example.org":
                assert not q
            else:
                assert q is True and reason == off_site.QUARANTINE_REASON
        assert s.get(Source, ok).status == STATUS_QUALIFIED


def test_sweep_is_incremental(Session):
    with Session() as s:
        _source(s, "i.example.org", ["i.example.org"] * 20)
        off_site.sweep(s)
        state = off_site._load_state(s)
        assert state["s"] is None  # the first full sweep went through every qualified source
        # Articles arrive later: the source they belong to is checked on the next run.
        sid = _source(s, "j.example.org", ["k.example.com"] * 20)
        out = off_site.sweep(s)
        assert out["held"] == 1 and s.get(Source, sid).status == STATUS_DISQUALIFIED
        assert off_site.sweep(s)["checked"] == 0  # nothing new: nothing checked


def test_a_quarantined_article_keeps_its_own_reason(Session):
    with Session() as s:
        sid = _source(s, "l.example.org", ["m.example.com"] * 20)
        first = s.query(Article).filter_by(source_id=sid).order_by(Article.id).first()
        first.quarantined, first.quarantine_reason = True, "nav_soup"
        s.commit()
        assert off_site.sweep(s)["articles_marked"] == 19
        assert s.get(Article, first.id).quarantine_reason == "nav_soup"


# ------------------------------------------------------------------ the way back (POST/DELETE host-pairs)
def _client(monkeypatch, Session):
    from src.api.quarantine import router

    monkeypatch.setattr(qj, "_default_session", lambda: Session())
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_same_outlet_readmits_and_lifts_the_marks_then_withdraw_holds_again(Session, monkeypatch):
    with Session() as s:
        sid = _source(s, "n.example.org", ["n.example.org"] * 4 + ["n-new.example.net"] * 16)
        off_site.sweep(s)
        assert s.get(Source, sid).status == STATUS_DISQUALIFIED
    c = _client(monkeypatch, Session)
    r = c.post("/api/quarantine/host-pairs", json={"source_id": sid, "article_site": "n-new.example.net"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["readmitted"] is True and body["articles_released"] == 16
    with Session() as s:
        src = s.get(Source, sid)
        assert src.status == STATUS_QUALIFIED and src.qualification_criteria_version == off_site.CONFIRMED_CRITERIA_VERSION
        assert s.query(Article).filter_by(source_id=sid, quarantined=True).count() == 0
        versions = [v for (v,) in s.query(SourceQualificationAttempt.criteria_version)
                    .filter_by(source_id=sid).order_by(SourceQualificationAttempt.id)]
        assert versions == [off_site.CRITERIA_VERSION, off_site.CONFIRMED_CRITERIA_VERSION]  # append-only
        ev = s.query(SourceAdmissionEvent).filter_by(source_id=sid).one()  # logged, undoable
        assert ev.prior_status == STATUS_DISQUALIFIED and ev.criteria_version == off_site.CONFIRMED_CRITERIA_VERSION
    w = c.delete(f"/api/quarantine/host-pairs?source_id={sid}&article_site=n-new.example.net").json()
    assert w == {"removed": 1, "held": True, "articles_marked": 16}
    with Session() as s:
        assert s.get(Source, sid).status == STATUS_DISQUALIFIED


def test_confirming_an_unrelated_site_does_not_readmit(Session, monkeypatch):
    with Session() as s:
        sid = _source(s, "o.example.org", ["o-cdn.example.net"] * 2 + ["casino.example.com"] * 18)
        off_site.sweep(s)
    c = _client(monkeypatch, Session)
    r = c.post("/api/quarantine/host-pairs", json={"source_id": sid, "article_site": "example.net"}).json()
    assert r["readmitted"] is False
    with Session() as s:
        assert s.get(Source, sid).status == STATUS_DISQUALIFIED


def test_held_payload_for_the_sources_tab(Session):
    with Session() as s:
        sid = _source(s, "p.example.org", ["p.example.org"] * 8 + ["q.example.com"] * 12)
        clean = _source(s, "r.example.org", ["r.example.org"] * 20)
        off_site.sweep(s)
        srcs = s.query(Source).filter(Source.id.in_([sid, clean])).all()
        out = off_site.held_payloads(s, srcs)
    assert set(out) == {sid}
    assert out[sid]["other_site"] == "example.com" and out[sid]["n_other"] == 12 and out[sid]["n_known"] == 20


def test_qualification_judging_holds_an_off_site_candidate(Session, monkeypatch):
    """R728 A inside judging: a trial whose pages came from another site is held, not stamped qualified."""
    from src.catalog import qualification as q

    with Session() as s:
        sid = _source(s, "s.example.org", ["casino.example.com"] * 20, status=q.STATUS_UNQUALIFIED)
        src = s.get(Source, sid)
        monkeypatch.setattr(q, "trial_fetch", lambda *a, **k: None)
        out = q.run_qualification_pass(s, None, per_pass=1, recheck_per_pass=0,
                                       now=datetime.now(UTC).replace(tzinfo=None))
        assert out.get("off_site_held") == 1, out
        s.refresh(src)
        assert src.status == STATUS_DISQUALIFIED
        assert {v for (v,) in s.query(SourceQualificationAttempt.criteria_version).filter_by(source_id=sid)} == {
            off_site.CANDIDATE_CRITERIA_VERSION}
    # Confirming a held CANDIDATE sends it back to judging; it is never qualified unjudged.
    c = _client(monkeypatch, Session)
    r = c.post("/api/quarantine/host-pairs", json={"source_id": sid, "article_site": "example.com"}).json()
    assert r["readmitted"] is False and r["requeued"] is True and r["articles_released"] == 20
    with Session() as s:
        assert s.get(Source, sid).status == q.STATUS_UNQUALIFIED
        assert s.query(SourceAdmissionEvent).filter_by(source_id=sid).count() == 0


# ------------------------------------------------------------------ hosts a hostile redirect could use to hide
def test_trailing_dot_and_ip_hosts_are_sites():
    assert off_site.site_of("casino.example.com.") == "example.com"
    assert off_site.site_of("203.0.113.9") == "203.0.113.9"
    assert off_site.site_of("[2001:db8::1]") == "2001:db8::1"
    assert off_site.site_of(None) is None and off_site.site_of("") is None


def test_redirect_to_a_trailing_dot_or_an_ip_is_held(Session):
    with Session() as s:
        a = _source(s, "t.example.org", ["casino.example.com."] * 20)
        b = _source(s, "u.example.org", ["203.0.113.9"] * 20)
        assert off_site.evaluate(s, a, "t.example.org").state == off_site.HELD
        assert off_site.evaluate(s, b, "u.example.org").state == off_site.HELD


def test_a_listed_domain_alias_is_the_same_site(Session):
    # url_utils.DOMAIN_ALIASES: the reader's own "another site" note treats bbc.com and bbc.co.uk as one.
    with Session() as s:
        sid = _source(s, "bbc.com", ["www.bbc.co.uk"] * 20)
        assert off_site.evaluate(s, sid, "bbc.com").state == off_site.CLEAR


def test_marks_are_owed_with_the_hold_and_set_by_a_later_run(Session, monkeypatch):
    """A failure after the hold commits leaves the marks OWED (queued in the hold's own transaction), never lost."""
    real = off_site.quarantine_off_site

    def boom(*a, **k):
        raise RuntimeError("disk full")

    with Session() as s:
        sid = _source(s, "v.example.org", ["v.example.org"] * 5 + ["w.example.com"] * 15)
        monkeypatch.setattr(off_site, "quarantine_off_site", boom)
        out = off_site.sweep(s)
        assert out["held"] == 1 and out["articles_marked"] == 0 and out["marks_failed"] == 1
        assert s.get(Source, sid).status == STATUS_DISQUALIFIED
        assert off_site.pending_marks(s) == [(sid, "example.com")]
        monkeypatch.setattr(off_site, "quarantine_off_site", real)
        out = off_site.sweep(s)  # nothing new to check, but the owed marks are set
        assert out["articles_marked"] == 15 and off_site.pending_marks(s) == []
        assert s.query(Article).filter_by(source_id=sid, quarantined=True).count() == 15


def test_marks_go_in_chunks(Session, monkeypatch):
    monkeypatch.setattr(off_site, "MARK_CHUNK", 4)
    with Session() as s:
        sid = _source(s, "x.example.org", ["y.example.com"] * 20)
        assert off_site.sweep(s)["articles_marked"] == 20
        assert off_site.release_off_site(s, sid, "example.com") == 20
