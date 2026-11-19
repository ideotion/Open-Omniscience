"""The PubMed ``PubmedArticleSet`` XML format, parsed in pure Python (brief S07-01, slice S1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ONE FORMAT, BOTH TRANSPORTS. NLM's baseline and daily update files and the E-utilities
``efetch`` answer are the same ``PubmedArticleSet`` document, so this one parser serves the bulk
transport the maintainer prefers (V1-4 as answered under RC11 = b, «pubmed bulk prefered over
API») and any later API path alike. It reads a byte stream and touches no socket, no file and no
database: what is kept, and where, is the store's business (R745: only the records the user's
corpus cites or the user names).

WHAT IT REFUSES TO INVENT. A record without an abstract has ``abstract=None``, a gap, never an
empty string that reads as "the abstract is blank". A publication date the journal gave only as
free text (``MedlineDate``, ``"1998 Dec-1999 Jan"``) keeps that text and has no ISO date; a
partial date stays partial (``"2024"``, ``"2024-03"``). A record with no readable PMID cannot be
identified, so it is SKIPPED AND COUNTED in the tally, never given a made-up id. A book record
(``PubmedBookArticle``) is not an article, and is counted, not read.

PROVENANCE IS READ FROM THE RECORD (the 2026-07-14 ruling: preprint, peer-reviewed and retracted
are classes, never blended; retraction status is first-class). ``retracted`` when the record's
publication types say ``Retracted Publication`` or a ``CommentsCorrections`` link says the record
was retracted (``RetractionIn``, ``RetractedandRepublishedIn``); else ``preprint`` when its types
say ``Preprint``; else ``journal``. ``journal`` means "a record PubMed indexes as a journal
publication": peer review is the journal's claim, which nothing here verifies, and the surface
says so. A record that is itself a retraction notice, an erratum or an expression of concern
also names that in ``notice_kind``. NOT RETRACTED IS ONLY "NOT RETRACTED IN THIS COPY OF THE
RECORD": a retraction NLM recorded after this file was written is not in it.

THE XML IS SOMEBODY ELSE'S, so it goes through ``defusedxml`` (a core dependency): an
entity-expansion bomb fails as a parse error, never as a machine out of memory. The ``DOCTYPE``
NLM puts at the top of every file names an external DTD; expat never fetches it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import IO, Any

#: Provenance classes, in the order the surface lists them.
CLASSES = ("journal", "preprint", "retracted")

#: ``CommentsCorrections`` link types that say THIS record was retracted.
_RETRACTED_BY = frozenset({"RetractionIn", "RetractedandRepublishedIn"})

#: Link types kept on a record, as (link type, PMID or None, the source text NLM gives).
#: Every other link type (CommentIn, Cites, ...) is a citation relation, not a status, and is
#: not kept here.
STATUS_LINKS = frozenset(
    {
        "RetractionIn",
        "RetractionOf",
        "RetractedandRepublishedIn",
        "RetractedandRepublishedFrom",
        "ErratumIn",
        "ErratumFor",
        "ExpressionOfConcernIn",
        "ExpressionOfConcernFor",
        "CorrectedandRepublishedIn",
        "CorrectedandRepublishedFrom",
        "UpdateIn",
        "UpdateOf",
    }
)

#: Publication types that make the record itself a notice about another record.
_NOTICE_TYPES = {
    "Retraction of Publication": "retraction_notice",
    "Published Erratum": "erratum",
    "Expression of Concern": "expression_of_concern",
}

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_DAYS_IN = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_PMCID = re.compile(r"PMC[1-9][0-9]{0,9}")
_DIGITS = re.compile(r"[1-9][0-9]{0,9}")
_WS = re.compile(r"\s+")

#: A bound per text field, so one malformed record cannot hold the whole file's memory. Real
#: abstracts are a few thousand characters; the longest PubMed allows is far below this.
MAX_TEXT = 100_000


@dataclass(frozen=True, slots=True)
class AbstractSection:
    #: NLM's label (``BACKGROUND``, ``METHODS`` ...) or None for an unstructured abstract.
    label: str | None
    text: str


@dataclass(frozen=True, slots=True)
class StatusLink:
    ref_type: str
    pmid: int | None
    source: str | None


@dataclass(frozen=True, slots=True)
class PubmedRecord:
    pmid: int
    version: int
    #: ``MedlineCitation/@Status``: MEDLINE, PubMed-not-MEDLINE, In-Process, Publisher ...
    citation_status: str | None
    title: str | None
    vernacular_title: str | None
    #: None = the record carries no abstract (a gap). Never an empty tuple.
    abstract: tuple[AbstractSection, ...] | None
    abstract_copyright: str | None
    journal: str | None
    #: ISO, as precise as the record: "2024", "2024-03" or "2024-03-05". None when only free text exists.
    pub_date: str | None
    #: The free-text date, verbatim, when the record gives no structured one.
    pub_date_text: str | None
    languages: tuple[str, ...]
    doi: str | None
    pmcid: str | None
    publication_types: tuple[str, ...]
    mesh: tuple[str, ...]
    keywords: tuple[str, ...]
    provenance_class: str
    notice_kind: str | None
    status_links: tuple[StatusLink, ...]


@dataclass(frozen=True, slots=True)
class PubmedDeletion:
    """An update file's ``DeleteCitation`` entry: NLM withdrew this PMID from PubMed."""

    pmid: int
    version: int


