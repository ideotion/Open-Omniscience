"""The additive restore-merge must carry source QUALIFICATION state.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-24: the maintainer ran 8 parallel app instances (for download
throughput) and merged all 8 backups into one corpus. Two independent gaps meant the
qualification lifecycle did not survive that merge:

  1. ``_merge_sources``' INSERT allowlist omitted ``status`` / ``qualified_at`` /
     ``qualification_criteria_version``. Because ``Source.status`` carries
     ``server_default='unqualified'``, every merged-in source landed UNQUALIFIED.
  2. ``source_qualification_attempts`` had no handler at all — it was in neither
     ``_MERGE_HANDLED`` nor ``_MERGE_IGNORED``, so it fell through to
     ``_unmerged_tables``: counted, never carried. That table is the system of record
     for the re-qualification backoff ladder.

The operational cost was that ``select_sources`` admits only ``status='qualified'``, so
merged sources were excluded from collection until re-trialled over the network. The
SAFETY cost — the reason this is a data-safety fix — is that a source the incoming corpus
had DISQUALIFIED arrived indistinguishable from never-judged, and ``select_unqualified``
selects exactly ``status='unqualified'``: a merge LAUNDERED a known-bad source back into
the trial queue with its ladder reset to zero.

These tests pin both halves, in both directions (carried where it must be, local-wins
preserved where that is the policy).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backup.merge import merge_corpus
from src.database.models import Base, Source, SourceQualificationAttempt

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}

_T0 = datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC).replace(tzinfo=None)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _add_source(s, domain: str, *, status: str, at: datetime | None = None,
                version: str | None = None) -> int:
    src = Source(
        name=domain, domain=domain, status=status,
        qualified_at=at, qualification_criteria_version=version,
    )
    s.add(src)
    s.flush()
    return int(src.id)


def _add_attempt(s, source_id: int, verdict: str, when: datetime,
                 version: str = "nav-soup-v1") -> None:
    s.add(SourceQualificationAttempt(
        source_id=source_id, attempted_at=when, verdict=verdict, criteria_version=version,
    ))


def _sources(path: Path) -> dict[str, Source]:
    with _corpus(path)() as s:
        return {r.domain: r for r in s.query(Source).all()}


def _attempts(path: Path, domain: str) -> list[SourceQualificationAttempt]:
    with _corpus(path)() as s:
        src = s.query(Source).filter_by(domain=domain).one()
        return (
            s.query(SourceQualificationAttempt)
            .filter_by(source_id=src.id)
            .order_by(SourceQualificationAttempt.attempted_at.asc())
            .all()
        )


# --------------------------------------------------------------------------- #
#  The stamp on sources the merge INTRODUCES
# --------------------------------------------------------------------------- #
def test_a_qualified_verdict_survives_the_merge(tmp_path):
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        _add_source(s, "lemonde.fr", status="qualified", at=_T0, version="nav-soup-v1")
        s.commit()
    _corpus(working)  # empty local corpus

    merge_corpus(staged, working, _BATCH_META)

    got = _sources(working)["lemonde.fr"]
    assert got.status == "qualified"
    assert got.qualified_at is not None
    assert got.qualification_criteria_version == "nav-soup-v1"


def test_a_disqualified_source_is_not_laundered_back_into_the_trial_queue(tmp_path):
    """THE data-safety case. A source judged bad on another instance must NOT arrive
    looking never-judged — ``select_unqualified`` filters exactly status=='unqualified',
    so an unqualified arrival silently re-admits a known-bad source for trial with its
    backoff ladder reset."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        sid = _add_source(s, "junk.example", status="disqualified", at=_T0,
                          version="nav-soup-v1")
        _add_attempt(s, sid, "disqualified", _T0)
        s.commit()
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META)

    got = _sources(working)["junk.example"]
    assert got.status == "disqualified", "a disqualified source was laundered to unqualified"
    # And the evidence that produced the verdict came with it.
    assert [a.verdict for a in _attempts(working, "junk.example")] == ["disqualified"]


