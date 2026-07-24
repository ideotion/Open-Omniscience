"""
Local LLM API -- DUAL BACKEND (Ollama + vLLM, HTTP only).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Endpoints are synchronous (`def`) so blocking httpx calls run in the threadpool.
If the active backend is unreachable or the model isn't loaded, these return
HTTP 503 with a clear message -- never a fabricated result. LLM outputs are
persisted with provenance (model + prompt version + timestamp) as
ArticleAnalysis rows.

DUAL BACKEND (B1, 2026-07-24 field-feedback Session B, RULED A12): inference
calls (generate/summarize/translate/synthesize/bulk) resolve through
``get_llm_client()`` to whichever backend is ACTIVE -- vLLM on a GPU machine
with an installed, running server (concurrency, B3), Ollama otherwise (KEPT
for the CPU-only fleet, never dropped). Ollama-ONLY management operations
(pull/remove/the installed-models catalog/the binary installer) always use
``get_ollama_client()`` regardless of which backend is active for inference.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.fts import SearchQueryError, search_ids
from src.database.models import Article, ArticleAnalysis
from src.database.session import get_db
from src.llm.backend import LlmBackend
from src.llm.ollama import (
    CATALOG_AS_OF,
    DEFAULT_MODEL,
    LLMError,
    LLMUnavailable,
    OllamaClient,
)

router = APIRouter(prefix="/api/llm", tags=["llm"])

# Prompt versions are part of provenance: bump when a default prompt changes.
# v2 (2026-06-17): tighter, honesty-first prompts — language pin, attribution guard,
# per-claim citations + single-source flag for synthesis (see _build_prompting).
SUMMARY_PROMPT_VERSION = "summary-v2"
_SUMMARY_SYSTEM = (
    "You are a careful research assistant for an investigative journalist. Summarize the "
    "article below in 3-5 sentences, using only its text. Keep the essentials: who, what, "
    "when, where, and any figures, dates, or attributed/quoted claims. Preserve attribution "
    '("X said", "allegedly") -- never turn a claim into a fact. Stay neutral: add no '
    "background, do not interpret, judge credibility, or conclude. If it is not a coherent "
    "article (paywall, navigation, error page), say exactly that. Write in {language}. "
    "Output only the summary, with no preamble."
)

TRANSLATE_PROMPT_VERSION = "translate-v2"
_TRANSLATE_SYSTEM = (
    "You are a faithful translator for an investigative journalist. Translate the title and "
    "body below into {target}, as literally as the target language allows. Preserve meaning, "
    "names, numbers, dates, quotations and paragraph breaks exactly. Do NOT summarize, "
    "interpret, soften, censor, or add; keep proper nouns in their original form. If a passage "
    "is already in {target}, leave it unchanged. Output only the translation, with no preamble "
    "or notes."
)
# Keep prompts within a small CPU model's context.
_MAX_CHARS = 6000

_ollama_client: OllamaClient | None = None


def get_ollama_client() -> OllamaClient:
    """Dependency returning a shared OllamaClient SPECIFICALLY — for Ollama-only
    management operations (pull/remove/the installed-models catalog) that have
    no vLLM analog, regardless of which backend is currently ACTIVE for
    inference (``get_llm_client``, which may resolve to vLLM on a GPU machine).
    A pull/remove is always an Ollama-process action; routing it through the
    active-backend dependency would try to ``.pull()`` a ``VllmClient``, which
    has no such method — this dependency exists precisely to avoid that."""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client


def _stored_backend_override() -> str | None:
    try:
        from src.config.app_settings import load_settings

        s = load_settings()
        return s.llm_backend if s.llm_backend != "auto" else None
    except Exception:  # noqa: BLE001 - a settings hiccup must not break inference
        return None


def get_llm_client():
    """Dependency returning the shared client for the ACTIVE backend (overridable
    in tests via ``app.dependency_overrides``).

    DUAL BACKEND (B1, 2026-07-24 field-feedback Session B, RULED A12): resolves
    through ``src.llm.backend.get_client()`` — vLLM when a GPU + an installed,
    running vLLM server are present, Ollama otherwise (never dropped, never a
    silent replacement). ``VllmClient``/``OllamaClient`` are structurally
    interchangeable (``LlmBackend``), so every call site below (summarize/
    translate/synthesize/bulk) works against either backend unchanged."""
    from src.llm.backend import get_client

    return get_client(backend=_stored_backend_override())


def get_llm_client_with_name() -> tuple[str, "LlmBackend"]:
    """Like ``get_llm_client`` but also returns the resolved backend NAME (B3):
    a batch consumer (bulk summarize/translate) uses it to pick the right
    concurrency ceiling — ``concurrency_for("vllm")`` vs. ``concurrency_for
    ("ollama")`` — without re-running GPU/vLLM/Ollama detection a second time."""
    from src.llm.backend import get_client_with_name

    return get_client_with_name(backend=_stored_backend_override())


def active_model() -> str:
    """The operator's chosen default model for the ACTIVE backend — the STORED
    UI setting (Ollama: maintainer Q10; vLLM: B1.4) if set, else a backend-aware
    fallback. A per-request ``model`` still overrides it. Never fatal: any
    settings/resolution hiccup falls back to the Ollama DEFAULT_MODEL."""
    try:
        from src.llm.backend import resolve_backend
        from src.config.app_settings import load_settings

        s = load_settings()
        override = s.llm_backend if s.llm_backend != "auto" else None
        backend = resolve_backend(override=override)["backend"]
        if backend == "vllm":
            if s.llm_model_vllm:
                return s.llm_model_vllm
            # vLLM serves exactly ONE model at a time (unlike Ollama's catalog) —
            # ask the running server what it was started with, rather than
            # guessing a name it may not recognise.
            try:
                from src.llm.vllm_client import VllmClient

                served = VllmClient(timeout=3.0).list_installed()
                if served:
                    return served[0]
            except Exception:  # noqa: BLE001 - a probe hiccup falls through honestly
                pass
            return DEFAULT_MODEL
        return s.llm_model or DEFAULT_MODEL
    except Exception:  # noqa: BLE001 - a settings hiccup must not break inference
        return DEFAULT_MODEL


def _llm_settings():
    """The stored app settings, or None if unreadable (never fatal)."""
    try:
        from src.config.app_settings import load_settings

        return load_settings()
    except Exception:  # noqa: BLE001 - settings must never break inference
        return None


def _effective_keep_alive() -> str | None:
    """How long Ollama keeps the model loaded after a call (stored UI setting)."""
    s = _llm_settings()
    return s.llm_keep_alive if s else None


def _apply_target(template: str, target: str) -> str:
    """Insert the target language into a translate prompt. The built-in default uses a
    ``{target}`` placeholder; a custom prompt without one gets an explicit instruction
    appended (so the target is always conveyed, whatever the operator wrote)."""
    if "{target}" in template:
        return template.replace("{target}", target)
    return f"{template}\n\nTranslate into {target}."


# A short, IN-LANGUAGE directive appended to the summary/synthesis system prompt so a
# small model RELIABLY writes its answer in the UI language (maintainer 2026-06-21: a
# weak model often echoed the SOURCE language despite the English "{language}" pin).
# Keyed by UI language code; the instruction is written natively in that language so the
# operative command is in the same language we want the output in. (We keep the tuned
# English prompt BODY — translating multi-sentence instructions across 12 languages risks
# DEGRADING a weak model's compliance; forcing the OUTPUT language is the reliable win.)
_NATIVE_DIRECTIVE = {
    "en": "Write your entire response in English.",
    "fr": "Rédige l'intégralité de ta réponse en français.",
    "de": "Schreibe deine gesamte Antwort auf Deutsch.",
    "es": "Escribe toda tu respuesta en español.",
    "pt": "Escreve toda a tua resposta em português.",
    "it": "Scrivi tutta la tua risposta in italiano.",
    "nl": "Schrijf je volledige antwoord in het Nederlands.",
    "ru": "Напиши весь ответ на русском языке.",
    "ar": "اكتب إجابتك كاملةً باللغة العربية.",
    "zh": "请用中文写出全部回答。",
    "ja": "回答はすべて日本語で書いてください。",
    "hi": "अपना पूरा उत्तर हिन्दी में लिखें।",
    "bn": "আপনার সম্পূর্ণ উত্তর বাংলায় লিখুন।",
    "id": "Tulis seluruh jawabanmu dalam bahasa Indonesia.",
}


def _build_prompting(
    op: str,
    *,
    target: str | None = None,
    output_language: str | None = None,
    output_lang_code: str | None = None,
) -> tuple[str, str, str]:
    """Resolve ``(system_prompt, prompt_version, prompt_text)`` for an op.

    Prompts are operator-editable (Settings → Models). A non-empty stored override is
    used verbatim, else the built-in default; the version flags default-vs-custom, and
    ``prompt_text`` is the EXACT system text used (recorded per result so provenance
    stays honest even after the operator edits a prompt). Evaluated at call time, so
    the synthesis constants defined later in this module are available.

    ``output_language`` (the v2 language pin, maintainer 2026-06-17) fills the
    ``{language}`` placeholder of the summary/synthesis prompts. When unset, summary
    defaults to "the same language as the article" (faithful) and synthesis to
    "English" (a neutral default for multilingual inputs). ``target`` is the translate
    output language. A custom prompt may include ``{language}`` too — we substitute it
    either way, so operator prompts can pin the language as well.

    ``output_lang_code`` (maintainer 2026-06-21) is the UI language CODE; when given for
    summary/synthesis we append a native-language directive (``_NATIVE_DIRECTIVE``) so a
    weak model actually answers in the UI language instead of echoing the source.
    """
    s = _llm_settings()
    overrides = {
        "summary": (s.llm_prompt_summary if s else ""),
        "translate": (s.llm_prompt_translate if s else ""),
        "synthesis": (s.llm_prompt_synthesis if s else ""),
    }
    defaults = {
        "summary": _SUMMARY_SYSTEM,
        "translate": _TRANSLATE_SYSTEM,
        "synthesis": _SYNTHESIS_SYSTEM,
    }
    override = (overrides.get(op) or "").strip()
    is_custom = bool(override)
    template = override or defaults[op]
    if op == "translate":
        tgt = (target or "English")
        system = _apply_target(template, tgt)
        base = "translate-custom" if is_custom else TRANSLATE_PROMPT_VERSION
        version = f"{base}:{tgt}"
    elif op == "synthesis":
        lang = (output_language or "").strip() or "English"
        system = template.replace("{language}", lang)
        version = "synthesis-custom" if is_custom else SYNTHESIS_PROMPT_VERSION
    else:  # summary
        lang = (output_language or "").strip() or "the same language as the article"
        system = template.replace("{language}", lang)
        version = "summary-custom" if is_custom else SUMMARY_PROMPT_VERSION
    if op in ("summary", "synthesis"):
        directive = _NATIVE_DIRECTIVE.get((output_lang_code or "").strip().lower())
        if directive:
            system = f"{system}\n\n{directive}"
    return system, version, system


class GenerateRequest(BaseModel):
    prompt: str
    model: str | None = None
    system: str | None = None


class SummarizeRequest(BaseModel):
    model: str | None = None
    # The language to WRITE the summary in (v2 language pin). The SPA passes the
    # current UI language; unset = "the same language as the article" (faithful).
    output_language: str | None = None
    # UI language CODE -> the native-language output directive (remark 13, 2026-06-24):
    # single-article summaries must come out in the UI language like bulk/synthesis do.
    ui_lang: str | None = None


class TranslateRequest(BaseModel):
    target_language: str = "English"
    model: str | None = None


@router.get("/health")
def llm_health(client=Depends(get_llm_client)) -> dict:
    """Report whether the ACTIVE backend (Ollama or vLLM, B1) is reachable and
    which model(s) it has. Drives the top-bar "AI" pill (B4) -- green/red by
    ``available``, no model count."""
    from src.llm.backend import resolve_backend

    try:
        backend = resolve_backend()["backend"]
    except Exception:  # noqa: BLE001 - a resolution hiccup must not break the health check
        backend = "ollama"
    try:
        installed = client.list_installed()
        return {
            "available": True,
            "backend": backend,
            "base_url": client.base_url,
            "installed_models": installed,
        }
    except LLMUnavailable as exc:
        return {
            "available": False,
            "backend": backend,
            "base_url": client.base_url,
            "installed_models": [],
            "detail": str(exc),
        }


@router.get("/backend")
def llm_backend_status() -> dict:
    """The full backend-resolution DECISION + the facts behind it (B1.3) --
    which backend is active, why, and the detection facts (GPU / vLLM installed
    + running / Ollama available). Drives the Settings -> AI tab's disclosure
    (the maintainer must never see a silent switch)."""
    from src.llm.backend import resolve_backend
    from src.config.app_settings import load_settings

    try:
        s = load_settings()
        override = s.llm_backend if s.llm_backend != "auto" else None
        stored_override = s.llm_backend
    except Exception:  # noqa: BLE001 - a settings hiccup must not break the status view
        override, stored_override = None, "auto"
    resolved = resolve_backend(override=override)
    resolved["stored_override"] = stored_override
    return resolved


@router.get("/models")
def llm_models(client: OllamaClient = Depends(get_ollama_client)) -> dict:
    """What the operator actually has installed in OLLAMA (live, local) + a
    suggested catalog -- the Ollama model-management panel (pull/remove),
    regardless of which backend is currently ACTIVE for inference (see
    ``/api/llm/backend`` for that).

    The picker should lead with `installed` (truth from Ollama). `catalog` is a
    hardware-annotated suggestion list with an honest `catalog_as_of` date --
    it goes stale fast; newer models may exist at https://ollama.com/library.
    """
    from src.llm.ollama import annotate_catalog, total_ram_gb

    try:
        installed = client.list_installed_detailed()
        available = True
    except LLMUnavailable:
        installed, available = [], False
    return {
        "available": available,
        "default": DEFAULT_MODEL,
        "active": active_model(),  # the stored UI choice (Q10), or the default
        "total_ram_gb": total_ram_gb(),
        "catalog_as_of": CATALOG_AS_OF,
        "catalog": annotate_catalog(),
        "installed": installed,
    }


@router.get("/prompts")
def llm_prompts() -> dict:
    """The local-LLM behaviour the operator can tune (maintainer 2026-06-17): the
    keep-alive duration and the editable SYSTEM PROMPTS, each with its built-in
    default and the current override ("" = using the default). Read by Settings → Models.

    Four system prompts — ``summary`` (used for one OR many articles), ``translate`` (one
    OR many; ``{target}`` is the target language), ``synthesis`` (one combined output
    across several), and ``ai_keywords`` (the built-in keyword/entity EXTRACTION prompt,
    Part B; ``{max_terms}`` is the per-article cap). Bulk reuses the single-article
    summary/translate prompt per article — there is no separate "several" prompt.
    """
    from src.ai_layer.extract import _EXTRACT_SYSTEM, EXTRACT_PROMPT_VERSION
    from src.config.app_settings import AppSettings

    s = _llm_settings()
    return {
        "keep_alive": (s.llm_keep_alive if s else AppSettings().llm_keep_alive),
        "keep_alive_default": AppSettings().llm_keep_alive,
        "prompts": {
            "summary": {
                "default": _SUMMARY_SYSTEM,
                "current": (s.llm_prompt_summary if s else "") or "",
                "version": SUMMARY_PROMPT_VERSION,
            },
            "translate": {
                "default": _TRANSLATE_SYSTEM,
                "current": (s.llm_prompt_translate if s else "") or "",
                "version": TRANSLATE_PROMPT_VERSION,
            },
            "synthesis": {
                "default": _SYNTHESIS_SYSTEM,
                "current": (s.llm_prompt_synthesis if s else "") or "",
                "version": SYNTHESIS_PROMPT_VERSION,
            },
            "ai_keywords": {
                "default": _EXTRACT_SYSTEM,
                "current": (s.llm_prompt_ai_keywords if s else "") or "",
                "version": EXTRACT_PROMPT_VERSION,
            },
        },
        "note": (
            "Empty = use the built-in default. The exact prompt used is recorded with "
            "each result (provenance). The translate prompt may contain {target} for the "
            "target language; the keyword-extraction prompt may contain {max_terms}. "
            "Save changes via Settings (PUT /api/settings)."
        ),
    }


@router.post("/generate")
def llm_generate(req: GenerateRequest, client: LlmBackend = Depends(get_llm_client)) -> dict:
    """Single-shot generation. 503 if Ollama/model unavailable."""
    model = req.model or active_model()
    try:
        result = client.generate(req.prompt, model=model, system=req.system)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"model": result.model, "text": result.text}


# Ollama model tags: registry/name:tag with the usual punctuation. Validated so a
# user-supplied name can never inject into the Ollama request path.
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ModelRequest(BaseModel):
    model: str


@router.post("/pull")
def llm_pull(req: ModelRequest, client: OllamaClient = Depends(get_ollama_client)):
    """Pull (download + install) a model via the LOCAL Ollama process — STREAMS
    Ollama's real progress as NDJSON (invariant #20: never a fabricated bar).

    TRANSPORT HONESTY (maintainer Q9): the bytes egress via the Ollama process over
    CLEARNET, not the app's Tor proxy — the UI discloses this at consent. Airplane
    mode (kill switch) refuses the pull at the client. Gated by the ONE consent (#14)."""
    import json as _json

    if not _MODEL_RE.match(req.model or ""):
        raise HTTPException(status_code=400, detail="invalid model name")

    def _stream():
        try:
            for prog in client.pull(req.model):
                yield _json.dumps(prog, separators=(",", ":")) + "\n"
        except (LLMUnavailable, LLMError) as exc:
            yield _json.dumps({"error": str(exc)[:300]}, separators=(",", ":")) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


# Model-download QUEUE (§2.C1): pulls run one at a time, the rest queue, each
# cancellable. The streaming /pull above stays for the single-pull path; the queue
# is the multi-pull path surfaced in the task manager.
@router.post("/pull/queue")
def llm_pull_queue(req: ModelRequest) -> dict:
    """Add a model to the pull queue (one active pull at a time). The frontend gates
    this through the ONE network consent first (clearnet egress via Ollama, Q9)."""
    from src.llm.pull_queue import get_pull_manager

    try:
        return get_pull_manager().enqueue(req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pull/status")
def llm_pull_status() -> dict:
    """The active pull + queued models + recent history (for the AI tab + /api/jobs)."""
    from src.llm.pull_queue import get_pull_manager

    return get_pull_manager().status()


@router.post("/pull/cancel")
def llm_pull_cancel(req: ModelRequest) -> dict:
    """Cancel a queued model (removed) or the active pull (aborted — not resumable)."""
    from src.llm.pull_queue import get_pull_manager

    return get_pull_manager().cancel(req.model)


# --------------------------------------------------------------------------- #
#  Ollama BINARY installer (maintainer Q7=B, 2026-06-16): download + verify +
#  run the OFFICIAL installer, with consent + a VISIBLE elevation step. The
#  checksum is GitHub's OWN attestation (never fabricated); see src/llm/installer.
# --------------------------------------------------------------------------- #


@router.get("/install/status")
def llm_install_status() -> dict:
    """Is Ollama already installed, can the app install it here, and is elevation
    available without a password? Drives the AI tab's install panel."""
    from src.llm.installer import install_status

    return install_status()


@router.post("/install/prepare")
def llm_install_prepare() -> dict:
    """Download the OFFICIAL Ollama installer and VERIFY it against GitHub's
    attested SHA-256 before anything runs (never an unverified script). A network
    action over CLEARNET via the guarded factory — refused under airplane mode,
    gated by the ONE consent (#14). Returns the verified version + sha + the exact
    command to run it (and the app can run it when elevation is non-interactive)."""
    from src.llm.installer import (
        InstallerUnavailable,
        InstallerVerificationError,
        prepare_installer,
    )

    try:
        prepared = prepare_installer()
    except InstallerUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InstallerVerificationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return prepared.to_dict()


class InstallRunRequest(BaseModel):
    path: str


@router.post("/install/run")
def llm_install_run(req: InstallRunRequest):
    """Run a previously prepared+verified installer, streaming its output as
    NDJSON (honest real progress, never a fabricated bar — invariant #20). Runs
    ONLY when elevation is available without a password (root / passwordless
    sudo); otherwise it streams an error telling the user the manual command —
    so the TTY-less backend can never hang on a password prompt. The script's own
    download of the binary egresses over CLEARNET (disclosed, Q9)."""
    import json as _json

    from src.llm.installer import InstallerError, run_installer

    def _stream():
        try:
            for line in run_installer(req.path):
                if line.startswith("__exit__ "):
                    code = line.split(" ", 1)[1].strip()
                    yield _json.dumps(
                        {"event": "done", "exit_code": int(code or "1")},
                        separators=(",", ":"),
                    ) + "\n"
                else:
                    yield _json.dumps({"event": "line", "text": line[:500]}, separators=(",", ":")) + "\n"
        except InstallerError as exc:
            yield _json.dumps({"event": "error", "error": str(exc)[:500]}, separators=(",", ":")) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.post("/remove")
def llm_remove(req: ModelRequest, client: OllamaClient = Depends(get_ollama_client)) -> dict:
    """Remove an installed model via the LOCAL Ollama process."""
    if not _MODEL_RE.match(req.model or ""):
        raise HTTPException(status_code=400, detail="invalid model name")
    try:
        client.remove(req.model)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)[:200]) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:200]) from exc
    return {"removed": req.model, "ok": True}


