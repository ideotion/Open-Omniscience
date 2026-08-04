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
    DEFAULT_VLLM_MODEL,
    LLMError,
    LLMUnavailable,
    OllamaClient,
)
from src.llm.prompts_i18n import PROMPTS as _PROMPTS

router = APIRouter(prefix="/api/llm", tags=["llm"])

# Prompt versions are part of provenance: bump when a default prompt changes.
# v2 (2026-06-17): tighter, honesty-first prompts — language pin, attribution guard,
# per-claim citations + single-source flag for synthesis (see _build_prompting).
SUMMARY_PROMPT_VERSION = "summary-v2"
# The English bodies live in ONE place (src/llm/prompts_i18n) alongside their
# eleven translations, so a copy here could never silently fork from them. The
# names are kept: they are the honest default for any path with no UI language
# to select with, and several tests + the prompt-editor endpoint refer to them.
_SUMMARY_SYSTEM = _PROMPTS["summary"]["en"]

TRANSLATE_PROMPT_VERSION = "translate-v2"
_TRANSLATE_SYSTEM = _PROMPTS["translate"]["en"]

# Keep prompts within a small CPU model's context. E-S4 (2026-08-01): no longer used
# to CUT user-asked work -- `src.ai_layer.context` sizes the budget from the configured
# window and the never-truncate paths chunk instead. Kept as the module's own default
# and because the synthesis path (a deliberately bounded multi-article excerpt set,
# not one article) still bounds its excerpts by it.
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
            # NEVER DEFAULT_MODEL here: that is an OLLAMA TAG, and vLLM cannot resolve
            # one — the two backends consume different artifacts (GGUF tag vs HF
            # safetensors repo) and their quantisation vocabularies do not translate.
            # Before DEFAULT_VLLM_MODEL existed this path handed vLLM a name it could
            # never serve, so the fallback silently produced a guaranteed failure.
            return DEFAULT_VLLM_MODEL
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


def _version_with_method(prompt_version: str, method: dict) -> str:
    """Record a CHUNKED run in the stored provenance.

    ``prompt_version`` is String(50), and the suffix is short by design. A single-call
    run is left untouched, so nothing about existing rows or the common path changes;
    only a run whose METHOD differed says so."""
    mode = (method or {}).get("mode")
    parts = int((method or {}).get("parts") or 1)
    if mode not in ("chunked", "hierarchical") or parts <= 1:
        return prompt_version
    combined = f"{prompt_version}+{mode}-{parts}"
    # The column is String(50) and this string is ALSO value-bearing: the translation
    # target language lives after the colon. Truncating into it would corrupt the
    # target rather than merely lose the method note, so on overflow the method note
    # is the thing dropped -- the response still carries it in full.
    return combined if len(combined) <= 50 else prompt_version


def _user_text_budget(text: str) -> tuple[int, str]:
    """How much article text fits one call, and which script it is written in.

    Reads the operator's configured context window; with none set this returns the
    pre-E-S4 constant, so nothing about a default install changes."""
    from src.ai_layer.context import dominant_script, text_budget_chars

    script = dominant_script(text or "")
    try:
        s = _llm_settings()
        num_ctx = getattr(s, "llm_max_context_length", None) if s else None
    except Exception:  # noqa: BLE001 - settings are advisory here
        num_ctx = None
    return text_budget_chars(num_ctx, script), script


