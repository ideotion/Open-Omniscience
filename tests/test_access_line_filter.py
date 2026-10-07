"""The server's access line names the route template and a standard method, with no query (2026-10-07).

A passphrase typed into the address bar is a path, and the access line is a log the app cannot keep out of journald, ``docker
logs`` or a launcher's redirect. ``AccessLineFilter`` is attached to the ``uvicorn.access`` logger by the app itself, so it holds
however the server is started.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
import logging

import pytest

from src.utils import access_log

MARK = "zq-typed-in-the-bar-77"


@pytest.fixture
def written():
    """What a console handler on the real ``uvicorn.access`` logger writes, formatted by the app's own access formatter."""
    from src.api import main  # noqa: F401 - importing the app is what installs the filter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(access_log.AccessFormatter('%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    log = logging.getLogger("uvicorn.access")
    old_level, old_prop = log.level, log.propagate
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(handler)
    try:
        yield stream
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
        log.propagate = old_prop


def _serve_line(method, full_path, status=404):
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", method, full_path, "1.1", status)


def test_the_app_attaches_the_filter_to_the_access_logger_itself():
    """MUTATION TARGET: the install taken out of ``src/api/main.py`` (a server started by the uvicorn command line never goes
    through ``_serve`` or ``uvicorn_log_config``, and imports the app)."""
    from src.api import main  # noqa: F401

    filters = [f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, access_log.AccessLineFilter)]
    assert len(filters) == 1
    before = len(logging.getLogger("uvicorn.access").filters)
    assert access_log.install_access_line_filter() is filters[0], "a second call returns the one filter"
    assert len(logging.getLogger("uvicorn.access").filters) == before, "and adds none"


def test_an_unmatched_path_and_its_query_never_reach_the_line(written):
    """MUTATION TARGET: the filter taken off, or the path or the query passed through again."""
    _serve_line("GET", f"/api/{MARK}?token={MARK}&x=1")
    line = written.getvalue()
    assert MARK not in line and "token" not in line and "?" not in line, line
    assert 'GET (no route matched) HTTP/1.1" 404' in line and "127.0.0.1:5000" in line


def test_a_method_the_client_made_up_is_written_as_a_fixed_word(written):
    _serve_line(MARK.upper(), "/api/health")
    line = written.getvalue()
    assert MARK.upper() not in line and "(other method)" in line, line


def test_a_record_that_is_not_the_servers_five_part_line_is_replaced_by_a_fixed_text(written):
    """Fails closed: a record of another shape on this logger is never written as it came."""
    logging.getLogger("uvicorn.access").info("GET /api/%s?q=%s", MARK, MARK)
    line = written.getvalue()
    assert MARK not in line and access_log.ACCESS_LINE_WITHHELD in line, line


# --------------------------------------------------------------------------- #
#  The label itself, on an app of the test's own (never the process's shared one)
# --------------------------------------------------------------------------- #
def _small_app():
    from fastapi import APIRouter, FastAPI
    from starlette.applications import Starlette

    app = FastAPI()

    @app.get("/direct")
    def direct():
        return {}

    router = APIRouter()

    @router.get("/items/{item_id}")
    def item(item_id: str):
        return {}

    app.include_router(router, prefix="/api/v1")
    app.mount("/static", Starlette(routes=[]), name="static")
    return app


@pytest.fixture
def small(written):
    """The real filter on the real logger, reading the test's own app; put back as it was."""
    filt = next(f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, access_log.AccessLineFilter))
    old, filt.app = filt.app, _small_app()
    try:
        yield written
    finally:
        filt.app = old


@pytest.mark.parametrize(
    "method, path, expected",
    [
        ("GET", f"/direct?q={MARK}", "GET /direct "),
        ("GET", f"/api/v1/items/{MARK}?x=1", "GET /api/v1/items/{item_id} "),
        ("GET", f"/static/{MARK}.css", "GET /static "),
        ("POST", "/direct", "POST /direct "),  # a method mismatch is a partial match, named by its route
        ("GET", f"/nowhere/{MARK}", "GET (no route matched) "),
    ],
)
def test_the_label_is_the_template_with_its_prefixes_for_every_kind_of_route(small, method, path, expected):
    _serve_line(method, path)
    line = small.getvalue()
    assert expected in line and MARK not in line and "?" not in line, line


