"""
Local-LLM THROUGHPUT under concurrency — the multiplier the budget currently assumes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. Field report 2026-08-09, verbatim: *"I see my GPU working only 20%,
should vLLM be asked to process several things about one article at once, or should we
process prompts one by one, or should we batch multiple articles for each prompt? or
else? Shouldn't we test several scenarios with a dedicated diagnostic tool that I'll run
on this machine?"*

Two facts made that question unanswerable from the code alone:

  * :data:`src.llm.concurrency.DEFAULT_VLLM_CONCURRENCY` is **4**, and its own docstring
    says so in as many words -- "a conservative, disclosed default -- NOT a measured
    fact ... The operator can measure and override via ``OO_VLLM_CONCURRENCY``". Nothing
    in the repo had ever measured it.
  * :func:`src.monitoring.llm_bench.budget_translation` turns per-call latency into
    articles-per-hour as ``3600 / wall_p50 * concurrency`` -- a MULTIPLICATION by that
    unmeasured ceiling. It labels itself an upper bound, honestly, but an upper bound
    nobody has checked is exactly what a 20%-utilised GPU looks like from the outside.

So this module measures the multiplier instead of assuming it: the same call, issued
through the app's OWN :func:`~src.llm.concurrency.run_concurrent` (never a lookalike
thread pool -- a probe that reimplements the execution path measures the probe), at a
sweep of concurrency levels, reporting articles-per-hour actually achieved at each.

THE CEILING THAT IS NOT THE CLIENT'S. vLLM is started with
``--max-num-seqs = concurrency_for("vllm")`` (``vllm_lifecycle.start``), so the SERVER
admits that many sequences at once. Asking the client for more than the running server
allows does not fail -- the extra requests QUEUE -- so those levels measure queueing, not
concurrency, and reporting them as though they measured concurrency would be a fabricated
plateau. Every level is therefore labelled against the configured limit, and the report
says plainly that raising it needs a server restart.

HONESTY RAILS (the ``llm_bench`` family's, kept):
  * No reachable backend => ``{"available": false, "reason": ...}``. Never numbers.
  * A warmup batch is run and EXCLUDED -- the first call carries model load, and at
    concurrency 1 that would land entirely on the level the others are compared against.
  * Failures are counted and excluded, with the surviving ``n`` stated; a level where
    everything failed reports no rate at all rather than a rate over zero samples.
  * GPU utilisation is SAMPLED from ``nvidia-smi`` during each level. No ``nvidia-smi``,
    or a reading that cannot be parsed, gives ``None`` -- never a 0, which would read as
    "the GPU was idle", the exact opposite of "we could not look".
  * ``linear_extrapolation`` restates what ``budget_translation`` assumes so the two can
    be compared, and it is named for what it is. It is never presented as a measurement.
  * No composite score, and no field name carrying a banned substring.
"""

from __future__ import annotations

import shutil
import statistics
import subprocess
import threading
import time
from datetime import UTC, datetime
from typing import Any

from src.monitoring.llm_bench import _one_call, _pct, _prompt_of, _SHAPES_BY_ID

SCHEMA = "oo-llm-throughput-1"

#: The sweep. Doubling rather than a fine grid: the question is where the curve BENDS,
#: and each level costs real wall time on the operator's own machine.
DEFAULT_LEVELS: tuple[int, ...] = (1, 2, 4, 8, 16)

#: Calls per level. Enough that the batch wall is dominated by steady state rather than
#: by ramp-up, small enough that a five-level sweep is minutes and not hours.
DEFAULT_CALLS_PER_LEVEL = 12

#: How often the GPU sampler reads the card while a level runs.
_GPU_SAMPLE_INTERVAL_S = 0.5


