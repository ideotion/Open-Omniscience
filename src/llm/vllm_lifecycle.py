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
import math
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


def server_log_path() -> Path:
    """Where the vLLM server's own stdout/stderr is captured.

    Field report 2026-07-29: a maintainer set a HuggingFace model, clicked start, and
    got "doesn't work" with nothing to act on. Root cause was here -- the server was
    spawned with stdout AND stderr to DEVNULL, so every startup failure (a gated or
    misspelled repo id, a missing HF token, and above all a CUDA OOM when the weights
    do not fit the card) killed the process SILENTLY. The UI could then only report
    "not running", forever, with no way to learn why.

    A server whose failures are invisible is not diagnosable, and this project's rule
    is to degrade LOUDLY. The log is truncated at each start so it always describes the
    CURRENT attempt rather than accumulating unboundedly.
    """
    return venv_dir() / "server.log"


# How much of the server log the status payload carries, from EACH END. Bounded so
# the Settings panel never has to render a multi-megabyte field.
#
# BOTH ends, because the root cause can be at either (field report 2026-08-02). This
# used to keep only the tail, on the stated assumption that "a CUDA OOM message puts
# the actionable numbers at the END". That is true when a RUNNING server dies, and
# exactly false for the failure that actually reached the field: vLLM's EngineCore is
# a CHILD process, so it prints its own traceback FIRST and the parent APIServer then
# dumps ~20 KB of its own stack ending in the words "See root cause above." The
# retained tail was therefore guaranteed to hold the useless half. The operator's
# bundle showed precisely that -- 29,855 bytes of log, the last 8,000 kept, and the
# reason the server died sitting in the 21,855 that were thrown away.
_LOG_HEAD_BYTES = 8000
_LOG_TAIL_BYTES = 8000


def server_log_tail(*, limit: int = _LOG_TAIL_BYTES, head_limit: int = _LOG_HEAD_BYTES) -> dict:
    """Both ends of the last server start's output, for the UI and the diagnostics
    bundle. Degrades to a stated absence -- never an empty string that would read as
    "the server said nothing wrong".

    ``tail`` keeps its meaning (the last bytes) so existing readers are unaffected;
    ``head`` and ``elided_bytes`` are additive. When the whole file fits, ``head`` is
    absent rather than a duplicate of ``tail`` -- a reader must never be shown the same
    text twice and left to wonder whether the server said it twice."""
    p = server_log_path()
    try:
        if not p.is_file():
            return {"available": False, "reason": "no server log yet (never started here)"}
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size <= limit:
                return {
                    "available": True,
                    "path": str(p),
                    "bytes": size,
                    "truncated": False,
                    "elided_bytes": 0,
                    "tail": fh.read().decode("utf-8", errors="replace"),
                }
            head = fh.read(min(head_limit, max(0, size - limit)))
            fh.seek(size - limit)
            tail = fh.read()
        elided = size - len(head) - limit
        return {
            "available": True,
            "path": str(p),
            "bytes": size,
            "truncated": True,
            # Stated, never implied: a reader must be able to tell that the two halves
            # are not contiguous, and by how much.
            "elided_bytes": elided,
            "head": head.decode("utf-8", errors="replace"),
            "tail": tail.decode("utf-8", errors="replace"),
        }
    except OSError as exc:
        return {"available": False, "reason": f"could not read the server log: {exc}"}


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
    """A cheap check (no subprocess) -- the marker is written ONLY after a verified
    successful ``pip install`` (see ``run_install_job``).

    The marker must be READABLE, not merely present (2026-07-29): a torn write left
    a zero-byte file that satisfied ``is_file()``, so the app reported vLLM installed
    while ``install_info()`` returned None. "Installed" is a claim; an unreadable
    record cannot support it. ``_write_marker`` is atomic, so this only matters for
    a marker written by an older build."""
    return _marker_path().is_file() and venv_python().is_file() and install_info() is not None


def install_info() -> dict | None:
    """The persisted install record ({version, installed_at}), or None."""
    p = _marker_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a sibling temp + ``os.replace``.

    The project's standing convention for any file whose HALF-WRITTEN state would be
    misread (``_atomic_copy`` / the manifest swap). Used here for the install marker
    (a torn one used to read as "installed") and the journal trim (a torn one used to
    destroy the whole history). The temp is cleaned if the replace itself fails, so a
    validated temp is never orphaned."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _write_marker(version: str) -> None:
    venv_dir().mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        _marker_path(), json.dumps({"version": version, "installed_at": time.time()})
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

# How often an IDLE install subprocess wakes the caller so its cancel check can run.
# pip is silent for the whole of a multi-GB wheel download, so without this a Cancel
# click is not seen until the download ends (see _default_runner).
_RUNNER_POLL_S = 0.5
# How many attempts an INTERACTIVE status() carries. The full journal (bounded at
# _ATTEMPTS_CAP) is ~414 KB at worst case and rides a panel the operator refreshes;
# the diagnostics bundle asks for all of it explicitly.
_UI_HISTORY_LIMIT = 3
# Yielded while the child is silent. Consumed by run_install_job's stop check and
# NEVER counted as output: it is our own heartbeat, not something pip said.
_HEARTBEAT = "__tick__"

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
    resolver: str | None = None,
    fallback_fired: bool | None = None,
    started_at: float | None = None,
    duration_s: float | None = None,
) -> None:
    """Append one attempt to the bounded journal. NEVER RAISES: on any failure it
    logs once and disables recording for this process (log + disable, never
    raise), so the journal can never abort the install it exists to record.

    VERIFIABILITY (2026-08-01): ``resolver`` / ``fallback_fired`` / ``duration_s``
    exist so an operator's exported bundle can ANSWER the questions the uv switch
    raised, instead of leaving them to inference:

    * ``resolver`` -- ``"uv"`` or ``"pip"``, recorded as its own field. The
      resolver name is also folded into ``phase``, but reading it back out of a
      phase string is parsing, and a diagnostic whose whole job is "which path
      ran?" should not answer it by string-matching its own log.
    * ``fallback_fired`` -- True when uv was wanted but pip actually ran. That is
      the single fact distinguishing "uv worked" from "uv silently failed and pip
      quietly saved us", which otherwise look identical from a successful install.
    * ``duration_s`` -- wall time for the attempt. The uv switch was justified by
      pip being slow on torch + the CUDA runtime; without a duration the journal
      cannot measure the very thing the change was made for. ``None`` when the
      caller did not time it -- never 0, which would read as an instant install.

    All four are optional so existing callers (and every already-written journal
    line) stay valid; a reader must treat a missing field as unknown, not false."""
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
            "resolver": (str(resolver) if resolver else None),
            "fallback_fired": fallback_fired,
            "started_at": (float(started_at) if started_at is not None else None),
            "duration_s": (round(float(duration_s), 3) if duration_s is not None else None),
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
            # ATOMIC (2026-07-29): the APPEND above degrades safely by design (a torn
            # tail is one unparseable line, which install_history skips), but a
            # truncate-then-write TRIM has a window in which the file is EMPTY -- and a
            # crash there destroys the whole history. That is the one thing a journal
            # whose stated purpose is surviving a crash must not do to itself.
            _atomic_write_text(path, "\n".join(lines[-_ATTEMPTS_CAP:]) + "\n")
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


