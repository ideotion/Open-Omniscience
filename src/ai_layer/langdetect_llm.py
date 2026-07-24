"""
OPT-IN local-LLM language detection for articles STILL unknown after the offline detector
(maintainer addendum 2026-07-10, B15).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

DOCTRINE (binding — the maintainer's constraints):
  * DETECTOR-FIRST ordering: this runs ONLY for an article whose AUTHORITATIVE
    ``Article.language`` is unset AND whose offline-deduced ``detected_language``
    (``src/analytics/langdetect.py``, py3langid) is also unset. The cheap, deterministic,
    zero-network offline detector always runs first; the LLM is the last resort for what it
    could not classify (short text, low confidence, or a language it does not cover).
  * NEVER OVERWRITES the trusted channels. It writes ONLY the AI-derived ``ai_keyword`` table
    (``kind="language"``) — a THIRD, clearly-labelled "AI-derived · unreliable" provenance
    class rendered inline in the article view — and never touches ``Article.language`` nor
    ``Article.detected_language``. The two-class asserted-vs-offline-deduced model is intact;
    this is a strictly additional, weaker, labelled layer.
  * GARBAGE STORES NOTHING: the model must reply with an ISO 639-1 code in the app's KNOWN
    vocabulary (``translate.KNOWN_LANG_CODES``). A refusal, an explanation, a made-up code,
    or a language the app has no name for → ``None`` → no row written (miss over invent).
  * OPT-IN + VISIBLE + ABORTABLE: it is never on the scrape hot path (a model over many
    articles is slow); it runs as a user-started, cancellable, task-manager-visible
    background job (``src/api/ai.py``). Local loopback only (Ollama); airplane mode (the kill
    switch) refuses it at the client, surfaced.

Pure here (prompt build + parse + the unknown-language query), so it is testable with a stub
client and no network. The batch writer mirrors ``jobs.extract_for_articles``.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from src.ai_layer import store as ai_store
from src.ai_layer.jobs import ArticleWork
from src.ai_layer.translate import KNOWN_LANG_CODES, lang_name
from src.database.models import AiKeyword, Article
from src.database.session import session_scope
from src.llm.ollama import LLMUnavailable

# Bump when the prompt changes (provenance flag travels with each AI-derived result).
LANGDETECT_PROMPT_VERSION = "ai-langdetect-v1"
# The AI-metadata kind for a detected language (the third provenance class).
LANG_KIND = "language"

# A leading label the model might prepend ("Language:", "The language is", "ISO 639-1 code =").
_LABEL = re.compile(
    r"^\s*(?:the\s+)?(?:language|lang|code|iso[\s-]?639(?:[\s-]?1)?)\s*(?:is|=|:)?\s*",
    re.IGNORECASE,
)
_REFUSAL = re.compile(
    r"\b(as an ai|i (?:cannot|can't|am unable|am not able)|unknown|not sure|unclear|"
    r"multiple|mixed)\b",
    re.IGNORECASE,
)
_MAX_TEXT = 4000  # the lead is plenty to identify a language; bound the model's input


def build_system() -> str:
    """The detection system prompt: reply with ONLY the ISO 639-1 code."""
    return (
        "You identify the language a text is written in. Reply with ONLY the ISO 639-1 "
        "two-letter language code in lowercase (for example: en, fr, de, ru, ar, zh, ja, ko, "
        "fa, vi). Output nothing else — no explanation, no punctuation, no quotes. If you "
        "cannot tell, output: unknown."
    )


def parse_lang(raw: str | None) -> str | None:
    """Clean the model output to a KNOWN ISO 639-1 code, or ``None`` if unusable.

    The cleaned reply must BE a known code (after stripping a leading 'Language:'-style
    label + surrounding quotes/punctuation) — NOT contain one. This deliberately rejects a
    chatty sentence like "It is French": English words such as 'it' (Italian), 'no'
    (Norwegian) and 'he' (Hebrew) are themselves codes, so scanning-for-a-code inside prose
    would mislabel. Also rejects refusals / 'unknown' / 'mixed'. Garbage stores nothing —
    miss over invent. Case-insensitive."""
    s = (raw or "").strip()
    if not s or _REFUSAL.search(s):
        return None
    s = _LABEL.sub("", s).strip().strip("\"'“”«».`:!?,;()[]").strip().lower()
    return s if s in KNOWN_LANG_CODES else None


def detect_language_llm(
    client, title: str, content: str, *, model: str, keep_alive: str | None = None
) -> str | None:
    """Ask the local model for the language of one article. Returns a KNOWN ISO 639-1
    code or ``None`` (empty text, refusal, or an unrecognised/garbage answer). Raises the
    client's error if Ollama is unavailable — the caller (the job) decides."""
    text = f"{(title or '').strip()}\n\n{(content or '').strip()}".strip()
    if not text:
        return None
    result = client.generate(
        text[:_MAX_TEXT], model=model, system=build_system(), keep_alive=keep_alive
    )
    return parse_lang(getattr(result, "text", None))


def _already_labelled():
    """A correlated EXISTS: this article already has an AI language label."""
    return exists().where((AiKeyword.article_id == Article.id) & (AiKeyword.kind == LANG_KIND))


