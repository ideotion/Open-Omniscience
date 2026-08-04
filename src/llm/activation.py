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
import time

_LOG = logging.getLogger("llm.activation")

#: Backends this module knows how to bring up, in the order a payload lists them.
BACKENDS = ("vllm", "ollama")

#: How long :func:`ensure_running` WATCHES a freshly spawned vLLM before it is willing
#: to call the start "under way".
#:
#: A model load takes tens of seconds and no button click may wait for that -- but the
#: startup failures that matter here are FAST. A port collision, a CUDA/driver init
#: error, a missing or gated repo and an import error all kill the child within a second
#: or two, and every one of those used to be indistinguishable from a healthy load.
#: So: watch briefly, report an exit as an exit, and report anything still alive at the
#: end of the window as still loading -- which is the truth and not a hedge.
#:
#: Deliberately SHORT, because the window is not the only thing that catches a death:
#: :func:`activation_plan` reports the same tri-state on every read, so the card's own
#: re-polling catches a CUDA OOM forty seconds in, which no click-time watch could.
#: This one exists so an INSTANT death is answered by the click that caused it.
_VLLM_CONFIRM_S = 3.0
_VLLM_CONFIRM_STEP_S = 0.25

#: How much of the server log an exited start carries back. The HEAD, deliberately:
#: vLLM's EngineCore is a CHILD of the API server, so a startup failure prints its
#: traceback FIRST and the parent's stack (ending "See root cause above") follows it.
_LOG_EXCERPT_CHARS = 700


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
            out = alt

    # WHAT BECAME OF THE LAST START, on every read. The click-time watch can only see a
    # death inside its own few seconds; a CUDA OOM forty seconds into a model load is
    # just as fatal and used to leave the card saying "starting" forever. Reported as
    # INFORMATION, never as a blocker: the operator must be able to fix the cause and
    # press the button again, and a state that latched until the next successful start
    # would make the button refuse the very retry that would work.
    if not out["running"]:
        last = _last_start_failure()
        if last:
            out["last_start"] = last
    return out


def _last_start_failure() -> dict | None:
    """The last vLLM spawn IN THIS PROCESS, when it exited -- with the head of its log.

    None for every other state (never started here, still loading, answering): only a
    death has something to report, and reporting anything else would put a permanent
    notice on a card that is working fine.
    """
    try:
        from src.llm.vllm_lifecycle import start_outcome

        outcome = start_outcome()
    except Exception as exc:  # noqa: BLE001 - a probe must never break the plan
        _LOG.info("vLLM start-outcome probe failed: %s", exc)
        return None
    if outcome.get("state") != "exited":
        return None
    out = {
        "backend": "vllm",
        "returncode": outcome.get("returncode"),
        "detail": str(outcome.get("detail") or ""),
        "log_hint": str(outcome.get("log_hint") or ""),
        "log_path": outcome.get("log_path"),
    }
    if head := _server_log_head():
        out["server_log_head"] = head
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
        state: dict = {}
        try:
            from src.llm.vllm_lifecycle import model_cache_state

            state = model_cache_state(model) or {}
        except Exception as exc:  # noqa: BLE001 - an unreadable cache is not a "no"
            _LOG.info("vLLM model cache probe failed: %s", exc)
        cached = state.get("cached")
        if cached and state.get("location") == "legacy":
            # PRESENT, but not where the server will look. Starting now would make vLLM
            # re-download several GB it already has, which is the same egress the
            # refusal below exists to prevent -- so it is refused for the same reason,
            # and told apart from "you never downloaded it", which is what an operator
            # in this state used to be told.
            out["blocker"] = (
                f"{model} IS downloaded — at {state.get('path')} — but the server is "
                "started pointed at the app's own model folder, so it would fetch the "
                "weights again over the clear internet. Move that cache to "
                "Settings → AI's configured path (or set HF_HOME back to the old one), "
                "and nothing has to be downloaded twice."
            )
            return out
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


def _confirm_vllm_start(
    *,
    grace: float = _VLLM_CONFIRM_S,
    step: float = _VLLM_CONFIRM_STEP_S,
    sleep=time.sleep,
) -> dict:
    """Watch a just-spawned vLLM long enough to tell a load from a death.

    ``vllm_lifecycle.start_outcome()`` is the tri-state that already answers this --
    ``starting`` / ``ready`` / ``exited`` -- and it was built for exactly this failure
    (field report 2026-08-02: a server that had already exited, polled ten times). This
    module's own comment said "do not guess here" and then guessed anyway: it took
    ``Popen`` succeeding as the start succeeding, so a child that died two seconds later
    was reported as ``started: True``, the coordinator's gate accepted it, and the sweep
    spent its whole retry budget on a server that was never coming.

    Returns as soon as the state is decided; only a still-``starting`` child runs the
    window down. ``sleep`` is injected so tests never spend real seconds.
    """
    from src.llm.vllm_lifecycle import start_outcome

    out = start_outcome()
    waited = 0.0
    while out.get("state") == "starting" and waited < grace:
        sleep(step)
        waited += step
        out = start_outcome()
    return out


def _server_log_head(limit: int = _LOG_EXCERPT_CHARS) -> str:
    """The FIRST bytes of the last vLLM server log, or "" if there is nothing to read.

    ``server_log_tail`` keeps both ends: ``head`` when the file was truncated, and a
    whole ``tail`` when it fits -- whose start IS the head. Either way the beginning of
    the file is what a startup failure needs (see :data:`_LOG_EXCERPT_CHARS`).
    """
    try:
        from src.llm.vllm_lifecycle import server_log_tail

        log = server_log_tail()
        if not log.get("available"):
            return ""
        return str(log.get("head") or log.get("tail") or "").strip()[:limit]
    except Exception as exc:  # noqa: BLE001 - an unreadable log must not mask the exit
        _LOG.info("could not read the vLLM server log: %s", exc)
        return ""


