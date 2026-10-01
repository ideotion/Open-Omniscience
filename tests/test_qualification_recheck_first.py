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
    allocate_rechecks,
    pending_forced_rechecks,
    qualification_queue,
)
from src.database.models import Base, Source, SourceQualificationAttempt
from tests.test_qualification_recheck import LONG_AGO, NOW, _attempt, _selected, _src

MEASURED = "oo-source-qualification-3"
CURATED = "oo-curated-catalog-1"
T_FLAG = NOW - timedelta(days=1)


def _COHORT():
    return {
        "min_articles": 1, "cohort_cut": {}, "cohort": {"baselines": {}, "lang_short_cut": {}},
        "token": "t", "articles": 0, "sources": 0, "furniture_df": None,
    }


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


def _flag(store, *sources, at=T_FLAG, tried=None, turn="ordinary"):
    """``tried`` maps a domain to when THIS install last tried it (the entry's own record)."""
    tried = tried or {}
    store[q.RECHECK_FIRST_KEY] = {
        "turn": turn,
        "flagged": {
            str(s.id): {
                "flagged_at": at.replace(tzinfo=None).isoformat(),
                "last_tried_at": tried[s.domain].replace(tzinfo=None).isoformat() if s.domain in tried else None,
            }
            for s in sources
        },
    }


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
    """The order is when THIS install last tried the entry, recorded in the entry: a host that
    never answers is stamped at every try and yields the head of the line to a source nobody has
    tried; a local judgement writes the verdict and the status together, so the entry is no
    longer inverted and drops out."""
    dead = _inverted_qualified(db, "dead.example")
    fresh = _inverted_qualified(db, "fresh.example")
    _flag(store, dead, fresh, tried={"dead.example": NOW - timedelta(hours=1)})

    assert [s.domain for s in pending_forced_rechecks(db)] == ["fresh.example", "dead.example"]
    # one slot: the untried source gets it, not the dead host
    assert _selected(db, per_pass=0, recheck_per_pass=1) == {"fresh.example"}

    _attempt(db, fresh, STATUS_DISQUALIFIED, NOW + timedelta(hours=1))   # a local judgement ran
    fresh.status = STATUS_DISQUALIFIED                                  # ...and settled it
    db.commit()
    assert [s.domain for s in pending_forced_rechecks(db)] == ["dead.example"]


def test_the_order_ignores_the_attempt_log_whose_newest_row_is_the_copied_in_one(db, store):
    """For a flagged source the newest attempt is the imported one that inverted it, and it may
    carry a clock AHEAD of this machine's. That must not park the entry at the back."""
    ahead = _inverted_qualified(db, "ahead.example", newest_disq_days_ago=-30)   # 30 days in the future
    other = _inverted_qualified(db, "other.example", newest_disq_days_ago=10)
    _flag(store, ahead, other, tried={"other.example": NOW - timedelta(days=1)})
    assert [s.domain for s in pending_forced_rechecks(db)][0] == "ahead.example", "never tried here"


def test_a_pass_stamps_what_it_tried_so_a_dead_host_sinks_and_the_rest_rotate(db, store):
    a = _inverted_qualified(db, "a.example")
    b = _inverted_qualified(db, "b.example")
    c = _inverted_qualified(db, "c.example")
    _flag(store, a, b, c)

    def one_pass(hours):
        before = {x.id for x in db.query(SourceQualificationAttempt).all()}
        q.run_qualification_pass(
            db, None, per_pass=0, recheck_per_pass=1, now=NOW + timedelta(hours=hours),
            cohort_provider=_COHORT)
        ids = {x.source_id for x in db.query(SourceQualificationAttempt).all() if x.id not in before}
        return {x.domain for x in db.query(Source).filter(Source.id.in_(ids or {-1})).all()}

    # an empty cohort judges nothing: every try writes no_evidence, as a dead host does
    assert [one_pass(h) for h in (1, 2, 3, 4)] == [{"a.example"}, {"b.example"}, {"c.example"}, {"a.example"}]
    stamped = store[q.RECHECK_FIRST_KEY]["flagged"]
    assert all(e["last_tried_at"] for e in stamped.values())


