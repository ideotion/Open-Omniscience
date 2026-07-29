"""
vLLM lifecycle: detect / start / stop / install / default-model download / context
auto-tune (B2, 2026-07-24 field-feedback Session B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

vLLM is a MANAGED EXTERNAL PROCESS, exactly like Ollama -- never a core
dependency (torch stays banned from ``pyproject.toml``). This module owns:

  * a dedicated venv under the data dir (never the app's own interpreter/venv --
    torch/CUDA must never leak into the core install);
  * a marker file proving a completed install (never a subprocess probe on every
    health check -- ``is_installed()`` is a cheap file-existence check);
  * starting/stopping the OpenAI-compatible server as a subprocess bound to
    loopback;
  * the context-size auto-tune math (``compute_server_args``), pure + testable;
  * the consented, task-manager-visible install job (drags torch/CUDA, multi-GB
    -- disclosed BEFORE consent, never silently downloaded).

RULED (A12, §8 out-of-scope): vLLM's CPU mode is NOT viable on this project's
fleet and must never be presented as an option -- ``start()`` REFUSES outright
when no GPU is detected, pointing at Ollama instead. This is the honest
"CPU-only machine + install attempt -> refusal, not a doomed install" (B2.3).

Nothing here is GPU-verified in this sandbox (no GPU present) -- the mechanism
is proven with an injectable runner (tests never spawn a real subprocess); a
maintainer on the GPU-equipped VM (per A12's hardware ground truth) is the
live-validation gate, stated honestly in every status payload's absence of a
fabricated "verified" claim.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess  # noqa: S404 - fixed argv, no shell; every call site documents why
import sys
import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

# The exact version verified against PyPI's JSON API 2026-07-25 (this sandbox can
# reach pypi.org; huggingface.co/docs.vllm.ai were blocked, so verification stopped
# at what was reachable). Bump only after re-verifying against
# https://pypi.org/pypi/vllm/json -- never guessed (the fabricated-endpoint burn).
# 2026-07-25: confirmed 0.26.0 is the current release on PyPI (non-yanked,
# uploaded the same day) -- one release ahead of the previously-pinned 0.25.1,
# which was correct as of ITS OWN verification date and simply went stale by a
# day (vLLM ships fast). Re-verified the wheel SHAPE is unchanged: both 0.25.1
# and 0.26.0 publish only `cp38-abi3-manylinux_2_28_{x86_64,aarch64}` wheels +
# a source sdist -- LINUX ONLY, no macOS/Windows wheel at all (see
# platform_support() below, added the same day this was caught).
VLLM_VERIFIED_VERSION = "0.26.0"
VLLM_VERIFIED_AS_OF = "2026-07-25"

DEFAULT_PORT = 8000
DEFAULT_HOST = "127.0.0.1"

# A disclosed ESTIMATE, never a precise fabricated figure: vLLM pulls torch + CUDA
# runtime wheels alongside itself, a well-known heavy combination. Shown to the
# operator BEFORE consenting to install (B2.3).
ESTIMATED_INSTALL_SIZE_NOTE = (
    "several GB (typically 5-10 GB combined: vLLM + torch + the CUDA runtime "
    "wheels) -- an estimate, not a measured figure; the actual download size "
    "depends on your platform and is shown by pip as it runs."
)

# --- Install resource floors (V2, 2026-07-29) ------------------------------- #
# DERIVED, not guessed: ESTIMATED_INSTALL_SIZE_NOTE above puts the download at
# 5-10 GB, and pip holds each wheel AND its unpacked contents at the same time,
# so peak usage sits materially above the download size. Below this floor the
# install CANNOT succeed, which is why it is a HARD refusal that no
# acknowledgement overrides.
INSTALL_DISK_FLOOR_BYTES = 15 * 1024**3

# A DISCLOSED HEURISTIC, never a sourced requirement. vLLM's serving process
# needs host RAM for the Python process, the CUDA context and the model-loading
# path, on TOP of GPU VRAM -- but no minimum has been measured for this
# project's fleet, and this project does not assert thresholds it cannot source.
# So below this floor the operator is WARNED with the real number and must
# acknowledge; they are never refused, because they may know something this
# check does not.
LOW_RAM_WARN_BYTES = 8 * 1024**3

# Bounded tail of pip output, used for BOTH failure CLASSIFICATION (the other
# half of the CLAUDE.md:519-520 lesson: "point TMPDIR at the install volume +
# classify disk-full vs network failures honestly") and the V3 attempt journal.
# Bounded by construction -- a multi-GB install emits a lot of lines and none of
# them may accumulate.
_OUTPUT_TAIL_LINES = 50
_OUTPUT_LINE_CHARS = 400
_ENOSPC_MARKERS = ("no space left on device", "errno 28")

# RAM-backed filesystems (mirrors forensics._VOLATILE_FS): pip unpacking multi-GB
# wheels into one of these is the Errno-28-while-df-reports-free-disk condition.
_VOLATILE_FILESYSTEMS = frozenset({"tmpfs", "ramfs"})


class VllmLifecycleError(Exception):
    """Base class for vLLM lifecycle failures (install/start/stop)."""


class VllmUnsupportedError(VllmLifecycleError):
    """No GPU detected -- vLLM's CPU mode is not viable on this fleet (RULED)."""


# --------------------------------------------------------------------------- #
#  Paths + the install marker
# --------------------------------------------------------------------------- #
def venv_dir() -> Path:
    """The dedicated vLLM venv -- NEVER the app's own interpreter (isolates
    torch/CUDA from core; a broken vLLM install can never break the app)."""
    override = os.getenv("OO_VLLM_VENV_DIR")
    return Path(override) if override else (data_dir() / "vllm_venv")


def _marker_path() -> Path:
    return venv_dir() / ".oo_vllm_installed.json"