def _run_over_long_text(
    client,
    *,
    op: str,
    title: str,
    content: str,
    model: str,
    system: str,
    keep_alive,
) -> tuple[str, dict]:
    """Run a USER-ASKED summarize/translate over text of any length.

    RULING 16: a user-driven operation NEVER silently truncates. Cutting a
    translation at 6,000 characters produces something indistinguishable from a
    complete translation of a shorter article -- the reader cannot tell, and that is
    exactly the kind of silence this project does not ship.

    Fits in one call -> one call, byte-identical to before. Too long -> the text is
    split at paragraph (then sentence) boundaries so that the parts CONCATENATE BACK
    to the whole, and:

      * translate  -- every part is translated and the results joined, because a
        translation of the whole is the concatenation of translations of its parts;
      * summary    -- every part is summarised, then those summaries are summarised
        together. A summary is NOT concatenative, so pasting part-summaries would
        produce a list, not a summary.

    Returns ``(text, method)``; ``method`` carries ``parts`` so the caller can label
    the result. The method change is disclosed, never hidden.
    """
    budget, script = _user_text_budget(content)
    head = f"Article title: {title or '(untitled)'}" if op == "summary" else f"Title: {title or '(untitled)'}"
    from src.ai_layer.context import chunk_text

    chunks = chunk_text(content or "", budget)
    if len(chunks) <= 1:
        prompt = f"{head}\n\n{chunks[0] if chunks else ''}"
        result = client.generate(prompt, model=model, system=system, keep_alive=keep_alive)
        return result.text, {"parts": 1, "mode": "single", "script": script, "model": result.model}

    parts: list[str] = []
    used_model = model
    for i, chunk in enumerate(chunks, 1):
        prompt = f"{head} (part {i} of {len(chunks)})\n\n{chunk}"
        r = client.generate(prompt, model=model, system=system, keep_alive=keep_alive)
        parts.append(r.text or "")
        used_model = r.model or used_model
    if op == "translate":
        return "\n\n".join(parts), {
            "parts": len(chunks),
            "mode": "chunked",
            "script": script,
            "model": used_model,
            "note": (
                f"Translated in {len(chunks)} parts, split at paragraph boundaries and "
                "joined. Every character of the article was translated."
            ),
        }
    combined = "\n\n".join(parts)
    r = client.generate(
        f"{head}\n\nThese are summaries of {len(chunks)} consecutive parts of one "
        f"article. Write ONE summary of the whole article from them.\n\n{combined}",
        model=model,
        system=system,
        keep_alive=keep_alive,
    )
    return (r.text or combined), {
        "parts": len(chunks),
        "mode": "hierarchical",
        "script": script,
        "model": r.model or used_model,
        "note": (
            f"A hierarchical summary over {len(chunks)} parts: each part was summarised, "
            "then those summaries were summarised together. Every character of the "
            "article was read, but only through that two-step reduction."
        ),
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
    from src.llm.prompts_i18n import prompt_for, prompt_version

    s = _llm_settings()
    overrides = {
        "summary": (s.llm_prompt_summary if s else ""),
        "translate": (s.llm_prompt_translate if s else ""),
        "synthesis": (s.llm_prompt_synthesis if s else ""),
    }
    override = (overrides.get(op) or "").strip()
    is_custom = bool(override)
    # RULING 14 (2026-07-31): the built-in body is now written in the UI language.
    # An OPERATOR OVERRIDE still wins verbatim -- unchanged contract: whoever wrote
    # their own prompt gets exactly it, in whatever language they wrote it, and no
    # translation table is consulted.
    template = override or prompt_for(op, output_lang_code)
    if op == "translate":
        tgt = (target or "English")
        system = _apply_target(template, tgt)
        base = "translate-custom" if is_custom else prompt_version(
            TRANSLATE_PROMPT_VERSION, output_lang_code)
        version = f"{base}:{tgt}"
    elif op == "synthesis":
        lang = (output_language or "").strip() or "English"
        system = template.replace("{language}", lang)
        version = ("synthesis-custom" if is_custom
                   else prompt_version(SYNTHESIS_PROMPT_VERSION, output_lang_code))
    else:  # summary
        lang = (output_language or "").strip() or "the same language as the article"
        system = template.replace("{language}", lang)
        version = ("summary-custom" if is_custom
                   else prompt_version(SUMMARY_PROMPT_VERSION, output_lang_code))
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
    # UI language CODE. Ruling 14 (2026-07-31) put the built-in prompt BODY into
    # the operator's language, and this is the only thing that selects it. Unset
    # falls back to the English body -- the behaviour before the ruling, so an
    # older client keeps working exactly as it did.
    ui_lang: str | None = None


@router.get("/health")
def llm_health(client=Depends(get_llm_client)) -> dict:
    """Report whether the ACTIVE backend (Ollama or vLLM, B1) is reachable and
    which model(s) it has. Drives the top-bar "AI" pill (B4) -- green/red by
    ``available``, no model count."""
    from src.llm.backend import resolve_backend

    # ONE resolution pass -- this call already happened here, so the V4 capability
    # fields ride into the payload for free: the top-bar pill can then name the
    # REAL situation ("no backend at all") instead of a generic "offline" that
    # reads the same whether the fallback is up or down.
    try:
        resolved = resolve_backend()
    except Exception:  # noqa: BLE001 - a resolution hiccup must not break the health check
        resolved = {}
    # NEVER fabricate a backend name we did not resolve. This previously said
    # "ollama" unconditionally on failure -- a claim about which backend is active
    # that nothing had observed. None = honestly unknown.
    backend = resolved.get("backend")
    no_backend = resolved.get("no_backend")
    backend_reason = resolved.get("reason")
    # HARDWARE SUITABILITY (2026-07-30) -- a THIRD, distinct state for the pill.
    # "this machine cannot practically run a local LLM" is NOT the same as "the
    # backend is offline": the first is not fixed by starting anything, so the pill
    # must not invite the operator to start a backend that would then crawl. Built
    # ONCE and spread into BOTH branches below, so it can never be present in one
    # return and silently missing from the other. Reuses resolve_backend()'s own
    # `gpu` dict -> no additional nvidia-smi probe on this (event-driven) path.
    from src.llm.backend import inference_capability

    try:
        hw = inference_capability(gpu=resolved.get("gpu"))
        hw_fields = {
            "hardware_practical": hw["practical"],
            "hardware_reason": hw["reason"],
            "hardware_overridden": hw["overridden"],
        }
    except Exception:  # noqa: BLE001 - a probe hiccup must not break the health check
        # None = honestly unknown, NEVER a fabricated "practical" or "impractical".
        hw_fields = {
            "hardware_practical": None,
            "hardware_reason": None,
            "hardware_overridden": None,
        }
    try:
        installed = client.list_installed()
        return {
            "available": True,
            "backend": backend,
            "no_backend": no_backend,
            "backend_reason": backend_reason,
            "base_url": client.base_url,
            "installed_models": installed,
            **hw_fields,
        }
    except LLMUnavailable as exc:
        return {
            "available": False,
            "backend": backend,
            "no_backend": no_backend,
            "backend_reason": backend_reason,
            "base_url": client.base_url,
            "installed_models": [],
            "detail": str(exc),
            **hw_fields,
        }


@router.get("/backend")
def llm_backend_status() -> dict:
    """The full backend-resolution DECISION + the facts behind it (B1.3) --
    which backend is active, why, and the detection facts (GPU / vLLM installed
    + running / Ollama available). Drives the Settings -> AI tab's disclosure
    (the maintainer must never see a silent switch)."""
    from src.llm.backend import inference_capability, resolve_backend
    from src.config.app_settings import load_settings

    allow_impractical: bool | None = None
    try:
        s = load_settings()
        override = s.llm_backend if s.llm_backend != "auto" else None
        stored_override = s.llm_backend
        allow_impractical = bool(s.llm_allow_impractical_hw)
    except Exception:  # noqa: BLE001 - a settings hiccup must not break the status view
        override, stored_override = None, "auto"
    resolved = resolve_backend(override=override)
    resolved["stored_override"] = stored_override
    # HARDWARE SUITABILITY (2026-07-30, maintainer-ruled). A SEPARATE question from
    # "which backend would serve": this says whether running a local LLM on this
    # machine is practical at all. Reuses the `gpu` dict resolve_backend() just
    # produced, so this costs ZERO additional nvidia-smi probes, and passes the
    # already-loaded setting so it costs zero additional settings reads either.
    resolved["hardware"] = inference_capability(
        override=allow_impractical, gpu=resolved.get("gpu")
    )
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
    from src.llm.ollama import MINISTRAL_SUGGESTION, annotate_catalog, total_ram_gb

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
        # The one-click Ministral suggestion (maintainer 2026-07-29). Served BESIDE
        # `catalog`, never inside it: the catalog carries a "verified against
        # ollama.com/library" contract this tag has not met, and merging it in would
        # launder an unverified entry into a verified list. Its own `verification` and
        # `caveats` fields travel with it so the UI can state what is and is not known.
        "ministral": MINISTRAL_SUGGESTION,
    }


