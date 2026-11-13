"""The HTML strips on untrusted text are LINEAR and byte-identical to the regexes they replace.

Audit recheck 2026-11-13 (P1, P2, P8). The 2026-08-05 fix made the article strip's <style>/<script>
BLOCK linear and left three siblings K*N: the comment regex and the opener search beside it in
``src/analytics/extract.py`` (every collected page), all three original patterns in the newsletter
strip (``src/ingest/email.py``, bodies the person did not write, 36 MiB cap), and the keyword
cleaner's tag and e-mail patterns (``src/services/text_processor.py``). MEASURED before the fix:
280 KB of ``<style>`` 42.7 s in the newsletter strip; 160 KB of ``<!--`` 1.92 s in the article
strip; a 20 KB token with no ``@`` 0.48 s in the cleaner; each 4x per doubling.

Two kinds of test, one per property: a DIFFERENTIAL against the old regexes (kept here as the
oracle), on hand shapes, seeded random documents and every real HTML file the repository ships;
and a TIME bound on the measured worst input, read on the thread's own CPU clock (LESSONS, PR #1174).
"""

from __future__ import annotations

import random
import re
from html import unescape
from pathlib import Path

import pytest

from src.analytics.extract import _has_markup, strip_markup
from src.ingest.email import _strip_html
from src.services.text_processor import TextProcessor
from src.utils.markup_blocks import (
    has_html_comment,
    strip_html_comments,
    strip_html_tags,
    strip_style_script,
)
from tests.wallclock_helpers import CPU_CLOCK

_ROOT = Path(__file__).resolve().parents[1]

# The patterns as they shipped before 2026-11-13: the oracle.
_OLD_STYLE_SCRIPT = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_OLD_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OLD_TAG = re.compile(r"<[^>]+>", re.DOTALL)
_OLD_STYLE_OPEN = re.compile(r"<(style|script)\b[^>]*>", re.IGNORECASE | re.DOTALL)
_OLD_EMAIL = re.compile(r"\S+@\S+")
_OLD_MARKUP_TAG = re.compile(r"</?[a-zA-Z][\w-]*(\s[^<>]*?)?/?>", re.DOTALL)
_OLD_ENTITY = re.compile(r"&[#a-zA-Z][#a-zA-Z0-9]*;")


def _old_email_strip(html_text: str) -> str:
    text = _OLD_STYLE_SCRIPT.sub(" ", html_text)
    text = _OLD_COMMENT.sub(" ", text)
    text = _OLD_TAG.sub(" ", text)
    text = unescape(text)
    text = text.replace("​", "").replace("﻿", "")
    return re.sub(r"\s+", " ", text).strip()


def _old_strip_markup(text: str) -> str:
    if not (_OLD_MARKUP_TAG.search(text) or _OLD_STYLE_OPEN.search(text) or _OLD_COMMENT.search(text) or _OLD_ENTITY.search(text)):
        return text
    out = _OLD_STYLE_SCRIPT.sub(" ", text)
    out = _OLD_COMMENT.sub(" ", out)
    out = _OLD_MARKUP_TAG.sub(" ", out)
    return unescape(out)


def _old_clean(text: str) -> str:
    """TextProcessor.clean_text before 2026-11-13, step for step."""
    import html as _html
    import unicodedata

    if not text:
        return ""
    text = _html.unescape(str(text))
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = _OLD_EMAIL.sub(" ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^\w\s\-]", " ", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if unicodedata.category(c)[0] != "C")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"^\s+|\s+$", "", text)


_SHAPES = [
    "",
    "plain text, no markup at all",
    "<p>Hello <b>world</b></p>",
    "<style>body{}</style>after",
    "<STYLE type='x'>a</STYLE >tail <script src=a>b</script>",
    "unclosed <style>body{} and more",
    "<style no close bracket",
    "<!-- c -->x<!-- d",
    "<!---->",
    "<!-->",
    "<!-- a --> <!-- b -->",
    "<!--[if mso]><table><![endif]-->body",
    "a < b and c > d",
    "<<a>",
    "<><a>",
    "<",
    ">",
    "x<y<z",
    "<a href='x'>link</a> mail me@example.org or @handle or trailing@",
    "@@a a@ @a a@b@c",
    "<style>a<style>b</style>c",
    "</style>orphan <script>x",
    "<scriptx>not a script</scriptx>",
    "&amp; &nbsp; &copy;",
]


