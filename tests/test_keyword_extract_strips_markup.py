"""
HTML/CSS must never become keywords (field diagnostics 2026-06-21).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The live keyword log showed a 36.5k "unknown-language" junk bucket dominated by
CSS/HTML tokens (``div``, ``span``, ``max-width``, ``font-size``, ``font-family``)
— stored article bodies that still carried raw markup. We strip markup at the ONE
extraction chokepoint so EVERY path (web/.eml/wiki/future) is defended and a
re-index cleans existing rows. Clean text must stay byte-identical so a term's
recorded first-offset still points at the right place in the stored body.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor, strip_markup
from src.analytics.store import index_article
from src.database.models import Article, Base, Keyword, KeywordMention, Source

# Tokens that must NEVER survive as keywords once markup is stripped.
_CSS_HTML_JUNK = {
    "div", "span", "max-width", "font-size", "font-family", "color",
    "wrapper", "class", "style", "script", "copy", "nbsp", "amp",
}

_MARKUP_ARTICLE = (
    "<style>.box{max-width:100px;font-size:12px;font-family:Arial}</style>"
    '<div class="wrapper"><span style="color:red">Breaking coverage about '
    "elections and inflation across the country.</span></div>"
    "<!-- tracking comment mentioning div span color -->"
    "&copy; 2024 Example &nbsp; AT&amp;T"
)


def _norms(terms) -> set[str]:
    return {t.normalized for t in terms}


# --------------------------------------------------------------------------- #
# strip_markup: clean text byte-identical, markup removed
# --------------------------------------------------------------------------- #
def test_strip_markup_leaves_clean_text_byte_identical():
    # No real tag / entity -> returned unchanged so keyword offsets stay exact.
    clean = "The ratio was 3 < 4 and 5 > 2 in the report about elections."
    assert strip_markup(clean) is clean or strip_markup(clean) == clean
    assert strip_markup(clean) == clean


def test_strip_markup_does_not_eat_angle_bracketed_urls():
    # "<https://x>" is tag-LIKE but not a real tag (no name letter before a
    # whitespace/slash/'>' close), so it is NOT stripped (clean text untouched).
    s = "See <https://example.org> for details about the elections coverage."
    assert strip_markup(s) == s


def test_strip_markup_drops_style_blocks_tags_comments_and_decodes_entities():
    out = strip_markup(_MARKUP_ARTICLE)
    assert "<" not in out and ">" not in out
    # CSS property names / element names gone.
    for junk in ("max-width", "font-size", "font-family", "wrapper", "color"):
        assert junk not in out.lower()
    # Real prose survived; entities decoded (no &copy; / &nbsp; / &amp;).
    assert "elections" in out and "inflation" in out
    assert "&copy;" not in out and "&nbsp;" not in out and "&amp;" not in out
    assert "©" in out  # &copy; decoded, not left as the literal text "copy"


# --------------------------------------------------------------------------- #
# extract(): markup never becomes a keyword; real content survives
# --------------------------------------------------------------------------- #
def test_extract_does_not_mint_css_or_html_keywords():
    by = _norms(BaselineExtractor().extract(_MARKUP_ARTICLE))
    assert not (by & _CSS_HTML_JUNK), f"markup leaked as keywords: {by & _CSS_HTML_JUNK}"
    assert "elections" in by and "inflation" in by and "country" in by


def test_extract_offsets_unchanged_for_clean_text():
    # A clean article keeps exact offsets (strip is a no-op), so the surrounding
    # sentence the reader slices from the stored body still lines up.
    text = "Markets fell as inflation worried traders about the wider economy today."
    for t in BaselineExtractor().extract(text):
        if t.first_offset is not None:
            assert text[t.first_offset:].lower().startswith(t.term.split()[0].lower())


# --------------------------------------------------------------------------- #
# end-to-end: indexing a junky article stores clean keywords (re-index path)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _article(db, text):
    db.add(Source(name="S", domain="x.test", country="us"))
    a = Article(
        url="https://x.test/1",
        canonical_url="https://x.test/1",
        source_id=1,
        title="T",
        content=text,
        hash="h-markup",
        language="en",
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def test_index_article_stores_no_markup_keywords(db):
    art = _article(db, _MARKUP_ARTICLE)
    index_article(db, art, extractor=BaselineExtractor())
    stored = {k.normalized_term for k in db.query(Keyword).all()}
    assert not (stored & _CSS_HTML_JUNK), f"markup indexed: {stored & _CSS_HTML_JUNK}"
    assert "elections" in stored and "inflation" in stored
    # Re-index is idempotent and stays clean (counters consistent with the join).
    index_article(db, art, extractor=BaselineExtractor())
    stored2 = {k.normalized_term for k in db.query(Keyword).all()}
    assert not (stored2 & _CSS_HTML_JUNK)
    for kw in db.query(Keyword).all():
        live = (
            db.query(KeywordMention)
            .filter_by(keyword_id=kw.id)
            .count()
        )
        assert kw.article_count == live  # one mention row per (keyword, article)
