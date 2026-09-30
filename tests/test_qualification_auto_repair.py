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


def test_boot_runs_the_repair_outside_the_seeding_transaction() -> None:
    """Source-level guard (the function is called from run_deferred_startup): kv_set_json must
    not run inside an open ORM write transaction on the same thread."""
    from pathlib import Path

    src = Path("src/api/main.py").read_text(encoding="utf-8")
    seed_end = src.index("could not seed the source catalog at startup")
    call = src.index("auto_repair_inversions()", seed_end)
    assert call > seed_end, "the repair must follow the seeding block, never sit inside it"
