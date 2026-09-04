"""
The SHIPPED QUALIFICATION OVERLAY (maintainer ruling 2026-09-04): verdicts that travel with
the app so a fresh install starts from what earlier instances measured.

The load-bearing property is that adoption obeys the SAME rule the restore merge obeys --
adopt only onto a never-judged row, local verdict always wins, both directions. Two paths
adopting the same kind of evidence must not disagree about who wins, so the local-wins tests
here are deliberately the mirror of tests/test_merge_source_qualification.py's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import (
    QUALIFIED_RECHECK_MONTHS,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_INHERITED,
    select_due_qualified,
)
from src.catalog.qualification_overlay import apply_overlay, load_overlay
from src.database.models import Base, Source, SourceQualificationAttempt

NOW = datetime(2026, 9, 4, tzinfo=UTC)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _overlay_file(tmp_path: Path, rows: list[dict], **top) -> Path:
    p = tmp_path / "source_qualification.yml"
    p.write_text(yaml.safe_dump({"verdicts": rows, **top}), encoding="utf-8")
    return p


def _src(db, domain, status=STATUS_UNQUALIFIED, *, qualified_at=None):
    s = Source(name=domain, domain=domain, status=status, qualified_at=qualified_at)
    db.add(s)
    db.commit()
    return s


# ------------------------------------------------------------------ loading

def test_an_absent_overlay_is_simply_no_overlay(tmp_path):
    """An install shipping no overlay must behave exactly as it does today."""
    assert load_overlay(tmp_path / "nope.yml") == {}


def test_only_real_verdicts_ship(tmp_path):
    """`unqualified` is the ABSENCE of a verdict and adopts nothing; an unknown value is
    dropped loudly rather than coerced, because this file decides what an install collects."""
    p = _overlay_file(tmp_path, [
        {"domain": "good.example", "status": "qualified"},
        {"domain": "bad.example", "status": "disqualified"},
        {"domain": "noop.example", "status": "unqualified"},
        {"domain": "weird.example", "status": "probably-fine"},
        {"domain": "", "status": "qualified"},
        "not-a-row",
    ])
    assert set(load_overlay(p)) == {"good.example", "bad.example"}


def test_a_broken_overlay_never_blocks_boot(tmp_path):
    p = tmp_path / "source_qualification.yml"
    p.write_text("verdicts: [oh: dear: no", encoding="utf-8")
    assert load_overlay(p) == {}


def test_an_unreadable_stamp_becomes_none_not_now(tmp_path):
    """Inventing a stamp would restart the re-verification clock on a verdict that is
    actually old -- the fabricated freshness the inherited clock exists to prevent."""
    p = _overlay_file(tmp_path, [{"domain": "x.example", "status": "qualified",
                                  "qualified_at": "the fourth of some month"}])
    assert load_overlay(p)["x.example"]["qualified_at"] is None


def test_dates_and_datetimes_both_parse_to_aware_utc(tmp_path):
    p = _overlay_file(tmp_path, [
        {"domain": "a.example", "status": "qualified", "qualified_at": "2026-08-20"},
        {"domain": "b.example", "status": "qualified", "qualified_at": "2026-08-20T11:30:00Z"},
    ])
    got = load_overlay(p)
    for d in ("a.example", "b.example"):
        assert got[d]["qualified_at"].tzinfo is not None
        assert got[d]["qualified_at"].date() == datetime(2026, 8, 20).date()


# ---------------------------------------------------------------- adoption

def test_a_never_judged_source_adopts_a_shipped_qualified_verdict(db, tmp_path):
    """THE point of the feature: a fresh install starts with app-qualified sources."""
    _src(db, "good.example")
    p = _overlay_file(tmp_path, [{"domain": "good.example", "status": "qualified",
                                  "qualified_at": "2026-08-20"}])
    out = apply_overlay(db, now=NOW, path=p)

    s = db.query(Source).filter_by(domain="good.example").one()
    assert s.status == STATUS_QUALIFIED
    assert s.qualified_at.date() == datetime(2026, 8, 20).date()
    assert out["adopted"] == 1 and out["qualified"] == 1


def test_a_never_judged_source_adopts_a_shipped_disqualification(db, tmp_path):
    """The safety direction, and the reason the overlay is a record and not a whitelist: a
    fresh install skips a known-broken source instead of rediscovering it over Tor."""
    _src(db, "bad.example")
    # The row deliberately CARRIES a qualified_at. A fixture without one cannot discriminate:
    # both the correct branch and one that copied the stamp across would produce None, and a
    # mutation that kept the stamp on a disqualified row passed the first version of this
    # test for exactly that reason.
    p = _overlay_file(tmp_path, [{"domain": "bad.example", "status": "disqualified",
                                  "qualified_at": "2026-08-20"}])
    apply_overlay(db, now=NOW, path=p)

    s = db.query(Source).filter_by(domain="bad.example").one()
    assert s.status == STATUS_DISQUALIFIED
    assert s.qualified_at is None, "a disqualified row must carry no 'qualified' stamp"
    assert s.qualification_criteria_version is None


def test_a_local_disqualification_is_never_laundered_by_the_shipped_file(db, tmp_path):
    """The direction that would make shipping verdicts dangerous. Mirrors the merge's own
    guard: a file cannot overturn what this instance measured."""
    _src(db, "bad.example", status=STATUS_DISQUALIFIED)
    p = _overlay_file(tmp_path, [{"domain": "bad.example", "status": "qualified"}])
    out = apply_overlay(db, now=NOW, path=p)

    assert db.query(Source).filter_by(domain="bad.example").one().status == STATUS_DISQUALIFIED
    assert out["adopted"] == 0 and out["kept_local"] == 1


def test_a_local_qualified_verdict_is_not_downgraded_by_the_shipped_file(db, tmp_path):
    """The mirror twin -- local-wins is symmetric, or it is not a policy."""
    earned = NOW - timedelta(days=2)
    _src(db, "mine.example", status=STATUS_QUALIFIED, qualified_at=earned)
    p = _overlay_file(tmp_path, [{"domain": "mine.example", "status": "disqualified"}])
    apply_overlay(db, now=NOW, path=p)

    s = db.query(Source).filter_by(domain="mine.example").one()
    assert s.status == STATUS_QUALIFIED and s.qualified_at.date() == earned.date()


def test_a_domain_absent_from_the_overlay_stays_unqualified(db, tmp_path):
    """Negative space, and the second of the two lists the ask describes: everything the
    overlay does not name still ships unqualified and queues for qualification as today."""
    _src(db, "unknown.example")
    p = _overlay_file(tmp_path, [{"domain": "other.example", "status": "qualified"}])
    apply_overlay(db, now=NOW, path=p)
    assert db.query(Source).filter_by(domain="unknown.example").one().status == STATUS_UNQUALIFIED


def test_adoption_records_that_the_stamp_was_inherited(db, tmp_path):
    """A shipped verdict must never read as local evidence."""
    _src(db, "good.example")
    p = _overlay_file(tmp_path, [{"domain": "good.example", "status": "qualified",
                                  "qualified_at": "2026-08-20"}])
    apply_overlay(db, now=NOW, path=p)

    rows = db.query(SourceQualificationAttempt).all()
    assert [r.verdict for r in rows] == [VERDICT_INHERITED]


def test_an_inherited_shipped_stamp_still_comes_due_on_its_own_age(db, tmp_path):
    """End to end with slice 1: a verdict earned long ago elsewhere and adopted today is
    re-verified promptly, rather than reading as freshly measured here."""
    old = (NOW - timedelta(days=30 * QUALIFIED_RECHECK_MONTHS + 5)).date().isoformat()
    _src(db, "old.example")
    p = _overlay_file(tmp_path, [{"domain": "old.example", "status": "qualified",
                                  "qualified_at": old}])
    apply_overlay(db, now=NOW, path=p)

    due = select_due_qualified(db, now=NOW, limit=5)
    assert [s.domain for s in due] == ["old.example"]


def test_a_recent_shipped_stamp_is_not_immediately_re_verified(db, tmp_path):
    """The twin: adopting must not make a genuinely fresh verdict due, or every fresh
    install would re-trial its whole catalog on day one."""
    _src(db, "fresh.example")
    p = _overlay_file(tmp_path, [
        {"domain": "fresh.example", "status": "qualified",
         "qualified_at": (NOW - timedelta(days=3)).date().isoformat()}
    ])
    apply_overlay(db, now=NOW, path=p)
    assert select_due_qualified(db, now=NOW, limit=5) == []


def test_applying_twice_adopts_once(db, tmp_path):
    """Boot runs this every time; a second pass must be a no-op, not a second attempt row."""
    _src(db, "good.example")
    p = _overlay_file(tmp_path, [{"domain": "good.example", "status": "qualified"}])
    first = apply_overlay(db, now=NOW, path=p)
    second = apply_overlay(db, now=NOW + timedelta(days=1), path=p)

    assert first["adopted"] == 1 and second["adopted"] == 0
    assert db.query(SourceQualificationAttempt).count() == 1


def test_a_source_not_in_the_database_is_ignored(db, tmp_path):
    """The overlay stamps sources the catalog seeds; it never CREATES one. A verdict is not
    a reason to start collecting from a domain nobody put in the catalog."""
    p = _overlay_file(tmp_path, [{"domain": "ghost.example", "status": "qualified"}])
    out = apply_overlay(db, now=NOW, path=p)
    assert out["adopted"] == 0
    assert db.query(Source).count() == 0


# ----------------------------------------------------------------- the wiring

def _calls_with_binding(source: str, name: str) -> list[int]:
    """Line numbers where ``name`` is CALLED and is resolvable from that call's scope.

    A source guard that only looks for the identifier is satisfied by a call whose import
    sits in an unrelated function -- which raises NameError at runtime while the test stays
    green (the recorded ruff-F821-caught defect). So the binding is resolved the way Python
    resolves it: walk outwards from the call through each enclosing function and the module,
    looking for an import alias, an assignment, or a def of that name in that scope's own
    body without descending into nested scopes, which have their own.
    """
    import ast

    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def binds(scope: ast.AST, ident: str) -> bool:
        for node in ast.walk(scope):
            # Do not credit a binding that lives inside a NESTED scope.
            owner = node
            while owner is not scope:
                if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                      ast.Lambda)):
                    break
                owner = parents.get(owner, scope)
            else:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if any((a.asname or a.name.split(".")[0]) == ident for a in node.names):
                        return True
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) \
                        and node.id == ident:
                    return True
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == ident:
                    return True
        return False

    out: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == name):
            continue
        scope: ast.AST | None = node
        while scope is not None:
            if isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
                if binds(scope, name):
                    out.append(node.lineno)
                    break
            scope = parents.get(scope)
    return out


def test_both_boot_paths_actually_adopt_the_shipped_verdicts():
    """A helper with no caller is a dead end -- the shape this repo has paid for repeatedly.
    main.py seeds the catalog in TWO places (the lifespan startup and the __main__ launcher),
    and a fix that reaches one of two callers is the recorded gate-every-entry-point defect,
    so both are required rather than "at least one"."""
    src = (Path(__file__).resolve().parents[1] / "src" / "api" / "main.py").read_text(
        encoding="utf-8"
    )
    lines = _calls_with_binding(src, "apply_overlay")
    assert len(lines) == 2, (
        f"expected the overlay to be applied at BOTH boot seeding sites, found {lines}"
    )


def test_the_binding_check_is_not_vacuous():
    """The guard above is only worth anything if it can fail. An import in a DIFFERENT
    function must not satisfy a call -- that is precisely the NameError case it exists to
    catch, and a check that merely greps for the identifier would pass it."""
    good = "def f():\n    from m import apply_overlay\n    apply_overlay(1)\n"
    bad = "def g():\n    from m import apply_overlay\n\ndef f():\n    apply_overlay(1)\n"
    assert len(_calls_with_binding(good, "apply_overlay")) == 1
    assert _calls_with_binding(bad, "apply_overlay") == []
