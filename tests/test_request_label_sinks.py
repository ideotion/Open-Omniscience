"""The sinks that name a request keep naming its route, whatever the framework logs or mounts (core fold 4, 2026-10-07).

``test_request_label.py`` sends requests through the app and reads what the journals keep. This file pins the sinks that a source
grep cannot: slowapi's own warning (its last argument is the path the client typed), the 429 and 500 labels, the in-flight stamp
and the pool's endpoint while a request is being served, a request a MOUNTED app answers (Starlette's ``Mount`` never sets
``scope["route"]``), and the older journal lines that carry a path, which are read with it withheld. Each test fails when its guard
goes (the slowapi one proves it with its own control).
"""

from __future__ import annotations

import asyncio
import json
import logging
import types

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import Response

from src.api.ratelimit import _DropRatelimitWarning, limiter
from src.database import pool_watch
from src.monitoring import errorlog, latency, request_label

TYPED = "zq-typed-in-the-bar-91"


@pytest.fixture
def journal_file(monkeypatch, tmp_path):
    monkeypatch.setattr(errorlog, "_log_path", lambda: tmp_path / "app_errors.jsonl")
    monkeypatch.setattr(errorlog, "_http_last", {})
    latency._reset_for_tests()
    return tmp_path / "app_errors.jsonl"


@pytest.fixture
def root_journal(journal_file):
    """The journal's own handler on the root logger, as ``errorlog.install`` puts it, for the length of a test."""
    handler = errorlog._JsonlErrorHandler(level=logging.WARNING)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield journal_file
    finally:
        root.removeHandler(handler)


def _text(path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _metrics_labels() -> str:
    from src.api.main import REQUEST_COUNT, REQUEST_LATENCY

    return json.dumps([[s.labels for s in m.samples] for m in (*REQUEST_COUNT.collect(), *REQUEST_LATENCY.collect())])


_APP: list[FastAPI] = []


def _limited_app() -> FastAPI:
    """A throwaway app with the repo's limiter, the app's own 429 handler and a route with a string id, limited to one a minute.
    Built ONCE: the limiter files a decorated route under its function's name, so a second copy would be limited twice."""
    if _APP:
        return _APP[0]
    from src.api import main

    app = FastAPI()
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, main.rate_limit_exceeded_handler)

    @app.get("/things/{ident}")
    @limiter.limit("1/minute")
    async def thing(request: Request, ident: str):
        return {"ok": ident}

    _APP.append(app)
    return app


_HOSTS = iter(f"198.51.100.{n}" for n in range(1, 250))


def _client_of(app: FastAPI) -> TestClient:
    """A test client of its own address (the limiter keys on it, and its storage outlives a test)."""
    return TestClient(app, client=(next(_HOSTS), 5000))


def _past_its_limit(client: TestClient) -> int:
    assert client.get(f"/things/{TYPED}").status_code == 200
    return client.get(f"/things/{TYPED}").status_code


# --------------------------------------------------------------------------- #
#  slowapi's own warning
# --------------------------------------------------------------------------- #
def test_slowapis_own_warning_never_carries_the_typed_path_to_a_handler_or_the_journal(root_journal, caplog):
    """MUTATION TARGET: the filter on the limiter's logger. ``ratelimit %s (%s) exceeded at endpoint: %s`` names the path."""
    client = _client_of(_limited_app())
    with caplog.at_level(logging.DEBUG):
        assert _past_its_limit(client) == 429
    seen = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert TYPED not in seen and TYPED not in _text(root_journal)
    assert "Rate limit exceeded for" in seen, "the app's own line (which names the route) is still written"


def test_without_the_filter_the_same_request_does_write_the_path(root_journal, caplog):
    """The control: this test can fail. With the filter off the slowapi record reaches the handlers and the journal."""
    limiter.logger.filters[:] = [f for f in limiter.logger.filters if not isinstance(f, _DropRatelimitWarning)]
    try:
        client = _client_of(_limited_app())
        with caplog.at_level(logging.DEBUG):
            assert _past_its_limit(client) == 429
        assert TYPED in "\n".join(r.getMessage() for r in caplog.records) and TYPED in _text(root_journal)
    finally:
        limiter.logger.addFilter(_DropRatelimitWarning())


def test_the_filter_drops_that_record_and_no_other_of_the_logger():
    flt = _DropRatelimitWarning()

    def rec(msg: str) -> logging.LogRecord:
        return logging.LogRecord("slowapi", logging.WARNING, __file__, 1, msg, (), None)

    assert flt.filter(rec("ratelimit %s (%s) exceeded at endpoint: %s")) is False
    assert flt.filter(rec("some other warning of the library")) is True
    assert sum(isinstance(f, _DropRatelimitWarning) for f in limiter.logger.filters) == 1, "installed once, on the limiter's logger"


