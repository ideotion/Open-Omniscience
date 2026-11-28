"""Row 461 (after row 458): a value put into a sentence with ``String.prototype.replace`` is inserted as written.

With a string pattern and a string replacement, ``replace`` reads ``$&``, ``$'``, ``$``` and ``$$`` in the
REPLACEMENT as patterns, so a folder name, model name or server reason holding one rewrote the sentence around it.
Every such call in the app's own scripts passes a function instead; a literal replacement (no value in it) may stay.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"

_CALL = re.compile(r"""\.replace\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\s*,\s*""")
_LITERAL = re.compile(r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`[^`$]*`)\s*\)""")
_FUNCTION = re.compile(r"(\([^()]*\)\s*=>|\w+\s*=>|function\b)")


def _scripts():
    return sorted(p for p in STATIC.rglob("*.js") if "vendor" not in p.parts)


def _string_form_values(text: str) -> list[int]:
    return [text.count("\n", 0, m.start()) + 1 for m in _CALL.finditer(text)
            if not _LITERAL.match(text, m.end()) and not _FUNCTION.match(text, m.end())]


def test_no_string_pattern_replace_takes_a_value_as_a_replacement_pattern():
    found = {str(p.relative_to(ROOT)): lines for p in _scripts() if (lines := _string_form_values(p.read_text(encoding="utf-8")))}
    assert found == {}, f"use the function form, .replace(pattern, () => value): {found}"


def test_the_scan_sees_the_old_form_and_passes_the_safe_ones():
    """ANTI-VACUITY: the scan flags the shape the sweep removed and leaves the two safe shapes alone."""
    assert _string_form_values('t("{n} left").replace("{n}", count)') == [1]
    assert _string_form_values('x.replace("\\u0001p\\u0002", `<b>${esc(path)}</b>`)') == [1]
    assert _string_form_values('t("{n} left").replace("{n}", () => count)') == []
    assert _string_form_values('x.replace("\\u0001f\\u0002", `<bdi translate="no">keys</bdi>`)') == []
    assert _string_form_values("s.replace('a', 'b')") == []
    # and the app's scripts really hold function-form swaps, so an empty result above is not an empty scan
    assert sum(p.read_text(encoding="utf-8").count('", () => ') for p in _scripts()) > 50
