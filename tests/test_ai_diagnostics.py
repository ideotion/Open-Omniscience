"""
Tests for the `ai` diagnostics member (B7.1, 2026-07-24 field-feedback Session B) --
src/monitoring/ai_diagnostics.py + GET /api/diagnostics/ai. No network: the backend/
vLLM/job-report probes are cheap, local, and already honest-degrading on their own,
so these tests exercise the real functions directly (only forcing failures where
needed to prove the degrade-never-crash contract).
"""

from __future__ import annotations

import json

from src.api import diagnostics as d
from src.monitoring import ai_diagnostics as AID


def test_report_has_the_expected_top_level_shape():
    out = AID.ai_diagnostics_report()
    assert out["schema"] == AID.SCHEMA
    assert set(out) == {"schema", "backend", "active_model", "context", "vllm", "jobs"}


def test_report_carries_every_named_ai_job_summary():
    out = AID.ai_diagnostics_report()
    jobs = out["jobs"]
    assert set(jobs) == {
        "keyword_triage", "source_tags", "perception_eval_live",
        "perception_extract", "language_detection",
    }
    # each is a real report dict (honest {available: False} stubs on a fresh
    # test environment where nothing has ever run -- never a crash, never absent).
    for name, report in jobs.items():
        assert isinstance(report, dict), f"{name} report must be a dict"


def test_backend_section_reports_gpu_and_ollama_facts():
    out = AID.ai_diagnostics_report()
    backend = out["backend"]
    assert "backend" in backend and "gpu" in backend and "ollama_available" in backend


def test_a_backend_probe_failure_degrades_that_section_only(monkeypatch):
    def _raise():
        raise RuntimeError("simulated nvidia-smi probe crash")

    monkeypatch.setattr(AID, "_backend_facts", _raise)
    out = AID.ai_diagnostics_report()
    assert out["backend"]["available"] is False
    assert "simulated nvidia-smi probe crash" in out["backend"]["error"]
    # the rest of the report still comes back -- one section's crash never
    # takes down the whole diagnostics member.
    assert "jobs" in out and isinstance(out["jobs"], dict)


def test_a_job_report_failure_degrades_that_one_job_only(monkeypatch):
    def _raise():
        raise RuntimeError("simulated corrupt log")

    monkeypatch.setattr(
        "src.ai_layer.triage_job.last_keyword_triage_report", _raise
    )
    out = AID.ai_diagnostics_report()
    assert out["jobs"]["keyword_triage"]["available"] is False
    assert "simulated corrupt log" in out["jobs"]["keyword_triage"]["error"]
    # a sibling job report is unaffected.
    assert isinstance(out["jobs"]["source_tags"], dict)


def test_context_settings_report_both_backends_honestly():
    out = AID.ai_diagnostics_report()
    ctx = out["context"]
    assert "vllm" in ctx and "ollama" in ctx
    # vLLM not installed in this test environment -> an honest unavailable stub,
    # never a fabricated computed context.
    assert ctx["vllm"].get("available") is False
    # Ollama's context is a STATIC configured setting -- no RAM-derived auto-tune
    # exists yet, and that gap is stated, not hidden.
    assert "configured_num_ctx" in ctx["ollama"]
    assert "no ram-derived auto-tune" in ctx["ollama"]["method"].lower()


def test_no_secret_looking_field_names_anywhere_in_the_payload():
    """A conservative secret-name scan (the debug-bundle / no-score-field walker
    convention): no key in the serialized payload looks like it is carrying a
    credential. This report only ever touches loopback URLs, GPU facts, and
    already-safe report files, so this should trivially hold -- pinned as a
    regression guard against a future field accidentally dumping raw settings."""
    out = AID.ai_diagnostics_report()
    blob = json.dumps(out).lower()
    for bad in ("password", "passphrase", "api_key", "apikey", "secret", "access_token"):
        assert bad not in blob, f"the ai diagnostics payload must never mention {bad!r}"


def test_endpoint_returns_the_same_report_as_json():
    resp = d.ai_diagnostics()
    body = json.loads(bytes(resp.body))
    assert body["schema"] == AID.SCHEMA
