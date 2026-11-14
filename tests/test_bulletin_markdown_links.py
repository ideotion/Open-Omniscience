"""The bulletin's Markdown export links only to http, https and mailto, like its HTML export.

A title is source text and reaches the ``.md`` file as written; the reader's own Markdown renderer
makes the links there, so the check runs over the whole rendered text, by link target (#1949 leftover).
Each hostile case is red on main before ``_md_safe_links`` and green after it.
"""

from __future__ import annotations

import re

import pytest

from src.bulletin.render import _md_safe_links, render_markdown
from tests.test_bulletin_render import _WITH_STORIES


def _with_titles(*rows: dict) -> dict:
    stories = dict(_WITH_STORIES["stories"])
    first = dict(stories["stories"][0], article_rows=list(rows))
    stories["stories"] = [first, *stories["stories"][1:]]
    return dict(_WITH_STORIES, stories=stories)


# Every target CommonMark would follow after `](`, after `]:`, or inside `<...>`, with its scheme.
_LIVE_INLINE = re.compile(r"(?<!\\)\]\(\s*<?([^\s)>]*)")
_LIVE_DEFINITION = re.compile(r"(?<!\\)\]:[ \t]*\n?[ \t]*<?(\S*?)>?(?:\s|$)")
_LIVE_ANGLE = re.compile(r"(?<!\\)<([A-Za-z][A-Za-z0-9+.-]*:|[A-Za-z/!?])")


def _unsafe_targets(md: str) -> list[str]:
    bad = [
        t
        for t in _LIVE_INLINE.findall(md) + _LIVE_DEFINITION.findall(md)
        if not re.match(r"(?i)(https?|mailto):", t)
    ]
    bad += [t for t in _LIVE_ANGLE.findall(md) if not re.match(r"(?i)(https?|mailto):", t)]
    return bad


@pytest.mark.parametrize(
    "title",
    [
        "[click](javascript:location=name)",
        "[[a](javascript:x)](javascript:y)",
        "[a [b] c](javascript:x)",
        r"[a\]b](javascript:x)",
        "[a]( javascript:x)",
        "[a](<javascript:x>)",
        "[a](JavaScript:x)",
        "![a](javascript:x)",
        "[a](data:text/html,x)",
        "[b]: javascript:x",
        "<javascript:x>",
        '<a href="javascript:x">a</a>',
        "<img src=x onerror=alert(1)>",
    ],
)
@pytest.mark.parametrize("url", [None, "https://a.example/"])
def test_a_link_hidden_in_a_title_is_not_a_link_in_markdown(title: str, url) -> None:
    md = render_markdown(_with_titles({"title": title, "url": url}))
    assert _unsafe_targets(md) == []
    assert "javascript" in md.lower() or "data:" in md or "onerror" in md  # escaped, never removed


@pytest.mark.parametrize(
    "url", ["https://example.org/a?b=1", "http://example.org/", "mailto:desk@example.org"]
)
def test_an_ordinary_link_stays_a_link_in_markdown(url: str) -> None:
    md = render_markdown(_with_titles({"title": "Headline", "url": url}))
    assert f"[Headline]({url})" in md


def test_safe_forms_and_already_escaped_text_are_left_alone() -> None:
    text = "[a](https://x/) <https://x/> [b]: mailto:d@x \\<i> 3 < 4 `[0001]`"
    assert _md_safe_links(text) == text


def test_the_markdown_without_hostile_titles_is_unchanged() -> None:
    """The pass rewrites only what it must: an ordinary edition reads the same before and after it."""
    md = render_markdown(_WITH_STORIES)
    assert _md_safe_links(md) == md
