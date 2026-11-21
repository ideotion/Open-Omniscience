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


def test_a_download_through_the_proxy_goes_on_while_the_same_proxy_stays_set(monkeypatch):
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    w = tw.TransportWatch()
    tw.bump()
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY, discovery_external_enabled=True)  # another setting
    assert w.stop_reason() is None


def test_a_download_through_the_proxy_stops_when_the_proxy_is_changed(monkeypatch):
    """R772(b): the approved transport is the mode AND the proxy; another proxy is another transport."""
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    w = tw.TransportWatch()
    _settings(monkeypatch, fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9150")
    tw.bump()
    with pytest.raises(tw.TransportStopped) as exc:
        w.check()
    assert exc.value.reason == "proxy" and str(exc.value) == tw.PROXY_STOP
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)  # changed back: the stop stands
    assert w.stop_reason() == "proxy"


def test_the_transport_identity_never_carries_the_proxy_address(monkeypatch):
    st = _settings(monkeypatch, fetch_mode="protected", http_proxy="socks5h://user:secret@127.0.0.1:9050")
    tid = tw.transport_id(st)
    assert tid.startswith("protected:") and "secret" not in tid and "9050" not in tid and "127.0.0.1" not in tid
    other = tw.transport_id(_settings(monkeypatch, fetch_mode="protected", http_proxy="socks5h://user:other@127.0.0.1:9050"))
    assert other != tid  # the credentials are part of the proxy the user approved
    assert tw.display_token(tid) != tw.display_token(other) and tid[10:] not in tw.display_token(tid)


def test_a_proxy_start_stops_when_protected_mode_is_switched_off(monkeypatch):
    """R772: a download is bound to the mode it was approved under, in either direction."""
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    w = tw.TransportWatch()
    _settings(monkeypatch)
    tw.bump()
    assert w.stop_reason() == "unprotected"
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)  # switched back on: the stop stands
    with pytest.raises(tw.TransportStopped) as exc:
        w.check()
    assert exc.value.reason == "unprotected" and str(exc.value) == tw.UNPROTECTED_STOP
    assert "switched off" in tw.UNPROTECTED_STOP and "direct connection" in tw.UNPROTECTED_STOP


def test_switching_protected_mode_off_tells_every_watch_at_once(monkeypatch, tmp_path):
    import src.safety.settings as settings
    from src.llm import install_transport as it

    monkeypatch.setattr(settings, "_path", lambda: tmp_path / "safety_settings.json")
    monkeypatch.setattr(it, "stop_running_installs", lambda: [])
    settings.save_settings({"fetch_mode": "protected", "http_proxy": _PROXY})
    before = tw.generation()
    settings.save_settings({"http_proxy": _PROXY})  # the same transport: no change
    assert tw.generation() == before
    settings.save_settings({"http_proxy": "socks5h://127.0.0.1:9150"})  # R772(b): another proxy is another transport
    assert tw.generation() == before + 1
    settings.save_settings({"fetch_mode": "transparent"})
    assert tw.generation() == before + 2


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


def test_a_session_snapshot_taken_before_the_switch_rereads_at_its_first_check(monkeypatch):
    import src.safety.settings as settings

    monkeypatch.setattr(tw, "RECHECK_S", 60.0)
    snapshot = settings.SafetySettings()  # read direct...
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    tw.bump()  # ...and the switch is saved before the session's watch takes the generation
    w = tw.TransportWatch.for_settings(snapshot)
    assert w.stop_reason() == "protected"


def test_an_unreadable_store_stops_a_download_even_when_the_environment_names_a_proxy(monkeypatch):
    import src.safety.settings as settings
    from src.config.kv_store import KvReadError

    monkeypatch.delenv("OO_FETCH_MODE", raising=False)
    monkeypatch.setenv("OO_HTTP_PROXY", _PROXY)
    w = tw.TransportWatch(protected=False)

    def locked():
        raise KvReadError("locked")

    monkeypatch.setattr(settings, "_read_raw", locked)
    s = settings.load_settings()
    assert s.is_protected and not s.read_failed and s.store_unreadable
    assert w.stop_reason() == "unreadable"  # the R769 reason, never "protected mode was switched on"


