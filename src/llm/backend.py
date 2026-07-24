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


def resolve_backend(*, override: str | None = None) -> dict:
    """The ONE decision point: which backend should serve inference right now,
    and why. Returns::

        {
          "backend": "ollama" | "vllm",
          "reason": "<disclosed, human-readable>",
          "override": "<the requested override, or None>",
          "gpu": {...},            # detect_gpu()
          "vllm": {"installed": bool, "running": bool},
          "ollama_available": bool,
        }

    Precedence: an explicit ``override`` (or ``OO_LLM_BACKEND``) of "ollama"/"vllm"
    always wins (an operator's explicit choice is never second-guessed); "auto"
    (the default) prefers vLLM ONLY when a GPU is present AND vLLM is installed
    AND its server is currently running -- vLLM is never auto-selected merely
    because it is installed (a stopped server would silently 503 every call);
    the caller-facing "start vLLM" flow (B2/B4) is what brings it up. Ollama is
    the default and fallback in every other case (RULED A12 -- never dropped)."""
    env_override = os.getenv("OO_LLM_BACKEND", "").strip().lower()
    chosen_override = (override or env_override or "auto").strip().lower()
    if chosen_override not in _VALID_OVERRIDES:
        chosen_override = "auto"

    gpu = detect_gpu()
    vllm = _vllm_status()
    ollama_ok = _ollama_available()

    if chosen_override == "ollama":
        return {
            "backend": "ollama",
            "reason": "explicit override (ollama)",
            "override": chosen_override,
            "gpu": gpu,
            "vllm": vllm,
            "ollama_available": ollama_ok,
        }
    if chosen_override == "vllm":
        return {
            "backend": "vllm",
            "reason": "explicit override (vllm)",
            "override": chosen_override,
            "gpu": gpu,
            "vllm": vllm,
            "ollama_available": ollama_ok,
        }
    # auto: vLLM only when a GPU is present AND vLLM is installed AND running.
    if gpu.get("available") and vllm.get("installed") and vllm.get("running"):
        reason = "GPU detected + vLLM installed and running (concurrency-capable)"
        return {
            "backend": "vllm",
            "reason": reason,
            "override": None,
            "gpu": gpu,
            "vllm": vllm,
            "ollama_available": ollama_ok,
        }
    if gpu.get("available") and vllm.get("installed") and not vllm.get("running"):
        reason = "GPU + vLLM installed but its server is not running -- using Ollama meanwhile"
    elif gpu.get("available") and not vllm.get("installed"):
        reason = "GPU detected but vLLM is not installed -- using Ollama meanwhile"
    else:
        reason = "no GPU detected (or vLLM unavailable) -- Ollama is the CPU-first backend"
    return {
        "backend": "ollama",
        "reason": reason,
        "override": None,
        "gpu": gpu,
        "vllm": vllm,
        "ollama_available": ollama_ok,
    }


# One client instance PER BACKEND KIND (never per call -- httpx connection pooling
# is worth reusing), re-resolved on every ``get_client()`` call so a backend that
# comes up/down mid-session (vLLM starting, Ollama restarting) is picked up without
# a process restart. Module-level singleton dict, mirrors the existing per-kind
# singleton convention (``src.api.llm._client`` before this change, ``OllamaClient``
# itself for pull_queue, etc.).
_clients: dict[str, object] = {}


def get_client(*, backend: str | None = None) -> LlmBackend:
    """Resolve + return the shared client for the active backend (lazily
    constructed, one instance per kind for the process lifetime)."""
    from src.llm.ollama import OllamaClient
    from src.llm.vllm_client import VllmClient

    resolved = resolve_backend(override=backend)
    kind = resolved["backend"]
    if kind not in _clients:
        _clients[kind] = VllmClient() if kind == "vllm" else OllamaClient()
    return _clients[kind]  # type: ignore[return-value]


def _reset_clients_for_tests() -> None:
    _clients.clear()
