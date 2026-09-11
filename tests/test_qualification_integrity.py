"""The 0.4 Row A closing clause, as something a reader can re-open.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row A closes on a committed import at scale "and a spot-check confirms a previously-
disqualified source is still disqualified afterwards" -- because "a pass that only counts
``qualified`` rows cannot see the inversion this row exists to catch". Row E adds that on
an instance with tens of thousands of sources, a spot-check done by hand is the shape of
check that gets reported as done without being done.

THE DEFECT IS REPRODUCED FIRST, in ``test_the_2026_07_24_inversion_is_what_this_catches``:
a source judged ``disqualified``, whose live status is then set to ``unqualified`` exactly
as the dropped stamp columns' ``server_default`` would have set it. That is what the check
has to see, and the reason it is worth having is that at every layer above the INSERT it
looks like nothing at all -- a plausible legal value, no NULL, no error.

The negative space is asserted throughout, because each direction has a way of being
uselessly wrong: a healthy corpus must report NOTHING (a check that always finds something
is not a check), a corpus with no attempt history must refuse to call itself clean (zero
findings over zero evidence is not a pass), a legitimate re-qualification must not read as
an inversion, and an adopted verdict -- which writes an ``inherited`` row, never a
judgement -- must not be mistaken for one either.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.catalog.qualification import (
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_INHERITED,
    VERDICT_NO_EVIDENCE,
)
from src.catalog.qualification_integrity import (
    SCHEMA,
    qualification_integrity_report,
    repair_inversions,
)
from src.database.models import Base, Source, SourceQualificationAttempt

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _source(session: Session, domain: str, status: str) -> Source:
    src = Source(name=domain, domain=domain, status=status)
    session.add(src)
    session.flush()
    return src


def _attempt(session: Session, src: Source, verdict: str, *, at: datetime, version: str = "v1") -> None:
    session.add(SourceQualificationAttempt(
        source_id=src.id, attempted_at=at, verdict=verdict, criteria_version=version,
    ))
    session.flush()


def _judged(session: Session, domain: str, verdict: str, *, at: datetime | None = None) -> Source:
    """A source judged the way ``evaluate_and_stamp`` judges one: the attempt row and the
    live status written together, which is exactly the invariant this check reads."""
    src = _source(session, domain, verdict)
    _attempt(session, src, verdict, at=at or NOW)
    return src


# --------------------------------------------------------------------------- #
# The defect, reproduced
# --------------------------------------------------------------------------- #
def test_the_2026_07_24_inversion_is_what_this_catches(session: Session) -> None:
    """A source judged disqualified, whose live status is the dropped stamp's default."""
    src = _judged(session, "known-bad.example", STATUS_DISQUALIFIED)
    # What the merge's missing column allowlist did: Source.status carries
    # server_default='unqualified', so the row arrives looking never-judged.
    src.status = STATUS_UNQUALIFIED
    session.flush()

    out = qualification_integrity_report(session)

    assert out["verdict"] == "inversions-found"
    assert out["laundered_total"] == 1, out
    assert out["demoted_total"] == 0
    named = [r["domain"] for r in out["laundered"]]
    assert named == ["known-bad.example"], "the finding must NAME the source, not only count it"
    row = out["laundered"][0]
    assert row["live_status"] == STATUS_UNQUALIFIED
    assert row["last_judged"] == STATUS_DISQUALIFIED
    assert row["judged_at"] is not None and row["criteria_version"] == "v1"
    assert "previously disqualified" in out["reason"]


def test_the_other_direction_is_a_separate_fact(session: Session) -> None:
    """Judged qualified, no longer qualified: the same stamp loss, a different cost.

    Collapsing the two into one "inconsistent" count would tell a reader neither which
    sources are back in the trial queue nor which are starved out of collection.
    """
    src = _judged(session, "good.example", STATUS_QUALIFIED)
    src.status = STATUS_UNQUALIFIED
    session.flush()

    out = qualification_integrity_report(session)
    assert out["laundered_total"] == 0, "a demotion is not a laundering"
    assert out["demoted_total"] == 1
    assert [r["domain"] for r in out["demoted"]] == ["good.example"]


def test_both_directions_at_once_stay_apart(session: Session) -> None:
    bad = _judged(session, "bad.example", STATUS_DISQUALIFIED)
    good = _judged(session, "good.example", STATUS_QUALIFIED)
    bad.status = STATUS_QUALIFIED   # the dangerous one: back in collection
    good.status = STATUS_UNQUALIFIED
    session.flush()

    out = qualification_integrity_report(session)
    assert out["inversions_total"] == 2
    assert out["laundered_total"] == 1 and out["demoted_total"] == 1
    assert out["consistent"] == 0