def _random_doc(rnd: random.Random) -> str:
    atoms = [
        "<style>", "</style>", "<script>", "</script >", "<style ", "<!--", "-->", "<!-->", "<", ">",
        "<div class='a'>", "</p>", "@", "a@b", " ", "\n", "word", "&amp;", "<b>", "x", "<!---->",
    ]
    return "".join(rnd.choice(atoms) for _ in range(rnd.randint(1, 30)))


def _real_html() -> list[Path]:
    """Every HTML file the repository ships: real pages with real scripts, styles and comments."""
    files = sorted((_ROOT / "src" / "static").rglob("*.html")) + sorted((_ROOT / "tests" / "fixtures").rglob("*.html"))
    assert len(files) >= 5, "the real-page sample is gone; point this at other shipped HTML"
    return files


@pytest.mark.parametrize("text", _SHAPES)
def test_each_linear_primitive_matches_its_regex(text: str) -> None:
    assert strip_style_script(text) == _OLD_STYLE_SCRIPT.sub(" ", text)
    assert strip_html_comments(text) == _OLD_COMMENT.sub(" ", text)
    assert strip_html_tags(text) == _OLD_TAG.sub(" ", text)
    assert has_html_comment(text) == (_OLD_COMMENT.search(text) is not None)


@pytest.mark.parametrize("text", _SHAPES)
def test_the_three_public_paths_match_their_old_output(text: str) -> None:
    assert _strip_html(text) == _old_email_strip(text)
    assert strip_markup(text) == _old_strip_markup(text)
    assert TextProcessor().clean_text(text) == _old_clean(text)


def test_randomised_differential() -> None:
    rnd = random.Random(20261113)
    tp = TextProcessor()
    for _ in range(3000):
        s = _random_doc(rnd)
        assert strip_style_script(s) == _OLD_STYLE_SCRIPT.sub(" ", s), s
        assert strip_html_comments(s) == _OLD_COMMENT.sub(" ", s), s
        assert strip_html_tags(s) == _OLD_TAG.sub(" ", s), s
        assert has_html_comment(s) == (_OLD_COMMENT.search(s) is not None), s
        assert _strip_html(s) == _old_email_strip(s), s
        assert strip_markup(s) == _old_strip_markup(s), s
        assert tp.clean_text(s) == _old_clean(s), s


def test_real_pages_come_out_exactly_as_before() -> None:
    """extract.py runs on every article: on real markup the output may not move by one byte."""
    tp = TextProcessor()
    for path in _real_html():
        page = path.read_text(encoding="utf-8", errors="replace")
        assert _strip_html(page) == _old_email_strip(page), path
        assert strip_markup(page) == _old_strip_markup(page), path
        assert tp.clean_text(page) == _old_clean(page), path


def test_clean_text_is_returned_as_the_same_object() -> None:
    """Keyword offsets index into the stored body: text with no markup comes back untouched."""
    clean = "An ordinary sentence about policy, elections and a < b."
    assert strip_markup(clean) is clean
    assert _has_markup(clean) is False


# --------------------------------------------------------------------------- #
#  The time bounds, on the measured worst inputs
# --------------------------------------------------------------------------- #
# Each bound is 5 s of this thread's CPU. The linear code takes milliseconds; the old patterns
# measured 42.7 s (newsletter, 280 KB), about 30 s (article comments, scaled from 1.92 s at
# 160 KB to 640 KB) and about 190 s (cleaner, 400 KB token), so each bar sits far from both.
_BOUND_S = 5.0


def _cpu(fn, arg) -> float:
    t0 = CPU_CLOCK()
    fn(arg)
    return CPU_CLOCK() - t0


@pytest.mark.parametrize(
    "unit,count",
    [("<style>", 40_000), ("<!--", 160_000), ("<a", 160_000), ("<script ", 40_000)],
)
def test_newsletter_strip_is_linear_on_unclosed_markup(unit: str, count: int) -> None:
    assert _cpu(_strip_html, unit * count) < _BOUND_S


@pytest.mark.parametrize("unit,count", [("<!--", 160_000), ("<style ", 80_000), ("<script>", 60_000)])
def test_article_strip_is_linear_on_unclosed_markup(unit: str, count: int) -> None:
    assert _cpu(strip_markup, unit * count) < _BOUND_S


@pytest.mark.parametrize("text", ["a" * 400_000, "@" + "a" * 400_000, "<" * 400_000])
def test_keyword_cleaner_is_linear_on_long_tokens(text: str) -> None:
    assert _cpu(TextProcessor().clean_text, text) < _BOUND_S
