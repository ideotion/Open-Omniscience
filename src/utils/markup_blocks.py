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

HONEST COST. On WELL-FORMED input this is slightly slower than a C-level
``re.sub``, because it pays two Python-level searches per block: measured
0.0056 s against 0.0048 s per 400,000 chars of ref-heavy wikitext (+17%). Trading
0.8 ms on the healthy path for 14 s on the broken one is the whole point, and both
numbers are stated so the trade stays visible.
"""

from __future__ import annotations

import re
from collections.abc import Callable


def strip_blocks(
    text: str,
    opener: re.Pattern[str],
    closer_for: Callable[[re.Match[str]], re.Pattern[str]],
    repl: str = " ",
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
    """
    out: list[str] = []
    copied = 0
    scan = 0
    exhausted: set[tuple[str, int]] = set()
    while True:
        m = opener.search(text, scan)
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
    text: str, opener: re.Pattern[str], closer: re.Pattern[str], repl: str = " "
) -> str:
    """:func:`strip_blocks` for the common case of ONE opener/closer pair."""
    return strip_blocks(text, opener, lambda _m: closer, repl)
