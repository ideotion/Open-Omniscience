"""The measured OSM ingest as ONE command: what ``scripts/osm_reference_run.py`` runs (0.5 row D, S05-04).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The gate closes row D when one country is ingested on the 2-core, 3.5 GB reference VM with its sizes,
times, peak memory and peak disk RECORDED. This runs the app's own scripts for that
(``osm_ingest.py``, ``osm_history_ingest.py``, optionally ``build_place_gazetteer.py``) as CHILD
PROCESSES of a runner that measures them, and writes ONE JSON report. It measures; it downloads
nothing (the downloads are the app's, consented and sized there), so the report names its inputs by
file name and never goes near the network.

THE MACHINE IS NEVER PUT AT RISK, and each guard says what it protects:

* **THE STORE IS A THROWAWAY.** The children run on a fresh data directory made for this run
  (``OO_DATA_DIR`` forced to it, ``OO_DB_PLAINTEXT`` removed, a random passphrase in the children's
  environment only -- never in argv, a log or the report) so the user's own store is never opened.
  The store is encrypted, because that is the path every real install runs. The runner deletes it at
  the end, as its LAST step, and records the deletion; ``--keep-store`` leaves it for a separate
  gazetteer build and a later ``--cleanup``. A directory is only ever deleted if it carries this
  runner's marker file.
* **THE PREFLIGHT FLOOR** refuses before anything is read when the disk cannot plausibly hold the
  run. The code has NO size model for ``osm.db`` or for the node-location work file (the 190 bytes a
  node of ``reader.DICT_BYTES_PER_NODE`` is MEMORY), so the floor is a GUESS, labelled as one in the
  report: ``floor_factor`` (2) x the input's size, plus the reserve. A previous run's report
  (``--prior-report``) replaces the guess with that run's measured peak disk per input byte.
* **THE RESERVE** (default 2 GiB) is what the machine keeps for itself -- the operating system, the
  report's own write, a shell to log in with. If free disk falls below it DURING a phase, the
  sampler stops that child cleanly (SIGTERM, then SIGKILL after a grace period), the phase is
  recorded ``refused-mid-run`` with the figures, and the rest of the run is not started. The same
  holds for available MEMORY (default 256 MiB): a 3.5 GB VM that is out of memory is a VM the
  operator cannot log into, and the ingest's own spill-to-disk path is what should be absorbing it.
* **THIS TOOL WRITES NO SECRET TO DISK.** A run that deletes its store uses a random passphrase that
  lives only in the children's environment. ``--keep-store`` needs the operator's own
  ``--passphrase-file`` (a file they made, holding any passphrase), so that a separate gazetteer build
  can open the kept store with the same file; the runner only reads it. The runner refuses a workdir
  inside the repository, where the store and its logs would sit in the working tree.
* **THE REPORT** carries no secret and no path outside this run's own data directory: inputs by
  file name, children's error text scrubbed of the passphrase and of every absolute path.

WHAT IS MEASURED, and how: per phase, wall time and CPU time and the kernel's own peak-memory
high-water mark for the child (``wait4``), plus a sampler (once a second by default) for peak
resident memory across the child and its descendants, peak allocated bytes of the data directory
(which holds the spill work file) and the lowest free disk seen. WHAT IS NOT: see ``not_measured`` in
the report -- a fixture-scale run proves the instrument, never the VM.
"""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
MARKER = ".oo-osm-reference-run"
GIB = 1024**3
MIB = 1024**2

#: WHAT THE MACHINE KEEPS FOR ITSELF. Guesses, labelled as such in the report; each protects one thing.
#: 2 GiB of free disk protects the operating system's own writes (journal, logs, swap growth), a login
#: shell the operator can still open, and this report's own write: a VM whose disk is full cannot even
#: record why the run was stopped. Below it the sampler stops the child.
DEFAULT_RESERVE_BYTES = 2 * GIB
#: 256 MiB of available memory protects the machine staying responsive (the VM is 3.5 GB): below it for
#: three samples in a row the kernel's OOM killer is close, and it kills whatever is largest, which may
#: not be this run. The ingest's own spill-to-disk path should have absorbed the pressure first.
DEFAULT_MIN_AVAILABLE_BYTES = 256 * MIB
#: The preflight floor when nothing measured exists: this many times the input's size, plus the reserve.
#: It protects against STARTING a run the disk plainly cannot finish (hours of reading, then a full
#: disk). It is a GUESS: the code has no size model for osm.db or the work file, which is why the
#: report says so and a measured report (``--prior-report``) replaces it.
DEFAULT_FLOOR_FACTOR = 2.0
#: How long a stopped child's process group gets to leave on SIGTERM (so SQLite closes its files
#: cleanly) before SIGKILL: long enough to flush a WAL, short enough that a guard actually guards.
TERMINATE_GRACE_S = 30.0
#: The timeline keeps at most this many points; past it every second point is dropped and the stride
#: doubles. It bounds the REPORT's size on a multi-day run, never the measured peaks (those are exact).
TIMELINE_MAX = 600

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
#  reading the machine
# --------------------------------------------------------------------------- #


