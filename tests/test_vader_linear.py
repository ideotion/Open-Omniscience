"""The linear-time VADER returns stock VADER's scores, bit for bit, and is linear.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/analytics/vader_linear.py`` overrides three methods of a third-party analyzer, so
its whole claim is EQUALITY: the same per-token scores (type and sign of zero included,
since stock turns some int 0 into float 0.0) and the same result dict, on every text.
The differential tests below compare it with the stock class of the INSTALLED release
over hand-written cases aimed at every rule it touches, seeded random token soups, and
real English prose cut to several sizes. The complexity pins COUNT operations rather
than timing them, and each is shown to fire on stock, so it has teeth.
"""

from __future__ import annotations

import random
import re
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("vaderSentiment")

import vaderSentiment.vaderSentiment as vader  # noqa: E402
import yaml  # noqa: E402

from src.analytics import vader_linear as vl  # noqa: E402

_REPO = Path(__file__).resolve().parents[1]
Stock = vader.SentimentIntensityAnalyzer
Linear = vl.LinearSentimentIntensityAnalyzer


class _Traced:
    """Mixin recording the per-token scores ``polarity_scores`` hands ``score_valence``:
    the full-precision values, before the result dict rounds them."""

    seen: list[tuple[str, str]] = []

    def score_valence(self, sentiments, text):
        self.seen = [(type(s).__name__, repr(s)) for s in sentiments]
        return super().score_valence(sentiments, text)


class _TracedStock(_Traced, Stock):
    pass


class _TracedLinear(_Traced, Linear):
    pass


@pytest.fixture(scope="module")
def pair():
    return _TracedStock(), _TracedLinear()


def _same(pair, text: str) -> None:
    stock, linear = pair
    want = stock.polarity_scores(text)
    got = linear.polarity_scores(text)
    assert linear.seen == stock.seen, f"per-token scores differ on {text[:120]!r}"
    assert repr(got) == repr(want), f"result differs on {text[:120]!r}: {got} != {want}"


# --- equality ------------------------------------------------------------------- #

# Every rule the reproduction touches, and the quirks it must keep: the first "but"
# only; "but" first, last, alone, twice, in capitals; equal scores on both sides of it
# (matched by VALUE in stock); zeros as int and float; "no" negating its neighbour;
# "kind of"; the idioms and booster bigrams; "least"/"at least"/"very least";
# "never so"/"never this"/"without doubt"; ALL CAPS against mixed case; emoticons and
# emoji; "!!!" and "???"; and texts of one to four tokens, at the edge of every
# check's reach.
_CASES = [
    "",
    "good",
    "but",
    "not good",
    "good but",
    "but good",
    "no good",
    "BUT GOOD",
    "good BUT bad",
    "It was good, but it was bad.",
    "good good but good good",
    "great but good but bad but terrible",
    "The plot was good, but the characters are uncompelling and the dialog is not great.",
    "fine fine fine but fine fine fine",
    "happy but happy but happy",
    "bad, worse but okay and good",
    "no no good at all",
    "no problem, no doubt, no way",
    "not bad at all",
    "Not bad at all",
    "The book was kind of good.",
    "The book was only kind of good.",
    "kind of",
    "it is sort of nice and kind of sad",
    "At least it isn't a horrible book.",
    "at least good",
    "the least good thing",
    "the very least good thing",
    "least good",
    "never so good",
    "never this happy",
    "he is never so happy without doubt the best",
    "without doubt good",
    "the shit hit the fan",
    "it's the bomb, yeah right, cut the mustard, hand to mouth",
    "back handed compliment with a bad ass kiss of death",
    "VADER is VERY SMART, handsome, and FUNNY!!!",
    "VADER is VERY SMART, uber handsome, and FRIGGIN FUNNY!!!",
    "VADER is not smart, handsome, nor funny.",
    "GOOD",
    "GOOD GREAT",
    "Today SUX!",
    "Today only kinda sux! But I'll get by, lol",
    "Make sure you :) or :D today!",
    "Catch utf-8 emoji such as 💘 and 💋 and 😁",
    "💘💋😁 but 😢",
    "Is this good??? Really??",
    "Is this good????",
    "wow!!!!! amazing!!",
    "good good good bad bad bad but good",
    "I don't think it's good but it isn't bad either",
    "never good, never bad, but never so terrible",
    "good\nbut\n\tbad",
    "   good    but   bad   ",
]