def test_with_an_odd_budget_the_extra_slot_changes_hands_each_pass(db, store):
    """One slot, a long list and an ordinary queue that is due: rounding the slot up for the list
    would give it to the list every pass. It alternates instead."""
    flagged = [_inverted_qualified(db, f"f{i}.example") for i in range(4)]
    _flag(store, *flagged)
    for i in range(4):
        old = _src(db, f"old{i}.example", STATUS_QUALIFIED, qualified_at=LONG_AGO)
        _attempt(db, old, STATUS_QUALIFIED, LONG_AGO + timedelta(days=i))

    def kind(hours):
        before = {x.id for x in db.query(SourceQualificationAttempt).all()}
        q.run_qualification_pass(
            db, None, per_pass=0, recheck_per_pass=1, now=NOW + timedelta(hours=hours),
            cohort_provider=_COHORT)
        ids = {x.source_id for x in db.query(SourceQualificationAttempt).all() if x.id not in before}
        names = {x.domain for x in db.query(Source).filter(Source.id.in_(ids or {-1})).all()}
        return "list" if any(n.startswith("f") for n in names) else "ordinary"

    assert [kind(h) for h in (1, 2, 3, 4)] == ["ordinary", "list", "ordinary", "list"]


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

    # an entry this install already tried keeps its record across boots
    store[q.RECHECK_FIRST_KEY]["flagged"][str(qual.id)]["last_tried_at"] = "2026-09-04T00:00:00"
    qi.flag_inversions_for_recheck(now=NOW + timedelta(days=5))
    assert store[q.RECHECK_FIRST_KEY]["flagged"][str(qual.id)]["last_tried_at"] == "2026-09-04T00:00:00"

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
        cohort_provider=_COHORT,
    )
    assert out["forced_rechecks"] == 1 and out["rechecks"] == 1
    assert db.query(Source).count() == 1


# ------------------------------------------------- the reviews' findings (Opus on #1285)

class _S:
    def __init__(self, i):
        self.id = i


def _due_disqualified(db, domain):
    s = _src(db, domain, STATUS_DISQUALIFIED)
    _attempt(db, s, STATUS_DISQUALIFIED, LONG_AGO)
    return s


def _due_qualified(db, domain, days=0):
    s = _src(db, domain, STATUS_QUALIFIED, qualified_at=LONG_AGO)
    _attempt(db, s, STATUS_QUALIFIED, LONG_AGO + timedelta(days=days))
    return s


def _new_attempts(db, before):
    return [x for x in db.query(SourceQualificationAttempt).all() if x.id not in before]


def test_a_budget_of_one_never_spends_more_than_one_slot(db, store):
    """On the list's turn with both ordinary pools due, a budget of one used to spend three slots
    (a negative slice count took almost the whole qualified pool)."""
    f = _inverted_qualified(db, "f.example")
    _flag(store, f, turn="list")
    _due_disqualified(db, "dq.example")
    _due_qualified(db, "ql1.example")
    _due_qualified(db, "ql2.example", 1)
    before = {x.id for x in db.query(SourceQualificationAttempt).all()}
    out = q.run_qualification_pass(
        db, None, per_pass=0, recheck_per_pass=1, now=NOW, cohort_provider=_COHORT)
    assert out["rechecks"] == 1 and len(_new_attempts(db, before)) == 1
    for turn in (True, False):
        assert len(allocate_rechecks([_S(1)], [_S(2)], [_S(3), _S(4)], 1, odd_to_list=turn)) == 1