@router.get("/prompts")
def llm_prompts(lang: str | None = None) -> dict:
    """The local-LLM behaviour the operator can tune (maintainer 2026-06-17): the
    keep-alive duration and the editable SYSTEM PROMPTS, each with its built-in
    default and the current override ("" = using the default). Read by Settings → Models.

    Four system prompts — ``summary`` (used for one OR many articles), ``translate`` (one
    OR many; ``{target}`` is the target language), ``synthesis`` (one combined output
    across several), and ``ai_keywords`` (the built-in keyword/entity EXTRACTION prompt,
    Part B; ``{max_terms}`` is the per-article cap). Bulk reuses the single-article
    summary/translate prompt per article — there is no separate "several" prompt.

    ``lang``: the UI language code. Ruling 14 (2026-07-31) put the four built-in
    bodies into the operator's language, so the DEFAULTS shown here must follow --
    otherwise the editor would display an English placeholder while a French prompt
    was the one actually running, which is exactly the kind of quiet disagreement
    between what is shown and what is used that provenance exists to prevent. Unset
    = English, so an older client sees precisely what it saw before.
    """
    from src.ai_layer.extract import EXTRACT_PROMPT_VERSION
    from src.config.app_settings import AppSettings
    from src.llm.prompts_i18n import normalize_lang, prompt_for, prompt_version

    code = normalize_lang(lang)
    s = _llm_settings()
    return {
        "keep_alive": (s.llm_keep_alive if s else AppSettings().llm_keep_alive),
        "keep_alive_default": AppSettings().llm_keep_alive,
        "prompts": {
            "summary": {
                "default": prompt_for("summary", code),
                "current": (s.llm_prompt_summary if s else "") or "",
                "version": prompt_version(SUMMARY_PROMPT_VERSION, code),
            },
            "translate": {
                "default": prompt_for("translate", code),
                "current": (s.llm_prompt_translate if s else "") or "",
                "version": prompt_version(TRANSLATE_PROMPT_VERSION, code),
            },
            "synthesis": {
                "default": prompt_for("synthesis", code),
                "current": (s.llm_prompt_synthesis if s else "") or "",
                "version": prompt_version(SYNTHESIS_PROMPT_VERSION, code),
            },
            "ai_keywords": {
                "default": prompt_for("ai_keywords", code),
                "current": (s.llm_prompt_ai_keywords if s else "") or "",
                "version": prompt_version(EXTRACT_PROMPT_VERSION, code),
            },
        },
        "note": (
            "Empty = use the built-in default. The exact prompt used is recorded with "
            "each result (provenance). The translate prompt may contain {target} for the "
            "target language; the keyword-extraction prompt may contain {max_terms}. "
            "Save changes via Settings (PUT /api/settings)."
        ),
        # Which language's built-in bodies are shown above. Stated rather than
        # implied: an operator comparing this editor against a stored result's
        # prompt_version needs to know the two are talking about the same text.
        "prompt_language": code,
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
    # The operator's explicit confirmation past a preflight WARNING (low RAM, or
    # a RAM-backed install target). Never overrides a BLOCKING refusal.
    acknowledge_low_resources: bool = False


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


_VLLM_MODEL_JOB = None


def _get_vllm_model_job():
    """The model-WEIGHTS download job, separate from the vLLM install job.

    Two jobs, not one, because they fail and cancel for different reasons and an
    operator may legitimately want the second without repeating the first (a second
    model, or a first download after an install they already ran). Same lazy
    registration as its sibling above."""
    global _VLLM_MODEL_JOB
    if _VLLM_MODEL_JOB is None:
        from src.jobs.background import BackgroundJob, register_job

        def _worker(ctx, **kwargs):
            # ONE job serves both the single default-model download and a bench-roster
            # batch, so they can never run at once against the same cache and the task
            # manager shows one honest "downloading" entry rather than two.
            from src.llm.vllm_lifecycle import (
                run_model_download_job,
                run_models_download_job,
            )

            if "models" in kwargs:
                return run_models_download_job(ctx, **kwargs)
            return run_model_download_job(ctx, **kwargs)

        _VLLM_MODEL_JOB = register_job(
            BackgroundJob(
                "vllm-model-download", "Downloading the model", _worker, cancellable=True
            )
        )
    return _VLLM_MODEL_JOB


def _pull_queue_state(artifact: str, queue: dict, installed: bool | None) -> dict:
    """The pull queue's view of ONE artifact, in the job vocabulary its vLLM sibling
    already speaks: ``state`` (running / done / error / cancelled / idle) + ``detail``.

    Why this exists at all (field report 2026-08-02): the caller that follows this
    endpoint waits for a ``state`` that is not ``"running"``, and NEITHER branch
    published one at the top level. The vLLM branch nested a BackgroundJob (which has
    a ``state``) under ``job``; the Ollama branch returned the raw queue, which has
    ``active``/``queue``/``history`` and no ``state`` anywhere. So the follower polled
    every three seconds forever and the setup chain hung on the download step on any
    machine -- the endpoint and its only consumer never agreed on where the answer
    lives. Both halves now answer in the follower's own vocabulary.

    ``idle`` is deliberately its own answer rather than being folded into ``done``:
    nothing was asked of the queue for this artifact, which is not the same as a
    finished download, and the two must not be told apart only by a comment. The
    already-installed case IS ``done``, because the goal state is reached -- with
    ``installed`` unknown (``None``, the daemon being down) it stays ``idle``, never
    a fabricated success."""
    active = queue.get("active") or {}
    if active.get("model") == artifact:
        pct = active.get("percent")
        detail = active.get("status") or "pulling"
        return {"state": "running", "detail": f"{detail} {pct}%" if pct else detail}
    if artifact in (queue.get("queue") or []):
        return {"state": "running", "detail": "queued"}
    for entry in reversed(queue.get("history") or []):
        if entry.get("model") != artifact:
            continue
        status = entry.get("status") or ""
        if status == "done":
            return {"state": "done", "detail": "downloaded"}
        if status == "cancelled":
            return {"state": "cancelled", "detail": "cancelled"}
        # Anything else the queue recorded is a failure, and the queue's own error
        # text is the only honest detail -- never a generic "failed".
        return {"state": "error", "detail": entry.get("error") or status or "failed"}
    if installed:
        return {"state": "done", "detail": "already installed"}
    return {"state": "idle", "detail": "no download has been requested"}


def _job_view(job: dict) -> dict:
    """Lift a BackgroundJob's own ``state``/``detail`` to the top level, so the two
    branches of ``/default-model/status`` are followed the same way. A projection
    rather than a spread of the whole job: only the two fields the follower reads are
    promoted, so a future job field can never shadow ``plan`` or ``backend``."""
    return {"state": job.get("state"), "detail": job.get("detail") or job.get("error") or ""}


@router.get("/default-model/status")
def default_model_status() -> dict:
    """Live state of the default-model download, for whichever backend serves.

    The Ollama half already had a live surface (the pull queue); the vLLM half had
    none, because there was no download to report on. There is now.

    BOTH halves now also report a top-level ``state``/``detail`` in the same
    vocabulary (2026-08-02): a caller that follows this endpoint to completion must
    not have to know which backend answered in order to recognise the end."""
    plan = _default_model_plan()
    if plan["backend"] != "vllm":
        from src.llm.pull_queue import get_pull_manager

        queue = get_pull_manager().status()
        view = _pull_queue_state(plan["artifact"], queue, plan.get("installed"))
        return {"backend": "ollama", "plan": plan, "queue": queue, **view}
    job = _get_vllm_model_job().status()
    return {"backend": "vllm", "plan": plan, "job": job, **_job_view(job)}


@router.post("/vllm/install")
def vllm_install(req: VllmInstallRequest | None = None) -> dict:
    """Start the CONSENTED, task-manager-visible vLLM install (B2.3): a dedicated
    venv + ``pip install vllm==<verified version>`` (drags torch/CUDA, several
    GB -- disclosed via ``/api/llm/vllm/status``'s ``estimated_size_note``
    before the frontend even offers this button). Refuses (409) on a non-Linux
    host (no vLLM wheel exists there at all), a CPU-only machine, under
    airplane mode, or when the resource preflight BLOCKS (not enough disk to
    unpack the wheels) / WARNS without an acknowledgement (low RAM, or a
    RAM-backed install target); 409-free for an already-running install
    (returns its current status).

    The platform/CPU/airplane checks run HERE, synchronously, before the
    background job even starts -- ``run_install_job`` re-checks all three
    itself (defense in depth for any direct caller), but a check made only
    inside the worker THREAD would surface as an async job failure, not this
    endpoint's 409 (the BackgroundJob chassis returns immediately once
    ``.start()`` spawns the thread; an exception raised inside the worker
    never propagates back here). An already-in-flight install is reported
    409-free regardless of the current platform/GPU/airplane state (those
    conditions gate STARTING a new install, not an already-running one)."""
    from src.ingest.egress_window import PURPOSE_AI_INSTALL, egress_permitted
    from src.llm.backend import detect_gpu
    from src.llm.vllm_lifecycle import (
        VLLM_VERIFIED_VERSION,
        install_preflight,
        platform_support,
    )

    body = req or VllmInstallRequest()
    job = _get_vllm_install_job()
    if job.status().get("running"):
        st = job.status()
        st["started"] = False
        return st
    support = platform_support()
    if not support["supported"]:
        raise HTTPException(status_code=409, detail=support["reason"])
    if not egress_permitted(PURPOSE_AI_INSTALL):
        raise HTTPException(
            status_code=409,
            detail="Network is OFF (airplane mode): refusing to install vLLM. "
            "Turn airplane mode off, or allow the AI install to go online on its own.",
        )
    gpu = detect_gpu()
    if not gpu.get("available"):
        raise HTTPException(
            status_code=409,
            detail="No GPU detected on this machine -- vLLM is GPU-first and would "
            "install into a backend that can never usefully run. Use Ollama instead.",
        )
    # Same synchronous-duplication rationale as the three checks above: the worker
    # re-runs the preflight itself, but a check made only inside the worker THREAD
    # surfaces as an async job failure instead of this endpoint's 409. The detail is
    # a DICT here (not a string) so the frontend can tell an acknowledgeable warning
    # from a hard refusal and drive the confirm dialog from the real numbers.
    pre = install_preflight(version=body.version or VLLM_VERIFIED_VERSION, gpu=gpu)
    if pre["blocking"]:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Cannot install vLLM on this machine.",
                "acknowledgeable": False,
                "blocking": pre["blocking"],
                "preflight": pre,
            },
        )
    if pre["requires_acknowledgement"] and not body.acknowledge_low_resources:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "This machine is below a resource floor for a vLLM install.",
                "acknowledgeable": True,
                "warnings": pre["warnings"],
                "preflight": pre,
            },
        )
    try:
        st = job.start(
            version=body.version or VLLM_VERIFIED_VERSION,
            acknowledge_low_resources=body.acknowledge_low_resources,
        )
        st["started"] = True
    except RuntimeError:
        st = job.status()
        st["started"] = False
    return st


