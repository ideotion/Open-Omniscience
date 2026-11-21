"""R768 (row 240) and R769 (row 241): a running download stops when its transport changes under it.

R768: a download that started over a direct connection stops when protected mode is switched on. It never continues on that
transport and is never re-routed: it is paused with that reason, the partial file kept, and the operator resumes it.
R769: any running download, or AI install, stops when the stored settings can no longer be read (fail closed), and says that
reason rather than "protected mode".

One shared helper (``src.safety.transport_watch``) answers at every request and chunk boundary; ``GuardedSession`` carries one,
so every download built on ``guarded_session`` checks it without a per-feature copy.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

import pytest
import requests

from src.safety import transport_watch as tw

_ROOT = Path(__file__).resolve().parents[1]
_PROXY = "socks5h://127.0.0.1:9050"


def _settings(monkeypatch, **kw):
    import src.safety.settings as settings

    st = settings.SafetySettings(**kw)
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    return st


def _unreadable(monkeypatch):
    import src.safety.settings as settings

    def boom():
        raise RuntimeError("the store is locked")

    monkeypatch.setattr(settings, "load_settings", boom)


@pytest.fixture(autouse=True)
def _fast_recheck(monkeypatch):
    monkeypatch.setattr(tw, "RECHECK_S", 0.0)


# --------------------------------------------------------------------------- the helper


def test_a_direct_start_stops_when_protected_mode_is_switched_on(monkeypatch):
    _settings(monkeypatch)
    w = tw.TransportWatch()
    assert w.stop_reason() is None
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    tw.bump()
    assert w.stop_reason() == "protected"
    _settings(monkeypatch)  # switched back off: the stop stands, nothing resumes on its own
    assert w.stop_reason() == "protected"
    with pytest.raises(tw.TransportStopped) as exc:
        w.check()
    assert exc.value.reason == "protected" and str(exc.value) == tw.PROTECTED_STOP


def test_a_download_through_the_proxy_goes_on_while_protected_mode_stays_on(monkeypatch):
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    w = tw.TransportWatch()
    tw.bump()
    _settings(monkeypatch, fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9150")  # another proxy: not a downgrade
    assert w.stop_reason() is None


@pytest.mark.parametrize("protected", [False, True])
def test_unreadable_settings_stop_any_download_and_name_that_reason(monkeypatch, protected):
    if protected:
        _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    else:
        _settings(monkeypatch)
    w = tw.TransportWatch()
    _unreadable(monkeypatch)
    assert w.stop_reason() == "unreadable"
    st = _settings(monkeypatch)
    st.read_failed = True
    w2 = tw.TransportWatch(protected=False)
    assert w2.stop_reason() == "unreadable"
    assert "could not be read" in tw.UNREADABLE_STOP and "protected mode" not in tw.UNREADABLE_STOP


def test_the_settings_are_not_reread_on_every_chunk(monkeypatch):
    monkeypatch.setattr(tw, "RECHECK_S", 60.0)
    reads: list[int] = []
    import src.safety.settings as settings

    st = settings.SafetySettings()
    def load():
        reads.append(1)
        return st

    monkeypatch.setattr(settings, "load_settings", load)
    w = tw.TransportWatch()
    reads.clear()
    for _ in range(1000):
        assert w.stop_reason() is None
    assert reads == []
    tw.bump()  # the switch is seen at once, whatever the interval
    w.stop_reason()
    assert reads == [1]


# --------------------------------------------------------------------------- the session every download is built on


class _ChunkAdapter(requests.adapters.BaseAdapter):
    """Serves a body of ``n`` chunks; ``on_chunk(i)`` runs as chunk ``i`` is read."""

    def __init__(self, n: int, on_chunk) -> None:
        super().__init__()
        self.n, self.on_chunk, self.sent = n, on_chunk, 0

    def send(self, request, *args, **kwargs):  # type: ignore[override]
        self.sent += 1
        adapter = self

        class _Raw(io.RawIOBase):
            i = 0

            def readable(self):
                return True

            def readinto(self, b):
                if self.i >= adapter.n:
                    return 0
                adapter.on_chunk(self.i)
                self.i += 1
                b[:] = b"x" * len(b)  # one read, whatever size the reader asks for, is one chunk
                return len(b)

        resp = requests.Response()
        resp.status_code = 200
        resp.raw = _Raw()
        resp.url = request.url
        resp.request = request
        return resp

    def close(self):
        return None


def _session(monkeypatch, adapter):
    from src.safety.fetcher import _session_for
    from src.safety.settings import SafetySettings

    s = _session_for(SafetySettings())  # built while protected mode is off: it sends direct
    s.mount("https://", adapter)
    return s


def test_a_direct_body_stops_at_the_next_chunk_after_the_switch(monkeypatch):
    _settings(monkeypatch)

    def on_chunk(i):
        if i == 2:  # the switch lands while the third chunk arrives
            _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
            tw.bump()

    adapter = _ChunkAdapter(100, on_chunk)
    s = _session(monkeypatch, adapter)
    got: list[bytes] = []
    resp = s.get("https://dumps.example.org/big", stream=True)
    with pytest.raises(tw.TransportStopped):
        for chunk in resp.iter_content(4):
            got.append(chunk)
    assert len(got) == 2  # nothing handed on after the switch
    # and the session sends nothing more on its old transport
    with pytest.raises(tw.TransportStopped):
        s.get("https://dumps.example.org/next")
    assert adapter.sent == 1


def test_a_caller_that_does_not_stream_is_read_through_the_watch_too(monkeypatch):
    _settings(monkeypatch)
    calls: list[int] = []

    def on_chunk(i):
        calls.append(i)
        if i == 1:
            _unreadable(monkeypatch)

    s = _session(monkeypatch, _ChunkAdapter(50, on_chunk))
    with pytest.raises(tw.TransportStopped) as exc:
        s.get("https://pubmed.example.org/file.xml.gz")
    assert exc.value.reason == "unreadable"
    assert len(calls) < 50


def test_a_body_with_no_change_is_read_whole(monkeypatch):
    _settings(monkeypatch)
    s = _session(monkeypatch, _ChunkAdapter(5, lambda i: None))
    body = s.get("https://dumps.example.org/small").content
    assert len(body) == 5 * requests.models.CONTENT_CHUNK_SIZE and set(body) == {ord("x")}


# --------------------------------------------------------------------------- the downloads


def test_a_dump_download_pauses_with_the_reason_and_keeps_its_partial_file(monkeypatch, tmp_path):
    from src.wiki.dumps import DumpDownloadManager

    class _Resp:
        status_code = 200
        headers = {"Content-Length": "12"}

        def raise_for_status(self):
            return None

        def iter_content(self, _n):
            yield b"abcd"
            raise tw.TransportStopped("protected")

    m = DumpDownloadManager(base_dir=tmp_path, http_get=lambda url, headers: _Resp())
    entry = m._entry_for("en", "pages-articles")
    res = m._download(entry)
    assert res.status == "paused" and res.paused_by == "protected" and res.error is None
    assert Path(res.dest).read_bytes() == b"abcd"


def test_an_osm_download_pauses_with_the_settings_reason(tmp_path):
    from src.geo.osm_downloads import OsmDownloadManager

    class _Resp:
        status_code = 200
        headers = {"Content-Length": "12"}

        def raise_for_status(self):
            return None

        def iter_content(self, _n):
            yield b"abcd"
            raise tw.TransportStopped("unreadable")

    m = OsmDownloadManager(base_dir=tmp_path, http_get=lambda url, headers: _Resp())
    res = m._download(m._entry_for("monaco"))
    assert res.status == "paused" and res.paused_by == "settings" and res.error is None


# --------------------------------------------------------------------------- the AI installs (R769)


def test_an_ai_pull_stops_when_the_settings_become_unreadable(monkeypatch):
    from src.ingest import clear_kill_switch
    from src.llm.install_transport import AI_INSTALL_UNREADABLE_NOTE
    from src.llm.ollama import LLMUnavailable, OllamaClient

    clear_kill_switch()
    _settings(monkeypatch)

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield '{"completed": 1}'
            _unreadable(monkeypatch)
            yield '{"completed": 2}'
            yield '{"completed": 3}'

    c = OllamaClient()
    monkeypatch.setattr(c._client, "stream", lambda *a, **k: _Stream())
    gen = c.pull("qwen2.5:3b")
    assert next(gen)["completed"] == 1
    with pytest.raises(LLMUnavailable) as exc:
        next(gen)
    assert str(exc.value) == AI_INSTALL_UNREADABLE_NOTE


def test_a_vllm_job_stops_when_the_settings_become_unreadable_and_says_so(monkeypatch):
    from src.api.llm import _with_stop_note
    from src.jobs.background import BackgroundJob
    from src.llm import install_transport as it
    from src.llm.vllm_lifecycle import _stop_probe

    monkeypatch.setattr(it, "_STOPPED_AT", {})
    _settings(monkeypatch)
    ready = threading.Event()

    def worker(ctx):
        probe = _stop_probe(ctx)
        ready.set()
        while not probe():
            time.sleep(0.01)
        return {"state": "cancelled"} if ctx.stopping else {"state": "odd"}

    job = BackgroundJob("vllm-install", "test", worker, cancellable=True)
    job.start()
    assert ready.wait(5)
    _unreadable(monkeypatch)
    end = time.monotonic() + 10
    while job.status()["state"] != "cancelled" and time.monotonic() < end:
        time.sleep(0.02)
    st = _with_stop_note(job.status())
    assert st["state"] == "cancelled" and st["stopped_note"] == it.AI_INSTALL_UNREADABLE_NOTE


# --------------------------------------------------------------------------- the page


def test_every_panel_names_the_two_reasons_in_every_language():
    pause_p = (
        "Paused because protected mode was switched on: this download had started over a direct connection. Resume downloads "
        "the rest through your proxy."
    )
    pause_s = "Paused because the safety settings could not be read: nothing is sent until they can be read again. Resume once they can be read."
    for name in ("app-core.js", "taskmanager.js", "app-map.js"):
        js = (_ROOT / "src" / "static" / name).read_text(encoding="utf-8")
        assert 'paused_by === "protected"' in js and 'paused_by === "settings"' in js, name
        assert pause_p in js and pause_s in js, name
    med = (_ROOT / "src" / "static" / "app-medical.js").read_text(encoding="utf-8")
    assert '"protected_mode"' in med and '"settings_unreadable"' in med
    from src.llm import install_transport as it

    keys = [
        pause_p, pause_s, "Paused: protected mode was switched on", "Paused: the settings could not be read",
        tw.PROTECTED_STOP, tw.UNREADABLE_STOP, it.AI_INSTALL_UNREADABLE_NOTE, it.AI_INSTALLER_UNREADABLE_NOTE,
    ]
    for lang in ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        data = json.loads((_ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        for key in keys:
            assert data.get(key), (lang, key[:40])
