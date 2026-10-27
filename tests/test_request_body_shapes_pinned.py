"""The request-body shapes of the state-changing operations are pinned by route (audit 0.5.0 item 35, item 3; R315).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``docs/SECURITY.md`` names three layers between a cross-site page and a state-changing request: the Host allow-set, the Origin / Referer
middleware, and FastAPI's strict JSON body check. The third applies only to a route that DECLARES a required JSON body. Measured on
2026-10-27 (``/mnt/project-files/audit-0.5.0/proposal-raw-body-content-type-2026-10-27.md``), the 317 POST / PUT / PATCH / DELETE operations of
the schema are:

* 165 declare an ``application/json`` body (the strict check applies);
* 148 declare none; THREE of them read the body themselves, so a ``text/plain`` or form POST reaches the parser and only the Origin layer
  stands before it: ``POST /api/claims/trail-bundle/verify`` (``await request.body()``, a pure check) and the two corpus-writing uploads
  ``POST /api/newsletters/import`` and ``POST /api/documents/pdf/upload`` (``await request.form()``: multipart in practice, declared as
  nothing; measured 2026-10-27 to answer 200 to NO body at all and to create the "Imported newsletters (.eml)" source row on an empty POST);
* 4 declare ``multipart/form-data``, a "simple request" type a browser sends cross-site without a preflight.

A new route can add a SIXTH shape (a raw-stream reader, a ``text/plain`` model, a form body) without changing any count above and
without any other test noticing. This file fails by NAME when that happens, so whoever adds it decides, in the PR, whether the Origin
layer alone is enough for it, and records the answer in the table below.

What it pins: the multipart set by route; the raw-body readers by function (an AST scan of ``src/`` for ``.body()`` / ``.stream()`` /
``.form()`` / ``.json()`` on a name that is a request); every operation's declared shape being one of the three; and the per-shape counts
as floors on both install profiles (R283).

Stated limits: the scan sees a request read through a variable named ``request`` or ``req`` (the names the app uses); a handler that
builds a ``starlette.requests.Request`` from a scope, or reads ``receive`` directly, is invisible to it. A route that declares a JSON body
but is never given one (every field optional) is a JSON-shape route here; its behaviour with no body is the Origin ratchet's business
(``tests/test_origin_guard_every_route.py``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.test_get_routes_side_effects import _analysis_extra_installed

_METHODS = ("post", "put", "patch", "delete")
_ROOT = Path(__file__).resolve().parent.parent

# (METHOD, path) -> why this route takes a multipart body. A fifth entry is a new simple-request surface: add it only with the sentence that
# says what bounds the upload and what the Origin layer is the only guard for.
_MULTIPART: dict[tuple[str, str], str] = {
    ("POST", "/api/catalog/import"): "a source-catalogue sheet upload; a missing file part answers 200 with zero rows",
    ("POST", "/api/diagnostics/source-qualification-merge"): "per-instance qualification exports; every part is optional, so an empty POST answers 200 (it computes, it writes no file)",
    ("POST", "/api/commodities/{symbol}/prices/import-csv"): "a price CSV, bounded read of 16 MiB; the commodity router needs the [analysis] extra",
    ("POST", "/api/verify/image-metadata"): "an image for EXIF extraction, bounded read of 50 MiB; no write",
}
# Listed because the install without the `[analysis]` extra (numpy, pandas, scipy, sklearn, statsmodels) does not mount it.
_NEEDS_ANALYSIS_EXTRA = {("POST", "/api/commodities/{symbol}/prices/import-csv")}

# "file::function" -> the route it serves and why a raw body is read there. The route is a "declares no body" operation in the schema
# (that is how a raw reader hides), which test_each_raw_reader_serves_a_route_that_declares_no_body pins.
_RAW_BODY_READERS: dict[str, tuple[tuple[str, str], str]] = {
    "src/api/claims.py::verify_claim_trail_bundle": (
        ("POST", "/api/claims/trail-bundle/verify"),
        "a trail bundle is posted as the raw ZIP body; a pure check (no database, no write) bounded at MAX_VERIFY_BYTES. Accepts any Content-Type "
        "(measured 2026-10-27: text/plain, form and multipart all reach the parser); proposal to answer 415 is in the audit folder, not decided",
    ),
    "src/api/ingestion.py::import_newsletters": (
        ("POST", "/api/newsletters/import"),
        "local .eml files ingested anonymised into the corpus; parses request.form() itself, so the schema shows no body and any Content-Type "
        "or none answers 200 (an empty POST still gets-or-creates the 'Imported newsletters (.eml)' source row); per-file bound _MAX_EML_BYTES; "
        "a declared `files: list[UploadFile]` would put it in the multipart group (proposal, not decided)",
    ),
    "src/api/ingestion.py::upload_pdfs": (
        ("POST", "/api/documents/pdf/upload"),
        "local PDFs ingested into the corpus; parses request.form() itself, any Content-Type or none answers 200; per-file bound _MAX_PDF_BYTES "
        "(200 MiB); same declared-UploadFile proposal as the newsletter import",
    ),
}

# Per-shape counts on 2026-10-27 (main d165a4229), as FLOORS: new routes are welcome, fewer means the finder stopped seeing routes.
# Full install: 165 JSON, 148 none, 4 multipart = 317. Without the [analysis] extra: 156, 147, 3 = 306 (the commodity, statistical-analysis and
# article-similarity routers are disabled there; one of the missing 11 is the multipart price import). Measured with the five packages blocked.
_FLOOR_FULL = {"json": 165, "none": 148, "multipart": 4}
_FLOOR_CORE_ONLY = {"json": 156, "none": 147, "multipart": 3}
_FLOOR = _FLOOR_FULL if _analysis_extra_installed() else _FLOOR_CORE_ONLY

_REQUEST_NAMES = frozenset({"request", "req", "http_request"})
_READ_METHODS = frozenset({"body", "stream", "form", "json"})


def _shape(op: dict) -> str:
    """``json`` / ``none`` / ``multipart`` for a schema operation, else the sorted content types joined (an unknown shape)."""
    body = op.get("requestBody")
    if not body:
        return "none"
    kinds = sorted(body.get("content", {}))
    if kinds == ["application/json"]:
        return "json"
    if kinds == ["multipart/form-data"]:
        return "multipart"
    return "+".join(kinds) or "empty-body-declaration"


def _operations() -> list[tuple[str, str, str]]:
    """(METHOD, path, shape) for every state-changing operation of the app's own schema."""
    from src.api.main import app

    out = []
    for path, ops in app.openapi()["paths"].items():
        for method, op in ops.items():
            if method in _METHODS:
                out.append((method.upper(), path, _shape(op)))
    return sorted(out)