def ensure_running(
    *,
    override: str | None = None,
    wait: bool = True,
    timeout: float | None = None,
    confirm: dict | None = None,
) -> dict:
    """Make a local backend serve, starting one if that is what it takes.

    Idempotent by probe: an already-reachable backend is reported as such and nothing
    is spawned. Never raises for an ordinary refusal -- a blocker comes back in the
    payload with ``started: False`` and a reason, because the caller is a UI click and
    an exception there becomes a stack trace where a sentence belongs.

    ``ready`` is the only field that claims the backend is actually answering, and
    ``started`` now claims only what it can: a process was spawned AND was still alive
    when we last looked. A vLLM whose engine dies during initialisation comes back
    ``started: False`` with its exit code and the head of its log, not as a start in
    progress -- see :func:`_confirm_vllm_start`.

    ``confirm`` is passed through to that watcher (``grace`` / ``step`` / ``sleep``) so
    a test never spends real seconds; production leaves it None.
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
            out["log_path"] = res.get("log_path")
            if not res.get("started"):
                out["detail"] = str(res.get("reason") or "vLLM was not started")
                out["ready"] = res.get("reason") == "already running"
                return out
            # ``start()`` returns the moment Popen succeeds, so "started" so far means
            # only "a process was spawned". Ask the lifecycle's own tri-state what
            # became of it rather than assuming, which is what this branch used to do.
            outcome = _confirm_vllm_start(**(confirm or {}))
            out["start_outcome"] = outcome
            state = str(outcome.get("state") or "")
            if state == "ready":
                out["started"] = True
                out["ready"] = True
                out["detail"] = f"vLLM is answering on {plan['model']}."
            elif state == "exited":
                out.update(_vllm_exited(out, plan, outcome, wait=wait, timeout=timeout))
            else:
                # Alive and not answering yet. The normal path for a model load, and
                # the one case where "starting" is the honest word.
                out["started"] = True
                out["detail"] = (
                    f"vLLM is starting on {plan['model']}. A model load takes tens of "
                    "seconds; the backend reports when it is answering."
                )
        else:
            out.update(_start_ollama(wait=wait, timeout=timeout))
    except Exception as exc:  # noqa: BLE001 - a launch failure is a sentence, not a 500
        out["started"] = False
        out["ready"] = False
        out["detail"] = str(exc)
        out["error"] = True
        _LOG.info("activation of %s failed: %s", backend, exc)
    return out


def _start_ollama(*, wait: bool, timeout: float | None) -> dict:
    """Launch the Ollama daemon. Split out so the vLLM-exited path below can reach it
    without a second copy of the "already running counts as ready" rule."""
    from src.llm.ollama_lifecycle import start as ollama_start

    kw: dict = {"wait": wait}
    if timeout is not None:
        kw["timeout"] = timeout
    res = ollama_start(**kw)
    ready = bool(res.get("ready")) or res.get("reason") == "already running"
    return {
        "started": bool(res.get("started")),
        "ready": ready,
        "detail": str(
            res.get("note")
            or res.get("reason")
            or ("Ollama is running." if ready else "Ollama was launched.")
        ),
    }


def _vllm_exited(
    out: dict, plan: dict, outcome: dict, *, wait: bool, timeout: float | None
) -> dict:
    """A vLLM start that DIED during engine init: say so, name where the reason is, and
    fall back to Ollama when the operator did not ask for vLLM by name.

    The fallback is the same rule the plan already applies one step earlier -- an
    explicit choice is never second-guessed, and the preferred backend's blocker is
    CARRIED rather than discarded, so the operator still learns their GPU is idle and
    why (the recorded pill-regression lesson). It is applied here too because a start
    that exits is as structural as a start that was refused: the next click will fail
    the same way, and refusing to serve at all when Ollama is right there installed is
    the very "honest and useless" outcome that lesson names.
    """
    code = outcome.get("returncode")
    head = _server_log_head()
    why = (
        f"vLLM's server process exited immediately (code {code}) while loading "
        f"{plan['model']} — the start FAILED; it is not still loading, so waiting "
        "will not help."
    )
    hint = str(outcome.get("log_hint") or "")
    path = outcome.get("log_path") or out.get("log_path")
    upd: dict = {
        "started": False,
        "ready": False,
        "detail": why + (f" {hint}" if hint else ""),
        "log_path": path,
    }
    if head:
        # The reason itself, not just a path to it: an operator reading a toast should
        # not have to go and find the file to learn that the repo was gated or the port
        # was taken.
        upd["server_log_head"] = head

    if plan.get("override"):
        upd["error"] = True
        return upd

    alt = _plan_for("ollama", "vLLM's server exited during startup", plan["candidates"], None)
    if not (alt["running"] or alt["can_start"]):
        upd["error"] = True
        return upd
    started = _start_ollama(wait=wait, timeout=timeout)
    if not (started["started"] or started["ready"]):
        upd["error"] = True
        return upd
    return {
        **alt,
        **started,
        "log_path": path,
        **({"server_log_head": head} if head else {}),
        "start_outcome": outcome,
        "fell_back_from": {"backend": "vllm", "blocker": upd["detail"]},
        "chosen_because": (
            f"vLLM was preferred but its server exited on startup ({why}), so Ollama "
            "serves instead"
        ),
        "detail": f"{started['detail']} {why}",
    }
