"""The furniture cut counts OUTLETS, not feed rows (row J, R146).

``compute_cross_source_df`` answers "in how many DISTINCT sources is this term a top keyword", and the cut is a fraction of
the audited sources. Since a source is one feed of an outlet, the feeds of one site share its template: counted per row,
one publisher's furniture read as ubiquitous across "unrelated sources" (BBC alone holds 31 rows). Both the df and its
denominator (the audited count, the count with a fingerprint) now count distinct outlets, here and in the audit.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.analytics import source_audit as sa
from src.analytics import source_quality as sq
from src.database.models import Article, Base, Keyword, KeywordMention, Source

_OUTLET = {1: "a.example", 2: "a.example", 3: "b.example", 4: "c.example"}


def test_a_term_counts_once_per_outlet_and_the_default_is_unchanged():
    top = {1: ["share now", "x"], 2: ["share now", "y"], 3: ["share now"], 4: ["z"]}
    assert sq.compute_cross_source_df(top)["share now"] == 3          # per source row, as before
    df = sq.compute_cross_source_df(top, _OUTLET.__getitem__)
    assert df["share now"] == 2 and df["x"] == 1 and df["z"] == 1     # a.example's two feeds are one holder
    assert sq.count_outlets(top, _OUTLET.__getitem__) == 3 and sq.count_outlets(top) == 4
    assert sq.count_outlets([1, 2], _OUTLET.__getitem__) == 1


def _corpus() -> Session:
    """Four feed rows of three outlets (a.example holds two), each with one indexed article topping 'share now'."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    k = Keyword(term="share now", normalized_term="share now")
    s.add(k)
    s.flush()
    for i, domain in _OUTLET.items():
        src = Source(name=f"S{i}", domain=domain, rss_url=f"https://{domain}/feed{i}.xml", source_type="news",
                     language="en", enabled=True)
        s.add(src)
        s.flush()
        art = Article(url=f"https://{domain}/a{i}", canonical_url=f"https://{domain}/a{i}", source_id=src.id,
                      content="body " * 200, hash=f"h{i}", word_count=200, language="en", title=f"t{i}")
        s.add(art)
        s.flush()
        s.add(KeywordMention(article_id=art.id, keyword_id=k.id, count=3, source_id=src.id, observed_on=date(2026, 7, 1)))
    s.commit()
    return s


def test_the_quality_report_counts_outlets_in_the_df_the_cut_and_the_attainable_maximum():
    s = _corpus()
    assert s.query(Source).count() == 4
    files = sq.build_quality_report_files(s, generated_at="2026-10-17T00:00:00", floor=3)
    manifest = json.loads(files["manifest.json"])
    df = manifest["observed"]["cross_source_df"]
    assert df["unit"] == "outlets"
    assert df["max"] == 3.0, "share now tops four feed rows of three outlets"
    assert df["n_sources_with_fingerprint"] == 3 and df["max_attainable"] == 3
    assert manifest["config"]["furniture_unit"] == "outlets"


def test_the_audit_measures_the_share_against_an_outlet_df_and_an_outlet_denominator(monkeypatch):
    s = _corpus()
    seen: dict = {}
    real = sq.flag_furniture_sources

    def spy(per_top, df, n_sources, **kw):
        seen["df"], seen["n"] = dict(df), n_sources
        return real(per_top, df, n_sources, **kw)

    monkeypatch.setattr(sq, "flag_furniture_sources", spy)
    sa._furniture_share_by_source(s, [r.id for r in s.query(Source)])
    assert seen["df"]["share now"] == 3 and seen["n"] == 3


def test_the_frozen_cohort_publishes_an_outlet_df_and_count():
    s = _corpus()
    frozen = sa.frozen_cohort(s, min_articles=1)
    assert frozen["furniture_n_sources"] == 3, "four feed rows, three outlets"
    assert frozen["furniture_df"]["share now"] == 3