def cgroup_memory_limit_bytes() -> int | None:
    """A container's memory limit, or None when there is none to read (``max``, or no cgroup)."""
    for f in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = Path(f).read_text("ascii").strip()
        except OSError:
            continue
        if raw.isdigit() and int(raw) < 1 << 60:
            return int(raw)
    return None


def host_facts(path_on_disk: Path) -> dict:
    """What the report says about the machine: counts and sizes, never a hostname or a user."""
    import psutil

    try:
        import osmium  # type: ignore[import-not-found]

        pyosmium = str(getattr(osmium, "__version__", "") or "installed")
    except ImportError:
        pyosmium = None
    du = shutil.disk_usage(path_on_disk)
    return {
        "cpu_count_logical": os.cpu_count(),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "memory_total_bytes": int(psutil.virtual_memory().total),
        "memory_available_bytes": int(psutil.virtual_memory().available),
        "cgroup_memory_limit_bytes": cgroup_memory_limit_bytes(),
        "disk_total_bytes": int(du.total),
        "disk_free_bytes": int(du.free),
        "platform": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "pyosmium": pyosmium,
    }


def dir_allocated_bytes(path: Path) -> int:
    """Bytes ALLOCATED on disk under ``path`` (``st_blocks``), the figure that runs a disk out."""
    total = 0
    stack = [str(path)]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_blocks * 512
                    except OSError:
                        continue
        except OSError:
            continue
    return total


@dataclass
class Probe:
    """Where the sampler reads free disk and available memory; a test swaps it for a scripted one."""

    free_disk: Callable[[Path], int] = lambda p: int(shutil.disk_usage(p).free)  # noqa: E731
    available_memory: Callable[[], int] = lambda: int(__import__("psutil").virtual_memory().available)  # noqa: E731


# --------------------------------------------------------------------------- #
#  scrubbing: the report holds no secret and no foreign path
# --------------------------------------------------------------------------- #

_ABS_PATH = re.compile(r"(?<![\w.:/>])(?:[A-Za-z]:\\|/)(?:[^\s'\"`:;,()<>\[\]{}|]+)")


def scrub(text: str, *, secrets_: tuple[str, ...] = (), run_dir: Path | None = None) -> str:
    """``text`` without any of ``secrets_`` and with every absolute path reduced to its file name.

    A path inside this run's own directory becomes ``<run>/...``; any other becomes just its last
    component. The report is a document an operator pastes or attaches, so a traceback's home
    directory and the repository's location have no business in it.
    """
    out = text
    for s in secrets_:
        if s:
            out = out.replace(s, "<redacted>")
    rd = str(run_dir) if run_dir else None

    def _one(m: re.Match) -> str:
        p = m.group(0)
        if rd and (p == rd or p.startswith(rd + os.sep)):
            return "<run>" + p[len(rd):]
        return p.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1] or "<path>"

    return _ABS_PATH.sub(_one, out)


def _tail(path: Path, lines: int = 12, *, secrets_: tuple[str, ...], run_dir: Path) -> str:
    try:
        raw = path.read_text("utf-8", errors="replace")
    except OSError:
        return ""
    return scrub("\n".join(raw.strip().splitlines()[-lines:]), secrets_=secrets_, run_dir=run_dir)


# --------------------------------------------------------------------------- #
#  the preflight
# --------------------------------------------------------------------------- #


