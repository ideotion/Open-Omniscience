"""THE ADMISSION GATE: a `qualified` verdict flips `enabled=True`, under an audit trail
with an undo (Q1101 ⛔ = a, 2026-09-15; brief `S04-12` S1).

WHY THIS FILE IS WRITTEN THE WAY IT IS. Q1101 lets the app enable a source for collection
UNATTENDED. That is a data-safety change: the failure that matters is not "the flip did not
happen" but "something was admitted that should not have been", and the second one is
silent -- a source quietly joins collection and nothing anywhere says which decision let
it in. So most of what follows is NEGATIVE SPACE: verdicts that must NOT enable, a
no-evidence attempt that must not even leave a record, and an undo that must put back BOTH
halves of what it replaced rather than the half a reader would notice.

The recorded 2026-07-24 inversion class is the specific shape guarded here: an aggregation
that omits zero-evidence entries makes "absent" read as "passed", and an admission gate
then promotes a source on zero verification. `log_no_evidence_attempts` is the path that
case takes, and the tests below assert it reaches neither `status` nor `enabled` nor the
audit table.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.catalog.qualification import (  # noqa: E402
    CRITERIA_VERSION,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    UNDO_ALREADY_UNDONE,
    UNDO_LATER_ADMISSION,
    UNDO_LATER_VERDICT,
    AdmissionUndoRefused,
    admission_audit,
    evaluate_and_stamp,
    log_no_evidence_attempts,
    select_unqualified,
    undo_admission,
)
from src.database.models import Base, Source, SourceAdmissionEvent  # noqa: E402

NOW = datetime(2026, 9, 18, 12, 0, 0)

# One real failing criterion, in the shape `decide_verdict` reads: an extraction-failure
# criterion is the only kind that can disqualify, so this is what a `disqualified` verdict
# is actually made of rather than a plausible-looking dict.
_EXTRACTION_FAIL = [{"name": "extraction_failure", "extraction_failure": True}]
# A failing SOFT criterion -- real, and deliberately NOT disqualifying. Included because a
# fixture in which every failure disqualifies cannot tell "the verdict router works" from
# "everything fails", and because this is the row that must still be admitted.
_SOFT_FAIL = [{"name": "short_articles", "extraction_failure": False}]


def _session(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'adm.db'}", future=True)
    Base.metadata.create_all(engine)
    return Session(engine, future=True)


def _src(s: Session, domain: str, *, status: str = STATUS_UNQUALIFIED, enabled=False) -> Source:
    """NOTE THE DEFAULT, and that it is NOT production's.

    `configs/sources.yml` seeds essentially every catalogue source `enabled: true`, and
    `Source.enabled` carries `default=True` besides -- so `enabled=False` here is the
    DISCOVERED-CANDIDATE shape, not the common one. That mismatch is exactly what let an
    earlier cut of this file pass green over a real hole (an adversarial pass found it),
    so `_catalogue_src` below exists for the production shape and the tests that matter
    are driven over BOTH.
    """
    src = Source(name=domain, domain=domain, status=status, enabled=enabled)
    s.add(src)
    s.commit()
    return src


def _catalogue_src(s: Session, domain: str, *, status: str = STATUS_UNQUALIFIED) -> Source:
    """The shape the shipped catalogue actually produces: enabled, not yet judged."""
    return _src(s, domain, status=status, enabled=True)


def _events(s: Session) -> list[SourceAdmissionEvent]:
    return list(s.query(SourceAdmissionEvent).order_by(SourceAdmissionEvent.id).all())


# --------------------------------------------------------------------------- #
#  The flip itself
# --------------------------------------------------------------------------- #
def test_a_qualified_verdict_enables_the_source_and_records_the_prior_state(tmp_path) -> None:
    """Q1101's whole content, plus the audit row the ruling makes it rest on."""
    s = _session(tmp_path)
    src = _src(s, "good.example", status=STATUS_UNQUALIFIED, enabled=False)

    out = evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()

    assert src.enabled is True, "a qualified verdict did not admit the source"
    assert src.status == STATUS_QUALIFIED
    assert out["qualified"] == 1
    assert out["admitted"] == 1

    (ev,) = _events(s)
    assert ev.source_id == src.id
    assert ev.verdict == STATUS_QUALIFIED
    assert ev.criteria_version == CRITERIA_VERSION
    # The state the undo has to put back. `prior_enabled` False and `prior_status`
    # unqualified is exactly what the row was before the pass touched it.
    assert ev.prior_enabled is False
    assert ev.prior_status == STATUS_UNQUALIFIED
    assert ev.undone_at is None


