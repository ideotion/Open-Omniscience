"""Row 418: the apply path writes through Core statements, and its results did not move.

Each write that left the ORM's unit of work is compared here with the ORM code it replaced, kept below as the reference:
the same rows, the same ids, the same stored values. Timestamps are compared by meaning (set, and of the stored form),
never by value, because two runs cannot share a clock.

- the date tags (``datestore.store_for_article``): read as plain rows; relabel, insert, then delete, in the unit of
  work's order, so a new tag takes the id the flush gave it even when a tag about to go held the highest id;
- the places and entities (``whostore``): one executemany each instead of one ``db.add`` per row;
- the article's derived columns (``index_article``): one UPDATE, the object told the stored values, nothing dirty;
- the two stamps and the engine record: compiled once, because SQLAlchemy cannot cache a SQLite ``ON CONFLICT``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.analytics import store
from src.analytics.extract import BaselineExtractor
from src.database.models import (
    Article,
    ArticleEntity,
    ArticleIndexStamp,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    ArticleWwwStamp,
    Base,
    IndexEngine,
    Source,
)
from src.timemap import datestore, whostore
from tests._app_engine import app_sqlite_engine

_TEXTS = (
    "On 3 March 2024 President Emmanuel Macron met the World Health Organization in Geneva. On 5 April 2024 Paris and "
    "Berlin agreed.",
    "In Nairobi on 12 May 2024 the International Monetary Fund met. Minister John Smith spoke in Lagos about inflation.",
    "Nothing dated here. Senator Kenji Tanaka visited Tokyo and Seoul with the European Central Bank.",
)


def _db():
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _article(session, i: int, content: str) -> Article:
    a = Article(
        url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1, title="T", content=content,
        hash=f"h{i}", language="en", published_at=datetime(2024, 6, 1, tzinfo=UTC), created_at=datetime.now(UTC),
    )
    session.add(a)
    session.commit()
    return a


# --------------------------------------------------------------------------- the ORM code row 418 replaced (reference)


def _orm_store_dates(db, article, *, today=None, precomputed=None):
    if article is None or not (article.content or "").strip():
        return 0
    tags = db.query(ArticleMentionedDate).filter(ArticleMentionedDate.article_id == article.id).all()
    existing = {(t.mentioned_on.isoformat(), t.precision) for t in tags}
    observed = article.published_at or article.created_at
    anchor = observed.date() if observed else None
    added = 0
    found = precomputed if precomputed is not None else datestore.extract_dates(
        article.content, today=today, anchor=anchor, language=article.language
    )
    extractor = (
        datestore.EXTRACTOR_KNOWN_LANGUAGE if (article.language or "").strip() else datestore.EXTRACTOR_NO_LANGUAGE
    )
    found_keys = {(c["date"], c["precision"]) for c in found}
    changed = False
    for t in tags:
        if t.status != "candidate" or t.extractor not in datestore._OWN_EXTRACTORS:
            continue
        key = (t.mentioned_on.isoformat(), t.precision)
        if key not in found_keys:
            db.delete(t)
            existing.discard(key)
            changed = True
        elif t.extractor != extractor:
            t.extractor = extractor
            changed = True
    for c in found:
        key = (c["date"], c["precision"])
        if key in existing:
            continue
        db.add(
            ArticleMentionedDate(
                article_id=article.id, mentioned_on=date.fromisoformat(c["date"]), precision=c["precision"],
                snippet=c["text"][:300], confidence=datestore._CONFIDENCE.get(c["precision"], 0.5),
                extractor=extractor, status="candidate",
            )
        )
        existing.add(key)
        added += 1
    if added or changed:
        if db.in_nested_transaction():
            db.flush()
        else:
            db.commit()
    return added


def _orm_store_places(db, article, *, precomputed=None):
    db.query(ArticleMentionedPlace).filter_by(article_id=article.id).delete()
    places = precomputed if precomputed is not None else whostore.extract_locations(
        article.content or "", source_country=article.country
    )
    for pl in places:
        db.add(
            ArticleMentionedPlace(
                article_id=article.id, name=pl["name"][:160], country=(pl.get("country") or None), kind=pl.get("kind"),
                mentions=int(pl.get("mentions") or 1), snippet=(pl.get("snippet") or "")[:400] or None,
                lat=pl.get("lat"), lon=pl.get("lon"), note=(pl.get("note") or "")[:300] or None,
                extractor=whostore._EXTRACTOR,
            )
        )
    return len(places)


def _orm_store_entities(db, article, *, precomputed=None):
    db.query(ArticleEntity).filter_by(article_id=article.id).delete()
    ents = precomputed if precomputed is not None else whostore.extract_entities(article.content or "")
    n = 0
    for cls, key in (("person", "people"), ("organization", "organizations")):
        for e in ents.get(key, []):
            db.add(
                ArticleEntity(
                    article_id=article.id, name=e["name"][:200], entity_class=cls, mentions=int(e.get("mentions") or 1),
                    snippet=(e.get("snippet") or "")[:400] or None, note=(e.get("note") or "")[:300] or None,
                    extractor=whostore._EXTRACTOR,
                )
            )
            n += 1
    return n


def _orm_write_article_derived(session, article, values):
    for key, value in values.items():
        setattr(article, key, value)


_ROWS = {
    "dates": "SELECT id, article_id, mentioned_on, precision, snippet, confidence, extractor, status, "
    "created_at IS NOT NULL FROM article_mentioned_dates ORDER BY id",
    "places": "SELECT id, article_id, name, country, kind, mentions, snippet, lat, lon, note, extractor, "
    "created_at IS NOT NULL FROM article_mentioned_places ORDER BY id",
    "entities": "SELECT id, article_id, name, entity_class, mentions, snippet, note, extractor, created_at IS NOT NULL "
    "FROM article_entities ORDER BY id",
    "articles": "SELECT id, sentiment_score, sentiment_label, top_keyword_id, top_keyword_count, top_keyword_tied_n, "
    "keyword_indexed_at IS NOT NULL, updated_at IS NOT NULL FROM articles ORDER BY id",
    "stamps": "SELECT article_id, engine, inputs, typeof(stamped_at), stage_version, carried_from_batch "
    "FROM article_index_stamps ORDER BY article_id",
    "www_stamps": "SELECT article_id, engine, inputs, typeof(stamped_at), stage_version, carried_from_batch "
    "FROM article_www_stamps ORDER BY article_id",
    "engines": "SELECT engine, stage, components, typeof(recorded_at) FROM index_engines ORDER BY engine",
    "mentions": "SELECT id, keyword_id, article_id, count, first_offset FROM keyword_mentions ORDER BY id",
}


def _scenario(session) -> dict:
    """Index three articles, judge two date tags by hand, plant another extractor's tag, then re-index every article
    with changed text, so the diff relabels, inserts and deletes, and the places and entities are replaced."""
    ex = BaselineExtractor()
    arts = [_article(session, i, t) for i, t in enumerate(_TEXTS)]
    for a in arts:
        store.index_article(session, a, extractor=ex, country="fr")
        session.commit()
    first = arts[0]
    tags = session.query(ArticleMentionedDate).filter_by(article_id=first.id).order_by(ArticleMentionedDate.id).all()
    assert len(tags) >= 2, "the scenario needs two date tags on the first article"
    tags[0].status = "confirmed"
    session.add(
        ArticleMentionedDate(
            article_id=first.id, mentioned_on=date(2020, 1, 1), precision="day", snippet="x", confidence=0.5,
            extractor="someone-else", status="candidate",
        )
    )
    session.commit()
    # Relabel: the same text read without a language keeps its tags under the other provenance label.
    arts[1].language = None
    session.commit()
    first.content = "On 9 June 2024 Doctor Fatima Haddad went to Cairo and Dubai for the Arab Monetary Fund."
    arts[2].content = _TEXTS[2] + " On 1 July 2024 President Pierre Dupont arrived in Madrid."
    session.commit()
    for a in arts:
        store.index_article(session, a, extractor=ex, country="fr")
        session.commit()
    return {name: [tuple(r) for r in session.execute(text(q))] for name, q in _ROWS.items()}


def test_the_core_writes_give_the_rows_and_ids_of_the_orm_writes(monkeypatch):
    core = _scenario(_db())

    monkeypatch.setattr(datestore, "store_for_article", _orm_store_dates)
    monkeypatch.setattr(whostore, "store_places_for_article", _orm_store_places)
    monkeypatch.setattr(whostore, "store_entities_for_article", _orm_store_entities)
    monkeypatch.setattr(store, "_write_article_derived", _orm_write_article_derived)
    orm = _scenario(_db())

    assert core == orm
    # The scenario exercised what it claims to: dates were relabelled, judged tags and the other extractor's kept,
    # places and entities written, stamps and engine rows present.
    assert {r[6] for r in core["dates"]} >= {datestore.EXTRACTOR_KNOWN_LANGUAGE, datestore.EXTRACTOR_NO_LANGUAGE}
    assert any(r[7] == "confirmed" for r in core["dates"]) and any(r[6] == "someone-else" for r in core["dates"])
    assert core["places"] and core["entities"] and core["stamps"] and core["www_stamps"] and core["engines"]
    assert all(r[3] == "text" for r in core["stamps"] + core["www_stamps"])


def test_a_new_date_tag_takes_the_id_the_flush_gave_it_when_the_highest_tag_goes():
    """The unit of work inserted before it deleted, so a new tag never reused the id of a tag about to go. The Core
    diff keeps that order; this pins it on the one shape where the order shows: the tag being removed holds max(id)."""
    s = _db()
    a = _article(s, 0, "On 3 March 2024 the minister spoke.")
    assert datestore.store_for_article(s, a) == 1
    gone = s.execute(text("SELECT max(id) FROM article_mentioned_dates")).scalar_one()
    a.content = "On 4 March 2024 the minister spoke."
    s.commit()
    assert datestore.store_for_article(s, a) == 1
    rows = s.execute(text("SELECT id, mentioned_on FROM article_mentioned_dates")).all()
    assert [(r[0], str(r[1])) for r in rows] == [(gone + 1, "2024-03-04")]


def test_the_article_is_not_left_dirty_and_reads_the_stored_values():
    s = _db()
    a = _article(s, 0, _TEXTS[0])
    store.index_article(s, a, extractor=BaselineExtractor(), country="fr")
    assert a not in s.dirty
    row = s.execute(
        text("SELECT top_keyword_id, top_keyword_count, top_keyword_tied_n, sentiment_label FROM articles WHERE id = :i"),
        {"i": a.id},
    ).one()
    assert (a.top_keyword_id, a.top_keyword_count, a.top_keyword_tied_n, a.sentiment_label) == tuple(row)
    assert a.keyword_indexed_at is not None and a.updated_at is not None


def test_a_www_failure_still_keeps_the_keyword_attempt_record(monkeypatch):
    """The derived UPDATE runs before the when/where/who savepoint, as the flush did, so a failure there leaves it."""
    s = _db()
    a = _article(s, 0, _TEXTS[0])

    def _boom(*_a, **_k):
        raise ValueError("planted")

    monkeypatch.setattr(whostore, "store_places_for_article", _boom)
    store.index_article(s, a, extractor=BaselineExtractor(), country="fr")
    s.commit()
    s.expire_all()
    assert s.get(Article, a.id).keyword_indexed_at is not None


@pytest.mark.parametrize("model", [ArticleIndexStamp, ArticleWwwStamp])
def test_the_stamp_upsert_is_built_once_and_overwrites_like_the_construct(model):
    assert store._stamp_upsert(model) is store._stamp_upsert(model)
    assert store._record_engine_insert() is store._record_engine_insert()
    s = _db()
    a = _article(s, 0, "x")
    now = datetime(2026, 11, 24, 22, 1, 2, 345678, tzinfo=UTC)
    params = {"article_id": a.id, "engine": "e", "inputs": "i", "stamped_at": now, "stage_version": 3,
              "carried_from_batch": 7}
    s.execute(store._stamp_upsert(model), params)
    s.execute(store._stamp_upsert(model), {**params, "engine": "f", "stage_version": 4})
    s.execute(store._record_engine_insert(), {"engine": "e", "stage": "kw", "components": "c", "recorded_at": now})
    s.execute(store._record_engine_insert(), {"engine": "e", "stage": "kw", "components": "other", "recorded_at": now})
    table = model.__tablename__
    assert s.execute(text(f"SELECT engine, stamped_at, stage_version, carried_from_batch FROM {table}")).all() == [
        ("f", "2026-11-24 22:01:02.345678", 4, None)  # a conflict clears the carry, as the construct's set_ did
    ]
    assert s.query(IndexEngine.components).all() == [("c",)]
