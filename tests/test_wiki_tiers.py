"""Q707's tiers and the lane's storage budget: what is decided, and what is refused.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mostly NEGATIVE SPACE. A tier classifier is easy to write so that it says "hot" to
everything, and a budget is easy to write so that it never stops anything; both would
pass a test that only checked the happy answer. What is checked here is the refusals:
a bare string is not a title list, an unknown tier is not a default, an unmeasured
budget is not an exhausted one, and a page that MOVED is not a different page.
"""

from __future__ import annotations

import pytest

from src.wiki import tiers
from src.wiki.tiers import (
    BUDGET_GB_MAX,
    BUDGET_GB_MIN,
    DEFAULT_TOTAL_BUDGET_GB,
    HOT_REASONS,
    TIERS,
    HotSet,
    UnknownTierError,
    budget_state,
    normalize_title,
    require_budget_gb,
    require_tier,
)


# --------------------------------------------------------------------------- #
# The vocabularies are CLOSED.
# --------------------------------------------------------------------------- #
def test_the_tier_vocabulary_is_exactly_Q707s_three_in_its_order():
    assert TIERS == ("hot", "warm", "cold")


def test_an_unknown_tier_is_REFUSED_and_never_defaulted():
    assert require_tier("hot") == "hot"
    with pytest.raises(UnknownTierError) as exc:
        require_tier("lukewarm")
    assert "lukewarm" in str(exc.value), "the refusal names the value"
    assert "hot" in str(exc.value), "and what it should have been"


def test_the_hot_reasons_put_the_operators_OWN_choice_first():
    """Q716's pin before Q707's three rules. When both apply, the operator's wins."""
    assert HOT_REASONS[0] == "pinned"
    assert set(HOT_REASONS) == {"pinned", "tracked", "corpus_mention", "pageview_top"}


def test_warm_and_cold_carry_a_reason_that_is_NOT_the_budget():
    """The whole point of the third counter: a tier not built yet is not a full disk."""
    for decision in (tiers.warm(), tiers.cold()):
        assert decision.ingests_text is False
        assert decision.deferred_reason == tiers.DEFERRED_UNTIL_WARM_TIER
        assert "budget" not in (decision.deferred_reason or "")
    from src.wiki.runner import BUDGET_FULL

    assert tiers.DEFERRED_UNTIL_WARM_TIER != BUDGET_FULL


def test_warm_and_cold_name_NO_reason_for_being_what_they_are():
    """A page is WARM by not being HOT. "reason: not_hot" would dress an absence up."""
    assert tiers.warm().reason is None
    assert tiers.cold().reason is None


# --------------------------------------------------------------------------- #
# Title normalisation.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("fixture_alpha", "Fixture alpha"),
        ("  Fixture   Alpha  ", "Fixture Alpha"),
        ("Fixture_Alpha", "Fixture Alpha"),
        ("éclair", "Éclair"),
        ("", ""),
        ("   ", ""),
        ("_", ""),
    ],
)
def test_titles_normalise_to_the_editions_own_form(raw, want):
    assert normalize_title(raw) == want


def test_normalisation_does_NOT_touch_anything_past_the_first_character():
    """A lower-cased rest would merge "NASA" and "Nasa", which are different pages."""
    assert normalize_title("NASA budget") == "NASA budget"
    assert normalize_title("iPhone") == "IPhone"  # MediaWiki's own behaviour, not ours


# --------------------------------------------------------------------------- #
# HotSet.
# --------------------------------------------------------------------------- #
def test_a_bare_string_of_titles_is_REFUSED_rather_than_iterated():
    """"Rome" would iterate into five one-letter titles matching nothing, and the
    page would fall silently to WARM. The same trap the edition list refuses."""
    hot = HotSet("en", corpus_mention_titles={"Rome"})
    with pytest.raises(TypeError) as exc:
        hot.decide(titles="Rome")
    assert "SEQUENCE" in str(exc.value)


def test_each_of_the_four_reasons_reaches_HOT_under_its_own_name():
    assert HotSet("en", pinned_ids={7}).decide(titles=["X"], page_id=7).reason == "pinned"
    assert HotSet("en", tracked_titles={"X"}).decide(titles=["X"]).reason == "tracked"
    assert (
        HotSet("en", corpus_mention_titles={"X"}).decide(titles=["X"]).reason == "corpus_mention"
    )
    assert (
        HotSet("en", pageview_top_titles={"X"}).decide(titles=["X"]).reason == "pageview_top"
    )


def test_when_several_reasons_apply_the_OPERATORS_own_is_the_one_reported():
    hot = HotSet(
        "en",
        pinned_ids={7},
        tracked_titles={"X"},
        corpus_mention_titles={"X"},
        pageview_top_titles={"X"},
    )
    assert hot.decide(titles=["X"], page_id=7).reason == "pinned"
    # Without the pin, the next-strongest is the operator's hand-tracked list.
    assert hot.decide(titles=["X"], page_id=8).reason == "tracked"


def test_a_page_nothing_matches_is_WARM_and_its_text_is_NOT_fetched():
    decision = HotSet("en", corpus_mention_titles={"X"}).decide(titles=["Y"])
    assert decision.tier == "warm"
    assert decision.ingests_text is False


def test_a_page_RENAMED_mid_batch_is_still_the_page_the_corpus_mentions():
    """The measured defect: deciding on the newest name alone dropped page 101."""
    hot = HotSet("en", corpus_mention_titles={"Fixture Alpha"})
    both = ["Fixture Alpha", "Fixture Alpha (renamed)"]
    assert hot.decide(titles=both, page_id=101).tier == "hot"
    # And the mutation that reintroduces the defect: the newest name only.
    assert hot.decide(titles=[both[-1]], page_id=101).tier == "warm"