def test_a_soft_criterion_failure_still_qualifies_and_still_admits(tmp_path) -> None:
    """Anti-vacuity for the fixture above: not every failing criterion disqualifies, so a
    source with a real soft failure must still be admitted. Without this, a bug that
    disqualified everything would be invisible in a file whose other fixtures pass clean."""
    s = _session(tmp_path)
    src = _src(s, "terse.example")

    evaluate_and_stamp(s, [src], {src.id: _SOFT_FAIL}, now=NOW)
    s.commit()

    assert src.status == STATUS_QUALIFIED
    assert src.enabled is True


# --------------------------------------------------------------------------- #
#  NEGATIVE SPACE -- what must never be admitted
# --------------------------------------------------------------------------- #
def test_a_disqualified_verdict_never_enables_and_never_records_an_admission(tmp_path) -> None:
    """The verdict that means 'judged and found wanting' must not reach `enabled`, and must
    leave NO admission row -- an audit trail that lists a non-admission is one a reader
    cannot use to answer 'what did the app let in'."""
    s = _session(tmp_path)
    src = _src(s, "broken.example", status=STATUS_UNQUALIFIED, enabled=False)

    out = evaluate_and_stamp(s, [src], {src.id: _EXTRACTION_FAIL}, now=NOW)
    s.commit()

    assert src.status == STATUS_DISQUALIFIED
    assert src.enabled is False, "a disqualified source was enabled for collection"
    assert out["admitted"] == 0
    assert _events(s) == []


def test_a_disqualified_verdict_does_not_disable_a_source_the_operator_enabled(tmp_path) -> None:
    """The MIRROR, and it is not symmetrical on purpose. Q1101 rules on ADMISSION; it says
    nothing about revoking one, and `enabled` is also an operator-set field. So a
    disqualified verdict leaves `enabled` exactly as it found it -- the source stops being
    collected because the gate requires QUALIFIED too, not because the app silently
    rewrote a column a person may have set by hand."""
    s = _session(tmp_path)
    src = _src(s, "operator-enabled.example", status=STATUS_QUALIFIED, enabled=True)

    evaluate_and_stamp(s, [src], {src.id: _EXTRACTION_FAIL}, now=NOW)
    s.commit()

    assert src.status == STATUS_DISQUALIFIED
    assert src.enabled is True
    assert _events(s) == []


def test_a_no_evidence_attempt_touches_neither_status_nor_enabled_nor_the_audit(tmp_path) -> None:
    """THE 2026-07-24 INVERSION CLASS, pinned at the gate Q1101 built on it.

    A source with literally no evidence is absent from the metrics dict, and an
    aggregation that reads a missing key as an empty list cannot tell 'examined and clean'
    from 'nothing to judge'. `log_no_evidence_attempts` is the path that case takes; if the
    flip ever leaked into it, a source would be admitted on zero verification and the audit
    row would assert a decision nobody made."""
    s = _session(tmp_path)
    src = _src(s, "silent.example", status=STATUS_UNQUALIFIED, enabled=False)

    n = log_no_evidence_attempts(s, [src], now=NOW)
    s.commit()

    assert n == 1
    assert src.status == STATUS_UNQUALIFIED
    assert src.enabled is False
    assert _events(s) == []


def test_re_stamping_a_source_that_is_ALREADY_COLLECTING_records_no_admission(tmp_path) -> None:
    """A re-check of a source collection already reaches is a qualified verdict and NOT an
    admission. Recording it would bury the real admissions under one no-op row per
    re-check, and `admitted` would stop answering 'how many new sources did this pass let
    in' on every pass after the first.

    Note the fixture: already-collecting means enabled AND qualified. The near-miss --
    enabled but NOT yet qualified -- is the test directly below, and it is an admission.
    """
    s = _session(tmp_path)
    src = _src(s, "already.example", status=STATUS_QUALIFIED, enabled=True)

    out = evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()

    assert out["qualified"] == 1
    assert out["admitted"] == 0, "a re-check of a collecting source was counted as an admission"
    assert _events(s) == []


