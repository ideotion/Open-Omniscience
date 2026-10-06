"""The curated catalogue is qualified BY RULING (maintainer, 2026-09-10) and re-verified like
any other qualified source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

The ruling admits the hand-vetted catalogues at seed instead of leaving ~3,400 rows to wait
their turn behind a discovery backlog of tens of thousands. What these tests pin is the part
the ruling did NOT say and a careless build would get wrong:

* the stamp's BASIS is recorded (an attempt row reading ``curated``, a criteria-version
  marker naming the catalogue) so it can never read as a measurement;
* a source this instance MEASURED -- ``disqualified`` above all -- is never re-stamped, so
  nothing is laundered; and a shipped, measured verdict outranks the curation stamp in
  either direction, because the overlay's "local wins" rule defends judgements, not rulings;
* the six-month clock starts at the stamp, and the disqualified ladder ignores it;
* the export counts a curation stamp and never ships it as an earned verdict;
* the scope is exactly the hand-vetted provenances -- a discovered, cited, generated or
  hand-added row is untouched whatever it reads.

Each guard below was mutation-checked by neutering the corresponding branch and reading the
failure by name (see the PR for the matrix).
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.provenance_scope import CURATED_PROVENANCES, is_curated
from src.catalog.qualification import (
    CLOCK_VERDICTS,
    CRITERIA_VERSION,
    CURATED_CRITERIA_VERSION,
    QUALIFIED_RECHECK_MONTHS,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_CURATED,
    VERDICT_INHERITED,
    VERDICT_NO_EVIDENCE,
    consecutive_disqualifications_from_verdicts,
    select_due_qualified,
    stamp_curated_catalog,
)
from src.catalog.qualification_export import BASIS_CURATED, build_overlay_export
from src.catalog.qualification_overlay import apply_overlay
from src.database.models import Base, Source, SourceQualificationAttempt
from src.discovery.source_trail import source_provenance

NOW = datetime(2026, 9, 10, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _src(db, domain, *, tags="news,via:curated", status=STATUS_UNQUALIFIED,
         qualified_at=None, criteria_version=None, enabled=True):
    s = Source(name=domain, domain=domain, tags=tags, status=status, enabled=enabled,
               qualified_at=qualified_at, qualification_criteria_version=criteria_version)
    db.add(s)
    db.commit()
    return s


def _attempt(db, s, verdict, *, at=NOW, criteria_version="t"):
    db.add(SourceQualificationAttempt(
        source_id=s.id, attempted_at=at, verdict=verdict, criteria_version=criteria_version,
    ))
    db.commit()


def _attempts(db, s):
    return [
        r.verdict for r in db.query(SourceQualificationAttempt)
        .filter_by(source_id=s.id).order_by(SourceQualificationAttempt.id).all()
    ]


# ------------------------------------------------------------------ the stamp itself

def test_a_curated_row_is_stamped_qualified_with_its_basis_recorded(db):
    s = _src(db, "curated.example")
    out = stamp_curated_catalog(db, now=NOW)
    db.refresh(s)
    assert out["stamped"] == 1 and out["curated"] == 1
    assert s.status == STATUS_QUALIFIED
    assert s.qualified_at.replace(tzinfo=UTC) == NOW
    # The stamp names what judged it -- nothing -- rather than a criteria version.
    assert s.qualification_criteria_version == CURATED_CRITERIA_VERSION
    assert s.qualification_criteria_version != CRITERIA_VERSION
    assert _attempts(db, s) == [VERDICT_CURATED]


def test_the_scope_is_exactly_the_hand_vetted_catalogues(db):
    """A generated or discovered row keeps waiting its turn; a hand-vetted one does not.
    `via:wikidata` (the GENERATED world catalogue) is app-provided and still out of scope --
    the ruling says curated, and a Wikidata query is nobody's judgement."""
    inside = {p: _src(db, f"{p}.example", tags=f"news,via:{p}") for p in sorted(CURATED_PROVENANCES)}
    outside = {
        "wikidata": _src(db, "generated.example", tags="news,world-catalog,via:wikidata"),
        "discovery": _src(db, "found.example", tags="news,world-catalog,via:wikidata-discovery",
                          enabled=False),
        "cited": _src(db, "cited.example", tags="cited"),
        "hand-added": _src(db, "typed.example", tags="news"),
        "prefix-trap": _src(db, "trap.example", tags="news,via:curated-not-really"),
    }
    out = stamp_curated_catalog(db, now=NOW)
    assert out["stamped"] == len(inside)
    for s in inside.values():
        db.refresh(s)
        assert s.status == STATUS_QUALIFIED and is_curated(s)
    for s in outside.values():
        db.refresh(s)
        assert s.status == STATUS_UNQUALIFIED and _attempts(db, s) == [] and not is_curated(s)


def test_a_disqualified_catalogue_row_is_never_laundered(db):
    """The ruling admits the catalogue; it does not overturn a verdict this instance measured."""
    s = _src(db, "broken.example", status=STATUS_DISQUALIFIED)
    _attempt(db, s, STATUS_DISQUALIFIED, at=NOW - timedelta(days=3))
    out = stamp_curated_catalog(db, now=NOW)
    db.refresh(s)
    assert s.status == STATUS_DISQUALIFIED and s.qualified_at is None
    assert out["stamped"] == 0 and out["disqualified"] == 1
    assert _attempts(db, s) == [STATUS_DISQUALIFIED]


