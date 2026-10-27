"""The Origin guard refuses a foreign page on EVERY state-changing operation of the app (audit 0.5.0 item 35).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``docs/SECURITY.md`` ("The local API") names the layers between a cross-site page and a state-changing request. On the routes that
take no body or an optional one (148 + 11 of 317 on 2026-10-26) and on the raw-body modules, only layers 1 and 2 stand, and the Origin / Referer check in
``src/api/main.py::csrf_and_security_headers`` is the layer that answers first; until now it was pinned on a few routes.
It is a middleware on the method, so it holds for every route today; this file keeps it that way by sending a foreign ``Origin``
to every ``POST`` / ``PUT`` / ``PATCH`` / ``DELETE`` operation in the app's own OpenAPI schema and asserting 403, so a router
wired around the middleware or a path-based exemption fails here by name, and a mounted sub-application added later fails the mount-set test.

What a 403 here proves and does not: the request was refused before ANY handler ran (the response is the middleware's own body,
checked; a text comparison, so it cannot tell the middleware from a dependency returning the same words), for the operations the
schema lists. Operations with ``include_in_schema=False`` are not in the schema (the three that exist are GETs) and the two mounts
(``/static``, ``/metrics``) are driven by hand below, their set pinned to the ``app.mount`` calls in ``main.py``.

The fixture engages the network kill switch and does not re-raise handler exceptions: if the guard is ever broken, the handlers this
loop reaches must not touch the network or hide the list of operations that got through.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_METHODS = ("post", "put", "patch", "delete")
_FOREIGN = {"Origin": "http://evil.example"}
_REFUSAL = "Cross-origin state-changing request refused (loopback only)."
# The number of state-changing operations the schema listed on 2026-10-26 and again on 2026-10-27 (main 26ce1da6a). A floor, not an
# exact count: new routes are welcome and are covered by the same loop; fewer than this means the finder stopped seeing routes (a
# framework change in how the schema is built), which would turn every assertion below into a loop over nothing. The Core-only
# install (no [analysis] extra) mounts 11 fewer (the commodity, statistical-analysis and article-similarity routes are disabled
# there, and say so at boot): 306, measured by CI's Core-only lane and reproduced by blocking numpy/pandas/scipy/sklearn/statsmodels.
_OPERATIONS_FLOOR_FULL = 317
_OPERATIONS_FLOOR_CORE_ONLY = 306


def _analysis_extra_installed() -> bool:
    return all(importlib.util.find_spec(m) is not None for m in ("numpy", "pandas", "scipy", "sklearn", "statsmodels"))


_OPERATIONS_FLOOR = _OPERATIONS_FLOOR_FULL if _analysis_extra_installed() else _OPERATIONS_FLOOR_CORE_ONLY


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from src.api.main import app
    from src.ingest import activate_kill_switch, clear_kill_switch

    # A broken guard would run real handlers (95 answered 200 in the mutation check, some destructive, some resolving public hosts):
    # the kill switch keeps them off the network, and raise_server_exceptions=False lists the misses instead of dying on the first.
    activate_kill_switch()
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        clear_kill_switch()


def _operations(app) -> list[tuple[str, str]]:
    """(METHOD, concrete path) for every state-changing operation in the OpenAPI schema; ``{id}`` becomes a placeholder."""
    schema = app.openapi()
    found = []
    for path, ops in schema["paths"].items():
        concrete = re.sub(r"\{[^}]+\}", "1", path)
        for method in ops:
            if method in _METHODS:
                found.append((method.upper(), concrete))
    return sorted(found)


def test_the_schema_walk_still_sees_the_routes():
    from src.api.main import app

    ops = _operations(app)
    assert len(ops) >= _OPERATIONS_FLOOR, (
        f"the OpenAPI schema lists {len(ops)} state-changing operations, fewer than the {_OPERATIONS_FLOOR} it listed on "
        "2026-10-27 for this install: either routes were removed (lower the floor, with a reason) or the walk went blind"
    )


def test_every_state_changing_operation_refuses_a_foreign_origin(client):
    from src.api.main import app

    bad = []
    for method, path in _operations(app):
        r = client.request(method, path, headers=_FOREIGN)
        if r.status_code != 403 or r.json().get("detail") != _REFUSAL:
            bad.append((method, path, r.status_code, r.text[:80]))
    assert not bad, f"{len(bad)} operation(s) answered a foreign-Origin request without the middleware's refusal: {bad[:10]}"


def test_a_foreign_referer_alone_is_refused_on_a_sample_of_every_method(client):
    from src.api.main import app

    by_method: dict[str, tuple[str, str]] = {}
    for method, path in _operations(app):
        by_method.setdefault(method, (method, path))
    assert set(by_method) == {m.upper() for m in _METHODS}, "the schema lists no operation for some state-changing method"
    for method, path in by_method.values():
        r = client.request(method, path, headers={"Referer": "http://evil.example/page"})
        assert r.status_code == 403 and r.json().get("detail") == _REFUSAL, (method, path, r.status_code)


@pytest.mark.parametrize("mount", ["/static/oo.js", "/metrics/", "/metrics"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_the_mounted_applications_are_behind_the_same_guard(client, mount, method):
    r = client.request(method, mount, headers=_FOREIGN)
    assert r.status_code == 403 and r.json().get("detail") == _REFUSAL, (method, mount, r.status_code)


def test_the_mount_set_is_the_two_this_file_drives():
    """A mounted sub-application added later is a path the loops above never send to; make that a failure here, not a silence."""
    source = (Path(__file__).resolve().parent.parent / "src" / "api" / "main.py").read_text(encoding="utf-8")
    mounts = set(re.findall(r'app\.mount\(\s*"([^"]+)"', source))
    assert mounts == {"/static", "/metrics"}, f"main.py mounts {sorted(mounts)}: add the new one to the mount test above"


def test_the_refusal_is_not_a_blanket_403(client):
    """The loop above would pass if the middleware refused everything. The same request with this server's own Origin reaches the
    handler (``/api/newsletters/remove-imported`` answers 400 to ``confirm: false``), and so does one that sends neither header."""
    for headers in ({"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}, {}):
        r = client.post("/api/newsletters/remove-imported", json={"confirm": False}, headers=headers)
        assert r.status_code == 400, (headers, r.status_code, r.text)


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_this_servers_own_origin_is_not_refused_on_the_other_methods(client, method):
    """A blanket 403 for a method other than POST would pass the loop above; the app's own Origin must get past the middleware. The
    path need not exist: an unknown path answers 404/405 from the router, which is anything but the middleware's refusal."""
    r = client.request(method, "/api/no-such-route-for-the-origin-ratchet", headers={"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"})
    assert r.status_code != 403, (method, r.status_code, r.text)
