"""
Guard: the i18n chrome audit sees the actual UI engine, not just index.html.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

GUI audit 2026-07-28, finding I-1 -- the highest-leverage one.

``scripts/i18n_report.py`` used to set ``_UI = index.html`` and open nothing
else. So ``--audit-chrome`` reported "1069 UI strings, 801 keyed" and
``--min 100`` read a green 2130/2130 x12 -- while ``app.js``, the actual
18.5k-line UI engine, was **entirely invisible** to it, along with
``reader.js`` and the three auxiliary pages. That is how the coverage number
could say "100 %" while untranslated surfaces kept turning up in the field:
the instrument was not wrong, it was pointed at the wrong thing.

Widening the scope does NOT touch the blocking gate: ``--min`` compares each
locale against ``en.json`` and never reads these files. It only lets the
REPORT see what the engine actually renders -- which is what makes the
remaining gap measurable instead of invisible.

This pins the scope so it cannot silently narrow again.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from tests.js_source_helper import app_modules

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "i18n_report.py"
_STATIC = _ROOT / "src" / "static"

# Every surface that renders user-visible chrome and must therefore be in
# scope. The UI ENGINE is the load-bearing one -- and it is no longer one file:
# app.js was decomposed into ordered modules (S-3, 2026-08-20), so the engine's
# modules are read from index.html rather than named here. A hard-coded "app.js"
# would have kept passing against the one remaining slice while the other
# sixteen went unscanned -- finding I-1 all over again, in its own guard.
_ENGINE_MODULES = tuple(app_modules())

# The GUIs-gallery JS surface (CLAUDE.md invariant #30), added by audit finding
# P1-01 (2026-09-08): _aux_js()'s <script src> scan of index.html cannot reach
# these files -- boot.js/gallery.js ARE ordinary static tags but the two Alpine
# skins are injected at RUNTIME by boot.js's own GUIS registry, so no markup
# regex can ever discover them, however it is widened. Computed INDEPENDENTLY
# of scripts/i18n_report.py's own _guis_js() (a separate glob over the same
# directory, mirroring how _ENGINE_MODULES is a separate read of index.html
# rather than a call into the tool's own _aux_js()) -- so a regression that
# narrows the tool's glob (e.g. an accidental vendor/ inclusion or exclusion)
# is still caught here instead of the guard silently agreeing with the bug.
_GUIS_DIR = _STATIC / "guis"
_GUIS_MODULES = tuple(sorted(f"guis/{p.name}" for p in _GUIS_DIR.glob("*.js")))
assert _GUIS_MODULES, "src/static/guis has no .js files -- the gallery moved or was removed"

_MUST_SCAN = ("index.html", *_ENGINE_MODULES, *_GUIS_MODULES, "reader.js",
              "taskmanager.html", "unlock.html", "investigate.html")

# boot.js is pure registry/loader logic -- no rendered chrome at all (its GUI
# `name` fields are deliberately UNTRANSLATED proper nouns, per its own source
# comment). It must still be SCANNED (finding P1-01: a future string added
# there needs to be seen), but requiring a non-zero count from a file that
# genuinely renders nothing would be demanding a fabricated string just to
# satisfy the test -- exactly the kind of dishonesty this project's
# non-negotiables forbid. Every other file in _MUST_SCAN carries real chrome.
_ALLOWED_EMPTY = frozenset({"guis/boot.js"})


def _module():
    spec = importlib.util.spec_from_file_location("i18n_report", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", _MUST_SCAN)
def test_audit_scans_every_chrome_bearing_surface(name):
    audit = _module().audit_chrome()
    per_file = audit.get("per_file", {})
    assert name in per_file, (
        f"{name} is not scanned by the chrome audit -- it renders user-visible "
        "chrome, so strings there would be invisible to the coverage report "
        "(finding I-1: that is exactly how the number read 100% while the "
        "field kept meeting untranslated surfaces)"
    )
    if name in _ALLOWED_EMPTY:
        return
    assert per_file[name] > 0, (
        f"{name} is scanned but yielded 0 strings -- the extractor shapes "
        "probably stopped matching; verify before assuming the file is clean"
    )


def test_the_engine_contributes_a_substantial_share():
    """The UI engine must not silently drop to a token count.

    A regex-based extractor can degrade to near-zero without erroring (a
    changed quoting style, a refactor to template literals). Anchoring on a
    floor makes that visible instead of reading as "the engine is now clean".

    The floor is over the engine AS A WHOLE, summed across its modules: a
    per-module floor would be wrong (a small module legitimately carries few
    strings) and would have to be re-tuned every time a boundary moves.
    """
    per_file = _module().audit_chrome().get("per_file", {})
    total = sum(per_file.get(m, 0) for m in _ENGINE_MODULES)
    assert total >= 100, (
        f"the UI engine yielded only {total} chrome strings across "
        f"{len(_ENGINE_MODULES)} module(s) -- it is a ~24k-line engine, so this "
        "almost certainly means the extractor shapes stopped matching rather "
        "than that it became translatable"
    )


def test_widening_scope_did_not_move_the_blocking_gate():
    """--min compares locales against en.json and must be scope-independent.

    If widening the audit ever started failing --min, the two concerns would
    have become entangled and a coverage REPORT could block CI.
    """
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--min", "100"],
        capture_output=True, text=True, cwd=_ROOT,
    )
    assert proc.returncode == 0, (
        f"--min 100 failed after the scope widening:\n{proc.stdout}\n{proc.stderr}"
    )


def test_audit_reports_a_per_file_breakdown():
    """Without it, a scope regression is invisible in the output itself."""
    audit = _module().audit_chrome()
    assert isinstance(audit.get("per_file"), dict) and audit["per_file"], (
        "the audit must report which files it scanned, so a silently narrowed "
        "scope is visible in the report rather than only in this test"
    )
    assert audit["ui_strings"] >= sum(1 for _ in _MUST_SCAN), "implausible total"


def test_guis_gallery_is_in_scope():
    """Audit finding P1-01 (2026-09-08): the entire GUIs-gallery JS surface
    used to be invisible to --audit-chrome -- boot.js/gallery.js because the
    file-discovery regex required a name starting with "app", and the two
    Alpine skins (ui-command.js, ui-canvas.js) because they are never a
    <script src> tag in any static HTML at all (CLAUDE.md invariant #30: they
    are injected at runtime by boot.js's own GUIS registry). Pinned directly
    here, on top of the general _MUST_SCAN parametrization above, so a
    regression reads unambiguously as "the guis/ scope P1-01 closed reopened"
    rather than as one row failing among many unrelated ones.
    """
    per_file = _module().audit_chrome().get("per_file", {})
    for name in _GUIS_MODULES:
        assert name in per_file, f"{name} is not scanned by the chrome audit"
    non_empty = [m for m in _GUIS_MODULES if m not in _ALLOWED_EMPTY]
    assert non_empty, "no guis/*.js module carries chrome to check"
    for name in non_empty:
        assert per_file[name] > 0, (
            f"{name} is scanned but yielded 0 strings -- the extractor shapes "
            "probably stopped matching; verify before assuming the file is clean"
        )


def test_t9_and_t9m_aliases_are_not_invisible_to_the_t_call_gate():
    """Audit finding P1-01: many modules locally alias OOI18N.t to `t9`/`t9m`
    (`const t9 = (window.OOI18N && OOI18N.t) ? OOI18N.t : (s) => s`) instead of
    calling it `t` directly. A plain `\\bt\\(` regex never matches `t9(`/`t9m(`
    at all -- not a near-miss, a structural blind spot -- so every aliased call
    site was invisible to both --max-unkeyed-t-calls and --max-untranslatable.
    This proves the widened regex actually counts them, on a real, currently
    shipping call site (src/static/guis/gallery.js's Alpine-engine badge
    tooltip), rather than only asserting the regex object's pattern text.
    """
    mod = _module()
    tcalls = mod.unkeyed_t_calls()
    assert tcalls["sites"] > 0
    # The badge tooltip is wrapped in t9(...) and IS keyed (this PR added the
    # key in all 12 locales) -- so it must count as a SITE but never appear in
    # the unkeyed list. If the regex regressed back to matching only literal
    # `t(`, this call site would vanish from `sites` entirely rather than
    # merely moving to `unkeyed`, which is the failure this test is for.
    gallery = (_STATIC / "guis" / "gallery.js").read_text(encoding="utf-8")
    assert "t9(" in gallery, "gallery.js no longer uses the t9(...) alias -- update this test"
    badge_tooltip = (
        "Uses Alpine.js — a tiny framework vendored locally (MIT, zero network)."
    )
    assert badge_tooltip not in tcalls["unkeyed"], (
        "the t9(...)-wrapped Alpine badge tooltip is unkeyed -- either the key "
        "was lost from a locale file, or the t9(/t9m( regex widening regressed"
    )
