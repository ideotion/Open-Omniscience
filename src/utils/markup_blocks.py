"""
Strip delimited BLOCKS out of untrusted markup in one linear pass.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE SHAPE THIS EXISTS TO REPLACE. ``OPEN.*?CLOSE`` is the textbook way to remove a
block, and it is fine right up until an opener has no closer: the lazy ``.*?``
expands to end-of-document, fails, and the engine restarts that scan from the NEXT
opener -- so K openers cost K*N. It is reached by ordinary broken markup, not by a
crafted input, and the cliff turns only on whether the closers happen to be there.

That was found in 2026-08-05 in the HTML path (``<style>``/``<script>``), fixed
there, written into the ledger -- and was still live in
``src.wiki.corpus.plain_from_wikitext`` on 2026-09-07, in THREE patterns
(``<ref>…</ref>``, ``{|…|}``, ``<!--…-->``), on the path every watched-page sync and
every dump ingest runs through. MEASURED on the real function at 400,000 chars:
0.014 s well-formed against **13.4 s** for unclosed-``<ref>`` spam and 12.3 s for
unclosed-``{|``. A fix recorded in the ledger does not propagate itself to a sibling
module; only a shared primitive does, which is why this is a module rather than a
second copy of the same loop.

WHAT DOES NOT WORK, recorded so it is not re-attempted: possessive quantifiers and
an unrolled loop remove the BACKTRACKING and buy about 2x, because the K restarts
are not backtracking -- they are K separate linear scans. Leaving the regex engine
is what fixes it.

THE SAME SHAPE, WORN DIFFERENTLY (2026-09-09). Six more patterns in that same wiki
strip read ``OPEN[^X]*CLOSE``: an opener with no closer makes the character class
consume to end-of-document and then backtrack, which is again K scans, and they were
the expensive half -- up to 14.769 s -> 59.445 s through the whole strip for a 2x
input. They CAPTURE and rewrite rather than remove, so :func:`sub_anchored` replaces
only the "try again one character to the right" loop and leaves the pattern, its
groups and the replacement template in the regex engine. So does the ``<ref …>``
BLOCK OPENER, which carried the shape INSIDE this module's own scanner, because
``strip_blocks`` searches with it (:func:`search_anchored`).

HONEST COST, and it is not small. The block scanner pays two Python-level searches
per block: 0.0056 s against 0.0048 s per 400,000 chars of ref-heavy wikitext (+17%).
The anchored substitutions pay a Python loop iteration per CONSTRUCT, and there are
seven of them over every page, which is a bigger bill: measured on well-formed
wikitext, **0.66 -> 1.33 ms** for a typical 20 KB page, 3.15 -> 6.60 ms at 100 KB,
13.67 -> 28.57 ms at 420 KB -- about 2.1x. Against it: 59.445 s -> 0.0136 s on the
broken input, and the broken input is ordinary malformed wikitext, not a crafted
attack. Both numbers are stated so the trade stays visible rather than discovered.
"""

from __future__ import annotations

import re
from collections.abc import Callable

#: Where to resume after a FAILED attempt at an opener, or ``None`` for "nothing can
#: match in the rest of the document". Takes (text, opener start, anchor end).
Resync = Callable[[str, int, int], int | None]


