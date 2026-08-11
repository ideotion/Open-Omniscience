"""Articles, with the metadata the corpus actually holds about them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ask, 2026-08-11: "they should incorporate much more content, including
the cards system, full articles and their entire metadata … I'd like bulletin not
only to cover the keyword, but article content."

The field edition of 2026-08-10 described 72,225 articles and did not name one. It
had no title, no byline, no date, no excerpt — a document about a corpus with no
corpus in it. This module is the piece that was missing: given a set of article
ids, the facts the corpus holds about each of them.

TWO CLASSES, KEPT APART, because the reader already draws this line and a bulletin
that blurred it would be less honest than the app it came from:

* **Asserted by the source** — title, byline, publication date, the language the
  page declared. Carried as published, wrong dates and all.
* **Deduced by this app** — the detected language, the word count, the sentiment
  (English only, and it says so), the extracted keywords, places, dates and
  entities. Every one of these is a measurement over the text, never a fact the
  publisher stated.

LINKS ARE EXTERNAL, ALWAYS (§12). A local article id resolves to a DIFFERENT
article on a recipient's install, so the id travels in the JSON record — where it
is useful to the operator who owns the corpus — and the rendered document links
only to the original URL.

FULL TEXT IS THE ARCHIVE'S JOB. ``evidence.build_evidence_archive`` already writes
every article an edition's numbers were computed over — "**all of them**, not a
sample", so the counts can be recomputed — and that archive is owner-only by
design. The document therefore carries a bounded EXCERPT, marked when truncated,
and says where the whole text is. Putting a period's full text in a shareable
document would duplicate an artifact that already exists and turn a summary into a
redistribution of someone else's writing.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from src.database.models import (
    Article,
    ArticleAnalysis,
    ArticleEntity,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Keyword,
    KeywordMention,
    Source,
)

_LOG = logging.getLogger(__name__)

DEFAULT_EXCERPT_CHARS = 400
DEFAULT_KEYWORDS = 6
DEFAULT_FACETS = 5  # places / dates / entities shown per article

# SQLite's parameter ceiling is ~999; every lookup below is an IN over article ids,
# so the id list is chunked rather than trusted to be short.
_CHUNK = 400


def _iso(v: Any) -> str | None:
    if isinstance(v, datetime):
        return v.isoformat()
    return None if v is None else str(v)


def _chunks(ids: list[int]):
    for i in range(0, len(ids), _CHUNK):
        yield ids[i : i + _CHUNK]


def _keywords(session, ids: list[int], per: int) -> dict[int, list[dict]]:
    """Each article's own most-mentioned keywords.

    Joins keyword_mentions to keywords — the SMALL table — and never to articles,
    so this costs no article page read beyond the one the caller already pays.
    """
    out: dict[int, list[dict]] = {}
    for chunk in _chunks(ids):
        rows = (
            session.query(KeywordMention.article_id, Keyword.term, KeywordMention.count)
            .join(Keyword, Keyword.id == KeywordMention.keyword_id)
            .filter(KeywordMention.article_id.in_(chunk))
            .order_by(KeywordMention.article_id, KeywordMention.count.desc(), Keyword.term)
            .all()
        )
        for aid, term, count in rows:
            bucket = out.setdefault(int(aid), [])
            if len(bucket) < per:
                bucket.append({"term": term, "mentions": int(count or 0)})
    return out


def _places(session, ids: list[int], per: int) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for chunk in _chunks(ids):
        rows = (
            session.query(
                ArticleMentionedPlace.article_id,
                ArticleMentionedPlace.name,
                ArticleMentionedPlace.country,
                ArticleMentionedPlace.kind,
                ArticleMentionedPlace.mentions,
            )
            .filter(ArticleMentionedPlace.article_id.in_(chunk))
            .order_by(ArticleMentionedPlace.article_id, ArticleMentionedPlace.mentions.desc())
            .all()
        )
        for aid, name, country, kind, mentions in rows:
            bucket = out.setdefault(int(aid), [])
            if len(bucket) < per:
                bucket.append(
                    {"name": name, "country": country, "kind": kind,
                     "mentions": int(mentions or 0)}
                )
    return out


def _dates(session, ids: list[int], per: int) -> dict[int, list[dict]]:
    """Dates the TEXT mentions — not the publication date.

    ``status == "rejected"`` is excluded: a human looked at that candidate and said
    no, and re-publishing it would ignore the one judgement in the set.
    """
    out: dict[int, list[dict]] = {}
    for chunk in _chunks(ids):
        rows = (
            session.query(
                ArticleMentionedDate.article_id,
                ArticleMentionedDate.mentioned_on,
                ArticleMentionedDate.precision,
                ArticleMentionedDate.status,
            )
            .filter(
                ArticleMentionedDate.article_id.in_(chunk),
                (ArticleMentionedDate.status.is_(None))
                | (ArticleMentionedDate.status != "rejected"),
            )
            .order_by(ArticleMentionedDate.article_id, ArticleMentionedDate.mentioned_on)
            .all()
        )
        for aid, on, precision, status in rows:
            bucket = out.setdefault(int(aid), [])
            if len(bucket) < per:
                bucket.append(
                    {"date": _iso(on), "precision": precision, "status": status or "candidate"}
                )
    return out


def _entities(session, ids: list[int], per: int) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for chunk in _chunks(ids):
        rows = (
            session.query(
                ArticleEntity.article_id,
                ArticleEntity.name,
                ArticleEntity.entity_class,
                ArticleEntity.mentions,
            )
            .filter(ArticleEntity.article_id.in_(chunk))
            .order_by(ArticleEntity.article_id, ArticleEntity.mentions.desc())
            .all()
        )
        for aid, name, cls, mentions in rows:
            bucket = out.setdefault(int(aid), [])
            if len(bucket) < per:
                bucket.append(
                    {"name": name, "class": cls, "mentions": int(mentions or 0)}
                )
    return out


def article_rows(
    session,
    article_ids: list[int],
    *,
    limit: int = 10,
    excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
    keywords_per_article: int = DEFAULT_KEYWORDS,
    facets_per_article: int = DEFAULT_FACETS,
) -> list[dict]:
    """The facts this corpus holds about ``article_ids``, newest first.

    ``limit`` bounds how many articles are DESCRIBED; it never changes a count
    elsewhere in the edition. The caller states how many of how many it is showing.
    """
    ids = [int(i) for i in (article_ids or [])]
    if not ids:
        return []

    ordered = (
        session.query(Article)
        .filter(Article.id.in_(ids[: _CHUNK * 4]), Article.quarantined.isnot(True))
        .order_by(Article.published_at.desc().nullslast(), Article.id.desc())
        .limit(int(limit))
        .all()
    )
    if not ordered:
        return []
    shown = [int(a.id) for a in ordered]

    src_ids = {int(a.source_id) for a in ordered if a.source_id}
    sources = {
        int(r[0]): {"name": r[1], "domain": r[2], "country": r[3], "source_type": r[4]}
        for r in session.query(
            Source.id, Source.name, Source.domain, Source.country, Source.source_type
        ).filter(Source.id.in_(src_ids or {-1}))
    }

    kw = _keywords(session, shown, keywords_per_article)
    pl = _places(session, shown, facets_per_article)
    dt = _dates(session, shown, facets_per_article)
    en = _entities(session, shown, facets_per_article)

    rows: list[dict] = []
    for a in ordered:
        aid = int(a.id)
        try:
            text = (a.get_content() or "").strip()
        except Exception:  # noqa: BLE001 - one unreadable body never costs the row
            _LOG.debug("bulletin: article %s body unreadable", aid, exc_info=True)
            text = ""
        excerpt = text[: int(excerpt_chars)]
        # Sentiment is VADER, which reads English and nothing else, so a score is
        # present only where it was measurable. An absent score is an absent
        # measurement, never a neutral one.
        sentiment = None
        if a.sentiment_score is not None or a.sentiment_label:
            sentiment = {
                "score": a.sentiment_score,
                "label": a.sentiment_label,
                "basis": "rule-based lexicon, English only",
            }
        rows.append(
            {
                # The id is for the operator who owns this corpus. It is NEVER a link
                # in the rendered document: the same id is another article elsewhere.
                "id": aid,
                "title": a.title,
                "url": a.url,
                "source": sources.get(int(a.source_id or -1), {}),
                "asserted": {
                    "published_at": _iso(a.published_at),
                    "author": a.author,
                    "language": a.language,
                },
                "deduced": {
                    "collected_at": _iso(a.created_at),
                    "detected_language": a.detected_language,
                    "word_count": a.word_count,
                    "reading_time": a.reading_time,
                    "sentiment": sentiment,
                },
                "keywords": kw.get(aid, []),
                "places": pl.get(aid, []),
                "dates": dt.get(aid, []),
                "entities": en.get(aid, []),
                "excerpt": excerpt,
                "excerpt_truncated": len(text) > len(excerpt),
            }
        )
    return rows


def article_bodies(session, article_ids: list[int]) -> dict[int, str]:
    """The full stored text of each article, for the annexes bundle.

    Kept OUT of ``article_rows`` deliberately: the document carries an excerpt, and a
    render path that decrypted every full body to show four hundred characters of it
    would pay the codec for text it throws away. The annexes ask for the whole thing
    and pay for it there.

    PRESENT-BUT-EMPTY AND ABSENT MEAN DIFFERENT THINGS. An article whose stored text
    is genuinely empty maps to ``""``; one whose text could not be read — or which is
    quarantined, or no longer in the corpus — is OMITTED. Collapsing the two would
    make the caller tell a reader "this could not be read" about an article that
    simply has no body, which is a different fact.
    """
    out: dict[int, str] = {}
    ids = [int(i) for i in (article_ids or [])]
    for chunk in _chunks(ids):
        for art in session.query(Article).filter(
            Article.id.in_(chunk), Article.quarantined.isnot(True)
        ):
            try:
                out[int(art.id)] = art.get_content() or ""
            except Exception:  # noqa: BLE001 - one unreadable body never costs the rest
                _LOG.debug("bulletin: article %s body unreadable", art.id, exc_info=True)
    return out


def article_analyses(session, article_ids: list[int]) -> dict[int, list[dict]]:
    """Stored model output per article — summaries, translations — with provenance.

    Every row carries the model, the prompt version and when, because a paragraph of
    model text with no origin cannot be told apart from something the corpus holds.
    The translation TARGET is recovered from ``prompt_version`` (it is stored as
    ``translate-v2:French``, provenance with no extra column) through the same parser
    the article view uses, so a chunked run's ``+chunked-3`` suffix is not read as
    part of the language.
    """
    from src.api.llm import _parse_target_language

    out: dict[int, list[dict]] = {}
    ids = [int(i) for i in (article_ids or [])]
    for chunk in _chunks(ids):
        rows = (
            session.query(ArticleAnalysis)
            .filter(ArticleAnalysis.article_id.in_(chunk))
            .order_by(ArticleAnalysis.article_id, ArticleAnalysis.kind, ArticleAnalysis.id)
            .all()
        )
        for r in rows:
            out.setdefault(int(r.article_id), []).append(
                {
                    "kind": r.kind,
                    "result": r.result,
                    "model": r.model,
                    "prompt_version": r.prompt_version,
                    "target_language": _parse_target_language(r.prompt_version),
                    "created_at": _iso(r.created_at),
                }
            )
    return out


ARTICLE_CAVEAT = (
    "Two classes of fact, kept apart. Title, byline, publication date and the "
    "declared language are what the SOURCE asserted, carried as published — a wrong "
    "date here is the publisher's wrong date. The detected language, word count, "
    "keywords, places, mentioned dates and entities are DEDUCED by this app from the "
    "text, never confirmed: a place name is a lexical surface form the extractor does "
    "not disambiguate, and a mentioned date is a candidate a human has not checked "
    "unless it says otherwise. Sentiment appears only where it could be measured — a "
    "rule-based English lexicon — so its absence is an absence of measurement and not "
    "a neutral reading. Links go to the original page: a local article id means a "
    "different article on another install. Excerpts are the opening of the stored "
    "text; the full text of every article a figure was computed over lives in the "
    "owner-only evidence archive for this period, not in this document."
)