@pytest.mark.parametrize("text", _CASES)
def test_the_scores_equal_stock_on_every_rule_it_touches(pair, text):
    _same(pair, text)


def test_the_but_check_keeps_stocks_match_by_value():
    # The quirk the docstring names, pinned on stock itself so the claim cannot rot:
    # the score after the "but" is never boosted, the first one is halved twice.
    assert Stock._but_check(["good", "but", "ok"], [1.5, 0, 0.75]) == [0.375, 0, 0.75]
    assert Linear._but_check(["good", "but", "ok"], [1.5, 0, 0.75]) == [0.375, 0, 0.75]


_SCORES = [0, 0, 0.0, -0.0, 0.5, 0.75, 1.0, 1.5, 2.25, 3.375, -0.5, -0.75, -1.5, -2.25, 3, -2]


def test_the_but_check_equals_stock_on_random_lists():
    rnd = random.Random(20260927)
    for _ in range(20_000):
        n = rnd.randint(1, 40)
        words = [rnd.choice(["a", "b", "but", "BUT", "But", "x"]) for _ in range(n)]
        scores = [rnd.choice(_SCORES) for _ in range(n)]
        want = Stock._but_check(list(words), list(scores))
        got = Linear._but_check(list(words), list(scores))
        assert [(type(s), repr(s)) for s in got] == [(type(s), repr(s)) for s in want], (
            words, scores, got, want,
        )


def _vocabulary() -> list[str]:
    words = [
        "good", "bad", "great", "terrible", "happy", "sad", "love", "hate", "nice", "ok",
        "fine", "no", "not", "never", "without", "doubt", "so", "this", "least", "at", "very",
        "kind", "of", "sort", "but", "BUT", "But", "and", "or", "nor", "isn't", "don't",
        "the", "a", "it", "was", "is", "extremely", "barely", "hardly", "uber", "friggin",
        "GOOD", "BAD", "VERY", "NOT", ":)", ":(", ":D", "lol", "sux", "kinda", "!", "!!",
        "???", "?", "💘", "😁", "😢", "yeah", "right", "bomb", "hit", "fan", "shit",
    ]
    for idiom in list(vader.SPECIAL_CASES) + list(vader.BOOSTER_DICT):
        words.extend(idiom.split())
    return words


def test_the_scores_equal_stock_on_random_token_soups(pair):
    rnd = random.Random(1)
    vocab = _vocabulary()
    for _ in range(2_000):
        n = rnd.choice([1, 2, 3, 4, 5, rnd.randint(6, 80)])
        _same(pair, " ".join(rnd.choice(vocab) for _ in range(n)))


def _english_prose() -> str:
    parts = [
        (_REPO / "docs" / "USER_MANUAL.md").read_text(encoding="utf-8"),
        (_REPO / "docs" / "ETHICS.md").read_text(encoding="utf-8"),
    ]
    return re.sub(r"`[^`]*`", " ", "\n".join(parts))


@pytest.mark.parametrize("size", [300, 2_000, 8_000, 20_000])
def test_the_scores_equal_stock_on_english_prose(pair, size):
    prose = _english_prose()
    assert len(prose) > 4 * size, "the prose fixture is too short to cut"
    rnd = random.Random(size)
    for _ in range(3):
        start = rnd.randrange(0, len(prose) - size)
        _same(pair, prose[start : start + size])


# --- linear, by count ------------------------------------------------------------- #


class _Passes:
    """Full passes over a document's tokens, in either list the analyzer holds them in."""

    n = 0


class _CountedList(list):
    def __iter__(self):
        _Passes.n += 1
        return super().__iter__()


class _CountedTokens(vl._Tokens):
    def __iter__(self):
        _Passes.n += 1
        return super().__iter__()


def _passes_over_the_tokens(analyzer_cls, text: str, monkeypatch) -> int:
    # The tokenizer hands back a counting list, and the copy the linear analyzer makes
    # of it counts too -- so a check that re-reads either one, per word, shows up.
    original = vader.SentiText._words_and_emoticons
    monkeypatch.setattr(
        vader.SentiText, "_words_and_emoticons", lambda self: _CountedList(original(self))
    )
    monkeypatch.setattr(vl, "_Tokens", _CountedTokens)
    analyzer = analyzer_cls()
    _Passes.n = 0
    analyzer.polarity_scores(text)
    monkeypatch.undo()
    return _Passes.n