def venv_python() -> Path:
    """The venv's own Python interpreter (POSIX layout; Windows is out of scope
    per the standing Debian-first V1 pathway ruling)."""
    return venv_dir() / "bin" / "python"


def venv_bin(name: str) -> Path:
    return venv_dir() / "bin" / name


def pip_tmpdir() -> Path:
    """Where pip unpacks wheels during the vLLM install (V1, 2026-07-29).

    Deliberately derived from ``venv_dir()`` and NOT from ``data_dir()``: with
    ``OO_VLLM_VENV_DIR`` set, the venv can live on a volume the data dir knows
    nothing about, and the property that actually matters is that the unpack
    area sits on the SAME VOLUME as the install target -- so the disk figure the
    preflight measures is the one pip will really consume.

    It is created immediately before the install subprocesses and removed in a
    ``finally`` afterwards. That DIVERGES from ``install.sh:pip_install``, which
    deliberately KEEPS its build dir -- and the divergence is safe because pip's
    resumable download cache is ``$XDG_CACHE_HOME/pip``, a different directory
    entirely, so nothing is lost by deleting this one, while a failed 10 GB
    unpack would otherwise strand 10 GB beside the venv."""
    return venv_dir().parent / ".oo-vllm-pip-build"


def is_installed() -> bool:
    """A cheap, file-existence-only check (no subprocess) -- the marker is written
    ONLY after a verified successful ``pip install`` (see ``run_install_job``)."""
    return _marker_path().is_file() and venv_python().is_file()


def install_info() -> dict | None:
    """The persisted install record ({version, installed_at}), or None."""
    p = _marker_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_marker(version: str) -> None:
    venv_dir().mkdir(parents=True, exist_ok=True)
    _marker_path().write_text(
        json.dumps({"version": version, "installed_at": time.time()}), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
#  Install ATTEMPT journal (V3, 2026-07-29) -- the marker records only SUCCESS;
#  this records EVERY attempt, so a FAILED install stays diagnosable after a
#  restart.
#
#  WHY: writing the marker only on a verified-successful pip exit is correct --
#  is_installed() must never claim a half-configured backend works. But it means
#  a FAILURE leaves no durable trace at all: the error lives in in-memory
#  BackgroundJob state (truncated to 300 chars) and is gone on the next boot, so
#  a bundle taken after a restart shows install_info: null with nothing saying an
#  install was ever attempted or why it died -- exactly what the 2026-07-29
#  operator bundle showed. A backend install is long, fallible and rare: the
#  shape that most deserves a persisted record.
#
#  BOUNDED BY CONSTRUCTION, AND HONEST ABOUT IT: the newest _ATTEMPTS_CAP
#  attempts, each keeping the last _OUTPUT_TAIL_LINES lines (pip's output is far
#  larger) truncated to _OUTPUT_LINE_CHARS. Every record states how many lines it
#  KEPT and the REAL total, so a tail can never be read as a complete log.
#
#  NEVER RAISES INTO THE INSTALL PATH: a journal whose own write failure
#  propagates aborts the very operation it exists to record (the recorded house
#  lesson from the all-diagnostics crash journal). On any failure this logs ONCE,
#  DISABLES itself for the process, and install_history_bounds() reports that it
#  stopped -- an incomplete history is never presented as complete.
# --------------------------------------------------------------------------- #
_ATTEMPTS_CAP = 20

# Set once if the journal ever fails to write: log + disable, never raise.
_history_disabled = False
_history_disabled_reason: str | None = None

# Value-side redaction for CAPTURED OUTPUT. The recursive KEY-based scrub below
# cannot help here: pip output is a free-text VALUE, so a credential inside a
# line sails straight through a key scrub. This covers exactly two documented
# shapes and claims nothing more -- it is NOT a general credential detector:
#   * inline URL credentials (a private index: https://user:token@host/simple)
#   * key=value / key: value pairs whose KEY names a credential
# Deliberately narrow: over-redacting pip's diagnostics would destroy the very
# evidence this journal exists to keep -- verified that the
# "[Errno 28] No space left on device" line survives verbatim.
_URL_CREDENTIALS_RE = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)(?P<user>[^/\s:@]+):(?P<value>[^/\s@]+)@"
)
_INLINE_CREDENTIAL_RE = re.compile(
    r"(?P<key>(?:api[_-]?key|access[_-]?token|token|password|passwd|passphrase|secret)"
    r"\s*[=:]\s*)(?P<value>[^\s&\"']+)",
    re.IGNORECASE,
)


def _history_path() -> Path:
    """The attempt journal, beside the success marker in the managed venv dir."""
    return venv_dir() / "install_attempts.jsonl"


def _redact_secrets_in_text(text: str) -> str:
    """Redact the two documented credential shapes from one line of captured
    output. Scope is stated, not implied -- see ``_URL_CREDENTIALS_RE``."""
    out = _URL_CREDENTIALS_RE.sub(
        lambda m: f"{m.group('scheme')}{m.group('user')}:***redacted***@", text
    )
    return _INLINE_CREDENTIAL_RE.sub(lambda m: f"{m.group('key')}***redacted***", out)