def strip_blocks(
    text: str,
    opener: re.Pattern[str],
    closer_for: Callable[[re.Match[str]], re.Pattern[str]],
    repl: str = " ",
    *,
    find_opener: Callable[[str, int], re.Match[str] | None] | None = None,
) -> str:
    """Replace every COMPLETE ``opener…closer`` block with ``repl``. Linear.

    ``closer_for`` maps an opener match to the closer that ends it, so one call
    can serve several tag families (``<ref>`` closes with ``</ref>``, ``{|`` with
    ``|}``) while keeping each family's exhaustion separate.

    TWO CURSORS, and the distinction between them is the correctness argument:
    ``copied`` is how far the OUTPUT has been written, ``scan`` is where the next
    search starts. An opener whose family can no longer close must advance only
    ``scan`` -- advancing ``copied`` too would silently swallow the text before it,
    which is the bug a randomised differential caught in the first draft of the
    HTML version.

    An unmatched opener RETIRES its family for the remainder of the document: if
    there is no closer after position p there is none after any q > p, so every
    later opener of that family can be skipped without re-scanning. That is what
    turns K scans into one.

    An input with nothing to remove returns the ORIGINAL object, byte-identical,
    so a caller's offsets into unchanged text stay exact.

    ``find_opener`` replaces ``opener.search`` when the OPENER ITSELF carries the
    quadratic shape -- ``<ref[^>]*>`` in a document with no ``>`` costs a full scan
    per ``<ref``, inside the very function written to stop that. Pass
    :func:`search_anchored` bound to the opener's anchor and resync rule; the
    matches it returns are the same matches, found in one walk instead of K.
    """
    search = find_opener if find_opener is not None else opener.search
    out: list[str] = []
    copied = 0
    scan = 0
    exhausted: set[tuple[str, int]] = set()
    while True:
        m = search(text, scan)
        if m is None:
            break
        closer = closer_for(m)
        # Keyed on the closer's PATTERN **and FLAGS**, not on the opener's text.
        # The opener's text is wrong because `<ref>` and `<REF name=x>` are one
        # family that must retire together, or a document alternating their
        # spellings pays a scan per opener again. The flags are in the key because
        # two closers can share a source string and differ only in case-sensitivity,
        # and those are genuinely different families -- cheap to get right now,
        # invisible to every test if it is got wrong.
        key = (closer.pattern, closer.flags)
        if key in exhausted:
            scan = m.end()  # copy cursor untouched: the opener stays in the output
            continue
        close = closer.search(text, m.end())
        if close is None:
            exhausted.add(key)
            scan = m.end()
            continue
        out.append(text[copied : m.start()])
        out.append(repl)
        copied = scan = close.end()
    if not out:
        return text
    out.append(text[copied:])
    return "".join(out)


def strip_one_block(
    text: str,
    opener: re.Pattern[str],
    closer: re.Pattern[str],
    repl: str = " ",
    *,
    find_opener: Callable[[str, int], re.Match[str] | None] | None = None,
) -> str:
    """:func:`strip_blocks` for the common case of ONE opener/closer pair."""
    return strip_blocks(text, opener, lambda _m: closer, repl, find_opener=find_opener)


#: Characters that make a family's body class stop. Used by :func:`stop_char_resync`.
def stop_char_resync(stops: str) -> Resync:
    """The resync rule for ``ANCHOR [^stops]* CLOSER`` families.

    THE ARGUMENT, because the whole correctness of :func:`sub_anchored` rests on
    it. Take a family whose body cannot contain any character of ``stops`` and
    whose closer BEGINS with one of them (``<[^>]+>``, ``[[…]]``, ``<ref…/>``).
    Let an attempt at opener ``p`` fail, and let ``X`` be the first stop character
    at or after that opener's end.

    * If there is no such ``X``, the body runs to end-of-document and the closer
      can never be found -- and that is true for every LATER opener too, since
      each begins further right. Nothing can match again: **stop**.
    * Otherwise every opener ``p'`` in ``(p, X)`` ends at or before ``X`` (the
      anchor's own text contains no stop character, which is checked by the
      differential), so its body stops at the SAME ``X`` and fails the same way.
      They can all be skipped: **resume at X**.

    That is what turns K failing attempts, each scanning to end-of-document, into
    one walk over the document.
    """
    finder = re.compile("[" + re.escape(stops) + "]")

    def _resync(text: str, _start: int, anchor_end: int) -> int | None:
        hit = finder.search(text, anchor_end)
        return None if hit is None else hit.start()

    # Readable back off the rule, so a test can check the precondition the skip
    # rests on (no anchor may contain a stop character) instead of restating it.
    _resync.stops = stops  # type: ignore[attr-defined]
    return _resync


def needs_char_resync(needed: str) -> Resync:
    """The weaker rule for families the strong one is NOT sound for.

    BOTH external-link forms (``\\[https?://\\S+\\s+([^\\]]+)\\]`` and
    ``\\[https?://\\S+\\]``) look like the family above and are not: ``\\S+``
    crosses ``]`` freely, so a match can END PAST the first ``]`` and a failure at
    one opener says nothing about the next. The randomised differential found it
    on the second form within a few thousand documents, on shapes like
    ``"http:// [https://]] [[]]"`` -- an earlier opener fails, the strong rule
    skips to the first ``]``, and a real match sitting before it is silently lost.
    So this rule never skips: it only answers the one question that IS sound, "can
    anything still match at all" (no ``]`` left after this opener means none after
    any later one either), and otherwise steps to the next opener -- a C-level
    literal scan, not another full attempt.

    This closes the measured cliff, which is opener-only spam with no closer
    anywhere, and NOT the adversarial shape of one far-away closer behind many
    openers. That residue is stated rather than papered over.
    """
    finder = re.compile(re.escape(needed))

    def _resync(text: str, start: int, anchor_end: int) -> int | None:
        return start + 1 if finder.search(text, anchor_end) else None

    _resync.needs = needed  # type: ignore[attr-defined]
    return _resync


