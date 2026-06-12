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

from sqlalchemy.orm import Session

from src.database.models import Article, ArticleEntity, ArticleMentionedPlace
from src.timemap.entextract import extract_entities
from src.timemap.locextract import extract_locations

_EXTRACTOR = "lexical-v1"


def store_places_for_article(db: Session, article: Article) -> int:
    text = (article.content or "")
    db.query(ArticleMentionedPlace).filter_by(article_id=article.id).delete()
    places = extract_locations(text, source_country=article.country)
    for pl in places:
        db.add(
            ArticleMentionedPlace(
                article_id=article.id,
                name=pl["name"][:160],
                country=(pl.get("country") or None),
                kind=pl.get("kind"),
                mentions=int(pl.get("mentions") or 1),
                snippet=(pl.get("snippet") or "")[:400] or None,
                lat=pl.get("lat"),
                lon=pl.get("lon"),
                note=(pl.get("note") or "")[:300] or None,
                extractor=_EXTRACTOR,
            )
        )
    return len(places)


def store_entities_for_article(db: Session, article: Article) -> int:
    text = (article.content or "")
    db.query(ArticleEntity).filter_by(article_id=article.id).delete()
    ents = extract_entities(text)
    n = 0
    for cls, key in (("person", "people"), ("organization", "organizations")):
        for e in ents.get(key, []):
            db.add(
                ArticleEntity(
                    article_id=article.id,
                    name=e["name"][:200],
                    entity_class=cls,
                    mentions=int(e.get("mentions") or 1),
                    snippet=(e.get("snippet") or "")[:400] or None,
                    note=(e.get("note") or "")[:300] or None,
                    extractor=_EXTRACTOR,
                )
            )
            n += 1
    return n
