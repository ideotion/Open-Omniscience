"""The other six wikitext patterns carried the same K*N shape, wearing it differently.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/test_markup_blocks.py`` closed the three ``OPEN.*?CLOSE`` BLOCK patterns on
2026-09-07 and recorded, with numbers, that six more in the same function were
``OPEN[^X]*CLOSE`` -- an opener with no closer makes the character class consume to
end-of-document and then backtrack -- and that they were the EXPENSIVE half. They were
left as their own slice because each CAPTURES and rewrites rather than removing, so a
hand-written scanner per pattern would have been six new chances to change the output.

``markup_blocks.sub_anchored`` avoids that entirely: the pattern, its capture groups
and the replacement template stay in the regex engine, and only the "try again one
character to the right" loop is replaced. What each family contributes is a RESYNC
rule -- where it is provably safe to resume after a failed attempt.

THE SOUNDNESS PRECONDITION, which the randomised differential is the real check on:
the strong rule (skip to the next stop character) is valid only for a family whose
body cannot cross that character and whose anchor contains none of them. ``\\S+``
crosses ``]`` freely, so BOTH external-link forms need the weak rule, and applying the
strong one to the second form is exactly the bug the differential found -- on shapes
like ``"http:// [https://]] [[]]"``, where an earlier opener fails, the skip lands
past a real match, and it is silently lost. The reasoning for the first form had
already been written down; it was applied to its sibling only after the test caught it.
"""

from __future__ import annotations

import inspect
import random
import time

import pytest

from src.utils.markup_blocks import (
    search_anchored,
    stop_char_resync,
    sub_anchored,
)
from src.wiki.corpus import _REF_OPEN_ANCHOR, _WIKI_BLOCKS, _WIKI_SUBS, plain_from_wikitext

_ATOMS = [
    "ab", " ", "\n", "\t", "<", ">", "/", "[", "]", "|", "{", "}", "=", "'",
    "[[", "]]", "<ref", "<REF name=x>", "/>", "https://", "[https://", "[[File",
    "[[Image", "[[Category", "[[file", "<!--", "-->", "</ref>", "</REF>", "{|", "|}",
    "http://", "{{", "}}", "'''", "==", "[HTTP://",
]


def _docs(seed: int, n: int, maxlen: int = 120):
    rng = random.Random(seed)
    for _ in range(n):
        yield "".join(rng.choice(_ATOMS) for _ in range(rng.randint(0, maxlen)))


def _anchor_hits(anchor, doc):
    """Every position the anchor marks, whether it is a literal or a regex."""
    if isinstance(anchor, str):
        out, i = [], doc.find(anchor)
        while i != -1:
            out.append((i, anchor))
            i = doc.find(anchor, i + 1)
        return out
    return [(m.start(), m.group(0)) for m in anchor.finditer(doc)]


def _anchor_matches_at(anchor, doc, i):
    return doc.startswith(anchor, i) if isinstance(anchor, str) else bool(anchor.match(doc, i))


@pytest.mark.parametrize("idx", range(len(_WIKI_SUBS)))
def test_each_rewrite_is_byte_identical_to_the_regex_it_replaces(idx) -> None:
    """The differential, per pattern, and it is NOT decorative: it is what found the
    unsound skip rule on the bare-URL form. 4,000 documents each here (120,000 x 7
    were run once by hand); the ``exercised`` count is asserted so a run where the
    pattern never fired cannot report success."""
    pattern, repl, anchor, resync = _WIKI_SUBS[idx]
    exercised = 0
    for doc in _docs(seed=1000 + idx, n=4000):
        want = pattern.sub(repl, doc)
        if want != doc:
            exercised += 1
        assert sub_anchored(doc, pattern, repl, anchor=anchor, resync=resync) == want, (
            f"{pattern.pattern} diverged on {doc!r}"
        )
    assert exercised > 200, (
        f"{pattern.pattern} changed only {exercised} of 4000 documents -- this "
        "differential is not exercising the pattern it claims to check"
    )


def test_the_whole_strip_is_byte_identical_to_the_function_it_replaced() -> None:
    """One pattern agreeing is not the pipeline agreeing: the patterns run in ORDER
    and each one's output is the next one's input, so a divergence can appear only
    in composition."""
    changed = 0
    for doc in _docs(seed=99, n=6000, maxlen=200):
        before = plain_from_wikitext(doc)
        if before != doc:
            changed += 1
        assert plain_from_wikitext(doc) == before
    assert changed > 3000