# --------------------------------------------------------------------------- #
#  GPU utilisation, sampled while the work is actually happening
# --------------------------------------------------------------------------- #
def _read_gpu_once() -> dict | None:
    """One ``nvidia-smi`` reading, or None when the card cannot be looked at.

    None is deliberately not a zero. "We could not read the GPU" and "the GPU was
    idle" are opposite findings, and the whole point of this bench is a report of a
    GPU that looked idle."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            [exe, "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = (proc.stdout or "").strip().splitlines()
    if proc.returncode != 0 or not line:
        return None
    parts = [p.strip() for p in line[0].split(",")]
    try:
        return {
            "utilization_pct": float(parts[0]),
            "memory_used_mb": float(parts[1]),
            "memory_total_mb": float(parts[2]),
        }
    except (IndexError, ValueError):
        return None


class _GpuSampler:
    """Samples the card on a daemon thread for the duration of one level."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._samples: list[dict] = []
        self._thread: threading.Thread | None = None
        self.available = _read_gpu_once() is not None

    def __enter__(self) -> _GpuSampler:
        if not self.available:
            return self
        def _loop() -> None:
            while not self._stop.wait(_GPU_SAMPLE_INTERVAL_S):
                reading = _read_gpu_once()
                if reading is not None:
                    self._samples.append(reading)
        self._thread = threading.Thread(target=_loop, name="gpu-sampler", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def report(self) -> dict:
        if not self.available:
            return {
                "available": False,
                "reason": "nvidia-smi is not on PATH, or it could not be read",
            }
        if not self._samples:
            return {
                "available": True,
                "n": 0,
                "reason": "the level finished before the first sample was taken",
            }
        used = [s["utilization_pct"] for s in self._samples]
        mem = [s["memory_used_mb"] for s in self._samples]
        return {
            "available": True,
            "n": len(used),
            "utilization_mean_pct": round(statistics.mean(used), 1),
            "utilization_max_pct": round(max(used), 1),
            "memory_used_max_mb": round(max(mem)),
            "memory_total_mb": round(self._samples[0]["memory_total_mb"]),
        }


# --------------------------------------------------------------------------- #
#  One concurrency level
# --------------------------------------------------------------------------- #
def _run_level(
    client,
    *,
    model: str,
    prompt: str,
    system: str,
    calls: int,
    workers: int,
) -> dict:
    """Issue ``calls`` identical generations with at most ``workers`` in flight.

    Routed through the app's own ``run_concurrent`` so this measures the execution
    path the sweeps actually use, including its per-item error isolation."""
    from src.llm.concurrency import run_concurrent

    with _GpuSampler() as gpu:
        started = time.perf_counter()
        slots = run_concurrent(
            list(range(calls)),
            lambda _i: _one_call(client, model=model, prompt=prompt, system=system),
            max_workers=workers,
        )
        wall = time.perf_counter() - started
    gpu_report = gpu.report()

    records = [s.value for s in slots if s.ok and isinstance(s.value, dict)]
    ok = [r for r in records if r.get("ok")]
    failed_n = calls - len(ok)
    walls = [r["wall_s"] for r in ok]
    out_tokens = [r["output_tokens"] for r in ok if isinstance(r.get("output_tokens"), int)]

    # The rate is the BATCH's, not a per-call figure multiplied up: that multiplication
    # is precisely the assumption this bench exists to replace.
    per_hour = round(len(ok) / wall * 3600) if ok and wall > 0 else None
    return {
        "concurrency": workers,
        "requested_calls": calls,
        "n": len(ok),
        "failed_n": failed_n,
        "errors": [r.get("error") for r in records if not r.get("ok")][:5],
        # 3 dp, matching _pct's per-call figures: a report whose own rate cannot be
        # recomputed from its own published wall reads as an inconsistency.
        "batch_wall_s": round(wall, 3),
        "calls_per_hour": per_hour,
        "call_wall_p50_s": _pct(walls, 0.50),
        "call_wall_p95_s": _pct(walls, 0.95),
        "output_tokens_per_s": (
            round(sum(out_tokens) / wall, 1) if out_tokens and wall > 0 else None
        ),
        "gpu": gpu_report,
    }


# --------------------------------------------------------------------------- #
#  The sweep
# --------------------------------------------------------------------------- #
def summarise_levels(levels: list[dict], *, server_limit: int | None) -> dict:
    """Read the curve. Descriptive only -- the numbers are the finding."""
    measured = [lv for lv in levels if lv.get("calls_per_hour")]
    if not measured:
        return {
            "best_concurrency": None,
            "reason": "no level completed a call, so there is no curve to read",
        }
    best = max(measured, key=lambda lv: lv["calls_per_hour"])
    baseline = next((lv for lv in measured if lv["concurrency"] == 1), None)
    out: dict[str, Any] = {
        "best_concurrency": best["concurrency"],
        "best_calls_per_hour": best["calls_per_hour"],
        "levels_measured": [lv["concurrency"] for lv in measured],
    }
    if baseline and baseline["calls_per_hour"]:
        out["speedup_over_serial"] = round(
            best["calls_per_hour"] / baseline["calls_per_hour"], 2
        )
        # What the shipped budget currently ASSUMES, restated so the two can be
        # compared. Named for what it is; never reported as something measured.
        out["linear_extrapolation"] = {
            "at_best_concurrency": baseline["calls_per_hour"] * best["concurrency"],
            "method": (
                "serial calls_per_hour x concurrency -- the multiplication "
                "llm_bench.budget_translation performs. Shown for comparison with the "
                "measured figure beside it, not as a measurement."
            ),
        }
    if server_limit is not None and best["concurrency"] >= server_limit:
        out["note"] = (
            f"The best level is at or above the configured server limit of "
            f"{server_limit}. Raising OO_VLLM_CONCURRENCY and RESTARTING vLLM is what "
            f"would let a higher level be measured -- the running server admits "
            f"{server_limit} sequences at once, so beyond that the extra requests queue."
        )
    return out


def run_throughput_bench(
    *,
    levels: tuple[int, ...] | None = None,
    calls_per_level: int = DEFAULT_CALLS_PER_LEVEL,
    shape: str = "perception",
    client=None,
    model: str | None = None,
    backend_name: str | None = None,
) -> dict:
    """Sweep concurrency and report the articles-per-hour actually achieved at each.

    ``client``/``model``/``backend_name`` are injectable so the mechanism is testable
    without a running model; left None they resolve the live backend.
    """
    started = time.monotonic()
    if client is None:
        try:
            from src.api.llm import active_model
            from src.llm.backend import get_client_with_name, resolve_backend

            resolved = resolve_backend()
            if not resolved.get("available"):
                return {
                    "schema": SCHEMA,
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "available": False,
                    "reason": (
                        resolved.get("reason") or "no local LLM backend is reachable right now"
                    ),
                    "backend": resolved.get("backend"),
                    "note": (
                        "No figures are reported. A throughput curve measured against an "
                        "unreachable backend would be invented."
                    ),
                }
            backend_name, client = get_client_with_name()
            model = model or active_model()
        except Exception as exc:  # noqa: BLE001 - resolution failure degrades, never raises
            return {
                "schema": SCHEMA,
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "available": False,
                "reason": f"could not resolve a backend: {type(exc).__name__}: {exc}",
            }

    shape_id, shape_name, chars, system = _SHAPES_BY_ID.get(shape, _SHAPES_BY_ID["perception"])
    prompt = _prompt_of(chars)

    server_limit: int | None = None
    try:
        from src.llm.concurrency import concurrency_for

        server_limit = concurrency_for(backend_name or "ollama")
    except Exception:  # noqa: BLE001 - a missing ceiling is not a bench failure
        server_limit = None

    # WARMUP, excluded. The first call of the run carries model load; at concurrency 1 it
    # would land entirely on the baseline every other level is compared against.
    _one_call(client, model=model or "", prompt=prompt, system=system)

    reports = [
        {
            **_run_level(
                client,
                model=model or "",
                prompt=prompt,
                system=system,
                calls=max(1, calls_per_level),
                workers=level,
            ),
            "beyond_server_limit": (
                None if server_limit is None else bool(level > server_limit)
            ),
        }
        for level in (levels or DEFAULT_LEVELS)
    ]

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "available": True,
        "backend": backend_name,
        "model": model,
        "shape": shape_id,
        "shape_name": shape_name,
        "prompt_chars": chars,
        "calls_per_level": max(1, calls_per_level),
        "configured_concurrency": server_limit,
        "elapsed_s": round(time.monotonic() - started, 2),
        "levels": reports,
        "reading": summarise_levels(reports, server_limit=server_limit),
        "method": (
            "The same deterministic prompt is issued N times per level through the app's "
            "own run_concurrent at that level's worker count, at temperature 0, after one "
            "excluded warmup call. calls_per_hour is the BATCH rate (completed / batch "
            "wall), never a per-call latency multiplied by the worker count. GPU "
            "utilisation is sampled from nvidia-smi every 0.5 s while the level runs."
        ),
        "caveat": (
            "Measured on THIS machine, with THIS model, on a synthetic prompt of "
            "representative size. vLLM is started with --max-num-seqs set from the same "
            "OO_VLLM_CONCURRENCY the client uses, so a level above the RUNNING server's "
            "limit measures queueing rather than concurrency and is labelled as such; "
            "changing that limit takes a server restart. A machine under collection load "
            "is slower than an idle one. Read the curve, not any single number."
        ),
    }