def test_no_budget_up_to_seven_ever_overspends_or_repeats_a_source():
    forced = [_S(i) for i in range(1, 5)]
    dq = [_S(2), _S(10), _S(11)]            # 2 is flagged AND due in the disqualified pool
    ql = [_S(3), _S(20), _S(21)]
    for total in range(0, 8):
        for turn in (False, True):
            ids = [x.id for x in allocate_rechecks(forced, dq, ql, total, odd_to_list=turn)]
            assert len(ids) <= total and len(ids) == len(set(ids)), (total, turn, ids)


def test_a_flagged_source_that_is_also_due_in_a_pool_is_evaluated_once(db, store):
    s = _src(db, "both.example", STATUS_DISQUALIFIED)
    s.qualification_criteria_version = MEASURED
    db.commit()
    _attempt(db, s, STATUS_DISQUALIFIED, LONG_AGO)
    _attempt(db, s, STATUS_QUALIFIED, NOW - timedelta(days=45))     # imported, newer, disagrees
    _flag(store, s)
    for i in range(3):
        _due_disqualified(db, f"dq{i}.example")
    before = {x.id for x in db.query(SourceQualificationAttempt).all()}
    q.run_qualification_pass(
        db, None, per_pass=0, recheck_per_pass=4, now=NOW, cohort_provider=_COHORT)
    mine = [x for x in _new_attempts(db, before) if x.source_id == s.id]
    assert len(mine) == 1


def test_a_row_reset_to_unqualified_is_left_to_the_new_candidate_queue(db, store):
    a = _inverted_qualified(db, "a.example")
    _flag(store, a)
    a.status = "unqualified"
    db.commit()
    assert pending_forced_rechecks(db) == []
    before = {x.id for x in db.query(SourceQualificationAttempt).all()}
    q.run_qualification_pass(
        db, None, per_pass=2, recheck_per_pass=2, now=NOW, cohort_provider=_COHORT)
    assert len([x for x in _new_attempts(db, before) if x.source_id == a.id]) <= 1


def test_the_default_budget_lets_both_ordinary_kinds_advance_while_the_list_has_entries(db, store):
    """Budget 2, a list, and BOTH ordinary pools due: the single ordinary slot alternates between
    the disqualified and the qualified side instead of the disqualified side always winning."""
    flagged = [_inverted_qualified(db, f"f{i}.example") for i in range(3)]
    _flag(store, *flagged)
    _due_disqualified(db, "dq.example")
    _due_qualified(db, "ql.example")

    def ordinary_kind(hours):
        before = {x.id for x in db.query(SourceQualificationAttempt).all()}
        q.run_qualification_pass(
            db, None, per_pass=0, recheck_per_pass=2, now=NOW + timedelta(hours=hours),
            cohort_provider=_COHORT)
        names = {db.get(Source, x.source_id).domain for x in _new_attempts(db, before)}
        return sorted(n for n in names if not n.startswith("f"))

    assert [ordinary_kind(h) for h in (1, 2)] == [["dq.example"], ["ql.example"]]
    forced = [_S(1)]
    chosen, contested = q.allocate_rechecks_detail(forced, [_S(2)], [_S(3)], 2, odd_to_list=False)
    assert [x.id for x in chosen] == [1, 2] and contested
    chosen, contested = q.allocate_rechecks_detail(forced, [_S(2)], [_S(3)], 2, odd_to_list=True)
    assert [x.id for x in chosen] == [1, 3] and contested


def test_an_entry_that_never_settles_stops_being_forced_after_a_few_tries(db, store):
    a = _inverted_qualified(db, "dead.example")
    _flag(store, a)
    for hour in range(q.MAX_FORCED_TRIES):
        assert [s.domain for s in pending_forced_rechecks(db)] == ["dead.example"]
        q.run_qualification_pass(
            db, None, per_pass=0, recheck_per_pass=2, now=NOW + timedelta(hours=hour),
            cohort_provider=_COHORT)          # an empty cohort never judges it: it stays inverted
    entry = store[q.RECHECK_FIRST_KEY]["flagged"][str(a.id)]
    assert entry["tries"] == q.MAX_FORCED_TRIES
    assert pending_forced_rechecks(db) == []
    assert qualification_queue(db, now=NOW, recheck_per_pass=2)["rechecks"]["flagged"] == 0


