"""The Observatory's ranked-table drill-through — audit §4.3 (P0).

``app-observatory.js`` used to pass a galaxy's curated cluster LABEL
(``hit.name`` / ``g.name`` / ``_obs.view.focus.name``) straight into
``openAnalysisFor`` as a literal full-text query. A cluster label is not text
that appears in articles: hand-verified on the live corpus, "Elections &
democracy" (the corpus's TOP galaxy by mentions) returned zero articles that
way, and "Public finance" returned 19 -- a populated, plausible, WRONG article
set presented as that galaxy's evidence (see the audit + FIX_BRIEF.md §4.3).

This file pins the fix: the drill-through now resolves the galaxy's REAL
membership (``/api/insights/supergroups``'s own ``members``, the same rows the
galaxy's numbers are computed from) into an article-id set via the existing
set-algebra endpoint (``/api/insights/corpus-algebra``, ``op=union`` -- the
same resolver the Keywords-subtab Combine picker already uses via
``openAnalysisForIds``), and opens THAT set. A galaxy that cannot be resolved
fails closed: nothing opens, and a toast names why.

Two layers, because a source assertion alone cannot prove the fix RUNS
correctly and a behavioural assertion alone cannot prove the OLD bug's three
exact call sites are gone (a fix could add a correct new path beside the old
broken one and still regress):

  1. Source-level: the three broken call sites (audit's app-observatory.js
     lines 406/444/484) are gone; the real membership + set-algebra path is in
     the code.
  2. Behavioural: the extracted functions are DRIVEN under node with a mocked
     ``api``/``toast``/``openAnalysisForIds``, proving the terms sent to
     corpus-algebra are the galaxy's real member keywords (never its name),
     that a resolved galaxy opens the analysis window on the resolved ids, and
     that an unresolvable galaxy opens NOTHING and toasts an error instead.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import subprocess
import urllib.parse
from pathlib import Path

import pytest

from tests.js_source_helper import (
    assert_absent,
    assert_present,
    function_source,
    read_static,
)

_ROOT = Path(__file__).resolve().parents[1]


def _obs_js() -> str:
    return read_static("app-observatory.js")


# ---------------------------------------------------------------------------
# 1. Source-level: the exact broken call sites are gone; the real path is in.
# ---------------------------------------------------------------------------

def test_the_three_label_as_query_call_sites_are_gone() -> None:
    """The audit's exact defect lines: a galaxy's curated NAME handed to
    ``openAnalysisFor`` as a literal full-text query, from the table button,
    the canvas click, and the keyboard Enter/Space handler."""
    js = _obs_js()
    assert_absent(js, "openAnalysisFor(hit.name",
                   why="the canvas click must resolve real membership, not the label")
    assert_absent(js, "openAnalysisFor(b.dataset.obsOpen",
                   why="the table row must resolve real membership, not the label")
    assert_absent(js, "openAnalysisFor(_obs.view.focus.name",
                   why="the keyboard Enter/Space path must resolve real membership, not the label")
    # No other label-as-query path may have been left in reach of a click either.
    assert_absent(js, "openAnalysisFor(g.name",
                   why="no drill-through may pass the curated cluster label as a search query")


def test_the_membership_resolver_and_set_algebra_call_are_present() -> None:
    js = _obs_js()
    assert_present(js, "_obsOpenGalaxy", why="the replacement resolver must exist")
    assert_present(js, "/api/insights/supergroups",
                    why="must read the galaxy's REAL members, the same rows its own numbers use")
    assert_present(js, "/api/insights/corpus-algebra",
                    why="must resolve real member keywords to a real article-id set, "
                        "the same substrate openAnalysisForIds's other callers use")
    assert_present(js, "openAnalysisForIds",
                    why="must open the EXACT resolved id set, not a fresh text search")
    # Every former call site must now route through the resolver.
    assert_present(js, "_obsOpenGalaxy(hit.id, hit.name)")
    assert_present(js, "_obsOpenGalaxy(b.dataset.obsId, b.dataset.obsName)")
    assert_present(js, "_obsOpenGalaxy(_obs.view.focus.id, _obs.view.focus.name)")


def test_the_table_button_carries_the_galaxy_id_not_only_its_label() -> None:
    """The old markup carried only the label in ``data-obs-open`` -- there was no id to
    resolve against. The button must now carry the galaxy's real id."""
    js = _obs_js()
    assert_present(js, 'data-obs-id="${esc(g.id)}"',
                    why="the row must carry the galaxy id the resolver needs")
    assert_absent(js, "data-obs-open=", why="the label-only attribute must be gone")


def test_a_prior_commit_had_the_defect_at_these_exact_sites() -> None:
    """Prove the assertions above are not vacuous: the CURRENT branch's own parent
    commit (before this fix) really did carry all three broken call sites, so
    ``test_the_three_label_as_query_call_sites_are_gone`` is a real regression
    guard and not a check that was always true."""
    proc = subprocess.run(
        ["git", "show", "HEAD:src/static/app-observatory.js"],
        capture_output=True, text=True, cwd=str(_ROOT), check=True,
    )
    old = proc.stdout
    assert "openAnalysisFor(hit.name" in old
    assert "openAnalysisFor(b.dataset.obsOpen" in old
    assert "openAnalysisFor(_obs.view.focus.name" in old
    assert "_obsOpenGalaxy" not in old, "HEAD must predate the fix for this to be a real proof"