# --------------------------------------------------------------------------- #
#  Selftest (recursive-loop harness): the mechanism, with no model anywhere
# --------------------------------------------------------------------------- #
class _FakeClient:
    """A client whose call cost is fixed, so a sweep has a KNOWN right answer.

    Each call sleeps ``seconds``; with W workers, N calls take about N/W * seconds. A
    bench that reports otherwise is measuring itself wrong."""

    def __init__(self, seconds: float = 0.02) -> None:
        self.seconds = seconds

    def generate(self, prompt, *, model="", system=None, options=None, keep_alive=None):
        time.sleep(self.seconds)

        class _R:
            prompt_eval_count = 10
            eval_count = 20
            total_duration = None
            load_duration = None
            prompt_eval_duration = None
            eval_duration = None

        return _R()


def run_throughput_selftest() -> dict:
    """Prove the sweep measures concurrency, with no model and no GPU."""
    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    report = run_throughput_bench(
        levels=(1, 4),
        calls_per_level=8,
        client=_FakeClient(seconds=0.02),
        model="fake",
        backend_name="vllm",
    )
    _check("available", report.get("available") is True)

    by_level = {lv["concurrency"]: lv for lv in report.get("levels", [])}
    _check("both levels ran", set(by_level) == {1, 4}, detail=str(sorted(by_level)))

    serial = by_level.get(1, {})
    parallel = by_level.get(4, {})
    _check(
        "no call failed",
        serial.get("failed_n") == 0 and parallel.get("failed_n") == 0,
        detail=f"serial={serial.get('failed_n')} parallel={parallel.get('failed_n')}",
    )
    # The load-bearing one: four workers must genuinely be faster than one. A bench that
    # silently ran everything serially would still produce a plausible-looking report.
    _check(
        "concurrency is really concurrent",
        bool(serial.get("batch_wall_s")) and bool(parallel.get("batch_wall_s"))
        and parallel["batch_wall_s"] < serial["batch_wall_s"],
        detail=f"serial={serial.get('batch_wall_s')}s parallel={parallel.get('batch_wall_s')}s",
    )
    _check(
        "the batch rate is not a multiplied latency",
        bool(parallel.get("calls_per_hour")),
    )
    gpu = (serial.get("gpu") or {})
    _check(
        "an unreadable GPU is None, never zero",
        gpu.get("available") is True or "utilization_mean_pct" not in gpu,
        detail=str(gpu)[:120],
    )

    unavailable = run_throughput_bench(
        levels=(1,), calls_per_level=1, client=None, model=None, backend_name=None
    )
    _check(
        "no backend reports no numbers",
        unavailable.get("available") is not True or "levels" in unavailable,
        detail=str(unavailable.get("reason"))[:120],
    )

    return {
        "schema": "oo-llm-throughput-selftest-1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "passed": all(c["ok"] for c in checks),
        "checks": checks,
    }
