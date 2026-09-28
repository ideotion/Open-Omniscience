"""The inline-handler ratchet (Q1127 = a, 0.5 gate row I, brief S05-09 S1 + S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ruling: retire the inline event handlers, with a ratchet that fails on any NEW one, and
drop ``'unsafe-inline'`` from the CSP's ``script-src`` when the count reaches zero. An inline
handler is script the browser runs from an attribute, so ``script-src 'unsafe-inline'`` has
to stay while one exists; the same is true of an inline ``<script>`` block, so this file
ratchets both.

ONE PUBLISHED PATTERN. ``on<event>`` for an event in ``EVENTS``, optional whitespace, ``=``,
then a quote -- plain, or backslash-escaped inside a JS string. It is scanned over every
served surface: ``src/static`` (HTML and JS, the vendored Alpine aside) and the Python modules
under ``src/api`` that render HTML. Two brief-era counts used two different patterns (613 and
602) and neither matches the other, which is why the pattern lives HERE with its own mutation
check and the pins are its own counts: a pin measured with another pattern pins nothing.

ZERO SLACK. Each file's count must EQUAL its pin: a new handler reddens by file name, and a
conversion that removes one reddens too until the pin is lowered in the same change, so the
ratchet can never quietly hold room for a regression.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The event list is the pattern: widening it is a change to what is measured.
EVENTS = (
    "click|dblclick|contextmenu|change|input|submit|reset|search|invalid|select|"
    "keydown|keyup|keypress|focus|blur|focusin|focusout|"
    "mouseover|mouseout|mouseenter|mouseleave|mousedown|mouseup|mousemove|wheel|scroll|"
    "load|error|abort|toggle|close|cancel|resize|beforeunload|unload|"
    "dragstart|drag|dragover|dragenter|dragleave|drop|dragend|"
    "touchstart|touchend|touchmove|pointerdown|pointerup|pointermove|pointerenter|pointerleave|"
    "animationend|transitionend|paste|copy|cut"
)
HANDLER = re.compile(r"(?<![\w.$-])on(?:" + EVENTS + r")\s*=\s*\\?[\"']", re.I)
# An inline <script> block: a <script> tag with no src attribute.
INLINE_SCRIPT = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>", re.I)

# Measured on main @ 00af1d9 (2026-09-28) with HANDLER above: 656 -- index.html 353, the
# nineteen app-*.js modules 291, taskmanager.html 11, unlock.html 1. The SPA (index.html +
# app-*.js, 644) converted to data-on-* in the same PR; what is left is pinned here.
HANDLER_PINS: dict[str, int] = {
    "src/static/taskmanager.html": 11,
    "src/static/unlock.html": 1,
}

# Inline <script> blocks on served pages (the reader and law reader are rendered in Python).
INLINE_SCRIPT_PINS: dict[str, int] = {
    "src/api/law.py": 1,
    "src/api/main.py": 2,
    "src/static/investigate.html": 1,
    "src/static/taskmanager.html": 1,
    "src/static/unlock.html": 1,
}


def _served_files() -> list[Path]:
    static = ROOT / "src" / "static"
    files = [p for p in static.rglob("*") if p.suffix in (".html", ".js") and "vendor" not in p.parts]
    files += sorted((ROOT / "src" / "api").rglob("*.py"))
    return sorted(files)


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def count_handlers(text: str) -> int:
    return len(HANDLER.findall(text))


def count_inline_scripts(text: str) -> int:
    return len(INLINE_SCRIPT.findall(text))


def test_the_pattern_catches_every_spelling_and_nothing_else():
    """The mutation check: the lesson of the ``onclick="cap"`` grep (LESSONS 2026-09-09)."""
    caught = [
        '<button onclick="go()">',
        "<button onclick='go()'>",
        '<input onChange = "go()">',
        '`<a onclick="${fn}(1)">`',
        "'<b onclick=\\\"go()\\\">'",
        '<img onerror="x()">',
        '<div onkeydown="if(event.key===1)go()">',
    ]
    for src in caught:
        assert count_handlers(src) == 1, f"the pattern missed {src!r}"
    missed = [
        '<button data-on-click="go">',
        "el.onclick = go;",
        'el.addEventListener("click", go)',
        "const oncloseHandler = 1;",
        '<p>click on="that"</p>',
        "reason=\"x\" button='y'",
    ]
    for src in missed:
        assert count_handlers(src) == 0, f"the pattern over-matched {src!r}"
    assert count_inline_scripts("<script>1</script><script src='/a.js'></script>") == 1
    assert count_inline_scripts('<script type="module" src="/a.js"></script>') == 0


def test_no_served_file_gains_an_inline_handler():
    over, under = [], []
    for p in _served_files():
        n = count_handlers(p.read_text(encoding="utf-8"))
        pin = HANDLER_PINS.get(_rel(p), 0)
        if n > pin:
            over.append(f"{_rel(p)}: {n} inline handlers, pinned at {pin}")
        elif n < pin:
            under.append(f"{_rel(p)}: {n} inline handlers, pin still {pin} -- lower it")
    assert not over, (
        "NEW inline event handlers (Q1127 = a: the CSP cannot drop 'unsafe-inline' while one "
        "exists). Bind with data-on-<event> (src/static/oo-on.js) or addEventListener:\n  "
        + "\n  ".join(over)
    )
    assert not under, "a conversion lowered a count; lower its pin in the same change:\n  " + "\n  ".join(under)
    for rel in HANDLER_PINS:
        assert (ROOT / rel).exists(), f"{rel} is pinned but no longer exists: drop its pin"


def test_no_served_page_gains_an_inline_script():
    bad = []
    for p in _served_files():
        if p.suffix == ".js":
            continue
        n = count_inline_scripts(p.read_text(encoding="utf-8"))
        pin = INLINE_SCRIPT_PINS.get(_rel(p), 0)
        if n != pin:
            bad.append(f"{_rel(p)}: {n} inline <script> blocks, pinned at {pin}")
    assert not bad, "\n  ".join(bad)


# --------------------------------------------------------------------------- #
# The replacement: data-on-<event> bindings, run by src/static/oo-on.js
# --------------------------------------------------------------------------- #

import subprocess  # noqa: E402

STATIC = ROOT / "src" / "static"
_HELPERS = {"ooPrevent", "ooStop", "ooPreventStop", "ooCloseDialog", "ooClickId", "ooSetValue",
            "ooClearValue", "ooBodyClass", "ooOpenUrl"}


def _binding_bodies(text: str):
    """Every data-on-* value, with each JS ``${...}`` interpolation replaced by ``0``."""
    for m in re.finditer(r"data-on-(\w+)=(\\?[\"'])", text):
        q, i, body = m.group(2), m.end(), []
        while i < len(text):
            if text.startswith("${", i):
                depth, j = 1, i + 2
                while depth:
                    depth += {"{": 1, "}": -1}.get(text[j], 0)
                    j += 1
                body.append(" 0 ")
                i = j
                continue
            if text.startswith(q, i):
                break
            body.append(text[i])
            i += 1
        yield m.group(1), "".join(body)


def _called_names(body: str) -> set[str]:
    body = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "0", body)
    return set(re.findall(r"([A-Za-z_$][\w$]*)\s*\(", body))


def _allowlist() -> list[str]:
    js = (STATIC / "oo-on.js").read_text(encoding="utf-8")
    m = re.search(r"const OO_ACTIONS = \[(.*?)\];", js, re.S)
    assert m, "oo-on.js's OO_ACTIONS list must parse"
    return re.findall(r'"([\w$]+)"', m.group(1))


def _spa_files() -> list[Path]:
    return [STATIC / "index.html", *sorted(STATIC.glob("app-*.js"))]


# Names a binding reaches only through a JS interpolation (``data-on-click="${action}"``),
# so no scan of the markup can see them. Each is listed with where it is built.
_INTERPOLATED = {
    "openCardCorpus": "app-home.js, the Lead card's and the carousel's Open corpus",
    "openCardCorpusQuery": "app-home.js, the same two, when the Lead carries no article ids",
}


def test_every_bound_name_is_allowlisted_and_every_allowlisted_name_is_bound():
    used: set[str] = set()
    for p in _spa_files():
        for _, body in _binding_bodies(p.read_text(encoding="utf-8")):
            used |= _called_names(body)
    used |= set(_INTERPOLATED)
    listed = set(_allowlist())
    assert _allowlist() == sorted(listed), "keep OO_ACTIONS sorted and free of repeats"
    missing = sorted(used - listed - _HELPERS)
    assert not missing, f"bound in markup but not in oo-on.js OO_ACTIONS (the binding is refused): {missing}"
    dead = sorted(listed - used)
    assert not dead, f"in OO_ACTIONS but bound nowhere (a dead entry widens the surface): {dead}"


def test_every_allowlisted_name_is_a_global_function_declaration():
    """oo-on.js resolves a name on window at call time. A ``function`` declaration at a
    classic script's top level is a window property; a ``const``/``let`` arrow is NOT, so a
    binding to one would silently do nothing."""
    js = "\n".join(p.read_text(encoding="utf-8") for p in sorted(STATIC.glob("*.js")))
    for name in _allowlist():
        assert re.search(r"^ {4}(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", js, re.M), (
            f"{name} is bound from markup but is not a top-level function declaration"
        )


def test_the_dispatcher_loads_before_the_app_and_is_cached_offline():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="/static/oo-on.js"') < html.index('src="/static/app-core.js"')
    assert '"/static/oo-on.js"' in (STATIC / "sw.js").read_text(encoding="utf-8")


def test_the_dispatcher_runs_as_real_code():
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "oo_on_node_test.js")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "oo_on_node_test.js: OK" in proc.stdout