def test_a_text_is_read_a_fixed_number_of_times_whatever_its_length(monkeypatch):
    short = "good but not so bad, never so great, kind of nice. " * 5
    long = short * 20
    passes = {_passes_over_the_tokens(Linear, t, monkeypatch) for t in (short, long)}
    assert len(passes) == 1 and max(passes) <= 6, passes
    # Teeth: stock re-reads the whole text for every lexicon word, so its count grows
    # with the text -- about twentyfold here.
    stock_short = _passes_over_the_tokens(Stock, short, monkeypatch)
    stock_long = _passes_over_the_tokens(Stock, long, monkeypatch)
    assert stock_long > 10 * stock_short, (stock_short, stock_long)


class _CountedScores(list):
    """A score list that counts the scans stock's "but" check makes."""

    def __init__(self, scores):
        super().__init__(scores)
        self.scans = 0

    def index(self, *a):
        self.scans += 1
        return super().index(*a)

    def pop(self, *a):
        self.scans += 1
        return super().pop(*a)

    def insert(self, *a):
        self.scans += 1
        return super().insert(*a)


def test_the_but_check_makes_no_scan_per_token():
    words = ["good"] * 500 + ["but"] + ["bad"] * 500
    scores = [1.9] * 500 + [0] + [-2.5] * 500
    linear = _CountedScores(scores)
    Linear._but_check(words, linear)
    assert linear.scans == 0
    stock = _CountedScores(scores)
    Stock._but_check(words, stock)
    assert stock.scans >= 2 * 1000  # teeth: index + pop + insert, per token
    assert list(linear) == list(stock)


def test_one_analyzer_keeps_no_state_between_texts():
    """It is shared: ingest's cached instance serves every thread of a drain."""
    analyzer = Linear()
    before = dict(vars(analyzer))
    analyzer.polarity_scores("good but bad, not so great :) " * 10)
    assert vars(analyzer).keys() == before.keys()
    assert all(vars(analyzer)[k] is before[k] for k in before)


# --- the guard ---------------------------------------------------------------------- #


def test_the_installed_vader_is_the_file_the_reproduction_was_checked_against():
    """requirements.lock pins the release; this pins its bytes. A bump must redo the
    reproduction (configs/external_artifacts.yml, vader-linear-reproduction)."""
    assert vl.installed_source_sha256() == vl.VADER_SOURCE_SHA256
    assert type(vl.make_analyzer()) is Linear


def test_any_other_vader_scores_with_the_stock_analyzer(monkeypatch, caplog):
    monkeypatch.setattr(vl, "VADER_SOURCE_SHA256", "0" * 64)
    with caplog.at_level("INFO", logger=vl.__name__):
        analyzer = vl.make_analyzer()
    assert type(analyzer) is Stock
    assert "stock analyzer" in caplog.text


def test_an_unreadable_vader_source_never_matches(monkeypatch):
    monkeypatch.setattr(vl.vader, "__file__", str(_REPO / "no" / "such" / "vaderSentiment.py"))
    assert vl.installed_source_sha256() is None
    assert type(vl.make_analyzer()) is Stock


def test_ingest_and_framing_score_with_the_linear_analyzer():
    from src.analytics import sentiment
    from src.awareness import framing

    assert type(sentiment._analyzer()) is Linear
    assert type(framing._analyzer) is Linear


def test_the_release_is_the_same_everywhere_it_is_named():
    registry = yaml.safe_load((_REPO / "configs" / "external_artifacts.yml").read_text())
    entry = next(a for a in registry["artifacts"] if a["id"] == "vader-linear-reproduction")
    assert entry["pin"]["verified"] == vl.VADER_RELEASE
    lock = (_REPO / "requirements.lock").read_text()
    assert f"vadersentiment=={vl.VADER_RELEASE} " in lock
    extras = tomllib.loads((_REPO / "pyproject.toml").read_text())["project"][
        "optional-dependencies"
    ]["analysis"]
    assert f"vaderSentiment>={entry['pin']['floor']}" in extras