def test_no_route_is_ever_written_with_an_empty_label(small):
    for path in ("/direct", "/api/v1/items/x", "/static/a", "/zzz"):
        for method in ("GET", "POST", MARK):
            _serve_line(method, path)
    for line in small.getvalue().splitlines():
        assert 'GET  HTTP' not in line and '  HTTP/' not in line, line


@pytest.mark.parametrize("path", ["/api/%zz", "/api/%", "/api/%e0%a4%a", "/" + "9" * 5000, "/api/%00%ff"])
def test_a_malformed_escape_and_an_overlong_id_never_raise_and_name_no_typed_text(small, path):
    _serve_line("GET", path)
    line = small.getvalue()
    assert "zz" not in line.replace("(no route", "") and "99999" not in line and "e0" not in line, line
    assert "route" in line or "GET" in line


@pytest.mark.parametrize(
    "client, written_as",
    [
        ("203.0.113.9:4411", "203.0.113.9:4411"), ("[::1]:80", "[::1]:80"), ("::1", "::1"), ("1.2.3.4", "1.2.3.4"),
        ("0:0:0:0:0:0:0:1", "::1"),  # the PARSED address's own text, never the input's
        ("1.2.3.4:007", "1.2.3.4:7"),
        (f"{MARK}, 1.2.3.4", "(client)"), ("1.2.3.4:abc", "(client)"), ("evil.example:80", "(client)"), ("1.2.3.4:70000", "(client)"),
        ("::1%typed-secret-77", "(client)"), ("[::1%typed-secret-77]:80", "(client)"), ("fe80::1%25", "(client)"),
        ("fe80::1%" + "a" * 3000, "(client)"), ("[::1]x", "(client)"), ("unix:/tmp/typed-secret-77.sock", "(client)"),
        ("", "(client)"), (None, "(client)"), (b"1.2.3.4", "(client)"), (("1.2.3.4", 80), "(client)"),
    ],
)
def test_the_client_is_written_only_as_the_address_it_parses_to(small, client, written_as):
    """MUTATION TARGET: ``safe_client`` returning its input (Python parses an IPv6 scope id, and the input is free text behind a
    proxy that is trusted for ``X-Forwarded-For``)."""
    from src.monitoring.request_label import safe_client

    assert safe_client(client) == written_as
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', client, "GET", "/direct", "1.1", 200)
    line = small.getvalue()
    assert f"{written_as} - " in line and "secret-77" not in line and "aaaa" not in line and "%" not in line.split(" - ")[0], line


def test_the_rate_limit_line_names_the_client_only_as_an_address(caplog):
    """MUTATION TARGET: ``safe_client`` at the rate-limit handler (``src/api/main.py``): its line is another place the client's text
    reaches a log."""
    from fastapi.testclient import TestClient

    from tests.test_request_label_sinks import _limited_app, _past_its_limit

    client = TestClient(_limited_app(), client=(f"{MARK}-host", 5000))
    with caplog.at_level(logging.DEBUG):
        assert _past_its_limit(client) == 429
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("Rate limit exceeded for"))
    assert line.startswith("Rate limit exceeded for (client): ") and MARK not in line, line


def test_the_route_walk_falls_back_to_the_flat_list_of_an_older_fastapi(monkeypatch):
    """pyproject allows ``fastapi>=0.110``, whose ``app.routes`` is a flat list and which has no ``iter_route_contexts``."""
    import sys
    import types

    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    monkeypatch.setitem(sys.modules, "fastapi.routing", types.SimpleNamespace())  # ``from fastapi.routing import iter_route_contexts`` fails
    access_log._CONTEXTS.clear()

    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/things/{ident}", ok), Route("/plain", ok)])
    assert access_log._route_of("/things/zz", "GET", app) == "/things/{ident}"
    assert access_log._route_of("/plain", "GET", app) == "/plain"
    assert access_log._route_of("/nope", "GET", app) == access_log.UNMATCHED_ROUTE
    access_log._CONTEXTS.clear()


