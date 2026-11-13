"""Every API route is either called by the shipped UI or listed with a reason (Lane M).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

On 2026-11-13 six climate fetchers and an Open-Meteo route were found built on the
server with no button anywhere: a feature an ordinary person cannot click is a
feature they do not have. ``scripts/route_callers.py`` reads every route from the
``src/api`` SOURCE and every URL literal from ``src/static`` and ``src/tui``;
``configs/routes_without_ui.tsv`` lists each route no UI file calls, with a class
and a reason. This file keeps the two in step:

* a NEW route nobody calls fails until it is wired or listed with its reason;
* a listed route that gained a caller (or was removed) fails until its row goes,
  so the list never claims a gap that is closed;
* the count of ``feature`` rows (a reader feature with no button) has a zero-slack
  ceiling: wiring one lowers it, and adding one is a visible edit here.

Source-only on purpose: a positive read of the shared ``src.api.main.app`` made a
route guard flaky in CI (CLAUDE.md, session rituals). The one test that imports the
app only checks that every live route is in the static set, a direction a missing
route cannot fail.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TSV = ROOT / "configs" / "routes_without_ui.tsv"

# Wire a feature, delete its row and lower this by one. Raising it means a new
# server feature shipped without a button: say why in the PR.
FEATURE_CEILING = 73

CLASSES = {"internal", "superseded", "feature"}


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "route_callers", ROOT / "scripts" / "route_callers.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("route_callers", mod)
    spec.loader.exec_module(mod)
    return mod


rc = _load_tool()


@pytest.fixture(scope="module")
def routes():
    return rc.build(("ui",))


@pytest.fixture(scope="module")
def rows() -> list[dict[str, str]]:
    lines = [
        ln for ln in TSV.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")
    ]
    return list(csv.DictReader(lines, delimiter="\t"))


def test_every_uncalled_route_is_listed(routes, rows):
    listed = {(r["method"], r["path"]) for r in rows}
    missing = sorted(
        f"{r.method} {r.path} ({r.file}:{r.line})"
        for r in routes
        if not r.callers and (r.method, r.path) not in listed
    )
    assert not missing, (
        "These routes have no caller in src/static or src/tui. Give each a button, or add it to "
        "configs/routes_without_ui.tsv with its class and reason (run scripts/route_callers.py):\n  "
        + "\n  ".join(missing)
    )


def test_every_listed_route_still_exists_and_is_still_uncalled(routes, rows):
    by_key = {(r.method, r.path): r for r in routes}
    stale = []
    for row in rows:
        r = by_key.get((row["method"], row["path"]))
        if r is None:
            stale.append(f"{row['method']} {row['path']}: no such route any more")
        elif r.callers:
            stale.append(f"{row['method']} {row['path']}: now called by {', '.join(r.callers)}")
    assert not stale, (
        "Remove these rows from configs/routes_without_ui.tsv (and lower FEATURE_CEILING for a feature):\n  "
        + "\n  ".join(stale)
    )


def test_rows_are_well_formed_and_unique(rows):
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["method"], row["path"])
        assert key not in seen, f"duplicate row {key}"
        seen.add(key)
        assert row["class"] in CLASSES, f"{key}: class {row['class']!r} not in {sorted(CLASSES)}"
        assert row["reason"].strip(), f"{key}: a row needs its reason"
        if row["class"] == "feature":
            assert row["value"] in {"1", "2", "3"}, (
                f"{key}: a feature carries its value to a reader (1-3)"
            )
            assert row["surface"].strip(), (
                f"{key}: a feature names the surface its button belongs on"
            )


def test_feature_ceiling_is_exact(rows):
    n = sum(1 for r in rows if r["class"] == "feature")
    assert n <= FEATURE_CEILING, (
        f"{n} reader features without a button, ceiling {FEATURE_CEILING}: wire one instead of listing it"
    )
    assert n == FEATURE_CEILING, (
        f"{n} features listed: lower FEATURE_CEILING to {n} (zero slack, or the ratchet does nothing)"
    )


def test_static_route_set_covers_the_live_app():
    """Every route the app serves is one the source reader found (so none hides from the sweep)."""
    from fastapi.routing import APIRoute

    from src.api.main import app

    def flat(rs, prefix=""):
        for r in rs:
            if type(r).__name__ == "_IncludedRouter":
                c = r.include_context
                yield from flat(r.original_router.routes, prefix + (c.prefix or ""))
            else:
                yield r, prefix

    static = {(r.method, r.path) for r in rc.collect_routes()}
    live = {
        (m, p + r.path)
        for r, p in flat(app.routes)
        if isinstance(r, APIRoute)
        for m in r.methods - {"HEAD", "OPTIONS"}
    }
    unseen = sorted(live - static)
    assert not unseen, (
        f"routes the source reader cannot see (register them with @router.<verb>): {unseen}"
    )


# --- the matcher itself: the shapes that made the first pass wrong --------------------------


def _calls(path: str, js: str) -> bool:
    fl = rc._FileLits(
        "x.js", [x for x in rc._js_literals(js) if "/" in x], set(rc._js_literals(js))
    )
    fl.tokens |= {w for x in rc._js_literals(js) for w in rc._NESTED_WORD.findall(x)}
    return rc._calls(path, fl)


def test_an_apostrophe_in_a_comment_does_not_hide_later_calls():
    js = '// don\'t trip\nconst x = 1;\napi("/api/ai/prompts");'
    assert _calls("/api/ai/prompts", js)


def test_a_regex_literal_with_a_quote_does_not_hide_later_calls():
    js = "s.replace(/['\"`]/g, '');\napi(`/api/ai/prompts/${id}`);"
    assert _calls("/api/ai/prompts/{prompt_id}", js)


def test_a_longer_path_is_not_its_own_prefix():
    assert not _calls("/api/llm/pull", 'api("/api/llm/pull/status")')


def test_concatenated_shapes_count():
    assert _calls(
        "/api/custody/{item_id}/verify", 'api("/api/custody/" + encodeURIComponent(id) + "/verify")'
    )
    assert _calls(
        "/api/events/feeds/user/{key}", 'api("/api/events/feeds/user/" + k, {method: "DELETE"})'
    )
    assert _calls(
        "/api/integrity/collapse/apply",
        'api("/api/integrity/collapse/" + (a ? "apply" : "revert"))',
    )
    assert not _calls(
        "/api/integrity/collapse/apply_all",
        'api("/api/integrity/collapse/" + (a ? "apply" : "revert"))',
    )


def test_a_hole_stands_for_a_named_segment_only_when_the_name_is_spelled():
    js = 'const jobs = ["keyword-triage"]; api(`/api/diagnostics/${job}/status`);'
    assert _calls("/api/diagnostics/keyword-triage/status", js)
    assert not _calls("/api/diagnostics/card-audit/status", js)


def test_a_base_handed_across_files_is_composed():
    a = rc._FileLits("a.js", ["/api/law/documents/" + rc._HOLE], set())
    b = rc._FileLits("b.js", [rc._HOLE + "/versions"], set())
    assert rc._composed("/api/law/documents/{document_id}/versions", [a, b])
    # a bare "/verify" elsewhere does not vouch for a route whose base sits in another file
    c = rc._FileLits("c.js", ["/api/reports/evidence"], set())
    d = rc._FileLits("d.js", ["/verify"], set())
    assert not rc._composed("/api/reports/evidence/verify", [c, d])