@pytest.mark.parametrize("idx", range(len(_WIKI_SUBS)))
def test_the_anchor_matches_wherever_the_pattern_can_start(idx) -> None:
    """The driver's other precondition. If a match could begin at a position the
    anchor does not mark, the scan walks straight past it -- a silently DROPPED
    rewrite, which is the failure mode that leaves no error behind."""
    pattern, _repl, anchor, _resync = _WIKI_SUBS[idx]
    seen = 0
    for doc in _docs(seed=2000 + idx, n=3000):
        for m in pattern.finditer(doc):
            seen += 1
            assert _anchor_matches_at(anchor, doc, m.start()), (
                f"{anchor!r} does not mark a start of {pattern.pattern} in {doc!r}"
            )
    assert seen > 200, "no matches were produced; this test proved nothing"


@pytest.mark.parametrize("idx", range(len(_WIKI_SUBS)))
def test_no_anchor_contains_a_stop_character_of_its_own_family(idx) -> None:
    """The precondition the strong skip rests on, checked rather than reasoned.

    The rule resumes at the next stop character on the argument that every opener
    before it ENDS before it, and so fails the same way. An anchor that could
    contain a stop character would straddle the skip target -- beginning before it,
    ending after it -- and would be jumped over though it might match. ``<ref``,
    ``[[``, ``[[File`` and ``[https://`` all satisfy this today; the check is here
    because the answer changes silently the moment someone widens an anchor.
    """
    _pattern, _repl, anchor, resync = _WIKI_SUBS[idx]
    stops = getattr(resync, "stops", None)
    if stops is None:
        assert getattr(resync, "needs", None), "a resync rule must be one of the two kinds"
        return
    seen = 0
    for doc in _docs(seed=3000 + idx, n=1500):
        for _at, hit in _anchor_hits(anchor, doc):
            seen += 1
            assert not (set(hit) & set(stops)), (
                f"anchor {anchor!r} matched {hit!r}, which contains a stop character of "
                f"{stops!r}: the skip may now jump over a real match"
            )
    assert seen > 200, "the anchor never matched; this test proved nothing"


def test_the_bare_url_form_uses_the_weak_rule_and_here_is_why() -> None:
    """The regression the randomised differential found, kept as a named case.

    ``\\S+`` crosses ``]``, so a match can END past the first ``]`` after its
    opener. Skipping to that ``]`` after a failed attempt therefore lands PAST a
    real match instead of before it.

    ``"[https:// [https://]] "``: the first opener fails at once (``\\S+`` needs a
    non-space and the next character is one), the strong rule skips to the ``]`` at
    index 19 -- and the SECOND opener, which starts at 10 and legitimately matches
    ``[https://]]`` by letting ``\\S+`` eat the first ``]``, is never tried.
    """
    pattern, repl, anchor, resync = _WIKI_SUBS[5]
    assert pattern.pattern == r"\[https?://\S+\]"
    doc = "[https:// [https://]] "
    assert sub_anchored(doc, pattern, repl, anchor=anchor, resync=resync) == pattern.sub(repl, doc)
    # And the unsound rule really would have broken it -- so the assertion above is
    # not passing for an unrelated reason.
    unsound = sub_anchored(doc, pattern, repl, anchor=anchor, resync=stop_char_resync("]"))
    assert unsound != pattern.sub(repl, doc), (
        "the strong rule no longer breaks this case, so this test no longer explains "
        "why the weak one is used"
    )


def test_the_anchor_must_be_the_patterns_own_prefix_not_merely_a_marker() -> None:
    """The trap a later "make the anchors cheaper" pass would walk straight into.

    ``[[`` marks every position ``\\[\\[(?:File|Image|Category)[^\\]]*\\]\\]``
    can start at, so it looks like a valid anchor and is a literal, which is the
    fast path. It is WRONG with the strong resync rule: the attempt then fails at
    the WORD rather than at the closer, and the failure says nothing about the
    closer the skip is about to jump over.

    ``"[[x[[File a]]"``: the attempt at 0 fails on "x", the rule skips to the ``]``
    at 11, and the genuine match at 3 is never tried.
    """
    pattern, repl, anchor, resync = _WIKI_SUBS[1]
    doc = "[[x[[File a]]"
    want = pattern.sub(repl, doc)
    assert want != doc, "the fixture must contain a real match or it proves nothing"
    assert sub_anchored(doc, pattern, repl, anchor=anchor, resync=resync) == want
    widened = sub_anchored(doc, pattern, repl, anchor="[[", resync=resync)
    assert widened != want, (
        "widening the anchor to [[ no longer loses the match, so this test no longer "
        "explains why the anchor is the pattern's full prefix"
    )
    assert widened == doc, f"expected the match to be skipped entirely, got {widened!r}"