@router.get("/vllm/install/preflight")
def vllm_install_preflight() -> dict:
    """What a vLLM install would cost THIS machine, measured, before the click
    (V2): free disk on the volume the venv will live on, total system RAM, and
    whether that volume is RAM-backed. ``blocking`` = the install will be
    refused; ``warnings`` = refused unless ``acknowledge_low_resources`` is set;
    ``notes`` = a probe that could not read its value (stated, never estimated).
    Read-only, no network."""
    from src.llm.vllm_lifecycle import install_preflight

    return install_preflight()


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
    # Acknowledge a model whose estimated weights exceed this GPU's VRAM. The estimate
    # reads the model NAME, so a quantised repo that does not advertise it in its name
    # must remain startable by an operator who knows better -- the refusal is a guard
    # against a silent CUDA OOM, not a claim to know every model's true footprint.
    allow_oversized: bool = False


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
            allow_oversized=req.allow_oversized,
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


def _provisioning_backend(r: dict) -> dict:
    """WHICH backend a DOWNLOAD should provision for -- which is not always the one
    :func:`resolve_backend` would route an inference call to right now.

    THE RULE ITSELF NOW LIVES IN ``src.llm.backend.provisioning_backend`` (2026-08-04),
    because a THIRD caller appeared: backend ACTIVATION ("which backend do I start")
    needs the same precedence, and a second copy of it is how two surfaces begin
    disagreeing about the same machine. This wrapper stays so the call sites and the
    tests that name it keep reading the same way; the body is one delegation.

    Field report 2026-08-02 ("the model does not download"), reproduced from the
    bundle: a laptop with an RTX 4070, vLLM installed but its server never started,
    and Ollama NOT installed at all. ``resolve_backend`` correctly answered
    ``"ollama"`` -- Ollama is the ruled fallback and its own reason said outright
    that NOTHING was reachable -- but reading that SELECTION as a download target
    named an Ollama tag and queued a pull into a daemon that does not exist. The
    setup panel meanwhile said "This machine will use vLLM", because the frontend
    picks its target from the hardware. Two notions of "which backend" met in one
    chain, and the honest one for provisioning is not the routing one:

      * ROUTING asks who can serve THIS request, so an unreachable backend is
        disqualified -- a stopped server would 503.
      * PROVISIONING asks what this machine will serve with ONCE SET UP, so
        "not running yet" is the normal state, and the answer must be what is
        installed (or, failing that, what the hardware can actually use).

    Precedence, and why: an explicit override wins (an operator's stated choice is
    never second-guessed, here as everywhere else) -> a REACHABLE backend wins next
    (something serves right now; feed that) -> otherwise installed-ness decides,
    with the GPU preference breaking a tie exactly as ``resolve_backend``'s auto
    branch does -> and when NEITHER is installed the hardware preference is
    reported together with ``prerequisite``, so the caller states what must be
    installed first instead of naming an artifact nothing here can fetch.

    Derived entirely from fields ``resolve_backend`` already returns: no extra
    probe, no second source of truth about what is installed."""
    from src.llm.backend import provisioning_backend

    return provisioning_backend(r)


