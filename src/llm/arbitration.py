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
import time

_LOG = logging.getLogger("llm.arbitration")

#: How long to wait for a stopped/released backend's memory to actually come back. The
#: driver frees asynchronously, so an immediate reading under-reports; polling until it
#: stops improving costs nothing when the release was instant.
_SETTLE_TIMEOUT_S = 20.0
_SETTLE_POLL_S = 0.5


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
            out["released"] = bool(detail.get("stopped"))
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
) -> dict:
    """Make ``backend`` the one holding the card, and report every step of it.

    Releases every OTHER known backend first, then -- when ``start`` -- brings the named
    one up. ``model`` matters only for vLLM, which serves exactly one model per server,
    so pointing it at a different model IS a restart.

    ``ready`` is the honest bottom line: it is a live probe of the backend answering,
    never an inference from "we spawned something". A start that was attempted and has
    not come up yet reports ``ready: False`` with the reason, because the caller's next
    move is to send it work.
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
    if not start:
        out["started"] = None
        out["ready"] = _is_ready(backend)
        return out

    try:
        out["started"] = _start(backend, model)
    except Exception as exc:  # noqa: BLE001 - a failed start is the finding
        out["started"] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    out["ready"] = _is_ready(backend)
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
        out["reason"] = _why_not_ready(backend)
        if held:
            out["reason"] += f" — and the card was not released by: {', '.join(held)}"
    return out


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
            vllm_lifecycle.stop()
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


def _is_ready(backend: str) -> bool:
    try:
        if backend == "ollama":
            from src.llm.ollama_lifecycle import is_running

            return is_running()
        if backend == "vllm":
            from src.llm import vllm_lifecycle

            return vllm_lifecycle.is_running()
    except Exception:  # noqa: BLE001
        return False
    return False


def _why_not_ready(backend: str) -> str:
    """The most specific reason available, never the generic one.

    vLLM keeps a tri-state for exactly this ("still loading" is not "died"), and a
    model load runs to tens of seconds, so reporting a not-yet-ready server as a
    failure would be the fabricated-failure mirror of the fabricated-success this
    whole chain exists to remove.
    """
    if backend == "vllm":
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


__all__ = ["free_vram_mb", "hand_gpu_to", "release_backend"]
