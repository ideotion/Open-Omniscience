"""
Tests for story lineage (Theme 4) — wire detection + time-ordered chain.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.signals import detect_wire_attribution, trace_lineage


def test_detect_wire_attribution():
    assert detect_wire_attribution("The minister resigned, according to Reuters.") == "Reuters"
    assert detect_wire_attribution("(AFP) — Talks collapsed overnight.") == "AFP"
    assert detect_wire_attribution("Bloomberg reported record profits.") == "Bloomberg"
    assert detect_wire_attribution("A local council met on Tuesday.") is None
    # bare 'ap' must not false-positive on ordinary words like 'apple'
    assert detect_wire_attribution("She bought an apple at the shop.") is None


def test_trace_lineage_orders_by_time_and_finds_wire():
    now = datetime.now(UTC)
    docs = [
        {"id": "3", "source": "Late Echo", "text": "Reuters reported the deal closed.",
         "published_at": now},
        {"id": "1", "source": "Wire Desk", "text": "According to Reuters, the deal closed today.",
         "published_at": now - timedelta(hours=6)},
        {"id": "2", "source": "Mid Echo", "text": "The deal closed, sources say.",
         "published_at": now - timedelta(hours=2)},
    ]
    lin = trace_lineage(docs)
    assert lin.n == 3
    assert lin.primary.doc_id == "1"                 # earliest published is the primary candidate
    assert [i.doc_id for i in lin.chain] == ["1", "2", "3"]
    assert lin.wire_origin == "Reuters"
    assert "earliest" in lin.caveat.lower()


def test_undated_sort_last():
    now = datetime.now(UTC)
    docs = [
        {"id": "a", "source": "X", "text": "no date here", "published_at": None},
        {"id": "b", "source": "Y", "text": "dated", "published_at": now},
    ]
    lin = trace_lineage(docs)
    assert lin.primary.doc_id == "b"                 # the dated one leads; undated sorts last
    assert lin.chain[-1].doc_id == "a"
