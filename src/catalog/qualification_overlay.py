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
    CURATED_CRITERIA_VERSION,
    JUDGING_VERDICTS,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_CURATED,
    VERDICT_INHERITED,
    is_collectable,
    log_inherited_stamps,
    record_admission,
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
    if not adoption_enabled():
        # The operator reverted (Q1106's third operation). Adoption looks for rows
        # reading `unqualified`, which is precisely the state a revert restores, so
        # without this the next boot would undo the revert and the operator would find
        # the verdicts back. Reported rather than skipped silently -- a boot step that
        # declined to run is a fact the editor shows.
        return {
            "available": True, "adopted": 0, "kept_local": 0,
            "declined_by_preference": True, "in_overlay": len(overlay),
        }

    now = now or datetime.now(UTC)
    rows = (
        session.query(Source)
        .filter(Source.domain.in_(sorted(overlay)))
        .all()
    )

    adopted: list[Source] = []
    kept_local = 0
    replaced_curated = 0
    admitted = 0
    counts = {STATUS_QUALIFIED: 0, STATUS_DISQUALIFIED: 0}
    for source in rows:
        record = overlay.get((source.domain or "").strip().lower())
        if record is None:
            continue
        local_status = source.status or STATUS_UNQUALIFIED
        # A stamp the curated catalogue carries BY RULING (2026-09-10) is not a local
        # verdict: nothing was measured here, so a shipped verdict that WAS measured
        # outranks it in either direction -- a shipped `disqualified` in particular must
        # not be declined as "local wins" on the strength of a curation stamp.
        curated_stamp = (
            local_status == STATUS_QUALIFIED
            and source.qualification_criteria_version == CURATED_CRITERIA_VERSION
        )
        if local_status != STATUS_UNQUALIFIED and not curated_stamp:
            # This instance reached its own verdict. Local wins -- the same rule the restore
            # merge applies to the same kind of evidence.
            kept_local += 1
            continue
        if curated_stamp:
            replaced_curated += 1
        # Read BEFORE the write, for the same reason evaluate_and_stamp does: the audit
        # row's whole purpose is to let an operator put the source back.
        prior_enabled = source.enabled
        prior_status = source.status
        source.status = record["status"]
        if record["status"] == STATUS_QUALIFIED:
            source.qualified_at = record["qualified_at"]
            source.qualification_criteria_version = record["criteria_version"]
        else:
            # Mirrors evaluate_and_stamp: a disqualified row carries no 'qualified' stamp,
            # so a stale one can never survive a failure.
            source.qualified_at = None
            source.qualification_criteria_version = None
        # ADOPTION IS A SECOND WAY INTO COLLECTION, and it was an unrecorded one. The
        # catalogue ships its rows `enabled: true` awaiting a verdict, so adopting a
        # shipped `qualified` verdict onto one takes it from unreachable to actively
        # scraped without `enabled` moving -- live-reproduced as `select_sources` going
        # from [] to [the domain] while the admission audit stayed empty and the undo had
        # nothing to act on. The verdict recorded is `inherited` rather than `qualified`,
        # which is the project's existing word for a stamp this instance did not measure:
        # the audit then says WHICH KIND of evidence let the source in, and an operator
        # reading the list can tell a local judgement from a shipped one without leaving
        # the row. Undo is the ordinary one -- it restores prior_enabled and prior_status.
        if record_admission(
            session, source, prior_enabled=prior_enabled, prior_status=prior_status,
            now=now, verdict=VERDICT_INHERITED,
            criteria_version=record["criteria_version"],
        ):
            admitted += 1
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
        # Curated stamps a measured shipped verdict replaced -- reported apart from
        # `adopted` onto never-judged rows, because "we had no verdict" and "we had a
        # ruling's stamp and a measurement outranked it" are different facts.
        "replaced_curated": replaced_curated,
        # How many of those adoptions actually ADMITTED a source to collection -- each one
        # carries an admission-audit row and can be undone there individually. Reported
        # apart from `adopted`, because adopting a verdict onto a disabled row changes
        # what the app KNOWS and adopting one onto an enabled row changes what it DOES.
        "admitted": admitted,
        "in_overlay": len(overlay),
    }


def adoption_enabled() -> bool:
    """Is this install adopting the shipped verdicts at startup? (``AppSettings``.)

    Defensive by design: this is read on the BOOT path, and a settings file that cannot
    be read must not stop the app from starting. Any failure reads as True, which is the
    behaviour that shipped before the preference existed -- the safe direction here is
    the one that changes nothing.
    """
    try:
        from src.config.app_settings import load_settings

        return bool(load_settings().adopt_shipped_verdicts)
    except Exception:  # noqa: BLE001 - never block boot on a preference read
        _LOG.debug("could not read the overlay-adoption preference; adopting", exc_info=True)
        return True