def _scrub_history(obj):
    """Redact anything under a credential-shaped KEY, then redact credentials
    inside free-text VALUES.

    The key half mirrors ``src/api/diagnostics.py:_p0_scrub`` -- duplicated
    DELIBERATELY rather than imported: ``src.llm`` must not depend on
    ``src.api``, and reaching a 10-line helper through the diagnostics router
    would drag FastAPI into the install path. The value half is what a key scrub
    structurally cannot do."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = k.lower() if isinstance(k, str) else ""
            out[k] = (
                "***redacted***"
                if any(s in kl for s in ("passphrase", "password", "secret"))
                else _scrub_history(v)
            )
        return out
    if isinstance(obj, list):
        return [_scrub_history(v) for v in obj]
    if isinstance(obj, str):
        return _redact_secrets_in_text(obj)
    return obj


def record_install_attempt(
    *,
    version: str,
    phase: str,
    outcome: str,
    exit_code: int | None = None,
    error: str | None = None,
    output_tail: Sequence[str] | None = None,
    output_lines_total: int | None = None,
    preflight: dict | None = None,
) -> None:
    """Append one attempt to the bounded journal. NEVER RAISES: on any failure it
    logs once and disables recording for this process (log + disable, never
    raise), so the journal can never abort the install it exists to record."""
    global _history_disabled, _history_disabled_reason
    if _history_disabled:
        return
    try:
        kept = [str(ln)[:_OUTPUT_LINE_CHARS] for ln in (output_tail or [])][-_OUTPUT_TAIL_LINES:]
        total = int(output_lines_total) if output_lines_total is not None else len(kept)
        record = {
            "at": time.time(),
            "version": str(version),
            "phase": str(phase),
            "outcome": str(outcome),
            "exit_code": exit_code,
            "error": (str(error)[:500] if error else None),
            "output_tail": kept,
            "output_lines_kept": len(kept),
            "output_lines_total": total,
            "output_truncated": total > len(kept),
            "output_line_cap": _OUTPUT_TAIL_LINES,
            "output_line_chars": _OUTPUT_LINE_CHARS,
            "preflight": preflight,
        }
        line = json.dumps(_scrub_history(record), ensure_ascii=False, separators=(",", ":"))
        path = _history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        # Bounded by construction: keep only the newest _ATTEMPTS_CAP attempts.
        # The file is <= _ATTEMPTS_CAP lines, so trimming on every append is
        # cheap -- unlike the 2000-line rolling error log, which amortises it.
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > _ATTEMPTS_CAP:
            path.write_text("\n".join(lines[-_ATTEMPTS_CAP:]) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - must NEVER break the install it records
        _history_disabled = True
        _history_disabled_reason = f"{type(exc).__name__}: {exc}"[:200]
        try:
            _LOG.warning(
                "vLLM install-attempt journal write failed -- recording disabled "
                "for this process",
                exc_info=True,
            )
        except Exception:  # noqa: BLE001, S110 - even the failure log must not raise here
            pass


def install_history() -> list[dict]:
    """Every RECORDED install attempt, oldest first (JSONL file order).

    Bounded to the newest ``_ATTEMPTS_CAP`` attempts -- read
    ``install_history_bounds()`` alongside it for the caps and for whether
    recording is still enabled, so a bounded (or write-failure-truncated) history
    is never mistaken for a complete one. Never raises: a missing file is ``[]``
    and an unparseable line is skipped (a torn final write must not hide the
    attempts recorded before it)."""
    try:
        path = _history_path()
        if not path.is_file():
            return []
        out: list[dict] = []
        for ln in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
        return out[-_ATTEMPTS_CAP:]
    except OSError:
        return []


def install_history_bounds() -> dict:
    """What the history is bounded BY, stated beside the data so a reader can
    never take a bounded tail for the complete record."""
    try:
        kept = len(install_history())
    except Exception:  # noqa: BLE001
        kept = 0
    try:
        path: str | None = str(_history_path())
    except Exception:  # noqa: BLE001
        path = None
    recording = "enabled"
    stopped_reason = None
    if _history_disabled:
        recording = "disabled-after-a-write-failure"
        stopped_reason = _redact_secrets_in_text(_history_disabled_reason or "")[:200] or None
    return {
        "attempts_kept": kept,
        "attempts_cap": _ATTEMPTS_CAP,
        "output_line_cap": _OUTPUT_TAIL_LINES,
        "output_line_chars": _OUTPUT_LINE_CHARS,
        "path": path,
        "order": "oldest first",
        "recording": recording,
        "recording_stopped_reason": stopped_reason,
        "note": (
            "Bounded by construction: only the newest attempts are kept, and each keeps "
            "only the last lines of output (pip's real output is far larger) -- every "
            "record states how many lines it kept AND the real total, so a tail is never "
            "a complete log. Credential-shaped values in captured output are redacted. "
            "The journal lives inside the managed venv directory, so deleting that "
            "directory also deletes this history. When 'recording' is not 'enabled', "
            "attempts made since then are NOT recorded."
        ),
    }


# --------------------------------------------------------------------------- #
#  Running state (health check, never a fabricated instant green)
# --------------------------------------------------------------------------- #
_proc: subprocess.Popen | None = None


def base_url() -> str:
    from src.llm.vllm_client import DEFAULT_VLLM_URL

    return os.getenv("OO_VLLM_URL", DEFAULT_VLLM_URL)


def is_running(*, timeout: float = 2.0) -> bool:
    """A live ``GET /v1/models`` health probe (bounded timeout so a dead server
    doesn't hang the caller). Honest False on any failure -- never assumed from
    the tracked subprocess handle alone (the process could be starting, or a
    server started by another means entirely)."""
    from src.llm.vllm_client import VllmClient

    try:
        return VllmClient(timeout=timeout).is_available()
    except Exception:  # noqa: BLE001 - a health probe must never raise
        return False


def process_alive() -> bool:
    """True if THIS process is tracking a live subprocess (distinct from
    ``is_running()`` -- a server started by another means, or one still loading
    its model, is not reflected here)."""
    return _proc is not None and _proc.poll() is None


# --------------------------------------------------------------------------- #
#  Context-size auto-tune (B2.5, ruled: disclosed auto-with-override)
# --------------------------------------------------------------------------- #
def compute_server_args(
    vram_mb: int | None,
    *,
    weight_footprint_gb: float = 5.0,
    kv_cache_reserve_frac: float = 0.15,
    max_model_len_override: int | None = None,
    gpu_memory_utilization_override: float | None = None,
) -> dict:
    """Compute ``--max-model-len`` and ``--gpu-memory-utilization`` from detected
    VRAM (pure, testable). METHOD (disclosed, not asserted as exact): reserve
    ``weight_footprint_gb`` for the model's own weights (a stated ESTIMATE -- the
    default 5.0 GB matches a 4-bit-quantized Mistral-7B-class model, the RULED
    default model, per A13); of the remainder, ``kv_cache_reserve_frac`` is kept
    as headroom (activation memory / fragmentation), and ``gpu_memory_utilization``
    is set to use the rest. ``max_model_len`` scales with the remaining VRAM at a
    rough ~1 MB/token/layer-class budget (a conservative, DISCLOSED heuristic --
    never a measured fact; the operator override always wins).

    Returns ``{"max_model_len", "gpu_memory_utilization", "method", "caveat"}``.
    An explicit override for either field is honoured verbatim (no re-derivation).
    """
    method = (
        f"reserve {weight_footprint_gb} GB for model weights, "
        f"{kv_cache_reserve_frac:.0%} of the remainder as headroom; the rest sets "
        "gpu_memory_utilization; max_model_len scales with the remaining VRAM."
    )
    caveat = (
        "A conservative, DISCLOSED heuristic — not a measured fact. Override "
        "either value in Settings if the server OOMs or under-uses the GPU."
    )
    if max_model_len_override is not None and gpu_memory_utilization_override is not None:
        return {
            "max_model_len": max_model_len_override,
            "gpu_memory_utilization": gpu_memory_utilization_override,
            "method": "operator override (verbatim)",
            "caveat": caveat,
        }
    if not vram_mb or vram_mb <= 0:
        # No measured VRAM to derive from -- an honest, conservative default rather
        # than a guess scaled off nothing.
        return {
            "max_model_len": max_model_len_override or 4096,
            "gpu_memory_utilization": gpu_memory_utilization_override or 0.85,
            "method": "no VRAM reading available -- a conservative fixed default",
            "caveat": caveat,
        }
    vram_gb = vram_mb / 1024.0
    usable_gb = max(0.5, vram_gb - weight_footprint_gb)
    kv_gb = usable_gb * (1.0 - kv_cache_reserve_frac)
    gpu_util = gpu_memory_utilization_override
    if gpu_util is None:
        gpu_util = round(min(0.95, max(0.5, (weight_footprint_gb + kv_gb) / vram_gb)), 2)
    max_len = max_model_len_override
    if max_len is None:
        # ~0.5 MB of KV cache per 1K context tokens is a broad, model-family-
        # dependent rule of thumb for a 7B-class model -- rounded to a sane power-
        # of-two-ish bucket, capped to keep the server from claiming an implausibly
        # long context on modest VRAM.
        est_tokens = int((kv_gb * 1024) / 0.5) * 1000
        max_len = max(2048, min(32768, (est_tokens // 1024) * 1024 or 2048))
    return {
        "max_model_len": max_len,
        "gpu_memory_utilization": gpu_util,
        "method": method,
        "caveat": caveat,
    }


# --------------------------------------------------------------------------- #
#  Start / stop the server (subprocess, bound to loopback)
# --------------------------------------------------------------------------- #
def server_argv(
    model: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    max_model_len: int | None = None,
    gpu_memory_utilization: float | None = None,
) -> list[str]:
    """Build the server command line (pure -- testable without a real venv).
    Prefers the ``vllm`` console script installed in the managed venv (the
    current documented CLI, ``vllm serve <model>``); falls back to the module
    invocation if the console script is absent (an older/differently-laid-out
    install), so a start attempt is not defeated by one missing entry point."""
    console = venv_bin("vllm")
    if console.is_file():
        argv = [str(console), "serve", model]
    else:
        argv = [str(venv_python()), "-m", "vllm.entrypoints.openai.api_server", "--model", model]
    argv += ["--host", host, "--port", str(port)]
    if max_model_len is not None:
        argv += ["--max-model-len", str(max_model_len)]
    if gpu_memory_utilization is not None:
        argv += ["--gpu-memory-utilization", str(gpu_memory_utilization)]
    return argv


def start(
    model: str,
    *,
    max_model_len: int | None = None,
    gpu_memory_utilization: float | None = None,
    popen: Callable[..., subprocess.Popen] | None = None,
) -> dict:
    """Launch the vLLM server as a subprocess bound to loopback. Refuses outright
    on a CPU-only machine (RULED, §8) -- Ollama is the CPU path, never vLLM's CPU
    mode presented as viable. ``popen`` is injectable for tests (never a real
    subprocess in the test suite)."""
    global _proc
    from src.llm.backend import detect_gpu

    if not is_installed():
        raise VllmLifecycleError("vLLM is not installed. Run the install flow first.")
    gpu = detect_gpu()
    if not gpu.get("available"):
        raise VllmUnsupportedError(
            "No GPU detected -- vLLM's CPU mode is not a viable option on this machine. "
            "Ollama is the CPU-first backend; use it instead."
        )
    if process_alive() or is_running():
        return {"started": False, "reason": "already running", "base_url": base_url()}
    args = compute_server_args(
        gpu.get("vram_mb"),
        max_model_len_override=max_model_len,
        gpu_memory_utilization_override=gpu_memory_utilization,
    )
    argv = server_argv(
        model,
        max_model_len=args["max_model_len"],
        gpu_memory_utilization=args["gpu_memory_utilization"],
    )
    run = popen or subprocess.Popen
    proc = run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    _proc = proc
    return {
        "started": True,
        "model": model,
        "argv": argv,
        "server_args": args,
        "base_url": base_url(),
        "note": "starting (model load takes tens of seconds) -- poll is_running() before use",
    }


def stop(*, timeout: float = 10.0) -> dict:
    """Stop the tracked subprocess (SIGTERM, then SIGKILL after ``timeout``)."""
    global _proc
    if _proc is None:
        return {"stopped": False, "reason": "not tracked by this process"}
    proc = _proc
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    _proc = None
    return {"stopped": True}


def status() -> dict:
    """A full status snapshot for the Settings -> AI tab and the diagnostics
    member (B7) -- installed/running/GPU/platform facts, never a fabricated
    readiness. ``platform`` is disclosed here (not just at install-attempt
    time) so a non-Linux machine sees "not supported here" BEFORE ever
    reaching for the install button.

    ``preflight`` (V2) carries the MEASURED install cost -- free disk on the
    volume the venv lives on, total system RAM, whether the unpack area is
    RAM-backed -- so the cost is visible BEFORE the button, and so a diagnostics
    bundle records why an install refused (the 2026-07-29 operator bundle could
    not show that). ``install_history`` (V3) records every ATTEMPT, not just the
    successes the marker records, so a failed install stays diagnosable after a
    restart. Both are ADDITIVE -- every existing consumer is unaffected."""
    from src.llm.backend import detect_gpu

    gpu = detect_gpu()
    return {
        "installed": is_installed(),
        "install_info": install_info(),
        "running": is_running(),
        "process_tracked": process_alive(),
        "gpu": gpu,
        "platform": platform_support(),
        "base_url": base_url(),
        "venv_dir": str(venv_dir()),
        "verified_version": VLLM_VERIFIED_VERSION,
        "verified_as_of": VLLM_VERIFIED_AS_OF,
        "estimated_size_note": ESTIMATED_INSTALL_SIZE_NOTE,
        # `gpu` is passed in so the preflight never spawns a SECOND nvidia-smi
        # probe for a status call that already paid for one.
        "preflight": install_preflight(gpu=gpu),
        "install_history": install_history(),
        "install_history_bounds": install_history_bounds(),
    }


# --------------------------------------------------------------------------- #
#  Install (consented, task-manager job) — pip install into the managed venv.
#
#  Trust model: unlike the Ollama BINARY installer (a root-elevating shell
#  script, needing its own GitHub-attestation checksum verification), this runs
#  `pip install` in an UNPRIVILEGED venv over HTTPS to PyPI -- pip's own
#  resolver + TLS to the index is the accepted trust boundary this project
#  ALREADY relies on for every other pip extra ([analysis], [segmentation], …).
#  No elevation, no root, no shell script -- a materially lower-risk operation,
#  so no separate attested-checksum step is added here.
# --------------------------------------------------------------------------- #
def _check_online() -> None:
    from src.ingest import kill_switch_active

    if kill_switch_active():
        raise VllmLifecycleError(
            "Network is OFF (airplane mode): refusing to install vLLM. "
            "Turn airplane mode off to install."
        )


def platform_support() -> dict:
    """Describe the host OS and whether vLLM can be installed here at all.

    PyPI verified fact (2026-07-25, ``VLLM_VERIFIED_AS_OF``): every recent
    ``vllm`` release ships ONLY ``manylinux`` wheels for x86_64/aarch64 -- no
    macOS wheel, no native Windows wheel, at any version. The sdist fallback
    pip would otherwise attempt needs a full CUDA build toolchain and is not a
    realistic path either. Mirrors ``src.llm.installer.platform_support()``'s
    shape (``{os, arch, supported, reason}``) for the same class of question
    about the Ollama binary installer, but there is no graphical-installer
    alternative to point at here -- the honest answer on a non-Linux host is
    simply "use Ollama instead" (RULED A12: Ollama is never dropped).

    Checked BEFORE any subprocess/venv work in ``run_install_job`` (and by the
    ``/api/llm/vllm/install`` endpoint's own synchronous pre-check, mirroring
    how the airplane-mode and no-GPU checks are both duplicated there) --
    without this, a Windows machine with an NVIDIA GPU (``detect_gpu()`` only
    probes ``nvidia-smi``, which exists on Windows too) would sail past the
    GPU gate straight into a doomed ``pip install`` against wheels that don't
    exist for its platform, surfacing as a confusing raw pip/subprocess error
    instead of an honest, actionable refusal -- the exact "install fails"
    symptom this function exists to turn into a clear message.
    """
    system = platform.system().lower()
    arch = platform.machine().lower()
    if system == "linux":
        return {"os": "linux", "arch": arch, "supported": True}
    return {
        "os": system or "unknown",
        "arch": arch,
        "supported": False,
        "reason": (
            f"vLLM only ships Linux wheels (manylinux x86_64/aarch64) -- there is no "
            f"macOS or Windows build to install on this platform ({system or 'unknown'}). "
            "Ollama is the supported backend here."
        ),
    }


# --------------------------------------------------------------------------- #
#  Install resource preflight (V2, 2026-07-29) -- REAL measurements or an
#  honest absence. Never a guess, and never a fabricated 0.
# --------------------------------------------------------------------------- #
def _gb(n: int | None) -> float | None:
    """Bytes -> GB for display. ``None`` stays ``None`` -- never rendered as 0."""
    return None if n is None else round(n / (1024**3), 2)


def _nearest_existing(path: Path) -> Path | None:
    """The nearest existing ancestor of ``path`` (the venv dir does not exist
    before the first install, and ``shutil.disk_usage`` raises on a missing
    path). ``None`` if nothing on the chain exists."""
    try:
        p = path.resolve()
    except OSError:
        p = path
    for candidate in [p, *p.parents]:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def _free_disk_bytes(path: Path) -> int | None:
    """Free bytes on the volume backing ``path`` (via its nearest existing
    ancestor). ``None`` when unreadable -- an honest ABSENCE, never a 0: a
    fabricated 0 would manufacture a refusal out of an unreadable statvfs."""
    target = _nearest_existing(path)
    if target is None:
        return None
    try:
        return int(shutil.disk_usage(str(target)).free)
    except OSError:
        return None


def _total_ram_bytes() -> int | None:
    """Total physical RAM from ``/proc/meminfo``'s ``MemTotal`` (Linux; this
    whole install path is Linux-only per ``platform_support()``). Read from the
    kernel, never estimated. ``None`` when unreadable -- see ``_free_disk_bytes``
    for why that is never a 0.

    ``/proc/meminfo`` rather than ``psutil`` on purpose: psutil is an optional
    extra ([analysis]) that a core install does not have, and a resource
    preflight that silently degrades to "unknown" on a core install is worth
    less than two lines of stdlib parsing."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    # "MemTotal:       16461176 kB"
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _filesystem_type_of(path: Path) -> str | None:
    """The filesystem backing ``path`` (``tmpfs``/``ramfs`` == RAM-backed), or
    None when unknowable (off Linux) -- an honest unknown, never a guess.

    REUSES the already-correct /proc/mounts parser in ``src.monitoring.forensics``
    rather than re-implementing it: duplicating that parser would be a silent
    drift risk, and forensics exposes no public single-path accessor. The private
    import is isolated to this ONE named seam (which also makes it injectable in
    tests) and guarded, so an import failure degrades rather than crashing. The
    detector resolves non-strictly, so it answers correctly for a directory that
    does not exist yet."""
    try:
        from src.monitoring.forensics import _filesystem_type

        return _filesystem_type(path)
    except Exception:  # noqa: BLE001 - an unknown filesystem is honest; a crash is not
        return None


