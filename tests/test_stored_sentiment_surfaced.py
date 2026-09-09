"""The tone scored at ingest is now SHOWN, not just stored.

The SENTIMENT AT INGEST entry's REMAINING half asked to "SURFACE the stored sentiment in
the reader/cards/lists". Two thirds of that had quietly landed since (the reader and the
analysis Articles list both read the stored columns today), and the docket's literal
wording -- that the UI "still reads on-demand framing" -- had gone stale. What had NOT
landed is the part the entry names first: the feed CARDS, and the Search tab's LIST. The
columns were populated on every re-index and nothing on either surface read them.

WHAT MUST NOT DRIFT, because this is a signal that is easy to over-state:
  * the caveat travels WITH the value -- VADER is an English lexicon, so a score over
    non-English coverage is unreliable, and every chip carries that in its hover;
  * an unscored article draws NOTHING. A core install has no VADER and non-English
    returns None by design, so a default-to-neutral would invent a measurement for
    exactly the articles the pipeline honestly declined to score;
  * there is ONE implementation of how a tone is drawn.
"""

from __future__ import annotations

from tests.js_source_helper import app_js, assert_absent, assert_present, function_source


def test_the_feed_card_payload_carries_the_stored_tone():
    import inspect

    from src.api import feed

    card = inspect.getsource(feed._card)
    assert '"sentiment_score": a.sentiment_score' in card
    assert '"sentiment_label": a.sentiment_label' in card
    assert "score_article" not in card, "the card must READ the stored column, never rescore"


def test_the_feed_card_draws_the_tone_without_repeating_the_language():
    js = app_js()
    card = function_source(js, "_feedCard")
    assert_present(card, "_toneChip(a)", why="the stored tone belongs on the card")
    assert_absent(card, "_anToneChip(", why=(
        "the card already prints the language two segments earlier; the deduced-language "
        "half of _anToneChip would repeat it"
    ))


def test_the_search_list_draws_the_tone_like_the_analysis_list_already_does():
    search = function_source(app_js(), "doSearch")
    assert_present(search, "_anToneChip(a)", why=(
        "the search row shows a.language only, so the deduced-language note is "
        "informative here -- the same call the analysis Articles list already makes"
    ))


def test_there_is_exactly_one_implementation_of_the_tone_chip():
    """A second copy is how two surfaces come to caption the same number differently."""
    js = app_js()
    assert js.count("function _toneChip(") == 1
    an = function_source(js, "_anToneChip")
    assert_present(an, "_toneChip(a)", why="the split must REUSE, not fork")
    assert "var(--ok)" not in an, "the colour rule lives in _toneChip alone"


def test_an_unscored_article_draws_nothing_at_all():
    """Not a zero, not 'neutral': the pipeline declines to score non-English and a core
    install has no VADER, so a default would invent a measurement precisely where the
    honest answer is that none was taken."""
    chip = function_source(app_js(), "_toneChip")
    assert_present(chip, 'if (!a || !a.sentiment_label) return ""')
    assert_absent(chip, '"neutral"', why="no fabricated default label")
    assert_absent(chip, "|| 0", why="a missing score must not become 0.00")


def test_every_surface_that_shows_a_tone_carries_the_english_only_caveat():
    chip = function_source(app_js(), "_toneChip")
    assert_present(chip, "Tone (VADER, English-only) — a signal, not a verdict.")
    assert_present(chip, "title=", why="the caveat rides the value as a hover (#17)")


def test_the_caveat_string_is_already_translated_everywhere():
    """This slice adds no new strings on purpose -- it reuses the shipped chip, whose
    caveat is keyed in all twelve locales. Pinned so a later reword cannot silently
    ship an English-only caveat about an English-only method."""
    import json
    import pathlib

    key = "Tone (VADER, English-only) — a signal, not a verdict."
    missing = [
        p.stem
        for p in sorted(pathlib.Path("src/static/locales").glob("*.json"))
        if key not in json.loads(p.read_text("utf-8"))
    ]
    assert not missing, f"the tone caveat is unkeyed in: {missing}"