def test_the_boot_step_keeps_the_tries_of_an_entry_it_lists_again(db, store, monkeypatch):
    monkeypatch.setenv(qi.AUTO_REPAIR_ENV, "1")
    a = _inverted_qualified(db, "a.example")
    _flag(store, a)
    store[q.RECHECK_FIRST_KEY]["flagged"][str(a.id)]["tries"] = 2
    import src.database.session as sess
    from contextlib import contextmanager

    @contextmanager
    def scope():
        yield db

    monkeypatch.setattr(sess, "session_scope", scope)
    qi.flag_inversions_for_recheck(now=NOW)
    assert store[q.RECHECK_FIRST_KEY]["flagged"][str(a.id)]["tries"] == 2


def test_a_stored_entry_of_the_wrong_shape_does_not_fail_the_pass(db, store):
    a = _inverted_qualified(db, "a.example")
    store[q.RECHECK_FIRST_KEY] = {"turn": "ordinary", "flagged": {
        str(a.id): {"flagged_at": 5, "last_tried_at": ["x"], "tries": "many"}, "junk": 3}}
    assert [s.domain for s in pending_forced_rechecks(db)] == ["a.example"]
    store[q.RECHECK_FIRST_KEY] = {"flagged": ["not", "a", "dict"]}
    assert pending_forced_rechecks(db) == []
    q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=_COHORT)


def test_recording_a_try_never_rewrites_a_list_it_could_not_read(db, store, monkeypatch):
    a = _inverted_qualified(db, "a.example")
    _flag(store, a)
    before = copy.deepcopy(store[q.RECHECK_FIRST_KEY])
    import src.config.kv_store as kv

    def locked(_key):
        raise OSError("database is locked")

    monkeypatch.setattr(kv, "kv_get_json_strict", locked)
    q.record_forced_tries({a.id}, now=NOW, odd_budget=True)
    assert store[q.RECHECK_FIRST_KEY] == before


def test_the_tries_are_recorded_after_the_pass_committed(db, store, monkeypatch):
    a = _inverted_qualified(db, "a.example")
    _flag(store, a)
    seen: list[bool] = []
    real = q.record_forced_tries

    def spy(ids, **kw):
        seen.append(db.in_transaction())     # kv_set_json must never run inside an open transaction
        return real(ids, **kw)

    monkeypatch.setattr(q, "record_forced_tries", spy)
    q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=2, now=NOW, cohort_provider=_COHORT)
    assert seen == [False]


def test_the_ordinary_pools_are_queried_a_share_deeper_while_the_list_has_entries(db, store, monkeypatch):
    a = _inverted_qualified(db, "a.example")
    _flag(store, a)
    limits: list[int] = []
    real = q.select_due_disqualified

    def spy(session, **kw):
        limits.append(kw["limit"])
        return real(session, **kw)

    monkeypatch.setattr(q, "select_due_disqualified", spy)
    q.run_qualification_pass(db, None, per_pass=0, recheck_per_pass=4, now=NOW, cohort_provider=_COHORT)
    assert limits == [4 + (4 + 1) // 2]


def test_the_queue_view_follows_the_turn_of_the_contested_slot(db, store):
    f = _inverted_qualified(db, "f.example")
    _due_disqualified(db, "dq.example")
    _due_qualified(db, "ql.example")
    names = {}
    for turn in ("ordinary", "list"):
        _flag(store, f, turn=turn)
        view = qualification_queue(db, now=NOW, recheck_per_pass=2, next_limit=2)
        names[turn] = [r["domain"] for r in view["rechecks"]["next"]]
    assert names["ordinary"] == ["f.example", "dq.example"]
    assert names["list"] == ["f.example", "ql.example"]