def _filesystem_facts(path: Path) -> dict:
    """``{path, filesystem, ram_backed}`` for the volume backing ``path``.
    ``ram_backed`` is TRI-STATE -- ``None`` when the filesystem is unknowable
    (the forensics ``at_risk`` precedent), never a reassuring fabricated
    ``False``."""
    fstype = _filesystem_type_of(path)
    return {
        "path": str(path),
        "filesystem": fstype,
        "ram_backed": (fstype in _VOLATILE_FILESYSTEMS) if fstype else None,
    }


def install_preflight(*, version: str = VLLM_VERIFIED_VERSION, gpu: dict | None = None) -> dict:
    """Measure what a vLLM install would actually cost THIS machine, before any
    download. Callable on its own (``GET /api/llm/vllm/install/preflight``, and
    embedded in ``status()``) so the cost is visible before the click, and so it
    is testable without running an install.

    Every number here is READ FROM THE SYSTEM. Where a probe cannot read a value
    it reports ``None`` + ``"measured": False`` and its check is SKIPPED -- never
    estimated, and never defaulted to 0 (a fabricated 0 would turn an unreadable
    file into a refusal, which is the same class of error as a fabricated pass).

    Three deliberately distinct outcome lists:

      * ``blocking``  -- the install CANNOT succeed. Refused unconditionally;
                         ``acknowledge_low_resources`` does NOT override these.
      * ``warnings``  -- it may still work. Refused UNLESS the operator
                         acknowledges (``requires_acknowledgement``).
      * ``notes``     -- facts worth stating that gate nothing (e.g. a probe that
                         could not read its value). Surfaced, never silent.

    ``gpu`` may be passed by a caller that has ALREADY probed (``status()``,
    ``run_install_job``) so a single request never spawns two ``nvidia-smi``
    subprocesses; omitted, it is probed here.

    This is a preflight for the INSTALL. Whether vLLM then serves usefully at a
    given RAM/VRAM is a separate, unmeasured question (design doc §1.5/V5) and
    nothing here claims to answer it."""
    if gpu is None:
        try:
            from src.llm.backend import detect_gpu

            gpu = detect_gpu()
        except Exception:  # noqa: BLE001 - a GPU probe hiccup must not break the preflight
            gpu = None

    tmp = pip_tmpdir()
    free = _free_disk_bytes(tmp)
    ram = _total_ram_bytes()
    fs = _filesystem_facts(tmp)

    free_gb, ram_gb = _gb(free), _gb(ram)
    disk_floor_gb, ram_floor_gb = _gb(INSTALL_DISK_FLOOR_BYTES), _gb(LOW_RAM_WARN_BYTES)
    disk_ok: bool | None = None if free is None else free >= INSTALL_DISK_FLOOR_BYTES
    ram_ok: bool | None = None if ram is None else ram >= LOW_RAM_WARN_BYTES

    blocking: list[dict] = []
    warnings: list[dict] = []
    notes: list[dict] = []

    if disk_ok is False:
        blocking.append(
            {
                "check": "disk",
                "detail": (
                    f"Only {free_gb} GB free on {tmp} -- installing vLLM needs at least "
                    f"{disk_floor_gb} GB there. The download is {ESTIMATED_INSTALL_SIZE_NOTE} "
                    "and pip holds each wheel AND its unpacked contents at the same time. "
                    f"Check what is actually full (look at the 'Avail' column):  df -h {tmp}"
                ),
            }
        )
    elif free is None:
        notes.append(
            {
                "check": "disk",
                "detail": (
                    f"Could not read the free space for {tmp}, so the disk check was skipped "
                    "-- no figure is estimated here. The install may still fail on space."
                ),
            }
        )

    ram_caveat = (
        "That floor is a DISCLOSED heuristic, not a sourced requirement: vLLM needs host "
        "RAM for its Python process, the CUDA context and model loading, on top of GPU "
        "VRAM, and no minimum has been measured for this fleet. It warns; it never decides."
    )
    if ram_ok is False:
        warnings.append(
            {
                "check": "ram",
                "detail": (
                    f"This machine has {ram_gb} GB of total RAM, below the {ram_floor_gb} GB "
                    f"this check flags. {ram_caveat} The install itself may well complete; "
                    "whether the server then runs usefully at this RAM has not been measured."
                ),
            }
        )
    elif ram is None:
        notes.append(
            {
                "check": "ram",
                "detail": (
                    "Could not read /proc/meminfo, so no RAM figure is reported and the RAM "
                    "check was skipped -- nothing is estimated here."
                ),
            }
        )

    if fs["ram_backed"] is True:
        warnings.append(
            {
                "check": "unpack_area",
                "detail": (
                    f"{tmp} is on a {fs['filesystem']} (RAM-backed) filesystem, so the space "
                    "reported free there is RAM, not disk -- and pointing pip's TMPDIR at it "
                    "(which this install does) cannot help. Set OO_DATA_DIR (or "
                    "OO_VLLM_VENV_DIR) to a path on real disk before installing."
                ),
            }
        )
    elif fs["filesystem"] is None:
        notes.append(
            {
                "check": "unpack_area",
                "detail": (
                    f"Could not determine the filesystem backing {tmp} (unknown, not assumed)."
                ),
            }
        )

    return {
        "schema": "oo-vllm-install-preflight-1",
        "version": version,
        "checked_at": time.time(),
        "venv_dir": str(venv_dir()),
        "gpu": gpu,
        "disk": {
            "path": str(tmp),
            "measured": free is not None,
            "free_bytes": free,
            "free_gb": free_gb,
            "floor_bytes": INSTALL_DISK_FLOOR_BYTES,
            "floor_gb": disk_floor_gb,
            "sufficient": disk_ok,
            "method": (
                "shutil.disk_usage() on the volume that will hold both the vLLM venv and "
                "pip's unpack area"
            ),
        },
        "ram": {
            "measured": ram is not None,
            "total_bytes": ram,
            "total_gb": ram_gb,
            "floor_bytes": LOW_RAM_WARN_BYTES,
            "floor_gb": ram_floor_gb,
            "sufficient": ram_ok,
            "method": "MemTotal from /proc/meminfo (Linux; this install path is Linux-only)",
            "caveat": ram_caveat,
        },
        "unpack_area": {
            **fs,
            "note": (
                "pip unpacks wheels here during the install; this install points TMPDIR at "
                "it so unpacking never lands on a small RAM-backed /tmp."
            ),
        },
        "blocking": blocking,
        "warnings": warnings,
        "notes": notes,
        "requires_acknowledgement": bool(warnings),
        "estimated_size_note": ESTIMATED_INSTALL_SIZE_NOTE,
    }


