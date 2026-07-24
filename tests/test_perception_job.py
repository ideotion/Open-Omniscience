"""
Tests for src/ai_layer/perception_job.py -- the persisted LIVE perception-eval
artifact (B6, 2026-07-24 Session B). No network: an injected fake client
stands in for the model.
"""

from __future__ import annotations

import json

from src.ai_layer import perception_job as J


class _FakeResult:
    def __init__(self, text: str):
        self.text = text


class _FakeClient:
    def generate(self, prompt, *, model, system=None, keep_alive=None):
        return _FakeResult("WHO: none\nWHERE: none\nWHEN: none")


class _RaisingClient:
    def generate(self, *a, **kw):
        from src.llm.ollama import LLMUnavailable

        raise LLMUnavailable("simulated outage")


def test_last_report_is_an_honest_stub_when_nothing_has_run(monkeypatch, tmp_path):
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    out = J.last_perception_eval_live_report()
    assert out["available"] is False
    assert "note" in out


def test_run_and_persist_writes_a_dated_json_and_returns_it(monkeypatch, tmp_path):
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    out = J.run_and_persist_perception_eval(_FakeClient(), model="stub:test")
    assert out["status"] == "ok"
    assert out["schema"] == J.PERCEPTION_LIVE_SCHEMA
    assert out["model"] == "stub:test"
    assert "report" in out
    assert "run_at" in out
    assert out["path"] and out["filename"]

    # the file on disk is valid JSON and round-trips the same payload shape
    files = list(tmp_path.glob("oo-perception-eval-live-*.json"))
    assert len(files) == 1
    on_disk = json.loads(files[0].read_text(encoding="utf-8"))
    assert on_disk["status"] == "ok" and on_disk["model"] == "stub:test"


def test_last_report_reads_the_newest_saved_run(monkeypatch, tmp_path):
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    J.run_and_persist_perception_eval(_FakeClient(), model="stub:test")
    last = J.last_perception_eval_live_report()
    assert last["available"] is True
    assert last["model"] == "stub:test"
    assert last["schema"] == J.PERCEPTION_LIVE_SCHEMA


def test_an_outage_still_persists_an_honest_unavailable_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    out = J.run_and_persist_perception_eval(_RaisingClient(), model="stub:test")
    assert out["status"] == "unavailable"
    assert "report" not in out
    last = J.last_perception_eval_live_report()
    assert last["status"] == "unavailable"


def test_last_report_degrades_honestly_on_a_corrupt_file(monkeypatch, tmp_path):
    monkeypatch.setattr(J, "_dir", lambda: tmp_path)
    bad = tmp_path / "oo-perception-eval-live-20260101-000000-000000.json"
    bad.write_text("{not valid json", encoding="utf-8")
    out = J.last_perception_eval_live_report()
    assert out["available"] is False
    assert "error" in out
