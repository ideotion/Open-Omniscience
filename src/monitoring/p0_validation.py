"""The P0 data-safety validation kit — the push-button acceptance run (S1.2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY: the v0.2.0 tag is HELD on the maintainer's LIVE-corpus validation of the P0
data-safety set (backup/restore at scale · unlock-at-scale · collector RSS). No
sandbox can run a 100 GB corpus, so this module makes that acceptance run
PUSH-BUTTON: one cancellable background job drives the real backup engine against
the operator's own live corpus, verifies it, probes a staged restore WITHOUT
touching the live corpus, reads the merged unlock + collector instrumentation, and
emits ONE report with a per-check verdict.

HONESTY (the whole point):
  * measurements only — NO composite quality score; the "summary" is a plain
    conjunction (did any check FAIL?), never a number to game;
  * NEVER a fabricated pass — a check that cannot run here reports
    ``not-measurable-here`` WITH the reason and the operator step that would
    measure it (a cold boot, a multi-day soak);
  * the verdicts test against the WRITTEN acceptance bars
    (``docs/product/SCALE_ROADMAP.md``), quoted into the report so it is
    self-describing;
  * it is UNABLE to corrupt or delete live data: the backup writes only to the
    operator's dest dir (guarded against overlapping the data dir) — its one touch
    of the live store is the engine's standard WAL checkpoint under the write lock,
    a content-preserving fold, never a replace/delete — and the restore is a STAGED
    probe + a dry-run merge PREVIEW (``commit=False`` — the restore never writes the
    live corpus at all), with every temp cleaned up; the live corpus is never
    replaced, deleted, or corrupted on any path;
  * the report is stamped with the backup-engine format + app version, so a later
    engine change (e.g. S3 adaptive volume sizing) makes a stale validation
    detectable.

The heavy work runs on the job thread (never the event loop); the backup already
owns writer-gate discipline and disk preflight. On cancel/finish the throwaway
restore staging is removed and a partial backup is cleaned (it can never be
mistaken for a complete one — the streaming engine writes no final manifest until
the set is whole).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("monitoring.p0_validation")

P0_VALIDATION_SCHEMA = "oo-p0-validation-1"

# The <2 s steady-state unlock bar (SCALE_ROADMAP P0.4). Not a constant in the
# unlock path — the acceptance target lives in the roadmap; we compare against it.
_UNLOCK_BAR_MS = 2000.0

# Below this corpus size the "bounded RAM" property of the streaming backup is
# trivially satisfied (a whole-corpus buffer would still be small), so peak RSS
# cannot DISCRIMINATE a streaming path from a materializing one. We report the
# numbers but mark the bounded-RAM sub-assessment not-measurable, never a pass on
# no evidence — the real proof needs the full-scale corpus.
_BOUNDED_RAM_MIN_CORPUS_MB = 2048.0

# A streaming backup's added RSS must not scale with the corpus. If the peak RSS
# DELTA (over the pre-backup baseline) reaches this fraction of the corpus size on
# a large corpus, RAM tracked the corpus — the OOM signature the bar forbids.
_BOUNDED_RAM_MAX_DELTA_FRACTION = 0.5

# Collector RSS "climbing" heuristic: flag when the peak pass RSS rises more than
# this many MB above the first pass. A SUSTAINED absolute rise is the OOM signature
# at any baseline (a +1.9 GB climb on a 4 GB baseline is a leak even though the
# RATIO is only 1.48x — an earlier ratio-AND gate hid exactly that case). A rise
# under the floor is treated as noise, not flagged. Stated in the report so the
# operator can judge from the per-pass numbers.
_COLLECTOR_CLIMB_ABS_MB = 512.0

_MIB = 1024 * 1024


def backup_engine_format() -> str:
    """The current backup container format, stamped into the report so a later
    engine change makes a stale validation detectable."""
    from src.backup.stream_backup import STREAM_KIND

    return STREAM_KIND


# --------------------------------------------------------------------------- #
#  The written acceptance bars (self-describing report; verbatim intent from
#  docs/product/SCALE_ROADMAP.md so the report never drifts from the doc silently)
# --------------------------------------------------------------------------- #
def _acceptance_bars() -> dict[str, str]:
    return {
        "p0_1_backup": (
            "The oo-volumes-2 streaming backup completes with BOUNDED RAM end to "
            "end (no plaintext corpus snapshot, no zip, banded parity) — RAM must "
            "not scale with the corpus. Acceptance: the maintainer's real 100 GB "
            "corpus backs up without OOM; RSS stays flat."
        ),
        "p0_1_verify": (
            "The backup VERIFIES: the Ed25519-signed volume manifest plus every "
            "data + parity volume checksum, and (with the passphrase) every volume "
            "stream-decrypts and its member checksums cross-check the signed "
            "envelope. Acceptance: verify reports ok with no bad volumes."
        ),
        "p0_2_restore": (
            "Restore streams member-by-member (bounded RAM), disk-preflights "
            "staging, and hands the artifact to the UNCHANGED additive merge. "
            "Acceptance: the maintainer's real 100 GB backup imports on a fresh "
            "install. Here: a staged round-trip + a dry-run merge PREVIEW proves "
            "the machinery end to end, with the live corpus only ever read."
        ),
        "p0_3_collector": (
            "Flat RSS across recycled collection passes; the memory guard pauses "
            "(never dies) under injected pressure. Acceptance: a multi-day live "
            "soak shows flat RSS and no OOM."
        ),
        "p0_4_unlock": (
            "Steady-state unlock < 2 s at 100 GB; any long phase visible and "
            "honest. Acceptance: a cold boot on the full corpus unlocks under the "
            "2 s bar."
        ),
    }


# --------------------------------------------------------------------------- #
#  RSS sampler (bounded-RAM evidence for the backup/restore windows)
# --------------------------------------------------------------------------- #
class _RssSampler:
    """Samples this process's RSS on a background thread for the duration of a
    ``with`` block, tracking the peak. All fields None when psutil is absent — a
    missing reading is reported honestly, never a fabricated 0."""

    def __init__(self, interval_s: float = 0.5) -> None:
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.baseline_mb: float | None = None
        self.peak_mb: float | None = None
        self._proc: Any = None

    def _rss_mb(self) -> float | None:
        try:
            if self._proc is None:
                import psutil

                self._proc = psutil.Process()
            return round(self._proc.memory_info().rss / _MIB, 1)
        except Exception:  # noqa: BLE001 - RSS is best-effort; degrade to None
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            v = self._rss_mb()
            if v is not None:
                self.peak_mb = v if self.peak_mb is None else max(self.peak_mb, v)
            self._stop.wait(self._interval)

    def __enter__(self) -> "_RssSampler":
        self.baseline_mb = self._rss_mb()
        self.peak_mb = self.baseline_mb
        self._thread = threading.Thread(
            target=self._run, name="p0-rss-sampler", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    @property
    def delta_mb(self) -> float | None:
        if self.peak_mb is None or self.baseline_mb is None:
            return None
        return round(max(0.0, self.peak_mb - self.baseline_mb), 1)


def _ram_bounded_assessment(
    delta_mb: float | None, corpus_mb: float
) -> tuple[str, str]:
    """Return (verdict, note) for the bounded-RAM property from the peak RSS delta.

    ``bounded`` / ``unbounded`` / ``not-measurable`` — pure, so it is unit-tested
    without touching psutil or the backup path."""
    if delta_mb is None:
        return (
            "not-measurable",
            "peak RSS could not be sampled (psutil unavailable), so the "
            "bounded-RAM property is unproven here — the backup's completion and "
            "verification still stand.",
        )
    if corpus_mb < _BOUNDED_RAM_MIN_CORPUS_MB:
        return (
            "not-measurable",
            f"corpus is {corpus_mb:.0f} MB (< {_BOUNDED_RAM_MIN_CORPUS_MB:.0f} MB): "
            "bounded RAM is trivially satisfied at this size and cannot discriminate "
            "a streaming path from a materializing one — the acceptance run needs "
            "the full-scale corpus.",
        )
    limit = corpus_mb * _BOUNDED_RAM_MAX_DELTA_FRACTION
    if delta_mb >= limit:
        return (
            "unbounded",
            f"peak RSS grew {delta_mb:.0f} MB (>= {_BOUNDED_RAM_MAX_DELTA_FRACTION:g}"
            f"x the {corpus_mb:.0f} MB corpus) — RAM scaled with the corpus, the OOM "
            "signature the bounded-RAM bar forbids.",
        )
    return (
        "bounded",
        f"peak RSS grew only {delta_mb:.0f} MB over a {corpus_mb:.0f} MB corpus — "
        "RAM did not scale with the corpus.",
    )


# --------------------------------------------------------------------------- #
#  Input safety: the dest dir must never overlap the live data dir
# --------------------------------------------------------------------------- #
def validate_dest_dir(dest_dir: str | Path) -> Path:
    """Resolve + guard the operator-supplied backup destination.

    Refuses (ValueError) a dest that IS, contains, or lives inside the data dir —
    the backup writes volumes there, and pointing it at the live store risks
    interleaving backup files with the corpus/state. A clean, separate directory
    (ideally an external drive) is the only safe target. The parent must exist and
    be writable so the job fails loudly up front, never mid-write."""
    from src.paths import data_dir

    if not str(dest_dir).strip():
        raise ValueError("a destination directory is required")
    dest = Path(dest_dir).expanduser().resolve()
    dd = data_dir().resolve()
    if dest == dd or dd in dest.parents or dest in dd.parents:
        raise ValueError(
            f"the backup destination {dest} overlaps the live data directory "
            f"{dd} — choose a separate, empty directory (ideally an external "
            "drive) so backup files never mix with the live corpus."
        )
    # The backup does mkdir(parents=True); the honest preflight is that the nearest
    # EXISTING ancestor is a writable directory (a bad mount / read-only drive fails
    # loudly here, up front, never mid-write).
    anchor = dest
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    if not anchor.exists() or not anchor.is_dir():
        raise ValueError(f"no existing directory to create the destination under: {dest}")
    if not os.access(anchor, os.W_OK):
        raise ValueError(f"the destination location is not writable: {anchor}")
    return dest


# --------------------------------------------------------------------------- #
#  P0.1 — backup (+ incremental refresh) + verify
# --------------------------------------------------------------------------- #
def _check_backup(
    ctx: Any,
    dest_dir: Path,
    passphrase: str,
    *,
    include_newsletters: bool,
    measure_incremental: bool,
) -> tuple[dict, dict]:
    """Drive the streaming backup (once, plus an optional incremental refresh) and
    then verify it. Returns (backup_check, verify_check). The passphrase never
    enters either dict."""
    from src.backup.artifact import write_volume_backup
    from src.backup.stream_backup import verify_stream_backup

    bars = _acceptance_bars()

    def _progress(p: dict) -> None:
        with contextlib.suppress(Exception):
            ctx.set_progress(detail=f"backup: {p.get('phase', '')}")

    # ---- full backup, sampling RSS across the run --------------------------- #
    t0 = time.monotonic()
    summary: dict | None = None
    err: str | None = None
    with _RssSampler() as rss:
        try:
            summary = write_volume_backup(
                dest_dir,
                passphrase,
                include_newsletters=include_newsletters,
                should_stop=lambda: ctx.stopping,
                progress_cb=_progress,
            )
        except Exception as exc:  # noqa: BLE001 - a backup fault is a measured FAIL
            err = f"{type(exc).__name__}: {exc}"
    backup_wall_s = round(time.monotonic() - t0, 3)

    corpus_bytes = int((summary or {}).get("corpus_bytes") or 0)
    corpus_mb = corpus_bytes / _MIB
    ram_verdict, ram_note = _ram_bounded_assessment(rss.delta_mb, corpus_mb)

    # ---- optional incremental refresh (proves changed-volume re-emit) ------- #
    incremental: dict | None = None
    if summary is not None and measure_incremental and not ctx.stopping:
        try:
            it0 = time.monotonic()
            s2 = write_volume_backup(
                dest_dir,
                passphrase,
                include_newsletters=include_newsletters,
                should_stop=lambda: ctx.stopping,
                progress_cb=_progress,
            )
            incremental = {
                "wall_s": round(time.monotonic() - it0, 3),
                "volumes": s2.get("volumes"),
                "volumes_reused": s2.get("volumes_reused"),
                "volumes_emitted": s2.get("volumes_emitted"),
                "bytes_reused": s2.get("bytes_reused"),
                "bytes_emitted": s2.get("bytes_emitted"),
                "note": (
                    "a second pass against the same destination with no corpus "
                    "change should reuse most volumes (checksum-compared, never "
                    "size/mtime) — the changed-volume re-emit property."
                ),
            }
        except Exception as exc:  # noqa: BLE001 - a bonus measurement; record the fault, never hide it
            # A cancel during the refresh is not a fault; anything else is recorded so a
            # real changed-volume-re-emit failure is visible (not None-as-if-not-attempted).
            if not ctx.stopping:
                incremental = {
                    "error": f"{type(exc).__name__}: {exc}",
                    "note": "the incremental refresh pass raised; the full backup + verify still stand.",
                }

    backup_measurements = {
        "duration_s": backup_wall_s,
        "baseline_rss_mb": rss.baseline_mb,
        "peak_rss_mb": rss.peak_mb,
        "peak_rss_delta_mb": rss.delta_mb,
        "corpus_bytes": corpus_bytes,
        "corpus_encrypted": (summary or {}).get("corpus_encrypted"),
        "volumes": (summary or {}).get("volumes"),
        "volumes_reused": (summary or {}).get("volumes_reused"),
        "volumes_emitted": (summary or {}).get("volumes_emitted"),
        "bytes_reused": (summary or {}).get("bytes_reused"),
        "bytes_emitted": (summary or {}).get("bytes_emitted"),
        "plaintext_bytes": (summary or {}).get("plaintext_bytes"),
        "gate_held_s": (summary or {}).get("gate_held_s"),
        "parity_available": (summary or {}).get("parity_available"),
        "resumed": (summary or {}).get("resumed"),
        "ram_bounded": {"verdict": ram_verdict, "note": ram_note},
        "incremental_refresh": incremental,
        "notes": (summary or {}).get("notes") or [],
    }

    if err is not None:
        # A cooperative cancel surfaces as VolumeStopped (should_stop fired), which
        # is a not-measurable outcome, NOT a data-safety FAIL. A genuine fault (no
        # cancel in flight) is a fail.
        cancelled = bool(ctx.stopping)
        backup_check = _verdict(
            "not-measurable" if cancelled else "fail",
            "the backup was cancelled before it completed."
            if cancelled
            else f"the streaming backup did not complete: {err}",
            backup_measurements,
            bars["p0_1_backup"],
        )
        verify_check = _verdict(
            "not-measurable",
            "the backup was cancelled." if cancelled else "no backup was produced, so there is nothing to verify.",
            {},
            bars["p0_1_verify"],
        )
        return backup_check, verify_check

    # The P0.1 bar IS bounded-RAM-at-scale. So a completed backup is only a PASS when RAM
    # was actually measured bounded; when it cannot be measured here (a sub-scale corpus
    # or no psutil) the SCALE bar is untestable, so the verdict is not-measurable-here —
    # never a 'pass' that over-reads as 'bounded RAM validated' (the honesty non-negotiable).
    # The backup's completion + verification are captured by the p0_1_verify check + the
    # measurements; a real fault already returned 'fail' above.
    if ram_verdict == "unbounded":
        backup_check = _verdict("fail", ram_note, backup_measurements, bars["p0_1_backup"])
    elif ram_verdict == "bounded":
        backup_check = _verdict(
            "pass", "the streaming backup completed with bounded RAM. " + ram_note,
            backup_measurements, bars["p0_1_backup"],
        )
    else:  # not-measurable
        backup_check = _verdict(
            "not-measurable",
            "the streaming backup completed and the volumes were written (verification is "
            "the separate P0.1-verify check), but the P0.1 scale bar — bounded RAM at "
            "100 GB — is not measurable here: " + ram_note,
            backup_measurements,
            bars["p0_1_backup"],
        )

    # ---- verify the freshly-written set ------------------------------------- #
    vt0 = time.monotonic()
    verr: str | None = None
    vrep: dict | None = None
    try:
        vrep = verify_stream_backup(dest_dir, passphrase)
    except Exception as exc:  # noqa: BLE001
        verr = f"{type(exc).__name__}: {exc}"
    verify_measurements = {
        "duration_s": round(time.monotonic() - vt0, 3),
        "ok": None if vrep is None else vrep.get("ok"),
        "signature": None if vrep is None else vrep.get("signature"),
        "decrypted": None if vrep is None else vrep.get("decrypted"),
        "bad_volumes": None if vrep is None else vrep.get("bad_volumes"),
        "missing_volumes": None if vrep is None else vrep.get("missing_volumes"),
        "parity": None if vrep is None else vrep.get("parity"),
        "problems": None if vrep is None else vrep.get("problems"),
        "method": None if vrep is None else vrep.get("method"),
    }
    if verr is not None:
        verify_check = _verdict(
            "fail", f"verification raised: {verr}", verify_measurements, bars["p0_1_verify"]
        )
    elif vrep and vrep.get("ok"):
        verify_check = _verdict(
            "pass",
            "the volume manifest signature and every volume checksum verified; the "
            + ("passphrase decrypted every volume and " if vrep.get("decrypted") else "")
            + "member checksums cross-checked the signed envelope.",
            verify_measurements,
            bars["p0_1_verify"],
        )
    else:
        probs = "; ".join((vrep or {}).get("problems") or ["unknown"])
        verify_check = _verdict(
            "fail", f"verification failed: {probs}", verify_measurements, bars["p0_1_verify"]
        )
    return backup_check, verify_check


# --------------------------------------------------------------------------- #
#  P0.2 — staged restore round-trip + dry-run merge preview (never commits)
# --------------------------------------------------------------------------- #
def _check_restore(
    ctx: Any, dest_dir: Path, passphrase: str, staging_root: Path
) -> dict:
    """Restore the just-written set into a THROWAWAY staging dir and run a dry-run
    merge PREVIEW (``commit=False``) — the live corpus is only ever read, never
    replaced. Returns the check; the staging is always cleaned up."""
    from src.backup.artifact import cleanup_staging, read_volume_backup
    from src.backup.merge import run_restore

    bars = _acceptance_bars()
    with contextlib.suppress(Exception):
        ctx.set_progress(detail="restore: staging")

    staged = None
    t0 = time.monotonic()
    with _RssSampler() as rss:
        try:
            staged = read_volume_backup(
                dest_dir, passphrase, staging_root=staging_root, include_merge_budget=True
            )
            with contextlib.suppress(Exception):
                ctx.set_progress(detail="restore: dry-run merge preview")
            report = run_restore(staged, commit=False, reindex_imported=False)
        except Exception as exc:  # noqa: BLE001 - a restore fault is a measured FAIL
            with contextlib.suppress(Exception):
                if staged is not None:
                    cleanup_staging(staged)
            return _verdict(
                "fail",
                f"the staged restore probe did not complete: {type(exc).__name__}: {exc}",
                {"duration_s": round(time.monotonic() - t0, 3), "peak_rss_mb": rss.peak_mb},
                bars["p0_2_restore"],
            )
    duration_s = round(time.monotonic() - t0, 3)

    staged_bytes = 0
    with contextlib.suppress(Exception):
        staged_bytes = sum(
            p.stat().st_size for p in staged.staging_dir.rglob("*") if p.is_file()
        )
    committed = bool(report.get("committed"))
    verification_ok = bool((report.get("verification") or {}).get("ok"))
    measurements = {
        "duration_s": duration_s,
        "baseline_rss_mb": rss.baseline_mb,
        "peak_rss_mb": rss.peak_mb,
        "peak_rss_delta_mb": rss.delta_mb,
        "staged_bytes": staged_bytes,
        "signature_state": report.get("signature_state"),
        "artifact_kind": report.get("artifact_kind"),
        "encrypted": report.get("encrypted"),
        "plan": report.get("plan"),
        "verification": report.get("verification"),
        "committed": committed,
    }

    with contextlib.suppress(Exception):
        cleanup_staging(staged)

    if committed:
        # This must be impossible on a preview — surface it as a critical fail
        # rather than a silent pass (never trust a run that claims to have written).
        return _verdict(
            "fail",
            "SAFETY ALARM: the dry-run restore reported committed=true — a preview "
            "must never write the live corpus. Do not trust this run; report it.",
            measurements,
            bars["p0_2_restore"],
        )
    if not verification_ok:
        return _verdict(
            "fail",
            "the restore staged but the dry-run merge verification failed — the "
            "backup may not import cleanly.",
            measurements,
            bars["p0_2_restore"],
        )
    return _verdict(
        "pass",
        "the backup restored into a throwaway staging dir and the dry-run merge "
        "preview verified; the live corpus was only read, never replaced "
        "(committed=false).",
        measurements,
        bars["p0_2_restore"],
    )


# --------------------------------------------------------------------------- #
#  P0.4 — unlock-at-scale (reads the merged per-phase instrumentation)
# --------------------------------------------------------------------------- #
_COLD_BOOT_HOWTO = (
    "To measure unlock on the FULL corpus: cleanly shut the app down (the power "
    "button / Ctrl-C), then start it and unlock. The per-phase timing of that cold "
    "boot is recorded automatically; re-run this validation immediately after to "
    "read it. The recorded timing reflects the corpus size AT that boot, so measure "
    "with the full corpus present."
)


def _unlock_verdict(last_unlock: dict | None) -> dict:
    """Pure verdict from the last boot's recorded unlock timing (or its absence)."""
    bar = _acceptance_bars()["p0_4_unlock"]
    if not last_unlock or not isinstance(last_unlock, dict):
        return _verdict(
            "not-measurable",
            "no per-phase unlock timing was recorded from the last boot. " + _COLD_BOOT_HOWTO,
            {"bar_ms": _UNLOCK_BAR_MS, "how_to_time_next_cold_boot": _COLD_BOOT_HOWTO},
            bar,
        )
    phases = last_unlock.get("phases") or []
    total_ms = last_unlock.get("synchronous_total_ms")
    derived = False
    if total_ms is None and phases:
        total_ms = round(sum(float(p.get("ms") or 0) for p in phases), 1)
        derived = True
    # A DERIVED total of 0 (phases present but every phase missing its ms) is not a real
    # measurement — never emit a fabricated "0 ms pass". Production always writes
    # synchronous_total_ms, so this only guards a malformed/partial record.
    if derived and total_ms is not None and float(total_ms) <= 0:
        total_ms = None
    slowest = None
    if phases:
        slowest = max(phases, key=lambda p: float(p.get("ms") or 0))
    measurements = {
        "recorded_at": last_unlock.get("at"),
        "synchronous_total_ms": total_ms,
        "phases": phases,
        "slowest_phase": slowest,
        "wal_bytes_before_open": last_unlock.get("wal_bytes_before_open"),
        "bar_ms": _UNLOCK_BAR_MS,
        "method": last_unlock.get("method"),
        "how_to_time_next_cold_boot": _COLD_BOOT_HOWTO,
    }
    if total_ms is None:
        return _verdict(
            "not-measurable",
            "an unlock record exists but carries no total timing. " + _COLD_BOOT_HOWTO,
            measurements,
            bar,
        )
    if float(total_ms) < _UNLOCK_BAR_MS:
        return _verdict(
            "pass",
            f"the last boot's synchronous unlock was {total_ms:.0f} ms, under the "
            f"{_UNLOCK_BAR_MS:.0f} ms bar. Confirm at full scale with a cold boot "
            "on the complete corpus.",
            measurements,
            bar,
        )
    detail = f"the last boot's synchronous unlock was {total_ms:.0f} ms, over the {_UNLOCK_BAR_MS:.0f} ms bar."
    if slowest:
        detail += f" Slowest phase: {slowest.get('phase')} ({float(slowest.get('ms') or 0):.0f} ms)."
    return _verdict("fail", detail, measurements, bar)


