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
import os
import subprocess  # noqa: S404 - fixed argv, no shell; every call site documents why
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

from src.paths import data_dir

# The exact version verified against PyPI's JSON API 2026-07-24 (this sandbox can
# reach pypi.org; huggingface.co/docs.vllm.ai were blocked, so verification stopped
# at what was reachable). Bump only after re-verifying against
# https://pypi.org/pypi/vllm/json -- never guessed (the fabricated-endpoint burn).
VLLM_VERIFIED_VERSION = "0.25.1"
VLLM_VERIFIED_AS_OF = "2026-07-24"

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
    member (B7) -- installed/running/GPU facts, never a fabricated readiness."""
    from src.llm.backend import detect_gpu

    return {
        "installed": is_installed(),
        "install_info": install_info(),
        "running": is_running(),
        "process_tracked": process_alive(),
        "gpu": detect_gpu(),
        "base_url": base_url(),
        "venv_dir": str(venv_dir()),
        "verified_version": VLLM_VERIFIED_VERSION,
        "verified_as_of": VLLM_VERIFIED_AS_OF,
        "estimated_size_note": ESTIMATED_INSTALL_SIZE_NOTE,
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


def run_install_job(
    ctx,
    *,
    version: str = VLLM_VERIFIED_VERSION,
    runner: Callable[[list[str]], Iterator[str]] | None = None,
) -> dict:
    """``BackgroundJob`` worker: create the managed venv (if absent) + ``pip
    install vllm==<version>``, streaming honest PHASE text (pip gives no
    reliable percentage, so this never fakes one — B2.3). Refuses up front on a
    CPU-only machine or under airplane mode. Writes the install marker ONLY on a
    verified-successful pip exit code — a failed install leaves NO marker, so
    ``is_installed()`` never claims a half-configured backend works."""
    from src.llm.backend import detect_gpu

    _check_online()
    gpu = detect_gpu()
    if not gpu.get("available"):
        raise VllmUnsupportedError(
            "No GPU detected on this machine -- vLLM is GPU-first and would install "
            "into a backend that can never usefully run. Use Ollama instead."
        )
    ctx.set_progress(detail="preparing the managed venv")
    d = venv_dir()
    if not venv_python().is_file():
        run = runner or _default_runner
        venv_exit_code = 0
        for line in run([sys.executable, "-m", "venv", str(d)]):
            if ctx.stopping:
                return {"installed": False, "state": "cancelled"}
            if line.startswith("__exit__ "):
                venv_exit_code = int(line.split(" ", 1)[1].strip() or "1")
                continue
            ctx.set_progress(detail=f"venv: {line[:120]}")
        if venv_exit_code != 0:
            raise VllmLifecycleError(
                f"could not create the vLLM venv (python -m venv exit code {venv_exit_code})."
            )
    ctx.set_progress(detail=f"pip install vllm=={version} (this downloads {ESTIMATED_INSTALL_SIZE_NOTE})")
    run = runner or _default_runner
    pip = venv_bin("pip")
    argv = [str(pip), "install", f"vllm=={version}"]
    exit_code = 0
    for line in run(argv):
        if ctx.stopping:
            return {"installed": False, "state": "cancelled"}
        if line.startswith("__exit__ "):
            exit_code = int(line.split(" ", 1)[1].strip() or "1")
            continue
        ctx.set_progress(detail=line[:200])
    if exit_code != 0:
        raise VllmLifecycleError(f"pip install vllm=={version} failed (exit code {exit_code}).")
    _write_marker(version)
    return {"installed": True, "version": version, "state": "done"}


def _default_runner(argv: list[str]) -> Iterator[str]:
    """Run a real subprocess, yielding its output lines then a final
    ``__exit__ <code>`` sentinel (mirrors ``src.llm.installer.run_installer``'s
    streaming shape)."""
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield line.rstrip("\n")
    finally:
        proc.stdout.close()
        code = proc.wait()
    yield f"__exit__ {code}"