def preflight(
    *,
    extract_bytes: int,
    history_bytes: int | None,
    free_bytes: int,
    reserve_bytes: int,
    floor_factor: float = DEFAULT_FLOOR_FACTOR,
    prior_report: dict | None = None,
    min_free_override: int | None = None,
) -> dict:
    """The disk the run needs free, how that was derived, and whether the disk has it.

    ``prior_report``'s measured ``peak_data_dir_bytes`` per input byte (the ingest phase) replaces
    the guessed factor. An override (``--min-free-gb``) replaces both. The basis is stated either way.
    """
    ratio = None
    basis = f"GUESS: {floor_factor:g} x the extract's size + the reserve (the code has no size model for osm.db or the work file)"
    if prior_report:
        try:
            ph = next(p for p in prior_report["phases"] if p["name"] == "ingest" and p.get("peak_data_dir_bytes"))
            inp = prior_report["inputs"]["extract"]["bytes"]
            ratio = ph["peak_data_dir_bytes"] / inp * 1.25
            basis = (f"MEASURED by the prior report: its ingest peaked at {ph['peak_data_dir_bytes']} bytes for a "
                     f"{inp}-byte extract, x1.25 margin, + the reserve")
        except (KeyError, StopIteration, ZeroDivisionError, TypeError):
            ratio = None
    factor = ratio if ratio is not None else floor_factor
    ingest_need = int(factor * extract_bytes) + reserve_bytes
    # The history cut is read FROM its file and written to the same store: the ingest's own measured
    # (or guessed) footprint is the only comparable figure there is, and it is labelled as such.
    history_need = (int(factor * extract_bytes) + reserve_bytes) if history_bytes else None
    needed = min_free_override if min_free_override is not None else max(ingest_need, history_need or 0)
    return {
        "free_bytes": free_bytes,
        "needed_bytes": needed,
        "reserve_bytes": reserve_bytes,
        "floor_basis": ("operator override (--min-free-gb)" if min_free_override is not None else basis),
        "ok": free_bytes >= needed,
    }


# --------------------------------------------------------------------------- #
#  running one child under measurement
# --------------------------------------------------------------------------- #


@dataclass
class PhaseSpec:
    name: str
    argv: list[str]


