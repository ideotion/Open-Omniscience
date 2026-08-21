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
_MUST_SCAN = ("index.html", *_ENGINE_MODULES, "reader.js",
              "taskmanager.html", "unlock.html", "investigate.html")


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
