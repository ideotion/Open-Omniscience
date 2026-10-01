"""The forced re-check list (PR 3 of the rank 14 fix, 2026-10-01).

A verdict measured here that an imported history disagrees with is never changed by that history
(rule 12 = b), but a copied-in attempt resets the re-verification clock, so its own re-check would
come a whole interval after the OTHER instance's attempt. The boot step lists such sources
(``qualification.recheck_first``); the pass takes them ahead of its two ordinary pools, within the
same re-check budget, least recently tried first, and never more than half of the slots.

Scheduling only: no network, the trial fetch is skipped and the cohort is injected, exactly like
tests/test_qualification_recheck.py, whose fixtures and helpers are reused.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog import qualification as q
from src.catalog import qualification_integrity as qi
from src.catalog.qualification import (
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    VERDICT_NO_EVIDENCE,
    allocate_rechecks,
    pending_forced_rechecks,
    qualification_queue,
)
from src.database.models import Base, Source
from tests.test_qualification_recheck import LONG_AGO, NOW, _attempt, _selected, _src

MEASURED = "oo-source-qualification-3"
CURATED = "oo-curated-catalog-1"
T_FLAG = NOW - timedelta(days=1)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def store(monkeypatch):
    data: dict[str, dict] = {}
    import src.config.kv_store as kv

    monkeypatch.setattr(kv, "kv_get_json", lambda key: copy.deepcopy(data.get(key)))
    monkeypatch.setattr(kv, "kv_get_json_strict", lambda key: copy.deepcopy(data.get(key)))
    monkeypatch.setattr(kv, "kv_set_json", lambda key, obj: data.__setitem__(key, copy.deepcopy(obj)))
    return data


def _flag(store, *sources, at=T_FLAG):
    store[q.RECHECK_FIRST_KEY] = {"flagged": {str(s.id): at.replace(tzinfo=None).isoformat() for s in sources}}


def _inverted_qualified(db, domain, *, newest_disq_days_ago=10):
    """Live qualified (measured stamp) against a NEWER imported disqualification: not due by
    any ordinary clock, because the copied-in attempt reset it."""
    s = _src(db, domain, STATUS_QUALIFIED, qualified_at=LONG_AGO)
    s.qualification_criteria_version = MEASURED
    db.commit()
    _attempt(db, s, STATUS_QUALIFIED, LONG_AGO)
    _attempt(db, s, STATUS_DISQUALIFIED, NOW - timedelta(days=newest_disq_days_ago))
    return s


def test_a_flagged_source_is_checked_although_no_ordinary_clock_is_due(db, store):
    a = _inverted_qualified(db, "a.example")
    assert _selected(db, per_pass=0, recheck_per_pass=2) == set(), "nothing is due without the flag"
    _flag(store, a)
    assert _selected(db, per_pass=0, recheck_per_pass=2) == {"a.example"}


def test_the_safe_order_is_flagged_too(db, store):
    """Live disqualified against a newer imported qualification (S7a): its disqualified ladder
    would wait a month from the other instance's attempt."""
    b = _src(db, "b.example", STATUS_DISQUALIFIED)
    _attempt(db, b, STATUS_DISQUALIFIED, LONG_AGO)
    _attempt(db, b, STATUS_QUALIFIED, NOW - timedelta(days=3))
    assert _selected(db, per_pass=0, recheck_per_pass=2) == set()
    _flag(store, b)
    assert _selected(db, per_pass=0, recheck_per_pass=2) == {"b.example"}


def test_a_re_check_budget_of_zero_switches_the_list_off_too(db, store):
    a = _inverted_qualified(db, "a.example")
    _flag(store, a)
    assert _selected(db, per_pass=5, recheck_per_pass=0) == set()