def _check_unlock() -> dict:
    try:
        from src.monitoring.forensics import session_forensics

        return _unlock_verdict(session_forensics().get("last_unlock"))
    except Exception as exc:  # noqa: BLE001
        return _verdict(
            "not-measurable",
            f"could not read the unlock instrumentation: {type(exc).__name__}: {exc}. "
            + _COLD_BOOT_HOWTO,
            {"how_to_time_next_cold_boot": _COLD_BOOT_HOWTO},
            _acceptance_bars()["p0_4_unlock"],
        )


# --------------------------------------------------------------------------- #
#  P0.3 — collector RSS over recent passes + memory-guard state
# --------------------------------------------------------------------------- #
_SOAK_HOWTO = (
    "To measure collector memory: go online and let a multi-day collection soak "
    "run, then re-run this validation. Flat RSS across recycled passes is the pass "
    "signal; a climbing curve is the OOM signature to investigate."
)


def _collector_verdict(samples: list[dict], guard_state: dict) -> dict:
    """Pure verdict from the collect-perf samples + memory-guard state."""
    bar = _acceptance_bars()["p0_3_collector"]
    pass_summaries = [s for s in samples if s.get("kind") == "summary"]
    guard_engaged_samples = sum(1 for s in samples if s.get("memory_guard_engaged"))
    base = {
        "samples_read": len(samples),
        "passes_seen": len(pass_summaries),
        "memory_guard": guard_state,
        "guard_engaged_samples": guard_engaged_samples,
        "how_to_soak": _SOAK_HOWTO,
    }
    if not pass_summaries:
        base["note"] = (
            "no completed collection passes in the recent window — the flat-RSS "
            "property needs a live soak."
        )
        return _verdict("not-measurable", "no collector passes to assess. " + _SOAK_HOWTO, base, bar)

    def _pass_max(s: dict) -> float | None:
        rss = s.get("rss_mb") or {}
        v = rss.get("max")
        return float(v) if isinstance(v, (int, float)) else None

    maxes = [(s.get("pass_id"), _pass_max(s)) for s in pass_summaries]
    numeric = [m for _, m in maxes if m is not None]
    base["pass_rss_max_mb"] = [
        {"pass_id": pid, "rss_max_mb": mx} for pid, mx in maxes
    ]
    if len(numeric) < 2:
        base["note"] = (
            "fewer than two passes carry an RSS curve — one pass cannot show a "
            "trend. Needs a longer soak."
        )
        return _verdict("not-measurable", "not enough passes to assess an RSS trend. " + _SOAK_HOWTO, base, bar)

    first, last = numeric[0], numeric[-1]
    peak = max(numeric)
    rise = round(peak - first, 1)
    guard_engaged = bool((guard_state or {}).get("engaged"))
    base["rss_first_pass_max_mb"] = first
    base["rss_last_pass_max_mb"] = last
    base["rss_peak_across_passes_mb"] = peak
    base["rss_rise_first_to_peak_mb"] = rise
    base["climb_threshold_mb"] = _COLLECTOR_CLIMB_ABS_MB
    base["climb_method"] = (
        f"climbing when the peak pass RSS rises >{_COLLECTOR_CLIMB_ABS_MB:g} MB above "
        "the first pass (a sustained absolute rise is the OOM signature at any baseline)."
    )
    # HONEST WINDOW CAVEAT: collect_perf trims its log to ~5000 lines (~2 h), so this
    # reads only the RETAINED tail — a SLOWER multi-day leak may not appear here. The
    # true multi-day acceptance signal is the app surviving days of collection without
    # an OOM: check the memory guard did not stay engaged and the previous session
    # ended cleanly (session forensics), not just this window.
    base["window_caveat"] = (
        "assesses only the retained collect-perf window (~2 h / the passes below); a "
        "slower multi-day leak may not show here — the multi-day signal is the app "
        "surviving days of collection without an OOM (memory-guard state + a clean "
        "previous-session end)."
    )
    if rise > _COLLECTOR_CLIMB_ABS_MB:
        return _verdict(
            "fail",
            f"collector RSS rose {rise:.0f} MB across {len(numeric)} passes "
            f"({first:.0f} -> peak {peak:.0f} MB) — over the {_COLLECTOR_CLIMB_ABS_MB:.0f} "
            "MB climb floor, the OOM signature. Investigate pass recycling / the memory "
            "guard, and run a multi-day soak.",
            base,
            bar,
        )
    guard_note = " The memory guard is currently engaged." if guard_engaged else ""
    return _verdict(
        "pass",
        f"collector RSS rose only {rise:.0f} MB across {len(numeric)} passes "
        f"({first:.0f} -> peak {peak:.0f} MB, under the {_COLLECTOR_CLIMB_ABS_MB:.0f} MB "
        f"floor) over the retained window.{guard_note} Confirm over a multi-day live soak.",
        base,
        bar,
    )


