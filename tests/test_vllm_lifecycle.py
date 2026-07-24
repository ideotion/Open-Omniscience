"""
Tests for the vLLM lifecycle module (B2, 2026-07-24 field-feedback Session B):
detect / install / start / stop / context auto-tune. No real subprocess, GPU,
or vLLM package is ever touched -- every runner/Popen is injected, matching
this project's own precedent for the Ollama binary installer
(``tests/test_llm_installer.py``, which the app itself can only fixture-test
in a sandbox with no GPU either).
"""

from __future__ import annotations

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
    yield
    V._proc = None


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
# compute_server_args -- the context auto-tune math (pure, disclosed method)
# --------------------------------------------------------------------------- #
def test_compute_server_args_no_vram_reading_is_a_conservative_default():
    args = V.compute_server_args(None)
    assert args["max_model_len"] == 4096
    assert 0 < args["gpu_memory_utilization"] <= 1
    assert "method" in args and "caveat" in args


def test_compute_server_args_scales_with_vram():
    small = V.compute_server_args(8192)   # 8 GB
    large = V.compute_server_args(24576)  # 24 GB
    assert large["max_model_len"] >= small["max_model_len"]
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
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8192}
    )
    # Pretend the venv python already exists (skip the `python -m venv` phase).
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_runner(argv):
        yield "Collecting vllm==0.25.1"
        yield "Successfully installed vllm-0.25.1"
        yield "__exit__ 0"

    result = V.run_install_job(FakeCtx(), version="0.25.1", runner=fake_runner)
    assert result["installed"] is True
    assert V.is_installed() is True
    assert V.install_info()["version"] == "0.25.1"


def test_install_job_never_writes_a_marker_on_a_failed_exit(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8192}
    )
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_runner(argv):
        yield "ERROR: could not find a version that satisfies the requirement"
        yield "__exit__ 1"

    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(FakeCtx(), version="0.25.1", runner=fake_runner)
    assert V.is_installed() is False  # a failed install leaves NO marker


def test_install_job_creates_the_venv_first_when_absent(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8192}
    )
    seen_argvs = []

    def fake_runner(argv):
        seen_argvs.append(argv)
        if "venv" in argv:
            # Simulate venv creation actually producing a python binary, so the
            # subsequent pip-install phase's own venv_bin("pip") lookup is moot
            # here (the fake pip call below never actually touches disk).
            V.venv_python().parent.mkdir(parents=True, exist_ok=True)
            V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")
            yield "__exit__ 0"
            return
        yield "Successfully installed vllm-0.25.1"
        yield "__exit__ 0"

    result = V.run_install_job(FakeCtx(), version="0.25.1", runner=fake_runner)
    assert result["installed"] is True
    assert any("venv" in a for a in seen_argvs)


def test_install_job_honours_a_cancel_between_venv_and_pip(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8192}
    )

    def fake_runner(argv):
        yield "creating venv"
        yield "__exit__ 0"

    ctx = FakeCtx(stop_after=0)
    result = V.run_install_job(ctx, version="0.25.1", runner=fake_runner)
    assert result["state"] == "cancelled"
    assert V.is_installed() is False
