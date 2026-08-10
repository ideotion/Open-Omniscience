"""What the bench needs before it can run, and getting it — without a shopping trip.

Maintainer ask 2026-08-10, after three runs where the answer to "why did nothing
happen" was always something the machine already knew before it started: a model that
was never downloaded, a backend that was not running, a weights directory that was
half there. Those are all knowable in seconds. Spending an afternoon discovering them
one pair at a time is the waste this module removes.

THREE THINGS, IN THIS ORDER.

**Survey.** For every roster model on every backend, one answer: ``ready`` (it is on
this machine and the backend can serve it), ``missing`` (it is not, and here is how
big it is), ``incomplete`` (it is partly on the disk and will not load), or
``backend-absent`` (the backend itself is not installed, so nothing under it is a
download decision yet). A survey performs no download and starts no server, so it is
safe to run before asking the operator anything.

**Ask.** The survey is the question. Downloading tens of gigabytes is not something to
infer from a click on "run the benchmark", so the plan is REPORTED and the fetch is a
separate, explicit yes — carrying the total size, because "download the missing
models" means very different things at 2 GB and at 60 GB.

**Fetch, and bench as each one lands.** Downloads are network-bound and the bench is
GPU-bound, so they overlap: one thread pulls model N+1 while the bench measures model
N. Nothing contends — a download writes to the disk and never touches the card. The
operator sees the first results while the rest is still arriving, which for a roster
that takes hours to fetch is the difference between a usable session and a wait.

WHAT THIS MODULE DOES NOT DO: decide. It never enables a backend the operator did not
install, never picks models for them, and never treats "I could not read the cache" as
"it is not there" — an unreadable probe is reported as unknown, because refusing a
download for a model that is already present wastes the same afternoon in the other
direction.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterable, Sequence
from typing import Any

_LOG = logging.getLogger(__name__)

PROVISION_SCHEMA = "oo-bench-provision-1"

#: Backends the bench knows how to survey, in the order a report lists them.
BACKENDS = ("ollama", "vllm")

#: Approximate download size per roster model, in MB, by backend. DISCLOSED as an
#: estimate: the real size is whatever the publisher ships today, and neither backend
#: reports it before the fetch starts. It exists so "download everything" can be
#: answered with a number instead of a shrug -- an operator on a metered link deserves
#: an order of magnitude before they say yes, and being wrong by 20% still answers the
#: question they are asking.
_SIZE_HINT_MB = {
    "vllm": 2400.0,    # bf16 weights for a 1-3B-class model
    "ollama": 1800.0,  # a 4-bit quantized GGUF of the same class
}


# --------------------------------------------------------------------------- #
#  Survey
# --------------------------------------------------------------------------- #
def _vllm_state(model: str) -> dict:
    """``ready`` / ``missing`` / ``incomplete`` / ``unknown`` for one vLLM model."""
    try:
        from src.llm import vllm_lifecycle
    except Exception as exc:  # noqa: BLE001 - a core install has no vLLM at all
        return {"state": "backend-absent", "detail": f"vLLM is not importable here ({exc})"}
    try:
        cache = vllm_lifecycle.model_cache_state(model) or {}
    except Exception as exc:  # noqa: BLE001
        return {"state": "unknown", "detail": f"the weights cache could not be read ({exc})"}
    if cache.get("cached") is True:
        return {"state": "ready", "bytes": cache.get("bytes"), "path": cache.get("path")}
    if cache.get("incomplete"):
        # Partly on the disk and unloadable. Distinct from missing on purpose: the
        # repair is the same download, but the operator is owed the wasted bytes.
        return {"state": "incomplete", "detail": cache["incomplete"], "bytes": cache.get("bytes")}
    if cache.get("cached") is None:
        return {"state": "unknown", "detail": "the weights directory could not be read"}
    return {"state": "missing", "expected": cache.get("expected")}


def _ollama_installed(client=None) -> tuple[set[str], str | None]:
    """Tags this Ollama holds, and why the list is empty when it is.

    ``(set(), reason)`` and ``(set(), None)`` are different answers -- a daemon that is
    down knows nothing, a daemon that is up with no models knows everything -- so the
    reason is returned rather than inferred from an empty set.
    """
    try:
        from src.llm.ollama import OllamaClient
    except Exception as exc:  # noqa: BLE001
        return set(), f"the Ollama client is not importable here ({exc})"
    try:
        c = client or OllamaClient()
        return {str(m) for m in (c.list_installed() or [])}, None
    except Exception as exc:  # noqa: BLE001 - a daemon that is down is normal, not an error
        return set(), f"Ollama did not answer ({exc})"


def survey(
    *,
    keys: Sequence[str] | None = None,
    ollama_client=None,
    wake: Callable[[str], dict] | None = None,
) -> dict:
    """What the bench needs, what is here, and what a full fetch would cost.

    Performs NO download and starts no server of its own. ``wake`` is the one exception
    and is optional: an Ollama daemon that is down reports zero models, which reads as
    "you have nothing" when the truth is "nobody asked". Waking it is cheap, local, and
    the difference between a useful survey and a misleading one -- but it stays
    injectable so a caller (and every test) can refuse it.
    """
    from src.llm.bench_roster import BENCH_ROSTER, identifiers_for

    wanted = list(keys) if keys else [e["key"] for e in BENCH_ROSTER]
    woken: dict[str, dict] = {}
    if wake is not None:
        try:
            woken["ollama"] = wake("ollama") or {}
        except Exception as exc:  # noqa: BLE001 - a failed wake is a fact, not a crash
            woken["ollama"] = {"woken": False, "error": str(exc)}

    installed_ollama, ollama_reason = _ollama_installed(ollama_client)
    rows: list[dict] = []
    refusals: list[dict] = []
    for backend in BACKENDS:
        ok, refused = identifiers_for(backend, wanted)
        for r in refused:
            refusals.append({"backend": backend, **r})
        for entry in ok:
            model = entry["identifier"]
            if backend == "vllm":
                state = _vllm_state(model)
            elif ollama_reason is not None:
                state = {"state": "unknown", "detail": ollama_reason}
            else:
                state = (
                    {"state": "ready"}
                    if model in installed_ollama
                    else {"state": "missing"}
                )
            rows.append(
                {
                    "key": entry["key"],
                    "label": entry.get("label"),
                    "backend": backend,
                    "model": model,
                    "size_hint_mb": _SIZE_HINT_MB.get(backend),
                    **state,
                }
            )

    to_fetch = [r for r in rows if r["state"] in ("missing", "incomplete")]
    unknown = [r for r in rows if r["state"] == "unknown"]
    ready = [r for r in rows if r["state"] == "ready"]
    est_mb = sum(float(r.get("size_hint_mb") or 0.0) for r in to_fetch)
    return {
        "schema": PROVISION_SCHEMA,
        "models": rows,
        "ready": len(ready),
        "to_fetch": to_fetch,
        "unknown": unknown,
        "refused": refusals,
        "estimated_download_mb": round(est_mb, 1) if to_fetch else 0.0,
        "estimated_download_note": (
            "An ESTIMATE from a per-backend size class, not a figure either backend "
            "published before the fetch. It answers 'roughly how much' — do not read it "
            "as a byte count."
        ),
        "woken": woken,
        "question": _question(ready, to_fetch, unknown, est_mb),
    }


def _question(ready: list[dict], to_fetch: list[dict], unknown: list[dict], est_mb: float) -> dict:
    """The one sentence the operator has to answer, and what happens either way."""
    if not to_fetch:
        return {
            "needs_download": False,
            "text": (
                f"All {len(ready)} roster models this machine can serve are already here. "
                "The bench can run now."
                if ready
                else "No roster model is available on either backend, and nothing is "
                "missing that a download would fix — check that a backend is installed."
            ),
        }
    names = ", ".join(sorted({r["model"] for r in to_fetch})[:6])
    more = len({r["model"] for r in to_fetch}) - 6
    return {
        "needs_download": True,
        "count": len(to_fetch),
        "estimated_mb": round(est_mb, 1),
        "text": (
            f"{len(to_fetch)} model(s) are not on this machine — roughly "
            f"{est_mb/1024:.1f} GB to download ({names}{f', +{more} more' if more > 0 else ''}). "
            f"{len(ready)} are already here and can be benched either way."
            + (
                f" {len(unknown)} could not be checked and are neither counted nor skipped."
                if unknown
                else ""
            )
        ),
    }


# --------------------------------------------------------------------------- #
#  Fetch, and bench as each one lands
# --------------------------------------------------------------------------- #
def _download_one(row: dict, *, ctx=None) -> dict:
    """Fetch one model on its own backend. Returns an outcome, never raises."""
    backend, model = row["backend"], row["model"]
    try:
        if backend == "vllm":
            from src.llm import vllm_lifecycle

            out = vllm_lifecycle.run_model_download_job(ctx, model=model)
            return {"model": model, "backend": backend, **(out or {})}
        from src.llm.ollama import OllamaClient

        client = OllamaClient()
        last: dict = {}
        for evt in client.pull(model):
            last = evt or last
            if ctx is not None and getattr(ctx, "stopping", False):
                return {"model": model, "backend": backend, "downloaded": False,
                        "state": "cancelled"}
        return {"model": model, "backend": backend, "downloaded": True, "state": "downloaded",
                "last_event": last.get("status")}
    except Exception as exc:  # noqa: BLE001 - one model's failure never ends the batch
        return {"model": model, "backend": backend, "downloaded": False, "state": "error",
                "error": str(exc)}


def provision_and_bench(
    plan: Iterable[dict],
    *,
    ready: Sequence[dict] = (),
    bench_one: Callable[[list[str]], Any],
    download: Callable[[dict], dict] | None = None,
    ctx=None,
) -> dict:
    """Download the plan while benching what is already usable, then what arrives.

    The overlap is the point. A roster fetch is measured in hours and a bench pass in
    minutes, so running them in series means the card sits idle for most of the
    session. A single downloader thread feeds a queue; this thread benches whatever is
    in it. They cannot contend: a download writes to the disk and the bench holds the
    GPU.

    ``bench_one`` receives one pair key list and returns whatever the bench returns —
    injected rather than imported so the sequencing is testable without a model, and so
    the caller decides what "bench" means.

    A download that FAILS is reported and skipped, never benched: measuring a model
    that did not arrive would produce a row of errors indistinguishable from a model
    that arrived and is bad.
    """
    plan = list(plan)
    q: "queue.Queue[dict | None]" = queue.Queue()
    fetch = download or (lambda row: _download_one(row, ctx=ctx))
    downloads: list[dict] = []

    def pump() -> None:
        try:
            for row in plan:
                if ctx is not None and getattr(ctx, "stopping", False):
                    break
                try:
                    out = fetch(row)
                except Exception as exc:  # noqa: BLE001
                    # Recorded, not lost. A fetch that raises would otherwise vanish
                    # from `downloads` entirely, so the report would show one fewer
                    # model than the plan and say nothing about the difference.
                    out = {
                        "model": row.get("model"),
                        "backend": row.get("backend"),
                        "downloaded": False,
                        "state": "error",
                        "error": str(exc),
                    }
                downloads.append(out)
                if out.get("downloaded"):
                    q.put(row)
        finally:
            # ALWAYS closes the queue, including on an exception anywhere above: a
            # consumer blocked on a sentinel that never arrives is a hang, and a hang
            # here looks exactly like a slow download.
            q.put(None)

    worker = threading.Thread(target=pump, name="oo-bench-provision", daemon=True)
    worker.start()

    benched: list[dict] = []

    def _bench(rows: Sequence[dict]) -> None:
        for row in rows:
            if ctx is not None and getattr(ctx, "stopping", False):
                return
            pair = f"{row['backend']}|{row['model']}"
            try:
                benched.append({"pair": pair, "report": bench_one([pair])})
            except Exception as exc:  # noqa: BLE001 - one pair never ends the run
                benched.append({"pair": pair, "error": str(exc)})

    # What is already here is benched FIRST, so the operator has results while the
    # download is still going rather than after it.
    _bench(list(ready))
    while True:
        row = q.get()
        if row is None:
            break
        _bench([row])
    worker.join(timeout=5.0)

    return {
        "schema": PROVISION_SCHEMA,
        "downloads": downloads,
        "benched": benched,
        "method": (
            "Models already on the machine are benched first; the rest are downloaded "
            "one at a time on a background thread and benched as each one lands. A "
            "failed download is reported and NOT benched — a model that never arrived "
            "would otherwise produce a row of errors that reads like a bad model."
        ),
    }


__all__ = [
    "BACKENDS",
    "PROVISION_SCHEMA",
    "provision_and_bench",
    "survey",
]