def _check_collector() -> dict:
    try:
        from src.monitoring.collect_perf import recent_samples
        from src.scheduler import memguard

        # Read the FULL retained window (the log self-trims to ~5000 lines / ~2 h), so
        # every pass summary in it is compared — not just the last few minutes.
        return _collector_verdict(recent_samples(5000), memguard.memory_guard.state())
    except Exception as exc:  # noqa: BLE001
        return _verdict(
            "not-measurable",
            f"could not read the collector instrumentation: {type(exc).__name__}: {exc}. "
            + _SOAK_HOWTO,
            {"how_to_soak": _SOAK_HOWTO},
            _acceptance_bars()["p0_3_collector"],
        )


# --------------------------------------------------------------------------- #
#  Verdict + report assembly
# --------------------------------------------------------------------------- #
def _verdict(verdict: str, reason: str, measurements: dict, bar: str) -> dict:
    """One check block. ``verdict`` in {pass, fail, not-measurable-here}."""
    v = "not-measurable-here" if verdict == "not-measurable" else verdict
    return {
        "verdict": v,
        "reason": reason,
        "acceptance_bar": bar,
        "measurements": measurements,
    }


def _summarize(checks: dict[str, dict]) -> dict:
    """A plain conjunction over the checks — NOT a composite score. The maintainer
    reads each check; this only counts the buckets and states the honest gate."""
    passed = sum(1 for c in checks.values() if c["verdict"] == "pass")
    failed = sum(1 for c in checks.values() if c["verdict"] == "fail")
    not_measurable = sum(1 for c in checks.values() if c["verdict"] == "not-measurable-here")
    return {
        "pass": passed,
        "fail": failed,
        "not_measurable_here": not_measurable,
        "no_check_failed": failed == 0,
        "note": (
            "This is a conjunction of the individual checks, NOT a composite "
            "quality score. Read each check. The tag is gated on the data-safety "
            "checks (backup, verify, restore) passing AND unlock/collector being "
            "measured on a cold boot / multi-day soak — a 'not-measurable-here' is "
            "a step still owed on the operator's machine, never a pass."
        ),
    }