@pytest.mark.parametrize("passing", ["unreadable", "protected"])
def test_a_long_lived_session_is_rebuilt_after_a_passing_stop(monkeypatch, passing):
    from src.safety import fetcher

    monkeypatch.setattr(fetcher, "_FOLLOWING", {})
    _settings(monkeypatch)
    s1 = fetcher.following_session("t768", "ua")
    if passing == "unreadable":
        _unreadable(monkeypatch)
    else:
        _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
        tw.bump()
    with pytest.raises(tw.TransportStopped):
        s1.transport_watch.check()
    _settings(monkeypatch)  # readable again, back to direct: the transport key is the one s1 was built under
    s2 = fetcher.following_session("t768", "ua")
    assert s2 is not s1 and s2.transport_watch.stop_reason() is None
    with pytest.raises(tw.TransportStopped):
        s1.transport_watch.check()  # the stopped one is never re-opened


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


def _stopping_resp(reason):
    class _Resp:
        status_code = 200
        headers = {"Content-Length": "12"}

        def raise_for_status(self):
            return None

        def iter_content(self, _n):
            yield b"abcd"
            raise tw.TransportStopped(reason)

    return _Resp()


def _manager(kind, tmp_path, http_get=None):
    if kind == "dump":
        from src.wiki.dumps import DumpDownloadManager

        return DumpDownloadManager(base_dir=tmp_path, http_get=http_get, max_concurrent=1)
    from src.geo.osm_downloads import OsmDownloadManager

    return OsmDownloadManager(base_dir=tmp_path, http_get=http_get, max_concurrent=1)


def _entry(kind, m, name):
    return m._entry_for(name, "pages-articles") if kind == "dump" else m._entry_for(name)


