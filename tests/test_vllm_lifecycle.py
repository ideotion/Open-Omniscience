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
import os
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
    _allow_install(monkeypatch)
    # Pretend the venv (with its pip) already exists -- skip the `python -m venv` phase.
    _fake_venv()

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
        yield "ERROR: could not find a version that satisfies the requirement"
        yield "__exit__ 1"

    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(FakeCtx(), version="0.25.1", runner=fake_runner)
    assert V.is_installed() is False  # a failed install leaves NO marker


def test_install_job_creates_the_venv_first_when_absent(monkeypatch):
    _allow_install(monkeypatch)
    seen_argvs = []

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
        existed.append(Path(env["TMPDIR"]).is_dir())
        yield "__exit__ 0"

    V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert existed == [True]
    assert not V.pip_tmpdir().exists()


def test_the_pip_unpack_dir_is_cleaned_up_even_when_pip_fails(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()
    existed = []

    def fake_runner(argv, env=None):
        existed.append(Path(env["TMPDIR"]).is_dir())
        yield "__exit__ 1"

    with pytest.raises(V.VllmLifecycleError):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert existed == [True]
    assert not V.pip_tmpdir().exists()


def test_the_pip_unpack_dir_is_cleaned_up_on_cancel(monkeypatch):
    """The finally covers the early cancel RETURN, not only the raise."""
    _allow_install(monkeypatch)

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
        yield "Collecting vllm"

    with pytest.raises(V.VllmLifecycleError, match="no exit status"):
        V.run_install_job(FakeCtx(), version="0.26.0", runner=fake_runner)
    assert V.is_installed() is False


def test_a_disk_full_pip_failure_is_classified_not_reported_as_a_bare_exit_code(monkeypatch):
    _allow_install(monkeypatch)
    _fake_venv()

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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

    def fake_runner(argv, env=None):
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
