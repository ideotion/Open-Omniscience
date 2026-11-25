"""Row 421 (R832): "N articles not analysed yet" is ONE shared notion beside "not screened", and the surfaces say it.

An article of an import still listed as ``merged`` owes the re-index while either analysis stamp of the current engine is
missing (the backlog's own test). An article queued for screening or quarantined is counted under that reason only, never
also here, so the reasons never name one article twice. Query time only: nothing is written.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.analytics import quarantine_scope as qs
from src.database.models import (
    Article,
    ArticleIndexStamp,
    ArticleWwwStamp,
    Base,
    MergeBatch,
    MergedRow,
    ScreeningPending,
    Source,
)
from tests._app_engine import app_sqlite_engine
from tests.js_source_helper import function_body, python_function_source

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh_cache():
    qs._not_analysed_cache.update(at=None, value=None, store=None)
    yield
    qs._not_analysed_cache.update(at=None, value=None, store=None)


def _store(status: str = "merged"):
    """Six articles. Of the merged import's five: 1 analysed (both stamps), 2 only its keyword stamp, 3 no stamp, 4 no stamp
    and queued for screening, 5 no stamp and quarantined. Article 6 was collected, not imported, and has no stamp."""
    from src.backup.merge import _backlog_engines, _backlog_www_engine

    eng = app_sqlite_engine(":memory:")
    Base.metadata.create_all(eng)
    s = Session(eng)
    src = Source(name="a", domain="a.test")
    s.add(src)
    s.flush()
    for n in range(1, 7):
        s.add(Article(id=n, url=f"https://a.test/{n}", canonical_url=f"https://a.test/{n}", source_id=src.id, title="t",
                      content="x", hash=f"{n:064d}", quarantined=True if n == 5 else None))
    s.flush()
    batch = MergeBatch(artifact_kind="oo-backup-2", origin_fingerprint="unsigned", status=status)
    s.add(batch)
    s.flush()
    for n in range(1, 6):
        s.add(MergedRow(batch_id=batch.id, table_name="articles", row_id=n))
    kw, www = _backlog_engines()[0], _backlog_www_engine()
    s.add(ArticleIndexStamp(article_id=1, engine=kw, inputs="i"))
    s.add(ArticleWwwStamp(article_id=1, engine=www, inputs="i"))
    s.add(ArticleIndexStamp(article_id=2, engine=kw, inputs="i"))
    s.add(ScreeningPending(article_id=4))
    s.commit()
    return s


def test_the_count_is_the_backlog_without_the_articles_another_reason_names():
    s = _store()
    assert qs.not_analysed_count(s) == 2, "articles 2 and 3: 4 is not screened yet, 5 is quarantined, 1 is done, 6 was never imported"
    assert qs.not_counted_tally(s) == {"not_screened": 1, "not_analysed": 2}


def test_an_import_no_longer_listed_as_merged_owes_nothing():
    s = _store(status="complete")
    assert qs.not_analysed_count(s) == 0
    assert qs.count_not_analysed(s, [1, 2, 3]) == 0


def test_a_figure_counts_only_its_own_results():
    s = _store()
    assert qs.count_not_analysed(s, [1, 2, 3, 4, 5, 6]) == 2
    assert qs.count_not_analysed(s, [3, 3, 6]) == 1, "an id given twice is one article"
    assert qs.count_not_analysed(s, [1]) == 0
    assert qs.count_not_analysed(s, []) == 0
    many = list(range(1, 2000))  # past one 900-id chunk
    assert qs.count_not_analysed(s, many) == 2


def test_with_not_analysed_sets_the_key_and_leaves_it_out_when_unread(monkeypatch):
    s = _store()
    assert qs.with_not_analysed({}, s, [2, 3]) == {"not_analysed_yet": 2}
    monkeypatch.setattr(qs, "count_not_analysed", lambda _s, _ids: None)
    assert qs.with_not_analysed({"a": 1}, s, [2]) == {"a": 1}, "unknown is absent, never 0"


def test_an_unreadable_count_is_absent_from_the_tally(monkeypatch):
    s = _store()

    def unread(_s):
        raise RuntimeError("locked")

    monkeypatch.setattr(qs, "not_analysed_count", unread)
    assert qs.not_counted_tally(s) == {"not_screened": 1}


def test_a_cached_count_is_never_served_for_another_store():
    a = _store()
    assert qs.not_analysed_count(a) == 2
    b = _store(status="complete")
    assert qs.not_analysed_count(b) == 0, "a second store is read, not answered from the first one's cache"


def test_the_status_totals_carry_both_reasons():
    from src.analytics.queries import status_totals

    out = status_totals(_store())
    assert out["not_screened"] == 1 and out["not_analysed"] == 2


def test_the_dossier_carries_the_corpus_wide_count(monkeypatch):
    from src.entities import dossier

    assert dossier._not_analysed_in_corpus(_store()) == {"not_analysed_in_corpus": 2}

    def unread(_s):
        raise RuntimeError("locked")

    monkeypatch.setattr(qs, "not_analysed_count", unread)
    assert dossier._not_analysed_in_corpus(_store()) == {}
    src = (ROOT / "src/entities/dossier.py").read_text(encoding="utf-8")
    assert "**_not_analysed_in_corpus(session)," in src
    js = (ROOT / "src/static/app-dossier.js").read_text(encoding="utf-8")
    body = function_body(js, "dossierHtml")
    assert "d.not_analysed_in_corpus" in body and '"{n} articles not analysed yet"' in body


def test_the_bulletin_states_the_disjoint_count():
    from src.bulletin.i18n import Translator
    from src.bulletin.render import _md_disclosures

    d = {"reindex_backlog": {"available": True, "articles_pending": 9, "not_analysed": 4}}
    text = "\n".join(_md_disclosures({"disclosures": d}, Translator("en")))
    assert "- 4 imported article(s) await re-index" in text
    d = {"reindex_backlog": {"available": True, "articles_pending": 9}}  # an older record keeps the backlog's figure
    assert "- 9 imported article(s) await re-index" in "\n".join(_md_disclosures({"disclosures": d}, Translator("en")))
    facts = python_function_source((ROOT / "src/bulletin/facts.py").read_text(encoding="utf-8"), "disclosures")
    assert '"not_analysed": not_analysed_count(session)' in facts


def test_the_figures_built_from_the_analysis_say_it_and_the_others_do_not():
    """Source pins, one per surface family: the Explore figures that read the re-index's output (keywords, When/Where/Who,
    sentiment, sources' tone, the mind map) and the conjunction panel carry ``not_analysed_yet``; the panels draw it."""
    ins = (ROOT / "src/api/insights.py").read_text(encoding="utf-8")
    assert ins.count("with_not_analysed(") == 5
    conj = (ROOT / "src/analytics/conjunction.py").read_text(encoding="utf-8")
    assert "count_not_analysed(session, _counted_ids)" in conj and '"not_analysed_yet": not_analysed' in conj
    an = (ROOT / "src/static/app-analysis.js").read_text(encoding="utf-8")
    body = function_body(an, "anNotCountedYetHtml")
    assert "d.not_analysed_yet" in body and '"{n} of these results not analysed yet"' in body
    corpus = (ROOT / "src/static/app-corpus.js").read_text(encoding="utf-8")
    assert "d.not_analysed_yet" in corpus and "+ notAnalysed" in corpus
    insjs = (ROOT / "src/static/app-insights.js").read_text(encoding="utf-8")
    assert "s.not_analysed" in function_body(insjs, "_insHeldText")
    # read no re-index output, so they carry nothing: per-day article counts, article text, cited links
    for path in ("src/api/commodity.py", "src/api/framing.py"):
        assert "not_analysed" not in (ROOT / path).read_text(encoding="utf-8")


def test_the_new_key_is_in_every_language():
    import json

    for loc in sorted((ROOT / "src/static/locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        assert "{n}" in d["{n} of these results not analysed yet"], loc.name
