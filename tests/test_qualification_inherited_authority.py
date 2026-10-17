"""R149: a status held by an INHERITED verdict is not an integrity inversion, and the repair leaves it alone.

A restored sibling feed (R148) and an overlay adoption take another row's verdict and write one ``inherited`` attempt, while
the source can still carry older judging attempts of its own. The four things pinned here, each with a red-without:
both directions of the restore go green; a status set by anything else is still an inversion; a newer judging attempt
overrides the inherited one; and the repair script leaves a held row alone.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.backup.merge import merge_corpus
from src.catalog.qualification_integrity import qualification_integrity_report, repair_inversions
from src.database.models import Source
from src.database.models import SourceQualificationAttempt as A
from tests.test_merge_feed_identity import _META, _corpus, _src

T1, T2, T3 = datetime(2026, 9, 1), datetime(2026, 10, 1), datetime(2026, 10, 2)


def _restore(tmp_path: Path, outlet_status: str, incoming_status: str):
    staged, working = tmp_path / "staged.db", tmp_path / "working.db"
    with _corpus(staged)() as s:
        sid = _src(s, "dw.com", "https://dw.com/old-feed", status=incoming_status)
        s.add(A(source_id=sid, attempted_at=T1, verdict=incoming_status, criteria_version="v"))
        s.commit()
    with _corpus(working)() as s:
        sid = _src(s, "dw.com", "https://dw.com/en", status=outlet_status)
        if outlet_status == "qualified":
            s.query(Source).filter_by(id=sid).one().qualified_at = T1
            s.query(Source).filter_by(id=sid).one().qualification_criteria_version = "oo-qual-7"
        _src(s, "dw.com", "https://dw.com/de", status="unqualified")
        s.commit()
    merge_corpus(staged, working, _META)
    return _corpus(working)


def _imported(session, *attempt_ids, source_ids=()):
    """Name rows in ``merged_rows`` as a backup merge would: these attempts (and sources) arrived from another instance."""
    from src.database.models import MergeBatch, MergedRow

    batch = MergeBatch()
    session.add(batch)
    session.flush()
    for i in attempt_ids:
        session.add(MergedRow(batch_id=batch.id, table_name="source_qualification_attempts", row_id=i))
    for i in source_ids:
        session.add(MergedRow(batch_id=batch.id, table_name="sources", row_id=i))
    session.commit()


def _check(session):
    return qualification_integrity_report(session), repair_inversions(session, dry_run=True)


def test_a_restore_under_a_disqualified_outlet_holds_its_status_without_an_inversion(tmp_path):
    with _restore(tmp_path, "disqualified", "qualified")() as s:
        sib = s.query(Source).filter_by(rss_url="https://dw.com/old-feed").one()
        assert sib.status == "disqualified"  # R148/R153: the outlet's disqualification, not the incoming qualified
        report, repair = _check(s)
        assert report["inversions_total"] == 0 and report["laundered_total"] == 0
        assert report["status_held_by_inherited_verdict_total"] == 1  # named, not silently clean
        assert report["status_held_by_inherited_verdict"][0]["domain"] == "dw.com"
        # not called clean in silence: the verdict's own words name the held rows
        assert report["verdict"] == "consistent" and "INHERITED" in report["reason"]
        assert repair["restored_to_qualified_total"] == 0 and repair["restored_to_disqualified_total"] == 0
        assert repair["held_by_inherited_verdict"] == 1


def test_a_restore_under_a_qualified_outlet_keeps_the_incoming_disqualified_on_its_own_evidence(tmp_path):
    """R153: nothing is handed on in the qualified direction, so the feed stays disqualified WITH its own judging
    attempt behind it: consistent, nothing held, nothing for the repair to undo."""
    with _restore(tmp_path, "qualified", "disqualified")() as s:
        sib = s.query(Source).filter_by(rss_url="https://dw.com/old-feed").one()
        assert sib.status == "disqualified"
        report, repair = _check(s)
        assert report["inversions_total"] == 0 and report["laundered_total"] == 0
        assert report["status_held_by_inherited_verdict_total"] == 0
        assert repair["restored_to_qualified_total"] == 0 and repair["held_by_inherited_verdict"] == 0


def _judged(session, status, *, qualified_at=None, extra=(), judging_imported=True):
    sid = _src(session, "x.com", "https://x.com/f", status=status)
    session.query(Source).filter_by(id=sid).one().qualified_at = qualified_at
    session.add(A(source_id=sid, attempted_at=T1, verdict="qualified", criteria_version="v"))
    for at, verdict in extra:
        session.add(A(source_id=sid, attempted_at=at, verdict=verdict, criteria_version="v"))
    session.commit()
    # the INHERITED row is this install's (not named in merged_rows); the judging ones arrived from another instance
    if judging_imported:
        _imported(session, *[a.id for a in session.query(A).filter(A.source_id == sid, A.verdict != "inherited")])
    return sid


def test_a_status_set_by_anything_else_is_still_an_inversion(tmp_path):
    # an inherited row newer than the judging one cannot vouch for 'unqualified' (no verdict) ...
    with _corpus(tmp_path / "a.db")() as s:
        _judged(s, "unqualified", extra=[(T2, "inherited")])
        report, _ = _check(s)
        assert report["inversions_total"] == 1 and report["status_held_by_inherited_verdict_total"] == 0
    # ... nor for a 'qualified' that carries no stamp date
    with _corpus(tmp_path / "c.db")() as s:
        sid = _src(s, "y.com", "https://y.com/f", status="qualified")
        s.add(A(source_id=sid, attempted_at=T1, verdict="disqualified", criteria_version="v"))
        s.add(A(source_id=sid, attempted_at=T2, verdict="inherited", criteria_version="v"))
        s.commit()
        _imported(s, *[a.id for a in s.query(A).filter(A.source_id == sid, A.verdict == "disqualified")])  # judged disqualified, inherited newer, live 'qualified' with no qualified_at: not held
        report, _ = _check(s)
        assert report["inversions_total"] == 1 and report["status_held_by_inherited_verdict_total"] == 0


def test_a_newer_judging_attempt_overrides_the_inherited_one(tmp_path):
    with _corpus(tmp_path / "d.db")() as s:
        # judged qualified @T1, inherited @T2, judged qualified again @T3, but the status says disqualified
        _judged(s, "disqualified", extra=[(T2, "inherited"), (T3, "qualified")])
        report, _ = _check(s)
        assert report["inversions_total"] == 1 and report["status_held_by_inherited_verdict_total"] == 0


def test_the_repair_script_leaves_a_held_row_alone(tmp_path):
    with _restore(tmp_path, "disqualified", "qualified")() as s:
        out = repair_inversions(s, dry_run=False)
        s.commit()
        assert out["reconciled_total"] == 0
        assert s.query(Source).filter_by(rss_url="https://dw.com/old-feed").one().status == "disqualified"


def _merge_into(tmp_path, local_status, incoming_history, *, local_attempt_at=None):
    """Instance A holds feed x.com/f; instance B's backup carries the same feed with ``incoming_history``; merged for real."""
    staged, working = tmp_path / "staged.db", tmp_path / "working.db"
    with _corpus(staged)() as s:
        sid = _src(s, "x.com", "https://x.com/f", status="qualified" if local_status == "disqualified" else "disqualified")
        s.query(Source).filter_by(id=sid).one().qualified_at = T3 if local_status == "disqualified" else None
        for at, verdict in incoming_history:
            s.add(A(source_id=sid, attempted_at=at, verdict=verdict, criteria_version="v"))
        s.commit()
    with _corpus(working)() as s:
        sid = _src(s, "x.com", "https://x.com/f", status=local_status)
        s.query(Source).filter_by(id=sid).one().qualified_at = T1 if local_status == "qualified" else None
        s.add(A(source_id=sid, attempted_at=local_attempt_at or datetime(2026, 8, 1), verdict=local_status, criteria_version="oo-qual-7"))
        s.commit()
    merge_corpus(staged, working, _META)
    return _corpus(working)


