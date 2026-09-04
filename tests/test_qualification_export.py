"""
The EXPORT half of the accumulation loop (maintainer ask 2026-09-04) and the merge script
that combines several instances' exports into the shipped overlay.

The round trip is the point: what one instance exports must be exactly what the next fresh
install adopts, so these tests drive the real exporter into the real overlay loader rather
than asserting a schema twice.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import (
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_INHERITED,
    VERDICT_NO_EVIDENCE,
)
from src.catalog.qualification_export import (
    BASIS_INHERITED,
    BASIS_MEASURED,
    build_overlay_export,
    to_overlay_yaml,
)
from src.catalog.qualification_overlay import apply_overlay, load_overlay
from src.database.models import Base, Source, SourceQualificationAttempt

NOW = datetime(2026, 9, 4, tzinfo=UTC)
_ROOT = Path(__file__).resolve().parents[1]


def _merge_script():
    spec = importlib.util.spec_from_file_location(
        "merge_sq", _ROOT / "scripts" / "merge_source_qualification.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _src(db, domain, status, *, tags="news,via:curated", qualified_at=None, judged=True):
    s = Source(name=domain, domain=domain, status=status, tags=tags,
               qualified_at=qualified_at, qualification_criteria_version="t")
    db.add(s)
    db.commit()
    if judged and status in (STATUS_QUALIFIED, STATUS_DISQUALIFIED):
        db.add(SourceQualificationAttempt(
            source_id=s.id, attempted_at=qualified_at or NOW, verdict=status,
            criteria_version="t",
        ))
        db.commit()
    return s


# ------------------------------------------------------------------- export

def test_the_export_carries_both_verdict_kinds(db):
    _src(db, "good.example", STATUS_QUALIFIED, qualified_at=NOW)
    _src(db, "bad.example", STATUS_DISQUALIFIED)
    out = build_overlay_export(db, now=NOW)
    assert {v["domain"]: v["status"] for v in out["verdicts"]} == {
        "good.example": STATUS_QUALIFIED, "bad.example": STATUS_DISQUALIFIED,
    }
    assert out["split"]["qualified"] == 1 and out["split"]["disqualified"] == 1


def test_the_pending_list_is_a_first_class_figure(db):
    """"900 qualified" and "900 qualified of 3,600" are different states of the world, and
    the verdict list alone shows only the first."""
    _src(db, "good.example", STATUS_QUALIFIED, qualified_at=NOW)
    for i in range(3):
        _src(db, f"pending{i}.example", STATUS_UNQUALIFIED)
    out = build_overlay_export(db, now=NOW)
    assert out["split"] == {"qualified": 1, "disqualified": 0, "pending": 3, "total": 4}
    assert len(out["pending_sample"]) == 3


def test_a_source_the_app_found_for_itself_is_not_exported(db):
    """A verdict for a domain no shipped catalog contains would adopt onto nothing on a
    fresh install -- so it is counted, never shipped, and never silently dropped."""
    _src(db, "shipped.example", STATUS_QUALIFIED, qualified_at=NOW)
    _src(db, "found.example", STATUS_QUALIFIED, tags="news,via:wikidata-discovery",
         qualified_at=NOW)
    out = build_overlay_export(db, now=NOW)
    assert [v["domain"] for v in out["verdicts"]] == ["shipped.example"]
    assert out["scope"]["judged_but_not_app_provided"] == 1


def test_the_shipped_wikidata_catalog_is_not_confused_with_discovery(db):
    """The trap provenance_scope documents: `via:wikidata` ships with the app,
    `via:wikidata-discovery` does not, and a substring match captures both."""
    _src(db, "catalog.example", STATUS_QUALIFIED, tags="news,via:wikidata", qualified_at=NOW)
    _src(db, "found.example", STATUS_QUALIFIED, tags="news,via:wikidata-discovery",
         qualified_at=NOW)
    out = build_overlay_export(db, now=NOW)
    assert [v["domain"] for v in out["verdicts"]] == ["catalog.example"]


def test_an_inherited_verdict_is_labelled_as_such(db):
    """Two instances agreeing about a verdict one of them merely copied is one measurement
    seen twice. Without this label a merge would count an echo as corroboration."""
    _src(db, "mine.example", STATUS_QUALIFIED, qualified_at=NOW)
    adopted = _src(db, "theirs.example", STATUS_QUALIFIED, qualified_at=NOW, judged=False)
    db.add(SourceQualificationAttempt(
        source_id=adopted.id, attempted_at=NOW, verdict=VERDICT_INHERITED, criteria_version="t"
    ))
    db.commit()

    basis = {v["domain"]: v["basis"] for v in build_overlay_export(db, now=NOW)["verdicts"]}
    assert basis == {"mine.example": BASIS_MEASURED, "theirs.example": BASIS_INHERITED}


def test_a_no_evidence_attempt_is_not_a_measurement(db):
    """`no_evidence` records that a judgement did NOT happen."""
    s = _src(db, "x.example", STATUS_QUALIFIED, qualified_at=NOW, judged=False)
    db.add(SourceQualificationAttempt(
        source_id=s.id, attempted_at=NOW, verdict=VERDICT_NO_EVIDENCE, criteria_version="t"
    ))
    db.commit()
    assert build_overlay_export(db, now=NOW)["verdicts"][0]["basis"] == BASIS_INHERITED


def test_the_export_carries_the_date_the_verdict_was_reached(db):
    """Re-stamping on export would restart the six-month clock on every accumulation run --
    an expiry that can never fire."""
    earned = NOW - timedelta(days=200)
    _src(db, "old.example", STATUS_QUALIFIED, qualified_at=earned)
    got = build_overlay_export(db, now=NOW)["verdicts"][0]["qualified_at"]
    assert got.startswith(earned.date().isoformat())


# -------------------------------------------------------------- round trip

def test_an_export_is_adopted_verbatim_by_a_fresh_install(db, tmp_path):
    """THE property the whole feature rests on: same schema out as in."""
    earned = NOW - timedelta(days=10)
    _src(db, "good.example", STATUS_QUALIFIED, qualified_at=earned)
    _src(db, "bad.example", STATUS_DISQUALIFIED)
    overlay_file = tmp_path / "source_qualification.yml"
    overlay_file.write_text(to_overlay_yaml(build_overlay_export(db, now=NOW)), encoding="utf-8")

    # A brand-new install: the same catalog domains, nothing judged.
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    fresh = sessionmaker(bind=engine, future=True)()
    for d in ("good.example", "bad.example"):
        fresh.add(Source(name=d, domain=d, status=STATUS_UNQUALIFIED, tags="via:curated"))
    fresh.commit()

    out = apply_overlay(fresh, now=NOW, path=overlay_file)
    assert out["adopted"] == 2
    got = {s.domain: (s.status, s.qualified_at) for s in fresh.query(Source).all()}
    assert got["good.example"][0] == STATUS_QUALIFIED
    assert got["good.example"][1].date() == earned.date(), "the reached date must survive"
    assert got["bad.example"][0] == STATUS_DISQUALIFIED


def test_the_rendered_overlay_is_loadable(db, tmp_path):
    _src(db, "good.example", STATUS_QUALIFIED, qualified_at=NOW)
    p = tmp_path / "o.yml"
    p.write_text(to_overlay_yaml(build_overlay_export(db, now=NOW)), encoding="utf-8")
    assert set(load_overlay(p)) == {"good.example"}


# ------------------------------------------------------------ merge script

def _row(domain, status, at="2026-08-01", basis="measured"):
    return {"domain": domain, "status": status, "qualified_at": at,
            "criteria_version": "t", "basis": basis}


def test_merging_two_instances_accumulates_their_verdicts():
    m = _merge_script()
    out = m.merge([[_row("a.example", "qualified")], [_row("b.example", "qualified")]],
                  {}, accept_newest=False)
    assert set(out["merged"]) == {"a.example", "b.example"}
    assert out["report"]["added"] == 2


def test_a_disagreement_is_reported_and_never_auto_resolved():
    """Picking a winner automatically would ship a verdict no human looked at, to every
    install, silently."""
    m = _merge_script()
    out = m.merge(
        [[_row("x.example", "qualified", "2026-08-01")],
         [_row("x.example", "disqualified", "2026-08-20")]],
        {}, accept_newest=False,
    )
    assert out["merged"] == {}
    assert [c["domain"] for c in out["report"]["conflicts"]] == ["x.example"]


def test_accept_newest_resolves_only_when_asked():
    m = _merge_script()
    out = m.merge(
        [[_row("x.example", "qualified", "2026-08-01")],
         [_row("x.example", "disqualified", "2026-08-20")]],
        {}, accept_newest=True,
    )
    assert out["merged"]["x.example"]["status"] == "disqualified"
    assert out["report"]["conflicts"], "resolving it does not make it not a finding"


def test_an_inherited_row_is_not_counted_as_corroboration():
    """Importing one backup into eight instances must not manufacture eightfold agreement:
    agreement is counted over MEASURED rows, so a lone measurement beats seven echoes of
    the other verdict rather than being outvoted by them."""
    m = _merge_script()
    out = m.merge(
        [[_row("x.example", "disqualified", "2026-08-20", basis="measured")]]
        + [[_row("x.example", "qualified", "2026-08-25", basis="inherited")]] * 7,
        {}, accept_newest=False,
    )
    assert out["report"]["conflicts"] == []
    assert out["merged"]["x.example"]["status"] == "disqualified"


def test_existing_entries_the_exports_do_not_mention_are_carried_through():
    """Merging one instance's export must not drop what the others contributed."""
    m = _merge_script()
    existing = {"old.example": {"domain": "old.example", "status": "qualified",
                                "qualified_at": "2026-01-01", "criteria_version": "t"}}
    out = m.merge([[_row("new.example", "qualified")]], existing, accept_newest=False)
    assert out["merged"]["old.example"] == existing["old.example"]
    assert out["report"]["carried_through_untouched"] == 1


