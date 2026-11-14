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
2026-07-25 -- PyPI is reachable in this sandbox, docs.vllm.ai/huggingface.co are
not, so verification stopped at what was reachable):
  * PyPI ``vllm`` package exists, latest version 0.26.0, ``requires-python
    <3.15,>=3.10`` (``https://pypi.org/pypi/vllm/json``). Every recent release
    ships ONLY `manylinux` wheels for x86_64/aarch64 -- no macOS or Windows
    wheel at any version (``src.llm.vllm_lifecycle.platform_support()``).
  * The package's OWN description states "OpenAI-compatible API server" --
    ``/v1/chat/completions`` + ``/v1/models`` are the long-stable, documented
    surface (unchanged since early vLLM releases; this is well-established,
    not a guess).
Degrade LOUDLY (the project's honesty non-negotiable): if the vLLM server is
unreachable or the model is not loaded, raise -- never return a fabricated
"analysis".
"""

from __future__ import annotations

import logging
import os

import httpx

from src.llm.ollama import (
    GenerationResult,
    LLMError,
    LLMUnavailable,
    _http_error_text,
    _is_loopback_url,
    _require_loopback,
)
from src.monitoring.secret_scrub import record_text

_LOG = logging.getLogger(__name__)

#: ``owned_by`` values on ``/v1/models`` that name a proxy to a hosted API, not a model running here (R688). LiteLLM and
#: other OpenAI-compatible proxies report ``openai``; vLLM says ``vllm``, llama.cpp ``llamacpp``.
_RELAY_OWNERS = frozenset({"openai", "litellm"})

#: The sentence the person reads when the vLLM address is a proxy (keyed in every locale).
RELAY_REFUSAL = (
    "The server at the vLLM address lists its models as owned by OpenAI or LiteLLM, which is how a proxy to an online "
    "service describes itself, so it is refused: the text you give it could leave the machine. Point the vLLM address at "
    "a model running on this computer."
)

#: The app's own listening port (``main.py`` reads ``OO_PORT``, default 8000).
#: Duplicated as a literal rather than imported so this module keeps no import
#: edge into the API layer; the invariant test pins the two together.
_APP_PORT_ENV = "OO_PORT"
_APP_PORT_FALLBACK = 8000


def default_vllm_port() -> int:
    """The port ``vllm serve`` should bind — DERIVED so it can never be the app's.

    FIELD REPORT 2026-08-02 ("installing vLLM on a new machine fails"). This was
    a flat ``8000`` — the SAME port the app itself serves on. The consequences,
    both reproduced:

    * ``vllm serve`` could never bind it: ``OSError(98) Address already in use``.
      The server therefore never started on ANY machine that got as far as a
      successful install. It stayed latent only because no machine had one.
    * The health probe then asked *the app* whether it was vLLM. The app has no
      ``/v1/models`` route, so it answered **404** — 270 of them in one session
      in the field bundle — and ``is_running()`` read that as "vLLM is down"
      rather than "something else owns this port".

    Deriving from ``OO_PORT`` rather than hardcoding 8001 keeps the two apart
    even when the operator moves the app: a collision cannot be reintroduced by
    configuration. ``OO_VLLM_PORT`` still overrides explicitly."""
    explicit = os.getenv("OO_VLLM_PORT")
    if explicit:
        try:
            port = int(explicit)
        except ValueError:
            port = 0
        if 1 <= port <= 65535:
            return port
        # A malformed override must not silently reinstate the collision.
        _LOG.warning("ignoring malformed OO_VLLM_PORT=%r; deriving instead", explicit)
    try:
        app_port = int(os.getenv(_APP_PORT_ENV, str(_APP_PORT_FALLBACK)))
    except ValueError:
        app_port = _APP_PORT_FALLBACK
    if not (1 <= app_port <= 65534):
        app_port = _APP_PORT_FALLBACK
    return app_port + 1


def default_vllm_url() -> str:
    """Base URL for the local vLLM server. Computed per call, never frozen at
    import: a module constant captured whatever ``OO_PORT`` happened to be when
    this module was first imported, which is exactly how the client and the
    server can end up disagreeing about where vLLM lives."""
    return f"http://127.0.0.1:{default_vllm_port()}"


#: Back-compat alias. Prefer :func:`default_vllm_url` — this is evaluated at
#: import time and so cannot see a later ``OO_PORT``/``OO_VLLM_PORT`` change.
DEFAULT_VLLM_URL = default_vllm_url()

# -- sampling-option mapping ----------------------------------------------- #
#
# Ollama takes sampling knobs in an ``options`` dict; the OpenAI-compatible
# chat-completions body takes them as TOP-LEVEL fields under different names.
# Before 2026-07-31 this client accepted ``options`` purely for signature parity
# and dropped it on the floor, so a caller asking for ``temperature: 0`` got the
# server's default sampling and never learned otherwise -- a silent determinism
# bug on exactly the backend the GPU path uses.
#
# ONLY EXACT EQUIVALENTS ARE MAPPED. A knob whose meaning differs between the two
# APIs is dropped and reported, never approximated: a silently-approximated
# sampling parameter changes generation in a way the caller did not ask for, which
# is worse than an absent one.
#
# The mapped set is deliberately the OpenAI chat-completions SPEC subset, so it is
# safe against any OpenAI-compatible server rather than only vLLM. (docs.vllm.ai is
# not reachable from this sandbox -- the same limitation this module's header
# already records -- so vLLM-only extensions such as ``top_k`` and
# ``repetition_penalty`` are deliberately NOT sent: they are outside the spec and
# would 400 on a strict server. They are listed in ``_DROPPED_REASONS`` so the
# omission is stated rather than silent.)
_OPTION_TO_OPENAI: dict[str, str] = {
    "temperature": "temperature",
    "top_p": "top_p",
    "seed": "seed",
    "stop": "stop",
    "presence_penalty": "presence_penalty",
    "frequency_penalty": "frequency_penalty",
}

# Ollama's ``num_predict`` is "max tokens to GENERATE" == OpenAI's ``max_tokens``,
# but Ollama overloads negatives (-1 unlimited, -2 fill context) which have no
# OpenAI spelling -- so a negative is dropped rather than sent as a bogus bound.
_NUM_PREDICT = "num_predict"

_DROPPED_REASONS: dict[str, str] = {
    "repeat_penalty": (
        "Ollama's repeat_penalty and OpenAI's frequency_penalty use different "
        "formulations and ranges; mapping one onto the other would change sampling"
    ),
    "repeat_last_n": "no OpenAI chat-completions equivalent",
    "num_ctx": "vLLM fixes context length at server start (--max-model-len), not per request",
    "mirostat": "no OpenAI chat-completions equivalent",
    "mirostat_eta": "no OpenAI chat-completions equivalent",
    "mirostat_tau": "no OpenAI chat-completions equivalent",
    "tfs_z": "no OpenAI chat-completions equivalent",
    "typical_p": "no OpenAI chat-completions equivalent",
    "top_k": "outside the OpenAI chat-completions spec; a strict server rejects it",
    "repetition_penalty": "outside the OpenAI chat-completions spec; a strict server rejects it",
}


def openai_sampling_params(options: dict | None) -> tuple[dict, list[str]]:
    """Map Ollama-style ``options`` onto OpenAI-compatible sampling parameters.

    Pure and side-effect free, so the mapping is unit-testable without a running
    vLLM server (the whole point: the bug it fixes was invisible to every test
    because no test could reach a server).

    Returns ``(params, dropped)`` -- the body fields to merge into the request, and
    the option names that were NOT sent. ``dropped`` is what makes the omission
    honest: the caller (and the log) can see exactly which knobs did not apply,
    instead of assuming all of them did.

    ``temperature: 0`` maps to ``temperature: 0`` -- note it must survive the
    falsiness trap: a plain ``if value:`` test would drop precisely the value a
    determinism-seeking caller cares most about.
    """
    if not options:
        return {}, []
    params: dict = {}
    dropped: list[str] = []
    for key, value in options.items():
        if value is None:  # "unset", not "set to nothing"
            continue
        if key in _OPTION_TO_OPENAI:
            params[_OPTION_TO_OPENAI[key]] = value
        elif key == _NUM_PREDICT:
            # Ollama's negative sentinels have no OpenAI spelling; omitting
            # max_tokens IS "no explicit bound", which is what -1 means.
            if isinstance(value, int) and value >= 0:
                params["max_tokens"] = value
            else:
                dropped.append(key)
        else:
            dropped.append(key)
    return params, dropped


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
        # default_vllm_url() per call, not the import-time constant: the port is
        # derived from OO_PORT, and freezing it at import is how the client ends
        # up probing a different address than the one the server was told to bind.
        resolved_url: str = base_url or os.getenv("OO_VLLM_URL") or default_vllm_url()
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
                f"vLLM not reachable at {self.base_url}: {record_text(exc)}. Is the vllm server running?"
            ) from exc
        data = resp.json()
        return [m["id"] for m in (data.get("data") or []) if m.get("id")]

    def served_window(self) -> int | None:
        """Tokens the RUNNING server will actually accept, or None if unreadable.

        vLLM's model card on ``GET /v1/models`` carries ``max_model_len`` -- the window
        the engine was started with. We were already calling this endpoint twice and
        keeping only ``id``, while a caller that needed the window RE-DERIVED it from
        free VRAM (``coverage._resolve_window``) and labelled the result "derived from
        VRAM at start". It was not: it re-ran the estimate against the card as it is
        NOW, and once vLLM is running it has claimed most of that card, so the reading
        describes a different machine state than the server holds. Two numbers for one
        quantity, and the one that governs is the server's.

        None on an unreachable server or a card without the field -- never a guess, and
        the caller keeps its derivation as the fallback.
        """
        self._check_kill_switch()
        try:
            resp = self._client.get("/v1/models")
            resp.raise_for_status()
            for m in resp.json().get("data") or []:
                n = m.get("max_model_len")
                if isinstance(n, int) and n > 0:
                    return n
        except Exception:  # noqa: BLE001 - advisory read; the caller degrades honestly
            return None
        return None

    def list_installed_detailed(self) -> list[dict]:
        """Mirrors ``OllamaClient.list_installed_detailed`` shape for the shared
        picker -- vLLM's ``/v1/models`` carries no size/date, so those are honestly
        ``None`` (never guessed)."""
        self._check_kill_switch()
        try:
            resp = self._client.get("/v1/models")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"vLLM not reachable at {self.base_url}: {record_text(exc)}") from exc
        return [
            {"tag": m["id"], "size_gb": None, "modified": None}
            for m in (resp.json().get("data") or [])
            if m.get("id")
        ]

    # -- what the server says it is (R671, R688) ---------------------------- #

    def server_kind(self, model: str = "") -> str:
        """What the server at ``base_url`` says it is: ``"ollama"``, ``"relay"``, ``"vllm"`` or ``"other"``.

        * ``"ollama"``: it answers ``/api/tags`` with a model list (an Ollama daemon, which forwards cloud models);
        * ``"relay"``: any card on ``/v1/models`` names an owner that identifies a proxy to a hosted API
          (:data:`_RELAY_OWNERS`: LiteLLM and other OpenAI proxies say ``openai``);
        * ``"vllm"``: every such card says ``owned_by: "vllm"``, as vLLM's own model card does;
        * ``"other"``: anything else, including a model list it cannot read -- llama.cpp, LM Studio and similar local
          servers, which this app cannot see into.

        Raises :class:`LLMUnavailable` when the server does not answer at all, or answers ``/api/tags`` with a 5xx.
        """
        return self._identify(model)[0]

    def _identify(self, model: str) -> tuple[str, list]:
        """:meth:`server_kind`, plus the Ollama model list it read (empty for any other kind), so the check that
        follows judges the same answer rather than asking twice."""
        try:
            tags = self._client.get("/api/tags")
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"vLLM not reachable at {self.base_url}: {record_text(exc)}. Is the vllm server running?") from exc
        if tags.is_success:
            try:
                body = tags.json()
            except ValueError:
                body = None  # not JSON at all (a catch-all page): this path is not an Ollama model list
            if isinstance(body, dict) and isinstance(body.get("data"), list):
                # llama.cpp's llama-server answers /api/tags with its OpenAI model list beside an Ollama-style one
                # ("models" AND "data"); Ollama's own answer has no "data". It is judged by its cards below.
                body = None
            elif isinstance(body, dict) and "error" in body and "models" not in body:
                # LM Studio answers an unknown route with 200 and {"error": "Unexpected endpoint ..."}: not a model
                # list of any kind, so the server is judged by its /v1/models cards below.
                body = None
            if body is not None:
                listed = body.get("models") if isinstance(body, dict) else None
                if isinstance(listed, list):
                    return "ollama", listed
                # JSON on Ollama's own path that is not Ollama's shape: whatever answers there is imitating it, and
                # passing it as "other" would let a shim in front of a daemon carry a cloud model through.
                raise LLMUnavailable(f"The server at {self.base_url} answered its model list in a shape this app cannot read, so no text is sent to it.")
        elif tags.status_code >= 500:
            # Something serves that path and failed: an Ollama daemon mid-restart reads this way, and passing it as
            # "other" would send text to the one server known to forward cloud models. vLLM and the local servers
            # answer 404 there.
            raise LLMUnavailable(f"The server at {self.base_url} failed to list its models, so no text is sent to it.")
        try:
            resp = self._client.get("/v1/models")
        except httpx.HTTPError as exc:
            # A server that answered /api/tags and then cannot answer its own model list is failing, not identified:
            # a proxy whose upstream is down reads this way while its chat route still works.
            raise LLMUnavailable(f"The server at {self.base_url} did not answer its model list, so no text is sent to it.") from exc
        if resp.status_code >= 500:
            raise LLMUnavailable(f"The server at {self.base_url} failed to list its models, so no text is sent to it.")
        try:
            resp.raise_for_status()  # a 404 or 401 (vLLM started with --api-key) leaves the server unidentified
            cards = resp.json().get("data")
        except (httpx.HTTPError, ValueError, AttributeError):
            return "other", []
        cards = [c for c in (cards if isinstance(cards, list) else []) if isinstance(c, dict)]
        def owner(c: dict) -> str:
            return str(c.get("owned_by") or "").strip().lower()

        # Being a proxy is a property of the server, so ANY card naming a relay owner marks it, whichever model is asked.
        if any(owner(c) in _RELAY_OWNERS for c in cards):
            return "relay", []
        named = [c for c in cards if not model or c.get("id") == model]
        if named and all(owner(c) == "vllm" for c in named):
            return "vllm", []
        return "other", []

    def _require_local_server(self, model: str) -> None:
        """Refuse to send text to a server KNOWN to relay it off this computer (R688, as amended).

        A loopback URL proves only that the first hop is local. Ollama serves the same OpenAI-compatible
        ``/v1/chat/completions`` and forwards a cloud model, or a local alias of one, to ollama.com from its own process
        (R671); a proxy such as LiteLLM forwards everything to a hosted API. So, before every generation:

        * a cloud-suffixed name is refused with no request at all;
        * an Ollama daemon (it answers ``/api/tags`` with a model list) must list the model with no remote field, exactly
          as ``OllamaClient`` requires;
        * a server whose model card names a proxy owner (:data:`_RELAY_OWNERS`) is refused;
        * vLLM, and any other local OpenAI-compatible server (llama.cpp, LM Studio and the like), is used as before. For
          the latter Settings shows a caveat (``vllm_lifecycle.status``'s ``server_kind``), because the app cannot see
          whether it sends text elsewhere. The stricter rule -- only a server that says it is vLLM -- is the operator's
          choice to ask for, not ours to impose on a working private setup.

        WHAT IT CANNOT SEE. It reads the server's description of itself. A loopback relay that passes the real answers
        through (``ssh -L`` to a GPU box, an nginx or socat relay, a vLLM router in front of remote workers) is
        indistinguishable from the server behind it, and its traffic leaves from a process this app's socket guard does
        not see. ``owned_by`` is a label anyone can write, and a proxy that hides Ollama's ``/api/tags`` (or adds a
        ``data`` list to it, as llama.cpp's answer carries) reads as "other". The llama.cpp and LM Studio shapes of
        ``/api/tags`` are recognised from their published behaviour, not from a live server. Between these reads and the request that follows, another server could take the port. What this closes
        is the plain case: ``OO_VLLM_URL`` or ``OO_VLLM_PORT`` set to an Ollama daemon carrying a cloud model, or to a
        proxy that says it is one.

        At most two loopback reads per generation, next to a generation that takes seconds.
        """
        from src.llm.ollama import RemoteModelRefused
        from src.llm.remote_models import REFUSAL, is_cloud_name, local_entry

        if is_cloud_name(model):
            raise RemoteModelRefused(f"{REFUSAL} ({model!r})")
        kind, models = self._identify(model)
        if kind == "relay":
            raise RemoteModelRefused(RELAY_REFUSAL)  # the exact string, so the UI can translate it
        if kind != "ollama":
            return
        verdict, _entry = local_entry(model, models)
        if verdict == "cloud":
            raise RemoteModelRefused(f"{REFUSAL} ({model!r})")
        if verdict == "missing":
            raise LLMUnavailable(f"Model {model!r} is not installed on the Ollama server at {self.base_url}.")

    # -- generation -------------------------------------------------------- #

    def generate(
        self,
        prompt: str,
        *,
        model: str = "",
        system: str | None = None,
        options: dict | None = None,
        keep_alive: str | None = None,  # noqa: ARG002 - no vLLM analog; see note below
    ) -> GenerationResult:
        """Single-shot completion via ``POST /v1/chat/completions``.

        ``options`` carries Ollama-style sampling knobs and IS honoured here, mapped
        onto their OpenAI-compatible spellings by :func:`openai_sampling_params`
        (``temperature``, ``top_p``, ``seed``, ``stop``, the two penalties, and
        ``num_predict`` -> ``max_tokens``). Knobs with no exact equivalent are
        dropped and logged rather than approximated -- see ``_DROPPED_REASONS``.
        Until 2026-07-31 the whole dict was discarded for "signature parity", so a
        caller requesting ``temperature: 0`` silently got the server's default
        sampling; that made any determinism claim false on the GPU backend.

        ``keep_alive`` genuinely has no vLLM analog -- a served vLLM model stays
        resident for the server's whole lifetime, with no per-call unload/reload --
        so it is still accepted for signature parity and ignored.
        """
        self._check_kill_switch()
        self._require_local_server(model)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict = {"model": model, "messages": messages, "stream": False}
        sampling, dropped = openai_sampling_params(options)
        payload.update(sampling)
        if dropped:
            _LOG.debug(
                "vLLM: %d sampling option(s) not sent (%s); reasons: %s",
                len(dropped),
                ", ".join(sorted(dropped)),
                "; ".join(
                    f"{k}: {_DROPPED_REASONS.get(k, 'no OpenAI chat-completions equivalent')}"
                    for k in sorted(dropped)
                ),
            )
        # Counted at the SEAM (see src/llm/inflight.py): the pill's "working" state is
        # a fact about inference actually running, not an enumeration of the callers
        # that might be running some.
        from src.llm.inflight import generating

        try:
            with generating(model, backend="vllm"):
                resp = self._client.post("/v1/chat/completions", json=payload)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise LLMUnavailable(
                    f"Model {model!r} is not the model this vLLM server was started with."
                ) from exc
            raise LLMError(f"vLLM error for model {model!r}: {_http_error_text(exc)}") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"vLLM not reachable at {self.base_url}: {record_text(exc)}") from exc
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