def test_an_unqualified_source_still_arrives_unqualified(tmp_path):
    """Negative space: carrying the stamp must not invent a verdict for a source that
    genuinely was never judged."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        _add_source(s, "new.example", status="unqualified")
        s.commit()
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META)

    got = _sources(working)["new.example"]
    assert got.status == "unqualified"
    assert got.qualified_at is None
    assert got.qualification_criteria_version is None
    assert _attempts(working, "new.example") == []


# --------------------------------------------------------------------------- #
#  The attempt HISTORY (the ladder's system of record)
# --------------------------------------------------------------------------- #
def test_attempt_history_is_carried_with_remapped_source_ids(tmp_path):
    """source ids differ between corpora, so the history must ride temp.map_sources.
    Seed the local corpus with a decoy so the incoming id cannot coincidentally match."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        for n in range(4):  # decoys: local ids 1..4 are taken
            _add_source(s, f"decoy{n}.example", status="unqualified")
        s.commit()
    with _corpus(staged)() as s:
        sid = _add_source(s, "tracked.example", status="disqualified", at=_T0)
        _add_attempt(s, sid, "disqualified", _T0)
        _add_attempt(s, sid, "disqualified", _T0 + timedelta(days=30))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    rows = _attempts(working, "tracked.example")
    assert len(rows) == 2, "attempt history was dropped or mis-mapped"
    local_id = _sources(working)["tracked.example"].id
    assert {r.source_id for r in rows} == {local_id}, "source_id was not remapped"


def test_re_importing_the_same_backup_does_not_duplicate_attempts(tmp_path):
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        sid = _add_source(s, "repeat.example", status="disqualified", at=_T0)
        _add_attempt(s, sid, "disqualified", _T0)
        s.commit()
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META)
    merge_corpus(staged, working, _BATCH_META)  # the same artifact again

    assert len(_attempts(working, "repeat.example")) == 1


def test_two_instances_attempts_on_the_same_domain_both_survive(tmp_path):
    """The maintainer's actual case: 8 instances each trialled the same domain at
    different times. Those are genuinely DISTINCT attempts — dedup is on
    (source_id, attempted_at), so both must survive rather than collapsing."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        sid = _add_source(s, "shared.example", status="unqualified")
        _add_attempt(s, sid, "disqualified", _T0)  # instance A's attempt
        s.commit()
    with _corpus(staged)() as s:
        sid = _add_source(s, "shared.example", status="disqualified", at=_T0)
        _add_attempt(s, sid, "disqualified", _T0 + timedelta(days=31))  # instance B's
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    rows = _attempts(working, "shared.example")
    assert len(rows) == 2, "a distinct attempt from another instance was lost"


# --------------------------------------------------------------------------- #
#  Local-wins is UNCHANGED for a domain that already exists locally
# --------------------------------------------------------------------------- #
def test_an_existing_local_source_keeps_its_own_stamp(tmp_path):
    """The merge's standing policy: for a domain already present, the local row wins
    untouched. Carrying the stamp must not turn the merge into an UPDATE."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        _add_source(s, "both.example", status="qualified", at=_T0, version="local-v1")
        s.commit()
    with _corpus(staged)() as s:
        _add_source(s, "both.example", status="disqualified", at=_T0, version="incoming-v9")
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    got = _sources(working)["both.example"]
    assert got.status == "qualified", "local-wins was broken — the merge overwrote a verdict"
    assert got.qualification_criteria_version == "local-v1"


