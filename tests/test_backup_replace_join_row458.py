"""Row 458: server values in the erase and import reports never garble or break their sentence.

A string second argument to ``String.prototype.replace`` reads ``$&``, ``$'`` and ``$``` as patterns, so a folder
path holding one rewrote the sentence around it; the function form inserts the value as written. A list field the
server sent as something other than an array (a string, an object) made ``.join`` throw and lost the whole report;
it now reads as empty.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "src/static/app-backup.js").read_text(encoding="utf-8")

# A marker swap whose replacement is a template holding a value: it must be the function form.
_STRING_FORM = re.compile(r'\.replace\("\\u0001\w*\\u0002", `[^`]*\$\{')


def test_no_marker_swap_takes_a_value_as_a_replacement_pattern():
    assert _STRING_FORM.findall(JS) == []
    # ANTI-VACUITY: the swaps the row names are still there, in the function form.
    for marker, n in (("folders", 2), ("path", 2), ("name", 1)):
        assert JS.count(f'.replace("\\u0001{marker}\\u0002", () => `') == n, marker


def test_list_fields_are_read_only_as_arrays():
    assert "const _list = (v) => (Array.isArray(v) ? v.map(String) : []);" in JS
    for field in ("keys_left_names", "left_untouched", "left_common_names"):
        assert f"_list(r.{field})" in JS, field
        assert f"r.{field}.join" not in JS and f"(r.{field} || [])" not in JS, field


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_function_form_keeps_a_dollar_pattern_as_written():
    """What the change relies on, run in the engine the app runs in."""
    script = r"""
const frame = "left in \u0001path\u0002 folder";
const path = "/data/$&/$'x";
const asString = frame.replace("\u0001path\u0002", `<b>${path}</b>`);
const asFunction = frame.replace("\u0001path\u0002", () => `<b>${path}</b>`);
if (asFunction !== "left in <b>/data/$&/$'x</b> folder") throw new Error("function form: " + asFunction);
if (asString === asFunction) throw new Error("the string form no longer garbles, so this test proves nothing");
"""
    subprocess.run(["node", "-e", script], check=True, timeout=30)
