"""Tests for dismiss-with-reason capture (Cards batch E, evidence-tier remainder).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The store is local, JSON-backed, no schema, counts-only (never a score); it is kept
SEPARATE from the dismissed-id set so the additive feedback capture never risks the
dismissal mechanic itself.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


def test_record_and_summarize(data_dir):
    from src.briefing.dismiss_reasons import all_reasons, record_reason, reason_summary

    record_reason("card-1", "Not relevant", card_type="rising")
    record_reason("card-2", "not relevant", card_type="rising")  # same reason, different case
    record_reason("card-3", "Already knew this", card_type="diet_self_audit")
    record_reason("card-4", "", card_type="rising")  # blank reason is still real feedback

    assert len(all_reasons()) == 4
    summary = reason_summary()
    assert summary["total"] == 4
    assert summary["with_reason"] == 3
    # By type: rising dismissed 3x, diet 1x.
    assert summary["by_card_type"]["rising"] == 3
    assert summary["by_card_type"]["diet_self_audit"] == 1
    # Case-folded grouping: "Not relevant" + "not relevant" count together.
    by_reason = {r["reason"]: r["count"] for r in summary["by_reason"]}
    assert by_reason["not relevant"] == 2
    assert by_reason["(no reason given)"] == 1
    # No score anywhere in the read side — check field NAMES recursively, never a
    # repr() substring (the method text legitimately says "no score").
    def _no_score_keys(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert "score" not in str(k).lower() and str(k).lower() not in {"rank", "rating"}
                _no_score_keys(v)
        elif isinstance(obj, list):
            for v in obj:
                _no_score_keys(v)

    _no_score_keys(summary)


def test_record_requires_card_id(data_dir):
    from src.briefing.dismiss_reasons import record_reason

    with pytest.raises(ValueError):
        record_reason("", "some reason")


def test_reason_is_length_capped(data_dir):
    from src.briefing.dismiss_reasons import all_reasons, record_reason

    record_reason("card-x", "y" * 5000)
    assert len(all_reasons()[-1]["reason"]) <= 500


def test_clear_reasons(data_dir):
    from src.briefing.dismiss_reasons import all_reasons, clear_reasons, record_reason

    record_reason("card-1", "noise")
    clear_reasons()
    assert all_reasons() == []


def test_corrupt_non_list_reasons_does_not_crash(data_dir):
    """A version-matching payload with a non-list 'reasons' must NOT crash the
    append/iterate paths (would otherwise 500 the endpoints)."""
    import json

    from src.briefing.dismiss_reasons import _path, all_reasons, record_reason, reason_summary

    _path().write_text(json.dumps({"version": "oo-dismiss-reasons-1", "reasons": "oops"}), "utf-8")
    # Neither the write path nor the read path may raise on the malformed payload.
    record_reason("card-9", "still works")
    assert reason_summary()["total"] == 1
    assert len(all_reasons()) == 1


def test_dismiss_reason_endpoints(data_dir):
    from src.api.main import app

    with TestClient(app) as c:
        r = c.post("/api/signals/dismiss-reason",
                   json={"card_id": "abc123", "reason": "Wrong", "card_type": "rising"})
        assert r.status_code == 200 and r.json()["recorded"] is True
        # A missing card_id is a 400, never a silent no-op.
        bad = c.post("/api/signals/dismiss-reason", json={"card_id": "", "reason": "x"})
        assert bad.status_code == 400
        summary = c.get("/api/signals/dismiss-reasons").json()
        assert summary["total"] == 1
        assert summary["by_card_type"]["rising"] == 1