def test_an_unreachable_host_goes_to_the_back_and_a_judgement_settles_it(db, store):
    """no_evidence is not a judgement: the entry stays, but being the MOST recently tried it
    yields the head of the line to a source nobody has tried; a local judgement writes the verdict
    and the status together, so the entry is no longer inverted and drops out."""
    dead = _inverted_qualified(db, "dead.example")
    fresh = _inverted_qualified(db, "fresh.example")
    _attempt(db, dead, VERDICT_NO_EVIDENCE, NOW - timedelta(hours=1))   # the host never answers
    _flag(store, dead, fresh)

    assert [s.domain for s in pending_forced_rechecks(db)] == ["fresh.example", "dead.example"]
    # one slot: the untried source gets it, not the dead host
    assert _selected(db, per_pass=0, recheck_per_pass=1) == {"fresh.example"}

    _attempt(db, fresh, STATUS_DISQUALIFIED, NOW + timedelta(hours=1))   # a local judgement ran
    fresh.status = STATUS_DISQUALIFIED                                  # ...and settled it
    db.commit()
    assert [s.domain for s in pending_forced_rechecks(db)] == ["dead.example"]


def test_a_healed_inversion_leaves_the_list(db, store):
    a = _inverted_qualified(db, "a.example")
    _flag(store, a)
    a.status = STATUS_DISQUALIFIED          # live now agrees with the newest judging attempt
    db.commit()
    assert pending_forced_rechecks(db) == []


def test_a_long_list_cannot_starve_the_ordinary_re_checks(db, store):
    """The share: with 4 slots the list takes 2, and the longest-overdue ordinary re-checks keep
    the other 2, however long the list is."""
    flagged = [_inverted_qualified(db, f"f{i}.example") for i in range(6)]
    _flag(store, *flagged)
    for i in range(3):
        old = _src(db, f"old{i}.example", STATUS_QUALIFIED, qualified_at=LONG_AGO)
        _attempt(db, old, STATUS_QUALIFIED, LONG_AGO + timedelta(days=i))
    picked = _selected(db, per_pass=0, recheck_per_pass=4)
    assert len({d for d in picked if d.startswith("f")}) == 2
    assert picked >= {"old0.example", "old1.example"}


def test_a_slot_the_ordinary_queue_cannot_use_goes_back_to_the_list(db, store):
    flagged = [_inverted_qualified(db, f"f{i}.example") for i in range(6)]
    _flag(store, *flagged)
    picked = _selected(db, per_pass=0, recheck_per_pass=4)
    assert len(picked) == 4, "nothing ordinary is due, so the whole budget is the list's"


def test_allocate_without_a_list_is_the_ordinary_split():
    class S:
        def __init__(self, i):
            self.id = i

    dq, ql = [S(1), S(2), S(3)], [S(11), S(12), S(13)]
    assert [x.id for x in allocate_rechecks([], dq, ql, 4)] == [1, 2, 11, 12]
    assert [x.id for x in allocate_rechecks([], dq, [], 2)] == [1, 2]


def test_an_unreadable_list_means_todays_order(db, monkeypatch):
    import src.config.kv_store as kv

    def boom(_key):
        raise OSError("locked")

    monkeypatch.setattr(kv, "kv_get_json", boom)
    _inverted_qualified(db, "a.example")
    assert _selected(db, per_pass=0, recheck_per_pass=2) == set()


def test_the_queue_view_counts_the_flagged_and_follows_the_pass(db, store):
    a = _inverted_qualified(db, "a.example")
    _flag(store, a)
    view = qualification_queue(db, now=NOW, recheck_per_pass=2)
    assert view["rechecks"]["flagged"] == 1
    assert [r["domain"] for r in view["rechecks"]["next"]] == ["a.example"]
    off = qualification_queue(db, now=NOW, recheck_per_pass=0)
    assert off["rechecks"]["flagged"] == 0


# ---------------------------------------------------------------- the boot step that lists them

