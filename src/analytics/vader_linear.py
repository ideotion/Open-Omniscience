"""VADER's English sentiment in time linear in the text -- with the same output, bit for bit.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Three methods below are adapted from vaderSentiment 3.3.2, Copyright (c) 2016 C.J. Hutto,
under the MIT License; its notice is reproduced above the class that carries them.

WHY THIS EXISTS. Stock VADER is quadratic in the length of a text, in three places:

  * ``_negation_check`` and ``_special_idioms_check`` each begin by lowercasing EVERY
    token of the document, and ``sentiment_valence`` calls them up to four times for
    each word the lexicon knows -- so a document of n tokens is lowercased O(n) times;
  * ``_but_check``, once a document says "but", re-finds each score with
    ``list.index`` and replaces it with ``pop`` + ``insert``: three O(n) list operations
    per token.

A news article is a few hundred tokens, where none of that shows. A re-extraction drain
over imported backups is different: it scores every English article again, and the long
ones (a Wikipedia page, a transcript) dominate it. MEASURED 2026-09-27 on the start of
``docs/USER_MANUAL.md``, stock against this module: 3.1 against 1.6 ms at 3 KB, 21 against
4.0 ms at 10 KB, 144 against 10 ms at 25 KB, 1,527 against 36 ms at 80 KB. On the real
drain (``reindex_articles``, three workers, 600 English texts of about 27 KB cut from this
repo's docs) the wall time went from 157 s to 54 s, and every row it wrote was identical:
all 50 tables matched column for column, apart from the run's timestamps and the engine
stamp.

WHAT CHANGED, AND WHAT DID NOT. The rules, their order and their arithmetic are stock:
every float operation happens in the same order on the same operands, so every score is
the same float. Two things changed: WHERE a lowercased token is read from (a copy made
once per document, instead of one per call), and HOW ``_but_check`` finds "the first
position holding this score" (a heap of positions per score, instead of a scan). The
second needs care, because stock's loop does not do what it appears to: see
:meth:`LinearSentimentIntensityAnalyzer._but_check`.

THE GUARD. This reproduces ONE file: vaderSentiment 3.3.2's ``vaderSentiment.py``, which
its wheel and its sdist both ship with the digest :data:`VADER_SOURCE_SHA256` (checked
2026-09-27, when 3.3.2 of 2020-05-22 was still the newest release on PyPI).
:func:`make_analyzer` hashes the file actually imported and hands back the STOCK analyzer
for any other bytes -- another release, a distribution's patch, a local edit. That
fallback is slower and right by definition: the reproduction is never trusted for code
it was not checked against. ``tests/test_vader_linear.py`` checks it against the stock
analyzer on every CI run that has the [analysis] extra.
"""

from __future__ import annotations

import hashlib
import heapq
import logging
from pathlib import Path
from typing import Any

import vaderSentiment.vaderSentiment as vader

# The reproduced methods keep stock's own lines, so they read against upstream line for line;
# the only lint findings in this file are that verbatim code's formatting idioms.
# ruff: noqa: UP030, UP032, SIM102

_log = logging.getLogger(__name__)

#: The release whose ``vaderSentiment.py`` this module reproduces, and that file's
#: sha256 as both its wheel and its sdist ship it (the wheel's RECORD agrees).
VADER_RELEASE = "3.3.2"
VADER_SOURCE_SHA256 = "25cd814d23000b41c0e242d99960832c6620b3f1b844469173404500ce63206b"


class _Tokens(list):
    """A document's tokens, carrying their lowercased copy -- made once, then read by
    every per-word check instead of being rebuilt inside each of them."""

    __slots__ = ("lowered",)

    def __init__(self, tokens: list[str]) -> None:
        super().__init__(tokens)
        self.lowered = [str(w).lower() for w in tokens]


def _lowered(words_and_emoticons: list[str]) -> list[str]:
    # Stock's own expression, read from the per-document copy when there is one.
    if isinstance(words_and_emoticons, _Tokens):
        return words_and_emoticons.lowered
    return [str(w).lower() for w in words_and_emoticons]


