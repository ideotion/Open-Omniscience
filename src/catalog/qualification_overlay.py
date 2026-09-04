"""
The SHIPPED QUALIFICATION OVERLAY -- verdicts that travel with the app, so a fresh install
starts from what earlier instances already measured.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ASK (maintainer, 2026-09-04): "the app accumulates qualified sources so that any newly
fresh install comprises a list of app-qualified sources to begin with", with the catalog
"updated to include only qualified sources, and the rest ... added to the list of sources
that aren't yet qualified".

THE SHAPE RULED: a SEPARATE generated file, ``configs/source_qualification.yml``, mapping
domain -> verdict. ``configs/sources.yml`` stays hand-curated and byte-untouched -- the
recorded "never re-serialise a curated file to edit one entry" lesson forbids rewriting
3,429 entries per accumulation run, which would bury the real diff and conflict with every
parallel curation change. The two lists the ask describes fall out of this without splitting
anything: a domain IN the overlay ships judged, a domain absent from it ships unqualified and
queues for qualification exactly as today. Same curated+generated shape as
``legal_sources_generated.yml``.

WHY THIS IS NOT THE PRE-QUALIFIED-BY-CURATION STAMP THE 2026-07-20 RULING REJECTED. That
ruling refused a verdict asserted by CURATION -- somebody's opinion standing in for evidence.
Every row here was EARNED by ``run_qualification_pass`` on a real corpus: it is the same
basis a restored backup's stamp already travels on, and the same basis the receiving
install's own first pass would eventually have produced. What changes is only that the
measurement no longer has to be repeated from scratch on every install.

ADOPTION IS THE MERGE'S RULE, DELIBERATELY IDENTICAL (see ``_merge_sources``): a verdict is
adopted only where the local row reads ``unqualified``, which means "no verdict has been
reached here" -- there is nothing to overwrite, so adopting is pure information gain. A local
verdict always wins, in BOTH directions: a local ``disqualified`` can never be laundered to
``qualified`` by a shipped file, and a local ``qualified`` is never downgraded by one. Two
paths that adopt the same kind of evidence must not disagree about who wins.

DISQUALIFIED VERDICTS SHIP TOO (ruled): a fresh install skips a known-broken source instead
of spending Tor bandwidth rediscovering that it is broken, and the re-qualification ladder
still gives it its second chance on the clock. That makes the overlay a RECORD rather than a
whitelist -- the honest artifact, and the one that cannot quietly narrow what the app looks at.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.catalog.qualification import (
    CRITERIA_VERSION,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    log_inherited_stamps,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_LOG = logging.getLogger("catalog.qualification_overlay")

DEFAULT_OVERLAY_PATH = Path(__file__).resolve().parents[2] / "configs" / "source_qualification.yml"

# Only a real verdict may ship. `unqualified` is the ABSENCE of one, so a row carrying it
# would be noise that adopts nothing; `no_evidence`/`inherited` are attempt-log verdicts and
# were never Source.status values. A row with anything else is dropped LOUDLY rather than
# coerced, because coercing an unknown verdict is how a file starts deciding things nobody
# reviewed.
SHIPPABLE_VERDICTS = (STATUS_QUALIFIED, STATUS_DISQUALIFIED)


def _parse_stamp(raw: object) -> datetime | None:
    """A date or datetime from YAML -> an aware UTC datetime. Anything unreadable becomes
    None rather than `now`: a stamp is the date a verdict was REACHED, and inventing one
    would restart the re-verification clock on a verdict that is actually old -- the exact
    fabricated freshness the inherited-clock rule exists to prevent."""
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, date):
        return datetime(raw.year, raw.month, raw.day, tzinfo=UTC)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def load_overlay(path: Path | None = None) -> dict[str, dict]:
    """``{domain: {"status", "qualified_at", "criteria_version"}}``, or ``{}`` when the file
    is absent -- an install that ships no overlay behaves exactly as it does today.

    Malformed rows are SKIPPED and counted in the log, never guessed at: this file decides
    what a fresh install collects, so a row it cannot read must not become a verdict."""
    p = path or DEFAULT_OVERLAY_PATH
    if not p.exists():
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - a broken overlay must never block boot
        _LOG.warning("could not read the qualification overlay at %s", p, exc_info=True)
        return {}
    rows = raw.get("verdicts") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return {}

    out: dict[str, dict] = {}
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        domain = str(row.get("domain") or "").strip().lower()
        status = str(row.get("status") or "").strip()
        if not domain or status not in SHIPPABLE_VERDICTS:
            skipped += 1
            continue
        out[domain] = {
            "status": status,
            "qualified_at": _parse_stamp(row.get("qualified_at")),
            "criteria_version": str(
                row.get("criteria_version") or raw.get("criteria_version") or CRITERIA_VERSION
            ),
        }
    if skipped:
        _LOG.warning("qualification overlay: skipped %d unreadable row(s) in %s", skipped, p)
    return out


def apply_overlay(
    session: Session, overlay: dict[str, dict] | None = None, *,
    now: datetime | None = None, path: Path | None = None,
) -> dict:
    """Adopt shipped verdicts onto never-judged local sources. Idempotent and cheap on every
    boot after the first: adoption only touches rows reading ``unqualified``, and a row it
    stamps stops matching (nothing ever returns to ``unqualified``, so there is no
    oscillation).

    Returns a tally that distinguishes what was ADOPTED from what was DECLINED because this
    instance had already judged the source itself -- two facts a single number cannot carry,
    and the second is the evidence that local-wins is actually holding.
    """
    from src.database.models import Source

    overlay = load_overlay(path) if overlay is None else overlay
    if not overlay:
        return {"available": False, "adopted": 0, "kept_local": 0}

    now = now or datetime.now(UTC)
    rows = (
        session.query(Source)
        .filter(Source.domain.in_(sorted(overlay)))
        .all()
    )

    adopted: list[Source] = []
    kept_local = 0
    counts = {STATUS_QUALIFIED: 0, STATUS_DISQUALIFIED: 0}
    for source in rows:
        record = overlay.get((source.domain or "").strip().lower())
        if record is None:
            continue
        if (source.status or STATUS_UNQUALIFIED) != STATUS_UNQUALIFIED:
            # This instance reached its own verdict. Local wins -- the same rule the restore
            # merge applies to the same kind of evidence.
            kept_local += 1
            continue
        source.status = record["status"]
        if record["status"] == STATUS_QUALIFIED:
            source.qualified_at = record["qualified_at"]
            source.qualification_criteria_version = record["criteria_version"]
        else:
            # Mirrors evaluate_and_stamp: a disqualified row carries no 'qualified' stamp,
            # so a stale one can never survive a failure.
            source.qualified_at = None
            source.qualification_criteria_version = None
        counts[record["status"]] += 1
        adopted.append(source)

    if adopted:
        # The attempt row says the stamp was INHERITED, not measured here. It is what stops a
        # reader (and the ladder) mistaking a shipped verdict for local evidence, and it is
        # deliberately excluded from the qualified re-verification clock, so a stamp that was
        # already old when it shipped comes due sooner rather than reading as fresh today.
        log_inherited_stamps(session, adopted, now=now)
    session.commit()
    return {
        "available": True,
        "adopted": len(adopted),
        "qualified": counts[STATUS_QUALIFIED],
        "disqualified": counts[STATUS_DISQUALIFIED],
        "kept_local": kept_local,
        "in_overlay": len(overlay),
    }
