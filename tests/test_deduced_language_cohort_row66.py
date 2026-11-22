"""An article no page or source tagged is judged in the language the offline detector deduced
(field report 2026-11-14 row 66: 7,016 articles sat in the "unknown" cohort because the
source-quality report read only the stated tag). The stated tag always wins and is never
overwritten; the sample record says when the language was deduced."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.analytics import source_quality as sq
from src.database.models import Article, Base, Source
from tests._app_engine import app_sqlite_engine


def test_cohort_language_prefers_the_stated_one():
    assert sq._cohort_lang("sv", "fr") == "sv"
    assert sq._cohort_lang(None, "fr") == "fr"
    assert sq._cohort_lang("  ", "fr") == "fr"
    assert sq._cohort_lang(None, None) is None


def test_the_report_files_a_deduced_article_under_its_language():
    engine = app_sqlite_engine(":memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="S", domain="s.example", source_type="news", language=None, enabled=True)
    other = Source(name="D", domain="d.example", source_type="news", language="de", enabled=True)
    s.add_all([src, other])
    s.flush()
    s.add(Article(url="http://s/1", canonical_url="http://s/1", source_id=src.id, content="Un texte. " * 40,
                  hash="h1", word_count=80, language=None, detected_language="fr", title="t1"))
    s.add(Article(url="http://s/2", canonical_url="http://s/2", source_id=other.id, content="Ein Text. " * 40,
                  hash="h2", word_count=80, language="de", detected_language="fr", title="t2"))
    s.commit()
    files = sq.build_quality_report_files(s, generated_at="2026-11-16T00:00:00", seed=1, floor=1)
    samples = {r["article_id"]: r for r in map(json.loads, files["sample_articles.jsonl"].decode().splitlines())}
    assert samples[1]["language"] == "fr" and samples[1]["language_deduced"] is True
    assert samples[2]["language"] == "de" and samples[2]["language_deduced"] is False
    # the stored tag is untouched: the report reads, it never writes
    assert s.get(Article, 1).language is None
    assert "unknown" not in json.loads(files["per_language_health.json"])


# Row 110: the bad-item labels and selectors decide "unsegmented" from the SAME cohort language the
# sample record reports, so a page with no stated language that the detector read as Chinese is not
# called very_short on its character-run word count, while one stated as Chinese never was either.

def _zh_corpus():
    from src.database.models import ArticleLink

    engine = app_sqlite_engine(":memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="Z", domain="z.example", source_type="news", language=None, enabled=True)
    s.add(src)
    s.flush()
    rows = [  # (language, detected_language): deduced zh, stated zh, deduced fr
        (None, "zh"), ("zh", None), (None, "fr"),
    ]
    for i, (lang, det) in enumerate(rows, start=1):
        s.add(Article(url=f"http://z/{i}", canonical_url=f"http://z/{i}", source_id=src.id, content="字" * 400,
                      hash=f"z{i}", word_count=5, language=lang, detected_language=det, title=f"t{i}"))
    s.flush()
    for i in (1, 2, 3):
        s.add(ArticleLink(article_id=i, url=f"http://x/{i}", normalized_url=f"http://x/{i}", link_type="external"))
    s.commit()
    return s, src.id


def test_a_deduced_unsegmented_language_gets_no_word_count_label():
    assert sq._pre_label(None, word_count=5, external_links=1, language=sq._cohort_lang(None, "zh")) == []
    assert sq._pre_label(None, word_count=5, external_links=1, language=sq._cohort_lang("zh", None)) == []
    labels = sq._pre_label(None, word_count=5, external_links=1, language=sq._cohort_lang(None, "fr"))
    assert any(x.startswith("very_short") for x in labels) and any(x.startswith("high_link_density") for x in labels)


def test_the_selectors_skip_a_deduced_unsegmented_article_like_the_label():
    s, sid = _zh_corpus()
    assert sq.select_cheap_signals(s, {sid}) == {3}
    assert sq.link_dense_article_ids(s) == {3}
    assert sq.link_dense_article_ids(s, article_ids={1, 2, 3}) == {3}


def test_the_sample_record_label_uses_the_deduced_language():
    s, _sid = _zh_corpus()
    recs = {r["article_id"]: r for r in sq.build_sample_records(
        s, {1: ["x"], 2: ["x"], 3: ["x"]}, set(), include_newsletter_text=False)}
    assert recs[1]["language"] == "zh" and recs[1]["pre_label"] == []
    assert recs[2]["pre_label"] == []
    assert any(x.startswith("very_short") for x in recs[3]["pre_label"])