def test_the_route_contexts_are_built_once_per_app_and_again_when_the_routes_change(monkeypatch):
    """MUTATION TARGET: the cache (about a thousand route contexts were rebuilt for every access line)."""
    import fastapi.routing as fr

    built: list[int] = []
    real = fr.iter_route_contexts
    monkeypatch.setattr(fr, "iter_route_contexts", lambda routes: (built.append(1), real(routes))[1])
    access_log._CONTEXTS.clear()
    app = _small_app()
    for _ in range(5):
        assert access_log._route_of("/direct", "GET", app) == "/direct"
    assert len(built) == 1
    app.add_api_route("/added", lambda: {}, methods=["GET"])
    assert access_log._route_of("/added", "GET", app) == "/added"
    assert len(built) == 2, "a route added after the first line is read"
    access_log._CONTEXTS.clear()


def test_a_withheld_record_drops_its_exception_stack_and_extra_fields(written):
    log = logging.getLogger("uvicorn.access")
    seen: list[logging.LogRecord] = []

    class Last(logging.Handler):
        def emit(self, record):
            seen.append(record)

    h = Last()
    log.addHandler(h)
    try:
        try:
            raise ValueError(MARK)
        except ValueError:
            log.info("GET /x?q=%s", MARK, exc_info=True, stack_info=True, extra={"typed": MARK})
    finally:
        log.removeHandler(h)
    rec = seen[0]
    assert rec.getMessage() == access_log.ACCESS_LINE_WITHHELD
    assert rec.exc_info is None and rec.exc_text is None and rec.stack_info is None and not hasattr(rec, "typed")


# --------------------------------------------------------------------------- #
#  The WebSocket lines, one real record per format on ``uvicorn.error``
# --------------------------------------------------------------------------- #
@pytest.fixture
def ws_written():
    from src.api import main  # noqa: F401

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    log = logging.getLogger("uvicorn.error")
    old_level, old_prop = log.level, log.propagate
    log.setLevel(logging.INFO)
    log.propagate = False
    log.addHandler(handler)
    try:
        yield stream
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
        log.propagate = old_prop


def test_the_filter_for_websocket_lines_is_on_the_servers_own_logger():
    from src.api import main  # noqa: F401

    assert [f for f in logging.getLogger("uvicorn.error").filters if isinstance(f, access_log.WebSocketLineFilter)]


@pytest.mark.parametrize(
    "fmt, args, tail",
    [
        ('%s - "WebSocket %s" [accepted]', ("203.0.113.9:1", f"/ws/{MARK}?token={MARK}"), "[accepted]"),
        ('%s - "WebSocket %s" 403', ("203.0.113.9:1", f"/ws/{MARK}?token={MARK}"), "403"),
        ('%s - "WebSocket %s" %d', (MARK + ", 5.6.7.8", f"/ws/{MARK}?token={MARK}", 403), "403"),
    ],
)
def test_each_websocket_line_names_no_typed_text(ws_written, fmt, args, tail):
    logging.getLogger("uvicorn.error").info(fmt, *args)
    line = ws_written.getvalue()
    assert MARK not in line and "token" not in line and "?" not in line, line
    assert line.strip().endswith(tail) and "WebSocket (no route matched)" in line, line


def test_another_line_of_the_servers_logger_passes_unchanged(ws_written):
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    assert ws_written.getvalue().strip() == "Application startup complete."