# --------------------------------------------------------------------------- #
#  vLLM lifecycle (B2, 2026-07-24 field-feedback Session B): detect / install /
#  start / stop, mirroring the Ollama binary-installer section above. vLLM is
#  GPU-first (RULED, out of scope for CPU mode) -- every mutating endpoint here
#  refuses honestly on a machine with no detected GPU, pointing at Ollama.
# --------------------------------------------------------------------------- #


@router.get("/vllm/status")
def vllm_status() -> dict:
    """Detect/installed/running facts for the Settings -> AI tab's vLLM panel
    (B2). Never a fabricated readiness -- a live health probe, not just the
    tracked-process flag."""
    from src.llm.vllm_lifecycle import status

    return status()


class VllmInstallRequest(BaseModel):
    version: str | None = None


_VLLM_INSTALL_JOB = None


def _get_vllm_install_job():
    """Lazily register the BackgroundJob (mirrors the keyword-triage/source-tags
    job registration pattern) -- avoids importing src.jobs.background at module
    load for a job that most installs never touch."""
    global _VLLM_INSTALL_JOB
    if _VLLM_INSTALL_JOB is None:
        from src.jobs.background import BackgroundJob, register_job

        def _worker(ctx, **kwargs):
            from src.llm.vllm_lifecycle import run_install_job

            return run_install_job(ctx, **kwargs)

        _VLLM_INSTALL_JOB = register_job(
            BackgroundJob("vllm-install", "Installing vLLM", _worker, cancellable=True)
        )
    return _VLLM_INSTALL_JOB


