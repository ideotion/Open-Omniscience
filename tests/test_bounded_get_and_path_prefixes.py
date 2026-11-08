"""Hardening of the climate fetchers' transport (R572): a body read that STOPS at the bound, and a session that talks only to
its own DIRECTORIES on a multi-tenant host. Negative-space tests: each refusal has a case that would pass if the guard were absent."""

from __future__ import annotations

import contextlib
import io

import pytest
import requests

from src.safety import fetcher
from src.safety.fetcher import RedirectRefused, _checked_path_prefixes, refuse_unlisted_path
from src.stats import fetch

OWID = ("/owid/co2-data/", "/owid/energy-data/")


# --- path prefixes -----------------------------------------------------------------------------------------------------------------------


def test_a_listed_directory_passes_and_every_other_repository_is_refused():
    refuse_unlisted_path("https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv?x=1", OWID)
    refuse_unlisted_path("https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv", OWID)
    for bad in (
        "https://raw.githubusercontent.com/evil/repo/master/a.csv",
        "https://raw.githubusercontent.com/owid/other-data/master/a.csv",
        "https://raw.githubusercontent.com/owid/co2-datax/master/a.csv",  # the prefix ends with a slash: a longer name is another repository
        "https://raw.githubusercontent.com/owid/co2-data",  # the directory itself, no trailing slash
        "https://raw.githubusercontent.com/",
    ):
        with pytest.raises(RedirectRefused):
            refuse_unlisted_path(bad, OWID)


@pytest.mark.parametrize(
    "bad",
    [
        "https://raw.githubusercontent.com/owid/co2-data/../../evil/repo/a.csv",
        "https://raw.githubusercontent.com/owid/co2-data/%2e%2e/%2e%2e/evil/a.csv",
        "https://raw.githubusercontent.com/owid/co2-data/%2E%2E/x",
        "https://raw.githubusercontent.com/owid/co2-data/a%2fb",
        "https://raw.githubusercontent.com/owid/co2-data\\..\\evil",
    ],
)
def test_dot_segments_escapes_and_backslashes_are_refused_not_normalised(bad):
    with pytest.raises(RedirectRefused):
        refuse_unlisted_path(bad, OWID)


def test_a_malformed_prefix_list_is_a_programming_error():
    assert _checked_path_prefixes(None) is None
    assert _checked_path_prefixes(["/a/", "/a/b/"]) == ("/a/", "/a/b/")
    for bad in (["a/"], ["/a"], ["/a/../"], ["/a//b/"], ["/a%2f/"], ["/a\\b/"], ["/./"], ["//"]):
        with pytest.raises(ValueError):
            _checked_path_prefixes(bad)
    with pytest.raises(ValueError):
        _checked_path_prefixes([])
    with pytest.raises(TypeError):
        _checked_path_prefixes("/owid/")


