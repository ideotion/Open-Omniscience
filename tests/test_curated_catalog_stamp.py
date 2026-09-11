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
    export = build_overlay_export(db, now=NOW + timedelta(days=201))
    assert export["basis"][BASIS_CURATED] == 0
    assert {v["domain"] for v in export["verdicts"]} == {s.domain}
    assert source_provenance(db, s.id)["qualification_basis"] == "measured"


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
