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
    from datetime import date

    from src.llm.ollama import CATALOG_AS_OF

    import re as _re
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
    # 5. the eye brand mark (grid-iris path is its fingerprint)
    assert "C8 6.5, 24 6.5, 30 16" in html, "brand mark must be the ASCII-eye vector"
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
