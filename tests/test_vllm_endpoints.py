"""
Endpoint-level tests for the dual-backend + vLLM lifecycle API (B1/B2,
2026-07-24 field-feedback Session B). Mirrors
``test_triage_and_source_tags_endpoints.py``'s style -- call the FastAPI route
functions directly, no TestClient/thread needed for the job-control routes.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api import llm as L


@pytest.fixture(autouse=True)
def _reset_state(tmp_path, monkeypatch):
    from src.llm import backend as B
    from src.llm import vllm_lifecycle as V

    B._reset_clients_for_tests()
    monkeypatch.setenv("OO_VLLM_VENV_DIR", str(tmp_path / "vllm_venv"))
    V._proc = None
    L._ollama_client = None
    if L._VLLM_INSTALL_JOB is not None:
        job = L._VLLM_INSTALL_JOB
        with job._lock:
            job._state = "idle"
            job._result = None
            job._thread = None
            job._error = None
    yield
    B._reset_clients_for_tests()
    V._proc = None


def test_backend_status_endpoint_discloses_the_decision(monkeypatch):
    from src.llm import backend as B

    monkeypatch.setattr(B, "detect_gpu", lambda: {"available": False})
    monkeypatch.setattr(B, "_vllm_status", lambda: {"installed": False, "running": False})
    monkeypatch.setattr(B, "_ollama_available", lambda: True)
    r = L.llm_backend_status()
    assert r["backend"] == "ollama"
    assert "reason" in r and "gpu" in r and "vllm" in r
    assert r["stored_override"] == "auto"
    # V4: /api/llm/backend surfaces CAPABILITY, not only selection.
    assert r["available"] is True and r["no_backend"] is False


def test_vllm_status_endpoint_reports_not_installed(tmp_path):
    r = L.vllm_status()
    assert r["installed"] is False
    assert "verified_version" in r
    assert "estimated_size_note" in r


def test_vllm_install_refuses_on_cpu_only(monkeypatch):
    from src.llm import backend as B

    monkeypatch.setattr(B, "detect_gpu", lambda: {"available": False})
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    with pytest.raises(HTTPException) as ei:
        L.vllm_install()
    assert ei.value.status_code == 409


def test_vllm_install_refuses_on_a_non_linux_host_even_with_a_gpu(monkeypatch):
    """A Windows/macOS machine (even one reporting a GPU) must be refused for
    the platform reason, before it ever reaches a doomed pip install against
    wheels that don't exist for its OS."""
    from src.llm import backend as B

    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr(B, "detect_gpu", lambda: {"available": True, "vram_mb": 8192})
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    with pytest.raises(HTTPException) as ei:
        L.vllm_install()
    assert ei.value.status_code == 409
    assert "Linux wheels" in ei.value.detail


