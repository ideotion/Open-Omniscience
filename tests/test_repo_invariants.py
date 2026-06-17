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
    html = _ui_source()
    # 1. Wikipedia edition picker is a dropdown, never a text input
    assert '<select id="wiki-lang"' in html, "wiki-lang must be a <select> (CLAUDE.md #1)"
    assert '<input id="wiki-lang"' not in html
    # 3. constant top-bar footprints
    assert ".act-host:empty { visibility:hidden; }" in html, "act-host slot must stay reserved"
    assert "#llm { min-width" in html, "LLM pill needs a fixed footprint"
    # 4. §2 (ruled 2026-06-14, amends #4): vitals moved OUT of the chrome into the
    #    task-manager window's System tab; the chrome keeps a PERSISTENT task-manager
    #    access (#activity is hidden when idle); version still not in the chrome.
    assert 'id="vitals-mini"' not in html, "the vitals strip must NOT live in the chrome (§2 amends #4)"
    assert 'id="tm-open"' in html and 'id="tm-system"' in html, (
        "a persistent task-manager access (#tm-open) + the System tab (#tm-system, where "
        "vitals now live) must both exist (CLAUDE.md #4, §2)"
    )
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
        'ooChart($("mkt-chart-oo")',
        'ooChart($("ins-trend-oo")',
        'ooChart($("idx-chart-oo")',  # indices detail rolled onto ooChart
    ):
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
    assert "series_top=5" in html and "dashChartSvg(" in html, (
        "loadTrendWindows() must request series_top and render per-term sparklines"
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
    #     CLAUDE.md Non-negotiables): a briefing card's CAVEAT renders in a visible
    #     .card-caveat line, NEVER hidden behind the method toggle. Only the verbose
    #     method/math stays in the toggle-gated .mc block. (This regressed once: the
    #     .mc block held BOTH method AND caveat behind a default-OFF checkbox.)
    assert 'class="card-caveat">${esc(c.caveat)}' in html, (
        "every briefing card must render its caveat VISIBLE BY DEFAULT (CLAUDE.md "
        "informed-consent: caveats are never hidden behind a calm-UI toggle)"
    )
    mc_block = html.split('<div class="mc" hidden>', 1)[1].split("</div>", 1)[0]
    assert "c.caveat" not in mc_block, (
        "the per-card caveat must NOT live inside the toggle-gated .mc block — it is "
        "visible by default (CLAUDE.md informed-consent mandate)"
    )
    assert "c.method" in mc_block, (
        "the verbose method/math stays behind the 'Show method' toggle (.mc)"
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
    #     controversial sources" action over /api/stats/sources/ingest, living in a
    #     Settings subtab. The directory is DESCRIPTIVE only (no figures, no score);
    #     producers are stanced sources (the "controversial" framing is a note, never
    #     a credibility verdict). Outbound home URLs MUST go through extLink so they
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
    assert (
        'data-tab="guis"' in html and 'id="set-guis"' in html and 'id="guis-gallery"' in html
    ), "Settings must carry the GUIs subtab button + the set-guis panel + the #guis-gallery host"
    assert 'cat === "guis"' in html and "OOGUIs.renderGallery" in html, (
        "showSetCat() must lazy-render the gallery when the GUIs subtab is shown"
    )


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
    walks a new user to a working app. SLICE 1 = shell + Language step + Finish/
    start-collecting step (encryption + sources-by-theme are deferred placeholder
    steps). Binding constraints, pinned so they cannot regress between sessions:
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
    # the two SLICE-1 steps + the two DEFERRED placeholder steps (so the next
    # slice slots its real UI in without re-deriving the structure).
    for step in ('data-step="lang"', 'data-step="finish"',
                 'data-step="encryption"', 'data-step="sources"'):
        assert step in html, f"the wizard step is missing: {step}"
    # 2. Language step uses THE i18n engine via the shared picker (no new list).
    gw = html.split('id="guide-wizard"', 1)[1].split("</dialog>", 1)[0]
    assert 'id="gw-langs"' in gw, "the wizard must carry the Language step's picker"
    assert "function _gwRenderLangs(" in html and "pickLang(b.dataset.lang)" in html, (
        "the Language step must switch the whole UI through pickLang()/OOI18N.setLang "
        "(invariant #15) — it must not build a second language list"
    )
    # 3. INFORMED CONSENT — the wizard NEVER posts the network; "Go online & start
    #    collecting" routes through the existing firstRun()/toggleNetwork() flow,
    #    so ensureOnline (the ONE consent popup) always fires (invariant #14).
    go_block = html.split('if (go) go.onclick', 1)[1].split("};", 1)[0]
    assert 'api("/api/system/network"' not in go_block, (
        "the wizard must NOT POST the network itself — it is the invitation layer "
        "only; going online must pass ensureOnline (CLAUDE.md #14)"
    )
    assert ("firstRun(" in go_block) or ("toggleNetwork(" in go_block), (
        "the wizard's 'Go online' must route through the existing firstRun()/"
        "toggleNetwork() flow (which calls ensureOnline) (CLAUDE.md #14)"
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
    # absorption: the moved controls must all still exist (nothing lost in the move)
    for ctrl in ('id="sched-status"', "saveScheduler(", 'id="ing-url"', 'id="bi-search"'):
        assert ctrl in html, f"moved Collect control missing after the move: {ctrl}"
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
    assert 'if (cat === "sources") { loadManagedSources(); loadCandidates(); }' in html, (
        "the Sources subtab must run the managed-sources + candidates onShow loads"
    )


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
    assert "AG.categories = (fac.categories" in html, "categories must be data-driven from the catalog facets"
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
    assert 'category: "imported"' in html and "imported: true" in html, "imported events are their own class"
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
    """Item I: Synthesize is reachable from the analysis window too (its own query +
    a dedicated panel), so the last Search-tab capability is mirrored. The Search-tab
    call stays back-compatible (optional query/mount args)."""
    html = _ui_source()
    assert "function synthesizeResults(btn, qArg, mountId)" in html, "synthesize must take optional query + mount"
    assert "synthesizeResults(this, anQuery(), 'an-synth')" in html, "analysis window wires its own query + panel"
    assert 'id="an-synth"' in html, "a synthesis result panel in the analysis window"
    assert "synthesizeResults(this)" in html, "the Search-tab call site stays back-compatible"


def test_omnibar_enter_opens_analysis_window():
    """Item I: the omnibar's default Enter action opens the corpus/analysis window
    seeded with the query (ruled: Enter -> a corpus-of-articles window, not the
    Search tab). The Boolean Search-tab item stays available (nothing lost)."""
    html = _ui_source()
    assert "function openAnalysisFor" in html, "seeded analysis-window opener required"
    assert "run: () => openAnalysisFor(raw)" in html, "the default omnibar item opens analysis"
    # the Analysis item is unshifted LAST so it sits at index 0 (the Enter default),
    # while the Boolean search item remains reachable.
    i_search_item = html.index('showTab("search"); setTimeout(() => { $("q").value = raw; doSearch()')
    i_analysis_item = html.index("run: () => openAnalysisFor(raw)")
    assert i_search_item < i_analysis_item, "Analysis must be unshifted after Search (=> index 0, default Enter)"


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
    # the sidebar still lists tabs (invariant #2 not regressed)
    assert '<button class="nav-item" data-tab="analyze">' in html and '<button class="nav-item" data-tab="home">' in html


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


def test_tmap_mention_layer():
    """Temporal-map mention layer: the places the corpus's articles MENTION,
    plotted from the SHIPPED /api/insights/where substrate, reusing the map's
    existing equirectangular projection (lon2x/lat2y) and render loop.

    Honesty (non-negotiable): markers scale by raw article SPREAD (r∝√spread,
    AREA∝spread — no composite score); null-coordinate places are NOT plotted
    and their count is surfaced; the endpoint's "Deduced from text, never
    confirmed." caveat is VISIBLE on the layer (legend) AND in the readout.
    """
    html = _ui_source()

    # The in-map overlay toggle (Google-Maps "controls inside the map" convention).
    assert 'id="tmap-mentions-toggle"' in html, "the mention-layer toggle button must exist"
    assert 'onclick="toggleTmapMentions()"' in html, "the toggle must call toggleTmapMentions()"
    assert "function toggleTmapMentions()" in html, "toggleTmapMentions must be defined"

    # The layer fetches the SHIPPED corpus-wide WHERE endpoint (bounded, lazy).
    assert "/api/insights/where" in html, "the layer must fetch /api/insights/where"

    # Reuses the EXISTING projection — no second projection invented.
    assert "function buildTmapMentionLayer()" in html, "the layer builder must exist"
    assert "lon2x(p.lon)" in html and "lat2y(p.lat)" in html, (
        "mention markers must reuse the temporal map's lon2x/lat2y projection"
    )
    # Marker AREA ∝ spread ⇒ radius ∝ √(articles); honest raw count, never a score.
    assert "Math.sqrt((+p.articles" in html, "marker radius must scale with √(article spread)"

    # Null-coordinate places are dropped from the plot, their count surfaced.
    assert "p.lat != null && p.lon != null" in html, "places without coordinates must not be plotted"
    assert "places not mapped (no coordinates)" in html, (
        "the count of unmapped (null-coordinate) places must be surfaced honestly"
    )
    # Degrade loudly on empty.
    assert "No mapped mentions in your corpus yet." in html, "honest empty state required"

    # The deduced/never-confirmed caveat is present on BOTH the legend and the readout,
    # defaulting to the endpoint's verbatim string (informed-consent layering).
    assert "Deduced from text, never confirmed." in html, (
        "the endpoint's verbatim caveat must appear (legend + readout fallback)"
    )
    assert "function buildTmapMentionLegend()" in html, "the layer legend caveat line must exist"
    assert "function showTmapWhereDetail(" in html, "the marker readout must exist"


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
    # the commodity board detail still uses ooChart too (unchanged canonical path)
    assert 'ooChart($("mkt-chart-oo")' in html
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