def test_the_nginx_samples_keep_no_access_log_and_only_critical_errors():
    """MUTATION TARGET: the http-level ``access_log off;`` (a location's own ``access_log off;`` further down must not stand in for it),
    and the ``error_log`` level (nginx writes the request line, upstream and referrer on every error-level line)."""
    from pathlib import Path

    for name in ("nginx.conf", "nginx.production.conf"):
        text = (Path(__file__).resolve().parents[1] / "configs" / "nginx" / name).read_text(encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines()]
        live = [ln for ln in lines if ln.startswith("access_log")]
        assert live and set(live) == {"access_log off;"}, (name, live)
        first_server = next(i for i, ln in enumerate(lines) if ln.startswith("server {") or ln.startswith("server{"))
        first_access = next(i for i, ln in enumerate(lines) if ln.startswith("access_log"))
        assert first_access < first_server, f"{name}: the access_log off; must be set at http level, before the first server block"
        errors = [ln for ln in lines if ln.startswith("error_log")]
        assert errors and all(ln.rstrip(";").split()[-1] == "crit" for ln in errors), (name, errors)
        assert "The app writes its own access line" in text and "Only a critical error is logged" in text


# 26: the formats and ws="none", pinned to what is installed
def test_the_three_websocket_formats_are_the_ones_the_installed_server_writes():
    """A uvicorn upgrade that changes a format would otherwise let the typed path through unlabelled."""
    import importlib.util
    import pkgutil
    from pathlib import Path

    import uvicorn.protocols.websockets as pkg

    seen: dict[str, set[str]] = {fmt: set() for fmt in access_log._WEBSOCKET_FORMATS}
    modules = [m.name for m in pkgutil.iter_modules(pkg.__path__)]
    assert modules, "no protocol module found"
    for name in modules:
        # read as text: an implementation's own library (``wsproto``) need not be installed here
        source = Path(importlib.util.find_spec(f"{pkg.__name__}.{name}").origin).read_text(encoding="utf-8")
        if "WebSocket %s" not in source:
            continue
        for fmt in seen:
            if fmt in source:
                seen[fmt].add(name)
        # every implementation that logs a WebSocket line logs only lines of these three shapes
        for line in source.splitlines():
            if "WebSocket %s" in line:
                assert line.strip().rstrip(",").strip("'\"") in access_log._WEBSOCKET_FORMATS or any(f in line for f in access_log._WEBSOCKET_FORMATS), (name, line)
    assert all(seen.values()), seen


def test_serve_runs_the_server_with_websockets_off(monkeypatch):
    """MUTATION TARGET: ``ws="none"`` in ``_serve`` (captured from the real call by stubbing ``uvicorn.run``)."""
    import uvicorn

    from src.api import main
    from src.monitoring import exit_evidence, secret_scrub

    seen: dict = {}
    monkeypatch.setenv("OO_AUTOSEED", "0")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    monkeypatch.setattr(main, "install_signal_handlers", lambda: None)
    monkeypatch.setattr(secret_scrub, "guard_process", lambda: None)
    monkeypatch.setattr(exit_evidence, "arm_crash_trace", lambda: None)
    main._serve()
    assert seen.get("ws") == "none", seen


# --------------------------------------------------------------------------- #
#  The real configuration, in a fresh process, in both import orders
# --------------------------------------------------------------------------- #
_SUBPROCESS = r"""
import io, logging, logging.config, sys
order = sys.argv[1]
def imp():
    import src.api.main  # noqa
def cfg():
    from src.utils.logging_config import uvicorn_log_config
    logging.config.dictConfig(uvicorn_log_config())
(imp, cfg) if order == "main-first" else (cfg, imp)
for f in (imp, cfg) if order == "main-first" else (cfg, imp):
    f()
buf = io.StringIO()
for h in logging.getLogger("uvicorn.access").handlers:
    h.setStream(buf) if hasattr(h, "setStream") else None
logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:9", "GET", "/api/zq-typed-77?zq-typed-77=1", "1.1", 404)
print(buf.getvalue())
"""


@pytest.mark.parametrize("order", ["main-first", "config-first"])
def test_the_real_configuration_labels_the_line_in_either_import_order(order):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "-c", _SUBPROCESS, order], cwd=root, capture_output=True, text=True, timeout=120, check=False)
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    assert "zq-typed-77" not in out, out
    assert "GET (no route matched)" in out, out
