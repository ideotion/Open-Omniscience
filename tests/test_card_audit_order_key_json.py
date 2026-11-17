"""The card audit's ``order_key`` is valid JSON (field test 2026-11-14, row 64).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A card with no dated evidence sorts last on recency with ``-inf`` by design; the audit wrote it as ``-Infinity``,
which is not JSON. It now reads ``null`` with the reason beside it, and the ordering itself is unchanged.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from src.briefing.card import Card
from src.briefing.card_audit import _order_key_fields
from src.briefing.leads import order_key

NOW = datetime(2026, 11, 16, tzinfo=UTC)


def _card(evidence):
    return Card(type="rising", title="t", summary="s", bucket="rising", signal={}, method="m", caveat="c",
                evidence=evidence, n=10)


def test_a_card_without_dated_evidence_reads_null_with_its_reason():
    key = order_key(_card([{"title": "x", "outlet": "a.test"}]), now=NOW)
    assert key[2] == float("-inf")  # the sort keeps its design
    out = _order_key_fields(key)
    assert out["order_key"] == [1, key[1], None] and "date" in out["recency_missing"]
    json.dumps(out, allow_nan=False)  # strict JSON: raises on -inf


def test_a_dated_card_is_unchanged_and_carries_no_note():
    key = order_key(_card([{"title": "x", "outlet": "a.test", "published_at": "2026-11-15T00:00:00Z"}]), now=NOW)
    out = _order_key_fields(key)
    assert out == {"order_key": list(key)} and out["order_key"][2] == -1.0