def test_an_adopted_disqualification_is_never_laundered_either(db):
    """The negative twin the mutation matrix asked for: a `disqualified` row whose verdict was
    ADOPTED (an `inherited` row, no judging attempt) is not protected by the judged-ids guard
    above -- only the status filter keeps the stamp off it. Without this test the mutant that
    stamps every non-qualified catalogue row survives, because the sibling fixture's
    disqualified row happened to be judged locally."""
    s = _src(db, "shipped-bad.example", status=STATUS_DISQUALIFIED)
    _attempt(db, s, VERDICT_INHERITED, at=NOW - timedelta(days=3))
    out = stamp_curated_catalog(db, now=NOW)
    db.refresh(s)
    assert s.status == STATUS_DISQUALIFIED and s.qualified_at is None
    assert out["stamped"] == 0 and out["disqualified"] == 1
    assert _attempts(db, s) == [VERDICT_INHERITED]


def test_a_measured_or_adopted_qualified_row_keeps_its_own_clock(db):
    earlier = NOW - timedelta(days=100)
    measured = _src(db, "measured.example", status=STATUS_QUALIFIED, qualified_at=earlier,
                    criteria_version=CRITERIA_VERSION)
    _attempt(db, measured, STATUS_QUALIFIED, at=earlier)
    adopted = _src(db, "adopted.example", status=STATUS_QUALIFIED, qualified_at=earlier,
                   criteria_version=CRITERIA_VERSION)
    _attempt(db, adopted, VERDICT_INHERITED, at=earlier)
    out = stamp_curated_catalog(db, now=NOW)
    assert out["stamped"] == 0 and out["already_qualified"] == 2
    for s in (measured, adopted):
        db.refresh(s)
        assert s.qualified_at.replace(tzinfo=UTC) == earlier
        assert s.qualification_criteria_version == CRITERIA_VERSION
        assert VERDICT_CURATED not in _attempts(db, s)


def test_an_unqualified_row_that_was_nevertheless_judged_is_kept(db):
    """`evaluate_and_stamp` writes the attempt and the status together, so this shape is an
    anomaly -- and the direction that never overwrites evidence is the safe one."""
    s = _src(db, "anomaly.example")
    _attempt(db, s, STATUS_QUALIFIED, at=NOW - timedelta(days=1))
    out = stamp_curated_catalog(db, now=NOW)
    db.refresh(s)
    assert out["kept_local"] == 1 and out["stamped"] == 0
    assert s.status == STATUS_UNQUALIFIED


def test_a_no_evidence_history_does_not_block_the_stamp(db):
    """Tried and concluded nothing is not a judgement (the 2026-07-23 rule), so the row is
    still the catalogue's to admit."""
    s = _src(db, "quiet-feed.example")
    _attempt(db, s, VERDICT_NO_EVIDENCE, at=NOW - timedelta(days=10))
    _attempt(db, s, VERDICT_NO_EVIDENCE, at=NOW - timedelta(days=2))
    out = stamp_curated_catalog(db, now=NOW)
    db.refresh(s)
    assert out["stamped"] == 1 and s.status == STATUS_QUALIFIED
    assert _attempts(db, s) == [VERDICT_NO_EVIDENCE, VERDICT_NO_EVIDENCE, VERDICT_CURATED]


def test_stamping_twice_stamps_once(db):
    s = _src(db, "curated.example")
    stamp_curated_catalog(db, now=NOW)
    again = stamp_curated_catalog(db, now=NOW + timedelta(days=1))
    db.refresh(s)
    assert again["stamped"] == 0 and again["already_qualified"] == 1
    assert _attempts(db, s) == [VERDICT_CURATED]
    assert s.qualified_at.replace(tzinfo=UTC) == NOW  # the clock was not restarted


# ------------------------------------------------------------------ the clock and the ladder

def test_the_stamp_starts_the_same_six_month_clock_as_any_other_source(db):
    s = _src(db, "curated.example")
    stamp_curated_catalog(db, now=NOW)
    soon = NOW + timedelta(days=1)
    later = NOW + timedelta(days=30 * QUALIFIED_RECHECK_MONTHS + 1)
    assert select_due_qualified(db, now=soon, limit=10) == []
    assert [x.id for x in select_due_qualified(db, now=later, limit=10)] == [s.id]
    assert VERDICT_CURATED in CLOCK_VERDICTS


def test_the_disqualified_ladder_ignores_a_curation_stamp():
    """Like `inherited`: not a judgement, so it neither advances nor resets the ladder."""
    assert consecutive_disqualifications_from_verdicts(
        [VERDICT_CURATED, STATUS_DISQUALIFIED, STATUS_DISQUALIFIED]
    ) == 2
    assert consecutive_disqualifications_from_verdicts([VERDICT_CURATED]) == 0
    assert consecutive_disqualifications_from_verdicts(
        [STATUS_DISQUALIFIED, VERDICT_CURATED, STATUS_QUALIFIED]
    ) == 1


# ------------------------------------------------------------------ the overlay

def _overlay(tmp_path, rows):
    p = tmp_path / "source_qualification.yml"
    p.write_text(yaml.safe_dump({"verdicts": rows}), encoding="utf-8")
    return p


