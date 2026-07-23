"""
S3.1 (2026-07-23 field-feedback workflow) — the TEMPORARY criteria-calibration diagnostic.

A REPORT over the existing detectors (scan_non_article_candidates + the prose gate), never
new judging: covers the top-N sample collection (URL-shape reasons + the prose-gate
subpass), per-article detail fetch, aggregation, the top_n cap, honest skip of a vanished
id, and the no-score-field discipline.

NEGATIVE SPACE: a real article (substantial word_count, real prose) is NEVER collected,
whatever its URL or length.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.analytics.criteria_calibration import CRITERIA_VERSION, calibration_report
from src.database.models import Article, Base, Source

_BANNED = ("score", "ranking", "rating", "grade")


def _walk_no_score(o) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            assert not any(b in str(k).lower() for b in _BANNED), k
            _walk_no_score(v)
    elif isinstance(o, list):
        for v in o:
            _walk_no_score(v)


_NAV_SOUP_BODY = (
    "News Latest Irish News Mirror Bingo Soccer Golf Rugby Union Sport Business Politics "
    "World News Travel Money Markets Weather Video Photos Gallery Podcast Newsletters Events "
    "About Contact Home Search Login Sign Up Subscribe Cookies Advertisement Privacy Terms "
    "Follow Facebook Twitter Instagram Newsletter Preference Centre Manage Subscriptions "
    "Menu Toggle Navigation Skip Content Latest News Sport GAA Rugby Soccer Racing Golf Boxing "
    "Motors Showbiz TV Fashion Beauty Food Recipes Property Travel Family Voucher Codes Bingo "
    "Dating Contact Advertise Cookie Policy Privacy Policy Terms Conditions Modern Slavery "
    "Statement Complaints Regulation Archive Sitemap Jobs Shop Weddings Announcements Obituaries "
    "Horoscopes Puzzles Crosswords Competitions Vouchers Discounts Deals Reviews Betting Casino "
    "Lottery Results Traffic Cameras Roadworks Bus Times Train Times Flight Tracker Currency "
    "Converter Recipes Wine Beer Cocktails Restaurants Bars Nightlife Theatre Cinema Music Books"
)
_REAL_PROSE_BODY = (
    "The government said on Tuesday that it would review the policy after months of criticism "
    "from opposition lawmakers, who argued that the reform had failed to deliver the promised "
    "benefits to the region's struggling economy. Officials declined to give a firm timetable "
    "for the review, but said a report would follow before the end of the year, once "
    "consultations with local councils and community groups had concluded. "
) * 2


def _corpus() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="News", domain="news.example", language="en", enabled=True)
    s.add(src)
    s.flush()
    aid = [0]

    def add(url, wc, content="x", title=None):
        aid[0] += 1
        s.add(Article(url=url, canonical_url=url, source_id=src.id, content=content,
                      hash=f"h{aid[0]}", word_count=wc, language="en", title=title or f"t{aid[0]}"))

    add("https://news.example/2026/07/election-results", 500, content=_REAL_PROSE_BODY,
        title="Real article")  # real article -- kept
    add("https://news.example/", 10, title="Homepage")                    # homepage
    add("https://news.example/tag/gaza", 5, title="Tag: Gaza")            # taxonomy listing
    add("https://news.example/business", 8, title="Business section")     # section landing
    add("https://news.example/newsletter-preference-centre",
        len(_NAV_SOUP_BODY.split()), content=_NAV_SOUP_BODY,
        title="Newsletter preferences")                                  # nav soup (prose gate)
    s.commit()
    return s


def test_calibration_report_collects_url_shape_and_prose_gate_specimens():
    s = _corpus()
    out = calibration_report(s, top_n=100, prose_gate_limit=2000)

    assert out["schema"] == "oo-criteria-calibration-1"
    assert out["criteria_version"] == CRITERIA_VERSION

    criteria_seen = {a["criterion"] for a in out["articles"]}
    assert criteria_seen == {"url_homepage", "url_taxonomy", "url_section", "nav_soup"}

    # the real article is NEVER collected (negative space).
    titles = {a["title"] for a in out["articles"]}
    assert "Real article" not in titles

    # every collected article carries the full documented field set.
    for a in out["articles"]:
        for field in ("id", "title", "url", "source", "word_count", "language",
                      "best_matching_language", "function_word_density",
                      "sentence_punct_density", "criterion"):
            assert field in a, f"missing field {field}"
    assert all(a["source"] == "News" for a in out["articles"])
    assert all(a["language"] == "en" for a in out["articles"])

    # the nav-soup specimen's density numbers are genuinely low/low (the prose-gate shape).
    nav = next(a for a in out["articles"] if a["criterion"] == "nav_soup")
    assert nav["function_word_density"] < 0.12
    assert nav["sentence_punct_density"] < 0.01

    per_criterion = {r["criterion"]: r["count"] for r in out["aggregates"]["per_criterion"]}
    assert per_criterion["url_homepage"] == 1
    assert per_criterion["url_taxonomy"] == 1
    assert per_criterion["url_section"] == 1
    assert per_criterion["nav_soup"] == 1

    per_source = {r["source"]: r["count"] for r in out["aggregates"]["per_source"]}
    assert per_source["News"] == len(out["articles"])

    per_language = {r["language"]: r["count"] for r in out["aggregates"]["per_language"]}
    assert per_language["en"] == len(out["articles"])

    assert out["collected"] == len(out["articles"])
    assert "base_scan" in out and out["base_scan"]["schema"] == "oo-non-article-scan-1"


def test_calibration_report_caps_at_top_n():
    s = _corpus()
    out = calibration_report(s, top_n=2, prose_gate_limit=2000)
    assert out["collected"] <= 2
    assert len(out["articles"]) <= 2


def test_calibration_report_never_fabricates_a_vanished_row(monkeypatch):
    """An id the base scan reported can vanish before the detail fetch (a concurrent
    delete/prune) -- it must be silently skipped, never invented."""
    from src.analytics.criteria_calibration import calibration_report

    s = _corpus()

    def _fake_scan(session, **kwargs):
        return {
            "schema": "oo-non-article-scan-1",
            "scanned": 1,
            "flagged": 1,
            "pct_flagged": 100.0,
            "by_reason": [{"signal": "url_homepage", "reason": "x", "count": 1, "sample_ids": [999999]}],
            "prose_gate": {"enabled": False},
            "method": "m",
            "caveat": "c",
            "reversible": True,
        }

    import src.analytics.non_article_scan as scan_mod

    monkeypatch.setattr(scan_mod, "scan_non_article_candidates", _fake_scan)
    out = calibration_report(s, top_n=100)  # must not raise, and the phantom id yields nothing
    assert out["collected"] == 0
    assert out["articles"] == []


def test_no_score_field_anywhere():
    s = _corpus()
    _walk_no_score(calibration_report(s, top_n=100, prose_gate_limit=2000))