@router.post("/vllm/install")
def vllm_install(req: VllmInstallRequest | None = None) -> dict:
    """Start the CONSENTED, task-manager-visible vLLM install (B2.3): a dedicated
    venv + ``pip install vllm==<verified version>`` (drags torch/CUDA, several
    GB -- disclosed via ``/api/llm/vllm/status``'s ``estimated_size_note``
    before the frontend even offers this button). Refuses (409) on a CPU-only
    machine or under airplane mode; 409-free for an already-running install
    (returns its current status).

    The CPU/airplane checks run HERE, synchronously, before the background job
    even starts -- ``run_install_job`` re-checks both itself (defense in depth
    for any direct caller), but a check made only inside the worker THREAD
    would surface as an async job failure, not this endpoint's 409 (the
    BackgroundJob chassis returns immediately once ``.start()`` spawns the
    thread; an exception raised inside the worker never propagates back here).
    An already-in-flight install is reported 409-free regardless of the current
    GPU/airplane state (those conditions gate STARTING a new install, not an
    already-running one)."""
    from src.ingest import kill_switch_active
    from src.llm.backend import detect_gpu
    from src.llm.vllm_lifecycle import VLLM_VERIFIED_VERSION

    body = req or VllmInstallRequest()
    job = _get_vllm_install_job()
    if job.status().get("running"):
        st = job.status()
        st["started"] = False
        return st
    if kill_switch_active():
        raise HTTPException(
            status_code=409,
            detail="Network is OFF (airplane mode): refusing to install vLLM. "
            "Turn airplane mode off to install.",
        )
    if not detect_gpu().get("available"):
        raise HTTPException(
            status_code=409,
            detail="No GPU detected on this machine -- vLLM is GPU-first and would "
            "install into a backend that can never usefully run. Use Ollama instead.",
        )
    try:
        st = job.start(version=body.version or VLLM_VERIFIED_VERSION)
        st["started"] = True
    except RuntimeError:
        st = job.status()
        st["started"] = False
    return st