def _attempt_marks(session: Session, source_ids: list[int]) -> dict[int, dict]:
    """Per source: when this install last INHERITED a stamp, last JUDGED it for itself,
    and last stamped it from the curated catalogue.

    One pass over the attempt log for the whole candidate set, because the editor asks
    this about every domain in the overlay at once and a per-source query would be one
    round trip per shipped verdict.
    """
    from src.database.models import SourceQualificationAttempt as A

    marks: dict[int, dict] = {}
    if not source_ids:
        return marks
    rows = (
        session.query(A.source_id, A.verdict, A.attempted_at)
        .filter(A.source_id.in_(source_ids))
        .all()
    )
    for sid, verdict, at in rows:
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        mark = marks.setdefault(int(sid), {"inherited": None, "judged": None, "curated": None})
        if verdict == VERDICT_INHERITED:
            key = "inherited"
        elif verdict in JUDGING_VERDICTS:
            key = "judged"
        elif verdict == VERDICT_CURATED:
            key = "curated"
        else:
            continue
        if mark[key] is None or (at is not None and at > mark[key]):
            mark[key] = at
    return marks


# Why a row the overlay stamped here cannot be put back. Each is a REFUSAL with a
# reason, never a silent skip: the editor shows the counts beside the revertible ones,
# because "nothing to revert" and "three rows I will not touch" are different states.
REVERT_DECLINE_JUDGED = "judged_here_since"
REVERT_DECLINE_CURATED = "was_curated_before"


def _adoptions(session: Session, overlay: dict[str, dict]) -> tuple[list, dict[str, int]]:
    """Rows in this corpus whose CURRENT stamp came from the overlay, split into the ones
    a revert may put back and the ones it declines, with the reason.

    A row qualifies as "adopted here" only if the attempt log says this install inherited
    a stamp for it AND its status still matches what the overlay says. Either half alone
    is not enough: an inherited row that has since been judged carries a local verdict
    (the attempt row is history, not the current state), and a row that merely agrees with
    the overlay may have reached that verdict by measuring.
    """
    from src.database.models import Source

    rows = session.query(Source).filter(Source.domain.in_(sorted(overlay))).all()
    marks = _attempt_marks(session, [int(r.id) for r in rows])
    revertible: list = []
    declined = {REVERT_DECLINE_JUDGED: 0, REVERT_DECLINE_CURATED: 0}
    for source in rows:
        record = overlay.get((source.domain or "").strip().lower())
        if record is None or source.status != record["status"]:
            continue
        mark = marks.get(int(source.id))
        if mark is None or mark["inherited"] is None:
            continue  # this install never adopted this row -- it agrees on its own
        inherited_at = mark["inherited"]
        judged_at = mark["judged"]
        if judged_at is not None and judged_at >= inherited_at:
            # A local measurement came after the adoption. The live verdict is this
            # install's own, whatever it happens to agree with, and reverting it would
            # throw away a measurement rather than an adoption.
            declined[REVERT_DECLINE_JUDGED] += 1
            continue
        curated_at = mark["curated"]
        if curated_at is not None and curated_at <= inherited_at:
            # The overlay REPLACED a stamp the curated catalogue carried by ruling
            # (2026-09-10). `unqualified` is not what this row looked like before, so a
            # revert here would invent a state rather than restore one. Refused and
            # counted, in the shape of every other refusal in this area.
            declined[REVERT_DECLINE_CURATED] += 1
            continue
        revertible.append(source)
    return revertible, declined