def test_a_CATALOGUE_source_is_admitted_by_the_verdict_alone_and_IS_audited(tmp_path) -> None:
    """THE DEFECT AN ADVERSARIAL PASS FOUND, pinned. This is the ordinary case, not a
    corner: the shipped catalogue seeds sources `enabled: true, status: unqualified`, so
    the first qualification takes them from EXCLUDED to ACTIVELY SCRAPED without `enabled`
    ever moving.

    An earlier cut recorded a row only when `enabled` itself changed, so this -- the most
    common admission there is -- produced `admitted: 0` and no audit row, and the ruling's
    safety valve did not exist for the sources it matters most for. The unit is
    COLLECTABILITY, and this test is what says so.
    """
    s = _session(tmp_path)
    src = _catalogue_src(s, "catalogue.example")
    assert src.enabled is True and src.status == STATUS_UNQUALIFIED

    out = evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()

    assert out["admitted"] == 1, "the catalogue source's admission was not counted"
    (ev,) = _events(s)
    assert ev.prior_enabled is True, "the prior state must record that it was ALREADY enabled"
    assert ev.prior_status == STATUS_UNQUALIFIED

    # And the undo has to work for this shape too: it restores the STATUS, which is the
    # half that was doing the admitting.
    undo_admission(s, ev.id, now=NOW + timedelta(hours=1))
    assert src.enabled is True, "the undo disabled a source the operator had enabled"
    assert src.status == STATUS_UNQUALIFIED


def test_a_RE_ADMISSION_on_the_disqualification_ladder_is_audited(tmp_path) -> None:
    """The same defect's systemic form, and the ladder produces it as a matter of course.

    admit -> disqualify -> re-qualify. `enabled` stays True across the whole cycle (a
    disqualification does not revoke), so the RE-admission -- a genuine, unattended
    re-opening of collection -- was invisible under the old `enabled`-changed predicate.
    """
    s = _session(tmp_path)
    src = _src(s, "ladder.example", status=STATUS_UNQUALIFIED, enabled=False)

    evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()
    assert len(_events(s)) == 1

    evaluate_and_stamp(s, [src], {src.id: _EXTRACTION_FAIL}, now=NOW + timedelta(days=1))
    s.commit()
    assert src.status == STATUS_DISQUALIFIED
    assert src.enabled is True  # not revoked
    assert len(_events(s)) == 1, "a disqualification wrote an admission row"

    out = evaluate_and_stamp(s, [src], {}, now=NOW + timedelta(days=2))
    s.commit()

    assert out["admitted"] == 1, "the re-admission was not counted"
    evs = _events(s)
    assert len(evs) == 2, "the ladder's re-admission left no audit row"
    assert evs[1].prior_status == STATUS_DISQUALIFIED
    assert evs[1].prior_enabled is True


def test_the_audit_predicate_is_the_collection_gate_itself(tmp_path) -> None:
    """The two must not drift. `is_collectable` is the one authority both the audit and
    `select_sources` read, so this drives every state combination and asserts the helper
    agrees with what the SQL gate actually selects."""
    from src.catalog.qualification import is_collectable
    from src.scheduler.runner import select_sources
    from src.scheduler.settings import SchedulerSettings

    s = _session(tmp_path)
    combos = [
        (True, STATUS_QUALIFIED), (True, STATUS_UNQUALIFIED), (True, STATUS_DISQUALIFIED),
        (False, STATUS_QUALIFIED), (False, STATUS_UNQUALIFIED),
    ]
    for i, (en, st) in enumerate(combos):
        _src(s, f"combo{i}.example", status=st, enabled=en)
    picked = {x.domain for x in select_sources(s, SchedulerSettings())}
    for i, (en, st) in enumerate(combos):
        assert is_collectable(en, st) == (f"combo{i}.example" in picked), (
            f"is_collectable disagrees with the gate for enabled={en} status={st!r}"
        )
    # Anti-vacuity: the gate must actually select something and reject something, or the
    # agreement above is between two constants.
    assert 0 < len(picked) < len(combos)


def test_a_null_enabled_is_an_admission_and_is_restored_as_null(tmp_path) -> None:
    """`Source.enabled` is nullable and NULL means 'never set', which is a different fact
    from False. A NULL row IS admitted (it is not collecting), and the audit must store the
    NULL rather than coercing it to False -- otherwise the undo puts back a value the row
    never had.

    THE FIXTURE HAS TO WRITE THE NULL THE WAY THE DATABASE HOLDS IT. `Source.enabled`
    carries `default=True`, so constructing the row with `enabled=None` stores **True** --
    the recorded `Article.quarantined` trap, where a `None` fixture cannot reach the NULL
    branch at all and the test passes for a reason unrelated to its name. So the column is
    set to NULL by an explicit UPDATE and the NULL is ASSERTED before the subject of the
    test runs.
    """
    from sqlalchemy import text

    s = _session(tmp_path)
    src = _src(s, "never-set.example", status=STATUS_UNQUALIFIED, enabled=False)
    s.execute(text("UPDATE sources SET enabled = NULL WHERE id = :i"), {"i": src.id})
    s.commit()
    s.expire(src)
    assert src.enabled is None, "the fixture failed to produce the NULL it is about"

    out = evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()

    assert src.enabled is True
    assert out["admitted"] == 1
    (ev,) = _events(s)
    assert ev.prior_enabled is None, "a NULL enabled was stored as something else"

    undo_admission(s, ev.id, now=NOW + timedelta(minutes=1))
    assert src.enabled is None, "the undo invented a False where the row had never been set"