def _install_env(tmpdir: Path) -> dict[str, str]:
    """The environment for the install subprocesses: the ambient environment
    (PATH, proxy vars, locale -- all preserved) with ``TMPDIR`` redirected onto
    real disk. Mirrors ``install.sh:pip_install``'s ``TMPDIR="$pip_tmp" pip
    install ...``; TMPDIR only, matching that precedent (TMP/TEMP are Windows
    conventions and this path is Linux-only)."""
    env = dict(os.environ)
    env["TMPDIR"] = str(tmpdir)
    return env


def run_install_job(
    ctx,
    *,
    version: str = VLLM_VERIFIED_VERSION,
    runner: Callable[..., Iterator[str]] | None = None,
    acknowledge_low_resources: bool = False,
) -> dict:
    """``BackgroundJob`` worker: create the managed venv (if absent) + ``pip
    install vllm==<version>``, streaming honest PHASE text (pip gives no
    reliable percentage, so this never fakes one — B2.3). Refuses up front on a
    non-Linux host (no vLLM wheel exists there at all -- ``platform_support()``),
    a CPU-only machine, or under airplane mode. Writes the install marker ONLY
    on a verified-successful pip exit code — a failed install leaves NO
    marker, so ``is_installed()`` never claims a half-configured backend
    works.

    TMPDIR (V1, 2026-07-29 -- a RECURRENCE of a fix this project already made
    for ``install.sh:pip_install``; CLAUDE.md:519-520): pip unpacks each wheel in
    ``$TMPDIR`` before installing it, and on Qubes the ambient ``/tmp`` is a
    small RAM-backed tmpfs. vLLM drags torch + the CUDA runtime (5-10 GB), so
    inheriting that ``/tmp`` fails with ``Errno 28`` *while ``df`` reports
    hundreds of GB free* -- the exact confusing symptom the operator hit. Every
    install subprocess therefore runs with ``TMPDIR`` pointed at
    ``pip_tmpdir()``, on the same volume as the venv being built, and that
    directory is removed in a ``finally`` on every exit path (success, failure,
    cancel).

    RESOURCE PREFLIGHT (V2): measured BEFORE any subprocess, so a doomed
    multi-GB download never starts. ``acknowledge_low_resources`` carries the
    operator's explicit confirmation past a preflight WARNING (low RAM, or a
    RAM-backed install target). It never overrides a BLOCKING entry: an install
    with no room on disk cannot succeed, so no acknowledgement makes it honest
    to try.

    ATTEMPT JOURNAL (V3): every attempt -- installed, error or cancelled -- is
    appended to the bounded journal (``install_history()``) with the phase it
    reached, the REAL exit code, a bounded tail of the failing phase's output
    and the preflight it ran against. The PRE-WORK refusals below (platform /
    airplane / no GPU / blocking preflight) are deliberately NOT journalled:
    they consume nothing, the endpoint pre-checks them synchronously, and each
    is already answerable live from ``status()`` -- journalling them would evict
    real attempts from a 20-slot history."""
    from src.llm.backend import detect_gpu

    support = platform_support()
    if not support["supported"]:
        raise VllmUnsupportedError(support["reason"])
    _check_online()
    gpu = detect_gpu()
    if not gpu.get("available"):
        raise VllmUnsupportedError(
            "No GPU detected on this machine -- vLLM is GPU-first and would install "
            "into a backend that can never usefully run. Use Ollama instead."
        )

    # V2: measure BEFORE any subprocess. `gpu` is threaded through so the
    # preflight never spawns a second nvidia-smi.
    preflight = install_preflight(version=version, gpu=gpu)
    if preflight["blocking"]:
        raise VllmLifecycleError(
            "Cannot install vLLM on this machine. "
            + " ".join(b["detail"] for b in preflight["blocking"])
        )
    if preflight["requires_acknowledgement"] and not acknowledge_low_resources:
        raise VllmLifecycleError(
            "This machine is below a resource floor for a vLLM install. "
            + " ".join(w["detail"] for w in preflight["warnings"])
            + " Re-run the install with acknowledge_low_resources to proceed anyway."
        )

    phase = "venv"
    tail: deque[str] = deque(maxlen=_OUTPUT_TAIL_LINES)
    lines_total = 0

    def _journal(outcome: str, *, exit_code: int | None = None, error: str | None = None) -> None:
        record_install_attempt(
            version=version,
            phase=phase,
            outcome=outcome,
            exit_code=exit_code,
            error=error,
            output_tail=list(tail),
            output_lines_total=lines_total,
            preflight=preflight,
        )

    ctx.set_progress(detail="preparing the managed venv")
    d = venv_dir()
    tmp = pip_tmpdir()
    env = _install_env(tmp)
    try:
        tmp.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise VllmLifecycleError(
            f"could not create pip's unpack directory {tmp}: {exc}"
        ) from exc
    try:
        run = runner or _default_runner
        if not venv_python().is_file():
            # None, not 0: only the `__exit__` sentinel may declare success. A
            # runner that yields no sentinel must never write the marker.
            venv_exit_code: int | None = None
            for line in run([sys.executable, "-m", "venv", str(d)], env=env):
                if ctx.stopping:
                    _journal("cancelled")
                    return {"installed": False, "state": "cancelled"}
                if line.startswith("__exit__ "):
                    venv_exit_code = int(line.split(" ", 1)[1].strip() or "1")
                    continue
                lines_total += 1
                tail.append(line)
                ctx.set_progress(detail=f"venv: {line[:120]}")
            if venv_exit_code is None:
                msg = (
                    "creating the vLLM venv produced no exit status -- refusing to "
                    "continue on an unconfirmed result."
                )
                _journal("error", error=msg)
                raise VllmLifecycleError(msg)
            if venv_exit_code != 0:
                msg = (
                    f"could not create the vLLM venv (python -m venv exit code {venv_exit_code})."
                )
                _journal("error", exit_code=venv_exit_code, error=msg)
                raise VllmLifecycleError(msg)
        pip = venv_bin("pip")
        if not pip.is_file():
            msg = (
                f"the managed venv at {d} has no pip ({pip}). On Debian/Tails the stdlib "
                "'ensurepip' module ships in a separate package -- install python3-venv "
                "for your interpreter and retry."
            )
            _journal("error", error=msg)
            raise VllmLifecycleError(msg)
        ctx.set_progress(
            detail=f"pip install vllm=={version} (this downloads {ESTIMATED_INSTALL_SIZE_NOTE})"
        )
        # A fresh tail per phase: if pip fails, the venv phase's output is noise.
        phase = "pip"
        tail.clear()
        lines_total = 0
        # --retries/--timeout mirror install.sh:pip_install: pip's 15s default turns a
        # dropped link into a MISLEADING "ResolutionImpossible / no matching
        # distribution", and a 5-10 GB download is exposed to that for a long time.
        argv = [str(pip), "install", "--retries", "5", "--timeout", "60", f"vllm=={version}"]
        exit_code: int | None = None
        for line in run(argv, env=env):
            if ctx.stopping:
                _journal("cancelled")
                return {"installed": False, "state": "cancelled"}
            if line.startswith("__exit__ "):
                exit_code = int(line.split(" ", 1)[1].strip() or "1")
                continue
            lines_total += 1
            tail.append(line)
            ctx.set_progress(detail=line[:200])
        if exit_code is None:
            msg = (
                f"pip install vllm=={version} produced no exit status -- refusing to "
                "record an install that was never confirmed to succeed."
            )
            _journal("error", error=msg)
            raise VllmLifecycleError(msg)
        if exit_code != 0:
            joined = "\n".join(tail).lower()
            if any(m in joined for m in _ENOSPC_MARKERS):
                # Classify rather than echo a bare exit code (CLAUDE.md:519-520).
                msg = (
                    f"pip install vllm=={version} ran out of disk space while unpacking "
                    "(pip: 'No space left on device'). This install already points pip's "
                    f"TMPDIR at {tmp}, so the volume behind that path is what filled up. "
                    f"Check it (look at the 'Avail' column):  df -h {tmp}"
                )
            else:
                msg = f"pip install vllm=={version} failed (exit code {exit_code})."
            _journal("error", exit_code=exit_code, error=msg)
            raise VllmLifecycleError(msg)
        _write_marker(version)
        phase = "done"
        _journal("installed", exit_code=0)
        return {"installed": True, "version": version, "state": "done"}
    finally:
        # Every exit path -- success, raise, and the two cancel returns.
        shutil.rmtree(tmp, ignore_errors=True)


def _default_runner(argv: list[str], env: dict[str, str] | None = None) -> Iterator[str]:
    """Run a real subprocess, yielding its output lines then a final
    ``__exit__ <code>`` sentinel (mirrors ``src.llm.installer.run_installer``'s
    streaming shape).

    ``env`` defaults to ``None``, which is ``Popen``'s inherit-the-ambient-
    environment behaviour -- i.e. byte-identical to this function before the
    TMPDIR fix, so any other caller is unaffected. The vLLM install passes an
    env whose ``TMPDIR`` is on real disk (``_install_env``)."""
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield line.rstrip("\n")
    finally:
        proc.stdout.close()
        code = proc.wait()
    yield f"__exit__ {code}"