def test_the_rate_limit_line_and_its_429_label_name_the_route(root_journal, caplog):
    """MUTATION TARGET: ``rate_limit_exceeded_handler`` naming ``request.url`` or ``request.url.path`` again (the line and the label)."""
    client = _client_of(_limited_app())
    with caplog.at_level(logging.DEBUG):
        assert _past_its_limit(client) == 429
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("Rate limit exceeded for"))
    assert TYPED not in line and line.endswith("GET /things/{ident}"), line
    labels = _metrics_labels()
    assert TYPED not in labels and '"http_status": "429"' in labels


# --------------------------------------------------------------------------- #
#  The 500 label, the in-flight stamp, the pool's endpoint
# --------------------------------------------------------------------------- #
def _request(path: str) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "query_string": f"k={TYPED}".encode(),
        "headers": [], "client": ("203.0.113.9", 5000), "server": ("testserver", 80), "scheme": "http", "root_path": "",
    })


def test_the_500_label_names_the_route_not_the_path(journal_file, caplog):
    """MUTATION TARGET: the unhandled-error handler's ``REQUEST_COUNT`` label."""
    from src.api import main

    request = _request(f"/things/{TYPED}")
    request.scope["route"] = types.SimpleNamespace(path="/things/{ident}")
    with caplog.at_level(logging.DEBUG):
        response = asyncio.run(main.unhandled_exception_handler(request, RuntimeError("boom")))
    assert response.status_code == 500
    labels = _metrics_labels()
    assert TYPED not in labels and '"endpoint": "/things/{ident}"' in labels and '"http_status": "500"' in labels
    assert TYPED not in "\n".join(r.getMessage() for r in caplog.records)


def test_the_in_flight_stamp_and_the_pools_endpoint_name_the_route_while_the_request_is_served(journal_file):
    """MUTATION TARGET: ``monitor_requests`` stamping the raw path into ``latency.note_start`` or ``pool_watch.set_endpoint``."""
    from src.api import main

    seen: dict = {}

    async def call_next(request: Request) -> Response:
        request.scope["route"] = types.SimpleNamespace(path="/things/{ident}")  # what routing does, after the stamps
        latency._record_block(900.0)
        seen["in_flight"] = list(latency._EVENTS[-1]["in_flight"])
        seen["label"] = pool_watch._endpoint_label()
        seen["template"] = pool_watch.endpoint_template()
        return Response(status_code=200)

    asyncio.run(main.monitor_requests(_request(f"/things/{TYPED}"), call_next))
    assert seen["in_flight"] and seen["in_flight"][0]["route"] == "GET /things/{ident}"
    assert seen["label"] == "GET /things/{ident}" and seen["template"] == "GET /things/{ident}"
    assert TYPED not in json.dumps(seen["in_flight"], default=str) and TYPED not in repr(seen["label"])


def test_before_routing_the_stamps_are_the_fixed_label(journal_file):
    from src.api import main

    seen: dict = {}

    async def call_next(request: Request) -> Response:
        latency._record_block(900.0)
        seen["in_flight"] = list(latency._EVENTS[-1]["in_flight"])
        seen["label"] = pool_watch._endpoint_label()
        return Response(status_code=200)

    asyncio.run(main.monitor_requests(_request(f"/{TYPED}"), call_next))
    assert seen["label"] == f"GET {request_label.UNMATCHED_ROUTE}"
    assert TYPED not in json.dumps(seen["in_flight"], default=str)


