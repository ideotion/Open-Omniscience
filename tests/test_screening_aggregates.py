"""R830 group D / R831(2) / R832 (row 408 PR 3b): the remaining aggregates leave the articles still queued for screening out,
search-fed figures say how many results they did not count, the Home total keeps counting every article and says what it
holds, and the re-index backlog is said as "not analysed yet".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

from src.database.models import ScreeningPending
from tests.test_bulletin_facts import _corpus as _bulletin_corpus
from tests.test_bulletin_facts import _period
from tests.test_source_article_counts import SINCE, s  # noqa: F401 - s is a fixture

__all__ = ["s"]

ROOT = Path(__file__).resolve().parents[1]


def _queue(sess, ids) -> None:
    for i in ids:
        sess.add(ScreeningPending(article_id=int(i)))
    sess.commit()


def test_split_not_screened_keeps_order_and_counts_the_queued(s):
    from src.analytics.quarantine_scope import split_not_screened

    assert split_not_screened(s, [5, 3, 1]) == ([5, 3, 1], 0), "nothing queued: the ids come back whole"
    _queue(s, [3, 9])
    assert split_not_screened(s, [5, 3, 1, 3]) == ([5, 1], 1)
    assert split_not_screened(s, []) == ([], 0)


def test_per_source_counts_leave_queued_articles_out_on_both_plans(s):
    from src.analytics import source_article_counts as sac

    all_time = sac.unquarantined_counts_by_source(s)
    since = sac.counts_by_source_since(s, SINCE)
    # article 1 is source 1, quarantined NULL, five minutes old: counted by both before it is queued
    _queue(s, [1])
    assert sac.unquarantined_counts_by_source(s)[1] == all_time[1] - 1
    assert sac.counts_by_source_since(s, SINCE)[1] == since[1] - 1
    # the ORM fallbacks (a store missing an index, or another dialect) leave it out too
    fb_all = {int(a): int(b) for a, b in s.execute(sac._fallback_unquarantined()).all() if a is not None}
    fb_since = {int(a): int(b) for a, b in s.execute(sac._fallback_since(SINCE)).all() if a is not None}
    assert fb_all[1] == all_time[1] - 1 and fb_since[1] == since[1] - 1


def test_the_forced_plans_stay_index_only_with_the_queue_filter(s):
    from sqlalchemy import bindparam, text

    from src.analytics import source_article_counts as sac
    from src.database.models import Article

    for stmt, params in (
        (text("EXPLAIN QUERY PLAN " + sac._ALL_TIME_UNQUARANTINED), {}),
        (
            text("EXPLAIN QUERY PLAN " + sac._SINCE).bindparams(
                bindparam("since", SINCE, type_=Article.__table__.c.created_at.type)
            ),
            {},
        ),
    ):
        steps = [str(r[-1]) for r in s.execute(stmt, params)]
        scans = [st for st in steps if st.startswith(("SCAN articles", "SEARCH articles"))]
        assert scans and all("INDEX" in st for st in scans), steps
        assert all("COVERING INDEX" in st or "USING INDEX" in st or "PRIMARY KEY" in st for st in scans), steps


def test_the_bulletin_counts_and_says_the_articles_not_screened_yet():
    from src.bulletin import facts
    from src.bulletin.i18n import Translator
    from src.bulletin.render import _md_disclosures
    from src.database.models import Article

    sess = _bulletin_corpus()
    before = facts.masthead(sess, _period())["articles"]
    d = facts.disclosures(sess, _period())
    assert d["not_screened_in_period"] == 0
    first = sess.query(Article).order_by(Article.id).first()
    _queue(sess, [first.id])
    assert facts.masthead(sess, _period())["articles"] == before - 1, "the queued article leaves the edition's figures"
    d = facts.disclosures(sess, _period())
    assert d["not_screened_in_period"] == 1
    lines = _md_disclosures({"disclosures": d}, Translator("en"))
    assert any("not screened for junk yet" in ln for ln in lines), lines
    unread = _md_disclosures({"disclosures": {"not_screened_in_period": None}}, Translator("en"))
    assert any("could not be read" in ln for ln in unread), "an unread count is said, never printed as 0"


def test_stats_say_quarantined_and_not_analysed_beside_not_screened(monkeypatch):
    from sqlalchemy.orm import Session

    from src.api import database as dbapi
    from src.api import jobs as jobs_api
    from src.database.models import Article, Base, Source
    from tests._app_engine import app_sqlite_engine

    eng = app_sqlite_engine(":memory:")
    Base.metadata.create_all(eng)
    sess = Session(eng)
    src = Source(name="a", domain="a.test")
    sess.add(src)
    sess.flush()
    for n, q in enumerate((True, None, False)):
        sess.add(Article(url=f"https://a.test/{n}", canonical_url=f"https://a.test/{n}", source_id=src.id, title="t",
                         content="x", hash=f"{n:064d}", quarantined=q))
    sess.commit()
    monkeypatch.setattr(jobs_api, "_backlog_cache", {"at": 0.0, "value": None})
    monkeypatch.setattr("src.backup.merge.reindex_backlog", lambda: {"available": True, "articles_pending": 7})
    monkeypatch.setattr("src.analytics.screening_drain.kick_if_allowed", lambda: False)
    out = dbapi._not_counted(sess)
    assert out["quarantined"] == 1 and out["not_analysed"] == 7 and out["not_screened"] == 0
    monkeypatch.setattr(jobs_api, "_backlog_cache", {"at": 0.0, "value": None})
    monkeypatch.setattr("src.backup.merge.reindex_backlog", lambda: {"available": False, "reason": "locked"})
    assert "not_analysed" not in dbapi._not_counted(sess), "an unread backlog is absent, never a 0"


def test_search_fed_figures_disclose_and_lists_keep_every_result():
    """Source pins: every search-fed figure splits the queued results off and says how many; the facet options of the
    LIST do not, and the Explore panels, the per-tab line and the Home breakdown draw what the payloads carry."""
    ins = (ROOT / "src/api/insights.py").read_text(encoding="utf-8")
    assert ins.count("split_not_screened(db, ids)") == 6, "keywords, www, sentiment, sources, coordination, graph"
    assert ins.count('"not_counted_yet"') >= 5
    facets = ins[ins.index("def insights_corpus_source_language_facets") :]
    assert "split_not_screened" not in facets[: facets.index("\n@router")], "the LIST's filter options keep every result"
    links = (ROOT / "src/api/link_analysis.py").read_text(encoding="utf-8")
    assert "split_not_screened(db, ids)" in links and '"not_counted_yet": not_yet' in links
    an = (ROOT / "src/static/app-analysis.js").read_text(encoding="utf-8")
    for k in ("Www", "Links", "Sentiment", "Sources"):
        assert f"anNotCountedYetHtml(d) + _an{k}Html(d)" in an
    assert "_nc(_anWwwHtml)" in an, "the language-switch repaint keeps the line"
    corpus = (ROOT / "src/static/app-corpus.js").read_text(encoding="utf-8")
    assert corpus.count("anNotCountedYetHtml(d)") == 2
    shell = (ROOT / "src/static/app-shell.js").read_text(encoding="utf-8")
    show = shell[shell.index("function showTab(") :]
    assert "ooNotCountedTabLine(name)" in show[: show.index("\n    }\n")]
    home = (ROOT / "src/static/app-home.js").read_text(encoding="utf-8")
    for key in ("of which quarantined: {n}", "of which not screened yet: {n}", "of which not analysed yet: {n}"):
        assert key in home
