"""R831 (row 415): every group C aggregate takes the one slice (quarantined articles and articles still queued for screening
are left out of a count, never out of a list), status totals keep counting every article and say what they hold, and a
figure the slice cannot reach yet says so.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The corpus: six articles over two sources (fr, de), each mentioning "election" and "france", naming one person and one
place and citing one link. Article 5 is quarantined, article 6 is queued for screening: every figure below counts four.
"""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.database.models import (
    Article,
    ArticleEntity,
    ArticleLink,
    ArticleMentionedPlace,
    Base,
    Keyword,
    KeywordMention,
    ScreeningPending,
    Source,
)
from tests._app_engine import app_sqlite_engine

ROOT = Path(__file__).resolve().parents[1]
TODAY = date.today()
COUNTED = [1, 2, 3, 4]


@pytest.fixture()
def s() -> Session:
    engine = app_sqlite_engine(":memory:")
    Base.metadata.create_all(engine)
    sess = Session(engine)
    sess.add_all([Source(id=1, name="A", domain="a.test", country="fr"), Source(id=2, name="B", domain="b.test", country="de")])
    sess.flush()
    kws = {}
    for term in ("election", "france"):
        k = Keyword(term=term, normalized_term=term, language="en", article_count=5, mention_count=5)  # the counters keep the queued one
        sess.add(k)
        sess.flush()
        kws[term] = k
    now = datetime.now()
    for aid in range(1, 7):
        sid = 1 if aid % 2 else 2
        cc = "fr" if sid == 1 else "de"
        u = f"https://x.test/{aid}"
        sess.add(Article(id=aid, title=f"t{aid}", content="body " * 60, url=u, canonical_url=u, source_id=sid, hash=f"h{aid}",
                         created_at=now - timedelta(hours=aid), published_at=now - timedelta(hours=aid),
                         quarantined=True if aid == 5 else None, language="en", country=cc))
        sess.flush()
        for k in kws.values():
            sess.add(KeywordMention(keyword_id=k.id, article_id=aid, count=1, observed_on=TODAY, country=cc))
        sess.add(ArticleEntity(article_id=aid, name="Ada Lovelace", entity_class="person", mentions=1))
        sess.add(ArticleMentionedPlace(article_id=aid, name="Lyon", country="fr", kind="city", mentions=1, lat=45.76, lon=4.84))
        sess.add(ArticleLink(article_id=aid, url="https://origin.test/x", normalized_url="origin.test/x"))
    sess.add(ScreeningPending(article_id=6))
    sess.commit()
    return sess


def test_keyword_frequency_counts_only_the_counted_mentions(s):
    from src.analytics.queries import keyword_frequency

    assert keyword_frequency(s)(["election", "absent"]) == {"election": 4}


def test_associations_take_the_slice_on_every_side_of_the_pmi(s):
    from src.analytics.queries import associations

    r = associations(s, "election", min_cooccur=1)
    assert r["corpus_articles"] == 4 and r["n_articles_with_term"] == 4
    (pair,) = [p for p in r["pairs"] if p["normalized"] == "france"]
    # the counter says 5 (it keeps the queued article, as the screening always has): the queued share is taken off
    assert pair["cooccur"] == 4 and pair["n_b"] == 4


def test_who_and_where_count_four_and_say_four_in_the_denominator(s):
    from src.analytics.queries import where_aggregate, who_aggregate

    who = who_aggregate(s)
    assert who["entities"][0]["articles"] == 4 and who["coverage_articles"] == 4
    where = where_aggregate(s)
    assert where["places"][0]["articles"] == 4 and where["coverage_articles"] == 4


def test_the_maps_count_four(s):
    from src.analytics.queries import map_data, source_country_counts, unlocated_language_breakdown

    m = map_data(s, days=None)
    tops = {c["code"]: c["top"] for c in m["countries"]}
    assert sum(t["mentions"] for c in tops.values() for t in c if t["term"] == "election") == 4
    scc = source_country_counts(s)
    assert scc["total_articles"] == 4, "articles take the slice"
    assert scc["total_sources"] == 2, "sources are counted whole"
    assert sum(r["keywords"] for r in scc["by_country"]) == 8
    assert unlocated_language_breakdown(s) == {}


def test_server_locations_count_four(s):
    from src.analytics.queries import server_locations

    out = server_locations(s)
    assert sum(out["unavailable"].values()) == 4


def test_the_conjunction_counts_take_the_slice_and_the_set_keeps_every_article(s):
    from src.analytics.conjunction import conditional_trend, corpus_algebra

    r = corpus_algebra(s, ["election", "france"], op="intersection")
    assert r["article_ids"] == [1, 2, 3, 4, 5, 6], "a list keeps every article"
    assert [t["n"] for t in r["terms"]] == [4, 4]
    assert r["not_counted_yet"] == 1
    assert conditional_trend(s, r["article_ids"])["total"] == 4


def test_status_totals_count_every_article_and_say_what_they_hold(s):
    from src.analytics.queries import status_totals

    out = status_totals(s)
    assert out["total_articles"] == 6 and out["quarantined"] == 1 and out["not_screened"] == 1


def test_link_and_place_counts_take_the_slice(s):
    from src.analytics.link_furniture import source_article_totals
    from src.entities.places import mention_count

    assert source_article_totals(s, [1, 2]) == {1: 2, 2: 2}

    class _P:
        name, country = "Lyon", "fr"

    assert mention_count(s, _P()) == 4


