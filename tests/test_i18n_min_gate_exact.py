"""
Guard: the x12 locale gate compares the EXACT coverage, never the rounded one.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``scripts/i18n_report.py --min 100`` is the CI gate behind a non-negotiable:
"every consent/caveat string ships x12 locales". It compared the DISPLAY
percentage, which is ``round(100 * covered / n, 1)``. At the project's key
count a locale missing ONE key computes 99.969...%, which rounds to a flat
``100.0`` -- so it passed the gate, and the table printed "100.0%" beside it.
Any single missing key in any locale was invisible to the instrument that
exists to see exactly that.

Found the way it had to be found: a mutant. Restoring a locale file mid-session
discarded 19 uncommitted keys, and the gate said nothing.

The fix keeps the rounded ``percent`` for the human table (the column is
unchanged) and adds an unrounded ``percent_exact`` for the comparison. These
tests pin the behaviour rather than the wiring -- they run the gate against a
synthetic locale set and read its exit code, because asserting that the source
mentions ``percent_exact`` would survive code that computes it and compares the
rounded value anyway.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "i18n_report.py"
_REAL_LOCALES = _ROOT / "src" / "static" / "locales"

# Big enough that one missing key rounds away: the display rounds to 1 decimal,
# so the gap is invisible once 100/n < 0.05, i.e. above 2000 keys. The real
# en.json is far past that (see the last test), but the synthetic set states the
# threshold outright so this guard keeps working if the corpus of keys shrinks.
_N = 3000


def _module():
    spec = importlib.util.spec_from_file_location("i18n_report_gate", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_locales(dirpath: Path, *, missing: int) -> None:
    """en.json with _N keys, plus one locale declaring status:complete that is
    short by `missing` of them."""
    keys = {f"key.{i}": f"English {i}" for i in range(_N)}
    (dirpath / "en.json").write_text(
        json.dumps({"_meta": {"name": "English", "native": "English", "dir": "ltr",
                              "status": "source"}, **keys}, ensure_ascii=False),
        encoding="utf-8",
    )
    translated = {k: f"Traduit {k}" for k in list(keys)[: _N - missing]}
    (dirpath / "fr.json").write_text(
        json.dumps({"_meta": {"name": "French", "native": "Francais", "dir": "ltr",
                              "status": "complete"}, **translated}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.fixture()
def gate(tmp_path, monkeypatch):
    """The tool, pointed at a locale directory this test owns."""
    mod = _module()
    monkeypatch.setattr(mod, "_LOCALES", tmp_path)
    return mod


def test_one_missing_key_of_three_thousand_fails_the_gate(gate, tmp_path):
    _write_locales(tmp_path, missing=1)
    assert gate.main(["--min", "100"]) == 1, (
        "a locale declaring status:complete is missing a key and the gate passed "
        "-- this is the rounding hole: 2999/3000 rounds to 100.0%"
    )


def test_the_same_locale_still_DISPLAYS_a_rounded_hundred(gate, tmp_path):
    """The fix must not have been 'stop rounding the table'. The human column is
    unchanged; only the comparison moved. This also proves the defect was real:
    if `percent` did not round to 100.0 here, the old gate would have caught it."""
    _write_locales(tmp_path, missing=1)
    fr = next(loc for loc in gate.build_report()["locales"] if loc["code"] == "fr")
    assert fr["percent"] == 100.0
    assert fr["percent_exact"] < 100.0
    assert fr["missing"] == ["key.2999"]


def test_a_genuinely_complete_locale_still_passes(gate, tmp_path):
    _write_locales(tmp_path, missing=0)
    assert gate.main(["--min", "100"]) == 0, (
        "an exact-100% locale must not trip the gate -- a guard that fires on "
        "complete translations would just be turned off"
    )


def test_the_failure_names_how_many_keys_are_missing(gate, tmp_path, capsys):
    """At this key count the percentage alone reads '100.0%', which tells an
    operator nothing about what to fix. The count is the actionable half."""
    _write_locales(tmp_path, missing=7)
    assert gate.main(["--min", "100"]) == 1
    err = capsys.readouterr().err
    assert "fr" in err and "7 missing" in err, err


def test_the_shipped_locales_are_large_enough_for_the_hole_to_be_silent():
    """Why this guard exists, measured against the real files: at the project's
    key count a single gap is below the rounding resolution of the table."""
    keys = [k for k in json.loads((_REAL_LOCALES / "en.json").read_text(encoding="utf-8"))
            if k != "_meta"]
    n = len(keys)
    assert n > 2000, f"en.json has {n} keys"
    assert round(100 * (n - 1) / n, 1) == 100.0, (
        "one missing key no longer rounds to 100.0 -- the display resolution "
        "changed, so re-check what the gate compares"
    )