def test_vllm_install_refuses_under_airplane_mode(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    with pytest.raises(HTTPException) as ei:
        L.vllm_install()
    assert ei.value.status_code == 409


def test_vllm_install_starts_a_background_job(monkeypatch):
    """This is about the WIRING -- does the endpoint hand the job its arguments --
    so every resource the preflight consults is stubbed generously, via the one
    ``_preflight_stub`` helper the sibling tests use.

    It used to hand-roll three of those stubs and read the machine's REAL free disk,
    which meant it failed on any box under the 15 GB install floor for a reason that
    has nothing to do with what it asserts (observed: 13.92 GB free mid-suite on a
    16 GB volume, while the same test passed when run alone). Hand-rolling a SUBSET
    of a helper's stubs is what let it drift when the preflight grew a disk check;
    keep the helper, so the next resource check reaches this test too."""
    from src.llm import vllm_lifecycle as V

    _preflight_stub(monkeypatch, ram=32 * 1024**3, free=200 * 1024**3)

    started_kwargs: dict = {}
    job = L._get_vllm_install_job()
    monkeypatch.setattr(
        job, "start", lambda **kw: (started_kwargs.update(kw), {"state": "running"})[1]
    )
    result = L.vllm_install(L.VllmInstallRequest(version="0.25.1"))
    assert result["started"] is True
    assert started_kwargs["version"] == "0.25.1"
    # sanity: the lifecycle's own verified default is a real, stated version
    assert V.VLLM_VERIFIED_VERSION


def test_vllm_install_is_409_free_when_already_running():
    job = L._get_vllm_install_job()
    with job._lock:
        job._state = "running"

        class _Alive:
            def is_alive(self):
                return True

        job._thread = _Alive()
    result = L.vllm_install()
    assert result["started"] is False


def test_vllm_start_refuses_bad_model_name():
    with pytest.raises(HTTPException) as ei:
        L.vllm_start(L.VllmStartRequest(model="../etc/passwd"))
    assert ei.value.status_code == 400


def test_vllm_start_refuses_when_not_installed(monkeypatch):
    from src.llm import backend as B

    monkeypatch.setattr(B, "detect_gpu", lambda: {"available": True})
    with pytest.raises(HTTPException) as ei:
        L.vllm_start(L.VllmStartRequest(model="my-model"))
    assert ei.value.status_code == 409


def test_vllm_start_persists_the_model_as_the_active_vllm_setting(monkeypatch, tmp_path):
    import src.config.app_settings as aps
    from src.llm import backend as B
    from src.llm import vllm_lifecycle as V

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8")
    V._write_marker("0.25.1")
    monkeypatch.setattr(B, "detect_gpu", lambda: {"available": True, "vram_mb": 8192})
    monkeypatch.setattr(V, "is_running", lambda: False)

    class _FakeProc:
        def poll(self):
            return None

    monkeypatch.setattr(
        "subprocess.Popen", lambda argv, **kw: _FakeProc()
    )
    result = L.vllm_start(L.VllmStartRequest(model="my/model"))
    assert result["started"] is True
    assert aps.load_settings().llm_model_vllm == "my/model"


def test_vllm_stop_when_nothing_tracked():
    result = L.vllm_stop()
    assert result["stopped"] is False


def test_settings_validate_llm_backend_and_llm_model_vllm(tmp_path, monkeypatch):
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    assert aps.load_settings().llm_backend == "auto"
    aps.save_settings({"llm_backend": "vllm"})
    assert aps.load_settings().llm_backend == "vllm"
    with pytest.raises(aps.AppSettingsError):
        aps.save_settings({"llm_backend": "not-a-backend"})

    assert aps.load_settings().llm_model_vllm is None
    aps.save_settings({"llm_model_vllm": "org/Model-Name-AWQ"})
    assert aps.load_settings().llm_model_vllm == "org/Model-Name-AWQ"
    aps.save_settings({"llm_model_vllm": ""})
    assert aps.load_settings().llm_model_vllm is None
    with pytest.raises(aps.AppSettingsError):
        aps.save_settings({"llm_model_vllm": "../etc/passwd"})
    # a corrupt/invalid llm_backend on disk is ignored on load, never trusted blindly.
    (tmp_path / "s.json").write_text('{"llm_backend": "not-real"}', encoding="utf-8")
    assert aps.load_settings().llm_backend == "auto"


def test_settings_api_roundtrips_the_new_dual_backend_fields(tmp_path, monkeypatch):
    import src.config.app_settings as aps
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    with TestClient(app) as c:
        r = c.put("/api/settings", json={"llm_backend": "ollama", "llm_model_vllm": "a/b"})
        assert r.status_code == 200
        body = c.get("/api/settings").json()
        assert body["llm_backend"] == "ollama"
        assert body["llm_model_vllm"] == "a/b"
        assert c.put("/api/settings", json={"llm_backend": "bogus"}).status_code == 400


# --------------------------------------------------------------------------- #
# V2 (2026-07-29): the resource preflight, surfaced before the click and
# enforced at the endpoint so a doomed multi-GB download never starts.
# --------------------------------------------------------------------------- #
def _preflight_stub(monkeypatch, *, ram, free, ram_backed=False):
    from src.llm import vllm_lifecycle as V

    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    monkeypatch.setattr(
        "src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8192}
    )
    monkeypatch.setattr(V, "_total_ram_bytes", lambda: ram)
    monkeypatch.setattr(V, "_free_disk_bytes", lambda p: free)
    monkeypatch.setattr(V, "_filesystem_type_of", lambda p: "tmpfs" if ram_backed else "ext4")


def test_vllm_install_preflight_endpoint_exposes_the_cost_before_the_click():
    r = L.vllm_install_preflight()
    assert r["schema"] == "oo-vllm-install-preflight-1"
    for key in ("disk", "ram", "unpack_area", "blocking", "warnings", "notes"):
        assert key in r
    assert "requires_acknowledgement" in r


def test_vllm_install_409s_with_an_acknowledgeable_detail_on_low_ram(monkeypatch):
    _preflight_stub(monkeypatch, ram=6_025_867_264, free=200 * 1024**3)
    with pytest.raises(HTTPException) as exc:
        L.vllm_install(L.VllmInstallRequest())
    assert exc.value.status_code == 409
    assert exc.value.detail["acknowledgeable"] is True
    assert "5.61 GB" in exc.value.detail["warnings"][0]["detail"]


def test_a_low_disk_409_is_not_acknowledgeable_even_with_the_flag_set(monkeypatch):
    _preflight_stub(monkeypatch, ram=32 * 1024**3, free=2 * 1024**3)
    with pytest.raises(HTTPException) as exc:
        L.vllm_install(L.VllmInstallRequest(acknowledge_low_resources=True))
    assert exc.value.status_code == 409
    assert exc.value.detail["acknowledgeable"] is False
    assert exc.value.detail["blocking"]


def test_vllm_install_passes_the_acknowledgement_through_to_the_job(monkeypatch):
    """The flag is useless if the endpoint swallows it."""
    _preflight_stub(monkeypatch, ram=6 * 1024**3, free=200 * 1024**3)
    seen = {}
    job = L._get_vllm_install_job()
    monkeypatch.setattr(job, "start", lambda **kw: (seen.update(kw), {"state": "running"})[1])
    L.vllm_install(L.VllmInstallRequest(acknowledge_low_resources=True))
    assert seen["acknowledge_low_resources"] is True


def test_vllm_status_endpoint_carries_the_preflight_and_the_attempt_history():
    r = L.vllm_status()
    assert r["preflight"]["schema"] == "oo-vllm-install-preflight-1"
    assert isinstance(r["install_history"], list)
    assert "attempts_cap" in r["install_history_bounds"]


# --------------------------------------------------------------------------- #
#  The default-model button on a vLLM machine (field ask 2026-07-30)
# --------------------------------------------------------------------------- #
def _vllm_backend(monkeypatch):
    """Stub only the RESOLVER -- the plan itself stays the production function, so
    these exercise the real path rather than a double of it.

    The payload is built by ``backend._result``, the SAME one builder every real
    branch uses, rather than hand-written (2026-08-02). A two-key literal passed
    these tests for months while omitting every field a caller might read; when the
    download plan began reading ``vllm``/``ollama``/``available`` -- to stop
    provisioning for a backend that is not installed -- the double silently described
    a machine with no GPU and nothing installed, and the tests failed against correct
    code. A double of a payload should be built by the thing that builds the payload."""
    from src.llm import backend as B

    payload = B._result(
        backend="vllm",
        reason="GPU + vLLM running",
        override=None,
        gpu={"available": True, "name": "test-gpu", "vram_mb": 8188},
        vllm={"installed": True, "running": True},
        ollama_ok=False,
    )
    monkeypatch.setattr(B, "resolve_backend", lambda: payload)


def test_the_vllm_plan_is_a_real_download_with_a_real_cached_answer(monkeypatch, tmp_path):
    """It used to report ``server_start`` + ``installed: None`` -- true (vLLM does fetch
    at start) and useless as a button: no download, no progress, and no way to know
    whether the several GB were already on the disk."""
    _vllm_backend(monkeypatch)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    p = L.default_model_plan()
    assert p["backend"] == "vllm"
    assert p["mechanism"] == "download", "not 'the server will fetch it later'"
    assert p["installed"] is False, "a real probe, not an unknown"

    from src.llm.ollama import MINISTRAL_SUGGESTION

    rev = tmp_path / ("models--" + MINISTRAL_SUGGESTION["vllm_model"].replace("/", "--")) / "snapshots" / "r1"
    rev.mkdir(parents=True)
    (rev / "config.json").write_text("{}", encoding="utf-8")
    assert L.default_model_plan()["installed"] is True


def test_downloading_before_vllm_is_installed_says_which_button_to_press(monkeypatch):
    _vllm_backend(monkeypatch)
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)
    with pytest.raises(HTTPException) as exc:
        L.default_model_install()
    assert exc.value.status_code == 409
    assert "Install vLLM first" in str(exc.value.detail)


def test_the_download_is_refused_under_airplane_mode(monkeypatch):
    _vllm_backend(monkeypatch)
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    with pytest.raises(HTTPException) as exc:
        L.default_model_install()
    assert exc.value.status_code == 409


def test_the_status_route_reports_the_vllm_download_job(monkeypatch, tmp_path):
    """The Ollama half always had a live surface (the pull queue); the vLLM half had
    none, because there was no download to report on."""
    _vllm_backend(monkeypatch)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    st = L.default_model_status()
    assert st["backend"] == "vllm"
    assert "job" in st and "plan" in st
    assert st["job"]["running"] is False
