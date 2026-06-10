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

import os
from dataclasses import dataclass

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
    {"tag": "llama3.2:1b", "size": "~1.3 GB", "min_ram_gb": 4, "note": "smallest; very low-spec"},
    {"tag": "llama3.2:3b", "size": "~2 GB", "min_ram_gb": 8, "note": "balanced default"},
    {"tag": "gemma2:2b", "size": "~1.6 GB", "min_ram_gb": 6, "note": "small, fast"},
    {"tag": "qwen2.5:3b", "size": "~2 GB", "min_ram_gb": 8, "note": "strong multilingual"},
    {"tag": "phi3:mini", "size": "~2.3 GB", "min_ram_gb": 8, "note": "reasoning-leaning"},
]
DEFAULT_MODEL = os.getenv("OO_LLM_MODEL", "llama3.2:3b")


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
        out.append({**m, "fit": fit})
    return out


class LLMError(Exception):
    """Base class for LLM failures."""


class LLMUnavailable(LLMError):
    """Ollama is unreachable, or the requested model is not installed."""


@dataclass
class GenerationResult:
    model: str
    text: str
    prompt_eval_count: int | None = None
    eval_count: int | None = None


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
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    # -- availability ------------------------------------------------------ #

    def is_available(self) -> bool:
        try:
            self.list_installed()
            return True
        except LLMUnavailable:
            return False

    def list_installed(self) -> list[str]:
        """Return installed model tags, or raise LLMUnavailable if Ollama is down."""
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
    ) -> GenerationResult:
        """Single-shot completion. Raises LLMUnavailable if Ollama/model is absent."""
        payload: dict = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
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
        )

    def close(self) -> None:
        self._client.close()