@pytest.mark.parametrize("kind", ["dump", "osm"])
@pytest.mark.parametrize(("reason", "held"), [("protected", "protected"), ("unreadable", "settings")])
def test_a_stopped_download_is_held_at_the_head_of_the_queue_with_its_partial_file(monkeypatch, tmp_path, kind, reason, held):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch)
    m = _manager(kind, tmp_path, http_get=lambda url, headers: _stopping_resp(reason))
    waiting = _entry(kind, m, "fr" if kind == "dump" else "andorra")
    waiting.status = "queued"
    m._order.append(waiting.key)
    entry = _entry(kind, m, "en" if kind == "dump" else "monaco")
    entry.status = "downloading"
    res = m._download(entry)
    assert res.status == "queued" and res.held_by == held and res.error is None and res.paused_by is None
    assert Path(res.dest).read_bytes() == b"abcd"
    assert m._order[0] == entry.key and res.to_dict()["held_by"] == held


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_the_queue_is_held_when_protected_mode_comes_on_and_resumed_only_by_the_operator(monkeypatch, tmp_path, kind):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch)
    m = _manager(kind, tmp_path)
    launched: list[str] = []

    def launch(entry):
        launched.append(entry.key)
        entry.status = "done"  # the slot frees at once, so every entry the pump may start is started

    monkeypatch.setattr(m, "_launch", launch)
    names = ("de", "fr") if kind == "dump" else ("andorra", "malta")
    busy = _entry(kind, m, "en" if kind == "dump" else "monaco")
    busy.status = "downloading"  # the slot is taken: the two below queue
    direct = [m.start(n) if kind == "osm" else m.start(n, "pages-articles") for n in names]
    assert [d["status"] for d in direct] == ["queued", "queued"]
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    tw.bump()
    late = m.start("es") if kind == "dump" else m.start("cyprus")  # queued while already protected
    keys = list(m._order)
    busy.status = "done"
    m._pump()
    assert launched == [keys[-1]]  # only the one queued under protected mode ran
    for k in keys[:-1]:
        assert m._entries[k].status == "queued" and m._entries[k].held_by == "protected"
    _settings(monkeypatch)  # switched back off: the held ones still do not start
    m._pump()
    assert launched == [keys[-1]]
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    assert m.resume_held() == 2  # the operator's ONE click, in protected mode: in queue order, one slot at a time
    m._pump()  # the next slot frees (a worker's own pump in the app)
    assert launched == [keys[-1], *keys[:-1]]
    assert late["status"] == "queued"


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_switching_protected_mode_off_holds_what_was_queued_through_the_proxy(monkeypatch, tmp_path, kind):
    """R772: nothing queued under protected mode starts over the direct connection without a click; the panel names the
    transport a resume would use BEFORE the click."""
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    m = _manager(kind, tmp_path)
    launched: list[str] = []

    def launch(entry):
        launched.append(entry.key)
        entry.status = "done"

    monkeypatch.setattr(m, "_launch", launch)
    busy = _entry(kind, m, "en" if kind == "dump" else "monaco")
    busy.status = "downloading"
    m.start("de", "pages-articles") if kind == "dump" else m.start("andorra")
    (k,) = m._order
    busy.status = "done"
    _settings(monkeypatch)  # switched off
    m._pump()
    assert launched == [] and m._entries[k].held_by == "unprotected"
    row = next(d for d in m.list() if d["key"] == k)
    assert row["held_by"] == "unprotected" and row["resume_transport"] == "direct"
    assert m.resume_held() == 1 and launched == [k]  # the operator's click in direct mode


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_changing_the_proxy_holds_what_was_queued_through_the_old_one(monkeypatch, tmp_path, kind):
    """R772(b): a proxy change while protected mode stays on holds the queue, named, until the operator's click."""
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    m = _manager(kind, tmp_path)
    launched: list[str] = []

    def launch(entry):
        launched.append(entry.key)
        entry.status = "done"

    monkeypatch.setattr(m, "_launch", launch)
    busy = _entry(kind, m, "en" if kind == "dump" else "monaco")
    busy.status = "downloading"
    m.start("de", "pages-articles") if kind == "dump" else m.start("andorra")
    (k,) = m._order
    busy.status = "done"
    _settings(monkeypatch, fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9150")
    m._pump()
    assert launched == [] and m._entries[k].held_by == "proxy"
    row = next(d for d in m.list() if d["key"] == k)
    assert row["held_by"] == "proxy" and row["resume_transport"] == "proxy"
    assert row["resume_token"] == tw.display_token() and "9150" not in json.dumps(row)
    assert m.resume_held() == 1 and launched == [k]  # the operator's click, under the proxy now set


def test_a_launch_decided_through_one_proxy_stops_if_another_is_set_before_its_session(monkeypatch):
    from src.safety.fetcher import _session_for

    first = _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    decided = tw.transport_id(first)
    st = _settings(monkeypatch, fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9150")
    with tw.run(tw.for_launch(decided)), pytest.raises(tw.TransportStopped) as exc:
        _session_for(st).get("https://dumps.example.org/big")  # refused before anything is sent
    assert exc.value.reason == "proxy"


def test_a_launch_decided_through_the_proxy_stops_if_the_switch_off_lands_first(monkeypatch):
    from src.safety.fetcher import _session_for

    st = _settings(monkeypatch)  # switched off between the pump's reading and the session
    with tw.run(tw.for_launch("protected")), pytest.raises(tw.TransportStopped) as exc:
        _session_for(st).get("https://dumps.example.org/big")
    assert exc.value.reason == "unprotected"


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_unreadable_settings_hold_even_a_download_queued_under_protected_mode(monkeypatch, tmp_path, kind):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    m = _manager(kind, tmp_path)
    monkeypatch.setattr(m, "_launch", lambda e: pytest.fail("started while the settings could not be read"))
    busy = _entry(kind, m, "en" if kind == "dump" else "monaco")
    busy.status = "downloading"
    m.start("de", "pages-articles") if kind == "dump" else m.start("andorra")
    busy.status = "done"
    _unreadable(monkeypatch)
    m._pump()
    (k,) = m._order
    assert m._entries[k].held_by == "settings"
    assert m.resume_held() == 1 and m._entries[k].held_by == "settings"  # resumed into the same reason: nothing is sent


def test_a_launch_decided_direct_stops_if_the_switch_lands_before_its_session_is_built(monkeypatch):
    from src.safety.fetcher import _session_for
    from src.safety.settings import SafetySettings

    st = _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)  # saved between the pump's reading and the session
    with tw.run(tw.for_launch("direct")):
        s = _session_for(st)
        with pytest.raises(tw.TransportStopped) as exc:
            s.get("https://dumps.example.org/big")  # refused before anything is sent
    assert exc.value.reason == "protected"
    with tw.run(tw.for_launch("protected")):
        assert _session_for(st).transport_watch.stop_reason() is None  # decided protected: it goes on
    assert _session_for(SafetySettings()).transport_watch is not None and tw.current_run() is None


def test_every_segment_of_a_segmented_file_shares_the_runs_one_watch():
    import hashlib

    from src.ingest.segmented_download import segmented_fetch

    seen: list[object] = []
    body = b"x" * 4096

    def fetch_segment(url, start, end):
        seen.append(tw.current_run())
        return body[start:end]

    w = tw.TransportWatch(protected=False)
    with tw.run(w):
        segmented_fetch(
            "https://dumps.example.org/f", total_bytes=len(body), expected_sha256=hashlib.sha256(body).hexdigest(),
            fetch_segment=fetch_segment, n_segments=4, min_seg=1024,
        )
    assert len(seen) == 4 and all(x is w for x in seen)


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_downloads_stopped_together_requeue_in_the_order_they_ran(monkeypatch, tmp_path, kind):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch)
    m = _manager(kind, tmp_path, http_get=lambda url, headers: _stopping_resp("protected"))
    waiting = _entry(kind, m, "fr" if kind == "dump" else "andorra")
    waiting.status = "queued"
    m._order.append(waiting.key)
    first = _entry(kind, m, "en" if kind == "dump" else "monaco")
    second = _entry(kind, m, "de" if kind == "dump" else "malta")
    first._launch_seq, second._launch_seq = 1, 2
    m._download(second)  # the later one's worker reaches the stop first
    m._download(first)
    assert m._order == [first.key, second.key, waiting.key]


