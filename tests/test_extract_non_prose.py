"""Script code and LaTeX never become keywords (R699, causes 3 and 4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-10-06 keyword triage found jQuery calls left in the body of ko pages
(`addclass`, `attr`, `pdesc`, `pmurl`) and LaTeX macros in en articles (`mathcal`,
`mathbf`). Batch 1 of the stoplist hides those exact words; these tests use words it does
NOT list (`slidetoggle`, `prependto`, `boldsymbol`, `mathscr`), because the point of the
fix is that the next unlisted method or macro is never minted either.
"""

from __future__ import annotations

import time

from src.analytics.extract import (
    BaselineExtractor,
    _strip_code_lines,
    _strip_latex,
    strip_non_prose,
)

KO_WITH_SCRIPT = """국내 최대 쇼핑몰이 새로운 배송 서비스를 시작했다고 밝혔다.
$('#pdesc').slideToggle(200); $('.pmurl').prependTo('#box');
});
회사 관계자는 고객 반응이 매우 좋다고 말했다. 배송 서비스는 전국으로 확대된다.
"""

EN_WITH_LATEX = (
    "Researchers proved that for every family $\\mathscr{F}$ of sets the bound "
    "$\\boldsymbol{x} \\leq \\frac{n}{2}$ holds, a result about combinatorics that "
    "mathematicians had conjectured for decades. The combinatorics community welcomed it. "
    "\\begin{equation} \\sum_{i} x_i = \\boldsymbol{y} \\end{equation}"
)


def _terms(text: str, language: str) -> set[str]:
    return {t.normalized for t in BaselineExtractor().extract(text, language=language)}


# --------------------------------------------------------------------------- #
# through the extractor
# --------------------------------------------------------------------------- #
def test_script_code_in_a_korean_page_mints_no_keyword():
    terms = _terms(KO_WITH_SCRIPT, "ko")
    for junk in ("slidetoggle", "prependto", "pdesc", "pmurl", "box"):
        assert junk not in terms, (junk, sorted(terms))
    assert any("서비스" in t for t in terms), sorted(terms)


def test_latex_macros_mint_no_keyword():
    terms = _terms(EN_WITH_LATEX, "en")
    for junk in ("boldsymbol", "mathscr", "frac", "leq", "equation", "sum"):
        assert junk not in terms, (junk, sorted(terms))
    assert "combinatorics" in terms


# --------------------------------------------------------------------------- #
# what must NOT be removed
# --------------------------------------------------------------------------- #
def test_prose_with_parentheses_and_semicolons_is_kept():
    prose = (
        "The minister (who spoke on Tuesday) said prices rose; analysts disagreed.\n"
        "Sales were $5 million, up from $4 million (a 25% rise).\n"
    )
    assert _strip_code_lines(prose) == prose


def test_a_sentence_quoting_one_function_call_is_kept():
    prose = "Developers were told to call document.getElementById in their own scripts from now on.\n"
    assert _strip_code_lines(prose) == prose


def test_backslashes_without_latex_are_kept():
    for text in ("Hello\\nWorld from C:\\Users\\Bob", "a regex like \\d+ or \\w+ matched"):
        assert _strip_latex(text) == text


def test_the_text_keeps_its_length_so_offsets_stay_true():
    for text in (KO_WITH_SCRIPT, EN_WITH_LATEX):
        out = strip_non_prose(text)
        assert len(out) == len(text)
        assert out.count("\n") == text.count("\n")


# --------------------------------------------------------------------------- #
# linear on hostile input (this runs on every indexed article)
# --------------------------------------------------------------------------- #
def test_hostile_input_is_linear():
    for chunk in ("$(", "\\mathcal{", "\\begin{", "{;", "$('#a').attr(", "\\" * 7):
        small, big = chunk * 20_000, chunk * 80_000
        t0 = time.perf_counter()
        strip_non_prose(small)
        t_small = time.perf_counter() - t0
        t0 = time.perf_counter()
        strip_non_prose(big)
        t_big = time.perf_counter() - t0
        assert t_big < max(0.5, 8 * t_small), (chunk, t_small, t_big)