def sub_anchored(
    text: str,
    pattern: re.Pattern[str],
    repl: str,
    *,
    anchor: re.Pattern[str] | str,
    resync: Resync,
) -> str:
    """``pattern.sub(repl, text)``, byte-identical, without the K*N failed attempts.

    THE REGEX STILL DOES THE MATCHING. Only the "try again one character to the
    right" loop is replaced -- the pattern, its capture groups and the replacement
    template are handed to the engine unchanged and expanded by ``Match.expand``,
    so no rewrite is re-implemented by hand. That is deliberate: the six patterns
    this serves CAPTURE and rewrite rather than remove, and a hand-written scanner
    per pattern would be six new chances to change the output.

    ``anchor`` is the pattern's own FIXED PREFIX -- a compiled regex, or a plain
    ``str`` when the prefix is a literal (``"<"``, ``"[["``, ``"<ref"``), which is
    taken through ``str.find`` and is about twice as fast. It is what makes the scan
    linear: finding the next candidate is a C-level search, and only real candidates
    cost an attempt.

    IT MUST BE THE PATTERN'S OWN PREFIX, not merely something that marks every
    start, and the difference is not cosmetic. Widening ``[[File|Image|Category``
    to ``[[`` still marks every start -- and breaks the strong resync rule, because
    the attempt then fails at the WORD rather than at the closer, which says nothing
    about the closer the skip is about to jump over. ``"[[x[[File a]]"`` is the
    counterexample: the attempt at 0 fails, the rule skips to the ``]`` at 11, and
    the real match at 3 is lost. ``tests/test_markup_anchored_subs.py`` keeps it.

    ``resync`` decides where to resume after a FAILED attempt, or returns ``None``
    to say nothing can match in the rest of the document. It is the only place a
    family's specific reasoning lives; see :func:`stop_char_resync`.

    An input with nothing to replace returns the ORIGINAL object, byte-identical.
    """
    out: list[str] = []
    copied = 0
    pos = 0
    n = len(text)
    # The scan is INLINED rather than delegated to search_anchored, and the hot
    # lookups are hoisted, because this runs once per construct on every healthy
    # page too: the driver trades a C-level ``re.sub`` for a Python loop, and the
    # loop's own overhead is the whole of that trade. Measured on a 20 KB page,
    # 1.77 ms -> 1.06 ms against the 0.76 ms the plain ``re.sub`` chain costs.
    # A literal prefix goes through str.find, which beats a compiled regex about 2:1
    # on the same scan; a non-literal prefix keeps its pattern. Split before the loop
    # so the hot path branches on a None check rather than on isinstance.
    lit = anchor if isinstance(anchor, str) else ""
    rx = None if isinstance(anchor, str) else anchor
    alen = len(lit)
    try_match = pattern.match
    add = out.append
    literal = repl if "\\" not in repl else None  # no backreference: skip expand()
    while pos <= n:
        if rx is None:
            start = text.find(lit, pos)
            if start < 0:
                break
            anchor_end = start + alen
        else:
            a = rx.search(text, pos)
            if a is None:
                break
            start, anchor_end = a.start(), a.end()
        m = try_match(text, start)
        if m is None:
            nxt = resync(text, start, anchor_end)
            if nxt is None:
                break
            pos = nxt if nxt > start else start + 1
            continue
        end = m.end()
        if end == m.start():
            break
        add(text[copied:start])
        add(literal if literal is not None else m.expand(repl))
        copied = pos = end
    if not out:
        return text
    add(text[copied:])
    return "".join(out)