def build_p0_report(
    ctx: Any,
    *,
    dest_dir: Path,
    passphrase: str,
    include_newsletters: bool = True,
    measure_incremental: bool = True,
) -> dict:
    """Run every P0 check and assemble the report dict (no file I/O). The
    passphrase is used but never stored in the report."""
    from src.utils.export_envelope import app_version

    # The restore probe stages under the dest drive (which has the room a 100 GB
    # conversion + working copy needs), so it lives OUTSIDE data_dir's janitor scope.
    # Name it with the swept ``.restore-`` prefix so a crash leftover (which for an
    # ENCRYPTED live corpus contains a PLAINTEXT staged copy — an at-rest concern) is
    # reclaimed by sweep_stale_backup_temps, and proactively sweep any OLD leftover on
    # this drive from a previously-crashed probe before we begin.
    from src.backup.stream_backup import sweep_stale_backup_temps

    with contextlib.suppress(Exception):
        sweep_stale_backup_temps(dest_dir)
    staging_root = dest_dir / f".restore-p0-probe-{os.getpid()}"
    checks: dict[str, dict] = {}
    try:
        with contextlib.suppress(Exception):
            ctx.set_progress(total=5, done=0, detail="P0.1 backup")
        backup_check, verify_check = _check_backup(
            ctx,
            dest_dir,
            passphrase,
            include_newsletters=include_newsletters,
            measure_incremental=measure_incremental,
        )
        checks["p0_1_backup"] = backup_check
        checks["p0_1_verify"] = verify_check
        with contextlib.suppress(Exception):
            ctx.set_progress(done=2, detail="P0.2 restore probe")

        # Probe restore whenever the backup COMPLETED (pass OR not-measurable-here — a
        # sub-scale run still wrote a valid set) AND it verified. Only a FAILED or
        # cancelled backup has nothing safe to restore.
        if backup_check["verdict"] != "fail" and verify_check["verdict"] == "pass" and not ctx.stopping:
            staging_root.mkdir(parents=True, exist_ok=True)
            checks["p0_2_restore"] = _check_restore(ctx, dest_dir, passphrase, staging_root)
        else:
            checks["p0_2_restore"] = _verdict(
                "not-measurable",
                "restore was not probed because the backup did not complete and "
                "verify cleanly (or was cancelled).",
                {},
                _acceptance_bars()["p0_2_restore"],
            )

        with contextlib.suppress(Exception):
            ctx.set_progress(done=3, detail="P0.4 unlock")
        checks["p0_4_unlock"] = _check_unlock()
        with contextlib.suppress(Exception):
            ctx.set_progress(done=4, detail="P0.3 collector")
        checks["p0_3_collector"] = _check_collector()
        with contextlib.suppress(Exception):
            ctx.set_progress(done=5, detail="done")
    finally:
        # Never leave the throwaway restore staging behind, on any path.
        import shutil

        shutil.rmtree(staging_root, ignore_errors=True)

    report = {
        "schema": P0_VALIDATION_SCHEMA,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "app_version": app_version(),
        "backup_engine_format": backup_engine_format(),
        "dest_dir": str(dest_dir),
        "cancelled": bool(ctx.stopping),
        "checks": checks,
        "summary": _summarize(checks),
        "method": (
            "Drives the real backup engine against the operator's live corpus, "
            "verifies it, probes a staged restore + dry-run merge PREVIEW (the "
            "restore never writes the live corpus), and reads the merged unlock + collector "
            "instrumentation. Measurements only, no composite score; a check that "
            "cannot run here says why and names the operator step that would."
        ),
    }
    return report