def unknown_language_work(
    session: Session, limit: int, *, exclude_ids: Collection[int] | None = None
) -> list[ArticleWork]:
    """Articles STILL unknown after the offline detector AND not yet AI-labelled: both
    ``language`` AND ``detected_language`` unset (NULL or empty) AND no ``ai_keyword``
    language row. Newest first, bounded.

    The AI-label exclusion is LOAD-BEARING (skeptic HIGH): the job never writes the trusted
    channels, so without it the "unknown" set is constant and every run would re-fetch the
    SAME newest ``limit`` rows — the tail beyond ``limit`` would be UNREACHABLE. Excluding
    already-labelled articles in SQL makes the window SLIDE, so re-running truly continues the
    tail and the candidate count falls. (A garbage/'none' article stores no row, so it
    legitimately recurs and is retried — miss over invent.)

    ``exclude_ids`` is the CONTINUOUS-MODE seam (2026-07-23): a "none"/failed article writes
    no row, so within ONE continuous run — which must chain many batches without re-querying
    the DB in between attempts — the SQL exclusion above is not enough on its own: it would
    let the SAME still-unclassifiable articles (newest first, never labelled) re-occupy every
    subsequent batch's window forever, starving the rest of the backlog. Passing the set of
    article ids this run has already ATTEMPTED (regardless of outcome) makes every batch
    advance past them too, so a continuous run always terminates once genuinely nothing is
    left to attempt."""
    unset = lambda col: or_(col.is_(None), col == "")  # noqa: E731
    stmt = select(Article.id, Article.title, Article.content, Article.language).where(
        unset(Article.language), unset(Article.detected_language), ~_already_labelled()
    )
    if exclude_ids:
        stmt = stmt.where(~Article.id.in_(exclude_ids))
    rows = session.execute(stmt.order_by(Article.id.desc()).limit(limit)).all()
    return [ArticleWork(r[0], r[1] or "", r[2] or "", r[3]) for r in rows]


def detect_for_articles(
    work: list[ArticleWork],
    client,
    *,
    model: str,
    keep_alive: str | None = None,
    skip_existing: bool = True,
    should_stop=None,
    max_workers: int = 1,
) -> Iterator[dict]:
    """Detect + persist a language label for each article, yielding progress events.

    Emits a ``start``, one ``item`` per article (status = stored | skipped | failed | none),
    and a final ``done`` — or an aborted ``done`` if the local model goes away mid-run. All
    writes go to ``ai_keyword`` (kind="language") via the main session; ``Article.language``
    and ``Article.detected_language`` are NEVER written. A recognised code is stored; a
    garbage/unknown answer stores nothing (status "none").

    B3 (2026-07-24 Session B): ``max_workers`` bounds how many ``detect_language_llm``
    calls run concurrently (vLLM's actual advantage; Ollama stays serial at the
    default 1 — see ``src.llm.concurrency``). Results are still processed and
    stored STRICTLY IN INPUT ORDER within each concurrent chunk, so a label is
    never attributed to the wrong article and ``max_workers=1`` is byte-identical
    to the pre-B3 serial loop."""
    from src.llm.concurrency import run_concurrent

    total = len(work)
    yield {"event": "start", "total": total, "model": model, "kind": LANG_KIND}
    stored = skipped = failed = none = 0

    with session_scope() as session:
        already: set[int] = set()
        if skip_existing and work:
            ids = [w.article_id for w in work]
            already = {
                r[0]
                for r in session.execute(
                    select(AiKeyword.article_id).where(
                        AiKeyword.article_id.in_(ids), AiKeyword.kind == LANG_KIND
                    )
                ).all()
            }

        workers = max(1, max_workers)
        idx = 0
        n = len(work)
        while idx < n:
            if should_stop is not None and should_stop():
                yield {"event": "done", "total": total, "stored": stored, "skipped": skipped,
                       "failed": failed, "none": none, "aborted": True, "reason": "cancelled"}
                return
            batch: list[tuple[int, ArticleWork]] = []
            while idx < n and len(batch) < workers:
                w = work[idx]
                idx += 1
                pos = idx
                if skip_existing and w.article_id in already:
                    skipped += 1
                    yield {"event": "item", "i": pos, "total": total,
                           "article_id": w.article_id, "status": "skipped"}
                    continue
                batch.append((pos, w))
            if not batch:
                continue

            results = run_concurrent(
                batch,
                lambda item: detect_language_llm(
                    client, item[1].title, item[1].content, model=model, keep_alive=keep_alive
                ),
                max_workers=workers,
            )
            for (pos, w), res in zip(batch, results, strict=True):
                if not res.ok:
                    if isinstance(res.error, LLMUnavailable):
                        yield {"event": "done", "total": total, "stored": stored,
                               "skipped": skipped, "failed": failed, "none": none,
                               "aborted": True, "reason": str(res.error)[:200]}
                        return
                    failed += 1
                    yield {"event": "item", "i": pos, "total": total, "article_id": w.article_id,
                           "status": "failed", "error": str(res.error)[:200]}
                    continue
                code = res.value
                if not code:
                    none += 1  # garbage/unknown answer — store NOTHING (miss over invent)
                    yield {"event": "item", "i": pos, "total": total,
                           "article_id": w.article_id, "status": "none"}
                    continue
                ai_store.record_keywords(
                    session, w.article_id, [code], model=model, kind=LANG_KIND,
                    language=code, prompt_version=LANGDETECT_PROMPT_VERSION,
                )
                session.commit()  # persist progress; release the gate between articles
                stored += 1
                yield {"event": "item", "i": pos, "total": total,
                       "article_id": w.article_id, "status": "stored", "language": code}

    yield {"event": "done", "total": total, "stored": stored, "skipped": skipped,
           "failed": failed, "none": none, "aborted": False}


__all__ = [
    "LANGDETECT_PROMPT_VERSION", "LANG_KIND", "build_system", "parse_lang",
    "detect_language_llm", "unknown_language_work", "detect_for_articles", "lang_name",
]