def overlay_status(session: Session, *, path: Path | None = None) -> dict:
    """What the overlay editor shows BEFORE the operator touches anything (Q1106 = a).

    Read-only and local: no network, no writes, nothing judged. Three questions, kept
    apart because a single number answers none of them -- what the shipped file CONTAINS,
    what this install has ALREADY taken from it, and what adopting now WOULD change.
    """
    from src.database.models import Source

    p = path or DEFAULT_OVERLAY_PATH
    overlay = load_overlay(p)
    file_info: dict = {
        "path": str(p),
        "exists": p.exists(),
        "size_bytes": p.stat().st_size if p.exists() else None,
        "generated_at": None,
    }
    if p.exists():
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                stamp = raw.get("generated_at")
                file_info["generated_at"] = str(stamp) if stamp else None
        except Exception:  # noqa: BLE001 - a header we cannot read is not a failure
            file_info["generated_at"] = None

    shipped = {STATUS_QUALIFIED: 0, STATUS_DISQUALIFIED: 0}
    for entry in overlay.values():
        shipped[entry["status"]] += 1

    revertible, declined = _adoptions(session, overlay) if overlay else ([], {
        REVERT_DECLINE_JUDGED: 0, REVERT_DECLINE_CURATED: 0,
    })

    # THE PREVIEW. Adopting is a write, so what it would do is shown first -- and the two
    # figures are kept apart because adopting a verdict onto a disabled row changes what
    # the app KNOWS, while adopting one onto an already-enabled row changes what it DOES.
    would_adopt = would_admit = would_withdraw = 0
    if overlay:
        for source in session.query(Source).filter(Source.domain.in_(sorted(overlay))).all():
            record = overlay.get((source.domain or "").strip().lower())
            if record is None:
                continue
            local_status = source.status or STATUS_UNQUALIFIED
            curated_stamp = (
                local_status == STATUS_QUALIFIED
                and source.qualification_criteria_version == CURATED_CRITERIA_VERSION
            )
            if local_status != STATUS_UNQUALIFIED and not curated_stamp:
                continue
            would_adopt += 1
            now_collectable = is_collectable(source.enabled, source.status)
            then_collectable = is_collectable(source.enabled, record["status"])
            if then_collectable and not now_collectable:
                would_admit += 1
            elif now_collectable and not then_collectable:
                # THE MIRROR, and it is not hypothetical: a shipped `disqualified`
                # landing on a row the curated catalogue stamped qualified takes it OUT
                # of collection. Adoption is presented as gaining verdicts, so the one
                # direction a reader would not think to ask about is the one that has to
                # be on the screen before they press the button.
                would_withdraw += 1

    return {
        "file": file_info,
        "adopting_at_startup": adoption_enabled(),
        "in_overlay": len(overlay),
        "shipped_qualified": shipped[STATUS_QUALIFIED],
        "shipped_disqualified": shipped[STATUS_DISQUALIFIED],
        "adopted_here": len(revertible) + sum(declined.values()),
        "revertible": len(revertible),
        "declined": declined,
        "would_adopt": would_adopt,
        "would_admit": would_admit,
        "would_withdraw": would_withdraw,
        "method": (
            "Read from the shipped file and this corpus's own attempt log. A row counts as "
            "adopted here when the log records that this install inherited a stamp for it "
            "AND its current verdict is still the one the file carries."
        ),
        "caveat": (
            "Adopting changes only rows this install has never judged for itself: a local "
            "verdict always wins, in both directions. Reverting puts back the rows adoption "
            "stamped and stops adopting at startup, so the decision holds; it never edits "
            "the shipped file, which is generated by the operator."
        ),
    }


def revert_overlay(
    session: Session, *, now: datetime | None = None, path: Path | None = None,
) -> dict:
    """Put back every row this install's overlay adoption stamped, and stop adopting.

    The mirror of the admission audit's undo, one step further out: undo reverses ONE
    automatic admission, this reverses the whole shipped-file adoption. What it restores
    is "no verdict has been reached here" -- which is what the row actually said before,
    since adoption only ever touches rows reading ``unqualified``.

    An open admission row for a reverted source is marked undone in the same transaction:
    the source has stopped being collectable, and an audit that went on listing it as a
    live admission would be reporting something that is no longer true.

    The shipped FILE is never written. Re-adopting is one click and re-reads it.
    """
    from src.database.models import Source, SourceAdmissionEvent

    now = now or datetime.now(UTC)
    overlay = load_overlay(path)
    if not overlay:
        return {"available": False, "reverted": 0, "admissions_undone": 0, "declined": {}}

    revertible, declined = _adoptions(session, overlay)
    ids = [int(s.id) for s in revertible]
    # NAIVE UTC, to match what the admission-audit undo endpoint writes into the same
    # column. A tz-aware value beside naive ones in one SQLite column is how a later
    # "is this undone" comparison starts raising rather than answering.
    undone = now.replace(tzinfo=None) if now.tzinfo is not None else now
    admissions_undone = 0
    for source in revertible:
        source.status = STATUS_UNQUALIFIED
        source.qualified_at = None
        source.qualification_criteria_version = None
    if ids:
        for ev in (
            session.query(SourceAdmissionEvent)
            .filter(
                SourceAdmissionEvent.source_id.in_(ids),
                SourceAdmissionEvent.undone_at.is_(None),
            )
            .all()
        ):
            ev.undone_at = undone
            admissions_undone += 1
    # Turned off HERE rather than by the caller, so the preference and the restore land in
    # one operation: a revert whose second half depends on a separate call is a revert that
    # can half-happen.
    try:
        from src.config.app_settings import save_settings

        save_settings({"adopt_shipped_verdicts": False})
    except Exception:  # noqa: BLE001 - reported, never swallowed into a clean result
        _LOG.warning("reverted the overlay but could not persist the preference", exc_info=True)
        preference_held = False
    else:
        preference_held = True
    session.commit()
    still_collecting = (
        session.query(Source.id)
        .filter(Source.id.in_(ids), Source.enabled.is_(True), Source.status == STATUS_QUALIFIED)
        .count()
        if ids else 0
    )
    return {
        "available": True,
        "reverted": len(revertible),
        "admissions_undone": admissions_undone,
        "declined": declined,
        # Whether the second half of the revert actually landed. FALSE means the rows are
        # back but the next startup will adopt them again, which the operator has to be
        # told -- it is the difference between a revert and a pause.
        "preference_held": preference_held,
        # Must be zero: a reverted row reads `unqualified`, which the collection gate
        # excludes. Measured rather than asserted, because the one thing a revert must
        # not leave behind is a source still being scraped on a verdict it gave back.
        "still_collecting": int(still_collecting),
    }