@router.get("/vllm/install/status")
def vllm_install_status() -> dict:
    return _get_vllm_install_job().status()


@router.post("/vllm/install/cancel")
def vllm_install_cancel() -> dict:
    _get_vllm_install_job().cancel()
    return _get_vllm_install_job().status()


class VllmStartRequest(BaseModel):
    model: str
    max_model_len: int | None = None
    gpu_memory_utilization: float | None = None


@router.post("/vllm/start")
def vllm_start(req: VllmStartRequest) -> dict:
    """Start the vLLM server bound to loopback (B2.2). Honest "starting…" state
    (model load takes tens of seconds -- never a fake instant green); poll
    ``/vllm/status`` for readiness. Refuses (409) when no GPU is detected or
    vLLM is not installed (RULED -- vLLM's CPU mode is never presented as
    viable; Ollama is the CPU path)."""
    if not _MODEL_RE.match(req.model or ""):
        raise HTTPException(status_code=400, detail="invalid model name")
    from src.llm.vllm_lifecycle import VllmLifecycleError, VllmUnsupportedError, start

    try:
        result = start(
            req.model,
            max_model_len=req.max_model_len,
            gpu_memory_utilization=req.gpu_memory_utilization,
        )
    except VllmUnsupportedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except VllmLifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # A model just started under vLLM becomes the stored active choice for it,
    # so active_model()/the pill/the next generate() call agree with what is
    # actually being served (never a stale/mismatched setting).
    if result.get("started"):
        try:
            from src.config.app_settings import save_settings

            save_settings({"llm_model_vllm": req.model})
        except Exception:  # noqa: BLE001 - a settings-persist hiccup must not fail the start
            pass
    return result


