"""Backend ACTIVATION: bring a local backend up, on purpose, when the operator asks.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-08-04: "AI backend (ollama & vllm) won't start. Both seem to be
installed on my setup. Starting the local AI produces 'local model hiccup'."

Reproduced from the code, and the gap is structural rather than a bug in any one
place. THREE different questions about "which backend" already had answers here,
and the one this needed was missing:

  * ROUTING -- ``resolve_backend()``: who can serve THIS request right now. A
    stopped backend is correctly disqualified, because a stopped server 503s.
  * PROVISIONING -- ``provisioning_backend()``: what will this machine serve with
    ONCE SET UP, so a download lands where it will be used. Not-running-yet is the
    normal state there.
  * ACTIVATION -- this module: which backend should be STARTED, now, and can it
    actually be started.

Nothing answered the third. ``ollama_lifecycle.start()`` and
``vllm_lifecycle.start()`` both existed and both worked; no caller chose between
them. So "Start background AI" probed a backend nobody had started, found nothing,
and counted to ten -- the retry budget doing exactly what it was built to do,
against a condition no amount of retrying could change.

WHY THIS IS NOT A FOURTH PRECEDENCE RULE. It reuses ``provisioning_backend``'s
order verbatim (override, then what is already reachable, then installed-ness with
the GPU tie-break) because inventing a second ordering is how two surfaces start
disagreeing about the same machine. Activation adds exactly one constraint that
provisioning does not have: **you cannot start what is not installed**, so a
not-installed pick becomes a named blocker rather than a target.

"PREFER vLLM WHEN BOTH ARE INSTALLED" (maintainer, 2026-08-04) is implemented as
"prefer vLLM where vLLM can actually run" -- i.e. where a GPU is present, which is
the tie-break the shared rule already applies. That is not a weakening of the ask:
``vllm_lifecycle.start()`` REFUSES on a CPU-only machine by ruling, so preferring it
there would hand the operator a guaranteed failure instead of the Ollama daemon that
would have worked. The operator's own choice still wins outright, which is the other
half of the ask.

TWO REFUSALS THAT MATTER MORE THAN THE STARTS:

  * A vLLM server started on a model whose weights are NOT in the local cache
    fetches them from Hugging Face at startup -- several GB over the clear internet,
    from inside a subprocess this app's socket guard cannot see. ``start()`` has no
    such check (it has no reason to; it is not the consent layer). Activation is a
    one-click surface, so it refuses by name instead, and the operator downloads
    deliberately through the flow that asks.
  * Neither backend installed is not an error to retry -- it is a prerequisite to
    state.

Starting is otherwise ALLOWED under airplane mode, and that is the existing ruling
rather than an exception to it: both servers bind loopback, and loopback generate is
the permitted-offline half of the split that refuses pulls. Refusing to start the
thing that makes permitted offline inference possible would make the allowance
unusable exactly when it matters. The cache refusal above is what keeps that true.
"""

from __future__ import annotations

import logging

_LOG = logging.getLogger("llm.activation")

#: Backends this module knows how to bring up, in the order a payload lists them.
BACKENDS = ("vllm", "ollama")


def _candidates() -> dict:
    """Installed / running for BOTH backends, from each one's own lifecycle module.

    Read here rather than taken from ``resolve_backend`` because activation needs the
    facts for the backend it is NOT choosing too -- the payload names the alternative,
    so an operator who disagrees with the pick can see what else is available.
    """
    from src.llm import ollama_lifecycle, vllm_lifecycle

    out: dict = {}
    try:
        out["vllm"] = {
            "installed": bool(vllm_lifecycle.is_installed()),
            "running": bool(vllm_lifecycle.is_running()),
        }
    except Exception as exc:  # noqa: BLE001 - a probe must never break the plan
        out["vllm"] = {"installed": False, "running": False, "probe_error": str(exc)}
    try:
        out["ollama"] = {
            "installed": bool(ollama_lifecycle.is_installed()),
            "running": bool(ollama_lifecycle.is_running()),
        }
    except Exception as exc:  # noqa: BLE001
        out["ollama"] = {"installed": False, "running": False, "probe_error": str(exc)}
    return out