# --------------------------------------------------------------------------- #
#  Mounted apps
# --------------------------------------------------------------------------- #
def _mounted_app() -> FastAPI:
    """A small app with the app's own request monitor (``main.monitor_requests``, the middleware that feeds the latency summary and the
    metrics labels) and two mounts. NOT the shared ``src.api.main.app``: CLAUDE.md's rule (Lessons that cost a bug) forbids a test
    reading that process-global singleton's ``.routes``, which made the additive-restore guard flaky in CI. The real app's
    ``/metrics`` mount is skipped by the request monitor itself, and what only the real app reaches (the journal's 404 entry written by its
    exception handlers) is pinned by ``test_request_label.py``."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse

    from src.api import main

    def bare_app():  # a bare ASGI app (no routing of its own, as ``StaticFiles`` is) that answers 404; one object per mount
        async def nothing(scope, receive, send):
            await PlainTextResponse("nope", status_code=404)(scope, receive, send)

        return nothing

    app = FastAPI()
    app.add_middleware(BaseHTTPMiddleware, dispatch=main.monitor_requests)
    for name in ("static", "assets"):
        app.mount(f"/{name}", bare_app(), name=name)
    return app


@pytest.mark.parametrize("mount", ["/static", "/assets"])
def test_a_request_a_mounted_app_answers_is_named_by_the_mount_and_not_by_the_path_under_it(journal_file, mount):
    """MUTATION TARGET: ``request_label._mount_path``. Starlette's ``Mount`` sets ``scope["endpoint"]`` and never ``scope["route"]``."""
    client = TestClient(_mounted_app(), raise_server_exceptions=False)
    assert client.get(f"{mount}/{TYPED}").status_code == 404
    summary = repr(latency.summary())
    assert TYPED not in summary
    assert f"GET {mount}" in summary
    labels = _metrics_labels()
    assert f'"endpoint": "{mount}"' in labels and TYPED not in labels
    assert TYPED not in _text(journal_file)


def test_route_template_falls_back_to_the_mount_whose_app_is_the_endpoint():
    mounted = object()
    app = types.SimpleNamespace(routes=[types.SimpleNamespace(path="/other", app=object()), types.SimpleNamespace(path="/static", app=mounted)])
    assert request_label.route_template({"app": app, "endpoint": mounted}) == "/static"
    assert request_label.route_template({"app": app, "endpoint": object()}) is None
    assert request_label.route_template({"route": types.SimpleNamespace(path="/r/{id}"), "app": app, "endpoint": mounted}) == "/r/{id}"
    assert request_label.route_template({}) is None


# --------------------------------------------------------------------------- #
#  Older lines, read
# --------------------------------------------------------------------------- #
def _write(path, *entries: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps({"at": "2026-10-06T10:00:00+00:00", "level": "ERROR", **entry}) + "\n")


def test_every_older_line_that_names_a_path_is_read_with_it_withheld(journal_file):
    _write(
        journal_file,
        {"logger": "api", "message": f"unhandled error on GET /api/{TYPED}?k={TYPED}: ValueError: x\nValueError: x"},
        {"logger": "api", "message": f"unhandled error on ZQ{TYPED} /{TYPED}: ValueError: y"},
        {"logger": "api", "message": f"Rate limit exceeded for 203.0.113.9: http://127.0.0.1:8000/api/{TYPED}?k={TYPED}"},
        {"logger": "api", "message": f"Rate limit exceeded for ::1: http://[::1]:8000/{TYPED}"},
        {"logger": "slowapi", "message": f"ratelimit 5 per 1 minute (203.0.113.9) exceeded at endpoint: /api/{TYPED}"},
        {"logger": "frontend", "kind": "fetch-failed", "message": "network error", "endpoint": f"/api/x?k={TYPED}", "source": f"app.js?v={TYPED}"},
    )
    entries = errorlog.recent_errors()
    assert TYPED not in json.dumps(entries)
    messages = [e["message"] for e in entries]
    assert messages[0] == "unhandled error on " + request_label.PATH_WITHHELD, "no tail: no split can tell a spaced path from it"
    assert messages[1] == "unhandled error on " + request_label.PATH_WITHHELD
    assert messages[2] == "Rate limit exceeded for 203.0.113.9: " + request_label.PATH_WITHHELD
    assert messages[3] == "Rate limit exceeded for ::1: " + request_label.PATH_WITHHELD
    assert messages[4] == "ratelimit 5 per 1 minute (203.0.113.9) exceeded at endpoint: " + request_label.PATH_WITHHELD
    assert (entries[5]["endpoint"], entries[5]["source"]) == ("/api/x", "app.js")
    assert TYPED in _text(journal_file), "the file itself is left as it was"


def test_a_line_that_names_the_route_is_read_as_it_was_written(journal_file):
    _write(
        journal_file,
        {"logger": "api", "message": "unhandled error on route GET /api/articles/{id}/view: ValueError: x"},
        {"logger": "api", "message": "Rate limit exceeded for 203.0.113.9: GET /api/articles/{id}/view"},
        {"logger": "api", "message": f"Rate limit exceeded for 203.0.113.9: POST {request_label.UNMATCHED_ROUTE}"},
        {"logger": "api", "message": "something else entirely"},
    )
    assert [e["message"] for e in errorlog.recent_errors()] == [
        "unhandled error on route GET /api/articles/{id}/view: ValueError: x",
        "Rate limit exceeded for 203.0.113.9: GET /api/articles/{id}/view",
        f"Rate limit exceeded for 203.0.113.9: POST {request_label.UNMATCHED_ROUTE}",
        "something else entirely",
    ]


