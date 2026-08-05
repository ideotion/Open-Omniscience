"""
Tests for the vLLM lifecycle module (B2, 2026-07-24 field-feedback Session B):
detect / install / start / stop / context auto-tune. No real subprocess, GPU,
or vLLM package is ever touched -- every runner/Popen is injected, matching
this project's own precedent for the Ollama binary installer
(``tests/test_llm_installer.py``, which the app itself can only fixture-test
in a sandbox with no GPU either).
"""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import pytest

from src.llm import vllm_lifecycle as V


class FakeCtx:
    def __init__(self, stop_after: int | None = None):
        self._stop_after = stop_after
        self._calls = 0
        self.details: list[str] = []

    @property
    def stopping(self) -> bool:
        self._calls += 1
        return self._stop_after is not None and self._calls > self._stop_after

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        if detail is not None:
            self.details.append(detail)


@pytest.fixture(autouse=True)
def _isolate_venv(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_VLLM_VENV_DIR", str(tmp_path / "vllm_venv"))
    V._proc = None
    # V3: the journal's disable flag is a MODULE GLOBAL -- reset it, or the
    # write-failure test silently disables recording for every later test.
    V._history_disabled = False
    V._history_disabled_reason = None
    yield
    V._proc = None
    V._history_disabled = False
    V._history_disabled_reason = None


def _allow_install(monkeypatch, *, ram=32 * 1024**3, free=200 * 1024**3, ram_backed=False):
    """Open every refusal gate so a test can reach the pip phase, with the V2
    resource probes stubbed at MODULE level -- production code still calls them,
    so this is not a parameter-injected double bypassing the real path."""
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8192}
    )
    monkeypatch.setattr(V, "_total_ram_bytes", lambda: ram)
    monkeypatch.setattr(V, "_free_disk_bytes", lambda p: free)
    monkeypatch.setattr(V, "_filesystem_type_of", lambda p: "tmpfs" if ram_backed else "ext4")


def _fake_venv(with_pip=True):
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")
    if with_pip:
        V.venv_bin("pip").write_text("#!/bin/sh\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# install marker + is_installed()
# --------------------------------------------------------------------------- #
def test_not_installed_when_the_venv_is_absent():
    assert V.is_installed() is False
    assert V.install_info() is None


def test_is_installed_requires_both_marker_and_python():
    V.venv_dir().mkdir(parents=True)
    V._write_marker("0.25.1")
    # marker exists but no venv python -> still not installed (honest).
    assert V.is_installed() is False
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")
    assert V.is_installed() is True
    info = V.install_info()
    assert info["version"] == "0.25.1"
    assert isinstance(info["installed_at"], float)


# --------------------------------------------------------------------------- #
# platform_support() -- vLLM ships Linux-only wheels; a non-Linux host must be
# refused honestly rather than left to a doomed pip install (the "vllm install
# fails" symptom, root-caused: no OS check existed anywhere in this module).
# --------------------------------------------------------------------------- #
def test_platform_support_is_true_on_linux(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    support = V.platform_support()
    assert support == {"os": "linux", "arch": "x86_64", "supported": True}


def test_platform_support_is_false_on_windows(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    support = V.platform_support()
    assert support["supported"] is False
    assert support["os"] == "windows"
    assert "Linux wheels" in support["reason"]
    assert "Ollama" in support["reason"]


def test_platform_support_is_false_on_macos(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    support = V.platform_support()
    assert support["supported"] is False
    assert support["os"] == "darwin"


def test_install_job_refuses_on_a_non_linux_host_before_any_gpu_check(monkeypatch):
    """The exact real-world failure mode: a Windows machine WITH an NVIDIA GPU
    (nvidia-smi exists on Windows too) must be refused for the PLATFORM reason,
    not sail through the GPU gate into a doomed pip install."""
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8192}
    )
    with pytest.raises(V.VllmUnsupportedError, match="Linux wheels"):
        V.run_install_job(FakeCtx())


def test_status_discloses_platform_support(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    st = V.status()
    assert st["platform"]["supported"] is False


# --------------------------------------------------------------------------- #
# compute_server_args -- the context auto-tune math (pure, disclosed method)
# --------------------------------------------------------------------------- #
def test_compute_server_args_no_vram_reading_is_a_conservative_default():
    args = V.compute_server_args(None)
    assert args["max_model_len"] == 4096
    assert 0 < args["gpu_memory_utilization"] <= 1
    assert "method" in args and "caveat" in args


def test_compute_server_args_scales_with_vram():
    """AMENDED 2026-08-02. This asserted ``large >= small``, which a CONSTANT
    satisfies -- and the value was a constant: every card from 6 GB to 80 GB got
    max_model_len 32768, because the token estimate was ~1000x too generous and the
    cap decided every machine. The test passed for years while the function did not
    scale at all and its published method string said it did. Strict inequality is
    the whole point."""
    small = V.compute_server_args(8192)   # 8 GB
    large = V.compute_server_args(24576)  # 24 GB
    assert large["max_model_len"] > small["max_model_len"], (
        "a bigger card must buy more context -- equality means the cap is deciding"
    )
    assert 0 < small["gpu_memory_utilization"] <= 0.95
    assert 0 < large["gpu_memory_utilization"] <= 0.95


def test_compute_server_args_operator_override_is_honoured_verbatim():
    args = V.compute_server_args(8192, max_model_len_override=1234, gpu_memory_utilization_override=0.42)
    assert args["max_model_len"] == 1234
    assert args["gpu_memory_utilization"] == 0.42
    assert "override" in args["method"]


# --------------------------------------------------------------------------- #
# server_argv -- pure command-line construction
# --------------------------------------------------------------------------- #
def test_server_argv_falls_back_to_module_invocation_without_the_console_script():
    argv = V.server_argv("my-model", port=8000)
    assert str(V.venv_python()) in argv
    assert "vllm.entrypoints.openai.api_server" in argv
    assert "--model" in argv and "my-model" in argv
    assert "--host" in argv and "127.0.0.1" in argv
    assert "--port" in argv and "8000" in argv


def test_server_argv_prefers_the_console_script_when_present():
    V.venv_bin("vllm").parent.mkdir(parents=True, exist_ok=True)
    V.venv_bin("vllm").write_text("#!/bin/sh\n", encoding="utf-8")
    argv = V.server_argv("my-model")
    assert argv[0] == str(V.venv_bin("vllm"))
    assert argv[1:3] == ["serve", "my-model"]


def test_server_argv_includes_context_flags_when_given():
    argv = V.server_argv("m", max_model_len=2048, gpu_memory_utilization=0.5)
    assert "--max-model-len" in argv and "2048" in argv
    assert "--gpu-memory-utilization" in argv and "0.5" in argv


def test_server_argv_carries_enforce_eager_only_when_asked():
    """A bare switch: present when asked, ABSENT otherwise. The negative half is the
    load-bearing one -- a flag appended unconditionally would slow every card."""
    assert "--enforce-eager" in V.server_argv("m", port=1, enforce_eager=True)
    assert "--enforce-eager" not in V.server_argv("m", port=1)


# --------------------------------------------------------------------------- #
# enforce_eager -- skip CUDA-graph capture where the card cannot spare the pool
# --------------------------------------------------------------------------- #
def test_a_small_card_skips_cuda_graph_capture_and_a_large_one_keeps_it():
    """Field report 2026-08-04: capture died with cudaErrorMemoryAllocation at 86% of
    51 graphs on an 8 GiB card. Eager mode costs decode speed; a failed capture costs
    a server that never starts, and only the small card faces that trade.

    THE NEGATIVE HALF IS THE POINT: a large card must KEEP capture. A guard that fired
    everywhere would read as conservative while quietly slowing hardware that can
    comfortably afford the pool -- a fabricated cost, the mirror of a fabricated pass."""
    assert V.compute_server_args(8188)["enforce_eager"] is True, "the measured failure"
    assert V.compute_server_args(24576)["enforce_eager"] is False
    assert V.compute_server_args(81920)["enforce_eager"] is False


def test_the_eager_threshold_is_a_real_boundary_not_an_always_on_switch():
    """Pins that the rule actually TURNS somewhere between the two cases above, so a
    future edit cannot collapse it to a constant while both assertions still pass."""
    on = [mb for mb in (4096, 8192, 10240, 12288, 16384, 24576)
          if V.compute_server_args(mb)["enforce_eager"]]
    assert on and len(on) < 6, f"eager must be applied to some cards and not others: {on}"
    # ...and it must be the SMALL ones, in one contiguous run from the bottom.
    assert on == [4096, 8192, 10240]


def test_an_unreadable_card_skips_capture_rather_than_assuming_it_fits():
    """Consistent with the same branch's conservative context numbers: a card we cannot
    measure could be a small one, and the small card is the case that fails to start.
    The method must SAY that, so the value never reads as a measurement."""
    args = V.compute_server_args(None)
    assert args["enforce_eager"] is True
    assert "unreadable" in args["method"]


def test_an_operator_can_force_cuda_graphs_on_or_off():
    """An explicit choice is never second-guessed in either direction, and the method
    stops claiming a VRAM derivation the moment the operator decides instead."""
    forced_off = V.compute_server_args(8192, enforce_eager_override=False)
    assert forced_off["enforce_eager"] is False
    forced_on = V.compute_server_args(81920, enforce_eager_override=True)
    assert forced_on["enforce_eager"] is True
    both = V.compute_server_args(
        8192, max_model_len_override=1, gpu_memory_utilization_override=0.5
    )
    assert "operator override" in both["method"]
    # ...but enforce_eager was NOT overridden there, and the method must not pretend
    # otherwise: it says how that third value was actually reached.
    assert "CUDA-graph capture skipped" in both["method"]


# --------------------------------------------------------------------------- #
# start() -- refuses on CPU-only machines, refuses when not installed
# --------------------------------------------------------------------------- #
def test_start_refuses_when_not_installed(monkeypatch):
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": True})
    with pytest.raises(V.VllmLifecycleError):
        V.start("m")


def test_start_refuses_on_a_cpu_only_machine(monkeypatch, tmp_path):
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")
    V._write_marker("0.25.1")
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": False})
    with pytest.raises(V.VllmUnsupportedError):
        V.start("m")


def test_start_launches_the_subprocess_when_gpu_is_present(monkeypatch):
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")
    V._write_marker("0.25.1")
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8192}
    )
    monkeypatch.setattr(V, "is_running", lambda: False)

    calls = {}

    class _FakeProc:
        def poll(self):
            return None

    def fake_popen(argv, **kw):
        calls["argv"] = argv
        return _FakeProc()

    result = V.start("my/model", popen=fake_popen)
    assert result["started"] is True
    assert "my/model" in calls["argv"]
    assert V.process_alive() is True


@pytest.mark.parametrize("vram_mb,expect_eager", [(8192, True), (24576, False)])
def test_start_puts_the_computed_eager_decision_on_the_real_command_line(
    monkeypatch, vram_mb, expect_eager
):
    """The wiring, driven through the production path rather than asserted against the
    source: a decision computed and then never passed to the subprocess would leave
    compute_server_args' tests green while the server still captured graphs."""
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")
    V._write_marker("0.25.1")
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": vram_mb}
    )
    monkeypatch.setattr(V, "is_running", lambda: False)

    seen = {}

    class _FakeProc:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(argv, **kw):
        seen["argv"] = argv
        return _FakeProc()

    out = V.start("my/model", popen=fake_popen)
    assert out["server_args"]["enforce_eager"] is expect_eager
    assert ("--enforce-eager" in seen["argv"]) is expect_eager