def _vllm_model() -> str:
    """The model a vLLM start would serve: the operator's stored choice, else the
    app's vLLM default. Never an Ollama tag -- the two backends consume different
    artifacts and a tag handed to vLLM is a guaranteed failure (the recorded
    ``active_model`` lesson)."""
    from src.api.llm import DEFAULT_VLLM_MODEL

    try:
        from src.config.app_settings import load_settings

        stored = (load_settings().llm_model_vllm or "").strip()
        if stored:
            return stored
    except Exception:  # noqa: BLE001 - a settings hiccup falls back to the default
        pass
    return DEFAULT_VLLM_MODEL


def activation_plan(*, override: str | None = None) -> dict:
    """WHICH backend to start, whether it can be started, and what stands in the way.

    Read-only: probes only, nothing is launched. Returns::

        {
          "backend": "vllm" | "ollama",
          "chosen_because": str,
          "running": bool,          # the chosen backend already answers
          "can_start": bool,        # a start would be attempted
          "blocker": str | None,    # why it would not be, in words
          "model": str | None,      # vLLM only -- what it would serve
          "candidates": {"vllm": {...}, "ollama": {...}},
          "override": str | None,
        }

    ``can_start`` is False whenever ``running`` is True: there is nothing to start.
    A caller that wants "make it serve" should read ``running or can_start``.
    """
    from src.llm.backend import provisioning_backend, resolve_backend

    chosen_override = (override or "").strip().lower() or None
    if chosen_override not in {"ollama", "vllm", None}:
        chosen_override = None

    resolved = resolve_backend(override=chosen_override)
    pick = provisioning_backend(resolved)
    cands = _candidates()
    out = _plan_for(pick["backend"], pick["chosen_because"], cands, chosen_override)

    # FALL BACK TO THE OTHER BACKEND WHEN THE PREFERRED ONE CANNOT START.
    #
    # An explicit choice is never second-guessed, so this only applies to "auto". But
    # under auto, refusing outright when the OTHER backend would work is a real
    # regression: a GPU machine with vLLM installed-but-weights-not-fetched and a
    # perfectly good Ollama would get nothing at all, where it used to get Ollama.
    # (The browser's old hand-rolled pill logic had this fallback; the property is
    # pinned in tests/test_ai_pill_starts_the_backend.py, which is what caught its
    # loss when the decision moved server-side.)
    #
    # The preferred backend's blocker is CARRIED, not discarded -- the operator should
    # still learn that their vLLM needs weights, rather than silently getting the
    # slower backend and wondering why.
    if not chosen_override and not out["running"] and not out["can_start"]:
        other = "ollama" if out["backend"] == "vllm" else "vllm"
        alt = _plan_for(other, f"{out['backend']} cannot start here", cands, None)
        if alt["running"] or alt["can_start"]:
            alt["fell_back_from"] = {"backend": out["backend"], "blocker": out["blocker"]}
            alt["chosen_because"] = (
                f"{out['backend']} was preferred but cannot start ({out['blocker']}), "
                f"so {other} serves instead"
            )
            return alt
    return out