# --------------------------------------------------------------------------- #
#  The undo
# --------------------------------------------------------------------------- #
def test_the_undo_restores_BOTH_enabled_and_status(tmp_path) -> None:
    """Restoring only `enabled` would leave the source stamped `qualified` and disabled --
    a state the gate excludes, that the next pass has no reason to re-examine, and that no
    surface reports as reversed. The undo would look like it worked and strand the row."""
    s = _session(tmp_path)
    src = _src(s, "undo.example", status=STATUS_UNQUALIFIED, enabled=False)
    evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()
    (ev,) = _events(s)
    assert src.enabled is True and src.status == STATUS_QUALIFIED

    out = undo_admission(s, ev.id, now=NOW + timedelta(hours=1))

    assert out["undone"] is True
    assert src.enabled is False
    assert src.status == STATUS_UNQUALIFIED, "the undo left a 'qualified' stamp behind"
    # The stamp columns follow the status: a cleared status beside a live `qualified_at` is
    # two answers to one question.
    assert src.qualified_at is None
    assert src.qualification_criteria_version is None
    assert ev.undone_at is not None, "the audit row was not stamped"


def test_the_undo_is_append_only_and_refuses_a_second_reversal_by_name(tmp_path) -> None:
    """A reversed decision stays in the record -- a deleted one reads as a decision never
    made. And a second undo is REFUSED rather than silently re-applying a stale prior
    state over whatever the row holds now."""
    s = _session(tmp_path)
    src = _src(s, "twice.example")
    evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()
    (ev,) = _events(s)
    undo_admission(s, ev.id, now=NOW + timedelta(hours=1))

    # The operator re-enables it by hand afterwards. A second undo must not undo THAT.
    src.enabled = True
    s.commit()

    with pytest.raises(AdmissionUndoRefused, match="already undone"):
        undo_admission(s, ev.id, now=NOW + timedelta(hours=2))
    assert src.enabled is True, "a second undo overwrote a state the operator set"
    assert len(_events(s)) == 1, "the audit row was deleted rather than stamped"


def test_an_unknown_event_is_refused_by_name(tmp_path) -> None:
    s = _session(tmp_path)
    with pytest.raises(AdmissionUndoRefused, match="no such admission event"):
        undo_admission(s, 424242, now=NOW)


def test_undoing_an_OLDER_admission_while_a_LATER_one_stands_is_refused(tmp_path) -> None:
    """Found by an adversarial pass and live-reproduced before it was fixed.

    A source can be admitted twice (admit, the operator disables it, a later pass admits
    it again). Each event stores the state IT replaced, so undoing the OLDER one writes a
    prior state the newer admission has already superseded -- the source silently takes a
    value from two decisions ago while the newer event still renders as reversible,
    inviting a second click that revives a status the operator had deliberately cleared.

    The refusal names the way out rather than reordering silently: which admission an
    operator meant to reverse is their decision.
    """
    s = _session(tmp_path)
    src = _src(s, "order.example", status=STATUS_UNQUALIFIED, enabled=False)
    evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()
    src.enabled = False  # the operator disables it by hand, for their own reason
    s.commit()
    evaluate_and_stamp(s, [src], {}, now=NOW + timedelta(days=1))
    s.commit()
    older, newer = _events(s)
    assert older.id != newer.id and newer.undone_at is None

    with pytest.raises(AdmissionUndoRefused, match="later admission"):
        undo_admission(s, older.id, now=NOW + timedelta(days=2))
    # Nothing was written on the way to the refusal.
    assert src.enabled is True and src.status == STATUS_QUALIFIED
    assert older.undone_at is None

    # The way out the message names WORKS, and afterwards the older one is undoable --
    # otherwise the refusal would be a dead end rather than an ordering rule.
    undo_admission(s, newer.id, now=NOW + timedelta(days=3))
    undo_admission(s, older.id, now=NOW + timedelta(days=4))
    assert src.enabled is False and src.status == STATUS_UNQUALIFIED