# --------------------------------------------------------------------------- #
# The negative space -- each of these is a way the check could be uselessly wrong
# --------------------------------------------------------------------------- #
def test_a_healthy_corpus_reports_nothing(session: Session) -> None:
    """A check that finds something on a sound corpus is not a check."""
    _judged(session, "a.example", STATUS_QUALIFIED)
    _judged(session, "b.example", STATUS_DISQUALIFIED)
    _judged(session, "c.example", STATUS_QUALIFIED)

    out = qualification_integrity_report(session)
    assert out["verdict"] == "consistent"
    assert out["inversions_total"] == 0
    assert out["laundered"] == [] and out["demoted"] == []
    assert out["consistent"] == 3
    assert out["checked"]["with_judging_attempt"] == 3


def test_no_judgements_at_all_is_not_a_pass(session: Session) -> None:
    """Zero findings over zero evidence is the absence of the measurement, not a clean
    bill of health -- and the denominator is what says which one a reader is holding."""
    _source(session, "never-judged.example", STATUS_UNQUALIFIED)
    _source(session, "also.example", STATUS_UNQUALIFIED)

    out = qualification_integrity_report(session)
    assert out["verdict"] == "not-measurable-here"
    assert out["inversions_total"] == 0
    assert out["checked"]["with_judging_attempt"] == 0
    assert out["checked"]["without_judging_attempt"] == 2
    assert "not a pass" in out["reason"]


def test_a_legitimate_requalification_is_not_an_inversion(session: Session) -> None:
    """The ladder gives a disqualified source a second chance. When it passes, the NEWEST
    judging attempt is the qualified one -- reading the oldest, or any disqualified row,
    would condemn every source the re-qualification ruling exists to rehabilitate."""
    src = _source(session, "recovered.example", STATUS_QUALIFIED)
    _attempt(session, src, STATUS_DISQUALIFIED, at=NOW - timedelta(days=200))
    _attempt(session, src, STATUS_DISQUALIFIED, at=NOW - timedelta(days=90))
    _attempt(session, src, STATUS_QUALIFIED, at=NOW)

    out = qualification_integrity_report(session)
    assert out["verdict"] == "consistent", out["laundered"]
    assert out["inversions_total"] == 0


def test_no_evidence_and_inherited_rows_are_not_judgements(session: Session) -> None:
    """``no_evidence`` (the livelock fix) and ``inherited`` (adopting an overlay or backup
    stamp) both write an attempt row and NEITHER is this instance judging anything. Reading
    them as verdicts would invent an inversion out of an adoption."""
    src = _source(session, "adopted.example", STATUS_QUALIFIED)
    _attempt(session, src, VERDICT_INHERITED, at=NOW)
    _attempt(session, src, VERDICT_NO_EVIDENCE, at=NOW + timedelta(hours=1))

    out = qualification_integrity_report(session)
    assert out["verdict"] == "not-measurable-here", (
        "an adopted stamp is not a local judgement -- there is nothing here to check"
    )
    assert out["checked"]["with_judging_attempt"] == 0


def test_an_inherited_row_after_a_judgement_does_not_hide_the_inversion(session: Session) -> None:
    """The inverse of the test above, and the one that matters: a later adoption row must
    not be read as the newest verdict and quietly clear a real disqualification."""
    src = _judged(session, "known-bad.example", STATUS_DISQUALIFIED)
    _attempt(session, src, VERDICT_INHERITED, at=NOW + timedelta(days=1))
    src.status = STATUS_UNQUALIFIED
    session.flush()

    out = qualification_integrity_report(session)
    assert out["laundered_total"] == 1, "an inherited row is not a judgement and must not mask one"


def test_a_same_timestamp_tie_is_broken_by_append_order(session: Session) -> None:
    """A batch stamps every source with the same ``now``, so two judging attempts for one
    source can share a timestamp. The grouped MAX() surfaces both; the exact re-read
    decides. Reporting on whichever row the join returned would be a coin flip.
    """
    src = _source(session, "tied.example", STATUS_QUALIFIED)
    _attempt(session, src, STATUS_DISQUALIFIED, at=NOW)
    _attempt(session, src, STATUS_QUALIFIED, at=NOW)  # appended later: the real newest

    out = qualification_integrity_report(session)
    assert out["verdict"] == "consistent", out["laundered"]
    assert out["ties_resolved_by_append_order"] == 1, (
        "a tie the grouped query surfaced and the re-read cleared is counted, never "
        "dropped in silence"
    )


