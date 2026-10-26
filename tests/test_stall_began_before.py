"""R206 (stall forensics item G): a statement LONGER than the request that ended inside it is the shape of a lock holder, and the
"not longer than the request" rule drops it without a trace. It is now listed under ``began_before`` as evidence only: it never feeds
``found``, ``share_of_request`` or ``classify`` (the log has no thread id, so a holder and a bystander look the same)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.monitoring import slowquery
from src.monitoring import stall_forensics as sf

_END = datetime(2026, 10, 16, 16, 19, 59, tzinfo=UTC)


def _row(end, ms, sql):
    return {"at": end.isoformat(timespec="seconds"), "duration_ms": ms, "sql": sql}


@pytest.fixture
def rows(monkeypatch):
    held: list[dict] = []
    monkeypatch.setattr(slowquery, "recent", lambda limit=20: held)
    return held


def test_the_holder_is_listed_and_the_waiters_own_statement_is_still_the_one_named(rows):
    rows += [_row(_END - timedelta(seconds=1), 6_000.0, "INSERT holder"), _row(_END, 4_540.0, "INSERT waiter")]
    got = sf._statement_evidence(4_550.0, now=_END)
    assert got["found"] and got["sql"] == "INSERT waiter" and got["share_of_request"] < 1.0  # unchanged
    held = got["began_before"]
    assert [h["sql"] for h in held] == ["INSERT holder"]
    assert held[0]["overlap_share"] == 1.0 and held[0]["began_before_s"] > 0
    # no new class: the ambiguity is not turned into a verdict
    assert sf.classify({"statement": got}) == ["slow-statement"]


def test_the_field_savepoint_is_listed_but_never_read_as_more_than_the_request(rows):
    rows += [
        _row(_END - timedelta(minutes=5), 41_100.0, "SAVEPOINT sa_savepoint_1"),
        _row(_END - timedelta(seconds=2), 56_853.6, "SAVEPOINT sa_savepoint_1"),
        _row(_END, 55_310.8, "SELECT count(*) AS count_1 FROM keyword_mentions_all"),
    ]
    got = sf._statement_evidence(55_554.8, now=_END)
    assert got["sql"].startswith("SELECT count(*)") and got["share_of_request"] < 1.0
    assert [h["duration_ms"] for h in got["began_before"]] == [56_853.6]
    assert 0.0 < got["began_before"][0]["overlap_share"] <= 1.0


def test_a_statement_that_ended_before_the_request_is_not_listed(rows):
    rows += [_row(_END - timedelta(minutes=4), 55_000.0, "SELECT count(*)")]
    got = sf._statement_evidence(174_128.3, now=_END + timedelta(seconds=240))
    assert got["found"] is False and "began_before" not in got


def test_only_longer_statements_are_listed_when_nothing_else_ended_inside(rows):
    rows += [_row(_END, 9_000.0, "INSERT holder")]
    got = sf._statement_evidence(5_000.0, now=_END)
    assert got["found"] is False and [h["sql"] for h in got["began_before"]] == ["INSERT holder"]


def test_at_most_the_longest_two_are_listed_and_a_bound_value_is_never_carried(rows):
    rows += [_row(_END, 6_000.0 + i, f"S{i} " + "x" * 200) for i in range(5)]
    got = sf._statement_evidence(1_000.0, now=_END)
    assert [h["duration_ms"] for h in got["began_before"]] == [6_004.0, 6_003.0]
    assert all(len(h["sql"]) <= 80 for h in got["began_before"])


def test_a_record_without_one_costs_nothing_and_an_unreadable_time_is_skipped(rows):
    rows += [{"at": "x", "duration_ms": 90_000.0, "sql": "S"}, _row(_END, 500.0, "SELECT 1")]
    got = sf._statement_evidence(1_000.0, now=_END)
    assert "began_before" not in got


def test_the_report_says_what_the_list_means():
    assert "began_before" in sf._assemble([], [])["method"]


def test_the_numbers_are_exact_and_bounded_by_the_slack(rows):
    # request 5 s ending at _END, so it opened at _END - 5 s and the window opens a second earlier; a 9 s row ending 2 s before the end
    rows += [_row(_END - timedelta(seconds=2), 9_000.0, "INSERT holder")]
    got = sf._statement_evidence(5_000.0, now=_END)
    (held,) = got["began_before"]
    # it began 9 s before its end = 11 s before _END; the window opened 6 s before _END, so 5 s earlier: lower bound of the true 5 to 6 s
    assert held["began_before_s"] == 5.0
    # it covered from the window's opening to its end: 4 s of a 5 s request (an upper bound; the true value is 3 to 4 s)
    assert held["overlap_share"] == 0.8


def test_a_row_that_only_touches_the_slack_is_not_listed(rows):
    rows += [_row(_END - timedelta(seconds=6), 9_000.0, "INSERT holder")]  # ended exactly where the window opens: no overlap
    got = sf._statement_evidence(5_000.0, now=_END)
    assert got["found"] is False and "began_before" not in got


def test_a_time_that_is_not_finite_is_no_evidence_and_never_reaches_the_json(rows):
    import json

    rows += [_row(_END, float("nan"), "S1"), _row(_END, float("inf"), "S2"), _row(_END, 9_000.0, "INSERT holder")]
    got = sf._statement_evidence(5_000.0, now=_END)
    assert [h["sql"] for h in got["began_before"]] == ["INSERT holder"]
    json.dumps(got, allow_nan=False)
    assert "began_before" not in sf._statement_evidence(float("nan"), now=_END)