# --------------------------------------------------------------------------- #
#  Persistence (server-side file the download endpoint + debug bundle read)
# --------------------------------------------------------------------------- #
def _report_dir() -> Path:
    from src.paths import data_dir

    d = data_dir() / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_report_atomic(report: dict) -> Path:
    """Write the report to a dated file via a ``.part`` + atomic rename, keeping
    only the newest so the channel is one-shot (old reports just consume disk)."""
    out_dir = _report_dir()
    fname = f"oo-p0-validation-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    final = out_dir / fname
    part = out_dir / (fname + ".part")
    part.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(part, final)
    for old in (*out_dir.glob("oo-p0-validation-*.json"), *out_dir.glob("oo-p0-validation-*.json.part")):
        if old != final:
            with contextlib.suppress(OSError):
                old.unlink()
    return final


def last_p0_validation_report() -> dict:
    """The newest saved report (for the debug bundle / all-diagnostics), or an
    honest stub when none has been run — never fabricates a result."""
    try:
        out_dir = _report_dir()
        files = sorted(out_dir.glob("oo-p0-validation-*.json"))
        if not files:
            return {
                "schema": P0_VALIDATION_SCHEMA,
                "available": False,
                "note": (
                    "no P0 validation has been run yet — run it from Settings -> "
                    "Diagnostics, or POST /api/diagnostics/p0-validation."
                ),
            }
        report = json.loads(files[-1].read_text(encoding="utf-8"))
        report["available"] = True
        report["source_file"] = files[-1].name
        return report
    except Exception as exc:  # noqa: BLE001
        return {"schema": P0_VALIDATION_SCHEMA, "available": False, "error": str(exc)[:300]}


