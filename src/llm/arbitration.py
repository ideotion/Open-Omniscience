"""Hand ONE GPU from one backend to the other, and say what actually moved.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ask 2026-08-10: benchmark the same model on Ollama AND on vLLM, then several
models on each. On a single-card machine that is not two runs, it is one run that keeps
swapping which process owns the card -- and nothing in the app sequenced that. The field
already produced the failure this prevents (2026-08-05): five vLLM starts died in ten
minutes because Ollama was holding several gigabytes of an 8 GB card, and vLLM sizes its
budget as a fraction of the card rather than of what is free.

THE ASYMMETRY IS DELIBERATE AND IS THE WHOLE DESIGN.

  * **Making room for vLLM** asks Ollama to drop model RESIDENCY (``release_vram``).
    Nothing is stopped. Ollama reloads on its next request, so the worst case is one
    model-load latency, and a daemon the operator started is untouched -- which is why
    this is allowed where a kill would not be.
  * **Making room for Ollama** stops vLLM, because vLLM holds its allocation for its
    whole lifetime and has no equivalent "let go" request. That is within bounds for a
    server this app installed into a venv it owns; ``vllm_lifecycle.stop`` refuses
    anything else by name.

WHAT THIS MODULE WILL NOT DO: guess. Every function reports the free-VRAM reading before
and after, so a caller states what was recovered instead of asserting that something
was; a card that cannot be read reports ``None`` rather than 0 (opposite findings); and a
backend that could not be given the card says so and lets the caller decide, rather than
proceeding into a start that the numbers already say will fail.
"""

from __future__ import annotations

import logging
import os
import time

_LOG = logging.getLogger("llm.arbitration")

#: How long to wait for a stopped/released backend's memory to actually come back. The
#: driver frees asynchronously, so an immediate reading under-reports; polling until it
#: stops improving costs nothing when the release was instant.
_SETTLE_TIMEOUT_S = 20.0
_SETTLE_POLL_S = 0.5

#: How long to wait for a backend this module just STARTED to actually answer.
#: A vLLM model load runs to tens of seconds and reaches CUDA-graph capture around
#: t+67s on an 8 GB card, so anything shorter would report a healthy load as a
#: failure. Bounded, and abandoned early on an exit -- waiting out a dead server is
#: the fabricated-patience mirror of the fabricated readiness this replaces.
#: ``OO_GPU_HANDOVER_TIMEOUT_S`` overrides it for an operator whose weights are
#: larger or whose disk is slower than the machine this was measured on.
_READY_TIMEOUT_S = 300.0
_READY_POLL_S = 2.0


def free_vram_mb() -> int | None:
    """Free VRAM right now, or None when the card cannot be read.

    None is not zero. "We could not look" and "the card is full" lead to opposite
    decisions, and this number is read at the exact moments a caller is deciding
    whether to start something.
    """
    try:
        from src.llm.backend import detect_gpu

        v = detect_gpu().get("vram_free_mb")
        return v if isinstance(v, int) else None
    except Exception:  # noqa: BLE001 - a reading that fails is an absence, not a crash
        return None


def current_holder() -> dict:
    """Which backend holds the card right now, and -- for vLLM -- with which model.

    Exists so a caller that is about to rearrange the machine can put it back the way
    it found it. A bench that stops vLLM to measure Ollama and then walks away has
    silently changed which backend every later request is served by, which is a side
    effect nobody asked for and nobody would think to look for.

    ``backend`` is None when neither is up: an honest "nothing was holding it", which
    is a legitimate prior state and must not be restored INTO something.
    """
    try:
        from src.llm import vllm_lifecycle

        if vllm_lifecycle.is_running():
            return {"backend": "vllm", "model": _served_vllm_model()}
    except Exception:  # noqa: BLE001 - an unreadable backend is not a holder
        pass
    try:
        from src.llm.ollama_lifecycle import is_running as ollama_running

        if ollama_running():
            return {"backend": "ollama", "model": None}
    except Exception:  # noqa: BLE001
        pass
    return {"backend": None, "model": None}


def _settle(before: int | None, *, timeout: float = _SETTLE_TIMEOUT_S) -> tuple[int | None, float]:
    """Poll until the free-VRAM reading stops improving. Returns ``(after, waited_s)``."""
    if before is None:
        return free_vram_mb(), 0.0
    waited, last = 0.0, before
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        time.sleep(_SETTLE_POLL_S)
        waited += _SETTLE_POLL_S
        now = free_vram_mb()
        if now is None or now <= last:
            break
        last = now
    return free_vram_mb(), round(waited, 1)