def test_an_existing_source_still_gains_the_incoming_attempt_history(tmp_path):
    """The other half of local-wins: the local VERDICT is untouched, but the incoming
    EVIDENCE still accumulates into the shared history — which is what keeps the
    re-qualification ladder honest across a multi-instance merge."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        _add_source(s, "both.example", status="qualified", at=_T0, version="local-v1")
        s.commit()
    with _corpus(staged)() as s:
        sid = _add_source(s, "both.example", status="disqualified", at=_T0)
        _add_attempt(s, sid, "disqualified", _T0 + timedelta(days=5))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    rows = _attempts(working, "both.example")
    assert [r.verdict for r in rows] == ["disqualified"], (
        "an existing source's incoming attempt history was dropped"
    )


def test_the_merged_history_drives_the_real_ladder(tmp_path):
    """End-to-end through the production reader: the ladder counts the trailing run of
    'disqualified' verdicts, so a merged-in history must actually move it."""
    from src.catalog.qualification import consecutive_disqualifications

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        sid = _add_source(s, "laddered.example", status="disqualified", at=_T0)
        _add_attempt(s, sid, "disqualified", _T0)
        _add_attempt(s, sid, "disqualified", _T0 + timedelta(days=30))
        _add_attempt(s, sid, "disqualified", _T0 + timedelta(days=90))
        s.commit()
    _corpus(working)

    merge_corpus(staged, working, _BATCH_META)

    with _corpus(working)() as s:
        src = s.query(Source).filter_by(domain="laddered.example").one()
        assert consecutive_disqualifications(s, src.id) == 3, (
            "the merged history did not reach the ladder — it would have reset to 0"
        )


def test_the_attempts_table_is_registered_as_handled(tmp_path):
    """It must leave _unmerged_tables: a table reported as 'not merged' on every restore
    is exactly how this gap stayed invisible."""
    from src.backup.merge import _MERGE_HANDLED, _MERGE_IGNORED

    assert "source_qualification_attempts" in _MERGE_HANDLED
    assert "source_qualification_attempts" not in _MERGE_IGNORED


# --------------------------------------------------------------------------- #
#  The EXPORT side
# --------------------------------------------------------------------------- #
def test_the_export_snapshot_carries_the_qualification_state(tmp_path):
    """The export half of the round trip. ``snapshot_sqlite`` (the primitive every
    backup path uses to capture the corpus member — the single-file artifact via
    ``_collect_members``, and the volume/stream path via its own corpus member) is a
    whole-database copy through SQLite's online backup API, so qualification state has
    always been IN the backup; the 2026-07-24 loss was purely on the import side.

    Nothing pinned that, though, and an export-side regression would silently empty the
    import fix above. This guards the export end explicitly: both the stamp columns and
    the attempt history must survive a snapshot."""
    from src.backup.artifact import snapshot_sqlite

    live = tmp_path / "live.db"
    with _corpus(live)() as s:
        sid = _add_source(s, "exported.example", status="disqualified", at=_T0,
                          version="nav-soup-v1")
        _add_attempt(s, sid, "disqualified", _T0)
        _add_attempt(s, sid, "disqualified", _T0 + timedelta(days=30))
        s.commit()

    snap = tmp_path / "corpus-snapshot.db"
    snapshot_sqlite(live, snap)

    got = _sources(snap)["exported.example"]
    assert got.status == "disqualified", "the export dropped the qualification stamp"
    assert got.qualification_criteria_version == "nav-soup-v1"
    assert len(_attempts(snap, "exported.example")) == 2, (
        "the export dropped the qualification attempt history"
    )


def test_export_then_import_round_trips_a_disqualified_verdict(tmp_path):
    """End to end across BOTH halves: snapshot an instance's corpus the way a backup
    does, then merge that snapshot into a different corpus the way a restore does. This
    is the maintainer's actual multi-instance workflow in miniature, and the property
    that matters most — a known-bad source stays known-bad on the other side."""
    from src.backup.artifact import snapshot_sqlite

    instance_a = tmp_path / "instance_a.db"
    with _corpus(instance_a)() as s:
        sid = _add_source(s, "junk.example", status="disqualified", at=_T0)
        _add_attempt(s, sid, "disqualified", _T0)
        _add_attempt(s, sid, "disqualified", _T0 + timedelta(days=30))
        _add_source(s, "good.example", status="qualified", at=_T0, version="nav-soup-v1")
        s.commit()

    exported = tmp_path / "backup-corpus.db"
    snapshot_sqlite(instance_a, exported)

    merged = tmp_path / "merged.db"
    _corpus(merged)
    merge_corpus(exported, merged, _BATCH_META)

    rows = _sources(merged)
    assert rows["junk.example"].status == "disqualified"
    assert rows["good.example"].status == "qualified"
    assert len(_attempts(merged, "junk.example")) == 2


# --------------------------------------------------------------------------- #
#  ADOPTION: a never-judged local source takes the incoming verdict
#
#  Field report 2026-08-10: "Export and import should integrate source having been
#  qualified ... Currently I don't see this working." The 2026-07-24 fix above stamps
#  sources the merge INTRODUCES — but the maintainer runs many instances all seeded
#  from the SAME catalog, so essentially every incoming domain ALREADY EXISTS locally,
#  the INSERT skips it, and local-wins left it at server_default='unqualified'. That is
#  local-wins defending a NON-judgement: 'unqualified' means no verdict was reached
#  here, so there is nothing to defend and adopting is pure information gain.
# --------------------------------------------------------------------------- #
def test_a_never_judged_local_source_adopts_an_incoming_qualified_verdict(tmp_path):
    """THE field case. Same domain on both sides; judged there, never judged here."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        _add_source(s, "shared.example", status="unqualified")
        s.commit()
    with _corpus(staged)() as s:
        _add_source(s, "shared.example", status="qualified", at=_T0, version="oo-v1")
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    got = _sources(working)["shared.example"]
    assert got.status == "qualified", (
        "a source qualified on another instance stayed unqualified here — the "
        "qualification work of every other instance is invisible"
    )
    # The stamp travels with the verdict, or "qualified by OO on DATE" has no date.
    assert got.qualified_at == _T0
    assert got.qualification_criteria_version == "oo-v1"