def test_the_audit_publishes_what_it_CANNOT_account_for(tmp_path) -> None:
    """The audit records admissions made by JUDGING. A source can also be collecting
    because it came stamped in the shipped catalogue, carried an inherited stamp, or
    arrived in a restored backup -- none of which is a judgement made here.

    A panel claiming 'every admission' while three other routes exist would be making a
    claim its own table cannot support, so the DIFFERENCE is published. A gap is published
    as a gap.
    """
    s = _session(tmp_path)
    judged = _src(s, "judged.example", status=STATUS_UNQUALIFIED, enabled=False)
    evaluate_and_stamp(s, [judged], {}, now=NOW)
    s.commit()
    # A source that arrived already collecting, by a route with no admission row.
    _src(s, "shipped.example", status=STATUS_QUALIFIED, enabled=True)

    out = admission_audit(s, limit=50)

    assert out["collecting"] == 2
    assert out["accounted_for"] == 1
    assert out["unaccounted"] == 1, (
        "the audit claimed to account for a source it has no record of admitting"
    )
    assert out["coverage_note"], "the audit published no coverage note"


def test_an_undone_admission_stops_counting_as_accounted_for(tmp_path) -> None:
    """Negative-space twin for the disclosure above: an undone event is not an account of
    why a source is collecting, so if the operator re-enables the source by hand it must
    show up as unaccounted rather than silently crediting the reversed decision."""
    s = _session(tmp_path)
    src = _src(s, "reversed.example", status=STATUS_UNQUALIFIED, enabled=False)
    evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()
    assert admission_audit(s, limit=50)["accounted_for"] == 1

    undo_admission(s, _events(s)[0].id, now=NOW + timedelta(hours=1))
    src.enabled = True
    src.status = STATUS_QUALIFIED
    s.commit()

    out = admission_audit(s, limit=50)
    assert out["collecting"] == 1
    assert out["accounted_for"] == 0
    assert out["unaccounted"] == 1


def test_a_verdict_flipped_then_undone_then_re_judged_admits_again_and_records_twice(
    tmp_path,
) -> None:
    """An undo reverses THIS instance's decision; it is not a disqualification. So a later
    pass may admit the source again, and that is a SECOND admission with its own audit row
    -- not an amendment to the first, whose own prior state must stay exactly as recorded."""
    s = _session(tmp_path)
    src = _src(s, "again.example", status=STATUS_UNQUALIFIED, enabled=False)

    evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()
    first = _events(s)[0]
    undo_admission(s, first.id, now=NOW + timedelta(hours=1))

    evaluate_and_stamp(s, [src], {}, now=NOW + timedelta(days=1))
    s.commit()

    evs = _events(s)
    assert len(evs) == 2
    assert evs[0].undone_at is not None and evs[1].undone_at is None
    assert evs[0].prior_status == STATUS_UNQUALIFIED
    assert evs[1].prior_status == STATUS_UNQUALIFIED
    assert src.enabled is True


def test_undoing_an_admission_a_LATER_VERDICT_replaced_is_REFUSED_by_name(tmp_path) -> None:
    """Admit, then a later pass DISQUALIFIES, then the operator undoes the admission.

    Found by the skeptic pass Q1101's acceptance asks for, and REPRODUCED before it was
    believed. The earlier cut allowed this and restored ``prior_status="unqualified"``
    over a ``disqualified`` the engine had reached on its own evidence -- so a source the
    app had judged and REFUSED went back to reading never-judged. Measured on the real
    selectors, that is not a cosmetic column rewrite: ``select_due_disqualified`` holds a
    disqualified source behind its 1 -> 2 -> 4 -> 6 month ladder (not due at +0d or +20d,
    due at +40d), while ``select_unqualified`` returns it the SAME DAY with no ladder at
    all. The recorded laundering direction, through a path that lesson never touched.

    By this point the admission is not in effect anyway -- the source is not collecting --
    so refusing takes nothing away and cannot erase a verdict.
    """
    s = _session(tmp_path)
    src = _src(s, "later-bad.example", status=STATUS_UNQUALIFIED, enabled=False)
    evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()
    (ev,) = _events(s)

    evaluate_and_stamp(s, [src], {src.id: _EXTRACTION_FAIL}, now=NOW + timedelta(days=1))
    s.commit()
    assert src.status == STATUS_DISQUALIFIED
    assert src.enabled is True  # the disqualification does not revoke, per the mirror above

    with pytest.raises(AdmissionUndoRefused) as excinfo:
        undo_admission(s, ev.id, now=NOW + timedelta(days=2))
    assert "later verdict" in str(excinfo.value)

    # THE VERDICT SURVIVES, which is the whole point -- and so does the audit row, which
    # is append-only and must not read as undone by a refusal.
    assert src.status == STATUS_DISQUALIFIED
    assert src.enabled is True
    assert _events(s)[0].undone_at is None
    # And it is NOT back in the un-laddered trial queue.
    assert select_unqualified(s, limit=10) == []


