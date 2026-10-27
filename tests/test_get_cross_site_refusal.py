"""A GET that does work on the machine refuses the requests another site's page makes (R278).

The Origin middleware looks only at state-changing methods, so a page the person visits could fire any GET at a loopback address
with an ``<img src>``: heavy compute (the in-memory rollup benchmark), a live outbound request, a signing key minted. The routes
named here carry :func:`src.api.cross_site.refuse_cross_site_get`; this pins that each does, that a foreign Origin or Fetch
Metadata is answered 403 BEFORE the handler runs, and that a request with none of them still reaches it.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.api.cross_site import refuse_cross_site_get

# (module, full path of the GET route in that module's own router)
GUARDED = [
    ("src.api.diagnostics.performance", "/api/diagnostics/performance"),
    ("src.api.diagnostics.performance", "/api/diagnostics/benchmark"),
    ("src.api.diagnostics.performance", "/api/diagnostics/rollup-benchmark"),
    ("src.api.diagnostics.performance", "/api/diagnostics/llm-bench"),
    ("src.api.diagnostics.performance", "/api/diagnostics/llm-throughput"),
    ("src.api.diagnostics.performance", "/api/diagnostics/ai-activity-selftest"),
    ("src.api.diagnostics.performance", "/api/diagnostics/llm-throughput-selftest"),
    ("src.api.diagnostics.performance", "/api/diagnostics/source-coverage-benchmark"),
    ("src.api.diagnostics.evals", "/api/diagnostics/ir-eval-selftest"),
    ("src.api.diagnostics.evals", "/api/diagnostics/perception-eval-selftest"),
    ("src.api.diagnostics.evals", "/api/diagnostics/keyword-triage-selftest"),
    ("src.api.diagnostics.evals", "/api/diagnostics/recursive-loop"),
    ("src.api.diagnostics.evals", "/api/diagnostics/search-timing-selftest"),
    ("src.api.diagnostics.bundle", "/api/diagnostics/debug-bundle"),
    ("src.api.diagnostics.bundle", "/api/diagnostics/all"),
    ("src.api.diagnostics.corpus", "/api/diagnostics/bulletin-language-selftest"),
    ("src.api.diagnostics.corpus", "/api/diagnostics/power-profile-selftest"),
    ("src.api.diagnostics.keywords", "/api/diagnostics/keyword-selftest"),
    ("src.api.diagnostics.ai", "/api/diagnostics/qualification-assist-selftest"),
    ("src.api.diagnostics.sources", "/api/diagnostics/source-audit-selftest"),
    ("src.api.diagnostics.source_tags", "/api/diagnostics/source-tags-selftest"),
    ("src.api.signals", "/api/signals/fdr-selftest"),
    ("src.api.hazards", "/api/hazards"),
    ("src.api.monitoring", "/api/monitoring/health"),
    ("src.api.wiki", "/api/wiki/dumps/probe"),
    ("src.api.wiki", "/api/wiki/dumps/sizes"),
    ("src.api.custody", "/api/custody/export"),
    ("src.api.annotations", "/api/annotations/export"),
    ("src.api.geo", "/api/geo/downloads/size"),
    # served_file_response appends to diagnostics/runs.jsonl (+ .lock); the volume route also makes a directory, the parts route touches its set
    ("src.api.diagnostics.bundle", "/api/diagnostics/all-job/download"),
    ("src.api.diagnostics.bundle", "/api/diagnostics/all-job/volumes/{name}"),
    ("src.api.diagnostics.keyword_parts", "/api/diagnostics/keywords/parts/{set_id}/{name}"),
]


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in {"host": "127.0.0.1:8000", **headers}.items()]
    return Request({"type": "http", "method": "GET", "path": "/", "scheme": "http", "server": ("127.0.0.1", 8000), "headers": raw})


@pytest.mark.parametrize(("module", "path"), GUARDED)
def test_each_route_carries_the_dependency(module: str, path: str) -> None:
    router = importlib.import_module(module).router
    routes = [r for r in router.routes if getattr(r, "path", None) == path and "GET" in getattr(r, "methods", ())]
    assert len(routes) == 1, f"{path} is not exactly one GET route of {module}"
    assert refuse_cross_site_get in [d.call for d in routes[0].dependant.dependencies]


@pytest.mark.parametrize(("module", "path"), GUARDED)
@pytest.mark.parametrize(
    "headers",
    [{"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}],
)
def test_a_foreign_request_is_refused_before_the_handler_runs(module: str, path: str, headers: dict[str, str]) -> None:
    from src.api.main import app

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        r = client.get(path, headers=headers)
    assert r.status_code == 403
    assert "does work on your machine" in r.json()["detail"]


def test_a_request_with_no_origin_still_reaches_the_handler() -> None:
    from src.api.main import app

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        r = client.get("/api/signals/fdr-selftest")
        same = client.get(
            "/api/signals/fdr-selftest",
            headers={"Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin"},
        )
    assert r.status_code == 200
    assert same.status_code == 200


@pytest.mark.parametrize(
    "headers",
    [{}, {"Sec-Fetch-Site": "none"}, {"Sec-Fetch-Site": "same-origin", "Origin": "http://127.0.0.1:8000"}, {"Referer": "http://127.0.0.1:8000/x"}],
)
def test_the_app_own_page_and_non_browser_callers_pass(headers: dict[str, str]) -> None:
    assert refuse_cross_site_get(_request(headers)) is None


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "same-site"},
        {"Origin": "http://127.0.0.1:9999"},
        {"Referer": "https://evil.example/page"},
        {"host": "rebind.example"},
    ],
)
def test_other_ports_other_sites_and_foreign_hosts_are_refused(headers: dict[str, str]) -> None:
    with pytest.raises(HTTPException) as exc:
        refuse_cross_site_get(_request(headers))
    assert exc.value.status_code == 403


class _Rows:
    """The one query chain ``sources_health`` runs, answering two sources."""

    def __init__(self) -> None:
        self.rows = [object(), object()]

    def query(self, *_a):
        return self

    def filter(self, *_a):
        return self

    def order_by(self, *_a):
        return self

    def limit(self, *_a):
        return self

    def all(self):
        return self.rows


def _health(status: str, detail: str | None) -> dict:
    return {"source_id": 1, "name": "n", "url": "u", "status": status, "latency_ms": None, "checked_at": "t", "detail": detail}


def test_a_probe_the_kill_switch_refused_is_not_counted_as_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """W1: ``summary.down`` blamed the source for the person's own airplane mode while the per-source detail named the switch."""
    from src.api import monitoring

    answers = iter(
        [
            _health("down", "network kill switch is active -- collection stopped by operator"),
            _health("down", "HTTP 503"),
        ]
    )

    class _Result:
        def __init__(self, d: dict) -> None:
            self.d = d

        def to_dict(self) -> dict:
            return self.d

    monkeypatch.setattr(monitoring, "check_source", lambda *_a, **_k: _Result(next(answers)))
    monkeypatch.setattr(monitoring, "kill_switch_active", lambda: True)
    out = monitoring.sources_health(limit=2, db=_Rows(), fetcher=object())
    assert out["summary"] == {"refused_by_kill_switch": 1, "down": 1}