# --------------------------------------------------------------------------- #
#  The job worker (BackgroundJob) + a readable renderer
# --------------------------------------------------------------------------- #
def run_p0_validation(
    ctx: Any,
    *,
    dest_dir: str,
    passphrase: str,
    include_newsletters: bool = True,
    measure_incremental: bool = True,
) -> dict:
    """BackgroundJob worker: validate inputs, run every check, persist the report,
    and return the file location + the full report (the passphrase never lands in
    the returned dict)."""
    if not passphrase:
        raise ValueError("a backup passphrase is required to run the P0 validation")
    dest = validate_dest_dir(dest_dir)
    report: dict | None = None
    try:
        report = build_p0_report(
            ctx,
            dest_dir=dest,
            passphrase=passphrase,
            include_newsletters=include_newsletters,
            measure_incremental=measure_incremental,
        )
    finally:
        # A backup that did NOT complete cleanly (a cancel, a real error, or a crash
        # mid-report) must never leave a partial set that looks complete. Clean it —
        # cleanup_cancelled_build preserves a PREVIOUS complete backup at this dest and
        # removes only unreferenced partials, so it is safe on a fresh dest AND on a
        # refresh. A PASSED backup is a valid backup left for the operator to keep.
        backup_passed = bool(
            report and report.get("checks", {}).get("p0_1_backup", {}).get("verdict") == "pass"
        )
        if not backup_passed:
            with contextlib.suppress(Exception):
                from src.backup.stream_backup import cleanup_cancelled_build

                cleanup_cancelled_build(dest)
    path = _write_report_atomic(report)
    return {"path": str(path), "filename": path.name, "report": report}