def test_a_shipped_measured_disqualification_outranks_the_curation_stamp(db, tmp_path):
    s = _src(db, "curated.example")
    stamp_curated_catalog(db, now=NOW)
    out = apply_overlay(db, now=NOW + timedelta(days=1), path=_overlay(tmp_path, [
        {"domain": "curated.example", "status": STATUS_DISQUALIFIED},
    ]))
    db.refresh(s)
    assert out["replaced_curated"] == 1 and out["kept_local"] == 0
    assert s.status == STATUS_DISQUALIFIED and s.qualified_at is None
    assert _attempts(db, s) == [VERDICT_CURATED, VERDICT_INHERITED]


def test_a_shipped_measured_qualification_replaces_the_curation_stamp(db, tmp_path):
    s = _src(db, "curated.example")
    stamp_curated_catalog(db, now=NOW)
    shipped_at = NOW - timedelta(days=40)
    out = apply_overlay(db, now=NOW + timedelta(days=1), path=_overlay(tmp_path, [
        {"domain": "curated.example", "status": STATUS_QUALIFIED,
         "qualified_at": shipped_at.isoformat(), "criteria_version": "shipped-v9"},
    ]))
    db.refresh(s)
    assert out["replaced_curated"] == 1
    assert s.qualification_criteria_version == "shipped-v9"
    assert s.qualified_at.replace(tzinfo=UTC) == shipped_at


def test_a_local_measured_verdict_still_wins_over_the_overlay(db, tmp_path):
    """The negative twin: widening adoption to curation stamps must not reopen the local-wins
    guarantee for a verdict this instance actually reached."""
    s = _src(db, "measured.example", status=STATUS_QUALIFIED, qualified_at=NOW,
             criteria_version=CRITERIA_VERSION)
    _attempt(db, s, STATUS_QUALIFIED, at=NOW)
    out = apply_overlay(db, now=NOW + timedelta(days=1), path=_overlay(tmp_path, [
        {"domain": "measured.example", "status": STATUS_DISQUALIFIED},
    ]))
    db.refresh(s)
    assert out["kept_local"] == 1 and out["replaced_curated"] == 0
    assert s.status == STATUS_QUALIFIED


def test_the_overlay_then_the_stamp_is_the_boot_order_and_the_overlay_wins(db, tmp_path):
    """main.py applies the overlay BEFORE the stamp; a shipped disqualification for a
    catalogue domain must therefore survive the stamp that follows it."""
    s = _src(db, "curated.example")
    apply_overlay(db, now=NOW, path=_overlay(tmp_path, [
        {"domain": "curated.example", "status": STATUS_DISQUALIFIED},
    ]))
    out = stamp_curated_catalog(db, now=NOW)
    db.refresh(s)
    assert s.status == STATUS_DISQUALIFIED and out["stamped"] == 0


# ------------------------------------------------------------------ the export

def test_the_export_counts_a_curation_stamp_and_never_ships_it(db):
    curated = _src(db, "curated.example")
    measured = _src(db, "measured.example", status=STATUS_QUALIFIED, qualified_at=NOW,
                    criteria_version=CRITERIA_VERSION)
    _attempt(db, measured, STATUS_QUALIFIED, at=NOW)
    stamp_curated_catalog(db, now=NOW)
    export = build_overlay_export(db, now=NOW)
    assert export["basis"][BASIS_CURATED] == 1
    assert export["split"]["qualified"] == 2
    assert export["split"]["qualified_by_curation"] == 1
    shipped = {v["domain"] for v in export["verdicts"]}
    assert shipped == {measured.domain}
    assert curated.domain not in shipped


def test_a_re_verified_catalogue_row_reads_measured(db):
    s = _src(db, "curated.example")
    stamp_curated_catalog(db, now=NOW)
    _attempt(db, s, STATUS_QUALIFIED, at=NOW + timedelta(days=200), criteria_version=CRITERIA_VERSION)
    # What evaluate_and_stamp does with a real judgement: the attempt AND the live stamp move
    # together. The basis follows the LIVE stamp (2026-09-30), so this is what makes it measured.
    s.qualification_criteria_version = CRITERIA_VERSION
    s.qualified_at = NOW + timedelta(days=200)
    db.commit()
    export = build_overlay_export(db, now=NOW + timedelta(days=201))
    assert export["basis"][BASIS_CURATED] == 0
    assert {v["domain"] for v in export["verdicts"]} == {s.domain}
    assert source_provenance(db, s.id)["qualification_basis"] == "measured"


def _withdrawn_row(db, *, imported_followed=False):
    """What the boot repair leaves: status disqualified, no criteria version, the catalogue's own
    curated attempt and another instance's disqualifying judgement in the history. With
    ``imported_followed`` that judgement is recorded as a merge records its attempts (``merged_rows``),
    which is what a real withdrawn row's followed attempt is."""
    s = _src(db, "withdrawn.example")
    stamp_curated_catalog(db, now=NOW)
    _attempt(db, s, STATUS_DISQUALIFIED, at=NOW + timedelta(days=5), criteria_version=CRITERIA_VERSION)
    if imported_followed:
        _mark_imported(db, s, at=NOW + timedelta(days=5))
    s.status = STATUS_DISQUALIFIED
    s.qualification_criteria_version = None
    db.commit()
    return s


def _repair_record(s):
    """What repaired_rows reports for ``_withdrawn_row``: the imported attempt it followed."""
    import src.catalog.qualification_integrity as qi

    return {s.domain: qi._iso(NOW + timedelta(days=5))}


