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
* **THE RUNNER DYING DOES NOT LEAVE THE CHILD RUNNING.** SIGHUP (a dropped SSH session), SIGTERM and
  Ctrl-C stop the child's whole process group, delete the store and still write the report (signals within 250 ms of
  each other are ONE event; a second kills the group at once; a third SIGKILLs the group and gives the runner the
  signal's default action -- SIGTERM for a Ctrl-\\ -- so it leaves NO report and keeps the store, which ``--cleanup`` removes);
  ``PR_SET_PDEATHSIG`` is the backstop for a runner that is KILLED, where no handler can run. After
  EVERY child exit the group is swept with SIGKILL before the store is deleted, so a helper that
  ignored SIGTERM, or outlived a clean exit, cannot write into a store being removed.
* **THIS TOOL WRITES NO SECRET TO DISK.** A run that deletes its store uses a random passphrase that
  lives only in the children's environment. ``--keep-store`` needs the operator's own
  ``--passphrase-file`` (a file they made, holding any passphrase), so that a separate gazetteer build
  can open the kept store with the same file; the runner only reads it. The runner refuses a workdir
  inside the repository, where the store and its logs would sit in the working tree. The children's RAW logs
  (``logs/``) are deleted from any store the run leaves (kept, survived by a group, half-deleted, or abandoned by a third
  signal); the report carries their scrubbed tails.
* **THE REPORT** carries no secret and no path outside this run's own data directory: inputs by
  file name, children's error text scrubbed of the passphrase and of every absolute path.