def test_the_session_checks_the_path_of_the_first_request_and_of_every_redirect_hop(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(requests.Session, "send", lambda self, request, **kw: sent.append(request.url) or requests.Response())
    session = fetcher.guarded_session(allowed_hosts=("raw.githubusercontent.com",), allowed_path_prefixes=OWID)
    ok = requests.Request("GET", "https://raw.githubusercontent.com/owid/co2-data/master/f.csv").prepare()
    session.send(ok)
    assert sent == [ok.url]
    hop = requests.Request("GET", "https://raw.githubusercontent.com/evil/repo/master/f.csv").prepare()
    with pytest.raises(RedirectRefused):
        session.send(hop)
    assert sent == [ok.url], "a refused hop must never be sent"


def test_a_session_without_a_path_list_follows_none(monkeypatch):
    monkeypatch.setattr(requests.Session, "send", lambda self, request, **kw: requests.Response())
    session = fetcher.guarded_session(allowed_hosts=("raw.githubusercontent.com",))
    assert session.allowed_path_prefixes is None
    session.send(requests.Request("GET", "https://raw.githubusercontent.com/any/repo/x").prepare())


def test_the_three_climate_fetchers_pin_their_directories():
    assert fetch.GISTEMP_PATHS == ("/gistemp/tabledata_v4/",)
    assert fetch.OWID_PATHS == ("/owid/co2-data/", "/owid/energy-data/")
    assert fetch.USGS_PATHS == ("/fdsnws/event/1/",)
    # every URL a fetcher builds lies under its own list
    refuse_unlisted_path(fetch.gistemp_url("GLB"), fetch.GISTEMP_PATHS)
    refuse_unlisted_path(fetch.owid_dataset_url("co2"), fetch.OWID_PATHS)
    refuse_unlisted_path(fetch.owid_dataset_url("energy"), fetch.OWID_PATHS)
    refuse_unlisted_path(fetch.usgs_quakes_count_url("2020-01", "2020-03", 5.0), fetch.USGS_PATHS)
    refuse_unlisted_path(fetch.usgs_quakes_query_url("2020-01", "2020-03", 5.0), fetch.USGS_PATHS)


# --- the bounded read ---------------------------------------------------------------------------------------------------------------------


class _Raw:
    """A body that counts how much of it the reader pulled."""

    def __init__(self, data: bytes | None, *, endless: bytes = b""):
        self._buf = io.BytesIO(data) if data is not None else None
        self._endless = endless
        self.pulled = 0

    def read(self, n=-1, *_a, **_k):
        out = self._buf.read(n) if self._buf is not None else self._endless[:n]
        self.pulled += len(out)
        return out

    def close(self):
        pass


def _response(url, raw, headers=None, status=200):
    r = requests.Response()
    r.status_code = status
    r.raw = raw
    r.url = url
    r.headers.update(headers or {})
    r.encoding = "utf-8"
    return r


def _session(raw, headers=None, status=200):
    class Session:
        max_redirects = 30

        def get(self, url, **kw):
            return _response(url, raw, headers, status)

    return Session()


def _routes(table):
    """A fake session answering each URL from ``table``: url -> (raw, headers, status)."""

    class Session:
        max_redirects = 30
        asked: list[str] = []

        def get(self, url, **kw):
            assert kw.get("allow_redirects") is False, "redirects are followed by hand, never by requests"
            Session.asked.append(url)
            raw, headers, status = table[url]
            return _response(url, raw, headers, status)

    return Session()


def _get(session, max_chars):
    return fetch._bounded_get(session, "https://h/p/x", max_chars=max_chars)


def test_a_body_inside_the_bound_comes_back_whole_and_readable():
    body = b"Year,Jan\n1880,-0.2\n"
    resp = _get(_session(_Raw(body)), 100)
    assert resp.text == body.decode() and resp.content == body
    resp.raise_for_status()


def test_an_endless_body_is_abandoned_at_the_bound_not_read_to_the_end():
    raw = _Raw(None, endless=b"x" * 65536)
    with pytest.raises(fetch.BodyTooLarge) as exc:
        _get(_session(raw), 1000)
    assert "https://" not in str(exc.value), "the message names sizes, never the URL"
    assert raw.pulled <= 4000 + 65536, "reading stopped within one chunk of the bound"


def test_a_declared_content_length_over_the_bound_refuses_before_reading():
    raw = _Raw(b"x" * 10)
    with pytest.raises(fetch.BodyTooLarge):
        _get(_session(raw, headers={"Content-Length": "999999999"}), 1000)
    assert raw.pulled == 0


def test_exactly_at_the_byte_bound_passes_and_one_byte_over_is_refused():
    assert len(_get(_session(_Raw(b"x" * 4000)), 1000).content) == 4000
    with pytest.raises(fetch.BodyTooLarge):
        _get(_session(_Raw(b"x" * 4001)), 1000)


def test_an_error_status_is_not_read_at_all_and_still_raises_for_status():
    raw = _Raw(b"x" * 500)
    resp = _get(_session(raw, status=503), 100)
    assert raw.pulled == 0
    with pytest.raises(requests.HTTPError):
        resp.raise_for_status()


def test_a_redirect_body_is_never_read_and_the_hop_is_followed_by_hand():
    big = _Raw(None, endless=b"x" * 65536)
    final = _Raw(b"ok")
    session = _routes(
        {
            "https://h/p/x": (big, {"Location": "/p/y"}, 302),
            "https://h/p/y": (final, {}, 200),
        }
    )
    resp = _get(session, 100)
    assert resp.text == "ok" and big.pulled == 0, "the redirect's body is closed unread"
    assert session.asked == ["https://h/p/x", "https://h/p/y"]


def test_a_redirect_loop_stops_at_the_sessions_own_limit():
    session = _routes({"https://h/p/x": (_Raw(b""), {"Location": "/p/x"}, 302)})
    session.max_redirects = 3
    with pytest.raises(RedirectRefused):
        _get(session, 100)
    assert len(session.asked) == 4  # the first request plus three hops


def test_a_redirect_hop_to_another_directory_is_refused_by_the_real_session_and_never_sent(monkeypatch):
    sent: list[str] = []

    def fake_send(self, request, **kw):
        sent.append(request.url)
        if request.url.endswith("/owid/co2-data/master/f.csv"):
            return _response(request.url, _Raw(b""), {"Location": "/evil/repo/master/f.csv"}, 302)
        return _response(request.url, _Raw(b"pwned"))

    monkeypatch.setattr(requests.Session, "send", fake_send)
    session = fetcher.guarded_session(allowed_hosts=("raw.githubusercontent.com",), allowed_path_prefixes=OWID)
    with pytest.raises(RedirectRefused):
        fetch._bounded_get(session, "https://raw.githubusercontent.com/owid/co2-data/master/f.csv", max_chars=100)
    assert sent == ["https://raw.githubusercontent.com/owid/co2-data/master/f.csv"]


def test_a_control_character_in_the_url_is_refused_not_normalised_away():
    for bad in (
        "https://raw.githubusercontent.com/owid/co2-data/..\t/../evil",
        "https://raw.githubusercontent.com/owid/co2-data/a b",
        "https://raw.githubusercontent.com/owid/co2-data/a\nb",
        "https://raw.githubusercontent.com/owid/co2-data/a\x7fb",
    ):
        with pytest.raises(RedirectRefused):
            refuse_unlisted_path(bad, OWID)


def test_the_default_getters_build_their_session_with_their_own_lists_and_scale(monkeypatch):
    built: list[dict] = []
    bounded: list[int] = []

    def factory(**kw):
        built.append(kw)
        return "session"

    monkeypatch.setattr(fetch, "guarded_session", factory)
    monkeypatch.setattr(fetch, "_bounded_get", lambda session, url, *, max_chars: bounded.append(max_chars))
    fetch._gistemp_getter("u1")
    fetch._owid_bulk_getter("u2")
    fetch._usgs_getter(777)("u3")
    assert [(b["allowed_hosts"], b["allowed_path_prefixes"]) for b in built] == [
        (fetch.GISTEMP_HOSTS, fetch.GISTEMP_PATHS),
        (fetch.OWID_HOSTS, fetch.OWID_PATHS),
        (fetch.USGS_HOSTS, fetch.USGS_PATHS),
    ]
    assert bounded == [fetch.gistemp_max_chars(), fetch.owid_max_chars(), 777]


def test_usgs_reads_the_count_under_a_tiny_bound_and_the_events_under_the_counted_bound(monkeypatch):
    caps: list[int] = []

    def factory(max_chars):
        caps.append(max_chars)

        class R:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                pass

        return lambda url: R("0\n" if len(caps) == 1 else "time,mag,type,id,status\n")

    monkeypatch.setattr(fetch, "_usgs_getter", factory)
    with contextlib.suppress(ValueError):  # what the parse makes of an empty catalogue is not under test; the two caps are
        fetch.fetch_usgs_quakes("2020-01", "2020-01", 5.0)
    assert caps == [fetch._USGS_COUNT_MAX_CHARS, fetch.USGS_QUAKES_HEADER_ALLOWANCE]


# --- the same, on a REAL GuardedSession with a mounted transport (a stubbed ``send`` would hide ``resolve_redirects``) -------------------


class _Adapter(requests.adapters.BaseAdapter):
    def __init__(self, table):
        super().__init__()
        self.table = table
        self.asked: list[str] = []

    def send(self, request, **kw):
        self.asked.append(request.url)
        raw, headers, status = self.table[request.url]
        return _response(request.url, raw, headers, status)

    def close(self):
        pass


def _real(table, **kw):
    session = fetcher.guarded_session(allowed_hosts=("raw.githubusercontent.com",), allowed_path_prefixes=OWID, **kw)
    adapter = _Adapter(table)
    session.mount("https://", adapter)
    return session, adapter


BASE = "https://raw.githubusercontent.com/owid/co2-data/master/"


def test_on_a_real_session_a_redirect_body_is_never_pulled():
    big = _Raw(None, endless=b"x" * 65536)
    session, adapter = _real({BASE + "a.csv": (big, {"Location": "b.csv"}, 302), BASE + "b.csv": (_Raw(b"ok"), {}, 200)})
    resp = fetch._bounded_get(session, BASE + "a.csv", max_chars=100)
    assert resp.text == "ok" and adapter.asked == [BASE + "a.csv", BASE + "b.csv"]
    assert big.pulled == 0, "requests' own resolve_redirects must not read the 3xx body"


def test_on_a_real_session_a_non_ascii_location_is_a_refusal_not_a_decode_error():
    session, _ = _real({BASE + "a.csv": (_Raw(b""), {"Location": "/owid/co2-data/\u00e9"}, 302)})
    with pytest.raises(RedirectRefused):
        fetch._bounded_get(session, BASE + "a.csv", max_chars=100)


def test_on_a_real_session_zero_redirects_allowed_is_our_refusal_not_a_requests_exception():
    session, adapter = _real({BASE + "a.csv": (_Raw(b""), {"Location": "b.csv"}, 302)})
    session.max_redirects = 0
    with pytest.raises(RedirectRefused):
        fetch._bounded_get(session, BASE + "a.csv", max_chars=100)
    assert adapter.asked == [BASE + "a.csv"]


def test_on_a_real_session_the_kill_switch_stops_the_second_hop():
    from src.ingest import activate_kill_switch, clear_kill_switch

    calls: list[str] = []
    table = {BASE + "a.csv": (_Raw(b""), {"Location": "b.csv"}, 302), BASE + "b.csv": (_Raw(b"ok"), {}, 200)}
    session, adapter = _real(table)
    original = adapter.send

    def send(request, **kw):
        calls.append(request.url)
        out = original(request, **kw)
        activate_kill_switch()  # airplane mode is engaged between the hops
        return out

    adapter.send = send
    try:
        with pytest.raises(Exception, match="(?i)airplane|kill|network|offline|blocked"):
            fetch._bounded_get(session, BASE + "a.csv", max_chars=100)
    finally:
        clear_kill_switch()
    assert calls == [BASE + "a.csv"], "the second hop was never sent"