def test_a_row_the_boot_repair_withdrew_exports_as_inherited_not_measured(db, monkeypatch):
    """Rank 14 follow-up: its disqualification came from an imported history, so it must never ship
    as this install's own measurement (or come back as corroboration after the next import)."""
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db)
    before = build_overlay_export(db, now=NOW + timedelta(days=6))
    assert before["basis"]["measured"] == 1, "without the repair record the history reads as measured"

    monkeypatch.setattr(qi, "repaired_rows", lambda: (_repair_record(s), []))
    export = build_overlay_export(db, now=NOW + timedelta(days=6))
    assert export["basis"]["measured"] == 0 and export["basis"]["inherited"] == 1
    assert export["basis"]["repaired_exported_as_inherited"] == 1
    assert [(v["domain"], v["basis"]) for v in export["verdicts"]] == [(s.domain, "inherited")]


def test_a_repaired_row_this_install_re_judged_reads_measured_again(db, monkeypatch):
    """Either direction: a local qualification stamps a version, a local DISQUALIFICATION stamps
    none (the usual path, a month on), and the attempt is what tells the two apart."""
    import src.catalog.qualification_integrity as qi

    for verdict, version in ((STATUS_QUALIFIED, CRITERIA_VERSION), (STATUS_DISQUALIFIED, None)):
        s = _withdrawn_row(db) if not db.query(Source).filter_by(domain="withdrawn.example").count() else (
            db.query(Source).filter_by(domain="withdrawn.example").one())
        record = _repair_record(s)
        _attempt(db, s, verdict, at=NOW + timedelta(days=40), criteria_version=CRITERIA_VERSION)
        s.status = verdict
        s.qualification_criteria_version = version               # what evaluate_and_stamp writes
        db.commit()
        monkeypatch.setattr(qi, "repaired_rows", lambda record=record: (record, []))
        export = build_overlay_export(db, now=NOW + timedelta(days=41))
        assert export["basis"]["measured"] == 1, verdict
        assert export["basis"]["repaired_exported_as_inherited"] == 0, verdict


def test_a_repair_record_without_judged_at_reads_inherited_conservatively(db, monkeypatch):
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db)
    monkeypatch.setattr(qi, "repaired_rows", lambda: ({s.domain: None}, []))
    export = build_overlay_export(db, now=NOW + timedelta(days=6))
    assert [(v["domain"], v["basis"]) for v in export["verdicts"]] == [(s.domain, "inherited")]


def test_the_overlay_file_carries_the_warning_when_the_repair_record_was_unreadable(db, monkeypatch):
    """The flag in the basis block never reached the YAML a maintainer merges; now a comment does."""
    import src.catalog.qualification_integrity as qi
    from src.catalog.qualification_export import to_overlay_yaml

    _withdrawn_row(db)
    monkeypatch.setattr(qi, "repaired_rows", lambda: ({}, []))
    assert "WARNING" not in to_overlay_yaml(build_overlay_export(db, now=NOW + timedelta(days=6)))
    monkeypatch.setattr(qi, "repaired_rows", lambda: ({}, ["2026-09-30T00:00:00+00:00"]))
    text = to_overlay_yaml(build_overlay_export(db, now=NOW + timedelta(days=6)))
    assert "WARNING" in text and "2026-09-30T00:00:00+00:00" in text
    import yaml
    assert yaml.safe_load(text)["verdicts"] is not None, "still a valid overlay file"


def _mark_imported(db, s, *, at):
    """Record the attempt at ``at`` as a backup merge does: a batch, and its row in ``merged_rows``."""
    from src.database.models import MergeBatch, MergedRow

    attempt = (
        db.query(SourceQualificationAttempt)
        .filter_by(source_id=s.id, attempted_at=at).one()
    )
    batch = MergeBatch()
    db.add(batch)
    db.flush()
    db.add(MergedRow(
        batch_id=batch.id, table_name="source_qualification_attempts", row_id=attempt.id,
    ))
    db.commit()


def _basis_of(db, s, days):
    export = build_overlay_export(db, now=NOW + timedelta(days=days))
    return {v["domain"]: v["basis"] for v in export["verdicts"]}[s.domain], export


def test_a_newer_attempt_a_merge_brought_in_does_not_make_a_repaired_row_measured(db, monkeypatch):
    """Rule 12 = b: a later import never launders a repaired row into this install's own measurement.
    The merge names every attempt it inserts in ``merged_rows``, and the export reads that."""
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db)
    monkeypatch.setattr(qi, "repaired_rows", lambda: (_repair_record(s), []))
    assert _basis_of(db, s, 6)[0] == "inherited"
    later = NOW + timedelta(days=20)
    _attempt(db, s, STATUS_DISQUALIFIED, at=later, criteria_version=CRITERIA_VERSION)
    _mark_imported(db, s, at=later)
    basis, export = _basis_of(db, s, 21)
    assert basis == "inherited"
    assert export["basis"]["repaired_exported_as_inherited"] == 1
    assert source_provenance(db, s.id)["qualification_basis"] == "inherited"


