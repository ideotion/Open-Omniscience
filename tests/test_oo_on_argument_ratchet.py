"""A data-on-* argument is written as ``${esc(JSON.stringify(x))}``, never inside single quotes (audit F6, R203).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``'${esc(x)}'`` looks safe and is not: the browser decodes the attribute before ``oo-on.js`` parses it,
so the ``&#39;`` esc() wrote comes back as an apostrophe and closes the grammar's string. Reproduced in
Chromium with the real parser: ``x'); appShutdown(); ooSetValue('a','b`` inside
``ooSetValue('agenda-tag', '...')`` runs ``appShutdown``. ``tests/oo_on_arg_escape_node_test.js`` replays
both forms through the real parser.

Two rules over every ``src/static`` script that writes markup:

* no ``'${esc(`` inside a ``data-on-*`` attribute;
* a raw ``'${expr}'`` is allowed only for the (file, expression) pairs below, each a value the code
  itself chooses (a literal, an enum key, a DOM id prefix). Anything that can hold stored or scraped text
  uses the JSON form. A new pair here is a claim that the value cannot hold an apostrophe: say why.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"

_ATTR = re.compile(r'data-on-[a-z]+="[^"\n]*')

# (file, expression) -> what the value is. Values the code chooses; none is data.
_CODE_CHOSEN: dict[tuple[str, str], str] = {
    ("app-analysis.js", "ctx"): "a fixed panel prefix passed by the caller in this file",
    ("app-analysis.js", "field"): "a sort column key from a literal table",
    ("app-analysis.js", "group"): "a facet group name from a literal list",
    ("app-analysis.js", "m"): "a trend mode, one of three literals",
    ("app-analysis.js", "op"): "a bulk operation key from a literal table",
    ("app-analysis.js", "v"): "a provenance filter value from a literal list",
    ("app-core.js", "code"): "a UI locale code from the bundled locale list",
    ("app-corpus.js", "pfx"): "a DOM id prefix passed by the caller in this file",
    ("app-diagnostics.js", "k"): "an anchor kind from a literal list",
    ("app-diagnostics.js", "v"): "an anchor verdict from a literal list",
    ("app-home.js", "v"): "a feed order key from a literal list",
    ("app-library.js", "key"): "a metric key from a literal table",
    ("app-library.js", "metric"): "a metric key from a literal table",
    ("app-map.js", "m"): "a dump reading mode from a literal list",
    ("app-shell.js", "a"): "an accent value from the literal accent list",
    ("app-shell.js", "d"): "a density from the literal density list",
    ("app-shell.js", "f.id"): "a typeface id from the literal face catalogue",
    ("app-shell.js", "t.id"): "a theme id from the literal theme catalogue",
    ("app-shell.js", "v"): "a sidebar mode from the literal list",
    ("app-sources.js", "col"): "a sort column key from a literal table",
    ("app-sources.js", "id"): "the id of a multi-select the caller in this file created",
    ("app-sources.js", "k"): "a source-class key from a literal list",
}


def _scripts() -> list[Path]:
    return sorted(p for p in _STATIC.glob("*.js") if p.name != "oo-on.js")


def test_no_single_quoted_esc_in_a_data_on_attribute() -> None:
    bad = []
    for p in _scripts():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "data-on-" in line and "'${esc(" in line:
                bad.append(f"{p.name}:{n}: {line.strip()[:120]}")
    assert not bad, "use ${esc(JSON.stringify(x))} (the browser decodes &#39; back to ' before oo-on.js parses):\n" + "\n".join(bad)


def test_no_double_quoted_interpolation_inside_a_single_quoted_data_on_attribute() -> None:
    """The mirror image: ``data-on-click='f("${esc(x)}")'``. esc() writes a double quote as &quot;, which the browser decodes back to
    a double quote and closes the grammar's string, exactly as &#39; does in the other shape. The JSON form carries its own quotes."""
    attr = re.compile(r"data-on-[a-z]+='[^'\n]*")
    bad = []
    for p in _scripts():
        for m in attr.finditer(p.read_text(encoding="utf-8")):
            if '"${' in m.group(0):
                bad.append(f"{p.name}: {m.group(0)[:100]}")
    assert not bad, "use ${esc(JSON.stringify(x))} with no quotes around it:\n" + "\n".join(bad)


def test_a_raw_single_quoted_interpolation_is_a_value_the_code_chooses() -> None:
    found: set[tuple[str, str]] = set()
    for p in _scripts():
        for m in _ATTR.finditer(p.read_text(encoding="utf-8")):
            found.update((p.name, e) for e in re.findall(r"'\$\{([^}]*)\}'", m.group(0)))
    unlisted = sorted(found - set(_CODE_CHOSEN))
    stale = sorted(set(_CODE_CHOSEN) - found)
    assert not unlisted, f"a data-on-* argument interpolates a value inside single quotes: use esc(JSON.stringify(x)), or list it with a reason: {unlisted}"
    assert not stale, f"listed but no longer present, delete the entry: {stale}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_json_form_survives_the_real_parser() -> None:
    result = subprocess.run(  # noqa: S603
        ["node", str(_ROOT / "tests" / "oo_on_arg_escape_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
