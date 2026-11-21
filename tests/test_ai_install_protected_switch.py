"""R765 (row 232): switching protected mode on stops an AI install that is already running.

R763 refuses each AI-install step at its START while protected mode is on. A step that was already running when the operator
switched protected mode on kept downloading over the direct connection the operator had just turned away from. Saving protected
mode now stops each such step:
- the Ollama daemon's pull (the stream is left, which ends the daemon's download; queued pulls are dropped)
- the vLLM install and the model snapshot (their jobs are cancelled; their runner terminates the child)
- the Ollama installer script (its child is terminated and its pipe closed)

The save comes first and never waits on, or fails because of, the install. A stopped step says why. Starting it again needs a
fresh click, which R763 refuses until protected mode is off.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

import src.llm.install_transport as it
from tests.js_source_helper import function_body

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_stop_state(monkeypatch):
    monkeypatch.setattr(it, "_STOPPED_AT", {})
    monkeypatch.setattr(it, "_PROCS", {})
    monkeypatch.setattr(it, "_ACTIVE_PULLS", 0)


def _settings(monkeypatch, **kw):
    import src.safety.settings as settings

    st = settings.SafetySettings(**kw)
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    return st


def _wait(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


# --------------------------------------------------------------------------- the Ollama pull


class _Stream:
    """``httpx`` streaming context double: its lines are produced on demand, and ``closed`` records that the request ended."""

    def __init__(self, lines):
        self._lines = lines
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        yield from self._lines()


def test_a_running_pull_stops_reading_the_moment_protected_mode_is_switched_on(monkeypatch):
    from src.ingest import clear_kill_switch
    from src.llm.ollama import LLMUnavailable, OllamaClient

    clear_kill_switch()
    _settings(monkeypatch)
    sent: list[int] = []

    def lines():
        for i in range(1000):
            sent.append(i)
            yield f'{{"status": "pulling", "completed": {i}, "total": 1000}}'

    stream = _Stream(lines)
    c = OllamaClient()
    monkeypatch.setattr(c._client, "stream", lambda *a, **k: stream)
    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", lambda: type("M", (), {"stop_all": lambda self, n: False})())
    gen = c.pull("qwen2.5:3b")
    assert next(gen)["completed"] == 0
    assert it.stop_running_installs() == ["ollama-pull"]  # a pull on the direct route is named too
    with pytest.raises(LLMUnavailable) as exc:
        next(gen)
    assert str(exc.value) == it.AI_INSTALL_STOPPED_NOTE
    # one line was read past the switch (the one that told the loop to stop) and none was handed on; the request is closed
    assert len(sent) == 2 and stream.closed
    assert it._ACTIVE_PULLS == 0


def test_the_pull_queue_records_the_stop_and_drops_what_was_waiting(monkeypatch):
    from src.llm.ollama import LLMUnavailable
    from src.llm.pull_queue import ModelPullManager

    started = threading.Event()

    class Client:
        def pull(self, model):
            generation = it.stop_generation()
            started.set()
            while True:
                if it.stopped_since(generation):
                    raise LLMUnavailable(it.AI_INSTALL_STOPPED_NOTE)
                yield {"status": "pulling", "completed": 1, "total": 10}
                time.sleep(0.01)

        def list_installed_detailed(self):
            raise AssertionError("a stopped pull is never checked as a finished one")

    m = ModelPullManager(client_factory=Client)
    monkeypatch.setattr("src.llm.model_store.prepare_ollama_pull", lambda: {})
    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", lambda: m)
    monkeypatch.setattr("src.jobs.background.get_job", lambda kind: None)
    m.enqueue("qwen2.5:3b")
    m.enqueue("llama3.2:1b")
    assert started.wait(5)
    assert it.stop_running_installs() == ["ollama-pull"]
    assert _wait(lambda: m.status()["active"] is None)
    st = m.status()
    assert st["queue"] == []
    by_model = {e["model"]: e for e in st["history"]}
    for model in ("qwen2.5:3b", "llama3.2:1b"):
        assert by_model[model]["status"] == "cancelled"
        assert by_model[model]["note"] == it.AI_INSTALL_STOPPED_NOTE
        assert "error" not in by_model[model]


def test_the_download_status_says_why_the_pull_stopped():
    from src.api.llm import _pull_queue_state

    queue = {"active": None, "queue": [], "history": [{"model": "m", "status": "cancelled", "note": it.AI_INSTALL_STOPPED_NOTE}]}
    view = _pull_queue_state("m", queue, False)
    assert view == {"state": "cancelled", "detail": it.AI_INSTALL_STOPPED_NOTE, "stopped_note": it.AI_INSTALL_STOPPED_NOTE}
    # a Cancel the operator clicked keeps its plain word
    queue["history"] = [{"model": "m", "status": "cancelled"}]
    assert _pull_queue_state("m", queue, False) == {"state": "cancelled", "detail": "cancelled", "stopped_note": None}


def test_the_catalog_download_status_does_not_read_a_stopped_queue_as_done(monkeypatch):
    from src.api import llm

    class M:
        def status(self):
            return {"active": None, "queue": [], "history": [{"model": "m", "status": "cancelled", "note": it.AI_INSTALL_STOPPED_NOTE}]}

    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", lambda: M())
    monkeypatch.setattr(llm, "_download_backend", lambda backend: {"backend": "ollama"})
    out = llm.model_install_status("ollama")
    assert out["state"] == "cancelled" and out["stopped_note"] == it.AI_INSTALL_STOPPED_NOTE


# --------------------------------------------------------------------------- the vLLM jobs


@pytest.mark.parametrize("kind", ["vllm-install", "vllm-model-download"])
def test_a_running_vllm_job_is_cancelled_and_its_status_says_why(monkeypatch, kind):
    from src.api.llm import _with_stop_note
    from src.jobs.background import BackgroundJob


    def worker(ctx):
        while not ctx.stopping:
            time.sleep(0.01)
        return {"state": "cancelled"}  # the real workers return here; no later step runs

    job = BackgroundJob(kind, "test", worker, cancellable=True)
    monkeypatch.setattr("src.jobs.background.get_job", lambda k: job if k == kind else None)
    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", lambda: type("M", (), {"stop_all": lambda self, n: False})())
    job.start()
    assert _wait(lambda: job.status()["running"])
    assert it.stop_running_installs() == [kind]
    assert _wait(lambda: job.status()["state"] == "cancelled")
    st = _with_stop_note(job.status())
    assert st["stopped_note"] == it.AI_INSTALL_STOPPED_NOTE and st["detail"] == it.AI_INSTALL_STOPPED_NOTE
    # a later run, started after the switch, carries no stale note
    later = {"kind": kind, "state": "cancelled", "started_at": time.time() + 1}
    assert "stopped_note" not in _with_stop_note(later)
    # a run that finished as the switch landed is labelled "cancelled" by the job, but what it installed is used: no note
    done = {**job.status(), "result": {"installed": True, "state": "done"}}
    assert "stopped_note" not in _with_stop_note(done)


def test_a_run_the_operator_had_already_cancelled_keeps_reading_as_theirs(monkeypatch):
    from src.api.llm import _with_stop_note
    from src.jobs.background import BackgroundJob

    release = threading.Event()

    def worker(ctx):
        release.wait(5)  # still terminating its child when protected mode is switched on
        return {"state": "cancelled"}

    job = BackgroundJob("vllm-install", "test", worker, cancellable=True)
    monkeypatch.setattr("src.jobs.background.get_job", lambda k: job if k == "vllm-install" else None)
    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", lambda: type("M", (), {"stop_all": lambda self, n: False})())
    job.start()
    job.cancel()
    it.stop_running_installs()
    release.set()
    assert _wait(lambda: job.status()["state"] == "cancelled")
    assert "stopped_note" not in _with_stop_note(job.status())


def test_a_step_the_stop_came_before_is_never_spawned(monkeypatch):
    """The uv step falls back to pip when it is stopped; the runner must not then start pip."""
    import src.llm.vllm_lifecycle as vl

    spawned: list = []
    def popen(*a, **k):
        spawned.append(a)
        raise AssertionError("spawned")

    monkeypatch.setattr(vl.subprocess, "Popen", popen)
    assert list(vl._default_runner(["pip", "install", "vllm"], should_stop=lambda: True)) == [vl._HEARTBEAT]
    assert spawned == []


def test_the_stop_never_raises_even_when_every_source_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("unreadable")

    monkeypatch.setattr("src.jobs.background.get_job", boom)
    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", boom)
    assert it.stop_running_installs() == []


# --------------------------------------------------------------------------- the Ollama installer script


@pytest.mark.skipif(sys.platform == "win32", reason="the Ollama installer is a POSIX shell script")
def test_the_installer_script_and_the_download_it_waits_on_are_ended(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    """The script's shell is terminated, and the "curl" it waits on (a child the signal does not reach) ends when its next
    progress write meets the closed pipe."""
    import src.llm.installer as inst

    _settings(monkeypatch)
    script = tmp_path / "install.sh"
    # the inner shell stands in for curl: a foreground child of the script that writes progress into the shared pipe
    script.write_text(
        "#!/bin/sh\nsh -c 'echo pid $$; while :; do echo progress; sleep 0.05; done'\necho after-download\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(inst, "_validate_staged", lambda p: script)
    monkeypatch.setattr(inst, "_check_online", lambda: None)
    monkeypatch.setattr(inst, "_is_root", lambda: True)
    monkeypatch.setattr(it, "_TERMINATE_WAIT_S", 2.0)
    monkeypatch.setattr("src.jobs.background.get_job", lambda kind: None)
    monkeypatch.setattr("src.llm.pull_queue.get_pull_manager", lambda: type("M", (), {"stop_all": lambda self, n: False})())
    gen = inst.run_installer(str(script))
    first = next(gen)
    assert first.startswith("pid ")
    child = int(first.split()[1])
    assert it.stop_running_installs() == ["ollama-installer"]
    seen: list[str] = []
    with pytest.raises(inst.InstallerUnavailable) as exc:
        for line in gen:
            seen.append(line)
    assert str(exc.value) == it.AI_INSTALLER_STOPPED_NOTE
    assert "after-download" not in seen and not any(s.startswith("__exit__") for s in seen)

    def gone() -> bool:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            return True
        # a zombie still answers signal 0; it is no longer downloading
        try:
            with open(f"/proc/{child}/stat", encoding="utf-8") as fh:
                return fh.read().split(") ", 1)[1].startswith("Z")
        except OSError:
            return True

    assert _wait(gone, 10)
    assert not it._PROCS
    # what it unpacked is not reported as installed until an install finishes
    assert it._interrupted_marker().exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the Ollama installer is a POSIX shell script")
def test_a_silent_installer_still_sees_the_stop(monkeypatch, tmp_path):
    import src.llm.installer as inst

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    _settings(monkeypatch)
    script = tmp_path / "install.sh"
    script.write_text("#!/bin/sh\necho start\nsleep 60\necho never\n", encoding="utf-8")
    monkeypatch.setattr(inst, "_validate_staged", lambda p: script)
    monkeypatch.setattr(inst, "_check_online", lambda: None)
    monkeypatch.setattr(inst, "_is_root", lambda: True)
    monkeypatch.setattr(it, "_TERMINATE_WAIT_S", 2.0)
    gen = inst.run_installer(str(script))
    assert next(gen) == "start"
    with it._STOP_LOCK:  # only the generation: the reader alone must notice, with nothing printed
        it._STOP_GENERATION += 1
    began = time.monotonic()
    with pytest.raises(inst.InstallerUnavailable):
        list(gen)
    assert time.monotonic() - began < 10


def test_a_half_unpacked_ollama_is_not_reported_until_an_install_finishes(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    binary = tmp_path / "ollama"
    binary.write_bytes(b"truncated")
    it.mark_ollama_install_interrupted()
    assert it.ollama_install_interrupted(str(binary)) is True
    # a binary written after the stop (a later install, by the app or by hand) is believed
    os.utime(it._interrupted_marker(), (time.time() - 60, time.time() - 60))
    binary.write_bytes(b"whole")
    assert it.ollama_install_interrupted(str(binary)) is False
    it.clear_ollama_install_interrupted()
    assert it.ollama_install_interrupted(str(binary)) is False


@pytest.mark.skipif(sys.platform == "win32", reason="the Ollama installer is a POSIX shell script")
def test_an_installer_that_finished_before_the_switch_is_reported_as_finished(monkeypatch, tmp_path):
    import src.llm.installer as inst

    _settings(monkeypatch)
    script = tmp_path / "install.sh"
    script.write_text("#!/bin/sh\necho done\n", encoding="utf-8")
    monkeypatch.setattr(inst, "_validate_staged", lambda p: script)
    monkeypatch.setattr(inst, "_check_online", lambda: None)
    monkeypatch.setattr(inst, "_is_root", lambda: True)
    gen = inst.run_installer(str(script))
    assert next(gen) == "done"
    (proc,) = list(it._PROCS)
    assert _wait(lambda: _exited(proc.pid))  # the script has finished; the reader has not yet seen its end
    with it._STOP_LOCK:  # a switch that lands after the script's last line, once it has exited 0
        it._STOP_GENERATION += 1
    assert list(gen) == ["__exit__ 0"]


def test_only_the_switch_stops_installs_not_every_protected_save(monkeypatch, tmp_path):
    settings = _isolated_settings_file(monkeypatch, tmp_path)
    calls: list[int] = []
    def stop() -> list[str]:
        calls.append(1)
        return []

    monkeypatch.setattr(it, "stop_running_installs", stop)
    settings.save_settings({"fetch_mode": "protected", "http_proxy": "socks5h://127.0.0.1:9050"})
    settings.save_settings({"http_proxy": "socks5h://127.0.0.1:9150"})  # protected to protected: nothing can be running
    assert calls == [1]


def _exited(pid: int) -> bool:
    """True once ``pid`` is a zombie (exited, not yet reaped) or gone."""
    if not os.path.isdir("/proc/self"):  # no procfs (macOS): give the two-line script ample time instead
        time.sleep(1.0)
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().split(") ", 1)[1].startswith("Z")
    except OSError:
        return True


# --------------------------------------------------------------------------- the save


def _isolated_settings_file(monkeypatch, tmp_path):
    import src.safety.settings as settings

    monkeypatch.setattr(settings, "_path", lambda: tmp_path / "safety_settings.json")
    return settings


def test_saving_protected_mode_writes_it_first_then_stops_the_installs(monkeypatch, tmp_path):
    settings = _isolated_settings_file(monkeypatch, tmp_path)
    order: list[str] = []

    def stop():
        order.append("stop:" + settings._read_raw_strict()["fetch_mode"])
        return ["vllm-install"]

    monkeypatch.setattr(it, "stop_running_installs", stop)
    s = settings.save_settings({"fetch_mode": "protected", "http_proxy": "socks5h://127.0.0.1:9050"})
    assert order == ["stop:protected"]  # the mode was on disk before anything was stopped
    assert s.stopped_ai_installs == ["vllm-install"]
    order.clear()
    settings.save_settings({"fetch_mode": "transparent"})
    assert order == []  # transparent mode stops nothing


def test_the_save_never_fails_because_of_the_install(monkeypatch, tmp_path):
    settings = _isolated_settings_file(monkeypatch, tmp_path)

    def boom():
        raise RuntimeError("could not ask")

    monkeypatch.setattr(it, "stop_running_installs", boom)
    s = settings.save_settings({"fetch_mode": "protected", "http_proxy": "socks5h://127.0.0.1:9050"})
    assert s.is_protected and s.stopped_ai_installs == []


def test_the_settings_route_names_what_the_switch_stopped(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    _isolated_settings_file(monkeypatch, tmp_path)
    monkeypatch.setattr(it, "stop_running_installs", lambda: ["ollama-pull"])
    r = TestClient(app, base_url="http://127.0.0.1").put(
        "/api/safety/settings", json={"fetch_mode": "protected", "http_proxy": "socks5h://127.0.0.1:9050"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["stopped_ai_installs"] == ["ollama-pull"]


# --------------------------------------------------------------------------- the page


def _js(name: str) -> str:
    return (_ROOT / "src" / "static" / name).read_text(encoding="utf-8")


def test_the_page_says_the_install_was_stopped_when_protected_mode_is_saved():
    body = function_body(_js("app-backup.js"), "saveFetchMode")
    assert "stopped_ai_installs" in body and '"warn"' in body
    assert "Protected mode is on, so the AI install that was running was stopped" in body


def test_the_setup_chain_and_the_catalog_show_the_stop_note_instead_of_a_bare_cancel():
    js = _js("app-ai-tools.js")
    assert js.count('say(done.stopped_note ? t(done.stopped_note) : t("Cancelled."))') == 2
    assert "st.stopped_note ? t(st.stopped_note)" in js


def test_every_stop_sentence_is_translated():
    import json

    for lang in ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        data = json.loads((_ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        for key in (
            it.AI_INSTALL_STOPPED_NOTE,
            it.AI_INSTALLER_STOPPED_NOTE,
            "Protected mode is on, so the AI install that was running was stopped: it was downloading over a direct connection, "
            "not through your proxy. Switch protected mode off and start it again to finish.",
        ):
            assert data.get(key), (lang, key[:40])
