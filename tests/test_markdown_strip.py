"""The default model bolds headlines; the corpus must not keep the asterisks.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

MEASURED, not suspected: across a 48-item field translation probe (2026-08-12) the
default model wrapped a heading in ``**`` on 50% of its vLLM answers and 64% of its
Ollama answers. A stored translation is escaped into the reader, so those asterisks
reach the page literally -- and the source article's own text is plain, so the markdown
was invented by the model rather than carried across.

THE NEGATIVE SPACE IS THE HALF THAT MATTERS. This runs over every translation and
summary the app stores, so "it leaves ordinary text exactly alone" is a stronger
requirement than "it removes bold".
"""

import pytest

from src.api.llm import strip_markdown_emphasis as strip


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        # The measured case, in the scripts it was measured in.
        ("**Headline** and the body", "Headline and the body"),
        ("**رئيس هاكاينده هيشيلما** يعلن", "رئيس هاكاينده هيشيلما يعلن"),
        ("**Von Blatter zur Milliardenfrage**\n\nDie Rivalität", "Von Blatter zur Milliardenfrage\n\nDie Rivalität"),
        ("__also bold__ here", "also bold here"),
        ("**outer __inner__ text**", "outer inner text"),
    ],
)
def test_paired_emphasis_is_unwrapped_content_intact(raw, want):
    assert strip(raw) == want


@pytest.mark.parametrize(
    "raw",
    [
        "plain prose with nothing to do",
        "a * lone asterisk, and 5 * 3 = 15",            # a footnote marker / arithmetic
        "snake_case_identifier and __dunder alone",     # a lone doubled marker
        "unpaired ** with no partner",
        "** **",                                        # empty: no content to unwrap
        "",
        "第一段。**",
    ],
)
def test_text_without_paired_emphasis_is_returned_BYTE_IDENTICAL(raw):
    """The property that matters most: this touches every stored translation, so
    anything it changes that it was not built to change is silent corpus damage."""
    assert strip(raw) == raw


def test_it_is_idempotent():
    once = strip("**a** and **b**")
    assert strip(once) == once


def test_the_strip_is_DISCLOSED_when_it_fires_and_absent_when_it_does_not():
    """The stored text is no longer verbatim what the model returned. A reader
    comparing a stored translation against a re-run should be able to see why they
    differ -- and must not be told something was cleaned when nothing was."""
    from src.api.llm import _cleaned

    text, method = _cleaned("**Bold** lead", {"mode": "single"})
    assert text == "Bold lead"
    assert method["markdown_stripped"] is True
    assert method["mode"] == "single", "the original method fields must survive"

    text2, method2 = _cleaned("nothing to clean", {"mode": "single"})
    assert text2 == "nothing to clean"
    assert "markdown_stripped" not in method2, (
        "an absent key means the stored text IS the model's output; claiming a strip "
        "that did not happen is a fabricated disclosure"
    )


def test_every_production_text_path_goes_through_the_strip():
    """Summary, translation, single-call and chunked all assemble their result in ONE
    function, which is why the strip is applied there rather than at three call sites.
    A fourth return added later that skips it would leak again."""
    import ast
    import inspect

    import src.api.llm as L

    src = inspect.getsource(L._run_over_long_text)
    tree = ast.parse(src.lstrip())
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return) and n.value is not None]
    assert returns, "the function must return something"
    for r in returns:
        assert isinstance(r.value, ast.Call) and getattr(r.value.func, "id", "") == "_cleaned", (
            "every return of the one text-assembly function must pass through _cleaned; "
            f"found a bare return at line {r.lineno} of the function"
        )
