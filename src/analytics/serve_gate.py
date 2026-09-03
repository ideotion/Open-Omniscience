"""Cheap corpus-change watermark for the in-memory rollup serves (P1.10, SCALE_ROADMAP).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 12:14 field logs (2026-07-09) showed the 15-minute-TTL rollup rebuilds CHURNING:
trending-windows paid 62 calls / 3,286 s while the corpus sat unchanged between them — a
blind timer rebuilding a 20.9 M-mention rollup because a clock ticked, not because data
changed. This module gives :mod:`rollup_serve` and :mod:`map_serve` the CHANGE SIGNAL a
timer lacks, so a rebuild happens on CHANGE, not on a timer:

  * the **corpus epoch** (``derived_meta``, :mod:`src.analytics.corpus_epoch`) — bumped by
    exactly the non-append mutators (re-index / prune / restore-merge), INCLUDING one made
    by ANOTHER connection (the value lives in the database, not this process);
  * the **append watermark** — ``MAX(id)`` of the tables the rollup derives from. Ordinary
    ingest APPENDS without bumping the epoch (by design — else every scrape pass would
    force a full rebuild), so a pure epoch gate would freeze the rollup during collection;
    the max-id tail catches exactly that growth. An O(log n) rightmost B-tree descent per
    table, never a scan.

HONEST LIMIT (why the callers keep a long backstop TTL): a change that neither bumps the
epoch nor moves a max id — a cascade delete of mentions, a sentiment backfill on existing
articles, a source-country edit — is INVISIBLE to this token. The backstop rebuild bounds
that staleness, and the serve's ``basis``/``as_of`` disclosure keeps it visible either way.

A coordination read, not an analytic; never a score. Any error -> ``None`` (the caller
falls back to its backstop cadence — a doubt must never break or churn a serve).
"""

from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)


def change_token(
    session: Session, *, articles: bool = False, sources: bool = False
) -> tuple | None:
    """The cheap corpus-change watermark ``(corpus_epoch, max_mention_id[, max_article_id]
    [, max_source_id])`` — equal tokens mean "nothing the rollup derives from has visibly
    changed" (modulo the disclosed invisible classes above).

    Column-only queries throughout: the epoch is read with a fresh SELECT (never
    ``session.get``, whose identity map would hide another connection's bump inside a
    long-lived session), and each max id is an index-only lookup. ``None`` on ANY error.
    """
    from sqlalchemy import func

    from src.analytics.corpus_epoch import CORPUS_EPOCH_KEY
    from src.database.models import Article, DerivedMeta, KeywordMention, Source

    try:
        raw = (
            session.query(DerivedMeta.value)
            .filter(DerivedMeta.key == CORPUS_EPOCH_KEY)
            .scalar()
        )
        try:
            epoch = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            epoch = 0
        token: list[int] = [
            epoch,
            int(session.query(func.max(KeywordMention.id)).scalar() or 0),
        ]
        if articles:
            token.append(int(session.query(func.max(Article.id)).scalar() or 0))
        if sources:
            token.append(int(session.query(func.max(Source.id)).scalar() or 0))
        return tuple(token)
    except Exception:  # noqa: BLE001 - a coordination read must never break its caller
        _LOG.debug("serve gate: change-token read failed", exc_info=True)
        return None


def exclusive_verdict() -> dict | None:
    """Should a whole-corpus background build DECLINE right now because an exclusive
    operation owns the machine?

    Returns a skip record while an exclusive window is open (a restore, an import, the
    all-diagnostics bundle), else ``None``.

    WHY THIS EXISTS (S6.1, 2026-09-03). ``exclusive_window()`` pauses the CONTINUOUS
    COLLECTION LOOP and blocks ``run_now()``, and that was read as "the machine is
    claimed". It is not: the two rollup builds are kicked from a SERVE, i.e. from any
    HTTP read that happens to find the change gate open, so they start on their own
    schedule and never consulted the hold. That is precisely the shape the 2026-07-24
    lesson names -- "a pause that only stops the primary loop is honest-sounding and
    incomplete" -- and a whole-corpus columnar rebuild is the single heaviest thing this
    process does outside a pass.

    DECLINING IS SAFE HERE, and only here, because both callers are AUTO-ON accelerators
    whose own docstrings already say so: a skip leaves the previous rollup serving with
    ``change_pending`` true, so the next check retries, and the serve falls back to live
    queries -- "a declined build costs latency, never an answer". An operator asking for
    a build explicitly (the rollup benchmark calls ``columnar.build_keyword_daily``
    directly) never reaches this gate, which is the same carve-out ``_memory_verdict``
    makes.

    NOT extended to the briefing recompute: that one is kicked by a Home POLL, i.e. by a
    person waiting for an answer, and the standing ruling is that user work preempts
    background work -- refusing it for the hours a bundle can run would leave Home stale
    on a request the user just made.

    An unreadable scheduler is NOT evidence of a claim: any error returns ``None`` and the
    build proceeds, matching ``_memory_verdict``'s blind-guard direction (declining on an
    absent measurement would refuse every build wherever the import fails).
    """
    try:
        from src.scheduler.runner import exclusive_window_open

        if not exclusive_window_open():
            return None
        return {
            "reason": "exclusive-hold",
            "at": time.time(),
            # The claim is bounded and best-effort by construction: this says an
            # exclusive window is OPEN, never that nothing else is mid-flight.
            "detail": "an exclusive operation owns the machine (restore/import/diagnostics)",
        }
    except Exception:  # noqa: BLE001 - an unreadable scheduler must not block the build
        _LOG.debug("serve gate: exclusive-hold read failed", exc_info=True)
        return None