def release_backend(backend: str) -> dict:
    """Ask ``backend`` to stop holding the GPU, by whichever means is legitimate for it.

    Returns ``{backend, method, released, free_mb_before, free_mb_after, waited_s,
    detail}``. ``method`` names WHAT was done, because "released" means something
    materially different for the two backends and a caller reporting to an operator
    needs to be able to say which.
    """
    before = free_vram_mb()
    out: dict = {"backend": backend, "free_mb_before": before}
    if backend == "ollama":
        from src.llm.ollama_lifecycle import release_vram

        detail = release_vram()
        out["method"] = "unload-models"
        out["released"] = bool(detail.get("released"))
        out["detail"] = detail
    elif backend == "vllm":
        from src.llm import vllm_lifecycle

        if not vllm_lifecycle.is_running():
            out["method"] = "none"
            out["released"] = False
            out["detail"] = {"reason": "vLLM was not running"}
        else:
            detail = vllm_lifecycle.stop()
            out["method"] = "stop-server"
            # A stop that was PERFORMED and did not TAKE has released nothing: the
            # server is still answering and still holding the card, so the caller would
            # start Ollama onto memory vLLM has not given back. Same rule the
            # model-switch path applies -- written here too rather than left as a
            # comment on one branch, which is how this class recurred in the first
            # place.
            out["released"] = bool(detail.get("stopped")) and detail.get("port_quiet") is not False
            out["detail"] = detail
    else:
        out["method"] = "none"
        out["released"] = False
        out["detail"] = {"reason": f"unknown backend {backend!r}"}
    after, waited = _settle(before) if out["released"] else (free_vram_mb(), 0.0)
    out["free_mb_after"] = after
    out["waited_s"] = waited
    return out


def hand_gpu_to(
    backend: str,
    *,
    model: str | None = None,
    start: bool = True,
    others: tuple[str, ...] = ("ollama", "vllm"),
    wait_ready_s: float | None = None,
) -> dict:
    """Make ``backend`` the one holding the card, and report every step of it.

    Releases every OTHER known backend first, then -- when ``start`` -- brings the named
    one up. ``model`` matters only for vLLM, which serves exactly one model per server,
    so pointing it at a different model IS a restart.

    ``ready`` is the honest bottom line: it is a live probe of the backend answering
    **as the model that was asked for**, never an inference from "we spawned something".

    BOTH halves of that sentence were learned from one field run (2026-08-10). A deep
    bench asked for seven vLLM models in turn, and six came back with every task
    refused, because readiness was a probe of the PORT: a server serving model A
    answers, so pointing it at model B and asking "is it ready?" said yes, and the
    caller sent B's work to A's server. Nothing was mislabelled -- the client refuses a
    model it was not started with, which is what made the run diagnosable rather than
    fabricated -- but six models produced nothing and the run called itself complete.

    ``wait_ready_s`` exists because the other half of that fix would have produced the
    mirror defect: ``vllm_lifecycle.start`` returns the moment the process is spawned
    ("a model load takes tens of seconds -- poll is_running() before use"), so a
    one-shot probe taken immediately after a restart reads not-ready for a server that
    is loading perfectly well. The wait is bounded and is abandoned the moment the
    lifecycle's own tri-state says the server EXITED, so a dead start is reported in
    seconds rather than waited out.
    """
    steps: list[dict] = []
    for other in others:
        if other == backend:
            continue
        steps.append(release_backend(other))

    out: dict = {
        "backend": backend,
        "model": model,
        "released": steps,
        "free_mb_before_start": free_vram_mb(),
    }
    want = model if backend == "vllm" else None
    if not start:
        out["started"] = None
        out["ready"] = _is_ready(backend, want)
        return out

    try:
        out["started"] = _start(backend, model)
    except Exception as exc:  # noqa: BLE001 - a failed start is the finding
        out["started"] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    started = out["started"] if isinstance(out["started"], dict) else {}
    # A start that REFUSED has nothing to wait for. Polling for five minutes against a
    # server we were told we may not stop would turn one honest sentence into a
    # five-minute stall, per pair.
    refused = bool(started.get("switch_refused")) or bool(started.get("error"))
    # ONLY vLLM is waited for. Its ``start()`` returns the instant the process is
    # spawned; ``ollama_lifecycle.start()`` already blocks until the daemon answers or
    # gives up, so polling another five minutes for a daemon that has already been
    # waited for and failed is the same fabricated patience, one backend over.
    wait_for = _ready_timeout(wait_ready_s) if backend == "vllm" else 0.0
    out["ready"] = _wait_ready(backend, want, timeout=0.0 if refused else wait_for)
    if not out["ready"]:
        # A release that was REFUSED is the likeliest cause of the failure that follows
        # it, and it is the one fact the backend's own diagnosis cannot see: vLLM
        # reports "exited", not "exited because another process held four gigabytes".
        # Carrying it here is the difference between a reason and a symptom.
        held = [
            f"{s['backend']} ({(s.get('detail') or {}).get('reason') or 'not released'})"
            for s in steps
            if not s.get("released") and (s.get("detail") or {}).get("reason")
        ]
        # The start's OWN reason wins when it refused: it names what we were not
        # allowed to do, which is more specific than any probe of the aftermath.
        out["reason"] = started.get("reason") if refused else _why_not_ready(backend, want)
        out["reason"] = out["reason"] or _why_not_ready(backend, want)
        if held:
            out["reason"] += f" — and the card was not released by: {', '.join(held)}"
    return out