def search_anchored(
    text: str,
    pattern: re.Pattern[str],
    pos: int = 0,
    *,
    anchor: re.Pattern[str] | str,
    resync: Resync,
) -> re.Match[str] | None:
    """``pattern.search(text, pos)``, identical, without the K*N failed attempts.

    The scan :func:`sub_anchored` is built on, exposed separately because
    ``re.Pattern.search`` carries the same cliff as ``re.Pattern.sub`` and for the
    same reason: it too tries the pattern at position after position, and a
    pattern whose body class runs to end-of-document makes each of those attempts
    cost the whole document. ``strip_blocks`` searches with an OPENER pattern, so
    an opener like ``<ref[^>]*>`` re-introduces the very shape that function
    exists to remove -- measured at 2.5 s per 200,000 chars of ``<ref``-without-``>``.
    """
    n = len(text)
    lit = anchor if isinstance(anchor, str) else ""
    rx = None if isinstance(anchor, str) else anchor
    while pos <= n:
        if rx is None:
            start = text.find(lit, pos)
            if start < 0:
                return None
            anchor_end = start + len(lit)
        else:
            a = rx.search(text, pos)
            if a is None:
                return None
            start, anchor_end = a.start(), a.end()
        m = pattern.match(text, start)
        if m is not None:
            return m
        nxt = resync(text, start, anchor_end)
        if nxt is None:
            return None
        pos = nxt if nxt > start else start + 1
    return None


# --------------------------------------------------------------------------- #
#  The HTML family, shared (audit recheck 2026-11-13, P1/P2)
# --------------------------------------------------------------------------- #
# THE SAME MISS A THIRD TIME. The 2026-08-05 fix made the <style>/<script> BLOCK linear in
# src/analytics/extract.py and left, beside it, ``<!--.*?-->`` (the lazy-closer shape) and the
# opener ``<(style|script)\b[^>]*>`` searched with ``.search`` (the ``[^X]*X`` shape), both still
# K*N; and src/ingest/email.py kept all three of the original patterns, on newsletter bodies the
# person did not write. MEASURED on main ca1ab824: 280 KB of unclosed ``<style>`` 42.7 s in the
# newsletter strip, 160 KB of ``<!--`` 1.9 s in the article strip, each 4x per doubling. So the
# HTML family lives HERE, once, and both modules call it.

#: The <style>/<script> opener and its per-tag closers (``</\1\s*>`` as two patterns).
HTML_STYLE_SCRIPT_OPEN = re.compile(r"<(style|script)\b[^>]*>", re.IGNORECASE | re.DOTALL)
#: The whole block, exactly the regex this replaces. It is MATCHED (anchored at an opener the walk found),
#: never searched, so its backreference keeps the regex's own case rules and only the K*N retry loop goes.
#: A cheap superset of every closer either tag's spellings accept (``re.I`` lets ``s`` match ``ſ`` and ``i``
#: match ``ı``/``İ``): none after an opener means no spelling of that tag can close any more.
_HTML_TAG_CLOSE_ANY = {5: re.compile(r"</style", re.IGNORECASE), 6: re.compile(r"</script", re.IGNORECASE)}
_HTML_STYLE_SCRIPT_BLOCK = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
#: The opener's own fixed prefix (``\b`` included, so a failed attempt fails at the ``[^>]*>``
#: body and never at the word, which is what makes the strong resync rule sound).
_HTML_STYLE_SCRIPT_ANCHOR = re.compile(r"<(style|script)\b", re.IGNORECASE)
_GT_RESYNC = stop_char_resync(">")


def find_style_script_opener(text: str, pos: int = 0) -> re.Match[str] | None:
    """``HTML_STYLE_SCRIPT_OPEN.search(text, pos)``, identical, in one walk."""
    return search_anchored(text, HTML_STYLE_SCRIPT_OPEN, pos, anchor=_HTML_STYLE_SCRIPT_ANCHOR, resync=_GT_RESYNC)


def _backref_key(word: str) -> tuple[str, ...]:
    """The closers ``</\\1\\s*>`` accepts depend only on this: the regex engine compares a backreference
    under IGNORECASE character by character through the SIMPLE lowercase mapping. ``str.lower`` is the FULL
    mapping, which differs here for one letter the opener can match (``İ`` folds to ``i`` simply, to ``i̇``
    in full); ``ſ`` and ``ı`` keep their own class (an Opus read of PR #1949 measured all three, and the first
    draft's dict lookup raised KeyError on ``<scrıpt>``). At most a few hundred keys exist, so a dead key per
    spelling keeps the walk linear."""
    return tuple("i" if c == "\u0130" else c.lower() for c in word)


