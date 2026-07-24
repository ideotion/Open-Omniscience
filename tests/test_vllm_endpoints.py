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


def test_vllm_install_refuses_under_airplane_mode(monkeypatch):
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)
    with pytest.raises(HTTPException) as ei:
        L.vllm_install()
    assert ei.value.status_code == 409


def test_vllm_install_starts_a_background_job(monkeypatch):
    from src.llm import backend as B
    from src.llm import vllm_lifecycle as V

    monkeypatch.setattr(B, "detect_gpu", lambda: {"available": True, "vram_mb": 8192})
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: False)

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