def _default_model_plan() -> dict:
    """WHICH default-model artifact would be installed, for the backend that will
    actually serve, and by WHAT mechanism.

    The two backends do not merely want different files -- they DOWNLOAD differently,
    and pretending otherwise would be the fabrication here:

      * Ollama pulls a quantised image through the pull queue: a real download, one at
        a time, cancellable, with real byte progress.
      * vLLM fetches HuggingFace weights. It WOULD do that on its own at server start,
        which is why this used to report ``server_start`` and no download -- true, and
        useless as a button (field ask 2026-07-30: "there really should be a simple
        button to download locally Ministral-3b-instruct"). It now pre-fetches into the
        same HF cache the server reads, as a real job.

    Read-only and network-free: it reports the PLAN so the UI can label the button
    truthfully before the click, never after.
    """
    from src.llm.backend import resolve_backend
    from src.llm.ollama import MINISTRAL_SUGGESTION

    r = resolve_backend()
    pick = _provisioning_backend(r)
    backend = pick["backend"]
    mini = MINISTRAL_SUGGESTION
    if backend == "vllm":
        from src.llm.vllm_lifecycle import model_cache_state

        cache = model_cache_state(mini["vllm_model"])
        return {
            "backend": "vllm",
            "reason": r.get("reason"),
            "chosen_because": pick["chosen_because"],
            "prerequisite": pick["prerequisite"],
            "artifact": mini["vllm_model"],
            "mechanism": "download",
            "mechanism_note": (
                "Downloaded from Hugging Face into the local model cache the vLLM "
                "server reads at start. No percentage: the downloader reports progress "
                "as text, and turning that into a number here would be a guess."
            ),
            # A REAL answer now (the cache is probed) rather than the honest-but-useless
            # "we do not look", so the button can say "already downloaded" instead of
            # inviting a re-fetch of several GB the operator already holds. Still None,
            # never False, when the cache itself is unreadable.
            "installed": cache["cached"],
            "cache": cache,
            "size": "~8 GB (FP8 weights)",
            "license": mini["license"],
            "caveats": mini["caveats"],
        }
    installed = False
    try:
        client = OllamaClient()
        installed = any(m.get("tag") == mini["tag"] for m in client.list_installed_detailed())
    except LLMUnavailable:
        # The daemon is down, so "is it installed" is genuinely unknown -- NOT false.
        installed = None  # type: ignore[assignment]
    return {
        "backend": "ollama",
        "reason": r.get("reason"),
        "chosen_because": pick["chosen_because"],
        "prerequisite": pick["prerequisite"],
        "artifact": mini["tag"],
        "mechanism": "pull",
        "mechanism_note": (
            "Downloaded through the model pull queue — one at a time, cancellable, with "
            "real byte progress."
        ),
        "installed": installed,
        "size": mini["size"],
        "license": mini["license"],
        "caveats": mini["caveats"],
    }


@router.get("/default-model")
def default_model_plan() -> dict:
    """What "install the default model" would do on THIS machine (read-only)."""
    return _default_model_plan()