def test_a_browser_report_drops_the_query_of_the_url_it_names(journal_file):
    errorlog._frontend_last.clear()
    errorlog.note_frontend_error("fetch-failed", "network error", source=f"/app.js?v={TYPED}#x", endpoint=f"/api/search?q={TYPED}#frag")
    (entry,) = [json.loads(ln) for ln in _text(journal_file).splitlines()]
    assert (entry["source"], entry["endpoint"]) == ("/app.js", "/api/search") and TYPED not in json.dumps(entry)


def test_the_page_drops_the_query_before_it_posts_the_report():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src" / "static" / "app-core.js").read_text(encoding="utf-8")
    assert 'split(/[?#]/)[0]' in js and "body.endpoint = noQuery(endpoint)" in js and "body.source = noQuery(source)" in js


SECRET_WORDS = "correct horse battery staple"


def test_an_older_unhandled_line_with_a_spaced_path_keeps_no_word_of_it(journal_file):
    """MUTATION TARGET: the reader's whole-head match (a split that wrote back everything after the path's first space)."""
    _write(
        journal_file,
        {"logger": "api", "message": f"unhandled error on GET /{SECRET_WORDS}: ValueError: boom"},
        {"logger": "api", "message": f"unhandled error on route /{SECRET_WORDS}: ValueError: boom"},  # a method token the client chose
        {"logger": "api", "message": f"unhandled error on route GET /{SECRET_WORDS}: ValueError: boom"},
    )
    for entry in errorlog.recent_errors():
        assert "horse" not in json.dumps(entry) and "staple" not in json.dumps(entry), entry
        assert entry["message"] == "unhandled error on " + request_label.PATH_WITHHELD


def test_a_new_unhandled_line_is_kept_whole_and_so_is_one_with_a_converter_template(journal_file):
    _write(
        journal_file,
        {"logger": "api", "message": "unhandled error on route GET /api/articles/{article_id}: ValueError: boom"},
        {"logger": "api", "message": "unhandled error on route GET /files/{p:path}: ValueError: boom"},
        {"logger": "api", "message": "unhandled error on route (other method) (no route matched): ValueError: boom"},
    )
    assert [e["message"].split(": ", 1)[1] for e in errorlog.recent_errors()] == ["ValueError: boom"] * 3


def test_an_older_rate_limit_line_whose_client_text_holds_a_space_is_withheld_whole(journal_file):
    """(a) The client is an address or a fixed word; anything else is no address, and what follows it may be the URL."""
    _write(
        journal_file,
        {"logger": "api", "message": f"Rate limit exceeded for 1.2.3.4 evil: http://127.0.0.1:8000/{TYPED}"},
        {"logger": "api", "message": f"Rate limit exceeded for {TYPED} x: GET /api/{TYPED}"},
    )
    entries = errorlog.recent_errors()
    assert TYPED not in json.dumps(entries) and "evil" not in json.dumps(entries)
    assert all(e["message"] == "Rate limit exceeded for (client): " + request_label.PATH_WITHHELD for e in entries)


@pytest.mark.parametrize(
    "tail",
    [f"GET /{SECRET_WORDS}", f"route /{TYPED}", f"{TYPED} /x", f"GET /x?k={TYPED}", f"GET /x extra {TYPED}", f"post /{TYPED}"],
)
def test_a_rate_limit_line_is_kept_only_when_it_is_a_standard_method_and_a_template(journal_file, tail):
    """(b) The word ``route`` and a ``/``-path after a method are the client's to send through a custom method."""
    _write(journal_file, {"logger": "api", "message": f"Rate limit exceeded for 203.0.113.9: {tail}"})
    got = errorlog.recent_errors()[0]["message"]
    assert TYPED not in got and "horse" not in got and got == "Rate limit exceeded for 203.0.113.9: " + request_label.PATH_WITHHELD


def test_a_new_rate_limit_line_is_kept_whole(journal_file):
    _write(journal_file, {"logger": "api", "message": "Rate limit exceeded for 203.0.113.9: GET /api/articles/{article_id}"},
           {"logger": "api", "message": "Rate limit exceeded for (client): POST (no route matched)"})
    assert [e["message"] for e in errorlog.recent_errors()] == [
        "Rate limit exceeded for 203.0.113.9: GET /api/articles/{article_id}",
        "Rate limit exceeded for (client): POST (no route matched)",
    ]
