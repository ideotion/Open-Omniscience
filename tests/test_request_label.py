"""The diagnostics name a request by its route template and a standard method, never by the path the caller typed (2026-10-07).

A passphrase typed into the address bar is a path; a locked app holds no key to scrub it with. ``src/monitoring/request_label.py``
is what the error journal's HTTP entries, the latency log (its routes and its in-flight list), the pool's endpoint, the request
metrics (which the bundle carries) and the unhandled-error line write instead. These tests send real requests through the app's
middleware, with the passphrase in the path, and read every place that keeps them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from src.monitoring import errorlog, latency, request_label

TYPED = "zq-typed-in-the-bar-91"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(errorlog, "_log_path", lambda: tmp_path / "app_errors.jsonl")
    monkeypatch.setattr(errorlog, "_http_last", {})
    latency._reset_for_tests()
    from src.api.main import app

    return TestClient(app, raise_server_exceptions=False), tmp_path


def _journal(tmp_path) -> str:
    path = tmp_path / "app_errors.jsonl"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _metrics_labels() -> str:
    from src.api.main import REQUEST_COUNT, REQUEST_LATENCY

    return json.dumps([[s.labels for s in m.samples] for m in (*REQUEST_COUNT.collect(), *REQUEST_LATENCY.collect())])


def test_an_unmatched_path_with_a_passphrase_in_it_reaches_no_journal_or_label(client):
    """MUTATION TARGET: any of the five middleware sites that passed the raw path again."""
    c, tmp_path = client
    assert c.get(f"/api/{TYPED}").status_code == 404
    assert TYPED not in _journal(tmp_path)
    assert f"GET {request_label.UNMATCHED_ROUTE}" in repr(latency.summary()), "filed under the fixed label"
    assert TYPED not in repr(latency.summary()) and TYPED not in _metrics_labels()
    (entry,) = [json.loads(ln) for ln in _journal(tmp_path).splitlines() if '"http"' in ln]
    assert (entry["method"], entry["path"]) == ("GET", request_label.UNMATCHED_ROUTE)


def test_a_matched_route_is_named_by_its_template_and_not_by_the_value_in_it(client):
    c, tmp_path = client
    assert c.get(f"/api/articles/{TYPED}/view").status_code >= 400
    assert TYPED not in _journal(tmp_path) and TYPED not in repr(latency.summary()) and TYPED not in _metrics_labels()
    assert "/api/articles/{" in _journal(tmp_path)


def test_a_locked_app_answers_503_and_writes_no_raw_path(client, monkeypatch):
    """The locked app holds no key to scrub with: the 503 the gate answers before routing is the case a held-key scrub cannot cover."""
    c, tmp_path = client
    from src.api import unlock

    monkeypatch.setattr(unlock, "app_lock_state", lambda: "locked")
    assert c.get(f"/api/{TYPED}").status_code == 503
    assert TYPED not in _journal(tmp_path) and TYPED not in repr(latency.summary()) and TYPED not in _metrics_labels()
    assert request_label.UNMATCHED_ROUTE in _journal(tmp_path)


def test_a_method_the_client_made_up_is_never_written(client):
    c, tmp_path = client
    c.request("ZQTYPED", "/api/health")
    assert "ZQTYPED" not in _journal(tmp_path) and "ZQTYPED" not in _metrics_labels()


def test_the_unhandled_error_line_and_its_500_label_name_the_route_and_not_the_path(client, caplog):
    c, _ = client
    from src.api import main

    @main.app.get("/_test_boom/{value}")
    async def boom(value: str):  # pragma: no cover - raises
        raise RuntimeError("boom")

    added = main.app.router.routes[-1]  # the route above: taken out again below, so it outlives no test
    try:
        with caplog.at_level(logging.DEBUG):
            assert c.get(f"/_test_boom/{TYPED}").status_code == 500
    finally:
        main.app.router.routes.remove(added)
    # (the test client's own httpx logger names the URL it asked for: that is the caller's side, not the app's)
    app_text = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert TYPED not in app_text and "unhandled error on route GET /_test_boom/{value}" in app_text
    labels = _metrics_labels()
    assert TYPED not in labels and '"endpoint": "/_test_boom/{value}"' in labels and '"http_status": "500"' in labels
    assert all(r.path != "/_test_boom/{value}" for r in main.app.router.routes if hasattr(r, "path"))


def test_the_in_flight_list_names_the_template_once_routing_has_set_it():
    latency._reset_for_tests()
    scope: dict = {}
    latency.note_start(1, "GET (no route matched)", scope=scope, method="GET")

    class _Route:
        path = "/api/x/{id}"

    scope["route"] = _Route()
    latency._record_block(900.0)
    assert latency._EVENTS[-1]["in_flight"][0]["route"] == "GET /api/x/{id}"
    assert latency._inflight_route(latency._INFLIGHT[1]) == "GET /api/x/{id}"
    latency._reset_for_tests()


def test_the_request_middleware_never_reads_the_raw_path_or_method_into_a_diagnostic():
    """MUTATION TARGET: any site of ``monitor_requests`` that names the request by ``request.url.path`` or ``request.method`` (the
    in-flight stamp and the pool's endpoint are only read while a request is stalled or holds a connection, which a request
    through the test client does not do on an unmatched path)."""
    import inspect

    from src.api.main import monitor_requests

    source = inspect.getsource(monitor_requests)
    assert "request.url.path" not in source and "request.method" not in source.replace("safe_method(request.method)", "")