def test_a_local_attempt_after_an_imported_one_still_makes_the_row_measured(db, monkeypatch):
    """The control: the install judged it itself, so it is its own measurement whatever else arrived."""
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db)
    monkeypatch.setattr(qi, "repaired_rows", lambda: (_repair_record(s), []))
    imported_at = NOW + timedelta(days=20)
    _attempt(db, s, STATUS_DISQUALIFIED, at=imported_at, criteria_version=CRITERIA_VERSION)
    _mark_imported(db, s, at=imported_at)
    _attempt(db, s, STATUS_DISQUALIFIED, at=NOW + timedelta(days=30), criteria_version=CRITERIA_VERSION)
    basis, export = _basis_of(db, s, 31)
    assert basis == "measured"
    assert export["basis"]["repaired_exported_as_inherited"] == 0
    assert source_provenance(db, s.id)["qualification_basis"] == "measured"


def test_a_local_attempt_older_than_the_imported_one_does_not_decide(db, monkeypatch):
    """Only a judging attempt NEWER than the one the repair followed can overtake it."""
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db)
    monkeypatch.setattr(qi, "repaired_rows", lambda: (_repair_record(s), []))
    _attempt(db, s, STATUS_QUALIFIED, at=NOW + timedelta(days=1), criteria_version=CRITERIA_VERSION)
    assert _basis_of(db, s, 6)[0] == "inherited"


def test_residue_an_imported_attempt_with_no_merged_rows_row_reads_as_local(db, monkeypatch):
    """THE RESIDUE, pinned: an attempt that arrived by a path that left no ``merged_rows`` row (a
    batch removed by hand in the database) cannot be shown to be imported, so
    it reads as this install's own. Nothing in the app writes such a row; if this test starts failing
    because something else tells them apart, say so in OPEN_QUEUE and the 0.4 gate."""
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db)
    monkeypatch.setattr(qi, "repaired_rows", lambda: (_repair_record(s), []))
    later = NOW + timedelta(days=20)
    _attempt(db, s, STATUS_DISQUALIFIED, at=later, criteria_version=CRITERIA_VERSION)
    _mark_imported(db, s, at=later)
    assert _basis_of(db, s, 21)[0] == "inherited"
    from sqlalchemy import text

    db.execute(text("DELETE FROM merged_rows"))
    db.execute(text("DELETE FROM merge_batches"))
    db.commit()
    assert _basis_of(db, s, 21)[0] == "measured"


def test_a_followed_attempt_that_is_itself_imported_keeps_the_row_inherited(db, monkeypatch):
    """What a real withdrawn row looks like: the attempt the repair followed came in through a merge,
    so nothing local is newer and the row stays inherited (flip `newest_local is None` and this
    fails); an OLDER local attempt does not decide either (flip the `<=` and this fails)."""
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db, imported_followed=True)
    monkeypatch.setattr(qi, "repaired_rows", lambda: (_repair_record(s), []))
    assert _basis_of(db, s, 6)[0] == "inherited"
    assert source_provenance(db, s.id)["qualification_basis"] == "inherited"
    _attempt(db, s, STATUS_QUALIFIED, at=NOW + timedelta(days=1), criteria_version=CRITERIA_VERSION)
    assert _basis_of(db, s, 6)[0] == "inherited"
    _attempt(db, s, STATUS_DISQUALIFIED, at=NOW + timedelta(days=9), criteria_version=CRITERIA_VERSION)
    assert _basis_of(db, s, 10)[0] == "measured"


def test_only_an_attempt_of_the_attempts_table_marks_an_attempt_imported(db, monkeypatch):
    """``merged_rows`` names rows of many tables by id: another table's row with the same id must not
    make a local judgement read as imported."""
    import src.catalog.qualification_integrity as qi
    from src.database.models import MergeBatch, MergedRow

    s = _withdrawn_row(db, imported_followed=True)
    monkeypatch.setattr(qi, "repaired_rows", lambda: (_repair_record(s), []))
    later = NOW + timedelta(days=20)
    _attempt(db, s, STATUS_DISQUALIFIED, at=later, criteria_version=CRITERIA_VERSION)
    attempt = db.query(SourceQualificationAttempt).filter_by(source_id=s.id, attempted_at=later).one()
    batch = MergeBatch()
    db.add(batch)
    db.flush()
    db.add(MergedRow(batch_id=batch.id, table_name="articles", row_id=attempt.id))
    db.commit()
    assert _basis_of(db, s, 21)[0] == "measured"


def test_a_newer_attempt_that_is_not_a_judgement_does_not_decide(db, monkeypatch):
    """Only judging verdicts count: a newer ``inherited`` attempt (an overlay adoption) is not this
    install judging the source."""
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db, imported_followed=True)
    monkeypatch.setattr(qi, "repaired_rows", lambda: (_repair_record(s), []))
    _attempt(db, s, VERDICT_INHERITED, at=NOW + timedelta(days=20), criteria_version=CRITERIA_VERSION)
    assert _basis_of(db, s, 21)[0] == "inherited"


def test_a_source_whose_whole_judging_history_was_imported_is_not_this_installs_measurement(db):
    """The same rule for every row, not only repaired ones: a merge into a young install copies the
    sources' verdicts AND their attempts, and the export used to ship those as `measured` here."""
    imported = _src(db, "imported.example", status=STATUS_QUALIFIED, qualified_at=NOW,
                    criteria_version=CRITERIA_VERSION)
    own = _src(db, "own.example", status=STATUS_QUALIFIED, qualified_at=NOW,
               criteria_version=CRITERIA_VERSION)
    _attempt(db, imported, STATUS_QUALIFIED, at=NOW, criteria_version=CRITERIA_VERSION)
    _attempt(db, own, STATUS_QUALIFIED, at=NOW, criteria_version=CRITERIA_VERSION)
    _mark_imported(db, imported, at=NOW)
    export = build_overlay_export(db, now=NOW + timedelta(days=1))
    basis = {v["domain"]: v["basis"] for v in export["verdicts"]}
    assert basis == {"imported.example": "inherited", "own.example": "measured"}
    assert source_provenance(db, imported.id)["qualification_basis"] == "inherited"
    assert source_provenance(db, own.id)["qualification_basis"] == "measured"