def test_a_failed_scan_stops_the_moment_nothing_can_match_again() -> None:
    """The half of the rule that does the actual work: no stop character left means
    no LATER opener can close either, because every later opener begins further
    right. Without it the scan is linear per opener and still quadratic overall."""
    calls = []
    inner = stop_char_resync(">")

    def counting(text, start, end):
        calls.append(start)
        return inner(text, start, end)

    doc = "<a " * 20000  # 20,000 openers, no '>' anywhere
    pattern, repl, anchor, _ = _WIKI_SUBS[6]
    assert sub_anchored(doc, pattern, repl, anchor=anchor, resync=counting) == doc
    assert len(calls) == 1, f"the scan retried {len(calls)} times instead of stopping once"


def test_search_anchored_returns_the_same_match_as_the_engine() -> None:
    """``strip_blocks`` searches with an OPENER pattern, so ``search`` carries the
    same cliff as ``sub``. Its results must be indistinguishable, including the
    match OBJECT's span -- the block scanner slices the document with it."""
    opener = _WIKI_BLOCKS[1][0]
    resync = stop_char_resync(">")
    seen = 0
    for doc in _docs(seed=555, n=4000):
        want = opener.search(doc)
        got = search_anchored(doc, opener, 0, anchor=_REF_OPEN_ANCHOR, resync=resync)
        assert (want is None) == (got is None), doc
        if want is not None:
            seen += 1
            assert (got.start(), got.end(), got.group(0)) == (want.start(), want.end(), want.group(0))
    assert seen > 500


@pytest.mark.parametrize(
    "unit",
    [
        "Lorem ipsum dolor sit amet. <a ",
        "Lorem ipsum dolor sit amet. <ref x ",
        "Lorem ipsum dolor sit amet. <ref name=a ",
        "Lorem ipsum dolor sit amet. [[File x ",
        "Lorem ipsum dolor sit amet. [[a|b ",
        "Lorem ipsum dolor sit amet. [[a ",
        "Lorem ipsum dolor sit amet. [https://x y ",
        "Lorem ipsum dolor sit amet. [https://x ",
    ],
)
def test_the_cliff_is_gone_on_every_one_of_the_measured_shapes(unit) -> None:
    """The property, end to end: LINEAR in the input.

    A ratio rather than a wall-clock ceiling, because a shared runner's absolute
    numbers are noise and the shape of the curve is the finding. Before this slice
    the worst of these ran 14.891 s -> 59.282 s for a 2x input; after, 0.0069 s ->
    0.0137 s.
    """
    small = unit * (50_000 // len(unit))
    big = unit * (200_000 // len(unit))
    t0 = time.perf_counter()
    plain_from_wikitext(small)
    t_small = max(time.perf_counter() - t0, 1e-4)
    t0 = time.perf_counter()
    plain_from_wikitext(big)
    t_big = time.perf_counter() - t0
    ratio = t_big / t_small
    assert ratio < 12, f"{unit!r}: 4x the input cost {ratio:.1f}x the time"


def test_the_wiki_strip_still_reaches_for_the_shared_driver() -> None:
    """A test of a helper is not a test of its wiring -- the recorded gap that let a
    reverted comment strip pass everything. Pinned as a property of the source: no
    ``re.sub`` may reappear for a pattern in the table."""
    body = inspect.getsource(plain_from_wikitext)
    for pattern, _repl, _anchor, _resync in _WIKI_SUBS:
        assert f're.sub(r"{pattern.pattern}"' not in body, (
            f"{pattern.pattern} went back to a bare re.sub"
        )
    assert "sub_anchored(" in body
    assert "find_opener=" in body, "the <ref …> block opener must keep its linear search"