@router.post("/vllm/stop")
def vllm_stop() -> dict:
    from src.llm.vllm_lifecycle import stop

    return stop()


@router.post("/articles/{article_id}/summarize")
def summarize_article(
    article_id: int,
    req: SummarizeRequest,
    db: Session = Depends(get_db),
    client: LlmBackend = Depends(get_llm_client),
) -> dict:
    """Summarize a stored article with a local model and persist it with provenance."""
    article = db.query(Article).filter_by(id=article_id).first()
    if article is None:
        raise HTTPException(status_code=404, detail=f"Article {article_id} not found.")
    if not article.content:
        raise HTTPException(status_code=400, detail="Article has no content to summarize.")

    model = req.model or active_model()
    system, prompt_version, prompt_text = _build_prompting(
        "summary", output_language=req.output_language, output_lang_code=req.ui_lang
    )
    prompt = f"Article title: {article.title or '(untitled)'}\n\n{article.content[:_MAX_CHARS]}"
    # Visible in the task manager while the model runs ("is an LLM working?").
    from src.monitoring.tasks import track

    _t = (article.title or "article")[:48]
    try:
        with track("llm", f"Summarizing “{_t}”", detail=f"model {model}"):
            result = client.generate(
                prompt, model=model, system=system, keep_alive=_effective_keep_alive()
            )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    analysis = ArticleAnalysis(
        article_id=article.id,
        kind="summary",
        result=result.text,
        model=result.model,
        prompt_version=prompt_version,
        prompt_text=prompt_text,
        created_at=datetime.now(UTC),
    )
    db.add(analysis)
    db.commit()
    return {
        "analysis_id": analysis.id,
        "article_id": article.id,
        "kind": "summary",
        "model": result.model,
        "prompt_version": prompt_version,
        "result": result.text,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


@router.post("/articles/{article_id}/translate")
def translate_article(
    article_id: int,
    req: TranslateRequest,
    db: Session = Depends(get_db),
    client: LlmBackend = Depends(get_llm_client),
) -> dict:
    """Translate a stored article into a target language with a local model.

    A faithful translation (not a summary) is persisted with provenance so foreign
    sources become part of the searchable corpus -- widening world awareness without
    any text leaving the machine.
    """
    article = db.query(Article).filter_by(id=article_id).first()
    if article is None:
        raise HTTPException(status_code=404, detail=f"Article {article_id} not found.")
    if not article.content:
        raise HTTPException(status_code=400, detail="Article has no content to translate.")

    model = req.model or active_model()
    system, prompt_version, prompt_text = _build_prompting("translate", target=req.target_language)
    prompt = f"Title: {article.title or '(untitled)'}\n\n{article.content[:_MAX_CHARS]}"
    from src.monitoring.tasks import track

    _t = (article.title or "article")[:48]
    try:
        with track("llm", f"Translating → {req.target_language}: “{_t}”", detail=f"model {model}"):
            result = client.generate(
                prompt, model=model, system=system, keep_alive=_effective_keep_alive()
            )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    analysis = ArticleAnalysis(
        article_id=article.id,
        kind="translation",
        result=result.text,
        model=result.model,
        prompt_version=prompt_version,
        prompt_text=prompt_text,
        created_at=datetime.now(UTC),
    )
    db.add(analysis)
    db.commit()
    return {
        "analysis_id": analysis.id,
        "article_id": article.id,
        "kind": "translation",
        "source_language": article.language,
        "target_language": req.target_language,
        "model": result.model,
        "prompt_version": analysis.prompt_version,
        "result": result.text,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


def _parse_target_language(prompt_version: str | None) -> str | None:
    """The translation target language is stored INSIDE the prompt version as
    ``translate-v2:French`` (or ``translate-custom:French``, and ``translate-v1:…`` on
    older rows) — provenance with no extra column. Recover it for display, covering the
    default, custom, and legacy prompt cases (any ``translate-*:lang``)."""
    if prompt_version and prompt_version.startswith("translate-") and ":" in prompt_version:
        return prompt_version.split(":", 1)[1] or None
    return None


@router.get("/articles/{article_id}/analyses")
def list_article_analyses(
    article_id: int,
    kind: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """List the stored LLM analyses (summaries / translations / …) for an article.

    Newest first. EVERY past result is kept — a new summary/translation never
    replaces an old one (maintainer-ruled), so the reader shows the latest and folds
    the rest. Each row carries its full provenance (model, prompt version, date) so
    no generated text is ever shown without its origin.

    Read-only by construction: these rows live in ``article_analyses``, NOT in
    ``articles``, and the keyword indexer only ever reads ``articles.content`` — so a
    summary or translation is NEVER keyword-indexed or fed into the analytics (the
    maintainer-agreed contract). This endpoint only reads them back.
    """
    article = db.query(Article).filter_by(id=article_id).first()
    if article is None:
        raise HTTPException(status_code=404, detail=f"Article {article_id} not found.")
    qy = db.query(ArticleAnalysis).filter(ArticleAnalysis.article_id == article_id)
    if kind:
        qy = qy.filter(ArticleAnalysis.kind == kind)
    rows = qy.order_by(ArticleAnalysis.created_at.desc(), ArticleAnalysis.id.desc()).all()
    return {
        "article_id": article_id,
        "source_language": article.language,
        "count": len(rows),
        "analyses": [
            {
                "id": r.id,
                "kind": r.kind,
                "result": r.result,
                "model": r.model,
                "prompt_version": r.prompt_version,
                "prompt_text": r.prompt_text,
                "target_language": _parse_target_language(r.prompt_version),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# --------------------------------------------------------------------------- #
#  Corpus-wide synthesis (0.0.8 part 2, WP4 / RM-12)
# --------------------------------------------------------------------------- #

SYNTHESIS_PROMPT_VERSION = "synthesis-v2"
_SYNTHESIS_SYSTEM = (
    "You are a careful research assistant for an investigative journalist. Below are numbered "
    "excerpts from several stored articles; they may be in different languages. In {language}, "
    "write a neutral synthesis in three labeled parts: (1) what the sources agree on, (2) where "
    "they disagree, (3) open questions they leave unanswered. After every statement, cite the "
    "source number(s) in brackets, e.g. [2][5]. Flag any claim that appears in only one source. "
    "Use only the excerpts: add no outside information, do not decide who is right, do not "
    "assess credibility, and do not speculate. Output only the synthesis."
)
_SYNTHESIS_MAX_ARTICLES = 20
# Total prompt budget across all excerpts (keeps a small CPU model's context safe).
_SYNTHESIS_BUDGET_CHARS = 24_000
# Chunk size for id IN(...) queries in bulk_llm (audit finding 2026-07-17): the
# 2026-06-20 ruling deliberately removed bulk_llm's old article-count cap so it can
# process the WHOLE matched set uncapped -- which also removed the incidental
# protection that cap gave against SQLite's historical ~999 bound-variable
# ceiling. A card/search selection can legitimately carry thousands of ids (a
# Home card's article_ids can run to 2000; a broad search's matched set can run
# to tens of thousands), so both id IN(...) queries below must chunk. Matches the
# repo-wide _IN_CHUNK/GRAPH_ARTICLE_CAP/_FTS_ID_CHUNK convention.
_BULK_ID_CHUNK = 900


class SynthesizeRequest(BaseModel):
    article_ids: list[int] | None = None
    query: str | None = None
    model: str | None = None
    output_language: str | None = None  # v2 language pin (default English for synthesis)
    ui_lang: str | None = None  # UI language CODE -> native output directive (2026-06-21)


@router.post("/synthesize")
def synthesize_articles(
    req: SynthesizeRequest,
    db: Session = Depends(get_db),
    client: LlmBackend = Depends(get_llm_client),
) -> dict:
    """Synthesize a bounded SET of stored articles with a local model.

    Bounded fan-out by construction: at most {max} articles, one generation call,
    a per-article excerpt budget. The response carries the member ids so the
    output is always traceable to its inputs; the synthesis is stored per member
    article (kind="synthesis") with model + prompt-version provenance. The
    output is assistance, never a verdict -- it cites article numbers, and the
    caveat travels in the response.
    """
    if req.article_ids and len(req.article_ids) > _SYNTHESIS_MAX_ARTICLES:
        raise HTTPException(
            status_code=400,
            detail=f"At most {_SYNTHESIS_MAX_ARTICLES} articles per synthesis "
            f"(got {len(req.article_ids)}). Narrow the selection.",
        )

    truncated = False
    total_matched = 0
    if req.article_ids:
        articles = db.query(Article).filter(Article.id.in_(req.article_ids)).all()
        total_matched = len(req.article_ids)
    elif req.query:
        try:
            ids = search_ids(db, req.query) or []
        except SearchQueryError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid query: {exc}") from exc
        # How the members are chosen (maintainer asked): the query path takes the
        # search-relevance order from FTS, then the TOP N (the model bound). The
        # frontend lets the user pick the exact members (sent as article_ids) so this
        # silent truncation is no longer the only path.
        total_matched = len(ids)
        if len(ids) > _SYNTHESIS_MAX_ARTICLES:
            ids, truncated = ids[:_SYNTHESIS_MAX_ARTICLES], True
        articles = db.query(Article).filter(Article.id.in_(ids)).all()
    else:
        raise HTTPException(status_code=400, detail="Provide article_ids or query.")

    articles = [a for a in articles if a.content]
    if not articles:
        raise HTTPException(status_code=404, detail="No matching articles with content.")

    ordered = sorted(articles, key=lambda x: x.id)
    per_article = max(400, _SYNTHESIS_BUDGET_CHARS // len(ordered))
    parts = []
    members = []
    for i, a in enumerate(ordered, 1):
        src = a.source.name if a.source else "unknown source"
        pub = a.published_at.date().isoformat() if a.published_at else "undated"
        parts.append(
            f"[{i}] {a.title or '(untitled)'} ({src}, {pub})\n{a.content[:per_article]}"
        )
        members.append(
            {
                "n": i,
                "id": a.id,
                "title": a.title or "",
                "source": src,
                "published_at": a.published_at.isoformat() if a.published_at else "",
                "url": a.url or "",
                "language": a.language or "",
            }
        )
    excerpts = "\n\n---\n\n".join(parts)
    # Wrap the excerpts with an explicit directive at BOTH ends. A weak instruct model
    # otherwise misread the numbered list and asked "which one should I summarize?"
    # (maintainer 2026-06-21). The instruction is repeated AFTER the excerpts because a
    # small model weights the last instruction most.
    prompt = (
        f"Synthesize ALL {len(ordered)} excerpts below into ONE combined synthesis with "
        "the three labeled parts described in your instructions. Do not ask which one to "
        "use and do not summarize a single excerpt — cover every excerpt together.\n\n"
        f"{excerpts}\n\n"
        f"Now write the combined three-part synthesis of all {len(ordered)} excerpts above, "
        "citing the bracketed source numbers."
    )
    model = req.model or active_model()
    system, prompt_version, prompt_text = _build_prompting(
        "synthesis", output_language=req.output_language, output_lang_code=req.ui_lang
    )

    try:
        result = client.generate(
            prompt, model=model, system=system, keep_alive=_effective_keep_alive()
        )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    member_ids = [a.id for a in ordered]
    for a in ordered:
        db.add(
            ArticleAnalysis(
                article_id=a.id,
                kind="synthesis",
                result=result.text,
                model=result.model,
                prompt_version=prompt_version,
                prompt_text=prompt_text,
                created_at=datetime.now(UTC),
            )
        )
    db.commit()

    return {
        "kind": "synthesis",
        "model": result.model,
        "prompt_version": prompt_version,
        "member_ids": member_ids,
        "member_count": len(member_ids),
        "members": members,
        "total_matched": total_matched,
        "truncated": truncated,
        "max_articles": _SYNTHESIS_MAX_ARTICLES,
        "result": result.text,
        "caveat": (
            "A synthesis is reading assistance over the listed member articles only -- "
            "it asserts nothing beyond them and may miss nuance; verify against the "
            "stored copies before publication."
        ),
    }


# --------------------------------------------------------------------------- #
#  Bulk summarize / translate over a matched article set (streaming progress)
# --------------------------------------------------------------------------- #
#
# Unlike /synthesize (ONE combined output), bulk runs the local model over EACH
# article independently and stores a per-article result. A local CPU model over many
# articles is slow by nature, so we:
#   * process the WHOLE matched set — UNCAPPED (maintainer 2026-06-20). The run is a
#     visible, abortable task-manager job, so the user controls the (long) fan-out.
#   * SKIP work that need not run: a translate run NEVER re-translates and NEVER touches
#     an article already in the target language; summaries skip the already-summarized.
#     The start event reports `to_process` so the user sees how many will actually run.
#   * stream HONEST per-article progress as NDJSON (invariant #20 — never a fabricated
#     bar/ETA; only what actually completed),
#   * rely on the client's per-call kill-switch check (airplane mode aborts loudly),
#   * store each result as its OWN ArticleAnalysis row — kept forever, NEVER replacing
#     a prior one (the latest is shown first; older ones fold away in the reader).
# These rows are NOT keyword-indexed (they live in article_analyses, never in
# articles.content), so bulk output never pollutes the keyword analytics.

# code -> English name (mirrors the frontend _LANG_EN) so a translate run can skip an
# article already written in the target language.
_LANG_EN = {
    "en": "English", "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese",
    "ru": "Russian", "ar": "Arabic", "zh": "Chinese", "ja": "Japanese", "hi": "Hindi",
    "bn": "Bengali", "id": "Indonesian", "it": "Italian", "nl": "Dutch",
}


def _is_target_language(article_lang: str | None, target_name: str) -> bool:
    """True when an article is ALREADY in the translation target (so it is skipped).
    Unknown language -> False (never skip on a guess)."""
    code = (article_lang or "").strip().lower()
    if not code:
        return False
    tgt = (target_name or "").strip().lower()
    return code == tgt or _LANG_EN.get(code, "").lower() == tgt


class BulkLLMRequest(BaseModel):
    op: str  # "summarize" | "translate"
    article_ids: list[int] | None = None
    query: str | None = None
    source: str | None = None
    language: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    target_language: str = "English"
    output_language: str | None = None  # v2 language pin for the summarize op
    ui_lang: str | None = None  # UI language CODE -> native output directive (2026-06-21)
    model: str | None = None
    skip_existing: bool = True
    limit: int = 0  # 0 = no cap (process the whole matched set)


@router.post("/bulk")
def bulk_llm(
    req: BulkLLMRequest,
    db: Session = Depends(get_db),
    client_info: tuple[str, LlmBackend] = Depends(get_llm_client_with_name),
):
    """Summarize OR translate every article in a matched set with the local model.

    Selection mirrors the analysis window: an explicit ``article_ids`` set wins,
    otherwise the search filters (query/source/language/dates) resolve the set. The
    response streams NDJSON: one ``start`` object, one ``item`` per article
    (status = stored | skipped | failed), and a final ``done`` (or an aborted ``done``
    if the local model becomes unavailable mid-run — it won't recover, so we stop).

    B3 (2026-07-24 Session B): generation calls run through the bounded
    concurrency helper (``src.llm.concurrency``) — vLLM gets several requests
    in flight at once (the point of vLLM), Ollama stays serial by default. The
    STORE/STREAM order is always the input order regardless of which item's
    generation finished first (results are processed strictly in sequence per
    chunk), so a stored ``ArticleAnalysis`` never gets attributed to the wrong
    article and re-running with concurrency=1 is byte-identical to before.
    """
    client_backend_name, client = client_info
    op = (req.op or "").strip().lower()
    if op not in {"summarize", "translate"}:
        raise HTTPException(status_code=400, detail="op must be 'summarize' or 'translate'.")
    # UNCAPPED (maintainer 2026-06-20): process the WHOLE matched set. A positive `limit`
    # is an optional explicit bound; the default (<=0) means no cap. (The FTS path already
    # materialises the full match, so this is the same memory profile as the export path.)
    cap = req.limit if (req.limit and req.limit > 0) else None

    # Resolve the article set (the analysis window's own selection logic).
    if req.article_ids:
        seen: set[int] = set()
        ordered: list[int] = []
        for v in req.article_ids:
            if isinstance(v, int) and v not in seen:
                seen.add(v)
                ordered.append(v)
        ids = ordered if cap is None else ordered[:cap]
        requested = len(ids)
        by_id: dict[int, Article] = {}
        for _i in range(0, len(ids), _BULK_ID_CHUNK):
            chunk = ids[_i : _i + _BULK_ID_CHUNK]
            by_id.update({a.id: a for a in db.query(Article).filter(Article.id.in_(chunk)).all()})
        articles = [by_id[i] for i in ids if i in by_id]
    elif any([req.query, req.source, req.language, req.start_date, req.end_date]):
        from src.api.main import _query_articles

        arts, total = _query_articles(
            db, query=req.query, source=req.source, start_date=req.start_date,
            end_date=req.end_date, language=req.language, tags=None, limit=cap, offset=0,
        )
        articles = list(arts)
        requested = total
    else:
        raise HTTPException(status_code=400, detail="Provide article_ids or a query/filter.")

    # Snapshot the plain fields the stream needs (+ the article LANGUAGE so a translate run
    # can skip articles already in the target language), so it never depends on the request's
    # ORM session staying open while the (slow) model runs.
    work = [
        (a.id, a.title or "(untitled)", a.content or "", a.language)
        for a in articles
        if a.content
    ]
    if not work:
        raise HTTPException(status_code=404, detail="No matching articles with content.")

    model = req.model or active_model()
    target = (req.target_language or "English").strip() or "English"
    keep_alive = _effective_keep_alive()
    if op == "summarize":
        kind = "summary"
        system, prompt_version, prompt_text = _build_prompting(
            "summary", output_language=req.output_language, output_lang_code=req.ui_lang
        )
    else:
        kind = "translation"
        system, prompt_version, prompt_text = _build_prompting("translate", target=target)

    # skip_existing tops up only what's missing: which of these already have THIS exact
    # result (same kind, and for a translation the same target language)? We never
    # delete or replace — we just avoid recomputing what is already stored.
    already: set[int] = set()
    if req.skip_existing:
        work_ids = [w[0] for w in work]
        for _i in range(0, len(work_ids), _BULK_ID_CHUNK):
            chunk = work_ids[_i : _i + _BULK_ID_CHUNK]
            ex = db.query(ArticleAnalysis.article_id).filter(
                ArticleAnalysis.article_id.in_(chunk),
                ArticleAnalysis.kind == kind,
            )
            if op == "translate":
                ex = ex.filter(ArticleAnalysis.prompt_version == prompt_version)
            already.update(r[0] for r in ex.all())

    # A translate run NEVER translates an article already in the target language
    # (maintainer 2026-06-20) — unconditional, independent of skip_existing.
    same_lang: set[int] = set()
    if op == "translate":
        same_lang = {w[0] for w in work if _is_target_language(w[3], target)}

    total = len(work)
    # The count that will ACTUALLY run the model (shown up front so the user sees how many
    # articles are subject to translation / summarization): matched minus the already-done
    # (when skipping) and minus the already-in-target-language ones.
    to_process = sum(
        1 for w in work
        if w[0] not in same_lang and not (req.skip_existing and w[0] in already)
    )
    capped = False  # no cap anymore; kept for response compatibility

    # Make the run VISIBLE in the task manager ("is an LLM translating?"): one task
    # for the whole bulk run, progress = articles done / total (the model's REAL
    # work, never a fabricated %). Always finished, even on an early abort.
    from src.monitoring import tasks as _bgtasks

    _verb = "Summarizing" if op == "summarize" else f"Translating → {target}"
    _tok = _bgtasks.register(
        "llm", f"{_verb} {total} article(s)", detail=f"model {model}", total=total
    )

    def _stream():
        import json as _json

        from src.llm.concurrency import concurrency_for, run_concurrent

        def emit(obj: dict) -> str:
            return _json.dumps(obj, separators=(",", ":")) + "\n"

        yield emit({
            "event": "start", "op": op, "total": total, "requested": requested,
            "to_process": to_process, "already_done": len(already),
            "same_language": len(same_lang), "capped": capped, "model": model,
            "target_language": target if op == "translate" else None,
        })
        stored = skipped = failed = 0
        from src.database.session import SessionLocal

        # B3: vLLM gets several generations in flight at once; Ollama stays
        # serial (max_workers<=1 is a plain for-loop, byte-identical to before).
        concurrency = concurrency_for(client_backend_name)

        try:
          with SessionLocal() as s:
            i = 0
            n = len(work)
            while i < n:
                # Gather up to `concurrency` items that actually need a generation
                # call, skipping (inline, no model call) anything already done.
                batch: list[tuple[int, int, str, str]] = []  # (pos, article_id, title, prompt)
                while i < n and len(batch) < concurrency:
                    aid, title, content, _lang = work[i]
                    i += 1
                    pos = i
                    _bgtasks.update(_tok, done=pos)
                    if aid in same_lang:
                        skipped += 1
                        yield emit({"event": "item", "i": pos, "total": total,
                                    "article_id": aid, "title": title, "status": "skipped",
                                    "reason": "already in target language"})
                        continue
                    if req.skip_existing and aid in already:
                        skipped += 1
                        yield emit({"event": "item", "i": pos, "total": total,
                                    "article_id": aid, "title": title, "status": "skipped"})
                        continue
                    if op == "summarize":
                        prompt = f"Article title: {title}\n\n{content[:_MAX_CHARS]}"
                    else:
                        prompt = f"Title: {title}\n\n{content[:_MAX_CHARS]}"
                    batch.append((pos, aid, title, prompt))
                if not batch:
                    continue

                results = run_concurrent(
                    batch,
                    lambda item: client.generate(
                        item[3], model=model, system=system, keep_alive=keep_alive
                    ),
                    max_workers=concurrency,
                )
                # Process/store STRICTLY IN ORDER, regardless of which generation
                # actually finished first — a stored ArticleAnalysis always lines
                # up with the right article, and the first LLMUnavailable found
                # walking in order still aborts the run exactly like the serial
                # path did (results computed after it in wall-clock time but
                # earlier in sequence are simply discarded, never stored).
                for (pos, aid, title, _prompt), res in zip(batch, results, strict=True):
                    if not res.ok:
                        if isinstance(res.error, LLMUnavailable):
                            # Ollama down / model missing / airplane mode — won't recover.
                            yield emit({"event": "done", "total": total, "stored": stored,
                                        "skipped": skipped, "failed": failed,
                                        "aborted": True, "reason": str(res.error)[:200]})
                            return
                        failed += 1
                        yield emit({"event": "item", "i": pos, "total": total,
                                    "article_id": aid, "title": title, "status": "failed",
                                    "error": str(res.error)[:200]})
                        continue
                    result = res.value
                    s.add(ArticleAnalysis(
                        article_id=aid, kind=kind, result=result.text, model=result.model,
                        prompt_version=prompt_version, prompt_text=prompt_text,
                        created_at=datetime.now(UTC),
                    ))
                    s.commit()
                    stored += 1
                    yield emit({"event": "item", "i": pos, "total": total,
                                "article_id": aid, "title": title, "status": "stored",
                                "chars": len(result.text)})
          yield emit({"event": "done", "total": total, "stored": stored,
                      "skipped": skipped, "failed": failed, "aborted": False})
        finally:
            _bgtasks.finish(_tok)

    return StreamingResponse(_stream(), media_type="application/x-ndjson")