def _ready_timeout(explicit: float | None) -> float:
    if explicit is not None:
        return max(0.0, explicit)
    raw = os.getenv("OO_GPU_HANDOVER_TIMEOUT_S")
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            _LOG.info("ignoring unreadable OO_GPU_HANDOVER_TIMEOUT_S=%r", raw)
    return _READY_TIMEOUT_S


def _wait_ready(backend: str, model: str | None, *, timeout: float) -> bool:
    """Poll until ``backend`` answers as ``model``, it demonstrably died, or time runs out.

    Probes BEFORE sleeping, so a timeout of 0 is exactly the one-shot check this used to
    do and an already-ready backend costs nothing.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if _is_ready(backend, model):
            return True
        if backend == "vllm" and _vllm_exited():
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(_READY_POLL_S)


def _vllm_exited() -> bool:
    """Did the last vLLM start die? Read from the lifecycle's own tri-state.

    Only ``exited`` counts. "Still loading" is not a failure -- calling it one is the
    defect this wait exists to avoid, one level down.
    """
    try:
        from src.llm import vllm_lifecycle

        return str((vllm_lifecycle.start_outcome() or {}).get("state") or "") == "exited"
    except Exception:  # noqa: BLE001 - an unreadable journal is not a death
        return False


def _start(backend: str, model: str | None) -> dict:
    if backend == "ollama":
        from src.llm import ollama_lifecycle

        return ollama_lifecycle.start()
    if backend == "vllm":
        from src.llm import vllm_lifecycle

        if vllm_lifecycle.is_running():
            served = _served_vllm_model()
            if model is None or served == model:
                return {"started": False, "reason": "already running", "model": served}
            # A different model: vLLM serves one per server, so this is a restart and
            # there is no cheaper way to do it.
            #
            # THE OUTCOME OF THIS STOP IS LOAD-BEARING and used to be discarded. When
            # it refused -- a server this app did not start, or one it could not
            # signal -- the next line asked `start()` for the new model, `start()`
            # answered "already running" (its word for `process_alive() or
            # is_running()`, which is about a PROCESS and not about a model), and the
            # handover reported success while the old model kept the card. Every field
            # symptom followed from those two words being trusted.
            stopped = vllm_lifecycle.stop()
            # `port_quiet is False` is a stop that was PERFORMED and did not take: the
            # server is still answering, so starting the new model would read
            # "already running" and keep serving the old one. Treated exactly like a
            # refusal, because for the caller it is one.
            if not stopped.get("stopped") or stopped.get("port_quiet") is False:
                return {
                    "started": False,
                    "switch_refused": True,
                    "served": served,
                    "stop": stopped,
                    "reason": (
                        f"vLLM is serving {served!r} and could not be stopped to serve "
                        f"{model!r}: "
                        + (
                            stopped.get("reason")
                            or stopped.get("note")
                            or "it was stopped but its port is still answering"
                        )
                    ),
                }
            _settle(free_vram_mb())
        target = model or _default_vllm_model()
        if not target:
            # vLLM cannot be started without naming a model, and picking one here would
            # be this module inventing a decision that belongs to the activation plan.
            return {
                "started": False,
                "reason": (
                    "no vLLM model to serve: none was named and no default could be "
                    "resolved. Choose one in Settings → AI."
                ),
            }
        return vllm_lifecycle.start(target)
    raise ValueError(f"unknown backend {backend!r}")


def _default_vllm_model() -> str | None:
    """The model this machine would serve with, from the activation plan's own answer.

    Read rather than re-derived: activation already decides this, and a second opinion
    here is how two surfaces end up naming different models.
    """
    try:
        from src.llm.activation import _vllm_model

        return _vllm_model() or None
    except Exception:  # noqa: BLE001 - no answer is a reason, not a crash
        return None


def _served_vllm_model() -> str | None:
    try:
        from src.llm.vllm_client import VllmClient

        served = VllmClient(timeout=3.0).list_installed()
        return served[0] if served else None
    except Exception:  # noqa: BLE001
        return None


def _is_ready(backend: str, model: str | None = None) -> bool:
    """Is ``backend`` answering -- and, when a model is named, answering AS that model?

    The second half is the whole point. vLLM serves exactly one model per server, so a
    port that answers proves only that SOME model is loaded; asking it for another one
    gets every call refused. A caller whose next move is to send that model work needs
    the stronger claim, and there is no cheaper way to get it than asking the server
    which model it holds.
    """
    try:
        if backend == "ollama":
            from src.llm.ollama_lifecycle import is_running

            return is_running()
        if backend == "vllm":
            from src.llm import vllm_lifecycle

            if not vllm_lifecycle.is_running():
                return False
            return model is None or _served_vllm_model() == model
    except Exception:  # noqa: BLE001
        return False
    return False


def _why_not_ready(backend: str, model: str | None = None) -> str:
    """The most specific reason available, never the generic one.

    vLLM keeps a tri-state for exactly this ("still loading" is not "died"), and a
    model load runs to tens of seconds, so reporting a not-yet-ready server as a
    failure would be the fabricated-failure mirror of the fabricated-success this
    whole chain exists to remove.
    """
    if backend == "vllm":
        # The server is UP but holding something else: a restart that did not take.
        # Distinct from "not answering" and from "died", and it is the one an operator
        # can act on, so it is checked before either.
        if model:
            served = _served_vllm_model()
            if served and served != model:
                return (
                    f"the vLLM server is answering, but it is serving {served!r} rather "
                    f"than {model!r} — the restart did not take effect"
                )
        try:
            from src.llm import vllm_lifecycle

            outcome = vllm_lifecycle.start_outcome() or {}
            state = outcome.get("state")
            if state == "exited":
                excerpt = (vllm_lifecycle.failure_excerpt() or {}).get("excerpt")
                return f"the vLLM server exited during startup. {excerpt or ''}".strip()
            if state == "starting":
                return (
                    "the vLLM server is still loading its model (tens of seconds is "
                    "normal) — it is not ready yet, which is not the same as failed."
                )
        except Exception:  # noqa: BLE001
            pass
        return "the vLLM server is not answering yet"
    if backend == "ollama":
        from src.llm.ollama_lifecycle import is_installed

        if not is_installed():
            return "Ollama is not installed on this machine"
        return "the Ollama daemon is not answering yet"
    return f"unknown backend {backend!r}"


def restore_or_release(prior: dict | None) -> dict:
    """Put the card back the way ``prior`` found it -- including finding it EMPTY.

    THE CASE THAT WAS MISSING. The bench read the prior holder and handed the card
    back afterwards, which is right whenever something WAS serving. When nothing was,
    it returned "nothing to restore" and did nothing -- so a run started from a cold
    machine ended with whatever it had last benched still holding the card. For Ollama
    that is five minutes of residency; for vLLM it is the server's whole lifetime.
    Field report 2026-08-12: "I did the model benchmark, and noticed the last model
    didn't unload from memory."

    "Nothing was serving" is a state, not the absence of one, and restoring it means
    RELEASING -- which is why this is not simply a longer ``_restore_holder``.

    Nothing here starts a backend that was not up, and nothing kills a process this
    app did not spawn: ``release_backend`` drops Ollama's model residency (the daemon
    is usually the operator's own service and is left running, per the standing
    no-stop ruling) and stops only an app-spawned vLLM.
    """
    backend = (prior or {}).get("backend")
    if not backend:
        released = [release_backend(b) for b in ("vllm", "ollama")]
        did = [r for r in released if r.get("released")]
        return {
            "action": "release",
            "prior": None,
            "restored": True,
            "released": [
                {"backend": r["backend"], "method": r.get("method"), "detail": r.get("detail")}
                for r in did
            ],
            "free_mb_after": free_vram_mb(),
            "reason": (
                "nothing was serving before this run, so nothing is serving after it -- "
                "the models it loaded were released rather than left holding the card"
                if did
                else "nothing was serving before this run, and nothing was left holding the card"
            ),
        }
    model = (prior or {}).get("model")
    if backend == "vllm" and not model:
        # Restarting on the default would put the machine on a model it was not on,
        # which is a worse wrong answer than leaving it down: one is a stated gap, the
        # other is a silent change.
        return {
            "action": "none",
            "prior": prior,
            "restored": False,
            "reason": (
                "a vLLM server was running before this run, but which model it was "
                "serving could not be read -- restarting it on the default would put "
                "this machine on a model it was not on, so it was left alone"
            ),
        }
    now = current_holder()
    if now.get("backend") == backend and (backend != "vllm" or now.get("model") == model):
        return {"action": "none", "prior": prior, "restored": True,
                "reason": "the backend that was serving before this run still is"}
    note = hand_gpu_to(backend, model=model if backend == "vllm" else None)
    return {
        "action": "restore",
        "prior": prior,
        "restored": bool(note.get("ready")),
        "reason": note.get("reason"),
        "detail": note,
    }


__all__ = [
    "current_holder",
    "free_vram_mb",
    "hand_gpu_to",
    "release_backend",
    "restore_or_release",
]