@dataclass(slots=True)
class ParseTally:
    """What one parse read, and what it could not, by reason. Counts are exact."""

    articles: int = 0
    deletions: int = 0
    books_skipped: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def _text(el: Any) -> str | None:
    """All text under ``el`` (inline markup like ``<i>`` and ``<sup>`` flattened), whitespace folded."""
    if el is None:
        return None
    out = _WS.sub(" ", "".join(el.itertext())).strip()
    if len(out) > MAX_TEXT:
        out = out[:MAX_TEXT]
    return out or None


def _pmid(el: Any) -> tuple[int, int] | None:
    """(PMID, version) from a ``<PMID Version="n">`` element, or None when either is unreadable."""
    if el is None:
        return None
    raw = (el.text or "").strip()
    if not _DIGITS.fullmatch(raw):
        return None
    version = (el.get("Version") or "1").strip()
    if not _DIGITS.fullmatch(version):
        return None
    return int(raw), int(version)


def _month(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        n = int(raw)
        return n if 1 <= n <= 12 else None
    return _MONTHS.get(raw[:3].lower())


def _date(pub: Any) -> tuple[str | None, str | None]:
    """(partial ISO date, free text) from a ``PubDate``. Never more precise than the record."""
    if pub is None:
        return None, None
    medline = _text(pub.find("MedlineDate"))
    year_raw = (pub.findtext("Year") or "").strip()
    if not (len(year_raw) == 4 and year_raw.isdigit()):
        return None, medline
    out = year_raw
    month = _month(pub.findtext("Month"))
    if month is None:
        # A Season ("Spring") is text, not a month: the year stands alone, and the season is kept verbatim.
        return out, _text(pub.find("Season")) or medline
    out += f"-{month:02d}"
    day_raw = (pub.findtext("Day") or "").strip()
    if day_raw.isdigit() and 1 <= int(day_raw) <= _DAYS_IN[month - 1]:
        out += f"-{int(day_raw):02d}"
    return out, medline


def _ids(pubmed_data: Any) -> dict[str, str]:
    """The record's OWN article ids. Only the direct ``PubmedData/ArticleIdList``: a reference list
    nests further ``ArticleIdList`` elements, and those are the ids of the papers it CITES."""
    out: dict[str, str] = {}
    if pubmed_data is None:
        return out
    for aid in pubmed_data.findall("ArticleIdList/ArticleId"):
        kind = aid.get("IdType")
        val = (aid.text or "").strip()
        if kind and val and kind not in out:
            out[kind] = val
    return out


def _doi(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    # A DOI is "10.<registrant>/<suffix>"; anything else in the id slot is not one.
    return raw if raw.startswith("10.") and "/" in raw and len(raw) <= 300 else None


def _record(el: Any, tally: ParseTally) -> PubmedRecord | None:
    cit = el.find("MedlineCitation")
    ident = _pmid(cit.find("PMID")) if cit is not None else None
    if ident is None:
        tally.skip("no readable PMID")
        return None
    art = cit.find("Article")
    if art is None:
        tally.skip("no Article element")
        return None

    sections: list[AbstractSection] = []
    abstract_el = art.find("Abstract")
    if abstract_el is not None:
        for part in abstract_el.findall("AbstractText"):
            text = _text(part)
            if text:
                label = (part.get("Label") or "").strip() or None
                sections.append(AbstractSection(label=label, text=text))

    ptypes = tuple(t for t in (_text(p) for p in art.findall("PublicationTypeList/PublicationType")) if t)

    links: list[StatusLink] = []
    for cc in cit.findall("CommentsCorrectionsList/CommentsCorrections"):
        ref_type = cc.get("RefType")
        if ref_type not in STATUS_LINKS:
            continue
        target = _pmid(cc.find("PMID"))
        links.append(StatusLink(ref_type=ref_type, pmid=target[0] if target else None, source=_text(cc.find("RefSource"))))

    if "Retracted Publication" in ptypes or any(lk.ref_type in _RETRACTED_BY for lk in links):
        klass = "retracted"
    elif "Preprint" in ptypes:
        klass = "preprint"
    else:
        klass = "journal"
    notice = next((_NOTICE_TYPES[t] for t in ptypes if t in _NOTICE_TYPES), None)

    ids = _ids(el.find("PubmedData"))
    doi = _doi(ids.get("doi"))
    if doi is None:
        for loc in art.findall("ELocationID"):
            if loc.get("EIdType") == "doi" and loc.get("ValidYN", "Y") != "N":
                doi = _doi(loc.text)
                if doi:
                    break
    pmc = (ids.get("pmc") or "").strip()

    pub_date, pub_text = _date(art.find("Journal/JournalIssue/PubDate"))
    mesh = tuple(d for d in (_text(m.find("DescriptorName")) for m in cit.findall("MeshHeadingList/MeshHeading")) if d)
    keywords = tuple(k for k in (_text(k) for k in cit.findall("KeywordList/Keyword")) if k)
    languages = tuple(lang for lang in ((x.text or "").strip().lower() for x in art.findall("Language")) if lang)

    return PubmedRecord(
        pmid=ident[0],
        version=ident[1],
        citation_status=(cit.get("Status") or None),
        title=_text(art.find("ArticleTitle")),
        vernacular_title=_text(art.find("VernacularTitle")),
        abstract=tuple(sections) if sections else None,
        abstract_copyright=_text(abstract_el.find("CopyrightInformation")) if abstract_el is not None else None,
        journal=_text(art.find("Journal/Title")),
        pub_date=pub_date,
        pub_date_text=pub_text,
        languages=languages,
        doi=doi,
        pmcid=pmc if _PMCID.fullmatch(pmc) else None,
        publication_types=ptypes,
        mesh=mesh,
        keywords=keywords,
        provenance_class=klass,
        notice_kind=notice,
        status_links=tuple(links),
    )


def parse_pubmed(stream: IO[bytes], tally: ParseTally | None = None) -> Iterator[PubmedRecord | PubmedDeletion]:
    """Every article and every deletion in a ``PubmedArticleSet`` document, in document order.

    ``tally`` (optional) receives the counts, including what was skipped and why. A document
    whose root is not ``PubmedArticleSet`` is refused with a ``ValueError`` before anything is
    yielded: a different XML file is not "a PubMed file with no articles".
    """
    from defusedxml.ElementTree import iterparse

    t = tally if tally is not None else ParseTally()
    root = None
    depth = 0
    for event, el in iterparse(stream, events=("start", "end")):
        if event == "start":
            if root is None:
                if el.tag != "PubmedArticleSet":
                    raise ValueError(f"not a PubMed file: the root element is <{el.tag}>, not <PubmedArticleSet>")
                root = el
            depth += 1
            continue
        depth -= 1
        if depth != 1:
            continue  # only the root's direct children are records; everything deeper is read through them
        if el.tag == "PubmedArticle":
            rec = _record(el, t)
            if rec is not None:
                t.articles += 1
                yield rec
        elif el.tag == "DeleteCitation":
            for p in el.findall("PMID"):
                ident = _pmid(p)
                if ident is None:
                    t.skip("deletion with no readable PMID")
                    continue
                t.deletions += 1
                yield PubmedDeletion(pmid=ident[0], version=ident[1])
        elif el.tag == "PubmedBookArticle":
            t.books_skipped += 1
        else:
            t.skip(f"unknown record <{el.tag}>")
        # Free the record AND the root's reference to it: a daily file holds tens of thousands.
        el.clear()
        if root is not None:
            root.remove(el)