def test_the_queue_shows_why_and_one_control_resumes_it(monkeypatch):
    from fastapi import HTTPException

    from src.api import jobs

    calls: list[str] = []
    stamped: list[str | None] = []

    class _M:
        def __init__(self, name):
            self.name = name

        def resume_held(self, mode=None):
            calls.append(self.name)
            stamped.append(mode)
            return 1

    import src.geo.osm_downloads as osm
    import src.ingest as ingest
    import src.wiki.dumps as dumps

    monkeypatch.setattr(dumps, "get_manager", lambda: _M("dumps"))
    monkeypatch.setattr(osm, "get_manager", lambda: _M("osm"))
    monkeypatch.setattr(ingest, "kill_switch_active", lambda: False)
    _settings(monkeypatch)
    for body in (None, jobs.ResumeQueueBody(transport=""), jobs.ResumeQueueBody(transport="0" * 16)):
        with pytest.raises(HTTPException) as exc:
            jobs.resume_held_queue(body)
        assert exc.value.status_code == 409 and exc.value.detail == jobs.TRANSPORT_CHANGED
    assert calls == []
    token = tw.display_token()
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)  # changed after the page named the direct connection
    with pytest.raises(HTTPException):
        jobs.resume_held_queue(jobs.ResumeQueueBody(transport=token))
    assert calls == []
    assert jobs.resume_held_queue(jobs.ResumeQueueBody(transport=tw.display_token())) == {"resumed": 2}
    assert calls == ["dumps", "osm"] and stamped == [tw.mode_now()] * 2
    src = (_ROOT / "src" / "api" / "jobs.py").read_text(encoding="utf-8")
    assert src.count('"held_by": e.get("held_by")') == 2


