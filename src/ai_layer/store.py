"""
AI-layer store helpers: record + read AI-derived keywords.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure functions over a SQLAlchemy ``Session`` (testable in-memory; the production
session is the MAIN session — the AI ``ai_keyword`` table lives in the main DB since
the 2026-06-18 ruling). Honesty by construction: every stored term carries its model
provenance, nothing is a score, and ``confirmed`` curates the AI lens IN PLACE — a
confirmed row never crosses into the trusted ``keyword_mentions`` index.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import AiKeyword, Article

#: Bounds for the stored evidence snippet: enough context to judge a term, short enough
#: that a lens over twenty terms stays readable.
_EVIDENCE_PAD = 110
_EVIDENCE_MAX = 300


def evidence_for(text: str | None, term: str) -> str | None:
    """Where in the article's OWN text this term occurs -- or ``None``.

    THE POINT IS THAT THIS IS NOT A MODEL CLAIM. ``AiKeyword.evidence`` is documented as
    "the snippet the model drew the term from" and had ZERO writers since the column was
    added; asking the model for one would have made it a second unverifiable assertion
    beside the first. This is a deterministic search of the stored copy instead: it says
    only "the term appears HERE in your text", which is checkable by the reader.

    ``None`` IS THE INTERESTING ANSWER and must never be filled in. A term the model
    produced that does not occur in the article is either an inference, a translation,
    or an invention -- the reader is told which is unknown, but that it did not come
    from the text is exactly the honesty signal this lens can offer, and a fabricated
    snippet would destroy it.

    CASE FOLDING WITHOUT MOVING THE OFFSETS. The exact ``str.find`` runs first (C-speed,
    offset-exact). On a miss, an IGNORECASE regex over the ORIGINAL string is what keeps
    the offsets true: lowering the text and indexing back into it is wrong for
    ``İ``/``ß``, whose case mapping changes LENGTH. The needle is ``re.escape``d, so
    there is no pattern to backtrack; a literal search is linear, unlike the
    ``OPEN.*?CLOSE`` shape that cost a 412 KB article 138 seconds.
    """
    if not text or not term:
        return None
    i = text.find(term)
    if i >= 0:
        start, end = i, i + len(term)
    else:
        m = re.search(re.escape(term), text, re.IGNORECASE)
        if not m:
            return None
        start, end = m.span()
    lo, hi = max(0, start - _EVIDENCE_PAD), min(len(text), end + _EVIDENCE_PAD)
    snippet = text[lo:hi]
    # The slice must still contain what was matched -- the standing
    # `text[off:off + len(w)] == w` discipline, one level up.
    if text[start:end].casefold() not in snippet.casefold():
        return None
    snippet = " ".join(snippet.split())
    if lo > 0:
        snippet = "…" + snippet
    if hi < len(text):
        snippet += "…"
    return snippet[:_EVIDENCE_MAX] or None


def article_evidence_text(article) -> str:
    """The text a stored term was drawn from -- title + body, in the SHAPE the extractor
    was actually shown (``jobs.py``'s combined text), so a term the model took from the
    headline is never reported absent from the article.

    Reads through ``Article.get_content()``, NOT ``Article.content``. A compressed row
    keeps its text in ``compressed_content`` and leaves ``content`` empty, so searching
    the column directly would report every term of every compressed article as absent --
    fabricating exactly the absence this lens exists to report honestly.
    """
    if article is None:
        return ""
    body = article.get_content() or ""
    title = (article.title or "").strip()
    return f"{title}\n\n{body}" if title else body


def evidence_for_rows(session: Session, article_id: int, rows) -> tuple[dict[int, str], bool]:
    """Resolve where each row's term occurs in the article's stored copy.

    Returns ``({row_id: snippet}, article_has_text)``. THE SECOND VALUE IS THE POINT.
    ``AiKeyword.evidence`` is written only at insert time, so every row stored before that
    writer existed holds ``NULL`` -- and a ``NULL`` cannot say whether the term was searched
    for and missing, or never searched at all. Rendering both as "not found in your stored
    copy" states a search that never happened, which is the same three-state collapse
    ``weights_pin.py`` refuses when it omits ``revision_matches_pin`` for a cache nothing
    compared.

    Resolving at READ time removes the ambiguity rather than describing it: every row in the
    answer has just been searched, so an absent snippet IS "searched and not found" -- unless
    the stored copy has no text at all, which is what ``article_has_text=False`` reports and
    is a third fact, not a weaker version of the second.

    Read-only BY DESIGN: nothing is written back. Persisting would make a GET mutate, and
    the nearest precedent is a warning rather than a licence -- ``autoIndexInsights`` needed a
    cooldown after the P0-5 storm (``/api/insights/reindex`` 1,326x in 369 s, each batch a
    heavy write contending with the live scrape). The stored value is preferred when present
    and agrees with recomputation, because both go through :func:`evidence_for`.
    """
    rows = list(rows)
    if not rows:
        return {}, True
    article = session.get(Article, article_id)
    text = article_evidence_text(article)
    if not text.strip():
        return {}, False
    found: dict[int, str] = {}
    for r in rows:
        snippet = r.evidence or evidence_for(text, r.term)
        if snippet:
            found[r.id] = snippet
    return found, True


def record_keywords(
    session: Session,
    article_id: int,
    terms: Iterable[str],
    *,
    model: str,
    kind: str = "keyword",
    language: str | None = None,
    prompt_version: str | None = None,
    evidence_text: str | None = None,
) -> int:
    """Store AI-extracted ``terms`` for an article. Idempotent per (article, kind,
    term): a term already present for this article+kind is skipped, so a re-run tops
    up rather than duplicates. Returns the number of NEW rows added.

    ``evidence_text`` is the article's own text. When given, each stored term records
    WHERE it occurs in it (see :func:`evidence_for`) -- a deterministic fact about the
    stored copy, never a model claim, and absent rather than guessed when the term is
    not in the text. Optional so no existing caller changes behaviour by omission."""
    existing = {
        r[0]
        for r in session.execute(
            select(AiKeyword.term).where(
                AiKeyword.article_id == article_id, AiKeyword.kind == kind
            )
        ).all()
    }
    added = 0
    for raw in terms:
        term = (raw or "").strip()
        if not term or term in existing:
            continue
        session.add(
            AiKeyword(
                article_id=article_id,
                term=term,
                kind=kind,
                language=language,
                model=model,
                prompt_version=prompt_version,
                confirmed=False,
                evidence=evidence_for(evidence_text, term),
            )
        )
        existing.add(term)
        added += 1
    session.flush()
    return added


def keywords_for_article(
    session: Session,
    article_id: int,
    *,
    kind: str | None = None,
    confirmed_only: bool = False,
) -> list[AiKeyword]:
    """The AI-derived terms for one article (ordered by term). Read-only."""
    q = select(AiKeyword).where(AiKeyword.article_id == article_id)
    if kind:
        q = q.where(AiKeyword.kind == kind)
    if confirmed_only:
        q = q.where(AiKeyword.confirmed.is_(True))
    return list(session.execute(q.order_by(AiKeyword.term)).scalars())


def set_confirmed(session: Session, ai_keyword_id: int, confirmed: bool) -> bool:
    """Curate the lens in place: confirm/unconfirm one AI keyword. Returns False if
    the row does not exist. The row STAYS in the AI store either way."""
    row = session.get(AiKeyword, ai_keyword_id)
    if row is None:
        return False
    row.confirmed = bool(confirmed)
    session.flush()
    return True