# --------------------------------------------------------------------------- #
# Naming the sources verified (Row E)
# --------------------------------------------------------------------------- #
def test_the_examined_disqualified_sources_are_named(session: Session) -> None:
    """Row E asks the tooling to name the sources verified; a count alone names nobody."""
    for i in range(3):
        _judged(session, f"bad{i}.example", STATUS_DISQUALIFIED)
    _judged(session, "fine.example", STATUS_QUALIFIED)
    # Disqualified but never JUDGED here (an adopted overlay verdict): outside the
    # population this clause is about, because there is no local verdict to have lost.
    adopted = _source(session, "adopted-bad.example", STATUS_DISQUALIFIED)
    _attempt(session, adopted, VERDICT_INHERITED, at=NOW)

    out = qualification_integrity_report(session)
    chk = out["checked"]
    assert chk["currently_disqualified_and_judged"] == 3
    assert chk["verified_disqualified_sample"] == [
        "bad0.example", "bad1.example", "bad2.example",
    ]
    assert "adopted-bad.example" not in chk["verified_disqualified_sample"]


def test_the_named_sample_is_bounded_and_the_total_is_not(session: Session) -> None:
    """The truncation is stated, never silent: the count is exact whatever the list shows."""
    for i in range(9):
        _judged(session, f"bad{i}.example", STATUS_DISQUALIFIED)

    out = qualification_integrity_report(session, verified_sample=4)
    chk = out["checked"]
    assert chk["currently_disqualified_and_judged"] == 9, "the total is never the sample size"
    assert len(chk["verified_disqualified_sample"]) == 4
    assert chk["verified_disqualified_sample_cap"] == 4


def test_the_payload_names_no_score(session: Session) -> None:
    """The house no-score walkers ban score/ranking/rating/grade as key SUBSTRINGS."""
    _judged(session, "a.example", STATUS_QUALIFIED)
    out = qualification_integrity_report(session)

    banned = ("score", "ranking", "rating", "grade")
    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                low = str(k).lower()
                assert not any(b in low for b in banned), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
    walk(out)


def test_the_bundle_member_carries_the_finding_not_a_stub(session: Session) -> None:
    """Row E asks for TOOLING, and tooling nobody can reach is the dead-end shape. The
    check therefore rides the all-diagnostics bundle -- and this drives the REAL member
    generator, not the route signature.

    The distinction matters here for a reason this repo has already paid for once: called
    directly rather than through FastAPI, an unresolved ``Depends`` is a sentinel OBJECT
    and ``Query(False)`` is TRUTHY, and the bundle's own ``_safe()`` would swallow the
    resulting failure into an error stub -- a degraded member in every export, with
    nothing saying so. So the assertion is on a VALUE only the working path can produce:
    a seeded inversion, NAMED, arriving through the bundle."""
    import json as _json

    from src.api import diagnostics as d

    src = _judged(session, "known-bad.example", STATUS_DISQUALIFIED)
    src.status = STATUS_UNQUALIFIED
    session.flush()

    members = dict(d._all_diagnostics_members(session))
    assert "qualification-integrity.json" in members, "the member must be in the bundle"
    body = _json.loads(bytes(members["qualification-integrity.json"]().body))

    assert body["schema"] == SCHEMA
    assert body["verdict"] == "inversions-found"
    assert [r["domain"] for r in body["laundered"]] == ["known-bad.example"]


# --------------------------------------------------------------------------- #
# repair_inversions -- the operator-triggered reconciliation
# --------------------------------------------------------------------------- #