def test_a_never_judged_local_source_adopts_an_incoming_disqualified_verdict(tmp_path):
    """The SAFETY direction, and the reason adoption is not gated to 'qualified' only:
    a source another instance found bad must not keep being trialled here from scratch."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        _add_source(s, "junk.example", status="unqualified")
        s.commit()
    with _corpus(staged)() as s:
        _add_source(s, "junk.example", status="disqualified", at=None, version="oo-v1")
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    assert _sources(working)["junk.example"].status == "disqualified"


# --------------------------------------------------------------------------- #
#  The twins: adoption must never overwrite a verdict reached HERE
# --------------------------------------------------------------------------- #
def test_a_local_disqualification_is_never_laundered_by_an_incoming_qualified_verdict(tmp_path):
    """The direction that makes adoption dangerous, and the one no existing test
    covered: the merge must not let an incoming corpus overturn a disqualification this
    instance reached itself. That is the same laundering the 2026-07-24 fix closed,
    arriving by the opposite route."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        _add_source(s, "junk.example", status="disqualified", at=None, version="local-v1")
        s.commit()
    with _corpus(staged)() as s:
        _add_source(s, "junk.example", status="qualified", at=_T0, version="oo-v1")
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    got = _sources(working)["junk.example"]
    assert got.status == "disqualified", (
        "an incoming backup overturned a local disqualification — a known-bad source "
        "was laundered back into collection"
    )
    assert got.qualified_at is None, "a laundered stamp was written over a disqualification"


