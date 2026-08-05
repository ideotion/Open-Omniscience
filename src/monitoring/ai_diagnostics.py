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
    """Run one section, degrading to a SENTINEL rather than taking down the bundle.

    The sentinel key is ``section_ok`` and NOT ``available`` (renamed 2026-07-29).
    ``resolve_backend()`` legitimately returns ``available: False`` to mean "the
    selected backend is unreachable", which is a MEASUREMENT; the old sentinel used
    the same key to mean "this probe crashed", which is the ABSENCE of one. A reader
    of ``ai.json`` could not tell the operator's real "Ollama is down" from a hung
    ``nvidia-smi`` -- a measurement fabricated out of a failed probe, and the exact
    shape of the K2 lesson where a graceful degrade became a hiding place for the bug
    it was built to survive."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - one section's failure must not break the rest
        return {"section_ok": False, "error": str(exc)[:300]}


def _backend_facts() -> dict:
    from src.llm.backend import resolve_backend

    return resolve_backend()


def _hardware_facts(backend_facts: dict) -> dict:
    """Is local inference PRACTICAL on this machine (2026-07-30, maintainer-ruled)?

    A SEPARATE question from ``_backend_facts()``'s "which backend would serve" --
    an unsuitable machine can still resolve a backend, start it, and then crawl.

    SENTINEL DISCIPLINE: this payload's own key is ``practical``, so a crashed
    probe (which ``_safe`` marks ``section_ok: False``) can never be mistaken for
    a measured "impractical" -- the same reason ``_safe``'s sentinel was renamed
    off ``available`` in 2026-07-29. Reuses the ``gpu`` dict the backend probe
    already produced, so this member costs ZERO additional nvidia-smi probes;
    when that probe CRASHED there is no gpu dict to reuse and ``inference_capability``
    honestly runs (and reports) its own."""
    from src.llm.backend import inference_capability

    gpu = backend_facts.get("gpu") if backend_facts.get("section_ok") is not False else None
    return inference_capability(gpu=gpu if isinstance(gpu, dict) else None)


def _context_settings(backend_facts: dict, corpus: dict | None = None) -> dict:
    """Context/window sizing for whichever backend is active.

    Both are now COMPUTED, disclosed heuristics: vLLM's ``compute_server_args``
    (B2) and, since E-S4 (2026-08-01), Ollama's ``recommend_num_ctx`` -- the
    RAM/VRAM-derived analog that was B2's own carried-over gap. Ollama's PROPOSES
    only; ``configured_num_ctx`` still governs, because resizing an operator's
    context window off an estimate would be changing behaviour on a guess.

    ``corpus`` supplies the article-length half (``{"p95_words", "script"}``) and is
    INJECTED rather than measured here -- see the note at the call site."""
    from src.config.app_settings import load_settings

    out: dict = {}
    gpu = backend_facts.get("gpu") or {}
    vllm_installed = bool((backend_facts.get("vllm") or {}).get("installed"))
    if backend_facts.get("section_ok") is False:
        # The backend probe CRASHED, so `vllm_installed` is False because we learned
        # nothing -- not because vLLM is absent. Saying "vLLM is not installed" here
        # would be a claim about the machine derived from a failed probe.
        out["vllm"] = {
            "available": None,
            "reason": "the backend probe failed, so nothing was observed about vLLM here",
        }
    elif vllm_installed:
        from src.llm.vllm_lifecycle import compute_server_args

        # The free figure too (2026-08-05): on a machine sharing one card with Ollama,
        # a budget reported from the TOTAL describes a start that would be refused, and
        # a bundle exists to show what would really happen. Read at bundle time, so it
        # is a snapshot of that moment -- the `method` says so when it narrowed.
        out["vllm"] = compute_server_args(
            gpu.get("vram_mb"), vram_free_mb=gpu.get("vram_free_mb")
        )
    else:
        out["vllm"] = {"available": False, "reason": "vLLM is not installed"}

    settings = load_settings()
    configured = getattr(settings, "llm_max_context_length", None)
    # E-S4 (2026-08-01): the RAM/VRAM-derived num_ctx analog vLLM has had since B2 --
    # the documented B7 gap, now closed. It PROPOSES; the configured setting still
    # governs, because a heuristic must not silently resize an operator's window.
    from src.ai_layer.context import recommend_num_ctx

    ram_gb = None
    try:
        from src.llm.ollama import total_ram_gb

        ram_gb = total_ram_gb()
    except Exception:  # noqa: BLE001 - psutil is an optional extra; unreadable is a state
        ram_gb = None
    # The corpus half is INJECTED, never scanned here: measuring the article-length
    # distribution is a full-table pass, and a bundle member that quietly ran one
    # would make "read the AI settings" the most expensive click in diagnostics.
    # Absent, the auto-tune takes its own unmeasured branch and names the diagnostic
    # that would supply it.
    p95_words = (corpus or {}).get("p95_words")
    script = (corpus or {}).get("script") or "latin"
    out["ollama"] = {
        "configured_num_ctx": configured,
        "auto_tune": recommend_num_ctx(
            p95_words=p95_words,
            script=script,
            ram_gb=ram_gb,
            vram_mb=gpu.get("vram_mb") if isinstance(gpu, dict) else None,
            configured=configured,
        ),
        "note": (
            "The auto-tune PROPOSES; `configured_num_ctx` governs. A heuristic that "
            "silently resized the operator's context window would be changing behaviour "
            "on an estimate."
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


def ai_diagnostics_report(corpus: dict | None = None) -> dict:
    """Assemble the whole `ai` diagnostics payload. Every section is wrapped so
    a single probe/report failure degrades that section only -- the bundle
    build never aborts over this member."""
    backend = _safe(_backend_facts)
    context = _safe(
        lambda: _context_settings(backend if isinstance(backend, dict) else {}, corpus)
    )

    def _active_model():
        from src.api.llm import active_model

        return active_model()

    def _vllm_status():
        from src.llm.vllm_lifecycle import status

        # history_limit=None: the diagnostics bundle takes the COMPLETE attempt
        # journal. Being diagnosable after a restart is what V3 exists for; the
        # interactive default is trimmed for the UI panel, not for this member.
        return status(history_limit=None)

    return {
        "schema": SCHEMA,
        "backend": backend,
        "hardware": _safe(lambda: _hardware_facts(backend if isinstance(backend, dict) else {})),
        "active_model": _safe(_active_model),
        "context": context,
        "vllm": _safe(_vllm_status),
        "jobs": _safe(_job_reports),
    }


__all__ = ["SCHEMA", "ai_diagnostics_report"]