@dataclass
class PhaseResult:
    name: str
    status: str = "ok"  # ok | failed | refused | refused-mid-run | interrupted
    exit_code: int | None = None
    wall_seconds: float = 0.0
    cpu_user_seconds: float | None = None
    cpu_system_seconds: float | None = None
    peak_rss_bytes: int | None = None
    peak_rss_bytes_kernel: int | None = None
    peak_rss_bytes_sampled: int | None = None
    peak_data_dir_bytes: int = 0
    disk_free_before_bytes: int | None = None
    disk_free_after_bytes: int | None = None
    disk_free_min_bytes: int | None = None
    memory_available_min_bytes: int | None = None
    reason: str | None = None
    app_report: dict | None = None
    error_tail: str | None = None
    samples: int = 0
    timeline: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _children_rss(pid: int) -> int | None:
    import psutil

    try:
        p = psutil.Process(pid)
        total = p.memory_info().rss
        for c in p.children(recursive=True):
            try:
                total += c.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return int(total)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def run_phase(
    spec: PhaseSpec,
    *,
    env: dict[str, str],
    data_dir: Path,
    log_dir: Path,
    run_dir: Path,
    reserve_bytes: int,
    min_available_bytes: int,
    probe: Probe,
    sample_seconds: float,
    secrets_: tuple[str, ...],
) -> PhaseResult:
    """Run one child to its end (or its refusal) and measure it. Never raises for a child's failure."""
    res = PhaseResult(spec.name)
    log_dir.mkdir(parents=True, exist_ok=True)
    out_f, err_f = log_dir / f"{spec.name}.out", log_dir / f"{spec.name}.err"
    res.disk_free_before_bytes = probe.free_disk(run_dir)
    res.disk_free_min_bytes = res.disk_free_before_bytes
    stop = threading.Event()
    refusal: list[str] = []
    stride = {"n": 1, "i": 0}
    t0 = time.monotonic()

    with open(out_f, "wb") as fo, open(err_f, "wb") as fe:
        try:
            # Its own session: the child leads a process GROUP, so a stop reaches every descendant and
            # none keeps writing to the disk this guard is protecting after the child itself is gone.
            proc = subprocess.Popen(spec.argv, env=env, stdout=fo, stderr=fe, cwd=str(ROOT), start_new_session=True)  # noqa: S603
        except OSError as exc:
            res.status, res.reason = "failed", f"the phase could not be started ({type(exc).__name__})"
            res.wall_seconds = round(time.monotonic() - t0, 3)
            res.disk_free_after_bytes = probe.free_disk(run_dir)
            return res

        def _signal_group(sig: int) -> None:
            # The child is not reaped until the main thread's wait4 returns, so its pid cannot have been
            # reused while this runs: the group id is still ours.
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        def _terminate(reason: str) -> None:
            refusal.append(reason)
            _signal_group(signal.SIGTERM)
            deadline = time.monotonic() + TERMINATE_GRACE_S
            while time.monotonic() < deadline and not stop.is_set():
                time.sleep(0.1)
            if not stop.is_set():
                _signal_group(signal.SIGKILL)

        def _sample() -> None:
            low_mem_strikes = 0
            while not stop.is_set():
                rss = _children_rss(proc.pid)
                data = dir_allocated_bytes(data_dir)
                free = probe.free_disk(run_dir)
                avail = probe.available_memory()
                res.samples += 1
                if rss is not None:
                    res.peak_rss_bytes_sampled = max(res.peak_rss_bytes_sampled or 0, rss)
                res.peak_data_dir_bytes = max(res.peak_data_dir_bytes, data)
                res.disk_free_min_bytes = min(res.disk_free_min_bytes if res.disk_free_min_bytes is not None else free, free)
                res.memory_available_min_bytes = min(
                    res.memory_available_min_bytes if res.memory_available_min_bytes is not None else avail, avail)
                stride["i"] += 1
                if stride["i"] % stride["n"] == 0:
                    res.timeline.append({"t": round(time.monotonic() - t0, 2), "rss": rss, "data_dir": data, "free": free})
                    if len(res.timeline) > TIMELINE_MAX:
                        res.timeline = res.timeline[::2]
                        stride["n"] *= 2
                if free < reserve_bytes and not refusal:
                    _terminate(f"free disk fell to {free} bytes, below the {reserve_bytes}-byte reserve")
                    return
                low_mem_strikes = low_mem_strikes + 1 if avail < min_available_bytes else 0
                if low_mem_strikes >= 3 and not refusal:
                    _terminate(f"available memory stayed at {avail} bytes, below the {min_available_bytes}-byte minimum")
                    return
                stop.wait(sample_seconds)

        sampler = threading.Thread(target=_sample, name=f"ref-run-sampler-{spec.name}", daemon=True)
        sampler.start()
        status = None
        usage = None
        try:
            if hasattr(os, "wait4"):
                _pid, status, usage = os.wait4(proc.pid, 0)
                proc.returncode = os.waitstatus_to_exitcode(status)
            else:  # pragma: no cover - the VM is Linux; kept so the script still runs elsewhere
                proc.wait()
        except KeyboardInterrupt:
            res.status = "interrupted"
            res.reason = "the operator interrupted the run"
            _signal_group(signal.SIGTERM)
            deadline = time.monotonic() + TERMINATE_GRACE_S
            status = None
            while time.monotonic() < deadline:
                pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
                if pid:
                    break
                time.sleep(0.1)
            else:
                _signal_group(signal.SIGKILL)
                _pid, status, usage = os.wait4(proc.pid, 0)
            proc.returncode = os.waitstatus_to_exitcode(status)
        finally:
            stop.set()
            sampler.join(timeout=5)

    res.wall_seconds = round(time.monotonic() - t0, 3)
    res.exit_code = proc.returncode
    if usage is not None:
        res.cpu_user_seconds = round(usage.ru_utime, 3)
        res.cpu_system_seconds = round(usage.ru_stime, 3)
        # Linux reports ru_maxrss in KiB.
        res.peak_rss_bytes_kernel = int(usage.ru_maxrss) * 1024 if sys.platform.startswith("linux") else int(usage.ru_maxrss)
    peaks = [v for v in (res.peak_rss_bytes_kernel, res.peak_rss_bytes_sampled) if v]
    res.peak_rss_bytes = max(peaks) if peaks else None
    res.disk_free_after_bytes = probe.free_disk(run_dir)
    if res.status != "interrupted":
        if refusal:
            res.status, res.reason = "refused-mid-run", refusal[0]
        elif proc.returncode == 0:
            res.status = "ok"
        elif proc.returncode == 2:
            res.status = "refused"  # the app's own scripts exit 2 when they refuse by name
        else:
            res.status = "failed"
    try:
        raw = out_f.read_text("utf-8").strip()
        if raw.startswith("{"):
            res.app_report = json.loads(raw)
        elif raw:
            res.error_tail = scrub(raw[-600:], secrets_=secrets_, run_dir=run_dir)
    except (OSError, ValueError):
        pass
    if res.status != "ok":
        tail = _tail(err_f, secrets_=secrets_, run_dir=run_dir)
        res.error_tail = (res.error_tail + "\n" if res.error_tail else "") + tail if tail else res.error_tail
    return res


