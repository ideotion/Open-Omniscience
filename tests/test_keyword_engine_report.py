"""Keyword-engine efficacy + performance report (src/analytics/engine_report.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A bounded, read-only diagnostic over the corpus. Pins the metric shapes (no
composite score), the honest entity-precision + per-language-status logic, and that
translation/tag coverage + the self-test + timings are reported.
"""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.engine_report import _is_acronym, _lang_status, keyword_engine_report
from src.database.models import Article, Base, Keyword, KeywordMention, KeywordTag, Source


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _kw(s, term, norm, *, entity=False, lang="en"):
    k = Keyword(
        term=term, normalized_term=norm, language=lang, frequency=0,
        is_entity=entity, entity_type=("entity" if entity else None),
        is_ngram=(" " in norm), ngram_size=len(norm.split()),
    )
    s.add(k)
    s.flush()
    return k


def _seed(s):
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    a = Article(
        url="https://s.test/1", canonical_url="https://s.test/1", source_id=1,
        title="t", content="The election was held. WHO met. World news today.", hash="h1",
    )
    s.add(a)
    s.flush()
    who = _kw(s, "WHO", "WHO", entity=True)  # valid acronym entity
    world = _kw(s, "World", "world", entity=True)  # legacy non-acronym entity
    elec = _kw(s, "election", "election")  # term, in the real 'election' ring
    junk = _kw(s, "widget", "widget")  # term, no ring/tag
    for k in (who, world, elec, junk):
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=3, observed_on=date.today()))
    s.add(KeywordTag(keyword_id=elec.id, axis="topic", tag="politics", source="baseline"))
    s.commit()


def test_report_structure_and_metrics():
    s = _sess()
    _seed(s)
    r = keyword_engine_report(s, top_n=50, sample_articles=5)
    assert r["kind"] == "keyword-engine-report" and r["schema"] == "oo-keyword-engine-1"
    assert r["composition"]["keywords"] == 4 and r["composition"]["entities"] == 2
    # entity precision: WHO is an acronym, World is not -> 1 of 2
    assert r["entity_precision"]["valid_acronyms"] == 1 and r["entity_precision"]["pct_acronym"] == 50.0
    # translation coverage: "election" is in the real ring config
    assert r["translation_coverage"]["in_a_ring"] >= 1 and r["translation_coverage"]["rings_total"] >= 1
    # tag coverage: election carries a baseline tag
    assert r["tag_coverage"]["tagged"] >= 1
    langs = {x["language"]: x["status"] for x in r["language_coverage"]["languages"]}
    assert langs.get("en") == "functional"
    assert r["selftest"]["failed"] == 0
    assert r["performance"]["extraction"]["articles_sampled"] == 1
    assert "score" not in r  # no composite score, anywhere at the top level


def test_language_status_is_honest():
    assert _lang_status("zh") == "unsegmented" and _lang_status("ja") == "unsegmented"
    assert _lang_status("en") == "functional" and _lang_status("ru") == "functional"
    assert _lang_status("tr") == "no_stoplist" and _lang_status("xx") == "no_stoplist"


def test_acronym_predicate():
    assert _is_acronym("WHO") and _is_acronym("G7") and _is_acronym("COVID-19")
    assert not _is_acronym("world") and not _is_acronym("a")