def port_occupant(*, timeout: float = 2.0) -> dict:
    """WHO is on vLLM's port -- ``{"state": ..., "port": int, "detail": str}``.

    ``is_running()`` collapses every failure to False, which is right for "is it
    up?" and WRONG as an explanation. In the field (2026-08-02) vLLM's port was
    the app's own, so the probe reached the APP, got a 404 for ``/v1/models``,
    and reported "vLLM is down" 270 times while the real answer was "vLLM cannot
    live here". Those need different words, because they need different actions.

    ``state`` is one of:
      ``vllm``     -- a vLLM server answered; it is up.
      ``foreign``  -- SOMETHING answered but it is not vLLM. Occupied port.
      ``free``     -- nothing is listening. vLLM is simply not started.
      ``unknown``  -- the probe itself failed; never guessed as one of the above.
    """
    import socket as _socket
    from urllib.parse import urlparse

    from src.llm.vllm_client import VllmClient

    url = base_url()
    parsed = urlparse(url)
    port = parsed.port or 0
    try:
        if VllmClient(timeout=timeout).is_available():
            return {"state": "vllm", "port": port, "detail": f"a vLLM server is answering at {url}."}
    except Exception:  # noqa: BLE001 - a probe must never raise
        pass
    # Nothing vLLM-shaped answered. Is ANYTHING listening?
    try:
        with _socket.socket() as s:
            s.settimeout(timeout)
            connected = s.connect_ex((parsed.hostname or "127.0.0.1", port)) == 0
    except OSError:
        return {"state": "unknown", "port": port, "detail": f"could not probe {url}."}
    if not connected:
        return {
            "state": "free",
            "port": port,
            "detail": f"nothing is listening on port {port} -- vLLM is installed but not started.",
        }
    return {
        "state": "foreign",
        "port": port,
        "detail": (
            f"port {port} is already taken by another server, which is not vLLM. "
            "vLLM cannot bind it, so starting the server will fail until the port "
            "is free or OO_VLLM_PORT points somewhere else."
        ),
    }


def process_alive() -> bool:
    """True if THIS process is tracking a live subprocess (distinct from
    ``is_running()`` -- a server started by another means, or one still loading
    its model, is not reflected here)."""
    return _proc is not None and _proc.poll() is None


def start_outcome() -> dict:
    """What became of the last start THIS process spawned: a tri-state, not a boolean.

    ``start()`` returns the moment ``Popen`` succeeds, because a model load takes tens
    of seconds and blocking the request thread on it would be worse. That is correct,
    and it left a hole: if the child then DIES during engine initialisation, nothing
    said so. ``running`` stayed false and ``process_tracked`` stayed false -- exactly
    the same pair a server that is still loading shows -- so a failed start and a slow
    one were indistinguishable, and the caller's only recourse was to keep polling a
    port that would never open (field report 2026-08-02: "local model hiccup (1/10) --
    retrying in 5s", ten times, against a server that had already exited).

    The same lesson the port collision taught: a boolean up/down probe cannot separate
    "not started" from "started and gone", and it will confidently answer the wrong one.

      * ``not-started``  nothing was spawned by this process
      * ``starting``     the child is alive but not answering yet (the normal case)
      * ``ready``        the child is alive and the API answers
      * ``exited``       the child is GONE, with its returncode -- a failed start

    ``exited`` carries ``log_hint`` pointing at the log's HEAD, because for a startup
    failure that is where the reason is: EngineCore is a child of the API server, so it
    prints its traceback first and the parent's stack follows it.
    """
    if _proc is None:
        return {
            "state": "not-started",
            "detail": "no vLLM server was started by this process",
        }
    code = _proc.poll()
    if code is None:
        if is_running():
            return {"state": "ready", "detail": "the server is answering", "pid": _proc.pid}
        return {
            "state": "starting",
            "pid": _proc.pid,
            "detail": (
                "the server process is alive but not answering yet -- a model load takes "
                "tens of seconds; this is the normal path, not a failure"
            ),
        }
    return {
        "state": "exited",
        "returncode": code,
        "detail": (
            f"the server process exited with code {code} -- the start FAILED. It is not "
            "still loading, and polling will never succeed; start it again after fixing "
            "the cause below."
        ),
        "log_hint": (
            "read the HEAD of the server log: vLLM's EngineCore is a child process, so a "
            "startup failure prints its traceback FIRST and the parent's stack (ending in "
            "'See root cause above') follows it"
        ),
        "log_path": str(server_log_path()),
    }


