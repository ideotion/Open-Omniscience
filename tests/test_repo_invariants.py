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


def test_no_hardcoded_secrets_in_live_src():
    offenders = []
    for p in _live_py_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _SECRET_RE.search(line) and not any(tok in line for tok in _SECRET_ALLOW):
                offenders.append(f"{p.relative_to(_ROOT)}:{i}")
    assert not offenders, f"possible hardcoded secrets: {offenders}"


def test_quarantine_not_imported_by_live_code():
    pattern = re.compile(r"\b(from|import)\s+quarantine\b|\bquarantine\.")
    offenders = [
        str(p.relative_to(_ROOT))
        for p in _live_py_files()
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"live code imports quarantined modules: {offenders}"


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
    named CLI helper functions of src/api/main.py (panic/ephemeral/serve), or
    in src/diagnostics.py (the `doctor` command, whose entire purpose is a
    printed terminal report). Anything else is a regression.
    """
    import ast

    CLI_MODULES = {"src/diagnostics.py"}
    CLI_FUNCTIONS = {"main", "_panic_cli", "_run_ephemeral", "_serve"}

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


def test_ui_invariants():
    """Maintainer-ruled UI invariants (see CLAUDE.md). These regressed once
    between sessions; now they fail CI instead of relying on memory."""
    html = (_SRC / "static" / "index.html").read_text(encoding="utf-8")
    # 1. Wikipedia edition picker is a dropdown, never a text input
    assert '<select id="wiki-lang"' in html, "wiki-lang must be a <select> (CLAUDE.md #1)"
    assert '<input id="wiki-lang"' not in html
    # 3. constant top-bar footprints
    assert ".act-host:empty { visibility:hidden; }" in html, "act-host slot must stay reserved"
    assert "#llm { min-width" in html, "LLM pill needs a fixed footprint"
    # 4. persistent vitals strip; no version in the chrome
    assert 'id="vitals-mini"' in html, "the compact vitals strip must exist"
    assert '<span id="version" hidden>' in html, "version stays out of the visible chrome"
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
    assert 'id="agenda-month"' in agenda_tab and 'id="agenda-view"' in agenda_tab, (
        "the agenda month grid + view switcher must exist in the tab"
    )
    assert 'return localStorage.getItem("oo.agenda.view") || "month"' in html, (
        "MONTH is the ruled default agenda view"
    )
    # 14. the network toggle is AIRPLANE-MODE (ruled 2026-06-12): one constant
    #     glyph whose FILL is the state — never ▶/⏸ action glyphs — and EVERY
    #     offline→online transition passes the ONE consent popup (local
    #     interface addresses; no public-IP echo before consent).
    assert 'id="net-plane"' in html and 'id="net-label"' in html, (
        "the network toggle must be the constant airplane glyph + label"
    )
    assert "▶ Online" not in html and "⏸ Offline" not in html, (
        "action glyphs must not label network STATE (CLAUDE.md #14)"
    )
    assert 'id="net-consent"' in html and "ensureOnline(" in html, (
        "every online transition must pass the consent popup"
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
    # 15. a PERMANENT language switcher lives in the top bar (ruled, RC gate):
    #     flag = visual convention only, the NATIVE NAME is the identifier;
    #     one click switches the whole UI via the one i18n engine.
    assert 'id="lang-switch"' in html and 'id="lang-menu"' in html, (
        "the permanent top-bar language switcher must exist (CLAUDE.md #15)"
    )
    assert "OOI18N.setLang(code)" in html, "the switcher must use THE i18n engine"
    for native in ("Français", "中文", "العربية", "Русский", "日本語"):
        assert native in html or native in open(
            _SRC / "static" / "index.html", encoding="utf-8"
        ).read(), f"native name {native!r} must appear in the menu data"
    # 16. ONE chart toolkit, detailed-curves SYSTEMATIC (ruled 2026-06-12):
    #     full series always (no thinning), sparse renders as honest points
    #     with the early-corpus caveat; wheel zoom / drag pan / pinned readout.
    assert "function ooChart(" in html, "the one chart toolkit must exist (CLAUDE.md #16)"
    assert "never downsampled" in html and "early corpus" in html, (
        "the toolkit must state and implement the detailed-curves rules"
    )
    for surface in ('ooChart($("mkt-chart-oo")', 'ooChart($("ins-trend-oo")'):
        assert surface in html, f"chart surface must use THE toolkit: {surface}"
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
    #      family subtab bar driven by THE universal component, with an "All cards"
    #      default lens and a per-family hue accent on cards.
    assert 'ooSubtabs($("home-fam-subtabs")' in html and "selectHomeFamily" in html, (
        "Home card families must use the universal subtab component (CLAUDE.md #18/#19)"
    )
    assert 'data-tab="__all"' in html and "All cards" in html, (
        "the family lens must default to an 'All cards' subtab (§5)"
    )
    assert "--fam:" in html, "cards must carry the family-hue left accent (§5)"
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
    # 21. Insights auto-indexes in the background (UI_SHELL_REDESIGN §6): the
    #     manual "Index corpus" button + palette action are gone; indexing follows
    #     ingest and a silent top-up clears any legacy backlog when Insights opens.
    assert "indexCorpus" not in html and ">Index corpus<" not in html, (
        "the manual 'Index corpus' button/action must be removed (UI_SHELL §6)"
    )
    assert "function autoIndexInsights(" in html and "autoIndexInsights()" in html, (
        "Insights must auto-index in the background (UI_SHELL §6)"
    )
    # 22. The analysis window (Group F, keystone #4): a full-screen #analyze tab
    #     driven by the universal subtab component, fed by the article-SET keyword
    #     endpoint, opened from the Search tab's Analyze button. Counts, no verdict.
    assert 'id="tab-analyze"' in html and 'data-tab="analyze"' in html, (
        "the analysis tab + its sidebar entry must exist (Group F)"
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
    assert '/api/links/corpus' in html and 'id="an-links"' in html, (
        "the analysis window must carry the shared-Links subtab (Group F)"
    )
    assert '/api/insights/corpus-sentiment' in html and 'id="an-sentiment"' in html, (
        "the analysis window must carry the Sentiment subtab (Group F)"
    )
    assert '/api/insights/corpus-sources' in html and 'id="an-sources"' in html, (
        "the analysis window must carry the source-coverage subtab (Group F)"
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
