"""The city gazetteer builder asks only with consent and only over the operator's transport (row 132).

Before row 132 ``scripts/build_city_gazetteer.py`` sent a raw ``requests`` call to query.wikidata.org: no ``--online``, no
transport read, no kill switch, so a Tor user running it as the Map's empty state tells them to went out on clearnet. These
pin the gates in the order a run meets them, the session it sends through, and that a failed or empty run never replaces
an existing ``configs/cities.yml``.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

from tests.js_source_helper import python_function_source

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_city_gazetteer", ROOT / "scripts" / "build_city_gazetteer.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def _answer(*rows):
    return json.dumps({"head": {"vars": []}, "results": {"bindings": list(rows)}}).encode()


def _city(name, lon, lat, cc, pop):
    return {
        "cityLabel": {"value": name},
        "coord": {"value": f"Point({lon} {lat})"},
        "cc": {"value": cc},
        "population": {"value": str(pop)},
    }


PARIS = _city("Paris", 2.35, 48.86, "FR", 2100000)
PARIS_TX = _city("Paris", -95.55, 33.66, "US", 25000)
PARIS_SMALL_DUP = _city("Paris", 2.30, 48.80, "FR", 1000)


def _no_session(s):
    pytest.fail("a session was built before every gate passed")


def _gates(monkeypatch, *, transport="direct", named=True, get=None):
    monkeypatch.setattr(M, "_settings_once", lambda: "S")
    monkeypatch.setattr(M, "_transport", lambda s: transport)
    monkeypatch.setattr(M, "_direct_chosen", lambda: named)
    monkeypatch.setattr(M, "_getter", (lambda s: get) if get is not None else _no_session)


def test_without_online_it_names_the_host_and_transport_and_sends_nothing(tmp_path, monkeypatch, capsys):
    _gates(monkeypatch, transport="proxy")
    out = tmp_path / "cities.yml"
    assert M.main(["--out", str(out)]) == 2
    cap = capsys.readouterr()
    listed = {line.strip() for line in cap.out.splitlines()}
    assert {"query.wikidata.org"} <= listed and "transport: proxy" in cap.out and "--online" in cap.err
    assert not out.exists()


@pytest.mark.parametrize("kind", ["refused", "unknown"])
def test_a_refused_or_unknown_transport_stops_before_anything_is_sent(tmp_path, monkeypatch, capsys, kind):
    _gates(monkeypatch, transport=kind)
    assert M.main(["--online", "--clearnet", "--out", str(tmp_path / "c.yml")]) == 2
    assert f"transport is {kind}" in capsys.readouterr().err


def test_a_direct_transport_nobody_chose_needs_clearnet_said_out_loud(tmp_path, monkeypatch, capsys):
    _gates(monkeypatch, transport="direct", named=False)
    assert M.main(["--online", "--out", str(tmp_path / "c.yml")]) == 2
    assert "--clearnet" in capsys.readouterr().err
    _gates(monkeypatch, transport="direct", named=False, get=lambda u: _answer(PARIS))
    assert M.main(["--online", "--clearnet", "--out", str(tmp_path / "c.yml")]) == 0
    # a proxy or a pool is protected mode, which the operator chose; no --clearnet is asked for
    _gates(monkeypatch, transport="proxy", named=False, get=lambda u: _answer(PARIS))
    assert M.main(["--online", "--out", str(tmp_path / "c2.yml")]) == 0


def test_a_proxy_variable_alone_does_not_choose_direct(monkeypatch, tmp_path):
    from src.safety import settings as safety

    monkeypatch.setattr(safety, "_read_raw", lambda: None)
    monkeypatch.delenv("OO_FETCH_MODE", raising=False)
    monkeypatch.setenv("OO_HTTP_PROXY", "socks5h://127.0.0.1:9050")
    assert M._direct_chosen() is False
    monkeypatch.setenv("OO_FETCH_MODE", "transparent")
    assert M._direct_chosen() is True
    monkeypatch.delenv("OO_FETCH_MODE")
    monkeypatch.setattr(safety, "_read_raw", lambda: {"fetch_mode": "transparent"})
    assert M._direct_chosen() is True

    def boom():
        raise RuntimeError("locked")

    monkeypatch.setattr(safety, "_read_raw", boom)
    assert M._direct_chosen() is False


def test_the_session_gets_the_settings_the_transport_was_read_from(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(M, "_settings_once", lambda: "S1")
    monkeypatch.setattr(M, "_transport", lambda s: (seen.append(("transport", s)), "proxy")[1])
    monkeypatch.setattr(M, "_direct_chosen", lambda: True)
    monkeypatch.setattr(M, "_getter", lambda s: (seen.append(("session", s)), (lambda u: _answer(PARIS)))[1])
    assert M.main(["--online", "--out", str(tmp_path / "c.yml")]) == 0
    assert seen == [("transport", "S1"), ("session", "S1")]


def test_unreadable_settings_read_as_unknown():
    assert M._transport(None) == "unknown"


def test_an_online_run_asks_once_and_writes_the_most_populous_per_name_and_country(tmp_path, monkeypatch):
    asked = []
    _gates(monkeypatch, get=lambda u: (asked.append(u), _answer(PARIS, PARIS_TX, PARIS_SMALL_DUP))[1])
    out = tmp_path / "cities.yml"
    assert M.main(["--online", "--min-pop", "1000", "--out", str(out)]) == 0
    assert len(asked) == 1 and asked[0].startswith(M.WDQS_ENDPOINT + "?") and "1000" in asked[0]
    import yaml

    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    rows = sorted((c["country"], c["population"]) for c in doc["cities"])
    assert rows == [("fr", 2100000), ("us", 25000)]
    assert not list(tmp_path.glob(".cities-*")), "the temporary file is renamed, never left behind"


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    _gates(monkeypatch, get=lambda u: _answer(PARIS))
    out = tmp_path / "cities.yml"
    assert M.main(["--online", "--dry-run", "--out", str(out)]) == 0
    assert not out.exists()


@pytest.mark.parametrize(
    "body, code",
    [
        (b"<html>busy</html>", 1),
        (b"[]", 1),
        (b'{"results": []}', 1),
        (b'{"results": {"bindings": "x"}}', 1),
        (_answer(), 1),  # no city at all
        (_answer({"cityLabel": {"value": "No coord"}}), 1),
    ],
)
def test_a_bad_or_empty_answer_never_replaces_the_existing_file(tmp_path, monkeypatch, body, code):
    out = tmp_path / "cities.yml"
    out.write_text("cities: [kept]\n", encoding="utf-8")
    _gates(monkeypatch, get=lambda u: body)
    assert M.main(["--online", "--out", str(out)]) == code
    assert out.read_text(encoding="utf-8") == "cities: [kept]\n"


@pytest.mark.parametrize(
    "exc, code",
    [(M.HttpStatus(429), 2), (M.AnswerTooLarge(), 1), (KeyboardInterrupt(), 1), (OSError("airplane"), 2)],
)
def test_a_failed_request_writes_nothing_and_names_only_the_class(tmp_path, monkeypatch, capsys, exc, code):
    out = tmp_path / "cities.yml"
    out.write_text("cities: [kept]\n", encoding="utf-8")

    def get(u):
        raise exc

    _gates(monkeypatch, get=get)
    assert M.main(["--online", "--out", str(out)]) == code
    assert out.read_text(encoding="utf-8") == "cities: [kept]\n"
    assert "airplane" not in capsys.readouterr().err  # the class, never the exception's own text


def test_min_pop_below_one_is_refused(tmp_path, monkeypatch):
    _gates(monkeypatch)
    assert M.main(["--online", "--min-pop", "0", "--out", str(tmp_path / "c.yml")]) == 2


class _Resp:
    def __init__(self, status=200, chunks=(), length=None):
        self.status_code, self._chunks, self.closed = status, list(chunks), False
        self.headers = {"Content-Length": str(length)} if length is not None else {}

    def iter_content(self, n):
        yield from self._chunks

    def close(self):
        self.closed = True


def _getter_with(monkeypatch, resp, seen=None):
    from src.safety import fetcher

    class _S:
        def get(self, url, **kw):
            assert kw["stream"] is True
            return resp

    def build(settings, **kw):
        if seen is not None:
            seen.append((settings, kw))
        return _S()

    monkeypatch.setattr(fetcher, "_session_for", build)
    return M._getter("SETTINGS")


def test_the_session_is_the_apps_guarded_one_for_this_host_only(monkeypatch):
    seen = []
    ok = _Resp(chunks=[b'{"a":', b"1}"])
    assert _getter_with(monkeypatch, ok, seen)(M.query_url(1000)) == b'{"a":1}' and ok.closed
    (settings, kw), = seen
    assert settings == "SETTINGS" and kw["allowed_hosts"] == (M.WDQS_HOST,)
    with pytest.raises(ValueError):
        _getter_with(monkeypatch, ok)("https://example.org/sparql?x")


def test_the_answer_is_streamed_and_cut_at_the_cap_and_always_closed(monkeypatch):
    declared = _Resp(length=M.MAX_ANSWER_BYTES + 1)
    with pytest.raises(M.AnswerTooLarge):
        _getter_with(monkeypatch, declared)(M.query_url(1000))
    assert declared.closed
    endless = _Resp(chunks=[b"x" * 65536] * (M.MAX_ANSWER_BYTES // 65536 + 2))
    with pytest.raises(M.AnswerTooLarge):
        _getter_with(monkeypatch, endless)(M.query_url(1000))
    assert endless.closed
    bad = _Resp(status=503)
    with pytest.raises(M.HttpStatus):
        _getter_with(monkeypatch, bad)(M.query_url(1000))
    assert bad.closed


def test_no_raw_client_is_left_in_the_script():
    src = (ROOT / "scripts" / "build_city_gazetteer.py").read_text(encoding="utf-8")
    assert "import requests" not in src and "urllib.request" not in src and "requests.Session" not in src
    getter = python_function_source(src, "_getter")
    assert "_session_for(settings, user_agent=DEFAULT_USER_AGENT, allowed_hosts=(WDQS_HOST,))" in getter


def test_hostile_rows_are_skipped_one_by_one_and_the_rest_is_written(tmp_path, monkeypatch, capsys):
    bad = [
        _city("\ud800", 2.0, 48.0, "FR", 10),                     # a lone surrogate: valid JSON, unloadable YAML
        _city("Inf", 2.0, "1" + "9" * 400, "FR", 10),                # lat overflows to inf
        _city("Far", 500.0, 999.0, "FR", 10),                        # out of range
        {**_city("Huge", 2.0, 48.0, "FR", 1), "population": {"value": "1e400"}},  # overflows int()
        {**_city("Dots", 2.0, 48.0, "FR", 1), "coord": {"value": "Point(1.2.3 4)"}},
        {**_city("Odd", 2.0, 48.0, "FR", 1), "cityLabel": "not a dict"},
        _city("Code", 2.0, 48.0, "FRA", 10),                         # not an ISO alpha-2
        _city("Neg", 2.0, 48.0, "FR", -5),
        _city("x" * 500, 2.0, 48.0, "FR", 10),
    ]
    out = tmp_path / "cities.yml"
    _gates(monkeypatch, get=lambda u: _answer(PARIS, *bad, PARIS_TX))
    assert M.main(["--online", "--out", str(out)]) == 0
    from src.catalog.cities import _load_file

    loaded = _load_file(out)  # the app's own loader reads what was written
    assert sorted(c.country for c in loaded) == ["fr", "us"]
    assert "rows skipped by reason" in capsys.readouterr().err


def test_a_file_the_app_could_not_load_never_replaces_the_one_it_has(tmp_path, monkeypatch):
    out = tmp_path / "cities.yml"
    out.write_text("cities: [kept]\n", encoding="utf-8")
    import src.catalog.cities as cities

    monkeypatch.setattr(cities, "_load_file", lambda p: [])  # the read-back finds fewer rows than were written
    with pytest.raises(ValueError):
        M.write_atomic(out, [{"name": "Paris", "lat": 48.0, "lon": 2.0, "country": "fr", "population": 1}])
    assert out.read_text(encoding="utf-8") == "cities: [kept]\n"
    assert not list(tmp_path.glob(".cities-*"))


def test_an_out_that_cannot_be_written_fails_cleanly(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "a-folder"
    folder.mkdir()
    _gates(monkeypatch, get=lambda u: _answer(PARIS))
    assert M.main(["--online", "--out", str(folder)]) == 1
    assert "could not be written" in capsys.readouterr().err
    assert folder.is_dir() and not list(tmp_path.glob(".cities-*"))


def test_the_written_file_is_readable_by_others_like_the_one_it_replaces(tmp_path):
    import os
    import stat

    out = tmp_path / "cities.yml"
    M.write_atomic(out, [{"name": "Paris", "lat": 48.0, "lon": 2.0, "country": "fr", "population": 1}])
    umask = os.umask(0)
    os.umask(umask)
    assert stat.S_IMODE(out.stat().st_mode) == 0o644 & ~umask


def test_a_trickling_server_is_cut_at_the_deadline(monkeypatch):
    import threading

    class _Trickle(_Resp):
        def __init__(self):
            super().__init__()
            self._closed = threading.Event()

        def iter_content(self, n):
            yield b" "
            # the next chunk never completes: the socket keeps getting a byte under its timeout, so only closing ends it
            if not self._closed.wait(10):
                pytest.fail("nothing closed the response at the deadline")
            raise OSError("connection closed")

        def close(self):
            self.closed = True
            self._closed.set()

    monkeypatch.setattr(M, "READ_DEADLINE_S", 0.3)
    resp = _Trickle()
    with pytest.raises(M.AnswerTooLarge):
        _getter_with(monkeypatch, resp)(M.query_url(1000))
    assert resp.closed
