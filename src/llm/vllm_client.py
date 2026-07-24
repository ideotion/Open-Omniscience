"""
Local LLM access via vLLM's OpenAI-compatible server (HTTP only).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Section B1 of the 2026-07-24 field-feedback Session B (AI-stack rework): the
DUAL BACKEND ruled by the maintainer (A12) -- vLLM on GPU-equipped machines,
Ollama KEPT for the CPU-only fleet, never dropped, never a silent replacement.

vLLM is an EXTERNAL process (like Ollama): the app never imports it in-process
(torch stays banned from `pyproject.toml`'s core dependencies). This client only
speaks HTTP to a running server. VERIFIED FACTS this module relies on (checked
2026-07-24 -- PyPI is reachable in this sandbox, docs.vllm.ai/huggingface.co are
not, so verification stopped at what was reachable):
  * PyPI ``vllm`` package exists, latest version 0.25.1, ``requires-python
    <3.15,>=3.10`` (``https://pypi.org/pypi/vllm/json``).
  * The package's OWN description states "OpenAI-compatible API server" --
    ``/v1/chat/completions`` + ``/v1/models`` are the long-stable, documented
    surface (unchanged since early vLLM releases; this is well-established,
    not a guess).
Degrade LOUDLY (the project's honesty non-negotiable): if the vLLM server is
unreachable or the model is not loaded, raise -- never return a fabricated
"analysis".
"""

from __future__ import annotations

import os

import httpx

from src.llm.ollama import (
    GenerationResult,
    LLMError,
    LLMUnavailable,
    _is_loopback_url,
    _require_loopback,
)

# Default OpenAI-compatible port `vllm serve` binds to.
DEFAULT_VLLM_URL = "http://127.0.0.1:8000"


class VllmClient:
    """Thin, honest HTTP client for a local vLLM OpenAI-compatible server.

    Structurally interchangeable with ``OllamaClient`` (see ``src/llm/backend.py``'s
    ``LlmBackend`` protocol): ``generate`` / ``list_installed`` / ``is_available`` /
    ``close`` all match shape, so every existing consumer (bulk summarize/translate,
    the triage/tag runs, the law-change summaries) works against either backend
    unchanged once it is resolved through ``src.llm.backend.get_client()``.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 180.0,
        client: httpx.Client | None = None,
    ):
        resolved_url: str = base_url or os.getenv("OO_VLLM_URL") or DEFAULT_VLLM_URL
        self.base_url = resolved_url.rstrip("/")
        self.timeout = timeout
        # Enforce loopback only when WE open the socket (mirrors OllamaClient) — an
        # injected client (tests) may use a MockTransport with a non-loopback nominal
        # URL and never egress.
        if client is None:
            _require_loopback(self.base_url)
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    # -- network kill switch ----------------------------------------------- #

    def _check_kill_switch(self) -> None:
        """Refuse a vLLM call while airplane mode is engaged -- but only when the
        call would actually reach beyond the local machine (a genuinely non-loopback
        ``base_url``, the same defense-in-depth OllamaClient applies). A pure loopback
        inference call is airplane-safe: unlike Ollama's pull/remove, vLLM has no
        clearnet-egressing endpoint at all here (model downloads are a SEPARATE,
        explicitly consented step -- see ``src/llm/vllm_lifecycle.py``), so there is
        no analog of Ollama's ``clearnet=True`` unconditional refusal."""
        from src.ingest import kill_switch_active

        if not _is_loopback_url(self.base_url) and kill_switch_active():
            raise LLMUnavailable(
                "Network is OFF (airplane mode): refusing the vLLM request. "
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
        """The model(s) currently SERVED by this vLLM instance (``GET /v1/models``).

        Unlike Ollama, a vLLM server serves exactly the ONE model it was started
        with (``vllm serve <model>``) -- so this is a 0-or-1-element list, never a
        multi-model catalog. Raises LLMUnavailable if the server is down."""
        self._check_kill_switch()
        try:
            resp = self._client.get("/v1/models")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(
                f"vLLM not reachable at {self.base_url}: {exc}. Is the vllm server running?"
            ) from exc
        data = resp.json()
        return [m["id"] for m in (data.get("data") or []) if m.get("id")]

    def list_installed_detailed(self) -> list[dict]:
        """Mirrors ``OllamaClient.list_installed_detailed`` shape for the shared
        picker -- vLLM's ``/v1/models`` carries no size/date, so those are honestly
        ``None`` (never guessed)."""
        self._check_kill_switch()
        try:
            resp = self._client.get("/v1/models")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"vLLM not reachable at {self.base_url}: {exc}") from exc
        return [
            {"tag": m["id"], "size_gb": None, "modified": None}
            for m in (resp.json().get("data") or [])
            if m.get("id")
        ]

    # -- generation -------------------------------------------------------- #

    def generate(
        self,
        prompt: str,
        *,
        model: str = "",
        system: str | None = None,
        options: dict | None = None,  # noqa: ARG002 - signature parity with OllamaClient
        keep_alive: str | None = None,  # noqa: ARG002 - no vLLM analog; see note below
    ) -> GenerationResult:
        """Single-shot completion via ``POST /v1/chat/completions``.

        ``keep_alive``/``options`` are Ollama-specific knobs accepted here ONLY for
        signature parity with ``OllamaClient.generate`` (so a caller need not branch
        by backend) -- they have no vLLM analog (a served vLLM model stays resident
        for the server's whole lifetime; there is no per-call unload/reload), so they
        are silently ignored rather than raising or faking an effect.
        """
        self._check_kill_switch()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict = {"model": model, "messages": messages, "stream": False}
        try:
            resp = self._client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise LLMUnavailable(
                    f"Model {model!r} is not the model this vLLM server was started with."
                ) from exc
            raise LLMError(f"vLLM error for model {model!r}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"vLLM not reachable at {self.base_url}: {exc}") from exc
        data = resp.json()
        choices = data.get("choices") or []
        text = ""
        if choices:
            text = ((choices[0].get("message") or {}).get("content") or "").strip()
        usage = data.get("usage") or {}
        return GenerationResult(
            model=data.get("model") or model,
            text=text,
            prompt_eval_count=usage.get("prompt_tokens"),
            eval_count=usage.get("completion_tokens"),
            # vLLM's OpenAI-compatible response carries token USAGE, not Ollama's
            # nanosecond wall-clock timings. Honest None (never a fabricated rate) --
            # a consumer reading the *_duration fields must degrade gracefully (a
            # cost/ETA computation over these fields must treat None as "timing
            # unavailable on this backend", per B1.2).
            total_duration=None,
            load_duration=None,
            prompt_eval_duration=None,
            eval_duration=None,
        )

    def close(self) -> None:
        self._client.close()