def test_a_catalogue_row_that_took_a_merged_verdict_reads_inherited_not_curated(db):
    """Every catalogue row carries a curated attempt. When a merge then gives it another instance's
    verdict (status and criteria version of the incoming row, the incoming attempts beside it), the
    verdict is inherited: neither the catalogue's stamp nor this install's measurement."""
    s = _src(db, "catalogue-merged.example")
    stamp_curated_catalog(db, now=NOW)
    s.status = STATUS_DISQUALIFIED
    s.qualification_criteria_version = CRITERIA_VERSION
    s.qualified_at = NOW + timedelta(days=2)
    db.commit()
    _attempt(db, s, STATUS_DISQUALIFIED, at=NOW + timedelta(days=2), criteria_version=CRITERIA_VERSION)
    _mark_imported(db, s, at=NOW + timedelta(days=2))
    basis, export = _basis_of(db, s, 3)
    assert basis == "inherited"
    assert source_provenance(db, s.id)["qualification_basis"] == "inherited"
    # and without any judging attempt the catalogue's own stamp still reads curated
    t = _src(db, "catalogue-only.example")
    stamp_curated_catalog(db, now=NOW)
    t.qualification_criteria_version = CRITERIA_VERSION  # live stamp no longer the catalogue's
    db.commit()
    assert source_provenance(db, t.id)["qualification_basis"] == "curated"
    export = build_overlay_export(db, now=NOW + timedelta(days=3))
    assert export["basis"]["curated"] == 1 and export["basis"]["inherited"] == 1, "a curated row is counted, never shipped"


def test_a_curated_row_with_imported_history_is_still_counted_as_having_judging_history(db):
    """The mismatch counter is about attempts COPIED IN: it keeps counting them."""
    s = _src(db, "curated-with-history.example")
    stamp_curated_catalog(db, now=NOW)
    _attempt(db, s, STATUS_DISQUALIFIED, at=NOW + timedelta(days=2), criteria_version=CRITERIA_VERSION)
    _mark_imported(db, s, at=NOW + timedelta(days=2))
    export = build_overlay_export(db, now=NOW + timedelta(days=3))
    assert export["basis"]["curated_stamp_with_judging_history"] == 1


def test_a_repair_stamp_that_cannot_be_read_is_read_as_still_followed(db, monkeypatch):
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db)
    monkeypatch.setattr(qi, "repaired_rows", lambda: ({s.domain: "not a date"}, []))
    _attempt(db, s, STATUS_DISQUALIFIED, at=NOW + timedelta(days=20), criteria_version=CRITERIA_VERSION)
    assert _basis_of(db, s, 21)[0] == "inherited"


def test_the_provenance_basis_reads_a_repaired_row_as_the_export_does(db, monkeypatch):
    """GET /api/sources/{id}/provenance must not call an imported verdict `measured` either."""
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db)
    assert source_provenance(db, s.id)["qualification_basis"] == "measured"
    monkeypatch.setattr(qi, "repaired_rows", lambda: (_repair_record(s), []))
    assert source_provenance(db, s.id)["qualification_basis"] == "inherited"
    _attempt(db, s, STATUS_DISQUALIFIED, at=NOW + timedelta(days=40), criteria_version=CRITERIA_VERSION)
    db.commit()
    assert source_provenance(db, s.id)["qualification_basis"] == "measured", "judged again here"


def test_the_provenance_page_says_when_the_repair_record_could_not_be_read(db, monkeypatch):
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db)
    monkeypatch.setattr(qi, "repaired_rows", lambda: ({s.domain: None}, []))
    assert source_provenance(db, s.id)["qualification_basis_unverified"] is False
    monkeypatch.setattr(qi, "repaired_rows", lambda: ({}, ["2026-09-30T00:00:00+00:00"]))
    assert source_provenance(db, s.id)["qualification_basis_unverified"] is True

    def boom():
        raise OSError("database is locked")

    monkeypatch.setattr(qi, "repaired_rows", boom)
    assert source_provenance(db, s.id)["qualification_basis_unverified"] is True


def test_the_provenance_basis_leaves_a_row_that_is_no_longer_judged_alone(db, monkeypatch):
    """The export ships only judged rows; a repaired row reset to unqualified is not labelled
    inherited by the page either."""
    import src.catalog.qualification_integrity as qi

    s = _withdrawn_row(db)
    monkeypatch.setattr(qi, "repaired_rows", lambda: (_repair_record(s), []))
    s.status = "unqualified"
    db.commit()
    assert source_provenance(db, s.id)["qualification_basis"] != "inherited"


def test_an_unreadable_repair_record_is_said_not_read_as_none_repaired(db, monkeypatch):
    import src.catalog.qualification_integrity as qi

    _withdrawn_row(db)

    def boom():
        raise OSError("database is locked")

    monkeypatch.setattr(qi, "repaired_rows", boom)
    export = build_overlay_export(db, now=NOW + timedelta(days=6))
    assert export["basis"]["repair_record_unreadable"] is True