def strip_style_script(text: str, repl: str = " ") -> str:
    r"""``re.sub(r"<(style|script)\b[^>]*>.*?</\1\s*>", repl, text, flags=I|S)``, byte-identical, linear.

    Not :func:`strip_blocks`, and the reason is a case that function gets wrong for this family:
    the opener's ``[^>]*`` crosses ``<``, so ``<style <script>x</script>`` matches the opener
    ``<style <script>``; when ``style`` has no closer, ``strip_blocks`` resumes AFTER that match and
    never sees the ``<script>`` block inside it, which the regex removes. A seeded differential found
    it (``tests/test_html_strips_linear.py``). Here the family comes from the ANCHOR, so a dead
    family's opener costs one anchor step and a live one's opener is matched only when it can be
    used:

    * the regex's opener ends at the FIRST ``>`` after the anchor (``[^>]`` cannot hold one), and its
      lazy body ends at the first closer after that: two literal-ish searches;
    * no ``>`` after an anchor means no later opener can complete either: stop;
    * no closer for a family after one of its openers means none after any later one: the family is
      dead, and its later anchors are stepped over.

    Every live search either removes a block (the scan jumps past its closer) or kills a family, so
    the walk is linear in ``text``. A "family" is one SPELLING's backreference class (:func:`_backref_key`),
    because ``</\1`` accepts different closers for ``style`` and ``ſtyle``; a tag-wide superset search kills
    every spelling of a tag at once in the ordinary case. HONEST WORST CASE: a document that spells the
    opener every possible way, each followed by a closer that only a superset accepts, pays one full
    failed match per spelling (at most 48 for style and 192 for script); measured 0.31 s per failed match
    at the 36 MiB newsletter cap, so about 75 s there, against hours for the K*N regex.
    """
    out: list[str] = []
    copied = pos = 0
    dead: set[tuple[str, ...]] = set()
    dead_tags: set[int] = set()
    while True:
        a = _HTML_STYLE_SCRIPT_ANCHOR.search(text, pos)
        if a is None:
            break
        family = _backref_key(a.group(1))
        tag = len(family)  # 5 is style, 6 is script, whatever the spelling
        if family in dead or tag in dead_tags:
            pos = a.end()
            continue
        gt = text.find(">", a.end())
        if gt < 0:
            break
        if _HTML_TAG_CLOSE_ANY[tag].search(text, gt + 1) is None:
            dead_tags.add(tag)
            pos = a.end()
            continue
        block = _HTML_STYLE_SCRIPT_BLOCK.match(text, a.start())
        if block is None:
            dead.add(family)
            pos = a.end()
            continue
        out.append(text[copied : a.start()])
        out.append(repl)
        copied = pos = block.end()
    if not out:
        return text
    out.append(text[copied:])
    return "".join(out)


def strip_html_comments(text: str, repl: str = " ") -> str:
    """``re.sub(r"<!--.*?-->", repl, text, flags=S)``, byte-identical, linear, in literal scans.

    One family: the first ``<!--`` with no ``-->`` after it ends the walk, since no later one can close.
    Not an HTML sanitiser (CodeQL's "--!>" rule): the output is plain text that is stored and shown
    escaped, and it must stay what the regex gave (a browser also ends a comment at ``--!>``)."""
    out: list[str] = []
    copied = 0
    while True:
        start = text.find("<!--", copied)
        if start < 0:
            break
        end = text.find("-->", start + 4)
        if end < 0:
            break
        out.append(text[copied:start])
        out.append(repl)
        copied = end + 3
    if not out:
        return text
    out.append(text[copied:])
    return "".join(out)


def has_html_comment(text: str) -> bool:
    """``re.search(r"<!--.*?-->", text, flags=S) is not None`` in two literal scans: a closed
    comment exists exactly when some ``-->`` follows the FIRST ``<!--``."""
    i = text.find("<!--")
    return i >= 0 and text.find("-->", i + 4) >= 0


def strip_html_tags(text: str, repl: str = " ") -> str:
    """``re.sub(r"<[^>]+>", repl, text)``, byte-identical, linear, in literal scans.

    A ``<`` opens a tag when the next character exists and is not ``>``; the tag ends at the first ``>``
    after it. ``<>`` fails at its ``<`` and the walk resumes at its ``>``; no ``>`` left means nothing more
    can match. No regex, so no engine retry loop to reason about."""
    out: list[str] = []
    copied = pos = 0
    n = len(text)
    while True:
        start = text.find("<", pos)
        if start < 0 or start + 1 >= n:
            break
        if text[start + 1] == ">":
            pos = start + 1
            continue
        end = text.find(">", start + 1)
        if end < 0:
            break
        out.append(text[copied:start])
        out.append(repl)
        copied = pos = end + 1
    if not out:
        return text
    out.append(text[copied:])
    return "".join(out)