def test_the_home_cards_judge_the_corpus_by_its_counted_articles(s):
    from src.briefing.producers import _corpus_articles
    from src.briefing.service import _article_count

    assert _corpus_articles(s) == 4 and _article_count(s) == 4


def test_the_agenda_dates_say_they_may_include_unscreened_articles():
    """The deduced-date counts are read in src/timemap/datestore.py, which the import hold keeps unchanged: each event says
    so, ×12, until the post-hold correction."""
    src = (ROOT / "src/api/events.py").read_text(encoding="utf-8")
    assert 'ev["may_include_unscreened"] = True' in src
    js = (ROOT / "src/static/app-agenda.js").read_text(encoding="utf-8")
    key = "These counts may include quarantined articles and articles not screened yet."
    assert "e.may_include_unscreened" in js and key in js


# --------------------------------------------------------------------------------------------------------------------- #
# The source guard: every group C site names the slice, and every exception is listed with its reason.
# --------------------------------------------------------------------------------------------------------------------- #

#: (file, function) -> the site must apply ``not_counted`` itself.
SLICED = {
    "src/analytics/queries.py": ["keyword_frequency", "ring_country_split", "unlocated_language_breakdown",
                                 "source_country_counts", "server_locations", "associations", "map_data",
                                 "who_aggregate", "where_aggregate", "_article_set", "layered_graph"],
    "src/analytics/conjunction.py": ["corpus_algebra", "conditional_trend"],
    "src/analytics/columnar.py": ["build_source_coverage"],
    "src/analytics/link_furniture.py": ["source_article_totals", "source_furniture", "outlet_link_shares"],
    "src/analytics/outlet_furniture.py": ["outlet_repeated_shingles", "outlet_furniture_keywords"],
    "src/analytics/supergroup_stats.py": ["_per_id_mentions", "_distinct_source_count"],
    "src/analytics/laundering.py": ["find_source_laundering"],
    "src/analytics/recycled_claim.py": ["find_recycled_claims"],
    "src/analytics/headline_body.py": ["find_headline_body_mismatch"],
    "src/analytics/emergence.py": ["find_manufactured_emergence"],
    "src/analytics/copypasta.py": ["find_copypasta"],
    "src/analytics/disputed_chronology.py": ["find_disputed_chronology"],
    "src/analytics/convergence.py": ["find_convergences"],
    "src/analytics/corroboration.py": ["find_weather_opportunities"],
    "src/briefing/producers.py": ["_corpus_articles", "diet_self_audit", "capacity_implausible", "coverage_advisor"],
    "src/briefing/service.py": ["_article_count"],
    "src/briefing/recipes.py": ["region_gone_quiet"],
    "src/api/link_analysis.py": ["stats", "top_cited"],
    "src/entities/places.py": ["mention_count"],
    "src/entities/dossier.py": ["_count", "qid_dossier"],
    "src/entities/items.py": ["mentioned_qids"],
}

#: Group C sites that do NOT take the slice, each with why (R831 asks for the list).
EXCEPTIONS = {
    ("src/analytics/queries.py", "status_totals"): "a STATUS total: counts every article and says what it holds (R831(2))",
    ("src/analytics/queries.py", "status_indexed_articles"): "status: how far the keyword index has got over everything stored",
    ("src/analytics/queries.py", "status_mentions"): "status: every stored mention, beside the status total",
    ("src/api/database.py", "_cheap_figures"): "the Library's stored-corpus figures, a status total with its breakdown on the tab",
    ("src/api/database.py", "_mentions_count"): "the Library's stored-mention figure, a status total",
    ("src/timemap/datestore.py", "upcoming_deduced"): "under the import hold; each event says it may include them",
    ("src/timemap/datestore.py", "deduced_date_article_ids"): "under the import hold; a list behind a deduced date",
    ("src/analytics/latest.py", "_facet_options"): "facet counts of a list that keeps quarantined articles; queued ones left out (PR 3b)",
    ("src/analytics/alerts.py", "_hazard_links"): "a lookup of an article id for a link, not a figure",
    ("src/entities/places.py", "resolve_mentioned"): "builds the gazetteer places; its count is never shown",
    ("src/entities/places.py", "mention_article_ids"): "a list, which keeps every article",
    ("src/entities/places.py", "search_places"): "counts places, not articles",
    ("src/analytics/observatory.py", "observatory_payload"): "its figures come through supergroup_stats, which takes the slice",
    ("src/analytics/group_stats.py", "group_stats"): "its figures come through supergroup_stats, which takes the slice",
    ("src/analytics/passport.py", "corpus_passport"): "counts the set it is given; the dossier hands it the counted set",
}


def _function_source(path: str, name: str) -> str:
    src = (ROOT / path).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{path}: no function {name}: update the guard with the code")


@pytest.mark.parametrize("path,name", [(p, n) for p, names in SLICED.items() for n in names])
def test_every_group_c_site_takes_the_slice(path, name):
    body = _function_source(path, name)
    assert "not_counted(" in body, f"{path}:{name} counts articles without the R831 slice (or list it in EXCEPTIONS with why)"


def test_every_exception_names_a_real_site_and_a_reason():
    for (path, name), why in EXCEPTIONS.items():
        if (path, name) == ("src/analytics/alerts.py", "_hazard_links"):
            continue  # an inner block, not a function of its own: named for the list
        _function_source(path, name)
        assert len(why) > 20
    assert not set(EXCEPTIONS) & {(p, n) for p, ns in SLICED.items() for n in ns}