@router.post("/default-model/install")
def default_model_install() -> dict:
    """Install the default model for whichever backend will actually be used.

    Field ask 2026-07-30: "download the appropriate ministral from either vllm or
    ollama depending on which will be used". The choice is not re-derived here -- it
    comes from :func:`resolve_backend`, the same function the pill and every inference
    call already trust, so the button can never install for a backend that will not
    serve.

    BOTH paths egress CLEARNET (Ollama's registry / Hugging Face), and neither goes
    through Tor, so both are refused under the kill switch rather than only the one that
    happens to route through our own client.
    """
    from src.ingest.egress_window import PURPOSE_AI_INSTALL, egress_permitted

    if not egress_permitted(PURPOSE_AI_INSTALL):
        raise HTTPException(
            status_code=409,
            detail=(
                "Airplane mode is engaged. Downloading a model is clearnet traffic "
                "(the model registry / Hugging Face), so it is refused while offline. "
                "Local inference with an already-installed model still works. "
                "You can also allow the AI install to go online on its own, which "
                "does not start collecting."
            ),
        )
    plan = _default_model_plan()
    if plan["backend"] == "vllm":
        from src.llm.vllm_lifecycle import VllmUnsupportedError, venv_python

        # The downloader lives in the managed venv (huggingface_hub ships with vLLM),
        # so name THAT as the reason rather than failing generically -- the fix is one
        # button away, on the same panel.
        if not venv_python().is_file():
            raise HTTPException(
                status_code=409,
                detail=str(
                    VllmUnsupportedError(
                        "vLLM is not installed yet, and the model downloader lives in "
                        "its environment. Install vLLM first, then download the model."
                    )
                ),
            )
        job = _get_vllm_model_job()
        if job.status().get("running"):
            return {**plan, "action": "downloading", "result": job.status()}
        try:
            from src.config.app_settings import save_settings

            save_settings({"llm_model_vllm": plan["artifact"]})
        except Exception:  # noqa: BLE001 - a settings hiccup must not read as a failed install
            pass
        job.start(model=plan["artifact"])
        return {**plan, "action": "downloading", "result": job.status()}

    # The symmetric prerequisite check to the vLLM branch above (field report
    # 2026-08-02). The pull queue accepts any well-formed tag and only discovers the
    # daemon is missing inside its pump thread, so without this an operator with no
    # Ollama installed got a cheerful "queued" for a download that could never begin.
    # A queue that accepts work for an absent worker reports success it cannot deliver.
    if plan.get("prerequisite") == "ollama":
        raise HTTPException(
            status_code=409,
            detail=(
                "Ollama is not installed yet, and its pull queue is what downloads "
                "this model. Install Ollama first, then download the model."
            ),
        )

    from src.llm.pull_queue import get_pull_manager

    try:
        queued = get_pull_manager().enqueue(plan["artifact"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        from src.config.app_settings import save_settings

        save_settings({"llm_model": plan["artifact"]})
    except Exception:  # noqa: BLE001 - the download is the load-bearing half
        pass
    return {**plan, "action": "queued", "result": queued}


class BenchRosterInstallRequest(BaseModel):
    """Which roster models to install. ``keys`` are roster keys, never raw identifiers:
    a caller cannot smuggle an arbitrary repo through this endpoint, and every string
    that reaches a download came from the dated roster."""

    keys: list[str] = []
    #: Which backend to install for. Omitted means "whichever this machine will serve
    #: with" -- the same provisioning question the default-model button asks. Named
    #: explicitly by the panels, because the vLLM section and the Ollama section each
    #: show THEIR OWN roster and must install what they showed.
    backend: str | None = None


def _roster_backend(explicit: str | None) -> dict:
    """The backend a roster view or install is about, and why.

    An explicit choice from a panel wins: the vLLM section showing Hugging Face repos
    must not install Ollama tags because the machine happens to prefer Ollama today."""
    from src.llm.backend import resolve_backend

    r = resolve_backend()
    pick = _provisioning_backend(r)
    if explicit in {"vllm", "ollama"} and explicit != pick["backend"]:
        installed = bool((r.get(explicit) or {}).get("installed"))
        return {
            "backend": explicit,
            "chosen_because": "explicitly requested by the panel",
            "prerequisite": None if installed else explicit,
        }
    return pick


@router.get("/bench-roster")
def bench_roster(backend: str | None = None) -> dict:
    """The comparative-bench roster for whichever backend this machine will serve with.

    Read-only and network-free: it reports what WOULD be installed, including the rows
    it cannot install, so the panel can be truthful before the operator clicks rather
    than after. Uses the same provisioning question as the default-model button --
    what will this machine serve with once set up -- not the routing question, which
    disqualifies a backend that is merely stopped."""
    from src.llm.bench_roster import roster_for

    pick = _roster_backend(backend)
    out = roster_for(pick["backend"])
    out["chosen_because"] = pick["chosen_because"]
    out["prerequisite"] = pick["prerequisite"]
    return out


@router.post("/bench-roster/install")
def bench_roster_install(req: BenchRosterInstallRequest | None = None) -> dict:
    """Install the selected roster models on the backend that will serve.

    Both paths egress CLEARNET (Hugging Face / the Ollama registry), neither goes
    through Tor, so both are refused under the kill switch exactly as the single
    default-model download is.

    REFUSALS TRAVEL WITH THE RESULT. Two of the six models are not published for
    Ollama, and selecting one returns it in ``refused`` with the reason rather than
    quietly downloading the four that do exist -- the operator asked for six and is
    owed an account of six."""
    from src.ingest.egress_window import PURPOSE_AI_INSTALL, egress_permitted
    from src.llm.bench_roster import identifiers_for

    if not egress_permitted(PURPOSE_AI_INSTALL):
        raise HTTPException(
            status_code=409,
            detail=(
                "Airplane mode is engaged. Downloading models is clearnet traffic "
                "(Hugging Face / the model registry), so it is refused while offline. "
                "You can allow the AI install to go online on its own, which does not "
                "start collecting."
            ),
        )
    body = req or BenchRosterInstallRequest()
    pick = _roster_backend(body.backend)
    backend = pick["backend"]
    if pick["prerequisite"]:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{'vLLM' if backend == 'vllm' else 'Ollama'} is not installed yet, and "
                "it is what downloads these models. Install it first."
            ),
        )
    ok, refused = identifiers_for(backend, body.keys)
    if not ok:
        return {"backend": backend, "action": "nothing_to_do", "queued": [], "refused": refused}

    if backend == "vllm":
        job = _get_vllm_model_job()
        if job.status().get("running"):
            return {
                "backend": backend,
                "action": "busy",
                "detail": "a model download is already running",
                "refused": refused,
                "result": job.status(),
            }
        job.start(models=[m["identifier"] for m in ok])
        return {
            "backend": backend,
            "action": "downloading",
            "queued": [m["identifier"] for m in ok],
            "refused": refused,
            "result": job.status(),
        }

    from src.llm.pull_queue import get_pull_manager

    manager = get_pull_manager()
    queued: list[str] = []
    for m in ok:
        try:
            manager.enqueue(m["identifier"])
            queued.append(m["identifier"])
        except ValueError as exc:
            # A malformed tag is one model's problem, not the batch's.
            refused.append({"key": m["key"], "label": m["label"], "reason": str(exc)})
    return {
        "backend": backend,
        "action": "queued",
        "queued": queued,
        "refused": refused,
        "result": manager.status(),
    }


