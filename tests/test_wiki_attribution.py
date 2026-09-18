"""Q726's licence obligation: CC BY-SA 4.0, named, with a link to the page history.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The history link IS the attribution: a wiki article has no byline, and CC BY-SA asks
for credit to the authors — who are the page's editors. So the tests that matter are
the ones about being WRONG rather than the ones about being present: an attribution
that credits the wrong project is a false statement about someone else's work, made
in a place a reader will believe, and it is worse than no attribution at all.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from src.wiki.attribution import (
    ALSO_AVAILABLE_UNDER,
    LICENCE_NAME,
    LICENCE_URL,
    attribution,
    history_url,
    page_url,
    revision_url,
)


def test_the_licence_is_named_WITH_ITS_VERSION():
    """"CC BY-SA" without a version is ambiguous across four incompatible releases."""
    assert LICENCE_NAME == "CC BY-SA 4.0"
    assert "4.0" in LICENCE_URL
    assert ALSO_AVAILABLE_UNDER == "GFDL", "named so a re-user knows the other path exists"


def test_the_history_url_points_at_the_AUTHORS_not_at_the_article():
    url = history_url("en", "Climate change")
    assert url == "https://en.wikipedia.org/w/index.php?title=Climate_change&action=history"
    assert url != page_url("en", "Climate change"), (
        "the article and its authors are two different links and two different obligations"
    )


def test_a_title_with_spaces_becomes_the_wikis_own_spelling():
    assert page_url("fr", "Changement  climatique") == "https://fr.wikipedia.org/wiki/Changement_climatique"


@pytest.mark.parametrize("wiki", ["", "  ", "en wiki", "en/../de", "en.wikipedia.org"])
def test_an_UNSAFE_or_unknown_edition_yields_NOTHING_rather_than_a_guess(wiki):
    assert page_url(wiki, "X") is None
    assert history_url(wiki, "X") is None
    assert attribution(wiki, "X") is None


@pytest.mark.parametrize("title", ["", "   ", "\n\t "])
def test_an_EMPTY_title_yields_nothing_rather_than_the_projects_main_page(title):
    """A history URL with no title is the wiki's main page. Silently crediting that
    instead of the article is exactly the wrong-attribution failure."""
    assert history_url("en", title) is None
    assert attribution("en", title) is None


def test_a_non_numeric_revision_produces_NO_revision_link_rather_than_a_broken_one():
    assert revision_url("en", "12345") == "https://en.wikipedia.org/w/index.php?oldid=12345"
    for bad in (None, "", "abc", "12a", "-1 OR 1=1"):
        assert revision_url("en", bad) is None


def test_the_claim_is_narrowed_to_TEXT_because_images_carry_their_own_licences():
    block = attribution("en", "Rome", revision="9")
    assert block is not None
    assert block["covers"] == "text"


def test_the_block_carries_URLS_AND_TOKENS_and_not_one_sentence():
    """A licence notice rendered in English to an Arabic-reading operator is a notice
    they were not given. The words are composed by the caller and ship ×12."""
    block = attribution("de", "Rom")
    assert block is not None
    for key, value in block.items():
        if key.endswith("_url") or key in {"licence", "wiki", "title", "covers", "also_under"}:
            continue
        raise AssertionError(f"unexpected prose-shaped field {key}={value!r}")


# --------------------------------------------------------------------------- #
# The reader renders it, visibly, and its links are confirmed.
# --------------------------------------------------------------------------- #
def _reader_source() -> str:
    return pathlib.Path("src/api/main.py").read_text(encoding="utf-8")


def test_the_reader_builds_the_block_OUTSIDE_the_revision_branch():
    """An article ingested from a DUMP carries no ``source_revision`` and is still
    Wikipedia text under the same licence. Computing the page ref inside the version
    branch would have silently withheld the attribution from every one of them."""
    src = _reader_source()
    ref_at = src.index("_ref = wiki_page_ref(")
    version_at = src.index('    version_row = ""')
    assert ref_at < version_at, "the page ref is resolved before the version branch"


def test_the_licence_block_is_rendered_BEFORE_the_article_and_is_not_hidden():
    src = _reader_source()
    assert "{licence_block}" in src
    at = src.index("{licence_block}")
    after = src[at : at + 200]
    assert "<article>{paras}</article>" in after, "it sits directly above the text it covers"
    block = src[src.index('licence_block = (') : src.index('licence_block = (') + 1400]
    assert "hidden" not in block and "<details" not in block, (
        "a licence obligation must not be behind a disclosure widget"
    )


def test_both_links_go_through_the_readers_OWN_external_confirm():
    """Invariant #7. The reader's confirm fires on ``a.ext`` and nothing else."""
    src = _reader_source()
    block = src[src.index('licence_block = (') : src.index('licence_block = (') + 1400]
    anchors = re.findall(r"<a ([^>]*)href=", block)
    assert anchors, "the block has links at all"
    for attrs in anchors:
        assert 'class="ext"' in attrs, f"an unconfirmed outbound link: {attrs!r}"


def test_the_reader_names_the_images_limit_in_the_same_breath():
    src = _reader_source()
    block = src[src.index('licence_block = (') : src.index('licence_block = (') + 1400]
    assert "covers the TEXT" in block
    assert "own separate licences" in block
