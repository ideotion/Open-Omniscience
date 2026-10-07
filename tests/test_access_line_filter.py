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


def test_a_matched_route_is_written_as_its_template_and_the_value_in_it_is_not(written):
    _serve_line("GET", f"/api/articles/{MARK}/view?lang=fr", status=200)
    line = written.getvalue()
    assert MARK not in line and "lang" not in line, line
    assert "GET /api/articles/{" in line, line


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


@pytest.mark.parametrize("client, kept", [("203.0.113.9:4411", True), ("[::1]:80", True), ("::1", True), ("1.2.3.4", True),
                                          (f"{MARK}, 1.2.3.4", False), ("1.2.3.4:abc", False), ("evil.example:80", False) ])
def test_the_client_is_written_only_when_it_is_an_address(small, client, kept):
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', client, "GET", "/direct", "1.1", 200)
    line = small.getvalue()
    assert (client in line) is kept and (kept or "(client)" in line), line


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
        ('%s - "WebSocket %s" %d', (MARK + ", 5.6.7.8", f"/ws/{MARK}?token={MARK}", 1000), "1000"),
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


def test_the_server_is_started_with_websockets_off():
    import inspect

    from src.api import main

    assert 'ws="none"' in inspect.getsource(main)


def test_the_nginx_samples_keep_no_access_log_of_their_own():
    from pathlib import Path

    for name in ("nginx.conf", "nginx.production.conf"):
        text = (Path(__file__).resolve().parents[1] / "configs" / "nginx" / name).read_text(encoding="utf-8")
        live = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("access_log")]
        assert live and set(live) == {"access_log off;"}, (name, live)
        assert "The app writes its own access line" in text


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
logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:9", "GET", "/api/zq-typed-77?token=zq-typed-77", "1.1", 404)
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
    assert "zq-typed-77" not in out and "token" not in out, out
    assert "GET (no route matched)" in out, out