@router.get("/bench-roster/status")
def bench_roster_status(backend: str | None = None) -> dict:
    """Live state of a roster install, resolved by the SAME question as the install.

    Not a reuse of ``/default-model/status``: that one resolves the backend from the
    default-model plan, so a vLLM panel installing on a machine that would otherwise
    provision Ollama would follow the wrong job and report a stranger's progress as its
    own. The follower must read the job the install actually started.

    HONEST SCOPE, because the two backends differ in kind. The vLLM path owns a single
    job, so its state IS this batch's state. The Ollama path enqueues into the shared
    pull queue, so what is reported is THE QUEUE -- which may carry pulls this batch did
    not ask for. ``queue_is_shared`` says which of the two you are reading rather than
    letting a caller assume."""
    pick = _roster_backend(backend)
    if pick["backend"] == "vllm":
        job = _get_vllm_model_job().status()
        return {"backend": "vllm", "queue_is_shared": False, "job": job, **_job_view(job)}

    from src.llm.pull_queue import get_pull_manager

    queue = get_pull_manager().status()
    active = queue.get("active")
    pending = queue.get("queue") or []
    if active:
        detail = f"downloading {active.get('model', '')} — {active.get('percent', 0)}%"
    elif pending:
        detail = f"{len(pending)} waiting"
    else:
        detail = "nothing downloading"
    return {
        "backend": "ollama",
        "queue_is_shared": True,
        "queue": queue,
        "state": "running" if (active or pending) else "done",
        "detail": detail,
    }


@router.get("/ollama/state")
def ollama_state() -> dict:
    """INSTALLED and RUNNING as two independent facts (field report 2026-07-29).

    Before this, the only Ollama predicate in any availability path was a probe of the
    RUNNING daemon, so an installed-but-stopped Ollama looked exactly like an absent
    one and the UI offered no control at all for it. Read-only, no network, and
    truthful while the daemon is down -- which is the whole point.
    """
    from src.llm.ollama_lifecycle import state

    return state()


@router.post("/ollama/start")
def ollama_start() -> dict:
    """Launch ``ollama serve`` (field report 2026-07-29: "a 'launch' button would then
    be made available to the user to start either service").

    Idempotent BY PROBE: an already-answering daemon reports ``started: false, reason:
    "already running"`` and nothing is spawned -- important because the daemon is
    frequently owned by systemd rather than by us. 409 when the binary is absent (that
    is an install problem, not a launch problem, and the install box is the right
    surface for it).

    NOT airplane-gated, deliberately: ``ollama serve`` binds a loopback port, and it is
    what makes the already-ruled offline loopback inference possible at all. Refusing it
    under the kill switch would make that allowance unusable exactly when it matters.
    Pull/remove stay refused offline -- their egress is real.
    """
    from src.llm.ollama_lifecycle import OllamaLifecycleError, start

    try:
        return start()
    except OllamaLifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/activation")
def llm_activation_plan() -> dict:
    """Which backend would be STARTED on this machine, and whether it can be.

    Read-only. The third "which backend" question, distinct from routing
    (``/backend``) and from provisioning (``/default-model``) -- see
    ``src.llm.activation``.
    """
    from src.llm.activation import activation_plan

    return activation_plan()