def test_the_later_verdict_refusal_does_NOT_fire_while_the_ADMISSION_STILL_STANDS(
    tmp_path,
) -> None:
    """THE NEGATIVE-SPACE TWIN, and the one that makes the guard a guard rather than a
    blanket refusal: an operator who merely turns a still-qualified source OFF has not
    replaced the verdict, so their undo must still work. A fix that refused here would be
    the same defect pointing the other way -- conservative-looking, and it would take the
    safety valve away in the ordinary case."""
    s = _session(tmp_path)
    src = _src(s, "still-good.example", status=STATUS_UNQUALIFIED, enabled=False)
    evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()
    (ev,) = _events(s)

    src.enabled = False           # the operator's own hand, no new verdict
    s.commit()
    assert src.status == STATUS_QUALIFIED

    out = undo_admission(s, ev.id, now=NOW + timedelta(days=1))

    assert out["undone"] is True
    assert src.status == STATUS_UNQUALIFIED
    assert src.enabled is False
    assert _events(s)[0].undone_at is not None


def test_a_refusal_that_says_UNDO_THAT_ONE_FIRST_always_points_at_a_REVERSIBLE_row(
    tmp_path,
) -> None:
    """THE ORDER of the two refusals, pinned -- found by the skeptic pass and reproduced
    before it was believed.

    ``later-admission-in-effect`` does not merely refuse, it gives ADVICE: *undo that one
    first*. Advice that leads to a second refusal is a dead end wearing the costume of a
    way out. With the guards in the other order, a source carrying TWO standing admissions
    AND a later disqualification answered ``later-admission-in-effect`` on the older row
    and ``later-verdict-in-effect`` on the row it pointed at -- so an operator following
    the instruction hit a second refusal and NO row for that source could be reversed at
    all, while the panel drew both as merely "blocked, see the other one".

    Reading the source's CURRENT state first makes the advice true by construction, and
    that is the property this test exists to keep: a row is only ever told to defer to a
    newer admission while the source is still qualified, which is exactly when that newer
    admission is itself reversible.
    """
    s = _session(tmp_path)
    # TWO standing admissions (admit, the operator disables it, a later pass admits it
    # again) -- the shape the older-admission guard was written for...
    doomed = _src(s, "advice-dead-end.example", status=STATUS_UNQUALIFIED, enabled=False)
    evaluate_and_stamp(s, [doomed], {}, now=NOW)
    s.commit()
    doomed.enabled = False
    s.commit()
    evaluate_and_stamp(s, [doomed], {}, now=NOW + timedelta(days=1))
    s.commit()
    # ...and THEN the later verdict, which writes no admission row of its own.
    evaluate_and_stamp(s, [doomed], {doomed.id: _EXTRACTION_FAIL}, now=NOW + timedelta(days=2))
    s.commit()
    assert doomed.status == STATUS_DISQUALIFIED
    assert len(_events(s)) == 2, "the fixture needs both admissions standing"

    # A second source, still qualified, carrying the same two-admission shape: the case
    # the older-admission refusal is FOR, so this test cannot pass by never firing it.
    ok = _src(s, "advice-works.example", status=STATUS_UNQUALIFIED, enabled=False)
    evaluate_and_stamp(s, [ok], {}, now=NOW)
    s.commit()
    ok.enabled = False
    s.commit()
    evaluate_and_stamp(s, [ok], {}, now=NOW + timedelta(days=1))
    s.commit()

    rows = admission_audit(s, limit=25)["events"]
    by_source: dict[int, list[dict]] = {}
    for row in rows:
        by_source.setdefault(int(row["source_id"]), []).append(row)

    # THE INVARIANT, stated over every source in the audit rather than over this fixture:
    # if any row is told to defer to a newer admission, SOME row for that source must
    # actually be reversible, or the advice cannot be followed.
    deferring = [r for r in rows if r["blocked_by"] == UNDO_LATER_ADMISSION]
    assert deferring, "anti-vacuity: no row deferred, so the invariant was never tested"
    for row in deferring:
        siblings = by_source[int(row["source_id"])]
        assert any(sib["reversible"] for sib in siblings), (
            f"{row['domain']} was told to undo a later admission first, but no admission "
            f"of it is reversible: {[(x['id'], x['blocked_by']) for x in siblings]}"
        )

    # And the two fixtures say the two different things, so the invariant above is holding
    # because of the ORDER and not because one branch stopped happening.
    doomed_rows = by_source[int(doomed.id)]
    assert {r["blocked_by"] for r in doomed_rows} == {UNDO_LATER_VERDICT}, (
        "a disqualified source's rows must ALL name the verdict -- naming each other "
        "sends the operator in a circle"
    )
    ok_rows = sorted(by_source[int(ok.id)], key=lambda r: r["id"])
    assert [r["blocked_by"] for r in ok_rows] == [UNDO_LATER_ADMISSION, None]

    # The advice, followed for real: the row it names really does undo, and then the older
    # one does too. (The doomed source's rows stay refused, which is the point -- there is
    # nothing left for an undo to take back once the engine has refused the source.)
    undo_admission(s, ok_rows[1]["id"], now=NOW + timedelta(days=3))
    undo_admission(s, ok_rows[0]["id"], now=NOW + timedelta(days=4))
    with pytest.raises(AdmissionUndoRefused, match="later verdict"):
        undo_admission(s, doomed_rows[0]["id"], now=NOW + timedelta(days=3))


