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
    {"tag": "granite4:350m", "size": "~0.3 GB", "min_ram_gb": 4, "note": "IBM Granite 4.0 — tiny (350M); simple tasks"},
    {"tag": "gemma3:1b", "size": "~0.8 GB", "min_ram_gb": 4, "note": "Google Gemma 3 — small & fast (1B)"},
    {"tag": "llama3.2:1b", "size": "~1.3 GB", "min_ram_gb": 4, "note": "Meta Llama 3.2 — smallest; very low-spec"},
    {"tag": "llama3.2:3b", "size": "~2 GB", "min_ram_gb": 8, "note": "Meta Llama 3.2 — balanced default"},
    {"tag": "granite4:micro", "size": "~2.1 GB", "min_ram_gb": 8, "note": "IBM Granite 4.0 — latest small (3.4B, hybrid)"},
    {"tag": "nemotron-mini", "size": "~2.7 GB", "min_ram_gb": 8, "note": "NVIDIA Nemotron Mini (4B)"},
    {"tag": "gemma3:4b", "size": "~3.3 GB", "min_ram_gb": 8, "note": "Google Gemma 3 (4B)"},
    {"tag": "mistral:7b", "size": "~4.4 GB", "min_ram_gb": 8, "note": "Mistral 7B (Apache-2.0)"},
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


def _require_loopback(url: str) -> None:
    """Refuse a non-loopback Ollama URL (privacy: LLM egress must stay on the machine).

    Inference is fully local by design; ``OO_OLLAMA_URL`` pointing at a remote host
    would silently send corpus text off the machine. Allow only loopback hosts so a
    misconfiguration fails loudly instead of leaking. (Skipped when a client is
    injected — tests drive an in-memory MockTransport with no real egress.)
    """
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if host in {"localhost", "::1"} or host.startswith("127."):
        return
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

    def _check_kill_switch(self) -> None:
        """Refuse any Ollama call while the global kill switch (airplane mode) is engaged.

        Ollama is loopback-only, but airplane mode means the operator wants NO
        connections at all — honour it for the LLM path too (defense in depth; it
        also blocks a misconfigured non-loopback URL slipping through an injected
        client). Degrade LOUDLY — never a fabricated answer.
        """
        from src.ingest import kill_switch_active

        if kill_switch_active():
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
    ) -> GenerationResult:
        """Single-shot completion. Raises LLMUnavailable if Ollama/model is absent."""
        self._check_kill_switch()
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

    def pull(self, model: str):
        """Pull (download + install) a model via the local Ollama process, STREAMING
        Ollama's own progress objects (yields dicts) — honest real progress, never a
        fabricated bar (invariant #20). Respects the kill switch.

        NOTE ON TRANSPORT (maintainer Q9, 2026-06-16): the pull egresses through the
        Ollama PROCESS over CLEARNET, NOT the app's Tor proxy/guarded factory — so
        airplane+Tor do not cover it. Airplane mode (the kill switch) still refuses it
        here; the UI must DISCLOSE the clearnet egress at consent."""
        self._check_kill_switch()
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
        self._check_kill_switch()
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