# --------------------------------------------------------------------------- #
#  the run
# --------------------------------------------------------------------------- #


def _scrub_obj(obj, *, secrets_: tuple[str, ...], run_dir: Path | None):
    """``scrub`` applied to every string of a JSON-shaped value: the last line of defence for the report."""
    if isinstance(obj, str):
        return scrub(obj, secrets_=secrets_, run_dir=run_dir)
    if isinstance(obj, list):
        return [_scrub_obj(v, secrets_=secrets_, run_dir=run_dir) for v in obj]
    if isinstance(obj, dict):
        return {k: _scrub_obj(v, secrets_=secrets_, run_dir=run_dir) for k, v in obj.items()}
    return obj


def _file_facts(p: Path | None) -> dict | None:
    if p is None:
        return None
    return {"name": p.name, "bytes": p.stat().st_size}


def _delete_store(run_dir: Path, probe: Probe) -> dict:
    """Delete this runner's own run directory, only if it carries the marker. Records what went."""
    t0 = time.monotonic()
    if not (run_dir / MARKER).is_file():
        return {"deleted": False, "refused": "the directory does not carry this runner's marker; nothing was removed"}
    before = dir_allocated_bytes(run_dir)
    free_before = probe.free_disk(run_dir.parent)
    shutil.rmtree(run_dir)
    return {
        "deleted": True,
        "bytes_freed": before,
        "seconds": round(time.monotonic() - t0, 3),
        "disk_free_before_bytes": free_before,
        "disk_free_after_bytes": probe.free_disk(run_dir.parent),
    }


def cleanup(run_dir: Path, *, probe: Probe | None = None) -> dict:
    """``--cleanup``: delete a KEPT store, recorded the same way as the end-of-run deletion."""
    return _delete_store(Path(run_dir), probe or Probe())


#: The gazetteer modes the runner offers. ``online`` is deliberately absent: the throwaway store carries
#: none of the operator's persisted transport settings (Tor, a proxy), so a Wikidata join run inside it
#: would reach the network on a different transport than the operator chose -- a silent downgrade. The
#: join is a separate step, on a KEPT store, with the operator's own OO_FETCH_MODE / OO_HTTP_PROXY.
GAZETTEER_MODES = ("off", "osm-only")


def build_phases(
    *,
    extract: Path,
    country: str,
    history: Path | None,
    reader: str | None,
    gazetteer: str,
    gazetteer_out: Path | None,
    python: str | None = None,
) -> list[PhaseSpec]:
    py = python or sys.executable
    reader_args = ["--reader", reader] if reader else []
    phases = [PhaseSpec("ingest", [py, str(ROOT / "scripts" / "osm_ingest.py"), "--extract", str(extract),
                                   "--country", country, *reader_args])]
    if history is not None:
        phases.append(PhaseSpec("history", [py, str(ROOT / "scripts" / "osm_history_ingest.py"), "--history", str(history),
                                            "--extract", str(extract), "--country", country, *reader_args]))
    if gazetteer != "off":
        assert gazetteer_out is not None
        how = ["--no-wikidata"]  # the online join is NEVER run inside the throwaway store: see build_phases below
        phases.append(PhaseSpec("gazetteer", [py, str(ROOT / "scripts" / "build_place_gazetteer.py"), "--country", country,
                                              "--out", str(gazetteer_out), *how]))
    return phases