def test_the_audit_says_which_rows_the_ENDPOINT_WOULD_REFUSE(tmp_path) -> None:
    """A button that renders claims its capability, so the panel must not offer an Undo
    the handler will always refuse. Both read ONE predicate, so they cannot disagree about
    a row: the audit publishes ``reversible`` + the ``blocked_by`` TOKEN the client keys,
    and every blocked row here is one ``undo_admission`` really does refuse."""
    s = _session(tmp_path)
    live = _src(s, "live.example", status=STATUS_UNQUALIFIED, enabled=False)
    gone = _src(s, "gone-verdict.example", status=STATUS_UNQUALIFIED, enabled=False)
    evaluate_and_stamp(s, [live, gone], {}, now=NOW)
    s.commit()
    evaluate_and_stamp(s, [gone], {gone.id: _EXTRACTION_FAIL}, now=NOW + timedelta(days=1))
    s.commit()

    by_domain = {e["domain"]: e for e in admission_audit(s, limit=25)["events"]}

    assert by_domain["live.example"]["reversible"] is True
    assert by_domain["live.example"]["blocked_by"] is None
    assert by_domain["gone-verdict.example"]["reversible"] is False
    assert by_domain["gone-verdict.example"]["blocked_by"] == UNDO_LATER_VERDICT

    # ANTI-VACUITY, both ways: the published verdict is the endpoint's own answer, not a
    # second opinion that happens to agree today.
    undo_admission(s, by_domain["live.example"]["id"], now=NOW + timedelta(days=2))
    with pytest.raises(AdmissionUndoRefused):
        undo_admission(s, by_domain["gone-verdict.example"]["id"], now=NOW + timedelta(days=2))


def test_an_undone_row_is_not_reversible_and_says_so_with_its_own_token(tmp_path) -> None:
    """``undone`` and ``reversible`` are different questions and must not collapse: an
    undone row is not reversible either, and the reason it gives is its OWN, so the panel
    never has to infer one state from the other."""
    s = _session(tmp_path)
    src = _src(s, "twice.example", status=STATUS_UNQUALIFIED, enabled=False)
    evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()
    (ev,) = _events(s)
    undo_admission(s, ev.id, now=NOW + timedelta(days=1))

    (row,) = admission_audit(s, limit=25)["events"]
    assert row["undone"] is True
    assert row["reversible"] is False
    assert row["blocked_by"] == UNDO_ALREADY_UNDONE


def test_every_blocked_by_token_the_audit_can_publish_is_keyed_in_every_locale(
    tmp_path,
) -> None:
    """The tokens are a CLOSED vocabulary the renderer keys, so a token with no key is a
    raw identifier on screen -- the exact defect a Chromium walk in ar caught for the
    status vocabulary. Read the tokens from the MODULE, never a retyped list, so a new one
    reddens here instead of shipping untranslated."""
    import json
    from pathlib import Path

    from src.catalog import qualification as q

    tokens = {
        q.UNDO_ALREADY_UNDONE, q.UNDO_LATER_ADMISSION,
        q.UNDO_LATER_VERDICT, q.UNDO_SOURCE_GONE,
    }
    assert len(tokens) == 4, "the tokens must stay distinct -- two reasons, two words"
    js = Path("src/static/app-ai-tools.js").read_text(encoding="utf-8")
    labels = {}
    for tok in tokens:
        # the renderer's own map: "<token>": t("<label>")
        i = js.index(f'"{tok}": t("')
        start = i + len(f'"{tok}": t("')
        labels[tok] = js[start : js.index('")', start)]
    locales = Path("src/static/locales")
    for lang_file in sorted(locales.glob("*.json")):
        data = json.loads(lang_file.read_bytes())
        for tok, label in labels.items():
            assert label in data, f"{lang_file.name} is missing {label!r} (token {tok})"
            assert str(data[label]).strip(), f"{lang_file.name}: {label!r} is empty"


