"""The CLML adapter: what it reads, and the five things it refuses to do.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field feedback 2026-08-07, ruling 34a. The HTML path reconstructs a law from a web page;
this reads it from the publisher's own XML, where page chrome does not exist. The tests
below are mostly about the REFUSALS, because a parser that returns a plausible-looking
empty Act is worse than one that fails: the tracker would store it, diff against it, and
report an amendment that never happened.

The fixture is HAND-AUTHORED (tests/fixtures/law/PROVENANCE.md) -- legislation.gov.uk is
not reachable from the build sandbox, and a file invented and called a captured sample
would be a fabricated verification. So these tests pin BEHAVIOUR, not schema fidelity:
every one of them would still be the right assertion if the real element names differ.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.law.adapters import TEXT_RECOVERY_FLOOR, AdapterRefusal
from src.law.adapters.clml import parse_clml

FIXTURE = Path(__file__).parent / "fixtures" / "law" / "example_act.clml.xml"


@pytest.fixture(scope="module")
def act() -> bytes:
    return FIXTURE.read_bytes()


# ---------------------------------------------------------------- what it reads


def test_the_provision_tree_is_read_in_document_order(act):
    doc = parse_clml(act)
    assert [p.number for p in doc.provisions] == ["1", "2", "3"]
    assert [p.heading for p in doc.provisions] == [
        "Overview of this Act",
        "Interpretation",
        "Duty to measure",
    ]


def test_a_provision_is_addressable_by_its_container_path(act):
    doc = parse_clml(act)
    # The address a citation uses -- and the key a per-section diff needs, which an
    # index into a list could never be: inserting a section renumbers every index.
    assert doc.provisions[0].identifier == "Part 1 Preliminary/1"
    assert doc.provisions[2].identifier == "Part 2 Measurement/3"


def test_a_provisions_number_and_heading_are_not_repeated_inside_its_own_text(act):
    doc = parse_clml(act)
    first = doc.provisions[0]
    assert first.text == "This Act makes provision about the measurement of things."
    assert not first.text.startswith("1")
    assert "Overview of this Act" not in first.text


def test_a_subsection_stays_inside_its_section(act):
    """One provision per citable section, carrying its subsections.

    Splitting subsections out would make an amendment to s.2(2) report as a change to a
    different provision than s.2 -- the diff would be addressing something a reader does
    not cite.
    """
    doc = parse_clml(act)
    assert len(doc.provisions) == 3
    section_2 = doc.provisions[1]
    assert "A reference to measurement includes estimation." in section_2.text


def test_the_whole_document_text_carries_no_page_chrome(act):
    doc = parse_clml(act)
    text = doc.text
    assert "measurement of things" in text
    # The defect this adapter exists to make structurally impossible: the HTML reading of
    # the real Data Protection Act opened with the portal's search form.
    for chrome in ("Skip to main content", "Cymraeg", "Search Legislation", "Title:"):
        assert chrome not in text


# ------------------------------------------------------------- the date discipline


def test_each_date_comes_only_from_the_field_that_states_it(act):
    doc = parse_clml(act, retrieved_on="2026-08-20")
    assert doc.enacted_on == "2018-05-23"  # when the legislature made it
    assert doc.valid_on == "2026-01-01"  # what point in time this text represents
    assert doc.retrieved_on == "2026-08-20"  # when we fetched it
    assert len({doc.enacted_on, doc.valid_on, doc.retrieved_on}) == 3


def test_the_capture_date_never_becomes_the_documents_own_date(act):
    """The maintainer's actual complaint: "Published 2026-07-31" on a 2018 Act.

    The document WITH a stated date is the easy half, and on its own it cannot fail: a
    fallback short-circuits on the real value and never fires. The discriminating case is
    the document that states no date at all -- that is where a fallback would invent one.
    """
    doc = parse_clml(act, retrieved_on="2026-07-31")
    assert doc.enacted_on == "2018-05-23"
    assert doc.enacted_on != doc.retrieved_on

    undated = """<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
      <Metadata><Title>An Act</Title></Metadata>
      <Body><P1><Pnumber>1</Pnumber><Text>Some provision of the law.</Text></P1></Body>
    </Legislation>"""
    doc = parse_clml(undated, retrieved_on="2026-07-31")
    assert doc.enacted_on is None, "the capture date was substituted for an unstated one"
    assert doc.valid_on is None


def test_an_unstated_date_is_none_rather_than_another_date():
    """A missing date must read as unknown -- never fall back to a date we do have."""
    xml = """<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
      <Metadata><Title>Undated Act</Title></Metadata>
      <Body><P1><Pnumber>1</Pnumber><Text>Some provision of the law.</Text></P1></Body>
    </Legislation>"""
    doc = parse_clml(xml, retrieved_on="2026-08-20")
    assert doc.enacted_on is None
    assert doc.valid_on is None
    assert doc.retrieved_on == "2026-08-20"


def test_a_year_inside_the_body_is_not_the_documents_year():
    """A year mentioned in the law is not the year the law was made."""
    xml = """<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
      <Metadata><Title>An Act</Title></Metadata>
      <Body><P1><Pnumber>1</Pnumber>
        <Text>The scheme established in 1971 continues in force under this Act.</Text>
        <Year>1971</Year>
      </P1></Body>
    </Legislation>"""
    doc = parse_clml(xml)
    assert doc.year is None


# -------------------------------------------------------------------- the refusals


def test_an_unrecognised_root_is_refused_not_half_parsed():
    """An error page, a search result or a redirect all parse as "some XML"."""
    html = "<html><body><h1>Page not found</h1><p>Try searching instead.</p></body></html>"
    with pytest.raises(AdapterRefusal) as exc:
        parse_clml(html)
    assert "not a CLML document" in str(exc.value)
    assert "html" in str(exc.value)  # names what it actually saw


def test_malformed_xml_is_refused():
    with pytest.raises(AdapterRefusal) as exc:
        parse_clml("<Legislation><Body><P1>unclosed")
    assert "not well-formed" in str(exc.value)


def test_a_document_with_no_provisions_is_refused():
    """Structure but no law in it is a parse failure, not an empty Act."""
    xml = """<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
      <Metadata><Title>Shell</Title></Metadata><Body><Part><Title>Part 1</Title></Part></Body>
    </Legislation>"""
    with pytest.raises(AdapterRefusal) as exc:
        parse_clml(xml)
    assert "no provisions found" in str(exc.value)


def test_recovering_too_little_of_the_body_is_refused():
    """The load-bearing check -- it holds even if every schema assumption is wrong.

    Here most of the body's text sits in an element the adapter treats as a container
    with no provisions inside it, so the text is real, present, and NOT captured. A
    parser that returned this would have silently dropped most of a statute.
    """
    filler = " ".join(f"Section text number {i} of considerable length." for i in range(200))
    xml = f"""<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
      <Metadata><Title>Mostly Unread</Title></Metadata>
      <Body>
        <P1><Pnumber>1</Pnumber><Text>A short captured provision.</Text></P1>
        <Schedule><Title>Schedule 1</Title><Unmodelled>{filler}</Unmodelled></Schedule>
      </Body>
    </Legislation>"""
    with pytest.raises(AdapterRefusal) as exc:
        parse_clml(xml)
    assert "too little of the document was recovered" in str(exc.value)
    assert f"{TEXT_RECOVERY_FLOOR:.0%}" in str(exc.value)  # states the bar it failed


def test_entity_expansion_is_refused_rather_than_parsed():
    """Untrusted network XML: the billion-laughs / XXE guard, not the stdlib parser."""
    bomb = """<?xml version="1.0"?>
    <!DOCTYPE Legislation [
      <!ENTITY a "aaaaaaaaaa">
      <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
    ]>
    <Legislation><Body><P1><Pnumber>1</Pnumber><Text>&b;</Text></P1></Body></Legislation>"""
    with pytest.raises(AdapterRefusal) as exc:
        parse_clml(bomb)
    assert "xml" in str(exc.value).lower()


# ------------------------------------------------- the twins (never over-refuse)


def test_an_unmodelled_element_costs_structure_but_never_text():
    """An unfamiliar tag is reported -- and its text is still kept.

    The twin of the recovery refusal above: the adapter must not become so strict that a
    schema it half-recognises reads as a failure. Losing law text is the worse error.
    """
    xml = """<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation">
      <Metadata><Title>An Act</Title></Metadata>
      <Body><P1><Pnumber>1</Pnumber>
        <P1para><Text>The ordinary provision text.</Text></P1para>
        <SomethingNew>Text inside a tag this adapter does not model.</SomethingNew>
      </P1></Body>
    </Legislation>"""
    doc = parse_clml(xml)
    assert doc.provisions
    assert "Text inside a tag this adapter does not model." in doc.provisions[0].text
    # Reported, because a silent unknown is how a schema change goes unnoticed. It is
    # counted at the point it is MET -- inside a captured provision, the walk stops, so
    # the report is about elements between provisions.
    assert isinstance(doc.unknown_elements, dict)


def test_a_namespace_revision_does_not_break_the_read(act):
    """Matching is by local name, so the publisher may renumber its namespaces."""
    original = act.decode("utf-8")
    revised = original.replace(
        "http://www.legislation.gov.uk/namespaces/legislation",
        "http://www.legislation.gov.uk/namespaces/legislation/2030",
    )
    before, after = parse_clml(original), parse_clml(revised)
    assert after.text == before.text
    assert [p.identifier for p in after.provisions] == [p.identifier for p in before.provisions]


def test_a_clean_document_reports_full_recovery_and_no_unknowns(act):
    """Anti-vacuity: the refusal tests above must not be passing because nothing parses."""
    doc = parse_clml(act)
    assert doc.text_recovered_pct >= TEXT_RECOVERY_FLOOR
    assert doc.unknown_elements == {}
    assert doc.body_chars > 0


def test_the_report_states_its_method_and_its_caveat(act):
    d = parse_clml(act, retrieved_on="2026-08-20").as_dict()
    assert d["method"] and d["caveat"]
    assert d["provisions"] == 3
    # No score-shaped field anywhere in the payload (the house key-walk convention).
    banned = ("score", "ranking", "rating", "grade", "quality")
    assert not [k for k in d if any(b in k.lower() for b in banned)]
