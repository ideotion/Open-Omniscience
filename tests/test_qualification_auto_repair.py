"""The boot-time repair of the SAFE direction, its revert record, and the report fields.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Diagnostics rank 14 (2026-09-30): sources that read live-qualified although their newest judging
attempt says disqualified. THE RULE THIS PINS: only the direction that WITHDRAWS a source from
collection runs by itself; restoring 'qualified' (a re-admission) stays operator-run. Every
automatic change is kept, with the status and stamp it replaced, in a revert record that has NO
cap -- a capped record would silently make the oldest repairs irreversible.

The key-value store and the session scope are swapped for in-memory fakes, so nothing here
touches a real data directory.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.catalog import qualification_integrity as qi
from src.catalog.qualification import (
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    VERDICT_CURATED,
)
from src.database.models import Base, Source, SourceQualificationAttempt

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
CURATED = "oo-curated-catalog-1"
MEASURED = "oo-source-qualification-3"
T0 = datetime(2026, 8, 1, 9, 0)  # naive UTC, as every writer stores it


@pytest.fixture()
def env(monkeypatch):
    # the suite-wide conftest switches the boot repair off; these tests are about it
    monkeypatch.setenv(qi.AUTO_REPAIR_ENV, "1")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)
    store: dict[str, dict] = {}

    @contextlib.contextmanager
    def scope():
        s = maker()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    import copy

    import src.config.kv_store as kv
    import src.database.session as sess

    monkeypatch.setattr(sess, "session_scope", scope)
    monkeypatch.setattr(kv, "kv_get_json", lambda key: copy.deepcopy(store.get(key)))
    monkeypatch.setattr(kv, "kv_get_json_strict", lambda key: copy.deepcopy(store.get(key)))
    monkeypatch.setattr(kv, "kv_set_json", lambda key, obj: store.__setitem__(key, copy.deepcopy(obj)))

    class Env:
        pass

    e = Env()
    e.maker, e.store, e.scope = maker, store, scope
    yield e
    engine.dispose()


def _add(s: Session, domain: str, live: str, judged: str, *, at: datetime = T0,
         live_version: str | None = None, live_at: datetime | None = None) -> int:
    if live == STATUS_QUALIFIED and live_version is None:
        live_version = CURATED  # a catalogue stamp is the class the boot repair may withdraw
    src = Source(name=domain, domain=domain, status=live,
                 qualification_criteria_version=live_version, qualified_at=live_at)
    s.add(src)
    s.flush()
    s.add(SourceQualificationAttempt(
        source_id=src.id, attempted_at=at, verdict=judged, criteria_version="v1"))
    s.flush()
    return int(src.id)


def _status(env, domain: str) -> Source:
    with env.scope() as s:
        src = s.query(Source).filter_by(domain=domain).one()
        s.expunge(src)
        return src


def test_only_the_withdrawing_direction_runs_by_itself(env) -> None:
    with env.scope() as s:
        _add(s, "bad.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED,
             live_version="oo-curated-catalog-1", live_at=T0)
        _add(s, "good.example", "unqualified", STATUS_QUALIFIED)   # a re-admission
    out = qi.auto_repair_inversions(now=NOW)

    assert out["repaired"] == 1
    assert _status(env, "bad.example").status == STATUS_DISQUALIFIED
    assert _status(env, "bad.example").qualification_criteria_version is None
    # the other direction is an operator's call: untouched, still reported as an inversion
    assert _status(env, "good.example").status == "unqualified"
    with env.scope() as s:
        rep = qi.qualification_integrity_report(s)
    assert rep["demoted_total"] == 1 and rep["laundered_total"] == 0


def test_every_repair_is_recorded_with_what_it_replaced(env) -> None:
    with env.scope() as s:
        _add(s, "bad.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED,
             live_version="oo-curated-catalog-1", live_at=T0)
    qi.auto_repair_inversions(now=NOW)

    summary = qi.repair_summary()
    assert summary["repaired_total"] == 1 and summary["repair_runs"] == 1
    assert summary["last_repair_at"] == NOW.isoformat()
    (row,) = summary["repairs"]
    assert row["domain"] == "bad.example" and row["was_status"] == STATUS_QUALIFIED
    assert row["restored_to"] == STATUS_DISQUALIFIED and row["reverted_at"] is None
    run = env.store[qi.REPAIR_RUN_PREFIX + NOW.isoformat()]
    assert run["applied"] is True
    assert run["repairs"][0]["was_criteria_version"] == "oo-curated-catalog-1"
    with env.scope() as s:
        rep = qi.qualification_integrity_report(s)
    assert rep["repaired_total"] == 1 and rep["verdict"] == "consistent"


def test_a_second_run_finds_nothing_and_writes_nothing(env) -> None:
    with env.scope() as s:
        _add(s, "bad.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    before = dict(env.store)
    out = qi.auto_repair_inversions(now=NOW + timedelta(hours=1))
    assert out["repaired"] == 0 and env.store == before


def test_the_revert_record_has_no_cap(env) -> None:
    n = qi.NAME_CAP + 50
    with env.scope() as s:
        for i in range(n):
            _add(s, f"bad{i}.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    out = qi.auto_repair_inversions(now=NOW)

    assert out["repaired"] == n
    assert len(qi.repair_summary()["repairs"]) == n, "a capped record hides the oldest repairs"
    result = qi.revert_repairs(dry_run=False)
    assert result["reverted"] == n


def test_a_revert_restores_status_and_stamp_and_holds_the_source_out(env) -> None:
    with env.scope() as s:
        _add(s, "bad.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED,
             live_version="oo-curated-catalog-1", live_at=T0)
    qi.auto_repair_inversions(now=NOW)

    dry = qi.revert_repairs(dry_run=True)
    assert dry["reverted"] == 1
    assert _status(env, "bad.example").status == STATUS_DISQUALIFIED, "a dry run writes nothing"

    qi.revert_repairs(dry_run=False)
    got = _status(env, "bad.example")
    assert got.status == STATUS_QUALIFIED
    assert got.qualification_criteria_version == "oo-curated-catalog-1"
    assert got.qualified_at == T0
    assert qi.repair_summary()["repairs"][0]["reverted_at"] is not None

    # without the hold, the very next boot would simply repair it again
    again = qi.auto_repair_inversions(now=NOW + timedelta(days=1))
    assert again["repaired"] == 0 and again["held_by_operator_revert"] == 1
    assert _status(env, "bad.example").status == STATUS_QUALIFIED
    assert qi.repair_summary()["repairs_held_by_revert"] == ["bad.example"]


def test_a_revert_never_overwrites_a_later_verdict(env) -> None:
    with env.scope() as s:
        _add(s, "bad.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    with env.scope() as s:
        s.query(Source).filter_by(domain="bad.example").one().status = "unqualified"
    result = qi.revert_repairs(dry_run=False)
    assert result["reverted"] == 0 and result["moved_on_since_repair"] == 1
    assert _status(env, "bad.example").status == "unqualified"


def test_the_report_names_when_the_engine_last_spoke(env) -> None:
    recent = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
    with env.scope() as s:
        a = _add(s, "judged.example", STATUS_QUALIFIED, STATUS_QUALIFIED, at=recent - timedelta(days=3))
        s.add(SourceQualificationAttempt(
            source_id=a, attempted_at=recent, verdict=VERDICT_CURATED, criteria_version="c"))
        s.add(SourceQualificationAttempt(
            source_id=a, attempted_at=recent - timedelta(hours=1), verdict=STATUS_QUALIFIED,
            criteria_version="v1"))
    with env.scope() as s:
        chk = qi.qualification_integrity_report(s)["checked"]
    assert chk["last_attempt_at"].startswith(recent.date().isoformat())
    # ANY attempt counts for the first pair, only a real judgement for the second
    assert chk["attempts_last_24h"] == 2 and chk["judging_attempts_last_24h"] == 1
    assert chk["last_judging_attempt_at"] < chk["last_attempt_at"]


def test_the_report_degrades_to_zero_when_the_record_is_unreadable(monkeypatch) -> None:
    import src.config.kv_store as kv

    def boom(_key):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(kv, "kv_get_json", boom)
    monkeypatch.setattr(kv, "kv_get_json_strict", boom)
    summary = qi.repair_summary()
    assert summary["repaired_total"] == 0 and "could not be read" in summary["repairs_note"]


def _attempt(env, domain: str, verdict: str, at: datetime) -> None:
    with env.scope() as s:
        src = s.query(Source).filter_by(domain=domain).one()
        s.add(SourceQualificationAttempt(
            source_id=src.id, attempted_at=at, verdict=verdict, criteria_version="v1"))


def test_the_record_and_its_index_exist_before_anything_is_applied(env, monkeypatch) -> None:
    """The ordering the review found untested: record AND index first, then the change. A
    repair that is committed but never indexed could not be seen or reverted."""
    import src.config.kv_store as kv

    with env.scope() as s:
        _add(s, "bad.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    seen: list[tuple[str, str]] = []
    real_set = kv.kv_set_json

    def spy(key, obj):
        seen.append((key, _status(env, "bad.example").status))
        real_set(key, obj)

    monkeypatch.setattr(kv, "kv_set_json", spy)
    qi.auto_repair_inversions(now=NOW)

    keys = [k for k, _ in seen]
    assert keys[0].startswith(qi.REPAIR_RUN_PREFIX) and keys[1] == qi.REPAIR_INDEX_KEY
    assert seen[0][1] == seen[1][1] == STATUS_QUALIFIED, "both writes precede the change"
    assert seen[2][1] == STATUS_DISQUALIFIED, "the confirmation follows it"


def test_a_failed_confirmation_leaves_a_listed_and_revertable_run(env, monkeypatch) -> None:
    import src.config.kv_store as kv

    with env.scope() as s:
        _add(s, "bad.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    real_set = kv.kv_set_json
    calls = {"n": 0}

    def flaky(key, obj):
        calls["n"] += 1
        if calls["n"] == 3:                      # the confirmation write
            raise OSError("disk full")
        real_set(key, obj)

    monkeypatch.setattr(kv, "kv_set_json", flaky)
    with pytest.raises(OSError):
        qi.auto_repair_inversions(now=NOW)
    monkeypatch.setattr(kv, "kv_set_json", real_set)

    assert _status(env, "bad.example").status == STATUS_DISQUALIFIED
    summary = qi.repair_summary()
    assert summary["repaired_total"] == 0 and summary["repairs_unconfirmed"] == 1
    assert [r["domain"] for r in summary["repairs"]] == ["bad.example"]
    assert qi.revert_repairs(dry_run=False)["reverted"] == 1
    assert _status(env, "bad.example").status == STATUS_QUALIFIED


def test_only_the_planned_sources_are_applied(env, monkeypatch) -> None:
    """The plan that is recorded is the plan that is applied: an inversion that appears between
    the two steps is left for the next boot rather than changed without a record."""
    import src.config.kv_store as kv

    with env.scope() as s:
        _add(s, "planned.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    real_set = kv.kv_set_json
    added = {"done": False}

    def spy(key, obj):
        real_set(key, obj)
        if key == qi.REPAIR_INDEX_KEY and not added["done"]:
            added["done"] = True
            with env.scope() as s:
                _add(s, "late.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)

    monkeypatch.setattr(kv, "kv_set_json", spy)
    out = qi.auto_repair_inversions(now=NOW)

    assert out["repaired"] == 1
    assert _status(env, "planned.example").status == STATUS_DISQUALIFIED
    assert _status(env, "late.example").status == STATUS_QUALIFIED
    assert [r["domain"] for r in qi.repair_summary()["repairs"]] == ["planned.example"]
    # and the next boot picks the late one up, with its own record
    assert qi.auto_repair_inversions(now=NOW + timedelta(hours=1))["repaired"] == 1


def test_a_domain_repaired_twice_reverts_to_its_newest_record(env) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED,
             live_version=CURATED, live_at=T0)
    qi.auto_repair_inversions(now=NOW)
    # re-qualified later by a real judgement (attempt + stamp together), then inverted again
    t1 = T0 + timedelta(days=9)
    with env.scope() as s:
        src = s.query(Source).filter_by(domain="x.example").one()
        src.status, src.qualification_criteria_version, src.qualified_at = (
            STATUS_QUALIFIED, CURATED, t1)
        s.add(SourceQualificationAttempt(
            source_id=src.id, attempted_at=t1, verdict=STATUS_QUALIFIED, criteria_version="v1"))
    t2 = t1 + timedelta(days=9)
    _attempt(env, "x.example", STATUS_DISQUALIFIED, t2)
    qi.auto_repair_inversions(now=NOW + timedelta(days=30))

    result = qi.revert_repairs(dry_run=False)
    assert result["reverted"] == 1, "one domain, one revert, never two"
    got = _status(env, "x.example")
    assert got.qualification_criteria_version == CURATED and got.qualified_at == t1


def test_a_revert_never_undoes_a_later_judgement_that_agrees_with_the_repair(env) -> None:
    """A real disqualified verdict produces exactly the state the repair writes, so status
    alone cannot tell them apart: the newest judging attempt must still be the one followed."""
    with env.scope() as s:
        _add(s, "bad.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    _attempt(env, "bad.example", STATUS_DISQUALIFIED, T0 + timedelta(days=3))

    result = qi.revert_repairs(dry_run=False)
    assert result["reverted"] == 0 and result["moved_on_since_repair"] == 1
    assert _status(env, "bad.example").status == STATUS_DISQUALIFIED


def test_the_hold_is_written_before_the_revert_changes_anything(env, monkeypatch) -> None:
    """If a write fails part-way through a revert, the next boot must not silently repair the
    source again: the hold lands first."""
    import src.config.kv_store as kv

    with env.scope() as s:
        _add(s, "bad.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    real_set = kv.kv_set_json
    seen: list[str] = []

    def spy(key, obj):
        seen.append(_status(env, "bad.example").status)
        real_set(key, obj)

    monkeypatch.setattr(kv, "kv_set_json", spy)
    qi.revert_repairs(dry_run=False)
    assert seen[0] == STATUS_DISQUALIFIED, "the first write (the hold) precedes the change"
    assert qi.auto_repair_inversions(now=NOW + timedelta(days=1))["repaired"] == 0


_MAIN_PY = Path(__file__).resolve().parents[1] / "src" / "api" / "main.py"


def _boot_call_ancestry():
    import ast

    tree = ast.parse(_MAIN_PY.read_text(encoding="utf-8"))
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    hits = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "auto_repair_inversions"
    ]
    assert len(hits) == 1, "the boot hook calls auto_repair_inversions exactly once"
    chain = []
    node: ast.AST = hits[0]
    while id(node) in parents:
        node = parents[id(node)]
        chain.append(node)
    return chain


def test_boot_calls_the_repair_outside_any_session_scope() -> None:
    """kv_set_json must never run inside an open ORM write transaction on the same thread."""
    import ast

    for node in _boot_call_ancestry():
        if isinstance(node, ast.With):
            for item in node.items:
                text = ast.unparse(item.context_expr)
                assert "session_scope" not in text, "the repair sits inside a session_scope"


def test_boot_swallows_a_failed_repair_and_is_not_gated_by_autoseed() -> None:
    import ast

    chain = _boot_call_ancestry()
    tries = [n for n in chain if isinstance(n, ast.Try)]
    assert tries and any(
        h.type is not None and ast.unparse(h.type) == "Exception"
        for t in tries for h in t.handlers
    ), "a repair that cannot run must never block startup"
    for node in chain:
        if isinstance(node, ast.If):
            assert "OO_AUTOSEED" not in ast.unparse(node.test), "a reconciliation is not a seed"


# --------------------------------------------------------------------------- #
#  Which rows the boot repair may touch (rule 12 = b), and the Opus re-review's notes
# --------------------------------------------------------------------------- #
def test_a_verdict_measured_here_is_never_changed_by_the_boot_repair(env) -> None:
    """The coordinator's 12 = b objection: an imported history must not demote, by itself, a
    row whose live verdict this install produced. It is reported and left for a local re-check."""
    with env.scope() as s:
        _add(s, "mine.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED,
             live_version=MEASURED, live_at=T0)
        _add(s, "catalogue.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)   # curated stamp
        _add(s, "never.example", "unqualified", STATUS_DISQUALIFIED)         # no verdict at all
        _add(s, "s7a.example", STATUS_DISQUALIFIED, STATUS_QUALIFIED)        # the safe order
    out = qi.auto_repair_inversions(now=NOW)

    assert out["repaired"] == 2
    assert _status(env, "mine.example").status == STATUS_QUALIFIED
    assert _status(env, "mine.example").qualification_criteria_version == MEASURED
    assert _status(env, "catalogue.example").status == STATUS_DISQUALIFIED
    assert _status(env, "never.example").status == STATUS_DISQUALIFIED
    assert _status(env, "s7a.example").status == STATUS_DISQUALIFIED
    with env.scope() as s:
        rep = qi.qualification_integrity_report(s)
    assert rep["inversions_total"] == 2          # mine.example and s7a.example remain, reported
    assert rep["auto_repairable_total"] == 0 and rep["not_auto_repaired_total"] == 2
    assert rep["not_auto_repaired_measured_here_total"] == 1
    assert rep["not_auto_repaired_requalify_direction_total"] == 1
    assert {r["domain"]: r["live_stamp"] for r in rep["laundered"]} == {"mine.example": "measured"}


def test_the_report_counts_what_the_boot_repair_would_take(env) -> None:
    with env.scope() as s:
        _add(s, "mine.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED,
             live_version=MEASURED, live_at=T0)
        _add(s, "catalogue.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
        _add(s, "never.example", "unqualified", STATUS_DISQUALIFIED)
        rep = qi.qualification_integrity_report(s)
    assert rep["auto_repairable_total"] == 2 and rep["not_auto_repaired_total"] == 1
    stamps = {r["domain"]: r["live_stamp"] for r in rep["laundered"]}
    assert stamps == {"mine.example": "measured", "catalogue.example": "catalogue",
                      "never.example": "none"}


def test_an_older_record_is_not_eligible_once_the_newer_one_was_reverted(env) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED, live_version=CURATED, live_at=T0)
    qi.auto_repair_inversions(now=NOW)
    # a write that is not a judgement re-inverts the row (no new attempt), then a second repair
    t1 = T0 + timedelta(days=5)
    with env.scope() as s:
        src = s.query(Source).filter_by(domain="x.example").one()
        src.status, src.qualification_criteria_version, src.qualified_at = (
            STATUS_QUALIFIED, CURATED, t1)
    # the hold from nothing yet: the second repair is a new run for the same domain
    qi.auto_repair_inversions(now=NOW + timedelta(days=1))
    assert len(qi._read_repair_index()["runs"]) == 2
    assert qi.revert_repairs(dry_run=False)["reverted"] == 1
    assert _status(env, "x.example").qualified_at == t1
    # an operator withdraws it again; the older record must not be the one a second revert uses
    with env.scope() as s:
        qi.repair_inversions(s, dry_run=False)
    assert qi.revert_repairs(dry_run=False)["reverted"] == 0
    assert _status(env, "x.example").status == STATUS_DISQUALIFIED


def test_the_confirmation_records_what_was_applied_not_what_was_planned(env, monkeypatch) -> None:
    """A planned row that resolves itself between the plan and the apply must not be recorded
    as a repair that happened."""
    with env.scope() as s:
        _add(s, "stays.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
        _add(s, "resolves.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    import src.config.kv_store as kv

    real = kv.kv_set_json
    fired: list[int] = []

    def spy(key, obj):
        real(key, obj)
        if key.startswith(qi.REPAIR_RUN_PREFIX) and not obj.get("applied") and not fired:
            fired.append(1)       # right after the plan is recorded, before it is applied
            with env.scope() as s:
                s.query(Source).filter_by(domain="resolves.example").one().status = (
                    STATUS_DISQUALIFIED)

    monkeypatch.setattr(kv, "kv_set_json", spy)
    out = qi.auto_repair_inversions(now=NOW)

    assert out["repaired"] == 1
    run = env.store[qi.REPAIR_RUN_PREFIX + qi._iso(NOW)]
    assert run["applied"] is True
    assert [r["domain"] for r in run["repairs"]] == ["stays.example"]


def test_a_row_that_turns_measured_between_the_plan_and_the_apply_is_not_withdrawn(
        env, monkeypatch) -> None:
    """The apply re-checks the LIVE stamp (rule 12 = b against a concurrent local pass): a row the
    plan saw as the catalogue's stamp, which a local re-check then qualified for real, is left."""
    with env.scope() as s:
        _add(s, "stays.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
        _add(s, "measured-meanwhile.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    import src.config.kv_store as kv

    real = kv.kv_set_json
    fired: list[int] = []

    def spy(key, obj):
        real(key, obj)
        if key.startswith(qi.REPAIR_RUN_PREFIX) and not obj.get("applied") and not fired:
            fired.append(1)       # right after the plan is recorded, before it is applied
            with env.scope() as s:
                row = s.query(Source).filter_by(domain="measured-meanwhile.example").one()
                row.status = STATUS_QUALIFIED
                row.qualification_criteria_version = "oo-source-qualification-3"

    monkeypatch.setattr(kv, "kv_set_json", spy)
    out = qi.auto_repair_inversions(now=NOW)

    assert out["repaired"] == 1
    assert _status(env, "measured-meanwhile.example").status == STATUS_QUALIFIED
    assert _status(env, "stays.example").status == STATUS_DISQUALIFIED
    run = env.store[qi.REPAIR_RUN_PREFIX + qi._iso(NOW)]
    assert [r["domain"] for r in run["repairs"]] == ["stays.example"]


def test_a_qualified_row_with_no_criteria_version_is_measured_and_left_alone(env) -> None:
    """``none`` means status unqualified; a qualified row WITHOUT a version is an anomaly and is
    classed with the measured rows, the side the ruling leaves alone, and reported as such."""
    with env.scope() as s:
        s.add(Source(name="nov.example", domain="nov.example", status=STATUS_QUALIFIED,
                     qualification_criteria_version=None))
        s.flush()
        sid = s.query(Source).filter_by(domain="nov.example").one().id
        s.add(SourceQualificationAttempt(source_id=sid, attempted_at=T0,
                                         verdict=STATUS_DISQUALIFIED, criteria_version="v1"))
        _add(s, "cat.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    with env.scope() as s:
        assert qi.live_stamp_class(s.query(Source).filter_by(domain="nov.example").one()) == "measured"
    out = qi.auto_repair_inversions(now=NOW)

    assert out["repaired"] == 1
    assert _status(env, "nov.example").status == STATUS_QUALIFIED
    assert _status(env, "cat.example").status == STATUS_DISQUALIFIED


def test_a_plan_that_fails_to_apply_at_every_boot_does_not_grow_the_record(env, monkeypatch) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    real = qi.repair_inversions

    def failing_apply(session, **kw):
        if not kw.get("dry_run", True):
            raise RuntimeError("disk full")
        return real(session, **kw)

    monkeypatch.setattr(qi, "repair_inversions", failing_apply)
    for hours in range(4):
        with pytest.raises(RuntimeError):
            qi.auto_repair_inversions(now=NOW + timedelta(hours=hours))

    runs = [k for k in env.store if k.startswith(qi.REPAIR_RUN_PREFIX)]
    assert len(runs) == 1 and len(qi._read_repair_index()["runs"]) == 1
    summary = qi.repair_summary()
    assert summary["repairs_unconfirmed"] == 1 and summary["repaired_total"] == 0


def test_a_replaced_plan_reports_the_time_it_was_applied_not_the_first_attempt(env, monkeypatch) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    real = qi.repair_inversions
    broken = {"on": True}

    def flaky_apply(session, **kw):
        if broken["on"] and not kw.get("dry_run", True):
            raise RuntimeError("disk full")
        return real(session, **kw)

    monkeypatch.setattr(qi, "repair_inversions", flaky_apply)
    with pytest.raises(RuntimeError):
        qi.auto_repair_inversions(now=NOW)
    broken["on"] = False
    later = NOW + timedelta(hours=5)
    qi.auto_repair_inversions(now=later)

    run = env.store[qi.REPAIR_RUN_PREFIX + qi._iso(NOW)]
    assert run["applied"] is True and run["applied_at"] == qi._iso(later)
    assert qi.repair_summary()["repairs"][0]["applied_at"] == qi._iso(later)


def test_the_boot_repair_can_be_switched_off_for_the_test_suite(env, monkeypatch) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    monkeypatch.setenv(qi.AUTO_REPAIR_ENV, "0")
    out = qi.auto_repair_inversions(now=NOW)
    assert out["repaired"] == 0 and "skipped" in out
    assert _status(env, "x.example").status == STATUS_QUALIFIED and not env.store


def test_the_conftest_switches_it_off_for_the_whole_suite() -> None:
    from pathlib import Path

    src = (Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("OO_QUALIFICATION_AUTO_REPAIR", "0")' in src


def test_the_operator_script_honours_the_hold_unless_told_not_to(env) -> None:
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "repair_script", Path(__file__).resolve().parents[1] / "scripts"
        / "repair_qualification_inversions.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    assert qi.revert_repairs(dry_run=False)["reverted"] == 1     # back to qualified, and held
    assert _status(env, "x.example").status == STATUS_QUALIFIED

    script.main(["--apply"])
    assert _status(env, "x.example").status == STATUS_QUALIFIED, "the hold is honoured"
    script.main(["--apply", "--ignore-hold"])
    assert _status(env, "x.example").status == STATUS_DISQUALIFIED


def test_the_summary_forgets_its_cached_keys_so_an_out_of_process_revert_shows(env, monkeypatch) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    import src.config.kv_store as kv

    forgotten: list[str] = []
    monkeypatch.setattr(kv, "kv_invalidate", lambda key=None: forgotten.append(key))
    qi.repair_summary()
    assert qi.REPAIR_INDEX_KEY in forgotten
    assert qi.REPAIR_RUN_PREFIX + qi._iso(NOW) in forgotten


def test_an_inverted_backup_imported_into_a_consistent_instance_is_withdrawn_at_the_next_boot(
    tmp_path, monkeypatch
) -> None:
    """The whole path, found by the diagnostics thread's reproduction: a backup from an instance
    that is itself inverted (a catalogue stamp beside a newer disqualified attempt, the 085639
    shape) lands on a consistent catalogue-stamped instance. The incoming stamp replaces nothing
    but the attempts merge copies every attempt row, so the importing instance reads
    inversions-found until the next boot repair withdraws it."""
    import copy
    from datetime import timedelta

    from src.backup.merge import merge_corpus
    from tests.test_merge_source_qualification import (
        _BATCH_META,
        _CURATED,
        _MEASURED,
        _SEEN,
        _T0,
        _add_attempt,
        _add_source,
        _attempts,
        _corpus,
        _integrity,
        _sources,
    )

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        sid = _add_source(s, "psx.com.pk", status="qualified", at=_T0, version=_CURATED)
        _add_attempt(s, sid, "curated", _T0, version=_CURATED)
        # a measured row on the importing side, to prove the repair leaves it alone
        mid = _add_source(s, "mine.example", status="qualified", at=_T0, version=_MEASURED)
        _add_attempt(s, mid, "qualified", _T0, version=_MEASURED)
        s.commit()
    with _corpus(staged)() as s:
        sid = _add_source(s, "psx.com.pk", status="qualified", at=_T0, version=_CURATED)
        _add_attempt(s, sid, "curated", _T0, version=_CURATED)
        _add_attempt(s, sid, "disqualified", _SEEN, version=_MEASURED)
        mid = _add_source(s, "mine.example", status="qualified", at=_T0, version=_CURATED)
        _add_attempt(s, mid, "disqualified", _SEEN + timedelta(days=1), version=_MEASURED)
        s.commit()
    assert _integrity(staged)["verdict"] == "inversions-found"

    merge_corpus(staged, working, _BATCH_META)
    got = _sources(working)
    assert got["psx.com.pk"].status == "qualified" and got["psx.com.pk"].qualification_criteria_version == _CURATED
    assert [a.verdict for a in _attempts(working, "psx.com.pk")] == ["curated", "disqualified"]
    assert _integrity(working)["inversions_total"] == 2          # inverted until the next boot

    # the next boot, against that corpus (a fake key-value store, the working file's sessions)
    maker = _corpus(working)
    store: dict[str, dict] = {}

    @contextlib.contextmanager
    def scope():
        s = maker()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    import src.config.kv_store as kv
    import src.database.session as sess

    monkeypatch.setenv(qi.AUTO_REPAIR_ENV, "1")
    monkeypatch.setattr(sess, "session_scope", scope)
    monkeypatch.setattr(kv, "kv_get_json", lambda key: copy.deepcopy(store.get(key)))
    monkeypatch.setattr(kv, "kv_get_json_strict", lambda key: copy.deepcopy(store.get(key)))
    monkeypatch.setattr(kv, "kv_set_json", lambda key, obj: store.__setitem__(key, copy.deepcopy(obj)))
    out = qi.auto_repair_inversions(now=NOW)

    after = _sources(working)
    assert out["repaired"] == 1
    assert after["psx.com.pk"].status == STATUS_DISQUALIFIED, "the catalogue-stamped row is withdrawn"
    assert after["mine.example"].status == STATUS_QUALIFIED, "a verdict measured here is not"
    rep = _integrity(working)
    assert rep["inversions_total"] == 1 and rep["not_auto_repaired_measured_here_total"] == 1
    assert [r["domain"] for r in rep["laundered"]] == ["mine.example"]


def test_a_held_domain_is_not_counted_as_auto_repairable(env) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    qi.revert_repairs(dry_run=False)                       # back to qualified, and held
    assert qi.auto_repair_inversions(now=NOW + timedelta(hours=1))["repaired"] == 0
    with env.scope() as s:
        rep = qi.qualification_integrity_report(s)
    assert rep["auto_repairable_total"] == 0
    assert rep["not_auto_repaired_held_total"] == 1 and rep["not_auto_repaired_total"] == 1


def test_a_measured_row_is_in_no_record_and_a_second_boot_writes_nothing(env) -> None:
    with env.scope() as s:
        _add(s, "mine.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED,
             live_version=MEASURED, live_at=T0)
        _add(s, "cat.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    for run in (v for k, v in env.store.items() if k.startswith(qi.REPAIR_RUN_PREFIX)):
        assert "mine.example" not in [r["domain"] for r in run["repairs"]]
    import copy

    before = copy.deepcopy(env.store)
    assert qi.auto_repair_inversions(now=NOW + timedelta(hours=1))["repaired"] == 0
    assert env.store == before, "nothing planned, nothing written"


def test_an_applied_run_whose_confirmation_failed_is_confirmed_at_the_next_boot(env, monkeypatch) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    import src.config.kv_store as kv

    real = kv.kv_set_json
    state = {"fail": True}

    def flaky(key, obj):
        if state["fail"] and key.startswith(qi.REPAIR_RUN_PREFIX) and obj.get("applied"):
            raise OSError("disk full")
        real(key, obj)

    monkeypatch.setattr(kv, "kv_set_json", flaky)
    with pytest.raises(OSError):
        qi.auto_repair_inversions(now=NOW)
    assert qi.repair_summary()["repairs_unconfirmed"] == 1
    state["fail"] = False
    qi.auto_repair_inversions(now=NOW + timedelta(hours=1))
    summary = qi.repair_summary()
    assert summary["repaired_total"] == 1 and summary["repairs_unconfirmed"] == 0


def test_an_applied_but_unconfirmed_record_survives_a_later_different_plan(env, monkeypatch) -> None:
    """A run that applied but could not confirm is never overwritten by the next plan: it lists
    different sources, so it is appended, and BOTH records stay revertable."""
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    import src.config.kv_store as kv

    real = kv.kv_set_json
    state = {"fail": True}

    def flaky(key, obj):
        if state["fail"] and key.startswith(qi.REPAIR_RUN_PREFIX) and obj.get("applied"):
            raise OSError("disk full")
        real(key, obj)

    monkeypatch.setattr(kv, "kv_set_json", flaky)
    with pytest.raises(OSError):
        qi.auto_repair_inversions(now=NOW)
    # a confirm that cannot land either (the store is still failing), then a NEW inversion
    with env.scope() as s:
        _add(s, "y.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    with pytest.raises(OSError):
        qi.auto_repair_inversions(now=NOW + timedelta(hours=1))
    runs = qi._read_repair_index()["runs"]
    assert len(runs) == 2, "the first run was appended to, not overwritten"
    first = env.store[qi.REPAIR_RUN_PREFIX + runs[0]]
    assert [r["domain"] for r in first["repairs"]] == ["x.example"]
    state["fail"] = False
    assert qi.revert_repairs(dry_run=False)["reverted"] == 2


# --------------------------------------------------------------------------- #
#  The coordinator's S2 / S3: fail closed, and the claims that were only read, now exercised
# --------------------------------------------------------------------------- #
def test_an_unreadable_index_skips_the_repair_and_overwrites_nothing(env, monkeypatch) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    before = {k: dict(v) for k, v in env.store.items()}
    with env.scope() as s:
        _add(s, "y.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)   # would be planned
    import src.config.kv_store as kv

    def locked(_key):
        raise OSError("database is locked")

    monkeypatch.setattr(kv, "kv_get_json_strict", locked)
    out = qi.auto_repair_inversions(now=NOW + timedelta(hours=1))

    assert out["repaired"] == 0 and "cannot be read" in out["skipped"]
    assert _status(env, "y.example").status == STATUS_QUALIFIED, "nothing is repaired this boot"
    assert env.store == before, "the stored index and runs are exactly as they were"
    with pytest.raises(OSError):
        qi.revert_repairs(dry_run=False)                            # the revert refuses too


def test_the_strict_reader_tells_an_unreadable_store_from_an_absent_key(tmp_path, monkeypatch) -> None:
    import sqlite3

    import src.config.kv_store as kv

    db = tmp_path / "open_omniscience.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    kv.kv_invalidate()
    assert kv.kv_get_json_strict("k") is None            # no file, no table: absent
    kv.kv_set_json("k", {"a": 1})
    kv.kv_invalidate()
    assert kv.kv_get_json_strict("k") == {"a": 1}
    kv.kv_invalidate()
    with sqlite3.connect(db) as c:
        c.execute("DROP TABLE app_state")
    assert kv.kv_get_json_strict("k") is None            # the table is simply not there yet

    def broken(_path):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(kv, "_open", broken)
    kv.kv_invalidate()
    with pytest.raises(sqlite3.OperationalError):
        kv.kv_get_json_strict("k")


def test_the_strict_reader_raises_on_a_query_time_failure_and_on_a_corrupt_value(
        tmp_path, monkeypatch) -> None:
    import sqlite3

    import src.config.kv_store as kv

    db = tmp_path / "open_omniscience.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    kv.kv_invalidate()
    kv.kv_set_json("k", {"a": 1})
    kv.kv_invalidate()
    with sqlite3.connect(db) as c:
        c.execute("UPDATE app_state SET value = ? WHERE key = 'k'", ('{"a": 1',))   # truncated
    with pytest.raises(ValueError):
        kv.kv_get_json_strict("k")                      # present but unparseable is NOT absent
    assert kv.kv_get_json("k") is None                  # the lenient reader still says absent
    kv.kv_invalidate()

    class Locked:
        def execute(self, *_a, **_k):
            raise sqlite3.OperationalError("database is locked")

        def close(self) -> None:
            pass

    monkeypatch.setattr(kv, "_open", lambda _p: Locked())
    with pytest.raises(sqlite3.OperationalError):
        kv.kv_get_json_strict("k")                      # a failure at QUERY time, not only at open


def test_the_report_summary_reads_the_index_strictly(env, monkeypatch) -> None:
    import src.config.kv_store as kv

    def locked(_key):
        raise OSError("database is locked")

    monkeypatch.setattr(kv, "kv_get_json_strict", locked)   # the lenient reader still answers
    summary = qi.repair_summary()
    assert "could not be read" in summary["repairs_note"], "an unreadable index is said, not read as empty"


def test_the_operator_script_stops_when_the_revert_record_is_unreadable(env, monkeypatch, capsys) -> None:
    import importlib.util
    from pathlib import Path

    import src.config.kv_store as kv

    spec = importlib.util.spec_from_file_location(
        "repair_script2", Path(__file__).resolve().parents[1] / "scripts"
        / "repair_qualification_inversions.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)

    def locked(_key):
        raise OSError("database is locked")

    monkeypatch.setattr(kv, "kv_get_json_strict", locked)
    assert script.main(["--apply"]) == 2
    assert _status(env, "x.example").status == STATUS_QUALIFIED
    assert "cannot read the revert record" in capsys.readouterr().err
    assert script.main(["--revert-repairs"]) == 2         # the revert path stops cleanly too
    assert "the revert stopped" in capsys.readouterr().err


def test_a_later_plan_that_includes_the_failed_sources_replaces_the_failed_record(env, monkeypatch) -> None:
    """Boot 1 plans {x} and fails to apply; an import adds y; boot 2 plans {x, y}: one record,
    not an unconfirmed run for x beside a confirmed one that also lists it."""
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    real = qi.repair_inversions
    broken = {"on": True}

    def flaky_apply(session, **kw):
        if broken["on"] and not kw.get("dry_run", True):
            raise RuntimeError("disk full")
        return real(session, **kw)

    monkeypatch.setattr(qi, "repair_inversions", flaky_apply)
    with pytest.raises(RuntimeError):
        qi.auto_repair_inversions(now=NOW)
    broken["on"] = False
    with env.scope() as s:
        _add(s, "y.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW + timedelta(hours=1))
    qi.auto_repair_inversions(now=NOW + timedelta(hours=2))

    summary = qi.repair_summary()
    assert summary["repair_runs"] == 1
    assert summary["repaired_total"] == 2 and summary["repairs_unconfirmed"] == 0


def test_a_run_is_not_reconciled_by_a_later_runs_work(env) -> None:
    """R1 lists x and was never applied; R2 lists x and y and was applied but never confirmed.
    Both rows now read withdrawn, but only R2 can claim them."""
    with env.scope() as s:
        x = _add(s, "x.example", STATUS_DISQUALIFIED, STATUS_DISQUALIFIED)
        y = _add(s, "y.example", STATUS_DISQUALIFIED, STATUS_DISQUALIFIED)
    r1, r2 = "2026-09-30T12:00:00+00:00", "2026-09-30T13:00:00+00:00"
    row = lambda sid, dom: {"source_id": sid, "domain": dom, "restored_to": STATUS_DISQUALIFIED}  # noqa: E731
    env.store[qi.REPAIR_RUN_PREFIX + r1] = {"run_at": r1, "applied": False, "repairs": [row(x, "x.example")]}
    env.store[qi.REPAIR_RUN_PREFIX + r2] = {"run_at": r2, "applied": False, "repairs": [
        row(x, "x.example"), row(y, "y.example")]}
    env.store[qi.REPAIR_INDEX_KEY] = {"runs": [r1, r2], "last_run_at": r2, "reverted_domains": []}

    qi._confirm_applied_runs(qi._read_repair_index())

    assert env.store[qi.REPAIR_RUN_PREFIX + r2]["applied"] is True
    assert env.store[qi.REPAIR_RUN_PREFIX + r1]["applied"] is False
    summary = qi.repair_summary()
    # counted PER DOMAIN from the newest record: x is confirmed by R2, so R1's x is superseded
    assert summary["repaired_total"] == 2 and summary["repairs_unconfirmed"] == 0
    assert [r["superseded"] for r in summary["repairs"] if r["run_at"] == r1] == [True]
    assert {r["applied_at"] for r in summary["repairs"] if r["confirmed"]} == {None}
    assert [r["reconciled"] for r in summary["repairs"] if r["run_at"] == r2] == [True, True]
    assert [r["reconciled"] for r in summary["repairs"] if r["run_at"] == r1] == [False]


def test_the_held_domain_read_forgets_the_per_process_cache(env, monkeypatch) -> None:
    """A revert run in another process must show in the report's held count."""
    import src.config.kv_store as kv

    forgotten: list[str | None] = []
    monkeypatch.setattr(kv, "kv_invalidate", lambda key=None: forgotten.append(key))
    qi.held_domains()
    assert qi.REPAIR_INDEX_KEY in forgotten


def test_an_unreadable_run_is_kept_byte_for_byte_and_the_repair_carries_on(env, monkeypatch) -> None:
    """Per-run degradation: a run record that cannot be read is never replaced or confirmed, the
    repair appends its new plan as its own run, and the report names the unreadable run."""
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    assert qi.auto_repair_inversions(now=NOW)["repaired"] == 1
    run_key = qi.REPAIR_RUN_PREFIX + qi._iso(NOW)
    before = dict(env.store[run_key])
    with env.scope() as s:
        _add(s, "y.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    import src.config.kv_store as kv

    strict = kv.kv_get_json_strict

    def flaky(key):
        if key == run_key:
            raise OSError("database is locked")
        return strict(key)

    monkeypatch.setattr(kv, "kv_get_json_strict", flaky)
    out = qi.auto_repair_inversions(now=NOW + timedelta(hours=1))

    assert out["repaired"] == 1                                    # y is withdrawn, the app carries on
    assert _status(env, "y.example").status == STATUS_DISQUALIFIED
    assert env.store[run_key] == before, "the unreadable record is exactly as it was"
    assert len(qi._read_repair_index()["runs"]) == 2
    summary = qi.repair_summary()
    assert summary["repair_runs_unreadable"] == [qi._iso(NOW)]
    assert summary["repaired_total"] == 1 and [r["domain"] for r in summary["repairs"]] == ["y.example"]


def test_a_run_is_not_confirmed_while_a_later_run_cannot_be_read(env, monkeypatch) -> None:
    """What an unreadable later run lists is unknown, so no earlier run is confirmed on its account."""
    with env.scope() as s:
        x = _add(s, "x.example", STATUS_DISQUALIFIED, STATUS_DISQUALIFIED)
    r1, r2 = "2026-09-30T12:00:00+00:00", "2026-09-30T13:00:00+00:00"
    env.store[qi.REPAIR_RUN_PREFIX + r1] = {"run_at": r1, "applied": False, "repairs": [
        {"source_id": x, "domain": "x.example", "restored_to": STATUS_DISQUALIFIED}]}
    env.store[qi.REPAIR_RUN_PREFIX + r2] = {"run_at": r2, "applied": True, "repairs": []}
    env.store[qi.REPAIR_INDEX_KEY] = {"runs": [r1, r2], "last_run_at": r2, "reverted_domains": []}
    import src.config.kv_store as kv

    strict = kv.kv_get_json_strict

    def flaky(key):
        if key == qi.REPAIR_RUN_PREFIX + r2:
            raise OSError("database is locked")
        return strict(key)

    monkeypatch.setattr(kv, "kv_get_json_strict", flaky)
    qi._confirm_applied_runs(qi._read_repair_index())
    assert env.store[qi.REPAIR_RUN_PREFIX + r1]["applied"] is False


def test_an_indexed_run_whose_record_is_absent_never_has_its_key_taken(env) -> None:
    """The replace rule needs a recorded run that lists sources: an index entry with no record
    must not be 'replaced' by the new plan (an empty record changed nothing, trivially)."""
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    ghost = "2026-09-30T11:00:00+00:00"
    env.store[qi.REPAIR_INDEX_KEY] = {"runs": [ghost], "last_run_at": ghost, "reverted_domains": []}
    out = qi.auto_repair_inversions(now=NOW)

    assert out["repaired"] == 1 and out["run_at"] == qi._iso(NOW)
    assert qi._read_repair_index()["runs"] == [ghost, qi._iso(NOW)]
    assert qi.REPAIR_RUN_PREFIX + ghost not in env.store


def _failing_then_ok(monkeypatch):
    real = qi.repair_inversions
    state = {"broken": True}

    def flaky(session, **kw):
        if state["broken"] and not kw.get("dry_run", True):
            raise RuntimeError("disk full")
        return real(session, **kw)

    monkeypatch.setattr(qi, "repair_inversions", flaky)
    return state


def test_a_failed_plan_is_replaced_when_none_of_its_left_out_sources_was_changed(env, monkeypatch) -> None:
    """R1 plans {x, z} and fails; z is then resolved elsewhere (it reads the OPPOSITE of what R1
    would have written) and y appears; the next plan {x, y} replaces R1: one record, nothing left
    reading unconfirmed."""
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
        _add(s, "z.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    state = _failing_then_ok(monkeypatch)
    with pytest.raises(RuntimeError):
        qi.auto_repair_inversions(now=NOW)
    state["broken"] = False
    with env.scope() as s:
        _add(s, "y.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    _attempt(env, "z.example", STATUS_QUALIFIED, T0 + timedelta(days=1))   # re-judged qualified: consistent again
    qi.auto_repair_inversions(now=NOW + timedelta(hours=1))

    summary = qi.repair_summary()
    assert summary["repair_runs"] == 1
    assert summary["repaired_total"] == 2 and summary["repairs_unconfirmed"] == 0
    assert {r["domain"] for r in summary["repairs"]} == {"x.example", "y.example"}


def test_a_failed_plan_is_kept_when_a_left_out_source_reads_what_it_would_have_written(
        env, monkeypatch) -> None:
    """z now reads disqualified: the failed run MAY have applied it, so its record (the only revert
    record for z) stays and the new plan is appended."""
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
        _add(s, "z.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    state = _failing_then_ok(monkeypatch)
    with pytest.raises(RuntimeError):
        qi.auto_repair_inversions(now=NOW)
    state["broken"] = False
    with env.scope() as s:
        s.query(Source).filter_by(domain="z.example").one().status = STATUS_DISQUALIFIED
        _add(s, "y.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW + timedelta(hours=1))

    first = env.store[qi.REPAIR_RUN_PREFIX + qi._iso(NOW)]
    assert {r["domain"] for r in first["repairs"]} == {"x.example", "z.example"}
    assert len(qi._read_repair_index()["runs"]) == 2


def test_a_second_revert_marks_the_records_a_stopped_revert_left_unmarked(env, monkeypatch) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    run_key = qi.REPAIR_RUN_PREFIX + qi._iso(NOW)
    import src.config.kv_store as kv

    real = kv.kv_set_json

    def disk_full_for_runs(key, obj):
        if key.startswith(qi.REPAIR_RUN_PREFIX):
            raise OSError("disk full")
        real(key, obj)

    monkeypatch.setattr(kv, "kv_set_json", disk_full_for_runs)
    with pytest.raises(OSError):
        qi.revert_repairs(dry_run=False)
    assert _status(env, "x.example").status == STATUS_QUALIFIED          # row reverted and held
    assert not env.store[run_key]["repairs"][0].get("reverted_at")        # but the record is unmarked
    monkeypatch.setattr(kv, "kv_set_json", real)

    dry = qi.revert_repairs(dry_run=True)
    assert dry["reverted"] == 0 and dry["already_reverted_unmarked"] == 1
    out = qi.revert_repairs(dry_run=False)
    assert out["already_reverted_unmarked"] == 1
    assert env.store[run_key]["repairs"][0]["reverted_at"]
    assert _status(env, "x.example").status == STATUS_QUALIFIED
    assert qi.revert_repairs(dry_run=True)["already_reverted_unmarked"] == 0


def test_the_revert_refuses_naming_an_unreadable_run_and_changes_nothing(env, monkeypatch, capsys) -> None:
    import importlib.util
    from pathlib import Path

    import src.config.kv_store as kv

    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    run_key = qi.REPAIR_RUN_PREFIX + qi._iso(NOW)
    before = {k: dict(v) for k, v in env.store.items()}
    strict = kv.kv_get_json_strict

    def flaky(key):
        if key == run_key:
            raise OSError("database is locked")
        return strict(key)

    monkeypatch.setattr(kv, "kv_get_json_strict", flaky)
    with pytest.raises(qi.UnreadableRunRecord) as excinfo:
        qi.revert_repairs(dry_run=False)
    assert excinfo.value.run_at == qi._iso(NOW)
    assert env.store == before and _status(env, "x.example").status == STATUS_DISQUALIFIED

    spec = importlib.util.spec_from_file_location(
        "repair_script3", Path(__file__).resolve().parents[1] / "scripts"
        / "repair_qualification_inversions.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(["--revert-repairs", "--apply"]) == 2
    err = capsys.readouterr().err
    assert qi._iso(NOW) in err and "nothing was changed" in err


def test_repaired_rows_names_the_unreadable_runs_instead_of_dropping_them(env, monkeypatch) -> None:
    """An unreadable run's domains are unknown; the export must be told, not read "none repaired"."""
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    run_key = qi.REPAIR_RUN_PREFIX + qi._iso(NOW)
    rows, unreadable = qi.repaired_rows()
    assert list(rows) == ["x.example"] and rows["x.example"] and unreadable == []
    import src.config.kv_store as kv

    strict = kv.kv_get_json_strict

    def flaky(key):
        if key == run_key:
            raise OSError("database is locked")
        return strict(key)

    monkeypatch.setattr(kv, "kv_get_json_strict", flaky)
    assert qi.repaired_rows() == ({}, [qi._iso(NOW)])


def test_an_unreadable_newest_run_at_the_same_instant_is_not_overwritten(env, monkeypatch) -> None:
    """A clock stepped back gives the new run the unreadable run's own key; writing it would
    replace the record byte for byte kept elsewhere."""
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    run_key = qi.REPAIR_RUN_PREFIX + qi._iso(NOW)
    before = dict(env.store[run_key])
    with env.scope() as s:
        _add(s, "y.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    import src.config.kv_store as kv

    strict = kv.kv_get_json_strict

    def flaky(key):
        if key == run_key:
            raise OSError("database is locked")
        return strict(key)

    monkeypatch.setattr(kv, "kv_get_json_strict", flaky)
    out = qi.auto_repair_inversions(now=NOW)
    assert out["repaired"] == 0 and "skipped" in out
    assert env.store[run_key] == before
    assert _status(env, "y.example").status == STATUS_QUALIFIED


def test_repaired_domains_lists_applied_unreverted_repairs_only(env) -> None:
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
        _add(s, "y.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)
    assert qi.repaired_domains() == {"x.example", "y.example"}
    env.store[qi.REPAIR_RUN_PREFIX + qi._iso(NOW)]["repairs"][0]["reverted_at"] = "2026-10-01T00:00:00+00:00"
    reverted = env.store[qi.REPAIR_RUN_PREFIX + qi._iso(NOW)]["repairs"][0]["domain"]
    assert reverted not in qi.repaired_domains()
    env.store[qi.REPAIR_RUN_PREFIX + qi._iso(NOW)]["applied"] = False      # planned, never applied
    assert qi.repaired_domains() == set()


def test_the_strict_reader_does_not_serve_a_corrupt_value_from_the_cache(tmp_path, monkeypatch) -> None:
    import sqlite3

    import src.config.kv_store as kv

    db = tmp_path / "open_omniscience.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    kv.kv_invalidate()
    kv.kv_set_json("k", {"a": 1})
    kv.kv_invalidate()
    with sqlite3.connect(db) as c:
        c.execute("UPDATE app_state SET value = ? WHERE key = 'k'", ('{"a": 1',))
    assert kv.kv_get_json("k") is None                  # the lenient reader caches the raw value
    with pytest.raises(ValueError):
        kv.kv_get_json_strict("k")                      # ...and the strict one must not trust the cache
    kv.kv_invalidate()


def test_a_restore_does_not_carry_the_repair_record(tmp_path) -> None:
    from src.backup.merge import merge_corpus
    from src.database.models import AppState
    from tests.test_merge_source_qualification import _BATCH_META, _corpus

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    mine = {"runs": ["2026-09-30T12:00:00+00:00"], "last_run_at": "x", "reverted_domains": ["keep.example"]}
    with _corpus(working)() as s:
        s.add(AppState(key=qi.REPAIR_INDEX_KEY, value=__import__("json").dumps(mine)))
        s.commit()
    with _corpus(staged)() as s:
        s.add(AppState(key=qi.REPAIR_INDEX_KEY, value='{"runs": ["other"], "reverted_domains": []}'))
        s.add(AppState(key=qi.REPAIR_RUN_PREFIX + "other", value='{"applied": true, "repairs": []}'))
        s.commit()

    merge_corpus(staged, working, _BATCH_META)
    with _corpus(working)() as s:
        rows = {r.key: r.value for r in s.query(AppState).all()}
    assert __import__("json").loads(rows[qi.REPAIR_INDEX_KEY]) == mine, "this machine's record is untouched"
    assert qi.REPAIR_RUN_PREFIX + "other" not in rows, "another machine's record never arrives"


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "repair_script_cli", Path(__file__).resolve().parents[1] / "scripts"
        / "repair_qualification_inversions.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def test_revert_repairs_is_a_dry_run_through_the_script_unless_apply_is_given(env) -> None:
    script = _load_script()
    with env.scope() as s:
        _add(s, "x.example", STATUS_QUALIFIED, STATUS_DISQUALIFIED)
    qi.auto_repair_inversions(now=NOW)

    assert script.main(["--revert-repairs"]) == 0
    assert _status(env, "x.example").status == STATUS_DISQUALIFIED, "no --apply, nothing written"
    assert qi._read_repair_index()["reverted_domains"] == []
    script.main(["--revert-repairs", "--apply"])
    assert _status(env, "x.example").status == STATUS_QUALIFIED
    assert qi._read_repair_index()["reverted_domains"] == ["x.example"]


def test_the_boot_block_is_exercised_and_never_raises(monkeypatch, caplog) -> None:
    """Not only read from the syntax tree: the real try block of run_deferred_startup is cut out
    of main.py and run, once with a repair that fails and once with one that repaired."""
    import ast
    import logging
    import textwrap

    source = _MAIN_PY.read_text(encoding="utf-8")
    tries = [n for n in _boot_call_ancestry() if isinstance(n, ast.Try)]
    node = tries[0]
    block = textwrap.dedent(" " * node.col_offset + ast.get_source_segment(source, node))
    log = logging.getLogger("test.boot")

    def boom():
        raise RuntimeError("store locked")

    monkeypatch.setattr(qi, "auto_repair_inversions", boom)
    with caplog.at_level(logging.INFO, logger="test.boot"):
        exec(compile(block, "<boot-block>", "exec"), {"logger": log})   # must not raise
    assert any("could not reconcile" in r.getMessage() for r in caplog.records)

    caplog.clear()
    monkeypatch.setattr(qi, "auto_repair_inversions", lambda: {"repaired": 3})
    with caplog.at_level(logging.INFO, logger="test.boot"):
        exec(compile(block, "<boot-block>", "exec"), {"logger": log})
    assert any("Restored 3 source" in r.getMessage() for r in caplog.records)


def test_ruling_12_a_measured_local_verdict_survives_an_imported_disqualification(tmp_path, monkeypatch) -> None:
    """The whole path for the case the coordinator's ruling is about: a verdict measured HERE,
    a newer disqualification imported from another instance. The merge keeps the local status
    (C2) and the next boot does not take it back."""
    import copy

    from src.backup.merge import merge_corpus
    from tests.test_merge_source_qualification import (
        _BATCH_META,
        _MEASURED,
        _SEEN,
        _T0,
        _add_attempt,
        _add_source,
        _corpus,
        _integrity,
        _sources,
    )

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(working)() as s:
        sid = _add_source(s, "mine.example", status="qualified", at=_T0, version=_MEASURED)
        _add_attempt(s, sid, "qualified", _T0, version=_MEASURED)
        s.commit()
    with _corpus(staged)() as s:
        sid = _add_source(s, "mine.example", status="disqualified", at=None, version=None)
        _add_attempt(s, sid, "disqualified", _SEEN, version=_MEASURED)
        s.commit()
    merge_corpus(staged, working, _BATCH_META)
    assert _sources(working)["mine.example"].status == "qualified"
    assert _integrity(working)["inversions_total"] == 1

    maker = _corpus(working)
    store: dict[str, dict] = {}

    @contextlib.contextmanager
    def scope():
        s = maker()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    import src.config.kv_store as kv
    import src.database.session as sess

    monkeypatch.setenv(qi.AUTO_REPAIR_ENV, "1")
    monkeypatch.setattr(sess, "session_scope", scope)
    monkeypatch.setattr(kv, "kv_get_json", lambda key: copy.deepcopy(store.get(key)))
    monkeypatch.setattr(kv, "kv_get_json_strict", lambda key: copy.deepcopy(store.get(key)))
    monkeypatch.setattr(kv, "kv_set_json", lambda key, obj: store.__setitem__(key, copy.deepcopy(obj)))
    assert qi.auto_repair_inversions(now=NOW)["repaired"] == 0
    assert _sources(working)["mine.example"].status == "qualified", "12 = b: it is not taken back"
    assert not store, "and nothing was recorded"