def test_a_followed_page_stays_HOT_by_ID_when_every_title_stopped_matching():
    """A move BETWEEN batches: no name matches any more, but we already follow it."""
    hot = HotSet("en", corpus_mention_titles={"Old"}, hot_page_ids={55})
    assert hot.decide(titles=["Totally New"], page_id=55).tier == "hot"
    assert hot.decide(titles=["Totally New"], page_id=56).tier == "warm"


def test_the_set_reports_each_SOURCES_own_count_and_never_a_blend():
    hot = HotSet(
        "en",
        pinned_ids={1, 2},
        tracked_titles={"A"},
        corpus_mention_titles={"A", "B", "C"},
        pageview_top_titles={"D"},
        hot_page_ids={1, 2, 3},
    )
    assert hot.sizes() == {
        "pinned": 2,
        "tracked": 1,
        "corpus_mention": 3,
        "pageview_top": 1,
        "known_page_ids": 3,
    }
    # len() is DISTINCT titles -- "A" is in two sources and is counted once.
    assert len(hot) == 4


def test_titles_are_normalised_on_the_way_IN_as_well_as_on_the_way_out():
    hot = HotSet("en", corpus_mention_titles={"fixture_alpha"})
    assert hot.decide(titles=["Fixture alpha"]).tier == "hot"


# --------------------------------------------------------------------------- #
# The budget.
# --------------------------------------------------------------------------- #
def test_the_published_default_is_Q707s_twenty_GB():
    assert DEFAULT_TOTAL_BUDGET_GB == 20


def test_a_budget_outside_the_bounds_is_REFUSED_and_never_clamped():
    """A clamp turns a slipped keystroke into a silently tiny lane."""
    assert require_budget_gb(BUDGET_GB_MIN) == BUDGET_GB_MIN
    assert require_budget_gb(BUDGET_GB_MAX) == BUDGET_GB_MAX
    for bad in (0, -1, BUDGET_GB_MAX + 1):
        with pytest.raises(ValueError):
            require_budget_gb(bad)
    for bad in ("twenty", None, [20]):
        with pytest.raises(ValueError):
            require_budget_gb(bad)


def test_an_UNMEASURED_budget_is_not_an_exhausted_one():
    """A lane that has never run holds no bytes. Refusing to ingest because nothing
    has been measured would stop the lane on its first pass, forever."""
    state = budget_state(total_gb=20, disk_bytes=None, editions=12)
    assert state.measured is False
    assert state.exhausted is False
    assert state.remaining_bytes is None, "None, never 0 -- a different fact"


def test_an_OVER_budget_lane_reports_zero_remaining_and_never_a_negative():
    state = budget_state(total_gb=1, disk_bytes=5 * 1024**3, editions=1)
    assert state.exhausted is True
    assert state.remaining_bytes == 0, "a negative remainder reads as a countdown"


def test_the_per_edition_share_falls_as_editions_are_added_and_the_division_is_visible():
    one = budget_state(total_gb=12, disk_bytes=0, editions=1)
    twelve = budget_state(total_gb=12, disk_bytes=0, editions=12)
    assert twelve.per_edition_bytes == one.per_edition_bytes // 12
    assert twelve.as_dict()["editions"] == 12, "the divisor travels with the number"


def test_a_budget_with_no_editions_is_REFUSED_rather_than_divided_by_zero():
    with pytest.raises(ValueError):
        budget_state(total_gb=20, disk_bytes=0, editions=0)


def test_the_budgets_METHOD_travels_with_its_numbers_and_names_the_governor():
    method = budget_state(total_gb=20, disk_bytes=1, editions=12).as_dict()["method"]
    assert "governor" in method, "Q1012: one rate authority, never a second beside it"
    assert "-wal" in method, "the spend figure says which bytes it counted"


# --------------------------------------------------------------------------- #
# The duplicated constants are PINNED to their sources, never trusted.
# --------------------------------------------------------------------------- #
def test_the_settings_edition_default_equals_the_apps_twelve_UI_locales():
    from src.scheduler.settings import WIKI_LANE_DEFAULT_EDITIONS
    from src.wiki.languages import UI_LOCALE_CODES

    assert set(WIKI_LANE_DEFAULT_EDITIONS) == set(UI_LOCALE_CODES)
    assert len(WIKI_LANE_DEFAULT_EDITIONS) == 12, "Q725 = a's 'default: all twelve'"
    assert len(set(WIKI_LANE_DEFAULT_EDITIONS)) == 12, "no duplicates"


def test_the_settings_budget_constants_equal_the_tier_modules():
    from src.scheduler.settings import (
        WIKI_LANE_BUDGET_GB_MAX,
        WIKI_LANE_BUDGET_GB_MIN,
        WIKI_LANE_DEFAULT_BUDGET_GB,
    )

    assert WIKI_LANE_DEFAULT_BUDGET_GB == DEFAULT_TOTAL_BUDGET_GB
    assert (WIKI_LANE_BUDGET_GB_MIN, WIKI_LANE_BUDGET_GB_MAX) == (BUDGET_GB_MIN, BUDGET_GB_MAX)


def test_settings_still_has_NO_src_imports_at_module_level():
    """The reason the constants above are duplicated at all. If this ever stops being
    true, delete the duplicates rather than keeping both."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("src/scheduler/settings.py").read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names: list[str] = []
    for node in top_level:
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
    assert not [n for n in names if n.startswith("src.")], (
        f"settings.py grew a module-level src import: {names}"
    )
