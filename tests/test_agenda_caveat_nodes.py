"""The Agenda caveat's SECOND render site, and the node-shape rule behind both.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Found 2026-09-09 while verifying the served-caveat key in a browser. The month
view (the default) renders the caveat alone into ``#agenda-monthhint`` and, once
the whole paragraph was keyed, translated correctly. The LIST view did not, and
the reason is a rule worth stating once for the whole app:

``src/static/i18n.js``'s ``tr()`` looks up ``map[core]`` where ``core`` is one
whole TEXT NODE with its internal whitespace normalised. There is no sentence
splitting and no substring replacement anywhere in the walker. So the moment a
translatable string is CONCATENATED with anything else into one node -- here
``${esc(AG.caveat)} · showing ${rows.length} of ${AG.events.length}`` -- the
resulting node matches no key, and BOTH halves render in English. Measured in
Chromium at fr and ja before the fix: the full English caveat followed by a bare
English "showing 153 of 153", in a UI otherwise fully translated.

The repair is the general one: give a walker-translated string its own node, and
translate anything interpolated at render time through the template-is-the-key
rule (``_bulTf``), so the numbers never pass through a translation table.
"""

from __future__ import annotations

import json
import pathlib
import re

_STATIC = pathlib.Path(__file__).resolve().parents[1] / "src" / "static"
_LOCALES = _STATIC / "locales"

_COUNT_KEY = "showing {shown} of {total}"


def _render_agenda() -> str:
    """``renderAgenda()``'s body, sliced out of the real module by name.

    Sliced rather than line-matched: the populated-list render is a multi-line
    template literal, and a line-based grep for it silently stops finding
    anything the moment someone reflows it -- which is exactly the shape of a
    test that goes quietly vacuous. The shared helper balances braces, so the
    slice survives reformatting.
    """
    from tests.js_source_helper import function_body, read_static

    return function_body(read_static("app-agenda.js"), "renderAgenda")


def _populated_render(body: str) -> str:
    """The branch that renders rows AND a count (the one that concatenated)."""
    at = body.index("AG.events.length")
    start = body.rindex("box.innerHTML", 0, at)
    return body[start : body.index("`;", at) + 2] if "`;" in body[at:] else body[start : at + 400]


def _empty_render(body: str) -> str:
    """The no-events branch: the caveat is the whole paragraph there."""
    at = body.index("No events this month")
    return body[body.rindex("box.innerHTML", 0, at) : at]


def test_the_list_view_never_concatenates_the_caveat_into_a_larger_node() -> None:
    """THE REGRESSION, stated as the shape that caused it.

    ``esc(AG.caveat)`` followed by more text inside the SAME element makes one
    text node, which the walker cannot match. The caveat must sit in a child
    element of its own.
    """
    render = _populated_render(_render_agenda())
    assert "<span>${esc(AG.caveat)}</span>" in render, (
        "the served caveat must sit in its OWN element so i18n.js's whole-node "
        f"match can reach it; got: {render.strip()[:300]}"
    )
    # And nothing may share that node: the caveat's element must contain the
    # caveat and nothing else. A sibling after the closing tag is fine.
    assert re.search(r"<span>\$\{esc\(AG\.caveat\)\}</span>", render), (
        "the caveat's element must contain the caveat and nothing else"
    )


def test_the_count_is_translated_at_render_time_not_left_in_english() -> None:
    """The other half of the same node. "showing N of M" was raw English in every
    locale; it must go through the template-is-the-key helper, with the numbers
    as data.
    """
    render = _populated_render(_render_agenda())
    assert "showing ${rows.length} of ${AG.events.length}" not in render, (
        "the bare English count is back in the markup"
    )
    assert '_bulTf("showing {shown} of {total}"' in render, (
        "the count must be translated through _bulTf with the numbers as data; "
        f"got: {render.strip()[:300]}"
    )


def test_the_count_template_is_keyed_in_every_locale_with_both_placeholders() -> None:
    """A template key whose translation dropped a placeholder would render a
    literal "{total}" to the user -- worse than the English it replaced."""
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12, f"expected 12 locales, found {len(files)}"
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert _COUNT_KEY in data, f"{path.name} has no key for {_COUNT_KEY!r}"
        value = data[_COUNT_KEY]
        assert "{shown}" in value and "{total}" in value, (
            f"{path.name}: the translation lost a placeholder -- {value!r}"
        )
        if path.stem != "en":
            assert value != _COUNT_KEY, f"{path.name}: untranslated passthrough"


def test_the_empty_list_render_keeps_the_caveat_alone_in_its_node() -> None:
    """The no-events branch already had the right shape (the caveat is the whole
    paragraph). Pin it, so a future edit that adds "…and here is why" to that
    line breaks a test rather than a locale.
    """
    render = _empty_render(_render_agenda())
    assert '<p class="hint">${esc(AG.caveat)}</p>' in render, (
        f"the empty-list caveat must stay alone in its paragraph; got: {render.strip()[:300]}"
    )
