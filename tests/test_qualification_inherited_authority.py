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


def _check(session):
    return qualification_integrity_report(session), repair_inversions(session, dry_run=True)


def test_both_restore_directions_hold_their_status_without_an_inversion(tmp_path):
    for outlet, incoming in (("disqualified", "qualified"), ("qualified", "disqualified")):
        sub = tmp_path / outlet
        sub.mkdir()
        with _restore(sub, outlet, incoming)() as s:
            sib = s.query(Source).filter_by(rss_url="https://dw.com/old-feed").one()
            assert sib.status == outlet  # R148: the outlet's verdict, not the incoming one
            report, repair = _check(s)
            assert report["inversions_total"] == 0 and report["laundered_total"] == 0
            assert report["status_held_by_inherited_verdict_total"] == 1  # named, not silently clean
            assert report["status_held_by_inherited_verdict"][0]["domain"] == "dw.com"
            assert repair["restored_to_qualified_total"] == 0 and repair["restored_to_disqualified_total"] == 0
            assert repair["held_by_inherited_verdict"] == 1


def _judged(session, status, *, qualified_at=None, extra=()):
    sid = _src(session, "x.com", "https://x.com/f", status=status)
    session.query(Source).filter_by(id=sid).one().qualified_at = qualified_at
    session.add(A(source_id=sid, attempted_at=T1, verdict="qualified", criteria_version="v"))
    for at, verdict in extra:
        session.add(A(source_id=sid, attempted_at=at, verdict=verdict, criteria_version="v"))
    session.commit()
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
        s.commit()  # judged disqualified, inherited newer, live 'qualified' with no qualified_at: not held
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
