"""Per-provision diff: which sections changed, and what it refuses to guess.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The document-level text diff answers "did it change, by how many bytes". Once a document
is read from structured XML, the question a reader actually asks becomes answerable:
*which sections changed?* These tests pin the identity rule that makes it trustworthy --
provisions match by citable address, never by position -- and the limit it accepts.
"""

from __future__ import annotations

from src.law.adapters import ParsedLaw, Provision
from src.law.adapters.diff import diff_provisions


def _doc(*provisions: tuple[str, str, str]) -> ParsedLaw:
    """(number, heading, text) triples in one flat Part."""
    return ParsedLaw(
        title="An Act",
        provisions=[
            Provision(number=n, heading=h, text=t, path=("Part 1",), element="P1")
            for n, h, t in provisions
        ],
    )


BASE = _doc(
    ("1", "Overview", "This Act makes provision about things."),
    ("2", "Interpretation", "In this Act, thing means a thing."),
    ("3", "Duty", "A person must measure each thing."),
)


def test_an_untouched_document_reports_nothing_changed():
    d = diff_provisions(BASE, BASE)
    assert d.touched == 0
    assert d.unchanged == 3


def test_one_amended_section_is_the_only_one_reported():
    after = _doc(
        ("1", "Overview", "This Act makes provision about things."),
        ("2", "Interpretation", "In this Act, thing means any measurable thing."),
        ("3", "Duty", "A person must measure each thing."),
    )
    d = diff_provisions(BASE, after)
    assert d.by_status() == {"changed": 1}
    assert d.changes[0].identifier == "Part 1/2"
    assert d.changes[0].delta_chars == len("In this Act, thing means any measurable thing.") - len(
        "In this Act, thing means a thing."
    )
    assert d.unchanged == 2


def test_inserting_a_section_does_not_report_the_rest_of_the_act_as_amended():
    """The whole reason identity is an address and not an index.

    A position-matched diff would slide every provision below the insertion by one and
    report the remainder of the statute as changed -- a fabricated amendment on exactly
    the audit trail whose value is being trustworthy.
    """
    after = _doc(
        ("1", "Overview", "This Act makes provision about things."),
        ("1A", "Purpose", "The purpose of this Act is measurement."),
        ("2", "Interpretation", "In this Act, thing means a thing."),
        ("3", "Duty", "A person must measure each thing."),
    )
    d = diff_provisions(BASE, after)
    assert d.by_status() == {"added": 1}
    assert d.changes[0].identifier == "Part 1/1A"
    assert d.unchanged == 3


def test_a_repealed_section_is_reported_as_removed():
    after = _doc(
        ("1", "Overview", "This Act makes provision about things."),
        ("3", "Duty", "A person must measure each thing."),
    )
    d = diff_provisions(BASE, after)
    assert d.by_status() == {"removed": 1}
    assert d.changes[0].identifier == "Part 1/2"
    assert d.changes[0].chars_after is None


def test_a_renumbered_but_identical_section_is_a_move_not_a_rewrite():
    after = _doc(
        ("1", "Overview", "This Act makes provision about things."),
        ("2A", "Interpretation", "In this Act, thing means a thing."),
        ("3", "Duty", "A person must measure each thing."),
    )
    d = diff_provisions(BASE, after)
    assert d.by_status() == {"moved": 1}
    assert d.changes[0].identifier == "Part 1/2 -> Part 1/2A"
    assert d.changes[0].delta_chars == 0


def test_a_renumbered_AND_amended_section_is_reported_as_two_facts_not_one_guess():
    """The stated limit -- and it must stay stated rather than be smoothed over.

    Matching a renumbered, rewritten provision to its former self means guessing which of
    two differently-numbered provisions is "the same one, edited". The honest output is
    the two facts actually observed.
    """
    after = _doc(
        ("1", "Overview", "This Act makes provision about things."),
        ("2A", "Interpretation", "Entirely different replacement wording here."),
        ("3", "Duty", "A person must measure each thing."),
    )
    d = diff_provisions(BASE, after)
    assert d.by_status() == {"added": 1, "removed": 1}
    assert {c.identifier for c in d.changes} == {"Part 1/2", "Part 1/2A"}


def test_a_heading_change_alone_is_still_a_change():
    after = _doc(
        ("1", "Overview", "This Act makes provision about things."),
        ("2", "Meaning of thing", "In this Act, thing means a thing."),
        ("3", "Duty", "A person must measure each thing."),
    )
    d = diff_provisions(BASE, after)
    assert d.by_status() == {"changed": 1}


def test_moving_a_section_between_parts_is_a_move_not_a_deletion():
    """Identity is the whole path, so a section that changes Part is still traceable."""
    after = ParsedLaw(
        title="An Act",
        provisions=[
            Provision(number="1", heading="Overview", text="This Act makes provision about things.", path=("Part 1",), element="P1"),
            Provision(number="3", heading="Duty", text="A person must measure each thing.", path=("Part 1",), element="P1"),
            Provision(number="2", heading="Interpretation", text="In this Act, thing means a thing.", path=("Part 2",), element="P1"),
        ],
    )
    d = diff_provisions(BASE, after)
    assert d.by_status() == {"moved": 1}
    assert d.changes[0].identifier == "Part 1/2 -> Part 2/2"


def test_counts_are_stated_and_no_field_is_score_shaped():
    d = diff_provisions(BASE, _doc(("1", "Overview", "changed text"))).as_dict()
    assert d["provisions_before"] == 3 and d["provisions_after"] == 1
    assert d["method"] and d["caveat"]
    banned = ("score", "ranking", "rating", "similarity", "confidence")
    assert not [k for k in d if any(b in k.lower() for b in banned)]
    for change in d["changes"]:
        assert not [k for k in change if any(b in k.lower() for b in banned)]
