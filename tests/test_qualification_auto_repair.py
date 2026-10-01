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
T0 = datetime(2026, 8, 1, 9, 0)  # naive UTC, as every writer stores it


@pytest.fixture()
def env(monkeypatch):
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
    monkeypatch.setattr(kv, "kv_set_json", lambda key, obj: store.__setitem__(key, copy.deepcopy(obj)))

    class Env:
        pass

    e = Env()
    e.maker, e.store, e.scope = maker, store, scope
    yield e
    engine.dispose()


def _add(s: Session, domain: str, live: str, judged: str, *, at: datetime = T0,
         live_version: str | None = None, live_at: datetime | None = None) -> int:
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
    assert qi.repair_summary()["repaired_total"] == 0


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
             live_version="stampA", live_at=T0)
    qi.auto_repair_inversions(now=NOW)
    # re-qualified later by a real judgement (attempt + stamp together), then inverted again
    t1 = T0 + timedelta(days=9)
    with env.scope() as s:
        src = s.query(Source).filter_by(domain="x.example").one()
        src.status, src.qualification_criteria_version, src.qualified_at = (
            STATUS_QUALIFIED, "stampB", t1)
        s.add(SourceQualificationAttempt(
            source_id=src.id, attempted_at=t1, verdict=STATUS_QUALIFIED, criteria_version="v1"))
    t2 = t1 + timedelta(days=9)
    _attempt(env, "x.example", STATUS_DISQUALIFIED, t2)
    qi.auto_repair_inversions(now=NOW + timedelta(days=30))

    result = qi.revert_repairs(dry_run=False)
    assert result["reverted"] == 1, "one domain, one revert, never two"
    got = _status(env, "x.example")
    assert got.qualification_criteria_version == "stampB" and got.qualified_at == t1


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


def _boot_call_ancestry():
    import ast
    from pathlib import Path

    tree = ast.parse(Path("src/api/main.py").read_text(encoding="utf-8"))
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
