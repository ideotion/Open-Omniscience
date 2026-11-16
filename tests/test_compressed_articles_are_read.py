"""R725 + R726: an article kept compressed is read like any other.

Such an article holds its text in ``compressed_content`` and leaves ``content`` empty. The date,
place and entity stores read ``article.content``, and so did the import's junk screen: every one
of them saw an empty body and found nothing. They now read the decompressed text
(``src.timemap.text.article_text``, the same rule as ``Article.get_content``).

Pinned here: the inline, serial and pool paths give a compressed article the SAME rows, and those
rows are the ones the article would get uncompressed; the junk screen judges a compressed body; and
the merge's carry digest is taken over the same text the stamp was.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.extract import get_extractor
from src.database.models import Article, Base, Source

_BODY = (
    "The World Health Organization met in Geneva on 5 March 2024 with officials from Kenya. "
    "Ministers said the drought in Nairobi had worsened since January, and the agency warned "
    "that prices would keep rising. "
) * 4
_NAV_SOUP = (
    "News Latest Irish News Mirror Bingo Soccer Golf Rugby Union Sport Business Politics "
    "World News Travel Money Markets Weather Video Photos Gallery Podcast Newsletters Events "
    "About Contact Home Search Login Sign Up Subscribe Cookies Advertisement Privacy Terms "
    "Follow Facebook Twitter Instagram Newsletter Preference Centre Manage Subscriptions "
    "Menu Toggle Navigation Skip Content Latest News Sport GAA Rugby Soccer Racing Golf Boxing "
) * 2  # over the 100-word floor below which the text gate never judges


@pytest.fixture()
def Session():  # noqa: N802 - a sessionmaker
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, autoflush=False)
    with factory() as s:
        s.add(Source(name="S", domain="example.com", enabled=True))
        s.commit()
    return factory


def _add(s, i: int, body: str, *, compressed: bool, url: str | None = None) -> int:
    url = url or f"https://s.test/2024/03/{i}/story"
    a = Article(source_id=1, url=url, canonical_url=url, title=f"T{i}", content=body, language="en",
                country="KE", hash=f"h{i}-{int(compressed)}", word_count=len(body.split()))
    if compressed:
        a.compress_content()
        a.content = ""
    s.add(a)
    s.flush()
    return a.id


def _rows(s, aid: int) -> dict:
    from src.database.models import ArticleMentionedDate
    from src.timemap.whostore import ArticleEntity, ArticleMentionedPlace

    return {
        "entities": sorted((e.name, e.entity_class) for e in s.query(ArticleEntity).filter_by(article_id=aid)),
        "places": sorted((p.name, p.country) for p in s.query(ArticleMentionedPlace).filter_by(article_id=aid)),
        "dates": sorted((d.mentioned_on.isoformat(), d.precision) for d in
                        s.query(ArticleMentionedDate).filter_by(article_id=aid)),
    }


def test_the_inline_stores_read_a_compressed_article(Session):
    from src.timemap.datestore import store_for_article as store_dates_for_article
    from src.timemap.whostore import store_entities_for_article, store_places_for_article

    with Session() as s:
        plain = _add(s, 1, _BODY, compressed=False)
        packed = _add(s, 2, _BODY, compressed=True)
        for aid in (plain, packed):
            art = s.get(Article, aid)
            store_dates_for_article(s, art)
            store_places_for_article(s, art)
            store_entities_for_article(s, art)
        s.commit()
        got, want = _rows(s, packed), _rows(s, plain)
    assert want["entities"] and want["places"] and want["dates"], "the body must yield rows, or this proves nothing"
    assert got == want


@pytest.mark.parametrize("workers", [0, 2])
def test_the_serial_and_pool_paths_give_a_compressed_article_the_inline_rows(Session, workers):
    """``workers=0`` is the serial precompute; ``workers=2`` over 20 articles is the pool (it declines below 16)."""
    from src.analytics import reindex_parallel as RP
    from src.analytics.store import reindex_articles

    with Session() as s:
        ids = [_add(s, i, _BODY + f" Story {i}.", compressed=(i % 2 == 0)) for i in range(20)]
        s.commit()
    stats: dict = {}
    with Session() as s:
        reindex_articles(s, extractor=get_extractor("baseline"), article_ids=ids, workers=workers, stats=stats)
        pre = {aid: _rows(s, aid) for aid in ids}
    paths = (stats.get("precompute") or {}).get("by_path") or {}
    if workers:
        assert "pool" in paths, f"the pool did not run: {paths}"
    with Session() as s, pytest.MonkeyPatch.context() as mp:
        mp.setattr(RP, "_extract_www", lambda *_a, **_k: None)  # inline extraction only
        reindex_articles(s, extractor=get_extractor("baseline"), article_ids=ids, workers=0)
        inline = {aid: _rows(s, aid) for aid in ids}
    assert pre == inline
    packed, plain = inline[ids[0]], inline[ids[1]]
    assert packed["entities"] and packed["places"] and packed["dates"]
    assert packed["entities"] == plain["entities"] and packed["places"] == plain["places"]


def test_the_junk_screen_judges_a_compressed_body(Session):
    from src.analytics.quarantine_job import default_quarantine_candidates_batch

    with Session() as s:
        soup = _add(s, 1, _NAV_SOUP, compressed=True, url="https://s.test/all-about/newsletter-preference-centre")
        prose = _add(s, 2, _BODY, compressed=True)
        s.commit()
        r = default_quarantine_candidates_batch(s, article_ids=[soup, prose], write=True)
        assert r["quarantined_ids"] == [soup] and r["by_reason"] == {"nav_soup": 1}
        art = s.get(Article, soup)
        assert art.quarantined is True and art.quarantine_reason == "nav_soup"
        from src.analytics.criteria_calibration import CRITERIA_VERSION

        assert art.quarantine_criteria_version == CRITERIA_VERSION == "nav-soup-v3"
        assert s.get(Article, prose).quarantined is not True


def test_an_unreadable_blob_does_not_fail_the_screens_batch(Session):
    """A blob this install cannot decompress (a codec not installed here, or a corrupt one) is screened
    by URL as before R726 and counted; the rest of its batch is still judged."""
    from src.analytics.quarantine_job import default_quarantine_candidates_batch

    with Session() as s:
        bad = _add(s, 1, _BODY, compressed=True)
        s.get(Article, bad).compressed_content = b"\xffnot-a-known-codec"
        soup = _add(s, 2, _NAV_SOUP, compressed=True, url="https://s.test/all-about/newsletter-preference-centre")
        s.commit()
        r = default_quarantine_candidates_batch(s, article_ids=[bad, soup], write=True)
        assert r["scanned"] == 2 and r["undecodable"] == 1
        assert r["quarantined_ids"] == [soup]
        assert s.get(Article, bad).quarantined is not True


def test_the_junk_screen_still_reads_the_source_on_the_host_path(Session):
    """The added column shifts the row layout; the host-mismatch reading must still find the source id."""
    from src.analytics.quarantine_job import default_quarantine_candidates_batch

    with Session() as s:
        aid = _add(s, 1, _BODY, compressed=True, url="https://www.elsewhere.org/2024/03/1/story")
        s.commit()
        r = default_quarantine_candidates_batch(s, article_ids=[aid], include_host_mismatch=True)
    assert r["host_mismatch"]["mismatch"] == 1


def test_the_carry_digest_is_taken_over_the_text_the_stamp_was(Session):
    """The merge recomputes the www inputs digest from an incoming row; for a compressed row it must hash the decompressed text,
    as the stamp did, or every compressed article would be refused as changed."""
    from src.analytics.engine_identity import www_inputs_digest
    from src.backup.merge import _stored_text
    from src.timemap.text import article_text

    with Session() as s:
        art = s.get(Article, _add(s, 1, _BODY, compressed=True))
        stamped = www_inputs_digest(raw_content=article_text(art), country=art.country, language=art.language)
        recomputed = www_inputs_digest(
            raw_content=_stored_text(art.content, art.compressed_content), country=art.country, language=art.language
        )
    assert stamped == recomputed
    assert article_text(art) == _BODY


def test_an_object_without_get_content_reads_its_content_attribute():
    from types import SimpleNamespace

    from src.timemap.text import article_text

    assert article_text(SimpleNamespace(content="x")) == "x"
    assert article_text(SimpleNamespace(content=None)) == ""
