"""Language-aware sentiment computed + stored at ingest (the maintainer's ask).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

VADER scores ENGLISH articles at ingest (through index_article) and stores the
result on the article; every other language stays NULL — never a fabricated
neutral. The non-English / no-library paths return (None, None) WITHOUT touching
VADER, so a core install (no [analysis] extra) never crashes at ingest.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.sentiment import score_article
from src.analytics.store import index_article
from src.database.models import Article, Base, Source

try:
    import vaderSentiment  # noqa: F401

    _HAS_VADER = True
except ImportError:
    _HAS_VADER = False

_needs_vader = pytest.mark.skipif(not _HAS_VADER, reason="sentiment scoring needs the [analysis] extra")


def _sess():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_non_english_returns_none_without_needing_vader():
    # The language gate (and empty check) return BEFORE VADER is touched, so the
    # honest gap holds even on a core install — and ingest never crashes.
    assert score_article("Une catastrophe terrible et un désastre total.", "fr") == (None, None)
    assert score_article("anything at all", None) == (None, None)
    assert score_article("", "en") == (None, None)


@_needs_vader
def test_score_article_is_english_only_and_signed():
    pos, plabel = score_article("This is wonderful, excellent — a great, happy victory!", "en")
    assert pos is not None and pos > 0 and plabel == "positive"
    neg, nlabel = score_article("This is terrible, awful — a disaster and a tragedy.", "en")
    assert neg is not None and neg < 0 and nlabel == "negative"


@_needs_vader
def test_index_article_populates_sentiment_at_ingest():
    s = _sess()
    s.add(Source(name="Src", domain="s.test"))
    s.flush()
    en = Article(
        url="https://s.test/1", canonical_url="https://s.test/1", source_id=1, title="Good",
        content="A wonderful, excellent, fantastic outcome — everyone is delighted and happy.",
        hash="h1", language="en",
    )
    fr = Article(
        url="https://s.test/2", canonical_url="https://s.test/2", source_id=1, title="Fr",
        content="Une catastrophe terrible et un désastre total pour tout le monde.",
        hash="h2", language="fr",
    )
    s.add_all([en, fr])
    s.flush()
    ex = BaselineExtractor()
    index_article(s, en, extractor=ex)
    index_article(s, fr, extractor=ex)
    s.commit()
    assert en.sentiment_score is not None and en.sentiment_label == "positive"
    assert fr.sentiment_score is None and fr.sentiment_label is None  # honest gap, non-English
