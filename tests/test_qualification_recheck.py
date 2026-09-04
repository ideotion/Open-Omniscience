"""
RECURRENT RE-VERIFICATION of source qualification (maintainer ruling 2026-09-04).

Two things are under test, and the first is a REGRESSION REPRODUCTION rather than a new
feature: with a large unqualified backlog the shared per-pass budget was always exhausted by
never-judged candidates, so `select_due_disqualified` was never reached and the
re-qualification ladder -- shipped correct in 2026-07 -- had in practice never run on a field
instance. The second is the new flat ~6-month re-check of QUALIFIED verdicts, including the
clock that starts when a stamp is ADOPTED here, so a fresh install does not re-qualify a
shipped catalog it was handed (superseding an earlier rule that clocked on the originating
date -- see the test that records the change).

In-memory SQLite, no network: the trial fetch is skipped by passing ``fetcher=None`` and the
cohort is injected, so what is exercised is the SCHEDULING -- which candidates a pass picks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import (
    QUALIFIED_RECHECK_MONTHS,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_INHERITED,
    VERDICT_NO_EVIDENCE,
    consecutive_disqualifications_from_verdicts,
    log_inherited_stamps,
    qualified_recheck_due_at,
    run_qualification_pass,
    select_due_qualified,
)
from src.database.models import Base, Source, SourceQualificationAttempt

NOW = datetime(2026, 9, 4, tzinfo=UTC)
LONG_AGO = NOW - timedelta(days=400)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _src(db, domain, status=STATUS_UNQUALIFIED, *, qualified_at=None):
    s = Source(name=domain, domain=domain, status=status, qualified_at=qualified_at)
    db.add(s)
    db.commit()
    return s


def _attempt(db, source, verdict, at):
    db.add(SourceQualificationAttempt(
        source_id=source.id, attempted_at=at, verdict=verdict, criteria_version="t"
    ))
    db.commit()


def _empty_cohort():
    """A cohort that judges nothing -- the pass runs, and every candidate lands in the
    no-evidence branch. That is what makes these SCHEDULING tests: which sources a pass
    SELECTS is observable without needing real articles or a verdict."""
    return {
        "min_articles": 1, "cohort_cut": {}, "cohort": {"baselines": {}, "lang_short_cut": {}},
        "token": "t", "articles": 0, "sources": 0, "furniture_df": None,
    }


def _selected(db, *, per_pass, recheck_per_pass):
    """Run one pass and return the domains it actually picked up, read off the attempt log
    the pass writes -- the production record, never a test-only hook."""
    before = {a.id for a in db.query(SourceQualificationAttempt).all()}
    run_qualification_pass(
        db, None, per_pass=per_pass, recheck_per_pass=recheck_per_pass, now=NOW,
        cohort_provider=_empty_cohort,
    )
    rows = db.query(SourceQualificationAttempt).all()
    ids = {r.source_id for r in rows if r.id not in before}
    return {s.domain for s in db.query(Source).filter(Source.id.in_(ids or {-1})).all()}


# ---------------------------------------------------------------- the regression

def test_a_backlog_of_new_candidates_no_longer_starves_the_ladder(db):
    """THE FINDING. A full window of never-judged candidates used to consume the whole
    budget, leaving `remaining == 0`, so a due disqualified source was never re-checked --
    the ladder was unreachable on any instance with a real backlog. Reproduced here with a
    backlog twice the budget; with the re-check budget at 0 the due source is invisible."""
    for i in range(10):
        _src(db, f"new{i}.example")
    bad = _src(db, "bad.example", status=STATUS_DISQUALIFIED)
    _attempt(db, bad, STATUS_DISQUALIFIED, LONG_AGO)

    starved = _selected(db, per_pass=5, recheck_per_pass=0)
    assert "bad.example" not in starved, (
        "the old shared-budget behaviour: a due re-check is unreachable behind a backlog"
    )
    assert len(starved) == 5

    picked = _selected(db, per_pass=5, recheck_per_pass=2)
    assert "bad.example" in picked, "the reserved budget must reach the due re-check"


def test_the_reserved_budget_does_not_shrink_the_new_candidate_window(db):
    """The mirror direction: re-checks must not be paid for out of the backlog's budget,
    or the fix would trade one starvation for the other."""
    for i in range(10):
        _src(db, f"new{i}.example")
    bad = _src(db, "bad.example", status=STATUS_DISQUALIFIED)
    _attempt(db, bad, STATUS_DISQUALIFIED, LONG_AGO)

    picked = _selected(db, per_pass=5, recheck_per_pass=2)
    assert len({d for d in picked if d.startswith("new")}) == 5


def test_unused_new_slots_still_spill_into_rechecks(db):
    """Today's behaviour, kept: when the backlog is short the leftover slots go to
    re-checks rather than being wasted."""
    _src(db, "new0.example")
    for i in range(4):
        s = _src(db, f"bad{i}.example", status=STATUS_DISQUALIFIED)
        _attempt(db, s, STATUS_DISQUALIFIED, LONG_AGO)

    picked = _selected(db, per_pass=5, recheck_per_pass=0)
    assert "new0.example" in picked
    assert len([d for d in picked if d.startswith("bad")]) == 4


# ------------------------------------------------- the qualified re-check clock

def test_a_freshly_qualified_source_is_not_re_checked(db):
    """Negative space, and the one that stops this becoming a re-trial storm: a verdict
    reached last week is not due."""
    s = _src(db, "fresh.example", status=STATUS_QUALIFIED, qualified_at=NOW - timedelta(days=7))
    _attempt(db, s, STATUS_QUALIFIED, NOW - timedelta(days=7))
    assert select_due_qualified(db, now=NOW, limit=10) == []


def test_a_qualified_verdict_past_the_interval_comes_due(db):
    s = _src(db, "old.example", status=STATUS_QUALIFIED,
             qualified_at=NOW - timedelta(days=30 * QUALIFIED_RECHECK_MONTHS + 1))
    _attempt(db, s, STATUS_QUALIFIED, NOW - timedelta(days=30 * QUALIFIED_RECHECK_MONTHS + 1))
    assert [x.domain for x in select_due_qualified(db, now=NOW, limit=10)] == ["old.example"]


def test_the_boundary_is_the_stated_interval_not_a_looser_one(db):
    """The interval is a claim; a re-check that fired at five months would make the
    documented six a fabricated figure."""
    just_inside = NOW - timedelta(days=30 * QUALIFIED_RECHECK_MONTHS - 1)
    s = _src(db, "edge.example", status=STATUS_QUALIFIED, qualified_at=just_inside)
    _attempt(db, s, STATUS_QUALIFIED, just_inside)
    assert select_due_qualified(db, now=NOW, limit=10) == []
    assert qualified_recheck_due_at(just_inside) > NOW


def test_a_freshly_adopted_stamp_is_not_due_however_old_the_verdict_is(db):
    """SUPERSEDES an earlier test that asserted the opposite (the clock reading the
    ORIGINATING date, so a stamp earned more than an interval ago arrived already expired).

    Changed deliberately on the maintainer's 2026-09-04 ask -- recorded rather than quietly
    flipped. Every release reaches users more than QUALIFIED_RECHECK_MONTHS after it was
    cut, so the old rule meant a fresh install spent its first passes re-verifying the whole
    shipped catalog: measured at 10 of 10 already due on an overlay stamped 9 months back.
    That defeats the accumulation the overlay exists for -- a verdict earned once should not
    have to be earned again on every machine.

    Nothing here claims local verification. `qualified_at` still holds the originating date
    (asserted below), the attempt row still says `inherited`, and the export still reports
    basis `inherited`. Only the LOCAL clock starts at adoption.
    """
    earned = NOW - timedelta(days=30 * QUALIFIED_RECHECK_MONTHS + 10)
    s = _src(db, "adopted.example", status=STATUS_QUALIFIED, qualified_at=earned)
    log_inherited_stamps(db, [s], now=NOW)
    db.commit()

    assert select_due_qualified(db, now=NOW, limit=10) == [], (
        "a stamp adopted today must wait a full interval before this instance re-verifies "
        "it, however old the verdict was when it arrived -- otherwise a fresh install "
        "re-qualifies the entire shipped catalog on day one"
    )
    # SQLite round-trips a DateTime as NAIVE even when an aware UTC value was stored (the
    # convention select_due_qualified itself re-attaches UTC for), so compare the instant.
    stored = s.qualified_at
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=UTC)
    assert stored == earned, (
        "the ORIGINATING date must survive adoption: deferring the local clock must never "
        "be implemented by restamping the verdict as though it were earned here"
    )


def test_an_adopted_stamp_does_come_due_once_ITS_OWN_interval_elapses(db):
    """The twin of the test above, and the one that stops it being a licence to never
    re-verify anything. Same adopted stamp, but adoption itself is now older than the
    interval -- so it must come due. Without this, deferring and DISABLING look identical.
    """
    earned = NOW - timedelta(days=30 * QUALIFIED_RECHECK_MONTHS + 10)
    adopted = NOW - timedelta(days=30 * QUALIFIED_RECHECK_MONTHS + 10)
    s = _src(db, "adopted.example", status=STATUS_QUALIFIED, qualified_at=earned)
    log_inherited_stamps(db, [s], now=adopted)
    db.commit()

    due = select_due_qualified(db, now=NOW, limit=10)
    assert [x.domain for x in due] == ["adopted.example"], (
        "an inherited stamp must still be re-verified locally once the interval has run "
        "from the day it was adopted here"
    )


def test_a_recently_inherited_recent_stamp_is_not_due(db):
    """The twin: inheriting must not make a genuinely fresh verdict due either."""
    s = _src(db, "adopted.example", status=STATUS_QUALIFIED,
             qualified_at=NOW - timedelta(days=3))
    log_inherited_stamps(db, [s], now=NOW)
    db.commit()
    assert select_due_qualified(db, now=NOW, limit=10) == []


def test_a_qualified_row_with_no_clock_at_all_is_treated_as_due(db):
    """A data anomaly (qualified with no stamp and no judging attempt) self-heals by being
    re-judged, rather than sitting permanently unverifiable and invisible."""
    _src(db, "anomaly.example", status=STATUS_QUALIFIED, qualified_at=None)
    assert [x.domain for x in select_due_qualified(db, now=NOW, limit=10)] == ["anomaly.example"]


def test_the_oldest_verdict_is_re_checked_first(db):
    for domain, days in (("mid.example", 250), ("oldest.example", 400), ("newer.example", 200)):
        at = NOW - timedelta(days=days)
        s = _src(db, domain, status=STATUS_QUALIFIED, qualified_at=at)
        _attempt(db, s, STATUS_QUALIFIED, at)
    assert [x.domain for x in select_due_qualified(db, now=NOW, limit=3)] == [
        "oldest.example", "mid.example", "newer.example",
    ]


def test_unqualified_and_disqualified_sources_are_never_offered_as_qualified_rechecks(db):
    _src(db, "new.example")
    bad = _src(db, "bad.example", status=STATUS_DISQUALIFIED)
    _attempt(db, bad, STATUS_DISQUALIFIED, LONG_AGO)
    assert select_due_qualified(db, now=NOW, limit=10) == []


def test_a_zero_recheck_budget_really_disables_qualified_re_verification(db):
    """An explicit "off" must turn the thing off. Unused NEW slots spill into DISQUALIFIED
    re-checks (that is today's behaviour and predates this setting), but they must never
    reach QUALIFIED re-verification, or `qualification_recheck_per_pass = 0` would still
    re-verify -- a setting that does not mean what it says. Caught by the pre-existing
    frozen-cohort and machine-floor suites, whose fixtures are corpora of already-qualified
    sources: a first cut let the spill through and made every one of them due."""
    stale = _src(db, "stale.example", status=STATUS_QUALIFIED, qualified_at=LONG_AGO)
    _attempt(db, stale, STATUS_QUALIFIED, LONG_AGO)
    bad = _src(db, "bad.example", status=STATUS_DISQUALIFIED)
    _attempt(db, bad, STATUS_DISQUALIFIED, LONG_AGO)

    picked = _selected(db, per_pass=5, recheck_per_pass=0)
    assert "stale.example" not in picked
    assert "bad.example" in picked, "the disqualified spill is today's behaviour, kept"


def test_the_reserved_budget_caps_qualified_rechecks_even_with_spare_slots(db):
    """The cap is the budget, not whatever happens to be free: spare new-candidate slots
    raise how many DISQUALIFIED re-checks run, never how many qualified ones do."""
    for i in range(5):
        s = _src(db, f"stale{i}.example", status=STATUS_QUALIFIED, qualified_at=LONG_AGO)
        _attempt(db, s, STATUS_QUALIFIED, LONG_AGO)

    picked = _selected(db, per_pass=5, recheck_per_pass=1)
    assert len([d for d in picked if d.startswith("stale")]) == 1


def test_both_recheck_kinds_share_the_reserved_budget(db):
    """Neither re-check pool may lock the other out at the default budget."""
    bad = _src(db, "bad.example", status=STATUS_DISQUALIFIED)
    _attempt(db, bad, STATUS_DISQUALIFIED, LONG_AGO)
    stale = _src(db, "stale.example", status=STATUS_QUALIFIED, qualified_at=LONG_AGO)
    _attempt(db, stale, STATUS_QUALIFIED, LONG_AGO)

    picked = _selected(db, per_pass=0, recheck_per_pass=2)
    assert picked == {"bad.example", "stale.example"}


def test_re_verification_still_runs_when_new_admissions_are_switched_off(db):
    """`qualification_per_pass=0` means "stop taking new candidates", and must not
    silently also mean "stop verifying the ones already admitted"."""
    stale = _src(db, "stale.example", status=STATUS_QUALIFIED, qualified_at=LONG_AGO)
    _attempt(db, stale, STATUS_QUALIFIED, LONG_AGO)
    out = run_qualification_pass(
        db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=_empty_cohort,
    )
    assert out["enabled"] is True
    assert out["evaluated"] == 1 and out["rechecks"] == 1 and out["new_candidates"] == 0


def test_both_budgets_at_zero_disables_the_pass(db):
    _src(db, "new.example")
    assert run_qualification_pass(db, None, per_pass=0, recheck_per_pass=0, now=NOW) == {
        "enabled": False
    }


# --------------------------------------------------------------- the ladder rules

def test_an_inherited_row_neither_advances_nor_resets_the_ladder():
    """It is not a judgement, so it must not be able to reset a ladder that real failures
    built -- nor count as a failure itself."""
    assert consecutive_disqualifications_from_verdicts(
        [VERDICT_INHERITED, STATUS_DISQUALIFIED, STATUS_DISQUALIFIED]
    ) == 2
    assert consecutive_disqualifications_from_verdicts(
        [VERDICT_INHERITED, VERDICT_NO_EVIDENCE, STATUS_QUALIFIED]
    ) == 0
    assert consecutive_disqualifications_from_verdicts([VERDICT_INHERITED]) == 0


def test_an_inherited_row_never_becomes_a_source_status(db):
    """The three-state admission-gate model is untouched: `inherited` lives only in the
    attempt log."""
    s = _src(db, "adopted.example", status=STATUS_QUALIFIED, qualified_at=NOW)
    log_inherited_stamps(db, [s], now=NOW)
    db.commit()
    db.refresh(s)
    assert s.status == STATUS_QUALIFIED
    assert {r.verdict for r in db.query(SourceQualificationAttempt).all()} == {VERDICT_INHERITED}


# ------------------------------------------------------- the setting is reachable

def test_the_recheck_budget_is_writable_through_the_config_endpoint():
    """A setting the API body does not declare is silently dropped by
    `save_settings(model_dump(exclude_unset=True))` -- so the knob would exist, be
    documented, and be unreachable from the UI. The dead-seam shape this repo has paid
    for repeatedly."""
    from src.api.scheduler import SchedulerConfigUpdate

    assert "qualification_recheck_per_pass" in SchedulerConfigUpdate.model_fields
    body = SchedulerConfigUpdate(qualification_recheck_per_pass=4)
    assert body.model_dump(exclude_unset=True) == {"qualification_recheck_per_pass": 4}


def test_the_setting_round_trips_through_save_and_load(tmp_path, monkeypatch):
    from src.scheduler import settings as st

    monkeypatch.setattr(st, "_settings_path", lambda: tmp_path / "settings.json")
    st.save_settings({"qualification_recheck_per_pass": 7})
    assert st.load_settings().qualification_recheck_per_pass == 7


def test_an_out_of_range_budget_is_REFUSED_not_quietly_clamped(tmp_path, monkeypatch):
    """The house convention for this settings path, confirmed by driving it: an
    out-of-range value RAISES rather than being silently coerced -- so an operator who
    typed 10,000 learns that, instead of being given 100 and told nothing."""
    from src.scheduler import settings as st

    monkeypatch.setattr(st, "_settings_path", lambda: tmp_path / "settings.json")
    with pytest.raises(st.SchedulerSettingsError):
        st.save_settings({"qualification_recheck_per_pass": 10_000})


def test_the_panel_describes_the_re_check_the_engine_actually_applies():
    """The qualification panel renders the BACKEND's vocabulary rather than restating it in
    HTML, precisely so it cannot describe a gate the engine no longer applies. A
    re-verification clock the panel does not mention is that defect pointing the other
    way: the engine applies something the operator is never told about."""
    import inspect

    from src.api import source_management

    src = inspect.getsource(source_management.qualification_config)
    assert '"recheck"' in src
    assert "QUALIFIED_RECHECK_MONTHS" in src
