"""
Tor throughput — per-kind ladder + segmented-download math (planning §5).

Pure tests over deterministic fixtures (no network). The §5 non-negotiables are the assertions:
ordering ≠ exclusion (a floored/low-weight kind is never starved; an unreachable mirror is kept,
not deleted), and a segmented download can NEVER pass off a partial/corrupt file — integrity is
MANDATORY (a content-swap or a missing checksum is refused, not silently trusted). No composite
score. Includes the two skeptic regressions: floor-never-starves-a-peer, and reassemble refuses a
content swap / a missing checksum.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib

import pytest

from src.ingest.tor_throughput import (
    KindLadder,
    plan_segments,
    rank_mirrors,
    reassemble,
    run_tor_throughput_selftest,
)


def _run_ladder(rates, floors=None, *, steps=200):
    lad = KindLadder(rates=rates, floors=floors)
    served = []
    for _ in range(steps):
        k = lad.next_kind(set(rates))
        if k is not None:
            served.append(k)
    return served


def test_ladder_serves_high_weight_more_but_never_starves_a_low_one():
    served = _run_ladder({"markets": 5.0, "crawl": 0.5}, {"crawl": 0.2})
    assert served.count("markets") > served.count("crawl")  # priority respected (~10:1)
    assert served.count("crawl") >= 1  # ordering != exclusion — the low-weight kind is served


def test_ladder_floor_never_starves_an_equal_weight_peer():
    # Skeptic F2: a floor set at the peer's own weight must NOT lock the peer out (was a=0, b=2000).
    served = _run_ladder({"a": 1.0, "b": 1.0}, {"a": 0.0, "b": 1.0}, steps=1000)
    assert served.count("a") >= 1 and served.count("b") >= 1
    # equal effective weight -> roughly balanced, never a lockout
    assert abs(served.count("a") - served.count("b")) <= 1


def test_ladder_floor_delivers_real_volume_to_a_zero_priority_kind():
    # A zero-rate kind with a floor is served at its floor weight (VOLUME, not just a tie-break).
    served = _run_ladder({"fast": 4.0, "slow": 0.0}, {"slow": 0.5}, steps=45)
    assert served.count("slow") >= 3  # ~45 * 0.5/4.5 ≈ 5


def test_ladder_zero_weight_kind_is_an_honest_no_op():
    # rate 0 AND no floor -> the kind asks for no share and is never served (not a starvation).
    served = _run_ladder({"a": 1.0, "idle": 0.0}, steps=50)
    assert served.count("idle") == 0 and served.count("a") == 50


def test_ladder_empty_pending_and_no_kinds():
    assert KindLadder({"a": 1.0}).next_kind(set()) is None
    with pytest.raises(ValueError):
        KindLadder({})


def test_ladder_is_deterministic():
    a = _run_ladder({"x": 3.0, "y": 1.0}, steps=40)
    b = _run_ladder({"x": 3.0, "y": 1.0}, steps=40)
    assert a == b


def test_plan_segments_tiles_exactly_and_respects_min_seg():
    segs = plan_segments(100, 4, min_seg=10)
    assert segs[0][0] == 0 and segs[-1][1] == 100
    assert all(segs[i][1] == segs[i + 1][0] for i in range(len(segs) - 1))  # contiguous
    assert sum(e - s for s, e in segs) == 100
    assert all((e - s) >= 10 for s, e in segs)


def test_plan_segments_edge_cases():
    assert plan_segments(5, 4, min_seg=10) == [(0, 5)]  # too small -> one whole segment
    assert plan_segments(0, 4) == []
    with pytest.raises(ValueError):
        plan_segments(100, 0)
    with pytest.raises(ValueError):
        plan_segments(100, 4, min_seg=0)


def test_reassemble_roundtrip_and_order_independence():
    data = b"abcdefghij"
    parts = [(4, data[4:10]), (0, data[0:4])]  # out of order on purpose
    got = reassemble(parts, expected_total=10, expected_sha256=hashlib.sha256(data).hexdigest())
    assert got == data


def test_reassemble_integrity_is_mandatory_and_airtight():
    good = hashlib.sha256(b"abcdefghij").hexdigest()
    with pytest.raises(ValueError):  # gap
        reassemble([(0, b"ab"), (4, b"ef")], expected_total=6, expected_sha256=good)
    with pytest.raises(ValueError):  # overlap
        reassemble([(0, b"abcd"), (2, b"cdef")], expected_total=6, expected_sha256=good)
    with pytest.raises(ValueError):  # wrong total (truncation)
        reassemble([(0, b"abcd")], expected_total=10, expected_sha256=good)
    with pytest.raises(ValueError):  # checksum mismatch
        reassemble([(0, b"abcd"), (4, b"XXXXXX")], expected_total=10, expected_sha256=good)
    # THE data-safety line: a content-swap that satisfies contiguity must be REFUSED by the digest
    with pytest.raises(ValueError):
        reassemble([(0, b"BBB"), (3, b"AAA")], expected_total=6,
                   expected_sha256=hashlib.sha256(b"AAABBB").hexdigest())
    # ...and omitting the checksum refuses rather than trusts
    with pytest.raises(ValueError):
        reassemble([(0, b"abcd")], expected_total=4, expected_sha256="")


def test_reassemble_accepts_uppercase_manifest_hex():
    data = b"abcdefghij"
    upper = hashlib.sha256(data).hexdigest().upper()
    assert reassemble([(0, data)], expected_total=10, expected_sha256=upper) == data


def test_rank_mirrors_orders_by_latency_and_keeps_unreachable_last():
    ranked = rank_mirrors({
        "slow": [{"ok": True, "latency_ms": 900}, {"ok": True, "latency_ms": 1100}],
        "fast": [{"ok": True, "latency_ms": 100}, {"ok": True, "latency_ms": 120}],
        "dead": [{"ok": False, "latency_ms": None}],
    })
    order = [m["mirror"] for m in ranked["mirrors"]]
    assert order == ["fast", "slow", "dead"]  # measured latency; unreachable last, NOT excluded
    assert ranked["mirrors"][-1]["reachable"] is False
    assert ranked["mirrors"][2]["mirror"] == "dead"  # still present


def test_rank_mirrors_reports_ok_rate_and_n():
    ranked = rank_mirrors({"m": [{"ok": True, "latency_ms": 50}, {"ok": False, "latency_ms": None}]})
    row = ranked["mirrors"][0]
    assert row["n"] == 2 and row["ok"] == 1 and row["ok_rate"] == 0.5


def test_selftest_all_green():
    log = run_tor_throughput_selftest()
    assert log["passed"] is True, [c for c in log["checks"] if not c["passed"]]


def test_no_score_field_anywhere():
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade"))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(rank_mirrors({"m": [{"ok": True, "latency_ms": 50}]}))
    walk(run_tor_throughput_selftest())
