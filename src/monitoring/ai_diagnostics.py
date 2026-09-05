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

#: Bumped to -2 on 2026-08-06: ``active_model`` changed from a bare string to
#: ``{provisioning_backend, model, routing_backend}``, and ``vllm_last_failure`` joined.
#: A field that changes TYPE is a schema change even when nothing in this repo reads it
#: -- exported bundles are compared across months and across machines, and a reader
#: hitting a dict where the last export held a string deserves to be told which shape
#: it is looking at rather than left to infer it.
SCHEMA = "oo-ai-diagnostics-2"


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
        from src.llm.ollama import DEFAULT_VLLM_MODEL
        from src.llm.vllm_lifecycle import (
            _DEFAULT_WEIGHT_GB,
            _KV_MB_PER_TOKEN,
            _WEIGHT_LOAD_MARGIN_GB,
            compute_server_args,
            kv_basis,
            measured_weight_gb,
        )

        # THE MODEL'S OWN FACTS, not the class defaults (2026-09-05). This called
        # `compute_server_args` with neither the checkpoint's KV cost nor its measured
        # weight footprint, so the block always described the FALLBACK derivation --
        # a start no machine performs, since `start()` reads both. The 2026-09-04 field
        # export therefore reported "this model's own shape could not be read" on a
        # machine whose shape had never been looked at, and the running server's real
        # `max_model_len` differed from the published one with nothing to explain it.
        # A bundle exists to show what would really happen.
        # The model vLLM would actually be started with -- `active_model("vllm")` is
        # the provisioning answer (what this machine will serve with once its backend
        # is up), which is the question a context budget is about; routing is a
        # different question and is not this one.
        try:
            from src.api.llm import active_model

            model = active_model("vllm") or DEFAULT_VLLM_MODEL
        except Exception:  # noqa: BLE001 - a diagnostic must degrade, never raise
            model = DEFAULT_VLLM_MODEL
        basis = kv_basis(model)
        kv_mb = basis.get("mb_per_token") if basis.get("measured") else _KV_MB_PER_TOKEN
        try:
            measured_gb = measured_weight_gb(model)
        except Exception:  # noqa: BLE001 - a diagnostic must degrade, never raise
            measured_gb = None
        footprint = (
            round(measured_gb + _WEIGHT_LOAD_MARGIN_GB, 2)
            if measured_gb is not None
            else _DEFAULT_WEIGHT_GB
        )
        # The free figure too (2026-08-05): on a machine sharing one card with Ollama,
        # a budget reported from the TOTAL describes a start that would be refused, and
        # a bundle exists to show what would really happen. Read at bundle time, so it
        # is a snapshot of that moment -- the `method` says so when it narrowed.
        out["vllm"] = compute_server_args(
            gpu.get("vram_mb"),
            vram_free_mb=gpu.get("vram_free_mb"),
            weight_footprint_gb=footprint,
            kv_mb_per_token=kv_mb or _KV_MB_PER_TOKEN,
            model_max_tokens=basis.get("max_position_embeddings"),
        )
        # The DERIVATION's own inputs, beside the numbers they produced -- so a machine
        # still on the fallback constant says WHICH file it could not read rather than
        # only that it could not, which is what cost a round trip.
        out["vllm"]["model"] = model
        out["vllm"]["kv_per_token"] = basis
        out["vllm"]["weights_gb"] = {
            "used": footprint,
            "measured": measured_gb,
            "load_margin_gb": _WEIGHT_LOAD_MARGIN_GB,
            "source": (
                "the checkpoint's own weight files plus a load margin"
                if measured_gb is not None
                else "the conservative class default (nothing measurable on disk)"
            ),
        }
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

    def _active_model(backend_facts: dict):
        """The model this machine will actually serve with -- a PROVISIONING answer.

        Field bundle 2026-08-06: an RTX 4070 laptop with vLLM installed, its server in a
        start-retry loop, and Ollama not installed at all. ``resolve_backend()`` answered
        ``"ollama"`` -- correctly, since ROUTING disqualifies an unreachable backend and
        Ollama is the ruled fallback -- so ``active_model()`` with no argument read the
        Ollama setting and this report named ``ministral-3:8b-instruct-2512-q4_K_M`` on a
        machine with no Ollama to serve it. Every AI job in the same bundle had in fact
        run against the vLLM repo id, so the diagnostics disagreed with the app.

        That is the recorded routing-vs-provisioning split, one surface further on:
        reading a selection function's answer for a question it was not written for.
        ``provisioning_backend`` exists for exactly this and its own docstring describes
        this machine. Both answers are reported, because on a dual-backend machine "which
        model" genuinely has two answers and a reader needs to see the backend beside it."""
        from src.api.llm import active_model
        from src.llm.backend import provisioning_backend

        prov = provisioning_backend(backend_facts) if backend_facts else {}
        chosen = prov.get("backend")
        return {
            "provisioning_backend": chosen,
            "model": active_model(chosen) if chosen else active_model(),
            "routing_backend": backend_facts.get("backend"),
            "note": (
                "`model` is what this machine will serve with once its backend is up "
                "(provisioning). `routing_backend` is who could serve a request right "
                "now, which is a different question and falls back to Ollama when "
                "nothing is reachable."
            ),
        }

    def _vllm_status():
        from src.llm.vllm_lifecycle import status

        # history_limit=None: the diagnostics bundle takes the COMPLETE attempt
        # journal. Being diagnosable after a restart is what V3 exists for; the
        # interactive default is trimmed for the UI panel, not for this member.
        return status(history_limit=None)

    def _vllm_last_failure():
        from src.llm.vllm_lifecycle import newest_failed_start_log

        return newest_failed_start_log()

    return {
        "schema": SCHEMA,
        "backend": backend,
        "hardware": _safe(lambda: _hardware_facts(backend if isinstance(backend, dict) else {})),
        "active_model": _safe(
            lambda: _active_model(backend if isinstance(backend, dict) else {})
        ),
        "context": context,
        "vllm": _safe(_vllm_status),
        # The complete log of the most recent FAILED start. The status payload above
        # carries only a bounded excerpt, and the live server log is truncated by the
        # next start -- so on a machine in a start-retry loop this is the one member
        # that says WHY, and it is the member every previous round had to ask for.
        "vllm_last_failure": _safe(_vllm_last_failure),
        "jobs": _safe(_job_reports),
    }


__all__ = ["SCHEMA", "ai_diagnostics_report"]