def test_with_the_switch_off_a_down_stays_down(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api import monitoring

    class _Result:
        def to_dict(self) -> dict:
            return _health("down", "network kill switch is active -- collection stopped by operator")

    monkeypatch.setattr(monitoring, "check_source", lambda *_a, **_k: _Result())
    monkeypatch.setattr(monitoring, "kill_switch_active", lambda: False)
    out = monitoring.sources_health(limit=1, db=_Rows(), fetcher=object())
    assert out["summary"] == {"down": 2}


def _request_on(scheme: str, headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/", "scheme": scheme, "server": ("oo.lan", 443), "headers": raw})


def test_a_proxy_that_names_the_default_port_in_host_is_the_same_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """The follow-on to the Opus read of R278: ``Host: oo.lan:443`` and ``Origin: https://oo.lan`` name one server.

    The raw string compare this replaced refused that pair on a GET while the POST middleware let it through.
    """
    monkeypatch.setenv("OO_ALLOWED_HOSTS", "oo.lan")
    assert refuse_cross_site_get(_request_on("https", {"host": "oo.lan:443", "origin": "https://oo.lan"})) is None
    assert refuse_cross_site_get(_request_on("https", {"host": "oo.lan", "origin": "https://oo.lan:443"})) is None
    assert refuse_cross_site_get(_request_on("http", {"host": "oo.lan:80", "referer": "http://oo.lan/page"})) is None


@pytest.mark.parametrize(
    ("scheme", "headers"),
    [
        ("https", {"host": "oo.lan:443", "origin": "https://oo.lan:8443"}),
        ("https", {"host": "oo.lan:443", "origin": "https://evil.example"}),
        ("https", {"host": "oo.lan:443", "origin": "ftp://oo.lan:443"}),
        ("https", {"host": "oo.lan", "origin": "https://oo.lan:99999"}),
    ],
)
def test_a_different_port_host_or_scheme_is_still_a_different_server(
    monkeypatch: pytest.MonkeyPatch, scheme: str, headers: dict[str, str]
) -> None:
    monkeypatch.setenv("OO_ALLOWED_HOSTS", "oo.lan")
    with pytest.raises(HTTPException) as exc:
        refuse_cross_site_get(_request_on(scheme, headers))
    assert exc.value.status_code == 403


def test_the_osm_size_read_makes_no_head_for_a_foreign_page_and_one_for_the_own_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """A-014 (R284): a cross-site GET of ``/api/geo/downloads/size`` reached the outbound HEAD and answered 200."""
    from src.api.main import app
    from src.geo import osm_downloads

    heads: list[str] = []

    class _Manager:
        def size_reading(self, code: str) -> dict:
            heads.append(code)
            return {"code": code, "bytes": 1}

    monkeypatch.setattr(osm_downloads, "get_manager", lambda: _Manager())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        foreign = client.get("/api/geo/downloads/size?code=planet", headers={"Sec-Fetch-Site": "cross-site", "Referer": "https://evil.example/x"})
        no_metadata = client.get("/api/geo/downloads/size?code=planet", headers={"Origin": "https://evil.example"})
        own = client.get("/api/geo/downloads/size?code=planet", headers={"Sec-Fetch-Site": "same-origin", "Referer": "http://127.0.0.1/"})
        script = client.get("/api/geo/downloads/size?code=planet")
    assert foreign.status_code == 403 and no_metadata.status_code == 403
    assert heads == ["planet", "planet"]
    assert own.status_code == 200 and script.status_code == 200


# --- F3: the three GETs that append to diagnostics/runs.jsonl (found by tests/test_get_routes_side_effects_with_data.py) -------------------
# serving a diagnostics file writes a begin and an end line (+ the .lock) through ``served_file_response``; a refusal that runs before
# the handler leaves the log as it was. An unguarded route with nothing planted answers 404 BEFORE it writes, so each case plants the file
# and first proves, with a same-origin request, that the route WOULD have written.


def _plant(route: str, monkeypatch: pytest.MonkeyPatch, tmp_path) -> str:
    import json

    from src.api import diagnostics_volumes as dvol
    from src.api.diagnostics import bundle as b
    from src.api.diagnostics import keyword_parts as kp

    if route == "all-job":
        zip_path = tmp_path / "oo-all-diagnostics-20261027-000000.zip"
        zip_path.write_bytes(b"PK" + b"1" * 50)
        monkeypatch.setattr(b, "_newest_all_diagnostics_archive", lambda: zip_path)
        return "/api/diagnostics/all-job/download"
    if route == "volume":
        out = tmp_path / "vols"
        out.mkdir()
        (out / "set-part-1.zip").write_bytes(b"PK" + b"1" * 50)
        monkeypatch.setattr(b, "_all_diagnostics_volumes_dir", lambda: out)
        monkeypatch.setattr(dvol, "load_manifest", lambda _p: {"volumes": [{"name": "set-part-1.zip"}], "manifest_files": []})
        return "/api/diagnostics/all-job/volumes/set-part-1.zip"
    root = tmp_path / "parts"
    folder = root / "oo-keyword-parts-abc123"
    folder.mkdir(parents=True)
    (folder / "part-0001.zip").write_bytes(b"PK" + b"2" * 80)
    (folder / "set.json").write_text(json.dumps({"files": [{"name": "part-0001.zip"}]}), encoding="utf-8")
    monkeypatch.setattr(kp, "_parts_root", lambda: root)
    return "/api/diagnostics/keywords/parts/oo-keyword-parts-abc123/part-0001.zip"


@pytest.mark.parametrize("route", ["all-job", "volume", "parts"])
def test_a_foreign_request_leaves_runs_jsonl_as_it_was(route: str, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from src.api.main import app
    from src.monitoring import diagnostics_runs as runs

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    runs.reset_for_tests()
    try:
        url = _plant(route, monkeypatch, tmp_path)
        log_dir = tmp_path / "data" / "diagnostics"
        with TestClient(app, base_url="http://127.0.0.1:8000") as client:
            own = client.get(url, headers={"Sec-Fetch-Site": "same-origin"})
            assert own.status_code == 200
            assert (log_dir / "runs.jsonl").is_file(), "the control did not write: this test would pass on an unguarded route"
            before = (log_dir / "runs.jsonl").read_bytes()
            for headers in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
                refused = client.get(url, headers=headers)
                assert refused.status_code == 403
        assert (log_dir / "runs.jsonl").read_bytes() == before
    finally:
        runs.reset_for_tests()


def _served_file_response_callers() -> list[tuple[str, str, bool]]:
    """(file, function, guarded) for every function under ``src/`` that calls ``served_file_response``: ``guarded`` is true when the
    function is a route whose decorator carries ``dependencies=[Depends(refuse_cross_site_get)]``."""
    found: list[tuple[str, str, bool]] = []
    root = Path(__file__).resolve().parent.parent / "src"
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            calls = any(
                isinstance(n, ast.Call)
                and (getattr(n.func, "attr", None) or getattr(n.func, "id", None)) == "served_file_response"
                for n in ast.walk(fn)
            )
            if not calls:
                continue
            guarded = any(
                isinstance(d, ast.Call)
                and any(
                    kw.arg == "dependencies" and "refuse_cross_site_get" in ast.unparse(kw.value)
                    for kw in d.keywords
                )
                for d in fn.decorator_list
            )
            found.append((str(path.relative_to(root.parent)), fn.name, guarded))
    return found


def test_every_route_that_serves_a_logged_file_is_guarded() -> None:
    """``served_file_response`` appends to diagnostics/runs.jsonl, so a route that calls it without the guard lets another site's page
    make the log grow (F3). A fourth such route fails here BY NAME, before anyone has planted a file for it."""
    callers = _served_file_response_callers()
    assert len(callers) >= 3, "the scan found fewer callers than the three F3 routes: it has stopped finding things"
    unguarded = [f"{f}::{name}" for f, name, ok in callers if not ok]
    assert not unguarded, f"call served_file_response only from a route with dependencies=[Depends(refuse_cross_site_get)]: {unguarded}"