def test_an_unreadable_run_makes_the_export_say_so_and_name_it(db, monkeypatch):
    """Its domains are unknown, so a repaired row may read measured; the basis block says that."""
    import src.catalog.qualification_integrity as qi

    _withdrawn_row(db)
    monkeypatch.setattr(qi, "repaired_rows", lambda: ({}, ["2026-09-30T00:00:00+00:00"]))
    export = build_overlay_export(db, now=NOW + timedelta(days=6))
    assert export["basis"]["repair_record_unreadable"] is True
    assert export["basis"]["repair_runs_unreadable"] == ["2026-09-30T00:00:00+00:00"]


def test_a_curated_stamp_with_copied_in_judging_history_still_reads_curated(db):
    """Diagnostics rank 14: a restore copied another instance's judging attempts beside a
    still-curated stamp, and ~2,000 rows per instance then read 'measured' and shipped as this
    instance's own verdict. The LIVE stamp decides; the mismatch is counted apart."""
    s = _src(db, "curated.example")
    stamp_curated_catalog(db, now=NOW)
    _attempt(db, s, STATUS_QUALIFIED, at=NOW + timedelta(days=5), criteria_version=CRITERIA_VERSION)

    export = build_overlay_export(db, now=NOW + timedelta(days=6))
    assert export["basis"][BASIS_CURATED] == 1 and export["basis"]["measured"] == 0
    assert export["basis"]["curated_stamp_with_judging_history"] == 1
    assert export["verdicts"] == [], "a catalogue default is never shipped as a verdict"
    assert source_provenance(db, s.id)["qualification_basis"] == "curated"


# ------------------------------------------------------------------ the surface

def test_the_provenance_panel_carries_the_basis(db):
    curated = _src(db, "curated.example")
    stamp_curated_catalog(db, now=NOW)
    adopted = _src(db, "adopted.example", status=STATUS_QUALIFIED, qualified_at=NOW,
                   criteria_version=CRITERIA_VERSION)
    _attempt(db, adopted, VERDICT_INHERITED, at=NOW)
    plain = _src(db, "plain.example", tags="news")
    assert source_provenance(db, curated.id)["qualification_basis"] == "curated"
    assert source_provenance(db, adopted.id)["qualification_basis"] == "inherited"
    assert source_provenance(db, plain.id)["qualification_basis"] is None


def test_a_curated_stamp_admits_the_source_to_collection(db):
    """The point of the ruling: the row joins regular collection without a trial."""
    from src.scheduler.runner import select_sources
    from src.scheduler.settings import SchedulerSettings

    s = _src(db, "curated.example")
    before = [x.id for x in select_sources(db, SchedulerSettings()).all()]
    stamp_curated_catalog(db, now=NOW)
    after = [x.id for x in select_sources(db, SchedulerSettings()).all()]
    assert before == [] and after == [s.id]


