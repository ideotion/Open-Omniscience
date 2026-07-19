"""
Per-jurisdiction law coverage/freshness diagnostic.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S5 of the law-vertical brief (2026-07-17): "the maintainer's next 'is law working?'
is answered by one JSON." Per-jurisdiction tracked-document counts, baseline
coverage, freshness ages, and a per-document verdict tally (reusing the exact
classification the Governments -> Law UI already shows, src.api.law._verdict_of,
so there is never a second, drifting guess at what a status string means).

THE COMPLETENESS PRINCIPLE (brief §2, maintainer-clarified 2026-07-17): a tracked
document is an entry point, never a coverage claim. "Covering a jurisdiction" means
covering its OWN official enumeration of its legal corpus (France alone has 76
codes en vigueur) — a per-jurisdiction enumeration adapter (S6, network-gated, not
built by this pass) is what supplies that denominator. Until one exists for a
jurisdiction, this diagnostic says so honestly ("no enumeration adapter — coverage
unknown") instead of presenting the tracked count as if it measured completeness.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.database.models import LawDocument


def law_coverage_report(session: Session) -> dict:
    """Counts + method, no score. See module docstring for the completeness caveat."""
    from src.api.law import _verdict_of  # the ONE classification, reused (never a 2nd guess)

    docs = session.query(LawDocument).order_by(LawDocument.jurisdiction, LawDocument.id).all()
    by_jur: dict[str, list[LawDocument]] = {}
    for d in docs:
        by_jur.setdefault(d.jurisdiction, []).append(d)

    now = datetime.now(UTC)

    def _age_hours(dt) -> float | None:
        if dt is None:
            return None
        # SQLite stores naive datetimes; the app writes them from datetime.now(UTC),
        # so treat a naive value as UTC rather than mixing aware/naive subtraction.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return (now - dt).total_seconds() / 3600.0

    jurisdictions = []
    for jur, rows in sorted(by_jur.items()):
        tracked = len(rows)
        baselined = sum(1 for r in rows if r.baseline_text is not None)
        verdicts: dict[str, int] = {}
        ages: list[float] = []
        never_checked = 0
        for r in rows:
            age = _age_hours(r.last_checked_at)
            if age is None:
                # Never checked: no real outcome to classify -- counted ONLY in the
                # dedicated `never_checked` field, never smeared into `verdicts` too
                # (which would double-count the same fact two different ways).
                never_checked += 1
            else:
                ages.append(age)
                v = _verdict_of(r.last_status)
                verdicts[v] = verdicts.get(v, 0) + 1
        jurisdictions.append(
            {
                "jurisdiction": jur,
                "tracked": tracked,
                "baselined": baselined,
                "baseline_pct": round(100 * baselined / tracked, 1) if tracked else 0.0,
                "never_checked": never_checked,
                "oldest_check_age_hours": round(max(ages), 1) if ages else None,
                "newest_check_age_hours": round(min(ages), 1) if ages else None,
                "verdicts": verdicts,
                # THE COMPLETENESS PRINCIPLE: never a fabricated coverage fraction.
                "coverage": "no enumeration adapter — coverage unknown",
            }
        )

    total_docs = len(docs)
    total_baselined = sum(1 for d in docs if d.baseline_text is not None)
    return {
        "documents": total_docs,
        "baselined": total_baselined,
        "jurisdictions": jurisdictions,
        "method": (
            "Per-jurisdiction tracked-document counts, baseline coverage, freshness "
            "ages (hours since last_checked_at), and -- for documents that have "
            "actually been checked at least once -- their last_status classified "
            "into a small honest verdict set (robots_blocked / error / empty / "
            "changed / reverted / baselined / unchanged / other — the same "
            "classification the Governments -> Law UI shows). A document never yet "
            "checked has no outcome to classify, so it is counted only in "
            "`never_checked`, never smeared into `verdicts` too. Counts and ages "
            "only, no score."
        ),
        "caveat": (
            "A tracked-document count is an entry point, never a coverage claim: "
            "\"covering a jurisdiction\" means covering its OWN official enumeration "
            "of its legal corpus (e.g. France's 76 codes en vigueur) — that needs a "
            "per-jurisdiction enumeration adapter this install does not yet have. "
            "Every jurisdiction below honestly reports coverage as unknown rather "
            "than presenting the tracked count as if it were the whole corpus."
        ),
    }
