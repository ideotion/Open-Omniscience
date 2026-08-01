"""
Local LLM access via Ollama (HTTP only).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Ollama is an external native binary; the app talks to it over HTTP via httpx and
keeps NO heavy ML in-process (no torch/transformers). Privacy: inference is fully
local; no data leaves the machine.

Degrade LOUDLY (PRODUCT_SYNTHESIS §3.7): if Ollama is unreachable or the requested
model is not installed, raise -- never return a fabricated "analysis".
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

# Real, currently-existing Ollama tags suitable for CPU-only single-user use.
# (The previous catalog -- gemma4:e2b, llama4, qwen3.5 -- was hallucinated.)
#
# HONESTY CONTRACT (maintainer direction, 0.0.8): this list goes stale fast.
# CATALOG_AS_OF is shown wherever the catalog appears, and a repo-invariant test
# (tests/test_repo_invariants.py) FAILS once it is older than the freshness
# window -- so every release cycle is forced to re-verify it against
# https://ollama.com/library or knowingly bump the date. `min_ram_gb` powers the
# in-app hardware-fit annotation (it informs the operator's choice, never makes
# it). Always prefer the operator's actually-installed models (live from
# /api/tags) over this suggested list.
CATALOG_AS_OF = "2026-06"
# The Ollama server version this cycle was developed/tested against. We do NOT
# pin or bundle Ollama (it moves fast and is a per-OS native binary); we attest
# what we tested with, and `doctor` shows installed-vs-tested so a drift is
# visible without us pretending to a freshness we can't guarantee.
OLLAMA_TESTED_VERSION = "0.5.x"
MODEL_CATALOG: list[dict] = [
    # === Text generation (summarize / translate / synthesize use plain
    # /api/generate, no tool-calling -> any instruct/chat TEXT model that fits the
    # RAM works). Ordered RECOMMENDED-FIRST: models under OSI-approved permissive
    # licenses (Apache-2.0 / MIT) lead; models whose licenses carry acceptable-use
    # restrictions are listed lower and labelled, so the operator chooses with eyes
    # open. `license` is each model's OWN license (shown in the picker) -- never a
    # statement about the corpus. Verified against https://ollama.com/library this
    # cycle; two unverifiable entries (gemma4:e4b, translategemma:4b) were removed
    # rather than shipped on faith. The runtime can still point at ANY tag via
    # OO_LLM_MODEL / the in-app "pull any tag" box -- this is only the curated list. ===
    # --- Permissive (Apache-2.0 / MIT) — recommended; Mistral PRIORITISED (remark 1,
    #     maintainer 2026-06-24); tags maintainer-named, sizes advisory (verify on a
    #     networked box). Pick a smaller model if your RAM (min_ram_gb) is lower. ---
    {"tag": "mistral:7b", "size": "~4.4 GB", "min_ram_gb": 8, "license": "Apache-2.0", "note": "Mistral 7B — prioritised; runs on ~8 GB RAM; Apache-2.0"},
    {"tag": "mistral-small:latest", "size": "~14 GB", "min_ram_gb": 24, "license": "Apache-2.0", "note": "Mistral Small 3.x (~24B) — prioritised; capable but needs ~24 GB RAM; Apache-2.0"},
    {"tag": "granite4:350m", "size": "~0.3 GB", "min_ram_gb": 4, "license": "Apache-2.0", "note": "IBM Granite 4.0 — tiny (350M); simple tasks; Apache-2.0"},
    {"tag": "qwen3:1.7b", "size": "~1.4 GB", "min_ram_gb": 4, "license": "Apache-2.0", "note": "Alibaba Qwen3 (1.7B) — small & permissive; Apache-2.0"},
    {"tag": "granite4:micro", "size": "~2.1 GB", "min_ram_gb": 8, "license": "Apache-2.0", "note": "IBM Granite 4.0 — small (3.4B, hybrid); Apache-2.0"},
    {"tag": "granite4.1:3b", "size": "~2 GB", "min_ram_gb": 8, "license": "Apache-2.0", "note": "IBM Granite 4.1 — multilingual (3B); Apache-2.0"},
    # Licence read from the model card 2026-07-29 (apache-2.0, ungated) and tag read
    # from ollama.com/library — so it meets this list's verification bar. Needs Ollama
    # 0.13.1+, which is NEWER than OLLAMA_TESTED_VERSION; stated in the note rather than
    # discovered through a failed pull. Card names 11 languages; ru/hi/bn/id/th/vi/el/sr/mr
    # are not among them.
    {"tag": "ministral-3:3b-instruct-2512-q4_K_M", "size": "~3.0 GB", "min_ram_gb": 8, "license": "Apache-2.0", "note": "Mistral Ministral 3 (3B) — fits 8 GB VRAM; needs Ollama 0.13.1+; Apache-2.0; card names 11 languages (not ru/hi/bn/id/th/vi/el/sr/mr)"},
    # The app's DEFAULT since 2026-07-30 (see DEFAULT_MODEL). Tag, size, quant list and
    # digest read from ollama.com/library that day; the library publishes only q4_K_M,
    # q8_0 and fp16 for this model — there is no Q5_K_M there (see the entry below).
    # Multimodal (8.4B LM + 0.4B vision encoder); this blob bundles the vision projector,
    # though nothing in this app calls vision — summarize/translate/synthesize/triage/
    # source-tags/perception are all text.
    {"tag": "ministral-3:8b-instruct-2512-q4_K_M", "size": "~6.0 GB", "min_ram_gb": 16, "max_vram_gb": 8, "license": "Apache-2.0", "note": "Mistral Ministral 3 (8B) — the app's default; needs Ollama 0.13.1+; Apache-2.0; card names 11 languages but says 'dozens of languages, including' (non-exhaustive)"},
    # The Q5_K_M the maintainer asked for. It exists ONLY as a GGUF file in Mistral's own
    # repo, not on ollama.com/library, so it is reachable through Ollama's hf.co
    # passthrough. Listed rather than defaulted, with its gaps stated: (a) nobody has run
    # this pull, so that the tag RESOLVES is unverified — the file's existence and size
    # are verified, which is not the same claim; (b) the passthrough resolves one quant
    # file and almost certainly does NOT fetch the separate 858 MB mmproj, so vision is
    # likely lost (irrelevant here — see above — but stated rather than discovered).
    # Same size as the q4_K_M above because that one spends its budget on the vision
    # projector and this one spends it on text precision.
    {"tag": "hf.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF:Q5_K_M", "size": "~6.06 GB", "min_ram_gb": 16, "max_vram_gb": 8, "license": "Apache-2.0", "note": "Mistral Ministral 3 (8B, Q5_K_M) — higher-precision text than the library q4_K_M; pulled from Mistral's own GGUF repo via hf.co passthrough. UNVERIFIED: the file exists (6.06 GB) but this pull has not been run; vision projector likely not fetched."},
    {"tag": "qwen3:4b", "size": "~2.6 GB", "min_ram_gb": 8, "license": "Apache-2.0", "note": "Alibaba Qwen3 (4B) — balanced & permissive; Apache-2.0"},
    {"tag": "phi4-mini", "size": "~2.5 GB", "min_ram_gb": 8, "license": "MIT", "note": "Microsoft Phi-4-mini (3.8B) — MIT"},
    {"tag": "olmo2:7b", "size": "~4.5 GB", "min_ram_gb": 8, "license": "Apache-2.0", "note": "Allen AI OLMo 2 (7B) — fully open; Apache-2.0"},
    {"tag": "granite4.1:8b", "size": "~5 GB", "min_ram_gb": 8, "license": "Apache-2.0", "note": "IBM Granite 4.1 — multilingual (8B), RAG/tools; Apache-2.0"},
    {"tag": "phi4", "size": "~9 GB", "min_ram_gb": 16, "license": "MIT", "note": "Microsoft Phi-4 (14B) — MIT; needs ~16 GB"},
    {"tag": "gpt-oss:20b", "size": "~14 GB", "min_ram_gb": 16, "license": "Apache-2.0", "note": "OpenAI gpt-oss — 20B MoE reasoning; needs ~16 GB; Apache-2.0"},
    # --- Use-restricted licenses (kept available, NOT recommended as defaults) ---
    {"tag": "gemma3:1b", "size": "~0.8 GB", "min_ram_gb": 4, "license": "Gemma (use restrictions)", "note": "Google Gemma 3 (1B) — Gemma license, use restrictions"},
    {"tag": "gemma3:4b", "size": "~3.3 GB", "min_ram_gb": 8, "license": "Gemma (use restrictions)", "note": "Google Gemma 3 (4B) — Gemma license, use restrictions"},
    {"tag": "llama3.2:1b", "size": "~1.3 GB", "min_ram_gb": 4, "license": "Llama Community (use restrictions)", "note": "Meta Llama 3.2 (1B) — Llama Community License, use restrictions"},
    {"tag": "llama3.2:3b", "size": "~2 GB", "min_ram_gb": 8, "license": "Llama Community (use restrictions)", "note": "Meta Llama 3.2 (3B) — Llama Community License, use restrictions"},
    {"tag": "nemotron-mini", "size": "~2.7 GB", "min_ram_gb": 8, "license": "NVIDIA Open Model License", "note": "NVIDIA Nemotron Mini (4B) — NVIDIA Open Model License"},
    # === Embedding models: downloadable here, but the app's summarize / translate /
    # synthesize features do NOT use them (they are for semantic search / RAG, a
    # future capability). Labelled `kind: embedding` so the picker says so. ===
    {"tag": "embeddinggemma", "size": "~0.6 GB", "min_ram_gb": 4, "kind": "embedding", "license": "Gemma (use restrictions)", "note": "Google EmbeddingGemma (308M) — text embeddings; not used by summarize/translate"},
    {"tag": "nomic-embed-text-v2-moe", "size": "~1 GB", "min_ram_gb": 4, "kind": "embedding", "license": "Apache-2.0", "note": "Nomic Embed v2 MoE — multilingual embeddings (~100 languages); not used by summarize/translate"},
    {"tag": "bge-m3", "size": "~1.2 GB", "min_ram_gb": 4, "kind": "embedding", "license": "MIT", "note": "BAAI BGE-M3 — multilingual embeddings; not used by summarize/translate"},
]

# --------------------------------------------------------------------------- #
#  One-click Ministral (maintainer request 2026-07-29)
# --------------------------------------------------------------------------- #
# LICENCE BLOCKER CLEARED 2026-07-29. docs/design/AI_LAYER_STRATEGY_2026-07-29.md §2.4
# required "one page fetch of the model card" before any catalog entry, because the
# Apache-2.0 finding was single-sourced and the PREVIOUS generation (Ministral
# 8B-Instruct-2410) shipped under the non-commercial Mistral Research License. The
# maintainer performed that fetch: all three Ministral 3 cards (3B/8B/14B) carry
# `license: apache-2.0` in the README YAML and the verbatim line "This model is
# licensed under the Apache 2.0 License." The repos are ungated (no consent banner,
# no extra_gated_fields; an anonymous README fetch succeeded).
#
# So this is now a NORMAL catalog entry, held to the same bar as its peers -- it is
# listed in MODEL_CATALOG above rather than kept in quarantine.
#
# TAG CORRECTION, recorded because the earlier code asserted the opposite: the short
# form `ministral-3:3b` DOES exist and carries the SAME digest (f04aa1c738f6) as
# `ministral-3:3b-instruct-2512-q4_K_M` -- one image, two names. The long form is kept
# because it pins the quantisation explicitly; the short form is not "unverifiable", it
# is simply less specific.
#
# `ministral-3:latest` resolves to the 8B image (6.0 GB, q4_K_M, digest 1922accd5827 —
# the same blob as `ministral-3:8b` and `ministral-3:8b-instruct-2512-q4_K_M`), re-checked
# 2026-07-30. This used to be recorded as a warning ("do NOT use :latest") back when the
# 8B was the wrong model to land on; since 2026-07-30 the 8B IS the default, so it is
# recorded as a plain fact instead. Still prefer the explicit tag over `:latest`: a bare
# name silently follows whatever upstream re-points it at, which for a 6 GB download is
# a surprise worth not having.
MINISTRAL_TAG = "ministral-3:3b-instruct-2512-q4_K_M"
# The vLLM (GPU) counterpart. The model card states the 3B is "capable of fitting in
# 8GB of VRAM in FP8", and ships a vllm serve command requiring vllm >= 0.12.0 (our pin
# is 0.26.0). The 8B does NOT fit 8 GB in any published build: its FP8 weights are ~9 GB
# and the only 4-bit AWQ build reports 13.4 GB at runtime.
MINISTRAL_VLLM_MODEL = "mistralai/Ministral-3-3B-Instruct-2512"
# Ollama's own model page states this requirement. Our OLLAMA_TESTED_VERSION is 0.5.x,
# so an operator on the tested version CANNOT run it -- stated rather than discovered
# through a failed pull.
MINISTRAL_MIN_OLLAMA = "0.13.1"
MINISTRAL_SUGGESTION: dict = {
    "tag": MINISTRAL_TAG,
    "size": "~3.0 GB",
    "min_ram_gb": 8,
    "max_vram_gb": 8,
    "vllm_model": MINISTRAL_VLLM_MODEL,
    "min_ollama": MINISTRAL_MIN_OLLAMA,
    "license": "Apache-2.0",
    "verification": "licence read from the model card 2026-07-29; tag read from ollama.com/library",
    "note": (
        "Mistral Ministral 3 (3B, q4_K_M) — ~3.0 GB, fits under 8 GB VRAM. Apache-2.0, "
        "ungated. GPU users: mistralai/Ministral-3-3B-Instruct-2512 fits 8 GB in FP8."
    ),
    "caveats": [
        f"Requires Ollama {MINISTRAL_MIN_OLLAMA} or newer (this cycle was tested against "
        f"{OLLAMA_TESTED_VERSION}).",
        # CORRECTED 2026-07-29: the earlier text claimed only ar/zh/ja/ko were named. The
        # card actually enumerates ELEVEN languages. The substantive gap is unchanged and
        # is what matters for this corpus -- none of ru/hi/bn/id/th/vi/el/sr/mr is named,
        # though the card does say "dozens of languages", so they are unenumerated and
        # unbenchmarked rather than stated unsupported.
        "Card names 11 languages (en fr es de it pt nl zh ja ko ar). Not named: "
        "ru, hi, bn, id, th, vi, el, sr, mr — unenumerated, not stated unsupported.",
    ],
}
# The app's default OLLAMA model tag (a fallback when the operator has not chosen one
# in Settings). Override with OO_LLM_MODEL.
#
# RULED 2026-07-30 (maintainer): Ministral 3 8B replaces granite4:micro as the default.
# The previous default was chosen to be "low-spec-friendly"; that constraint is dropped
# by the same ruling, which scopes local inference to machines with a DEDICATED GPU (or
# Apple Silicon's unified memory) — on a GPU-less laptop inference is impractically slow
# whatever the model, so sizing the default down bought nothing real.
#
# 6.0 GB, Apache-2.0, ungated. Needs Ollama MINISTRAL_MIN_OLLAMA or newer.
#
# QUANT, stated because it is NOT what was asked for: the maintainer asked for Q5_K_M.
# ollama.com/library publishes NO Q5_K_M for any Ministral-3 size — only q4_K_M, q8_0
# and fp16 (checked 2026-07-30). A Q5_K_M does exist in Mistral's own GGUF repo and is
# listed in MODEL_CATALOG as a hf.co passthrough, but nobody has yet confirmed that the
# passthrough tag actually PULLS, and an unverified tag as the default would break every
# fresh install. So the verified library tag is the default and the Q5_K_M is one click
# away in the picker, carrying its own honest status. Promote it here once a real
# `ollama pull` confirms it.
DEFAULT_MODEL = os.getenv("OO_LLM_MODEL", "ministral-3:8b-instruct-2512-q4_K_M")

# The app's default VLLM model — a SEPARATE identifier, never the Ollama tag above.
#
# The two backends consume different artifacts of the same model and their quantisation
# vocabularies do not translate: Ollama takes GGUF tags (Q4_K_M/Q5_K_M/…), vLLM takes a
# HuggingFace safetensors repo (awq/gptq/fp8/…). Handing an Ollama tag to vLLM cannot
# work, which is exactly what api/llm.py::active_model did on its fallback path before
# this constant existed.
#
# This is the 3B, DELIBERATELY, on the same evidence recorded at MINISTRAL_VLLM_MODEL
# above: the 8B does not fit 8 GB of VRAM in any published vLLM build. Re-verified
# 2026-07-30 — the only 4-bit AWQ build is 7.18 GB of weights (~6.69 GiB resident,
# because the vision tower, the multimodal projector, lm_head and the embedding table
# all stay BF16 through 4-bit quantisation) and OOMs at startup on an 8 GB card. So on
# an 8 GB GPU the honest split is: 8B through Ollama for one-at-a-time quality work,
# 3B through vLLM where its concurrency actually pays (the corpus-wide sweeps).
DEFAULT_VLLM_MODEL = os.getenv("OO_VLLM_MODEL", MINISTRAL_VLLM_MODEL)


def total_ram_gb() -> float | None:
    """Total physical RAM in GB (for hardware-fit hints), or None if unknown."""
    try:
        import psutil

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:  # noqa: BLE001 - a hint is optional, never fatal
        return None


def annotate_catalog(ram_gb: float | None = None) -> list[dict]:
    """The catalog with a per-model hardware-fit hint based on total RAM.

    'fits' / 'tight' / 'too_large' / 'unknown' -- advisory only. We never hide a
    model or decide for the operator; we annotate so they can choose well.
    """
    ram = total_ram_gb() if ram_gb is None else ram_gb
    out = []
    for m in MODEL_CATALOG:
        need = m.get("min_ram_gb")
        if ram is None or need is None:
            fit = "unknown"
        elif ram >= need:
            fit = "fits"
        elif ram >= need * 0.75:
            fit = "tight"
        else:
            fit = "too_large"
        # kind defaults to "text" (usable by summarize/translate); an "embedding"
        # entry overrides it via **m, so the picker can label it honestly.
        out.append({"kind": "text", **m, "fit": fit})
    return out


class LLMError(Exception):
    """Base class for LLM failures."""


class LLMUnavailable(LLMError):
    """Ollama is unreachable, or the requested model is not installed."""


def _is_loopback_url(url: str) -> bool:
    """True if url's hostname is loopback (127.0.0.0/8, ::1, or the localhost family).

    Uses ``ipaddress`` for the numeric case (never a string prefix match — a bare
    ``.startswith("127.")`` would wrongly accept a crafted DNS name like
    ``127.0.0.1.evil.example``, which resolves to whatever IP the attacker's DNS
    returns, not loopback). A bare hostname is only treated as local via an exact
    match against the localhost aliases; anything else that fails IP parsing is
    treated as remote.
    """
    host = (urlparse(url).hostname or "").lower()
    if host in {"localhost", "ip6-localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # a remote (or unparsable) hostname


def _require_loopback(url: str) -> None:
    """Refuse a non-loopback Ollama URL (privacy: LLM egress must stay on the machine).

    Inference is fully local by design; ``OO_OLLAMA_URL`` pointing at a remote host
    would silently send corpus text off the machine. Allow only loopback hosts so a
    misconfiguration fails loudly instead of leaking. (Skipped when a client is
    injected — tests drive an in-memory MockTransport with no real egress.)
    """
    if _is_loopback_url(url):
        return
    host = (urlparse(url).hostname or "").lower()
    raise LLMError(
        f"OO_OLLAMA_URL must be loopback (127.0.0.1 / localhost / ::1); got {host!r}. "
        "The local LLM never talks to a remote host."
    )


@dataclass
class GenerationResult:
    model: str
    text: str
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    # Ollama's OWN measured timing (nanoseconds), passed through VERBATIM when present —
    # the raw material for the keyword-triage cost/ETA computation (planning §8) and any
    # honest throughput measurement. Absent (older Ollama / a non-timing response) = None,
    # never a fabricated 0. Additive: every existing GenerationResult(...) call omits these.
    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_duration: int | None = None
    eval_duration: int | None = None


class OllamaClient:
    """Thin, honest HTTP client for a local Ollama server."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = (base_url or os.getenv("OO_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip(
            "/"
        )
        self.timeout = timeout
        # Enforce loopback only when WE open the socket. An injected client (tests)
        # may use a MockTransport with a non-loopback nominal URL and never egress.
        if client is None:
            _require_loopback(self.base_url)
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    # -- network kill switch ----------------------------------------------- #

    def _check_kill_switch(self, *, clearnet: bool = False) -> None:
        """Refuse an Ollama call while the global kill switch (airplane mode) is engaged
        -- but only for calls whose egress actually reaches beyond the local machine.

        Loopback inference (list/generate: talking to OUR OWN Ollama daemon on
        127.0.0.1/localhost/::1) is not the kind of connection airplane mode is meant
        to guard against, so it is allowed through -- UNLESS ``base_url`` itself is
        not loopback, in which case this is defense in depth against a misconfigured
        or injected non-loopback client, and the call is refused like any other.

        ``clearnet=True`` call sites (pull/remove) are refused while offline
        regardless of ``base_url``: a pull instructs the separate Ollama PROCESS to
        fetch model weights over clearnet (maintainer Q9, 2026-06-16) -- egress this
        in-process socket guard cannot see. Degrade LOUDLY — never a fabricated answer.

        The ONE exemption for that clearnet half is an operator-consented EGRESS
        WINDOW (``src.ingest.egress_window``): pulling the default model IS the AI
        install the window exists for, and the operator was told, in the same breath
        as consenting, that Ollama fetches its weights itself and this app cannot
        bound which hosts it contacts. The kill switch stays engaged throughout, so
        the collector and every other gated fetch keep refusing.

        The NON-LOOPBACK ``base_url`` half is NEVER exempted by a window: that check
        is defense in depth against a misconfigured or injected client, which has
        nothing to do with installing the local AI.
        """
        from src.ingest import kill_switch_active
        from src.ingest.egress_window import PURPOSE_AI_INSTALL, egress_permitted

        if not kill_switch_active():
            return
        if not _is_loopback_url(self.base_url):
            raise LLMUnavailable(
                "Network is OFF (airplane mode): refusing the Ollama request to a "
                "non-loopback address. Turn airplane mode off to use the local LLM."
            )
        if clearnet and not egress_permitted(PURPOSE_AI_INSTALL):
            raise LLMUnavailable(
                "Network is OFF (airplane mode): refusing the Ollama request. "
                "Turn airplane mode off to use the local LLM."
            )

    # -- availability ------------------------------------------------------ #

    def is_available(self) -> bool:
        try:
            self.list_installed()
            return True
        except LLMUnavailable:
            return False

    def list_installed(self) -> list[str]:
        """Return installed model tags, or raise LLMUnavailable if Ollama is down."""
        self._check_kill_switch()
        try:
            resp = self._client.get("/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(
                f"Ollama not reachable at {self.base_url}: {exc}. Is the ollama service running?"
            ) from exc
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]

    def list_installed_detailed(self) -> list[dict]:
        """Installed models with sizes/dates as Ollama reports them (live, local).

        This is the source of truth for the in-app picker: what the operator
        ACTUALLY has, never a guessed catalog. Raises LLMUnavailable if down.
        """
        self._check_kill_switch()
        try:
            resp = self._client.get("/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(
                f"Ollama not reachable at {self.base_url}: {exc}. Is the ollama service running?"
            ) from exc
        out = []
        for m in resp.json().get("models", []):
            size = m.get("size")
            out.append(
                {
                    "tag": m.get("name"),
                    "size_gb": round(size / (1024**3), 1) if isinstance(size, int) else None,
                    "modified": m.get("modified_at"),
                }
            )
        return out

    # -- generation -------------------------------------------------------- #

    def generate(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_MODEL,
        system: str | None = None,
        options: dict | None = None,
        keep_alive: str | None = None,
    ) -> GenerationResult:
        """Single-shot completion. Raises LLMUnavailable if Ollama/model is absent.

        ``keep_alive`` is passed through to Ollama verbatim (e.g. "30m", "-1" to keep
        the model loaded, "0" to unload at once). None leaves Ollama's own default.
        """
        self._check_kill_switch()
        payload: dict = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        try:
            resp = self._client.post("/api/generate", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise LLMUnavailable(
                    f"Model {model!r} is not installed. Run: ollama pull {model}"
                ) from exc
            raise LLMError(f"Ollama error for model {model!r}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Ollama not reachable at {self.base_url}: {exc}") from exc
        data = resp.json()
        return GenerationResult(
            model=model,
            text=(data.get("response") or "").strip(),
            prompt_eval_count=data.get("prompt_eval_count"),
            eval_count=data.get("eval_count"),
            total_duration=data.get("total_duration"),
            load_duration=data.get("load_duration"),
            prompt_eval_duration=data.get("prompt_eval_duration"),
            eval_duration=data.get("eval_duration"),
        )

    def pull(self, model: str):
        """Pull (download + install) a model via the local Ollama process, STREAMING
        Ollama's own progress objects (yields dicts) — honest real progress, never a
        fabricated bar (invariant #20). Respects the kill switch.

        NOTE ON TRANSPORT (maintainer Q9, 2026-06-16): the pull egresses through the
        Ollama PROCESS over CLEARNET, NOT the app's Tor proxy/guarded factory — so
        airplane+Tor do not cover it. Airplane mode (the kill switch) still refuses it
        here; the UI must DISCLOSE the clearnet egress at consent."""
        self._check_kill_switch(clearnet=True)
        import json as _json

        try:
            with self._client.stream(
                "POST", "/api/pull", json={"model": model, "stream": True}
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        yield _json.loads(line)
                    except ValueError:
                        continue
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"Ollama error pulling {model!r}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Ollama not reachable at {self.base_url}: {exc}") from exc

    def remove(self, model: str) -> bool:
        """Delete an installed model via the local Ollama process. Returns True on
        success; LLMUnavailable if the model is absent. Respects the kill switch."""
        self._check_kill_switch(clearnet=True)
        try:
            resp = self._client.request("DELETE", "/api/delete", json={"model": model})
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise LLMUnavailable(f"Model {model!r} is not installed.") from exc
            raise LLMError(f"Ollama error removing {model!r}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Ollama not reachable at {self.base_url}: {exc}") from exc
        return True

    def close(self) -> None:
        self._client.close()