WHAT IS MEASURED, and how: per phase, wall time and CPU time and the kernel's own peak-memory
high-water mark for the child (``wait4``), plus a sampler (once a second by default) for peak
resident memory across the child and its descendants, peak allocated bytes of the data directory and the
run's own temp directory (which hold the spill work file and SQLite's temp files) and the lowest free disk seen. WHAT IS NOT: see ``not_measured`` in
the report -- a fixture-scale run proves the instrument, never the VM.
"""

from __future__ import annotations

import contextlib
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
from typing import Any

from src.monitoring.secret_scrub import record_text, scrubbed

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
#: What real extracts measured (2026-10-15, docs/audit/osm-real-extract-2026-10-15): osm.db settled at 6.0 times the
#: bytes of Liechtenstein's own extract (2013) and 7.5 times a Dutch city's (Utrecht), about 500 bytes per kept object.
#: The runner is handed the CONTINENT file and cannot know what share of it the country is, so 7.5 x the file is the
#: worst case (the country is nearly all of it, as the United States is of North America's), not the expected one.
OSM_DB_PER_PBF_BYTE_LOW = 6.0
OSM_DB_PER_PBF_BYTE_HIGH = 7.5
#: Above 512 MiB the pyosmium reader keeps node locations in a file, and a real extract holds about 0.11 nodes a byte
#: (Liechtenstein 65.7 k nodes in 593 KB, Utrecht 1.16 M in 11.8 MB). Forcing the file on the 16 x Utrecht composite
#: measured +473 MB of peak disk for 18.5 M nodes, about 26 bytes a node (more than the 16 of the entries themselves): 26 x
#: 0.11 = 2.9 bytes per extract byte while the cut runs, rounded up to 3. The file is deleted when the ingest ends, so it
#: counts toward the PEAK only. The pure-Python reader's spill file starts at any size once its dict passes the memory
#: budget, which this figure does not cover (the preflight is not told the reader).
LOCATION_INDEX_BYTES_PER_PBF_BYTE = 3.0
#: How long a stopped child's process group gets to leave on SIGTERM (so SQLite closes its files
#: cleanly) before SIGKILL: long enough to flush a WAL, short enough that a guard actually guards.
#: It never extends the disk risk: inside the grace the sampler's disk read continues, and free disk
#: below half the reserve ends the grace at once with SIGKILL (a disk writing 150 MB/s would otherwise
#: spend the whole reserve in 14 s).
TERMINATE_GRACE_S = 30.0
#: The sampler's interval is kept within these bounds. Below 0.05 s the sampler's own work (a process-tree
#: walk and a directory scan) becomes the CPU it is measuring; above 10 s a disk crossing the reserve goes
#: unseen for long enough to fill the disk before the stop.
SAMPLE_SECONDS_MIN = 0.05
SAMPLE_SECONDS_MAX = 10.0
#: The timeline keeps at most this many points; past it every second point is dropped and the stride
#: doubles. It bounds the REPORT's size on a multi-day run, never the measured peaks (those are exact).
TIMELINE_MAX = 600
#: How long the runner waits, after SIGKILLing the child's group, for every member to be gone before it
#: reports one as surviving (a process in uninterruptible I/O on a slow disk can take a while to leave).
GROUP_GONE_TIMEOUT_S = 30.0

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

_ABS_PATH = re.compile(r"(?<![\w.>/])(?:[A-Za-z]:\\|/(?!/))(?:[^\s'\"`:;,()<>\[\]{}|]+)")
# ``scheme:///path`` and ``sqlite:////path``: a URL whose path is a file path (three or more slashes).
_FILE_URL = re.compile(r"(?P<scheme>\b[A-Za-z][\w+.-]*:)/{3,}(?P<path>[^\s'\"`:;,()<>\[\]{}|]+)")


def scrub(text: str, *, secrets_: tuple[str, ...] = (), run_dir: Path | None = None,
          roots: tuple[tuple[str, str], ...] = (), paths_only: bool = False) -> str:
    """``text`` without any of ``secrets_`` and with every absolute path reduced to its file name.

    The secrets go through the shared :func:`src.monitoring.secret_scrub.scrubbed`, which also takes out every passphrase
    this process holds (the operator's own session or ``OO_DB_PASSPHRASE``, whether or not it was handed in) and withholds a
    text that holds a secret too short to take out. ``paths_only=True`` is the PATHS-ONLY pass (the finished report, whose verdict words the exit code reads and
    whose engine texts were scrubbed where they were made).

    The run's own directory, and every known root in ``roots`` (``(path, label)`` pairs: the
    repository, the home directory, the input and output folders), are replaced LITERALLY first, so a
    directory name with a space in it cannot slip past the pattern. Any other absolute path becomes
    just its last component (a path with a space in an UNKNOWN directory keeps the fragment after
    the space: the pattern cannot know where such a path ends). The report is a document an operator
    pastes or attaches, so a traceback's home directory and the repository's location have no
    business in it.
    """
    out = text if paths_only else scrubbed(text, *secrets_)
    if run_dir:
        out = out.replace(str(run_dir), "<run>")
    for path, label in roots:
        if path and len(path) > 1:
            out = out.replace(path, label)

    def _base(p: str) -> str:
        return p.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1] or "<path>"

    out = _FILE_URL.sub(lambda m: m.group("scheme") + _base(m.group("path")), out)
    return _ABS_PATH.sub(lambda m: _base(m.group(0)), out)


#: How much of a failing child's stderr the report keeps: the last 12 lines (a traceback's tail, where the
#: cause is) and 600 characters of stdout. They bound the REPORT's size and what an operator pastes.
def _tail(path: Path, lines: int = 12, *, secrets_: tuple[str, ...], run_dir: Path,
          roots: tuple[tuple[str, str], ...] = ()) -> str:
    try:
        raw = path.read_text("utf-8", errors="replace")
    except OSError:
        return ""
    # SCRUB FIRST, then cut: a passphrase that straddles the cut (or holds a newline) would otherwise keep its tail.
    clean = scrub(raw, secrets_=secrets_, run_dir=run_dir, roots=roots)
    return "\n".join(clean.strip().splitlines()[-lines:])


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
            # Only a phase that FINISHED measures the whole footprint: a stopped or failed one peaked early.
            ph = next(p for p in prior_report["phases"]
                      if p["name"] == "ingest" and p.get("status") == "ok"
                      and (p.get("peak_data_dir_bytes") or p.get("disk_used_peak_bytes")))
            inp = prior_report["inputs"]["extract"]["bytes"]
            # The larger of the two measures: the directory scan cannot see SQLite's unlinked temp files, the
            # disk's own loss counts them (and anyone else writing to that disk).
            peak = max(int(ph.get("peak_data_dir_bytes") or 0), int(ph.get("disk_used_peak_bytes") or 0))
            # x1.25: the prior run's peak plus a quarter, because the next extract's footprint need not match
            # it byte for byte and a floor that is exactly the last peak refuses nothing it should.
            ratio = peak / inp * 1.25
            basis = (f"MEASURED by the prior report: its ingest peaked at {peak} bytes (the larger of the data directory's "
                     f"size and the disk's loss) for a {inp}-byte extract, x1.25 margin, + the reserve")
        except (KeyError, StopIteration, ZeroDivisionError, TypeError, ValueError):
            ratio = None
    factor = ratio if ratio is not None else floor_factor
    footprint = int(factor * extract_bytes)
    # The history phase writes into the SAME store after the ingest, so its footprint ADDS to the
    # ingest's (one reserve covers both). The code has no size model for it either: the figure assumed
    # is one more ingest-sized footprint, and the basis says so.
    history_footprint = footprint if history_bytes else 0
    if history_bytes:
        basis += "; the history phase is assumed to add one more ingest-sized footprint (also a guess)"
    needed = min_free_override if min_free_override is not None else footprint + history_footprint + reserve_bytes
    ok = free_bytes >= needed
    # THE WORST CASE, EXTRAPOLATED FROM TWO SMALL MEASUREMENTS (a 0.6 MB and a 12 MB file settled at 6.0 and 7.5 x), NOT
    # MEASURED AT THIS SIZE: the country is nearly the whole file, so osm.db is the high ratio of it, plus the node-location
    # file while the cut runs when the file is large enough to have one. It only WARNS (a refusal at 10.5 x would turn France
    # in Europe's 28 GB away from any disk under about 300 GB, though France is a sixth of that file); the mid-run sampler
    # stops a run whose disk reaches the reserve, which is the protection.
    from src.osm.reader import PyosmiumExtract

    per_byte = OSM_DB_PER_PBF_BYTE_HIGH + (LOCATION_INDEX_BYTES_PER_PBF_BYTE if extract_bytes > PyosmiumExtract.ON_DISK_ABOVE else 0)
    worst_footprint = int(per_byte * extract_bytes)
    worst = worst_footprint * (2 if history_bytes else 1) + reserve_bytes
    warning = None
    if ok and ratio is None and min_free_override is None and free_bytes < worst:
        warning = (f"free disk is {free_bytes} bytes; if this country is most of the {extract_bytes}-byte extract the run can need "
                   f"{worst} (osm.db at {OSM_DB_PER_PBF_BYTE_LOW:g} to {OSM_DB_PER_PBF_BYTE_HIGH:g} times the country's own bytes, "
                   f"settled sizes of two small real extracts scaled up, NOT measured at this size, plus the node-location file for a large one"
                   f"{', and the history phase adds its own footprint (counted twice here)' if history_bytes else ''}). "
                   f"It starts: the sampler stops it cleanly if the disk reaches the reserve. Pass --min-free-gb to refuse instead")
    return {
        "free_bytes": free_bytes,
        "needed_bytes": needed,
        "worst_case_bytes": worst,
        "warning": warning,
        "reserve_bytes": reserve_bytes,
        "floor_basis": ("operator override (--min-free-gb)" if min_free_override is not None else basis),
        "ok": ok,
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
    #: The most disk the machine lost during the phase (free before - lowest free): counts SQLite's unlinked
    #: temp files, which a directory scan cannot see (it also counts anyone else writing to that disk).
    disk_used_peak_bytes: int | None = None
    #: A signal to the runner that landed while this phase was alive, when it did not change the phase's class.
    interrupted_by: str | None = None
    #: True when a process of the child's group was STILL alive after the SIGKILL sweep and the wait: the
    #: store is then never deleted under it.
    group_survived: bool = False
    #: True when the sampler thread did not stop within its join timeout: no further phase is started.
    sampler_alive: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _phase_status(*, refusal: str | None, returncode: int | None, signalled: bool) -> str:
    """How a finished phase is classed. A guard's stop keeps its own class and reason (a signal on top of
    it is recorded as ``interrupted_by``, never allowed to rewrite what the guard did). ``signalled`` means
    the runner TOLD the child to stop: whatever it then exited with, the phase did not run to its own end."""
    if refusal:
        return "refused-mid-run"
    if signalled:
        return "interrupted"
    if returncode == 0:
        return "ok"
    return "refused" if returncode == 2 else "failed"  # the app's own scripts exit 2 when they refuse by name


def _group_alive(pgid: int) -> bool:
    """Is any NON-zombie process still in process group ``pgid``? (The group id stays reserved while any
    member lives, so this cannot be fooled by a recycled number.)"""
    import psutil

    for p in psutil.process_iter(["pid", "status"]):
        try:
            if p.info["status"] != psutil.STATUS_ZOMBIE and os.getpgid(p.info["pid"]) == pgid:
                return True
        except (ProcessLookupError, PermissionError, psutil.Error):
            continue
    return False


def _wait_group_gone(pgid: int, timeout_s: float) -> bool:
    """SIGKILL does not make a process vanish at once (a write in flight, a process in uninterruptible
    I/O): wait until no live member is left, up to ``timeout_s``. False means a member is STILL alive."""
    deadline = time.monotonic() + timeout_s
    while True:
        if not _group_alive(pgid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)


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


class _Interrupts:
    """What a SIGHUP / SIGTERM / SIGINT did to this run, shared by the handler and the phase runner.

    The handler never raises (an exception thrown into an arbitrary frame is how a store ends up deleted
    under a live child): it records the signal and signals the live child's process group itself --
    SIGTERM on the first, SIGKILL on any later one. ``pgid`` is set only while the child's group id is
    reserved (the leader unreaped), and cleared BEFORE the leader is reaped, so the handler can never
    signal a recycled id.
    """

    signal: str | None = None
    count: int = 0
    pgid: int | None = None
    #: True once the handler has actually signalled a live child's group (the child was told to stop).
    sent: bool = False
    #: When the last signal that COUNTED arrived: signals within ``SIGNAL_DEBOUNCE_S`` of it are one event.
    last: float | None = None
    #: The run directory while a run is live: the third signal removes the children's raw logs from it before the runner leaves.
    run_dir: Path | None = None


_INT = _Interrupts()

#: A dropped session sends a hangup, then another from the shell, then the kernel's own, within milliseconds:
#: signals that close together are ONE event, so the machine's own repeats never count as an operator insisting.
SIGNAL_DEBOUNCE_S = 0.25


def _pdeathsig_preexec():
    """A ``preexec_fn`` asking the kernel to SIGKILL the child if the runner dies (Linux only).

    It covers the leader only (the setting is cleared on fork, so a helper survives a SIGKILLed runner)
    and is the backstop for the one death no handler can see. It fails CLOSED: if the request fails, or
    the runner is already gone by the time it runs, the phase does not start. The foreign function is
    bound HERE, in the parent, so the child does no symbol lookup between fork and exec; and no sampler
    thread of an earlier phase is left alive when this is used (``run_phase`` joins it), because
    ``preexec_fn`` can deadlock in a child forked while another thread holds an interpreter or allocator lock.
    """
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    sigkill, parent, getppid = int(signal.SIGKILL), os.getpid(), os.getppid

    def _set() -> None:
        if prctl(1, sigkill) != 0 or getppid() != parent:  # 1 = PR_SET_PDEATHSIG
            raise OSError("the parent-death backstop could not be set, or the runner is already gone")

    return _set


def run_phase(
    spec: PhaseSpec,
    *,
    env: dict[str, str],
    data_dir: Path,
    tmp_dir: Path,
    log_dir: Path,
    run_dir: Path,
    reserve_bytes: int,
    min_available_bytes: int,
    probe: Probe,
    sample_seconds: float,
    secrets_: tuple[str, ...],
    roots: tuple[tuple[str, str], ...] = (),
) -> PhaseResult:
    """Run one child to its end (or its refusal) and measure it. Never raises for a child's failure."""
    res = PhaseResult(spec.name)
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    out_f, err_f = log_dir / f"{spec.name}.out", log_dir / f"{spec.name}.err"
    res.disk_free_before_bytes = probe.free_disk(run_dir)
    res.disk_free_min_bytes = res.disk_free_before_bytes
    stop = threading.Event()
    refusal: list[str] = []
    stride = {"n": 1, "i": 0}
    t0 = time.monotonic()

    # The logs are the child's raw output (paths and all): owner-only from the first byte.
    log_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    with os.fdopen(os.open(out_f, log_flags, 0o600), "wb") as fo, os.fdopen(os.open(err_f, log_flags, 0o600), "wb") as fe:
        # ``guard`` and ``reaped`` close the pid-reuse window: the leader is reaped only under the lock,
        # and every signal sent from the sampler takes it and refuses once the leader is reaped.
        guard = threading.Lock()
        reaped = {"v": False}
        terminating = {"v": False}

        def _signal_group(sig: int) -> None:
            with guard:
                if reaped["v"]:
                    return
                with contextlib.suppress(OSError):
                    os.killpg(proc.pid, sig)

        def _reap() -> tuple[int, Any]:
            """Wait for the leader WITHOUT reaping it (a zombie keeps its pid), sweep the group with
            SIGKILL (a helper that ignored SIGTERM, or outlived a clean exit, must not keep writing into a
            store about to be deleted), withdraw the handler's access to the group id, and only then reap,
            all under the lock."""
            os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT)
            with guard:
                with contextlib.suppress(OSError):
                    os.killpg(proc.pid, signal.SIGKILL)
                _INT.pgid = None
                _pid, st, us = os.wait4(proc.pid, 0)
                reaped["v"] = True
            return st, us

        def _disk_critical() -> bool:
            try:
                return probe.free_disk(run_dir) < reserve_bytes // 2
            except OSError:
                return False

        def _terminate(reason: str | None) -> None:
            """SIGTERM the group, give it the grace, then SIGKILL. ``reason`` None: a signal to the
            runner started this (the handler has already sent the SIGTERM) and it is not a guard stop."""
            terminating["v"] = True
            if reason:
                refusal.append(reason)
            _signal_group(signal.SIGTERM)
            deadline = time.monotonic() + TERMINATE_GRACE_S
            while time.monotonic() < deadline and not stop.is_set():
                if _disk_critical() or _INT.count >= 2:
                    break  # the grace must not spend the reserve it exists to protect; a second signal ends it
                time.sleep(0.1)  # a poll fine enough to notice the child leaving, coarse enough to cost nothing
            if not stop.is_set():
                _signal_group(signal.SIGKILL)

        def _sample() -> None:
            low_mem_strikes = 0
            try:
                while not stop.is_set():
                    if _INT.signal is not None and not terminating["v"]:
                        _terminate(None)
                        return
                    with guard:  # never read (or signal) a pid the main thread has already reaped
                        rss = None if reaped["v"] else _children_rss(proc.pid)
                    data = dir_allocated_bytes(data_dir) + dir_allocated_bytes(tmp_dir)
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
                    if free < reserve_bytes and not terminating["v"]:
                        _terminate(f"free disk fell to {free} bytes, below the {reserve_bytes}-byte reserve")
                        return
                    low_mem_strikes = low_mem_strikes + 1 if avail < min_available_bytes else 0
                    if low_mem_strikes >= 3 and not terminating["v"]:
                        _terminate(f"available memory stayed at {avail} bytes, below the {min_available_bytes}-byte minimum")
                        return
                    stop.wait(sample_seconds)
            except Exception as exc:  # noqa: BLE001 - a dead guard must stop the run, never leave it unguarded
                if not terminating["v"] and not stop.is_set():
                    _terminate(f"the sampler failed ({type(exc).__name__}), so the disk and memory guards were down; "
                               "the phase was stopped rather than left unguarded")

        if _INT.signal is not None:  # a signal landed before this phase's child existed: do not start one
            res.status, res.reason = "interrupted", f"the runner was interrupted ({_INT.signal}) before the phase started"
            res.wall_seconds = round(time.monotonic() - t0, 3)
            res.disk_free_after_bytes = probe.free_disk(run_dir)
            return res
        try:
            # Its own session: the child leads a process GROUP, so a stop reaches every descendant and
            # none keeps writing to the disk this guard is protecting after the child itself is gone.
            # PDEATHSIG is the backstop for the runner being KILLED (no handler runs on SIGKILL).
            proc = subprocess.Popen(spec.argv, env=env, stdout=fo, stderr=fe, cwd=str(ROOT),  # noqa: S603
                                    start_new_session=True, preexec_fn=_pdeathsig_preexec())  # noqa: PLW1509
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:  # UnicodeError: an env value the locale cannot encode
            res.status, res.reason = "failed", scrub(
                f"the phase could not be started ({record_text(exc, *secrets_, typed=True)})", secrets_=secrets_, run_dir=run_dir, roots=roots)
            res.wall_seconds = round(time.monotonic() - t0, 3)
            res.disk_free_after_bytes = probe.free_disk(run_dir)
            return res

        # From here to the end of this ``try`` NOTHING may leave the child alive: the ``finally`` kills the
        # group and reaps it whatever happened (a thread that would not start, a bug), before the caller
        # deletes the store.
        sampler = threading.Thread(target=_sample, name=f"ref-run-sampler-{spec.name}", daemon=True)
        status = None
        usage = None
        sig_during = None
        told_to_stop = False
        _INT.sent = False
        try:
            _INT.pgid = proc.pid
            sampler.start()
            status, usage = _reap()
            proc.returncode = os.waitstatus_to_exitcode(status)
            sig_during = _INT.signal
            told_to_stop = _INT.sent or terminating["v"]
            # killpg only SENDS the signal: wait until no member of the group is still alive, so nothing can
            # write into the store the caller deletes next. A member that will not go is reported, and the
            # store is kept.
            res.group_survived = not _wait_group_gone(proc.pid, GROUP_GONE_TIMEOUT_S)
        finally:
            _INT.pgid = None
            stop.set()
            if sampler.is_alive():
                # It wakes at once (``stop`` is set) unless it is inside one directory scan: wait that out,
                # so the next phase's Popen never forks while a sampler thread is alive.
                sampler.join(timeout=60)
            res.sampler_alive = sampler.is_alive()
            if not reaped["v"]:
                with guard:
                    with contextlib.suppress(OSError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    with contextlib.suppress(OSError):
                        os.wait4(proc.pid, 0)
                    reaped["v"] = True

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
    if res.disk_free_before_bytes is not None and res.disk_free_min_bytes is not None:
        res.disk_used_peak_bytes = max(0, res.disk_free_before_bytes - min(res.disk_free_min_bytes, res.disk_free_after_bytes))
    # A child that exits 0 after the runner TOLD it to stop is not a finished phase (it may have trapped the
    # signal and left early): only a signal that reached the runner as the child ended leaves the outcome alone.
    res.status = _phase_status(refusal=refusal[0] if refusal else None, returncode=proc.returncode,
                               signalled=sig_during is not None and told_to_stop)
    if refusal:
        res.reason = refusal[0]
    if sig_during is not None:
        if res.status == "interrupted":
            res.reason = (f"the runner was interrupted ({sig_during})"
                          + ("; the child exited 0 after being told to stop, which is not a completed phase"
                             if proc.returncode == 0 else ""))
        else:
            res.interrupted_by = sig_during
    if res.group_survived:
        res.status = "failed" if res.status == "ok" else res.status
        res.reason = (res.reason + "; " if res.reason else "") + (
            "a process of the child's group was still alive after SIGKILL: the store is kept, not deleted")
    try:
        raw = out_f.read_text("utf-8").strip()
        if raw.startswith("{"):
            # the engine's own words: scrubbed HERE, where they are read, not by a pass over the finished report
            res.app_report = _scrub_obj(json.loads(raw), secrets_=secrets_, run_dir=run_dir, roots=roots)
        elif raw:
            res.error_tail = scrub(raw, secrets_=secrets_, run_dir=run_dir, roots=roots)[-600:]  # scrub, THEN cut
    except (OSError, ValueError):
        pass
    if res.status != "ok":
        tail = _tail(err_f, secrets_=secrets_, run_dir=run_dir, roots=roots)
        res.error_tail = (res.error_tail + "\n" if res.error_tail else "") + tail if tail else res.error_tail
    return res


# --------------------------------------------------------------------------- #
#  the run
# --------------------------------------------------------------------------- #


class _terminating_signals:  # noqa: N801 - a context manager used like a function
    """While active, SIGHUP, SIGTERM and SIGINT stop the run cleanly instead of killing the runner outright.

    A dropped SSH session sends SIGHUP and the default action would end Python before any ``finally``,
    leaving the child filling the disk. The handler RAISES NOTHING: it records the signal in ``_INT`` and
    signals the live child's group (SIGTERM, then SIGKILL on a second signal), so the run unwinds along its
    ordinary path -- the store is deleted and the report written -- and no exception is ever thrown into an
    arbitrary frame. Handlers are restored on exit; off the main thread it installs none (and a signal
    then takes its default action).
    """

    def __enter__(self):
        self._prev: dict = {}
        _INT.signal, _INT.count, _INT.pgid, _INT.sent, _INT.last = None, 0, None, False, None
        _INT.run_dir = None
        if threading.current_thread() is not threading.main_thread():
            return self

        def _handler(signum, _frame):
            now_m = time.monotonic()
            if _INT.last is not None and now_m - _INT.last < SIGNAL_DEBOUNCE_S:
                return  # the same event as the one just handled (a dropped session sends several at once)
            _INT.last = now_m  # stored and counted BEFORE anything else runs: a handler nested here sees them
            _INT.count += 1
            if _INT.signal is None:
                _INT.signal = signal.Signals(signum).name
            pg = _INT.pgid
            if _INT.count >= 3:
                # The operator is insisting and something is stuck: the child goes first (nothing keeps writing
                # into a store nobody will delete), then the runner takes the DEFAULT action, so there is always
                # a way out that is not kill -9. SIGQUIT would dump a core holding the passphrase: SIGTERM instead.
                if pg is not None:
                    with contextlib.suppress(OSError):
                        os.killpg(pg, signal.SIGKILL)
                final = signal.SIGTERM if signum == getattr(signal, "SIGQUIT", None) else signum
                # The default action is armed FIRST, for every signal that does not dump a core: the log removal below
                # touches the disk, a disk that is full or hung is exactly the state this way out is for, and the next
                # signal must end the process even while that call is blocked.
                for name in ("SIGHUP", "SIGTERM", "SIGINT"):
                    sig = getattr(signal, name, None)
                    if sig is not None:
                        with contextlib.suppress(ValueError, OSError):
                            signal.signal(sig, signal.SIG_DFL)
                signal.signal(final, signal.SIG_DFL)
                quit_sig = getattr(signal, "SIGQUIT", None)
                if quit_sig is not None:
                    # SIGQUIT's default dumps a core holding the passphrase, so it cannot be handed back: it ends the
                    # process here, as a SIGTERM would, when a blocked removal is interrupted by it.
                    with contextlib.suppress(ValueError, OSError):
                        signal.signal(quit_sig, lambda _signum, _frame: os._exit(128 + int(signal.SIGTERM)))
                if _INT.run_dir is not None:  # the raw logs hold the children's words unscrubbed: no report is coming to say so
                    with contextlib.suppress(Exception):
                        _remove_logs(_INT.run_dir)
                os.kill(os.getpid(), final)
                os._exit(128 + int(final))  # only reached where the signal was not delivered (a runner that is PID 1)
            if pg is not None:
                _INT.sent = True
                with contextlib.suppress(OSError):
                    os.killpg(pg, signal.SIGTERM if _INT.count == 1 else signal.SIGKILL)

        for name in ("SIGHUP", "SIGTERM", "SIGINT", "SIGQUIT"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                if signal.getsignal(sig) == signal.SIG_IGN:
                    continue  # nohup (or `&`) chose to ignore it: that choice survives a dropped session
                self._prev[sig] = signal.signal(sig, _handler)
            except (ValueError, OSError):  # pragma: no cover
                continue
        tstp = getattr(signal, "SIGTSTP", None)
        if tstp is not None:  # Ctrl-Z would freeze the sampler (and the guards) while the child ran on
            with contextlib.suppress(ValueError, OSError):
                self._prev[tstp] = signal.signal(tstp, signal.SIG_IGN)
        return self

    def __exit__(self, *exc):
        _INT.run_dir = None
        for sig, prev in self._prev.items():
            with contextlib.suppress(ValueError, OSError):  # pragma: no cover
                signal.signal(sig, prev)
        return False


def _scrub_obj(obj, *, secrets_: tuple[str, ...], run_dir: Path | None, roots: tuple[tuple[str, str], ...] = (),
               paths_only: bool = False):
    """``scrub`` applied to every string in a JSON-shaped value, KEYS included: the keys of a child's JSON are the child's
    words, not this module's (``IngestReport.to_dict()`` defines them today, but a key built from an engine's text would carry
    it), so a key that holds a secret is rewritten, and two keys that come to the same text are kept apart (``#2``). The runner
    reads no key of a child's JSON that a pathological passphrase could rename but ``osm_db_bytes`` and ``extract_bytes``, which
    then read as missing: the failing-closed side. ``paths_only=True`` (the finished report, scrubbed where each text was made)
    reduces paths and takes out no secret."""
    if isinstance(obj, str):
        return scrub(obj, secrets_=secrets_, run_dir=run_dir, roots=roots, paths_only=paths_only)
    if isinstance(obj, list):
        return [_scrub_obj(v, secrets_=secrets_, run_dir=run_dir, roots=roots, paths_only=paths_only) for v in obj]
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            key = scrub(k, secrets_=secrets_, run_dir=run_dir, roots=roots, paths_only=paths_only) if isinstance(k, str) else k
            n = 1
            while key in out:
                n += 1
                key = f"{key}#{n}"
            out[key] = _scrub_obj(v, secrets_=secrets_, run_dir=run_dir, roots=roots, paths_only=paths_only)
        return out
    return obj


def _remove_logs(run_dir: Path) -> dict:
    """Delete the children's RAW logs (``logs/<phase>.out`` and ``.err``) from a store that is NOT being deleted (kept, or left
    by a deletion that stopped short): they are the engine's output as it wrote it, paths and anything it echoed, and such
    a store is left on a disk for days. The report carries the scrubbed tails, which is the record. A file that cannot be
    removed is named in the report; this never raises (an OSError here must not cost the report)."""
    left = 0
    try:
        log_dir = run_dir / "logs"
        for f in sorted(log_dir.glob("*")) if log_dir.is_dir() else []:
            try:
                f.unlink()
            except OSError:
                left += 1
        with contextlib.suppress(OSError):
            log_dir.rmdir()
    except OSError:
        left += 1
    return {"logs_removed": left == 0,
            "logs_note": ("the children's raw logs were removed from the store; the report carries their scrubbed tails"
                          if left == 0 else
                          f"{left} of the children's raw log files could not be removed and stay beside the store, "
                          "unscrubbed; --cleanup deletes them")}


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
    try:
        # The marker goes LAST: a deletion that is cut short leaves a directory ``--cleanup`` still recognises.
        for child in sorted(run_dir.iterdir(), key=lambda c: c.name == MARKER):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        run_dir.rmdir()
    except OSError as exc:  # the report must still be written: what is left is named, never hidden
        return {"deleted": False, "error": f"the deletion stopped: {type(exc).__name__}; delete the directory with --cleanup"}
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
        how = ["--no-wikidata"]  # the online join is NEVER run inside the throwaway store: see GAZETTEER_MODES above
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


def run(**kwargs: Any) -> tuple[dict, Path | None]:
    """:func:`_run` with SIGHUP / SIGTERM / SIGINT handled for the whole of it, the report write included."""
    if threading.current_thread() is not threading.main_thread():
        raise ValueError("the reference run must be called from the main thread: only there can its signal handling "
                         "stop the child cleanly (a signal would otherwise take its default action and leave the child running)")
    with _terminating_signals():
        return _run(**kwargs)


def _run(
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
    on_start: Callable[[Path], object] | None = None,
    on_preflight: Callable[[dict], object] | None = None,
    report_path: Path | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[dict, Path | None]:
    """Run the phases under measurement and return ``(report, run_dir)``.

    ``run_dir`` is None when no store was made (a plan, or a preflight refusal) or when it was
    deleted; with ``keep_store`` it is the directory to hand to ``--cleanup`` later.
    ``phases_override`` exists for tests (a scripted child in place of the app's scripts).
    ``on_start`` is called with the run directory as soon as it exists (the operator learns where it is
    before an hours-long run, not after); ``on_preflight`` is called with the preflight once the disk floor is met and before
    anything starts (the worst-case warning belongs before the run, not in its summary); ``report_path`` has the report written inside the signal
    handling's reach. Linux only: the stop is process groups, ``waitid`` and a parent-death backstop.
    """
    if not sys.platform.startswith("linux"):
        raise ValueError("the reference run needs Linux (process groups, waitid and the parent-death backstop); "
                         "the 2-core reference VM is one")
    if not (SAMPLE_SECONDS_MIN <= sample_seconds <= SAMPLE_SECONDS_MAX):
        raise ValueError(f"--sample-seconds must be between {SAMPLE_SECONDS_MIN:g} and {SAMPLE_SECONDS_MAX:g}")
    if keep_store and passphrase_file is None:
        raise ValueError("--keep-store needs --passphrase-file: a file you make holding any passphrase (for example "
                         "`python -c \"import secrets; print(secrets.token_urlsafe(24))\" > key`), so the later "
                         "gazetteer build can open the kept store; this tool writes no secret to disk")
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
    if report_path is not None:
        try:  # an unwritable report location is found NOW, not after hours of measuring
            Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"the report's directory cannot be created ({type(exc).__name__})") from None
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
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    g_out = Path(gazetteer_out).resolve() if gazetteer_out else None
    if gazetteer != "off" and g_out is None:
        g_out = base / f"places_gazetteer-{stamp}.yml"
    try:
        home: Path | None = Path.home()
    except (RuntimeError, KeyError):  # no home directory to name: nothing of it to scrub
        home = None
    known: dict[str, str] = {}
    for path, label in ((ROOT, "<repo>"), (base, "<workdir>"), (extract.parent, "<extract-dir>"),
                        (Path(history).parent if history else None, "<history-dir>"),
                        (g_out.parent if g_out else None, "<output-dir>"), (home, "<home>")):
        if path is not None:
            known.setdefault(str(path), label)
    roots = tuple(sorted(known.items(), key=lambda kv: -len(kv[0])))

    def _finish(run_dir: Path | None, kept_dir: Path | None) -> tuple[dict, Path | None]:
        report["not_measured"] = report["not_measured"] or not_measured(
            history=history is not None, gazetteer=gazetteer, kernel_peak=kernel_peak)
        report["finished_at"] = now().isoformat()
        # Paths only: every engine text was scrubbed of the passphrase where it was made (above), and a pass of the
        # secret over the finished record could rewrite a verdict word the exit code reads (a passphrase "failed").
        final = _scrub_obj(report, secrets_=(), run_dir=run_dir, roots=roots, paths_only=True)
        if report_path is not None:
            try:
                write_report(final, report_path)
            except OSError as exc:  # the measurement must not be lost to a bad report path after hours of work
                final["report_write_error"] = type(exc).__name__
        return final, kept_dir

    if plan_only:
        report["status"] = "plan"
        report["not_measured"] = ["everything: --plan runs nothing"]
        return _finish(None, None)
    # The key is read only now: a plan runs nothing, so it never holds the passphrase (the command's core-dump limit is
    # not asked of a plan, which therefore must not carry a key in memory).
    if passphrase_file is not None:
        try:
            passphrase = Path(passphrase_file).read_text("utf-8").strip()
        except UnicodeDecodeError:  # its message would name a byte of the file and its position: say neither
            raise ValueError("the passphrase file is not valid UTF-8") from None
        except OSError as exc:
            raise ValueError(f"cannot read the passphrase file ({type(exc).__name__})") from None
        if not passphrase:
            raise ValueError("the passphrase file is empty")
    else:
        passphrase = secrets.token_urlsafe(24)
    secrets_ = (passphrase,)
    if not pf["ok"]:
        report["status"] = "refused-preflight"
        report["reason"] = (f"free disk is {pf['free_bytes']} bytes and the run needs {pf['needed_bytes']} "
                            f"({pf['floor_basis']})")
        report["not_measured"] = ["everything: the preflight refused before any phase started"]
        return _finish(None, None)  # a refusal is a result too: the report names it, so the operator is never pointed at nothing

    if on_preflight is not None:
        with contextlib.suppress(OSError):  # a closed terminal must not end the run before it starts
            on_preflight(pf)
    run_dir = base / f"oo-osm-reference-run-{stamp}-{secrets.token_hex(3)}"
    data_dir = run_dir / "data"
    tmp_dir = run_dir / "tmp"
    try:
        run_dir.mkdir(mode=0o700)
        _INT.run_dir = run_dir
    except OSError as exc:  # an unwritable workdir is a named refusal with a report, not a traceback
        report["status"] = "refused"
        report["reason"] = f"the throwaway store cannot be made in the work directory ({type(exc).__name__})"
        report["not_measured"] = ["everything: no store could be made, so no phase started"]
        return _finish(None, None)
    # From here ANYTHING that goes wrong still ends in the deletion step and a written report.
    specs: list[PhaseSpec] = []
    try:
        data_dir.mkdir()
        tmp_dir.mkdir()
        (run_dir / MARKER).write_text("a throwaway store made by scripts/osm_reference_run.py; safe to delete\n", "utf-8")
        if on_start is not None:
            with contextlib.suppress(OSError):  # a closed terminal must not end the run before it starts
                on_start(run_dir)
        env = {k: v for k, v in os.environ.items()
               if k not in ("OO_DB_PLAINTEXT", "OO_DATA_VOLUME_ID", "OO_DB_PASSPHRASE", "OO_DATA_DIR", "DATABASE_URL")}
        # Temporary and spill files stay on the filesystem the guard reads (and are deleted with the store).
        env.update({"OO_DATA_DIR": str(data_dir), "OO_DB_PASSPHRASE": passphrase, "PYTHONUNBUFFERED": "1",
                    "TMPDIR": str(tmp_dir), "SQLITE_TMPDIR": str(tmp_dir)})
        specs = phases_override if phases_override is not None else build_phases(
            extract=extract, country=country, history=Path(history) if history else None, reader=reader,
            gazetteer=gazetteer, gazetteer_out=g_out)

        for spec in specs:
            if _INT.signal is not None:
                report["status"] = "interrupted"
                report["reason"] = f"the runner was interrupted ({_INT.signal}) before phase {spec.name}"
                break
            res = run_phase(spec, env=env, data_dir=data_dir, tmp_dir=tmp_dir, log_dir=run_dir / "logs", run_dir=run_dir,
                            reserve_bytes=reserve_bytes, min_available_bytes=min_available_bytes, probe=probe,
                            sample_seconds=sample_seconds, secrets_=secrets_, roots=roots)
            stuck = res.sampler_alive and res.status == "ok"
            if stuck:
                res.status = "failed"
                res.reason = "the sampler thread did not stop, so no further phase was started (a fork beside a live thread is not safe)"
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
    except Exception as exc:  # noqa: BLE001 - the run's own failure is a result: recorded, store removed, report written
        note = scrub(f"the runner itself failed: {record_text(exc, passphrase, typed=True)}", secrets_=secrets_, run_dir=run_dir, roots=roots)
        if report["status"] == "ok":
            report["status"], report["reason"] = "failed", note
        else:  # what happened first (a signal, a guard's stop) stays the status; this is added to it
            report["reason"] = f"{report.get('reason') or report['status']}; then {note}"
    finally:
        # THE THIRD STEP: the throwaway store goes, and the report says so. A kept store is left on purpose --
        # and so is one a child's group still held when the sweep ended: nothing is deleted under a live writer.
        survived = any(p.get("group_survived") for p in report["phases"])
        done_ok = {p["name"] for p in report["phases"] if p.get("status") == "ok"}
        unfinished = [sp.name for sp in specs if sp.name not in done_ok]
        report["not_measured"] = not_measured(history=history is not None, gazetteer=gazetteer, kernel_peak=kernel_peak)
        if report["status"] != "ok":
            report["not_measured"] += [f"phase {n}: did not run to completion (the run ended {report['status']})"
                                       for n in unfinished]
        if keep_store:
            report["store"] = {"kept": True, "note": "left for a separate gazetteer build; delete it with --cleanup",
                               **_remove_logs(run_dir)}
            kept_dir: Path | None = run_dir
        elif survived:
            report["store"] = {"kept": True, "deleted": False,
                               "note": "a process of the child's group was still alive after SIGKILL, so the store was NOT "
                                       "deleted; delete it with --cleanup once that process is gone",
                               **_remove_logs(run_dir)}
            kept_dir = run_dir
        else:
            gone = _delete_store(run_dir, probe)
            report["store"] = {"kept": not gone.get("deleted"), **gone}
            kept_dir = None if gone.get("deleted") else run_dir
            if not gone.get("deleted"):  # a deletion that stopped short leaves what it left: the raw logs go regardless
                report["store"].update(_remove_logs(run_dir))
    if _INT.signal is not None and report["status"] != "interrupted":
        # What the run did stays its status (a finished run is ok, a guard's stop is refused-mid-run); the signal
        # that reached the runner is recorded beside it, never lost.
        report["interrupted_by"] = _INT.signal
    return _finish(run_dir, kept_dir)


def write_report(report: dict, path: Path) -> None:
    """Write the report atomically. It is a measurement, not a secret; it names its inputs by file name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
