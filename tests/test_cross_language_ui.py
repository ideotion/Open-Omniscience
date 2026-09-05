"""The R1 disclosure's UI wiring — the facts a node suite cannot see.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What the notice SAYS is proven behaviourally in
``tests/cross_language_notice_node_test.js``, which extracts the real renderer from the
shipped module. Only the wiring is checked here: that the notice is actually rendered
into the article list, that the reader's locale reaches the request, and that the
narrowing control does not silently apply to an id-seeded corpus (which has no term to
widen, so offering the choice would describe a control that does nothing).

Required by ``test_every_node_suite_has_a_driver``: an unrun node suite looks exactly
like a passing one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.js_source_helper import function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


def _analysis() -> str:
    return read_static("app-analysis.js")


def test_the_notice_is_rendered_into_the_article_list() -> None:
    """A disclosure that exists and is never drawn is the dead-end shape this feature is
    most exposed to -- the rings themselves were correct and unread for a year."""
    body = strip_comments(function_body(_analysis(), "_anLoadArticles"))
    assert "_crossLangNotice(d.cross_language" in body, (
        "the notice is not rendered from the /api/articles payload"
    )


def test_the_readers_locale_reaches_the_request_and_only_for_a_text_query() -> None:
    """``ui_lang`` NARROWS an ambiguous term to the ring matching the reader's language.

    It is sent only with a text query: an id-seeded corpus is an exact set with no term
    to widen, so sending expansion parameters there would imply a choice that does not
    exist.
    """
    body = strip_comments(function_body(_analysis(), "_articleQuery"))
    assert 'q.get("query")' in body, "expansion params are not gated on a text query"
    assert "ui_lang" in body and "OOI18N.current" in body, (
        "the reader's locale is not passed, so an ambiguous term cannot be narrowed"
    )
    assert '"expand", "false"' in body, "there is no way to request the literal term"


def test_expansion_is_on_by_default() -> None:
    """R1 rules it ON by default. A default of false would make the feature invisible."""
    src = strip_comments(_analysis())
    assert "let _anExpand = true;" in src, (
        "cross-language expansion is not on by default -- R1 requires it, and the "
        "disclosure plus the one-click narrowing are what make that honest"
    )


def test_cross_language_notice_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "cross_language_notice_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_omnibar_renders_the_disclosure_it_publishes():
    """`search_omni` publishes `cross_language`, a per-row `via_ring` and a separate
    `cross_language_items` count. Until this landed nothing in the frontend read any of
    them -- the "machine-readable answer with no caller" dead end, in the very feature
    whose own commit message names that trap. The BEHAVIOUR is driven in node (the
    renderer, extracted from the shipped module); this pins that the wiring exists at
    all, so a deletion cannot pass by removing the node suite's subject."""
    shell = strip_comments(read_static("app-shell.js"))
    body = function_body(shell, "_omniItems")
    assert "_omniCrossNote(_omniLive.cross_language)" in body, (
        "the omnibar fetches a disclosure and never renders it"
    )
    assert "_omniTypedRows(g)" in body, (
        "the group total must be compared against the rows the reader TYPED, not the "
        "count padded by cross-language sibling rows"
    )
    assert "it.via_ring" in body, "a sibling row must say which concept put it there"


def test_the_omnibar_disclosure_uses_keyed_templates_not_a_built_sentence():
    """A value-bearing sentence is only translatable if its KEY is a fixed template: the
    frame is keyed x12 and the term and the concept are DATA interpolated after."""
    shell = strip_comments(read_static("app-shell.js"))
    body = function_body(shell, "_omniCrossNote")
    assert "tf(" in body and 'OOI18N.tf' in body
    for frame in (
        "{term} also matched as the concept",
        "{term} denotes several concepts, so it was not expanded",
    ):
        assert frame in body, frame
    en_path = Path(__file__).resolve().parents[1] / "src/static/locales/en.json"
    # encoding= is not optional here: the keys asserted below carry curly quotes, so a
    # cp1252 default (Windows) would crash the read rather than fail the assertion.
    en = json.loads(en_path.read_text(encoding="utf-8"))
    for key in (
        "{term} also matched as the concept “{concept}”",
        "{term} denotes several concepts, so it was not expanded",
    ):
        assert key in en, f"the omnibar renders {key!r} with no key behind it"


def test_the_reader_s_sense_choice_reaches_the_request() -> None:
    """R2a's wiring, and the half a node test cannot see.

    The node suite drives the RENDERER, so it proves the pick buttons exist and call the
    handlers. It says nothing about whether the handler's state ever leaves the browser.
    This asserts the query builder actually sends it -- and sends it only under the same
    text-query guard as the rest of R1, since a pin on an id-seeded corpus would name a
    choice that does not exist there.
    """
    body = strip_comments(function_body(_analysis(), "_articleQuery"))
    assert "_anSenses" in body, "the reader's sense choices never reach the request"
    assert 'q.append("sense"' in body, "the pin is not sent as the repeatable sense param"
    guarded = body.split('if (q.get("query"))', 1)
    assert len(guarded) == 2 and "_anSenses" in guarded[1], (
        "the pin is sent outside the text-query guard -- it would ride an id-seeded corpus"
    )


def test_choosing_a_sense_and_clearing_it_both_re_run_the_search() -> None:
    """A pick that does not re-run is a label, not a search."""
    analysis = strip_comments(_analysis())
    for name in ("_anPickSense", "_anClearSense"):
        body = function_body(analysis, name)
        assert "_anLoadArticles" in body, f"{name} does not re-run the article list"
        assert "_anSenses" in body, f"{name} does not touch the sense state"


def test_a_rejected_pin_is_rendered_rather_than_swallowed() -> None:
    """The endpoint reports a pin it could not apply; a surface that drops it lies.

    Guarded on the KEY the notice renders, not merely on the field name appearing
    somewhere: the payload field could be read and the sentence still never drawn.
    """
    body = strip_comments(function_body(_analysis(), "_crossLangNotice"))
    assert "pin_applied" in body and "pinned_ring" in body
    assert "The sense you chose is not one this word belongs to" in body


def test_every_string_the_pick_renders_is_keyed_in_all_twelve_locales() -> None:
    """A value-bearing sentence needs a keyable FRAME, and a frame needs all 12 files.

    Adding a key to en.json alone leaves `--min 100` red, so this is the guard that
    catches the half-done version rather than CI.
    """
    body = strip_comments(function_body(_analysis(), "_crossLangNotice"))
    keys = [
        "Search one of them:",
        "{term}: searching the concept “{concept}”, which you chose",
        "Show all senses",
        "The sense you chose is not one this word belongs to, so it was ignored.",
    ]
    for key in keys:
        assert key in body, f"{key!r} is not rendered"
    locales = Path(__file__).resolve().parents[1] / "src/static/locales"
    for path in sorted(locales.glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in keys:
            assert key in table, f"{path.name} has no entry for {key!r}"