def not_measured(*, history: bool, gazetteer: str, kernel_peak: bool) -> list[str]:
    out = [
        "the download of the extract and of the history file: they run in the app, consented and sized there",
        "any time or memory on a machine other than the one this ran on: this report is that machine's, no other's",
        "a peak shorter than the sampler's interval is seen only through the kernel's own high-water mark (peak_rss_bytes_kernel)",
    ]
    if not history:
        out.append("the history phase: not run (no --history)")
    if gazetteer == "off":
        out.append("the gazetteer phase: not run (--gazetteer off)")
    elif gazetteer == "osm-only":
        out.append("the Wikidata join of the gazetteer: not run here (--gazetteer osm-only); it needs the operator's own transport setting, "
                   "so it is a separate step on a kept store: scripts/build_place_gazetteer.py --online")
    if not kernel_peak:
        out.append("the kernel's peak-memory high-water mark: unavailable on this platform; the sampled peak stands alone")
    return out


def run(
    *,
    extract: Path,
    country: str,
    history: Path | None = None,
    workdir: Path | None = None,
    reader: str | None = None,
    gazetteer: str = "off",
    gazetteer_out: Path | None = None,
    keep_store: bool = False,
    passphrase_file: Path | None = None,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
    min_available_bytes: int = DEFAULT_MIN_AVAILABLE_BYTES,
    floor_factor: float = DEFAULT_FLOOR_FACTOR,
    min_free_override: int | None = None,
    prior_report: dict | None = None,
    sample_seconds: float = 1.0,
    probe: Probe | None = None,
    phases_override: list[PhaseSpec] | None = None,
    plan_only: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[dict, Path | None]:
    """Run the phases under measurement and return ``(report, run_dir)``.

    ``run_dir`` is None when no store was made (a plan, or a preflight refusal) or when it was
    deleted; with ``keep_store`` it is the directory to hand to ``--cleanup`` later.
    ``phases_override`` exists for tests (a scripted child in place of the app's scripts).
    """
    if keep_store and passphrase_file is None:
        raise ValueError("--keep-store needs --passphrase-file: a file you make holding any passphrase (for example "
                         "`python -c \"import secrets; print(secrets.token_urlsafe(24))\" > key`), so the later "
                         "gazetteer build can open the kept store; this tool writes no secret to disk")
    if passphrase_file is not None:
        try:
            passphrase = Path(passphrase_file).read_text("utf-8").strip()
        except OSError as exc:
            raise ValueError(f"cannot read the passphrase file ({type(exc).__name__})") from None
        if not passphrase:
            raise ValueError("the passphrase file is empty")
    else:
        passphrase = secrets.token_urlsafe(24)
    if gazetteer not in GAZETTEER_MODES:
        raise ValueError(f"--gazetteer {gazetteer!r} is not offered here; the Wikidata join is a separate step on a kept store")
    probe = probe or Probe()
    extract = Path(extract).resolve()  # the children run from the repository, so a relative path would not find it
    if not extract.is_file():
        raise FileNotFoundError(f"the extract {extract.name} is not on disk; download it in the app first "
                                "(Settings, the offline-map downloads, under the online consent)")
    if history is not None:
        history = Path(history).resolve()
    if history is not None and not Path(history).is_file():
        raise FileNotFoundError(f"the history file {Path(history).name} is not on disk; download it in the app first "
                                "(Settings, OpenStreetMap, Full history)")
    base = Path(workdir).resolve() if workdir else extract.parent
    if base == ROOT or ROOT in base.parents:
        raise ValueError("the throwaway store must live outside the repository (its passphrase file and logs would sit "
                         "in the working tree); pass --workdir elsewhere")
    base.mkdir(parents=True, exist_ok=True)
    started = now()
    host = host_facts(base)
    pf = preflight(
        extract_bytes=extract.stat().st_size,
        history_bytes=Path(history).stat().st_size if history else None,
        free_bytes=probe.free_disk(base),
        reserve_bytes=reserve_bytes,
        floor_factor=floor_factor,
        prior_report=prior_report,
        min_free_override=min_free_override,
    )
    report: dict = {
        "schema_version": SCHEMA_VERSION,
        "started_at": started.isoformat(),
        "status": "ok",
        "country": country,
        "host": host,
        "inputs": {"extract": _file_facts(extract), "history": _file_facts(Path(history)) if history else None},
        "preflight": pf,
        "guards": {
            "reserve_bytes": reserve_bytes,
            "reserve_protects": "the operating system, a login shell and this report's own write",
            "min_available_memory_bytes": min_available_bytes,
            "min_available_memory_protects": "the machine staying responsive; the ingest's spill-to-disk path should absorb pressure first",
            "sample_seconds": sample_seconds,
        },
        "phases": [],
        "store": {"kept": False},
        "not_measured": [],
    }
    kernel_peak = hasattr(os, "wait4")
    if plan_only:
        report["status"] = "plan"
        report["not_measured"] = ["everything: --plan runs nothing"]
        report["finished_at"] = now().isoformat()
        return report, None
    if not pf["ok"]:
        report["status"] = "refused-preflight"
        report["reason"] = (f"free disk is {pf['free_bytes']} bytes and the run needs {pf['needed_bytes']} "
                            f"({pf['floor_basis']})")
        report["not_measured"] = ["everything: the preflight refused before any phase started"]
        report["finished_at"] = now().isoformat()
        return report, None

    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    run_dir = base / f"oo-osm-reference-run-{stamp}-{secrets.token_hex(3)}"
    data_dir = run_dir / "data"
    data_dir.mkdir(parents=True)
    (run_dir / MARKER).write_text("a throwaway store made by scripts/osm_reference_run.py; safe to delete\n", "utf-8")
    secrets_ = (passphrase,)
    env = {k: v for k, v in os.environ.items()
           if k not in ("OO_DB_PLAINTEXT", "OO_DATA_VOLUME_ID", "OO_DB_PASSPHRASE", "OO_DATA_DIR")}
    env.update({"OO_DATA_DIR": str(data_dir), "OO_DB_PASSPHRASE": passphrase, "PYTHONUNBUFFERED": "1"})

    g_out = Path(gazetteer_out).resolve() if gazetteer_out else None
    if gazetteer != "off" and g_out is None:
        g_out = base / f"places_gazetteer-{stamp}.yml"
    specs = phases_override if phases_override is not None else build_phases(
        extract=extract, country=country, history=Path(history) if history else None, reader=reader,
        gazetteer=gazetteer, gazetteer_out=g_out)

    try:
        for spec in specs:
            res = run_phase(spec, env=env, data_dir=data_dir, log_dir=run_dir / "logs", run_dir=run_dir,
                            reserve_bytes=reserve_bytes, min_available_bytes=min_available_bytes, probe=probe,
                            sample_seconds=sample_seconds, secrets_=secrets_)
            report["phases"].append(res.to_dict())
            if res.status != "ok":
                report["status"] = res.status if res.status in ("refused-mid-run", "interrupted") else (
                    "refused" if res.status == "refused" else "failed")
                report["reason"] = f"phase {spec.name}: {res.reason or res.status}"
                break
            if spec.name == "ingest" and res.app_report:
                report["outputs"] = {"osm_db_bytes": res.app_report.get("osm_db_bytes"),
                                     "extract_bytes": res.app_report.get("extract_bytes")}
        # What the app's own header read says about the lane file: the encrypted path really ran.
        try:
            from src.database.connect import is_encrypted_file

            lane = next(iter(sorted(data_dir.glob("osm.db"))), None)
            report["at_rest"] = {"osm_db_encrypted_by_header": (is_encrypted_file(lane) if lane else None),
                                 "configured": "encrypted (a throwaway passphrase)"}
        except Exception:  # noqa: BLE001 - a reading that fails is a null, never a fabricated yes
            report["at_rest"] = {"osm_db_encrypted_by_header": None, "configured": "encrypted (a throwaway passphrase)"}
        if g_out is not None and g_out.is_file():
            import hashlib

            report.setdefault("outputs", {})["gazetteer"] = {
                "name": g_out.name, "bytes": g_out.stat().st_size,
                "sha256": hashlib.sha256(g_out.read_bytes()).hexdigest()}
    finally:
        # THE THIRD STEP: the throwaway store goes, and the report says so. A kept store is left on purpose.
        if keep_store:
            report["store"] = {"kept": True, "note": "left for a separate gazetteer build; delete it with --cleanup"}
            kept_dir: Path | None = run_dir
        else:
            report["store"] = {"kept": False, **_delete_store(run_dir, probe)}
            kept_dir = None
    report["not_measured"] = not_measured(history=history is not None, gazetteer=gazetteer, kernel_peak=kernel_peak)
    report["finished_at"] = now().isoformat()
    return _scrub_obj(report, secrets_=secrets_, run_dir=run_dir), kept_dir


def write_report(report: dict, path: Path) -> None:
    """Write the report atomically. It is a measurement, not a secret; it names its inputs by file name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", "utf-8")
    tmp.replace(path)