def _plan_for(
    backend: str, chosen_because: str, cands: dict, chosen_override: str | None
) -> dict:
    """Can THIS backend be started, and what stands in the way. The per-backend half of
    :func:`activation_plan`, split out so the fallback path asks the same question of
    the alternative instead of a looser version of it."""
    mine = cands.get(backend) or {"installed": False, "running": False}

    out: dict = {
        "backend": backend,
        "chosen_because": chosen_because,
        "running": bool(mine.get("running")),
        "can_start": False,
        "blocker": None,
        "model": None,
        "candidates": cands,
        "override": chosen_override,
    }

    if out["running"]:
        out["blocker"] = None
        return out

    if not mine.get("installed"):
        other = "ollama" if backend == "vllm" else "vllm"
        alt = cands.get(other) or {}
        extra = (
            f" {other} is installed and could be started instead."
            if alt.get("installed")
            else " Neither backend is installed yet."
        )
        out["blocker"] = (
            f"{backend} is not installed on this machine, so there is nothing to "
            f"start.{extra}"
        )
        return out

    if backend == "vllm":
        model = _vllm_model()
        out["model"] = model
        cached = None
        try:
            from src.llm.vllm_lifecycle import model_cache_state

            cached = model_cache_state(model).get("cached")
        except Exception as exc:  # noqa: BLE001 - an unreadable cache is not a "no"
            _LOG.info("vLLM model cache probe failed: %s", exc)
            cached = None
        if cached is False:
            # NOT a start we are willing to make on one click: vLLM would fetch the
            # weights from Hugging Face itself, in a subprocess outside this app's
            # socket guard. Downloading several GB is a decision, not a side effect.
            out["blocker"] = (
                f"{model} is not in the local model cache. Starting vLLM now would "
                "make it download the weights from Hugging Face over the clear "
                "internet, from a process this app cannot route through Tor -- so "
                "download the model first, deliberately, and then start the server."
            )
            return out
        # cached is None -> the cache could not be read. Allowed: refusing on a failed
        # probe would block a machine whose weights are present but whose cache dir we
        # cannot stat, and the start itself reports honestly either way.

    out["can_start"] = True
    return out


def ensure_running(
    *,
    override: str | None = None,
    wait: bool = True,
    timeout: float | None = None,
) -> dict:
    """Make a local backend serve, starting one if that is what it takes.

    Idempotent by probe: an already-reachable backend is reported as such and nothing
    is spawned. Never raises for an ordinary refusal -- a blocker comes back in the
    payload with ``started: False`` and a reason, because the caller is a UI click and
    an exception there becomes a stack trace where a sentence belongs.

    ``ready`` is the only field that claims the backend is actually answering. A start
    that spawned but has not come up yet reports ``started: True, ready: False`` with
    the lifecycle's own note -- a model load takes tens of seconds and calling that
    "ready" is the fabrication both lifecycle modules already refuse to make.
    """
    plan = activation_plan(override=override)
    backend = plan["backend"]
    out = dict(plan)
    out["started"] = False
    out["ready"] = bool(plan["running"])

    if plan["running"]:
        out["detail"] = f"{backend} is already running."
        return out
    if not plan["can_start"]:
        out["detail"] = plan["blocker"] or "this backend cannot be started right now"
        return out

    try:
        if backend == "vllm":
            from src.llm.vllm_lifecycle import start as vllm_start

            res = vllm_start(plan["model"])
            # vLLM's start returns as soon as Popen succeeds -- the engine then loads
            # for tens of seconds. Its own start_outcome() is the tri-state that tells
            # ready from still-loading from already-dead; do not guess here.
            out["started"] = bool(res.get("started"))
            out["ready"] = False
            out["detail"] = (
                f"vLLM is starting on {plan['model']}. A model load takes tens of "
                "seconds; the backend reports when it is answering."
                if out["started"]
                else str(res.get("reason") or "vLLM was not started")
            )
            if not out["started"] and res.get("reason") == "already running":
                out["ready"] = True
            out["log_path"] = res.get("log_path")
        else:
            from src.llm.ollama_lifecycle import start as ollama_start

            kw: dict = {"wait": wait}
            if timeout is not None:
                kw["timeout"] = timeout
            res = ollama_start(**kw)
            out["started"] = bool(res.get("started"))
            out["ready"] = bool(res.get("ready")) or res.get("reason") == "already running"
            out["detail"] = str(
                res.get("note")
                or res.get("reason")
                or ("Ollama is running." if out["ready"] else "Ollama was launched.")
            )
    except Exception as exc:  # noqa: BLE001 - a launch failure is a sentence, not a 500
        out["started"] = False
        out["ready"] = False
        out["detail"] = str(exc)
        out["error"] = True
        _LOG.info("activation of %s failed: %s", backend, exc)
    return out
