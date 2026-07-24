"""
Repository security/hygiene invariants (codifies the audit's positive controls, F-008).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

These cheap, fast checks turn audit observations into guardrails: no hardcoded secrets
in live code, the quarantined fabricated modules are imported by nothing live, and every
in-app doc the API offers actually exists on disk. If any regresses, CI fails.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"

# Conservative: a secret-like NAME assigned a non-trivial STRING LITERAL. Env reads,
# ORM Column defaults, descriptions and placeholders are excluded so this stays
# low-false-positive (it is a guardrail, not a scanner).
_SECRET_RE = re.compile(
    r"\b(password|passwd|secret|api_key|apikey|access_token|auth_token|private_key)\b"
    r"\s*=\s*['\"][A-Za-z0-9/+_\-]{8,}['\"]",
    re.IGNORECASE,
)
_SECRET_ALLOW = (
    "getenv",
    "environ",
    "os.",
    "Column",
    "description",
    "example",
    "placeholder",
    "field(",
    "default=",
    "None",
    "self.",
)


def _live_py_files() -> list[Path]:
    return [p for p in _SRC.rglob("*.py") if "__pycache__" not in p.parts]


def _ui_source() -> str:
    """The full UI source = index.html + the externalised app.js + app.css (audit
    PR H decomposed index.html into cached static assets). Invariants that grep the
    UI read all three so the assertions are a MOVE, not a loss; app.js/app.css are
    appended after the markup, so markup-scoped splits still resolve to the markup
    region while whole-source / JS-marker-scoped assertions see the script too."""
    base = _SRC / "static"
    parts = [(base / "index.html").read_text(encoding="utf-8")]
    for extra in ("app.js", "app.css"):
        p = base / extra
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_revision_anomalies_statistics_surface():
    """The merged /api/stats/revision-anomalies endpoint (the reliable-memory check) is
    reachable from Settings → Statistics: a 'Check revision anomalies' button + a
    #statfig-revisions box, and a loadRevisionAnomalies() that fetches the endpoint and
    renders the flagged revisions WITH the honesty envelope (method + innocent-twin caveat)
    visible. Browser-unverified per fork-3 — node-checked + grep-guarded here."""
    ui = _ui_source()
    assert 'id="statfig-revisions"' in ui, "the revision-anomalies output box must exist"
    assert "loadRevisionAnomalies()" in ui, "the button must call loadRevisionAnomalies"
    assert "function loadRevisionAnomalies" in ui, "the handler must be defined"
    assert "/api/stats/revision-anomalies" in ui, "it must call the merged endpoint"
    # The honesty envelope (method + innocent-twin caveat) must be rendered, never dropped.
    assert "d.caveat" in ui and "d.method" in ui, "the method + caveat must render"


def test_stat_time_series_chart_surface():
    """Phase B3: the Settings → Statistics panel charts a stored series over time using the
    merged /api/stats/figures/series feed + the node-tested ooViz.statChartGeometry — a
    comparability segment is its own path (never joined), a gap is a break. Browser-unverified
    per fork-3 — node-checked + grep-guarded here."""
    base = _SRC / "static"
    html = (base / "index.html").read_text(encoding="utf-8")
    app = (base / "app.js").read_text(encoding="utf-8")
    ooviz = (base / "ooviz.js").read_text(encoding="utf-8")
    # ooViz is loaded as a global BEFORE app.js (so window.ooViz exists when app.js runs).
    assert "/static/ooviz.js" in html, "ooviz.js must be loaded by index.html"
    assert html.index("/static/ooviz.js") < html.index("/static/app.js"), "ooviz before app.js"
    # The chart controls + container.
    assert 'id="statfig-chart"' in html, "the chart container must exist"
    assert 'id="statfig-view-area"' in html, "the area input must exist"
    assert "renderStatChart()" in html, "the Chart button must call renderStatChart"
    # The handler draws the merged feed through the merged geometry helper, caveat visible.
    assert "function renderStatChart" in app, "the handler must be defined"
    assert "/api/stats/figures/series" in app, "it must fetch the chart-series feed"
    assert "ooViz.statChartGeometry" in app, "it must draw via the node-tested geometry helper"
    assert "d.caveat" in app, "the honesty caveat must render"
    # The geometry helper is exported by ooViz (node-tested separately).
    assert "function statChartGeometry" in ooviz, "statChartGeometry must be defined"
    assert "statChartGeometry: statChartGeometry" in ooviz, "it must be exported in the API"


def test_stats_choropleth_feed_and_data_layer():
    """§5B Phase C: the choropleth feed. store.map_figures returns ONE latest-vintage cell
    per ref_area for a series (single-producer; several producers FLAG multi_producer and
    are NEVER averaged), the /api/stats/map endpoint exposes it, and the pure
    ooViz.choroplethData / symbolRadii apply the normalized-only honesty gate (a different
    unit/base-year/SA basis is no-data, never recoloured; a level is proportional symbols).
    The frontend ooMap render is the browser-deferred follow-on; the data layer is verified
    here (the store CI test + the ooViz node test) and grep-guarded for regression."""
    store_src = (_SRC / "stats" / "store.py").read_text(encoding="utf-8")
    api_src = (_SRC / "api" / "stats.py").read_text(encoding="utf-8")
    ooviz = (_SRC / "static" / "ooviz.js").read_text(encoding="utf-8")
    # The store feed: one cell per area, single-producer, never averaged, with an iso2 bridge.
    assert "def map_figures(" in store_src, "the choropleth store feed is missing"
    assert "multi_producer" in store_src, "several producers must be flagged, not averaged"
    assert "never averages producers" in store_src, "the no-average caveat must travel"
    assert "to_iso2" in store_src, "each cell must carry an iso2 bridge for the map renderer"
    # The endpoint.
    assert '@router.get("/map")' in api_src, "the /api/stats/map endpoint is missing"
    assert "map_figures(" in api_src, "the endpoint must call the store feed"
    # The pure honesty data layer (node-tested in tests/ooviz_node_test.js).
    assert "function choroplethData" in ooviz, "the comparability gate must exist"
    assert "function symbolRadii" in ooviz, "the levels->symbols companion must exist"
    assert "choroplethData: choroplethData" in ooviz and "symbolRadii: symbolRadii" in ooviz, (
        "both must be exported in the ooViz API"
    )


def test_stats_choropleth_map_surface():
    """§5B Phase C frontend: the Settings → Statistics panel maps an indicator by country
    through the ONE ooMap component + the node-tested ooViz.choroplethData gate — incomparable
    basis → no-data (never recoloured), a level refuses the choropleth, multi_producer flagged,
    the cells' backend iso2 bridge keys the map. Browser-unverified per fork-3 (node-checked +
    grep-guarded here)."""
    base = _SRC / "static"
    html = (base / "index.html").read_text(encoding="utf-8")
    app = (base / "app.js").read_text(encoding="utf-8")
    # Controls + host in the Statistics panel.
    assert 'id="statfig-map"' in html, "the map host must exist"
    assert 'id="statfig-map-level"' in html, "the level (count/total) toggle must exist"
    assert "renderStatMap()" in html, "the Map button must call renderStatMap"
    # The handler reuses ooMap + the node-tested gate, keyed by the backend iso2.
    assert "function renderStatMap" in app, "the handler must be defined"
    assert "/api/stats/map" in app, "it must fetch the choropleth feed"
    assert "ooViz.choroplethData" in app, "it must apply the comparability gate"
    assert "ooMap(host" in app, "it must render through the one ooMap component"
    assert "c.iso2" in app or "iso2By" in app, "it must key the map on the backend iso2 bridge"


def test_live_language_switch_rerenders_cldr_name_surfaces():
    """Field test 2026-06-19 #16: country/continent names (CLDR-derived at render time)
    must update when the UI language changes, not only on a page refresh. i18n.setLang
    emits an 'oo:langchange' event; app.js listens and re-renders the map (+ sources)."""
    base = _SRC / "static"
    i18n = (base / "i18n.js").read_text(encoding="utf-8")
    app = (base / "app.js").read_text(encoding="utf-8")
    assert "oo:langchange" in i18n, "setLang no longer emits the language-change event"
    assert 'CustomEvent("oo:langchange"' in i18n
    assert 'addEventListener("oo:langchange"' in app, "app.js does not listen for the lang switch"
    # The listener must re-render the CLDR-name surface (the world map).
    listener = app.split('addEventListener("oo:langchange"', 1)[1][:400]
    assert "_renderOoMapDim" in listener, "lang switch no longer re-renders the map names"


def test_analysis_window_per_query_spawns_tabs_and_retires_corpus_modal():
    """Field test 2026-06-19 THEME-3: a search/Lead/keyword spawns a NAMED, closeable,
    persisted analysis TAB over the one #an surface (multi-document workspace), with an
    Overview screen; the legacy #corpus-win modal is RETIRED (openCorpus now spawns a
    tab). One analysis surface (ruling: 'retire both')."""
    base = _SRC / "static"
    app = (base / "app.js").read_text(encoding="utf-8")
    html = (base / "index.html").read_text(encoding="utf-8")
    # The spawned-tab strip + machinery.
    assert 'id="an-tabstrip"' in html, "the analysis-tab strip is missing"
    for fn in ("function _anSpawn(", "function _anActivate(", "function _anCloseTab(",
               "function _anRenderStrip(", "function _anRestoreTabs("):
        assert fn in app, f"the analysis-tab machinery is incomplete: {fn}"
    assert "let _anTabs" in app and "_AN_TABS_KEY" in app, "tabs must persist across sessions"
    # openCorpus retired -> routes to a spawned analysis tab (one surface).
    assert "function openCorpus(term) { openAnalysisFor(term); }" in app, (
        "#corpus-win must be retired — openCorpus now spawns an analysis tab"
    )
    assert "document.getElementById(\"corpus-win\").showModal()" not in app, (
        "the legacy keyword modal must no longer be shown"
    )
    # The Overview screen (generic per-card landing, Q1).
    assert '<button class="active" data-tab="overview">Overview</button>' in html
    assert "function renderAnOverview(" in app and 'id="an-overview"' in html


def test_trends_render_as_clickable_bar_graphs():
    """Field test 2026-06-19 #25: the rising/top Trends are clickable horizontal BAR
    graphs (bar length ∝ the real count/rate, value shown — no score), and clicking a
    bar opens the unified analysis window (trend + worldwide spread)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function termBarsHtml(terms, valueOf, labelOf)" in app
    assert 'termBarsHtml(rising.terms' in app and 'termBarsHtml(top.terms' in app, (
        "the rising/top Trends must render as bar graphs (#25)"
    )
    bars = app.split("function termBarsHtml(", 1)[1].split("\n    }", 1)[0]
    assert "openAnalysisFor(" in bars, "clicking a trend bar must open the analysis window"


def test_world_map_fullscreen_uses_the_fullscreen_api():
    """Field test 2026-06-19 #12 (THEME-2): the map ⛶ control uses the real Fullscreen
    API (with a CSS fallback + Esc/click exit), not just a CSS .mm-big toggle."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    big = app.split('else if (a === "big")', 1)[1].split("else {", 1)[0]
    assert "requestFullscreen" in big and "exitFullscreen" in big, (
        "the map fullscreen control must use the Fullscreen API"
    )
    assert 'addEventListener("fullscreenchange"' in app, "must reset the ⛶ glyph on exit"
    # #15: offline-map regions are a LIST (per-row Download), not a <select> dropdown.
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="osm-region-list"' in html and '<select id="osm-region"' not in html, (
        "offline-map regions must be a list, not a dropdown (#15)"
    )
    assert "osm-region-row" in app, "each region row renders with a direct Download button"


def test_prune_unused_keywords_action_is_discoverable():
    """Keyword reduction (2026-06-21): a junk-removal GC (delete keywords with zero
    mentions) must exist + be discoverable. It is cleanup, NOT the rejected arbitrary
    cap — a keyword with any mention is never touched. The engine report surfaces the
    prunable bucket so the count is explainable first."""
    store = (_SRC / "analytics" / "store.py").read_text(encoding="utf-8")
    assert "def prune_orphan_keywords(" in store, "the orphan-keyword GC must exist"
    api = (_SRC / "api" / "insights.py").read_text(encoding="utf-8")
    assert "/prune-keywords" in api, "the prune endpoint must be registered"
    er = (_SRC / "analytics" / "engine_report.py").read_text(encoding="utf-8")
    assert "mention_distribution" in er, "the report must surface the mention distribution"
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function pruneKeywords(" in app and "/api/insights/prune-keywords" in app
    # The one-click "clean up" chains re-index THEN prune (the recommended order) so
    # the operator runs one action, reusing the confirm-free cores.
    assert "function cleanupKeywords(" in app, "the one-click clean-up convenience must exist"
    assert "_reindexAllLoop(" in app and "_pruneCore(" in app, "it must reuse the shared cores"
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    assert "cleanupKeywords(" in html, "the one-click clean-up button must be discoverable"


def test_reindex_whole_corpus_action_is_discoverable():
    """§3.F (autonomous 2026-06-21): a FORCE re-index of ALL articles must exist and
    be discoverable — the drain for stale metadata an old engine produced (e.g.
    pre-markup-strip CSS keywords). backfill_corpus only touches un-indexed articles,
    so a dedicated paged reindex_all_batch + endpoint + Settings button are needed."""
    store = (_SRC / "analytics" / "store.py").read_text(encoding="utf-8")
    assert "def reindex_all_batch(" in store, "a force-all re-index batch helper must exist"
    api = (_SRC / "api" / "insights.py").read_text(encoding="utf-8")
    assert "/reindex-all" in api, "the reindex-all endpoint must be registered"
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    assert "reindexAllCorpus(" in html, "a discoverable re-index button must exist"
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function reindexAllCorpus(" in app and "/api/insights/reindex-all" in app


def test_reindex_background_job_is_wired():
    """Keyword-engine Phase 1.1: the whole-corpus re-index runs as a pausable BACKGROUND
    JOB with a persisted cursor (mirrors NewsletterImportManager) — it survives a tab
    close and RESUMES from where it stopped, instead of the old client loop that
    restarted from article 0. Guard the full wiring: the manager, the endpoints, the
    /api/jobs surfacing + DB-writer arbitration + cancel/resume routing, and the frontend
    start/poll + the task-manager pause/resume controls."""
    job = (_SRC / "analytics" / "reindex_job.py").read_text(encoding="utf-8")
    assert "class ReindexJobManager" in job and "def get_reindex_manager(" in job
    # persisted cursor + resume (the trap fix) + pausable
    assert "_load_persisted" in job and "def resume(" in job and "def pause(" in job
    api = (_SRC / "api" / "insights.py").read_text(encoding="utf-8")
    assert "/reindex-job" in api and "get_reindex_manager" in api
    jobs = (_SRC / "api" / "jobs.py").read_text(encoding="utf-8")
    assert "def _reindex_jobs(" in jobs and "jobs.extend(_reindex_jobs())" in jobs
    # it joins the DB-writer arbitration set (serialised with collect/import)
    assert '("collect", "import", "reindex", "quarantine")' in jobs
    # cancel/resume routed to the owning manager
    assert 'job_id == "reindex"' in jobs and "get_reindex_manager()" in jobs
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "_startReindexJob(" in app and "_pollReindexJob(" in app
    assert "/api/insights/reindex-job" in app
    # the Settings buttons drive the background job (kept reindexAllCorpus/cleanupKeywords)
    assert "reindexAllCorpus(" in app and "cleanupKeywords(" in app
    # Phase 1.2: keyword-only scope plumbs end-to-end (index_article -> reindex_all_batch
    # -> the job -> the endpoint -> the cleanup button uses the keyword-only scope).
    store = (_SRC / "analytics" / "store.py").read_text(encoding="utf-8")
    assert 'scope: str = "full"' in store and 'scope != "keywords"' in store
    assert "scope=scope" in store  # reindex_all_batch threads scope to index_article
    assert 'scope: str = "full"' in job  # the manager accepts scope
    assert "scope must be" in api  # the endpoint validates scope
    assert '_startReindexJob(true, "keywords")' in app  # cleanup uses the keyword-only scope
    # Phase 1.3: batched commits (COLLECTOR_WRITER_BATCHING.md) — the commit primitive +
    # the batched re-index path with the rollback-then-redo-per-article no-loss fallback.
    assert "commit: bool = True" in store  # index_article gains the commit primitive
    assert "if commit:" in store  # the conditional final commit
    assert "commit_batch: int = 1" in store  # reindex_all_batch batches (default 1 = byte-identical)
    assert "_redo_committed" in store  # the no-loss fallback (mirror ingest_emails)
    assert "OO_REINDEX_COMMIT_BATCH" in job  # the job reads the batch-size knob (default 1)
    # Phase 1.4: a tuning pass (FTS5 'optimize' segment-merge + PRAGMA optimize planner
    # stats) wired after the bulk re-index AND the bulk newsletter import.
    fts = (_SRC / "database" / "fts.py").read_text(encoding="utf-8")
    assert "def optimize_after_bulk(" in fts and "VALUES ('optimize')" in fts
    assert "optimize_after_bulk" in job  # the re-index job runs it on a complete pass
    importjob = (_SRC / "ingest" / "import_job.py").read_text(encoding="utf-8")
    assert "optimize_after_bulk" in importjob  # the import job runs it on completion


def test_reconcile_keyword_language_is_wired():
    """Keyword-engine P4.2: a background pass re-languages keywords to their
    signature-majority article language (the first-write-wins tag index_article never
    reconciles), perf-safe (no per-row keyword_mentions->articles join), exposed as an
    endpoint AND folded into the re-index job's complete pass."""
    store = (_SRC / "analytics" / "store.py").read_text(encoding="utf-8")
    assert "def reconcile_keyword_language(" in store
    # perf-safe: reads Article.language (covering idx_article_language), NOT a per-row join
    assert "Article.language" in store and "art_lang" in store
    api = (_SRC / "api" / "insights.py").read_text(encoding="utf-8")
    assert "/reconcile-keyword-language" in api
    job = (_SRC / "analytics" / "reindex_job.py").read_text(encoding="utf-8")
    assert "reconcile_keyword_language" in job  # the cleanup flow fixes language too


def test_ir_eval_harness_is_wired():
    """Keyword-engine P3: an IR retrieval-eval harness (the gate for ranking/conflation
    quality changes) — native metrics (no new dep), per-language aggregation, the
    conflation recall/precision deltas, a regression gate, a fixture self-test, and an
    in-app diagnostics endpoint."""
    ev = (_SRC / "analytics" / "ir_eval.py").read_text(encoding="utf-8")
    for fn in ("def ndcg_at_k(", "def rr_at_k(", "def recall_at_k(", "def precision_at_k(",
               "def evaluate(", "def conflation_delta(", "def regression_check(",
               "def evaluate_against_corpus(", "def run_ir_eval_selftest("):
        assert fn in ev, f"ir_eval must define {fn}"
    # honesty: per-language breakdown + no composite score; conflation reported separately
    assert "by_language" in ev and "recall_delta" in ev and "precision_delta" in ev
    api = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    assert "/ir-eval-selftest" in api and "run_ir_eval_selftest" in api
    # the OPERATIONAL input path: a documented gold-set FILE loader + a one-call BM25F A/B,
    # so the maintainer can feed graded queries in (the harness was a mechanism without one).
    assert "def load_gold_set(" in ev and "def bm25f_weight_ab(" in ev
    assert "class GoldSetError" in ev  # a malformed gold set fails loudly, never silently
    fts = (_SRC / "database" / "fts.py").read_text(encoding="utf-8")
    assert "weights:" in fts, "search_ids needs a thread-safe per-call weights override for the A/B"
    assert (_SRC.parent / "configs" / "ir_eval" / "gold_set.example.json").exists(), (
        "a bundled gold-set TEMPLATE must ship so the maintainer has the format"
    )
    # the IN-APP path: a diagnostics endpoint runs the gold-set eval / BM25F A/B
    assert '/ir-eval"' in api and "load_gold_set" in api and "bm25f_weight_ab" in api, (
        "an /api/diagnostics/ir-eval endpoint must run the gold-set eval in-app (P3 operational)"
    )
    # the Diagnostics-panel control that drives it (path + optional A/B weights -> a click)
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    appjs = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="ir-eval-path"' in html and "runIrEval(" in html, (
        "the Diagnostics panel must wire the IR-eval gold-set control"
    )
    assert "function runIrEval(" in appjs and "/api/diagnostics/ir-eval?" in appjs


def test_p0_validation_kit_is_wired():
    """S1.2: the push-button v0.2.0 acceptance run — one cancellable job that drives the
    REAL backup engine against the live corpus, verifies it, probes a STAGED restore + a
    dry-run merge PREVIEW (never commits), and reads the merged unlock + collector
    instrumentation into ONE report with a per-check verdict. Measurements only, never a
    fabricated pass, version/format-stamped."""
    mod = (_SRC / "monitoring" / "p0_validation.py").read_text(encoding="utf-8")
    for fn in ("def run_p0_validation(", "def build_p0_report(", "def validate_dest_dir(",
               "def _check_backup(", "def _check_restore(", "def _check_unlock(",
               "def _check_collector(", "def last_p0_validation_report(",
               "def render_p0_validation_text("):
        assert fn in mod, f"p0_validation must define {fn}"
    # HONESTY: no composite score; the summary is a conjunction; the restore is a PREVIEW
    # (commit=False) that never touches the live corpus; the report is version/format-stamped.
    assert "commit=False" in mod, "the restore probe must be a dry-run PREVIEW (never commit)"
    assert '"backup_engine_format"' in mod and "def backup_engine_format(" in mod, (
        "the report must be stamped with the backup-engine format so a stale run is detectable"
    )
    assert "NOT a composite" in mod or "no composite score" in mod
    # it drives the REAL live path (never an injected corpus_source double — the ZETA lesson):
    # write_volume_backup / verify_stream_backup / read_volume_backup / run_restore, no seam.
    assert "write_volume_backup(" in mod and "verify_stream_backup(" in mod
    assert "read_volume_backup(" in mod and "run_restore(" in mod
    assert "corpus_source" not in mod, "must NOT inject a corpus_source double (ZETA (c) lesson)"
    # the endpoints trio + download, wired into the debug bundle AND the all-diagnostics zip.
    api = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    for route in ('"/p0-validation"', '"/p0-validation/status"', '"/p0-validation/cancel"',
                  '"/p0-validation/download"'):
        assert route in api, f"diagnostics must register {route}"
    assert 'BackgroundJob(\n        "p0-validation"' in api or '"p0-validation",' in api
    assert '"p0_validation"' in api, "the debug bundle must carry the last P0 validation report"
    assert '"p0-validation.json"' in api, "the all-diagnostics zip must carry the P0 report member"
    assert "is_writer=False" in api  # it never commits the live corpus
    # the Diagnostics-panel control (dest + passphrase -> a click) + the JS handlers.
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    appjs = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="p0-dest"' in html and 'id="p0-pass"' in html and "runP0Validation(" in html
    assert "function runP0Validation(" in appjs and "/api/diagnostics/p0-validation" in appjs
    # the runbook the panel hint points at exists.
    assert (_SRC.parent / "docs" / "product" / "P0_VALIDATION_RUNBOOK.md").exists(), (
        "the operator runbook must ship (S1.3)"
    )


def test_render_p0_result_does_not_shadow_the_real_html_escaper():
    """Audit finding 2026-07-17 (M7): renderP0Result declared a LOCAL `esc` that
    fell back to a non-existent global `escapeHtml` -- since that global is never
    defined anywhere in app.js, the ternary always evaluated to a no-op passthrough,
    silently defeating all 5 esc() calls in the function (which feed out.innerHTML,
    an XSS sink: verdict labels, reasons, and the summary note). Regression guard:
    the function must rely on the real module-level esc() (top of file) instead of
    redeclaring/shadowing one."""
    appjs = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    start = appjs.index("function renderP0Result(")
    end = appjs.index("\n    }\n", start)
    body = appjs[start:end]
    assert "typeof escapeHtml" not in body, "must not fall back to the non-existent global escapeHtml"
    assert "const esc" not in body, "must not shadow the real module-level esc()"
    # esc() is still used (the fix removes the shadow, not the escaping calls).
    assert body.count("esc(") >= 5


def test_render_pagesize_result_does_not_shadow_the_real_html_escaper():
    """Audit finding 2026-07-17 (M7 recurrence): renderPagesizeResult (the page-size
    A/B bench result renderer, DB-10 §1b) was written with the EXACT SAME shadowing
    bug as renderP0Result -- a local `esc` falling back to the non-existent global
    `escapeHtml`, silently defeating every esc() call (incl. s.error, an operator/
    exception-reflected string) that feeds out.innerHTML. Same fix, same regression
    guard shape."""
    appjs = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    start = appjs.index("async function renderPagesizeResult(")
    end = appjs.index("\n    }\n", start)
    body = appjs[start:end]
    assert "typeof escapeHtml" not in body, "must not fall back to the non-existent global escapeHtml"
    assert "const esc" not in body, "must not shadow the real module-level esc()"
    assert body.count("esc(") >= 5


def test_dump_and_osm_pollers_clear_before_set():
    """Audit finding 2026-07-17 (L5): startDump's inline dump-progress poller and
    _osmPoll each created a fresh setInterval with NO shared timer variable to clear
    first -- unlike the established _llmPullStartPoll/_volStartPoll/_fbStartPoll
    pattern elsewhere in this file. Starting several dump editions (the multi-pick
    loop calls startDump once per edition) or clicking Download on several OSM
    regions in quick succession (a real action the merged region-list UI invites)
    stacked one independent 3s poller per start/click -- a polling-storm repeat of
    the 2026-06-27/07-01 item-F5 family. Regression guard: both pollers must
    clear-before-set, matching the three known-good pollers' shape exactly."""
    appjs = (_SRC / "static" / "app.js").read_text(encoding="utf-8")

    def _fn_body(marker: str) -> str:
        start = appjs.index(marker)
        end = appjs.index("\n    }\n", start)
        return appjs[start:end]

    dump_poll = _fn_body("function _dumpStartPoll(")
    assert "if (_dumpPollTimer) clearInterval(_dumpPollTimer);" in dump_poll
    assert "_dumpStartPoll();" in _fn_body("async function startDump("), (
        "startDump must call the shared, clearing poller, not an inline setInterval"
    )

    osm_poll = _fn_body("function _osmPoll(")
    assert "if (_osmPollTimer) clearInterval(_osmPollTimer);" in osm_poll

    # The three already-fixed pollers this fix mirrors must still clear-before-set
    # (a regression guard on the PATTERN this fix relies on, not just the two new
    # sites) -- each declares its own module-level timer + a `if (TIMER) clearInterval`
    # guard before assigning a new one.
    for timer, fn_marker in (
        ("_llmPullPoll", "function _llmPullStartPoll("),
        ("_volPollTimer", "function _volStartPoll("),
        ("_fbPoll", "function _fbStartPoll("),
    ):
        body = _fn_body(fn_marker)
        assert f"if ({timer}) clearInterval({timer});" in body, (
            f"{fn_marker} lost its clear-before-set guard"
        )


def test_bm25f_per_column_ranking_is_wired():
    """Keyword-engine P5.1: FTS ranking is BM25F — bm25() weighted per column (title vs
    body) so a title keyword outranks a body-only mention. The weights are env-tunable and
    reversible (equal weights = the old flat rank), and bound as parameters (never
    f-string-formatted into SQL). One change covers every consumer (search_ids is the single
    FTS ranking entry point)."""
    fts = (_SRC / "database" / "fts.py").read_text(encoding="utf-8")
    assert "def _bm25_weights(" in fts
    assert "OO_BM25_TITLE_WEIGHT" in fts and "OO_BM25_BODY_WEIGHT" in fts
    # weighted bm25 ORDER BY with the weights as BOUND params, not string-formatted SQL
    assert "ORDER BY bm25(article_fts, :wt, :wb)" in fts
    assert ":wt" in fts and ":wb" in fts


def test_lemmatization_is_on_by_default_display_layer_and_reversible():
    """Keyword-engine P4.3, ruled default-ON 2026-07-18: simplemma lemmatization conflates
    morphological keyword variants (study/studied) at the DISPLAY layer (families.py), NOT
    the stored index. The measure-before-trust gate is satisfied by a maintainer precision
    review of the live-corpus lemma_preview (lemmatization is a display-layer change,
    invisible to the FTS retrieval harness, so an IR-gold-set A/B was never the coherent
    measurement for it). Opt OUT with OO_FAMILY_LEMMA=0; graceful-degrade when simplemma is
    absent; a visible conflated_by provenance. It must NEVER touch the trusted
    normalize/store path (that would rewrite the canonical index)."""
    fam = (_SRC / "analytics" / "families.py").read_text(encoding="utf-8")
    assert "def _lemma(" in fam and "def _lemma_enabled(" in fam
    assert 'os.getenv("OO_FAMILY_LEMMA"' in fam and '"1")' in fam  # default ON
    assert "_MISLEMMA_DENYLIST" in fam and "conflated_by" in fam  # denylist + visible provenance
    assert "import simplemma" in fam  # optional dep, try/except guarded
    # lemmatization is display-only: the trusted extractor/normalize path must NOT import it
    extract = (_SRC / "analytics" / "extract.py").read_text(encoding="utf-8")
    store = (_SRC / "analytics" / "store.py").read_text(encoding="utf-8")
    assert "simplemma" not in extract and "simplemma" not in store, (
        "lemmatization must stay at the families DISPLAY layer, never the stored index"
    )
    # the optional dependency is declared in the [analysis] extra (CI exercises it)
    pyproject = (_SRC.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert "simplemma" in pyproject


def test_lemma_preview_shows_the_true_delta_over_the_plural_rule():
    """S2 of the 2026-07-18 default-on brief: the lemma_preview review instrument tags each
    candidate group by whether the PLURAL rule (families step 1.5, which runs before the
    lemma step) already accounts for it -- else a naive review over-counts "new merges"
    that are actually already collapsed by the earlier step. Pure computation, no score."""
    er = (_SRC / "analytics" / "engine_report.py").read_text(encoding="utf-8")
    assert "def _plural_rule_classification(" in er
    assert '"plural_rule"' in er and '"lemma_only"' in er and '"mixed"' in er
    assert "plural_overlap" in er and "by_plural_overlap" in er
    # cross-references the SAME plural mechanics the families grouping step uses -- never a
    # re-implementation that could silently drift from what the plural rule actually merges
    assert "_plural_bases" in er and "_PLURAL_DENYLIST" in er


def test_lemma_conflation_indicator_is_wired_conservative_and_flagged():
    """S3 of the 2026-07-18 default-on brief (deferred from the original opt-in ruling, now
    shipped since the feature is on by default): a family collapsed in part by
    lemmatization (conflated_by=["lemma"]) shows a small, honest, reversible marker in the
    Insights -> Families list -- browser-unverified per fork-3/Q6a, so this pins the wiring
    rather than a rendered screenshot."""
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "conflated by lemma" in js
    assert 'f.conflated_by || []).includes("lemma")' in js


def test_corpus_facets_drill_is_wired():
    """Keyword-engine P5.1b: the analysis window's When/Where/Who becomes an interactive
    FACET surface — a temporal (When) facet alongside who/where, and every value drills
    into a corpus narrowed to the articles mentioning it (a facet co-equal with the text
    query). Counts only, deduced from text, never confirmed. Cheap: the drill filters an
    article_id-indexed mention table, never a keyword_mentions->articles join."""
    qsrc = (_SRC / "analytics" / "queries.py").read_text(encoding="utf-8")
    assert "def corpus_when(" in qsrc and "def corpus_facet_article_ids(" in qsrc
    # the temporal facet buckets by year; the drill handles entity/place/when
    assert 'ArticleMentionedDate.status != "rejected"' in qsrc  # user-rejected tags excluded
    api = (_SRC / "api" / "insights.py").read_text(encoding="utf-8")
    assert "/corpus-facet-articles" in api
    assert '"when": q.corpus_when(' in api  # the When facet is additive on corpus-www
    # the drill rejects an unknown facet rather than silently returning empty
    assert 'facet must be entity|place|when' in api


def test_articles_endpoint_serialises_stored_sentiment():
    """§6: the /api/articles list exposes the stored sentiment (populated at ingest /
    re-index, VADER English-only) so lists / cards can show tone without an extra framing
    call -- null for non-English / not-yet-re-indexed articles, never a fabricated neutral.
    Both serialisation paths (the ids-seeded path + the query path) must carry it, plus the
    §2.6 secondary/deduced language; the analysis Articles list renders a tone chip.
    Both serialisation paths (ids-seeded + query) build results through the SHARED
    ``_article_row`` helper, which exposes these fields once -- so they can never drift
    apart (the prior duplicated dicts were unified)."""
    main = (_SRC / "api" / "main.py").read_text(encoding="utf-8")
    assert "def _article_row(" in main, "the shared /api/articles result builder must exist"
    assert main.count("_article_row(a") >= 2, (
        "both /api/articles serialisation paths (ids + query) must build via _article_row"
    )
    # the shared builder exposes the stored sentiment + the secondary/deduced language
    assert '"sentiment_score": a.sentiment_score' in main
    assert '"sentiment_label": a.sentiment_label' in main
    assert '"detected_language": a.detected_language' in main, (
        "the shared row must expose the secondary/deduced language (§2.6)"
    )
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function _anToneChip(" in app and "_anToneChip(a)" in app, (
        "the analysis Articles list must render the tone / deduced-language chip"
    )


def test_downloaded_dump_title_search_exists():
    """§2.4 (autonomous 2026-06-21): downloaded wiki dumps gain a bounded TITLE
    search over the multistream index (honest scope: titles only, not page bodies —
    decompressing every block per query is out of scope). Surfaced in the Settings
    dump-reader UI, not the per-keystroke omnibar (a multi-million-line scan must
    never run interactively)."""
    dr = (_SRC / "wiki" / "dumpread.py").read_text(encoding="utf-8")
    assert "def search_titles(" in dr, "the dump title-search core must exist"
    assert "scan_cap" in dr and '"capped"' in dr, "the scan must be bounded + report capping"
    api = (_SRC / "api" / "wiki.py").read_text(encoding="utf-8")
    assert "/dumps/search" in api, "the dump search endpoint must be registered"
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function dumpSearchTitles(" in app and "/api/wiki/dumps/search" in app, (
        "the Settings dump reader must offer a title search"
    )


def test_guided_wizard_language_step_consolidated():
    """§2.5 (autonomous 2026-06-21): the first-launch flow picks the language FIRST
    (unlock.html) + a permanent top-bar switcher always changes it, so the guided
    wizard no longer carries a redundant language step. The lang DOM/helper stay
    (unreachable) per the Desk lesson — nothing silently lost."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # The wizard flow must NOT contain a "lang" step (dropped §2.5). S4.7 later slotted the
    # real "sources" step, so guard on the ABSENCE of "lang", not an exact array.
    steps = app[app.index("const _GW_STEPS = [") : app.index("];", app.index("const _GW_STEPS = [")) + 2]
    assert '"lang"' not in steps, "the wizard lang step must be dropped from the flow"
    # The lang rendering helper is kept (unreachable, not deleted).
    assert "function _gwRenderLangs(" in app, "the lang helper must be preserved (Desk lesson)"


def test_offline_map_queued_rows_can_be_reordered():
    """§2.3 (autonomous 2026-06-21): the Settings → Offline-map row list lets the
    operator reorder QUEUED region downloads (the same prioritisation control the
    task manager already offers), optimistically + persisted via the geo endpoint."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "async function osmMove(key, dir)" in app, "an osmMove reorder helper must exist"
    assert "/api/geo/downloads/reorder" in app, "reorder must persist via the geo endpoint"
    # The queued row renders ↑/↓ controls calling osmMove.
    render = app.split("function _renderOsmList(", 1)[1].split("\n    }", 1)[0]
    assert "osmMove(" in render and "queue_position" in render, (
        "queued rows must render ↑/↓ reorder controls keyed on queue_position"
    )
    # The backend exposes queue_position on the downloads list so the UI can order them.
    osm = (_SRC / "geo" / "osm_downloads.py").read_text(encoding="utf-8")
    assert '"queue_position"' in osm, "osm downloads list must expose queue_position"


def test_world_map_near_time_capped_log_slider_and_no_download_confirm():
    """Field test 2026-06-19 THEME-2 (#14/#15): the "near in space & time" co-occurrence
    is capped to a TIGHT fixed window (it used the slider's span/12 ~166y, linking events
    decades apart); the time slider is LOGARITHMIC-by-age (recent gets most travel); and
    the offline-map download has no redundant confirm (ensureOnline stays the only gate)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "const _OOMAP_NEAR_YEARS = 2;" in app, "the near-time co-occurrence cap is gone"
    assert "Math.min(win || _OOMAP_NEAR_YEARS, _OOMAP_NEAR_YEARS)" in app
    assert "Math.pow(_LOGB, 1 - frac)" in app, "the time slider is no longer logarithmic"
    # The OSM download keeps the network consent but dropped the redundant 'are you sure'.
    osm = app.split("async function startOsmDownload(", 1)[1].split("\n    }", 1)[0]
    assert 'ensureOnline("Download an offline map region")' not in osm or "ensureOnline" in osm
    assert "confirm(t(\"Download this offline map region" not in osm, (
        "the redundant map-download confirm should be gone (#15)"
    )


def test_world_map_shapes_labels_and_click_country():
    """Field test 2026-06-19 THEME-2: the world map gains (a) deduced/scheduled
    events as distinct SHAPES (colour=kind, shape=certainty) so it reads without
    colour alone; (b) dynamic non-overlapping country labels (greedy declutter,
    constant on-screen size, re-laid-out on zoom, opt-in toggle); (c) click a
    country → its coverage breakdown (counts only, the VADER caveat on tone)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # (a) shape by certainty class, colour by kind
    assert "function _ooSigClass(s)" in app and "function _ooSigMarker(" in app, (
        "the signal shape helpers (certainty class → circle/triangle/diamond) must exist"
    )
    assert '"corpus-mention"' in app and "return \"deduced\"" in app, (
        "corpus-extracted (deduced) events must map to their own shape class"
    )
    assert "_ooSigMarker(cls, x, y, r, ring" in app, "signals must render via the shape helper"
    # (b) dynamic, non-overlapping, re-laid-out-on-zoom labels (opt-in)
    assert "function _ooMapLayoutLabels(host, vb)" in app, "the greedy label declutter must exist"
    assert "11 * (vb.w / MAP_W)" in app, "labels must be constant on-screen size as the viewBox zooms"
    assert "if (host._ooLabels && host._ooLabels.length) _ooMapLayoutLabels(host, vb)" in app, (
        "labels must re-declutter on every viewBox change (dynamic)"
    )
    assert "data-oomap-labels" in app and "onLabels:" in app, "an in-map Labels toggle must be wired"
    # (c) click a country → coverage detail (no score; VADER caveat on tone)
    assert "function _ooMapCountryDetail(row, dim)" in app, "the click-country coverage detail must exist"
    assert "onCountry: iso => _ooMapCountryDetail(" in app, "the map must wire onCountry to the detail"
    assert "English-only VADER lexicon" in app, "the per-country tone must carry the VADER caveat"


def test_world_map_osm_offline_overlay():
    """Field test 2026-06-19 THEME-2 (batch-1: in-browser .pbf parser): the world
    map can overlay a DOWNLOADED OSM region, parsed entirely in the browser (zero
    network) by the bounded OOPBF reader, served as a bounded byte prefix by the
    backend. Honest preview, capped render, no fabricated geometry."""
    html = _ui_source()  # index.html + app.js + app.css
    idx = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    # the parser module is loaded before app.js
    assert '/static/osmpbf.js' in idx, "the in-browser OSM .pbf reader must be loaded"
    # an opt-in in-map OSM toggle, wired through OOPBF.parse on a downloaded region
    assert "data-oomap-osm" in html and "onOsm" in html, "the map must offer an OSM overlay toggle"
    assert "function _ooMapToggleOsm()" in html and "OOPBF.parse(" in html, (
        "the toggle must parse the downloaded .osm.pbf in the browser"
    )
    # zero-network: it reads a LOCAL downloaded region via the bounded preview endpoint
    assert "/api/geo/regions/${encodeURIComponent(code)}/preview" in html
    # capped render (a dense region cannot choke the SVG) + honest preview legend
    assert 'id="oomap-osm"' in html and "offline OSM" in html
    # backend: the bounded preview endpoint exists, path-safe, bounded
    geo = (_ROOT / "src" / "api" / "geo.py").read_text(encoding="utf-8")
    assert '"/regions/{code}/preview"' in geo and "_PREVIEW_MAX" in geo, (
        "the bounded region-preview endpoint must exist + be capped"
    )
    assert "is_valid_code(code)" in geo, "the preview endpoint must reject path-unsafe codes"


def test_world_map_osm_admin_boundary_choropleth():
    """THEME-2 #51: the in-browser .pbf reader also decodes admin (country)
    boundary RELATIONS + tags, assembles them into closed polygons keyed by ISO
    code, and the choropleth AUGMENTS the coarse 110m geometry with them (a
    microstate the 110m set drops now renders a true shape). Honest: only rings
    actually closed are emitted (never a fabricated border); the OSM polygons add
    to / replace the coarse ones, never silently hide data. The verifiable core is
    node-tested (tests/osmpbf_node_test.js → tests/test_osmpbf_parser.py)."""
    pbf = (_SRC / "static" / "osmpbf.js").read_text(encoding="utf-8")
    # the parser gained StringTable + tag + relation decode + ring assembly
    assert "function decodeStringTable(" in pbf and "function resolveTags(" in pbf
    assert "withRelations" in pbf and "function decodeRelation(" in pbf  # boundary relation decode
    assert "relations.push(" in pbf, "relations must be decodable"
    assert "function assembleAdminAreas(" in pbf and "function stitchRings(" in pbf, (
        "admin-boundary assembly + ring stitching must exist"
    )
    assert "ISO3166-1:alpha2" in pbf, "country areas are keyed by the ISO 3166-1 alpha-2 tag"
    assert "assembleAdminAreas: assembleAdminAreas" in pbf, "the assembly must be exported (node-testable)"
    html = _ui_source()  # index.html + app.js + app.css
    # the OSM toggle now parses WITH tags+relations and assembles country boundaries
    assert "withTags: true, withRelations: true" in html, (
        "the OSM overlay must parse tags + relations to assemble boundaries"
    )
    assert "OOPBF.assembleAdminAreas(geo)" in html, "the frontend must assemble admin boundaries"
    # the boundaries are passed to ooMap and MERGE into the choropleth by ISO code
    assert "osmAreas:" in html and "opts.osmAreas" in html, "ooMap must accept the OSM areas"
    assert "c.osm" in html, "OSM-augmented polygons must be distinguishable (honest provenance)"
    assert "boundary from OSM" in html and "country boundaries" in html, (
        "the OSM provenance + count must be disclosed (honesty)"
    )


def test_analysis_articles_per_row_summarize_translate():
    """Track C: the analysis Articles list offers a PER-ARTICLE Summarize / Translate
    (the single-article complement to the bulk LLM run). Reuses the existing
    single-article endpoints (loopback Ollama), renders the result INLINE labelled
    AI-derived / unreliable with model provenance, and NEVER touches the trusted
    keyword index (the rows live in article_analyses). Browser-unverified."""
    html = _ui_source()  # index.html + app.js + app.css
    # per-row buttons wired to the handler
    assert "anArticleLlm(${a.id},'summarize',this)" in html and "anArticleLlm(${a.id},'translate',this)" in html, (
        "each article row must offer Summarize + Translate"
    )
    assert "async function anArticleLlm(" in html, "the per-article LLM handler must exist"
    # it calls the existing single-article endpoints (not the keyword index)
    assert "`/api/llm/articles/${id}/${op}`" in html, "must POST the single-article summarize/translate endpoint"
    # the result is labelled AI-derived / unreliable (honesty by construction)
    assert "AI summary — unreliable, verify against the source." in html
    assert "AI translation — unreliable, verify against the source." in html
    # the backend endpoints it relies on exist + store to article_analyses (never KeywordMention)
    llm = (_ROOT / "src" / "api" / "llm.py").read_text(encoding="utf-8")
    assert '"/articles/{article_id}/summarize"' in llm and '"/articles/{article_id}/translate"' in llm
    assert "ArticleAnalysis(" in llm, "single-article results store in article_analyses, not the keyword index"


def test_world_map_server_location_layer():
    """Data-architecture slice 6c (frontend): the world map offers a switchable
    "Server IPs" layer — the captured server IPs (6a) geolocated OFFLINE (6b),
    DISTINCT from the editorial source-country choropleth, with the honesty caveats
    visible and IP/host clustering surfaced as a shape to investigate, never a verdict.
    Conservative + browser-unverified (node-checked; needs a click-through)."""
    html = _ui_source()  # index.html + app.js + app.css
    # an opt-in in-map toggle wired through onServer, fed by the backend endpoint
    assert "data-oomap-server" in html and "onServer" in html, "the map needs a Server-IP toggle"
    assert "/api/insights/server-locations" in html, "the layer must read the server-locations endpoint"
    # distinct marker (violet squares) from the editorial choropleth + places overlay
    assert "serverPts" in html and "#8b5cf6" in html
    # caveats VISIBLE: CDN edge / anycast, not the origin; clustering is not a verdict
    assert "CDN edge / anycast" in html
    assert "a shape to investigate, never a verdict" in html
    # backend: the endpoint + query exist (built in the merged PR #407)
    ins = (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    assert '"/server-locations"' in ins
    q = (_ROOT / "src" / "analytics" / "queries.py").read_text(encoding="utf-8")
    assert "def server_locations(" in q


def test_subtabs_are_browser_style_with_clear_active_state():
    """Field test 2026-06-19 #31/#57 (THEME-1): one homogeneous browser-tab look with an
    UNMISTAKABLE active state — an accent underline + bold (the old subtle bg+border read
    as buttons and was unreliable). Plus #42: the LLM subtab is labelled "AI"."""
    css = (_SRC / "static" / "app.css").read_text(encoding="utf-8")
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    assert "nav.tabs { display:flex; flex-wrap:wrap; gap:2px; border-bottom:1px solid var(--border); }" in css
    # The active tab carries an accent underline (the clear indicator).
    assert "border-bottom:2px solid var(--accent); font-weight:700;" in css
    # #42: Models subtab renamed to AI (data-tab anchor stays the code identifier).
    assert '<button data-tab="models">AI</button>' in html


def test_language_codes_shown_as_full_names_via_cldr():
    """Field test 2026-06-19 #52/#53 (THEME-4): show the full language NAME (CLDR via
    Intl.DisplayNames), not a bare 2-letter code, wherever a language is displayed
    (sources table/meta, source profile, translation provenance)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function ooLangName(code, fallback)" in app, "the ooLangName CLDR helper is gone"
    assert 'new Intl.DisplayNames([ui], { type: "language" })' in app
    # Applied at the sources table language cell (re-renders live on oo:langchange).
    assert "ooLangName(s.language" in app


def test_network_polish_go_online_green_dynamic_title_and_panic_i18n():
    """Field test 2026-06-19 polish: (#O-5) going ONLINE flashes green; (#5) the airplane
    button carries a state-specific, i18n-safe dynamic title; (#64) the panic dialog is
    translatable."""
    base = _SRC / "static"
    css = (base / "app.css").read_text(encoding="utf-8")
    app = (base / "app.js").read_text(encoding="utf-8")
    i18n = (base / "i18n.js").read_text(encoding="utf-8")
    html = (base / "index.html").read_text(encoding="utf-8")
    # #O-5: go-on (online) is green (--ok), not the accent.
    assert "#net-flash.go-on  { background:radial-gradient(ellipse at top, color-mix(in srgb, var(--ok)" in css
    # #5: the button is JS-managed and i18n opts out of clobbering its title.
    assert "data-i18n-dyn" in html
    assert 'el.hasAttribute("data-i18n-dyn")' in i18n
    assert "btn.title = online" in app  # state-specific title in _paintNetwork
    # #64: panic dialog routed through t().
    panic = app.split("async function panicWipe()", 1)[1][:600]
    assert 't("PANIC WIPE' in panic and 't("To confirm, type WIPE' in panic


def test_oosubtabs_queries_buttons_live_and_markets_keep_selection():
    """Field test 2026-06-19 #31: the markets category subtab kept "All" visually active
    after switching. Root cause: ooSubtabs captured its button array once, but the markets
    nav rebuilds its buttons on every render, so the wired-once click handler painted
    detached buttons. ooSubtabs must query buttons LIVE, and the markets board must
    preserve the selected category across re-renders."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    oo = app.split("function ooSubtabs(", 1)[1].split("return { select: select", 1)[0]
    assert "const buttons = () =>" in oo, "ooSubtabs no longer queries its buttons live"
    assert "const btns = Array.prototype.slice.call(nav.querySelectorAll" not in oo, (
        "ooSubtabs went back to capturing a stale button array (the #31 regression)"
    )
    # The markets board persists the operator's category choice across re-renders.
    assert "_mktCat = key" in app and "indexOf(_mktCat)" in app


def test_seamless_install_and_language_first_first_launch():
    """Maintainer field test 2026-06-20: (1) the installer asks NOTHING and never
    provisions Ollama (that moved ENTIRELY to Settings -> AI); (2) first launch (a
    FRESH store) leads with LANGUAGE selection, not the passphrase -- while keeping
    encryption-by-default (the create-passphrase step just follows the language step)."""
    installer = (_ROOT / "install.sh").read_text(encoding="utf-8")
    # (1) Ollama install is fully out of the installer: no provisioning function, no
    # third-party installer, no model pulls. (configure_ollama_store_access stays defined,
    # pinned by tests/test_installer.py, but is no longer called by the default install.)
    assert "maybe_setup_ollama" not in installer, (
        "Ollama provisioning must be removed from the installer (moved to Settings -> AI)"
    )
    assert "ollama.com/install.sh" not in installer and "ollama pull" not in installer, (
        "the installer must never download/run Ollama or pull a model"
    )
    # No interactive component/launcher prompts -- seamless install.
    assert 'CHOSEN_EXTRAS="${OO_COMPONENTS:-analysis,compression,columnar}"' in installer
    assert 'whiptail --title "Open Omniscience -- choose components"' not in installer, (
        "the component-selection menu must be gone (seamless install asks nothing)"
    )
    assert 'local want="${OO_MAKE_LAUNCHER:-1}"' in installer, (
        "the launcher is created by default, no prompt (OO_MAKE_LAUNCHER=0 still opts out)"
    )

    # (2) The fresh-store first launch shows a language step FIRST.
    unlock = (_SRC / "static" / "unlock.html").read_text(encoding="utf-8")
    assert 'id="view-language"' in unlock and "showLanguageStep" in unlock, (
        "fresh first launch must offer a language step (view-language / showLanguageStep)"
    )
    assert 'if (s.state === "fresh") { showLanguageStep(); return; }' in unlock, (
        "a FRESH store must route to the language step, not straight to the passphrase"
    )
    # The choice persists + translates via the shared i18n engine (oo.lang).
    assert "OOI18N.setLang(code)" in unlock, (
        "the language choice must persist + translate via OOI18N.setLang"
    )
    # Encryption-by-default is PRESERVED: the create-passphrase view still exists and
    # simply follows the language step.
    assert "pickLanguage" in unlock and '$("view-create").classList.remove("hidden")' in unlock, (
        "after choosing a language, the create-passphrase view must follow"
    )
    assert 'id="view-create"' in unlock and "create-db" in unlock, (
        "the passphrase create flow must remain (encryption-by-default, just reordered)"
    )


def test_llm_pill_shows_count_and_opens_ai_settings():
    """Maintainer field test 2026-06-20: the top-bar LLM pill reads "<N> LLM" (the
    count in front, no "models" word, no checkmark), and clicking it opens
    Settings -> AI (the "models" subtab) instead of only re-checking health."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "`${h.installed_models.length} LLM`" in app, (
        "the LLM pill must read '<N> LLM' (count in front, no 'models')"
    )
    assert "LLM ✓ (" not in app and "} models)`" not in app, (
        "the old 'LLM ✓ (N models)' pill format must be gone"
    )
    assert "el.onclick = openAiSettings" in app and "function openAiSettings()" in app, (
        "clicking the LLM pill must open AI settings (openAiSettings)"
    )
    assert 'select("models")' in app, (
        "openAiSettings must navigate to Settings -> the AI/models subtab"
    )


def test_advanced_search_language_is_a_flag_dropdown():
    """Maintainer field test 2026-06-20: the Advanced-search language field is a <select>
    of full language names with flags (built from LANGS_12 in JS), not a free-text input."""
    html = _ui_source()
    assert '<select id="an-adv-lang"' in html, "the Advanced language field must be a <select>"
    assert '<input id="an-adv-lang"' not in html, "the old free-text language input must be gone"
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function _anFillLangSelect()" in app and "of LANGS_12" in app, (
        "the language <select> must be populated from LANGS_12 (flag + native name)"
    )


def test_facet_subtabs_relocated_to_top_strip():
    """Maintainer field test 2026-06-20: all facet subtabs render JUST UNDER the status
    bar. A sticky .chrome wraps the topbar + a #subtab-strip; showTab relocates each
    tab's ooSubtabs nav into the strip (moving the node keeps its listeners + state)."""
    html = _ui_source()
    assert 'class="chrome"' in html and 'id="subtab-strip"' in html, "the chrome + subtab strip must exist"
    assert ".chrome { position:sticky; top:0" in html, "the chrome must pin the status bar + strip at the top"
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function _relocateSubtabs(" in app and "_relocateSubtabs(name)" in app, (
        "showTab must relocate the active tab's facet subtabs into the strip"
    )
    for navid in ("an-subtabs", "ins-subtabs", "set-subtabs", "agenda-views", "indices-cats", "commodities-cats"):
        assert navid in app, f"the subtab-nav relocation map must cover {navid}"


def test_analysis_articles_paginated():
    """Maintainer field test 2026-06-20: the analysis Articles list is PAGINATED — a
    1000-result search is browsable with Prev/Next + 'Page X of Y' controls shown BOTH
    above and below the list (/api/articles already supports limit+offset)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function _anLoadArticles(" in app and "function _anArtGo(" in app and "_anArtPager(" in app
    assert 'q.set("offset"' in app and 'q.set("limit"' in app, "pagination must fetch by limit+offset"
    assert "_anLoadArticles(p, 0)" in app, "loadAnalysis must use the paginated loader"
    assert app.count("+ pager") >= 2, "the pager must render BOTH above and below the results list"
    assert 't("Page")' in app and 't("of")' in app, "the 'Page X of Y' control must exist"


def test_synthesis_opens_a_window_with_selection_metadata_and_export():
    """Maintainer field test 2026-06-21: 'synthesize results' opens a roomy, article-style
    WINDOW that (1) makes the member selection TRANSPARENT (which articles, of how many,
    by relevance) and lets the user pick, (2) shows the full corpus of synthesized
    articles WITH metadata, (3) is exportable/copyable, (4) writes in the UI language."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # the dialog window exists with a title + actions slot + body
    assert 'id="synth-window"' in html and 'id="synth-win-body"' in html
    assert 'id="synth-win-actions"' in html and 'id="synth-win-title"' in html
    # synthesizeResults opens the window (not the old inline #synth-result card)
    assert "synth-window" in app and ".showModal()" in app
    assert "function synthesizeResults(" in app
    # selection step: a candidate pool + checkboxes + a bounded count
    assert "_synthRenderSelect" in app and "synth-cb" in app and "_synthCount" in app
    assert "_SYNTH_MAX" in app, "the bound must be explicit/visible in the selection step"
    # the user-chosen ids drive the run (no silent top-20 truncation as the only path)
    assert "article_ids: ids" in app and "ui_lang: code" in app, "send chosen ids + UI language"
    # result step shows member metadata + export/copy
    assert "_synthRenderResult" in app and "r.members" in app
    assert "_synthExport" in app and "_synthAsMarkdown" in app and "_synthCopy" in app
    # the candidate fetch uses the new /api/articles ids param for a seeded corpus
    assert 'cp.set("ids"' in app


def test_bulk_translate_summary_runs_are_queued():
    """Maintainer field test 2026-06-21: batch translate/summarize runs are QUEUED — a
    new batch can be added while one is ongoing; they run ONE AT A TIME, each snapshots
    its selection, and the queue is visible with per-job cancel in a persistent panel."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # persistent queue containers (survive the config panel / extractor reusing the mount)
    assert 'id="bulk-queue-search"' in html and 'id="bulk-queue-an"' in html
    # queue machinery
    assert "let _bulkQueue" in app and "_bulkActive" in app and "function _bulkPump(" in app
    assert "function _bulkRunJob(" in app and "function bulkJobCancel(" in app
    # bulkLlmRun ENQUEUES (snapshots a job) + pumps, instead of running inline
    assert "_bulkQueue.push(job)" in app and "_bulkPump()" in app
    # one at a time: the pump returns if a job is already active
    assert "if (_bulkActive) return;" in app
    # the queue renders into every .bulk-queue container with a per-job Cancel
    assert 'querySelectorAll(".bulk-queue")' in app and "bulkJobCancel(" in app
    # the custom-extractor path keeps its own abort (not broken by the queue refactor)
    assert "function bulkLlmStop(" in app and "_bulkJobAbort" in app


def test_task_manager_reorder_moves_rows_optimistically():
    """Maintainer field test 2026-06-21: prioritising/moving a download in the task
    manager must VISUALLY move the row immediately — not wait for the backend round-trip
    or the next poll. Both task managers (in-app + the standalone /tasks page) renumber
    the cached queue and REPAINT before the POST, then reconcile."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    tm = (_SRC / "static" / "taskmanager.html").read_text(encoding="utf-8")
    # in-app: a paint-from-cache path + jobMove repaints before awaiting the reorder POST
    assert "function _paintJobs(" in app, "render-from-cache path for an instant move"
    mv = app[app.index("async function jobMove("):]
    mv = mv[: mv.index("\n    }")]
    assert "queue_position = idx + 1" in mv and "_paintJobs()" in mv, "optimistic renumber + repaint"
    assert mv.index("_paintJobs()") < mv.index("_reorderEndpoint"), "repaint must precede the POST"
    # standalone /tasks: same — renumber + re-render before the POST
    tmv = tm[tm.index("move: async function"):]
    tmv = tmv[: tmv.index("\n    }")]
    assert "queue_position = idx + 1" in tmv and "renderQueue(_jobs" in tmv
    assert tmv.index("renderQueue(_jobs") < tmv.index("reorderEp("), "repaint must precede the POST"


def test_offline_map_merged_list_state_and_planet_skips_downloaded():
    """Maintainer field test 2026-06-21: the Offline-map tab assembles the catalogue +
    downloads into ONE state-aware list (not-downloaded/queued/downloading%/paused/done),
    download clicks give instant feedback, and 'Whole planet' downloads only the
    continents you DON'T already have (never re-fetches downloaded parts)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # ONE merged list: loadOsmMap fetches BOTH endpoints and joins by code
    lm = app[app.index("async function loadOsmMap("):]
    lm = lm[: lm.index("\n    }")]
    assert "/api/geo/regions" in lm and "/api/geo/downloads" in lm and "Promise.all" in lm
    assert "function _renderOsmList(" in app and "_osmDlByCode" in app
    # state-aware row rendering with a visible progress bar
    rl = app[app.index("function _renderOsmList("):]
    rl = rl[: rl.index("\n    }\n")]
    for tok in ['t("Downloading")', 't("Downloaded")', 't("Queued")', "<progress"]:
        assert tok in rl, f"missing state token {tok}"
    # instant feedback on click
    assert 't("Starting…")' in app, "download click gives instant feedback"
    # 'Whole planet' = download only the MISSING continents (skip done/downloading/queued)
    pd = app[app.index("async function startPlanetDownload("):]
    pd = pd[: pd.index("\n    }")]
    assert "_osmContinents()" in pd and "already present" in pd
    assert '"done"' in pd and '"downloading"' in pd and '"queued"' in pd, "skip already-held parts"
    # the old separate downloads table is merged away (cleared)
    assert 'if (tbl) tbl.innerHTML = ""' in app


def test_backup_can_exclude_newsletters():
    """Maintainer field test 2026-06-21: the "replace faulty newsletters" workflow.

    UNIFIED 2026-07-01: the create-side "what to back up" tickbox was simplified away —
    the unified Export always captures the FULL corpus (encrypted volumes). The workflow
    is NOT lost: newsletters can be dropped at RESTORE (test_restore_can_exclude_newsletters)
    AND removed live (test_remove_imported_newsletters_live_action). The BACKEND exclusion
    capability is retained (used by the restore-side filter), so this test now pins the
    backend + the surviving restore-side UI toggle."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    art = (_SRC / "backup" / "artifact.py").read_text(encoding="utf-8")
    # The restore-side selective toggle survives (backup is now full-corpus by design).
    assert 'id="v2-restore-newsletters"' in html and "What to restore" in html
    # backend: the exclusion helper + write_backup_v2's honest default is retained.
    assert "def _drop_newsletter_articles(" in art and "def write_backup_v2(" in art
    assert "include_newsletters: bool = True" in art, "default keeps newsletters (no silent change)"
    # the filter targets the real newsletter source domains
    assert "newsletters.import.local" in art and "mailbox.import.local" in art


def test_restore_can_exclude_newsletters():
    """Maintainer field test 2026-06-21: selective RESTORE — 'what to restore' lets the
    user drop imported newsletters from the merge (symmetric to backup). The staged
    plaintext corpus is filtered BEFORE the merge, so the preview reflects the commit."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    bk = (_SRC / "api" / "backup_v2.py").read_text(encoding="utf-8")
    # UI: a "what to restore" fieldset + the newsletter toggle
    assert 'id="v2-restore-newsletters"' in html and "What to restore" in html
    # frontend sends include_newsletters at preview (token commit inherits the filter)
    assert 'fd.append("include_newsletters"' in app
    # backend: the filter runs on the STAGED copy before the merge (reuses the tested helper)
    assert "def _apply_restore_selection(" in bk and "_drop_newsletter_articles" in bk
    assert "include_newsletters: bool = Form(True)" in bk


def test_remove_imported_newsletters_live_action():
    """Brief §2.B: a LIVE 'remove imported newsletters' maintenance action purges the
    newsletter articles from the running corpus (restore is additive-only, so the backup
    tickbox alone never removes them) — closing the 'replace the faulty ones' loop. The
    confirm-required endpoint + the Settings button/handler + the 'back up first' nudge."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    ing = (_SRC / "api" / "ingestion.py").read_text(encoding="utf-8")
    email = (_SRC / "ingest" / "email.py").read_text(encoding="utf-8")
    # backend: the count + confirm-required remove endpoints
    assert '"/newsletters/imported-count"' in ing and '"/newsletters/remove-imported"' in ing
    assert "confirm:true is required" in ing
    # backend: the live-remove + count helpers + the single source of truth for domains
    assert "def delete_imported_newsletters(" in email and "def count_imported_newsletters(" in email
    assert "NEWSLETTER_SOURCE_DOMAINS" in email
    assert "backfill_keyword_counters" in email, "counters reconciled after the bulk delete"
    assert "with write_lock():" in email, "the bulk delete takes the single-writer gate"
    # UI: the panel (shown only when there's something to remove) + the two buttons
    assert 'id="nl-remove-panel"' in html and 'onclick="removeImportedNewsletters(' in html
    assert 'onclick="downloadBackupFirst(' in html  # the back-up-first nudge
    assert "function removeImportedNewsletters(" in app and "function loadNewsletterRemoveCount(" in app
    assert "/api/newsletters/remove-imported" in app


def test_filtered_indicator_and_tag_autobackfill():
    """Brief §2.D: when filters/sort are active the analysis window shows a 'Filtered'
    scope chip (honest place — filters are analysis-scoped). §3.H: the Keywords explorer
    auto-applies baseline tags once when it opens empty (the auto-index pattern)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # §2.D the active-filters indicator
    assert "function _anFilterSummary(" in app
    assert 't("Filtered")' in app
    # §3.H one-time silent baseline-tag backfill when the explorer opens with no tags
    assert "_kxAutoBackfilled" in app and "/api/insights/keyword-tags/backfill" in app


def test_model_download_queue():
    """Brief §2.C1: model pulls are a QUEUED, task-manager-visible job (one active, the
    rest queue, each cancellable — Ollama's pull is not resumable so cancel, not pause).
    The AI tab enqueues with instant feedback + a live downloads/status section."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    llm = (_SRC / "api" / "llm.py").read_text(encoding="utf-8")
    jobs = (_SRC / "api" / "jobs.py").read_text(encoding="utf-8")
    mgr = (_SRC / "llm" / "pull_queue.py").read_text(encoding="utf-8")
    assert "class ModelPullManager" in mgr and "def enqueue(" in mgr and "def cancel(" in mgr
    # one active pull at a time (a single pump thread)
    assert 'name="model-pull"' in mgr
    assert '"/pull/queue"' in llm and '"/pull/status"' in llm and '"/pull/cancel"' in llm
    assert "def _model_pull_jobs(" in jobs and '"model-pull:"' in jobs
    # UI: enqueue (instant feedback) + the downloads section
    assert 'id="llm-downloads"' in html
    assert "/api/llm/pull/queue" in app and "function _llmPullRefresh(" in app


def test_ollama_binary_installer():
    """Maintainer Q7=B (2026-06-16) + field test 2026-06-20 ("can't find the AI
    installer"): the app can DOWNLOAD + VERIFY + RUN the official Ollama installer
    from Settings → AI. The checksum is GitHub's OWN attestation (never fabricated);
    a mismatch refuses; elevation is explicit (run only when non-interactive, else
    the verified command for a terminal)."""
    inst = (_SRC / "llm" / "installer.py").read_text(encoding="utf-8")
    llm = (_SRC / "api" / "llm.py").read_text(encoding="utf-8")
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # the verified core: resolve+verify against GitHub's attested digest, refuse mismatch
    assert "def resolve_and_verify(" in inst and "def prepare_installer(" in inst
    assert "class InstallerVerificationError" in inst and "hashlib.sha256" in inst
    # never run something outside the verified staging area; elevation explicit
    assert "def _validate_staged(" in inst and "def can_run_unattended(" in inst
    assert "def run_installer(" in inst and "def manual_command(" in inst
    # kill-switch gated (no socket under airplane)
    assert "kill_switch_active" in inst
    # endpoints
    assert '"/install/status"' in llm and '"/install/prepare"' in llm and '"/install/run"' in llm
    # UI: an install panel (only when Ollama is absent) wired to the endpoints
    assert 'id="llm-install-box"' in html
    assert "function loadOllamaInstall(" in app and "function prepareOllamaInstall(" in app
    assert "/api/llm/install/prepare" in app and "/api/llm/install/status" in app


def test_newsletter_folder_import_job():
    """Brief §2.B: a SERVER-SIDE .eml FOLDER import runs as a pausable, task-manager-
    visible DB-writer job (the 20 GB+ case the upload can't handle). Reuses the batched
    ingest_emails; resume is idempotent (content-hash dedup + a PERSISTED cursor that
    survives an app restart)."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    ing = (_SRC / "api" / "ingestion.py").read_text(encoding="utf-8")
    jobs = (_SRC / "api" / "jobs.py").read_text(encoding="utf-8")
    job = (_SRC / "ingest" / "import_job.py").read_text(encoding="utf-8")
    # the manager: pausable, resumable, reuses the batched ingest, DB-writer via SessionLocal
    assert "class NewsletterImportManager" in job and "def resume(" in job
    assert "ingest_emails" in job and "SessionLocal" in job
    # resume survives an app restart: a persisted on-disk cursor, restored on construction
    assert "_load_persisted" in job and "def _save(" in job and "_STATE_FILE" in job
    # endpoints
    assert '"/newsletters/import-folder"' in ing and '"/newsletters/import-folder/status"' in ing
    # /api/jobs surfaces it as a DB-WRITER (kind="import" -> arbitration with collect)
    assert "def _import_jobs(" in jobs and '"kind": "import"' in jobs and '"newsletter-import"' in jobs
    # UI
    assert 'id="nl-folder"' in html and 'onclick="startFolderImport(' in html
    assert "function startFolderImport(" in app and "/api/newsletters/import-folder" in app


def test_newsletter_import_perf_and_upload_cap():
    """Brief §2.B: .eml ingest BATCHES commits (per-message fsync was the bottleneck on a
    20 GB+ folder) with a per-message fallback so a collision never loses data; and the
    upload endpoint raises Starlette's max_files=1000 default (HTTP 400 at ~1300 files)."""
    email = (_SRC / "ingest" / "email.py").read_text(encoding="utf-8")
    ing = (_SRC / "api" / "ingestion.py").read_text(encoding="utf-8")
    # batched commits + the no-data-loss fallback
    assert "commit_batch" in email and "OO_EMAIL_COMMIT_BATCH" in email
    assert "def _flush(" in email and "def _commit_one(" in email
    # the upload cap is raised above Starlette's 1000 default via manual form parsing
    assert "_MAX_UPLOAD_FILES" in ing and "request.form(max_files=" in ing


def test_advanced_search_sort_by_metadata():
    """Brief §2.D ('important'): /api/articles can sort by a metadata field (date|source|
    title|language) — an honest ordering, never a relevance/quality score — surfaced as a
    Sort control in the Advanced-search panel."""
    main = (_SRC / "api" / "main.py").read_text(encoding="utf-8")
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # backend: the params + the valid-field set + case-insensitive alphabetical
    assert "sort_by:" in main and "sort_dir:" in main and "_SORT_FIELDS" in main
    assert 'collate("NOCASE")' in main  # case-insensitive alphabetical, both paths agree
    # no score: the sort fields are pure metadata
    assert '{"date", "source", "title", "language"}' in main
    # UI: the sort + order selects + they feed the query
    assert 'id="an-adv-sort"' in html and 'id="an-adv-dir"' in html
    assert 'p.set("sort_by"' in app and 'p.set("sort_dir"' in app


def test_articles_provenance_toggle_and_keyword_count():
    """The unified analysis Articles subtab gains a content-provenance toggle (all/
    wikipedia/web/newsletter/statistics — a DESCRIPTIVE ingestion-channel filter, never a
    quality score) plus a small per-article keyword count (mentions of the searched
    keyword), optionally sorting by it. Cheap by construction: a source-level filter + a
    keyword_mentions-only count (never the keyword_mentions->articles decrypt join)."""
    main = (_SRC / "api" / "main.py").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    prov = (_SRC / "catalog" / "provenance.py").read_text(encoding="utf-8")
    # provenance is a descriptive class derived from the source, explicitly NOT a score
    assert "def provenance_of(" in prov and "never a score" in prov
    assert "PROVENANCE_CLASSES" in prov
    # backend: /api/articles accepts a provenance filter + a keyword_count sort; each result
    # carries provenance + keyword_count; the count is mentions-only (no decrypt join).
    assert "_provenance_filter(" in main and "_KEYWORD_COUNT_SORT" in main
    assert "_keyword_counts(" in main and "KeywordMention.count" in main
    assert '"keyword_count": keyword_count' in main  # per-result count
    assert '"keyword_for_count"' in main  # the resolved keyword whose counts are shown
    # frontend: the provenance toggle + the count badge + the count-sort wiring
    assert "_anSetProvenance(" in app and "function _anArtControls(" in app
    assert 'q.set("provenance"' in app and 'q.set("sort_by", "keyword_count")' in app
    assert "_anKwForCount" in app


def test_cited_secondary_sources_auto_integration():
    """In-article SECONDARY sources (cited domains) auto-integrate as new DISABLED
    'cited' sources: independence measured by DISTINCT SOURCES (never article count),
    commerce/social filtered, alias-deduped, never auto-scraped, no fabricated score.
    'cited' is a descriptive provenance class that slots into the Articles toggle."""
    lib = (_SRC / "discovery" / "cited_sources.py").read_text(encoding="utf-8")
    prov = (_SRC / "catalog" / "provenance.py").read_text(encoding="utf-8")
    sm = (_SRC / "api" / "source_management.py").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    # the cited provenance CLASS is in the closed set (a channel, never a score)
    assert 'CITED = "cited"' in prov and "CITED" in prov.split("PROVENANCE_CLASSES")[1]
    # engine: distinct-SOURCE independence + disabled + no fabricated score
    assert "def promote_cited_sources(" in lib and "def cited_domain_stats(" in lib
    assert "distinct" in lib.lower() and "enabled=False" in lib
    assert "reliability_score=None" in lib  # NEVER a fabricated score
    assert "is_commerce_domain" in lib and "is_social" in lib and "is_equivalent_domain" in lib
    # endpoint: the promote route (dry_run preview + real)
    assert '"/promote-cited"' in sm and "promote_cited_sources(" in sm
    # frontend: the promote action + the 'cited' bucket in the Articles toggle
    assert "function promoteCitedSources(" in app and "/api/sources/promote-cited" in app
    assert '["cited", t("Cited sources")]' in app
    assert "promoteCitedSources()" in html


def test_large_data_folder_backup():
    """Brief §2.A: a SERVER-SIDE 'copy to a folder/drive' backup streams the big public
    re-downloadable blobs (Wikipedia dumps + OSM maps + Ollama models) into a user-chosen
    directory — too big for the in-memory encrypted oo-backup-2. Pausable job + endpoints
    + the Settings panel; the corpus stays in the encrypted backup (these copied as-is)."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    bk = (_SRC / "api" / "backup_v2.py").read_text(encoding="utf-8")
    jobs = (_SRC / "api" / "jobs.py").read_text(encoding="utf-8")
    lib = (_SRC / "backup" / "folder_backup.py").read_text(encoding="utf-8")
    # library: the reliable core (atomic copy, dedup, additive restore, pausable job)
    assert "def write_folder_backup(" in lib and "def restore_folder_backup(" in lib
    assert "def _atomic_copy(" in lib and "class FolderBackupManager" in lib
    assert "never overwrite a local file" in lib  # additive restore
    assert "copied as-is" in lib  # public blobs NOT whole-file encrypted (makes 100 GB feasible)
    # endpoints: plan/start/restore + status
    for ep in ('"/folder/plan"', '"/folder/start"', '"/folder/restore"', '"/folder/status"'):
        assert ep in bk, ep
    # /api/jobs surfaces it as a pausable file job
    assert "def _folder_backup_jobs(" in jobs and '"folder-backup"' in jobs
    # UI: reached through the unified Export/Import dialog (the standalone
    # "folder-backup-panel" was retired 2026-07-01 when Import/Export was unified).
    # The dialog streams the chosen blob categories to /folder/start and restores
    # from a server-side folder via /folder/restore.
    assert "async function openUnifiedExport(" in app and 'id="ux-export"' in html
    assert "function openUnifiedImport(" in app and 'id="ux-import"' in html
    assert '"/api/backup/folder/start"' in app and '"/api/backup/folder/restore"' in app


def test_gui_shutdown_button_and_endpoint():
    """Maintainer field test 2026-06-21: the status bar has a shutdown (power) button
    that confirms, then stops the server (the GUI equivalent of Ctrl-C) — NOT uninstall
    or panic (data untouched)."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    sysapi = (_SRC / "api" / "system.py").read_text(encoding="utf-8")
    assert 'id="app-shutdown"' in html and 'onclick="appShutdown()"' in html
    assert "async function appShutdown(" in app and "/api/system/shutdown" in app
    assert "confirm(" in app, "a confirmation prompt must precede shutdown"
    assert '@router.post("/shutdown")' in sysapi and "confirmation required" in sysapi
    # the shutdown helper must require confirm + must not be the uninstall/panic path
    sd = (_SRC / "safety" / "shutdown.py").read_text(encoding="utf-8")
    assert "def request_shutdown(" in sd and "confirm" in sd
    assert "wipe" not in sd.lower() and "rmtree" not in sd.lower(), "shutdown must not delete anything"


def test_uninstall_and_shutdown_replace_ui_with_terminal_overlay():
    """Maintainer 2026-06-21: after uninstall (and shutdown) the browser must not keep
    showing a clickable app against a dead server. Both replace the UI with a full-screen
    terminal overlay (blocking the dead tabs) + a best-effort window.close()."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function _terminalOverlay(" in app
    assert "window.close()" in app, "best-effort close (works only for script-opened tabs)"
    # both the shutdown button and the uninstall flow use it
    ov = app[app.index("function _terminalOverlay("):]
    ov = ov[: ov.index("\n    }")]
    assert "position:fixed;inset:0" in ov and "z-index:99999" in ov, "must cover/disable the UI"
    assert "_terminalOverlay(" in app[app.index("async function appShutdown("):]
    assert "_terminalOverlay(" in app[app.index("async function uninstallApp("):]


def test_airplane_flash_feedback_is_consistent_everywhere():
    """Maintainer 2026-06-21: clicking the airplane button must give the SAME visual
    feedback everywhere. The app fires a direction-aware full-screen #net-flash
    (.go-on/.go-off, animated in the shared app.css); the standalone /tasks page must
    fire the same flash when engaging airplane (the toggle that happens there)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    tm = (_SRC / "static" / "taskmanager.html").read_text(encoding="utf-8")
    css = (_SRC / "static" / "app.css").read_text(encoding="utf-8")
    assert "#net-flash" in css and ".go-off" in css and "@keyframes netflash" in css
    assert 'classList.add(online ? "go-on" : "go-off")' in app, "the app fires the flash"
    # /tasks reuses app.css and fires the identical flash on engage-airplane
    assert "function flashNet(" in tm and 'classList.add(online ? "go-on" : "go-off")' in tm
    assert "flashNet(false)" in tm


def test_airplane_toggle_gives_instant_feedback():
    """Maintainer 2026-06-27: clicking the airplane button lagged a few seconds — the POST
    that trips the kill switch + installs the socket guard blocks. Going OFFLINE must now
    react INSTANTLY: an optimistic button repaint + the flash + a brief 'Entering airplane
    mode' pop-up fire BEFORE the background POST, and a failed POST reverts honestly (we are
    NOT actually offline)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    css = (_SRC / "static" / "app.css").read_text(encoding="utf-8")
    assert "function _airplanePopup(" in app and "Entering airplane mode" in app
    assert ".net-popup" in css and "net-popup-ok" in css  # the pop-up (auto-dismiss + OK/backdrop close)
    body = app.split("async function toggleNetwork(", 1)[1].split("function _flashNet(", 1)[0]
    paint = body.find("_paintNetwork(false)")
    popup = body.find("_airplanePopup(")
    post = body.find('api("/api/system/network"')  # the only network POST in the body is the offline one
    assert 0 <= paint < post and 0 <= popup < post, (
        "the offline transition must paint the button + pop up BEFORE (not await) the network POST"
    )
    assert "_paintNetwork(true)" in body, "a refused POST must revert the button (still honest about state)"


def test_no_hardcoded_secrets_in_live_src():
    offenders = []
    for p in _live_py_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _SECRET_RE.search(line) and not any(tok in line for tok in _SECRET_ALLOW):
                offenders.append(f"{p.relative_to(_ROOT)}:{i}")
    assert not offenders, f"possible hardcoded secrets: {offenders}"


def test_quarantine_not_imported_by_live_code():
    # NB `\bquarantine\.\w` (attribute access), not `\bquarantine\.` — the bare form
    # false-positived on a docstring SENTENCE ending in "... a reversible quarantine."
    # (2026-07-14, the #674 docstring turned this guard red repo-wide).
    pattern = re.compile(r"\b(from|import)\s+quarantine\b|\bquarantine\.\w")
    offenders = [
        str(p.relative_to(_ROOT))
        for p in _live_py_files()
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"live code imports quarantined modules: {offenders}"


def test_dormant_credibility_columns_never_serialized():
    """OO-D10-002: ``credibility_score`` / ``political_bias`` are dormant
    ``ExternalSource`` columns kept null by design (the quarantine removed every
    fabricated-score surface; the stored 50.0 defaults were NULLed by migration).
    They must NEVER be re-introduced into an API response -- a future contributor
    wiring the dormant scorer into a view would resurrect the exact composite-score
    honesty violation the project forbids (no composite trust/quality scores). The
    only legitimate uses are the model definition (database/models.py) and the
    DB->DB merge copy (backup/merge.py); no API module may name them.
    """
    api_dir = _SRC / "api"
    offenders = []
    for p in api_dir.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "credibility_score" in line or "political_bias" in line:
                offenders.append(f"{p.relative_to(_ROOT)}:{i}: {line.strip()}")
    assert not offenders, (
        "dormant fabricated-score columns surfaced in an API module "
        f"(honesty-by-construction violation): {offenders}"
    )


def test_reliability_score_is_operator_set_never_computed():
    """``reliability_score`` is an INTENTIONAL exemption to the no-composite-score
    rule (audit PR E, DEFAULT APPLIED): it is operator-asserted provenance metadata
    (a 1-10 number the operator sets per source via config/CSV import), NOT a value
    the app computes. The fabricated ``=5`` default was already NULLed (migration
    f4b5c6d7e8a9). Unlike credibility_score/political_bias (never serialized), this
    field IS exposed — so the guard here is different: it must never be DERIVED from
    article data, and a briefing card can never present it as a score.

    This pins the exemption so a future contributor cannot quietly turn it into a
    computed quality verdict (the exact honesty violation the project forbids).
    """
    # 1. A briefing card can NEVER carry it — it stays in card.py's forbidden
    #    score-field set (mechanically rejected by the card schema).
    card_src = (_SRC / "briefing" / "card.py").read_text(encoding="utf-8")
    assert '"reliability_score"' in card_src, (
        "reliability_score must remain in card.py's forbidden score-field set "
        "(a card may never present it as a computed score)"
    )
    # 2. No analytics/derivation module may ASSIGN it — it is only ever set from
    #    operator config/import (catalog/csv_io, ingest/seed) or left None. A
    #    computed write here would resurrect a fabricated quality score.
    write = re.compile(
        r"\.reliability_score\s*=(?!=)|\[[\"']reliability_score[\"']\]\s*=(?!=)"
    )
    for sub in ("analysis", "analytics", "awareness", "briefing", "integrity", "signals"):
        d = _SRC / sub
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            assert not write.search(p.read_text(encoding="utf-8")), (
                f"{p.relative_to(_ROOT)}: reliability_score must never be computed/"
                "derived by analytics — it is operator-set only (CLAUDE.md exemption)"
            )
    # 3. It stays an operator-importable column (the legitimate input path).
    csv_src = (_SRC / "catalog" / "csv_io.py").read_text(encoding="utf-8")
    assert "reliability_score" in csv_src, (
        "reliability_score must stay an operator-set CSV-import column"
    )


def test_no_dangerous_eval_or_deserialization_sinks():
    """S-010: live code must stay free of code-exec / unsafe-deserialization sinks."""
    banned = re.compile(
        r"\b(eval|exec)\s*\(|\bos\.system\s*\(|subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True"
        r"|\bpickle\.(load|loads)\b|\bmarshal\.(load|loads)\b|\byaml\.load\s*\(",
    )
    offenders = []
    for p in _live_py_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if banned.search(line):
                offenders.append(f"{p.relative_to(_ROOT)}:{i}: {line.strip()[:60]}")
    assert not offenders, f"dangerous sink(s) introduced: {offenders}"


def test_readme_version_matches_package():
    """Version coherence guard (docs/CONTRIBUTING.md): the README header must state exactly
    the package version, so the two can never silently drift again."""
    from importlib.metadata import version as _pkg_version

    pkg = _pkg_version("open-omniscience")
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"\*\*Version:\*\*\s*([0-9][0-9A-Za-z.\-+]*)", readme)
    assert m, "README has no '**Version:** X' header line"
    assert m.group(1) == pkg, (
        f"README version {m.group(1)!r} != package version {pkg!r}; "
        f"update README.md to match pyproject.toml (single source of truth)."
    )


def test_version_single_sourced_from_pyproject():
    """RC gate (release-eng): the version is single-sourced from pyproject. ``src.__version__``
    must RESOLVE to the installed package metadata, and ``src/__init__.py`` must NOT hardcode a
    version literal that could silently drift (the old ``__version__ = "0.0.9"`` hazard)."""
    from importlib.metadata import version as _pkg_version

    import src

    assert src.__version__ == _pkg_version("open-omniscience"), (
        "src.__version__ must single-source from importlib.metadata (pyproject), not a literal"
    )
    init_src = (_ROOT / "src" / "__init__.py").read_text(encoding="utf-8")
    assert re.search(r'__version__\s*=\s*"[0-9]', init_src) is None, (
        "src/__init__.py must not hardcode a __version__ literal — read it from package metadata"
    )


def test_toast_messages_stay_on_screen():
    """Bottom-right popup/toast messages (including errors) must stay on screen at least a few
    seconds and pause while the user is reading them (maintainer-asked 2026-07-10). Guards
    against a regression to a too-short fixed auto-dismiss. The single ``toast()`` function in
    app.js drives every bottom-right message, so asserting on it covers the whole SPA."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function toast(msg" in app, "the single bottom-right toast() function must exist"
    # errors/warnings linger longer than the default, and a hard minimum floor prevents flashes
    assert 'kind === "err" ? 9000' in app, "error toasts must linger longer than the default"
    assert "Math.max(4000" in app, "a minimum on-screen floor (>= a few seconds) must be enforced"
    # hover / keyboard focus pauses the auto-dismiss so a message is never lost mid-read
    assert 'n.addEventListener("mouseenter"' in app and 'n.addEventListener("focusin"' in app, (
        "toast must pause its auto-dismiss on hover AND keyboard focus"
    )


def test_red_lines_not_crossed():
    """GOVERNANCE.md dual-use red lines, enforced as a tripwire: forbidden capabilities
    (biometric recognition, private-individual tracking, central telemetry) must not appear
    in live code. A test is a tripwire, not a proof — the real guarantee is culture + review.
    """
    forbidden = re.compile(
        r"\b(face_recognition|facial_recognition|deepface|voice_recognition|speaker_id"
        r"|gait_recognition|track_individual|surveil_person|telemetry_send|phone_home)\b",
        re.IGNORECASE,
    )
    offenders = []
    for p in _live_py_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if forbidden.search(line):
                offenders.append(f"{p.relative_to(_ROOT)}:{i}")
    assert not offenders, f"red-line capability present (see docs/GOVERNANCE.md): {offenders}"


def test_in_app_docs_exist_on_disk():
    main = (_SRC / "api" / "main.py").read_text(encoding="utf-8")
    files = re.findall(r'"file":\s*"([^"]+)"', main)
    assert files, "could not find the in-app _DOCS registry"
    docs_dir = _ROOT / "docs"
    missing = [f for f in files if not (docs_dir / f).exists()]
    assert not missing, f"in-app docs registered but missing on disk: {missing}"


def test_no_print_in_library_code():
    """Library code must use loggers, not print() (audit finding MAINT-04).

    print() is legitimate ONLY as deliberate CLI/console output: under an
    `if __name__ == "__main__"` demo guard, inside `def main()`, inside the
    named CLI helper functions of src/api/main.py (panic/ephemeral/serve, and
    the legal-consent CLI helpers terms/accept-terms), or in src/diagnostics.py
    (the `doctor` command, whose entire purpose is a printed terminal report).
    Anything else is a regression.
    """
    import ast

    CLI_MODULES = {"src/diagnostics.py"}
    CLI_FUNCTIONS = {
        "main",
        "_panic_cli",
        "_run_ephemeral",
        "_serve",
        "_terms_cli",
        "_accept_terms_cli",
    }

    offenders: list[str] = []
    for p in _live_py_files():
        rel = str(p.relative_to(_ROOT))
        if rel in CLI_MODULES or not rel.startswith("src/"):
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        allowed_spans: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test_src = ast.unparse(node.test)
                if "__name__" in test_src and "__main__" in test_src:
                    allowed_spans.append((node.lineno, node.end_lineno or node.lineno))
            elif isinstance(node, ast.FunctionDef) and node.name in CLI_FUNCTIONS:
                allowed_spans.append((node.lineno, node.end_lineno or node.lineno))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
                and not any(a <= node.lineno <= b for a, b in allowed_spans)
            ):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"print() in library code (use a module logger; MAINT-04): {offenders}"
    )


def test_llm_catalog_freshness():
    """The suggested model catalog goes stale fast (maintainer direction): this
    fails once CATALOG_AS_OF is older than the freshness window, forcing each
    cycle to re-verify the list against https://ollama.com/library or knowingly
    bump the date. The live picker uses the operator's INSTALLED models; this
    list is only the offline suggestion."""
    import re as _re
    from datetime import date

    from src.llm.ollama import CATALOG_AS_OF
    m = _re.fullmatch(r"(\d{4})-(\d{2})", CATALOG_AS_OF)
    assert m, f"CATALOG_AS_OF must be 'YYYY-MM', got {CATALOG_AS_OF!r}"
    y, mo = int(m.group(1)), int(m.group(2))
    age_months = (date.today().year - y) * 12 + (date.today().month - mo)
    assert age_months <= 9, (
        f"LLM model catalog is {age_months} months old (CATALOG_AS_OF={CATALOG_AS_OF}). "
        f"Re-verify src/llm/ollama.py:MODEL_CATALOG against https://ollama.com/library "
        f"and bump CATALOG_AS_OF."
    )


def test_llm_prompt_editor_is_prefilled_copyable_and_default_aware():
    """Settings → Models prompt editor (maintainer ask 2026-06-18): boxes show the whole
    prompt PRE-FILLED with the effective text, are copyable, auto-grow, and saving a box
    still equal to the default clears the override (clean provenance). Browser-unverified —
    this pins the wiring so it can't silently regress."""
    src = _ui_source()
    # pre-fill the box with the effective prompt (override OR the built-in default)
    assert "|| _llmPromptDefaults[k]" in src, "prompt boxes must be PRE-FILLED with the default"
    # auto-size to show the whole prompt + a per-prompt Copy button
    assert "_autoGrowPrompt(" in src, "prompt boxes must auto-grow to show the whole prompt"
    assert "function copyLlmPrompt(" in src and "copyLlmPrompt('summary'" in src, (
        "each prompt needs a Copy button wired to copyLlmPrompt"
    )
    assert "resize:vertical" in src, "prompt textareas must be user-resizable"
    # saving a box that still equals the default stores "" (keeps provenance "default")
    assert "_promptOut" in src, "save must send '' when the box still equals the default"
    # Part B: the built-in keyword-EXTRACTION prompt is editable alongside the other three
    assert 'id="llm-prompt-ai_keywords"' in src, "the keyword-extraction prompt box is missing"
    assert "copyLlmPrompt('ai_keywords'" in src and 'llm_prompt_ai_keywords:' in src, (
        "the extraction prompt must be copyable AND saved through the settings body"
    )
    assert '"ai_keywords"]' in src, "loadLlmPrompts must populate the ai_keywords box"


def test_custom_extractor_settings_ui_is_wired():
    """Settings → Models manages a LIST of user-defined custom extractors (maintainer ask
    2026-06-18), CRUD over /api/ai/prompts. Browser-unverified — this pins the wiring."""
    src = _ui_source()
    # the define/manage form + list
    for el in ("ai-prompts-list", "ai-prompt-label", "ai-prompt-kind", "ai-prompt-text"):
        assert f'id="{el}"' in src, f"custom-extractor UI missing #{el}"
    assert "Custom extractors" in src
    # the CRUD handlers + load wiring on the Models subtab
    assert "async function loadCustomPrompts(" in src
    assert "function saveCustomPrompt(" in src and "function deleteCustomPrompt(" in src
    assert 'api(id ? `/api/ai/prompts/${id}` : "/api/ai/prompts"' in src, (
        "save must POST a new / PUT an existing custom prompt"
    )
    assert "loadCustomPrompts();" in src and 'cat === "models"' in src


def test_custom_extractor_run_from_analysis_window_is_wired():
    """A custom extractor RUNS over the selection on demand from BOTH the analysis window
    and the search toolbar (ctx-aware). Browser-unverified — this pins the wiring."""
    src = _ui_source()
    # the ctx-aware run control is reachable from both surfaces
    assert "onclick=\"aiRunPrompt('an')\"" in src, "analysis window needs a 'Run extractor' action"
    assert "onclick=\"aiRunPrompt('search')\"" in src, "search toolbar needs a 'Run extractor' action"
    assert "async function aiRunPrompt(" in src and "async function aiRunPromptStart(" in src
    # mirrors the bulk-LLM streaming run (same ctx-keyed selection + abort), POSTs to the endpoint
    assert "_bulkParams(ctx)" in src
    assert "`/api/ai/prompts/${id}/run`" in src, "must POST to the custom-prompt run endpoint"
    # results are the AI lens, never the trusted index — the copy must say so
    assert "AI-derived metadata" in src


def test_ui_invariants():
    """Maintainer-ruled UI invariants (see CLAUDE.md). These regressed once
    between sessions; now they fail CI instead of relying on memory."""
    html = _ui_source()
    # 1. Wikipedia edition picker is a dropdown, never a text input
    assert '<select id="wiki-lang"' in html, "wiki-lang must be a <select> (CLAUDE.md #1)"
    assert '<input id="wiki-lang"' not in html
    # 3. constant top-bar footprints
    assert ".act-host:empty { visibility:hidden; }" in html, "act-host slot must stay reserved"
    assert "#llm { min-width" in html, "LLM pill needs a fixed footprint"
    # 4. §2 (ruled 2026-06-14, amends #4): vitals moved OUT of the chrome into the
    #    task-manager window's System tab; the chrome keeps a PERSISTENT task-manager
    #    access (#activity is hidden when idle).
    assert 'id="vitals-mini"' not in html, "the vitals strip must NOT live in the chrome (§2 amends #4)"
    assert 'id="tm-open"' in html and 'id="tm-system"' in html, (
        "a persistent task-manager access (#tm-open) + the System tab (#tm-system, where "
        "vitals now live) must both exist (CLAUDE.md #4, §2)"
    )
    # AMENDED 2026-07-23 (maintainer ruling): the version IS shown, in ONE place —
    # visibly under the brand name in the sidebar (was `<span id="version" hidden>`).
    # The top BAR still never shows it.
    assert '<span id="version">' in html and '<span id="version" hidden>' not in html, (
        "the version renders visibly under the brand mark (2026-07-23 amends #4)"
    )
    brand = html.split('class="brand"', 1)[1][:1600]
    assert 'id="version"' in brand, "the version span must live inside the sidebar brand block"
    # 2. sidebar: medium widths collapse to a rail, not off-canvas
    assert "@media (max-width:860px) and (min-width:601px)" in html
    # 5. the eye brand mark (grid-iris path is its fingerprint) — in index.html
    #    AND the /unlock screen (must be THE SAME canonical eye, not a variant).
    assert "C8 6.5, 24 6.5, 30 16" in html, "brand mark must be the ASCII-eye vector"
    unlock = (_SRC / "static" / "unlock.html").read_text(encoding="utf-8")
    assert "C8 6.5, 24 6.5, 30 16" in unlock and "M11 12.5 H21" in unlock, (
        "the /unlock screen must use THE canonical eye (pointed-oval + grid-iris)"
    )
    assert "C8 21.5, 24 21.5" not in unlock and 'circle cx="32"' not in unlock, (
        "the old double-arc unlock eye must be gone (one canonical brand mark)"
    )
    # 7. ONE interface (final verdict 2026-06-10): the Desk UI is retired —
    #    desk.html must stay deleted and the installer must create one launcher.
    assert not (_SRC / "static" / "desk.html").exists(), (
        "Desk is retired (CLAUDE.md): never resurrect desk.html"
    )
    installer = (_ROOT / "install.sh").read_text(encoding="utf-8")
    assert '_mk_desktop "$APP_NAME-desk"' not in installer, (
        "single-launcher verdict: the installer must not create a Desk launcher"
    )
    # 8. external links ALWAYS confirmed via popup before opening (ruled
    #    2026-06-10) — delegated capture-phase guard in the UI.
    assert "_externalLinkGuard" in html, (
        "index.html: the external-link confirmation guard must exist (CLAUDE.md)"
    )
    # 9. evidence-tiered cards (ruled 2026-06-10): the trigger audit trail —
    #    plain words FIRST, the exact math beneath, both translatable.
    assert "Why am I seeing this?" in html, "cards must explain themselves (CLAUDE.md)"
    assert "The exact math" in html, "the equations render under the plain explanation"
    # 10. bundled open-source fonts (ruled 2026-06-11): OFL files ship in the
    #     repo, @font-face declarations are local, no external font host.
    fonts = _SRC / "static" / "fonts"
    for fname in (
        "Cantarell-Regular.woff2", "Inter-Variable.woff2", "Outfit-Variable.woff2",
        "Manrope-Variable.woff2", "JetBrainsMono-Variable.woff2",
        "SourceSerif4-Variable.woff2",
    ):
        assert (fonts / fname).exists(), f"bundled font missing: {fname} (CLAUDE.md)"
    assert list(fonts.glob("OFL-*.txt")), "OFL license texts must ship with the fonts"
    assert html.count("@font-face") >= 6, "bundled fonts must be declared in index.html"
    assert "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html, (
        "fonts are bundled — never fetched from an external host"
    )
    # 11. themed form widgets (the Settings 'font cursor' bug, 2026-06-11):
    #     range sliders styled to the theme; the Appearance .seg styles must
    #     never regress to the retired drawer scoping (dead selectors).
    assert 'input[type="range"]::-webkit-slider-thumb' in html, "range sliders must be themed"
    assert ".drawer .seg" not in html, "the drawer is retired; .seg styles must be unscoped"
    # 12. the Typeface picker exists and the theme catalog never shrinks.
    assert 'id="dr-faces"' in html, "the Typeface picker must exist (CLAUDE.md)"
    # 16 CSS blocks: 17 named themes, Ink lives in :root (System is JS-only).
    assert html.count('html[data-theme="') >= 16, "the theme catalog must not shrink"
    # 13. the agenda shows DATA, never plumbing (maintainer principle 2026-06-11):
    #     the feed directory lives in Settings → Agenda, and the month grid is
    #     the tab's default view.
    agenda_tab = html.split('id="tab-agenda"', 1)[1].split('class="tab-page"', 1)[0]
    assert 'id="agenda-feeds"' not in agenda_tab, (
        "the calendar directory is plumbing — it lives in Settings, not the Agenda tab"
    )
    assert 'id="agenda-feeds"' in html, "the calendar directory must still exist (in Settings)"
    assert 'id="set-agenda"' in html, "Settings must host the Agenda configuration section"
    assert 'id="agenda-month"' in agenda_tab and 'id="agenda-views"' in agenda_tab, (
        "the agenda month grid + view switcher must exist in the tab"
    )
    assert 'return localStorage.getItem("oo.agenda.view") || "month"' in html, (
        "MONTH is the ruled default agenda view"
    )
    # 13b. Agenda article-DEDUCED dates layer: /api/events/deduced flows through the
    #      AG.events pipeline like imported events (so every view renders it), as a
    #      distinct filterable "deduced" category, with the never-confirmed caveat
    #      VISIBLE and the title opening the EXACT article set (openAnalysisForIds).
    assert "function mapDeducedToAgenda(" in html and "/api/events/deduced" in html, (
        "the agenda must map /api/events/deduced into the event pipeline (deduced layer)"
    )
    assert 'category: "deduced"' in html and 'deduced.length ? ["deduced"]' in html, (
        "deduced events must be their own filterable category, surfaced only when present"
    )
    assert "e.deduced && Array.isArray(e.article_ids)" in html and "openAnalysisForIds(" in html, (
        "a deduced agenda event's title must open its exact article set (never-confirmed, clickable)"
    )
    # 14. the network toggle is AIRPLANE-MODE (ruled 2026-06-12): one constant
    #     glyph whose FILL is the state — never ▶/⏸ action glyphs — and EVERY
    #     offline→online transition passes the ONE consent popup (local
    #     interface addresses; no public-IP echo before consent).
    # The toggle is the constant airplane GLYPH whose FILL is the state. The text
    # label was dropped when the button moved to the top bar (§3, ruled): hover +
    # FILL convey state now — but the glyph + the FILL-painting must stay.
    assert 'id="net-plane"' in html and 'id="net-toggle"' in html, (
        "the network toggle must be the constant airplane glyph (CLAUDE.md #14)"
    )
    assert 'plane.setAttribute("fill"' in html, (
        "the airplane glyph's FILL must encode the network state (CLAUDE.md #14)"
    )
    assert "▶ Online" not in html and "⏸ Offline" not in html, (
        "action glyphs must not label network STATE (CLAUDE.md #14)"
    )
    assert 'id="net-consent"' in html and "ensureOnline(" in html, (
        "every online transition must pass the consent popup"
    )
    # 14e. Threat-model honesty (RC §4 + non-negotiable): the consent popup names
    #      WHICH LAYER the kill switch controls — only THIS app's network, never the
    #      device/OS/hardware; a userspace app can never equal a hardware switch.
    assert "controls only this app's network" in html and "hardware switch" in html, (
        "the network-consent popup must state that airplane mode controls only this "
        "app's traffic (the which-layer threat-model honesty, CLAUDE.md non-negotiable)"
    )
    for fn in ("schedulerStart", "schedulerRunNow", "firstRun"):
        body = html.split(f"async function {fn}(", 1)[1].split("async function", 1)[0]
        assert "ensureOnline(" in body, f"{fn} must consent before going online"
    assert "st.online" in html, (
        "scheduler responses carry network state for the immediate repaint"
    )
    # 14c. direction-aware transition color (UI_SHELL_REDESIGN §3): the online/
    #      offline transition uses DIFFERENT colors by direction (go-on vs go-off),
    #      not one red flash that conflates the two opposite meanings.
    assert "#net-flash.go-on" in html and "#net-flash.go-off" in html, (
        "the network transition flash must be direction-aware (§3)"
    )
    assert 'classList.add(online ? "go-on" : "go-off")' in html, (
        "going online vs offline must flash different colors (§3)"
    )
    # 14b. airplane-mode onboarding coachmark (ruled 2026-06-13): the INVITATION
    #      layer only — it teaches the ONE network switch but must NEVER bypass
    #      consent. Its "Go online" action routes through toggleNetwork() (which
    #      calls ensureOnline), so the coach itself never flips the network.
    assert 'id="net-coach"' in html, (
        "the airplane-mode onboarding coachmark must exist (CLAUDE.md)"
    )
    assert "dismissNetCoach(true); toggleNetwork();" in html, (
        "the coach 'Go online' must route through toggleNetwork()/ensureOnline — "
        "the invitation layer must never bypass the consent popup (CLAUDE.md #14)"
    )
    # 14d. Item V — airplane-mode PAUSED status honesty (ruled 2026-06-16, reversing
    #      the earlier muted treatment): a background pass that airplane mode has
    #      paused must NOT keep painting the active-green "Collecting…" chip. The
    #      paused chip is the SAME red as the engaged airplane button (var(--err)),
    #      the label is the keyed "Collecting paused…", and the fast activity poll
    #      honors the scheduler's own online flag so the chip can never lag green.
    assert ".activity.paused { color:var(--err)" in html, (
        "the paused activity chip must be red (var(--err), the airplane-button color), "
        "never muted (CLAUDE.md Item V, ruled 2026-06-16)"
    )
    assert ".activity.paused { color:var(--muted)" not in html, (
        "the paused chip must NOT use the reverted muted color (CLAUDE.md Item V)"
    )
    assert 'T("Collecting paused") + "…"' in html, (
        "the paused label must read 'Collecting paused…' (CLAUDE.md Item V)"
    )
    assert "s.online !== _netOnline" in html, (
        "the activity poll must honor the scheduler's online flag so a paused pass "
        "never lags as green Collecting… (CLAUDE.md Item V hardening)"
    )
    # 15. a PERMANENT language switcher lives in the top bar (ruled, RC gate):
    #     flag = visual convention only, the NATIVE NAME is the identifier;
    #     one click switches the whole UI via the one i18n engine.
    assert 'id="lang-switch"' in html and 'id="lang-menu"' in html, (
        "the permanent top-bar language switcher must exist (CLAUDE.md #15)"
    )
    assert "OOI18N.setLang(code)" in html, "the switcher must use THE i18n engine"
    for native in ("Français", "中文", "العربية", "Русский", "日本語"):
        # html already IS index.html's content (read at the top of this test).
        assert native in html, f"native name {native!r} must appear in the menu data"
    # 16. ONE chart toolkit, detailed-curves SYSTEMATIC (ruled 2026-06-12):
    #     full series always (no thinning), wheel zoom / drag pan / pinned readout.
    #     AMENDED by Item Y (ruled 2026-06-15): sparse series (n<10) render as a BAR
    #     graph (not dots), n>=10 as the full-resolution line; the "early corpus / no
    #     curve interpolated" caveat is REMOVED app-wide, only n=x is kept. Both
    #     renderers (ooChart + dashChartSvg) share the _SPARSE_BAR_MAX threshold.
    assert "function ooChart(" in html, "the one chart toolkit must exist (CLAUDE.md #16)"
    assert "never downsampled" in html, (
        "the toolkit must state and implement the full-resolution rule (CLAUDE.md #16)"
    )
    # Item Y: the n<10->bar rule is shared by both renderers, and the old sparse
    # caveat string is gone from the rendered UI (only the count n=x remains).
    assert "_SPARSE_BAR_MAX" in html and html.count("barMode") >= 2, (
        "n<10 must render as a BAR graph in both renderers via _SPARSE_BAR_MAX (Item Y)"
    )
    assert "dots shown, no curve interpolated through sparse points" not in html, (
        "the early-corpus sparse caveat must be removed app-wide (Item Y amends #16)"
    )
    for surface in (
        # P2-10: the commodity price detail moved into the shared fullscreen overlay
        # (chartSymbol -> chartEnlarge -> ooChart), so #mkt-chart-oo is no longer a
        # surface; chartEnlarge is the toolkit path now.
        'ooChart($("ins-trend-oo")',
        'ooChart($("idx-chart-oo")',  # indices detail rolled onto ooChart
    ):
        assert surface in html, f"chart surface must use THE toolkit: {surface}"
    assert "chartEnlarge(`${symbol}" in html, (
        "the commodity price detail must route through the shared chartEnlarge (ooChart) overlay (P2-10)"
    )
    # 17. the universal hover-for-information convention (ruled 2026-06-12,
    #     the informed-consent instrument): every titled element is marked
    #     automatically (dotted accent underline / corner dot) and opens ONE
    #     shared bubble; touch gets long-press; one delegated listener only.
    assert ".oo-tip-target" in html and 'tip.id = "oo-tip"' in html, (
        "the hover-affordance theme must exist (CLAUDE.md #17)"
    )
    assert "ooTipInit" in html and "touchstart" in html, (
        "the enhancer must be universal (auto-mark + touch long-press)"
    )
    # 6-EXTENDED (first target SHIPPED 2026-06-12): Home-card external evidence
    #    opens the LOCAL preview popup first — never a bare outbound jump — and
    #    the popup's outbound anchor shows the FULL URL as its visible text.
    assert 'id="link-preview"' in html, "the local link-preview dialog must exist (CLAUDE.md #6e)"
    assert "openLinkPreview('${esc(safeUrl(e.url))}')" in html, (
        "card evidence must route external links through the local preview (CLAUDE.md #6e)"
    )
    assert ">${esc(d.url)}</a>" in html, (
        "the outbound anchor's visible text must BE the full URL (CLAUDE.md #6e)"
    )
    # 6e-SWEEP (ruled "no bare source ↗ ANYWHERE"): one extLink() helper renders
    # every outbound source link via the local preview; no surface jumps straight
    # out. Guard the helper exists and that the bare target=_blank source↗ pattern
    # is gone from the data surfaces (search rows, markets, law, events, insights).
    assert "function extLink(url, label" in html, (
        "the extLink() outbound-link helper must exist (CLAUDE.md #6e sweep)"
    )
    import re as _re
    bare = _re.findall(r'target="_blank"[^>]*>(?:source|official source|official|'
                       r'Official[^<]*source)(?:&nbsp;|\s)?↗?</a>', html)
    assert not bare, f"bare external source↗ links must route through extLink (#6e): {bare[:3]}"
    # 18. ONE universal subtab component (keystone, ruled 2026-06-13): a single
    #     reusable helper drives the vertical subtab grammar everywhere — lateral
    #     sidebar = main tabs, vertical subtabs = facets. It owns ARIA + keyboard
    #     + roving tabindex; it must be reused on >=3 surfaces (Insights, Settings,
    #     corpus window) and the old per-surface attributes must be gone.
    assert "function ooSubtabs(" in html, (
        "the universal subtab component must exist (CLAUDE.md #18)"
    )
    assert 'aria-selected' in html and 'setAttribute("role", "tab")' in html, (
        "the subtab component must set ARIA roles/selection (accessibility)"
    )
    for surface in ('ooSubtabs($("ins-subtabs")', 'ooSubtabs($("set-subtabs")',
                    'ooSubtabs($("corpus-subtabs")'):
        assert surface in html, f"the subtab component must drive: {surface} (>=3 surfaces)"
    assert "data-ins" not in html and "data-set=" not in html and "data-ctab" not in html, (
        "divergent per-surface subtab attributes must be unified onto data-tab (CLAUDE.md #18)"
    )
    # 19. Home redesign (UI_SHELL_REDESIGN_PLAN §5): a compact at-a-glance stats
    #     strip is pinned at the TOP of Home; the Quick actions section is gone.
    home = html.split('id="tab-home"', 1)[1].split('id="tab-search"', 1)[0]
    assert "home-glance" in home and 'id="home-stats"' in home and "stat-strip" in home, (
        "Home must open with the compact at-a-glance strip (UI_SHELL_REDESIGN §5)"
    )
    assert "Quick actions" not in home and 'class="quick"' not in home, (
        "the Home Quick actions section must be removed (UI_SHELL_REDESIGN §5)"
    )
    assert home.index("home-glance") < home.index("Briefing</h2>"), (
        "the at-a-glance strip must sit at the TOP of Home, above the Briefing"
    )
    # 19b. Home card families as vertical subtabs (§5): the briefing renders a
    #      family subtab bar driven by THE universal component, with an "All Leads"
    #      default lens and a per-family hue accent on cards. ("Leads" = the
    #      user-facing rename of the briefing-card label, ruled 2026-06-16 §3.)
    assert 'ooSubtabs($("home-fam-subtabs")' in html and "selectHomeFamily" in html, (
        "Home card families must use the universal subtab component (CLAUDE.md #18/#19)"
    )
    assert 'data-tab="__all"' in html and "All Leads" in html, (
        "the family lens must default to an 'All Leads' subtab (§5)"
    )
    assert "--fam:" in html, "cards must carry the family-hue left accent (§5)"
    # 19c. Home → dashboard / helicopter view (UI rethink, Item 4b): a compact
    #      "Trending now" glance is REDUNDANT by design — it hides when nothing is
    #      trending (Home never blank-and-silent: the Briefing still renders) and
    #      every term DEEP-LINKS to its real tab (the analysis window; "More in
    #      Insights →" to the canonical Trends view). Fed by the disclosed
    #      window-vs-baseline rate (never a score); reuses the existing endpoint.
    assert 'id="home-trends-panel"' in home and 'id="home-trends"' in home, (
        "Home must carry the (redundant, deep-linking) Trending-now dashboard panel (Item 4b)"
    )
    assert "function loadHomeTrends(" in html and "loadHomeTrends()" in html, (
        "loadHomeTrends() must render Home trends and be called from loadHome (Item 4b)"
    )
    assert "/api/insights/trending-windows" in html.split("function loadHomeTrends(", 1)[1][:600], (
        "Home trends must reuse the trending-windows endpoint (no new backend, Item 4b)"
    )
    # Redundant + deep-linking: the panel is hidden until there is data, and a term
    # opens the analysis window (openAnalysisFor); nothing on Home is unique (#8).
    assert 'id="home-trends-panel" hidden' in home, (
        "the Home trends panel must default hidden (Home never blank-and-silent, Item 4b)"
    )
    assert "_insSubtabs&&_insSubtabs.select('trends')" in home, (
        "the Home 'More in Insights' link must deep-link to the Trends subtab (Item 4b)"
    )
    # 20. Task-manager window (ruled ×3): the vitals BUBBLE graduates to a
    #     dedicated tabbed WINDOW driven by the universal subtab component, with
    #     at least Tasks + System tabs. (Slice 1 — reuses the proven render/poll.)
    assert 'class="vitals-pop taskmgr"' in html and 'id="tm-subtabs"' in html, (
        "the task-manager window + its subtab bar must exist (CLAUDE.md)"
    )
    assert 'ooSubtabs($("tm-subtabs")' in html, (
        "the task-manager window must use THE universal subtab component"
    )
    assert 'id="tm-tasks"' in html and 'id="tm-system"' in html, (
        "the task-manager window needs Tasks + System panels"
    )
    # 20b. Active/Queue split (CLAUDE.md #20 REMAINING): running work and work
    #      waiting its turn are distinct subtabs of the SAME window, driven by
    #      the universal subtab component (data-tab, no inline onclick). The
    #      Queue panel surfaces the wiki-dump download queue with its reorder
    #      controls; both panels reuse ONE row renderer so the controls stay
    #      identical. Labels are DOM text (auto-translated x12).
    assert '<button data-tab="queue">Queue</button>' in html, (
        "the task-manager window needs a Queue subtab button (data-tab, DOM-text label; CLAUDE.md #20)"
    )
    assert 'id="tm-queue"' in html and 'id="queue-body"' in html, (
        "the task-manager Queue panel (#tm-queue / #queue-body) must exist (CLAUDE.md #20)"
    )
    assert 'data-tab="queue"' in html and "onclick" not in (
        html.split('id="tm-subtabs"', 1)[1].split("</nav>", 1)[0]
    ), "the Queue subtab must use data-tab via ooSubtabs, never inline onclick (CLAUDE.md #18)"
    assert "function _jobRow(" in html and "_jobRow(j, queuedKeysByKind, t)" in html, (
        "Active and Queue must share ONE job-row renderer (_jobRow) so controls stay identical"
    )
    # The Queue must still drive the real reorder endpoint (no invented backend).
    assert "/api/jobs/dumps/reorder" in html, (
        "the Queue reorder must POST the existing /api/jobs/dumps/reorder endpoint"
    )
    # 20d. Per-job controls extended to OSM-region downloads + a Resume action
    #      for paused/failed downloads (Item 2, Groups C/M). ONE row renderer now
    #      serves BOTH bulk-download kinds (wiki dumps + OSM regions); reorder is
    #      kind-aware (each manager owns its queue) and resume routes through the
    #      ONE network-consent popup (a resume re-opens a fetch — invariant #14).
    assert '_isDownloadKind(' in html and 'k === "osm-map"' in html, (
        "the job-row controls must cover OSM-region downloads, not only wiki dumps (Item 2)"
    )
    assert "/api/jobs/osm/reorder" in html, (
        "OSM queued downloads must reorder via the existing /api/jobs/osm/reorder endpoint"
    )
    assert "function jobResume(" in html and "/resume" in html, (
        "paused/failed downloads must offer Resume via jobResume() -> /api/jobs/{id}/resume"
    )
    _resume_body = html.split("function jobResume(", 1)[1][:500]
    assert "ensureOnline(" in _resume_body, (
        "jobResume must pass the ONE network-consent popup (invariant #14) before resuming"
    )
    # 20c. Sources/Schedule (CLAUDE.md #20 REMAINING): the same window gains a
    #      Schedule subtab surfacing the REAL collection schedule/activity. It is
    #      driven by the universal subtab component (data-tab, no inline onclick),
    #      its label is DOM text (auto-translated x12), and it reuses the EXISTING
    #      scheduler endpoint (/api/scheduler/activity already polled by the
    #      window) — never a new backend or a fabricated countdown.
    assert '<button data-tab="schedule">Schedule</button>' in html, (
        "the task-manager window needs a Schedule subtab button (data-tab, DOM-text label; CLAUDE.md #20)"
    )
    assert 'id="tm-schedule"' in html and 'id="sched-tm-body"' in html, (
        "the task-manager Schedule panel (#tm-schedule / #sched-tm-body) must exist (CLAUDE.md #20)"
    )
    # The subtab nav must stay inline-onclick-free (driven by ooSubtabs/data-tab).
    assert "onclick" not in (
        html.split('id="tm-subtabs"', 1)[1].split("</nav>", 1)[0]
    ), "the Schedule subtab must use data-tab via ooSubtabs, never inline onclick (CLAUDE.md #18)"
    assert "function _renderSchedule(" in html, (
        "the Schedule panel needs its renderer (_renderSchedule)"
    )
    # It must read the EXISTING scheduler-activity data, not invent a new endpoint.
    assert "/api/scheduler/activity" in html, (
        "the Schedule panel must reuse the existing /api/scheduler/activity data (no new backend; CLAUDE.md #20)"
    )
    # 20e. Coverage (per-tag scraping REACH): a Coverage subtab surfaces which
    #      tags have been reached, how many sources remain, at what %, built ONLY
    #      from the collector's own fetch timestamps (reach + freshness, never a
    #      completion claim or a score). Same subtab grammar (data-tab, DOM-text
    #      label, no inline onclick in the nav — asserted above); its own
    #      read-only endpoint; loaded lazily when the subtab opens.
    assert '<button data-tab="coverage">Coverage</button>' in html, (
        "the task-manager window needs a Coverage subtab button (data-tab, DOM-text label)"
    )
    assert 'id="tm-coverage"' in html and 'id="cov-tm-body"' in html, (
        "the task-manager Coverage panel (#tm-coverage / #cov-tm-body) must exist"
    )
    assert "function loadTagCoverage(" in html and "function _renderCoverage(" in html, (
        "the Coverage panel needs its loader + renderer (loadTagCoverage/_renderCoverage)"
    )
    assert "/api/scheduler/coverage" in html, (
        "the Coverage panel must read the read-only /api/scheduler/coverage endpoint"
    )
    # 21. Insights auto-indexes in the background (UI_SHELL_REDESIGN §6): the
    #     manual "Index corpus" button + palette action are gone; indexing follows
    #     ingest and a silent top-up clears any legacy backlog when Insights opens.
    assert "indexCorpus" not in html and ">Index corpus<" not in html, (
        "the manual 'Index corpus' button/action must be removed (UI_SHELL §6)"
    )
    assert "function autoIndexInsights(" in html and "autoIndexInsights()" in html, (
        "Insights must auto-index in the background (UI_SHELL §6)"
    )
    # 21b. Insights Trends shows the THREE preset windows side by side (24h · week ·
    #      month) — the ruled Trends redesign (2026-06-16). Additive to the
    #      adjustable single-window view; fed by /api/insights/trending-windows.
    assert 'id="trd-windows"' in html, "the Trends 3-window panel container must exist (Trends redesign)"
    assert "function loadTrendWindows(" in html and "/api/insights/trending-windows" in html, (
        "loadTrendWindows() must render the three preset windows from /trending-windows"
    )
    # 21b+. Each window's top terms render a daily sparkline from the series_top
    #       backend (additive), via the shared honest renderer (dashChartSvg: line
    #       when dense, Item-Y bars when sparse — never an interpolated curve).
    assert "series_top=6" in html and "dashChartSvg(" in html, (
        "loadTrendWindows() must request series_top and render per-term sparklines "
        "(series_top==limit so EVERY shown trending keyword is a small time-series graph)"
    )
    # 21b++. Each Trends sparkline can be ENLARGED into the interactive ooChart
    #        (invariant #16: full-resolution zoom/pan/readout; Item-Y bars when
    #        n<10) via a reusable modal dialog — no extra fetch (the daily series
    #        is already in the trending-windows payload). Item 1, Group E.
    assert 'id="chart-enlarge"' in html and "function chartEnlarge(" in html, (
        "the reusable chart-enlarge <dialog> + chartEnlarge() must exist (Item 1)"
    )
    assert "function enlargeTrend(" in html and "enlargeTrend(" in html, (
        "loadTrendWindows() sparklines must offer per-term enlarge via enlargeTrend()"
    )
    # 21c. Insights Convergence: a read-only view over GET /api/insights/convergences
    #      (space-time co-occurrence). Additive; independence is by distinct sources,
    #      co-occurrence is never causation — the API method+caveat are shown VISIBLE
    #      by default (informed consent), the cluster opens its exact article set.
    assert 'data-tab="convergence"' in html and 'id="ins-convergence"' in html, (
        "the Convergence subtab button + its panel must exist (Insights convergence view)"
    )
    assert "function loadConvergences(" in html and 'cat === "convergence"' in html, (
        "loadConvergences() must exist and be lazy-loaded from showInsightCat()"
    )
    assert "/api/insights/convergences" in html and "openAnalysisForIds(" in html, (
        "the convergence view must read /api/insights/convergences and open the exact article set"
    )
    # 21d. Convergence WATCH engine (ruling 2026-06-17 #3, ON by default): a Watches
    #      Insights subtab to create/list/enable-disable/edit/delete saved local
    #      conditions + browse firing history; a watch fires a "watch" Lead card. The
    #      engine runs automatically (in refresh_briefing) — local-only, no consent
    #      gate, no score. (Browser-unverified: this static guard pins the wiring.)
    assert 'data-tab="watches"' in html and 'id="ins-watches"' in html, (
        "the Watches subtab button + its panel must exist (watch engine #3)"
    )
    for fn in ("function loadWatches(", "function createWatch(", "function evaluateWatches("):
        assert fn in html, f"the Watches view needs {fn}"
    assert 'cat === "watches"' in html, "loadWatches() must be lazy-loaded from showInsightCat()"
    assert "/api/watches" in html and "/api/watches/evaluate" in html, (
        "the Watches view must read the watch CRUD + evaluate endpoints"
    )
    # A fired watch opens its EXACT article set (the history rows seed the analysis window).
    watches_js = html.split("function loadWatches(", 1)[1].split("function createWatch(", 1)[0]
    assert "openAnalysisForIds(" in watches_js, (
        "a watch's history must open its exact article set via openAnalysisForIds"
    )
    # 22. The analysis window (Group F, keystone #4): a full-screen #analyze tab
    #     driven by the universal subtab component, fed by the article-SET keyword
    #     endpoint, opened from the Search tab's Analyze button. Counts, no verdict.
    assert 'id="tab-analyze"' in html, (
        "the analysis window panel must exist (Group F); the Analysis SIDEBAR entry was "
        "retired 2026-06-20 — it is reached via search / openAnalysisFor, not a sidebar tab"
    )
    assert 'ooSubtabs($("an-subtabs")' in html, (
        "the analysis window must use THE universal subtab component"
    )
    assert "/api/insights/corpus-keywords" in html and "function openAnalysis(" in html, (
        "the analysis window must query the article-set keyword endpoint (Group F)"
    )
    # Its analysis subtabs over the matched set: When/Where/Who (deduced) + Links
    # (shared-origin structure). Each is an article-SET aggregation, counts only.
    assert '/api/insights/corpus-www' in html and 'id="an-www"' in html, (
        "the analysis window must carry the When/Where/Who subtab (Group F)"
    )
    # P5.1b: the When/Where/Who values are CLICKABLE FACETS — each drills into a corpus
    # narrowed to the articles that mention it (a facet co-equal with the text query).
    assert "function branchByFacet(" in html and "/api/insights/corpus-facet-articles" in html, (
        "the When/Where/Who facets must drill via the corpus-facet-articles endpoint (P5.1b)"
    )
    assert "_anFacets" in html and 'col(t("When")' in html, (
        "the facet surface must add the temporal (When) facet column (P5.1b)"
    )
    assert '/api/links/corpus' in html and 'id="an-links"' in html, (
        "the analysis window must carry the shared-Links subtab (Group F)"
    )
    assert '/api/insights/corpus-sentiment' in html and 'id="an-sentiment"' in html, (
        "the analysis window must carry the Sentiment subtab (Group F)"
    )
    assert '/api/insights/corpus-sources' in html and 'id="an-sources"' in html, (
        "the analysis window must carry the source-coverage subtab (Group F)"
    )
    assert 'id="an-advanced"' in html and "function anRunAdvanced(" in html, (
        "the analysis window must carry the Advanced-search tab that re-runs the "
        "analysis from refined filters (Group F, keystone #4)"
    )
    # 22b. Markets commodity overlay (Item 3, Group G): a commodity click opens the
    #      analysis window with a conditionally-shown Price subtab that overlays the
    #      PRICE curve with the corpus COVERAGE timeline on a SHARED time axis —
    #      co-occurrence, NEVER causation (shown visible). Dual LABELLED axes (each
    #      series its own scale; no magnitude conflation); reuses existing endpoints.
    assert 'data-tab="price"' in html and 'id="an-price-tab"' in html and 'id="an-price"' in html, (
        "the analysis window must carry the (commodity-gated) Price overlay subtab (Item 3)"
    )
    assert "function commodityOverlaySvg(" in html and "function renderAnPrice(" in html, (
        "the price x coverage overlay renderer + its loader must exist (Item 3)"
    )
    # Seeded by the commodity card (the title/Analyse buttons pass {commodity:...})
    # and threaded through openAnalysisFor's opts into _anCommodity.
    assert "_anCommodity" in html and "opts && opts.commodity" in html and "{commodity:" in html, (
        "the commodity identity must thread from the card into the Price overlay (Item 3)"
    )
    # The "co-occurrence … never causation" GRAPH caveat was REMOVED from charts
    # (maintainer ruling 2026-06-17 — it cluttered every graph); the Price overlay
    # must no longer show it. The non-causation PRINCIPLE still governs the design.
    assert "co-occurrence in your corpus, never causation" not in html.split(
        "function renderAnPrice(", 1
    )[1][:1500], "the graph causation caveat was removed (maintainer 2026-06-17)"
    # 23. Caveats are VISIBLE BY DEFAULT (permanent informed-consent invariant —
    #     CLAUDE.md Non-negotiables). AMENDED 2026-06-23 (flip cards): a Lead card now
    #     has a FRONT (the lead at a glance) + a BACK; the CAVEAT renders in a visible
    #     .card-caveat line on the card BACK — an equal side revealed by ONE flip, never
    #     a hidden toggle/checkbox — right beside the action that opens its corpus. It is
    #     in the DOM by default (not behind [hidden]); only the FRONT is decluttered.
    card_html = html.split("function cardHtml(", 1)[1].split("\n    function ", 1)[0]
    assert "card-face card-front" in card_html and "card-face card-back" in card_html, (
        "Lead cards must have a flip FRONT + BACK (maintainer 2026-06-23)"
    )
    assert '<p class="card-caveat">${esc(c.caveat)}</p>' in card_html, (
        "every Lead card must render its caveat VISIBLE BY DEFAULT in a .card-caveat "
        "line (CLAUDE.md informed-consent: never hidden behind a calm-UI toggle)"
    )
    # The caveat sits on the BACK face, NOT the front (decluttered) — and not behind a toggle.
    front_region = card_html.split("card-face card-front", 1)[1].split("card-face card-back", 1)[0]
    assert "card-caveat" not in front_region, (
        "the caveat must be on the card BACK, not the front face (maintainer 2026-06-23)"
    )
    back_region = card_html.split("card-face card-back", 1)[1]
    assert "${caveatLine}" in back_region, "the caveat must render on the card BACK face"
    # The verbose method renders on the back (the flip IS the detail layer now).
    assert "esc(c.method)" in card_html and 'class="mc"' in card_html, (
        "the method must render on the card back (the flip replaced the per-card '?')"
    )
    # Clicking flips; the standardized, family-themed button opens the corpus IN A NEW WINDOW.
    # lead-card-nested-interactive (P1, GUI-test finding): the flip trigger moved from
    # the outer .card (now a plain role="group" wrapper) onto the front face
    # specifically, resolving the ancestor .card via closest() -- see
    # test_lead_card_flip_trigger_is_not_nested_inside_an_interactive_role for the
    # full structural regression coverage of this restructuring.
    assert "function leadFlip(" in html and "leadFlip(this.closest('.card'),event)" in card_html, (
        "clicking a Lead card's front face must flip it (maintainer 2026-06-23)"
    )
    # corpus-open-dblclick-duplicate-tabs (P1): the direct window.open() moved into the
    # shared _openCorpusUrlOnce() debounce (a same-URL open within 700ms is a no-op) --
    # openCardCorpus still opens a real new window at "/?...", just through that helper.
    assert "function openCardCorpus(" in html and '_openCorpusUrlOnce("/?" + p.toString())' in html, (
        "the back's 'Open corpus' button must open the card's corpus in a new window"
    )
    assert "function _openCorpusUrlOnce(url)" in html and 'window.open(url, "_blank", "noopener")' in html, (
        "_openCorpusUrlOnce (the shared double-click debounce) must still perform a real window.open"
    )
    assert 'class="lead-open"' in card_html, "the back needs the standardized themed open-corpus button"
    assert "_hydrateCardCorpus" in html and '"corpus"' in html, (
        "a boot deep-link must hydrate the analysis from ?corpus= in the new window"
    )
    # Equal-size, family-themed flip cards (CSS): a 3D flip + a fixed height + --fam theming.
    assert "rotateY(180deg)" in html and "--lead-h" in html and ".lead-open" in html, (
        "Lead cards must be equal-size flip cards themed by family (--fam)"
    )
    # The caveat colour must be theme-aware (var(--caveat)), not a hardcoded hex that
    # fails WCAG AA on light themes — the most ethically important strings stay legible.
    assert "--caveat:" in html and "color:var(--caveat)" in html, (
        "caveat text must use the theme-aware var(--caveat) (WCAG AA across all 17 themes)"
    )
    # 24. Charts expose a text alternative (audit PR G, a11y): <canvas>/<svg> charts
    #     are opaque to screen readers, so every chart carries role="img" + a
    #     translated aria-label SUMMARY and a visually-hidden data table.
    assert "function _chartAria(" in html and "function _chartSrTable(" in html, (
        "charts must build a translated aria summary + a visually-hidden data table"
    )
    assert 'cv.setAttribute("role", "img")' in html and 'cv.setAttribute("aria-label"' in html, (
        "the ooChart canvas must expose role=img + an aria-label (a11y)"
    )
    assert 'role="img" aria-label="${esc(aria)}"' in html, (
        "the dashChartSvg <svg> must carry a translated aria-label (a11y)"
    )
    assert '<table class="sr-only">' in html, (
        "charts must ship a visually-hidden data-table fallback (a11y)"
    )
    # 25. Adaptive idle polling (audit PR G): the always-on chrome polls back off
    #     when idle instead of hammering the encrypted DB (field-log finding B). The
    #     network/activity polls route through the one adaptive helper.
    assert "function _adaptivePoll(" in html, (
        "the adaptive idle-backoff poll helper must exist (UI polling storm fix)"
    )
    assert "_adaptivePoll(_pollNetwork)" in html and "_adaptivePoll(_pollActivity)" in html, (
        "the always-on network/activity polls must use the adaptive backoff helper"
    )
    assert "setInterval(_pollNetwork" not in html, (
        "the fixed-interval network poll must be replaced by the adaptive backoff"
    )
    # 26. index.html monolith decomposed (audit PR H): the inline <style>/<script>
    #     were externalised into cached /static/app.css + /static/app.js (classic
    #     script, same load order, globals + inline handlers preserved). The markup
    #     file must LINK both and carry no inline blocks. (Read index.html alone here
    #     — the rest of this test uses _ui_source() so the moved JS/CSS still grep.)
    raw = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/static/app.css">' in raw, (
        "index.html must link the externalised stylesheet (PR H)"
    )
    assert '<script src="/static/app.js"></script>' in raw, (
        "index.html must load the externalised app.js (PR H)"
    )
    assert "<style>" not in raw and "\n  <script>\n" not in raw, (
        "no inline <style>/<script> may remain in index.html (PR H decomposition)"
    )
    assert raw.index("/static/i18n.js") < raw.index("/static/app.js"), (
        "i18n.js must still load before app.js (load order preserved)"
    )
    # 27. Offline-map (Group M) download manager in Settings: a region picker over
    #     /api/geo/regions + a resumable download-job table over /api/geo/downloads,
    #     living in a Settings subtab. Starting a download is a NETWORK action, so it
    #     MUST pass the ONE consent popup (ensureOnline, invariant #14) — assert the
    #     gate is present in the start path so it can't regress to a silent fetch.
    assert 'data-tab="offlinemap"' in html and 'id="set-offlinemap"' in html, (
        "the Offline map Settings subtab button + panel must exist (Group M frontend)"
    )
    assert "function loadOsmMap(" in html and 'cat === "offlinemap"' in html, (
        "loadOsmMap() must exist and be lazy-loaded from showSetCat()"
    )
    assert "/api/geo/regions" in html and "/api/geo/downloads" in html, (
        "the offline-map view must read the region catalogue + the download jobs"
    )
    assert "function startOsmDownload(" in html and "ensureOnline(" in html, (
        "starting an OSM download must pass the ONE consent popup (ensureOnline, invariant #14)"
    )
    # 28. LLM model management is a DEDICATED Settings subtab (Q6=A) with explicit
    #     actions over the existing endpoints — pull (NDJSON stream), remove, and the
    #     active-model picker (PUT /api/settings llm_model). Pulling is a network
    #     action over CLEARNET via Ollama, so it MUST pass the ONE consent popup
    #     (ensureOnline, invariant #14) — asserted so it can't regress to a silent pull.
    assert 'data-tab="models"' in html and 'id="set-models"' in html, (
        "the Models Settings subtab button + panel must exist (LLM management, Q6)"
    )
    assert "function pullModel(" in html and "function removeModel(" in html and (
        "function setActiveModel(" in html
    ), "the LLM subtab must wire pull / remove / set-active actions"
    assert "/api/llm/pull" in html and "/api/llm/remove" in html, (
        "the LLM subtab must call the pull + remove endpoints"
    )
    assert '"/api/settings", {method: "PUT"' in html or "llm_model" in html, (
        "set-active must persist the choice via PUT /api/settings {llm_model}"
    )
    # the pull path is gated by the ONE consent popup (clearnet egress via Ollama)
    assert "ensureOnline(" in html, "pulling a model must pass ensureOnline (invariant #14)"
    # 29. Official-statistics producers (Group N) Settings subtab: a descriptive
    #     directory over /api/stats/agencies + a one-click "register as DISABLED
    #     sources" action over /api/stats/sources/ingest, living in a Settings subtab.
    #     The directory is DESCRIPTIVE only (no figures, no score, NO "controversial"
    #     verdict label — ruling #50: a producer is a stanced source stated as a
    #     caveat; the user judges). Outbound home URLs MUST go through extLink so they
    #     open the LOCAL preview first (invariant #6/#6e — no bare external <a href>).
    assert 'data-tab="stats"' in html and 'id="set-stats"' in html, (
        "the Statistics Settings subtab button + panel must exist (Group N frontend)"
    )
    assert "function loadStatAgencies(" in html and 'cat === "stats"' in html, (
        "loadStatAgencies() must exist and be lazy-loaded from showSetCat()"
    )
    assert "/api/stats/agencies" in html and "/api/stats/sources/ingest" in html, (
        "the Statistics view must read the agency directory + the ingest endpoint"
    )
    # The agencies render must route home URLs through extLink (local preview, #6).
    stats_fn = html.split("function loadStatAgencies(", 1)[1].split("function ingestStatSources(", 1)[0]
    assert "extLink(" in stats_fn, (
        "the agencies render must use extLink() for home_url (invariant #6/#6e — "
        "outbound links open the local preview, never a bare external <a href>)"
    )
    # 29b. Official-statistics FIGURES UI (Group N figure layer): the Statistics subtab
    #      also carries a consented fetch + the stored-figures table + triangulation. The
    #      fetch is a network action -> it MUST pass ensureOnline (invariant #14); it reads
    #      the figure endpoints; triangulation is shown side by side. (Browser-unverified:
    #      this static guard pins the wiring so it cannot silently regress — fork-3.)
    for fn in ("function fetchStatFigure(", "function loadStatFigures(", "function triangulateStatSeries("):
        assert fn in html, f"the figures UI needs {fn}"
    assert 'id="set-stats"' in html and 'id="statfig-fetch"' in html and 'id="statfig-table"' in html, (
        "the figures panel (fetch button + table) must exist in the Statistics subtab"
    )
    assert "/api/stats/figures/fetch" in html and "/api/stats/triangulate" in html, (
        "the figures UI must call the fetch + triangulate endpoints"
    )
    fetchfig = html.split("function fetchStatFigure(", 1)[1].split("function loadStatFigures(", 1)[0]
    assert "ensureOnline(" in fetchfig, (
        "fetching official figures is a network action -> must pass ensureOnline (invariant #14)"
    )
    # 29c. Scheduled stat-vintage auto-refresh (ruling #12): the Statistics subtab lists
    #      TRACKED subscriptions (each fetch is replayed on its interval for new vintages)
    #      with enable/disable/remove + a "refresh due now". Surfaced + manageable, no score.
    for fn in ("function loadStatSubs(", "function toggleStatSub(", "function refreshStatSubs("):
        assert fn in html, f"the tracked-figures UI needs {fn}"
    assert 'id="statfig-subs"' in html and "/api/stats/subscriptions" in html, (
        "the tracked-figures panel + its subscriptions endpoint must be wired (ruling #12)"
    )

    # --- 30. Alternative-interfaces gallery (Settings -> GUIs, maintainer-ruled
    #     2026-06-17): a SANDBOX gallery of eight opt-in interfaces, each a
    #     SHARED-CORE SHELL that reuses app.js's id-targeted render logic under a
    #     scoped skin (html[data-ui="<id>"]); the default interface stays the
    #     guarded reference + default. The ethical non-negotiables are preserved
    #     BY CONSTRUCTION (same DOM) and enforced file-by-file in
    #     tests/test_gui_alternatives.py. Here we pin the additive WIRING so a
    #     future session cannot silently drop it.
    assert '<script src="/static/guis/boot.js">' in html, (
        "the GUIs boot loader must be included in <head> (applies the chosen skin before first paint)"
    )
    assert "/static/guis/gallery.js" in html, "the GUIs gallery renderer must be included"
    # The GUIs gallery is now folded into the unified "Graphics" subtab (Appearance +
    # GUIs, remark 11). The #guis-gallery host is preserved (nothing lost).
    assert (
        'data-tab="graphics"' in html and 'id="set-graphics"' in html and 'id="guis-gallery"' in html
    ), "the Graphics subtab must carry the #guis-gallery host (Appearance + GUIs fused)"
    assert 'cat === "graphics"' in html and "OOGUIs.renderGallery" in html, (
        "showSetCat() must lazy-render the gallery when the Graphics subtab is shown"
    )


def test_diagnostics_panel_button_consolidation():
    """DIAGNOSE-THE-DIAGNOSTICS ruling #7 (AMENDED 2026-07-20): remove all per-report
    DOWNLOAD buttons from the diagnostics panel except the ONE all-diagnostics button --
    safe because the completeness ratchet guarantees the bundle carries every covered
    report. THE DISTINCTION that must survive: job-starters/interactive ACTIONS are not
    report downloads and stay untouched; and a download button whose exact content is
    NOT actually in the bundle (a full-dump export the manifest's own 'excluded' block
    documents, or an endpoint on a DIFFERENT router the diagnostics ratchet never scans)
    must also stay -- removing it would strand that data behind no UI at all, which is
    not what the ruling asks for ("do not weaken that ratchet")."""
    html = _ui_source()

    # (a) ONE-BUTTON STATE: every plain per-report download button whose content the
    # all-diagnostics bundle ACTUALLY carries (per _DIAG_COVERAGE_MAP) must be gone --
    # these paths are covered 1:1 by a bundle member with no other stated exemption.
    removed_download_urls = (
        "/api/diagnostics/keyword-selftest?download=1",
        "/api/diagnostics/keyword-engine?download=1",
        "/api/diagnostics/keyword-growth?download=1",
        "/api/diagnostics/article-length?download=1",
        "/api/diagnostics/non-article-scan?download=1",
        "/api/diagnostics/source-audit?download=1",
        "/api/diagnostics/source-audit-selftest?download=1",
        "/api/diagnostics/home-cards?download=1",
        "/api/diagnostics/dates',",
        "/api/diagnostics/network',",
        "/api/diagnostics/performance',",
        "/api/diagnostics/benchmark',",
        "/api/diagnostics/debug-bundle',",
        "/api/diagnostics/request-latency',",
        "/api/diagnostics/slow-queries',",
        "/api/diagnostics/schema-drift',",
        "/api/diagnostics/integrity',",
        "/api/diagnostics/frontend-errors',",
    )
    for url in removed_download_urls:
        assert url not in html, f"a covered per-report download button survived: {url}"

    # (b) DELIBERATELY KEPT exceptions -- NOT weakening the ratchet:
    #   - the full keyword-corpus dump (both size variants): the manifest's own
    #     'excluded' block says the bundle carries only the bounded DIGEST, so these
    #     buttons are each report's ONLY full-dump access, not a redundant download.
    assert "window.open('/api/diagnostics/keywords?format=zip','_blank')" in html
    assert "per_lang=1000000" in html and "All keywords (.zip)" in html
    #   - source-quality + rollup-benchmark: explicitly named as surviving ACTIONS in
    #     the AMENDED ruling despite living in the same button row.
    assert "window.open('/api/diagnostics/source-quality?download=1','_blank')" in html
    assert "window.open('/api/diagnostics/rollup-benchmark','_blank')" in html
    #   - the 4 statistical-signal reports: on DIFFERENT routers (signals.py/insights.py),
    #     never scanned by the diagnostics-router ratchet and not bundle members --
    #     removing them would strand that data behind no UI at all.
    for url in (
        "/api/signals/fdr-selftest?download=1",
        "/api/signals/flood',",
        "/api/signals/bury',",
        "/api/insights/lunar-correlation',",
    ):
        assert url in html, f"a cross-router signal report (outside the ratchet) must stay: {url}"

    # (c) SURVIVING ACTION CONTROLS (job-starters / interactive tools, never downloads):
    for marker in (
        'id="all-diag-btn"', "runAllDiagnostics(", 'id="p0-run-btn"', "runP0Validation(",
        'id="psb-run-btn"', "runPagesizeBench(", "viewKeywordGrowth(", "enrichSources(",
        "enrichSourceTypes(", "discoverSources(", "discoverWorld(", "goldBuilderLoad(",
        "goldBuilderSave(", "loadLemmaPreview(", "runIrEval(", "loadSessionForensics(",
    ):
        assert marker in html, f"a surviving action control must still be wired: {marker}"


def test_corpus_tier_header():
    """Corpus maturity tier on Home (evidence-tiered cards REMAINING slice): a
    DESCRIPTIVE stage (early/developing/established) rides with the at-a-glance
    strip so a reader calibrates how much weight the evidence cards deserve.
    Binding (pinned so it cannot regress):
      * the tier element lives IN the Home glance strip (invariant #19 intact),
        not as a card, and is rendered from the additive briefing field;
      * the visible surface keeps the real numbers; an EARLY corpus shows the
        short "thin evidence" caveat inline (informed consent, visible by default);
      * the LONG explanation AND the exact thresholds live in the #oo-tip hover
        (invariant #17 — a translated title) — never hidden behind a toggle;
      * it is descriptive, NEVER a score bar / composite."""
    html = _ui_source()
    home = html.split('id="tab-home"', 1)[1].split('id="tab-search"', 1)[0]
    # 1. the tier element sits inside the glance strip, above the Briefing.
    assert 'id="home-tier"' in home and "corpus-tier" in home, (
        "the corpus maturity tier must render in the Home glance strip"
    )
    assert home.index("home-glance") < home.index('id="home-tier"') < home.index("Briefing</h2>"), (
        "the tier must ride WITH the at-a-glance strip, above the Briefing (invariant #19)"
    )
    # 2. it is rendered from the additive briefing field, not recomputed in JS.
    assert "function renderCorpusTier(" in html and "renderCorpusTier(data.corpus_tier)" in html, (
        "the tier must render from the additive briefing corpus_tier field"
    )
    # 3. the three descriptive stage labels exist (keyed x12 by the integrator).
    for stage in ("Early corpus", "Developing corpus", "Established corpus"):
        assert stage in html, f"the tier stage label is missing: {stage}"
    # 4. the early-corpus caveat is present (visible short form), and the hover
    #    carries the thresholds (the title is set with the threshold numbers).
    assert "thin evidence — read with care" in html, (
        "an early corpus must show the visible 'thin evidence' caveat (informed consent)"
    )
    assert "el.title =" in html.split("function renderCorpusTier(", 1)[1].split("function renderBriefing(", 1)[0], (
        "the tier must carry a #oo-tip hover title (invariant #17) with the threshold long-form"
    )
    assert "Thresholds:" in html, "the tier hover must state the exact thresholds verbatim"
    # 5. honesty: no score bar / composite for the tier.
    assert "tier-score" not in html and "maturity-score" not in html, (
        "the corpus tier is descriptive — never a score bar / composite"
    )


def test_first_launch_guide_wizard():
    """First-launch GUIDED SETUP (ruled 2026-06-13): a ONE-TIME stepped wizard
    walks a new user to a working app. Steps = Language -> Finish/start-collecting
    (the two inert "Coming soon" encryption + sources placeholders were removed
    2026-06-18 — encryption is chosen in the DB-unlock/install flow and sources
    auto-seed). Binding constraints, pinned so they cannot regress between sessions:
      * the wizard exists and REPLACES the #onboard welcome card as the first-run
        entry (the empty-corpus check opens it instead of the card);
      * the Language step switches the WHOLE UI through THE i18n engine
        (invariant #15) — it reuses pickLang/OOI18N.setLang, never a new list;
      * INFORMED CONSENT is never bypassed (invariant #14): the wizard is the
        INVITATION layer only — its "Go online" path routes through the existing
        firstRun()/toggleNetwork() flow (which calls ensureOnline); the wizard
        must NOT POST /api/system/network itself;
      * the one-time state is a USER-VISIBLE setting, not a hidden flag."""
    html = _ui_source()
    # 1. the wizard shell exists (stepped dialog with the standard nav).
    assert 'id="guide-wizard"' in html, "the first-launch guided wizard must exist (CLAUDE.md)"
    assert "function openGuide(" in html, "the wizard must be openable (openGuide)"
    for ctrl in ('id="gw-back"', 'id="gw-next"', 'id="gw-finish"', 'id="gw-dots"'):
        assert ctrl in html, f"the wizard shell control is missing: {ctrl}"
    # the real steps — the kept-but-unreachable Language DOM (Desk lesson), the S4.7
    # SOURCES-BY-THEME step, and Finish. The inert "Coming soon" encryption placeholder
    # was removed 2026-06-18; the sources placeholder became a REAL step in S4.7.
    for step in ('data-step="lang"', 'data-step="sources"', 'data-step="finish"'):
        assert step in html, f"the wizard step is missing: {step}"
    assert 'data-step="encryption"' not in html, "the inert encryption placeholder must be gone"
    # the sources step is REAL (a theme picker + emphasis), not an inert "Coming soon".
    assert 'id="gw-themes"' in html and 'id="gw-emph-langs"' in html, (
        "the S4.7 sources step must carry the real theme picker + language-emphasis controls"
    )
    # 2. Language step uses THE i18n engine via the shared picker (no new list).
    gw = html.split('id="guide-wizard"', 1)[1].split("</dialog>", 1)[0]
    assert 'id="gw-langs"' in gw, "the wizard must carry the Language step's picker"
    assert "function _gwRenderLangs(" in html and "pickLang(b.dataset.lang)" in html, (
        "the Language step must switch the whole UI through pickLang()/OOI18N.setLang "
        "(invariant #15) — it must not build a second language list"
    )
    # 3. INFORMED CONSENT — the wizard NEVER posts the network itself; "Go online &
    #    start collecting" routes through ensureOnline (invariant #14), which stays
    #    the ONE function in the whole app that ever POSTs /api/system/network.
    #    (product feedback 2026-07-17: the finish step's own screen now carries the
    #    SAME disclosure #net-consent shows [_gwRenderFinish, local interface IPs],
    #    so its call passes skipDialog:true to skip a now-redundant second dialog
    #    for the identical decision — the actual POST still lives only inside
    #    ensureOnline, never inlined into the wizard's own onclick body.)
    go_block = html.split('if (go) go.onclick', 1)[1].split("};", 1)[0]
    assert 'api("/api/system/network"' not in go_block, (
        "the wizard must NOT POST the network itself — it is the invitation layer "
        "only; going online must pass ensureOnline (CLAUDE.md #14)"
    )
    assert "ensureOnline(" in go_block, (
        "the wizard's 'Go online' must route through ensureOnline (CLAUDE.md #14)"
    )
    # The actual go-ONLINE POST is factored into ONE shared helper (_postGoOnline),
    # used by BOTH ensureOnline's dialog "ok" button and a skipDialog caller — never
    # a second inlined copy (the SEPARATE go-OFFLINE POST in toggleNetwork, {online:
    # false}, is a different action and legitimately its own call site).
    assert html.count('body: JSON.stringify({online:true})') == 1, (
        "the network-online POST must exist in exactly ONE place (_postGoOnline) — "
        "a second inlined copy would defeat the single-canonical-gate guarantee"
    )
    assert "async function _postGoOnline()" in html, "the shared go-online POST helper must exist"
    assert "if (opts.skipDialog) return _postGoOnline();" in html, (
        "ensureOnline's skipDialog path must reuse the shared helper, not a separate POST"
    )
    assert "done(await _postGoOnline())" in html, (
        "the dialog's own 'ok' button must also reuse the shared helper"
    )
    # 4. the wizard REPLACES the #onboard card as the first-run entry: the empty-
    #    corpus check opens the guide (and falls back to the card only afterwards).
    empty = html.split("async function checkEmptyCorpus(", 1)[1].split("async function", 1)[0]
    assert "openGuide()" in empty and "guideDone()" in empty, (
        "the empty-corpus first-run must open the guided wizard, gated by its "
        "one-time done state (the wizard REPLACES the #onboard card)"
    )
    # 5. the one-time state is a USER-VISIBLE setting (a Settings toggle), never
    #    a hidden flag.
    assert 'id="set-rerun-guide"' in html and "function setRerunGuide(" in html, (
        "the one-time guide state must be a user-visible Settings toggle, not a "
        "hidden flag (CLAUDE.md: 'a user-visible setting, not a hidden flag')"
    )
    assert "Re-run the first-launch guide" in html, (
        "the Settings toggle label must exist (and be keyed for i18n)"
    )


def test_guide_finish_step_shows_consent_disclosure_inline():
    """Product feedback 2026-07-17: the finish step used to be a plain button that,
    when clicked, closed the wizard and opened a SEPARATE #net-consent dialog
    showing the local interface IPs + the informed-consent wording -- two
    consecutive screens for the same "go online" decision. The finish step's OWN
    screen now shows that SAME disclosure inline (reusing #net-consent's exact,
    already-×12-keyed strings verbatim, so no new locale work is needed), fetched
    by _gwRenderFinish as soon as the step is shown."""
    html = _ui_source()
    gw = html.split('id="guide-wizard"', 1)[1].split("</dialog>", 1)[0]
    finish = gw.split('data-step="finish"', 1)[1].split("</section>", 1)[0]
    assert 'id="gw-ifaces"' in finish, "the finish step must carry an inline interfaces box"
    for phrase in (
        "Your machine presents these local network addresses:",
        "Beyond these local addresses, the internet sees whatever",
        "Airplane mode here controls only this app's network",
    ):
        assert phrase in finish, f"the finish step must show the same disclosure #net-consent uses: {phrase!r}"
    assert "async function _gwRenderFinish()" in html, "the finish-step interfaces renderer must exist"
    assert '"/api/system/interfaces"' in html.split("async function _gwRenderFinish(", 1)[1].split("\n    }\n", 1)[0], (
        "_gwRenderFinish must fetch the real interfaces, not fabricate them"
    )
    assert 'if (step === "finish") _gwRenderFinish();' in html, (
        "_gwPaint must render the disclosure when the finish step is shown"
    )


def test_net_coach_suppressed_while_the_wizard_is_open():
    """Product feedback 2026-07-17: on a fresh install, the guide wizard's own
    finish step invites "Go online & start collecting" while the airplane-mode
    coachmark (#net-coach) COULD ALSO be showing at the same time, pointing at the
    top-bar toggle with the same invitation — two prompts visible at once for one
    decision. maybeShowNetCoach now skips while the wizard is open, and openGuide
    hides the coach (non-permanently -- it must still be able to teach a later,
    non-wizard session) if it was already showing when the wizard opens."""
    html = _ui_source()
    coach_fn = html.split("function maybeShowNetCoach() {", 1)[1].split("\n    }\n", 1)[0]
    assert '$("guide-wizard")' in coach_fn and "wiz.open" in coach_fn, (
        "maybeShowNetCoach must not show while the guide wizard is open"
    )
    guide_fn = html.split("function openGuide() {", 1)[1].split("\n    }\n", 1)[0]
    assert "dismissNetCoach(false)" in guide_fn, (
        "openGuide must hide an already-showing coach NON-permanently (it may still "
        "teach a later session where the guide won't reopen)"
    )


def test_net_coach_never_places_above_the_topbar_row():
    """GUI-test findings net-coach-blocks-topbar-buttons (P0) + netcoach-blocks-lang-switch
    (P1, same root cause): _placeCoach()'s fallback branch (used whenever there is no room
    to the right of #net-toggle) computed `top = b.top - gap - h`, placing the coach ABOVE
    the button. Because the topbar sits at the very top of the viewport, that value is
    almost always deeply negative, and the subsequent clamp (`Math.max(pad, ...)`) always
    collapsed it right back down to `pad` -- landing the coach back inside the topbar's own
    row, overlapping #net-toggle/#lang-switch/#tm-open/#app-shutdown every single time this
    branch ran (verified live: document.elementFromPoint() at each button's center resolved
    to the coach, not the button, and a real Playwright .click() timed out). The fallback
    now places the coach BELOW the union of every button it must never cover -- the one
    direction structurally guaranteed to have room near a top-anchored topbar -- confirmed
    live: at both 1400px (room to the right, "left" branch) and 900px (no room, "below"
    branch forced), all four buttons independently resolve document.elementFromPoint() to
    themselves while the coach is showing."""
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    fn = js.split("function _placeCoach() {", 1)[1].split("\n    }\n", 1)[0]
    assert "top = b.top - gap - h" not in fn, (
        "the old always-fails-near-the-topbar fallback (place above the single button, "
        "then clamp) must be gone"
    )
    assert '"net-toggle", "lang-switch", "tm-open", "app-shutdown"' in fn, (
        "the fallback must compute a union rect over ALL FOUR protected buttons, not just "
        "the one #net-toggle it points at"
    )
    assert "guardBottom + gap" in fn, (
        "the fallback must place the coach BELOW the guard-button union (never above), the "
        "one direction guaranteed to have room near a top-anchored topbar"
    )


def test_topbar_wraps_instead_of_overflowing():
    """GUI-test findings topbar-overflow-mobile-375-net-toggle-unreachable (P0) +
    topbar-overflow-mainstream-widths (P1): .topbar was `display:flex` with the default
    `flex-wrap:nowrap` and no bounding media query anywhere in the stylesheet, so
    documentElement.scrollWidth exceeded clientWidth at every mainstream breakpoint down
    to 375px, pushing the airplane toggle (the sole informed-consent gate), the language
    switcher, the task-manager button, and the shutdown button off-screen with zero
    scroll affordance. flex-wrap:wrap lets the row grow additional rows instead of forcing
    horizontal overflow -- confirmed live at 1400/1024/768/601px (documentElement.scrollWidth
    == clientWidth, all four buttons on-screen and clickable at every width; #app-shutdown
    wraps to its own second row at 601px). NOTE: at 375px a SEPARATE, previously-undiscovered
    overflow source was found in Home's .panel.home-glance / #home-stats.stat-strip flex row
    (unrelated to the topbar; its own root cause and fix are out of scope here and are
    recorded as a fresh follow-up, not silently absorbed into this fix) -- this test pins
    only the topbar's OWN contribution, which is what these two findings are about."""
    css = (_SRC / "static" / "app.css").read_text(encoding="utf-8")
    topbar_rule = css.split(".topbar {", 1)[1].split("}", 1)[0]
    assert "flex-wrap:wrap" in topbar_rule.replace(" ", ""), (
        ".topbar must wrap onto additional rows instead of forcing horizontal overflow "
        "at narrow viewports"
    )


def test_collect_tab_moved_into_settings():
    """Content-first (§6, ruled 2026-06-13): the Collect tab LEFT the sidebar for a
    Settings subtab. The Desk lesson, enforced — nothing is lost: the scheduler +
    manual-ingest + batch-picker controls now live under #set-collect, reachable via
    the Collect subtab AND the showTab('ingest') redirect (so the palette + the
    'Collect now' buttons still land); the sidebar no longer offers it."""
    html = _ui_source()
    sidebar = html.split('id="set-subtabs"')[0]
    assert 'data-tab="ingest"' not in sidebar, "Collect must leave the sidebar (content-first)"
    assert 'id="set-collect"' in html and '<button data-tab="collect">' in html, (
        "Collect must exist as a Settings subtab (#set-collect + its nav button)"
    )
    # absorption: the moved controls must all still exist (nothing lost in the move —
    # the schedule/manual/batch knobs are demoted into "Advanced (legacy)" <details>,
    # NOT deleted; the full removal is a browser-verified follow-up per Q6a)
    for ctrl in ('id="sched-status"', "saveScheduler(", 'id="ing-url"', 'id="bi-search"'):
        assert ctrl in html, f"moved Collect control missing after the move: {ctrl}"
    # Simplification (2026-07-14): collection is one on/off toggle, no schedule to program.
    assert 'id="collect-toggle"' in html and "function collectToggle(" in html, (
        "Collection must present a single on/off toggle (collect-toggle + collectToggle)"
    )
    assert 'class="adv-collect"' in html, (
        "the schedule/manual/batch knobs must be demoted into the Advanced (legacy) details"
    )
    # the redirect keeps every showTab('ingest') reference working
    assert 'if (name === "ingest")' in html and '_setSubtabs.select("collect")' in html, (
        "showTab('ingest') must redirect to Settings → Collect"
    )
    assert 'if (cat === "collect") loadScheduler()' in html, (
        "the Collect subtab must run the scheduler's onShow load"
    )


def test_collection_speed_control_is_a_download_rate_target_with_maximum():
    """Bandwidth-governed collection (maintainer ruling 2026-06-16): the user-facing
    control is a DOWNLOAD-RATE target slider (kbps) with a 'Maximum' end-stop, not a
    raw task count. Honesty by construction — the visible caveat states it is a
    target not a guarantee and that per-host politeness is never traded for speed."""
    html = _ui_source()
    # The slider + its live "now" readout exist in the Collect subtab.
    assert 'id="sch-speed"' in html and 'type="range"' in html, "rate slider missing"
    assert 'id="sch-speed-now"' in html, "live measured-rate readout missing"
    # The stops drive a rate target, with the last stop = Maximum (governor mode).
    assert "SCHED_SPEED_STOPS" in html, "speed-stop mapping missing"
    # Save wires the download-rate model, never a bare worker count.
    assert "collect_rate_mode" in html and "collect_target_kbps" in html, (
        "the save must send the download-rate model (mode + target kbps)"
    )
    # Caveats VISIBLE by default (informed consent): the honest framing must ship.
    assert "A target, not a guarantee." in html, "the honest 'target not guarantee' caveat is required"
    assert "Per-host politeness is never traded for speed." in html, (
        "the source-respect guarantee must be stated in the control's hover"
    )


def test_sources_tab_moved_into_settings():
    """Content-first (§6, ruled 2026-06-13): the Sources tab LEFT the sidebar for a
    Settings subtab, same pattern as Collect. Nothing lost — the managed-sources
    table, candidates panel, and add-source form live under #set-sources, reachable
    via the Sources subtab AND the showTab('sources') redirect; the sidebar drops it."""
    html = _ui_source()
    assert '<button class="nav-item" data-tab="sources"' not in html, (
        "Sources must leave the sidebar (content-first)"
    )
    assert 'id="set-sources"' in html, "Sources must exist as a Settings subtab panel"
    for ctrl in ('id="src-table"', 'id="candidates-list"', "addSource(", 'id="src-search"'):
        assert ctrl in html, f"moved Sources control missing after the move: {ctrl}"
    assert 'if (name === "sources")' in html and '_setSubtabs.select("sources")' in html, (
        "showTab('sources') must redirect to Settings → Sources"
    )
    # The Sources subtab runs its onShow loads (loadSrcFacets feeds the #23 multi-select
    # dropdowns; managed-sources + candidates as before). Assert each call, not the exact
    # line, so adding an onShow load never reddens this verbatim check again.
    src_onshow = html.split('if (cat === "sources") {', 1)[1].split("}", 1)[0]
    for call in ("loadSrcFacets()", "loadManagedSources()", "loadCandidates()"):
        assert call in src_onshow, f"the Sources subtab onShow must run {call}"


def test_wikipedia_tab_moved_into_settings():
    """Content-first (§6, ruled 2026-06-13): the Wikipedia tab LEFT the sidebar. Unlike
    Collect/Sources this was a MERGE — Settings already had a Wikipedia subtab
    (#set-wikipedia, the offline dumps), so #tab-wiki's change-tracking / watch-a-page /
    flagged-changes sections folded INTO that one panel. Nothing lost: both feature sets
    now live under #set-wikipedia, reachable via the existing Wikipedia subtab AND the
    showTab('wiki') redirect; the sidebar drops it. The invariant-#1 #wiki-lang <select>
    moved intact (also pinned by the edition-picker invariant)."""
    html = _ui_source()
    assert '<button class="nav-item" data-tab="wiki"' not in html, (
        "Wikipedia must leave the sidebar (content-first)"
    )
    assert 'id="tab-wiki"' not in html, "the standalone Wikipedia tab-page must be gone"
    # both feature sets must coexist inside the single #set-wikipedia panel
    seg = html[html.index('id="set-wikipedia"'):html.index('id="set-agenda"')]
    for needle in ('Wikipedia change-tracking', 'id="wiki-pages"', 'id="wiki-changes"',
                   'id="wiki-lang"', 'Wikipedia offline baselines', 'id="dump-lang"'):
        assert needle in seg, f"Settings → Wikipedia missing merged content: {needle}"
    assert 'if (name === "wiki")' in html and '_setSubtabs.select("wikipedia")' in html, (
        "showTab('wiki') must redirect to Settings → Wikipedia"
    )
    assert 'if (cat === "wikipedia") loadWiki()' in html, (
        "the Wikipedia subtab must run loadWiki (tracking) on show"
    )


def test_sp500_is_classified_as_index():
    """The S&P 500 is an INDEX, not a commodity (maintainer-ruled): it must live
    in the index catalog and never in the commodity catalog, so the Commodities
    board excludes it. Locks the 2026-06-14 finding that this is already true."""
    from src.markets.feed_catalog import load_feeds, load_index_feeds

    idx = {f.symbol for f in load_index_feeds()}
    com = {f.symbol for f in load_feeds()}
    assert "SP500" in idx, "S&P 500 (SP500) must be in the index catalog"
    assert "SP500" not in com, "S&P 500 must NOT be in the commodity catalog"


def test_dropdown_option_labels_are_translatable():
    """Every static <select> CONTROL option label is keyed for i18n and safe to
    translate (ledger Item D, 2026-06-15: "none of the dropdown menus have been
    translated — check app-wide").

    The i18n engine rewrites an option's text node in place, so a translated
    option whose value is implicit (text == submitted value) would corrupt the
    form. This gate therefore asserts two things for every non-excluded select:
    (1) each static option label exists as a key in en.json (translatable), and
    (2) each carries an explicit ``value=`` (translating the text is safe).
    Data/native selects are excluded by id (the language picker keeps native
    names by design — invariant #15; wiki editions + loading placeholders are
    data, not chrome). A NEW unkeyed control option fails CI here.
    """
    import json

    html = _ui_source()
    en = set(json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8")))

    # Selects whose option labels are DATA or native-by-design (not chrome):
    exclude = {
        "oo-lang-select",  # native language names — invariant #15 (stay English)
        "wiki-lang",       # wiki edition data, e.g. "English (en)"
        "dump-lang",       # dynamic placeholder, replaced by edition data
        "dumpread-wiki",   # dynamic placeholder ("—")
        "osm-region",      # dynamic placeholder, replaced by /api/geo/regions data
        "statfig-source",  # producer proper names (World Bank / Eurostat) — data, not chrome
        "mbox-proto",      # protocol acronyms (IMAP / POP3) — data, not chrome
    }

    unkeyed: list[str] = []
    no_value: list[str] = []
    for m in re.finditer(r'<select\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
        sid = m.group(1)
        if sid in exclude:
            continue
        for om in re.finditer(r"<option\b([^>]*)>(.*?)</option>", m.group(2), re.S):
            attrs = om.group(1)
            label = re.sub(r"\s+", " ", om.group(2)).strip()
            if not label:
                continue
            if label not in en:
                unkeyed.append(f"#{sid}:{label!r}")
            if "value=" not in attrs:
                no_value.append(f"#{sid}:{label!r}")

    assert not unkeyed, (
        "static <select> option labels not keyed in en.json (Item D regression — "
        "key them ×12 and translate): " + ", ".join(unkeyed)
    )
    assert not no_value, (
        "translatable <option> without an explicit value= (the i18n text rewrite "
        "would corrupt the submitted value — add value=): " + ", ".join(no_value)
    )


def test_agenda_view_switch_and_week_view():
    """Agenda rework (ledger Item C, 2026-06-15): the Month/List dropdown became a
    uniform subtab switch (the ooSubtabs grammar — invariant #18 / Item J) with a
    new WEEK (7-day) view; the agenda uses the full content width.

    Guards the shape so it can't silently regress: the old <select id="agenda-view">
    is gone, replaced by a <nav id="agenda-views"> with month/week/list data-tab
    buttons wired through ooSubtabs; the Week renderer + its date helpers + the
    full-width rule all exist.
    """
    html = _ui_source()

    assert 'id="agenda-view"' not in html, "the Month/List <select> must be replaced by the subtab switch"
    assert 'id="agenda-views"' in html, "the view switch must be a <nav id='agenda-views'>"
    for view in ("month", "week", "list"):
        assert f'data-tab="{view}"' in html, f"the view switch must offer the {view} view"
    assert 'ooSubtabs($("agenda-views")' in html, "the view switch must use the universal ooSubtabs component (Item J)"
    assert 'id="agenda-week"' in html, "the Week view needs its render container"
    for fn in ("function renderAgendaWeek", "function agEventsOn", "function agPickDate", "function agWeekShift"):
        assert fn in html, f"the Week view requires {fn}()"
    assert "#tab-agenda { max-width:none; }" in html, "the agenda must use the full content width (maximize space)"


def test_agenda_category_chips_and_country_flags():
    """Agenda rework (ledger Item C d/e, 2026-06-15): the Category dropdown became
    distinct-colored, data-driven chips (extensible — a new catalog category like
    "religious" appears automatically), and the Country picker shows ISO-2 flag
    emoji beside the code (the code stays the unambiguous identifier — flags ≠
    identity).
    """
    html = _ui_source()

    assert 'id="agenda-cat"' not in html, "the Category <select> must be replaced by colored chips"
    assert 'id="agenda-cats"' in html, "the category chips need their container"
    for fn in ("function renderAgendaCatChips", "function agSetCat", "function agCatHue", "function agFlag"):
        assert fn in html, f"category chips / flags require {fn}()"
    assert "const cat = _agCat," in html, "the category filter must read the chip state (_agCat), not the removed select"
    # Data-driven from the catalog facets — the "real event tags (drop the useless
    # 'imported' category)" rework (39353cf) now folds the imported feeds' real kinds in
    # via a Set, so the assignment is `[...new Set((fac.categories || []).concat(...))]`.
    assert "AG.categories = [...new Set((fac.categories" in html, (
        "categories must be data-driven from the catalog facets"
    )
    assert "${agFlag(x)} ${esc(x)}" in html, "country options must show the flag emoji beside the ISO-2 code"
    assert ".ag-catchip" in html, "the category chips need their styling"
    # the future "religious" category is pre-keyed so its chip is born translated
    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    assert "religious" in en, "the forthcoming 'religious' category label must be keyed ×12"


def test_dates_render_in_app_language_not_browser_locale():
    """User-facing dates use the app language, not the browser locale (ledger Item
    F broader note, 2026-06-15): the shared ``fmtDateTime()`` formats via
    ``Intl.DateTimeFormat(OOI18N.current(), …)`` (full month name in the chosen UI
    language). The browser-locale anti-pattern ``new Date(x).toLocaleString()`` —
    which ignores the app language entirely — must not reappear for date display.
    """
    html = _ui_source()
    assert "function fmtDateTime" in html and "Intl.DateTimeFormat(OOI18N.current()" in html, (
        "the shared locale-aware date/time formatter must exist"
    )
    offenders = re.findall(r"new Date\([^)]*\)\.toLocaleString", html)
    assert not offenders, (
        f"browser-locale date display reintroduced (use fmtDateTime instead): {offenders}"
    )


def test_live_mailbox_pull_ui():
    """Live mailbox ingestion (ruling 2026-06-17 #11): Settings → Newsletters gains a
    "Pull from a mailbox (IMAP/POP3)" form. It is a NETWORK action -> must pass
    ensureOnline (invariant #14); it posts to /api/newsletters/mailbox; the anonymise +
    kill-switch guarantees live in the (tested) backend. Browser-unverified static guard."""
    html = _ui_source()
    assert 'id="set-newsletters"' in html and "function pullMailbox(" in html, (
        "the mailbox-pull form + handler must exist in the Newsletters subtab (#11)"
    )
    assert 'id="mbox-host"' in html and 'id="mbox-proto"' in html, "mailbox form fields must exist"
    assert "/api/newsletters/mailbox" in html, "the pull must call the mailbox endpoint"
    pull = html.split("function pullMailbox(", 1)[1].split("function ", 1)[0]
    assert "ensureOnline(" in pull, (
        "pulling a mailbox is a network action -> must pass ensureOnline (invariant #14)"
    )


def test_agenda_source_manager_sort_and_status_filter():
    """Settings → Agenda is a sortable, status-filterable source manager (ledger
    Item E-b, 2026-06-15: "present them with possible sorting capabilities … bulk
    select all dysfunctional, or per country"). The sort + status-filter controls
    and the folder-health helper exist; the new control labels are keyed ×12 (the
    dropdown-translatable gate also enforces this).
    """
    html = _ui_source()
    assert 'id="feeddir-sort"' in html and 'id="feeddir-status-filter"' in html, (
        "the source manager needs a Sort control and a Status filter"
    )
    assert "function famStatus" in html and "_FEED_SORTS" in html, (
        "folder health + the sort comparators must exist"
    )
    for opt in ('value="ok"', 'value="error"', 'value="unchecked"'):
        assert opt in html, f"the status filter must offer {opt}"


def test_agenda_merges_imported_events_as_filterable_class():
    """Auto-imported feed events surface IN the main agenda (ledger Item E,
    2026-06-15), deduped server-side and flagged as a distinct, filterable
    "imported" provenance class — never silently blended with curated events, and
    shown even under 'subscribed only' (they were explicitly imported).
    """
    html = _ui_source()
    assert "function mapImportedToAgenda" in html, "imported events must map into the agenda shape"
    assert "/api/events/imported?from=" in html, "loadAgenda must pull imported events (forward-looking)"
    # The "drop the useless 'imported' category" rework (39353cf): imported events now
    # carry their feed's REAL kind as the category, and the distinct, filterable
    # provenance class is the `imported: true` FLAG (not a generic "imported" category).
    assert "imported: true" in html, (
        "imported events must carry the imported:true provenance flag (their filterable class)"
    )
    assert "e.imported || (e.sources" in html, "imported events must bypass the subscribed-only filter"
    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    assert "imported" in en, "the 'imported' category label must be keyed ×12"


def test_agenda_feeds_reversible_exclude():
    """Bulk 'remove' in the Agenda source manager = a REVERSIBLE, per-machine
    exclude/unsubscribe (ruled 2026-06-15), never a delete-from-catalog: excluded
    folders keep their honest verdicts in the directory (anti-hiding) but
    contribute no imported events, and can be re-included.
    """
    html = _ui_source()
    assert "oo.agenda.excluded" in html, "exclusions must be a per-machine, reversible store"
    for fn in ("function agExcluded", "function agToggleExclude", "function agExcludeBulk", "function agExcludeClear"):
        assert fn in html, f"reversible exclude requires {fn}()"
    # imported events from an excluded folder are filtered out of the agenda
    assert "filter(e => !excl.has(e.calendar))" in html, "excluded folders must contribute no events"
    # the directory still RENDERS excluded folders (anti-hiding) — just marked
    assert 'class="cs-row${isExcl ? " excluded" : ""}"' in html, "excluded folders stay visible, marked"
    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    for k in ("Exclude", "Include", "Exclude dysfunctional", "Clear exclusions"):
        assert k in en, f"exclude control label {k!r} must be keyed ×12"


def test_agenda_add_ics_calendar():
    """Add-a-calendar by local .ics UPLOAD (Item E, 2026-06-15): no network — the
    events join the agenda (deduped) as a removable, user-owned calendar; the raw
    file is parsed and discarded (only title+date+uid stored).
    """
    html = _ui_source()
    assert 'id="ics-file"' in html and 'type="file"' in html, "an .ics file input is required"
    for fn in ("function importIcsFile", "function renderUserCalendars", "function removeUserCalendar"):
        assert fn in html, f"add-calendar requires {fn}()"
    assert "/api/events/feeds/import-ics" in html and "/api/events/feeds/user/" in html, "endpoints wired"
    api = (_SRC / "api" / "events.py").read_text(encoding="utf-8")
    assert "/feeds/import-ics" in api and "/feeds/user/{key}" in api, "backend endpoints exist"
    feeds = (_SRC / "events" / "feeds.py").read_text(encoding="utf-8")
    for fn in ("def import_ics_text", "def list_user_feeds", "def remove_user_feed"):
        assert fn in feeds, f"backend missing {fn}"
    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    for k in ("Add a calendar", "Import calendar", "Your calendars", "Remove"):
        assert k in en, f"add-calendar label {k!r} must be keyed ×12"


def test_fixity_ui_present():
    """The local fixity audit (B-2) has a Settings UI: a button + loud results panel
    wired to /api/integrity/fixity, with the divergence banner keyed ×12."""
    html = _ui_source()
    assert 'id="fixity-btn"' in html and "function runFixity" in html, "fixity button + handler required"
    assert "/api/integrity/fixity" in html, "the UI must call the fixity endpoint"
    assert 'id="fixity-result"' in html, "a results panel is required"
    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    for k in ("Check corpus integrity", "All articles match their capture-time hash."):
        assert k in en, f"fixity string {k!r} must be keyed ×12"


def test_agenda_add_calendar_by_url():
    """Add a calendar by URL (Item E, the network half): the fetch goes through the
    guarded fetcher AND is gated by the ONE consent popup (ensureOnline) before any
    network — never a silent fetch."""
    html = _ui_source()
    assert "function importIcsUrl" in html and 'id="ics-url"' in html, "URL add control required"
    assert "/api/events/feeds/import-url" in html, "URL import endpoint wired"
    # the consent gate MUST precede the network call (no silent fetch). Anchor on
    # the unique consent reason string for this handler.
    i_fn = html.index("function importIcsUrl")
    i_consent = html.index("Fetch a calendar from a URL you provided")
    i_post = html.index("/api/events/feeds/import-url")
    assert i_fn < i_consent < i_post, "ensureOnline must gate before the import-url fetch"
    api = (_SRC / "api" / "events.py").read_text(encoding="utf-8")
    assert "/feeds/import-url" in api and "make_fetcher()" in api, "backend fetches via the guarded fetcher"
    feeds = (_SRC / "events" / "feeds.py").read_text(encoding="utf-8")
    assert "def import_ics_url" in feeds and "webcal://" in feeds, "URL import + webcal normalization"


def test_analysis_window_absorbs_exports():
    """Item I (toward one search entry): the analysis window exports its OWN analysed
    set — CSV/JSON/methods appendix/signed evidence — built from its Advanced inputs,
    not the Search tab's. The Search-tab call sites stay back-compatible (optional
    args), so nothing is lost while capability migrates off the Search tab.
    """
    html = _ui_source()
    assert "function anParams" in html and "function anQuery" in html, "analysis-scoped params required"
    assert "exportResults('csv', anParams())" in html and "exportResults('json', anParams())" in html
    assert "exportMethods(anQuery())" in html and "exportEvidence(anQuery())" in html
    # functions made param-aware (back-compatible defaults)
    assert "function exportResults(fmt, p)" in html
    assert "function exportMethods(qArg)" in html and "function exportEvidence(qArg)" in html
    # the Search-tab call sites are unchanged (no-arg) — nothing lost
    assert "exportResults('csv')" in html and "exportMethods()" in html and "exportEvidence()" in html
    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    assert "Export this analysis:" in en


def test_analysis_window_absorbs_synthesize():
    """Item I: Synthesize is reachable from the analysis window too, so the last
    Search-tab capability is mirrored. REWORKED 2026-06-21: it now opens the synthesis
    WINDOW over a user-chosen member set (the window's selection/metadata/export
    behaviour is pinned by test_synthesis_opens_a_window_with_selection_metadata_and_export);
    the analysis window wires its OWN corpus (anParams), the Search tab the no-arg call."""
    html = _ui_source()
    assert "function synthesizeResults(btn, arg)" in html, "synthesize takes (btn, query|params)"
    assert "synthesizeResults(this, anParams())" in html, "analysis window wires its own corpus"
    assert "synthesizeResults(this)" in html, "the Search-tab call stays (no-arg) — nothing lost"


def test_omnibar_enter_opens_analysis_window():
    """Item I + field remark 9 (2026-06-24): the omnibar's default Enter action opens the
    corpus/analysis window seeded with the query — now in a NEW BROWSER TAB
    (openAnalysisInNewTab → window.open ?analyze=, hydrated by _hydrateCardCorpus →
    openAnalysisFor in the fresh tab). The in-SPA openAnalysisFor stays the opener for
    clicking a specific result + every card/commodity entry; the Boolean Search-tab item
    stays available (nothing lost)."""
    html = _ui_source()
    assert "function openAnalysisFor" in html, "seeded analysis-window opener required"
    assert "function openAnalysisInNewTab" in html, "the new-browser-tab opener (remark 9) required"
    assert "run: () => openAnalysisInNewTab(raw)" in html, "the default omnibar item opens a new tab"
    # The new-tab opener uses the proven ?analyze= deep-link + boot hydration.
    assert '"analyze"' in html and "_hydrateCardCorpus" in html, "?analyze= deep-link + hydration required"
    # the Analysis item is unshifted LAST so it sits at index 0 (the Enter default),
    # while the Boolean search item remains reachable.
    i_search_item = html.index('showTab("search"); setTimeout(() => { $("q").value = raw; doSearch()')
    i_analysis_item = html.index("run: () => openAnalysisInNewTab(raw)")
    assert i_search_item < i_analysis_item, "Analysis must be unshifted after Search (=> index 0, default Enter)"


def test_library_world_map_and_unlocated_donut():
    """Field remark 10: the Library 'World coverage' renders a per-country ARTICLE-count
    world map (the shared ooMap) + a donut of the 'no country' articles by language (full
    names via ooLangName). The catalogue-reach table is kept (Desk lesson)."""
    html = _ui_source()
    assert 'id="coverage-map"' in html and 'id="coverage-unlocated"' in html
    assert "function ooDonut" in html, "the reusable donut renderer is required"
    assert "async function renderCoverageMap" in html
    assert "renderCoverageMap();" in html, "loadCoverage must trigger the map/donut"
    # the map plots ARTICLE counts via ooMap; the donut reads the per-language unlocated bucket.
    assert "r.articles" in html and "ooMap(mapHost" in html
    assert "by_language" in html and "ooLangName(" in html
    # the catalogue-reach table is preserved (nothing lost).
    assert 'id="coverage-table"' in html


def test_library_central_dashboard():
    """Field remark 16: the Library tab is the central dashboard of everything DOWNLOADED
    (wiki dumps, maps, market series, laws, stats, models) + EXTRAPOLATED (AI summaries/
    translations/synthesis + keywords). Fed by ONE /api/library/overview roll-up; honest
    counts + sizes, no score."""
    html = _ui_source()
    assert 'id="library-overview"' in html
    assert "async function renderLibraryOverview" in html
    assert "/api/library/overview" in html
    assert "renderLibraryOverview()" in html, "must be wired into the tab onShow + poller"
    # the two layers are labelled + the AI-derived layer is disclosed unreliable.
    assert "Downloaded — the raw" in html and "Extrapolated — AI-derived" in html
    # representative downloaded + extrapolated tiles.
    assert "AI summaries" in html and "Wikipedia dumps" in html and "Offline map regions" in html


def test_storage_footprint_shown_wherever_db_size_shows():
    """B14 (A12b display half): the COMPLETE on-disk footprint — db+wal+shm+wiki_dumps+
    osm_regions+staging+other+Ollama model store — is shown on the Library dashboard AND the
    task-manager System tab, with the encrypted-private-corpus vs re-downloadable-public split
    VISIBLE (not toggled). Bytes only, no score; a recursive disk walk fetched LAZILY (on tab
    open) + cached, NEVER on the live poll."""
    html = _ui_source()
    # the A12b backend endpoint is consumed
    assert "/api/diagnostics/storage-footprint" in html
    assert "renderStorageFootprint" in html and "_fetchStorageFootprint" in html
    # hosted on BOTH surfaces + wired lazily (tab-open, not the poller)
    assert 'id="library-storage"' in html and 'id="vitals-storage"' in html
    assert 'renderStorageFootprint("library-storage")' in html
    assert 'renderStorageFootprint("vitals-storage")' in html
    # the honest private-vs-public split is rendered (not hidden behind a toggle) — and the
    # private label does NOT over-claim encryption (no fabricated security: -shm + staging in
    # the private sum are not necessarily encrypted, so it is "Private (local)").
    assert "Private (local; corpus encrypted at rest)" in html
    assert "Encrypted private corpus" not in html
    assert "_SF_PUBLIC" in html  # wiki/osm/models classed re-downloadable
    # NO score, and it must NOT ride the live poll (fetch is cached + forced only on Re-measure)
    assert "Re-measure" in html
    # cache guard: the fetch dedupes an in-flight walk so two hosts don't double-walk
    assert "_sfPending" in html and "_sfCache" in html


def test_settings_chrome_cleanups():
    """Field remarks 11/12/14/15: the Settings intro box is removed, Appearance + GUIs are
    fused into one 'Graphics' subtab (nothing lost), the sticky chrome is opaque (matching
    the sidebar's var(--bg2)), and the sidebar's empty space toggles collapse/expand."""
    html = _ui_source()
    # remark 12: the intro paragraph is gone; the subtab nav stays.
    assert "Everything that shapes how the app looks and behaves on this" not in html
    assert 'id="set-subtabs"' in html
    # remark 11: one Graphics subtab holds BOTH the Appearance content + the GUIs gallery.
    assert 'data-tab="graphics"' in html and 'id="set-graphics"' in html
    assert 'data-tab="guis"' not in html and 'id="set-guis"' not in html
    assert 'id="dr-themes"' in html and 'id="guis-gallery"' in html  # both contents preserved
    # remark 14: the sticky chrome is opaque (var(--bg2), the sidebar bg) — no transparent wash.
    assert "color-mix(in srgb, var(--bg) 82%, transparent)" not in html, "topbar must be opaque"
    assert "background:var(--bg2)" in html
    # remark 14 REOPENED (field report 2026-06-25): the sticky WRAPPER itself must carry the
    # bg, not just its children — a children-only bg let content show through when the facet
    # strip is hidden. Guard that the .chrome rule includes the opaque background.
    assert ".chrome { position:sticky; top:0; z-index:50; background:var(--bg2); }" in html, (
        "the sticky .chrome wrapper must carry the opaque bg, not only .topbar/.subtab-strip"
    )
    # remark 15: clicking the sidebar's empty space toggles collapse/expand.
    assert "_wireSidebarEmptyClickToggle" in html and "toggleSidebar()" in html


def test_ai_output_in_ui_language_and_prompt_relocalization():
    """Field remark 13: single-article summarize sends the UI language CODE (ui_lang) so the
    summary comes out in the UI language (like bulk/synthesis); single-article translate
    defaults to the UI language, not hardcoded English; the AI prompt editor re-renders on a
    language switch (its English prompt BODIES stay English by design — only the chrome
    relocalizes, and the OUTPUT language is the reliable lever)."""
    html = _ui_source()
    assert "ui_lang: (window.OOI18N && OOI18N.current)" in html, "summarize must send the UI language code"
    assert 'target_language: "English"' not in html, "single-article translate must not hardcode English"
    assert "target_language: _uiLangName()" in html, "translate defaults to the UI language"
    assert "oo:langchange" in html and "loadLlmPrompts()" in html, "prompt editor re-renders on langchange"


def test_cjk_keyword_disclosure():
    """Audit-07 B1: keyword extraction does not segment CJK, so CJK keyword
    aggregates are unreliable — the analysis window discloses this VISIBLY (with a
    hover long-form) exactly when CJK terms are present, never hidden."""
    html = _ui_source()
    assert "CJK not segmented" in html, "the CJK caveat marker must be present"
    assert "/[぀-ヿ㐀-䶿一-鿿가-힯]/.test(tm.term)" in html, "the caveat must trigger on detected CJK terms"
    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    assert "CJK not segmented — unreliable" in en
    # the long-form (hover bubble) is keyed too (informed-consent-by-layering)
    assert any(k.startswith("Keyword extraction splits on spaces") for k in en), "long-form must be keyed"


def test_search_retired_from_sidebar_but_reachable():
    """Ruled "one search entry" (Item I): now that the analysis window absorbs every
    Search-tab capability + the omnibar Enter entry, the Search SIDEBAR button is
    retired. Nothing is lost — #tab-search, doSearch and the entry paths remain, so
    Boolean search is still reachable (the omnibar / palette), just not a sidebar tab.
    """
    html = _ui_source()
    assert '<button class="nav-item" data-tab="search">' not in html, "no Search button in the sidebar rail"
    assert 'id="tab-search"' in html, "the search page is KEPT (nothing lost)"
    assert "function doSearch" in html, "Boolean search still exists"
    assert 'showTab("search")' in html, "search stays reachable (omnibar/palette entry points)"
    # Analysis is no longer a sidebar tab (retired 2026-06-20 — reached via search /
    # openAnalysisFor); the sidebar still lists its other tabs (invariant #2 not regressed).
    assert '<button class="nav-item" data-tab="analyze">' not in html, "Analysis sidebar tab retired"
    assert '<button class="nav-item" data-tab="insights">' in html and '<button class="nav-item" data-tab="home">' in html


def test_analysis_mindmap_subtab():
    """The universal analysis window gained a Mindmap sub-tab (Item I): a SELF-CONTAINED
    radial keyword-association graph seeded on the corpus's top keyword. It must NOT
    regress the load-bearing Insights mind-map (renderGraph + #ins-mindmap own the _mm*
    force/zoom canvas) — the analysis renderer is a distinct static SVG with its own host.
    """
    html = _ui_source()
    # the new self-contained renderer + its sub-tab button + panel host
    assert "function renderAnMindmap" in html, "the analysis-window radial renderer must exist"
    assert 'id="an-mindmap"' in html, "the analysis Mindmap panel host must exist"
    assert 'data-tab="mindmap"' in html, "the Mindmap sub-tab button must exist in #an-subtabs"
    # it must be wired into loadAnalysis (so the sub-tab actually renders)
    assert "renderAnMindmap(" in html, "renderAnMindmap must be called (wired into loadAnalysis)"
    # NO REGRESSION: the Insights mind-map is untouched and still present
    assert "function renderGraph" in html, "Insights renderGraph must remain (no regression)"
    assert 'id="ins-mindmap"' in html, "Insights #ins-mindmap host must remain (no regression)"
    # the analysis renderer must stay self-contained: its body must not touch the
    # Insights #ins-mindmap host nor share the _mm* force-canvas state.
    an_start = html.index("function renderAnMindmap")
    an_body = html[an_start:an_start + 2200]
    assert "ins-mindmap" not in an_body, "renderAnMindmap must not touch the Insights host"
    assert "_mm" not in an_body, "renderAnMindmap must not share the Insights _mm* state"


def test_text_only_modality_disclosed():
    """Audit-07 B1: the app analyses TEXT only — images/audio/video aren't analysed.
    Stated visibly in the analysis window (keyed ×12), not left implicit."""
    html = _ui_source()
    assert "Text only — images, audio and video aren't analysed." in html
    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    assert "Text only — images, audio and video aren't analysed." in en


def test_analysis_mindmap_controls():
    """Mind-map rules on the analysis Mindmap: a Cloud SECOND view, a text-size
    control and ⛶ enlarge — re-rendering deterministically from the same graph."""
    html = _ui_source()
    assert "function anMMset" in html and "const _anMM" in html, "stateful in-map controls required"
    assert 'anMMset({cloud:true})' in html and 'anMMset({cloud:false})' in html, "Map/Cloud second view"
    assert "anMMset({big:!_anMM.big})" in html, "⛶ enlarge"
    assert "anMMset({scale:+this.value})" in html, "text-size control"
    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    for k in ("Map", "Cloud", "Enlarge the mindmap"):
        assert k in en


def test_agenda_year_view():
    """Agenda Year view (Item C remaining): a 12-month overview of clickable month
    cards (per-month event counts), with year navigation, drilling into the Month grid."""
    html = _ui_source()
    assert 'data-tab="year"' in html and 'id="agenda-year"' in html, "Year tab + pane required"
    assert "function renderAgendaYear" in html and "function agYearShift" in html, "year renderer + nav"
    assert "function agOpenMonth" in html, "clicking a month drills into Month view"
    assert 'v === "year"' in html, "the shared nav bar must dispatch year navigation"


def test_agenda_views():
    """Agenda remaining views (ledger 'AGENDA CONTENT' — week/trimester/semester/
    year/decade): Week + Year already shipped; this adds TRIMESTER (3 months),
    SEMESTER (6 months) and DECADE (10 years), each reusing the Year view's data
    path + event placement (agEventsInMonth / agFiltered) and the SAME ooSubtabs
    view switch — no parallel switcher, no new backend endpoint.

    Guards the wiring so the new layouts can't silently regress: the switch offers
    all four data-tab views, each has its render container + renderer, navigation
    dispatches per view (trimester ±3 months, semester ±6 months, decade ±10 years),
    decade cells drill into that Year view, and the period uses an honest empty
    state — never a hidden/downsampled event set.
    """
    html = _ui_source()

    # all four views registered in the ONE ooSubtabs switch (data-tab buttons)
    for view in ("week", "trimester", "semester", "year", "decade"):
        assert f'data-tab="{view}"' in html, f"the view switch must offer the {view} view"
    assert 'ooSubtabs($("agenda-views")' in html, "the view switch must reuse the universal ooSubtabs component"

    # render containers for the new layouts
    assert 'id="agenda-months"' in html, "trimester/semester need their render container"
    assert 'id="agenda-decade"' in html, "the decade view needs its render container"

    # renderers + the SHARED event path (Year view's placement helpers reused)
    for fn in ("function renderAgendaMonths", "function renderAgendaDecade",
               "function agEventsInMonth", "function agMonthCard"):
        assert fn in html, f"the new views require {fn}()"
    # they render from the same filtered rows the other views use
    assert "renderAgendaMonths(rows, 3)" in html, "trimester = 3 consecutive months over the shared rows"
    assert "renderAgendaMonths(rows, 6)" in html, "semester = 6 consecutive months over the shared rows"
    assert "renderAgendaDecade(rows)" in html, "the decade view renders over the shared filtered rows"

    # navigation dispatches per view through the ONE shared nav bar (agNavShift)
    assert 'view === "trimester"' in html and 'view === "semester"' in html and 'view === "decade"' in html, (
        "renderAgenda must toggle the new panes by the active view"
    )
    assert "agMonthShift(d * 3)" in html, "trimester navigation steps by 3 months"
    assert "agMonthShift(d * 6)" in html, "semester navigation steps by 6 months"
    assert "agYearShift(d * 10)" in html, "decade navigation steps by 10 years"

    # decade cells drill into that Year view (reuse the Year layout, not a new one)
    assert "function agOpenYear" in html and 'agendaSetView("year")' in html, (
        "clicking a decade year cell must switch to that Year view"
    )

    # honest empty state for a period with no events (no silent downsampling/hiding)
    assert "No events in this period." in html, "periods with no events show an honest empty state"


def test_commodities_category_subtabs():
    """Commodities board groups cards into CATEGORY sub-tabs (maintainer-ruled
    COMMODITIES TAB REWORK §1) via the ONE universal subtab component (invariant
    #18) — never a bespoke impl. The category is DATA-DRIVEN (s.category from
    /api/markets/series), with an 'All' default lens (like Home families) and an
    'Other' fallback for unmapped categories; indices are excluded (S&P 500 is an
    INDEX, not a commodity), so the board never misfiles one as a commodity."""
    html = _ui_source()
    # the category nav lives above the card grid
    assert 'id="commodities-cats"' in html, "the category sub-tab nav must exist"
    assert html.index('id="commodities-cats"') < html.index('id="mkt-dashboard"'), (
        "the category nav must precede the card grid"
    )
    # driven by the ONE reusable ooSubtabs component, NOT a bespoke tab impl
    assert "ooSubtabs($(\"commodities-cats\")" in html or \
           "ooSubtabs(catNav, selectCommodityCat" in html, (
        "the category tabs must reuse ooSubtabs (universal subtab grammar)"
    )
    # the filter callback + the categoriser map exist
    assert "function selectCommodityCat" in html, "category filter callback required"
    assert "const MKT_CATS" in html, "the deterministic category map must exist"
    # "All" is the default lens (the ooSubtabs initial) and shows everything
    assert '{initial: "__all"}' in html, "'All' (__all) must be the default lens"
    assert 'key === "__all"' in html, "the '__all' lens must show every category"
    # data-driven: built from the categories actually present (no empty tab)
    assert "byCat" in html and "MKT_CATS.filter" in html, (
        "the present-category list must be data-driven (no empty tab)"
    )
    # indices are NOT commodities — excluded from the board
    assert 's.category !== "index"' in html, (
        "indices must be excluded from the commodities board"
    )
    # the labels are keyed for i18n (auto-translated ×12 via the t() lookup)
    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    assert "All" in en, "the 'All' lens label must be keyed for translation"


def test_indices_category_subtabs():
    """The Indices board groups cards into CONTINENT sub-tabs + a secondary TAG
    facet (maintainer 2026-06-17 markets revamp Slice 2: "show them in categories
    (continents, tags)") via the ONE universal subtab component (invariant #18),
    mirroring the commodities board so the twin boards stay near-identical. The
    continent is DATA-DRIVEN (card.continent from /api/markets/board), with an
    'All' default lens and an 'Other' fallback for un-located entries."""
    html = _ui_source()
    # the continent nav + the tag-chip row live above the card grid
    assert 'id="indices-cats"' in html, "the continent sub-tab nav must exist"
    assert 'id="indices-tags"' in html, "the tag-facet chip row must exist"
    assert html.index('id="indices-cats"') < html.index('id="idx-board"'), (
        "the continent nav must precede the index card grid"
    )
    # driven by the ONE reusable ooSubtabs component, NOT a bespoke tab impl
    assert 'ooSubtabs(catNav, selectIndexCat' in html, (
        "the continent tabs must reuse ooSubtabs (universal subtab grammar)"
    )
    assert "function selectIndexCat" in html, "continent filter callback required"
    assert "function renderIndicesBoard" in html, "the grouped board renderer must exist"
    # continent grouping is data-driven from the card facet (no empty tab)
    assert "_idxContinent" in html and "const IDX_CONTINENTS" in html, (
        "continent grouping must be data-driven from card.continent"
    )
    # the secondary TAG facet: toggle chips that AND-filter the visible cards
    assert "function toggleIndexTag" in html and "function applyIndexFilters" in html, (
        "the tag-chip AND-filter must exist"
    )
    assert "_idxTags" in html, "active-tag state must drive the tag filter"
    # the board cards carry their facet values so filtering needs no re-fetch
    assert "data-continent=" in html and "data-tags=" in html, (
        "each index card must carry its continent + tags for client-side faceting"
    )
    # '/board' must serve the facet fields the UI groups on (read the source
    # file directly — importing the module runs make_fetcher() at load time)
    board_src = (_SRC / "api" / "markets.py").read_text(encoding="utf-8")
    assert '"continent": f.continent' in board_src and '"tags": list(f.tags)' in board_src, (
        "the /board endpoint must expose continent + tags per card"
    )


def test_indices_multiseries_compare():
    """The Indices board lets the user AGGREGATE several curves onto one graph
    with Absolute/Indexed/Log scale controls (maintainer 2026-06-17 markets revamp
    Slice 3: "aggregate several curves onto the same graph … change the graph
    scales"). The overlay reuses the ONE ooChart toolkit (invariant #16) — no
    fabricated data (each curve is the symbol's real stored series)."""
    html = _ui_source()
    # the compare bar lives above the board; the selection is multi-symbol state
    assert 'id="idx-compare-bar"' in html, "the compare bar must exist"
    assert "const _idxCompare" in html, "the multi-select compare state must exist"
    assert "function toggleIdxCompare" in html and "function openIdxComparison" in html, (
        "the compare toggle + overlay opener must exist"
    )
    assert "function renderIdxCompareBar" in html, "the compare bar renderer must exist"
    # the overlay reuses chartEnlarge with the scale-control row (NOT a new modal)
    assert "{scales: true}" in html, "the comparison overlay must request the scale controls"
    assert "function chartEnlarge(title, seriesList, caveat, opts)" in html, (
        "chartEnlarge must accept the optional scale opts (back-compatible 4th arg)"
    )
    # Absolute / Indexed / Log are the three honest scale modes
    for mode in ('"absolute"', '"indexed"', '"log"'):
        assert mode in html, f"the scale toggle must offer {mode}"
    # ooChart gained an ADDITIVE log-Y mode: identity when off, so every existing
    # chart is byte-for-byte unchanged (the same contract as opts.indexed)
    assert "opts.logY" in html, "ooChart must support the additive opts.logY scale"
    assert "Math.log10(Math.max(v, LOGEPS))" in html, (
        "log-Y must map log10(value) (clamped) — never crash on a zero/negative"
    )
    assert "opts.logY ? Math.pow(10, d) : d" in html, (
        "log-Y must back-transform gridline labels to the REAL value (identity when off)"
    )


def test_markets_coherent_time_axis_and_legends():
    """The board graph timescales are COHERENT across sources + the legends are
    clear (maintainer 2026-06-17 markets revamp Slice 4: "graph timescales should
    be coherent between all sources … indices timescale legends should be clear").
    dashChartSvg gains an ADDITIVE shared [t0,t1] time axis (date-based placement),
    so every commodity card aligns on ONE calendar axis; without it the index-based
    mapping is byte-identical (Home sparklines / trends unchanged). The Indices
    cards gain a clear start→as-of date legend."""
    html = _ui_source()
    # dashChartSvg accepts the optional shared-window opts (back-compatible 3rd arg)
    assert "function dashChartSvg(points, unit, opts)" in html, (
        "dashChartSvg must accept the optional shared-axis opts"
    )
    # date-based placement only engages with a valid [t0,t1] window; else the
    # index-based X(i) is the fallback (the byte-identical additive contract)
    assert "const shared = isFinite(sa) && isFinite(sb) && sb > sa" in html, (
        "the shared time axis must require a valid [t0,t1] window"
    )
    assert "if (!shared) return X(i)" in html, (
        "without a shared window dashChartSvg must fall back to index-based X (no regression)"
    )
    # the commodities board feeds every card the SAME window so timescales cohere
    assert "{t0: axT0, t1: axT1}" in html, (
        "renderDashboard must pass one shared [t0,t1] window to every card"
    )
    assert "const axT0 = from || _span.min, axT1 = to || _span.max" in html, (
        "the shared window must come from the active scope (or the full data span)"
    )
    # the Indices cards carry a clear timescale legend (start → as-of)
    assert 'class="idx-range' in html, "each index spark must show a clear date-range legend"


def test_markets_family_stacked_graphs():
    """The commodities board is FAMILIES-FIRST (maintainer field test 2026-06-19
    P2-10, building on the 2026-06-17 Slice 5 "stack all curves into family graphs
    … as much data but with fewer graphs"): one multi-series ooChart per category
    is the DEFAULT view, reusing the ONE ooChart toolkit (invariant #16). The
    Cards/Families toggle is DROPPED — the per-commodity tools migrate into each
    family graph as member chips, so nothing is lost (the Desk lesson)."""
    html = _ui_source()
    # a reusable family-graph renderer (one multi-series ooChart per group)
    assert "function renderFamilyGraphs(host, groups, opts)" in html, (
        "the reusable family-graph renderer must exist"
    )
    # default INDEXED so different-magnitude members co-move honestly + a visible caveat
    assert "indexed: opts.indexed !== false" in html, (
        "family graphs must default to the indexed (cross-magnitude) scale"
    )
    assert 'class="card-caveat"' in html, "the families view must carry a VISIBLE caveat"
    # families-first: the view DEFAULTS to families; the toggle UI is dropped
    assert 'let _mktView = "families"' in html, "the board must DEFAULT to the families view (P2-10)"
    assert 'tog.innerHTML = ""; tog.style.display = "none"' in html, (
        "the Cards/Families toggle must be DROPPED (the slot is emptied/hidden, P2-10)"
    )
    # the per-commodity tools migrate into the family view as member chips
    assert 'class="fam-mbtn"' in html, "family graphs must carry per-member action buttons (Analyse + price detail)"
    assert "memberActions: [" in html, "the commodities families view must pass member actions"
    assert "class=\"fam-enlarge\"" in html, "each family must offer a fullscreen Enlarge (the shared overlay)"
    # the families branch builds one family per category + the same subtabs filter both
    assert "function commodityFamilies" in html, "the per-category family builder must exist"
    assert 'if (_mktView === "families")' in html, (
        "renderDashboard must branch to the families view"
    )
    assert 'class="fam-block mkt-cat"' in html, (
        "family blocks must carry .mkt-cat/data-cat so the category subtabs filter them too"
    )


def test_markets_one_fullscreen_graph_overlay():
    """The single-symbol price detail opens in the ONE shared fullscreen overlay
    (#chart-enlarge), not the cramped bottom strip, and PRESERVES "Correlate with
    news" (maintainer field test 2026-06-19 P2-10). chartSymbol routes into
    chartEnlarge; chartEnlarge gained an optional extra/onReady hook to host the
    correlation control; the correlation logic renders into a caller-supplied
    element so both the overlay and any legacy caller work."""
    html = _ui_source()
    assert "function _chartEnlargeExtra(body, opts)" in html, (
        "chartEnlarge must support optional extra content + an onReady hook"
    )
    assert "function correlateSymbolInto(symbol, el)" in html, (
        "the correlation must render into a caller-supplied element (overlay-friendly)"
    )
    # chartSymbol opens the fullscreen overlay and wires Correlate into it
    assert "chartEnlarge(`${symbol}" in html, "chartSymbol must route into the fullscreen overlay"
    assert 'id="ce-correlate"' in html, "the overlay must carry the 'Correlate with news' control"
    assert "correlateSymbolInto(symbol, body.querySelector" in html, (
        "the overlay Correlate button must wire into the per-symbol correlation"
    )


def test_markets_twin_board_parity():
    """The Indices and Commodities boards are near-identical twin boards
    (maintainer 2026-06-17 markets revamp Slice 6: "very similar … nearly
    identical, only the data they show is different"). Slice 6 brings the
    Families view + the time-range control to the Indices board, REUSING the
    same helpers (renderFamilyGraphs / ooTimeScope / windowPricesRange) so the
    two boards share their grammar. Cards view stays unchanged (no regression)."""
    html = _ui_source()
    # BOTH boards are families-first now (P2-10 twin parity): the toggle is dropped
    # and both default to the families view.
    assert 'let _idxView = "families"' in html, "the indices board must DEFAULT to the families view (P2-10)"
    assert "function setIdxView" in html, "the indices view callback must still exist (cards path reachable)"
    # the indices families view also carries member chips (twin parity)
    assert "renderFamilyGraphs(el, idxFamilies(), {" in html, (
        "indices families must pass member actions through the shared renderer"
    )
    # the indices Families view reuses the SAME family-graph renderer
    assert "function idxFamilies" in html and "function renderIdxFamilies" in html, (
        "the indices families builder + renderer must exist"
    )
    assert "renderFamilyGraphs(el, idxFamilies()" in html, (
        "the indices families view must reuse the ONE renderFamilyGraphs helper"
    )
    # the indices board gains a time-range control reusing ooTimeScope (twin of #mkt-timescope)
    assert 'id="idx-timescope"' in html, "the indices time-range control must exist"
    assert "function buildIdxTimeScope" in html and "_idxTimeScope = ooTimeScope" in html, (
        "the indices time-scope must reuse the ONE ooTimeScope component"
    )
    # families window the REAL full series (lazy-loaded) via the shared windowPricesRange
    assert "function loadIdxFullSeries" in html, "the indices full-series lazy loader must exist"
    assert "windowPricesRange(MKT_PRICES[c.symbol]" in html, (
        "indices families must window the real stored series (shared helper)"
    )


def test_markets_specific_subtab_shows_items_individually():
    """A SPECIFIC category/continent subtab (not the general "All" lens) shows each
    commodity/index in its OWN graph, one per item (maintainer-ruled: "commodities
    and indices should be shown individually in the not-general subtabs"). "All"
    keeps the combined per-category/continent family overview. The group builders
    explode to one series per group when a specific tab is active, and selecting a
    commodity category re-renders (the group set changes, not just a CSS hide)."""
    html = _ui_source()
    # commodities: commodityFamilies explodes when a specific category is selected
    assert 'if (_mktCat !== "__all") {' in html, (
        "commodities must show each item individually in a specific category subtab"
    )
    # indices: idxFamilies explodes when a specific continent is selected
    assert 'if (_idxCat !== "__all") {' in html, (
        "indices must show each item individually in a specific continent subtab"
    )
    # selecting a commodity category in families view re-renders (group set changes)
    assert 'if (_mktView === "families") { if (changed) renderDashboard(); return; }' in html, (
        "selecting a commodity category must re-render the exploded groups, not CSS-hide"
    )


def test_recursive_augmentation_logs_are_wired():
    """The 5 recursive-augmentation diagnostic logs (maintainer 2026-07-02) are wired:
    frontend error capture in the UI + the backend endpoints in the diagnostics router
    + all five ride the debug bundle and the all-diagnostics archive."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # log #1: the frontend captures window.onerror / unhandledrejection / failed fetch
    assert 'addEventListener("error"' in app and 'addEventListener("unhandledrejection"' in app, (
        "the UI must capture JS errors + unhandled rejections"
    )
    assert "/api/diagnostics/frontend-error" in app, "captured errors POST to the local log"
    # it must use the RAW fetch for its own report so it cannot recurse on its own failure
    assert "_ooRawFetch" in app, "the reporter must use the pre-wrap fetch to avoid recursion"

    diag = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    for route in (
        '"/frontend-error"',
        '"/request-latency"',
        '"/slow-queries"',
        '"/schema-drift"',
        '"/integrity"',
    ):
        assert route in diag, f"the diagnostics router must expose {route}"
    # the new logs ride the one-click bundles
    for member in ("request-latency.json", "slow-queries.json", "schema-drift.json",
                   "corpus-integrity.json", "frontend-errors.json"):
        assert member in diag, f"{member} must be in the all-diagnostics archive"
    assert "request_latency" in diag and "corpus_integrity" in diag, (
        "the debug bundle must carry the latency + integrity logs"
    )

    main = (_SRC / "api" / "main.py").read_text(encoding="utf-8")
    assert "start_watchdog" in main, "the event-loop-block watchdog must start at lifespan"
    assert "install as _install_slowquery" in main, "the slow-query listener must install at boot"


def test_commodity_card_opens_analysis():
    """Each commodity card's TITLE opens the universal analysis window seeded
    with that commodity's keyword query (maintainer-ruled COMMODITIES TAB REWORK
    item 4 / the corpora system's commodity-click entry — first slice). The
    title is a clickable affordance calling the EXISTING openAnalysisFor(query);
    the query comes from the curated COMMODITY_QUERY seed map (else the series
    display name). stopPropagation keeps the card's own price-detail click
    intact. A VISIBLE caveat states the maintainer's binding rule: the corpus
    surfaces CO-OCCURRENCE, never causation."""
    html = _ui_source()
    # the universal analysis entry point must exist (we wire to it, not reinvent)
    assert "function openAnalysisFor" in html, "openAnalysisFor must exist to wire to"
    # the curated symbol -> query seed map
    assert "const COMMODITY_QUERY" in html, "the curated COMMODITY_QUERY map must exist"
    # the card title is a clickable affordance that opens the analysis window,
    # falling back to the series name for unmapped commodities
    assert "COMMODITY_QUERY[s.symbol] || s.name" in html, (
        "the title query must come from COMMODITY_QUERY, defaulting to the name"
    )
    assert "openAnalysisFor(" in html, "the title must open the analysis window"
    # must not hijack the card's own (chartSymbol) click
    assert "event.stopPropagation(); openAnalysisFor(" in html, (
        "the title click must stopPropagation so the card's chartSymbol stays"
    )
    # the "co-occurrence … never causation" GRAPH caveat was REMOVED from charts
    # everywhere (maintainer ruling 2026-06-17); the combined-trend caveat no longer
    # carries it (the non-causation principle still governs the design, just not as
    # repeated on-graph text).
    assert 't("co-occurrence in your corpus, never causation")' not in html, (
        "the graph causation caveat was removed everywhere (maintainer 2026-06-17)"
    )


def test_ootimescope_range_control():
    """The reusable time-range control (maintainer UX: "dates + a visual range
    bar", NOT 5 buttons) replaced the 5-choice <select> on the Markets board.

    Asserts the component exists, the select is gone, and the control offers
    all three coordinated surfaces (date inputs + a draggable bar + presets)
    and re-renders the board on change.
    """
    html = _ui_source()
    # the reusable component
    assert "function ooTimeScope" in html, "the reusable ooTimeScope control must exist"
    # the old 5-choice time-scale <select> is GONE, the control box replaced it
    assert 'id="mkt-scale"' not in html, (
        "the 5-choice #mkt-scale select must be removed (replaced by ooTimeScope)"
    )
    assert 'id="mkt-timescope"' in html, "the markets board must mount #mkt-timescope"
    # (a) From / To date inputs
    assert '<input type="date" class="ts-from">' in html and '<input type="date" class="ts-to">' in html, (
        "the control must render From / To date inputs"
    )
    # (b) a visual draggable range bar (track + two handles)
    assert "ts-bar" in html and "ts-handle" in html, (
        "the control must render a draggable range bar (ts-bar + ts-handle)"
    )
    assert 'addEventListener("pointerdown"' in html or 'pointerdown' in html, (
        "the handles must be pointer-draggable (mouse + touch)"
    )
    # (c) quick presets as one-click shortcuts
    assert "ts-presets" in html and "data-preset" in html, "quick presets must exist"
    assert '_TS_PRESETS' in html, "the preset span table must exist"
    # the markets wiring: onChange re-renders the board, windowed by [from,to]
    assert "_mktScope = {from, to}; renderDashboard()" in html, (
        "the control's onChange must update the window and re-render the board"
    )
    assert "windowPricesRange(all, from, to)" in html, (
        "the board must window by absolute [from,to] dates (not a trailing days count)"
    )


def test_ootimescope_reused():
    """The reusable ooTimeScope control (maintainer: "reuse it so date filtering
    is consistent app-wide") is wired onto the keyword-trend surfaces beyond
    Markets: the Insights Explore trend and the corpus-window Trend sub-tab.

    Both fetch /api/insights/trend (the FULL bucketed series, no date params), so
    the window is applied CLIENT-SIDE by FILTERING the already-fetched points and
    re-rendering through the EXISTING ooChart renderer (invariant #16: the
    full-resolution series within the window is kept, never thinned).
    """
    html = _ui_source()
    # the shared windowing helpers + the one factory that mounts an ooTimeScope
    # over a trend series and re-renders on change.
    assert "function _buildTrendScope" in html, "the shared trend-scope factory must exist"
    assert "function _windowTrendPoints" in html, "the client-side trend filter must exist"
    # the factory mounts the SAME component (not a fork) and recomputes on change.
    assert "ooTimeScope(box, {" in html, "_buildTrendScope must instantiate the SAME ooTimeScope"
    assert "onChange: ({from, to}) => redraw(_windowTrendPoints(points, from, to))" in html, (
        "onChange must re-render from the date-filtered points (no downsampling)"
    )
    # default window = last 1 year anchored to the data MAX (never 'now').
    assert "function _trendDefaultWindow" in html, "a 1-year-from-max default window helper must exist"

    # (1) Insights Explore trend: a new container + the factory wiring.
    assert 'id="ins-trend-scope"' in html, "Insights Explore must mount #ins-trend-scope"
    assert '_buildTrendScope($("ins-trend-scope")' in html, (
        "Insights Explore must build the time-scope over its trend series"
    )
    # (2) Corpus window Trend sub-tab: a new container + the factory wiring.
    assert 'id="corpus-timescope"' in html, "the corpus window Trend tab must mount #corpus-timescope"
    assert '_buildTrendScope($("corpus-timescope")' in html, (
        "the corpus Trend tab must build the time-scope over its trend series"
    )
    # both surfaces keep handing points to the UNCHANGED ooChart renderer.
    assert html.count('ooChart($("ins-trend-oo")') == 1
    assert html.count('ooChart($("corpus-chart")') == 1


def test_temporal_map_retired_into_ooMap():
    """Map rework slice 5b (maintainer ruling 2026-06-18, "fold signals in, then
    retire"): the standalone temporal-map PANEL is RETIRED — its UI was removed and
    the Map tab routes to the unified ooMap, which absorbed the temporal map's full
    capability (choropleth + signals layer + time slider + click-detail + the
    mentioned-places overlay).

    ABSORPTION-GATED (the Desk lesson — nothing lost): every capability the temporal
    map had must survive on ooMap before its panel is removed. This REPLACES the old
    test_tmap_mention_layer (the mention layer is now ooMap's Places overlay, slice 4,
    covered in test_ooMap_choropleth).
    """
    html = _ui_source()

    # 1) The old temporal-map PANEL + its controls are GONE from the chrome.
    for gone in (
        'id="tmap-slider"', 'id="tmap-svg"', 'id="tmap-wrap"', 'id="tmap-legend"',
        'id="tmap-mentions-toggle"', "Temporal map <span",
        'onclick="toggleTmapPlay()"', 'onclick="toggleTmapMentions()"', 'oninput="onTmapSlide()"',
    ):
        assert gone not in html, f"the retired temporal-map panel must not ship: {gone}"

    # 2) The Map tab now drives the unified ooMap directly (not the temporal loader).
    assert "timemap: loadOoMapCoverage," in html, "the Map tab must route to the unified ooMap"

    # 3) ABSORBED capabilities survive on ooMap (the Desk lesson):
    #    - the mentioned-PLACES overlay (was the temporal mention layer) reuses the
    #      SAME /api/insights/where substrate + the deduced caveat;
    assert "/api/insights/where" in html, "the mentioned-places capability must survive on ooMap"
    assert "Deduced from text, never confirmed." in html, "the deduced caveat must survive"
    #    - the signal click-detail (ported in 5a.2) + the in-map time slider live on ooMap.
    assert "data-oomap-sig=" in html and "function _ooMapSignalDetail(s, visible, win)" in html, (
        "the temporal map's signal click-detail must live on ooMap"
    )
    assert "data-oomap-focus" in html, "the in-map time slider must live on ooMap"

    # 4) The shared helpers ooMap reuses are NOT removed by the retire.
    assert "function tmapFindCoverage(" in html, "tmapFindCoverage (reused by the ooMap detail) must survive"

    # 5) The now-unreachable temporal-only functions are flagged for the deletion-cleanup.
    assert "RETIRED (slice 5b)" in html, "the dead temporal functions must be flagged unreachable"


def test_ooMap_choropleth():
    """ooMap slice 2 (maintainer ruling 2026-06-18): the universal CHOROPLETH
    component -- country fills coloured by a measured dimension, in-map zoom/pan,
    a colour-scale legend, honest no-data, and a centroid POINT fallback. First
    dimension = sources-per-country, on the rebuilt Map (Temporal-map) tab.

    Honesty (non-negotiable): no-data is visually DISTINCT from zero (a hatch,
    never a guessed colour); polygon-less territories become POINTS, never an
    invented border; the caveat is VISIBLE by default (#23); unlocated sources
    are surfaced, never placed; counts only, no score.
    """
    html = _ui_source()

    # The reusable component + its geometry loader (loopback-only asset, slice 1).
    assert "async function ooMap(host, opts)" in html, "the ooMap component must exist"
    assert "async function _ooMapGeoLoad()" in html, "the geometry loader must exist"
    assert "/static/world_countries.json" in html, "ooMap must load the slice-1 country polygons"

    # Reuses the EXISTING equirectangular projection -- no second projection invented.
    assert "function _ooMapPath(rings)" in html, "the polygon path builder must exist"
    assert "lon2x(p[0])" in html and "lat2y(p[1])" in html, (
        "country polygons must reuse the map's lon2x/lat2y projection"
    )

    # Honest NO-DATA: a hatched pattern fill, distinct from any data colour, NOT zero.
    assert "url(#oomap-nodata)" in html, "no-data countries must use the hatch fill"
    assert 'pattern id="oomap-nodata"' in html, "the no-data hatch pattern must be defined"
    assert 't("no data")' in html, "a country with no value must read 'no data', never zero"

    # Centroid POINT fallback ONLY for data areas the polygon set lacks (never a border).
    assert "geoCodes.has((p.iso2" in html, (
        "points are plotted only for data areas WITHOUT a polygon (no invented borders)"
    )
    assert 't("(shown as a point)")' in html or 't("small areas shown as points")' in html, (
        "the point fallback must be disclosed in the legend/readout"
    )

    # In-map controls (Google-Maps "controls inside the map") + instance-local pan/zoom.
    assert 'data-oomap="in"' in html and 'data-oomap="reset"' in html, "in-map zoom/reset controls"
    assert "function _wireOoMap(host, opts)" in html, "instance-local viewBox wiring must exist"

    # a11y: the svg is role=img with an aria summary + a screen-reader top list.
    assert 'id="oo-choro"' in html and 'role="img"' in html, "the choropleth svg needs role=img"
    assert 'aria-label="${esc(aria)}"' in html, "the choropleth needs an aria-label summary"

    # The colour scale inherits the theme accent (no hardcoded palette).
    assert "function _ooMapFill(t)" in html and "color-mix(in srgb, var(--accent)" in html, (
        "the sequential fill must derive from the theme accent via color-mix"
    )

    # The first dimension is wired to the SHIPPED endpoint and rendered on the Map tab.
    assert "async function loadOoMapCoverage()" in html, "the Map-tab loader must exist"
    assert "/api/insights/map-coverage" in html, "the loader must fetch the coverage endpoint"
    assert 'id="oo-coverage-map"' in html, "the Map tab must host the choropleth"
    assert "loadOoMapCoverage();" in html, "the loader must be wired into the Map-tab open path"

    # Caveat VISIBLE by default (#23) + unlocated data surfaced, never placed.
    assert 'class="card-caveat"' in html and "${esc(opts.caveat)}" in html, (
        "the choropleth caveat must render in a visible .card-caveat line"
    )
    assert "with no country — counted, not mapped." in html, (
        "unlocated (country-less) data must be surfaced honestly, never mapped"
    )

    # --- slice 3: the DIMENSION PICKER (articles / keywords / sentiment) --- #
    assert "function _ooMapDims()" in html, "the dimension config must exist"
    for dim_id in ('"sources"', '"articles"', '"keywords"', '"sentiment"'):
        assert f"id: {dim_id}" in html, f"dimension {dim_id} must be offered"
    # An in-map picker overlay whose buttons re-colour the map (no re-fetch).
    assert "data-oomap-dim=" in html, "the in-map dimension picker buttons must exist"
    assert "opts.onDimension(b.dataset.oomapDim)" in html, "picker buttons must switch dimension"
    assert "function _renderOoMapDim()" in html, "the per-dimension re-render must exist"
    # SIGNED data (mean tone) rides a DIVERGING scale, never a one-sided ramp.
    assert "function _ooMapFillDiverging(t)" in html, "sentiment needs a diverging fill"
    assert 'opts.scale === "diverging"' in html, "the scale must branch to diverging for signed data"
    assert "var(--err)" in html and "var(--ok)" in html, (
        "the diverging ramp must use the theme's err/ok hues"
    )
    # The sentiment dimension carries the VADER English-only caveat (B1), visible.
    assert "Mean article tone (VADER) — English-lexicon only" in html, (
        "the sentiment dimension must disclose the VADER English-only limit"
    )

    # --- slice 4: GRANULARITY (continent aggregation + place-points overlay) --- #
    assert "function _ooMapContinentAgg(rows, dim)" in html, "the continent aggregator must exist"
    # honest aggregate: SUM for counts, sentiment_n-WEIGHTED mean for tone.
    assert "acc[c].wsum += v * n" in html, "continent tone must be a sentiment_n-weighted mean"
    # in-map granularity toggle (country / continent) + the wiring.
    assert 'data-oomap-gran="continent"' in html, "the continent granularity toggle must exist"
    assert "opts.onGranularity(b.dataset.oomapGran)" in html, "granularity buttons must switch level"
    # the mentioned-places overlay (switchable), reusing the WHERE substrate.
    assert "data-oomap-places" in html and "opts.onPlaces()" in html, "the places-overlay toggle must exist"
    assert "/api/insights/where" in html, "the places overlay must reuse the WHERE substrate"
    # the overlay is a DEDUCED layer — its caveat is surfaced, never confirmed.
    assert "Mentioned places: deduced from text, never confirmed." in html, (
        "the mentioned-places overlay must carry its deduced/never-confirmed caveat"
    )

    # continent NAMES are localised too — routed through t(), not raw backend English
    # (the 6 names are keyed x12; this is the map being fully part of the translation).
    assert "t(r.continent)" in html, "continent labels must be translated via t()"

    # COUNTRY names are localised via the browser's CLDR (Intl.DisplayNames, keyed by
    # the ISO code) — accurate per locale, zero translation tables. Code-only surfaces
    # (FR/US) stay as their language-neutral codes.
    assert "function ooRegionName(code, fallback)" in html, "the CLDR country-name helper must exist"
    assert 'new Intl.DisplayNames([lang], { type: "region" })' in html, (
        "country names must use Intl.DisplayNames region data (no hand-translated table)"
    )
    assert "ooRegionName(code, c.name)" in html, "map polygon labels must localise the country name"

    # --- slice 5a: SIGNALS layer + in-map time slider (folding the temporal map in) --- #
    # A switchable signals layer reusing the temporal-map substrate (/api/timemap)
    # + its kind colours; events placed in space AND time, never re-projected.
    assert "data-oomap-signals" in html and "opts.onSignals()" in html, "the Signals layer toggle must exist"
    assert "/api/timemap?limit=4000" in html, "the signals layer must reuse the /api/timemap substrate"
    assert "kindColor(s.kind)" in html, "signals must reuse the temporal map's kind colours"
    # The in-map TIME slider sweeps the focus moment; signals filter by the focus window.
    assert "data-oomap-focus" in html and "opts.onFocus(+fs.value)" in html, "the in-map time slider must exist"
    assert "Math.abs(s.t - focus) <= win" in html, "signals must filter by the focus window (space AND time)"
    # Honest event convention carried over: future/unconfirmed = a hollow/dashed ring.
    assert "const future = focus != null && s.t > focus" in html, "future events stay distinct (hollow/dashed)"

    # --- slice 5a.2: signal CLICK-TO-DETAIL (ported faithfully so 5b's retire loses nothing) --- #
    assert "data-oomap-sig=" in html and "opts.onSignal(s, host._ooSigVisible" in html, (
        "signal markers must be clickable -> the detail panel"
    )
    assert "function _ooMapSignalDetail(s, visible, win)" in html, "the ported signal-detail panel must exist"
    assert 'id="oo-coverage-detail"' in html, "the Map tab must host the signal-detail panel"
    # The honest space-time co-occurrence framing is carried over verbatim (never a cause).
    assert "function _ooMapNearby(s, visible, win)" in html, "the 'near in space & time' seed must be ported"
    assert "co-occurrence, not a connection or cause. You judge." in html, (
        "the near-in-space-time panel must keep its non-causal caveat"
    )
    # The space-time loop back to the corpus is preserved (find coverage).
    assert "tmapFindCoverage(" in html, "the 'find coverage in your corpus' action must be preserved"


def test_search_timescope():
    """The Search sidebar tab reuses the SAME ooTimeScope control for date-range
    filtering (maintainer: "reuse the time-range control everywhere") so PERIODS
    are first-class — replacing the old #f-from / #f-to begin/end date inputs.

    Asserts: the legacy date inputs are gone; the control mounts into
    #search-timescope via the ONE ooTimeScope factory (not a fork); and the
    selected from/to feed the UNCHANGED backend params start_date / end_date.
    """
    html = _ui_source()
    # the reusable component (shared with Markets/Insights/corpus window)
    assert "function ooTimeScope" in html, "the reusable ooTimeScope control must exist"
    # the legacy Search begin/end date inputs are REMOVED (replaced by the control)
    assert 'id="f-from"' not in html, "the legacy #f-from date input must be gone"
    assert 'id="f-to"' not in html, "the legacy #f-to date input must be gone"
    # the new container + the factory mounting the SAME component there
    assert 'id="search-timescope"' in html, "the Search tab must mount #search-timescope"
    assert "function buildSearchTimeScope" in html, "the Search time-scope factory must exist"
    assert 'ooTimeScope(box, {' in html, "the factory must instantiate the SAME ooTimeScope"
    # the from/to reach the search query via the UNCHANGED backend params
    assert "function searchTimeScopeParams" in html, "the param-forwarding helper must exist"
    assert 'p.set("start_date", sel.from)' in html, "the control's 'from' must feed start_date"
    assert 'p.set("end_date", sel.to)' in html, "the control's 'to' must feed end_date"
    assert "searchTimeScopeParams(p)" in html, "searchParams() must forward the time-scope window"
    # mounted lazily on first Search-tab open (TAB_LOADERS), idempotent
    assert "search: buildSearchTimeScope" in html, (
        "the Search tab loader must mount the time-scope control"
    )


def test_oochart_enlarge_indices():
    """ooChart is rolled onto the indices board detail (invariant #16).

    The REMAINING markets work (CLAUDE.md "MARKETS/INDICES/COMMODITIES") was to
    roll the ONE interactive chart toolkit onto the indices board detail (it was
    a static spark only). The commodity-card "enlarge"/detail path
    (chartSymbol -> #mkt-chart-oo) ALREADY used ooChart; this guards that the
    indices detail joins it through the SAME renderer (never a forked chart, the
    full series fetched from /api/commodities/{symbol}/prices, never the
    truncated board spark). The tiny in-card multiples (dashChartSvg / idxSpark)
    stay static (intended), and ooChart itself is unchanged.
    """
    html = _ui_source()
    # the indices detail handler exists and feeds THE shared toolkit
    assert "function indexDetail(" in html, "the indices detail handler must exist"
    assert 'ooChart($("idx-chart-oo")' in html, (
        "the indices detail must render through THE ooChart toolkit (invariant #16)"
    )
    # it pulls the FULL series from the prices endpoint, not the truncated spark
    assert "/api/commodities/${encodeURIComponent(symbol)}/prices" in html
    # index cards open the detail (the click path is wired, with data only)
    assert "onclick=\"indexDetail(" in html, "index cards must open the ooChart detail"
    assert 'id="idx-chart"' in html, "the indices detail mount container must exist"
    # the commodity board detail still uses ooChart too — now via the ONE shared
    # fullscreen overlay (P2-10: chartSymbol → chartEnlarge → ooChart), not a forked
    # chart. The indices comparison overlay uses the same chartEnlarge path.
    assert "chartEnlarge(`${symbol}" in html, (
        "the commodity price detail must route through the shared chartEnlarge (ooChart) overlay"
    )
    # ooChart itself is NOT forked: exactly one definition
    assert html.count("function ooChart(") == 1, "ooChart must not be forked"
    # the tiny in-card multiples remain the static SVGs (not converted)
    assert "function dashChartSvg(" in html and "function idxSpark(" in html


def test_commodity_corpus_entry():
    """The commodity/index GRAPH is a first-class entry into the analysis WINDOW
    (ledger MARKETS item 4 / the corpora-system commodity-click entry): a clear
    "Analyse ↗" affordance under the commodity chart and on the index card opens
    the corpus via the EXISTING openAnalysisFor (no new opener, no new backend).

    NON-DESTRUCTIVE (the Desk lesson): the price-detail + correlation path stays
    reachable — the card body still routes to chartSymbol / indexDetail. The term
    is the curated COMMODITY_QUERY family seed (else the real series/index name),
    never a fabricated family. Distinct from the already-shipped title (⊞) entry,
    which is left untouched (test_commodity_card_opens_analysis covers it)."""
    html = _ui_source()
    # the universal opener we wire to (reused, never reinvented)
    assert "function openAnalysisFor" in html, "openAnalysisFor must exist to wire to"
    # the graph carries an explicit "Analyse" affordance opening the window;
    # the visible label is keyed for ×12 translation
    assert 't("Analyse")' in html or 't2("Analyse")' in html, (
        "the graph must carry a keyed 'Analyse' affordance"
    )
    # that affordance opens the analysis window WITHOUT hijacking the card's own
    # price-detail click (stopPropagation), seeds the curated family query, AND
    # carries the commodity identity (Item 3) so the Price overlay subtab can show
    # the price curve x corpus coverage.
    assert "event.stopPropagation(); openAnalysisFor(${esc(JSON.stringify(q))}, ${cOpts})" in html, (
        "the commodity graph 'Analyse' must open the window on the family query + commodity opts"
    )
    # the PRICE-DETAIL + correlation path is NOT removed (the Desk lesson)
    assert "function chartSymbol(" in html, "the commodity price-detail handler must stay"
    assert "function correlateSymbol(" in html, "the price-vs-news correlation must stay"
    assert 'onclick="chartSymbol(' in html, "the commodity card body must still open price detail"
    assert "function indexDetail(" in html, "the index price-detail handler must stay"
    # honest term: the curated family seed, else the real name — never fabricated
    assert "COMMODITY_QUERY[s.symbol] || s.name" in html, (
        "the commodity term must be the curated family seed, defaulting to the name"
    )
def test_corpus_window_mindmap_subtab():
    """Mindmap sub-tab on THE corpus analysis window (ledger "ONE CORPORA
    SYSTEM": Mindmap is one of the ruled sub-tabs). It must REUSE the existing
    associations mind-map (renderMindmap → renderGraph) — the same radial
    renderer that carries the maintainer mind-map rules + in-map controls — NOT
    a new graph impl, and NOT a new backend endpoint. Pinned so it cannot
    regress between sessions:
      * a data-tab="mindmap" button exists in the corpus window's ooSubtabs nav;
      * corpusTab() handles "mindmap" by relocating the SHARED mind-map kit and
        calling renderMindmap() for THIS window's corpus term;
      * the renderer is reused, not forked (one renderMindmap / one renderGraph).
    """
    html = _ui_source()
    # 1. the Mindmap button lives in the corpus window's subtab nav.
    nav = html.split('id="corpus-subtabs"', 1)[1].split("</nav>", 1)[0]
    assert 'data-tab="mindmap"' in nav, (
        "the corpus window must carry a Mindmap sub-tab button in its ooSubtabs nav"
    )
    assert "Mindmap" in nav, "the sub-tab button label must be DOM text (auto-translated)"
    # the Trend/Articles/Links siblings stay (nothing lost).
    for sib in ('data-tab="trend"', 'data-tab="articles"', 'data-tab="links"'):
        assert sib in nav, f"corpus sub-tab regressed: {sib} missing"
    # 2. corpusTab dispatches "mindmap" → the SHARED renderer for the window term.
    body = html.split("async function corpusTab(", 1)[1].split("\n    function ", 1)[0]
    assert 'which === "mindmap"' in body, "corpusTab must handle the mindmap sub-tab"
    assert "renderMindmap(_corpusTerm)" in body, (
        "the Mindmap sub-tab must render the EXISTING associations mind-map for "
        "THIS window's corpus term (renderMindmap → renderGraph), not a new graph"
    )
    assert 'appendChild(kit)' in body or '$("mm-kit")' in body, (
        "the Mindmap sub-tab must RELOCATE the shared #mm-kit (no fork, no "
        "duplicate IDs) rather than re-implement the control bar"
    )
    # 3. the renderer is reused, not forked: exactly one of each.
    assert html.count("async function renderMindmap(") == 1, "renderMindmap must not be forked"
    assert html.count("function renderGraph(") == 1, "renderGraph must not be forked"
    # 4. the shared kit has a home anchor so it returns to Insights on leave/close.
    assert 'id="mm-kit"' in html and 'id="mm-kit-home"' in html, (
        "the relocatable mind-map kit needs a home anchor so Insights is never "
        "left without its mind-map"
    )
    assert "function _mmKitHome(" in html, "the kit must be restorable to Insights"


def test_corpus_window_sentiment_subtab():
    """Sentiment sub-tab on THE corpus analysis window (ledger "ONE CORPORA
    SYSTEM": Sentiment analysis is one of the ruled sub-tabs). It must REUSE the
    existing Insights framing renderer (loadFraming -> /api/framing) pointed at
    the window's corpus term -- NOT a new sentiment engine, NOT a new endpoint --
    and it MUST carry the English-only VADER disclosure (audit finding B1) so the
    honesty travels onto this surface. Pinned so it cannot regress between
    sessions:
      * a data-tab="sentiment" button exists in the corpus window's ooSubtabs nav
        (DOM-text label, no inline onclick) and the Trend/Articles/Links/Mindmap
        siblings stay (nothing lost);
      * corpusTab() handles "sentiment" by calling loadFraming() for _corpusTerm;
      * the renderer is reused, not forked (exactly one loadFraming);
      * the English-only VADER disclosure is reachable on this surface (the
        button's hover title states it AND the shared renderer emits the
        endpoint's caveat -- which is the English-lexicon VADER disclosure).
    """
    html = _ui_source()
    # 1. the Sentiment button lives in the corpus window's subtab nav.
    nav = html.split('id="corpus-subtabs"', 1)[1].split("</nav>", 1)[0]
    assert 'data-tab="sentiment"' in nav, (
        "the corpus window must carry a Sentiment sub-tab button in its ooSubtabs nav"
    )
    assert "Sentiment" in nav, "the sub-tab button label must be DOM text (auto-translated)"
    # the Trend/Articles/Links/Mindmap siblings stay (nothing lost).
    for sib in ('data-tab="trend"', 'data-tab="articles"', 'data-tab="links"', 'data-tab="mindmap"'):
        assert sib in nav, f"corpus sub-tab regressed: {sib} missing"
    # the English-only VADER disclosure is present in the button's hover long-form
    # (informed-consent layering) -- VADER + ENGLISH must both be named.
    assert "VADER" in nav and "ENGLISH" in nav.upper(), (
        "the Sentiment sub-tab must disclose the English-only VADER limit (audit B1) "
        "in its hover title"
    )
    # 2. corpusTab dispatches "sentiment" -> the SHARED framing renderer, term-keyed.
    body = html.split("async function corpusTab(", 1)[1].split("\n    function ", 1)[0]
    assert 'which === "sentiment"' in body, "corpusTab must handle the sentiment sub-tab"
    assert "loadFraming(_corpusTerm" in body, (
        "the Sentiment sub-tab must render the EXISTING Insights framing surface "
        "(loadFraming -> /api/framing) for THIS window's corpus term, not a new engine"
    )
    # 3. the renderer is reused, not forked: exactly one loadFraming.
    assert html.count("async function loadFraming(") == 1, "loadFraming must not be forked"
    # 4. loadFraming emits the endpoint's caveat (the English-only VADER disclosure)
    #    so the disclosure is VISIBLE on this surface, not just the hover title.
    framing_fn = html.split("async function loadFraming(", 1)[1].split("\n    async function ", 1)[0]
    assert "d.caveat" in framing_fn, (
        "the framing renderer must surface the endpoint caveat (English-only VADER "
        "disclosure) on every surface that reuses it, including the corpus window"
    )


def test_corpus_window_keywords_subtab():
    """Keywords sub-tab on THE corpus analysis window (ledger "ONE CORPORA
    SYSTEM": Keyword analysis is one of the ruled sub-tabs). It must REUSE the
    existing associations data (/api/insights/associations -> q.associations,
    the SAME data the mind-map plots) rendered as a ranked TABLE -- NOT a new
    keyword engine, NOT a new endpoint -- and present REAL per-keyword numbers
    with no composite score, distinct from the radial Mindmap. Pinned so it
    cannot regress between sessions:
      * a data-tab="keywords" button exists in the corpus window's ooSubtabs nav
        (DOM-text label, no inline onclick) and the Trend/Articles/Links/Mindmap/
        Sentiment siblings stay (nothing lost);
      * corpusTab() handles "keywords" by calling the table renderer for the
        window's _corpusTerm via the existing associations endpoint;
      * each row opens that keyword as its own corpus (openCorpus reuse) and the
        table is honest -- the endpoint method/caveat travel onto the surface,
        and n is shown; no composite score is invented.
    """
    html = _ui_source()
    # 1. the Keywords button lives in the corpus window's subtab nav (DOM text).
    nav = html.split('id="corpus-subtabs"', 1)[1].split("</nav>", 1)[0]
    assert 'data-tab="keywords"' in nav, (
        "the corpus window must carry a Keywords sub-tab button in its ooSubtabs nav"
    )
    assert "Keywords" in nav, "the sub-tab button label must be DOM text (auto-translated)"
    # the Trend/Articles/Links/Mindmap/Sentiment siblings stay (nothing lost).
    for sib in (
        'data-tab="trend"',
        'data-tab="articles"',
        'data-tab="links"',
        'data-tab="mindmap"',
        'data-tab="sentiment"',
    ):
        assert sib in nav, f"corpus sub-tab regressed: {sib} missing"
    # 2. corpusTab dispatches "keywords" -> the ranked-table renderer for _corpusTerm.
    body = html.split("async function corpusTab(", 1)[1].split("\n    function ", 1)[0]
    assert 'which === "keywords"' in body, "corpusTab must handle the keywords sub-tab"
    assert "renderCorpusKeywords(_corpusTerm" in body, (
        "the Keywords sub-tab must render the ranked table for THIS window's corpus term"
    )
    # 3. the renderer reuses the EXISTING associations endpoint (no new keyword engine).
    kfn = html.split("async function renderCorpusKeywords(", 1)[1].split(
        "\n    function ", 1
    )[0]
    assert "/api/insights/associations?" in kfn, (
        "the Keywords table must reuse the existing associations endpoint, not a new engine"
    )
    # 4. it renders a TABLE (distinct from the radial Mindmap graph).
    assert "<table" in kfn, "the Keywords sub-tab must render a TABLE (not a graph)"
    # 5. rows are clickable into that keyword's own corpus window (openCorpus reuse).
    assert "openCorpus(" in kfn, (
        "each Keywords row must open that keyword as its own corpus (openCorpus reuse)"
    )
    # 6. honesty: the endpoint method/caveat travel onto the surface and n is shown;
    #    no composite score is invented.
    assert "d.method" in kfn and "d.caveat" in kfn, (
        "the Keywords table must surface the endpoint's method + caveat (PMI honesty)"
    )
    assert "n_articles_with_term" in kfn, "the Keywords table must show n (real corpus count)"


def test_corpus_window_sources_subtab():
    """THE ONE CORPORA SYSTEM: the corpus analysis window carries a SOURCES
    (source-description) sub-tab -- WHICH sources feed this corpus, with their
    REAL per-corpus article count + the catalog metadata they ASSERT (domain,
    country, region, language, tags). Descriptive provenance, NOT the (future)
    competitive/angle tab and NOT tone (Sentiment owns that). It REUSES an
    existing endpoint -- no new backend, no fork. Pinned so it cannot regress:
      * a data-tab="sources" button exists in the corpus window's ooSubtabs nav
        (DOM-text label, no inline onclick) and every sibling sub-tab stays;
      * corpusTab() handles "sources" by calling renderCorpusSources for the
        window's _corpusTerm into a fresh #corpus-sources-host;
      * the renderer reuses /api/insights/corpus-sources (the corpus's distinct
        sources + REAL per-corpus article count) and enriches client-side from
        the bulk /api/sources catalog (no new keyword/source engine);
      * two-class honesty + no fabricated description: catalog metadata is
        labelled ASSERTED (not deduced), and a source with nothing on file reads
        an honest "No catalog metadata on file." (never a generated bio);
      * the source name reuses the EXISTING source-profile view (loadProfile),
        not an invented destination.
    """
    html = _ui_source()
    # 1. the Sources button lives in the corpus window's subtab nav (DOM text).
    nav = html.split('id="corpus-subtabs"', 1)[1].split("</nav>", 1)[0]
    assert 'data-tab="sources"' in nav, (
        "the corpus window must carry a Sources sub-tab button in its ooSubtabs nav"
    )
    assert "Sources" in nav, "the sub-tab button label must be DOM text (auto-translated)"
    # every sibling sub-tab stays (nothing lost).
    for sib in (
        'data-tab="trend"',
        'data-tab="articles"',
        'data-tab="links"',
        'data-tab="mindmap"',
        'data-tab="sentiment"',
        'data-tab="keywords"',
    ):
        assert sib in nav, f"corpus sub-tab regressed: {sib} missing"
    # 2. corpusTab dispatches "sources" -> the source-description renderer for _corpusTerm.
    body = html.split("async function corpusTab(", 1)[1].split("\n    function ", 1)[0]
    assert 'which === "sources"' in body, "corpusTab must handle the sources sub-tab"
    assert "renderCorpusSources(_corpusTerm" in body, (
        "the Sources sub-tab must render for THIS window's corpus term into a fresh host"
    )
    assert 'id="corpus-sources-host"' in body, (
        "the Sources sub-tab must mount a fresh #corpus-sources-host (the function-into-host pattern)"
    )
    # 3. the renderer reuses EXISTING endpoints (no new backend, no fork).
    sfn = html.split("async function renderCorpusSources(", 1)[1].split(
        "\n    function ", 1
    )[0]
    assert "/api/insights/corpus-sources?" in sfn, (
        "the Sources tab must reuse /api/insights/corpus-sources for the corpus's sources"
    )
    assert "/api/sources/?" in sfn, (
        "the Sources tab must enrich from the bulk /api/sources catalog (client-side merge)"
    )
    # 4. REAL per-source numbers + asserted metadata fields (no fabrication).
    assert "r.articles" in sfn, "each source row must show its REAL per-corpus article count"
    for field in ("meta.country", "meta.region", "meta.language", "meta.tags"):
        assert field in sfn, f"the Sources tab must show the asserted metadata field: {field}"
    # 5. honesty: asserted-not-deduced is stated, no generated description, honest empties.
    assert "asserted" in sfn.lower() and "deduced" in sfn.lower(), (
        "the Sources tab must label catalog metadata ASSERTED, not deduced from text"
    )
    assert "No catalog metadata on file." in sfn, (
        "a source with nothing on file must read an honest empty, never a fabricated description"
    )
    assert "No sources for this corpus yet." in sfn, "honest empty state when the corpus has no sources"
    # 6. the source name reuses the EXISTING source-profile view (loadProfile).
    assert "loadProfile()" in sfn, (
        "the source name must reuse the existing source-profile view, not an invented destination"
    )


def test_corpus_window_competitive_subtab():
    """THE ONE CORPORA SYSTEM: the corpus analysis window's LAST design facet --
    the corpus-only SOURCE-COMPETITIVE sub-tab. It shows how each source DIFFERS
    (volume / tone / timing / emphasis) side by side: a DESCRIPTIVE comparison of
    divergence, NEVER a ranking, a winner or a credibility verdict, and NEVER a
    composite score. It JOINS two EXISTING endpoints per source -- no new backend,
    no fork. Pinned so it cannot regress:
      * a data-tab="competitive" button exists in the corpus window's ooSubtabs
        nav (DOM-text label, no inline onclick) and every sibling sub-tab stays;
      * corpusTab() handles "competitive" by calling renderCorpusCompetitive for
        the window's _corpusTerm into a fresh #corpus-competitive-host;
      * the renderer JOINS /api/insights/corpus-sources (volume/timing/mean tone)
        with /api/framing (tone label + emphasised terms) -- both existing;
      * the four REAL dimensions are shown (volume = exact count, tone = VADER,
        timing = real first/last dates, emphasis = framing top_terms);
      * the n=1 honest state exists ("nothing to compare");
      * the "not a ranking / not credibility" + the VADER English-only
        disclosures are reachable (informed consent).
    """
    html = _ui_source()
    # 1. the Competitive button lives in the corpus window's subtab nav (DOM text).
    nav = html.split('id="corpus-subtabs"', 1)[1].split("</nav>", 1)[0]
    assert 'data-tab="competitive"' in nav, (
        "the corpus window must carry a Competitive sub-tab button in its ooSubtabs nav"
    )
    assert "Competitive" in nav, "the sub-tab button label must be DOM text (auto-translated)"
    assert "onclick" not in nav.lower(), "no inline onclick -- the ooSubtabs component owns clicks"
    # every sibling sub-tab stays (nothing lost).
    for sib in (
        'data-tab="trend"',
        'data-tab="articles"',
        'data-tab="links"',
        'data-tab="mindmap"',
        'data-tab="sentiment"',
        'data-tab="keywords"',
        'data-tab="sources"',
    ):
        assert sib in nav, f"corpus sub-tab regressed: {sib} missing"
    # 2. corpusTab dispatches "competitive" -> the renderer for _corpusTerm.
    body = html.split("async function corpusTab(", 1)[1].split("\n    function ", 1)[0]
    assert 'which === "competitive"' in body, "corpusTab must handle the competitive sub-tab"
    assert "renderCorpusCompetitive(_corpusTerm" in body, (
        "the Competitive sub-tab must render for THIS window's corpus term into a fresh host"
    )
    assert 'id="corpus-competitive-host"' in body, (
        "the Competitive sub-tab must mount a fresh #corpus-competitive-host (function-into-host)"
    )
    # 3. the renderer JOINS the two EXISTING endpoints (no new backend, no fork).
    cfn = html.split("async function renderCorpusCompetitive(", 1)[1].split(
        "\n    function ", 1
    )[0]
    assert "/api/insights/corpus-sources?" in cfn, (
        "Competitive must reuse /api/insights/corpus-sources for volume/timing/tone"
    )
    assert "/api/framing?" in cfn, (
        "Competitive must reuse /api/framing for the tone label + emphasised terms"
    )
    # 4. the four REAL dimensions are present (no score, no invented value).
    assert "r.articles" in cfn, "Volume must be the REAL per-source article count"
    assert "mean_tone" in cfn or "avg_tone" in cfn, "Tone must be the REAL VADER value"
    assert "r.first" in cfn and "r.last" in cfn, "Timing must use REAL first/last dates"
    assert "top_terms" in cfn, "Emphasis must come from the framing top_terms (real)"
    # 5. n=1 honest state -- "nothing to compare" (the ledger's n=1 has no competition).
    assert "rows.length === 1" in cfn, "the Competitive tab must special-case the single-source corpus"
    assert "Only one source in this corpus — nothing to compare." in cfn, (
        "n=1 must read an honest 'nothing to compare', never a fake comparison"
    )
    assert "No sources for this corpus yet." in cfn, "honest empty state when the corpus has no sources"
    # 6. the disclosures are reachable: 'not a ranking/credibility' + VADER English-only.
    assert "never a ranking" in cfn.lower(), "the 'descriptive, not a ranking' disclosure must be visible"
    assert "credibility" in cfn.lower(), "the 'not a credibility judgement' framing must be present"
    assert "VADER" in cfn, "the VADER tone disclosure must be reachable (tone is shown)"
    # honesty by construction: the comparison is ordered, never scored/ranked-as-quality.
    assert "composite score" not in cfn or "no composite score" in cfn.lower() or (
        "never a" in cfn.lower()
    ), "the Competitive tab must not compute a composite score"


def test_keyword_explorer_subtab():
    """Item AC: a Settings -> Keywords subtab explores keywords by their type/topic
    tags (the S3a tag API), hides noise, and applies the curated baseline tags
    (backfill). Panel content is un-keyed English, matching the adjacent super-group
    + diagnostics keyword-curation UIs; the nav label reuses the keyed 'Keywords'."""
    src = _ui_source()
    assert 'data-tab="keywords"' in src, "the Settings Keywords subtab button must exist"
    assert 'id="set-keywords"' in src, "the Keywords panel must exist"
    assert "function loadKeywordExplorer" in src, "the explorer loader must exist"
    assert "/api/insights/keyword-tags/facets" in src, "explore must read the tag facets"
    assert "/api/insights/keyword-tags/backfill" in src, "the apply-baseline-tags action must exist"
    assert "/api/insights/exclude" in src, "the hide action must reuse the exclude endpoint"


def test_families_kind_filter_and_taxonomy_honesty():
    """2026-07-18 field fix (entity-families brief, §0 rows 1-2): the Insights Families
    'all' filter used to fetch the raw top-N (terms included) then trim kind!=='term'
    CLIENT-side -- filter-AFTER-limit, so a term-dominated corpus starved the entity
    view down to whatever stray rows survived. The kind filter now applies SERVER-side,
    before the limit (kind=non_term is the new every-non-term-kind alias, same as
    'entity' until a real NER pass diversifies entity_type); the dropdown drops the
    never-populated person/org/location options (never fabricate taxonomy) with an
    honest note explaining why, and the stale 'Trump = Trump's' blurb (describing the
    retired Title-Case entity model) is gone."""
    src = _ui_source()
    i = src.index('id="ins-families"')
    j = src.index("</section>", i)
    section = src[i:j]
    assert 'value="entity"' in section and 'value="non_term"' in section
    for dead in ('value="person"', 'value="org"', 'value="location"'):
        assert dead not in section, f"{dead} is a fabricated, always-empty option"
    assert "await a future NER/gazetteer pass" in section, "the dead-option note must state why"
    assert "Trump" not in section, "the stale entity model's blurb example must be gone"

    # backend: kind=non_term applies is_entity=True BEFORE the limit (never a filter-after-limit trim)
    qsrc = (_SRC / "analytics" / "queries.py").read_text(encoding="utf-8")
    assert '"non_term"' in qsrc and "Keyword.is_entity.is_(True)" in qsrc
    api_src = (_SRC / "api" / "insights.py").read_text(encoding="utf-8")
    assert '"non_term"' in api_src, "non_term must be an accepted kind value on the endpoint"

    # the Insights read-only view no longer client-filters by kind after the fetch (the bug)
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    fam_view = app[app.index("async function loadFamilies(") : app.index("async function loadFamilyCuration(")]
    assert 'filter(f => f.kind !== "term")' not in fam_view, (
        "a client-side filter-after-limit is exactly the bug this fix replaces"
    )
    assert "&kind=" in fam_view, "the kind filter must be sent server-side unconditionally"


def test_family_curation_relocated_to_settings_and_single_member_guarded():
    """S4 of the same brief: the merge/split curation UI moves OFF the content tab
    (invariant #8) into Settings -> Keywords, beside the Keywords explorer; Insights
    keeps only the DATA view (no checkboxes/Merge button/split chips). The relocated
    review list is decision-only (multi-member/ring/manual-override -- never thousands
    of single-member rows), and a single-member family's split chip is a guarded
    no-op (§0 row 7) rather than a meaningless override write."""
    src = _ui_source()

    ins_i = src.index('id="ins-families"')
    ins_j = src.index("</section>", ins_i)
    ins_section = src[ins_i:ins_j]
    for gone in ("fam-pick", "familyMerge()", "familySplit(", "Merge selected"):
        assert gone not in ins_section, f"{gone!r} must not remain on the Insights data view"

    set_i = src.index('id="set-keywords"')
    set_j = src.index('id="set-leads"', set_i)  # the whole Settings Keywords view
    set_section = src[set_i:set_j]
    assert 'id="famc-list"' in set_section, "the relocated curation list must exist in Settings"
    assert 'onclick="familyMerge()"' in set_section
    assert 'id="fam-overrides"' in set_section, "the overrides list rides along (nothing lost)"

    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    cur = app[app.index("async function loadFamilyCuration(") : app.index("async function familySplit(")]
    assert "f.variants > 1 || f.ring_id || f.manual" in cur, (
        "the relocated review list must show ONLY rows where a decision exists"
    )
    assert "data-single=" in cur, "each split chip must carry whether its family is single-member"

    split_fn = app[app.index("async function familySplit(") : app.index("async function familyMerge(")]
    assert 'dataset.single === "1"' in split_fn, "a single-member family's ✕ must be a guarded no-op"
    assert "Nothing to split" in split_fn

    assert "loadFamilyCuration()" in app, "showSetCat must wire the curation loader on the Keywords subtab"


def test_super_ring_ui():
    """Step 4 of the pre-translation program: the Groups (super-groups) UI can add a
    cross-language RING as a member (the super-ring model), not just a family. It
    extends the existing super-group UI; a ring picker datalist is fed by
    /api/insights/rings and the add-ring handler POSTs a ring member."""
    src = _ui_source()
    assert 'id="sg-ring-options"' in src, "the ring-picker datalist must exist"
    assert "/api/insights/rings" in src, "loadSuperGroups must fetch the rings list"
    assert "function sgAddRing" in src, "the add-ring handler must exist"
    assert "rings: [ring]" in src, "add-ring must POST a ring member (not a family normalized)"


def test_supergroup_stats_ui():
    """Supergroups brief S1.5: the Groups surface discloses the honest per-group
    statistics (§0 rows 1/2/3/7) — a bounded windowed rate + sparkline on the
    top-mentioned groups, the mandatory dominance line, cross-group overlap on a
    member's hover, and zero-mention members collapsed behind a count rather than
    rendered as a wall of empty chips."""
    src = _ui_source()
    assert "series_top=12" in src, "loadSuperGroups must request a BOUNDED top-N series (never all groups)"
    fn = src[src.index("function sgCard(") : src.index("async function createSuperGroup(")]
    assert "g.dominance" in fn, "row 1: the dominance disclosure must render"
    assert "also_in" in fn, "row 2: cross-group overlap must be disclosed on a member"
    assert "zeroCount" in fn and "with no mentions yet" in fn, "row 7: zero-mention members must collapse"
    assert "dashChartSvg(g.series" in fn, "S1.5: the sparkline must reuse the shared honest-charts primitive"
    assert "g.rate.growth" in fn, "S1.5: the disclosed recent-vs-baseline rate must render"


def test_supergroup_curation_relocated_to_settings():
    """Supergroups brief S5: create/add-family/add-ring/delete/remove-member move
    to Settings -> Keywords (sgCurationCard); Insights -> Groups (sgCard) keeps
    ONLY the read-only data view (stats/dominance/trend/members-with-provenance),
    per the Desk rule -- nothing lost, just relocated."""
    src = _ui_source()
    assert 'id="sgc-name"' in src and 'onclick="createSuperGroup()"' in src, (
        "the create-group input must live in the Settings curation panel"
    )
    assert "function loadSupergroupCuration(" in src and "function sgCurationCard(" in src
    assert 'loadSupergroupCuration();' in src[
        src.index('if (cat === "keywords")') : src.index('if (cat === "keywords")') + 200
    ], "the Settings Keywords subtab must load the super-group curation panel"

    # sgCard (Insights, the data view) must carry NONE of the mutation actions.
    card_fn = src[src.index("function sgCard(") : src.index("async function createSuperGroup(")]
    for forbidden in ("sgRemoveMember", "deleteSuperGroup", "sgAddMember(this", "sgAddRing(this"):
        assert forbidden not in card_fn, f"sgCard (data view) must not carry {forbidden!r}"

    # sgCurationCard (Settings) carries all four.
    curation_fn = src[src.index("function sgCurationCard(") : src.index("async function sgAddMember(")]
    for required in ("deleteSuperGroup", "sgAddMember(this", "sgAddRing(this", "sgRemoveMember(this)"):
        assert required in curation_fn, f"sgCurationCard must carry {required!r}"


def test_keyword_to_supergroup_navigation():
    """Supergroups brief S3: a keyword's super-group membership is surfaced as a
    chip in the analysis window's Keywords subtab AND on omnibar keyword rows,
    linking to the group's own view (deep-scrolled to it, plural membership
    rendering every hit, never picking one)."""
    src = _ui_source()
    fn = src[src.index("function anRenderKwChips(") : src.index("function anContextHtml(")]
    assert "term.supergroups" in fn and "openSupergroup(" in fn, (
        "the Keywords-subtab chip must render every super-group the keyword belongs to"
    )
    assert "function openSupergroup(" in src, "the deep-link handler must exist"
    assert 'id="sg-card-${g.id}"' in src, "each group card must be addressable for the deep-link scroll"
    assert "it.supergroups" in src, "omnibar keyword rows must surface the same membership"


def test_naming_sweep_ring_disappears_from_the_user_visible_ui():
    """GROUPS layer amendment §A: the user-facing hierarchy is keyword -> group ->
    super-group. "ring" stays the internal name (ring_id / /ring-countries / /rings
    / the sg-ring-* element ids and datalists -- the Lead-rename precedent: labels
    only, no internal identifier change) but disappears from every string a user
    actually reads. Also resolves the naming collision: the Insights subtab that
    opens the super-group data view must say "Super-groups", not the ambiguous
    "Groups" (which the panel it opens never was)."""
    src = _ui_source()

    # The collision fix: the subtab nav button matches what #ins-supergroups holds.
    assert '<button data-tab="supergroups">Super-groups</button>' in src
    assert '<button data-tab="supergroups">Groups</button>' not in src

    # Regression-pin the specific curation-chrome fixes (§A "ring" pills/buttons/
    # placeholders -> "group"); scoped to exact prior literals so a legitimate
    # internal `ring_id`/`ring-countries`/geometric "ring" (donut slices, mind-map
    # concentric rings, GIS polygon rings, SVG hollow-ring markers) can never
    # false-positive this guard.
    forbidden_literals = (
        '<span class="pill" title="a cross-language ring merge">ring</span>',
        "add families or rings to it",
        '<span class="muted">ring·${(m.ring_members || []).length}</span>',
        "add a family or a ring below",
        'placeholder="add a ring (one concept, many languages)…"',
        ">Add ring</button>",
        'toast("Ring added.")',
        'toast("Add ring failed:',
    )
    for lit in forbidden_literals:
        assert lit not in src, f"a user-visible 'ring' literal survived the naming sweep: {lit!r}"

    # (the group pill's static title was superseded by §B's translated lvlTitle()
    # hover + the .lvl-group ring class -- test_circle_grammar_level_marking_is_
    # wired_and_contrast_verified pins that evolved markup.)
    required_literals = (
        'class="pill lvl-group"',
        "add families or groups to it",
        '<span class="muted">group·${(m.ring_members || []).length}</span>',
        "add a family or a group below",
        'placeholder="add a group (one concept, many languages)…"',
        ">Add group</button>",
        'toast("Group added.")',
        'toast("Add group failed:',
    )
    for lit in required_literals:
        assert lit in src, f"expected the renamed literal to be present: {lit!r}"

    # Internal identifiers are UNCHANGED (the brief's explicit "no internal id / API
    # path / config key change" rule) -- these still say "ring" by design.
    for internal in ('id="sg-ring-options"', "ring_id", "/api/insights/ring-countries",
                      "/api/insights/rings"):
        assert internal in src, f"internal ring-named identifier must be preserved: {internal!r}"


def test_naming_sweep_ring_map_header_is_keyed_group_wording():
    """The concept-map header (index.html, static -> keyable) picks a GROUP, not a
    ring, and the picker label reads "Concept (group)" -- both via NEW keys (an
    edited English string would silently orphan the old translation), so all 12
    locales stay covered."""
    import json

    locales_dir = _SRC / "static" / "locales"
    en = json.load(open(locales_dir / "en.json", encoding="utf-8"))
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    key1 = (
        "Pick a cross-language group — one concept counted across every language — "
        "to see where its coverage comes from, split by the producing source's "
        "country and language. Counts only; a source with an unknown country is "
        "shown honestly (never mapped, never guessed)."
    )
    key2 = "Concept (group)"
    assert key1 in en and key2 in en, "the renamed map-header keys must exist in en.json"
    assert key1 in html and key2 in html, "index.html must use the new group-wording keys"
    for loc in ("fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id"):
        d = json.load(open(locales_dir / f"{loc}.json", encoding="utf-8"))
        assert d.get(key1), f"{loc}: missing translation for the renamed map header"
        assert d.get(key2), f"{loc}: missing translation for 'Concept (group)'"


def test_circle_grammar_level_marking_is_wired_and_contrast_verified():
    """GROUPS layer amendment §B: uniform level marking app-wide -- plain chip =
    keyword, ONE ring = a group, TWO rings = a super-group. Pins (a) the two
    theme-derived colour variables (color-mix off --accent/--fg -- never a
    hardcoded hue, the --caveat lesson) with contrast math clearing WCAG
    non-text-UI (>=3:1) on every one of the 17 themes' panel surfaces, (b) the
    box-shadow-only ring classes never touch padding/width/height (zero layout
    shift, invariant #3's discipline extended here), (c) the reusable JS
    primitives + the breadcrumb component, and (d) the class is actually
    attached at the identified group/super-group chip render sites."""
    import json
    import re

    css = (_SRC / "static" / "app.css").read_text(encoding="utf-8")
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")

    # (a) theme-derived variables, never a hardcoded hex hue.
    assert "--lvl-group:color-mix(in srgb, var(--accent)" in css.replace("\n", "")
    assert "--lvl-super:color-mix(in srgb, var(--accent)" in css.replace("\n", "")
    assert re.search(r"--lvl-group\s*:\s*#[0-9a-fA-F]{3,6}", css) is None, (
        "a hardcoded hex for --lvl-group would repeat the failed caveat-colour attempt"
    )
    assert re.search(r"--lvl-super\s*:\s*#[0-9a-fA-F]{3,6}", css) is None

    # (b) the ring classes are box-shadow-only -- no layout-affecting properties.
    for cls in ("lvl-group", "lvl-super"):
        m = re.search(r"\." + cls + r"\s*\{([^}]*)\}", css)
        assert m, f".{cls} rule must exist"
        body = m.group(1)
        assert "box-shadow" in body, f".{cls} must draw its ring via box-shadow"
        for forbidden in ("padding", "width:", "height:", "border-width", "margin"):
            assert forbidden not in body, (
                f".{cls} must never declare {forbidden!r} (zero layout shift)"
            )

    # (c) the JS primitives.
    assert "function lvlClass(level)" in js
    assert "function lvlTitle(level)" in js
    assert "function lvlBreadcrumb(segments)" in js
    assert "function _lvlCrumbFire(" in js
    assert '"lvl-super"' in js and '"lvl-group"' in js  # lvlClass actually maps both

    # (d) attached at the identified render call sites (family/super-group chips,
    # the keyword -> super-group navigation chip from the sibling S3 brief).
    assert 'class="pill lvl-group"' in js, "the family-panel group pill must carry .lvl-group"
    assert '"chip${isRing ? " lvl-group" : ""}"' in js or "chip${isRing ? \" lvl-group\" : \"\"}" in js, (
        "a group (ring) member chip in sgCard must carry .lvl-group"
    )
    assert '"fam-chip${isRing ? " lvl-group" : ""}"' in js or "fam-chip${isRing ? \" lvl-group\" : \"\"}" in js, (
        "a group (ring) member chip in sgCurationCard must carry .lvl-group"
    )
    assert 'class="lvl-super" title="${esc(lvlTitle("super"))}"' in js, (
        "a super-group's own name/header must carry .lvl-super"
    )
    assert '"chip tiny lvl-super"' in js, (
        "the keyword -> super-group navigation chip must carry .lvl-super"
    )

    # (e) the two new translated hover strings exist + are translated in all locales.
    key_group = "A group: one concept counted across every language it appears in."
    key_super = "A super-group: several groups gathered under one theme."
    assert key_group in js and key_super in js, "lvlTitle must call t() with the literal English strings"
    locales_dir = _SRC / "static" / "locales"
    en = json.load(open(locales_dir / "en.json", encoding="utf-8"))
    assert key_group in en and key_super in en
    for loc in ("fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id"):
        d = json.load(open(locales_dir / f"{loc}.json", encoding="utf-8"))
        assert d.get(key_group), f"{loc}: missing translation for the group-level hover"
        assert d.get(key_super), f"{loc}: missing translation for the super-group-level hover"

    # Contrast math (mirrors the #23 caveat-colour precedent): all 17 themes' own
    # --accent/--fg mixed the SAME way the CSS declares, checked against every
    # theme's --panel/--panel2/--panel3. Decorative box-shadow rings are governed
    # by WCAG 1.4.11 (non-text UI components, >=3:1) since the level information
    # itself is carried by the ring COUNT + the translated hover, never colour
    # alone (WCAG 1.4.1) -- so 3:1 is the applicable bar, verified with margin.
    themes = {
        "ink": ("#14181f", "#1b212b", "#232b38", "#e8ebf0", "#5b9dd9"),
        "slate": ("#161b23", "#1e2531", "#28323f", "#e8ebf0", "#7aa2f7"),
        "midnight": ("#10142e", "#171c3c", "#1f2650", "#e8eaff", "#8b7dff"),
        "terminal": ("#0a1013", "#0e1619", "#13211d", "#c8f7d4", "#36d97a"),
        "sepia": ("#262019", "#2f2820", "#3a3127", "#efe5d6", "#d8a657"),
        "contrast": ("#0a0a0a", "#161616", "#222222", "#ffffff", "#ffd400"),
        "light": ("#ffffff", "#f3f5f9", "#e7ecf3", "#1b1f27", "#2f6fb3"),
        "paper": ("#fbf8f1", "#f1ebdc", "#e6ddc8", "#2b271f", "#9a6a2f"),
        "arctic": ("#171c22", "#1e242c", "#262e38", "#e5e9f0", "#88c0d0"),
        "solar": ("#073642", "#0a4150", "#11505f", "#eee8d5", "#b58900"),
        "forest": ("#131a14", "#19231a", "#223024", "#e3ece2", "#6fbf73"),
        "aubergine": ("#1a1424", "#231b30", "#2e2440", "#ece6f4", "#c084fc"),
        "garnet": ("#1f1419", "#291a20", "#35222a", "#f0e6ea", "#d96c7f"),
        "cyber": ("#0d1120", "#131830", "#1a2140", "#dbe6ff", "#22d3ee"),
        "mist": ("#f9fafc", "#eff2f6", "#e3e8ef", "#222831", "#5e81ac"),
        "dawn": ("#fffaf3", "#f2e9e1", "#e9dfd5", "#575279", "#b4637a"),
        "mint": ("#f8fbf8", "#ecf2ed", "#dfe9e1", "#1f2a23", "#2e7d5b"),
    }
    assert len(themes) == 17

    def hx(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def mix(c1, c2, pct1):
        r1, g1, b1 = hx(c1)
        r2, g2, b2 = hx(c2)
        w = pct1 / 100.0
        return (r1 * w + r2 * (1 - w), g1 * w + g2 * (1 - w), b1 * w + b2 * (1 - w))

    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    def rel_lum(rgb):
        r, g, b = rgb
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    def contrast(rgb1, rgb2):
        l1, l2 = rel_lum(rgb1), rel_lum(rgb2)
        lighter, darker = max(l1, l2), min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)

    NONTEXT_MIN = 3.0
    worst = 999.0
    for name, (panel, panel2, panel3, fg, accent) in themes.items():
        group_rgb = mix(accent, fg, 75)
        super_rgb = mix(accent, fg, 35)
        for bg in (panel, panel2, panel3):
            bg_rgb = hx(bg)
            cg = contrast(group_rgb, bg_rgb)
            cs = contrast(super_rgb, bg_rgb)
            worst = min(worst, cg, cs)
            assert cg >= NONTEXT_MIN, f"{name}: --lvl-group contrast {cg:.2f} < {NONTEXT_MIN}:1"
            assert cs >= NONTEXT_MIN, f"{name}: --lvl-super contrast {cs:.2f} < {NONTEXT_MIN}:1"
    assert worst >= NONTEXT_MIN  # sanity: the loop above already asserted every case


def test_concept_map_two_tier_browse_and_clickable_countries():
    """GROUPS layer amendment §D: the flat 540-item <select> is replaced by a
    two-tier circled browse (super-group chips -> click one -> its group chips,
    plus an Ungrouped-concepts bucket so no ring is ever unreachable) with a
    type-ahead filter; every country row/polygon AND the "not mapped" bucket
    drill into the exact corpus (never a dead end); every ⦾ group chip in the
    app deep-links to this map via openConceptMap."""
    import json

    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")

    # The old flat dropdown is GONE; the new two-tier browse scaffolding is present.
    assert 'id="sg-ringmap-pick"' not in html, "the flat 540-item dropdown must be removed"
    for el_id in ("sg-concept-filter", "sg-concept-crumb", "sg-concept-supers", "sg-concept-groups"):
        assert f'id="{el_id}"' in html, f"the concept-map two-tier browse must render #{el_id}"

    # The JS primitives.
    for fn in (
        "function renderConceptBrowse(",
        "function selectConceptBucket(",
        "function selectConceptGroup(",
        "function filterConceptBrowse(",
        "function openConceptMap(",
        "function _conceptApplyPending(",
        "async function _conceptDrillCountry(",
    ):
        assert fn in js, f"missing concept-map browse primitive: {fn!r}"

    # An "Ungrouped concepts" bucket so a ring with no super-group parent is
    # never silently unreachable from the picker.
    assert "_ungrouped_" in js
    assert "Ungrouped concepts" in js

    # Clickable countries: the ooMap polygon drill, the table-row drill, and the
    # "not mapped" bucket drill all resolve through the SAME shared function.
    assert "onCountry: (iso) => _conceptDrillCountry(ringId, iso)" in js
    assert '<tr style="cursor:pointer" onclick="_conceptDrillCountry(' in js
    assert 'onclick="_conceptDrillCountry(\'${esc(ringId)}\', null)"' in js, (
        "the not-mapped/unlocated bucket must be a clickable drill, never a dead-end div"
    )
    assert "/api/insights/ring-country-articles" in js
    assert "openAnalysisForIds(d.article_ids" in js

    # Every ⦾ group chip in the app deep-links to the map (openConceptMap), at
    # each identified render site: the family-panel pill, the sgCard chip's map
    # link, and the sgCurationCard chip's map link.
    assert 'onclick="openConceptMap(${esc(JSON.stringify(f.ring_id))})"' in js
    assert js.count('onclick="openConceptMap(${esc(JSON.stringify(m.ring_id))})"') >= 2, (
        "both sgCard and sgCurationCard ring-member chips must offer the map deep-link"
    )

    # The located-share honesty line (map coverage grows as source countries are
    # filled in -- an unlocated share is a gap, never a claim nobody covers a
    # concept), a NEW key so it never orphans a translation, present + translated
    # everywhere.
    key = (
        "Map coverage grows as more sources get a known country — an unlocated "
        "share is a data gap, never a claim that nobody covers a concept."
    )
    assert key in html
    locales_dir = _SRC / "static" / "locales"
    en = json.load(open(locales_dir / "en.json", encoding="utf-8"))
    assert key in en
    for loc in ("fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id"):
        d = json.load(open(locales_dir / f"{loc}.json", encoding="utf-8"))
        assert d.get(key), f"{loc}: missing translation for the map-coverage honesty line"


def test_task_manager_opens_in_a_standalone_tab():
    """The task manager opens in its OWN browser tab (maintainer 2026-06-18) so it
    can stay parked on the desktop while the user works in the app. Pinned: the
    #tm-open button calls openTaskManager() (window.open the /tasks page), the
    /tasks route serves the standalone page, and that page is a read+control view
    over the EXISTING job/scheduler/system APIs. It may ENGAGE airplane (the safe
    direction) but never goes ONLINE itself (P2-12: consent lives in the app)."""
    html = _ui_source()  # index.html + app.js + app.css
    assert 'onclick="openTaskManager()"' in html, "#tm-open must open the standalone task tab"
    assert "function openTaskManager(" in html and 'window.open("/tasks"' in html, (
        "openTaskManager must window.open the /tasks page (a named target stays in place)"
    )
    main_src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    assert '"/tasks"' in main_src and "taskmanager.html" in main_src, (
        "the /tasks route must serve the standalone taskmanager.html"
    )
    tm = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    for ep in ("/api/jobs", "/api/scheduler/activity", "/api/system/vitals"):
        assert ep in tm, f"the task page must read the existing {ep} endpoint (no new backend)"
    # The status-bar airplane control may engage airplane (offline = the SAFE
    # direction, no socket opens) but must NEVER cross ONLINE without the app's consent.
    assert "online: true" not in tm, "the task page must never go online (consent lives in the app)"
    for pid in ('id="jobs-body"', 'id="queue-body"', 'id="sched-body"', 'id="vitals-body"'):
        assert pid in tm, f"task panel missing: {pid}"


def test_task_manager_shows_pass_phase_and_upcoming_sources():
    """The task manager must show WHAT a pass is doing, not a bare 'idle'
    (maintainer 2026-06-18: "the task manager fails to show what the app is doing").
    Two surfaces, on BOTH the standalone /tasks page and the in-app app.js:
      * when a pass is ACTIVE but past the per-source scrape (progress cleared),
        the System view shows the honest PHASE (collecting / background / briefing),
        read from /api/scheduler/activity — never 'idle';
      * the Queue shows a read-only 'Up next this pass' preview of the collection
        order, with the honest 'order is re-randomised every pass' caveat (it is NOT
        a fixed reorderable queue — that distinction was the user's confusion)."""
    import json as _json

    tm = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    app = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    for src, name in ((tm, "taskmanager.html"), (app, "app.js")):
        # Phase mapping keyed off a.phase, gated on a.active (not a bare 'idle').
        assert "a.phase" in src, f"{name}: must read the pass phase from activity"
        assert "Background tasks (markets · calendars · checks)" in src, (
            f"{name}: must label the post-scrape background phase honestly"
        )
        assert "a.active" in src, f"{name}: the phase line must be gated on an active pass"
        # Read-only upcoming-sources preview + the not-a-fixed-queue caveat.
        assert "Up next this pass" in src, f"{name}: Queue must preview the upcoming sources"
        assert "Order is re-randomised every pass" in src, (
            f"{name}: the upcoming preview must carry the not-a-fixed-queue caveat"
        )
    # Both surfaces reuse the plan the activity poll ALREADY fetched (no new poll).
    assert "window._act" in tm and "plan.next_targets" in tm
    assert "_actData" in app and "plan.next_targets" in app
    # The new strings are keyed in en.json so they translate ×12 (gate stays 100%).
    en = _json.loads((_ROOT / "src" / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    for key in (
        "Collecting articles",
        "Background tasks (markets · calendars · checks)",
        "Building the briefing",
        "Up next this pass",
        "Order is re-randomised every pass — stratified by language and tag, not a fixed queue.",
    ):
        assert key in en, f"missing i18n key: {key!r}"


def test_task_manager_displays_actual_language_and_tag_strata():
    """Field test 2026-06-22 (#5): the queue preview must DISPLAY the actual strata it
    interleaves by (the languages + tags present, with real counts), not just claim
    'stratified by language and tag'. Both surfaces read plan.strata (derived cheaply
    from the bounded sample plan_preview already fetched — no new unbounded scan on the
    hot poll). The backend plan_preview must emit the strata."""
    tm = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    app = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    for src, name in ((tm, "taskmanager.html"), (app, "app.js")):
        assert "plan.strata" in src, f"{name}: must read the actual strata from the plan"
        assert 'st.languages' in src and 'st.tags' in src, (
            f"{name}: must render BOTH language and tag strata"
        )
    runner = (_SRC / "scheduler" / "runner.py").read_text(encoding="utf-8")
    # plan_preview emits the strata, derived from the already-fetched bounded sample
    # (no unbounded DISTINCT scan on the hot /api/scheduler/activity poll).
    assert '"strata": strata' in runner, "plan_preview must return the strata"
    assert "_source_lang" in runner and "_source_tag" in runner, (
        "strata must reuse the SAME bucketing stratified_interleave uses"
    )
    # The strata are counted from the already-fetched `rows` sample (no new query on the
    # hot poll) — the loop runs over rows, not a fresh DB call.
    plan_preview_body = runner.split("def plan_preview", 1)[1].split("\ndef ", 1)[0]
    assert "for r in rows:" in plan_preview_body and "lang_n[_source_lang(r)]" in plan_preview_body


def test_sidebar_is_a_flat_list_without_section_headers():
    """Field test 2026-06-22 (#22 flatten + #17 remove sidebar-visibility): the sidebar
    is ONE flat list — the Investigate/Collect/Trust section headers (.gl labels +
    .nav-group wrappers) are gone, and the 'Tools shown in the sidebar' checklist +
    the hide-a-tab feature are removed. Every tab stays present + reachable (invariant
    #2: lists all tabs)."""
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    app = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    nav = html.split('id="navGroups"', 1)[1].split("</nav>", 1)[0]
    # No section-header markup left in the live nav (comments may mention them).
    assert '<div class="gl">' not in nav and '<div class="nav-group"' not in nav, (
        "the sidebar must be a flat list — no .gl headers / .nav-group wrappers"
    )
    assert 'class="nav-groups flat"' in html, "the nav must carry the flat marker"
    # All the core tabs are still there (nothing lost by the flatten).
    for tab in ("home", "insights", "timemap", "law", "agenda", "indices", "markets", "library"):
        assert f'data-tab="{tab}"' in nav, f"flat sidebar lost the {tab} tab"
    # The sidebar-visibility feature is gone (checklist host + toggle fn + persistence).
    # (Checked via the removed identifiers, not the human label — an explanatory comment
    # may still NAME the removed feature.)
    assert 'id="dr-modules"' not in html, "the 'Tools shown in the sidebar' checklist must be removed"
    assert "toggleModule" not in app, "the hide-a-tab toggle must be removed"
    # The collapse-to-rail control STAYS (that is a different feature, invariant #2).
    assert "toggleSidebar" in app and 'id="sb-collapse"' in html


def test_world_law_renamed_governments_with_subtabs():
    """Maintainer chat 2026-06-22: World Law -> Governments, diversified into subtabs
    (Countries · Map · Law). The tab id stays "law" (the code anchor, timemap precedent);
    the LABEL is "Governments" (keyed x12). The existing law tracker is preserved as the
    Law subtab (Desk lesson — nothing lost); the Map subtab reuses ooMap fed by the
    per-country stats endpoint."""
    import json as _json

    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    app = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    # Nav relabelled (anchor stays data-tab="law").
    assert '<span>Governments</span>' in html and 'data-tab="law"' in html
    # The 3 subtabs + their panes.
    nav = html.split('id="gov-subtabs"', 1)[1].split("</nav>", 1)[0]
    for sub in ("countries", "map", "law"):
        assert f'data-tab="{sub}"' in nav, f"Governments missing the {sub} subtab"
    for pane in ("gov-countries", "gov-map", "gov-law"):
        assert f'id="{pane}"' in html, f"missing pane {pane}"
    # The existing law tracker is PRESERVED inside the Law subtab (Desk lesson).
    assert 'id="law-status"' in html and 'id="law-changes"' in html and 'id="law-docs"' in html
    # JS wiring: subtabs + the three loaders + the consented load + the map reuses ooMap.
    assert "function loadGovernments" in app and "function showGovView" in app
    assert "function loadGovCountry" in app and "function loadGovMap" in app
    assert "govLoadStandard" in app and "ensureOnline" in app  # the ONE consent on the fetch
    assert "/api/governments/" in app and "await ooMap(" in app  # the map reuses ooMap
    # The label is keyed x12 (gate stays 100%).
    en = _json.loads((_ROOT / "src" / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    assert en.get("Governments") == "Governments"


def test_custody_dissolved_from_sidebar_but_reachable_from_settings():
    """Field test 2026-06-22 (#20): Evidence & custody is an ACTION on content, so it
    leaves the sidebar (completing the Trust-group dissolution) and moves to Settings →
    Safety — but the Desk lesson holds: the page + tools stay, reachable from Settings
    (a showTab('custody') button) and the command palette (custody is in NAV)."""
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    app = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    nav = html.split('id="navGroups"', 1)[1].split("</nav>", 1)[0]
    assert 'data-tab="custody"' not in nav, "the custody sidebar button must be removed"
    # Reachable from Settings → Safety + preserved (the page + the save action stay).
    assert "showTab('custody')" in html, "Settings → Safety must carry a custody entry point"
    assert 'id="tab-custody"' in html, "the custody tab-page must be preserved (Desk lesson)"
    assert "saveCustody" in app, "the custody controls must be preserved"
    # Still palette-reachable (NAV keeps the entry).
    assert '{id:"custody"' in app, "custody must stay registered in NAV for the palette/deep-links"


def test_sources_have_multi_select_dropdown_filters():
    """Field test 2026-06-22 (#23): the Settings → Sources filters are multi-select
    DROPDOWNS fed by a facets endpoint (Language/Country/Type/Tags), with a tag any|all
    toggle and the free-text title search kept. Backend: a cheap facets endpoint + the
    list endpoints accept comma-separated OR-within multi-values."""
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    app = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    # The four multi-select <details> dropdowns + the tag any/all toggle + kept search.
    for el in ("src-msel-language", "src-msel-country", "src-msel-source_type", "src-msel-tag"):
        assert f'id="{el}"' in html, f"missing multi-select dropdown {el}"
    assert 'id="src-tag-all"' in html, "tags need an any|all toggle"
    assert 'id="src-search"' in html, "the free-text title search must be kept"
    # Frontend reads the facets + builds comma-separated OR-within params.
    assert "loadSrcFacets" in app and "/api/sources/facets" in app
    assert "mselValues" in app and 'p.set("tag_mode", "all")' in app
    # Localized full names on the language/country option labels (#19).
    assert "ooLangName" in app and "ooRegionName" in app
    # Backends: the facets endpoint + multi-value filtering on both list endpoints.
    sm = (_SRC / "api" / "source_management.py").read_text(encoding="utf-8")
    assert '@router.get("/facets"' in sm, "a /api/sources/facets endpoint must exist"
    sio = (_SRC / "api" / "source_io.py").read_text(encoding="utf-8")
    assert "tag_mode" in sio and ".in_(" in sio, "catalog/sources must support OR-within multi-values"


def test_airplane_button_has_no_perpetual_animation():
    """Airplane mode is the idle/default state, so a forever-running animation on
    the network button repaints every frame at rest — it pinned the browser near
    40% CPU (field report 2026-06-18; animated box-shadow is a WebKit repaint hog).
    The offline state must be shown statically (colour + a painted-once ring + the
    plane glyph FILL, invariant #14), never an infinite animation."""
    css = (_ROOT / "src" / "static" / "app.css").read_text(encoding="utf-8")
    assert "@keyframes netpulse" not in css, "the perpetual airplane-button pulse must be gone"
    # The #net-toggle.off rule must not start an animation (find its declaration block).
    import re

    m = re.search(r"#net-toggle\.off\s*\{([^}]*)\}", css)
    assert m, "missing #net-toggle.off rule"
    assert "animation" not in m.group(1), "#net-toggle.off must not run a perpetual animation"
    assert "var(--err)" in m.group(1), "offline state must still be shown (red colour/ring)"


def test_task_manager_redesign_windows_style():
    """The standalone task manager is a Windows-Task-Manager-style window
    (maintainer 2026-06-18): a persistent resource summary + Processes /
    Performance / Queue / Schedule / History tabs, airplane-aware, showing what
    actually runs (incl. LLM/analysis tasks) with live hardware charts."""
    tm = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    # The five tabs + their panels.
    for panel in ("processes", "performance", "queue", "schedule", "history"):
        assert f'data-panel="{panel}"' in tm, f"missing tab: {panel}"
        assert f'id="p-{panel}"' in tm, f"missing panel: p-{panel}"
    # Persistent resource summary strip (state + CPU/RAM/↓/jobs).
    assert 'id="tm-summary"' in tm and "renderSummary" in tm
    # Processes are grouped like Windows (apps / background / services).
    assert '"AI & analysis"' in tm and "renderProcesses" in tm
    # Background LLM/analysis tasks are surfaced (the "is an LLM translating?" view).
    assert '"llm"' in tm and '"analytics"' in tm
    # Performance tab draws live hardware charts from a rolling buffer.
    assert "renderPerformance" in tm and "sparkSvg" in tm and "Disk I/O" in tm
    # History tab reads the run log; airplane mode is honest in the schedule.
    assert "/api/jobs/history" in tm and "renderHistory" in tm
    assert "a.online === false" in tm and "paused — airplane mode" in tm
    # The status-bar airplane control (P2-12) may ENGAGE airplane (the safe
    # direction, no consent), but must NEVER go ONLINE from the task page —
    # crossing online requires the app's ONE consent popup, so offline routes to "/".
    assert 'JSON.stringify({ online: false })' in tm, "the task page may engage airplane (safe)"
    assert "online: true" not in tm, "the task page must NEVER go online without the app's consent"
    assert 'location.href = "/"' in tm, "going online must route back to the app (consent lives there)"

    # The backend surfaces background tasks + a history endpoint.
    jobs_src = (_ROOT / "src" / "api" / "jobs.py").read_text(encoding="utf-8")
    assert "_task_jobs" in jobs_src and "src.monitoring.tasks" in jobs_src
    assert '"/history"' in jobs_src and "recent_runs" in jobs_src
    # The LLM + AI endpoints register a visible task.
    llm_src = (_ROOT / "src" / "api" / "llm.py").read_text(encoding="utf-8")
    ai_src = (_ROOT / "src" / "api" / "ai.py").read_text(encoding="utf-8")
    assert "monitoring.tasks" in llm_src or "monitoring import tasks" in llm_src
    assert "monitoring import tasks" in ai_src or "monitoring.tasks" in ai_src


def test_task_manager_status_bar_and_sessions(monkeypatch=None):
    """Field test 2026-06-19 P2-12: the standalone task page gains the SPA's
    top-bar controls MINUS search — a status bar with airplane + a language
    picker + help; the Up-next list is a full vertical list; History is reframed
    as 'online sessions'; Performance adapts to window size (auto-fit grid)."""
    tm = (_ROOT / "src" / "static" / "taskmanager.html").read_text(encoding="utf-8")
    # Status bar: now IDENTICAL to the app's top bar (maintainer 2026-06-20) — the same
    # header.topbar markup (omni search + health/LLM pills + airplane + language flag + help).
    assert 'id="tm-status"' in tm, "the status bar must exist"
    assert 'class="topbar"' in tm and 'class="omni"' in tm, "the app's top-bar markup is reused"
    assert 'id="net-toggle"' in tm and "function paintAir()" in tm, "the airplane control must exist"
    assert 'id="lang-switch"' in tm and 'id="lang-menu"' in tm and "TM_LANGS" in tm, "the app's language flag menu"
    assert 'id="health"' in tm and 'id="llm"' in tm, "the health + LLM pills mirror the app"
    assert 'id="tm-help"' in tm, "a help affordance must exist (minus search)"
    # Up-next is a full vertical list (not a chip cloud)
    assert '<ol class="tm-upnext">' in tm, "Up-next must render as a full vertical list"
    # History reframed as online sessions
    assert 'data-panel="history" role="tab" data-i18n>Sessions' in tm, "the History tab is reframed as Sessions"
    assert 'esc(t("Online sessions"))' in tm, "the panel heading is 'Online sessions'"
    # Performance grid adapts to window size
    assert "repeat(auto-fit, minmax(220px, 1fr))" in tm, "the performance grid must be responsive"


def test_startup_seeds_the_source_catalog_at_unlock():
    """Data collection is the heart of the project, so the app MUST come up with
    its source catalog. An ENCRYPTED store (the default) is unlocked via the web,
    which runs run_deferred_startup — NOT main(); main() runs while the store is
    still locked, so its seed call never reaches an encrypted catalog. Field log
    2026-06-18 caught exactly this: an encrypted install came up with ~1 source
    and nothing to scrape. Guard that run_deferred_startup seeds sources."""
    main_src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    # run_deferred_startup now delegates the post-init upkeep to _run_startup_upkeep
    # (so the web-unlock path can background it); the seed lives there. Read both.
    deferred = main_src.split("def run_deferred_startup", 1)[1].split("\ndef test_", 1)[0]
    assert "_run_startup_upkeep" in deferred, "run_deferred_startup must call the upkeep"
    assert "seed_default_sources" in deferred, (
        "run_deferred_startup must seed the source catalog (encrypted stores seed at "
        "unlock, not in main()) — otherwise an encrypted install has nothing to collect"
    )


def test_startup_warms_the_insights_cache():
    """Boot-cold fix (field test 2026-06-22, §1.3): the in-memory insights read cache
    is empty after a restart, so without a boot warm the first Home/Insights open pays
    the cold whole-corpus aggregation (warm_cache runs after a scrape pass, but boot is
    airplane mode -> no pass). run_deferred_startup must kick warm_cache in a background
    (non-blocking) thread, gated by OO_NO_SCHEDULER so tests/headless skip it."""
    main_src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    # The cache warm lives in _run_startup_upkeep (called by run_deferred_startup); the
    # slice below spans both functions up to the next test-visible boundary.
    deferred = main_src.split("def run_deferred_startup", 1)[1].split("\n@asynccontextmanager", 1)[0]
    assert "warm_cache" in deferred, "run_deferred_startup must warm the insights cache at boot"
    # It must be backgrounded (a daemon Thread), never run inline (would block startup).
    assert "Thread(" in deferred and "daemon=True" in deferred, (
        "the boot cache warm must run in a daemon thread so it never blocks startup"
    )


def test_no_app_function_calls_i18n_t_without_binding_it():
    """Recurring bug class (Library tag-click; the analysis keyword subtab; Governments
    + Trends): a function calls the i18n helper t("…") but never binds a local
    `const t = …`, so it throws "t is not defined" at runtime. There is no module-level
    `t` — every function must alias it. Scan app.js for the pattern and fail on any
    function that calls t("…") without binding t (as a const/let/var or a parameter),
    excluding the legitimate `terms.map(t => …)` loop-variable use."""
    import re

    src = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    lines = src.split("\n")
    func_re = re.compile(r"^\s*(async\s+)?function\s+(\w+)\s*\(([^)]*)\)")
    offenders: list[str] = []
    i = 0
    while i < len(lines):
        m = func_re.match(lines[i])
        if not m:
            i += 1
            continue
        name, params = m.group(2), m.group(3)
        depth, body, j, started = 0, [], i, False
        while j < len(lines):
            depth += lines[j].count("{") - lines[j].count("}")
            body.append(lines[j])
            if "{" in lines[j]:
                started = True
            if started and depth <= 0:
                break
            j += 1
        text = "\n".join(body)
        calls_t = re.search(r"[^\w.]t\((?![\s]*\))[\"'`]", text)  # an i18n call t("…")
        binds_t = re.search(r"\b(const|let|var)\s+t\s*=", text) or re.search(r"\bt\b", params)
        loopvar = re.search(r"\(\s*t\s*=>", text) or re.search(r"\bfor\b.*\bt\b", text)
        if calls_t and not binds_t and not loopvar:
            offenders.append(f"{name} (line {i + 1})")
        i = j + 1
    assert not offenders, (
        "these app.js functions call i18n t(\"…\") without binding a local t "
        "(will throw 't is not defined'): " + ", ".join(offenders)
    )


def test_keyword_filter_shows_the_builtin_stoplist():
    """Field ask 2026-07-02: the Settings keyword filtering should let users SHOW the
    current filter-out list. The manual excluded list was already editable, but the
    bulk of the filtering is the built-in multilingual stoplist, which was invisible
    (only a toggle). Guard the read-only searchable view of it: the endpoint that
    returns the built-in stoplist, the Settings panel that shows it, and the loader."""
    ins = (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    assert '"/filter/builtin"' in ins and "global_stopwords" in ins, (
        "an endpoint must expose the built-in stoplist (read-only) for display"
    )
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="kf-builtin-view"' in html and 'id="kf-builtin-q"' in html, (
        "the keyword-filtering panel must show a searchable built-in-stoplist view"
    )
    app = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")
    assert "loadBuiltinStoplist" in app and "/api/insights/filter/builtin" in app


def test_unlock_enters_when_queryable_not_after_full_upkeep():
    """Field report 2026-07-02 ("unlocking takes ages", CPU ~12% / SSD idle): the
    unlock page waited for startup-status == "ready", but "ready" is only set AFTER
    the whole serial best-effort upkeep (ANALYZE, catalog seed-dedup, COUNTs, cache
    warm) finishes on a large encrypted corpus. The corpus is fully usable the instant
    init_db returns, so unlock must mark the corpus `queryable` right after init_db and
    the page must enter the Console on `queryable` — the upkeep finishes in the
    background. Guard all three legs so the slow gate can't come back."""
    ss = (_ROOT / "src" / "api" / "startup_status.py").read_text(encoding="utf-8")
    assert "def mark_queryable" in ss and '"queryable"' in ss, (
        "startup_status must expose a `queryable` signal set once the DB is usable"
    )
    unlock = (_ROOT / "src" / "api" / "unlock.py").read_text(encoding="utf-8")
    finish = unlock.split("def _finish_unlock", 1)[1].split("\ndef unlock", 1)[0]
    # mark_queryable must be called AFTER init_db (the DB is usable) and BEFORE the
    # background upkeep thread starts — i.e. it gates entry on init_db, not upkeep.
    assert "init_db()" in finish and "mark_queryable()" in finish, (
        "unlock must run init_db synchronously then mark the corpus queryable"
    )
    assert (
        finish.index("init_db()")
        < finish.index("mark_queryable()")
        < finish.index("def _upkeep")
    ), "mark_queryable must be called after init_db and before the background upkeep thread"
    html = (_ROOT / "src" / "static" / "unlock.html").read_text(encoding="utf-8")
    enter = html.split("async function waitReadyThenEnter", 1)[1].split("async function", 1)[0]
    assert "s.queryable" in enter, (
        "the unlock page must enter the Console as soon as the corpus is queryable, "
        "not only when the whole upkeep reports ready"
    )


def test_unlock_error_reshows_the_form_and_is_translated():
    """GUI-test finding LC-VIEW-HIDDEN-ON-ERROR (P0) + LC-ERROR-TEXT-UNTRANSLATED
    (P2, bonus, unmasked by the P0 fix): go(btn, fn) -- shared by #btn-unlock and
    #btn-create -- called _startPrep(), which unconditionally hid
    view-unlock/view-create/view-open and showed view-preparing BEFORE fn()
    resolved. On a thrown error the catch block wrote the message into the msg box
    and hid view-preparing again, but never re-showed whichever view _startPrep()
    had hidden -- the whole form (with the error trapped inside it) stayed
    invisible, leaving a blank page (confirmed live: document.body.innerText was
    empty after a too-short-passphrase submit). _startPrep now takes the caller's
    priorView (inferable from btn.id, which go() already has) and remembers it in
    _prepPriorView; the catch block re-shows that exact view. The error text
    itself (the backend's raw HTTPException detail -- "use at least 8 characters" /
    "passphrases do not match") is also now run through t() instead of assigned
    verbatim, so it renders in the user's chosen language like every other string
    on this page."""
    unlock = (_ROOT / "src" / "static" / "unlock.html").read_text(encoding="utf-8")

    prep = unlock.split("function _startPrep(", 1)[1].split("\n    }\n", 1)[0]
    assert prep.startswith("priorView) {"), (
        "_startPrep must accept the caller's priorView so it can be restored later"
    )
    assert "_prepPriorView = priorView || null;" in prep, (
        "_startPrep must remember which view was active before hiding it"
    )

    go_fn = unlock.split("async function go(btn, fn) {", 1)[1].split("\n      }\n", 1)[0]
    assert (
        '_startPrep(btn.id === "btn-unlock" ? "view-unlock" : "view-create");' in go_fn
    ), "go() must tell _startPrep which view is being hidden (inferred from btn.id)"

    catch_block = go_fn.split("catch (e) {", 1)[1]
    assert '$("view-preparing").classList.add("hidden");' in catch_block, (
        "the catch block must still hide the preparing view on failure"
    )
    hide_idx = catch_block.index('$("view-preparing").classList.add("hidden");')
    reshow = 'if (_prepPriorView) $(_prepPriorView).classList.remove("hidden");'
    assert reshow in catch_block, (
        "the catch block must re-show whichever view _startPrep() hid, or the form "
        "(and the error message inside it) stays invisible forever"
    )
    assert catch_block.index(reshow) > hide_idx, (
        "the prior view must be re-shown AFTER view-preparing is hidden, not before"
    )
    assert 'box.textContent = e.message ? t(e.message) : t(' in catch_block, (
        "the backend's raw error detail must be run through t() so it translates "
        "(bare `e.message ||` left it hardcoded English regardless of locale)"
    )

    # The two backend HTTPException details (src/api/unlock.py: "use at least 8
    # characters", "passphrases do not match") must be keyable -- present, and
    # actually translated (not just echoed back as English), in every locale.
    import json

    for code in (
        "ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh",
    ):
        data = json.loads((_SRC / "static" / "locales" / f"{code}.json").read_text(encoding="utf-8"))
        for key in ("use at least 8 characters", "passphrases do not match"):
            assert key in data and data[key], f"{code}.json is missing a translation for {key!r}"
            if code != "en":
                assert data[key] != key, f"{code}.json left {key!r} untranslated (verbatim English)"


def test_llm_catalog_tags_are_pullable_and_embeddings_labelled():
    """Every suggested model must be PULLABLE — its tag has to satisfy the same
    strict regex the /api/llm/pull endpoint enforces (src/api/llm.py:_MODEL_RE), so
    a catalog entry can never 400 when the user clicks Pull. Embedding models, which
    the summarize/translate/synthesize features cannot use, must be labelled
    kind="embedding" so the picker says so honestly (maintainer 2026-06-18). Read via
    AST so this runs without the optional httpx/LLM dependency."""
    import ast
    import re as _re

    src = (_ROOT / "src" / "llm" / "ollama.py").read_text(encoding="utf-8")
    catalog = None
    for node in ast.walk(ast.parse(src)):
        tgt = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            tgt = node.target.id
        elif isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            tgt = node.targets[0].id
        if tgt == "MODEL_CATALOG":
            catalog = ast.literal_eval(node.value)
    assert catalog, "MODEL_CATALOG must be a non-empty list"
    # the exact regex from src/api/llm.py (kept in sync; pinned here so a drift fails)
    pull_re = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    for m in catalog:
        assert pull_re.match(m["tag"]), f"catalog tag is not pullable: {m['tag']!r}"
        assert m.get("note"), f"catalog entry missing a note: {m['tag']!r}"
    # the embedding models we ship are labelled; nothing else is mislabelled
    embeds = {m["tag"] for m in catalog if m.get("kind") == "embedding"}
    assert {"bge-m3", "embeddinggemma", "nomic-embed-text-v2-moe"} <= embeds, (
        "the shipped embedding models must carry kind='embedding'"
    )
    assert "llama3.2:3b" not in embeds, "a text model must never be labelled embedding"


def test_keyword_views_show_verified_translations():
    """Language-aware keyword views (maintainer ruling 2026-06-19): don't blind the
    reader to foreign keywords — show each one WITH its verified cross-language
    translation into the UI language. Browser-unverified; this pins the wiring."""
    html = _ui_source()
    # The translation helper + UI-language target param exist and are used.
    for marker in ("function kwTransHtml(", "tgtLangParam(", "function uiLangCode(", "kw-trans"):
        assert marker in html, f"missing translation wiring: {marker}"
    # termListHtml renders the translation beside the keyword.
    assert "${kwTransHtml(t)}" in html, "termListHtml must render the verified translation"
    # The three keyword fetches request the verified translation for the UI language.
    assert "/api/insights/trending-windows?limit=6&series_top=6\" + tgtLangParam()" in html
    assert "/api/insights/trending-windows?limit=4&series_top=4\" + tgtLangParam()" in html
    assert "tgtLangParam()}${extra||\"\"}" in html, "the Trends top/rising fetch must pass target_lang"
    # It is a TRANSLATION (additive), not a filter that hides languages.
    assert "kwLangParam" not in html, "the rejected blind-by-language filter must not be present"


def test_translations_extend_to_analysis_window_and_supergroups():
    """Phase 3 (maintainer ruling: translations bind to families AND groups): the
    verified translation is shown in the analysis-window Keywords subtab and on
    super-group ring members too, not only the Trends/Home lists."""
    html = _ui_source()
    # Analysis-window Keywords subtab: corpus-keywords fetch carries target_lang and
    # each chip renders the translation.
    assert 'corpus-keywords?" + p.toString() + tgtLangParam()' in html, (
        "the analysis-window Keywords fetch must request the verified translation"
    )
    # Super-groups: the list fetch passes target_lang and ring members show the translation
    # (the S1.5 series_top/window_days params were added additively before it).
    assert 'target_lang=" + encodeURIComponent(uiLangCode())' in html and (
        "/api/insights/supergroups?series_top=" in html
    ), "the super-groups fetch must request the verified translation"
    # "ring" is the internal name only (GROUPS layer amendment §A) -- the pill now
    # reads "group·N" in the user-visible UI.
    assert "group·${(m.ring_members || []).length}" in html and "${kwTransHtml(m)}" in html, (
        "a super-group group member must render its verified translation"
    )


def test_tentative_llm_keyword_translation_is_wired_and_flagged():
    """Phase 4 (Wikidata rings + LLM fallback): keywords no verified ring covers get a
    TENTATIVE local-LLM translation, shown ONLY when there's no verified one, with a
    distinct ≈ marker + an 'unreliable, not verified' flag — an explicit action, never
    auto. Browser-unverified; this pins the wiring + the honesty surface."""
    html = _ui_source()
    for marker in ("function kwTentativeHtml(", "function anFillTentative(",
                   "/api/ai/translate-keywords", "kw-tentative", "anRenderKwChips("):
        assert marker in html, f"missing tentative-translation wiring: {marker}"
    # tentative shows ONLY when there is no verified translation, and is flagged unreliable.
    assert "if (!row || row.translation || !row.tentative) return" in html, (
        "the tentative translation must never override a verified one"
    )
    assert "AI-generated tentative translation — unreliable, not verified." in html
    # explicit, gated action (the button only appears when something needs it).
    assert "Translate the rest (AI, tentative)" in html and "d.terms.some(_anKwNeedsTentative)" in html


def test_auto_index_insights_is_throttled_not_a_per_tick_storm():
    """P0-5 (field test 2026-06-22): the Insights status poll (every 6 s) re-kicked a
    fresh re-index drain on every tick — /api/insights/reindex was called 1,326×/369 s,
    each batch a heavy write contending with the live scrape. autoIndexInsights now runs
    ONE bounded pass (<=40 batches, not the old 500) then cools down, and stops on a
    genuinely stuck backlog — so the 6 s poll can no longer storm the writer."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # The function gained a cooldown gate so a poll within the window is a no-op.
    assert "_autoIndexCooldownUntil" in app, "auto-index lost its cooldown throttle"
    assert "if (Date.now() < _autoIndexCooldownUntil) return;" in app, (
        "the 6 s poll can still re-kick a fresh drain every tick"
    )
    # Each pass is bounded to a sane batch count, never the old 150k-article blast.
    assert "++guard >= 40" in app, "the per-pass batch bound regressed"
    assert "++guard > 500)" not in app, "the old 500-batch (150k-article) blast is back"
    # A stuck backlog must stop re-attempting (Infinity cooldown), not hammer forever.
    assert "_autoIndexCooldownUntil = Infinity" in app


def test_warm_cache_keys_match_the_trending_windows_requests():
    """P0-4 (field test 2026-06-22): warm_cache must warm the EXACT (limit, series_top)
    shapes the UI requests for /api/insights/trending-windows, or the warm value is
    never a cache hit and the user pays the cold heavy query. This guards against the
    silent drift that caused it (the old warm key used limit=10, which NOTHING asked
    for). Every trending-windows request shape in app.js must be a warmed constant."""
    import re

    from src.api.insights import WARM_TRENDING_HOME, WARM_TRENDING_INSIGHTS

    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    shapes = set()
    for m in re.finditer(r"/api/insights/trending-windows\?limit=(\d+)&series_top=(\d+)", app):
        shapes.add((int(m.group(1)), int(m.group(2))))
    assert shapes, "no trending-windows request found in app.js (pattern moved?)"
    warmed = {tuple(WARM_TRENDING_HOME), tuple(WARM_TRENDING_INSIGHTS)}
    missing = shapes - warmed
    assert not missing, (
        f"app.js requests trending-windows shapes {missing} that warm_cache does NOT "
        f"warm (warmed={warmed}); align WARM_TRENDING_* or the user pays the cold query"
    )


def test_auto_update_note_removed_and_country_names_localized():
    """Field test 2026-06-22 #15 (the standalone "Updates automatically in the
    background." board notes are redundant -> removed) + #19 (displayed country
    NAMES are localized via the CLDR helper ooRegionName, superseding the old
    "codes stay" — the flag-emoji/anchors/provenance correctly keep the code)."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    assert "Updates automatically in the background." not in html, (
        "the redundant auto-update note is back (#15)"
    )
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # The source-profile "Country:" fact + the map-mention readout show the localized
    # name, not the raw uppercased 2-letter code.
    assert 'ooRegionName(meta.country, meta.country.toUpperCase())' in app
    assert 'ooRegionName(m.country, m.country)' in app


def test_server_side_folder_picker_wired():
    """Field test 2026-06-22 #8: "Browse buttons, never manual path typing". A
    traversal-safe /api/fs/list backs a folder picker wired into the folder-backup
    destination + the .eml folder-import path inputs (folders only, never file names)."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # Browse buttons on the server-side path inputs + the picker dialog. The
    # standalone folder-backup destination was folded into the unified Export/Import
    # dialog (2026-07-01): ux-dest = the export destination, ux-imp-src = the import
    # source folder; nl-folder = the .eml folder-import path.
    assert "ooFolderPicker('ux-dest'" in html, "no Browse on the unified Export destination"
    assert "ooFolderPicker('ux-imp-src'" in html, "no Browse on the unified Import source"
    assert "ooFolderPicker('nl-folder'" in html, "no Browse on the .eml folder import"
    assert 'id="folder-picker"' in html
    # The picker reads the traversal-safe backend and uses addEventListener (no inline onclick).
    assert "function ooFolderPicker(" in app and "/api/fs/list" in app
    assert 'el.addEventListener("click"' in app  # row navigation is delegated, not inline
    # The router is wired into the spine.
    wiring = (_SRC / "api" / "_wiring.py").read_text(encoding="utf-8")
    assert "files_router" in wiring


def test_restore_auto_detects_encryption_client_side():
    """Field test 2026-06-22 #10: restore reads the file's OOENC1 magic LOCALLY and
    shows the passphrase field only for an encrypted backup (no upload-to-check); a
    plaintext archive needs none. The magic matches read_artifact's exact signature."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert 'onchange="v2DetectEncryption()"' in html
    assert 'id="v2-restore-pass-wrap"' in html and "hidden" in html
    assert "function v2DetectEncryption(" in app
    # reads only the first 8 bytes locally, compares the OOENC1 magic bytes.
    assert "f.slice(0, 8).arrayBuffer()" in app
    assert "0x4f, 0x4f, 0x45, 0x4e, 0x43, 0x31, 0x00, 0x00" in app  # "OOENC1\\0\\0"
    # backend already raises the matching clear error (the source of truth).
    art = (_SRC / "backup" / "artifact.py").read_text(encoding="utf-8")
    assert 'blob[:8] == b"OOENC1\\x00\\x00"' in art


def test_home_card_click_diagnostics_and_download_all_wired():
    """Field report 2026-06-22: a RECURRING home-card click diagnostic ("what does
    clicking each Lead induce — its EXACT corpus or a fuzzy search that loses it") +
    a single "All diagnostics" download. Also pins the live fix: the briefing cache
    version was bumped so existing installs recompute and cards gain article_ids."""
    diag = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    cd = (_SRC / "briefing" / "card_diagnostics.py").read_text(encoding="utf-8")
    svc = (_SRC / "briefing" / "service.py").read_text(encoding="utf-8")

    # The recurring tool: the per-card click classifier + its seed-query replica.
    assert "def card_click_diagnostics(" in cd
    assert "def card_seed_query(" in cd
    # The endpoints exist and are downloadable.
    assert '@router.get("/home-cards")' in diag
    assert "card_click_diagnostics" in diag
    assert '@router.get("/all")' in diag and "def all_diagnostics(" in diag
    # The all-bundle gathers the other logs (each wrapped so one failure can't abort it).
    for member in ("debug-bundle.json", "home-cards.json", "keyword-engine.json"):
        assert member in diag
    assert ".error.txt" in diag  # per-member failure is recorded, never fatal

    # The Settings -> Diagnostics buttons: DIAGNOSE-THE-DIAGNOSTICS ruling #7
    # (2026-07-20) removed the standalone home-cards/debug-bundle download buttons --
    # the all-diagnostics bundle already carries both (home-cards.json, debug-bundle.json,
    # asserted above) and the completeness ratchet guarantees it. The "All diagnostics"
    # button now runs the BACKGROUND job (B6/#622): the old synchronous
    # window.open('/api/diagnostics/all') froze the single-worker server for ~36 min on a
    # large corpus, so the button POSTs /all-job (backend below), polls status, downloads
    # when ready.
    assert 'onclick="runAllDiagnostics(this)"' in html and 'id="all-diag-status"' in html
    assert '@router.post("/all-job")' in diag  # the non-blocking background-job endpoint
    assert ">All diagnostics (.zip)<" in html
    assert ">Keyword log (.zip)<" in html  # kept -- the FULL dump, exempt from the bundle
    assert "/api/diagnostics/home-cards?download=1" not in html, (
        "the standalone home-cards download button must be gone (bundle carries it)"
    )
    assert "/api/diagnostics/debug-bundle" not in html, (
        "the standalone debug-bundle download button must be gone (bundle carries it)"
    )
    assert "Download keyword log (.zip)" not in html  # the old verbose label is gone

    # The live hard-linking fix: cache version bumped so a pre-fix cached briefing
    # (cards without article_ids) is recomputed once.
    assert 'CACHE_VERSION = "oo-briefing-cache-2"' in svc


def test_http_error_responses_recorded_in_diagnostic_log():
    """Field test 2026-06-24: "I'd like all error codes recorded into a downloadable
    diagnostic log." Every HTTP error RESPONSE (4xx/5xx — incl. a 404 on an unmatched
    route, which logs nothing otherwise) is captured into data/app_errors.jsonl by the
    request middleware, which is the one place that sees the final status for EVERY
    response. The bundle already ships that file + the summary, so the codes are
    downloadable. The HTTP channel stays OUT of the problem/lock counts."""
    el = (_SRC / "monitoring" / "errorlog.py").read_text(encoding="utf-8")
    main = (_SRC / "api" / "main.py").read_text(encoding="utf-8")
    diag = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")

    # The recorder exists, has its own non-problem level + a poll-storm throttle.
    assert "def note_http_error(" in el
    assert '_HTTP_LEVEL = "HTTP"' in el and "_HTTP_THROTTLE_S" in el
    # HTTP is deliberately NOT a "problem" level (a 404/409 is often the right answer).
    assert '_PROBLEM_LEVELS = {"WARNING", "ERROR", "CRITICAL"}' in el
    # summary() surfaces the new counts (without inflating problems).
    for key in ("http_errors_total", "http_errors_this_session", "http_status_breakdown"):
        assert f'"{key}"' in el

    # The request middleware records every >= 400 response, best-effort.
    assert "monitor_requests" in main
    assert "status_code >= 400" in main and "note_http_error" in main

    # It rides the existing downloadable bundle (recent_errors + the summary).
    assert "recent_errors" in diag and "error_log" in diag


def test_governments_sources_facets_strata_strings_are_keyed():
    """Field report 2026-06-22: the Governments UI, the Sources multi-select facet
    filters and the task-manager language/tag strata shipped with English-fallback
    strings (gate stayed 100% but non-English users saw English there). They are now
    keyed; this pins that they stay keyed (the --min 100 gate then guarantees x12)."""
    import json

    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    must_be_keyed = [
        # Governments UI
        "Countries", "Law", "Country data", "Load standard country data",
        "World map — per-country data", "Indicator", "Latest available",
        "Could not load this country.", "Loaded country data:",
        "No country data yet — use the Countries tab to load it (online).",
        # Sources multi-select facet filters
        "Any", "match all tags", "selected",
        "Any: a source with ANY chosen tag. All: a source with EVERY chosen tag.",
        # task-manager strata buckets
        "untagged", "unknown",
    ]
    missing = [s for s in must_be_keyed if s not in en]
    assert not missing, f"these strings regressed to English-fallback (not keyed): {missing}"


def test_keyword_growth_curve_wired_and_decrypt_free():
    """Maintainer ask 2026-06-24 (at 909k keywords): a vocabulary-growth curve —
    cumulative keywords vs cumulative words. Pin the endpoint + the frontend View/
    download wiring, and that the analytic reads keyword_mentions ONLY (never joins to
    the encrypted articles table — the standing decrypt-trap rule)."""
    diag = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    assert '"/keyword-growth"' in diag and "keyword_growth_curve" in diag

    growth = (_SRC / "analytics" / "keyword_growth.py").read_text(encoding="utf-8")
    # decrypt-free: it queries keyword_mentions and never the articles table.
    assert "keyword_mentions" in growth
    assert "from articles" not in growth.lower() and "join articles" not in growth.lower()
    # (no-score is enforced on the actual payload in tests/test_keyword_growth.py)

    src = _ui_source()  # index.html + app.js
    assert "viewKeywordGrowth" in src and "_growthSvg" in src
    # DIAGNOSE-THE-DIAGNOSTICS ruling #7 (2026-07-20): the standalone JSON download
    # button is gone -- the all-diagnostics bundle already carries keyword-growth.json
    # (asserted in _all_diagnostics_members, tests/test_recursive_loop.py); the
    # interactive chart button (viewKeywordGrowth, asserted above) stays -- it is an
    # ACTION, not a report download.
    assert "/api/diagnostics/keyword-growth?download=1" not in src


def test_volume_backup_job_wired_slice_1c():
    """Slice 1c: the large encrypted backup (volumes + parity) is reachable in-app — the
    job manager, the four endpoints, the /api/jobs surface, and the Settings panel + JS.
    CRUCIALLY: every volume route the FRONTEND calls must compose to a real backend route
    (router prefix + decorator) — the path agreement that, when broken, gave a 404."""
    import re

    assert (_SRC / "backup" / "volume_job.py").exists()
    bv = (_SRC / "api" / "backup_v2.py").read_text(encoding="utf-8")
    assert 'prefix="/api/backup"' in bv
    jobs = (_SRC / "api" / "jobs.py").read_text(encoding="utf-8")
    assert "_volume_backup_jobs" in jobs and "volume-backup" in jobs
    src = _ui_source()
    assert "volBackupStart" in src and "volRestoreStart" in src and "vb-dest" in src

    # The backend route for each volume endpoint = "/api/backup" + the decorator path.
    backend_routes = {
        "/api/backup" + m
        for m in re.findall(r'@router\.(?:get|post)\("(/v2/volumes/[a-z]+)"\)', bv)
    }
    # The volume routes the frontend actually POSTs/GETs.
    frontend_routes = set(re.findall(r'"(/api/backup/v2/volumes/[a-z]+)"', src))
    assert frontend_routes, "frontend calls no /api/backup/v2/volumes/* route"
    missing = frontend_routes - backend_routes
    assert not missing, f"frontend calls volume routes with no matching backend route: {missing}"
    # all four endpoints present
    assert {"/api/backup/v2/volumes/" + a for a in ("start", "restore", "status", "cancel")} <= (
        backend_routes | frontend_routes
    )


def test_favicon_route_and_brand_icon_wired():
    """Field diagnostics 2026-07-01: the browser's default ``/favicon.ico`` request 404'd
    on every page — index.html declared no icon (static is mounted only at ``/static``),
    and taskmanager.html pointed at a non-existent ``.ico``. Fix: the REAL brand SVG (the
    eye — UI invariant #5) is served from ``/static``, a root ``/favicon.ico`` route
    redirects to it (``/favicon`` is already allowed while locked, so it resolves on the
    unlock screen too), and the HTML pages declare it. Guarded at the SOURCE: the app
    import needs the crypto extra, so a TestClient GET is CI-only; this file-level check
    runs in every lane."""
    favicon = _SRC / "static" / "favicon.svg"
    assert favicon.exists(), "src/static/favicon.svg (the brand icon) must exist"
    brand = (_ROOT / "assets" / "icon.svg").read_text(encoding="utf-8")
    assert favicon.read_text(encoding="utf-8") == brand, (
        "favicon.svg must BE the canonical brand icon assets/icon.svg (invariant #5), "
        "never a fabricated placeholder"
    )
    main = (_SRC / "api" / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/favicon.ico"' in main, "main.py must register a root /favicon.ico route"
    assert "/static/favicon.svg" in main, "the /favicon.ico route must resolve to the brand SVG"
    assert '"/favicon"' in (_SRC / "api" / "unlock.py").read_text(encoding="utf-8"), (
        "/favicon must stay allowed while the store is locked (the redirect resolves there too)"
    )
    for page in ("index.html", "taskmanager.html"):
        html = (_SRC / "static" / page).read_text(encoding="utf-8")
        assert "/static/favicon.svg" in html, f"{page} must declare the brand favicon"
        assert "favicon.ico" not in html, f"{page} must not reference the non-existent favicon.ico"


def test_vitals_poll_backs_off_when_panel_closed():
    """Field diagnostics 2026-07-01 (F5 — the idle polling storm): the vitals poller ran a
    FIXED 2 s ``setInterval`` whenever a background scrape was live, polling
    ``/api/system/vitals`` + ``/api/scheduler/activity`` every 2 s for the whole multi-hour
    scrape even with the panel CLOSED (~28.9k ``/api/scheduler/activity`` calls contending
    with the encrypted DB). It now uses an ADAPTIVE cadence — responsive while the panel is
    open, calmer when only the 'Collecting N/M' chip is live. The airplane/network state
    keeps its OWN ``_adaptivePoll``, so this must not touch it."""
    import re

    src = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"function _vitalsCadence\(\)\s*\{\s*return _vitalsOpen \? (\d+) : (\d+)", src)
    assert m, "_vitalsCadence() must exist and branch on _vitalsOpen (panel-open vs chip-only)"
    open_ms, closed_ms = int(m.group(1)), int(m.group(2))
    assert closed_ms > open_ms, (
        f"chip-only cadence ({closed_ms}ms) must be SLOWER than panel-open ({open_ms}ms) — "
        "that IS the storm fix"
    )
    assert "setTimeout(tick, _vitalsCadence())" in src, (
        "the vitals poll must self-schedule at the adaptive cadence"
    )
    assert "setInterval(() => { if (!document.hidden) _pollVitals(); }, 2000)" not in src, (
        "the fixed-2s setInterval vitals hammer must be gone"
    )
    assert "_adaptivePoll(_pollNetwork)" in src, (
        "the network/airplane poll must remain its own separate _adaptivePoll (untouched)"
    )



def test_all_diagnostics_runs_as_a_background_job():
    """B6 / field-test Item 10: the 'All diagnostics (.zip)' button no longer does a
    SYNCHRONOUS build that freezes the single-worker server for minutes on a large corpus.
    It starts the background job (POST /all-job), polls /all-job/status, shows live progress,
    and downloads /all-job/download when ready. JOB-STATE-AS-TRUTH: a dropped poll shows a
    'connection hiccup — retrying', never 'failed'. Browser-unverified per fork-3 —
    node-checked + grep-guarded here."""
    ui = _ui_source()
    assert 'runAllDiagnostics(this)' in ui, "the button must call the background-job handler"
    assert "async function runAllDiagnostics" in ui, "the handler must be defined"
    assert "/api/diagnostics/all-job" in ui, "it must start the background job"
    assert "/api/diagnostics/all-job/status" in ui, "it must poll job status"
    assert "/api/diagnostics/all-job/download" in ui, "it must download when ready"
    assert 'id="all-diag-status"' in ui, "a live-progress status element must exist"
    assert "Connection hiccup" in ui, "a dropped poll must degrade honestly, not say 'failed'"
    # The old synchronous window.open('/api/diagnostics/all') blocking click is gone.
    assert "window.open('/api/diagnostics/all','_blank')" not in ui, "the synchronous /all click must be replaced"


def test_llm_langdetect_is_optin_labelled_and_never_touches_trusted_channels():
    """B15: the OPT-IN local-LLM language detector for articles STILL unknown after the
    offline detector writes a THIRD 'AI-derived · unreliable' provenance class (ai_keyword
    kind='language') and NEVER the authoritative Article.language nor the offline-deduced
    Article.detected_language. Detector-first, validated (garbage stores nothing), a
    cancellable background job — never the scrape hot path."""
    mod = (_SRC / "ai_layer" / "langdetect_llm.py").read_text(encoding="utf-8")
    api = (_SRC / "api" / "ai.py").read_text(encoding="utf-8")
    ui = _ui_source()
    # writes ONLY ai_keyword(kind="language") via the store helper (the "never overwrites the
    # trusted channels" guarantee is proven behaviourally in tests/test_ai_langdetect.py::
    # test_detect_stores_only_ai_keyword_and_never_touches_article_language).
    assert 'LANG_KIND = "language"' in mod
    assert "record_keywords(" in mod and "kind=LANG_KIND" in mod
    # no UPDATE of the trusted columns: record_keywords takes language=code as a KEYWORD arg,
    # so the module never contains a dotted assignment to a .language attribute.
    assert ".language =" not in mod and ".detected_language =" not in mod
    # detector-first: the worklist requires BOTH channels unset
    assert "unset(Article.language)" in mod and "unset(Article.detected_language)" in mod
    # validated: a reply outside the known code set stores nothing (miss over invent)
    assert "KNOWN_LANG_CODES" in mod and "in KNOWN_LANG_CODES" in mod
    # no score anywhere in the AI-derived language layer (honesty by construction)
    assert "score" not in mod.lower()
    # a cancellable, is_writer background job (visible in /api/jobs), never inline in a scrape
    assert 'BackgroundJob(' in api and '"ai-langdetect"' in api
    assert "cancellable=True" in api and "is_writer=True" in api
    assert "should_stop=lambda: ctx.stopping" in api
    # the endpoints + the opt-in Settings button + candidate count
    assert '@router.post("/detect-language")' in api and '@router.get("/detect-language/candidates")' in api
    assert "runLangDetect" in ui and 'id="langdetect-btn"' in ui and "loadLangDetectCount" in ui
    # 2026-07-23 continuous-mode ask: an on/off switch chains internal batches until the
    # backlog is exhausted, instead of a fixed one-shot cap; a "none" result is excluded via
    # an in-run exclude_ids set (never persisted), so the unclassifiable residue can't starve
    # the rest of the backlog by re-occupying every batch's query window.
    assert "continuous: bool = False" in api and "exclude_ids=attempted" in api
    assert "exclude_ids" in mod and "Article.id.in_(exclude_ids)" in mod
    # 2026-07-24 field-feedback Session A §1: the checkbox is GONE — ONE button now toggles
    # start <-> stop (never a separate continuous/non-continuous choice in the UI), and a
    # transient LLMUnavailable mid-run retries with backoff instead of hard-aborting the run
    # into a benign-looking "done" (the maintainer's exact field report).
    assert 'id="langdetect-continuous"' not in ui, "the continuous checkbox must be removed"
    assert "Language detection ongoing" in ui, "the button must toggle to a stop label while running"
    assert "_LANGDETECT_MAX_CONSECUTIVE_FAILURES" in api, "transient failures must retry, not hard-abort"
    assert "advance_langdetect_auto_start" in api, "an auto-start ride-along must exist (default ON)"
    assert "ai_langdetect_auto" in api, "the auto-start must be gated by an operator setting"


def test_newsletter_eml_upload_runs_off_the_event_loop():
    """Audit finding 2026-07-17: ``POST /api/newsletters/import`` is an ``async def``
    handler (it needs ``await request.form(...)`` for the raised ``max_files`` cap), so it
    runs ON the single event loop -- the same freeze family already fixed for unlock/
    restore-preview/``/api/articles``/``upload_pdfs``. Parsing thousands of ``.eml`` files
    through ``ingest_emails`` (anonymise + ``index_article`` per message) is exactly the
    kind of multi-second synchronous DB work that must never block the whole server. The
    sibling ``upload_pdfs`` handler in the SAME file already does this correctly -- this
    pins that ``import_newsletters`` now matches it."""
    api = (_SRC / "api" / "ingestion.py").read_text(encoding="utf-8")
    handler = api[api.index("async def import_newsletters(") :]
    handler = handler[: handler.index("\n\n\nclass RemoveNewslettersBody")]
    assert "run_in_threadpool" in handler, "the heavy ingest_emails call must run off the loop"
    assert "await run_in_threadpool(ingest_emails, db, source, raws)" in handler
    # the sibling stays the reference pattern (regression guard against re-diverging)
    assert "await run_in_threadpool(ingest_pdf_blobs, db, blobs)" in api


def test_cross_time_recall_is_sacred_no_time_partitioned_corpus_tables():
    """5 TB review §F (docs/design/5TB_ARCHITECTURE_REVIEW.md): cross-time recall is SACRED — no
    design may make old data second-class. The concrete forbidden thing is a TIME-PARTITIONED /
    year-sharded / archive TWIN of a corpus-scaled table (e.g. keyword_mentions_2026 + _archive),
    which a full-corpus query would fan out to and could silently default AWAY from. A WINDOWED
    rollup is fine — the window is the user's QUERY, not a storage boundary (keyword_daily stays).
    This guard keeps 5 TB storage pressure from quietly regressing the principle (the same
    'enforce the principle in a test' discipline the UI invariants use). S3.4 / DB-10 §F."""
    import re

    models = (_SRC / "database" / "models.py").read_text(encoding="utf-8")
    tablenames = re.findall(r'__tablename__\s*=\s*["\']([^"\']+)["\']', models)
    assert tablenames, "no ORM tablenames found — the guard itself needs updating"
    # a corpus-scaled table must not have a year / archive / shard twin (time-partitioning)
    forbidden = re.compile(r"(_(?:19|20)\d{2}$|_archive$|_shard\d*$)")
    bad = [t for t in tablenames if forbidden.search(t)]
    assert not bad, (
        f"time-partitioned/archived corpus table(s): {bad} — cross-time recall is sacred (§F). "
        "Use a windowed rollup (the window is the user's query, not a storage boundary), never a "
        "second physical table split by time. See docs/design/5TB_ARCHITECTURE_REVIEW.md §F."
    )
    # the canonical windowed serve DEFAULTS to the WHOLE corpus (open bounds), never a baked-in
    # recency cutoff on the hot read path (a rollup window is the user's query, not a default).
    columnar = (_SRC / "analytics" / "columnar.py").read_text(encoding="utf-8")
    assert "start_day=None, end_day=None" in columnar, (
        "windowed_term_counts must keep open (whole-corpus) default bounds — no recency default "
        "on the hot read path (§F cross-time recall)."
    )


def test_ring_translation_breakdown_rides_the_hover():
    """S4.2: the per-language COMPOSITION of a merged cross-language keyword (language_breakdown)
    rides the #oo-tip LAYERED hover (the title attribute) on the Trends/Home rows — visible on
    demand, never crowding the visible row (invariant #17). kwTransHtml reads
    row.language_breakdown into its title, never into the row text."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    start = app.index("function kwTransHtml(")
    kw = app[start : app.index("function kwTentativeHtml(", start)]
    assert "row.language_breakdown" in kw, "the breakdown must feed kwTransHtml"
    assert "Across languages:" in kw
    assert 'title="' in kw  # rides the #oo-tip title (layered), not the visible row text


def test_synthesized_leads_carousel_is_local_pausable_and_caveated():
    """S4.3: the Home Leads carousel is LOCAL analytic synthesis (never LLM), PAUSABLE (WCAG 2.2
    — hover/focus + a manual toggle + keyboard), and a timed rotation NEVER hides a caveat (the
    caveat rides every rotated face, #23); every face DEEP-LINKS to its real corpus (#8); fed from
    the SAME briefing cards (evidence-tier order, no hidden score)."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="home-carousel-panel"' in html and 'id="home-carousel"' in html
    car = app[app.index("function renderLeadsCarousel(") : app.index("function _carRelease(") + 200]
    # LOCAL: fed from the briefing cards; NO LLM call anywhere in the carousel
    assert "renderLeadsCarousel(data.buckets.flatMap" in app
    for llm in ("/api/llm", "synthesize", "bulkLlm"):
        assert llm not in car, f"carousel must never call the LLM ({llm})"
    # PAUSABLE (WCAG 2.2): hover/focus pause + a manual toggle + keyboard
    assert "mouseenter" in car and "focusin" in car and "carouselToggle" in car
    assert "aria-pressed" in car and "ArrowLeft" in car and "ArrowRight" in car
    # the CAVEAT rides EVERY face + a deep-link on every face (#23 + #8)
    assert "c.caveat" in car and "card-caveat" in car and "openCardCorpus" in car


def test_omnibar_analysis_window_absorbs_the_insights_bar_capabilities():
    """S4.4: the omnibar->#an analysis window ABSORBS every term-exploration capability of the
    Insights search bar (exploreTerm / #ins-term), so retiring the bar later never loses a tool
    (the Desk lesson; UI-rethink invariant #5). The four capabilities:
      - trend        -> /api/insights/trend        (renderAnTrend, #an-trend)
      - associations -> /api/insights/associations (renderAnTrend, #an-keywords mindmap seed)
      - mindmap      -> renderAnMindmap             (#an-mindmap, self-contained #an renderer)
      - context      -> /api/insights/context       (S4.4 PORT: term-in-context concordance,
                                                      keyed on the analysis query, under the chips)
    This is a REGRESSION GUARD on the absorption, NOT an assertion that the bar is gone: the bar
    STAYS for now because #ins-explore INTERLEAVES the search bar with the NON-searchable
    corpus-landscape AND the RELOCATABLE shared #mm-kit mindmap component, so the actual hide is
    gated on a browser-verified untangling (recorded as the S4.4 carry-over)."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # the #an subtab panels exist for each absorbed lens
    assert 'id="an-trend"' in html and 'id="an-mindmap"' in html and 'id="an-keywords"' in html
    # trend + associations flow into #an (renderAnTrend)
    rt = app[app.index("async function renderAnTrend(") : app.index("async function renderAnRelated(")]
    assert "/api/insights/trend" in rt and "/api/insights/associations" in rt
    # mindmap: the self-contained #an renderer (never the Insights-bar renderMindmap/#ins-term)
    assert "renderAnMindmap(" in app
    # S4.4 PORT: term-in-context concordance, keyed on the analysis query, snippets only
    ctx = app[app.index("async function loadAnContext(") : app.index("async function loadAnContext(") + 900]
    assert "/api/insights/context" in ctx, "context snippets must be ported into #an"
    assert 'p.get("query")' in ctx and "anQuery()" in ctx, "context is keyed on the analysis query term"
    assert "anContextHtml(" in app and "In context" in app
    # the port renders snippets, never a score (counts/snippets only)
    ch = app[app.index("function anContextHtml(") : app.index("function anContextHtml(") + 1200]
    assert "score" not in ch.lower(), "the context concordance carries no score"


def test_i18n_composite_strings_and_translatable_card_titles():
    """S4.5: the i18n engine supports COMPOSITE strings — a fixed keyable TEMPLATE with
    {named} placeholders whose values are DATA left untranslated (OOI18N.tf). This is what
    makes a value-bearing string translatable: the frame translates ×12, the data does not.
    A card can carry a translatable title (title_i18n template + title_vars data), rendered
    via tf; the English `title` stays the fallback. The `rising` reference producer emits one,
    and the template key exists in ALL 12 locales (so --min 100 stays green)."""
    i18n = (_SRC / "static" / "i18n.js").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # (a) the engine exposes tf(): template lookup + {named} interpolation, exported
    assert "function tf(s, vars)" in i18n
    assert "map[s] == null ? s : map[s]" in i18n and "replace(/\\{(\\w+)\\}/g" in i18n
    assert "t, tf," in i18n, "tf must be exported on OOI18N"
    # (b) the UI renders a card's title via cardTitle -> OOI18N.tf, English title as fallback
    ct = app[app.index("function cardTitle(") : app.index("function cardTitle(") + 400]
    assert "c.title_i18n" in ct and "OOI18N.tf(" in ct and "c.title" in ct
    assert "esc(cardTitle(c))" in app, "the card front + carousel must render cardTitle(c)"
    # (c) the Card schema emits the translatable-title fields; the reference producer sets them
    card = (_SRC / "briefing" / "card.py").read_text(encoding="utf-8")
    assert '"title_i18n": self.title_i18n' in card and '"title_vars": self.title_vars' in card
    prod = (_SRC / "briefing" / "producers.py").read_text(encoding="utf-8")
    assert 'title_i18n="“{term}” is rising"' in prod and 'title_vars={"term":' in prod
    # (d) the template KEY is present in every one of the 12 locale files (gate stays 100%)
    import json as _json
    loc = _SRC / "static" / "locales"
    for lf in sorted(loc.glob("*.json")):
        d = _json.loads(lf.read_text(encoding="utf-8"))
        assert "“{term}” is rising" in d, f"{lf.name} missing the rising title template key"
        assert "{term}" in d["“{term}” is rising"], f"{lf.name}: translation must keep {{term}}"


def test_guided_wizard_sources_by_theme_step():
    """S4.7: the first-launch guided wizard gains a SOURCES-BY-THEME step (before Finish) that
    picks themes from the REAL catalog tag taxonomy + emphasizes languages, applied as scheduler
    config via LOOPBACK reads/writes only. The wizard NEVER posts the network — the finish step's
    consented go-online (toggleNetwork -> ensureOnline) stays the ONLY path to egress.
    HONESTY: themes DEFAULT to all-selected = collect everything (the cover-everything ruling);
    a partial pick sets select_tags (a filter), all-or-none clears it. Language emphasis maps to
    language_equilibrium (a cadence lever that ORDERS, never excludes). The language step is
    already consolidated out (§2.5) — the flow is [sources, finish]."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    # the step DOM exists (theme picker + language-emphasis group)
    assert 'data-step="sources"' in html and 'id="gw-themes"' in html and 'id="gw-emph-langs"' in html
    # the flow is sources -> finish (language step already dropped)
    assert '_GW_STEPS = ["sources", "finish"]' in app
    # themes come from the REAL catalog tag taxonomy (the app's own loopback coverage endpoint)
    rs = app[app.index("async function _gwRenderSources(") : app.index("function _gwUpdateThemeNote(")]
    assert "/api/scheduler/coverage" in rs, "themes must come from the real tag taxonomy"
    # apply = a LOOPBACK scheduler-config write; select_tags + language_equilibrium; never egress
    ap = app[app.index("async function _gwApplySourcePrefs(") : app.index("async function _gwApplySourcePrefs(") + 900]
    assert "/api/scheduler/config" in ap and "select_tags" in ap and "language_equilibrium" in ap
    assert "/api/system/network" not in ap, "the wizard must NEVER post the network"
    # cover-everything default: all-or-none selected => NO filter (empty select_tags)
    assert "on.length === 0 || on.length === all.length" in ap and "? [] :" in ap
    # the ONLY network path stays the finish step's consented go-online (unchanged)
    assert "toggleNetwork()" in app


def test_usgs_minerals_supply_surface_is_supply_not_prices():
    """S5.1: the USGS Mineral Commodity Summaries SUPPLY surface (rare-earths ruling B12).
    'supply, never prices' is enforced by construction (a price/unit-value/currency-unit row
    is refused in the parser), the agency + endpoint + a conservative Markets panel exist, and
    the panel degrades LOUDLY when no data is stored yet (the operator-fetch empty state)."""
    usgs = (_SRC / "stats" / "usgs.py").read_text(encoding="utf-8")
    assert "def parse_mcs_csv(" in usgs and 'AGENCY = "us-usgs"' in usgs
    assert "_SUPPLY_MEASURES" in usgs and "_is_price_text" in usgs, "the price-refusal guards"
    assert "import requests" not in usgs and "import httpx" not in usgs and "import socket" not in usgs, (
        "the parser must be network-free"
    )
    agencies = (_SRC / "stats" / "agencies.py").read_text(encoding="utf-8")
    assert '"us-usgs"' in agencies and "USGS" in agencies
    store = (_SRC / "stats" / "store.py").read_text(encoding="utf-8")
    assert "def minerals_supply_summary(" in store and '"available"' in store
    api = (_SRC / "api" / "stats.py").read_text(encoding="utf-8")
    assert '"/minerals-supply"' in api
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    ms = app[app.index("async function loadMineralsSupply(") : app.index("async function loadMineralsSupply(") + 1400]
    assert "/api/stats/minerals-supply" in ms and "d.available" in ms and "d.reason" in ms
    assert "supply data, not prices" in ms.lower()


def test_subjectivity_engine_is_multilingual_deduced_and_no_score():
    """S5.2: the rule-based subjectivity/loaded-language engine — multilingual via vendored
    lexicon FILES (dated + registered), descriptive components + spans (never a composite
    score), an HONEST per-language gap (available:false, never a fabricated 0). It FEEDS the
    manipulation card (secondary annotation, never a standalone Lead) and a DEDUCED per-article
    surface (three-class provenance). VADER (valence) is deliberately NOT reused."""
    sub = (_SRC / "analytics" / "subjectivity.py").read_text(encoding="utf-8")
    assert "def load_lexicon(" in sub and "def subjectivity(" in sub
    assert "SUBJECTIVITY_AS_OF" in sub, "dated (registered in external_artifacts.yml)"
    assert '"available": False' in sub and '"spans"' in sub, "honest gap + spans, no score"
    assert "import vader" not in sub.lower(), "VADER valence is not subjectivity; not reused"
    # seed lexicons across three scripts exist
    base = _SRC.parent / "configs" / "subjectivity"
    assert (base / "en.txt").is_file() and (base / "ru.txt").is_file() and (base / "ar.txt").is_file()
    # registered (the *_AS_OF protocol guard)
    reg = (_SRC.parent / "configs" / "external_artifacts.yml").read_text(encoding="utf-8")
    assert "subjectivity-lexicons" in reg and "SUBJECTIVITY_AS_OF" in reg
    # feeds the manipulation card (secondary annotation)
    hb = (_SRC / "analytics" / "headline_body.py").read_text(encoding="utf-8")
    assert "import subjectivity" in hb and '"subjectivity": subjectivity(' in hb
    # the DEDUCED per-article surface
    ins = (_SRC / "api" / "insights.py").read_text(encoding="utf-8")
    assert '"/subjectivity"' in ins and '"provenance": "deduced"' in ins


def test_ir_gold_set_builder_writes_validated_gold_and_closes_the_loop():
    """S5.3: the IR gold-set BUILDER makes the maintainer's gold set trivial to produce —
    samples REAL corpus queries (top keywords; search history is not stored, so nothing is
    invented), grades 0/1/2 with keyboard speed, and writes the EXACT ir_eval gold-set JSON
    VALIDATED by round-trip (an invalid set never lands). Closes the measure-before-trust loop
    for OO_FAMILY_LEMMA + the BM25F default (the run endpoint already exists)."""
    gb = (_SRC / "analytics" / "gold_builder.py").read_text(encoding="utf-8")
    assert "def sample_queries(" in gb and "def build_and_save_gold_set(" in gb and "def coverage(" in gb
    assert "load_gold_set" in gb and "os.replace(" in gb, "validated round-trip + atomic swap"
    assert "top_terms" in gb and "search history is not stored" in gb, "real queries, never invented"
    diag = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    assert '"/gold-builder/sample"' in diag and '"/gold-builder/save"' in diag
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function goldBuilderLoad(" in app and "function goldBuilderSave(" in app
    assert "/api/diagnostics/gold-builder/sample" in app and "/api/diagnostics/gold-builder/save" in app
    assert "function goldBuilderKey(" in app and 'ev.key === "0"' in app, "keyboard-speed grading"
    assert "_gbUpdateCoverage(" in app, "the coverage meter"


def test_lemma_preview_is_surfaced_in_the_diagnostics_panel():
    """S5.4: the lemma-conflation preview (what lemmatization merges, ON by default since
    2026-07-18) is VISIBLE in the Diagnostics panel next to the gold-set builder — it was
    only reachable by downloading the engine-report JSON. A focused endpoint + a render
    showing candidate groups + would-merge counts + the _MISLEMMA_DENYLIST affordance."""
    er = (_SRC / "analytics" / "engine_report.py").read_text(encoding="utf-8")
    assert "def lemma_preview_report(" in er, "the focused (no full-report) preview function"
    diag = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    assert '"/lemma-preview"' in diag
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    lp = app[app.index("async function loadLemmaPreview(") : app.index("async function loadLemmaPreview(") + 2600]
    assert "/api/diagnostics/lemma-preview" in lp and "_MISLEMMA_DENYLIST" in lp
    assert "candidate_groups" in lp and "keywords_that_would_merge" in lp
    assert 'id="lemma-preview-body"' in (_SRC / "static" / "index.html").read_text(encoding="utf-8")


def test_perception_eval_harness_is_wired_and_gate_first():
    """S6.5: the LLM-perception (who/where/when) eval HARNESS exists BEFORE any extraction
    feature (the ruled order) — precision/recall/HALLUCINATION per stratum vs a synthetic gold
    set, place string vs coordinate scored apart, de-US-centring split, no composite. Exposed
    as a diagnostics self-test; the rule-based baseline adapter is the bar an LLM must clear."""
    pe = (_SRC / "analytics" / "perception_eval.py").read_text(encoding="utf-8")
    assert "def evaluate_perception(" in pe and "def run_perception_eval_selftest(" in pe
    assert "hallucination_rate" in pe and "de_us_centring" in pe and "place_coordinate" in pe
    assert "def rule_based_perception(" in pe, "the baseline adapter (the bar for an LLM)"
    assert "PERCEPTION_GOLD" in pe and "needs_native_review" in pe
    diag = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    assert '"/perception-eval-selftest"' in diag


def test_all_diagnostics_bundle_covers_every_get_diagnostic():
    """RATCHET (maintainer 2026-07-17: '"all diagnostics" should comprise ALL
    diagnostics'): every GET endpoint on the diagnostics router must either
    contribute to the all-diagnostics bundle (a member file, or its /last report
    for job kinds) or be EXEMPT with a stated reason — mirrored honestly in the
    manifest's "excluded" block. A new GET diagnostic reddens this test until it
    is classified, so the bundle can never silently fall behind again.

    DIAGNOSE-THE-DIAGNOSTICS (2026-07-20): the covered/exempt maps below are IMPORTED
    from src.api.diagnostics, not hand-duplicated here — the manifest's own runtime
    coverage block (_diagnostics_coverage_report) recomputes this SAME comparison inside
    every all-diagnostics run, and importing rather than copying means the CI-time ratchet
    and the runtime block can never silently diverge from each other."""
    import re

    from src.api import diagnostics as _diag

    src = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    gets = set(re.findall(r'@router\.get\("([^"]+)"', src))

    # endpoint path -> the bundle member filename that carries its payload. Imported from
    # src.api.diagnostics (see the module docstring above) rather than duplicated here.
    covered = dict(_diag._DIAG_COVERAGE_MAP)
    exempt = dict(_diag._DIAG_COVERAGE_EXEMPT)
    unclassified = sorted(gets - set(covered) - set(exempt))
    assert not unclassified, (
        "new GET diagnostics endpoint(s) are neither in the all-diagnostics bundle "
        f"nor exempted with a reason: {unclassified} — add a bundle member (and the "
        "filename to this test's `covered` map) or an exemption here AND in the "
        "manifest's 'excluded' block"
    )
    stale = sorted((set(covered) | set(exempt)) - gets)
    assert not stale, f"classified paths no longer exist as GET routes: {stale}"
    members_block = src.split("def _all_diagnostics_members", 1)[1].split("def _", 1)[0]
    missing_members = sorted(
        fname for fname in covered.values() if f'"{fname}"' not in members_block
    )
    assert not missing_members, (
        f"bundle member file(s) named in the coverage map are absent from "
        f"_all_diagnostics_members: {missing_members}"
    )
    # The manifest documents its own boundary (honesty: exclusions never silent).
    assert '"excluded"' in src or '"excluded":' in src.replace(" ", ""), (
        "_all_diagnostics_manifest must carry the 'excluded' disclosure block"
    )


def test_fresh_stores_wire_incremental_auto_vacuum():
    """DB-10 §1a (ruled 2026-07-17): every 'Fresh file' branch of
    ``connect()`` must set ``auto_vacuum = INCREMENTAL`` (2) before any table
    exists — SQLite requires this ordering, and once set it is read back from
    the file header on every later open with no extra plumbing (unlike
    page_size, this has no reopen hazard). This is a fast wiring guard; the
    real functional create -> reopen -> PRAGMA-read-back round trip (plus the
    legacy-store-untouched proof) lives in
    tests/test_sqlcipher.py::test_fresh_stores_get_incremental_auto_vacuum_legacy_stores_untouched
    (a DB-creating test belongs beside connect()'s other functional tests, not
    in this source-grep-only file)."""
    src = (_SRC / "database" / "connect.py").read_text(encoding="utf-8")
    assert "_FRESH_AUTO_VACUUM = 2" in src, "the ruled INCREMENTAL constant is missing"
    fresh_branch = src.split("# Fresh file.", 1)[1]
    assert fresh_branch.count("PRAGMA auto_vacuum = {_FRESH_AUTO_VACUUM}") == 3, (
        "all three fresh-file sub-branches (explicit key, plaintext opt-out, "
        "ambient passphrase) must set auto_vacuum before returning the connection"
    )


def test_fresh_encrypted_stores_wire_the_ruled_page_size_and_a_reopen_probe():
    """DB-10 §1b (FIRM recommendation; NOT the marker design first attempted
    -- a persisted marker was found to go stale in THIS codebase, since
    snapshot_preserving/reencrypt_plain_to silently rewrite a live path at a
    different page size, reproduced empirically as a real HMAC failure on a
    merge-restore cycle). connect() instead PROBES on reopen (every valid
    page size, ruled default first) so it can never go stale, with an
    in-process (never persisted) cache so a repeated open of a non-default
    store doesn't re-pay the deliberately-expensive key derivation per
    candidate every time (an adversarial-skeptic finding, 2026-07-23: a
    narrower [16384, None]-only probe left any OTHER legitimate page size
    unopenable with no explicit hint, reproducing this fix's own target bug
    for exactly that case). This is the fast wiring guard; the real
    functional round trips (create -> a BRAND NEW process reopening via the
    normal boot path; the snapshot/re-encrypt pragma preservation; an
    atypical size found automatically; the cache) live in
    tests/test_sqlcipher.py::test_page_size_1b_round_trip_across_a_real_restart,
    ::test_snapshot_and_reencrypt_preserve_source_page_size_and_auto_vacuum,
    ::test_page_size_probe_finds_an_atypical_size_with_no_explicit_hint, and
    ::test_page_size_probe_caches_the_winning_candidate_per_path."""
    src = (_SRC / "database" / "connect.py").read_text(encoding="utf-8")
    assert "_FRESH_PAGE_SIZE = 16384" in src, "the ruled page-size default is missing"
    assert "_PAGE_SIZE_CANDIDATES" in src, "the widened multi-candidate probe list is missing"
    assert "_last_good_page_size" in src, "the in-process (never persisted) winning-candidate cache is missing"
    assert "def _try_open_encrypted(" in src, "the verify-then-fallback probe helper is missing"
    assert "def _match_source_pragmas(" in src, (
        "snapshot/re-encrypt must preserve the source's real page_size/auto_vacuum "
        "on the freshly-ATTACHed target, or a routine merge silently downgrades "
        "the §1b ruling on the very next snapshot"
    )
    for marker in ('_match_source_pragmas(conn, "enc")', '_match_source_pragmas(conn, "snap")'):
        assert marker in src, f"missing wiring: {marker}"
    fresh_branch = src.split("# Fresh file.", 1)[1]
    assert fresh_branch.count("PRAGMA cipher_page_size = {int(page_size)}") == 2, (
        "both fresh-ENCRYPTED sub-branches (explicit key, ambient passphrase) "
        "must declare cipher_page_size before returning the connection"
    )
    # Ordering guard: within EACH fresh-encrypted branch, cipher_page_size must
    # be set BEFORE auto_vacuum (empirically required -- the reverse order
    # corrupts page 1's HMAC once the schema is written, per the branch's own
    # inline comment).
    for branch in fresh_branch.split("if create_encrypted is False", 1)[0], fresh_branch.split(
        "if use_key:", 1
    )[1]:
        pg_i = branch.index("PRAGMA cipher_page_size = {int(page_size)}")
        av_i = branch.index("PRAGMA auto_vacuum = {_FRESH_AUTO_VACUUM}")
        assert pg_i < av_i, "cipher_page_size must be set BEFORE auto_vacuum on a fresh store"


def test_vacuum_button_has_a_real_size_gate():
    """DB-10 §1.4: the Settings 'Compact database (VACUUM)' button ran an
    unbounded synchronous rebuild on any corpus size with no warning — gate it
    with a real size threshold + an honest, measured time estimate (never a
    fabricated number), falling back to a plain confirm when the size can't be
    read (e.g. a non-SQLite backend). Live-verified in a real headless browser
    (small size -> no prompt; large size -> the real GB + the derived
    seconds-range shown; cancel -> the API is never called; unknown size -> the
    honest fallback caveat) — this is the fast source-grep companion."""
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "let _dbFileBytes = null;" in js
    assert "_dbFileBytes = (st.file && st.file.bytes != null) ? st.file.bytes : null;" in js
    assert "function _confirmVacuum()" in js
    assert "VACUUM_GATE_BYTES = 500 * 1000 * 1000" in js
    fn = js.split("async function vacuumNow()", 1)[1].split("\n    }", 1)[0]
    assert "if (!_confirmVacuum()) return;" in fn, (
        "vacuumNow must abort BEFORE disabling the button / calling the API "
        "when the size-gate confirm is declined"
    )


def test_pagesize_bench_job_is_wired():
    """DB-10 §1b: the page-size A/B bench is a background job with the full
    P0-validation-style surface (start/status/cancel/last/download composed under
    the router prefix), its rebuild SELF-VERIFIES the target pragmas (the ruled
    verify-before-trust probe), and the frontend panel calls the same composed
    routes (the 1c composed-route lesson)."""
    core = (_SRC / "monitoring" / "pagesize_bench.py").read_text(encoding="utf-8")
    api = (_SRC / "api" / "diagnostics.py").read_text(encoding="utf-8")
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")

    for marker in ("BenchVerifyError", "PRAGMA page_size", "PRAGMA tgt.cipher_page_size",
                   "sqlcipher_export", "VACUUM INTO", "sweep_stale_stages"):
        assert marker in core, f"pagesize_bench core lost its {marker!r} mechanism"
    assert 'APIRouter(prefix="/api/diagnostics"' in api
    for decorator in ('@router.post("/pagesize-bench")',
                      '@router.get("/pagesize-bench/status")',
                      '@router.post("/pagesize-bench/cancel")',
                      '@router.get("/pagesize-bench/last")',
                      '@router.get("/pagesize-bench/download")'):
        assert decorator in api, f"missing endpoint {decorator}"
    assert '"pagesize-bench", "page-size A/B bench (DB-10)"' in api, "job not registered"
    # The frontend must call the COMPOSED routes (prefix + decorator), never a drifted path.
    for url in ("/api/diagnostics/pagesize-bench", "/api/diagnostics/pagesize-bench/status",
                "/api/diagnostics/pagesize-bench/cancel",
                "/api/diagnostics/pagesize-bench/download"):
        assert url in js, f"frontend does not call {url}"


def test_agenda_dated_instances_place_in_their_own_year_and_show_provenance():
    """Maintainer field report 2026-07-17: three contradictory moon states on one
    day. Root cause: mapImportedToAgenda/mapDeducedToAgenda filled month/day (the
    ANNUAL-RULE placement keys) from the instance's real date, ghosting every dated
    instance into every displayed year (each year's moon phases drift ~11 days; a
    2025 movable feast projected onto 2026). Dated instances place via
    next_occurrence ONLY. Plus: imported events must name their feed (visible
    provenance — "the source should be clear")."""
    app = (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")

    imported = app.split("function mapImportedToAgenda")[1].split("function mapDeducedToAgenda")[0]
    deduced = app.split("function mapDeducedToAgenda")[1][:1600]  # the mapper body
    for name, body in (("mapImportedToAgenda", imported), ("mapDeducedToAgenda", deduced)):
        assert "month: null" in body and "day: null" in body, \
            f"{name} must not fill the annual-rule month/day keys"
        assert "+d.slice(5, 7)" not in body and "+d.slice(8, 10)" not in body, \
            f"{name} must not derive annual placement from the instance date"

    # Visible provenance: the feed-directory resolver + the from-pill in agRow.
    assert "_agFeedById" in app
    assert "Calendar feed(s) this event came from:" in app


def test_rate_mode_knob_in_top_bar_and_maximum_default():
    """Maintainer ruling 2026-07-23 (field feedback item 7): the bandwidth governor
    defaults to "maximum" (the old 500 KiB/s target deliberately parked workers —
    field-observed as a few kB/s on real connections), and the top bar carries a
    pretty gauge KNOB (#rate-toggle) toggling maximum <-> target with one click.
    The knob is a LOOPBACK settings write (PUT /api/scheduler/config, no egress
    side effect) so it must NOT be gated by ensureOnline; state paints via the
    accent .rate-max class + the needle rotation, and the Settings speed slider
    stays in sync via applySchedConfig."""
    html = _ui_source()
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    settings_src = (_SRC / "scheduler" / "settings.py").read_text(encoding="utf-8")

    # Backend default: maximum (target mode + its 500 KiB/s knob stay available).
    assert 'collect_rate_mode: str = "maximum"' in settings_src, (
        "the governor's default rate mode is 'maximum' (2026-07-23 ruling)"
    )

    # The knob exists in the top bar, before the airplane button, with the needle.
    assert 'id="rate-toggle"' in html and 'id="rate-needle"' in html
    assert html.index('id="rate-toggle"') < html.index('id="net-toggle"')

    # Wiring: toggle PUTs ONLY the rate mode, paints state, syncs the Settings
    # slider; boot loads the live state; the accent class is theme-derived CSS.
    assert "function toggleRateMode" in app and "function loadRateMode" in app
    assert '"rate-max"' in app, "the accent state class must be painted by _paintRateMode"
    assert "collect_rate_mode: next" in app, "the toggle PUTs only the rate mode"
    assert "loadRateMode();" in app, "boot must paint the knob's real state"
    fn = app.split("async function toggleRateMode", 1)[1].split("async function", 1)[0]
    assert "ensureOnline" not in fn, (
        "a loopback config write must never demand the network-consent popup"
    )
    assert "applySchedConfig(c)" in fn, "the Settings speed slider must stay in sync"
    css = (_SRC / "static" / "app.css").read_text(encoding="utf-8")
    assert "#rate-toggle.rate-max" in css and "var(--accent)" in css.split(
        "#rate-toggle.rate-max", 1
    )[1][:200], "the maximum state paints with the theme accent (never a hardcoded hue)"


def test_font_size_slider_has_an_accessible_label():
    """GUI-test finding font-size-slider-missing-label (P0, axe: label, critical):
    the Settings > Graphics 'Text size' range slider (#dr-font) had its visible label
    text sitting in a plain, unassociated <div class="sl">, so a screen-reader user
    tabbing to the slider heard only "slider, 88 to 124" with no indication of what it
    controls. Fixed by turning the wrapping element into a real <label for="dr-font">
    (same visual result via the unchanged .sl class; a <label> may wrap other markup
    like the live-percentage <span>), matching this file's own established convention
    for range sliders (see #mm-size / #sch-speed, both driven by a <label for=...>)."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    assert '<label class="sl" for="dr-font">' in html, \
        "the Text-size label must be a real <label for=\"dr-font\">, not a bare div"
    # The old, unassociated markup must be gone from directly before the input.
    assert '<div class="sl">Text size' not in html, \
        "the old unassociated <div class=\"sl\">Text size...</div> must not survive"


def test_analysis_tab_restore_runs_before_the_deep_link_hydration():
    """GUI-test finding analysis-boot-race-destroys-tab-workspace (P1): opening the
    omnibar in successive NEW browser tabs never accumulated a multi-tab analysis
    workspace -- every fresh tab showed only the one query it was just seeded with.
    Root cause: _anRestoreTabs() (restores the PERSISTED oo.an.tabs.v1 tab strip) ran
    AFTER the ?corpus=/?analyze= deep-link hydration IIFE, whose _anSpawn() ->
    _anActivate() -> _anSaveTabs() OVERWRITES that same localStorage key with only the
    just-spawned tab before the restore ever reads it. Fix: restore FIRST, so the
    deep-linked seed is ADDED (via _anSpawn's dedup-by-key reuse) to the restored set
    instead of clobbering it."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    restore_at = app.index("_anRestoreTabs();")
    hydrate_at = app.index("(function _hydrateCardCorpus() {")
    assert restore_at < hydrate_at, \
        "_anRestoreTabs() must run BEFORE the _hydrateCardCorpus deep-link IIFE, " \
        "or a fresh-tab deep link clobbers the persisted multi-tab workspace"
    # The old post-hydration restore call site must not linger as a second call.
    assert app.count("_anRestoreTabs();") == 1, \
        "_anRestoreTabs() must be called exactly once at boot (no duplicate call site)"


def test_corpus_window_open_is_debounced_against_double_clicks():
    """GUI-test finding corpus-open-dblclick-duplicate-tabs (P1): a fast double-click
    on a card/keyword that opens its corpus in a new tab (openCardCorpus /
    openAnalysisInNewTab) fired window.open() twice, leaving two duplicate browser
    tabs for the same corpus. Fixed with a shared _openCorpusUrlOnce() debounce (a
    same-URL open within 700ms is swallowed) that both call sites route through
    instead of calling window.open() directly."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function _openCorpusUrlOnce(url)" in app, "the shared debounce helper must exist"
    debounce_fn = app.split("function _openCorpusUrlOnce(url) {", 1)[1].split("\n    }\n", 1)[0]
    assert "_lastCorpusOpenUrl" in debounce_fn and "_lastCorpusOpenAt" in debounce_fn
    assert "700" in debounce_fn, "the debounce window must be present"
    assert "window.open(url" in debounce_fn, "the helper must still perform the real open"

    for fn_name in ("openCardCorpus", "openAnalysisInNewTab"):
        body = app.split(f"function {fn_name}(", 1)[1].split("\n    }\n", 1)[0]
        assert "_openCorpusUrlOnce(" in body, \
            f"{fn_name} must route its window.open through the shared debounce"
        assert "window.open(" not in body, \
            f"{fn_name} must not call window.open directly (bypasses the debounce)"


def test_saving_unrelated_settings_never_silently_overwrites_a_named_theme():
    """GUI-test finding theme-select-lossy-overwrite (P1): the Settings -> General
    panel's #set-theme select is a lossy 3-way dark/light/system BUCKET of the full
    17/18-theme value (Settings -> Graphics is the authoritative picker). saveSettings()
    used to unconditionally re-apply that bucket's plain default on EVERY Save click --
    so picking "Midnight" in Graphics, then saving an unrelated preference in General
    (e.g. the result-limit), silently collapsed the theme back to plain "ink". Fixed by
    tracking which bucket syncThemeSelect() last assigned (_lastSyncedThemeBucket) and
    only re-applying the select's value in saveSettings() when it has actually CHANGED
    since -- i.e. the user picked a different bucket in General themselves."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "_lastSyncedThemeBucket" in app, "the last-synced-bucket tracker must exist"

    sync_fn = app.split("function syncThemeSelect() {", 1)[1].split("\n    }\n", 1)[0]
    assert "_lastSyncedThemeBucket = bucket" in sync_fn, \
        "syncThemeSelect() must record the bucket it just assigned"

    save_fn = app.split("async function saveSettings() {", 1)[1].split("\n    }\n", 1)[0]
    assert '$("set-theme").value !== _lastSyncedThemeBucket' in save_fn, \
        "saveSettings() must gate the theme re-apply on an ACTUAL change to the select"
    # The unconditional call this fix replaced must not linger as an unguarded duplicate.
    unconditional = 'setTheme({dark:"ink", light:"light", system:"system"}[$("set-theme").value] || "ink");'
    assert save_fn.count(unconditional) <= 1, \
        "the theme re-apply must not run unconditionally anywhere in saveSettings()"
    if unconditional in save_fn:
        guard_at = save_fn.index('$("set-theme").value !== _lastSyncedThemeBucket')
        call_at = save_fn.index(unconditional)
        assert guard_at < call_at, "the guard must wrap the call, not merely precede it unrelatedly"

    # loadSettings()'s first-run seeding (guarded by the localStorage check) is
    # DELIBERATELY untouched by this fix -- it must stay exactly as guarded.
    load_fn = app.split("async function loadSettings() {", 1)[1].split("\n      } catch", 1)[0]
    assert 'if (!localStorage.getItem(UI_KEY)) {' in load_fn, \
        "loadSettings()'s guarded first-run theme seed must survive unmodified"
    guard_at = load_fn.index("if (!localStorage.getItem(UI_KEY)) {")
    seed_at = load_fn.index('setTheme({dark:"ink", light:"light", system:"system"}[s.theme] || "ink")')
    sync_at = load_fn.index("syncThemeSelect();")
    assert guard_at < seed_at < sync_at, \
        "the first-run seed must stay wrapped by its localStorage guard, before syncThemeSelect()"


def test_popstate_closes_every_open_dialog():
    """GUI-test finding imp-ghost-modal-after-back (P1): no popstate listener anywhere
    closed an open <dialog> -- browser Back while e.g. #ux-export was open left the tab
    underneath repainted while the dialog's native modal top-layer backdrop stayed
    active, blocking every click with no visual cue (only Escape recovered). Fixed with
    one shared popstate listener that closes EVERY open <dialog> via the native
    mechanism, not a hardcoded id list -- so it covers every dialog in the app, present
    and future.

    A bare .close() alone was insufficient -- an adversarial skeptic pass on this
    fix (mandatory for a shared-infrastructure change) found it would ORPHAN
    #net-consent's ensureOnline() Promise forever (per the <dialog> spec, .close()
    fires only "close", never "cancel"; that Promise resolves ONLY via its ok/cancel
    click handlers or dlg.oncancel) and skip #guide-wizard's closeGuide bookkeeping
    (wired to "cancel" too). Fixed by dispatching a synthetic "cancel" event (the
    same signal Escape sends) BEFORE the force-close, so every dialog's own
    resolve/cleanup path runs first."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert 'new Event("cancel", {cancelable: true})' in app, \
        "a synthetic cancel must be dispatched so each dialog's own resolve/cleanup runs"
    assert 'document.querySelectorAll("dialog[open]").forEach((d) => {' in app, \
        "a popstate handler must act on every open <dialog>, not a hardcoded subset"
    close_all_at = app.index('document.querySelectorAll("dialog[open]").forEach((d) => {')
    handler_block = app[close_all_at:close_all_at + 300]
    assert 'd.dispatchEvent(new Event("cancel"' in handler_block, \
        "the cancel dispatch must happen inside the per-dialog forEach callback"
    assert "d.close();" in handler_block, \
        "the dialog must still be force-closed after the cancel dispatch"
    dispatch_at = handler_block.index("d.dispatchEvent(")
    close_at = handler_block.index("d.close();")
    assert dispatch_at < close_at, \
        "cancel must be dispatched BEFORE the force-close, so listeners see it first"
    preceding = app[max(0, close_all_at - 250):close_all_at]
    assert 'window.addEventListener("popstate"' in preceding, \
        "the close-every-dialog call must be wired directly to a popstate listener"

    # Every dialog present in the markup must be reachable by the generic selector
    # (a plain <dialog id=...>, never something that would escape "dialog[open]").
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    dialog_ids = re.findall(r'<dialog id="([\w-]+)"', html)
    assert len(dialog_ids) >= 8, "sanity: expected several <dialog> elements in the markup"
    for did in dialog_ids:
        assert f'<dialog id="{did}"' in html, did


def test_api_error_handles_a_pydantic_validation_array_detail():
    """GUI-test finding ins-convergence-window-cap-mismatch (P1, the api() half): a
    FastAPI/Pydantic 422 response body's `detail` is an ARRAY of {type, loc, msg}
    objects, which `new Error(...)` string-coerces into the useless
    "[object Object],[object Object]" -- this is the SHARED error path for
    essentially every call made through api(), so the fix must not be scoped
    narrowly to one endpoint. Fixed via a small _apiErrorMessage(data, res) helper:
    an Array detail is joined from each item's .msg (or JSON.stringify as a
    fallback); a plain string detail (or none at all) must render BYTE-IDENTICALLY
    to the old expression."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function _apiErrorMessage(data, res)" in app, "the shared helper must exist"
    fn = app.split("function _apiErrorMessage(data, res) {", 1)[1].split("\n    }\n", 1)[0]
    assert "Array.isArray(d)" in fn, "it must specifically branch on an Array detail"
    assert "item.msg" in fn and "JSON.stringify(item)" in fn, \
        "array items must prefer .msg, falling back to JSON.stringify"
    assert 'res.status + " " + res.statusText' in fn, \
        "the no-detail-at-all fallback (status + statusText) must be preserved"

    # The throw site must route through the helper, not the old inline expression.
    assert "throw new Error(_apiErrorMessage(data, res));" in app, \
        "the !res.ok throw must call the shared helper"
    assert 'throw new Error((data && data.detail) || res.status + " " + res.statusText)' not in app, \
        "the old inline (never-Array-aware) expression must not linger as a duplicate"


def test_home_briefing_re_renders_on_language_switch():
    """GUI-test finding home-lead-title-frozen-locale (P1): the 'oo:langchange'
    listener re-rendered the world map / sources table / airplane-button title /
    AI-prompt editor on a language switch, but never re-rendered the Home briefing
    (renderBriefing, which also calls renderCorpusTier internally) -- so any
    OOI18N.tf()-built Home Lead-card title stayed frozen in whatever locale was
    active when it last rendered. Fixed by re-fetching+re-rendering the briefing
    in that same listener, gated on _lastBriefGen (only once the briefing has
    actually loaded at least once, so a fresh boot never fires an unnecessary
    fetch before Home was ever opened)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    listener = app.split('document.addEventListener("oo:langchange", () => {', 1)[1] \
                  .split("\n    });\n", 1)[0]
    assert "_lastBriefGen !== null" in listener, \
        "the re-render must be gated on the briefing having actually loaded once"
    assert "loadBriefing()" in listener, \
        "the langchange listener must re-fetch+re-render the Home briefing"


def test_insights_landscape_kind_group_labels_are_translated():
    """GUI-test finding insights-landscape-headers-hardcoded (P1): _KIND_GROUPS
    built label:"Themes"/"Other entities"/"People"/"Orgs"/"Places" and injected
    ${g.label} with no t() wrapper anywhere in loadLandscape() -- so the Insights
    -> landscape column headers stayed hardcoded English regardless of the active
    UI language. Fixed by wrapping the label in esc(t(...)), matching the
    surrounding code's escaping convention, plus keying the 4 labels that were not
    already translatable ("Places" alone already had a key) across all 12 locales."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    fn = app.split("async function loadLandscape(force) {", 1)[1].split("\n    }\n", 1)[0]
    assert "esc(t(g.label))" in fn, \
        "the column header must render through esc(t(...)), matching the surrounding code"
    assert re.search(r"\bconst t = \(window\.OOI18N", fn), \
        "loadLandscape() must declare the local t() alias like every other renderer"

    import json
    en = json.loads((_SRC / "static" / "locales" / "en.json").read_text(encoding="utf-8"))
    for label in ("People", "Orgs", "Other entities", "Themes", "Places"):
        assert label in en, f"{label!r} must be a keyed, translatable string"


def test_home_glance_panel_is_excluded_from_the_i18n_dom_walker():
    """GUI-test finding home-i18n-mixed-language-glance (P1): the i18n DOM-walker
    caches each text node's FIRST-SEEN value as "the original English" in a
    WeakMap; renderHomeStats()/renderCorpusTier()/renderHomeStatus() rebuild
    #home-stats/#home-tier/#home-status DIRECTLY via t() calls (correctly, for
    whatever language is active at that instant) -- but if the debounced
    MutationObserver's own apply() pass ever fires AFTER one of those renders, it
    permanently caches that ALREADY-TRANSLATED string as the node's "original",
    poisoning every future lookup for that node under every OTHER language (an
    Arabic-rendered node never matches a French map again). Fixed by marking the
    whole .home-glance panel data-i18n-dyn (the existing attribute-level opt-out
    convention, extended to text nodes) so the DOM-walker never touches or caches
    anything inside it -- those renderers already translate themselves."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<div class="panel home-glance"[^>]*\bdata-i18n-dyn\b', html), \
        ".home-glance must be marked data-i18n-dyn so its self-translating children " \
        "are never cached/poisoned by the DOM-walker"

    i18n_js = (_SRC / "static" / "i18n.js").read_text(encoding="utf-8")
    do_text_fn = i18n_js.split("function doText(n) {", 1)[1].split("\n  }\n", 1)[0]
    assert 'p.closest("[data-i18n-dyn]")' in do_text_fn, \
        "doText() must skip (never cache) text nodes inside a data-i18n-dyn ancestor"
    # The skip must come BEFORE the first-seen-wins cache write, or it's a no-op.
    skip_at = do_text_fn.index('p.closest("[data-i18n-dyn]")')
    cache_at = do_text_fn.index("origText.set(n, o)")
    assert skip_at < cache_at, \
        "the data-i18n-dyn skip must run BEFORE the node is ever cached"


def test_hazard_caveat_is_translated_across_all_locales():
    """GUI-test finding hazard-caveat-untranslated (P1): the Home hazard-lens
    disclosure box's long explanatory paragraph (server-emitted ALERT_CAVEAT,
    src/analytics/alerts.py) had ZERO matching key in ar/fr/de/es/zh/ja (0/6
    hit on the exact English source string) -- so only the short "Alerts"
    headline translated; the caveat itself always rendered in English regardless
    of locale, since the i18n DOM-walker can only translate a dynamically-
    injected server string when it exactly matches a known key. Fixed by adding
    the missing key + AI-drafted translation (flagged for native review, per the
    project's standing convention) across all 12 locale files."""
    alerts_py = (_SRC / "analytics" / "alerts.py").read_text(encoding="utf-8")
    assert "ALERT_CAVEAT = (" in alerts_py, "the server-side caveat constant must exist"
    caveat = alerts_py.split("ALERT_CAVEAT = (", 1)[1].split(")\n", 1)[0]
    # Reconstruct the exact Python-concatenated string the same way Python would.
    import ast
    key = ast.literal_eval("(" + caveat + ")")
    assert key.startswith("This layer never invents urgency."), \
        "sanity: the extracted caveat text must be the expected string"

    import json
    locales_dir = _SRC / "static" / "locales"
    for lang in ("en", "ar", "bn", "de", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        data = json.loads((locales_dir / f"{lang}.json").read_text(encoding="utf-8"))
        assert key in data, f"{lang}.json is missing the hazard-caveat key"
        assert data[key], f"{lang}.json has an empty translation for the hazard-caveat key"


def test_severe_contrast_findings_fixed_across_all_17_themes():
    """GUI-test findings pillwarn-severe-contrast + chip-button-color-contrast (both
    P1, axe colour-contrast): (1) .pill.warn and .nav-item.adv .badge rendered their
    text in var(--warn) directly -- a colour tuned for dot/border ACCENTS, not body
    text -- measuring as low as 1.87:1 on Dawn/Paper/Solar. (2) button/a.btnlike/
    .an-facet[aria-pressed="true"] render white text (the OLD --accent-fg default)
    on an accent-coloured background, measuring 2.89:1 on the default "ink" theme
    alone. Fixed by (1) a dedicated --warn-fg text-safe colour (mirroring the
    existing --caveat pattern: --warn itself is untouched for non-text dot/border
    uses) and (2) changing the DEFAULT --accent-fg to a near-black, with the
    themes that already passed with white (light/paper/mint) and the one other
    failing theme (dawn) pinning their own explicit override so the default change
    never silently regresses an already-passing theme. This test recomputes the
    real WCAG contrast ratio (mirroring the --lvl-group/--lvl-super precedent in
    test_circle_grammar_level_marking_is_wired_and_contrast_verified) for the
    ACTUAL rendering context of each fixed colour, across all 17 themes:
    --warn-fg against both .pill's background (--panel2) and the sidebar's
    background the .nav-item.adv .badge sits on (--bg2); --accent-fg against its
    own --accent (the button/.btnlike/.an-facet background)."""
    css = (_SRC / "static" / "app.css").read_text(encoding="utf-8")

    # Structural: --warn stays untouched for non-text uses; --warn-fg is the new,
    # separate text-safe colour used by the two fixed text contexts.
    assert re.search(r"--warn-fg\s*:\s*#[0-9a-fA-F]{3,6}", css), \
        "--warn-fg must exist as a real (non-color-mix) hex colour in :root"
    assert ".pill.warn{ color:var(--warn-fg)" in css.replace(" ", "") or \
        ".pill.warn{color:var(--warn-fg)" in css.replace(" ", ""), \
        ".pill.warn must render its text via --warn-fg, not --warn"
    assert ".nav-item.adv .badge { color:var(--warn-fg)" in css, \
        ".nav-item.adv .badge must render its text via --warn-fg, not --warn"

    # 17 themes: (accent, accent_fg [FINAL resolved value: root default or the
    # theme's own explicit override], panel2, bg2, warn_fg [FINAL resolved value]).
    themes = {
        "ink":       ("#5b9dd9", "#0a0f16", "#1b212b", "#0f1218", "#d9a441"),
        "slate":     ("#7aa2f7", "#0a0f16", "#1e2531", "#11151c", "#d9a441"),
        "midnight":  ("#8b7dff", "#0a0f16", "#171c3c", "#0b0e22", "#d9a441"),
        "terminal":  ("#36d97a", "#04140b", "#0e1619", "#06090c", "#d9a441"),
        "sepia":     ("#d8a657", "#241a0c", "#2f2820", "#201911", "#d9a441"),
        "contrast":  ("#ffd400", "#000000", "#161616", "#000000", "#ffd400"),
        "light":     ("#2f6fb3", "#ffffff", "#f3f5f9", "#e6eaf0", "#7a4308"),
        "paper":     ("#9a6a2f", "#ffffff", "#f1ebdc", "#ebe5d6", "#7a4308"),
        "arctic":    ("#88c0d0", "#0b1216", "#1e242c", "#12161b", "#d9a441"),
        "solar":     ("#b58900", "#002b36", "#0a4150", "#00313d", "#d9a441"),
        "forest":    ("#6fbf73", "#0a140b", "#19231a", "#0f150f", "#d9a441"),
        "aubergine": ("#c084fc", "#160e20", "#231b30", "#150f1d", "#d9a441"),
        "garnet":    ("#d96c7f", "#1c0d12", "#291a20", "#191014", "#d9a441"),
        "cyber":     ("#22d3ee", "#04121a", "#131830", "#090c15", "#d9a441"),
        "mist":      ("#5e81ac", "#0a0f16", "#eff2f6", "#e4e8ee", "#7a4308"),
        "dawn":      ("#b4637a", "#000000", "#f2e9e1", "#f4ece2", "#7a4308"),
        "mint":      ("#2e7d5b", "#ffffff", "#ecf2ed", "#e4ece6", "#7a4308"),
    }
    assert len(themes) == 17

    # Every hex value above must actually appear in the CSS as the resolved value
    # for that theme (catches a copy-paste slip in this test's own fixture data,
    # and catches a future colour edit that silently drifts from what's tested).
    root_block = css.split(":root {", 1)[1]
    depth = 1
    end = 0
    for i, ch in enumerate(root_block):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    root_block = root_block[:end]
    assert "--accent-fg:#0a0f16" in root_block.replace(" ", ""), \
        "the default --accent-fg must be the near-black fix value"
    assert "--warn-fg:#d9a441" in root_block.replace(" ", ""), \
        "the default --warn-fg must exist in :root"

    # normalise 3-digit shorthand (#fff) to 6-digit for comparison
    def _norm(h):
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return "#" + h.lower()

    for theme, (_, accent_fg, _, _, warn_fg) in themes.items():
        if theme == "ink":
            continue  # ink IS the :root default, already checked above
        sel = f'html[data-theme="{theme}"]'
        assert sel in css, f"theme selector {sel!r} must exist"
        block = css.split(sel, 1)[1].split("}", 1)[0]
        # accent-fg: either explicitly overridden (any hex incl. 3-digit shorthand),
        # or absent -> correctly falling through to the new :root default.
        m = re.search(r"--accent-fg\s*:\s*(#[0-9a-fA-F]{3,6})", block)
        resolved_accent_fg = m.group(1) if m else "#0a0f16"
        assert _norm(resolved_accent_fg) == _norm(accent_fg), (
            f"{theme}: expected resolved --accent-fg {accent_fg}, CSS resolves to "
            f"{resolved_accent_fg}"
        )
        m2 = re.search(r"--warn-fg\s*:\s*(#[0-9a-fA-F]{3,6})", block)
        resolved_warn_fg = m2.group(1) if m2 else "#d9a441"
        assert _norm(resolved_warn_fg) == _norm(warn_fg), (
            f"{theme}: expected resolved --warn-fg {warn_fg}, CSS resolves to "
            f"{resolved_warn_fg}"
        )

    def hx(h):
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    def rel_lum(rgb):
        r, g, b = rgb
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    def contrast(c1, c2):
        l1, l2 = rel_lum(hx(c1)), rel_lum(hx(c2))
        lighter, darker = max(l1, l2), min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)

    AA_TEXT_MIN = 4.5
    worst = 999.0
    for name, (accent, accent_fg, panel2, bg2, warn_fg) in themes.items():
        c_accent = contrast(accent_fg, accent)
        c_warn_panel2 = contrast(warn_fg, panel2)
        c_warn_bg2 = contrast(warn_fg, bg2)
        worst = min(worst, c_accent, c_warn_panel2, c_warn_bg2)
        assert c_accent >= AA_TEXT_MIN, (
            f"{name}: --accent-fg vs --accent (button/a.btnlike/an-facet text) = "
            f"{c_accent:.2f} < {AA_TEXT_MIN}:1"
        )
        assert c_warn_panel2 >= AA_TEXT_MIN, (
            f"{name}: --warn-fg vs --panel2 (.pill.warn text) = {c_warn_panel2:.2f} "
            f"< {AA_TEXT_MIN}:1"
        )
        assert c_warn_bg2 >= AA_TEXT_MIN, (
            f"{name}: --warn-fg vs --bg2 (sidebar .badge text) = {c_warn_bg2:.2f} "
            f"< {AA_TEXT_MIN}:1"
        )
    assert worst >= AA_TEXT_MIN  # sanity: the loop above already asserted every case

    # A nested de-emphasised count (e.g. a Home chip's article-count span) must
    # inherit the now-fixed button text colour rather than the page-level --muted
    # tone (calibrated for a PANEL background, not an accent-coloured button).
    assert re.search(
        r"button:not\(\.secondary\):not\(\.danger\):not\(\.ghost\):not\(\.lead-open\) \.muted,\s*"
        r"a\.btnlike \.muted,\s*"
        r"\.an-facet\[aria-pressed=\"true\"\] \.muted \{ color:inherit; \}",
        css,
    ), "a nested .muted count inside an accent-background control must inherit its parent's (fixed) text colour"


def test_evidence_links_underlined_and_use_the_shared_extlink_class():
    """GUI-test finding evidence-links-contrast-and-no-underline (P1, axe
    link-in-text-block): every outbound "source ↗" evidence link renders through
    the ONE shared extLink() chokepoint (invariant #6e) and relied on colour ALONE
    (accent text, no underline) to distinguish itself from surrounding body text --
    WCAG 1.4.1 requires more than colour for a link inside a text block. Fixed by
    always prefixing the "ext-link" class in extLink() and giving that class a
    permanent underline in CSS, removing the two inline text-decoration:none
    overrides that would otherwise have defeated it."""
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    css = (_SRC / "static" / "app.css").read_text(encoding="utf-8")

    fn = js.split("function extLink(url, label, cls, style) {", 1)[1].split("\n    }\n", 1)[0]
    assert '"ext-link"' in fn or "'ext-link'" in fn, \
        "extLink() must always attach the ext-link class regardless of the caller's own cls"
    assert "a.ext-link { text-decoration:underline" in css, \
        "the shared .ext-link class must render a permanent underline"

    # The two call sites that used to defeat the underline via an inline style
    # must no longer carry text-decoration:none.
    assert "text-decoration:none;align-self:center" not in js, \
        "no extLink() call site may re-introduce an inline text-decoration:none override"
    assert js.count('extLink(url, "Official / reference source ↗", "tiny secondary", "align-self:center")') >= 2, \
        "both temporal-map/insights source-link call sites must keep their style but drop the override"


def test_lead_card_flip_trigger_is_not_nested_inside_an_interactive_role():
    """GUI-test finding lead-card-nested-interactive (P1, axe nested-interactive):
    the outer Home Lead-card container was role="button" tabindex="0" while ALSO
    hosting genuinely interactive descendants (links/buttons on the back face once
    flipped) -- an invalid ARIA pattern (axe flagged 23 nodes). Fixed by making the
    outer container a plain role="group" wrapper (never itself interactive), moving
    the flip-trigger role/tabindex onto the FRONT face specifically (which has no
    interactive descendants of its own -- chip/heading/summary/sig-line/hint are
    all plain text), and giving the back's own "Back" hint its own small,
    explicitly-scoped <button> instead of relying on the whole (button/link-hosting)
    back face being itself a button."""
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    card_html = js.split("function cardHtml(", 1)[1].split("\n    function ", 1)[0]

    # The outer container is a plain, non-interactive group wrapper -- exact-string
    # match so no tabindex/onclick/role="button" can sneak back onto it.
    assert (
        '<div class="card bk-${esc(c.bucket)}" data-card="${c.id}" role="group" '
        'aria-label="${esc(_title)}">'
    ) in card_html, (
        'the outer .card container must be role="group" with NO tabindex/onclick '
        "(those now live on the front face specifically)"
    )

    # The front face (no interactive descendants of its own) carries the sole
    # flip-trigger role/tabindex/handlers, resolving the ancestor .card via closest().
    assert (
        'class="card-face card-front" tabindex="0" role="button" aria-label="${esc(_title)}"'
    ) in card_html, "the FRONT face must carry the flip-trigger role/tabindex"
    assert (
        "onclick=\"leadFlip(this.closest('.card'),event)\" "
        "onkeydown=\"leadFlipKey(this.closest('.card'),event)\""
    ) in card_html, "the front face's handlers must resolve to the ancestor .card via closest()"

    # The back's flip-back hint is now a real, explicitly-scoped <button> (not a
    # bare <span> that relied on an interactive-role ancestor it shared with other
    # buttons on the same face).
    assert (
        '<button class="lead-flip-hint back" onclick="leadFlip(this.closest(\'.card\'))">'
    ) in card_html, "the back's flip-back hint must be its own dedicated <button>"

    # Regression proof for the guard-defeats-itself trap: leadFlip's own
    # interactive-descendant guard (`ev.target.closest("button,a,input,label,
    # details,summary")`) would ALWAYS match a click whose event.target IS a
    # button -- so the Back button's own onclick call correctly OMITS the event
    # argument (falling through the "ev &&" guard check straight to the toggle)
    # rather than passing it and silently defeating its own click.
    lead_flip_fn = js.split("function leadFlip(card, ev) {", 1)[1].split("\n    }\n", 1)[0]
    assert 'ev.target.closest("button,a,input,label,details,summary")' in lead_flip_fn, \
        "sanity: leadFlip's interactive-descendant guard must still exist"
    assert "leadFlip(this.closest('.card'))" in card_html and \
        "leadFlip(this.closest('.card'),event)" in card_html, (
        "the Back button must call leadFlip WITHOUT an event arg (bypassing its own "
        "guard, which would otherwise match the button being clicked); the front "
        "face must still pass the event (so its OWN interactive-descendant guard "
        "keeps protecting the flip from stray clicks bubbling up from elsewhere)"
    )


def test_governments_law_pointer_shows_both_tracked_and_baselined():
    """GUI-test finding governments-law-pointer-misleading-zero-tracked (P1): the
    Governments -> Countries subtab's always-visible '(scales) Law: N tracked · M
    changes' discoverability pointer labelled /api/law/status's `tracked` field as
    the total tracked-document count, but that field server-side counts only
    documents WITH A COMPLETED BASELINE (`LawDocument.baseline_text IS NOT NULL`)
    -- reading '0 tracked' on a corpus with 23 real documents being watched across
    8 jurisdictions, before any online pass has run a baseline. One click away, the
    Law subtab uses the SAME API response correctly ('23 documents tracked · 0
    baselined'). Since the two concepts are legitimately distinct, the pointer now
    shows BOTH numbers, matching that established wording exactly rather than
    collapsing to one misleading word."""
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    fn = js.split("async function loadLawPointer() {", 1)[1].split("\n    }\n", 1)[0]

    # documents (the real tracked-document count) and tracked (the API's own,
    # baseline-only field) are BOTH read and BOTH shown, distinctly labelled.
    assert "s.documents" in fn, "the pointer must read the real tracked-document count"
    assert "baselined: s.tracked" in fn, (
        "the API's `tracked` field (baseline-only) must be relabelled 'baselined' "
        "in the pointer, matching the Law subtab's own established wording"
    )
    assert (
        'tf("Law: {documents} tracked · {baselined} baselined · {changes} changes"'
    ) in fn, "the pointer must show both numbers, distinctly labelled"
    # The stale, misleading single-word template must not linger as the live text.
    assert 'tf("Law: {tracked} tracked · {changes} changes"' not in fn, (
        "the old collapsed-to-one-word template must no longer be used live"
    )

    import json

    new_key = "Law: {documents} tracked · {baselined} baselined · {changes} changes"
    locales_dir = _SRC / "static" / "locales"
    for lang in ("en", "ar", "bn", "de", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        data = json.loads((locales_dir / f"{lang}.json").read_text(encoding="utf-8"))
        assert data.get(new_key), f"{lang}.json is missing the new law-pointer template key"


def test_convergence_window_input_max_matches_the_backend_cap():
    """GUI-test finding ins-convergence-window-cap-mismatch (P1, the <input> max
    half -- the api()-error-message half already shipped in Phase 5): the
    Insights -> Convergence 'Window (days)' input's HTML max="3650" invited a
    value the backend (GET /api/insights/convergences, window_days: Query(...,
    le=90)) would reject with a 422 -- reproduced live, entering 365 (well within
    the field's own stated range) surfaced a confusing error. The input's max now
    matches the real backend cap exactly, so the field never invites a value it
    will refuse."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    api_py = (_SRC / "api" / "insights.py").read_text(encoding="utf-8")

    m = re.search(r'id="cv-window"[^>]*\bmax="(\d+)"', html)
    assert m, "the #cv-window input must exist with a max attribute"
    html_max = int(m.group(1))

    # Several endpoints in this file declare their own "window_days: int = Query(...)"
    # with DIFFERENT le= caps (30/365/90) -- scope the search to the /convergences
    # endpoint specifically, not the first occurrence in the whole file.
    fn_src = api_py.split("def insights_convergences(", 1)[1].split("\ndef ", 1)[0]
    m2 = re.search(r"window_days:\s*int\s*=\s*Query\([^)]*\ble=(\d+)", fn_src)
    assert m2, "the /convergences endpoint's window_days Query(...) le= cap must exist"
    backend_max = int(m2.group(1))

    assert html_max == backend_max, (
        f"#cv-window's max ({html_max}) must equal the backend's real cap "
        f"({backend_max}) so the field never invites a value the API will reject"
    )


def test_trends_and_map_kind_selects_offer_only_functional_options():
    """GUI-test finding ins-kind-filter-nonfunctional-options (P1): the Insights ->
    Trends (#trd-kind) and the legacy Map tab's (#map-kind) 'Kind' selects both
    still listed person/orgs/places options the extractor never assigns --
    GET /api/insights/map?kind=person returned honestly-empty {countries:[],
    cities:[]} on the identical corpus/window that kind="" populated. The sibling
    Families subtab's own #fam-kind select already restricts itself to functional
    kinds and shows an explicit honesty hint explaining why; both selects now
    match that established pattern instead of offering a fabricated, always-empty
    choice."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")

    for sel_id in ("trd-kind", "map-kind"):
        block = html.split(f'id="{sel_id}"', 1)[1].split("</select>", 1)[0]
        for bad in ("person", "org", "location"):
            assert f'value="{bad}"' not in block, (
                f"#{sel_id} must not offer the non-functional '{bad}' option "
                "(the extractor never assigns it)"
            )
        assert 'value=""' in block and 'value="term"' in block and 'value="entity"' in block, (
            f"#{sel_id} must keep its functional options (all/term/entity)"
        )

    # Both selects carry the same honesty hint Families already established.
    hint = (
        "person / org / location kinds await a future NER/gazetteer pass — the "
        "extractor does not yet assign them, so they are not offered here rather "
        "than shown as a fabricated, always-empty choice."
    )
    assert html.count(hint) >= 3, (
        "the honesty hint must appear for Families (already shipped) AND both "
        "newly-fixed selects (Trends + the legacy Map tab)"
    )


def test_home_recent_panel_unhides_on_error_too():
    """GUI-test finding home-recent-panel-hidden-on-error (P1): loadHomeRecentList()'s
    catch(e) branch wrote an honest error message into the panel's own inner box
    but never cleared #home-recent-panel's own `hidden` attribute (the static
    markup starts `<section ... id="home-recent-panel" hidden>`, and only the two
    SUCCESS paths -- the honest empty state and the populated rows -- toggled it
    visible) -- so a genuine fetch failure silently disappeared instead of showing
    its own honest message."""
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    fn = js.split("async function loadHomeRecentList(tag) {", 1)[1].split("\n    }\n", 1)[0]

    catch_block = fn.split("} catch (e) {", 1)[1]
    assert "panel.hidden = false;" in catch_block, (
        "the catch branch must clear panel.hidden too, matching both success paths"
    )
    # sanity: the error message is still written into the panel's own inner box.
    assert "box.innerHTML" in catch_block


def test_chart_enlarge_note_refreshes_on_scale_toggle():
    """GUI-test finding mkt-002-stale-caveat-scale-toggle (P1): the Commodities
    enlarge dialog's dynamic scale hint (Absolute/Indexed/Log) updated correctly
    on toggle, but a SEPARATE static caption (#chart-enlarge-note, set once at
    dialog-open time from the caller's own caveat -- for the family-stacked
    Commodities view, a fixed 'Indexed to 100 at the window start…' string) never
    refreshed, so switching to Absolute or Log left it directly contradicting the
    now-accurate dynamic hint a few lines above. The note now mirrors the same
    per-mode HINTS text inside the same render() the scale-toggle click handler
    calls, so the two can never disagree."""
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    fn = js.split("function chartEnlarge(title, seriesList, caveat, opts) {", 1)[1].split(
        "\n    function _chartEnlargeExtra", 1)[0]

    render_block = fn.split("const render = () => {", 1)[1].split("};", 1)[0]
    assert "hint.textContent = HINTS[mode]" in render_block, (
        "sanity: the dynamic hint's own per-mode refresh must still exist"
    )
    assert "note.textContent = HINTS[mode]" in render_block, (
        "the static note must refresh to the SAME per-mode text inside the same "
        "render() the scale-toggle click handler calls"
    )
    # The click handler's only job is to update `mode` then call render() -- the
    # note refresh must live INSIDE render(), not be a second, separately-wired
    # update that could drift out of sync again.
    click_block = fn.split('ctl.addEventListener("click", (e) => {', 1)[1].split("});", 1)[0]
    assert "note.textContent" not in click_block, (
        "the note refresh must live inside render(), reached via the single "
        "render() call at the end of the click handler -- not duplicated here"
    )
    assert "render();" in click_block


def test_worldmap_fullscreen_targets_host_so_legend_and_caveat_stay_visible():
    """GUI-test finding worldmap-fullscreen-hides-legend-caveat (P1): the World
    map's fullscreen button targeted .oomap-wrap specifically (the SVG + in-map
    controls) via requestFullscreen(), but .oomap-legend, the method hint, and the
    caveat div are SIBLINGS of .oomap-wrap, not descendants -- a fullscreen
    element shows only its own subtree, so the browser natively hid all three
    while fullscreen. `host` (the caller's dedicated map container, e.g.
    #oo-coverage-map) already wraps .oomap-wrap AND .oomap-legend AND the method/
    caveat and nothing unrelated, so fullscreen now targets `host` instead."""
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    fn = js.split("function _wireOoMap(host, opts) {", 1)[1].split("\n    function ", 1)[0]

    # The three fullscreen call sites must all resolve against `host` directly,
    # never re-query .oomap-wrap as a narrower fullscreen target.
    assert "document.fullscreenElement === host" in fn
    assert "host.requestFullscreen" in fn
    assert 'host.querySelector(".oomap-wrap")' not in fn, (
        "fullscreen must no longer target the narrower .oomap-wrap div"
    )

    # Sanity: .oomap-legend/method/caveat really are siblings of .oomap-wrap under
    # `host` (never descendants of it) -- confirms `host` is the correct wider
    # container and this isn't fixing a problem that doesn't exist.
    render_fn = js.split('host.innerHTML = `<div class="oomap-wrap"', 1)[1].split(
        "host._ooSigVisible", 1)[0]
    assert 'class="oomap-legend"' in render_fn
    wrap_region = render_fn.split("</div>", 1)[0]
    assert 'class="oomap-legend"' not in wrap_region, (
        "sanity: .oomap-legend must be OUTSIDE the first (.oomap-wrap) closing div"
    )


def test_markdown_bold_span_survives_a_source_line_break():
    """GUI-test finding help-md-linebreak-bug (P1): mdToHtml()'s paragraph AND
    blockquote handling called its inline-emphasis formatter PER RAW SOURCE LINE
    (buf.map(inline).join(...)) before joining lines together, so a **bold**/
    *em*/[link]() span whose opening and closing markers land on different
    wrapped source lines was invisible to the per-line regex on BOTH lines --
    and could make a dangling opening marker mis-pair with a LATER, unrelated
    marker on the second line, producing a garbled, wrongly-placed <strong>
    (reported in USER_MANUAL.md and the Ethics doc, ~64 unrendered spans).
    Joining the raw lines into ONE string per paragraph/blockquote BEFORE
    running inline() lets the regex see the whole span regardless of which
    source line it was wrapped on."""
    js = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    fn = js.split("function mdToHtml(md) {", 1)[1].split("\n    function humanBytes", 1)[0]

    # Paragraphs: inline() must run on the WHOLE joined string, never per-line.
    assert "inline(buf.join(" in fn, (
        "flushPara must join the raw lines into one string BEFORE calling inline(), "
        "not call inline() per line and join the (already-processed) results"
    )
    assert "buf.map(inline)" not in fn, (
        "the old per-line inline() call (which could never see a span crossing "
        "two source lines) must be gone"
    )

    # Blockquotes: the SAME join-before-inline fix, but a quote's line breaks must
    # stay VISIBLE -- verified via the literal (non-raw-byte) six-character escape
    # sequence used as a placeholder that inline()/esc() can neither escape nor
    # accidentally match, swapped for a real <br> only AFTER inline() has run.
    assert "inline(q.join(" in fn, (
        "the blockquote handler must join its lines into one string BEFORE "
        "calling inline(), matching flushPara's fix"
    )
    assert "q.map(inline)" not in fn, (
        "the old per-line inline() call for blockquotes must be gone"
    )
    placeholder = chr(92) + "u0000"  # the literal 6-char escape sequence, computed
    assert placeholder in fn, (
        "the blockquote fix must use a real placeholder marker (never a plain "
        "space, which would also match every genuine space in the quoted text)"
    )

    # Byte-level sanity: the fix must be an ESCAPED source-text sequence, never an
    # actual embedded NUL byte in the file.
    raw_bytes = (_SRC / "static" / "app.js").read_bytes()
    assert b"\x00" not in raw_bytes, "app.js must never contain a literal NUL byte"

    # Runtime proof (mirrors mdToHtml's own regex set exactly): a bold span
    # spanning two lines renders as ONE correctly-wrapped <strong>, not a garbled
    # mis-pairing with an unrelated later marker on the second line.
    import re as _re

    def esc_(s):
        return _re.sub(r'[&<>"\']', lambda m: {"&": "&amp;", "<": "&lt;", ">": "&gt;",
                                                 '"': "&quot;", "'": "&#39;"}[m.group(0)], s)

    def inline_(t):
        t = esc_(t)
        t = _re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = _re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = _re.sub(r"(^|[^*])\*([^*]+)\*", r"\1<em>\2</em>", t)
        return t

    buf = ["Some **important text that", "continues here** and also **another** bold phrase."]
    buggy_per_line = " ".join(inline_(x) for x in buf)
    fixed_joined_first = inline_(" ".join(buf))
    assert "<strong> and also </strong>another**" in buggy_per_line, (
        "sanity: the OLD per-line approach really did mis-pair (proves this is a real bug)"
    )
    assert fixed_joined_first == (
        "Some <strong>important text that continues here</strong> and also "
        "<strong>another</strong> bold phrase."
    ), "the FIXED join-before-inline approach must correctly wrap both spans"


def test_docs_index_covers_live_docs():
    """docs/README.md must mention every top-level doc so a new file/folder never goes
    silently unindexed (PR #740/#744 remediation brief §4.2 -- the doc-hygiene reconciliation
    this test guards going forward). A file is checked by its exact filename; a directory is
    checked by "<name>/" so either a bare directory link or a link to a specific file inside
    it (e.g. "ledger/shipped.csv") satisfies the check."""
    docs_dir = _ROOT / "docs"
    index_text = (docs_dir / "README.md").read_text(encoding="utf-8")
    missing = []
    for entry in sorted(docs_dir.iterdir()):
        if entry.name == "README.md":
            continue
        needle = entry.name if entry.is_file() else f"{entry.name}/"
        if needle not in index_text:
            missing.append(entry.name)
    assert not missing, f"docs/README.md must reference every top-level doc; missing: {missing}"


def test_library_graphs_wired_and_downloaded_section_compressed():
    """S2 (2026-07-23 field-feedback workflow): the Library tab's bare live figures
    (sources/keywords/Wikipedia+law tracked counts) become small evolution graphs
    (reusing the EXISTING dashChartSvg + chartEnlarge helpers, invariant #16 —
    never a new visual language, never a larger tile), and the "Downloaded" section
    is compressed into the established collapsed-by-default <details class="adv-collect">
    disclosure (item 5). Wired via the /api/library/history endpoint (S2 backend)."""
    html = _ui_source()
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")

    # Three dedicated graph host sections exist in the Library tab, each with its
    # own panel (Activity / Wikipedia tracked / Law tracked -- item 5's ask for
    # OWN sections, not folded into the existing overview grid).
    for host_id in ("lib-activity-graphs", "lib-wiki-graphs", "lib-law-graphs"):
        assert f'id="{host_id}"' in html, f"missing Library graph host #{host_id}"

    # The Downloaded tiles are now inside a collapsed-by-default disclosure (the
    # same adv-collect convention Settings already uses for legacy/advanced
    # sections), not a permanently-open 9-tile grid.
    assert 'details class="adv-collect"' in app.split("function renderLibraryOverview", 1)[1].split(
        "\n    }\n", 1
    )[0], "the Downloaded tiles must be wrapped in a collapsed-by-default <details>"

    # Frontend wiring: each graph host has a dedicated render function, called
    # when the Library tab is shown, reusing dashChartSvg + chartEnlarge (no new
    # chart renderer) and fetching the real S2 endpoint.
    for fn in ("renderLibraryActivityGraphs", "renderLibraryWikiGraphs", "renderLibraryLawGraphs",
               "enlargeLibMetric"):
        assert f"function {fn}" in app, f"missing {fn}"
    assert "renderLibraryActivityGraphs(); renderLibraryWikiGraphs(); renderLibraryLawGraphs();" in app, (
        "the Library tab's show-dispatcher must render all three graph sections"
    )
    assert "dashChartSvg(series.map(" in app, "the small tile must reuse dashChartSvg, not a new renderer"
    assert "chartEnlarge(label" in app, "click-to-enlarge must reuse the existing chartEnlarge modal"
    assert "/api/library/history?metric=" in app


def test_library_qualification_tile_window_switcher_hide_flat_auto_log():
    """2026-07-24 field-feedback Session A §5: a 4-line source-qualification tile
    (counts only, never a score), a per-tile window switcher (ALL tiles share the
    same default window), hide-flat collapsing an all-zero/no-data series to a
    one-line note, and auto-log10 on a large cross-series spread — never
    multi-axis for same-unit series (the honest-viz dual-axis rejection)."""
    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    snap = (_SRC / "database" / "snapshots.py").read_text(encoding="utf-8")

    # backend: the 4 filtered metrics exist, aligned with database.py's own
    # qualification predicates (never two divergent definitions).
    for m in ("sources_qualified", "sources_disqualified", "sources_never_judged", "sources_candidates"):
        assert f'"{m}"' in snap, f"missing filtered snapshot metric {m}"
    assert "STATUS_QUALIFIED" in snap and "STATUS_DISQUALIFIED" in snap and "STATUS_UNQUALIFIED" in snap

    # frontend: the qualification tile, its 4 metrics, the window switcher, the
    # hide-flat check, and the auto-log gate all exist and are wired in.
    assert "function _libQualificationTile" in app
    assert "function enlargeLibQualification" in app
    for m in ("sources_qualified", "sources_disqualified", "sources_never_judged", "sources_candidates"):
        assert f'"{m}"' in app
    assert "_libQualificationTile(LIB_DEFAULT_DAYS)" in app, "the Activity section must render the qualification tile"
    # never a quality score — the enlarge caveat states counts-only explicitly.
    assert "never a quality score" in app

    # window switcher: one shared default, per-tile in-place re-render on click.
    assert "const LIB_WINDOWS = [[7," in app
    assert '"7d"' in app and '"30d"' in app and '"90d"' in app
    assert "function _libSetWindow" in app
    assert "onclick=\"_libSetWindow(" in app
    assert "const LIB_DEFAULT_DAYS = 30" in app
    # every render call site starts on the SAME default window (never a per-tile
    # divergent starting point) — articles_per_hour used to hardcode 7d.
    assert '"articles_per_hour", LIB_DEFAULT_DAYS' in app
    assert '"sources", LIB_DEFAULT_DAYS' in app
    assert '"wiki_pages", LIB_DEFAULT_DAYS' in app
    assert '"law_documents", LIB_DEFAULT_DAYS' in app

    # hide-flat: an all-zero/empty series collapses to a one-line note, both for
    # the single-metric tiles and the qualification tile.
    assert "function _libAllZero" in app
    assert "_libAllZero(series.map(p => p.n))" in app
    assert "_libAllZero(_libQualSeries.flatMap(" in app

    # auto-log (ruled): a shared axis; log10 only past a spread threshold, ALWAYS
    # labelled — never a silent switch, never a second (multi-)axis.
    assert "function _libQualSpread" in app
    assert "_libQualSpread(_libQualSeries) > 50" in app
    assert '"log scale"' in app
    assert "logY: _libQualSpread" in app  # the real ooChart opts.logY toggle, not a fake label

    # The 'slice-1c 404 lesson' (CLAUDE.md): the wiring test must COMPOSE the real
    # route (router prefix + decorator), never assert two literal strings side by
    # side. Mirrors tests/test_library_history.py::test_wiring_composes_the_real_route.
    lib_api = (_SRC / "api" / "library.py").read_text(encoding="utf-8")
    prefix_m = re.search(r'APIRouter\(prefix="([^"]+)"', lib_api)
    path_m = re.search(r'@router\.get\("(/history[^"]*)"', lib_api)
    assert prefix_m and path_m
    assert prefix_m.group(1) + path_m.group(1) == "/api/library/history"


def test_law_ai_change_summaries_are_a_labelled_linked_layer():
    """2026-07-24 field-feedback Session A §3 (ruled): an AI change summary is a
    LINKED layer over LawRevision (mirroring ArticleAnalysis's provenance shape —
    model + prompt_version + prompt_text), auto-generated for UI-language-floor
    jurisdictions and on-demand for the rest; NEVER the trusted diff/revision
    record, NEVER fed to keyword indexing. Guards the model, the API surface
    (id + ai_summary on both list/detail, the on-demand POST endpoint), and the
    frontend's 'AI-derived · unreliable' rendering + on-demand button."""
    models = (_SRC / "database" / "models.py").read_text(encoding="utf-8")
    assert "class LawRevisionSummary(Base):" in models
    lrs_body = models.split("class LawRevisionSummary(Base):", 1)[1].split("class ", 1)[0]
    for col in ("revision_id", "summary", "model", "prompt_version", "prompt_text"):
        assert col in lrs_body, f"LawRevisionSummary missing {col}"

    summarize_src = (_SRC / "law" / "summarize.py").read_text(encoding="utf-8")
    assert "def summarize_revision(" in summarize_src
    assert "def pending_ai_summaries(" in summarize_src
    assert "def advance_law_summaries(" in summarize_src
    assert "UI_LOCALE_CODES" in summarize_src  # gated on the 12 UI languages, not a hardcoded copy
    assert 'if not (revision.diff or "").strip():' in summarize_src  # never summarize a baseline

    # the corpus keyword pass must never read this table (the trusted-index guard).
    extract_src = (_SRC / "analytics" / "extract.py").read_text(encoding="utf-8")
    store_src = (_SRC / "analytics" / "store.py").read_text(encoding="utf-8")
    assert "LawRevisionSummary" not in extract_src and "LawRevisionSummary" not in store_src

    api = (_SRC / "api" / "law.py").read_text(encoding="utf-8")
    assert '"id": rev.id' in api  # law_changes exposes the revision id
    assert '"id": r.id' in api  # law_document's per-revision id, too
    assert '"ai_summary": _summary_dict(' in api
    prefix_m = re.search(r'APIRouter\(prefix="([^"]+)"', api)
    path_m = re.search(r'@router\.post\("(/revisions/\{revision_id\}/summarize)"\)', api)
    assert prefix_m and path_m
    assert prefix_m.group(1) + path_m.group(1) == "/api/law/revisions/{revision_id}/summarize"

    app = (_SRC / "static" / "app.js").read_text(encoding="utf-8")
    assert "function lawAiSummaryHtml(" in app
    assert "function lawSummarize(" in app
    assert "/api/law/revisions/${revId}/summarize" in app
    assert 'data-rev="${ch.id}"' in app
    # scheduler ride-along, gated + never blocking the scrape.
    runner = (_SRC / "scheduler" / "runner.py").read_text(encoding="utf-8")
    assert "from src.law.summarize import advance_law_summaries" in runner
    assert "sum_res = advance_law_summaries(session)" in runner


def test_law_tracking_budget_is_adaptive_not_a_fixed_five():
    """2026-07-24 field-feedback Session A §3 item 3 (ruled): auto_track_due's
    hardcoded batch=5/pass cannot baseline hundreds of documents once enumeration
    adapters land -- the per-pass budget now scales with the watched-document
    count, bounded both ways (unchanged on today's small corpus, capped so a
    large one never floods a single pass)."""
    track_src = (_SRC / "law" / "track.py").read_text(encoding="utf-8")
    assert "def adaptive_track_budget(" in track_src
    assert "batch: int | None = None" in track_src  # the OLD hardcoded default=5 is gone
    assert "batch = adaptive_track_budget(watched_count)" in track_src

    from src.law.track import adaptive_track_budget

    assert adaptive_track_budget(0) == 5
    assert adaptive_track_budget(23) == 5  # today's real corpus: byte-identical to the old default
    assert adaptive_track_budget(10_000) <= 25  # bounded -- never floods a single pass


def test_briefing_refresh_runs_in_a_background_thread_not_inline():
    """S4.1 duty-cycle fix (field-feedback 2026-07-23): refresh_briefing must NOT
    run synchronously inline at the tail of a collect pass — that blocked the very
    next pass's collection from starting until a single-core, whole-corpus
    recompute finished (measured as a major share of a maintainer-observed 3-8 min
    inter-pass gap on two different machines). Guard that the scheduler kicks it
    off via a dedicated async method with its own lock (non-overlapping, never
    queued) and that the pass itself no longer blocks on it -- see
    tests/test_briefing_duty_cycle.py for the full behavioural coverage."""
    runner = (_SRC / "scheduler" / "runner.py").read_text(encoding="utf-8")
    assert "def _refresh_briefing_async(self)" in runner
    assert "self._briefing_bg_lock" in runner and "self._briefing_thread" in runner
    # _refresh_briefing_async's OWN body: non-overlapping (a busy refresh is
    # skipped, never stacked/queued) and tracked in the task manager like the
    # other ride-alongs (world-discovery, qualification), not as a scheduler
    # phase — it can now genuinely overlap the next pass's own phase.
    async_body = runner.split("def _refresh_briefing_async(self)", 1)[1].split(
        "\n    def _default_run_once", 1
    )[0]
    assert "acquire(blocking=False)" in async_body
    assert 'tasks.register("briefing"' in async_body
    assert "threading.Thread(" in async_body and ".start()" in async_body

    # _default_run_once's OWN body: it calls the async kickoff, and never calls
    # refresh_briefing directly (the old synchronous inline call site is gone).
    pass_body = runner.split("def _default_run_once", 1)[1]
    assert "self._refresh_briefing_async()" in pass_body
    assert "refresh_briefing(" not in pass_body
    assert '_phase_set("briefing")' not in pass_body


def test_memory_headroom_honesty_never_projects_a_worker_count():
    """S4.3 (field-feedback 2026-07-23, 'memory-headroom honesty for small
    boxes'): a mem-low-capped pass must surface a REAL, MEASURED note (never a
    projected worker count computed from total RAM — that would be a fabricated
    capacity claim, exactly what the honesty non-negotiables forbid). Guard that
    the note derives from actually-observed governor back-offs, not a formula
    over total/available memory."""
    perf = (_SRC / "monitoring" / "collect_perf.py").read_text(encoding="utf-8")
    assert "self._mem_low_ticks" in perf and "self._mem_low_min_permits" in perf
    # The note is built from the OBSERVED minimum permits reached on a mem-low
    # tick, not a division/estimate over total_mb/mem_total_mb (never a
    # capacity formula).
    note_block = perf.split("memory_headroom_note = None", 1)[1].split(
        "return {", 1
    )[0]
    assert "self._mem_low_min_permits" in note_block
    assert "mem_total_mb" not in note_block and "total_mb" not in note_block
    # Always present in the payload, honestly None/0 when never observed —
    # never omitted (an omitted key would read as "not applicable" rather
    # than "did not happen").
    assert '"mem_low_ticks": self._mem_low_ticks' in perf
    assert '"mem_low_min_permits": self._mem_low_min_permits' in perf
    assert '"memory_headroom_note": memory_headroom_note' in perf