def test_an_osm_catch_up_run_is_one_download_and_stops_between_files(monkeypatch, tmp_path):
    from src.osm import replication as rep
    from src.safety import fetcher

    _settings(monkeypatch)
    sent: list[str] = []

    class _S:
        transport_watch = None

        def get(self, url, **kw):
            self.transport_watch.check()
            sent.append(url)
            raise AssertionError("unreached")

    def fake_guarded_session(**kw):
        s = _S()
        s.transport_watch = tw.TransportWatch()
        return s

    monkeypatch.setattr(fetcher, "guarded_session", fake_guarded_session)
    src_ = rep.GuardedDiffSource("monaco")
    first = src_._session("https://download.geofabrik.de/a")
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    tw.bump()
    second = src_._session("https://download.geofabrik.de/b")  # built under protected mode, but the run started direct
    assert second.transport_watch is first.transport_watch
    with pytest.raises(rep.DiffRefused) as exc:
        src_.fetch_diff(2, tmp_path / "2.osc.gz")
    assert str(exc.value) == tw.PROTECTED_STOP and sent == []


def test_an_update_check_stopped_mid_request_is_a_named_409(monkeypatch):
    from fastapi import HTTPException

    from src.api import system
    from src.maintenance import self_update

    def stopped():
        raise tw.TransportStopped("unreadable")

    monkeypatch.setattr(self_update, "check", stopped)
    with pytest.raises(HTTPException) as exc:
        system.update_check()
    assert exc.value.status_code == 409 and exc.value.detail == {"code": "transport_stopped", "message": tw.UNREADABLE_STOP}


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
        "Held because protected mode was switched on: this download had started, or was queued, over a direct connection. "
        "Resume the queue to download it through your proxy."
    )
    pause_s = (
        "Held because the safety settings could not be read: nothing is sent until they can be read again. Resume the queue once "
        "they can be read."
    )
    for name in ("app-core.js", "taskmanager.js", "app-map.js"):
        js = (_ROOT / "src" / "static" / name).read_text(encoding="utf-8")
        assert "held_by" in js and "Resume the queue" in js, name
        assert pause_p in js and pause_s in js, name
    assert "/api/jobs/queue/resume" in (_ROOT / "src" / "static" / "app-core.js").read_text(encoding="utf-8")
    med = (_ROOT / "src" / "static" / "app-medical.js").read_text(encoding="utf-8")
    assert '"protected_mode"' in med and '"settings_unreadable"' in med and '"proxy_changed"' in med
    from src.api.jobs import TRANSPORT_CHANGED
    from src.llm import install_transport as it

    keys = [
        pause_p, pause_s, "Held: protected mode was switched on", "Held: the settings could not be read", "Resume the queue",
        "Held: protected mode was switched off", "Resume the queue through your proxy", "Resume the queue over the direct connection",
        "Held because protected mode was switched off: this download had started, or was queued, through your proxy. It does not go "
        "on over the direct connection until you resume the queue.", tw.UNPROTECTED_STOP,
        "Resume every held download, in queue order, through the transport now in force.",
        tw.PROTECTED_STOP, tw.UNREADABLE_STOP, tw.PROXY_STOP, "Held: the proxy was changed",
        "Held because the proxy was changed: this download had started, or was queued, through another proxy. Resume the queue to "
        "download it through the proxy now set.", TRANSPORT_CHANGED,
        "Held because the app cannot confirm the transport this download was queued under: it was queued before the app was "
        "restarted or updated. Resume the queue to download it through the transport now in force.",
        "Held: queued before a restart", "Held: the transport changed. Resume the queue in the task manager.", it.AI_INSTALL_UNREADABLE_NOTE, it.AI_INSTALLER_UNREADABLE_NOTE,
    ]
    for lang in ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        data = json.loads((_ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
        for key in keys:
            assert data.get(key), (lang, key[:40])


# --------------------------------------------------------------------------- the second reads (R772(b))


def _no_switch():
    return False


def test_the_daily_map_update_queue_is_held_by_a_transport_change_and_resumed_only_by_the_click(monkeypatch):
    """R768/R772 for the OSM daily-update queue: a country queued under one transport never starts under another unasked."""
    import types

    from src.osm import update_job as U

    U._reset_for_tests()
    started, release = [], threading.Event()

    def runner(alpha3, **kw):
        started.append(alpha3)
        if alpha3 == "ZZZ":
            release.wait(10)
        return types.SimpleNamespace(outcome="current", reason="x", from_sequence=1, to_sequence=1, owed_remaining=None)

    _settings(monkeypatch)
    try:
        U.request_update("ZZ", consent=True, kill_switch=_no_switch, run=runner)
        deadline = time.monotonic() + 5
        while started != ["ZZZ"] and time.monotonic() < deadline:
            time.sleep(0.01)
        U.request_update("FR", consent=True, kill_switch=_no_switch, run=runner)  # queued over the direct connection
        _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    finally:
        release.set()
    assert U.wait_idle(5) and started == ["ZZZ"]
    (fra,) = [j for j in U.jobs() if j["alpha3"] == "FRA"]
    assert fra["state"] == "queued" and fra["held_by"] == "protected" and "_queued_mode" not in fra
    from src.api.jobs import _osm_update_jobs

    (row,) = [r for r in _osm_update_jobs() if r["id"] == "osm-update:FRA"]
    assert row["held_by"] == "protected" and row["resume_transport"] == "proxy" and row["resume_token"] == tw.display_token()
    assert U.resume_held(tw.mode_now()) == 1
    assert U.wait_idle(5) and started == ["ZZZ", "FRA"]
    U._reset_for_tests()


def test_a_daily_update_stopped_by_a_transport_change_goes_back_to_the_head_held(monkeypatch):
    from src.osm import update_job as U

    U._reset_for_tests()

    def runner(alpha3, **kw):
        tw.current_run().bind_transport(tw.DIRECT)  # the run was approved through the proxy; protected mode went off
        raise RuntimeError("stopped")

    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    U.request_update("FR", consent=True, kill_switch=_no_switch, run=runner)
    assert U.wait_idle(5)
    (fra,) = U.jobs()
    assert fra["state"] == "queued" and fra["held_by"] == "unprotected"
    U._reset_for_tests()


def test_a_medical_run_is_bound_to_the_transport_of_the_consented_click(monkeypatch):
    """The corpus scan runs before the first request: a change during it stops the run, named, before anything is sent."""
    import src.medical.fetch as F
    from src.api import medical

    seen: list[str | None] = []

    def fake_run_fetch(files, **kw):
        seen.append(tw.current_run().stop_reason())
        return {"listed": None}

    monkeypatch.setattr(F, "run_fetch", fake_run_fetch)
    _settings(monkeypatch, fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9150")  # changed after the click
    ctx = types_ns(stopping=False, set_progress=lambda **kw: None)
    medical._fetch_worker(ctx, files=1, mode=tw.transport_id(_settings_obj(fetch_mode="protected", http_proxy=_PROXY)))
    assert seen == ["proxy"]
    src = (_ROOT / "src" / "api" / "medical.py").read_text(encoding="utf-8")
    assert "_FETCH_JOB.start(files=files, mode=mode_now())" in src


def types_ns(**kw):
    import types

    return types.SimpleNamespace(**kw)


def _settings_obj(**kw):
    from src.safety.settings import SafetySettings

    return SafetySettings(**kw)


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_the_state_file_and_the_page_never_hold_the_transport_identity(monkeypatch, tmp_path, kind):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    m = _manager(kind, tmp_path)
    monkeypatch.setattr(m, "_launch", lambda e: None)
    busy = _entry(kind, m, "en" if kind == "dump" else "monaco")
    busy.status = "downloading"
    row = m.start("de", "pages-articles") if kind == "dump" else m.start("andorra")
    assert "queued_mode" not in row and all("queued_mode" not in d for d in m.list())
    (k,) = m._order
    assert m._entries[k].queued_mode.startswith("protected:")
    m._save()
    stored = json.loads(m.state_path.read_text(encoding="utf-8"))["entries"][k]
    assert stored["queued_mode"] == "protected"  # the kind only: no digest of the proxy at rest
    assert tw.transport_id(_settings_obj(fetch_mode="protected", http_proxy=_PROXY))[10:] not in m.state_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["dump", "osm"])
@pytest.mark.parametrize(("stored", "now", "held"), [
    ("protected", "protected", "unverified"),  # queued through a proxy before a restart: which one cannot be confirmed
    ("protected", "direct", "unprotected"),
    (None, "direct", "unverified"),  # queued by a build that recorded no transport
    (None, "protected", "unverified"),
    ("direct", "protected", "protected"),
    ("direct", "direct", None),
])
def test_after_a_restart_a_queue_entry_starts_only_when_its_transport_is_certain(monkeypatch, tmp_path, kind, stored, now, held):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    if now == "protected":
        _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    else:
        _settings(monkeypatch)
    m = _manager(kind, tmp_path)
    launched: list[str] = []
    monkeypatch.setattr(m, "_launch", lambda e: launched.append(e.key))
    e = _entry(kind, m, "de" if kind == "dump" else "andorra")
    e.status, e.queued_mode = "queued", stored
    m._order.append(e.key)
    m._pump()
    assert m._entries[e.key].held_by == held and launched == ([] if held else [e.key])


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_a_download_click_on_a_held_entry_leaves_it_held(monkeypatch, tmp_path, kind):
    """Only "Resume the queue", whose button names the transport and whose click carries its token, lifts a hold."""
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    m = _manager(kind, tmp_path)
    monkeypatch.setattr(m, "_launch", lambda e: pytest.fail("a held entry started without the token click"))
    e = _entry(kind, m, "de" if kind == "dump" else "andorra")
    e.status, e.held_by, e.queued_mode = "queued", "protected", tw.DIRECT
    m._order.append(e.key)
    row = m.start("de", "pages-articles") if kind == "dump" else m.start("andorra")
    assert row["status"] == "queued" and row["held_by"] == "protected"
    assert m.resume(e.key)["held_by"] == "protected"


def test_the_pool_order_is_part_of_the_transport_and_an_unused_single_proxy_is_not(monkeypatch):
    a, b = "socks5h://127.0.0.1:9050", "socks5h://127.0.0.1:9150"
    ab = tw.transport_id(_settings_obj(fetch_mode="protected", http_proxies=[a, b]))
    assert ab != tw.transport_id(_settings_obj(fetch_mode="protected", http_proxies=[b, a]))  # each host is sharded by the order
    assert ab == tw.transport_id(_settings_obj(fetch_mode="protected", http_proxies=[a, b], http_proxy=b))
    assert tw.transport_id(_settings_obj(fetch_mode="protected", http_proxy=a)) != tw.transport_id(
        _settings_obj(fetch_mode="protected", http_proxy=b))


def test_a_stop_while_reading_the_replication_state_is_named(monkeypatch):
    from src.osm import replication as rep

    class _Resp:
        status_code = 200

        @property
        def text(self):
            raise tw.TransportStopped("unreadable")

        def close(self):
            pass

    src = rep.GuardedDiffSource("europe", session_factory=lambda url: None)
    monkeypatch.setattr(src, "_get", lambda url: _Resp())
    with pytest.raises(rep.DiffRefused) as exc:
        src.fetch_state()
    assert str(exc.value) == tw.UNREADABLE_STOP


def test_a_token_that_is_not_ascii_is_refused_by_name_not_a_crash(monkeypatch):
    from fastapi import HTTPException

    import src.ingest as ingest
    from src.api import jobs

    monkeypatch.setattr(ingest, "kill_switch_active", lambda: False)
    _settings(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        jobs.resume_held_queue(jobs.ResumeQueueBody(transport="é" * 16))
    assert exc.value.status_code == 409 and exc.value.detail == jobs.TRANSPORT_CHANGED


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_cancel_then_resume_puts_a_held_download_back_in_the_queue_still_held(monkeypatch, tmp_path, kind):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    m = _manager(kind, tmp_path)
    monkeypatch.setattr(m, "_launch", lambda e: pytest.fail("a held entry started without the token click"))
    e = _entry(kind, m, "de" if kind == "dump" else "andorra")
    e.status, e.held_by, e.queued_mode = "queued", "proxy", tw.DIRECT
    m._order.append(e.key)
    assert m.pause(e.key) and m._entries[e.key].status == "paused"
    row = m.resume(e.key)
    assert row["status"] == "queued" and row["held_by"] == "proxy" and e.key in m._order


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_a_paused_download_resumed_under_another_transport_is_held_not_continued(monkeypatch, tmp_path, kind):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    approved = tw.mode_now()
    m = _manager(kind, tmp_path)
    launched: list[str] = []
    monkeypatch.setattr(m, "_launch", lambda e: launched.append(e.key))
    e = _entry(kind, m, "de" if kind == "dump" else "andorra")
    e.status, e.paused_by, e.queued_mode = "paused", "operator", approved
    _settings(monkeypatch, fetch_mode="protected", http_proxy="socks5h://127.0.0.1:9150")
    row = m.resume(e.key)
    assert row["status"] == "queued" and row["held_by"] == "proxy" and launched == []
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)  # the approved transport again: it simply goes on
    e.status, e.held_by = "paused", None
    m.resume(e.key)
    assert launched == [e.key]


@pytest.mark.parametrize("kind", ["dump", "osm"])
def test_a_first_click_records_the_transport_even_when_a_slot_is_free(monkeypatch, tmp_path, kind):
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    _settings(monkeypatch, fetch_mode="protected", http_proxy=_PROXY)
    m = _manager(kind, tmp_path)
    monkeypatch.setattr(m, "_launch", lambda e: None)
    row = m.start("de", "pages-articles") if kind == "dump" else m.start("andorra")
    assert row["status"] == "downloading" and m._entries[row["key"]].queued_mode == tw.mode_now()


@pytest.mark.parametrize("kind", ["dump", "osm"])
@pytest.mark.parametrize(("stored", "held"), [("protected", "unverified"), (None, "unverified"), ("unknown", "settings"), ("direct", None)])
def test_a_queue_read_back_after_a_restart_shows_what_it_cannot_confirm_as_held(monkeypatch, tmp_path, kind, stored, held):
    """No pump runs at boot, and none is needed: the hold is set by the read itself, with no settings read and nothing fetched."""
    m = _manager(kind, tmp_path)
    e = _entry(kind, m, "de" if kind == "dump" else "andorra")
    e.status, e.queued_mode = "queued", stored
    m._order.append(e.key)
    m._save()
    import src.safety.settings as settings

    monkeypatch.setattr(settings, "load_settings", lambda: pytest.fail("the read of a state file reads no settings"))
    again = _manager(kind, tmp_path)
    assert again._entries[e.key].held_by == held

