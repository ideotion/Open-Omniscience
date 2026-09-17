"""Read and write the TENTATIVE keyword-translation table (Q404's writers, brief S04-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``S04-04`` shipped the ``keyword_translations`` model, its migration and its merge
handler, and its docstring says in as many words that *"WRITERS LIVE IN ``S04-06``"* —
so the table has restored cleanly through a format bump before anything put a row in
it. This module is those writers, and the reader the ladder's tentative rung needs.

**WHAT A ROW IS, AND WHAT IT IS NOT.** One local model's answer about one term, kept
with the provenance needed to judge it. It is never the trusted index: the VERIFIED
ring translation always wins, :func:`src.ai_layer.translate.translate_keywords` already
skips any term a ring covers, and the ladder only ever reaches this rung when rung one
answered nothing. A reader that renders one of these owes the ``≈`` tier label.

**THE IDENTITY IS THE FULL FIVE-TUPLE** ``(term, source_lang, target_lang, model,
prompt_version)`` — the vintage shape, not the "one current translation" shape, because
a different model or prompt version is a DIFFERENT measurement and collapsing them
would pick a winner between two answers nobody compared. Two consequences this module
has to honour rather than work around:

* **The dedupe must be NULL-safe.** ``model`` and ``prompt_version`` are nullable by
  design, and SQLite's UNIQUE treats NULL as distinct from NULL — measured by the
  ``S04-04`` session, two byte-identical inserts with both NULL produced TWO rows. The
  schema's ``uq_keyword_translation_nullsafe`` expression index over the COALESCEd five
  columns is what actually enforces the declared identity, so the writer here inserts
  through it (``INSERT OR IGNORE``) rather than hand-rolling a ``WHERE NOT EXISTS`` that
  would disagree with it.
* **The "one answer" rule lives at the READ.** :func:`tentative_translations` picks the
  newest ``created_at`` and says so in its own docstring, rather than deleting older
  rows at write time — a rule at the read is visible, a deletion at the write is not.

**NOTHING HERE FABRICATES.** A term with no row gets no entry in the returned mapping,
and the ladder then reports ``untranslated``. The tempting fallback — echoing the source
term so every keyword "has" a translation — would make the tentative tier a measure of
nothing, so the absence is the honest answer and is pinned by a test.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from src.analytics.equivalence import _norm
from src.analytics.managed import normalize_lang
from src.database.models import KeywordTranslation

#: How many terms one read will resolve. A bound on the reader, independent of any
#: bound the writer honours -- the oversized table already exists by the time a reader
#: finds out, and every reader of an on-disk artifact needs its own ceiling.
_READ_CAP = 2000


def _key(term: str) -> str:
    """The normalised source term — ``equivalence._norm``, which is what the model's own
    cache keys on, so the two can never disagree about what "the same term" means."""
    return _norm(term)


def record_tentative(
    session: Session,
    *,
    term: str,
    source_lang: str | None,
    target_lang: str,
    text: str,
    model: str | None = None,
    prompt_version: str | None = None,
    commit: bool = True,
) -> bool:
    """Persist ONE tentative translation. Returns True when a row was actually added.

    Idempotent through the schema's NULL-safe unique index rather than through a
    read-then-write race: two callers asking the same model the same question on two
    threads both insert, and the second is ignored by the database.

    Refuses silently-useless input (an empty term, an empty answer, a same-language
    no-op, an answer identical to the source term) — recording those would fill the
    table with rows that assert nothing and would let a coverage count over it read as
    progress.
    """
    t = _key(term)
    src = normalize_lang(source_lang) or None
    tgt = normalize_lang(target_lang)
    body = (text or "").strip()
    if not t or not tgt or not body:
        return False
    if src == tgt or _norm(body) == t:
        return False
    stmt = insert(KeywordTranslation).values(
        term=t,
        source_lang=src or "",
        target_lang=tgt,
        text=body,
        model=model or None,
        prompt_version=prompt_version or None,
    )
    # SQLite: OR IGNORE lets the unique EXPRESSION index do the dedupe, which is the one
    # the merge handler's COALESCE key also matches.
    result = session.execute(stmt.prefix_with("OR IGNORE"))
    if commit:
        session.commit()
    return bool(getattr(result, "rowcount", 0))


def record_tentative_batch(
    session: Session,
    rows: Iterable[Mapping[str, Any]],
    *,
    target_lang: str,
    model: str | None = None,
    prompt_version: str | None = None,
) -> dict:
    """Persist a batch of ``{term, language, text}`` answers. Returns a small tally.

    ONE commit for the batch, and each row inserted through its own statement so a
    single refused row cannot discard the ones already staged beside it — the recorded
    mid-batch-rollback family, which this shape avoids by never rolling back at all
    (``OR IGNORE`` makes a collision a no-op rather than an ``IntegrityError``).
    """
    added = skipped = 0
    for r in rows:
        ok = record_tentative(
            session,
            term=str(r.get("term") or ""),
            source_lang=r.get("language"),
            target_lang=target_lang,
            text=str(r.get("text") or ""),
            model=model,
            prompt_version=prompt_version,
            commit=False,
        )
        added += int(ok)
        skipped += int(not ok)
    session.commit()
    return {"added": added, "skipped": skipped, "target_lang": normalize_lang(target_lang)}


def tentative_translations(
    session: Session, terms: Iterable[str], target_lang: str
) -> dict[str, dict]:
    """``{normalised term: {text, model, prompt_version, created_at}}`` for ``target_lang``.

    **WHICH ROW, WHEN THERE ARE SEVERAL.** The identity keeps one row per (model, prompt
    version), so a term can legitimately carry several answers. This returns the NEWEST
    by ``created_at`` and says so here, where a reader can see the rule — the alternative
    is deleting the older rows at write time, which hides the fact that two models
    disagreed. The ``model`` and ``prompt_version`` travel with the text so a surface can
    show WHO said it.

    A term with no row is ABSENT from the mapping, never present with an empty string:
    "no model has answered this" and "a model answered with nothing" are different facts,
    and only the first one is true here.
    """
    tgt = normalize_lang(target_lang)
    keys = [k for k in {_key(t) for t in terms} if k][:_READ_CAP]
    if not tgt or not keys:
        return {}
    newest = (
        select(
            KeywordTranslation.term,
            func.max(KeywordTranslation.created_at).label("newest"),
        )
        .where(KeywordTranslation.target_lang == tgt, KeywordTranslation.term.in_(keys))
        .group_by(KeywordTranslation.term)
        .subquery()
    )
    rows = session.execute(
        select(
            KeywordTranslation.term,
            KeywordTranslation.text,
            KeywordTranslation.model,
            KeywordTranslation.prompt_version,
            KeywordTranslation.created_at,
        ).join(
            newest,
            (KeywordTranslation.term == newest.c.term)
            & (KeywordTranslation.created_at == newest.c.newest),
        ).where(KeywordTranslation.target_lang == tgt)
    ).all()
    out: dict[str, dict] = {}
    for term, text, model, prompt_version, created_at in rows:
        if term in out:  # two rows share the newest timestamp: keep the first, deterministically
            continue
        out[term] = {
            "text": text,
            "model": model,
            "prompt_version": prompt_version,
            "created_at": created_at.isoformat() if created_at else None,
        }
    return out


def tentative_coverage(session: Session, target_lang: str) -> dict:
    """How many DISTINCT terms carry a tentative answer into ``target_lang``.

    Counts only, with the method stated. Deliberately NOT expressed as a percentage of
    anything: the denominator a reader would assume ("of all keywords") is a different
    population from the one the sweep was ever pointed at, and a ratio over a
    mostly-empty derived table degenerates into an existence test.
    """
    tgt = normalize_lang(target_lang)
    if not tgt:
        return {"terms": 0, "rows": 0, "target_lang": "", "method": "no target language given"}
    terms = session.scalar(
        select(func.count(func.distinct(KeywordTranslation.term))).where(
            KeywordTranslation.target_lang == tgt
        )
    )
    rows = session.scalar(
        select(func.count()).select_from(KeywordTranslation).where(
            KeywordTranslation.target_lang == tgt
        )
    )
    return {
        "terms": int(terms or 0),
        "rows": int(rows or 0),
        "target_lang": tgt,
        "method": (
            "Distinct terms with at least one TENTATIVE (local-model) translation into "
            "this language, and the total rows behind them -- more rows than terms means "
            "several models or prompt versions answered the same term, which is kept "
            "rather than collapsed. Never the verified tier, never a score, and not "
            "expressed as a share of any population."
        ),
    }
