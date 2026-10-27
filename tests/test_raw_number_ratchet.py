"""Leading "+N" and "lo–hi" tokens beside text keep their order under Arabic (0.5.1, R277).

Measured in Chromium under ``dir=rtl`` (qual-lane/rtl-raw-number-sites-2026-10-26.md): a leading plus is drawn
on the far side of its digits even alone, and a dash range after translated text is drawn reversed. The
fix is ``ooLtrIsolate`` (app-core.js), a first-strong isolate only under a right-to-left page; left-to-right
output is byte-identical. Percent signs are NOT covered: where a % sits is a typography ruling still open.

THE RATCHET. Each file's count of a raw ``+${`` and of a raw ``${a}–${b}`` template must EQUAL its pin
(zero slack, the same shape as ``test_raw_date_ratchet.py``). What the pinned remainder is:

* hard-coded English strings that are never translated (app-diagnostics, app-sources: ``+${n}`` in a toast
  or a status line);
* a year range alone in its own element (app-agenda), two dates alone in table cells (app-backup), and a
  pair of dates already wrapped one by one with ooIsoDate (app-analysis).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"

_PLUS = re.compile(r"(?<![\w$})\]])\+\$\{")
_RANGE = re.compile(r"\$\{[^}]*\}\s*–\s*\$\{")

_PINS = {
    "plus": {"app-diagnostics.js": 2, "app-sources.js": 1},
    "range": {"app-agenda.js": 1, "app-analysis.js": 1, "app-backup.js": 2},
}


def _files():
    return sorted(
        p for ext in ("*.js", "*.html") for p in _STATIC.rglob(ext) if "vendor" not in p.relative_to(_STATIC).parts
    )


def _counts(pattern):
    out = {}
    for p in _files():
        n = len(pattern.findall(p.read_text(encoding="utf-8")))
        if n:
            out[p.relative_to(_STATIC).as_posix()] = n
    return out


def test_every_raw_plus_token_is_accounted_for_and_nothing_holds_room():
    got = _counts(_PLUS)
    assert got == _PINS["plus"], (
        "a raw leading +N changed: render it through ooLtrIsolate(...) (see this file's docstring), or move the pin "
        f"if it is one of the kinds listed there. Found: {got}"
    )


def test_every_raw_range_token_is_accounted_for_and_nothing_holds_room():
    got = _counts(_RANGE)
    assert got == _PINS["range"], (
        "a raw lo–hi range changed: render it through ooLtrIsolate(...), or move the pin if it is one of the "
        f"kinds listed in this file's docstring. Found: {got}"
    )


def test_the_patterns_find_what_they_are_meant_to_find():
    for hit in ("<b>+${n}</b>", " +${names.length - 1}", "`+${x}`", "(+${x})".replace("(", " ")):
        assert _PLUS.search(hit), hit
    for miss in ("a+${n}", "${a}+${b}", "x)+${n}", "${n}"):
        assert not _PLUS.search(miss), miss
    assert _RANGE.search("${row.lo}–${row.hi}") and _RANGE.search("${a} – ${b}")
    assert not _RANGE.search("${a}-${b}") and not _RANGE.search("${a}—${b}")


def test_the_swapped_sites_use_the_helper():
    core = (_STATIC / "app-core.js").read_text(encoding="utf-8")
    assert "function ooLtrIsolate(" in core and '"\\u2068" + v + "\\u2069"' in core
    for name, n in (("app-agenda.js", 5), ("app-analysis.js", 1), ("app-core.js", 2), ("app-markets.js", 1),
                    ("app-ai-tools.js", 1), ("app-settings.js", 1)):
        text = (_STATIC / name).read_text(encoding="utf-8")
        got = text.count("ooLtrIsolate(") - (1 if name == "app-core.js" else 0)
        assert got == n, (name, got, n)


def test_the_helper_behaves_under_both_directions():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "oo_ltr_isolate_node_test.js")], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout
