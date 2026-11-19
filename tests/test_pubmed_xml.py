"""The PubMed XML parser (brief S07-01 slice S1): what it reads, and the gaps it refuses to fill.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Fixture only: the sandbox cannot reach NLM, and the fixture is invented text in NLM's shape (the
2026-07-14 ruling keeps real abstracts out of the repository). Most checks are negative space:
the gap stays a gap, the class is read from the record and never guessed, a cited paper's ids are
never taken for the record's own.
"""

from __future__ import annotations

import gzip
import io
from pathlib import Path

import pytest

from src.medical.pubmed_xml import (
    CLASSES,
    MAX_TEXT,
    ParseTally,
    PubmedDeletion,
    PubmedRecord,
    parse_pubmed,
)

FIXTURE = Path(__file__).parent / "fixtures" / "medical" / "pubmed_update_sample.xml"


def _parse(data: bytes) -> tuple[list, ParseTally]:
    tally = ParseTally()
    return list(parse_pubmed(io.BytesIO(data), tally)), tally


@pytest.fixture(scope="module")
def parsed() -> tuple[dict[int, PubmedRecord], list[PubmedDeletion], ParseTally]:
    items, tally = _parse(FIXTURE.read_bytes())
    recs = {r.pmid: r for r in items if isinstance(r, PubmedRecord)}
    dels = [d for d in items if isinstance(d, PubmedDeletion)]
    return recs, dels, tally


def _wrap(body: str) -> bytes:
    return f'<?xml version="1.0"?><PubmedArticleSet>{body}</PubmedArticleSet>'.encode()


def _article(pmid: str = "1", inner: str = "", data: str = "") -> str:
    return (
        f'<PubmedArticle><MedlineCitation Status="MEDLINE"><PMID Version="1">{pmid}</PMID>'
        f"<Article><ArticleTitle>t</ArticleTitle>{inner}</Article></MedlineCitation>"
        f"<PubmedData>{data}</PubmedData></PubmedArticle>"
    )


# --- the tally: every record accounted for ---------------------------------------------------


def test_every_record_in_the_file_is_read_or_counted_by_reason(parsed):
    recs, dels, tally = parsed
    assert sorted(recs) == [90000001, 90000002, 90000003, 90000004, 90000005]
    assert [(d.pmid, d.version) for d in dels] == [(90000007, 1), (90000008, 1)]
    assert tally.articles == 5
    assert tally.deletions == 2
    assert tally.books_skipped == 1
    # The record with an empty PMID is skipped and COUNTED, never given an id.
    assert tally.skipped == {"no readable PMID": 1}


def test_an_empty_update_file_is_zero_records_not_an_error():
    items, tally = _parse(_wrap(""))
    assert items == []
    assert (tally.articles, tally.deletions, tally.books_skipped, tally.skipped) == (0, 0, 0, {})


def test_a_file_that_is_not_pubmed_is_refused_not_read_as_empty():
    with pytest.raises(ValueError, match="not a PubMed file"):
        _parse(b"<?xml version='1.0'?><osmChange><create/></osmChange>")


def test_an_entity_expansion_bomb_is_refused_as_a_parse_error():
    bomb = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>
<PubmedArticleSet>&b;</PubmedArticleSet>"""
    from defusedxml import DefusedXmlException

    with pytest.raises(DefusedXmlException):
        _parse(bomb)


def test_nlms_external_doctype_is_accepted_and_never_fetched(parsed):
    # The fixture opens with NLM's DOCTYPE naming an https DTD; the parse above succeeded with no
    # network (the test suite has none), so expat read the declaration and fetched nothing.
    assert FIXTURE.read_bytes().count(b"<!DOCTYPE PubmedArticleSet PUBLIC") == 1
    assert parsed[2].articles == 5


def test_a_gzip_update_file_parses_through_a_gzip_stream():
    raw = gzip.compress(FIXTURE.read_bytes())
    with gzip.open(io.BytesIO(raw)) as fh:
        tally = ParseTally()
        assert sum(1 for _ in parse_pubmed(fh, tally)) == 7
    assert tally.articles == 5


# --- provenance: read from the record, never blended ------------------------------------------


def test_provenance_classes_are_read_from_the_record(parsed):
    recs, _, _ = parsed
    assert recs[90000001].provenance_class == "journal"
    assert recs[90000002].provenance_class == "retracted"
    assert recs[90000003].provenance_class == "preprint"
    assert recs[90000004].provenance_class == "journal"
    assert set(CLASSES) == {"journal", "preprint", "retracted"}


def test_a_retraction_link_alone_makes_a_record_retracted():
    # No "Retracted Publication" type: NLM sometimes links the notice before the type is added.
    cc = '<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn"><PMID Version="1">7</PMID></CommentsCorrections></CommentsCorrectionsList>'
    xml = _wrap(
        '<PubmedArticle><MedlineCitation><PMID Version="1">5</PMID><Article><ArticleTitle>t</ArticleTitle>'
        "<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article>"
        f"{cc}</MedlineCitation></PubmedArticle>"
    )
    (rec,), _ = _parse(xml)
    assert rec.provenance_class == "retracted"
    assert [(lk.ref_type, lk.pmid) for lk in rec.status_links] == [("RetractionIn", 7)]


def test_a_retracted_preprint_is_retracted_not_preprint():
    types = "<PublicationTypeList><PublicationType>Preprint</PublicationType><PublicationType>Retracted Publication</PublicationType></PublicationTypeList>"
    (rec,), _ = _parse(_wrap(_article(inner=types)))
    assert rec.provenance_class == "retracted"


def test_a_retraction_notice_is_named_as_a_notice_and_is_not_itself_retracted(parsed):
    recs, _, _ = parsed
    notice = recs[90000005]
    assert notice.notice_kind == "retraction_notice"
    assert notice.provenance_class == "journal"
    assert [(lk.ref_type, lk.pmid) for lk in notice.status_links] == [("RetractionOf", 90000002)]


def test_only_status_links_are_kept_and_a_comment_is_not_a_status(parsed):
    recs, _, _ = parsed
    links = recs[90000001].status_links
    assert [(lk.ref_type, lk.pmid, lk.source) for lk in links] == [("ErratumIn", 90000098, "J Invented Results 2024;12:99")]
    assert recs[90000001].provenance_class == "journal"  # an erratum corrects; it does not retract


# --- the gaps stay gaps -----------------------------------------------------------------------


def test_a_record_with_no_abstract_has_a_gap_not_an_empty_abstract(parsed):
    recs, _, _ = parsed
    assert recs[90000004].abstract is None
    assert recs[90000004].abstract_copyright is None
    assert recs[90000005].abstract is None


def test_an_abstract_with_only_empty_sections_is_a_gap():
    (rec,), _ = _parse(_wrap(_article(inner="<Abstract><AbstractText>   </AbstractText></Abstract>")))
    assert rec.abstract is None


def test_a_structured_abstract_keeps_its_sections_and_flattens_inline_markup(parsed):
    recs, _, _ = parsed
    rec = recs[90000001]
    assert [(s.label, s.text) for s in rec.abstract] == [
        ("BACKGROUND", "Invented background text spread over lines."),
        ("RESULTS", "An effect of 1.2 (CI 0.9 to 1.5) in an invented group of 103."),
    ]
    assert rec.abstract_copyright == "Copyright 2024 The Invented Authors."
    assert rec.title == "A fictional cohort study of example outcomes."
    unstructured = recs[90000002].abstract
    assert unstructured is not None and unstructured[0].label is None


def test_dates_are_never_more_precise_than_the_record(parsed):
    recs, _, _ = parsed
    assert (recs[90000001].pub_date, recs[90000001].pub_date_text) == ("2024-03-05", None)
    assert (recs[90000002].pub_date, recs[90000002].pub_date_text) == ("2019-11", None)
    # Free text only: no ISO date is invented from it, the text is kept verbatim.
    assert (recs[90000004].pub_date, recs[90000004].pub_date_text) == (None, "1998 Dec-1999 Jan")
    # A season is not a month: the year stands alone, the season is kept as text.
    assert (recs[90000005].pub_date, recs[90000005].pub_date_text) == ("2021", "Spring")


@pytest.mark.parametrize(
    ("pubdate", "expected"),
    [
        ("<Year>2024</Year><Month>Feb</Month><Day>30</Day>", "2024-02"),  # an impossible day is dropped, not clamped
        ("<Year>2024</Year><Month>13</Month>", "2024"),  # an impossible month leaves the year
        ("<Year>24</Year>", None),  # a two-digit year is not a year
        ("", None),
    ],
)
def test_an_impossible_date_part_is_dropped_never_repaired(pubdate, expected):
    inner = f"<Journal><JournalIssue><PubDate>{pubdate}</PubDate></JournalIssue></Journal>"
    (rec,), _ = _parse(_wrap(_article(inner=inner)))
    assert rec.pub_date == expected


# --- ids: the record's own, validated ---------------------------------------------------------


def test_ids_are_the_records_own_and_never_a_cited_papers(parsed):
    recs, _, _ = parsed
    rec = recs[90000001]
    assert rec.doi == "10.9999/jir.2024.001"  # PubmedData wins over ELocationID
    assert rec.pmcid == "PMC9000001"  # never the reference list's PMC9999999
    # A record with no PMC id of its own does not borrow the one a paper it cites carries.
    assert recs[90000003].pmcid is None


def test_a_doi_falls_back_to_the_elocation_and_an_invalid_one_is_refused():
    loc = '<ELocationID EIdType="doi" ValidYN="Y">10.1/abc</ELocationID>'
    (rec,), _ = _parse(_wrap(_article(inner=loc)))
    assert rec.doi == "10.1/abc"
    bad = '<ELocationID EIdType="doi" ValidYN="N">10.1/abc</ELocationID>'
    (rec,), _ = _parse(_wrap(_article(inner=bad)))
    assert rec.doi is None


def test_malformed_ids_are_absent_not_kept(parsed):
    recs, _, _ = parsed
    assert recs[90000004].doi is None
    assert recs[90000004].pmcid is None


@pytest.mark.parametrize("pmid", ["", "abc", "0", "-5", "12 34", "1" * 11])
def test_an_unreadable_pmid_skips_the_record_and_counts_it(pmid):
    items, tally = _parse(_wrap(_article(pmid=pmid)))
    assert items == []
    assert tally.skipped == {"no readable PMID": 1}


def test_a_deletion_with_an_unreadable_pmid_is_counted_and_the_rest_still_read():
    items, tally = _parse(_wrap('<DeleteCitation><PMID Version="1">x</PMID><PMID Version="1">42</PMID></DeleteCitation>'))
    assert items == [PubmedDeletion(pmid=42, version=1)]
    assert tally.skipped == {"deletion with no readable PMID": 1}


def test_version_is_read_and_identity_is_pmid_plus_version(parsed):
    recs, _, _ = parsed
    assert recs[90000002].version == 2
    assert recs[90000001].version == 1


# --- the rest of the record -------------------------------------------------------------------


def test_languages_mesh_keywords_types_and_status_are_carried(parsed):
    recs, _, _ = parsed
    rec = recs[90000001]
    assert rec.languages == ("eng",)
    assert rec.mesh == ("Humans", "Cohort Studies")
    assert rec.keywords == ("invented outcome",)
    assert rec.publication_types == ("Journal Article",)
    assert rec.citation_status == "MEDLINE"
    assert rec.journal == "Journal of Invented Results"
    assert recs[90000004].vernacular_title == "Un article inventé sans résumé."
    assert recs[90000004].languages == ("fre",)


def test_an_oversized_text_field_is_bounded():
    big = "x" * (MAX_TEXT + 500)
    (rec,), _ = _parse(_wrap(_article(inner=f"<Abstract><AbstractText>{big}</AbstractText></Abstract>")))
    assert len(rec.abstract[0].text) == MAX_TEXT


def test_records_are_freed_from_the_root_as_they_are_read():
    # A daily file holds tens of thousands of records: none may stay attached to the root.
    import defusedxml.ElementTree as DET

    roots: list = []
    real = DET.iterparse

    def spy(stream, events):
        for ev, el in real(stream, events=events):
            if not roots:
                roots.append(el)
            yield ev, el

    DET.iterparse = spy
    try:
        items = list(parse_pubmed(io.BytesIO(_wrap(_article("1") + '<DeleteCitation><PMID Version="1">9</PMID></DeleteCitation>' + _article("2")))))
    finally:
        DET.iterparse = real
    assert len(items) == 3
    # Every record, deletion included, was removed from the root once read.
    assert len(roots[0]) == 0


def test_the_module_never_touches_a_socket_or_a_database():
    src = Path(__file__).resolve().parents[1].joinpath("src", "medical", "pubmed_xml.py").read_text()
    for forbidden in ("import requests", "import httpx", "import socket", "urllib", "sqlalchemy", "session_scope"):
        assert forbidden not in src