@router.post("/activation/start")
def llm_activation_start() -> dict:
    """Bring a local backend up: vLLM where it can run, Ollama otherwise, and
    whichever one the operator explicitly chose regardless.

    This is what the AI control does when the operator switches local AI on. Before
    it existed, "Start background AI" probed a backend that nothing had started,
    found nothing, and spent its whole retry budget on a condition retrying cannot
    change ("local model hiccup", ten times).

    ALWAYS 200: an ordinary refusal (nothing installed, weights not downloaded) is a
    sentence in the payload, not an exception -- the caller is a button, and a stack
    trace is not an answer to "please start". ``ready`` is the only field that claims
    the backend is answering; a vLLM start reports ``started: true, ready: false``
    while the engine loads, which is the truth and not a failure.

    Not airplane-gated, for the reason the Ollama launch endpoint above already
    states: both servers bind loopback and this is what makes ruled offline inference
    possible. The one start that WOULD egress -- vLLM fetching uncached weights from
    Hugging Face inside its own subprocess -- is refused by name in the plan instead.
    """
    from src.llm.activation import ensure_running

    return ensure_running()


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
    # Visible in the task manager while the model runs ("is an LLM working?").
    from src.monitoring.tasks import track

    _t = (article.title or "article")[:48]
    try:
        with track("llm", f"Summarizing “{_t}”", detail=f"model {model}"):
            text, method = _run_over_long_text(
                client, op="summary", title=article.title or "", content=article.content,
                model=model, system=system, keep_alive=_effective_keep_alive(),
            )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # The METHOD is provenance: a hierarchical summary over 4 parts is a different
    # artifact from a single-call one, and the stored row has to be able to say which.
    stored_version = _version_with_method(prompt_version, method)
    analysis = ArticleAnalysis(
        article_id=article.id,
        kind="summary",
        result=text,
        model=method.get("model") or model,
        prompt_version=stored_version,
        prompt_text=prompt_text,
        created_at=datetime.now(UTC),
    )
    db.add(analysis)
    db.commit()
    return {
        "analysis_id": analysis.id,
        "article_id": article.id,
        "kind": "summary",
        "model": analysis.model,
        "prompt_version": stored_version,
        "result": text,
        "method": method,
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
    system, prompt_version, prompt_text = _build_prompting(
        "translate", target=req.target_language, output_lang_code=req.ui_lang
    )
    from src.monitoring.tasks import track

    _t = (article.title or "article")[:48]
    try:
        with track("llm", f"Translating → {req.target_language}: “{_t}”", detail=f"model {model}"):
            text, method = _run_over_long_text(
                client, op="translate", title=article.title or "", content=article.content,
                model=model, system=system, keep_alive=_effective_keep_alive(),
            )
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    stored_version = _version_with_method(prompt_version, method)
    analysis = ArticleAnalysis(
        article_id=article.id,
        kind="translation",
        result=text,
        model=method.get("model") or model,
        prompt_version=stored_version,
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
        "model": analysis.model,
        "prompt_version": analysis.prompt_version,
        "result": text,
        "method": method,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


def _parse_target_language(prompt_version: str | None) -> str | None:
    """The translation target language is stored INSIDE the prompt version as
    ``translate-v2:French`` (or ``translate-custom:French``, and ``translate-v1:…`` on
    older rows) — provenance with no extra column. Recover it for display, covering the
    default, custom, and legacy prompt cases (any ``translate-*:lang``).

    E-S4 (2026-08-01): a chunked run appends ``+chunked-3`` to the SAME string, so the
    method suffix is stripped here. This field is value-bearing — a parser that read
    the suffix as part of the language would print "French+chunked-3" as the target,
    which is why ``_version_with_method`` refuses to append when it cannot do so
    without also risking the 50-character truncation cutting into the language."""
    if prompt_version and prompt_version.startswith("translate-") and ":" in prompt_version:
        return prompt_version.split(":", 1)[1].split("+", 1)[0] or None
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
_SYNTHESIS_SYSTEM = _PROMPTS["synthesis"]["en"]
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
            # Quarantined out: a bulk run spends real model time per member, and a
            # summary/translation of a link list is a wasted call whose output then
            # sits in the corpus looking like analysis of an article.
            ids = search_ids(db, req.query, exclude_quarantined=True) or []
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
        system, prompt_version, prompt_text = _build_prompting(
            "translate", target=target, output_lang_code=req.ui_lang
        )

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

        from src.ai_layer.coordinator import user_batch_hold
        from src.llm.concurrency import concurrency_for, run_concurrent

        def emit(obj: dict) -> str:
            return _json.dumps(obj, separators=(",", ":")) + "\n"

        yield emit({
            "event": "start", "op": op, "total": total, "requested": requested,
            "to_process": to_process, "already_done": len(already),
            "same_language": len(same_lang), "capped": capped, "model": model,
            "target_language": target if op == "translate" else None,
            # PREEMPTION (2026-08-01 ruling 13): this is a USER-initiated batch, so
            # it takes the exclusive hold below and the background-AI coordinator
            # stands down for its duration (every sweep's cursor persists, and the
            # lane resumes on its own afterwards). Announced in the start event so
            # the UI can say so rather than leaving the pause invisible.
            "pauses_background_ai": True,
        })
        stored = skipped = failed = 0
        from src.database.session import SessionLocal

        # B3: vLLM gets several generations in flight at once; Ollama stays
        # serial (max_workers<=1 is a plain for-loop, byte-identical to before).
        concurrency = concurrency_for(client_backend_name)

        # The hold is released in the context manager's `finally`, so an aborted
        # stream (a client disconnect, a model outage mid-run) can never strand the
        # coordinator paused forever.
        try:
         with user_batch_hold(f"bulk {op}"):
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
                    batch.append((pos, aid, title, content))
                if not batch:
                    continue

                # RULING 16: a bulk run is a USER-initiated batch, so it must not
                # silently truncate either. Each item goes through the same
                # never-truncate path as the single-article buttons; an item that
                # fits is one call, byte-identical to before, and one that does not
                # becomes several calls for THAT item only -- the concurrency seam
                # is unchanged, it just holds a slot longer.
                results = run_concurrent(
                    batch,
                    lambda item: _run_over_long_text(
                        client,
                        op=("summary" if op == "summarize" else "translate"),
                        title=item[2], content=item[3], model=model, system=system,
                        keep_alive=keep_alive,
                    ),
                    max_workers=concurrency,
                )
                # Process/store STRICTLY IN ORDER, regardless of which generation
                # actually finished first — a stored ArticleAnalysis always lines
                # up with the right article, and the first LLMUnavailable found
                # walking in order still aborts the run exactly like the serial
                # path did (results computed after it in wall-clock time but
                # earlier in sequence are simply discarded, never stored).
                for (pos, aid, title, _content), res in zip(batch, results, strict=True):
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
                    text, method = res.value
                    s.add(ArticleAnalysis(
                        article_id=aid, kind=kind, result=text,
                        model=method.get("model") or model,
                        prompt_version=_version_with_method(prompt_version, method),
                        prompt_text=prompt_text,
                        created_at=datetime.now(UTC),
                    ))
                    s.commit()
                    stored += 1
                    yield emit({"event": "item", "i": pos, "total": total,
                                "article_id": aid, "title": title, "status": "stored",
                                "chars": len(text), "parts": method.get("parts", 1)})
          yield emit({"event": "done", "total": total, "stored": stored,
                      "skipped": skipped, "failed": failed, "aborted": False})
        finally:
            _bgtasks.finish(_tok)

    return StreamingResponse(_stream(), media_type="application/x-ndjson")
