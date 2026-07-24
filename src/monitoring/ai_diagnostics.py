"""
The `ai` diagnostics member (B7.1, 2026-07-24 field-feedback Session B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A secret-safe, READ-ONLY snapshot of the whole dual-backend AI stack for the
all-diagnostics bundle: which backend is active and why (hardware detection
facts), the active model, context/concurrency settings, and the last saved
summary of every AI-layer background job (keyword-triage, source-tag
assignment, the live perception-eval harness run, the perception-extraction
sweep, the continuous language-detection job).

Never runs anything itself -- every field is either a cheap live probe
(``resolve_backend``/``vllm_lifecycle.status`` -- GPU/vLLM-process facts,
no secrets) or a READ of an already-saved report file. Each section degrades
to an honest ``{"available": False, "error": ...}`` on its own failure rather
than ever taking down the whole bundle (the debug-bundle ``_safe()`` /
per-diagnostic-degrades convention).
"""

from __future__ import annotations

SCHEMA = "oo-ai-diagnostics-1"


def _safe(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - one section's failure must not break the rest
        return {"available": False, "error": str(exc)[:300]}


def _backend_facts() -> dict:
    from src.llm.backend import resolve_backend

    return resolve_backend()


def _context_settings(backend_facts: dict) -> dict:
    """Context/window sizing for whichever backend is active. vLLM's is a
    COMPUTED, disclosed heuristic (``compute_server_args``, B2); Ollama's is
    the STATIC configured setting -- there is NO RAM-derived auto-tune for
    Ollama's ``num_ctx`` yet (a genuine gap from B2's own scope, carried over
    honestly rather than silently omitted or fabricated here)."""
    from src.config.app_settings import load_settings

    out: dict = {}
    gpu = backend_facts.get("gpu") or {}
    vllm_installed = bool((backend_facts.get("vllm") or {}).get("installed"))
    if vllm_installed:
        from src.llm.vllm_lifecycle import compute_server_args

        out["vllm"] = compute_server_args(gpu.get("vram_mb"))
    else:
        out["vllm"] = {"available": False, "reason": "vLLM is not installed"}

    settings = load_settings()
    out["ollama"] = {
        "configured_num_ctx": getattr(settings, "llm_max_context_length", None),
        "method": "static configured setting -- NO RAM-derived auto-tune exists yet for Ollama",
        "caveat": (
            "B2 scoped a num_ctx-from-RAM analog for Ollama (mirroring vLLM's "
            "compute_server_args); it was not built this cycle -- a known gap, "
            "not a silent omission."
        ),
    }
    return out


def _job_reports() -> dict:
    out: dict = {}
    from src.ai_layer.triage_job import last_keyword_triage_report

    out["keyword_triage"] = _safe(last_keyword_triage_report)
    from src.ai_layer.source_tags_job import last_source_tags_report

    out["source_tags"] = _safe(last_source_tags_report)
    from src.ai_layer.perception_job import last_perception_eval_live_report

    out["perception_eval_live"] = _safe(last_perception_eval_live_report)
    from src.ai_layer.perception_extract_job import last_perception_extract_report

    out["perception_extract"] = _safe(last_perception_extract_report)

    def _langdetect():
        from src.api.ai import ai_detect_language_status

        return ai_detect_language_status()

    out["language_detection"] = _safe(_langdetect)
    return out


def ai_diagnostics_report() -> dict:
    """Assemble the whole `ai` diagnostics payload. Every section is wrapped so
    a single probe/report failure degrades that section only -- the bundle
    build never aborts over this member."""
    backend = _safe(_backend_facts)
    context = _safe(lambda: _context_settings(backend if isinstance(backend, dict) else {}))

    def _active_model():
        from src.api.llm import active_model

        return active_model()

    def _vllm_status():
        from src.llm.vllm_lifecycle import status

        return status()

    return {
        "schema": SCHEMA,
        "backend": backend,
        "active_model": _safe(_active_model),
        "context": context,
        "vllm": _safe(_vllm_status),
        "jobs": _safe(_job_reports),
    }


__all__ = ["SCHEMA", "ai_diagnostics_report"]
