"""
Dual-backend LLM resolution (B1, 2026-07-24 field-feedback Session B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RULED (A12, binding): vLLM on GPU-equipped machines (concurrency is the point,
B3), Ollama KEPT for the CPU-only fleet -- never a silent replacement, never
dropped. This module is the ONE place that decision is made, so every consumer
(the Settings AI tab, bulk summarize/translate, the triage/tag toggles, the law-
change summaries) resolves the SAME way instead of each hardcoding Ollama.

The resolution is DISCLOSED, never silent: ``resolve_backend()`` returns the
detection FACTS alongside the decision (GPU presence, vLLM installed/running,
Ollama available) so the Settings -> AI tab can state the active backend and
WHY, per the honesty non-negotiable (no fabricated capability, no hidden switch).

``LlmBackend`` is a structural Protocol (mypy-checked, not runtime-enforced) --
both ``OllamaClient`` and ``VllmClient`` already satisfy it without inheriting
from anything, so every existing Ollama-only call site keeps working unchanged;
only the RESOLVED client type changes when a GPU + an installed vLLM are present.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404 - fixed argv, no shell, 5s timeout (nvidia-smi probe only)
from typing import Protocol, runtime_checkable

from src.llm.ollama import GenerationResult

_VALID_OVERRIDES = ("auto", "ollama", "vllm")

# The clause every reason ends with when NOTHING can serve a request. A module
# constant so tests and any UI pin the sentence instead of a brittle literal.
NO_BACKEND_REASON = "no AI backend is reachable right now"


@runtime_checkable
class LlmBackend(Protocol):
    """The structural surface every LLM backend client provides. Both
    ``OllamaClient`` (``src.llm.ollama``) and ``VllmClient``
    (``src.llm.vllm_client``) satisfy this without declaring it explicitly --
    Python Protocols check structurally, so no inheritance/registration is
    needed and neither client's own module needs to import the other's."""

    def generate(
        self,
        prompt: str,
        *,
        model: str = ...,
        system: str | None = ...,
        keep_alive: str | None = ...,
    ) -> GenerationResult: ...

    def list_installed(self) -> list[str]: ...

    def is_available(self) -> bool: ...

    def close(self) -> None: ...


def detect_gpu() -> dict:
    """Best-effort NVIDIA GPU presence + VRAM probe via ``nvidia-smi`` (no torch/
    pynvml -- core stays free of GPU libraries). Honest ``available: False`` when
    the probe fails (no GPU, no driver, the command is missing, or it times out) --
    never asserted from guesswork. AMD/other GPUs are not probed here (vLLM's own
    ROCm path exists, per its PyPI description, but this app has no verified
    detection story for it yet; an honest gap, not a fabricated "no GPU")."""
    try:
        out = subprocess.run(  # noqa: S603,S607 - fixed argv, no shell, 5s cap
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return {"available": False, "reason": "nvidia-smi not found or timed out"}
    if out.returncode != 0 or not out.stdout.strip():
        return {"available": False, "reason": "nvidia-smi returned no GPU"}
    line = out.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    name = parts[0] if parts else None
    vram_mb: int | None = None
    if len(parts) > 1:
        try:
            vram_mb = int(float(parts[1]))
        except ValueError:
            vram_mb = None
    return {"available": True, "name": name, "vram_mb": vram_mb}


def _vllm_status() -> dict:
    """Delegates to ``src.llm.vllm_lifecycle`` (B2) -- imported lazily so a plain
    backend-resolution call never pays for importing the lifecycle module's own
    (heavier) subprocess-management machinery unless vLLM is actually in play."""
    try:
        from src.llm.vllm_lifecycle import is_installed, is_running
    except ImportError:
        return {"installed": False, "running": False}
    return {"installed": is_installed(), "running": is_running()}


def _ollama_available() -> bool:
    try:
        from src.llm.ollama import OllamaClient

        return OllamaClient().is_available()
    except Exception:  # noqa: BLE001 - a probe must never crash the resolver
        return False


def _result(
    *,
    backend: str,
    reason: str,
    override: str | None,
    gpu: dict,
    vllm: dict,
    ollama_ok: bool,
) -> dict:
    """Build the resolution payload. ONE builder for EVERY branch, so a field can
    never be present in three returns and silently missing from the fourth (the
    "an aggregation that omits an entry makes absent read as passed" family --
    the four hand-repeated dict literals this replaces were exactly that shape).

    ``available``/``no_backend`` are DERIVED from probes ``resolve_backend`` has
    already run this call -- no extra probe, no extra latency."""
    vllm_running = bool(vllm.get("running"))
    reachable = ollama_ok if backend == "ollama" else vllm_running
    return {
        "backend": backend,
        "reason": reason,
        "override": override,
        "gpu": gpu,
        "vllm": vllm,
        "ollama_available": ollama_ok,
        # --- V4 (2026-07-29) capability fields, purely ADDITIVE ------------ #
        "available": reachable,
        "no_backend": not (ollama_ok or vllm_running),
    }


def resolve_backend(*, override: str | None = None) -> dict:
    """The ONE decision point: which backend should serve inference right now,
    and why. Returns::

        {
          "backend": "ollama" | "vllm",   # SELECTION -- who would serve
          "reason": "<disclosed, human-readable>",
          "override": "<the requested override, or None>",
          "gpu": {...},            # detect_gpu()
          "vllm": {"installed": bool, "running": bool},
          "ollama_available": bool,
          "available": bool,       # CAPABILITY -- is the SELECTED backend reachable NOW
          "no_backend": bool,      # NOTHING is reachable (neither Ollama nor vLLM)
        }

    SELECTION AND CAPABILITY ARE NOT THE SAME QUESTION (V4, 2026-07-29). The
    operator's 2026-07-29 diagnostics bundle showed ``backend: "ollama"`` with
    the reason "... using Ollama meanwhile" while ``ollama_available`` was
    ``false``: true about selection, misleading about capability -- that machine
    had NO working backend. ``ollama_available`` was computed and returned but
    consulted by no branch. Now every reason names the real situation, and a
    caller can test capability without re-deriving it.

    COST: both new fields are derived from probes this function ALREADY runs on
    every call (``_ollama_available()``, and ``_vllm_status()``'s ``is_running()``
    live health check) -- no additional probe, no additional latency.

    HONESTY: ``available`` is never assumed true. Both probes return False when
    they fail OR error, so False means "not observed reachable", never "known
    dead" -- the conservative direction; neither can report an unreachable
    backend as reachable. Two known conflations ride along, named not hidden:
    ``_ollama_available()`` cannot distinguish a stopped daemon from a
    misconfigured non-loopback ``OO_OLLAMA_URL``, and ``_vllm_status()``'s
    ImportError fallback reports ``running: False`` without probing.

    Precedence: an explicit ``override`` (or ``OO_LLM_BACKEND``) of "ollama"/"vllm"
    always wins (an operator's explicit choice is never second-guessed) -- but an
    override that selects an unreachable backend now SAYS SO rather than reading
    as a working choice; "auto" (the default) prefers vLLM ONLY when a GPU is
    present AND vLLM is installed AND its server is currently running -- vLLM is
    never auto-selected merely because it is installed (a stopped server would
    silently 503 every call); the caller-facing "start vLLM" flow (B2/B4) is what
    brings it up. Ollama is the default and fallback in every other case (RULED
    A12 -- never dropped)."""
    env_override = os.getenv("OO_LLM_BACKEND", "").strip().lower()
    chosen_override = (override or env_override or "auto").strip().lower()
    if chosen_override not in _VALID_OVERRIDES:
        chosen_override = "auto"

    gpu = detect_gpu()
    vllm = _vllm_status()
    ollama_ok = _ollama_available()
    vllm_running = bool(vllm.get("running"))

    if chosen_override == "ollama":
        if ollama_ok:
            reason = "explicit override (ollama) -- Ollama is reachable"
        elif vllm_running:
            reason = (
                "explicit override (ollama), but Ollama is NOT reachable "
                "-- vLLM's server IS running; clear the override or start Ollama"
            )
        else:
            reason = (
                f"explicit override (ollama), but Ollama is NOT reachable -- {NO_BACKEND_REASON}"
            )
        return _result(
            backend="ollama",
            reason=reason,
            override=chosen_override,
            gpu=gpu,
            vllm=vllm,
            ollama_ok=ollama_ok,
        )

    if chosen_override == "vllm":
        if vllm_running:
            reason = "explicit override (vllm) -- its server is running"
        elif ollama_ok:
            reason = (
                "explicit override (vllm), but its server is NOT running "
                "-- Ollama IS reachable; clear the override to use it"
            )
        else:
            reason = (
                "explicit override (vllm), but its server is NOT running "
                f"-- {NO_BACKEND_REASON}"
            )
        return _result(
            backend="vllm",
            reason=reason,
            override=chosen_override,
            gpu=gpu,
            vllm=vllm,
            ollama_ok=ollama_ok,
        )

    # auto: vLLM only when a GPU is present AND vLLM is installed AND running.
    if gpu.get("available") and vllm.get("installed") and vllm_running:
        return _result(
            backend="vllm",
            reason="GPU detected + vLLM installed and running (concurrency-capable)",
            override=None,
            gpu=gpu,
            vllm=vllm,
            ollama_ok=ollama_ok,
        )

    # Every remaining branch FALLS BACK to Ollama -- so the reason must state
    # whether that fallback can actually serve a request (the V4 finding). The
    # SELECTION half of each sentence is unchanged (it is substring-pinned by
    # tests); only the trailing capability clause is now computed from a probe.
    if gpu.get("available") and vllm.get("installed"):
        selection = "GPU + vLLM installed but its server is not running"
        fallback = "using Ollama meanwhile (Ollama is reachable)"
    elif gpu.get("available"):
        selection = "GPU detected but vLLM is not installed"
        fallback = "using Ollama meanwhile (Ollama is reachable)"
    else:
        selection = "no GPU detected (or vLLM unavailable)"
        fallback = "Ollama is the CPU-first backend (reachable)"
    if ollama_ok:
        reason = f"{selection} -- {fallback}"
    elif vllm_running:
        # A vLLM server CAN be up while auto-selection declines it (is_running()
        # detects "a server started by another means entirely"): a backend IS
        # reachable, so this must NOT read as no_backend.
        reason = (
            f"{selection}, and Ollama is NOT reachable -- vLLM's server IS running "
            "but was not auto-selected (that needs a detected GPU and an installed vLLM)"
        )
    else:
        reason = f"{selection}, and Ollama is NOT reachable either -- {NO_BACKEND_REASON}"
    return _result(
        backend="ollama",
        reason=reason,
        override=None,
        gpu=gpu,
        vllm=vllm,
        ollama_ok=ollama_ok,
    )


# One client instance PER BACKEND KIND (never per call -- httpx connection pooling
# is worth reusing), re-resolved on every ``get_client()`` call so a backend that
# comes up/down mid-session (vLLM starting, Ollama restarting) is picked up without
# a process restart. Module-level singleton dict, mirrors the existing per-kind
# singleton convention (``src.api.llm._client`` before this change, ``OllamaClient``
# itself for pull_queue, etc.).
_clients: dict[str, object] = {}


def get_client_with_name(*, backend: str | None = None) -> tuple[str, LlmBackend]:
    """Resolve + return ``(backend_name, client)`` in ONE detection pass -- so a
    caller that also needs the backend NAME (B3's concurrency ceiling picks a
    different worker count for vLLM vs. Ollama) never re-runs GPU/vLLM/Ollama
    detection a second time just to learn what ``get_client()`` already knew."""
    from src.llm.ollama import OllamaClient
    from src.llm.vllm_client import VllmClient

    resolved = resolve_backend(override=backend)
    kind = resolved["backend"]
    # dict.setdefault is ONE atomic dict operation -- no check-then-act window
    # between reading membership and writing the cache entry (the 2026-07-25,
    # transversal audit 09, benign TOCTOU finding). A losing instance under a
    # genuine race is still constructed (as before) but never even bound to a
    # local before being superseded -- reclaimed near-instantly by refcounting.
    client = _clients.setdefault(kind, VllmClient() if kind == "vllm" else OllamaClient())
    return kind, client  # type: ignore[return-value]


def get_client(*, backend: str | None = None) -> LlmBackend:
    """Resolve + return the shared client for the active backend (lazily
    constructed, one instance per kind for the process lifetime)."""
    _, client = get_client_with_name(backend=backend)
    return client


def _reset_clients_for_tests() -> None:
    _clients.clear()