def test_an_inherited_row_copied_in_by_a_merge_does_not_hide_a_laundered_status(tmp_path):
    """The second read's HIGH: instance B's [judging, inherited] pair arrives under a source this install measured itself.
    The inherited row records how ANOTHER instance set ITS status; A's own measurement is contradicted by a newer judgement
    and must stay an inversion, in both directions."""
    for local, incoming_judging in (("qualified", "disqualified"), ("disqualified", "qualified")):
        sub = tmp_path / local
        sub.mkdir()
        with _merge_into(sub, local, [(T2, incoming_judging), (T3, "inherited")])() as s:
            report, repair = _check(s)
            assert report["inversions_total"] == 1 and report["status_held_by_inherited_verdict_total"] == 0, local
            assert repair["held_by_inherited_verdict"] == 0


def test_an_adoption_never_overrides_a_judgement_this_install_made(tmp_path):
    """The overlay adopts onto a row reading 'unqualified' even when it carries a LOCAL disqualification; the newest
    judging attempt being this install's own, the status is not held by the adoption."""
    with _corpus(tmp_path / "e.db")() as s:
        _judged(s, "disqualified", extra=[(T2, "inherited")], judging_imported=False)  # judged qualified here, adopted disqualified
        report, _ = _check(s)
        assert report["inversions_total"] == 1 and report["status_held_by_inherited_verdict_total"] == 0


def test_a_same_timestamp_tie_between_the_judgement_and_the_inherited_row_is_broken_by_append_order(tmp_path):
    """Both rows share one ``attempted_at``: the inherited row holds the status only when it was appended AFTER the judgement."""
    for order, held in ((("qualified", "inherited"), 1), (("inherited", "qualified"), 0)):
        with _corpus(tmp_path / f"t{held}.db")() as s:
            sid = _src(s, "t.com", "https://t.com/f", status="disqualified")
            for verdict in order:
                s.add(A(source_id=sid, attempted_at=T1, verdict=verdict, criteria_version="v"))
                s.flush()
            s.commit()
            _imported(s, *[a.id for a in s.query(A).filter(A.source_id == sid, A.verdict == "qualified")])
            report, _ = _check(s)
            assert report["status_held_by_inherited_verdict_total"] == held and report["inversions_total"] == 1 - held
