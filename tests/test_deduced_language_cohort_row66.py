"""An article no page or source tagged is judged in the language the offline detector deduced
(field report 2026-11-14 row 66: 7,016 articles sat in the "unknown" cohort because the
source-quality report read only the stated tag). The stated tag always wins and is never
overwritten; the sample record says when the language was deduced."""

from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.analytics import source_quality as sq
from src.database.models import Article, Base, Source


def test_cohort_language_prefers_the_stated_one():
    assert sq._cohort_lang("sv", "fr") == "sv"
    assert sq._cohort_lang(None, "fr") == "fr"
    assert sq._cohort_lang("  ", "fr") == "fr"
    assert sq._cohort_lang(None, None) is None


def test_the_report_files_a_deduced_article_under_its_language():
    engine = create_engine("sqlite:///:memory:")
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