def test_the_ui_strings_are_keyed_in_every_locale():
    """The pill's basis strings are built in app-sources.js; the i18n gate scans index.html,
    so a key added only there would be a silent English leak in eleven languages."""
    import json

    js = (_ROOT / "src" / "static" / "app-sources.js").read_text(encoding="utf-8")
    assert "qualification_basis" in js and 't("by catalogue")' in js
    for lang in ("en", "fr", "es", "de", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id"):
        data = json.loads((_ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        assert "by catalogue" in data, lang
        assert any(k.startswith("Qualified because it ships in the curated catalogue") for k in data), lang


# ------------------------------------------------------------------ the boot wiring

def _calls_with_binding(src: str, name: str) -> list[int]:
    """Line numbers of `name(...)` calls whose enclosing function (or module) binds `name`
    -- an import in another function does not count (the overlay test's own helper)."""
    tree = ast.parse(src)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def binds(scope: ast.AST, ident: str) -> bool:
        for n in ast.walk(scope):
            if isinstance(n, ast.ImportFrom) and any((a.asname or a.name) == ident for a in n.names):
                return True
        return False

    out: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == name):
            continue
        scope: ast.AST | None = node
        while scope is not None:
            if isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and binds(scope, name):
                out.append(node.lineno)
                break
            scope = parents.get(scope)
    return out


def test_both_boot_paths_stamp_the_curated_catalogue_after_the_overlay():
    """main.py seeds in TWO places; a stamp reaching one of them is the recorded
    gate-every-entry-point defect. And the ORDER matters: the overlay must land first so a
    shipped measured verdict wins -- pinned by line position at each site."""
    src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    stamps = _calls_with_binding(src, "stamp_curated_catalog")
    overlays = _calls_with_binding(src, "apply_overlay")
    assert len(stamps) == 2, f"expected the stamp at BOTH boot seeding sites, found {stamps}"
    assert len(overlays) == 2
    for stamp_line in stamps:
        preceding = [o for o in overlays if o < stamp_line]
        assert preceding, f"stamp at line {stamp_line} is not preceded by apply_overlay"
        assert stamp_line - max(preceding) < 40, "the stamp must follow its site's overlay call"


# ------------------------------------- the scope, on an install older than the tagging

# FIELD REPORT, 2026-09-11: "I just reinstalled / updated the app on an older instance, and
# notice that there are only 2600 sources collecting, which contradicts our recent pushes
# qualifying over 5000 sources."
#
# It did. The stamp scoped on the ``via:`` provenance TAG, which is a fact about the ROW --
# written by the seeder when it CREATES one. Three things then compose into a permanent
# strand:
#
#   1. ``via:`` tagging entered the seeder on 2026-06-08, so every older row carries none;
#   2. ``reconcile_source_metadata`` STRIPS the marker on purpose when healing an existing
#      row (copying it "would assert an origin this row may not have" -- which is right);
#   3. ``tags`` is deliberately outside the catalogue-corrections merge.
#
# So a pre-tagging row could never acquire one, stayed ``unqualified``, and
# ``select_sources`` admits only ``qualified`` -- it never collected, however many times the
# app was updated. Reproduced against the real 6,195-row catalogue: 3,000 planted legacy
# rows, run the boot sequence, and "Sources (collecting)" read 3,195 -- exactly the rows the
# update had CREATED. The same run with the one tag added read 6,195.
#
# The fix asks the CATALOGUE instead: is this domain one we ship? That is the question the
# 2026-09-10 ruling actually poses ("the curated catalogue is qualified"), it is checkable
# rather than inferred, and it asserts nothing about where the row came from.

def _a_real_catalogue_domain() -> str:
    """A domain the shipped curated catalogue really carries. Read, never hardcoded, so
    this cannot rot into a test about a domain the project has since dropped."""
    data = yaml.safe_load((_ROOT / "configs" / "sources.yml").read_text(encoding="utf-8"))
    for entry in data["sources"]:
        domain = str(entry.get("domain") or "").strip().lower()
        if domain:
            return domain
    raise AssertionError("configs/sources.yml carries no usable domain")


def test_a_row_predating_the_via_tagging_is_still_admitted_by_the_catalogue(db):
    """THE REGRESSION. No provenance tag at all, because the row predates tagging -- and a
    domain the curated catalogue ships. Before the fix this was out of scope and stayed
    unqualified for the life of the install."""
    legacy = _src(db, _a_real_catalogue_domain(), tags="news,politics")
    out = stamp_curated_catalog(db, now=NOW)
    db.refresh(legacy)
    assert legacy.status == STATUS_QUALIFIED, (
        "a catalogue domain whose row predates via: tagging is still stranded -- it will "
        "never be collected, which is the field report this fixed"
    )
    assert out["stamped"] == 1
    assert _attempts(db, legacy) == [VERDICT_CURATED], (
        "the basis must still read as a RULING, never as a measurement"
    )


def test_an_untagged_row_the_catalogue_does_NOT_ship_is_still_untouched(db):
    """THE BOUNDARY, and the reason the old scope was cautious. Widening from "the seeder
    made this row" to "we ship this domain" must not widen to "anything untagged": a
    hand-added source is the operator's, and the ruling says nothing about it."""
    mine = _src(db, "my-private-wiki.example", tags="news,politics")
    out = stamp_curated_catalog(db, now=NOW)
    db.refresh(mine)
    assert mine.status == STATUS_UNQUALIFIED, (
        "a hand-added domain outside every shipped catalogue was admitted by ruling -- "
        "the ruling admits the CATALOGUE, not whatever happens to carry no tag"
    )
    assert out["stamped"] == 0 and out["curated"] == 0


def test_the_provenance_tag_still_admits_a_domain_the_catalogue_has_since_dropped(db):
    """THE OTHER HALF, which is why the scope is an OR and not a replacement. A row the
    seeder really did create keeps its admission even after the domain leaves the shipped
    file -- otherwise a catalogue edit would silently un-qualify a running instance."""
    retired = _src(db, "dropped-from-the-catalogue.example", tags="news,via:curated")
    stamp_curated_catalog(db, now=NOW)
    db.refresh(retired)
    assert retired.status == STATUS_QUALIFIED


def test_a_measured_refusal_on_a_catalogue_domain_is_still_never_laundered(db):
    """The widened scope must not widen what the stamp OVERRIDES. A domain we ship, that
    this instance measured and refused, keeps its verdict -- the ruling admits the
    catalogue, it does not overturn a judgement."""
    refused = _src(db, _a_real_catalogue_domain(), status=STATUS_DISQUALIFIED)
    out = stamp_curated_catalog(db, now=NOW)
    db.refresh(refused)
    assert refused.status == STATUS_DISQUALIFIED
    assert out["stamped"] == 0 and out["disqualified"] == 1


def test_the_curated_domain_set_is_real_and_bounded():
    """ANTI-VACUITY. An empty set would make the widened scope a no-op and every test above
    would pass on the tag alone; a set containing everything would admit the world."""
    from src.catalog.provenance_scope import (
        CURATED_CATALOGUE_FILES,
        curated_catalogue_domains,
    )

    domains = curated_catalogue_domains()
    assert len(domains) > 1000, f"only {len(domains)} curated domains -- the read is broken"
    assert _a_real_catalogue_domain() in domains
    assert "my-private-wiki.example" not in domains
    assert all(d == d.strip().lower() for d in domains), "domains must be comparable as stored"

    # The GENERATED wikidata catalogue is app-provided but NOT curated (provenance_scope's
    # own distinction), so widening the stamp must not have quietly swept it in.
    assert "world_news_sources.yml" not in CURATED_CATALOGUE_FILES

    # Read once per process: the files ship with the app and cannot change while it runs,
    # and this sits on the boot path beside the seeder, which parses the same files.
    assert curated_catalogue_domains() is domains
