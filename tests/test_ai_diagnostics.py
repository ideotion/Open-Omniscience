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
    # `hardware` joined in 2026-07-30 (the inference hardware-suitability gate):
    # a SEPARATE question from `backend`'s "which backend would serve" -- an
    # unsuitable machine can still resolve a backend, start it, and then crawl.
    assert set(out) == {
        "schema", "backend", "hardware", "active_model", "context", "vllm", "jobs",
    }


def test_report_carries_every_named_ai_job_summary():
    out = AID.ai_diagnostics_report()
    jobs = out["jobs"]
    assert set(jobs) == {
        "keyword_triage", "source_tags", "perception_eval_live",
        "perception_extract", "language_detection",
    }
    # each is a real report dict (honest "nothing has run yet" stubs on a fresh
    # test environment -- never a crash, never absent).
    for name, report in jobs.items():
        assert isinstance(report, dict), f"{name} report must be a dict"


def test_backend_section_reports_gpu_and_ollama_facts():
    out = AID.ai_diagnostics_report()
    backend = out["backend"]
    assert "backend" in backend and "gpu" in backend and "ollama_available" in backend
    # V4 (2026-07-29): capability rides into ai.json for free (the block is a
    # verbatim resolve_backend() passthrough) -- the bundle must be able to say
    # "no working backend", not just "ollama selected".
    assert "available" in backend and "no_backend" in backend


def test_a_backend_probe_failure_degrades_that_section_only(monkeypatch):
    def _raise():
        raise RuntimeError("simulated nvidia-smi probe crash")

    monkeypatch.setattr(AID, "_backend_facts", _raise)
    out = AID.ai_diagnostics_report()
    # section_ok, NOT available: a crashed PROBE and a genuinely unreachable
    # BACKEND are different facts and must not share a key (2026-07-29).
    assert out["backend"]["section_ok"] is False
    assert "available" not in out["backend"], (
        "a failed probe must not report a capability it never observed")
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
    assert out["jobs"]["keyword_triage"]["section_ok"] is False
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


def test_the_vllm_block_carries_the_install_attempt_history_and_its_bound():
    """V3 (2026-07-29): a FAILED vLLM install leaves no marker (correct, by
    design), so a bundle would otherwise show install_info: null with nothing
    saying an install was ever attempted or why it died -- exactly what the
    2026-07-29 operator bundle showed. The attempt journal rides ai.json's vllm
    block (a verbatim status() passthrough), bounded, and states its own bound so
    a tail is never read as a complete log. The measured install COST rides with
    it, so a refusal is diagnosable from the bundle alone."""
    out = AID.ai_diagnostics_report()
    vllm = out["vllm"]
    assert isinstance(vllm.get("install_history"), list)
    bounds = vllm["install_history_bounds"]
    assert bounds["attempts_cap"] >= 1
    assert bounds["output_line_cap"] >= 1
    assert "attempts_kept" in bounds and "recording" in bounds
    assert vllm["preflight"]["schema"] == "oo-vllm-install-preflight-1"


def test_a_failed_probe_is_distinguishable_from_an_unreachable_backend(monkeypatch):
    """The sentinel key must not collide with a real measurement.

    ``resolve_backend()`` returns ``available: False`` to mean "the selected backend
    is unreachable right now" -- a MEASUREMENT, and the operator's actual 2026-07-29
    state. ``_safe`` used the SAME key to mean "this probe raised" -- the ABSENCE of a
    measurement. A reader of ai.json comparing two machines could not tell one from
    the other, which turns a graceful degrade into a hiding place for the very fault
    it exists to survive.

    Both directions are pinned here: the happy path must still publish a REAL
    ``available``, and the sad path must publish ``section_ok`` and no ``available``
    at all."""
    real = AID.ai_diagnostics_report()["backend"]
    assert "available" in real and isinstance(real["available"], bool), (
        "the success path must still report measured capability")
    assert "section_ok" not in real, "a working section must not carry the failure sentinel"

    def _raise():
        raise RuntimeError("nvidia-smi hung")

    monkeypatch.setattr(AID, "_backend_facts", _raise)
    degraded = AID.ai_diagnostics_report()["backend"]
    assert degraded["section_ok"] is False
    assert "available" not in degraded
    assert "nvidia-smi hung" in degraded["error"]


def test_a_crashed_backend_probe_never_becomes_a_claim_about_vllm(monkeypatch):
    """`_context_settings` derives its vLLM branch from the backend facts. When the
    backend probe CRASHED, `vllm.installed` is missing because nothing was observed --
    not because vLLM is absent -- so reporting "vLLM is not installed" would
    manufacture a fact about the machine out of a failed probe."""
    def _raise():
        raise RuntimeError("nvidia-smi hung")

    monkeypatch.setattr(AID, "_backend_facts", _raise)
    ctx = AID.ai_diagnostics_report()["context"]
    assert ctx["vllm"]["available"] is None, "unknown, never a fabricated False"
    assert "probe failed" in ctx["vllm"]["reason"]
    # ...and the honest gap for Ollama's static setting is still reported.
    assert "configured_num_ctx" in ctx["ollama"]