def render_p0_validation_text(report: dict) -> str:
    """A plain-text rendering of the report for the operator (the readable half of
    the JSON+readable artifact)."""
    lines: list[str] = []
    lines.append("Open Omniscience — P0 data-safety validation report")
    lines.append("=" * 54)
    lines.append(f"created:            {report.get('created_at')}")
    lines.append(f"app version:        {report.get('app_version')}")
    lines.append(f"backup engine:      {report.get('backup_engine_format')}")
    lines.append(f"destination:        {report.get('dest_dir')}")
    if report.get("cancelled"):
        lines.append("STATUS:             CANCELLED (partial)")
    s = report.get("summary") or {}
    lines.append(
        f"summary:            {s.get('pass', 0)} pass · {s.get('fail', 0)} fail · "
        f"{s.get('not_measurable_here', 0)} not-measurable-here"
    )
    lines.append("")
    order = [
        ("p0_1_backup", "P0.1 backup (streaming, bounded RAM)"),
        ("p0_1_verify", "P0.1 verify (signed manifest + volume checksums)"),
        ("p0_2_restore", "P0.2 restore (staged probe + dry-run merge preview)"),
        ("p0_4_unlock", "P0.4 unlock (< 2 s bar)"),
        ("p0_3_collector", "P0.3 collector (flat RSS across passes)"),
    ]
    checks = report.get("checks") or {}
    for key, title in order:
        c = checks.get(key)
        if not c:
            continue
        lines.append(f"[{c.get('verdict', '?').upper()}] {title}")
        lines.append(f"    {c.get('reason', '')}")
        lines.append("")
    lines.append(s.get("note", ""))
    return "\n".join(lines)
