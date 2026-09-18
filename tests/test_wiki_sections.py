"""Q711's section-awareness: which part of a page changed, and where it stops knowing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A "which section changed" answer that is confidently wrong is worse than one that says
where its confidence ends, so most of what is tested here is the ends: a renamed
section, a repeated heading, a first version, a page with no headings at all, and a
page rewritten so completely that listing its sections is just the diff again.
"""

from __future__ import annotations

from src.wiki.sections import (
    LEAD,
    MAX_REPORTED,
    section_diff,
    split_sections,
)


def test_text_before_the_first_heading_is_the_LEAD_and_is_named():
    """The part a reader sees first and most edits touch. Calling it "no section"
    would hide the most common change there is."""
    out = split_sections("Intro text.\n\n== History ==\nBody.")
    assert [s.title for s in out] == [LEAD, "History"]
    assert out[0].is_lead and out[0].level == 0
    assert out[1].level == 2


def test_a_page_with_NO_headings_is_one_lead_section_not_an_empty_list():
    """An empty list would make "the page changed but no section did", which is never
    true of a page that has text."""
    out = split_sections("Just a paragraph.")
    assert len(out) == 1 and out[0].title == LEAD


def test_mismatched_equals_runs_are_still_read_as_one_heading():
    """Real wikitext carries them and MediaWiki renders them; refusing to read one
    would silently merge two sections into one."""
    out = split_sections("lead\n== Odd ===\nbody\n== Even ==\nmore")
    assert [s.title for s in out] == [LEAD, "Odd", "Even"]


def test_every_heading_level_is_read_and_reported():
    text = "\n".join(f"{'=' * n} H{n} {'=' * n}\nbody{n}" for n in range(1, 7))
    out = split_sections("lead\n" + text)
    assert [s.level for s in out] == [0, 1, 2, 3, 4, 5, 6]


# --------------------------------------------------------------------------- #
# The diff.
# --------------------------------------------------------------------------- #
def test_a_FIRST_version_reports_nothing_rather_than_every_section_added():
    """A first sighting is not an edit. Reporting one as a page rewritten from nothing
    would put a fabricated event in every timeline this feeds."""
    out = section_diff(None, "lead\n== A ==\nbody")
    assert out.changes == ()
    assert out.total_changed == 0
    assert "first version" in out.caveat


def test_a_changed_section_is_named_with_its_own_gained_and_lost_characters():
    before = "lead\n== A ==\nshort\n== B ==\nsame"
    after = "lead\n== A ==\nmuch longer body\n== B ==\nsame"
    out = section_diff(before, after)
    assert [(c.kind, c.title) for c in out.changes] == [("changed", "A")]
    assert out.changes[0].added_chars > 0 and out.changes[0].removed_chars == 0
    assert out.unchanged == 2, "the lead and B -- the denominator the count needs"


def test_a_RENAMED_section_reads_as_one_removed_and_one_added_and_says_so():
    """Matching by heading text cannot tell a rename from a swap. The caveat is the
    honest form of that limit, and it travels with the result."""
    out = section_diff("lead\n== Old ==\nbody", "lead\n== New ==\nbody")
    kinds = sorted((c.kind, c.title) for c in out.changes)
    assert kinds == [("added", "New"), ("removed", "Old")]
    assert "renamed section" in out.caveat


def test_a_REPEATED_heading_makes_the_answer_ambiguous_and_the_result_says_which():
    """Wikipedia pages carry repeated "References" headings under different parents.
    A plain dict keeps only the last; the FIRST wins here and the ambiguity is named."""
    text = "lead\n== References ==\none\n== Other ==\nx\n== References ==\ntwo"
    out = section_diff(text, text.replace("one", "ONE"))
    assert out.duplicate_titles == ("References",)
    assert "repeats a heading" in out.caveat
    assert [c.title for c in out.changes] == ["References"]


def test_a_page_with_no_headings_on_either_side_is_reported_FLAT():
    """"Which section changed" has no finer answer to give, and saying so is better
    than naming the lead as though it were a choice among sections."""
    out = section_diff("one paragraph", "another paragraph")
    assert out.flat is True
    assert [c.title for c in out.changes] == [LEAD]


def test_the_section_LIST_truncates_while_the_COUNT_stays_exact():
    """A page rewritten end to end changes every section, and a list of two hundred is
    the diff again, longer. The count is cheap and honest even when the list is not."""
    before = "\n".join(f"== S{i} ==\nbody{i}" for i in range(MAX_REPORTED + 10))
    after = "\n".join(f"== S{i} ==\nCHANGED{i}" for i in range(MAX_REPORTED + 10))
    out = section_diff(before, after)
    assert out.total_changed == MAX_REPORTED + 10
    assert len(out.changes) == MAX_REPORTED
    assert out.truncated is True
    assert str(MAX_REPORTED + 10) in out.caveat


def test_the_changes_read_down_the_page_as_it_NOW_stands():
    before = "lead\n== A ==\na\n== B ==\nb\n== C ==\nc"
    after = "lead\n== A ==\nA!\n== B ==\nb\n== C ==\nC!"
    out = section_diff(before, after)
    assert [c.title for c in out.changes] == ["A", "C"]


def test_the_method_and_its_LIMITS_travel_with_the_numbers():
    out = section_diff("lead", "lead2").as_dict()
    assert "templates are not expanded" in out["method"]
    assert "never a percentage" in out["method"], (
        "a one-character change to a date can matter more than a rewritten paragraph; "
        "this app does not rank other people's edits"
    )


def test_no_field_in_the_payload_carries_a_banned_no_score_fragment():
    out = section_diff("lead\n== A ==\nx", "lead\n== A ==\ny").as_dict()
    banned = ("score", "ranking", "rating", "grade", "quality")
    for key in out:
        assert not any(b in key.lower() for b in banned), key
    for change in out["changes"]:
        for key in change:
            assert not any(b in key.lower() for b in banned), key


def test_an_identical_pair_reports_NO_changes_and_a_real_unchanged_count():
    text = "lead\n== A ==\na\n== B ==\nb"
    out = section_diff(text, text)
    assert out.changes == ()
    assert out.unchanged == 3, "the lead plus both sections"