def test_repair_inversions_dry_run_changes_nothing_but_reports_accurately(session: Session) -> None:
    bad = _judged(session, "bad.example", STATUS_DISQUALIFIED)
    good = _judged(session, "good.example", STATUS_QUALIFIED)
    bad.status = STATUS_QUALIFIED    # laundered
    good.status = STATUS_UNQUALIFIED  # demoted
    session.flush()

    out = repair_inversions(session, dry_run=True)

    assert out["dry_run"] is True
    assert out["applied"] is False
    assert out["reconciled_total"] == 2
    assert out["restored_to_disqualified_total"] == 1
    assert [r["domain"] for r in out["restored_to_disqualified"]] == ["bad.example"]
    assert out["restored_to_qualified_total"] == 1
    assert [r["domain"] for r in out["restored_to_qualified"]] == ["good.example"]

    # Nothing was actually written: re-fetch and confirm the inverted status stands,
    # and the integrity report still sees both inversions.
    session.expire_all()
    assert session.get(Source, bad.id).status == STATUS_QUALIFIED
    assert session.get(Source, good.id).status == STATUS_UNQUALIFIED
    still = qualification_integrity_report(session)
    assert still["inversions_total"] == 2


def test_repair_inversions_real_run_reconciles_both_directions(session: Session) -> None:
    bad = _judged(session, "bad.example", STATUS_DISQUALIFIED)
    good = _judged(session, "good.example", STATUS_QUALIFIED)
    bad.status = STATUS_QUALIFIED
    good.status = STATUS_UNQUALIFIED
    session.flush()

    out = repair_inversions(session, dry_run=False)
    session.commit()

    assert out["applied"] is True
    assert out["reconciled_total"] == 2

    session.expire_all()
    fixed_bad = session.get(Source, bad.id)
    fixed_good = session.get(Source, good.id)
    assert fixed_bad.status == STATUS_DISQUALIFIED
    assert fixed_bad.qualified_at is None
    assert fixed_good.status == STATUS_QUALIFIED
    assert fixed_good.qualified_at is not None

    # And the integrity report now sees a clean corpus.
    clean = qualification_integrity_report(session)
    assert clean["verdict"] == "consistent"
    assert clean["inversions_total"] == 0


def test_repair_inversions_stamps_the_attempts_own_date_not_now(session: Session) -> None:
    """Restoring a July verdict must not date it today -- mirrors evaluate_and_stamp's
    own rule and defeats nothing about the re-verification clock."""
    old = NOW - timedelta(days=51)
    src = _source(session, "wire.example", STATUS_QUALIFIED)
    _attempt(session, src, STATUS_QUALIFIED, at=old, version="oo-source-qualification-1")
    src.status = STATUS_UNQUALIFIED
    session.flush()

    repair_inversions(session, dry_run=False)
    session.commit()
    session.expire_all()

    fixed = session.get(Source, src.id)
    assert fixed.status == STATUS_QUALIFIED
    # SQLite round-trips a DateTime as tz-naive; compare on the naive wall-clock value
    # (the point under test is the DATE -- the attempt's own, never CURRENT_TIMESTAMP --
    # not the tzinfo SQLAlchemy attaches on the way out).
    assert fixed.qualified_at.replace(tzinfo=UTC) == old, (
        "the ATTEMPT's own date, never CURRENT_TIMESTAMP"
    )
    assert fixed.qualification_criteria_version == "oo-source-qualification-1"


def test_repair_inversions_writes_no_new_attempt_row(session: Session) -> None:
    """This reconciles existing history -- it must never itself write a judgement."""
    bad = _judged(session, "bad.example", STATUS_DISQUALIFIED)
    bad.status = STATUS_QUALIFIED
    session.flush()
    before = session.query(SourceQualificationAttempt).count()

    repair_inversions(session, dry_run=False)
    session.commit()

    after = session.query(SourceQualificationAttempt).count()
    assert after == before, "repair_inversions must write no new attempt row"


def test_repair_inversions_a_healthy_corpus_reconciles_nothing(session: Session) -> None:
    _judged(session, "a.example", STATUS_QUALIFIED)
    _judged(session, "b.example", STATUS_DISQUALIFIED)

    out = repair_inversions(session, dry_run=False)
    assert out["reconciled_total"] == 0
    assert out["restored_to_qualified"] == [] and out["restored_to_disqualified"] == []


def test_repair_inversions_reuses_the_same_join_as_the_report(session: Session) -> None:
    """A legitimate re-qualification (newest attempt wins) must not be repaired -- the
    same negative space the report itself is tested against, because repair_inversions
    re-derives from the identical candidate query rather than a second implementation."""
    src = _source(session, "recovered.example", STATUS_QUALIFIED)
    _attempt(session, src, STATUS_DISQUALIFIED, at=NOW - timedelta(days=90))
    _attempt(session, src, STATUS_QUALIFIED, at=NOW)

    out = repair_inversions(session, dry_run=False)
    assert out["reconciled_total"] == 0