# --------------------------------------------------------------------------- #
#  Context-size auto-tune (B2.5, ruled: disclosed auto-with-override)
# --------------------------------------------------------------------------- #
#: KV-cache cost of ONE context token, in MB -- the constant the context estimate
#: divides by. Derived, not guessed: 2 (K and V) x 32 layers x 32 heads x 128 head
#: dim x 2 bytes (fp16) = 512 KB for a 7B-class model with multi-head attention.
#: A grouped-query model (what we actually ship) costs ~4x less, so this errs toward
#: a SHORTER context, which is the survivable direction on a small card.
_KV_MB_PER_TOKEN = 0.5


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
    ``weight_footprint_gb`` for the model's own weights (a stated ESTIMATE -- see
    the note below on why the default is 5.0); of the remainder,
    ``kv_cache_reserve_frac`` is kept
    as headroom (activation memory / fragmentation), and ``gpu_memory_utilization``
    is set to use the rest. ``max_model_len`` scales with the remaining VRAM at a
    rough ~1 MB/token/layer-class budget (a conservative, DISCLOSED heuristic --
    never a measured fact; the operator override always wins).

    Returns ``{"max_model_len", "gpu_memory_utilization", "method", "caveat"}``.
    An explicit override for either field is honoured verbatim (no re-derivation).

    ON THE 5.0 GB DEFAULT (corrected 2026-07-30): this used to be documented as
    matching "a 4-bit-quantized Mistral-7B-class model, the RULED default model".
    That description is stale -- ``DEFAULT_VLLM_MODEL`` is Ministral 3 **3B** served
    in FP8 (~3.5 GB), because the 8B does not fit 8 GB of VRAM in any published vLLM
    build. The NUMBER is deliberately left at 5.0 rather than lowered to match:
    over-reserving costs context length, while under-reserving costs an OOM at
    startup, and on a small card the second failure is much worse than the first.
    So 5.0 is now an explicit conservative MARGIN over the real footprint, not a
    match to it. An operator who wants the extra context sets
    ``weight_footprint_gb`` (or ``max_model_len`` directly) and the override wins.
    """
    method = (
        f"reserve {weight_footprint_gb} GB for model weights, "
        f"{kv_cache_reserve_frac:.0%} of the remainder as headroom; the rest sets "
        f"gpu_memory_utilization; max_model_len = the remaining KV budget divided by "
        f"{_KV_MB_PER_TOKEN} MB/token (a 7B-class fp16 multi-head figure, deliberately "
        f"conservative), floored at 2048 and capped at 32768."
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
        # UNIT CORRECTED 2026-08-02. The 0.5 MB figure is per TOKEN, not per 1K
        # tokens: a 7B-class model with plain multi-head attention at fp16 costs
        # 2 (K+V) x 32 layers x 32 heads x 128 dim x 2 bytes = 512 KB per token.
        # Written as "per 1K tokens" and then multiplied by 1000, it over-counted
        # the affordable context by ~1000x, so `est_tokens` came out in the
        # MILLIONS and the 32768 cap silently decided every machine: a 6 GB card
        # with 0.85 GB of KV budget and an 80 GB card with 63.75 GB were both
        # handed 32768. The method string published to the operator said the value
        # "scales with the remaining VRAM" while it was a constant -- a fabricated
        # disclosure, and the likely cause of the field's engine-init failure
        # (32768 tokens asked of a 2.55 GB budget on an 8 GB laptop card).
        #
        # 0.5 MB/token stays DELIBERATELY conservative rather than being lowered to
        # match the shipped 3B model's grouped-query attention (~0.125 MB/token):
        # this function's own stated principle is that over-reserving costs context
        # length while under-reserving costs an OOM at startup, and on a small card
        # the second failure is much worse than the first.
        est_tokens = int((kv_gb * 1024) / _KV_MB_PER_TOKEN)
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
    port: int | None = None,
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
    # Resolved here, not defaulted in the signature: a signature default binds at
    # import and would freeze whatever OO_PORT was then -- the same staleness that
    # let the server and the client disagree about the address.
    if port is None:
        from src.llm.vllm_client import default_vllm_port

        port = default_vllm_port()
    argv += ["--host", host, "--port", str(port)]
    if max_model_len is not None:
        argv += ["--max-model-len", str(max_model_len)]
    if gpu_memory_utilization is not None:
        argv += ["--gpu-memory-utilization", str(gpu_memory_utilization)]
    return argv


_PARAM_RE = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)\s*[Bb](?![A-Za-z0-9])")
# Quantisation hints that appear in real repo/tag names. ~0.6 GB per billion params is
# the 4-bit ballpark (4 bits of weight + scales/zeros overhead); fp16/bf16 is 2.0.
_QUANT_HINTS = ("q4", "q5", "q8", "awq", "gptq", "int4", "int8", "4bit", "8bit", "nf4")
# FP8 is ~1 byte/param. Named separately from the 4-bit hints because it is a real,
# distinct tier -- and because assuming fp16 for anything unlabelled is what produced a
# wrong figure in the field (Ministral 3's Instruct checkpoints ship FP8 without saying
# so in the repo name).
_FP8_HINTS = ("fp8", "f8")


def estimate_weights_gb(model: str) -> dict:
    """Rough weight footprint for a model id, or an honest "unknown".

    vLLM loads fp16/bf16 by default, so an 8B model needs ~16 GB of WEIGHTS ALONE --
    it cannot start on an 8 GB card no matter how the KV cache is tuned. That is
    exactly the failure a maintainer hit with ``Ministral-3-8B-Instruct-2512`` on an
    8 GB GPU, and before this it surfaced only as a silent death.

    This is a HEURISTIC over the model NAME and says so: ``method`` states how the
    number was reached and ``confident`` is False whenever the name did not actually
    carry a parameter count. It never fabricates a figure -- an unparseable name
    returns None and the caller must not pretend to know.
    """
    name = (model or "").lower()
    m = _PARAM_RE.search(name)
    if not m:
        return {
            "params_b": None,
            "weights_gb": None,
            "quantised": None,
            "confident": False,
            "method": "no parameter count in the model name -- footprint unknown",
        }
    params = float(m.group(1))
    quantised = any(h in name for h in _QUANT_HINTS)
    fp8 = any(h in name for h in _FP8_HINTS)
    # A RANGE, not a point estimate. The earlier version reported a single fp16 figure
    # and was WRONG in the field: Ministral 3's Instruct checkpoints ship in FP8, so
    # "Ministral-3-8B-Instruct-2512" is ~8 GB of weights, not the ~16 GB that was
    # published to a maintainer. A model NAME does not carry its dtype, so claiming one
    # number was fabricated precision. The honest form states both ends and lets the
    # caller refuse only when even the OPTIMISTIC end does not fit.
    if quantised:
        low = high = params * 0.6
        basis = "4-bit quantised (from the name)"
    elif fp8:
        low = high = params * 1.0
        basis = "FP8 (from the name)"
    else:
        low, high = params * 1.0, params * 2.0
        basis = (
            "dtype NOT stated in the name -- FP8 (1 GB/B) to fp16/bf16 (2 GB/B); "
            "many recent Instruct checkpoints ship FP8"
        )
    return {
        "params_b": params,
        "weights_gb_low": round(low, 1),
        "weights_gb_high": round(high, 1),
        # Kept for callers that want one number to show: the OPTIMISTIC end, so nothing
        # downstream can overstate a model's cost.
        "weights_gb": round(low, 1),
        "quantised": quantised,
        "confident": True,
        "method": (
            f"{params:g}B parameters x {basis}, read from the model NAME -- "
            "weights only, excludes KV cache and activations"
        ),
    }


def vram_fit(model: str, vram_mb: int | None) -> dict:
    """Does this model's weight footprint plausibly fit this card?

    Verdicts: ``fits`` / ``tight`` / ``too_large`` / ``unknown``. ``unknown`` is a real
    answer, not a soft pass -- when the name carries no parameter count nothing is
    claimed either way, and the caller proceeds rather than refusing on a guess.
    """
    est = estimate_weights_gb(model)
    if not vram_mb or vram_mb <= 0 or est["weights_gb"] is None:
        return {"verdict": "unknown", "estimate": est, "vram_gb": None}
    vram_gb = round(vram_mb / 1024.0, 1)
    # Judge on the OPTIMISTIC end of the range. A refusal built on the pessimistic end
    # would block models that actually fit -- exactly the mistake that reported ~16 GB
    # for an FP8 8B. "too_large" now means "cannot fit even at the most favourable dtype
    # the name permits", which is a claim the estimate can actually support.
    low = est["weights_gb_low"]
    high = est.get("weights_gb_high", low)
    if low >= vram_gb:
        verdict = "too_large"
    elif high > vram_gb * 0.75:
        # Either genuinely close, or unknown-dtype where the pessimistic end is close.
        verdict = "tight"
    else:
        verdict = "fits"
    return {"verdict": verdict, "estimate": est, "vram_gb": vram_gb}


def start(
    model: str,
    *,
    max_model_len: int | None = None,
    gpu_memory_utilization: float | None = None,
    allow_oversized: bool = False,
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
    # Refuse a model whose WEIGHTS alone exceed the card, with the numbers, instead of
    # letting it CUDA-OOM into a silent death (field report 2026-07-29). Acknowledgeable
    # rather than absolute -- the estimate reads the model NAME, so a quantised repo
    # that does not say so in its name must still be startable by an operator who knows
    # better. Never fires on `unknown`: refusing on a guess would be its own fabrication.
    fit = vram_fit(model, gpu.get("vram_mb"))
    if fit["verdict"] == "too_large" and not allow_oversized:
        est = fit["estimate"]
        lo, hi = est["weights_gb_low"], est.get("weights_gb_high", est["weights_gb_low"])
        span = f"{lo} GB" if lo == hi else f"{lo}-{hi} GB"
        raise VllmUnsupportedError(
            f"{model} needs about {span} of weights ({est['method']}), but this GPU has "
            f"{fit['vram_gb']} GB -- so it does not fit even at the most favourable "
            "precision, before any KV cache. Use a smaller variant (the 3B class fits "
            "8 GB), a 4-bit AWQ/GPTQ build, or Ollama, which runs quantised models on "
            "far less memory."
        )
    args = compute_server_args(
        gpu.get("vram_mb"),
        max_model_len_override=max_model_len,
        gpu_memory_utilization_override=gpu_memory_utilization,
    )
    # Refuse a start that CANNOT succeed, before spawning anything (field report
    # 2026-08-02). vLLM's port was the app's own, so `vllm serve` hit
    # OSError(98) Address already in use and died instantly; the only symptom
    # anywhere was "running: false". A doomed launch should be an honest,
    # actionable refusal, not a subprocess that disappears -- the same principle
    # platform_support() already applies to a doomed install.
    occupant = port_occupant()
    if occupant["state"] == "foreign":
        raise VllmLifecycleError(
            occupant["detail"]
            + " (If this is the Open Omniscience app itself, the two are meant to"
            " differ -- vLLM's port is derived from OO_PORT, so check whether"
            " OO_VLLM_PORT or OO_VLLM_URL has been set to the app's port.)"
        )

    argv = server_argv(
        model,
        max_model_len=args["max_model_len"],
        gpu_memory_utilization=args["gpu_memory_utilization"],
    )
    run = popen or subprocess.Popen
    # CAPTURE the server's output instead of discarding it (field report 2026-07-29).
    # This used to be stdout=DEVNULL, stderr=DEVNULL, which made every startup failure
    # invisible: a gated/misspelled HF repo, a missing token, or a CUDA OOM all ended
    # as "not running" with no explanation anywhere in the app. Opened in "wb" so each
    # start describes the CURRENT attempt and the file cannot grow without bound.
    log_fh = None
    try:
        server_log_path().parent.mkdir(parents=True, exist_ok=True)
        log_fh = server_log_path().open("wb")
    except OSError:  # noqa: BLE001 - losing the log must never block the start itself
        log_fh = None
    out = log_fh or subprocess.DEVNULL
    # HF_HOME points the server's weight cache at the app's own model folder
    # (2026-08-04 maintainer ask). vLLM downloads and reads weights through
    # huggingface_hub, which honours it, so this is the whole mechanism -- and it must
    # be the SAME answer ``hf_cache_dir()`` gives, or a probe and a download would
    # disagree about where the weights are.
    from src.llm.model_store import launch_env

    proc = run(argv, stdout=out, stderr=subprocess.STDOUT, env=launch_env())  # noqa: S603
    _proc = proc
    return {
        "started": True,
        "model": model,
        "argv": argv,
        "server_args": args,
        "base_url": base_url(),
        "log_path": str(server_log_path()) if log_fh is not None else None,
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


def status(*, history_limit: int | None = _UI_HISTORY_LIMIT) -> dict:
    """A full status snapshot for the Settings -> AI tab and the diagnostics
    member (B7) -- installed/running/GPU/platform facts, never a fabricated
    readiness. ``platform`` is disclosed here (not just at install-attempt
    time) so a non-Linux machine sees "not supported here" BEFORE ever
    reaching for the install button.

    ``history_limit`` bounds ``install_history`` for INTERACTIVE callers. The
    journal is bounded by construction, but its worst case is real: 20 attempts x
    50 lines x 400 chars measured 414 KB, and this payload is fetched by the
    Settings -> AI panel and by the red-pill click -- on precisely the machine
    whose installs keep failing, which is what fills it. The diagnostics member
    passes ``None`` for the COMPLETE journal, because being diagnosable after a
    restart is the whole point of V3. The truncation is never silent:
    ``install_history_bounds`` states what was kept and the real total.

    ``preflight`` (V2) carries the MEASURED install cost -- free disk on the
    volume the venv lives on, total system RAM, whether the unpack area is
    RAM-backed -- so the cost is visible BEFORE the button, and so a diagnostics
    bundle records why an install refused (the 2026-07-29 operator bundle could
    not show that). ``install_history`` (V3) records every ATTEMPT, not just the
    successes the marker records, so a failed install stays diagnosable after a
    restart. Both are ADDITIVE -- every existing consumer is unaffected."""
    from src.llm.backend import detect_gpu

    gpu = detect_gpu()
    hist = install_history()
    return {
        "installed": is_installed(),
        "install_info": install_info(),
        # `installed` reads the MARKER; this reads the venv. They disagree exactly
        # when an install is broken -- a marker written by a past success while the
        # venv was later damaged, moved, or built against a Python that is gone.
        # That is the state a restart lands in, and until now the only symptom was a
        # backend that reported installed and then failed to start, with nothing in
        # the exported bundle able to tell the two apart. `None` = unrecognised
        # layout, i.e. not measurable -- never collapsed into False.
        "package_present": _package_present(venv_dir(), "vllm"),
        "running": is_running(),
        # WHO is on the port, not merely whether vLLM answered. "running: false"
        # alone sent a field report down the wrong path entirely (2026-08-02):
        # the port was the app's own, so "not running" was true and useless --
        # the actionable fact was that vLLM could never bind it.
        "port_occupant": port_occupant(),
        "process_tracked": process_alive(),
        # WHAT BECAME of the last start, as a tri-state. `process_tracked: false` is
        # shown by a server that is still loading AND by one that died during engine
        # init; conflating them is what made a failed start read as a transient hiccup
        # worth retrying ten times (field report 2026-08-02).
        "start_outcome": start_outcome(),
        "gpu": gpu,
        "platform": platform_support(),
        "base_url": base_url(),
        "venv_dir": str(venv_dir()),
        # The last start's own output (field report 2026-07-29). Without this, a server
        # that died on a gated repo, a bad model id or a CUDA OOM was reported only as
        # "not running", with the reason discarded to DEVNULL and unrecoverable.
        # `installed and not running` is precisely when an operator needs it.
        "server_log": server_log_tail(),
        "verified_version": VLLM_VERIFIED_VERSION,
        "verified_as_of": VLLM_VERIFIED_AS_OF,
        "estimated_size_note": ESTIMATED_INSTALL_SIZE_NOTE,
        # `gpu` is passed in so the preflight never spawns a SECOND nvidia-smi
        # probe for a status call that already paid for one.
        "preflight": install_preflight(gpu=gpu),
        "install_history": (
            hist if history_limit is None else hist[-history_limit:] if history_limit > 0 else []
        ),
        "install_history_bounds": {
            **install_history_bounds(),
            "attempts_in_this_payload": (
                len(hist) if history_limit is None else min(len(hist), max(history_limit, 0))
            ),
        },
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
    """Refuse the networked steps under airplane mode.

    Exempt only by an operator-consented EGRESS WINDOW, which permits the AI
    install WITHOUT starting the collector -- the kill switch stays engaged, so
    every other fetch path keeps refusing (``src.ingest.egress_window``).
    """
    from src.ingest.egress_window import PURPOSE_AI_INSTALL, egress_permitted

    if not egress_permitted(PURPOSE_AI_INSTALL):
        raise VllmLifecycleError(
            "Network is OFF (airplane mode): refusing to install vLLM. "
            "Turn airplane mode off, or allow the AI install to go online on its own."
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
def _gb(n: int | None, *, down: bool = False) -> float | None:
    """Bytes -> GB for display. ``None`` stays ``None`` -- never rendered as 0.

    ``down=True`` truncates instead of rounding, and is used for AVAILABLE space: with
    round-to-nearest, one byte short of the floor renders as "Only 15.0 GB free --
    needs at least 15.0 GB", a refusal that reads as a bug. Truncating also never
    over-reports how much room the operator actually has."""
    if n is None:
        return None
    gb = n / (1024**3)
    return math.floor(gb * 100) / 100 if down else round(gb, 2)


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


def _package_present(venv: Path, name: str) -> bool | None:
    """Is ``name`` importable from ``venv``'s site-packages?

    ``True`` / ``False`` / ``None`` -- and ``None`` (no readable site-packages, i.e.
    an unrecognised layout) is load-bearing: the caller must refuse ONLY on a
    measured absence. A file-existence check, never a subprocess: this runs on the
    install's success path, where spawning the freshly built interpreter is a slower
    and more fragile way to learn the same fact."""
    roots = sorted(venv.glob("lib/python*/site-packages")) + sorted(venv.glob("Lib/site-packages"))
    readable = [r for r in roots if r.is_dir()]
    if not readable:
        return None
    for root in readable:
        if (root / name).is_dir() or any(root.glob(f"{name}-*.dist-info")):
            return True
    return False


def _stop_probe(ctx) -> Callable[[], bool]:
    """``ctx.stopping`` as a callable, for ``_default_runner``'s cancel poll.

    The runner cannot import the job chassis, and a BackgroundJob ctx is not the only
    thing that can drive an install, so the cancel signal crosses that boundary as a
    plain predicate. A ctx without ``stopping`` never cancels rather than raising."""
    return lambda: bool(getattr(ctx, "stopping", False))


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

    free_gb, ram_gb = _gb(free, down=True), _gb(ram, down=True)
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

    # "We measured this machine and it is fine" and "this machine told us nothing"
    # produce IDENTICAL gate output: blocking=[] and requires_acknowledgement=False.
    # That is the absent-reads-as-passed shape. The gate itself is deliberately NOT
    # changed -- refusing on an unreadable /proc file would manufacture exactly the
    # kind of fabricated verdict this preflight exists to avoid, and an unmeasurable
    # preflight must never block (pinned by its own test). What was missing is the
    # DISTINCTION, so it is now stated: a consumer can tell a clean pass from an
    # empty one without re-deriving it from the notes list.
    checks_measured = sum(1 for v in (free, ram, fs["filesystem"]) if v is not None)
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
        # How much of this preflight is a MEASUREMENT rather than a silence. An empty
        # `blocking` from `checks_measured: 0` says nothing about the machine, and a
        # reader (UI, diagnostics bundle, future gate) must be able to see that
        # without inferring it from the absence of entries.
        "checks_measured": checks_measured,
        "checks_total": 3,
        "fully_unmeasured": checks_measured == 0,
        "estimated_size_note": ESTIMATED_INSTALL_SIZE_NOTE,
    }


def _install_env(tmpdir: Path) -> dict[str, str]:
    """The environment for the install subprocesses: the ambient environment
    (PATH, proxy vars, locale -- all preserved) with ``TMPDIR`` redirected onto
    real disk. Mirrors ``install.sh:pip_install``'s ``TMPDIR="$pip_tmp" pip
    install ...``; TMPDIR only, matching that precedent (TMP/TEMP are Windows
    conventions and this path is Linux-only).

    An operator-set ``TMPDIR`` IS overridden, deliberately: same-volume-as-the-install-
    target is the property that makes the preflight's measured free-disk figure the one
    pip actually consumes, and the whole defect being fixed here is an inherited TMPDIR
    on a RAM-backed filesystem. The path used is not hidden -- ``install_preflight``
    reports it as ``disk.path`` and the ENOSPC message names it.

    ``HF_HOME`` rides along (2026-08-04) so a weights download lands in the SAME place
    the server will read from and ``hf_cache_dir()`` will probe. Three call sites have
    to agree about that directory -- probe, download, serve -- and the way they stay
    agreed is that all three resolve it through ``model_store``."""
    from src.llm.model_store import launch_env

    env = launch_env()
    env["TMPDIR"] = str(tmpdir)
    return env


#  ------------------------------------------------------------------------- #
#  Pre-download the model WEIGHTS (field ask 2026-07-30: "there really should be
#  a simple button to download locally Ministral-3b-instruct")
#  ------------------------------------------------------------------------- #
def hf_cache_dir() -> Path:
    """Where Hugging Face keeps downloaded weights, by ITS OWN documented rules.

    Resolved the same way ``huggingface_hub`` resolves it -- ``HF_HUB_CACHE``, else
    ``HF_HOME/hub`` -- so a probe here and a download run inside the managed venv agree
    about the same directory. Read from the environment rather than by importing the
    library, because the app's own interpreter does not have ``huggingface_hub`` (it
    lives in the vLLM venv) and the answer must be available before anything is
    installed.

    THE FALLBACK IS THE APP'S OWN FOLDER (2026-08-04), not ``~/.cache``: the server is
    spawned with ``HF_HOME`` pointed there, so a probe that still answered ``~/.cache``
    would report "not downloaded" for weights that ARE present, and the activation
    guard built on this would then refuse a start that would have worked. An
    explicitly-set environment variable still wins, in HF's own precedence.
    """
    if (explicit := os.environ.get("HF_HUB_CACHE")):
        return Path(explicit)
    if (home := os.environ.get("HF_HOME")):
        return Path(home) / "hub"
    from src.llm.model_store import hf_home

    return hf_home() / "hub"


def model_cache_state(model: str) -> dict:
    """Is ``model`` already downloaded? ``{cached, path, bytes}``.

    Turns the plan's previously-honest-but-useless ``installed: None`` ("we do not
    probe") into a real answer, so the button can say "already downloaded" instead of
    inviting an operator to re-fetch several GB they already hold.

    A repo is cached when its ``snapshots/`` directory holds at least one revision with
    at least one file. That is deliberately stricter than "the directory exists":
    ``huggingface_hub`` creates the tree as soon as a download STARTS, so an interrupted
    fetch leaves a directory that a naive existence check would call cached -- reporting
    a half-downloaded model as ready is the fabrication to avoid here. ``bytes`` is the
    real on-disk size, or None when it cannot be read (never a 0)."""
    repo = "models--" + model.replace("/", "--")
    root = hf_cache_dir() / repo
    snaps = root / "snapshots"
    try:
        revisions = [d for d in snaps.iterdir() if d.is_dir()] if snaps.is_dir() else []
        cached = any(any(rev.iterdir()) for rev in revisions)
    except OSError:
        return {"cached": None, "path": str(root), "bytes": None}
    size: int | None = None
    if cached:
        try:
            size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
        except OSError:
            size = None
    return {"cached": cached, "path": str(root), "bytes": size}


#: Run INSIDE the managed venv (which has ``huggingface_hub`` -- vLLM depends on it).
#: ``-u`` so the progress lines reach us while the download runs rather than at the end.
_SNAPSHOT_SCRIPT = (
    "import sys\n"
    "from huggingface_hub import snapshot_download\n"
    "p = snapshot_download(sys.argv[1])\n"
    "print('__downloaded__ ' + p)\n"
)


def run_model_download_job(
    ctx,
    *,
    model: str,
    runner: Callable[..., Iterator[str]] | None = None,
) -> dict:
    """``BackgroundJob`` worker: fetch ``model``'s weights into the HF cache NOW.

    Field ask 2026-07-30. Before this, "install the default model" on a vLLM machine
    only recorded the name and started the server, because vLLM fetches weights itself
    on first start -- technically true, and useless as a button: the operator got no
    download, no progress, and no way to know whether the several GB were on the disk.
    Running ``snapshot_download`` in the managed venv gives the real thing, populating
    exactly the cache the server reads at start, so a later start is fast rather than
    silently downloading for ten minutes.

    Requires the vLLM venv (that is where ``huggingface_hub`` lives) -- refused with
    that as the reason, not a generic failure, since the fix is one button away. Refuses
    under airplane mode: this is clearnet traffic to Hugging Face, not Tor.

    No percentage: ``snapshot_download``'s progress goes to stderr as tqdm bars, which
    are honest to SHOW and dishonest to parse into a number here. The lines are streamed
    as they come and the success sentinel is the library's own returned path -- never an
    exit code alone, which a shell would give for a script that printed a traceback."""
    _check_online()
    if not venv_python().is_file():
        raise VllmUnsupportedError(
            "The vLLM environment is not installed yet, and the downloader lives in it "
            "(huggingface_hub ships with vLLM). Install vLLM first, then download the "
            "model."
        )
    state = model_cache_state(model)
    if state["cached"]:
        return {"downloaded": True, "state": "already_cached", **state}

    run = runner or _default_runner
    stop = _stop_probe(ctx)
    ctx.set_progress(detail=f"downloading {model} from Hugging Face")
    argv = [str(venv_python()), "-u", "-c", _SNAPSHOT_SCRIPT, model]
    exit_code: int | None = None
    path: str | None = None
    tail: deque[str] = deque(maxlen=_OUTPUT_TAIL_LINES)
    for line in run(argv, env=_install_env(pip_tmpdir()), should_stop=stop):
        if ctx.stopping:
            return {"downloaded": False, "state": "cancelled"}
        if line == _HEARTBEAT:
            continue
        if line.startswith("__exit__ "):
            exit_code = int(line.split(" ", 1)[1].strip() or "1")
            continue
        if line.startswith("__downloaded__ "):
            path = line.split(" ", 1)[1].strip()
            continue
        tail.append(line)
        ctx.set_progress(detail=line[:200])
    if exit_code != 0 or path is None:
        raise VllmLifecycleError(
            f"downloading {model} failed"
            + (f" (exit code {exit_code})" if exit_code is not None else "")
            + (": " + " | ".join(list(tail)[-3:]) if tail else "")
        )
    return {"downloaded": True, "state": "downloaded", **model_cache_state(model)}


def run_models_download_job(
    ctx,
    *,
    models: Sequence[str],
    runner: Callable[..., Iterator[str]] | None = None,
) -> dict:
    """Download SEVERAL models, one after another, reporting each on its own.

    Maintainer ask 2026-08-02: a button that installs a chosen bench roster. Sequential
    rather than parallel because they share one network link and one disk, and because
    the per-model output is only legible when one model is talking at a time.

    ONE FAILURE DOES NOT END THE BATCH, and that is the load-bearing decision. The
    roster's own Gemma-3n row is GATED on Hugging Face -- it will fail without an
    accepted licence and a token, which is stated in the UI before the click. If a
    failure aborted the run, ticking the one model that is expected to need a token
    would silently cost the operator the other five. So each model's outcome is
    recorded and the loop continues; the job succeeds if ANY model arrived, and the
    per-model verdicts travel in the result either way.

    Cancellation is honoured BETWEEN models and inside each one (the single-model
    worker already returns ``cancelled`` when ``ctx.stopping``), so a stop during a
    multi-gigabyte fetch does not have to wait for the whole batch."""
    results: list[dict] = []
    total = len(models)
    for i, model in enumerate(models, start=1):
        if ctx.stopping:
            results.append({"model": model, "state": "cancelled"})
            continue
        ctx.set_progress(detail=f"model {i} of {total}: {model}")
        try:
            one = run_model_download_job(ctx, model=model, runner=runner)
            results.append({"model": model, **one})
        except (VllmLifecycleError, VllmUnsupportedError) as exc:
            # Recorded with its own reason -- a gated repo and a typo look identical
            # from a bare "failed", and only one of them is the operator's to fix.
            results.append({"model": model, "state": "error", "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - one model's surprise is not the batch's
            results.append({"model": model, "state": "error", "error": repr(exc)})
    downloaded = [r for r in results if r.get("state") in {"downloaded", "already_cached"}]
    failed = [r for r in results if r.get("state") == "error"]
    return {
        "requested": total,
        "downloaded": len(downloaded),
        "failed": len(failed),
        "cancelled": sum(1 for r in results if r.get("state") == "cancelled"),
        "results": results,
        # Stated rather than inferred from the counts, so a caller cannot read a
        # partial batch as a clean one.
        "partial": bool(downloaded and failed),
    }


#: pip's own flags for a very large download. ``--retries``/``--timeout`` mirror
#: ``install.sh:pip_install``: pip's 15 s default turns a dropped link into a
#: MISLEADING "ResolutionImpossible / no matching distribution", and 5-10 GB is exposed
#: to that for a long time. ``uv`` retries by default and takes neither flag.
_PIP_NET_FLAGS = ["--retries", "5", "--timeout", "60"]


def _resolver_argv(
    pip: Path,
    version: str,
    run: Callable[..., Iterator[str]],
    env: dict[str, str],
    stop: Callable[[], bool] | None,
    ctx,
    tail: deque[str],
) -> tuple[str, list[str]]:
    """Pick the resolver for the big install: ``uv`` when it can be had, else ``pip``.

    FIELD REPORT 2026-07-30: "vLLM installation seems broken. I had to install uv ...
    then use ``uv pip install vllm``." The operator's own successful path is the
    evidence, so the built-in installer now takes it.

    WHY uv and not "pip, but harder": vLLM's dependency graph is torch plus the CUDA
    runtime, and pip's backtracking resolver on a graph that size is where installs go
    to die -- it can churn for a very long time and hold a lot of memory doing it, which
    is exactly what "seems broken" looks like from the outside (no output, no progress,
    no end). uv resolves that graph in one pass and downloads/unpacks in parallel. This
    is NOT a claim that pip is at fault in some measured way: the honest statement is
    that the operator's uv path worked where this one did not, and uv is the difference.

    ``pip install uv`` -- deliberately NOT ``curl https://astral.sh/uv/install.sh | sh``,
    which is what the operator had to do by hand. uv publishes a self-contained binary
    wheel with no dependencies, so it comes down the SAME channel (PyPI over HTTPS, into
    an unprivileged venv) that this module's trust model already rests on, with no shell
    pipe, no elevation and no second trust boundary to justify.

    FALLING BACK IS THE POINT, not a nicety: if uv cannot be installed for any reason
    the install continues on pip exactly as before, so this can make the install work
    where it did not, and cannot make it fail where it worked. Returns the resolver name
    (which becomes the journalled phase, so the field can tell the two apart) and its
    argv."""
    if os.environ.get("OO_VLLM_RESOLVER", "").lower() == "pip":
        return "pip", [str(pip), "install", *_PIP_NET_FLAGS, f"vllm=={version}"]
    ctx.set_progress(detail="installing uv (a fast resolver for vLLM's dependency graph)")
    exit_code: int | None = None
    try:
        for line in run(
            [str(pip), "install", *_PIP_NET_FLAGS, "uv"], env=env, should_stop=stop
        ):
            if ctx.stopping:
                break
            if line == _HEARTBEAT:
                continue
            if line.startswith("__exit__ "):
                exit_code = int(line.split(" ", 1)[1].strip() or "1")
                continue
            tail.append(line)
    except Exception:  # noqa: BLE001 - uv is an accelerator; pip is the floor
        _LOG.warning("could not install uv; falling back to pip", exc_info=True)
        exit_code = None
    uv = venv_bin("uv")
    if exit_code == 0 and uv.is_file():
        # `--python` because uv defaults to ITS OWN idea of an interpreter; without it a
        # uv living in the managed venv could resolve against a different Python than
        # the one that will run the server.
        return "uv", [
            str(uv), "pip", "install", "--python", str(venv_python()), f"vllm=={version}"
        ]
    return "pip", [str(pip), "install", *_PIP_NET_FLAGS, f"vllm=={version}"]


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
    # Wall clock for the attempt. `started_at` is epoch (a human-readable stamp for
    # the exported bundle); the elapsed figure comes from `monotonic` so an NTP step
    # mid-install cannot produce a negative or wildly wrong duration.
    started_at = time.time()
    started_mono = time.monotonic()
    # Set once the resolver is chosen; stays None if we never got that far, so an
    # attempt that died in the venv phase honestly reports "no resolver ran".
    resolver_used: str | None = None
    fallback_fired: bool | None = None

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
            resolver=resolver_used,
            fallback_fired=fallback_fired,
            started_at=started_at,
            duration_s=time.monotonic() - started_mono,
        )

    ctx.set_progress(detail="preparing the managed venv")
    d = venv_dir()
    tmp = pip_tmpdir()
    env = _install_env(tmp)
    # Sweep BEFORE creating it, not only in the finally afterwards. The finally does
    # not run when the process is killed -- SIGKILL, OOM, or the app's own SIGTERM
    # shutdown, whose worker sits on a DAEMON thread that is abandoned at interpreter
    # exit. Up to ~10 GB of half-unpacked wheels then persists (this area moved from
    # the ambient /tmp, which the OS clears, onto real disk beside the venv, which
    # nothing clears). Sweeping at the start reclaims that residue on the next attempt
    # AND means pip never unpacks into a stale tree.
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        tmp.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise VllmLifecycleError(
            f"could not create pip's unpack directory {tmp}: {exc}"
        ) from exc
    try:
        run = runner or _default_runner
        stop = _stop_probe(ctx)
        # `python -m venv` writes bin/python well BEFORE ensurepip finishes, so a
        # cancel/crash in that window leaves a venv with python and no pip. Keying
        # only on venv_python() then SKIPPED repair forever and blamed a missing
        # system package ("install python3-venv") for a state the previous attempt
        # created -- self-perpetuating, since bin/python exists from then on. A venv
        # missing EITHER is incomplete; `python -m venv` is idempotent, so re-running
        # it repairs in place. (Window confirmed live against a real venv creation.)
        if not venv_python().is_file() or not venv_bin("pip").is_file():
            # None, not 0: only the `__exit__` sentinel may declare success. A
            # runner that yields no sentinel must never write the marker.
            venv_exit_code: int | None = None
            for line in run([sys.executable, "-m", "venv", str(d)], env=env, should_stop=stop):
                if ctx.stopping:
                    _journal("cancelled")
                    return {"installed": False, "state": "cancelled"}
                if line == _HEARTBEAT:
                    continue
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
        # A fresh tail per phase: if the resolver fails, the venv phase's output is noise.
        phase = "uv"
        tail.clear()
        lines_total = 0
        # Whether uv was WANTED, read the same way `_resolver_argv` reads it. Asking
        # here (rather than widening that function's return arity, which every caller
        # and test pins) keeps the change additive.
        uv_wanted = os.environ.get("OO_VLLM_RESOLVER", "").lower() != "pip"
        resolver, argv = _resolver_argv(pip, version, run, env, stop, ctx, tail)
        # A successful uv install and a silent uv failure rescued by pip look
        # IDENTICAL from the outside -- both end in a working vLLM. This is the one
        # bit that tells them apart, so a field report can say which path actually
        # ran instead of assuming the intended one did.
        resolver_used = resolver
        fallback_fired = uv_wanted and resolver == "pip"
        phase = resolver
        tail.clear()
        lines_total = 0
        ctx.set_progress(
            detail=(
                f"{resolver} install vllm=={version} "
                f"(this downloads {ESTIMATED_INSTALL_SIZE_NOTE})"
            )
        )
        exit_code: int | None = None
        for line in run(argv, env=env, should_stop=stop):
            if ctx.stopping:
                _journal("cancelled")
                return {"installed": False, "state": "cancelled"}
            if line == _HEARTBEAT:
                continue
            if line.startswith("__exit__ "):
                exit_code = int(line.split(" ", 1)[1].strip() or "1")
                continue
            lines_total += 1
            tail.append(line)
            ctx.set_progress(detail=line[:200])
        if exit_code is None:
            msg = (
                f"{resolver} install vllm=={version} produced no exit status -- refusing "
                "to record an install that was never confirmed to succeed."
            )
            _journal("error", error=msg)
            raise VllmLifecycleError(msg)
        if exit_code != 0:
            joined = "\n".join(tail).lower()
            if any(m in joined for m in _ENOSPC_MARKERS):
                # Classify rather than echo a bare exit code (CLAUDE.md:519-520).
                msg = (
                    f"{resolver} install vllm=={version} ran out of disk space while "
                    "unpacking ('No space left on device'). This install already points "
                    f"the unpack area at {tmp}, so the volume behind that path is what "
                    f"filled up. Check it (look at the 'Avail' column):  df -h {tmp}"
                )
            else:
                msg = f"{resolver} install vllm=={version} failed (exit code {exit_code})."
            _journal("error", exit_code=exit_code, error=msg)
            raise VllmLifecycleError(msg)
        # pip exiting 0 is evidence about PIP, not about this venv: PIP_TARGET /
        # PIP_PREFIX / PIP_USER in the ambient environment (which _install_env
        # deliberately inherits, for proxy settings) all make pip install SOMEWHERE
        # ELSE and still exit 0. The marker is a claim that vLLM is installed HERE, so
        # confirm the package actually landed before writing it. Tri-state on purpose:
        # only a site-packages we could READ and that does NOT contain vllm is a
        # failure -- an unrecognised venv layout is a note, never a fabricated refusal.
        if _package_present(venv_dir(), "vllm") is False:
            msg = (
                f"pip reported success but vllm is not present in {venv_dir()}. "
                "Something redirected the install (PIP_TARGET / PIP_PREFIX / PIP_USER "
                "in the environment will do this). Refusing to record an install this "
                "venv cannot actually use."
            )
            _journal("error", exit_code=exit_code, error=msg)
            raise VllmLifecycleError(msg)
        _write_marker(version)
        phase = "done"
        _journal("installed", exit_code=0)
        return {"installed": True, "version": version, "state": "done"}
    finally:
        # Every exit path -- success, raise, and the two cancel returns.
        shutil.rmtree(tmp, ignore_errors=True)


def _terminate_child(proc: subprocess.Popen, *, timeout: float = 10.0) -> None:
    """SIGTERM, then SIGKILL after ``timeout`` -- the same shape ``stop()`` already
    uses for the served process. Never raises: a child that died on its own between
    the poll and the signal is a success, not an error."""
    try:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:  # noqa: BLE001 - best-effort teardown; never mask the real outcome
        _LOG.warning("could not terminate the install subprocess", exc_info=True)


def _default_runner(
    argv: list[str],
    env: dict[str, str] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[str]:
    """Run a real subprocess, yielding its output lines then a final
    ``__exit__ <code>`` sentinel (mirrors ``src.llm.installer.run_installer``'s
    streaming shape).

    ``env`` defaults to ``None``, which is ``Popen``'s inherit-the-ambient-
    environment behaviour -- i.e. byte-identical to this function before the
    TMPDIR fix, so any other caller is unaffected. The vLLM install passes an
    env whose ``TMPDIR`` is on real disk (``_install_env``).

    CANCELLABLE (2026-07-29). The output is drained on a pump thread and consumed
    through a timed queue, for one reason: the caller checks ``ctx.stopping``
    once PER YIELDED LINE, and a plain ``for line in proc.stdout`` blocks for as
    long as the child is silent. pip is silent for the whole of a wheel download
    -- 5-10 GB of torch/CUDA, hours on the operator's Tor-routed link -- so a
    Cancel click did nothing at all until the download finished on its own
    (live-reproduced: the worker sat in this loop 3s after cancel, and the job
    stayed "running", which also made the endpoint refuse every retry). Since the
    job advertises ``cancellable=True``, that was Cancel THEATER, which
    ``BackgroundJob``'s own docstring forbids.

    So: while idle this yields a ``_HEARTBEAT`` sentinel every ``_RUNNER_POLL_S``
    so the caller's stop check runs on a schedule, and when ``should_stop`` fires
    -- or the generator is closed -- the CHILD IS KILLED rather than left
    downloading. ``should_stop`` is optional; omitted, behaviour is the previous
    blocking drain."""
    import queue as _queue
    import threading as _threading

    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    q: _queue.Queue = _queue.Queue()
    eof = object()

    def _pump() -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                q.put(line.rstrip("\n"))
        except Exception:  # noqa: BLE001 - a closed pipe during teardown is expected
            pass
        finally:
            q.put(eof)

    _threading.Thread(target=_pump, name="vllm-install-pump", daemon=True).start()
    cancelled = False
    try:
        while True:
            try:
                item = q.get(timeout=_RUNNER_POLL_S)
            except _queue.Empty:
                if should_stop is not None and should_stop():
                    cancelled = True
                    break
                yield _HEARTBEAT  # wake the caller so ITS stop check runs too
                continue
            if item is eof:
                break
            yield item
            if should_stop is not None and should_stop():
                cancelled = True
                break
    except GeneratorExit:
        # The caller abandoned us (returned mid-loop). Kill the child rather than
        # blocking forever in proc.wait() on a live multi-GB download.
        cancelled = True
        raise
    finally:
        if cancelled:
            _terminate_child(proc)
        try:
            proc.stdout.close()
        except Exception:  # noqa: BLE001, S110 - teardown only
            pass
        code = proc.wait()
    if not cancelled:
        yield f"__exit__ {code}"
