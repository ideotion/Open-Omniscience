"""
Collection-performance logging: the bottleneck-finding system.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-06-16: "create a specific additional logging system that
will help identify the real bottlenecks (DB / CPU / memory) and find solutions."

This is that system. While a collect pass runs, :class:`CollectionMonitor` samples
— every ``interval_s`` — the app's OWN measured download rate, the in-flight fetch
count, the single-writer gate's contention, and process/system CPU + memory, then:

  1) drives the :class:`~src.scheduler.bandwidth.BandwidthGovernor` (rate + the
     contention flags it computes from those samples), and
  2) appends one honest JSONL line per tick to ``data/collect_perf.jsonl`` (bounded,
     local-only, surfaced ONLY via the Settings debug bundle — same pattern as
     app_errors.jsonl / field_test.jsonl), and
  3) at pass end writes a SUMMARY line with a TRANSPARENT, LABELLED bottleneck
     classification next to the raw numbers (never a single composite score).

Every number is measured (download rate = the app's own bytes diffed over
wall-clock; CPU/memory = psutil). Best-effort and defensive throughout: a fault in
monitoring must never break — or slow — a collection pass.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime

_LOG = logging.getLogger("monitoring.collect_perf")

# Keep the rolling log bounded (newest lines win), like the other diagnostics
# channels. ~1 line / 1.5 s ≈ 2400 lines/hour, so this holds ~a couple of hours.
_CAP_LINES = 5000

# Contention thresholds (honest, simple, and logged so the heuristic is auditable).
_CPU_SATURATED_PCT = 92.0  # system-wide CPU at/above this = CPU is the limit
_DEFAULT_MEM_FLOOR_MB = 512.0  # back off when available memory drops below this


def _log_path():
    from src.paths import data_dir

    return data_dir() / "collect_perf.jsonl"


# --------------------------------------------------------------------------- #
# Latest sample (for the live UI readout) — one process-global slot the
# scheduler activity payload reads without holding a monitor reference.
# --------------------------------------------------------------------------- #
_LATEST_LOCK = threading.Lock()
_LATEST: dict | None = None


def get_latest() -> dict | None:
    """The most recent perf sample (or None when no pass is being monitored)."""
    with _LATEST_LOCK:
        return dict(_LATEST) if _LATEST else None


def _set_latest(sample: dict | None) -> None:
    global _LATEST
    with _LATEST_LOCK:
        _LATEST = dict(sample) if sample else None


def _vitals() -> dict:
    """Process + system CPU% and memory, via psutil. All fields None on any error
    (psutil missing / sandbox) so the governor simply skips that back-off — never a
    fabricated number."""
    out = {"cpu_sys_pct": None, "cpu_proc_pct": None, "mem_avail_mb": None, "rss_mb": None}
    try:
        import psutil

        out["cpu_sys_pct"] = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        out["mem_avail_mb"] = round(vm.available / (1024 * 1024), 1)
        proc = psutil.Process()
        out["cpu_proc_pct"] = proc.cpu_percent(interval=None)
        out["rss_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - vitals are best-effort
        pass
    return out


def _writer_stats() -> dict:
    try:
        from src.database.writer import write_gate_stats

        return write_gate_stats()
    except Exception:  # noqa: BLE001
        return {}


def _append_jsonl(record: dict) -> None:
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 - logging must never break a pass
        _LOG.debug("collect_perf append failed", exc_info=True)


def _trim_jsonl() -> None:
    try:
        path = _log_path()
        if not path.exists():
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > _CAP_LINES:
            path.write_text("\n".join(lines[-_CAP_LINES:]) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        _LOG.debug("collect_perf trim failed", exc_info=True)


class CollectionMonitor:
    """Samples the live pass, drives the governor, and logs the perf timeline.

    Run as a daemon thread for the duration of one pass: ``start()`` then
    ``stop()`` (which joins promptly and writes the summary). Injection points
    (``rate_fn``, ``vitals_fn``, ``writer_stats_fn``, ``now_fn``) keep the loop
    deterministically testable without real waiting, psutil, or the DB.
    """

    def __init__(
        self,
        *,
        governor,
        pass_id: str,
        mode: str,
        interval_s: float = 1.5,
        mem_floor_mb: float = _DEFAULT_MEM_FLOOR_MB,
        rate_fn=None,
        vitals_fn=None,
        writer_stats_fn=None,
    ) -> None:
        self._gov = governor
        self._pass_id = pass_id
        self._mode = mode
        self._interval = max(0.05, float(interval_s))
        self._mem_floor = float(mem_floor_mb)
        self._vitals_fn = vitals_fn or _vitals
        self._writer_stats_fn = writer_stats_fn or _writer_stats
        self._rate_fn = rate_fn  # () -> measured_kbps; else diff bytes_total
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = time.time()
        # Rolling aggregates for the end-of-pass classification.
        self._n = 0
        self._rate_sum = 0.0
        self._peak_permits = 0
        self._max_inflight = 0
        self._max_cpu_sys = 0.0
        self._min_mem_avail: float | None = None
        self._max_writer_waiters = 0
        self._writer_wait_start: float | None = None
        self._writer_wait_last: float = 0.0
        # State for the bytes-diff rate when no rate_fn is injected.
        self._prev_bytes = 0
        self._prev_mono = 0.0

    # -- lifecycle --------------------------------------------------------- #

    def start(self) -> None:
        _trim_jsonl()
        self._prev_bytes = self._bytes_total()
        self._prev_mono = time.monotonic()
        try:  # prime psutil's since-last-call counters so the first reading is real
            import psutil

            psutil.cpu_percent(interval=None)
            psutil.Process().cpu_percent(interval=None)
        except Exception:  # noqa: BLE001
            pass
        self._thread = threading.Thread(target=self._loop, name="oo-collect-perf", daemon=True)
        self._thread.start()

    def stop(self, *, result: dict | None = None) -> dict | None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(3.0, self._interval * 2))
        _set_latest(None)
        return self._write_summary(result)

    # -- internals --------------------------------------------------------- #

    @staticmethod
    def _bytes_total() -> int:
        try:
            from src.monitoring.activity import activity_monitor

            return int(activity_monitor.snapshot().get("bytes_total", 0))
        except Exception:  # noqa: BLE001
            return 0

    @staticmethod
    def _inflight() -> tuple[int, int]:
        try:
            from src.monitoring.activity import activity_monitor

            return activity_monitor.inflight_count(), activity_monitor.inflight_hosts()
        except Exception:  # noqa: BLE001
            return 0, 0

    def _measure_rate(self) -> float:
        """Download rate in kbps (kiloBITS/s, decimal) over the last tick, diffing
        the app's cumulative byte counter — the same unit as the user's target."""
        if self._rate_fn is not None:
            try:
                return float(self._rate_fn())
            except Exception:  # noqa: BLE001
                return 0.0
        now = time.monotonic()
        total = self._bytes_total()
        dt = max(1e-3, now - self._prev_mono)
        rate = (total - self._prev_bytes) * 8 / 1000.0 / dt
        self._prev_bytes = total
        self._prev_mono = now
        return round(max(0.0, rate), 1)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - a monitoring fault must never abort a pass
                _LOG.debug("collect_perf tick failed", exc_info=True)

    def _tick(self) -> None:
        rate = self._measure_rate()
        vit = self._vitals_fn() or {}
        wstats = self._writer_stats_fn() or {}
        permits = int(getattr(self._gov, "permits", 0) or 0)
        inflight, inflight_hosts = self._inflight()

        cpu_sys = vit.get("cpu_sys_pct")
        mem_avail = vit.get("mem_avail_mb")
        waiters = int(wstats.get("waiters", 0) or 0)

        mem_low = mem_avail is not None and mem_avail < self._mem_floor
        cpu_saturated = cpu_sys is not None and cpu_sys >= _CPU_SATURATED_PCT
        # The writer is the limit when several workers are queued behind it.
        writer_saturated = waiters >= max(2, permits // 3)

        new_permits, reason = self._gov.observe(
            rate,
            writer_saturated=writer_saturated,
            cpu_saturated=cpu_saturated,
            mem_low=mem_low,
        )

        # Aggregates for the summary.
        self._n += 1
        self._rate_sum += rate
        self._peak_permits = max(self._peak_permits, permits, new_permits)
        self._max_inflight = max(self._max_inflight, inflight)
        if cpu_sys is not None:
            self._max_cpu_sys = max(self._max_cpu_sys, cpu_sys)
        if mem_avail is not None:
            self._min_mem_avail = mem_avail if self._min_mem_avail is None else min(self._min_mem_avail, mem_avail)
        self._max_writer_waiters = max(self._max_writer_waiters, waiters)
        tw = wstats.get("total_wait_s")
        if isinstance(tw, (int, float)):
            if self._writer_wait_start is None:
                self._writer_wait_start = float(tw)
            self._writer_wait_last = float(tw)

        sample = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "pass_id": self._pass_id,
            "elapsed_s": round(time.time() - self._started_at, 1),
            "mode": self._mode,
            "download_rate_kbps": rate,
            "target_kbps": getattr(self._gov, "target_kbps", None),
            "rate_mode": getattr(self._gov, "mode", None),
            "permits": permits,
            "permits_next": new_permits,
            "active_workers": int(getattr(self._gov, "active", 0) or 0),
            "inflight_fetches": inflight,
            "inflight_hosts": inflight_hosts,
            "adjust_reason": reason,
            "writer_gate": {
                "waiters": waiters,
                "peak_waiters": wstats.get("peak_waiters"),
                "contended": wstats.get("contended"),
                "total_wait_s": wstats.get("total_wait_s"),
                "max_wait_s": wstats.get("max_wait_s"),
            },
            "cpu_sys_pct": cpu_sys,
            "cpu_proc_pct": vit.get("cpu_proc_pct"),
            "mem_avail_mb": mem_avail,
            "rss_mb": vit.get("rss_mb"),
        }
        _set_latest(sample)
        _append_jsonl(sample)

    def _classify(self) -> dict:
        """Label the limiting factor from the pass aggregates — a transparent
        heuristic shown ALONGSIDE the raw numbers, never a hidden score."""
        avg_rate = round(self._rate_sum / self._n, 1) if self._n else 0.0
        writer_wait_delta = None
        if self._writer_wait_start is not None:
            writer_wait_delta = round(self._writer_wait_last - self._writer_wait_start, 3)
        target = getattr(self._gov, "target_kbps", 0)
        w_max = getattr(self._gov, "w_max", 0)
        mode = getattr(self._gov, "mode", "target")

        if self._min_mem_avail is not None and self._min_mem_avail < self._mem_floor:
            verdict = "memory-bound"
        elif self._max_writer_waiters >= 2 and (writer_wait_delta or 0) > 0:
            verdict = "writer-bound"
        elif self._max_cpu_sys >= 90.0:
            verdict = "cpu-bound"
        elif mode == "target" and target and avg_rate < target * 0.8 and self._peak_permits >= w_max:
            verdict = "network-or-source-bound"
        else:
            verdict = "target-met-or-headroom"

        return {
            "verdict": verdict,
            "method": (
                "Heuristic over the pass samples: memory floor, then writer-gate "
                "queueing, then CPU saturation, then rate-below-target at the worker "
                "ceiling. Raw numbers below — judge for yourself."
            ),
            "avg_download_rate_kbps": avg_rate,
            "target_kbps": target,
            "peak_permits": self._peak_permits,
            "max_inflight_fetches": self._max_inflight,
            "max_cpu_sys_pct": round(self._max_cpu_sys, 1),
            "min_mem_avail_mb": self._min_mem_avail,
            "max_writer_waiters": self._max_writer_waiters,
            "writer_total_wait_s_delta": writer_wait_delta,
            "samples": self._n,
        }

    def _write_summary(self, result: dict | None) -> dict | None:
        if self._n == 0:
            return None
        summary = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "pass_id": self._pass_id,
            "kind": "summary",
            "duration_s": round(time.time() - self._started_at, 1),
            "bottleneck": self._classify(),
        }
        if result:
            summary["articles_stored"] = result.get("articles_stored")
            summary["sources_processed"] = result.get("sources_processed")
            summary["pages_fetched"] = result.get("pages_fetched")
        _append_jsonl(summary)
        _trim_jsonl()
        return summary


def recent_samples(limit: int = 200) -> list[dict]:
    """The newest perf log lines (for the debug bundle). Best-effort."""
    try:
        path = _log_path()
        if not path.exists():
            return []
        out: list[dict] = []
        for ln in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out
    except Exception:  # noqa: BLE001
        return []
