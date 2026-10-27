"""Which EVENT may call which name: the per-event table in ``src/static/oo-on.js`` equals the markup (audit A-023/A-024, stage 1).

``OO_ACTIONS`` says which names a ``data-on-*`` binding may call, and nothing about which event may call them, so an
injected ``<img src=x data-on-error="addSource()">`` ran any of the 480 names with no click (``tests/oo_on_gate_node_test.js``
used to assert exactly that for ``deleteSource``). ``EVENT_ACTIONS`` is the table the dispatcher now consults: a name runs
only for an event type whose row lists it, and an event type with no row (33 of the 38 the dispatcher listens for) runs
nothing. The table is DERIVED from the markup, never maintained by memory, and pinned both ways here with zero slack: a new
binding that is not in the table is refused at run time (the button would do nothing), so the test names it before that
happens, and an entry no markup binds is a door nothing needs.

REGENERATE with ``python tests/test_oo_on_event_table.py`` (prints the literal for ``EVENT_ACTION_NAMES``).

STATED LIMITS (they are not solved by a table; ``docs/ledger`` carries the audit record):

* An event the BROWSER fires as a consequence of a script's ``el.click()`` (a checkbox's ``change``) is ``isTrusted``, so the
  A-023 chain (``ooClickId('discovery-external')`` then ``saveDiscoveryExternal``) is held shut only by the ``CLICK_IDS`` set.
* An injected binding the person then CLICKS is a trusted click on any name the click row lists. The table narrows the
  zero-click and wrong-event paths; the confirm in a name's own body and ``GESTURE_ONLY`` are what stand behind the click.
* Autofill and extensions dispatch untrusted ``input``/``change`` events; no trust rule is added for them here (stage 2, a
  proposal), so nothing in this change depends on how they behave. NOT measured.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_inline_handler_ratchet import (
    _HELPERS,
    _binding_bodies,
    _called_names,
    _served_files,
)

_ROOT = Path(__file__).resolve().parents[1]
_OO_ON = _ROOT / "src" / "static" / "oo-on.js"

# Names a binding reaches only through a JS interpolation (``data-on-click="${action}"``,
# ``data-on-click="${fn}(...)"``), so the scan cannot see the name. Each is a CLICK binding; the guard below checks that every
# interpolated-name site in the tree is a click, so the event written here is not an assumption.
_INTERPOLATED_CLICK = {
    "openCardCorpus": "app-home.js, the Lead card's and the carousel's Open corpus",
    "openCardCorpusQuery": "app-home.js, the same two, when the Lead carries no article ids",
}

# A binding whose NAME is an interpolation: the value begins with ``${`` or a ``${...}`` is followed by ``(``.
_INTERPOLATED_NAME = re.compile(r"""data-on-(\w+)=\\?["']\s*\$\{|data-on-(\w+)=\\?["'][^"'\n]*?\$\{[^}]*\}\s*\(""")


def scanned_table() -> dict[str, list[str]]:
    """``{event: sorted names}`` from every served surface's ``data-on-<event>`` bindings (``data-on-key`` is a key filter)."""
    known = set(_actions()) | _HELPERS
    table: dict[str, set[str]] = {}
    for p in _served_files():
        if p.name == "oo-on.js":
            continue
        for event, body in _binding_bodies(p.read_text(encoding="utf-8", errors="ignore")):
            if event == "key":
                continue
            table.setdefault(event, set()).update(_called_names(body) & known)
    table.setdefault("click", set()).update(_INTERPOLATED_CLICK)
    return {event: sorted(names) for event, names in sorted(table.items()) if names}


def _actions() -> list[str]:
    m = re.search(r"const OO_ACTIONS = \[(.*?)\];", _OO_ON.read_text(encoding="utf-8"), re.S)
    assert m, "oo-on.js's OO_ACTIONS list must parse"
    return re.findall(r'"([\w$]+)"', m.group(1))


def declared_table() -> dict[str, list[str]]:
    m = re.search(r"const EVENT_ACTION_NAMES = \{(.*?)\n  \};", _OO_ON.read_text(encoding="utf-8"), re.S)
    assert m, "oo-on.js must declare EVENT_ACTION_NAMES as a literal object"
    out: dict[str, list[str]] = {}
    for row in re.finditer(r"\n    (\w+): \[(.*?)\],?(?=\n    \w+: \[|\Z)", m.group(1), re.S):
        out[row.group(1)] = re.findall(r'"([\w$]+)"', row.group(2))
    return out


def render_js(table: dict[str, list[str]]) -> str:
    lines = ["  const EVENT_ACTION_NAMES = {"]
    for event, names in table.items():
        lines.append(f"    {event}: [")
        row = "     "
        for name in names:
            piece = f' "{name}",'
            if len(row) + len(piece) > 118:
                lines.append(row)
                row = "     "
            row += piece
        lines.append(row)
        lines.append("    ],")
    lines.append("  };")
    return "\n".join(lines)


def test_the_scan_sees_single_quoted_double_quoted_and_nested_bindings() -> None:
    """The mutation check: a scan that misses a spelling pins less than it claims (LESSONS, the ``onclick="cap"`` grep)."""
    text = (
        "<a data-on-click=\"showTab('home')\"></a>"
        " <a data-on-change='setTheme(this.value)'></a>"
        " <input data-on-input=\"filterDoc()\" data-on-keydown=\"ooClearValue(this);filterDoc()\" data-on-key=\"Escape\">"
        " `<b data-on-click=\"anParams()\">`"
    )
    got = {event: sorted(_called_names(body)) for event, body in _binding_bodies(text)}
    assert got["click"] in (["showTab"], ["anParams"]) and got["change"] == ["setTheme"], got
    assert got["input"] == ["filterDoc"] and got["keydown"] == ["filterDoc", "ooClearValue"], got
    assert _INTERPOLATED_NAME.search('data-on-click="${action}"') and _INTERPOLATED_NAME.search('data-on-click="${fn}(1)"')
    assert not _INTERPOLATED_NAME.search("data-on-click=\"showTab('${x}')\"")


def test_the_table_in_oo_on_js_is_exactly_the_table_the_markup_needs() -> None:
    declared, scanned = declared_table(), scanned_table()
    assert declared == scanned, (
        "EVENT_ACTION_NAMES in src/static/oo-on.js is not the table the markup binds. "
        "Regenerate with `python tests/test_oo_on_event_table.py`.\n"
        + "\n".join(
            f"  {event}: add {sorted(set(scanned.get(event, [])) - set(declared.get(event, [])))} "
            f"remove {sorted(set(declared.get(event, [])) - set(scanned.get(event, [])))}"
            for event in sorted(set(declared) | set(scanned))
            if declared.get(event) != scanned.get(event)
        )
    )
    for event, names in declared.items():
        assert names == sorted(names) and len(names) == len(set(names)), f"{event}: keep the row sorted, with no repeats"
    assert list(declared) == sorted(declared), "keep the rows sorted by event"


def test_every_allowlisted_action_is_reachable_through_at_least_one_event() -> None:
    reachable = {n for names in declared_table().values() for n in names}
    assert not (set(_actions()) - reachable), f"in OO_ACTIONS but no event may call it: {sorted(set(_actions()) - reachable)}"
    assert not (reachable - set(_actions()) - _HELPERS), "a table entry that is neither an action nor a helper"


def test_every_binding_whose_name_is_interpolated_is_a_click_and_is_in_the_click_row() -> None:
    """The scan reads names, so a name written as ``${fn}`` is invisible to it; the events of those sites are pinned instead."""
    sites: list[tuple[str, str]] = []
    for p in _served_files():
        if p.name == "oo-on.js":
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        sites += [(p.name, m.group(1) or m.group(2)) for m in _INTERPOLATED_NAME.finditer(text)]
    assert sites, "the scan found no interpolated-name binding; the pattern or the markup changed"
    assert all(event == "click" for _, event in sites), [s for s in sites if s[1] != "click"]
    click = set(declared_table()["click"])
    assert set(_INTERPOLATED_CLICK) <= click
    assert {"startOsmDownload", "resumeOsm"} <= click, "app-map.js builds these two as ${fn}(code, this) on a click"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_dispatcher_runs_exactly_the_table_in_the_real_code() -> None:
    result = subprocess.run(  # noqa: S603
        ["node", str(_ROOT / "tests" / "oo_on_event_table_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    print(render_js(scanned_table()))