def test_the_boot_step_lists_measured_inversions_in_both_directions(db, store, monkeypatch):
    import contextlib

    import src.database.session as sess

    @contextlib.contextmanager
    def scope():
        yield db

    monkeypatch.setattr(sess, "session_scope", scope)
    monkeypatch.setenv(qi.AUTO_REPAIR_ENV, "1")
    qual = _inverted_qualified(db, "qual.example")
    dis = _src(db, "dis.example", STATUS_DISQUALIFIED)
    _attempt(db, dis, STATUS_DISQUALIFIED, LONG_AGO)
    _attempt(db, dis, STATUS_QUALIFIED, NOW - timedelta(days=3))
    cat = _src(db, "cat.example", STATUS_QUALIFIED, qualified_at=LONG_AGO)   # catalogue stamp
    cat.qualification_criteria_version = CURATED
    db.commit()
    _attempt(db, cat, STATUS_DISQUALIFIED, NOW - timedelta(days=2))

    out = qi.flag_inversions_for_recheck(now=NOW)
    flagged = store[q.RECHECK_FIRST_KEY]["flagged"]
    assert out["flagged"] == 2 and set(flagged) == {str(qual.id), str(dis.id)}, (
        "the catalogue-stamped row is the boot repair's, not this list's")

    # idempotent, and an entry keeps its ORIGINAL flag instant
    first = dict(flagged)
    qi.flag_inversions_for_recheck(now=NOW + timedelta(days=5))
    assert store[q.RECHECK_FIRST_KEY]["flagged"] == first

    # a healed inversion drops out at the next boot
    qual.status = STATUS_DISQUALIFIED
    db.commit()
    qi.flag_inversions_for_recheck(now=NOW + timedelta(days=6))
    assert set(store[q.RECHECK_FIRST_KEY]["flagged"]) == {str(dis.id)}


def test_the_boot_step_fails_closed_and_can_be_switched_off(db, store, monkeypatch):
    import src.config.kv_store as kv

    _inverted_qualified(db, "a.example")
    monkeypatch.setenv(qi.AUTO_REPAIR_ENV, "0")
    assert "skipped" in qi.flag_inversions_for_recheck(now=NOW) and not store
    monkeypatch.setenv(qi.AUTO_REPAIR_ENV, "1")

    def locked(_key):
        raise OSError("database is locked")

    monkeypatch.setattr(kv, "kv_get_json_strict", locked)
    out = qi.flag_inversions_for_recheck(now=NOW)
    assert out["flagged"] == 0 and "cannot be read" in out["skipped"] and not store


def test_the_boot_calls_the_flagging_step_outside_any_session_scope_and_swallows_failure():
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/api/main.py").read_text(encoding="utf-8"))
    parents = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "flag_inversions_for_recheck"]
    assert len(calls) == 1
    node: ast.AST = calls[0]
    chain = []
    while id(node) in parents:
        node = parents[id(node)]
        chain.append(node)
    assert any(isinstance(n, ast.Try) and any(
        h.type is not None and ast.unparse(h.type) == "Exception" for h in n.handlers) for n in chain)
    assert not any(isinstance(n, ast.With) and "session_scope" in ast.unparse(n.items[0].context_expr)
                   for n in chain)
    assert not any(isinstance(n, ast.If) and "OO_AUTOSEED" in ast.unparse(n.test) for n in chain)


def test_the_pass_reports_how_many_rechecks_came_from_the_list(db, store):
    a = _inverted_qualified(db, "a.example")
    _flag(store, a)
    out = q.run_qualification_pass(
        db, None, per_pass=0, recheck_per_pass=2, now=NOW,
        cohort_provider=lambda: {
            "min_articles": 1, "cohort_cut": {}, "cohort": {"baselines": {}, "lang_short_cut": {}},
            "token": "t", "articles": 0, "sources": 0, "furniture_df": None,
        },
    )
    assert out["forced_rechecks"] == 1 and out["rechecks"] == 1
    assert db.query(Source).count() == 1