# _special_idioms_check and _negation_check below are adapted from vaderSentiment 3.3.2, and
# _but_check reimplements the same rule, under this notice (the distribution's LICENSE.txt):
#
#   The MIT License (MIT)
#
#   Copyright (c) 2016 C.J. Hutto
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy
#   of this software and associated documentation files (the "Software"), to deal
#   in the Software without restriction, including without limitation the rights
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#   copies of the Software, and to permit persons to whom the Software is
#   furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in all
#   copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#   SOFTWARE.
class LinearSentimentIntensityAnalyzer(vader.SentimentIntensityAnalyzer):
    """``SentimentIntensityAnalyzer`` with its three quadratic helpers made linear (the
    "but" check O(n log n)). Everything else -- the lexicon load, ``polarity_scores``,
    ``score_valence`` -- is inherited unchanged, and the object keeps no per-call state,
    so one instance is safe to share between threads, as the stock one is."""

    def sentiment_valence(
        self, valence: Any, sentitext: Any, item: str, i: int, sentiments: list[Any]
    ) -> list[Any]:
        # Stock hands sentitext.words_and_emoticons to both per-word checks. Make it the
        # list that carries its lowercased copy: the same tokens in the same order, and
        # nothing reads it but to index it.
        if not isinstance(sentitext.words_and_emoticons, _Tokens):
            sentitext.words_and_emoticons = _Tokens(sentitext.words_and_emoticons)
        return super().sentiment_valence(valence, sentitext, item, i, sentiments)

    @staticmethod
    def _but_check(words_and_emoticons: list[str], sentiments: list[Any]) -> list[Any]:
        """Stock's contrastive-"but" rule, found by a heap instead of a scan.

        Stock reads as "halve every score before the first 'but', boost every score
        after it". What its loop DOES: for each position k in turn it takes the score
        ``v`` now at k, finds with ``list.index`` the FIRST position j whose score
        currently equals ``v`` (j <= k, since k itself holds ``v``), and rescales
        position j -- not k -- to ``v * 0.5`` before the "but", ``v * 1.5`` after it,
        leaving it alone at it. So equal scores are matched by value: ``[1.5, 0, 0.75]``
        around a "but" becomes ``[0.375, 0, 0.75]`` (the first score halved twice, the
        last never boosted), not ``[0.75, 0, 1.125]``. That is what every stored score was
        computed with, so it is reproduced, not corrected; correcting it would be a
        different sentiment measure, which is not this module's call to make.

        The new score is ``v`` times the factor, never ``sentiments[j]`` times it. The two
        are only EQUAL, and at zero that shows: the result takes ``v``'s sign and is a
        float, whichever of ``0``, ``0.0`` and ``-0.0`` sat at j -- exactly as in stock.
        Every score is finite, so ``==`` is an equivalence here, and a dict groups exactly
        the values ``list.index`` treats as one.
        """
        words_and_emoticons_lower = [str(w).lower() for w in words_and_emoticons]
        if "but" in words_and_emoticons_lower:
            bi = words_and_emoticons_lower.index("but")
            # For each distinct score, a min-heap of the positions currently holding it:
            # its top is what list.index would return. Built in position order, so each
            # list is already a heap; kept exact as positions change score.
            holding: dict[Any, list[int]] = {}
            for pos, score in enumerate(sentiments):
                holding.setdefault(score, []).append(pos)
            for k in range(len(sentiments)):
                sentiment = sentiments[k]
                positions = holding[sentiment]
                si = positions[0]
                if si < bi:
                    new = sentiment * 0.5
                elif si > bi:
                    new = sentiment * 1.5
                else:
                    continue
                heapq.heappop(positions)
                sentiments[si] = new
                heapq.heappush(holding.setdefault(new, []), si)
        return sentiments

    @staticmethod
    def _special_idioms_check(valence: Any, words_and_emoticons: list[str], i: int) -> Any:
        # Stock, line for line, except that the lowercased tokens are read, not rebuilt.
        words_and_emoticons_lower = _lowered(words_and_emoticons)
        onezero = "{0} {1}".format(words_and_emoticons_lower[i - 1], words_and_emoticons_lower[i])

        twoonezero = "{0} {1} {2}".format(words_and_emoticons_lower[i - 2],
                                          words_and_emoticons_lower[i - 1], words_and_emoticons_lower[i])

        twoone = "{0} {1}".format(words_and_emoticons_lower[i - 2], words_and_emoticons_lower[i - 1])

        threetwoone = "{0} {1} {2}".format(words_and_emoticons_lower[i - 3],
                                           words_and_emoticons_lower[i - 2], words_and_emoticons_lower[i - 1])

        threetwo = "{0} {1}".format(words_and_emoticons_lower[i - 3], words_and_emoticons_lower[i - 2])

        sequences = [onezero, twoonezero, twoone, threetwoone, threetwo]

        for seq in sequences:
            if seq in vader.SPECIAL_CASES:
                valence = vader.SPECIAL_CASES[seq]
                break

        if len(words_and_emoticons_lower) - 1 > i:
            zeroone = "{0} {1}".format(words_and_emoticons_lower[i], words_and_emoticons_lower[i + 1])
            if zeroone in vader.SPECIAL_CASES:
                valence = vader.SPECIAL_CASES[zeroone]
        if len(words_and_emoticons_lower) - 1 > i + 1:
            zeroonetwo = "{0} {1} {2}".format(words_and_emoticons_lower[i], words_and_emoticons_lower[i + 1],
                                              words_and_emoticons_lower[i + 2])
            if zeroonetwo in vader.SPECIAL_CASES:
                valence = vader.SPECIAL_CASES[zeroonetwo]

        # check for booster/dampener bi-grams such as 'sort of' or 'kind of'
        n_grams = [threetwoone, threetwo, twoone]
        for n_gram in n_grams:
            if n_gram in vader.BOOSTER_DICT:
                valence = valence + vader.BOOSTER_DICT[n_gram]
        return valence

    @staticmethod
    def _negation_check(valence: Any, words_and_emoticons: list[str], start_i: int, i: int) -> Any:
        # Stock, line for line, except that the lowercased tokens are read, not rebuilt.
        words_and_emoticons_lower = _lowered(words_and_emoticons)
        if start_i == 0:
            if vader.negated([words_and_emoticons_lower[i - (start_i + 1)]]):  # 1 word preceding lexicon word (w/o stopwords)
                valence = valence * vader.N_SCALAR
        if start_i == 1:
            if words_and_emoticons_lower[i - 2] == "never" and \
                    (words_and_emoticons_lower[i - 1] == "so" or
                     words_and_emoticons_lower[i - 1] == "this"):
                valence = valence * 1.25
            elif words_and_emoticons_lower[i - 2] == "without" and \
                    words_and_emoticons_lower[i - 1] == "doubt":
                valence = valence
            elif vader.negated([words_and_emoticons_lower[i - (start_i + 1)]]):  # 2 words preceding the lexicon word position
                valence = valence * vader.N_SCALAR
        if start_i == 2:
            if words_and_emoticons_lower[i - 3] == "never" and \
                    (words_and_emoticons_lower[i - 2] == "so" or words_and_emoticons_lower[i - 2] == "this") or \
                    (words_and_emoticons_lower[i - 1] == "so" or words_and_emoticons_lower[i - 1] == "this"):
                valence = valence * 1.25
            elif words_and_emoticons_lower[i - 3] == "without" and \
                    (words_and_emoticons_lower[i - 2] == "doubt" or words_and_emoticons_lower[i - 1] == "doubt"):
                valence = valence
            elif vader.negated([words_and_emoticons_lower[i - (start_i + 1)]]):  # 3 words preceding the lexicon word position
                valence = valence * vader.N_SCALAR
        return valence


def installed_source_sha256() -> str | None:
    """The sha256 of the ``vaderSentiment.py`` this process imported, or None when it
    cannot be read (a sourceless install, say) -- which never matches, so it runs stock."""
    try:
        return hashlib.sha256(Path(vader.__file__).read_bytes()).hexdigest()
    except (OSError, TypeError):
        return None


def make_analyzer() -> Any:
    """The linear analyzer when the imported VADER is the file it reproduces; the stock
    analyzer otherwise. Both return the same scores; only the time differs."""
    if installed_source_sha256() == VADER_SOURCE_SHA256:
        return LinearSentimentIntensityAnalyzer()
    _log.info(
        "vaderSentiment is not the %s release src/analytics/vader_linear.py reproduces; "
        "scoring with the stock analyzer (the same scores, in time quadratic in the length "
        "of a text)",
        VADER_RELEASE,
    )
    return vader.SentimentIntensityAnalyzer()
