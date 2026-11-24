"""
Persist the Where (places) and Who (entities) extractors at ingest (T12).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The convergence substrate (CONFIRMED GO, field report #2): the extractors'
lexical candidates persist per article with snippet provenance and the rule
note that decided each entry — displayed as DEDUCED, never promoted to fact.
Idempotent per article (re-indexing replaces the rows), bounded by the
extractors' own scan caps. Dates persist via the sibling datestore module.
"""

from __future__ import annotations

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from src.database.models import Article, ArticleEntity, ArticleMentionedPlace
from src.timemap.entextract import extract_entities
from src.timemap.locextract import extract_locations

_EXTRACTOR = "lexical-v1"


def store_places_for_article(
    db: Session, article: Article, *, precomputed: list[dict] | None = None
) -> int:
    """``precomputed`` is the same list ``extract_locations`` returns, optionally
    computed in a worker process (the re-index's pooled precompute). ``None`` means
    "not precomputed" -- extract inline -- and is deliberately NOT the same fact as
    "no places found"."""
    text = (article.content or "")
    article_id = article.id
    db.execute(delete(ArticleMentionedPlace).where(ArticleMentionedPlace.article_id == article_id))
    places = (
        precomputed if precomputed is not None
        else extract_locations(text, source_country=article.country)
    )
    rows = [
        {
            "article_id": article_id,
            "name": pl["name"][:160],
            "country": (pl.get("country") or None),
            "kind": pl.get("kind"),
            "mentions": int(pl.get("mentions") or 1),
            "snippet": (pl.get("snippet") or "")[:400] or None,
            "lat": pl.get("lat"),
            "lon": pl.get("lon"),
            "note": (pl.get("note") or "")[:300] or None,
            "extractor": _EXTRACTOR,
        }
        for pl in places
    ]
    _insert_rows(db, ArticleMentionedPlace, rows)
    return len(places)


def _insert_rows(db: Session, model, rows: list[dict]) -> None:
    """Insert ``rows`` now, in list order, as ONE executemany (row 418).

    It replaces one ``db.add`` per row and the unit-of-work flush that wrote them: the same rows, the same ids (SQLite
    hands them out in statement order, as the flush did in add order), the same Python-side ``created_at`` default per
    row, through ``db.execute`` so the write gate and the R827 recorder see it as before. Nothing enters the identity
    map -- nothing here reads the rows back."""
    if rows:
        db.execute(insert(model.__table__), rows)


def places_for_article(db: Session, article_id: int, limit: int = 5) -> list[dict]:
    """Read the persisted (T12) places for an article, ordered by mentions desc.

    Returns the SAME dict shape the live extractor (``extract_locations``)
    emits — ``{name, country, kind, mentions, snippet, lat?, lon?, note}`` —
    so callers can swap stored rows for the live computation transparently.
    The rows stay DEDUCED candidates with their snippet provenance + rule note.
    """
    rows = (
        db.query(ArticleMentionedPlace)
        .filter_by(article_id=article_id)
        .order_by(ArticleMentionedPlace.mentions.desc(), ArticleMentionedPlace.id)
        .limit(limit)
        .all()
    )
    out: list[dict] = []
    for r in rows:
        d: dict = {
            "name": r.name,
            "country": r.country,
            "kind": r.kind,
            "mentions": r.mentions or 1,
            "snippet": r.snippet,
            "note": r.note,
        }
        if r.lat is not None:
            d["lat"] = r.lat
        if r.lon is not None:
            d["lon"] = r.lon
        out.append(d)
    return out


def entities_for_article(db: Session, article_id: int, limit: int = 5) -> dict:
    """Read the persisted (T12) entities for an article as the SAME shape the
    live extractor (``extract_entities``) returns — ``{"people": [...],
    "organizations": [...]}`` with each entry ``{name, mentions, snippet,
    note}``, ordered by mentions desc, capped per class. DEDUCED candidates."""
    result: dict[str, list[dict]] = {"people": [], "organizations": []}
    for cls, key in (("person", "people"), ("organization", "organizations")):
        rows = (
            db.query(ArticleEntity)
            .filter_by(article_id=article_id, entity_class=cls)
            .order_by(ArticleEntity.mentions.desc(), ArticleEntity.id)
            .limit(limit)
            .all()
        )
        result[key] = [
            {
                "name": r.name,
                "mentions": r.mentions or 1,
                "snippet": r.snippet,
                "note": r.note,
            }
            for r in rows
        ]
    return result


def store_entities_for_article(
    db: Session, article: Article, *, precomputed: dict | None = None
) -> int:
    """``precomputed`` is the same dict ``extract_entities`` returns, optionally
    computed in a worker process. ``None`` means "not precomputed", never "none found"."""
    text = (article.content or "")
    article_id = article.id
    db.execute(delete(ArticleEntity).where(ArticleEntity.article_id == article_id))
    ents = precomputed if precomputed is not None else extract_entities(text)
    rows = [
        {
            "article_id": article_id,
            "name": e["name"][:200],
            "entity_class": cls,
            "mentions": int(e.get("mentions") or 1),
            "snippet": (e.get("snippet") or "")[:400] or None,
            "note": (e.get("note") or "")[:300] or None,
            "extractor": _EXTRACTOR,
        }
        for cls, key in (("person", "people"), ("organization", "organizations"))
        for e in ents.get(key, [])
    ]
    _insert_rows(db, ArticleEntity, rows)
    return len(rows)