def test_the_merge_never_restamps_a_date():
    m = _merge_script()
    out = m.merge([[_row("a.example", "qualified", "2025-03-04")]], {}, accept_newest=False)
    assert out["merged"]["a.example"]["qualified_at"] == "2025-03-04"


def test_a_dateless_verdict_cannot_win_a_disagreement_by_default():
    """Being undated is not being recent."""
    m = _merge_script()
    out = m.merge(
        [[_row("x.example", "qualified", None)],
         [_row("x.example", "disqualified", "2026-08-20")]],
        {}, accept_newest=True,
    )
    assert out["merged"]["x.example"]["status"] == "disqualified"


def test_unshippable_rows_are_skipped_not_coerced():
    m = _merge_script()
    out = m.merge([[_row("a.example", "unqualified"), _row("", "qualified")]],
                  {}, accept_newest=False)
    assert out["merged"] == {} and out["report"]["skipped_rows"] == 2


def test_the_merge_output_is_what_the_loader_reads(tmp_path):
    """End of the loop: the script's own file must load, or accumulation writes something
    the app cannot adopt."""
    m = _merge_script()
    out = m.merge([[_row("a.example", "qualified", "2026-08-01")]], {}, accept_newest=False)
    p = tmp_path / "source_qualification.yml"
    p.write_text(m.render(out["merged"]), encoding="utf-8")
    got = load_overlay(p)
    assert got["a.example"]["status"] == "qualified"
    assert got["a.example"]["qualified_at"].date().isoformat() == "2026-08-01"


def test_the_cli_reports_and_can_write_nothing(tmp_path, capsys):
    m = _merge_script()
    exp = tmp_path / "e.json"
    exp.write_text(json.dumps({"verdicts": [_row("a.example", "qualified")]}), encoding="utf-8")
    target = tmp_path / "out.yml"
    assert m.main([str(exp), "-o", str(target), "--dry-run"]) == 0
    assert not target.exists(), "--dry-run must write nothing"
    assert json.loads(capsys.readouterr().out)["added"] == 1