def _raw_readers(root: Path) -> set[str]:
    """``file::function`` for every function under ``root`` that reads a request's body, stream or form."""
    found: set[str] = set()
    for f in sorted((root / "src").rglob("*.py")):
        if "static" in f.relative_to(root).parts:
            continue
        found |= _raw_readers_in(f.read_text(encoding="utf-8"), f.relative_to(root).as_posix())
    return found


def _raw_readers_in(source: str, name: str) -> set[str]:
    found: set[str] = set()
    tree = ast.parse(source)

    def walk(node: ast.AST, enclosing: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else enclosing
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in _READ_METHODS
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id in _REQUEST_NAMES
            ):
                found.add(f"{name}::{enclosing or '<module>'}")
            walk(child, inner)

    walk(tree, None)
    return found


@pytest.fixture(scope="module")
def operations():
    return _operations()


def test_every_state_changing_operation_declares_one_of_the_three_shapes(operations):
    odd = sorted((m, p, s) for m, p, s in operations if s not in ("json", "none", "multipart"))
    assert not odd, (
        "these operations declare a request body that is none of JSON, nothing or multipart/form-data (a text/plain model, a form body, "
        "a raw stream type): decide whether the Origin layer alone is enough for each, then teach this file the new shape. "
        f"{odd}"
    )


def test_the_multipart_operations_are_exactly_the_listed_ones(operations):
    got = {(m, p) for m, p, s in operations if s == "multipart"}
    want = set(_MULTIPART) if _analysis_extra_installed() else set(_MULTIPART) - _NEEDS_ANALYSIS_EXTRA
    assert got == want, (
        f"multipart operations not listed in _MULTIPART: {sorted(got - want)}; listed but not multipart or not mounted: {sorted(want - got)}"
    )


def test_the_per_shape_counts_have_not_fallen(operations):
    counts = {s: sum(1 for _m, _p, x in operations if x == s) for s in ("json", "none", "multipart")}
    low = {s: (counts[s], _FLOOR[s]) for s in _FLOOR if counts[s] < _FLOOR[s]}
    assert not low, (
        f"fewer operations of a body shape than on 2026-10-27 (found, floor): {low} -- routes were removed (lower the floor, with a reason) "
        "or the schema finder stopped seeing them"
    )


def test_the_raw_body_readers_are_exactly_the_listed_ones():
    got = _raw_readers(_ROOT)
    assert got == set(_RAW_BODY_READERS), (
        f"functions reading a request's raw body that are not listed in _RAW_BODY_READERS: {sorted(got - set(_RAW_BODY_READERS))}; "
        f"listed but no longer reading one: {sorted(set(_RAW_BODY_READERS) - got)}. A raw reader sits behind the Origin layer alone: say in "
        "the table what bounds it and whether it writes."
    )


def test_each_raw_reader_serves_a_route_that_declares_no_body(operations):
    shapes = {(m, p): s for m, p, s in operations}
    for func, (route, reason) in _RAW_BODY_READERS.items():
        assert reason.strip(), func
        assert shapes.get(route) == "none", (
            f"{func} is listed as serving {route}, which the schema shows with shape {shapes.get(route)!r}; a raw reader hides in the "
            "'declares no body' group, so a change here means the route or the table moved"
        )


def test_the_scanner_finds_a_raw_reader_and_only_a_raw_reader():
    """Liveness, so a green scan is not a blind one: the readers it must see, and the uses it must not."""
    seen = _raw_readers_in(
        "async def handler(request):\n    data = await request.body()\n"
        "async def streaming(req):\n    async for chunk in req.stream():\n        pass\n"
        "async def forms(request):\n    return await request.form()\n"
        "async def js(request):\n    return await request.json()\n",
        "x.py",
    )
    assert seen == {"x.py::handler", "x.py::streaming", "x.py::forms", "x.py::js"}, seen
    quiet = _raw_readers_in(
        "def a(request):\n    return request.url.path\n"
        "def b(response):\n    return response.json()\n"  # an HTTP client's reply, not a request
        "def c(request):\n    return request.headers.get('x')\n",
        "y.py",
    )
    assert quiet == set(), quiet


def test_the_real_scan_runs_over_real_files():
    """The AST scan of ``src/`` must be looking at files: it finds the one known reader, so an empty glob cannot pass the exact-set test."""
    assert "src/api/claims.py::verify_claim_trail_bundle" in _raw_readers(_ROOT)