# --------------------------------------------------------------------------- #
#  The audit view
# --------------------------------------------------------------------------- #
def test_the_audit_lists_newest_first_and_bounds_the_LIST_not_the_COUNT(tmp_path) -> None:
    """Anti-capping: a displayed figure is never secretly a cap. `limit` bounds the list;
    `total` is the real number of admissions."""
    s = _session(tmp_path)
    for i in range(5):
        src = _src(s, f"s{i}.example")
        evaluate_and_stamp(s, [src], {}, now=NOW + timedelta(minutes=i))
        s.commit()

    out = admission_audit(s, limit=2)

    assert out["total"] == 5, "the total was bounded by the list limit"
    assert out["shown"] == 2
    assert [e["domain"] for e in out["events"]] == ["s4.example", "s3.example"]
    assert out["events"][0]["prior_status"] == STATUS_UNQUALIFIED
    assert out["method"] and out["caveat"], "the audit view published no method or caveat"


def test_the_audit_can_exclude_undone_events_and_still_counts_them_separately(tmp_path) -> None:
    """'Undone' and 'never happened' are different facts, so an undone event is filterable
    out of the list and still counted -- never dropped from both."""
    s = _session(tmp_path)
    a = _src(s, "a.example")
    b = _src(s, "b.example")
    evaluate_and_stamp(s, [a], {}, now=NOW)
    s.commit()
    evaluate_and_stamp(s, [b], {}, now=NOW + timedelta(minutes=1))
    s.commit()
    undo_admission(s, _events(s)[0].id, now=NOW + timedelta(hours=1))

    live = admission_audit(s, limit=50, include_undone=False)
    assert live["total"] == 1
    assert [e["domain"] for e in live["events"]] == ["b.example"]
    assert live["undone_total"] == 1, "the undone event vanished from the accounting entirely"

    everything = admission_audit(s, limit=50, include_undone=True)
    assert everything["total"] == 2
    assert sum(1 for e in everything["events"] if e["undone"]) == 1


def test_the_audit_is_empty_rather_than_zeroed_on_an_instance_that_admitted_nothing(
    tmp_path,
) -> None:
    """An honest empty state. A zeroed row would read as 'an admission with no data'."""
    s = _session(tmp_path)
    out = admission_audit(s, limit=50)
    assert out["events"] == []
    assert out["total"] == 0 and out["undone_total"] == 0


# --------------------------------------------------------------------------- #
#  The gate the flip feeds
# --------------------------------------------------------------------------- #
def test_the_admitted_source_is_what_collection_then_selects(tmp_path) -> None:
    """End to end, because the flip is only worth anything if the collection gate agrees:
    an admitted source is selected, and the same source with its admission undone is not.

    This is the test that fails if `select_sources` and `evaluate_and_stamp` ever disagree
    about what admission means -- which is the whole hazard of moving the decision from the
    query to the verdict.
    """
    from src.scheduler.runner import select_sources
    from src.scheduler.settings import SchedulerSettings

    s = _session(tmp_path)
    src = _src(s, "collectme.example", status=STATUS_UNQUALIFIED, enabled=False)
    assert [x.domain for x in select_sources(s, SchedulerSettings())] == []

    evaluate_and_stamp(s, [src], {}, now=NOW)
    s.commit()
    assert [x.domain for x in select_sources(s, SchedulerSettings())] == ["collectme.example"]

    undo_admission(s, _events(s)[0].id, now=NOW + timedelta(hours=1))
    assert [x.domain for x in select_sources(s, SchedulerSettings())] == []


def test_utc_now_is_not_baked_into_the_module(tmp_path) -> None:
    """The audit's timestamps come from the caller's `now`, so a fixture can age a record
    deliberately. Guards against the recorded 'a second-precision clock makes a re-stamp
    invisible to a same-second fixture' trap by proving the module reads its argument."""
    s = _session(tmp_path)
    src = _src(s, "clock.example")
    stamp = datetime(2020, 1, 1, 0, 0, 0)
    evaluate_and_stamp(s, [src], {}, now=stamp)
    s.commit()
    (ev,) = _events(s)
    assert ev.occurred_at == stamp
    assert ev.occurred_at.year != datetime.now(UTC).year, (
        "the event took its own clock instead of the caller's"
    )