def test_a_local_qualified_verdict_is_not_downgraded_by_an_incoming_disqualification(tmp_path):
    """The mirror twin: local-wins is symmetric, so this instance's own 'qualified'
    survives an incoming 'disqualified' too."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        _add_source(s, "both.example", status="qualified", at=_T0, version="local-v1")
        s.commit()
    with _corpus(staged)() as s:
        _add_source(s, "both.example", status="disqualified", at=None, version="oo-v1")
        s.commit()

    merge_corpus(staged, working, _BATCH_META)

    got = _sources(working)["both.example"]
    assert got.status == "qualified"
    assert got.qualification_criteria_version == "local-v1"


# --------------------------------------------------------------------------- #
#  The tally the conclusion screen renders
# --------------------------------------------------------------------------- #
def test_the_tally_counts_what_this_import_actually_carried(tmp_path):
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        _add_source(s, "adopt.example", status="unqualified")          # -> adopted
        _add_source(s, "mine.example", status="qualified", at=_T0, version="local-v1")  # kept
        s.commit()
    with _corpus(staged)() as s:
        _add_source(s, "adopt.example", status="qualified", at=_T0, version="oo-v1")
        _add_source(s, "fresh.example", status="qualified", at=_T0, version="oo-v1")   # introduced
        _add_source(s, "mine.example", status="disqualified", at=None, version="oo-v1")
        s.commit()

    counts, _ = merge_corpus(staged, working, _BATCH_META)
    q = counts["_source_qualification"]

    assert q["introduced_qualified"] == 1, "a source the merge added carrying a verdict"
    assert q["adopted_qualified"] == 1, "a never-judged local source taking the verdict"
    assert q["local_verdict_kept"] == 1, "a verdict reached here, left alone"
    assert q["local_verdict_disagreed"] == 1, "and the backup disagreed about it"
    # "by which engine" -- read off the incoming stamp, never inferred.
    assert q["engines"] == {"oo-v1": 2}
    assert q["qualified_at_min"] is not None


def test_an_import_carrying_no_verdict_reports_no_qualification(tmp_path):
    """Negative-space twin: a backup with nothing judged must not produce a block of
    zeroes that reads as a finding about the backup. Absent is not the same as none."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        _add_source(s, "plain.example", status="unqualified")
        s.commit()
    with _corpus(staged)() as s:
        _add_source(s, "plain.example", status="unqualified")
        s.commit()

    counts, _ = merge_corpus(staged, working, _BATCH_META)
    q = counts["_source_qualification"]

    assert q["introduced_qualified"] == 0
    assert q["adopted_qualified"] == 0
    assert q["engines"] == {}, "an engine was attributed to a verdict that does not exist"
    assert _sources(working)["plain.example"].status == "unqualified"


def test_export_then_import_carries_qualification_between_two_seeded_instances(tmp_path):
    """THE maintainer's actual workflow, end to end (field report 2026-08-10).

    Both instances were seeded from the SAME catalog, so both already hold the same
    domains — which is exactly why the earlier round-trip test above (an EMPTY target
    corpus) could not have caught this: with nothing local, every source takes the
    INSERT path and arrives stamped. Here instance A has done the qualification work and
    instance B has not, which is the real shape of importing one instance's backup into
    another."""
    from src.backup.artifact import snapshot_sqlite

    instance_a = tmp_path / "instance_a.db"
    with _corpus(instance_a)() as s:
        sid = _add_source(s, "seeded.example", status="qualified", at=_T0, version="oo-v1")
        _add_attempt(s, sid, "qualified", _T0)
        _add_source(s, "seeded-junk.example", status="disqualified", at=None, version="oo-v1")
        s.commit()

    # Instance B: the SAME catalog domains, none of them judged here yet.
    instance_b = tmp_path / "instance_b.db"
    with _corpus(instance_b)() as s:
        _add_source(s, "seeded.example", status="unqualified")
        _add_source(s, "seeded-junk.example", status="unqualified")
        s.commit()

    exported = tmp_path / "backup-corpus.db"
    snapshot_sqlite(instance_a, exported)
    counts, _ = merge_corpus(exported, instance_b, _BATCH_META)

    rows = _sources(instance_b)
    assert rows["seeded.example"].status == "qualified", (
        "a source qualified on instance A stayed unqualified on instance B — the whole "
        "point of importing a backup from a machine that has done the work"
    )
    assert rows["seeded.example"].qualification_criteria_version == "oo-v1"
    assert rows["seeded-junk.example"].status == "disqualified"
    # Nothing was INTRODUCED — both domains already existed. That is the distinction
    # the conclusion screen has to report, or the count reads as zero on this workflow.
    assert counts["sources"]["new"] == 0
    assert counts["_source_qualification"]["adopted_qualified"] == 1
    assert counts["_source_qualification"]["adopted_disqualified"] == 1