# ---------------------------------------------------------------------------
# 2. Behavioural: drive the extracted resolver under node with mocked I/O.
# ---------------------------------------------------------------------------

def _harness_source() -> str:
    js = _obs_js()
    # function_source drops the `async` keyword (js_source_helper's decl-finder
    # matches on "function NAME(", which starts one token late for an async
    # declaration) -- restore it so `await` inside the body is legal syntax.
    member_terms = function_source(js, "_obsMemberTerms")
    load_sgs = "async " + function_source(js, "_obsLoadSupergroups")
    open_galaxy = "async " + function_source(js, "_obsOpenGalaxy")
    return "\n".join([
        "'use strict';",
        "let _obsSgById = null;",
        "global.window = { OOI18N: { t: (s) => s } };",
        "global.OOI18N = global.window.OOI18N;",
        member_terms,
        load_sgs,
        open_galaxy,
        _HARNESS_DRIVER,
    ])


_HARNESS_DRIVER = r"""
let toastCalls, apiCalls, openCalls, apiImpl;
function toast(msg, kind) { toastCalls.push({msg: msg, kind: kind}); }
function openAnalysisForIds(ids, label, opts) { openCalls.push({ids: ids, label: label, opts: opts}); }
async function api(url) { apiCalls.push(url); return apiImpl(url); }

async function scenario(id, name, impl) {
  _obsSgById = null;
  toastCalls = []; apiCalls = []; openCalls = [];
  apiImpl = impl;
  await _obsOpenGalaxy(id, name);
  return { toastCalls: toastCalls, apiCalls: apiCalls, openCalls: openCalls };
}

(async () => {
  const out = {};

  // A resolvable galaxy: real members (one family term + one ring's cross-
  // language forms), never the group's own display name.
  out.success = await scenario(5, "Elections & democracy", (url) => {
    if (url.indexOf("/api/insights/supergroups") === 0) {
      return { supergroups: [{
        id: 5, name: "Elections & democracy",
        members: [
          { normalized: "voting", ring_members: ["en:voting", "en:vote", "fr:vote"] },
          { normalized: "referendum" },
        ],
      }] };
    }
    if (url.indexOf("/api/insights/corpus-algebra") === 0) {
      return { article_ids: [11, 22, 33], op: "union" };
    }
    throw new Error("unexpected url " + url);
  });

  // An id no longer present in the supergroups payload -> zero resolvable terms.
  out.missing = await scenario(999, "Ghost galaxy", (url) => {
    if (url.indexOf("/api/insights/supergroups") === 0) return { supergroups: [] };
    throw new Error("unexpected url " + url);
  });

  // The membership fetch itself fails (offline API hiccup, bad response, ...).
  out.apiError = await scenario(5, "Elections & democracy", () => {
    throw new Error("network down");
  });

  process.stdout.write(JSON.stringify(out));
})();
"""


def _run_harness(tmp_path: Path) -> dict:
    script = tmp_path / "obs_drillthrough_harness.js"
    script.write_text(_harness_source(), encoding="utf-8")
    proc = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def harness_result(tmp_path_factory) -> dict:
    return _run_harness(tmp_path_factory.mktemp("obs_dt"))


def test_resolved_galaxy_opens_the_real_membership_ids_not_the_label(harness_result) -> None:
    r = harness_result["success"]
    assert r["toastCalls"] == [], "a resolvable galaxy must not fail-close"
    assert len(r["openCalls"]) == 1, "must open the analysis window exactly once"
    call = r["openCalls"][0]
    assert call["ids"] == [11, 22, 33], "must open the EXACT ids corpus-algebra resolved"
    assert call["label"] == "Elections & democracy", (
        "the label on the opened tab must match the label shown in the table (brief item 3)"
    )
    assert call["opts"] == {"source": "observatory"}

    # The terms sent to corpus-algebra must be the galaxy's REAL members --
    # never its own curated display name (the exact defect this closes).
    algebra_calls = [u for u in r["apiCalls"] if u.startswith("/api/insights/corpus-algebra")]
    assert len(algebra_calls) == 1
    qs = urllib.parse.urlparse(algebra_calls[0]).query
    terms = urllib.parse.parse_qs(qs)["terms"][0].split(",")
    assert set(terms) == {"voting", "vote", "referendum"}, terms
    assert "Elections & democracy" not in terms, (
        "the curated cluster label must never be sent as a search term"
    )
    assert urllib.parse.parse_qs(qs)["op"][0] == "union"

    sg_calls = [u for u in r["apiCalls"] if u.startswith("/api/insights/supergroups")]
    assert len(sg_calls) == 1, "membership must be read from the real supergroups endpoint"


def test_unresolvable_galaxy_fails_closed_no_window_opens(harness_result) -> None:
    r = harness_result["missing"]
    assert r["openCalls"] == [], "an unresolved galaxy must open NOTHING -- never a fallback search"
    assert len(r["toastCalls"]) == 1
    assert r["toastCalls"][0]["kind"] == "err"


def test_a_membership_fetch_failure_also_fails_closed(harness_result) -> None:
    r = harness_result["apiError"]
    assert r["openCalls"] == [], "an API failure must never fall back to a text-query guess"
    assert len(r["toastCalls"]) == 1
    assert r["toastCalls"][0]["kind"] == "err"
