"""
The stall ring in the diagnostics bundle (R159). The ring holds 200 records and a field record is ~1.7 KB, so a full ring is over
320 KB against the 200,000-byte line the plan gives ``contention.json``; no slot row covers it and a row would take the part below its
fixed floor. The member therefore shows as many records as fit the line, net of the gate section and the frame, the longest and the
newest, and SAYS how many it shows of how many the ring holds. The ring itself is untouched.
"""

from __future__ import annotations

import json

import pytest

from src.api.diagnostics import bundle
from src.monitoring import stall_forensics as sf
from tests.test_stall_forensics import _field_shaped_ring, _quiet


@pytest.fixture(autouse=True)
def _clean():
    sf._reset_for_tests()
    yield
    sf._reset_for_tests()


def _rec(i: int, duration_ms: float, pad: int = 0) -> dict:
    return {"at": "2026-10-16T16:00:00+00:00", "route": f"GET /api/r{i:03d}", "status": 200, "duration_ms": duration_ms,
            "consistent_with": ["undetermined"], "evidence": {"pad": "x" * pad}}


def _fill(rows: list[dict]) -> None:
    for r in rows:
        sf._RING.append(r)


def test_the_member_for_a_full_ring_of_the_widest_field_records_is_within_the_line(monkeypatch):
    _field_shaped_ring(monkeypatch, 123456.789)  # the real note_stall, 200 records of the field's shape
    member = bundle._contention_member()
    size = len(bundle._member_bytes(member))
    assert size <= sf.CONTENTION_LINE_BYTES
    sel = member["sections"]["stall-forensics"]["selection"]
    assert sel["of"] == sf._RING_CAP and 0 < sel["shown"] < sf._RING_CAP
    assert sel["basis"].startswith("longest+newest, fit to ")
    assert member["sections"]["stall-forensics"]["shown"] == sel["shown"] == len(member["sections"]["stall-forensics"]["stalls"])
    # as many as fit: what is left is less than the widest record, so no further record would have gone in
    widest = max(len(bundle._member_bytes(r)) for r in sf._RING) + 1
    assert sf.CONTENTION_LINE_BYTES - size < widest
    # the ring is untouched
    assert len(sf._RING) == sf._RING_CAP


def test_a_ring_that_fits_is_shown_whole_and_says_so(monkeypatch):
    _quiet(monkeypatch)
    for _ in range(5):
        sf.note_stall("GET /api/x", 200, 30_000.0)
    member = bundle._contention_member()
    sel = member["sections"]["stall-forensics"]["selection"]
    assert (sel["shown"], sel["of"]) == (5, 5)


def test_the_longest_stall_survives_when_it_is_the_oldest():
    # the ring drops its oldest record first, and the oldest may hold the worst stall: newest-only would lose it
    rows = [_rec(i, 900_000.0 - 10_000 * i, pad=400) for i in range(60)]  # the older, the longer
    _fill(rows)
    one = len(json.dumps(rows[1], separators=(",", ":"))) + 1
    rep = sf.report_fit(max_bytes=2500 + 12 * one)
    shown = {r["route"] for r in rep["stalls"]}
    assert "GET /api/r000" in shown  # the longest, oldest
    assert "GET /api/r059" in shown  # the newest
    assert 0 < len(rep["stalls"]) < 60
    assert rep["selection"]["shown"] == len(rep["stalls"]) and rep["selection"]["of"] == 60
    # newest first, as the route gives it
    ats = [int(r["route"].rsplit("r", 1)[1]) for r in rep["stalls"]]
    assert ats[:-1] == sorted(ats[:-1], reverse=True)


def test_a_record_that_is_both_longest_and_newest_is_taken_once():
    rows = [_rec(i, 6_000.0 + i, pad=100) for i in range(30)]  # the newest is also the longest
    _fill(rows)
    rep = sf.report_fit(max_bytes=10_000_000)
    routes = [r["route"] for r in rep["stalls"]]
    assert len(routes) == len(set(routes)) == 30


def test_the_section_never_exceeds_its_bytes_and_a_record_too_wide_is_passed_over():
    rows = [_rec(0, 800_000.0, pad=5000)] + [_rec(i, 6_000.0, pad=50) for i in range(1, 40)]
    _fill(rows)
    cap = 6000
    rep = sf.report_fit(max_bytes=cap)
    assert sf._size(rep) <= cap
    assert all(r["route"] != "GET /api/r000" for r in rep["stalls"])  # 5 KB wide: does not fit, smaller ones do
    assert rep["stalls"]
    # a cap smaller than the header shows no records and still says what it holds
    tiny = sf.report_fit(max_bytes=10)
    assert tiny["stalls"] == [] and tiny["selection"]["of"] == 40


def test_the_route_and_the_in_memory_report_still_give_the_whole_ring(monkeypatch):
    _field_shaped_ring(monkeypatch, None)
    assert len(sf.report(limit=sf._RING_CAP)["stalls"]) == sf._RING_CAP
    assert "selection" not in sf.report(limit=10)


def test_the_budget_counts_every_byte_down_to_the_comma_between_records():
    rows = [_rec(i, 6_000.0 + i) for i in range(40)]  # 40 records of one width
    _fill(rows)
    r = len(json.dumps(rows[0], separators=(",", ":")))
    everything = sf._size(sf.report_fit(max_bytes=9_999))  # four digits in the basis, like the budgets below
    header = everything - 40 * r - 39  # the header at its widest (both counts at two digits)
    assert sf.report_fit(max_bytes=header + 10 * (r + 1))["selection"]["shown"] == 10
    assert sf.report_fit(max_bytes=header + 10 * (r + 1) - 1)["selection"]["shown"] == 9
    # and what is shown is what the bytes were counted for
    rep = sf.report_fit(max_bytes=header + 10 * (r + 1))
    assert sf._size(rep) <= header + 10 * (r + 1)


def test_a_large_gate_section_takes_its_bytes_out_of_the_stall_records(monkeypatch):
    _field_shaped_ring(monkeypatch, 1234)
    monkeypatch.setattr(bundle, "write_gate_report", lambda: {"holders": ["t" * 50] * 1000})  # ~51 KB of gate section
    member = bundle._contention_member()
    assert len(bundle._member_bytes(member)) <= sf.CONTENTION_LINE_BYTES
    assert member["sections"]["stall-forensics"]["selection"]["shown"] < 100