def test_start_is_a_no_op_when_already_running(monkeypatch):
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")
    V._write_marker("0.25.1")
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8192}
    )
    monkeypatch.setattr(V, "is_running", lambda: True)
    result = V.start("m", popen=lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not launch")))
    assert result["started"] is False


# --------------------------------------------------------------------------- #
# stop()
# --------------------------------------------------------------------------- #
def test_stop_when_nothing_is_tracked():
    assert V.stop()["stopped"] is False


def test_stop_terminates_the_tracked_process():
    class _FakeProc:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    V._proc = _FakeProc()
    result = V.stop()
    assert result["stopped"] is True
    assert V._proc is None


# --------------------------------------------------------------------------- #
# run_install_job -- consented, streamed, marker written only on success
# --------------------------------------------------------------------------- #
def test_install_job_refuses_under_airplane_mode(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(FakeCtx())


def test_install_job_refuses_on_a_cpu_only_machine(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": False})
    with pytest.raises(V.VllmUnsupportedError):
        V.run_install_job(FakeCtx())


def test_install_job_writes_the_marker_only_on_a_successful_exit(monkeypatch):
    _allow_install(monkeypatch)
    # Pretend the venv (with its pip) already exists -- skip the `python -m venv` phase.
    _fake_venv()

    def fake_runner(argv, env=None, should_stop=None):
        yield "Collecting vllm==0.25.1"
        yield "Successfully installed vllm-0.25.1"
        yield "__exit__ 0"

    result = V.run_install_job(FakeCtx(), version="0.25.1", runner=fake_runner)
    assert result["installed"] is True
    assert V.is_installed() is True
    assert V.install_info()["version"] == "0.25.1"


def test_install_job_never_writes_a_marker_on_a_failed_exit(monkeypatch):
    # Isolated from the host OS (platform_support() is tested on its own,
    # above) -- this test's own subject is the pip-exit-code -> no-marker
    # behaviour, which must be exercised regardless of the CI runner's OS.
    _allow_install(monkeypatch)
    _fake_venv()

    def fake_runner(argv, env=None, should_stop=None):
        yield "ERROR: could not find a version that satisfies the requirement"
        yield "__exit__ 1"

    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(FakeCtx(), version="0.25.1", runner=fake_runner)
    assert V.is_installed() is False  # a failed install leaves NO marker


def test_install_job_creates_the_venv_first_when_absent(monkeypatch):
    _allow_install(monkeypatch)
    seen_argvs = []

    def fake_runner(argv, env=None, should_stop=None):
        seen_argvs.append(argv)
        if "venv" in argv:
            # Simulate venv creation actually producing a python binary, so the
            # subsequent pip-install phase's own venv_bin("pip") lookup is moot
            # here (the fake pip call below never actually touches disk).
            V.venv_python().parent.mkdir(parents=True, exist_ok=True)
            V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")
            V.venv_bin("pip").write_text("#!/bin/sh\n", encoding="utf-8")
            yield "__exit__ 0"
            return
        yield "Successfully installed vllm-0.25.1"
        yield "__exit__ 0"

    result = V.run_install_job(FakeCtx(), version="0.25.1", runner=fake_runner)
    assert result["installed"] is True
    assert any("venv" in a for a in seen_argvs)


def test_install_job_honours_a_cancel_between_venv_and_pip(monkeypatch):
    _allow_install(monkeypatch)

    def fake_runner(argv, env=None, should_stop=None):
        yield "creating venv"
        yield "__exit__ 0"

    ctx = FakeCtx(stop_after=0)
    result = V.run_install_job(ctx, version="0.25.1", runner=fake_runner)
    assert result["state"] == "cancelled"
    assert V.is_installed() is False


# --------------------------------------------------------------------------- #
# V1 (2026-07-29): TMPDIR must point at the INSTALL VOLUME, never the ambient
# /tmp. On Qubes /tmp is a RAM-backed tmpfs, so unpacking vLLM's 5-10 GB of
# torch/CUDA wheels there dies with Errno 28 WHILE df reports hundreds of free
# GB -- a RECURRENCE of the fix already made for install.sh:pip_install.
# --------------------------------------------------------------------------- #
def test_default_runner_forwards_env_to_the_real_subprocess(monkeypatch):
    """Drives the REAL _default_runner with Popen monkeypatched -- a runner
    DOUBLE would bypass the production path this fix actually lives in."""
    seen = {}

    class _FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("hello\n")

        def wait(self):
            return 0

    def _fake_popen(argv, **kw):
        seen.update(kw)
        seen["argv"] = argv
        return _FakeProc()

    monkeypatch.setattr(V.subprocess, "Popen", _fake_popen)
    out = list(V._default_runner(["/bin/true"], {"TMPDIR": "/data/x"}))
    assert out == ["hello", "__exit__ 0"]
    assert seen["env"] == {"TMPDIR": "/data/x"}


def test_default_runner_without_env_is_byte_identical_inherit_behaviour(monkeypatch):
    """env defaults to None == Popen's inherit-the-ambient-environment, i.e.
    unchanged for every other caller."""
    seen = {}

    class _FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("")

        def wait(self):
            return 0

    monkeypatch.setattr(
        V.subprocess, "Popen", lambda argv, **kw: (seen.update(kw), _FakeProc())[1]
    )
    list(V._default_runner(["/bin/true"]))
    assert seen["env"] is None


def test_install_points_pip_tmpdir_at_the_install_volume_not_the_ambient_tmpdir(monkeypatch):
    # The ambient TMPDIR is the thing that kills the install on Qubes (a small
    # RAM-backed /tmp). Set it explicitly so the redirect is proven against a
    # REAL ambient value rather than whatever this runner happens to have.
    monkeypatch.setenv("TMPDIR", "/tmp")
    _allow_install(monkeypatch)
    _fake_venv()
    envs = []

    def fake_runner(argv, env=None, should_stop=None):
        envs.append(env)
        yield "__exit__ 0"

    V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert envs and all(e is not None for e in envs), "every install subprocess gets an env"
    for e in envs:
        tmpdir = e["TMPDIR"]
        # REDIRECTED away from the ambient TMPDIR -- the whole point of V1.
        assert tmpdir != "/tmp", tmpdir
        assert Path(tmpdir) == V.pip_tmpdir()
        # SAME VOLUME as the install target -- that, not "under the data dir",
        # is the property that makes the measured free-disk figure the real one
        # (OO_VLLM_VENV_DIR can point at a volume the data dir knows nothing about).
        assert Path(tmpdir).parent == V.venv_dir().parent
        # the ambient environment is PRESERVED, not replaced
        assert e["PATH"] == os.environ["PATH"]


def test_the_pip_unpack_dir_exists_during_the_run_and_is_cleaned_up_on_success(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()
    existed = []

    def fake_runner(argv, env=None, should_stop=None):
        existed.append(Path(env["TMPDIR"]).is_dir())
        yield "__exit__ 0"

    V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    # Every subprocess of the install (the uv bootstrap AND the big resolve) sees the
    # redirected unpack dir -- checking only the first would leave the one that
    # actually downloads 5-10 GB unverified, which is the whole point of the redirect.
    assert existed and all(existed)
    assert not V.pip_tmpdir().exists()


def test_the_pip_unpack_dir_is_cleaned_up_even_when_pip_fails(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()
    existed = []

    def fake_runner(argv, env=None, should_stop=None):
        existed.append(Path(env["TMPDIR"]).is_dir())
        yield "__exit__ 1"

    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert existed and all(existed)
    assert not V.pip_tmpdir().exists()


def test_the_pip_unpack_dir_is_cleaned_up_on_cancel(monkeypatch):
    """The finally covers the early cancel RETURN, not only the raise."""
    _allow_install(monkeypatch)

    def fake_runner(argv, env=None, should_stop=None):
        yield "creating venv"
        yield "__exit__ 0"

    result = V.run_install_job(FakeCtx(stop_after=0), version="0.26.0", runner=fake_runner)
    assert result["state"] == "cancelled"
    assert not V.pip_tmpdir().exists()


# --------------------------------------------------------------------------- #
# V2: a REAL resource preflight, before any multi-GB download starts.
# --------------------------------------------------------------------------- #
def test_a_disk_full_preflight_refuses_before_any_subprocess_runs(monkeypatch):
    _allow_install(monkeypatch, free=2 * 1024**3)
    calls = []

    def fake_runner(argv, env=None, should_stop=None):
        calls.append(argv)
        yield "__exit__ 0"

    def _explode(*a, **kw):
        raise AssertionError("no subprocess may run once the preflight blocks")

    monkeypatch.setattr(V.subprocess, "Popen", _explode)
    with pytest.raises(V.VllmLifecycleError) as exc:
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert calls == []
    assert "2.0 GB free" in str(exc.value)
    assert "15.0 GB" in str(exc.value)
    assert V.is_installed() is False
    assert not V.pip_tmpdir().exists()


def test_acknowledging_low_resources_never_overrides_a_disk_refusal(monkeypatch):
    _allow_install(monkeypatch, free=2 * 1024**3)
    calls = []

    def fake_runner(argv, env=None, should_stop=None):
        calls.append(argv)
        yield "__exit__ 0"

    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(
            FakeCtx(), version="0.26.0", runner=fake_runner, acknowledge_low_resources=True
        )
    assert calls == []


def test_low_ram_warns_with_the_real_number_and_is_never_a_hard_refusal(monkeypatch):
    """The operator's actual 2026-07-29 machine: 6.03 GB of RAM."""
    _allow_install(monkeypatch, ram=6_025_867_264)
    pre = V.install_preflight()
    assert pre["blocking"] == []
    assert pre["requires_acknowledgement"] is True
    warn = [w for w in pre["warnings"] if w["check"] == "ram"]
    assert len(warn) == 1
    assert "5.61 GB" in warn[0]["detail"]
    assert "heuristic" in warn[0]["detail"]
    assert pre["ram"]["total_bytes"] == 6_025_867_264  # never rounded away
    assert pre["ram"]["sufficient"] is False


def test_low_ram_refuses_without_acknowledgement_then_proceeds_with_it(monkeypatch):
    _allow_install(monkeypatch, ram=4 * 1024**3)
    _fake_venv()
    calls = []

    def fake_runner(argv, env=None, should_stop=None):
        calls.append(argv)
        yield "__exit__ 0"

    with pytest.raises(V.VllmLifecycleError, match="acknowledge_low_resources"):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert calls == []
    result = V.run_install_job(
        FakeCtx(), version="0.26.0", runner=fake_runner, acknowledge_low_resources=True
    )
    assert result["installed"] is True


def test_preflight_reports_absent_not_zero_when_a_probe_cannot_measure(monkeypatch):
    monkeypatch.setattr(V, "_total_ram_bytes", lambda: None)
    monkeypatch.setattr(V, "_free_disk_bytes", lambda p: None)
    monkeypatch.setattr(V, "_filesystem_type_of", lambda p: None)
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": False})
    pre = V.install_preflight()
    assert pre["ram"]["total_bytes"] is None and pre["ram"]["total_gb"] is None
    assert pre["disk"]["free_bytes"] is None and pre["disk"]["free_gb"] is None
    assert pre["ram"]["measured"] is False and pre["disk"]["measured"] is False
    # tri-state: unknown, never a fabricated False that would manufacture a refusal
    assert pre["ram"]["sufficient"] is None and pre["disk"]["sufficient"] is None
    assert pre["unpack_area"]["ram_backed"] is None
    assert pre["blocking"] == []
    assert pre["requires_acknowledgement"] is False
    assert {n["check"] for n in pre["notes"]} == {"disk", "ram", "unpack_area"}


def test_an_unmeasurable_preflight_never_blocks_the_install(monkeypatch):
    _allow_install(monkeypatch)
    monkeypatch.setattr(V, "_total_ram_bytes", lambda: None)
    monkeypatch.setattr(V, "_free_disk_bytes", lambda p: None)
    monkeypatch.setattr(V, "_filesystem_type_of", lambda p: None)
    _fake_venv()

    def fake_runner(argv, env=None, should_stop=None):
        yield "__exit__ 0"

    assert V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)["installed"] is True


def test_a_ram_backed_install_target_is_an_acknowledgeable_warning_not_a_block(monkeypatch):
    """If the data dir is ITSELF tmpfs, redirecting TMPDIR there cannot help --
    surfaced honestly rather than silently useless."""
    _allow_install(monkeypatch, ram_backed=True)
    pre = V.install_preflight()
    warn = [w for w in pre["warnings"] if w["check"] == "unpack_area"]
    assert len(warn) == 1
    assert "tmpfs" in warn[0]["detail"] and "cannot help" in warn[0]["detail"]
    assert pre["blocking"] == []
    assert pre["requires_acknowledgement"] is True


def test_the_real_probes_read_real_values_or_honestly_return_none():
    """No monkeypatching -- exercises /proc/meminfo, shutil.disk_usage and the
    nearest-existing-ancestor walk for real."""
    ram = V._total_ram_bytes()
    assert ram is None or (isinstance(ram, int) and ram > 0)
    free = V._free_disk_bytes(V.pip_tmpdir())  # does not exist yet -- must still answer
    assert free is None or (isinstance(free, int) and free > 0)
    facts = V._filesystem_facts(V.pip_tmpdir())
    assert set(facts) == {"path", "filesystem", "ram_backed"}
    assert facts["ram_backed"] in (True, False, None)


def test_the_filesystem_probe_reuses_the_shared_forensics_detector():
    """A rename in forensics must redden HERE rather than silently degrading the
    preflight to 'unknown' (the stale-anchor lesson)."""
    from src.monitoring import forensics

    assert callable(forensics._filesystem_type)
    assert "tmpfs" in forensics._VOLATILE_FS


def test_the_preflight_payload_carries_no_score_looking_field_names():
    banned = ("score", "ranking", "rating", "grade")

    def walk(obj, path=""):
        bad = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and any(b in k.lower() for b in banned):
                    bad.append(f"{path}.{k}")
                bad += walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                bad += walk(v, f"{path}[{i}]")
        return bad

    assert walk(V.install_preflight()) == []


# --------------------------------------------------------------------------- #
# Latent fabricated-pass + raw-error guards found while wiring V1/V2.
# --------------------------------------------------------------------------- #
def test_a_runner_that_never_reports_an_exit_status_is_not_recorded_as_installed(monkeypatch):
    """exit_code used to INITIALISE to 0 (success), and only the __exit__
    sentinel changed it -- so a runner that yields no sentinel wrote the install
    marker for an install that was never confirmed. A fabricated pass, literally."""
    _allow_install(monkeypatch)
    _fake_venv()

    def fake_runner(argv, env=None, should_stop=None):
        yield "Collecting vllm"

    with pytest.raises(V.VllmLifecycleError, match="no exit status"):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert V.is_installed() is False


def test_a_disk_full_pip_failure_is_classified_not_reported_as_a_bare_exit_code(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()

    def fake_runner(argv, env=None, should_stop=None):
        yield "ERROR: Could not install packages due to an OSError:"
        yield "[Errno 28] No space left on device"
        yield "__exit__ 1"

    with pytest.raises(V.VllmLifecycleError) as exc:
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert "ran out of disk space" in str(exc.value)
    assert str(V.pip_tmpdir()) in str(exc.value)


def test_a_venv_without_pip_is_an_actionable_refusal_not_a_raw_filenotfound(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv(with_pip=False)

    def fake_runner(argv, env=None, should_stop=None):
        yield "__exit__ 0"

    with pytest.raises(V.VllmLifecycleError, match="has no pip"):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)


# --------------------------------------------------------------------------- #
# V3: the install-ATTEMPT journal. The marker records only SUCCESS (by design),
# so without this a failed install leaves NO durable trace: install_info is null
# after a restart and the error lived only in in-memory BackgroundJob state.
# --------------------------------------------------------------------------- #
def test_a_failed_install_records_an_attempt_with_the_real_exit_code(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()

    def fake_runner(argv, env=None, should_stop=None):
        yield "Collecting vllm==0.26.0"
        yield "ERROR: [Errno 28] No space left on device"
        yield "__exit__ 2"

    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)

    assert V.is_installed() is False  # unchanged: still NO marker
    assert V.install_info() is None
    history = V.install_history()  # ...but the attempt is now durable
    assert len(history) == 1
    attempt = history[0]
    assert attempt["outcome"] == "error"
    assert attempt["phase"] == "pip"
    assert attempt["exit_code"] == 2  # the REAL code, never a placeholder
    assert attempt["version"] == "0.26.0"
    # the diagnostic line survives verbatim -- redaction must never eat it
    assert any("No space left on device" in ln for ln in attempt["output_tail"])
    # and the preflight it ran against rides along
    assert attempt["preflight"]["gpu"]["available"] is True
    assert attempt["preflight"]["ram"]["total_bytes"] is not None


def test_a_successful_install_records_the_attempt_and_writes_the_marker(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()

    def fake_runner(argv, env=None, should_stop=None):
        yield "Successfully installed vllm-0.26.0"
        yield "__exit__ 0"

    assert V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)["installed"] is True
    assert V.install_info()["version"] == "0.26.0"  # the marker
    history = V.install_history()  # AND the journal
    assert len(history) == 1
    assert history[0]["outcome"] == "installed"
    assert history[0]["phase"] == "done"
    assert history[0]["exit_code"] == 0


def test_a_journal_write_failure_never_breaks_the_install(monkeypatch):
    """The recorded house lesson: a crash-recovery journal whose OWN write
    failure propagates aborts the very operation it exists to record. Injected
    at the real production seam so the real record_install_attempt body runs."""
    _allow_install(monkeypatch)
    _fake_venv()

    def _boom():
        raise OSError("simulated read-only data dir")

    monkeypatch.setattr(V, "_history_path", _boom)

    def fake_runner(argv, env=None, should_stop=None):
        yield "Successfully installed vllm-0.26.0"
        yield "__exit__ 0"

    assert V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)["installed"] is True
    assert V.is_installed() is True  # the install itself is untouched
    # ...and the journal degraded HONESTLY -- it says it stopped recording, rather
    # than an empty history reading as "no attempts were ever made".
    bounds = V.install_history_bounds()
    assert bounds["recording"] != "enabled"
    assert "simulated read-only data dir" in (bounds["recording_stopped_reason"] or "")


def test_the_retention_cap_actually_bounds_the_journal_file():
    for i in range(V._ATTEMPTS_CAP + 5):
        V.record_install_attempt(
            version=f"0.0.{i}", phase="pip", outcome="error", exit_code=1,
            output_tail=[f"line {i}"], output_lines_total=1,
        )
    history = V.install_history()
    assert len(history) == V._ATTEMPTS_CAP
    # the NEWEST attempts survive, in order -- never an arbitrary subset
    assert history[0]["version"] == "0.0.5"
    assert history[-1]["version"] == f"0.0.{V._ATTEMPTS_CAP + 4}"
    # the FILE is bounded too, not merely the reader
    assert len(V._history_path().read_text(encoding="utf-8").splitlines()) == V._ATTEMPTS_CAP


def test_the_journal_discloses_its_own_bound(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()

    def fake_runner(argv, env=None, should_stop=None):
        yield from (f"pip output line {i}" for i in range(500))
        yield "__exit__ 1"

    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)

    attempt = V.install_history()[0]
    # a TAIL is never presentable as a complete log: it states what it kept AND
    # the real total.
    assert attempt["output_lines_kept"] == V._OUTPUT_TAIL_LINES
    assert attempt["output_lines_total"] == 500
    assert attempt["output_truncated"] is True
    assert attempt["output_tail"][-1] == "pip output line 499"  # the NEWEST lines
    bounds = V.install_history_bounds()
    assert bounds["attempts_cap"] == V._ATTEMPTS_CAP
    assert bounds["output_line_cap"] == V._OUTPUT_TAIL_LINES
    assert bounds["attempts_kept"] == 1
    assert bounds["recording"] == "enabled"
    assert "Bounded by construction" in bounds["note"]


def test_a_cancelled_install_is_recorded_as_cancelled_not_absent(monkeypatch):
    """An aggregation that omits an outcome makes 'absent' read as 'never
    attempted'. A cancellation is a real event with its own outcome."""
    _allow_install(monkeypatch)

    def fake_runner(argv, env=None, should_stop=None):
        yield "creating venv"
        yield "__exit__ 0"

    result = V.run_install_job(FakeCtx(stop_after=0), version="0.26.0", runner=fake_runner)
    assert result["state"] == "cancelled"
    history = V.install_history()
    assert len(history) == 1
    assert history[0]["outcome"] == "cancelled"
    assert history[0]["phase"] == "venv"
    assert history[0]["exit_code"] is None


def test_credentials_in_captured_output_are_redacted(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()

    def fake_runner(argv, env=None, should_stop=None):
        yield "Looking in indexes: https://alice:hunter2@pypi.internal/simple"
        yield "__exit__ 1"

    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)

    blob = V._history_path().read_text(encoding="utf-8")
    assert "hunter2" not in blob  # never written to disk in the clear
    assert "***redacted***" in blob
    assert "pypi.internal" in blob  # the diagnostic host survives


def test_an_unparseable_journal_line_is_skipped_not_raised():
    V.record_install_attempt(version="0.26.0", phase="pip", outcome="error", exit_code=1)
    with V._history_path().open("a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
    history = V.install_history()  # a torn final write must not hide the
    assert len(history) == 1       # attempts recorded before it
    assert history[0]["outcome"] == "error"


def test_status_carries_the_preflight_the_history_and_its_bound(monkeypatch):
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": False})
    V.record_install_attempt(version="0.26.0", phase="pip", outcome="error", exit_code=1)
    st = V.status()
    # ADDITIVE: every field existing consumers already read is still present.
    for key in ("installed", "install_info", "running", "verified_version", "estimated_size_note"):
        assert key in st
    assert st["preflight"]["schema"] == "oo-vllm-install-preflight-1"
    assert len(st["install_history"]) == 1
    assert st["install_history_bounds"]["attempts_cap"] == V._ATTEMPTS_CAP


def test_no_banned_metric_key_substrings_in_the_status_payload(monkeypatch):
    """Walk the real payload's KEYS -- never repr(), which trips on honest prose."""
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": False})
    V.record_install_attempt(
        version="0.26.0", phase="pip", outcome="error", exit_code=1,
        output_tail=["x"], output_lines_total=1, preflight=V.install_preflight(),
    )
    banned = ("score", "ranking", "rating", "grade")

    def walk(obj, path=""):
        bad = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and any(b in k.lower() for b in banned):
                    bad.append(f"{path}.{k}")
                bad += walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                bad += walk(v, f"{path}[{i}]")
        return bad

    assert walk(V.status()) == []


# --------------------------------------------------------------------------- #
# Skeptic findings, 2026-07-29
# --------------------------------------------------------------------------- #
def test_cancel_kills_a_SILENT_child_instead_of_waiting_for_it(monkeypatch, tmp_path):
    """The load-bearing cancel test: it drives the REAL ``_default_runner`` against a
    REAL subprocess that goes SILENT, which is pip's actual shape while a multi-GB
    wheel downloads (no live progress on a non-TTY).

    The pre-existing tests all inject a generator that yields lines instantly, so the
    per-line ``ctx.stopping`` check always ran and the wedge was invisible: the worker
    blocked in ``for line in proc.stdout`` and the child kept downloading for as long
    as it liked, while the job stayed "running" and the endpoint refused every retry.
    Since the job advertises ``cancellable=True``, that was Cancel theater."""
    child = "import time,sys; print('Collecting vllm', flush=True); time.sleep(60)"
    real_popen = V.subprocess.Popen
    spawned = []

    def _popen(argv, **kw):
        kw.pop("env", None)
        p = real_popen([V.sys.executable, "-c", child], **kw)
        spawned.append(p)
        return p

    monkeypatch.setattr(V.subprocess, "Popen", _popen)

    stop = {"now": False}
    seen = []
    gen = V._default_runner(["pip", "install", "vllm"], env=None, should_stop=lambda: stop["now"])
    t0 = time.time()
    for line in gen:
        seen.append(line)
        if len(seen) >= 2:  # one real line, then at least one idle heartbeat
            stop["now"] = True
    elapsed = time.time() - t0

    assert V._HEARTBEAT in seen, (
        "an idle child must still wake the caller, or ctx.stopping is never re-read")
    assert elapsed < 30, f"cancel must not wait out the child ({elapsed:.1f}s of a 60s sleep)"
    assert spawned and spawned[0].poll() is not None, "the child must be KILLED, not left running"
    assert not any(s.startswith("__exit__") for s in seen), (
        "a cancelled run must not report an exit status it never legitimately observed")


def test_a_heartbeat_is_never_recorded_as_pip_output(monkeypatch):
    """The heartbeat is OUR sentinel, not something pip said. If it reached the
    journal or the progress line it would be a fabricated log entry."""
    _allow_install(monkeypatch)
    _fake_venv()
    monkeypatch.setattr(V, "_package_present", lambda venv, name: True)

    def fake_runner(argv, env=None, should_stop=None):
        yield V._HEARTBEAT
        yield "Collecting vllm"
        yield V._HEARTBEAT
        yield "__exit__ 0"

    ctx = FakeCtx()
    assert V.run_install_job(ctx, version="0.26.0", runner=fake_runner)["installed"] is True
    assert V._HEARTBEAT not in " ".join(ctx.details)
    rec = V.install_history()[-1]
    assert V._HEARTBEAT not in rec["output_tail"]
    assert rec["output_lines_total"] == 1, "only the real pip line counts as output"


def test_a_venv_with_python_but_no_pip_is_REPAIRED_not_blamed_on_the_system(monkeypatch):
    """`python -m venv` writes bin/python well before ensurepip finishes, so a cancel
    or crash in that window leaves python-without-pip. Keying only on venv_python()
    then skipped repair FOREVER and raised a message blaming a missing system package
    -- self-perpetuating, and misleading about a state the previous attempt created."""
    _allow_install(monkeypatch)
    _fake_venv(with_pip=False)  # the interrupted-venv state
    monkeypatch.setattr(V, "_package_present", lambda venv, name: True)
    calls = []

    def fake_runner(argv, env=None, should_stop=None):
        calls.append(argv)
        if "venv" in argv:
            V.venv_bin("pip").write_text("#!/bin/sh\n", encoding="utf-8")  # ensurepip finishes
        yield "__exit__ 0"

    assert V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)["installed"] is True
    assert any("venv" in a for a in calls), "the incomplete venv must be re-created, not skipped"


def test_pip_exiting_zero_without_installing_vllm_never_writes_the_marker(monkeypatch):
    """pip exiting 0 is evidence about PIP, not about this venv: PIP_TARGET /
    PIP_PREFIX / PIP_USER in the inherited environment all redirect the install and
    still exit 0. The marker claims vLLM is installed HERE, so it needs a measured
    absence to be refused -- and an UNRECOGNISED layout must not fabricate one."""
    _allow_install(monkeypatch)
    _fake_venv()

    def fake_runner(argv, env=None, should_stop=None):
        yield "__exit__ 0"

    monkeypatch.setattr(V, "_package_present", lambda venv, name: False)  # measured absence
    with pytest.raises(V.VllmLifecycleError, match="not present"):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert V.is_installed() is False, "a redirected install must leave NO marker"

    monkeypatch.setattr(V, "_package_present", lambda venv, name: None)  # unknown layout
    assert V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)["installed"] is True


def test_package_present_is_tristate_over_a_real_directory_tree(tmp_path):
    venv = tmp_path / "v"
    assert V._package_present(venv, "vllm") is None, "no site-packages -> unknown, never False"
    sp = venv / "lib" / "python3.13" / "site-packages"
    sp.mkdir(parents=True)
    assert V._package_present(venv, "vllm") is False, "a readable, empty site-packages -> absent"
    (sp / "vllm").mkdir()
    assert V._package_present(venv, "vllm") is True
    (venv / "lib" / "python3.13" / "site-packages" / "vllm").rmdir()
    (sp / "vllm-0.26.0.dist-info").mkdir()
    assert V._package_present(venv, "vllm") is True, "a dist-info alone is still evidence"


def test_the_pip_unpack_dir_is_swept_before_use_not_only_after(monkeypatch):
    """The ``finally`` cleanup does not run when the process is KILLED -- SIGKILL, OOM,
    or the app's own SIGTERM shutdown (the worker sits on a daemon thread, abandoned at
    interpreter exit). Up to ~10 GB then persists, because this area moved from the
    ambient /tmp (which the OS clears) onto real disk beside the venv (which nothing
    clears). Sweeping at the START reclaims that residue and stops pip unpacking into a
    stale tree."""
    _allow_install(monkeypatch)
    _fake_venv()
    monkeypatch.setattr(V, "_package_present", lambda venv, name: True)
    residue = V.pip_tmpdir()
    residue.mkdir(parents=True, exist_ok=True)
    (residue / "half-unpacked-torch.whl").write_text("x" * 1024, encoding="utf-8")
    seen = {}

    def fake_runner(argv, env=None, should_stop=None):
        seen["residue_at_run_time"] = (residue / "half-unpacked-torch.whl").exists()
        yield "__exit__ 0"

    V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert seen["residue_at_run_time"] is False, "stale unpack residue must be gone BEFORE pip runs"


def test_a_torn_marker_does_not_read_as_installed(monkeypatch):
    """`is_installed()` tested file EXISTENCE only, so a truncated marker made the app
    report vLLM installed while `install_info()` returned None. "Installed" is a claim;
    an unreadable record cannot support it."""
    _fake_venv()
    V._marker_path().write_text("", encoding="utf-8")  # a torn write
    assert V.install_info() is None
    assert V.is_installed() is False


def test_the_journal_trim_is_atomic(monkeypatch):
    """The append degrades safely by design (a torn tail is one skipped line), but the
    TRIM truncates the file first -- a crash in that window destroyed the WHOLE
    history, which is the one thing a crash journal must not do to itself."""
    for i in range(V._ATTEMPTS_CAP + 3):
        V.record_install_attempt(version=f"0.{i}", phase="pip", outcome="error", error="boom")
    assert len(V.install_history()) == V._ATTEMPTS_CAP

    calls = []
    real_replace = os.replace

    def _boom(src, dst):
        calls.append((src, dst))
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(V.os, "replace", _boom)
    V.record_install_attempt(version="9.9", phase="pip", outcome="error", error="boom")
    monkeypatch.setattr(V.os, "replace", real_replace)
    assert calls, "the trim must go through os.replace, not a truncating write"
    # The prior history survived the failed trim, and the temp is not orphaned.
    assert len(V.install_history()) >= V._ATTEMPTS_CAP
    assert not list(V._history_path().parent.glob("*.tmp")), "a failed swap must clean its temp"


def test_the_preflight_states_how_much_of_it_is_a_measurement(monkeypatch):
    """"We measured this machine and it is fine" and "this machine told us nothing"
    produced IDENTICAL gate output. The gate is deliberately unchanged (an unmeasurable
    preflight must never block), but the DISTINCTION is now stated."""
    _allow_install(monkeypatch)
    full = V.install_preflight()
    assert full["checks_measured"] == full["checks_total"] == 3
    assert full["fully_unmeasured"] is False

    monkeypatch.setattr(V, "_total_ram_bytes", lambda: None)
    monkeypatch.setattr(V, "_free_disk_bytes", lambda p: None)
    monkeypatch.setattr(V, "_filesystem_type_of", lambda p: None)
    blind = V.install_preflight()
    assert blind["checks_measured"] == 0 and blind["fully_unmeasured"] is True
    # ...and still never a fabricated refusal.
    assert blind["blocking"] == [] and blind["requires_acknowledgement"] is False


def test_the_ui_status_payload_is_bounded_but_the_bundle_gets_the_whole_journal():
    """The journal is bounded by construction, but its worst case is REAL: 20
    attempts x 50 lines x 400 chars measured ~414 KB, and status() rides the
    Settings -> AI panel and the red-pill click -- on exactly the machine whose
    installs keep failing, which is what fills it. The interactive payload is
    trimmed; the diagnostics bundle still takes everything, because being
    diagnosable after a restart is what the journal is FOR. Neither is silent."""
    for i in range(V._ATTEMPTS_CAP + 3):
        V.record_install_attempt(
            version=f"0.{i}", phase="pip", outcome="error", error="boom",
            output_tail=["x" * V._OUTPUT_LINE_CHARS] * V._OUTPUT_TAIL_LINES,
            output_lines_total=99999,
        )
    full = V.install_history()
    assert len(full) == V._ATTEMPTS_CAP

    ui = V.status()
    assert len(ui["install_history"]) == V._UI_HISTORY_LIMIT < V._ATTEMPTS_CAP
    assert ui["install_history"] == full[-V._UI_HISTORY_LIMIT:], "keep the NEWEST attempts"
    # the truncation is DISCLOSED, never inferred from a short list
    b = ui["install_history_bounds"]
    assert b["attempts_in_this_payload"] == V._UI_HISTORY_LIMIT
    assert b["attempts_kept"] == V._ATTEMPTS_CAP
    assert len(json.dumps(ui)) < len(json.dumps(V.status(history_limit=None)))

    whole = V.status(history_limit=None)
    assert whole["install_history"] == full
    assert whole["install_history_bounds"]["attempts_in_this_payload"] == V._ATTEMPTS_CAP


def test_the_diagnostics_member_takes_the_complete_journal():
    """Source guard on the WIRING: trimming status() for the UI must not silently
    trim the diagnostics bundle, whose whole purpose is the full record."""
    src = (Path(__file__).resolve().parents[1] / "src" / "monitoring" / "ai_diagnostics.py")
    assert "status(history_limit=None)" in src.read_text(encoding="utf-8")


def test_a_refusal_message_never_reads_as_self_contradictory_at_the_floor(monkeypatch):
    """Available space is truncated for display, not rounded to nearest: one byte
    short of the floor used to render "Only 15.0 GB free -- needs at least 15.0 GB",
    a refusal that reads as a bug. Truncating also never over-reports headroom."""
    monkeypatch.setattr(V, "_free_disk_bytes", lambda p: V.INSTALL_DISK_FLOOR_BYTES - 1)
    monkeypatch.setattr(V, "_total_ram_bytes", lambda: 32 * 1024**3)
    monkeypatch.setattr(V, "_filesystem_type_of", lambda p: "ext4")
    pre = V.install_preflight(gpu={"available": True})
    assert pre["disk"]["sufficient"] is False
    assert pre["disk"]["free_gb"] < pre["disk"]["floor_gb"], (
        "the DISPLAYED free figure must stay below the displayed floor it is refused against")


# --------------------------------------------------------------------------- #
#  uv-first install (field report 2026-07-30: "I had to install uv ... then
#  use `uv pip install vllm`")
# --------------------------------------------------------------------------- #
def _record(calls, *, uv_ok=True, install_exit="0"):
    """A runner that logs every argv and can make the uv bootstrap fail."""

    def runner(argv, env=None, should_stop=None):
        calls.append(list(argv))
        if argv[-1] == "uv":
            if uv_ok:
                V.venv_bin("uv").write_text("#!/bin/sh\n", encoding="utf-8")
                yield "__exit__ 0"
            else:
                yield "__exit__ 1"
            return
        yield f"__exit__ {install_exit}"

    return runner


def test_the_install_uses_uv_for_the_big_resolve(monkeypatch):
    """The operator's own successful path. vLLM's graph is torch plus the CUDA
    runtime, and pip's backtracking resolver on a graph that size is where installs go
    to die -- no output, no progress, no end, which is what "seems broken" looks like."""
    _allow_install(monkeypatch)
    _fake_venv()
    calls: list[list[str]] = []
    V.run_install_job(FakeCtx(), version="0.26.0", runner=_record(calls))

    bootstrap, big = calls[0], calls[-1]
    assert bootstrap[-1] == "uv" and bootstrap[0].endswith("/pip"), (
        "uv comes from PyPI over HTTPS into the unprivileged venv -- the SAME channel "
        "this module already trusts, never a piped shell script from a vendor site"
    )
    assert big[0].endswith("/uv") and big[1:3] == ["pip", "install"]
    assert "--python" in big and str(V.venv_python()) in big, (
        "uv otherwise resolves against its own idea of an interpreter, not the one "
        "that will run the server"
    )
    assert big[-1] == "vllm==0.26.0"


def test_a_uv_bootstrap_failure_falls_back_to_pip(monkeypatch):
    """Falling back IS the design: this can make the install work where it did not,
    and must not be able to make it fail where it worked."""
    _allow_install(monkeypatch)
    _fake_venv()
    calls: list[list[str]] = []
    out = V.run_install_job(FakeCtx(), version="0.26.0", runner=_record(calls, uv_ok=False))

    big = calls[-1]
    assert big[0].endswith("/pip") and big[-1] == "vllm==0.26.0"
    assert "--retries" in big, "the pip path keeps its own long-download flags"
    assert out["installed"] is True


def test_the_resolver_can_be_forced_back_to_pip(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()
    monkeypatch.setenv("OO_VLLM_RESOLVER", "pip")
    calls: list[list[str]] = []
    V.run_install_job(FakeCtx(), version="0.26.0", runner=_record(calls))
    assert len(calls) == 1, "no uv bootstrap at all"
    assert calls[0][0].endswith("/pip")


def test_a_failure_names_the_resolver_that_actually_ran(monkeypatch):
    """The journal and the error have to say WHICH resolver failed, or a field report
    describes a pip failure that was really uv's (or the reverse)."""
    _allow_install(monkeypatch)
    _fake_venv()
    calls: list[list[str]] = []
    with pytest.raises(V.VllmLifecycleError) as exc:
        V.run_install_job(FakeCtx(), version="0.26.0", runner=_record(calls, install_exit="1"))
    assert "uv install vllm==0.26.0 failed" in str(exc.value)
    assert V.install_history()[-1]["phase"] == "uv"


# --------------------------------------------------------------------------- #
#  Pre-downloading the model WEIGHTS (field ask 2026-07-30)
# --------------------------------------------------------------------------- #
def test_an_interrupted_download_is_not_reported_as_cached(monkeypatch, tmp_path):
    """huggingface_hub creates the repo tree as soon as a download STARTS, so a naive
    "does the directory exist" check calls a half-fetched model ready. Reporting an
    incomplete model as downloaded is the fabrication this probe exists to avoid."""
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    repo = tmp_path / "models--mistralai--Ministral-3-3B-Instruct-2512"
    (repo / "snapshots").mkdir(parents=True)
    assert V.model_cache_state("mistralai/Ministral-3-3B-Instruct-2512")["cached"] is False

    rev = repo / "snapshots" / "abc123"
    rev.mkdir()
    assert V.model_cache_state("mistralai/Ministral-3-3B-Instruct-2512")["cached"] is False, (
        "an empty revision directory is a started download, not a finished one"
    )

    (rev / "config.json").write_text("{}", encoding="utf-8")
    st = V.model_cache_state("mistralai/Ministral-3-3B-Instruct-2512")
    assert st["cached"] is True and st["bytes"] == 2


def test_the_cache_dir_follows_hugging_faces_own_rules(monkeypatch, tmp_path):
    """A probe here and a download inside the managed venv must agree about the same
    directory, or the button reports on a cache nothing writes to."""
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert V.hf_cache_dir() == tmp_path / "hf" / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "explicit"))
    assert V.hf_cache_dir() == tmp_path / "explicit"


def test_an_already_cached_model_is_not_re_downloaded(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    rev = tmp_path / "models--org--m" / "snapshots" / "r1"
    rev.mkdir(parents=True)
    (rev / "config.json").write_text("{}", encoding="utf-8")
    _fake_venv()
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)

    called: list[int] = []
    out = V.run_model_download_job(
        FakeCtx(), model="org/m", runner=lambda *a, **k: called.append(1) or iter(())
    )
    assert out["state"] == "already_cached" and called == []


def test_the_download_needs_the_vllm_env_and_says_so(monkeypatch):
    """The downloader lives in the managed venv (huggingface_hub ships with vLLM), so
    the refusal names that -- the fix is one button away on the same panel."""
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    with pytest.raises(V.VllmUnsupportedError) as exc:
        V.run_model_download_job(FakeCtx(), model="org/m")
    assert "Install vLLM first" in str(exc.value)


def test_the_download_is_refused_under_airplane_mode(monkeypatch):
    """Hugging Face is clearnet, not Tor."""
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    with pytest.raises(V.VllmLifecycleError):
        V.run_model_download_job(FakeCtx(), model="org/m")


def test_success_needs_the_librarys_own_path_not_just_an_exit_code(monkeypatch, tmp_path):
    """A shell exits 0 for a script that printed a traceback and downloaded nothing.
    The sentinel is snapshot_download's returned path, so a silent no-op cannot be
    recorded as a completed download."""
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    _fake_venv()
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)

    def _silent(argv, env=None, should_stop=None):
        yield "__exit__ 0"

    with pytest.raises(V.VllmLifecycleError):
        V.run_model_download_job(FakeCtx(), model="org/m", runner=_silent)


def test_a_real_download_reports_the_cache_it_produced(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    _fake_venv()
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)

    def _runner(argv, env=None, should_stop=None):
        assert argv[0] == str(V.venv_python()) and argv[-1] == "org/m"
        rev = tmp_path / "models--org--m" / "snapshots" / "r1"
        rev.mkdir(parents=True)
        (rev / "config.json").write_text("{}", encoding="utf-8")
        yield "Fetching 3 files:  33%"
        yield f"__downloaded__ {rev}"
        yield "__exit__ 0"

    out = V.run_model_download_job(FakeCtx(), model="org/m", runner=_runner)
    assert out["downloaded"] is True and out["state"] == "downloaded"
    assert out["cached"] is True


# --------------------------------------------------------------------------- #
# Attempt-journal verifiability (2026-08-01). The uv switch was made because the
# operator's own path was uv, but a SUCCESSFUL install told us nothing about
# which resolver actually ran or how long it took -- so an exported bundle could
# not confirm the fix was doing anything. These pin the three fields that turn
# "it seems to work" into a checkable claim.
# --------------------------------------------------------------------------- #
def _last_attempt():
    hist = V.install_history()
    assert hist, "expected at least one journalled attempt"
    return hist[-1]


def test_journal_records_the_resolver_that_actually_ran(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()
    # Force pip, the one branch that needs no uv on disk.
    monkeypatch.setenv("OO_VLLM_RESOLVER", "pip")

    def fake_runner(argv, env=None, should_stop=None):
        yield "Successfully installed vllm-0.26.0"
        yield "__exit__ 0"

    V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    a = _last_attempt()
    assert a["resolver"] == "pip"
    # pip was ASKED for, so falling back to it is not a fallback.
    assert a["fallback_fired"] is False


def test_journal_flags_a_silent_uv_failure_rescued_by_pip(monkeypatch):
    """The defect this field exists for: uv was wanted, uv failed, pip quietly
    saved the install -- and the result is indistinguishable from 'uv worked'
    unless something records it."""
    _allow_install(monkeypatch)
    _fake_venv()
    monkeypatch.delenv("OO_VLLM_RESOLVER", raising=False)
    # uv install "succeeds" but never produces the binary, so _resolver_argv
    # falls back -- exactly the silent case.
    monkeypatch.setattr(V, "venv_bin", lambda name: V.venv_dir() / "bin" / name)

    def fake_runner(argv, env=None, should_stop=None):
        yield "__exit__ 0"

    V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    a = _last_attempt()
    assert a["resolver"] == "pip"
    assert a["fallback_fired"] is True, "a uv->pip fallback must be visible in the journal"


def test_journal_records_a_real_duration_never_a_fabricated_zero(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()
    monkeypatch.setenv("OO_VLLM_RESOLVER", "pip")
    # First read is the start stamp; every read after it is 7.5 s later. A plain
    # iterator is fragile here -- it silently depends on how many times the code
    # under test happens to call monotonic().
    calls: list[int] = []

    def _mono() -> float:
        calls.append(1)
        return 100.0 if len(calls) == 1 else 107.5

    monkeypatch.setattr(V.time, "monotonic", _mono)

    def fake_runner(argv, env=None, should_stop=None):
        yield "__exit__ 0"

    V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    a = _last_attempt()
    assert a["duration_s"] == pytest.approx(7.5, abs=0.01)
    assert isinstance(a["started_at"], float)


def test_a_failed_attempt_still_carries_its_timing(monkeypatch):
    """A failure is the case an operator most needs timed -- 'it hung for an
    hour' and 'it died instantly' are different diagnoses."""
    _allow_install(monkeypatch)
    _fake_venv()
    monkeypatch.setenv("OO_VLLM_RESOLVER", "pip")

    def fake_runner(argv, env=None, should_stop=None):
        yield "ERROR: could not resolve"
        yield "__exit__ 1"

    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    a = _last_attempt()
    assert a["outcome"] == "error"
    assert a["duration_s"] is not None
    assert a["resolver"] == "pip"


def test_record_install_attempt_omits_unknowns_rather_than_guessing():
    """A caller that did not time the attempt must yield None, never 0.0 -- a
    zero duration reads as an instant install."""
    V.record_install_attempt(version="0.26.0", phase="pip", outcome="installed")
    a = _last_attempt()
    assert a["duration_s"] is None
    assert a["resolver"] is None
    assert a["fallback_fired"] is None


# --------------------------------------------------------------------------- #
# status().package_present -- the marker and the venv can disagree, and that is
# precisely the state a restart lands in.
# --------------------------------------------------------------------------- #
def test_status_distinguishes_a_written_marker_from_a_present_package(monkeypatch):
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": False})
    _fake_venv()
    V._write_marker("0.26.0")
    st = V.status()
    assert st["installed"] is True, "the marker was written"
    # ...but nothing ever put vllm in site-packages.
    assert st["package_present"] is not True, (
        "a marker must not be reported as a present package -- that conflation is "
        "exactly what makes a broken install look healthy after a restart"
    )


def test_package_present_is_none_when_the_layout_is_unreadable(monkeypatch):
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": False})
    # No site-packages at all -> not measurable, and must NOT collapse to False.
    assert V._package_present(V.venv_dir(), "vllm") is None
