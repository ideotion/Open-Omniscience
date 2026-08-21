"""
Structured legal-source adapters — a law read from its publisher's own XML.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (field feedback 2026-08-07, ruling 34a). The HTML path reads a legal
portal the way it reads a news site: fetch the page, strip what the markup declares to
be chrome, keep the rest. That works, and :mod:`src.services.boilerplate` made it work
much better — but it is still a *reconstruction*. The stored body of the UK *Data
Protection Act 2018* opened with the site's search form, and every bogus extraction
downstream (``Personal Acts`` as a PERSON, ``PART`` x24 as an ORGANIZATION) traced back
to text that was never part of the Act.

A publisher that serves its own XML removes that whole class of defect **by
construction**: there is no page chrome in the file, because the file is not a page. The
adapter's job is therefore not "strip better" but "read the structure the publisher
already declared" — which additionally yields the two things the HTML path can never
give us: a real provision tree (Part / Chapter / section), and dates that mean what they
say.

THE DATE DISCIPLINE (the maintainer's actual complaint). The reader showed *"Published
2026-07-31"* for a 2018 Act — the day we captured it, presented as the day it was made.
Three different dates were being collapsed into one field, so this contract keeps them
structurally separate and lets each be ``None``:

* ``enacted_on``    — when the legislature made it. Read from the document, never derived.
* ``valid_on``      — the point in time this consolidated text represents.
* ``retrieved_on``  — when WE fetched it. Supplied by the caller; the document cannot
  know it, so the parser never invents it.

A date that is not stated is ``None``. There is deliberately no fallback chain between
them: falling back is exactly how a capture date becomes a publication date.

HONEST STATUS OF THIS MODULE (read before trusting it). The parser is verified against
hand-authored fixtures written from the documented CLML shape, **not** against a fetched
document: ``legislation.gov.uk`` is not reachable from the build sandbox (the proxy
answers ``CONNECT tunnel failed, response 403``), and inventing a "sample response" to
test against would be a fabricated verification. It is therefore built to survive being
wrong about the schema rather than to assume it is right:

* elements are matched by **local name**, so a namespace revision does not break it;
* an unrecognised root is **refused**, never half-parsed into something a caller would
  store as an Act;
* elements it does not know are **counted and reported**, and their text is still kept —
  losing law text is worse than reporting an unfamiliar tag;
* it measures how much of the document's own body text it actually recovered, and refuses
  below a floor. That number is schema-independent: it is the one check that still works
  if every assumption above turns out to be wrong.

SAFETY: this is untrusted, network-fetched XML. Parsing goes through ``defusedxml`` --
the same guard :mod:`src.ingest.sitemap` and :mod:`src.wiki.dumpread` already use against
entity-expansion ("billion laughs") and external-entity (XXE) attacks that the stdlib
``ElementTree`` is vulnerable to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "AdapterRefusal",
    "ParsedLaw",
    "Provision",
    "TEXT_RECOVERY_FLOOR",
]

# Below this share of the body's own text, the parse is refused rather than returned.
# The point is not the exact number: it is that a parser which has understood a small
# fraction of a legal document must not hand that fraction back as "the Act". A caller
# storing 30% of a statute as its text has silently lost the rest, and nothing
# downstream could ever tell.
TEXT_RECOVERY_FLOOR = 0.80


class AdapterRefusal(Exception):
    """The adapter will not return a document, and says why.

    A refusal is a RESULT, not a crash: the caller records the reason and keeps the HTML
    path. Every refusal reason names what was actually observed, so a schema change shows
    up as a specific complaint rather than as silently emptier documents.
    """

    def __init__(self, reason: str, *, detail: str | None = None) -> None:
        super().__init__(reason if detail is None else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Provision:
    """One numbered provision (a section, article, regulation…) in document order.

    ``path`` is the chain of containers above it ("Part 1", "Chapter 2"), which is what
    makes a per-section diff addressable later: a provision's identity is its path plus
    its number, not its position in a list that shifts when a section is inserted.
    """

    number: str | None
    heading: str | None
    text: str
    path: tuple[str, ...] = ()
    element: str = ""

    @property
    def identifier(self) -> str:
        """A stable, human-readable address for this provision.

        Falls back to the heading, and then to the element name, so a provision with no
        number is still addressable — but never to an index, which would silently
        re-point at a different provision the moment one is inserted above it.
        """
        if self.number:
            return "/".join((*self.path, self.number))
        if self.heading:
            return "/".join((*self.path, self.heading))
        return "/".join((*self.path, self.element or "?"))


@dataclass
class ParsedLaw:
    """A legal document as its publisher declared it. Counts and text; no score."""

    title: str | None
    provisions: list[Provision] = field(default_factory=list)
    # The three dates, deliberately independent (see the module docstring).
    enacted_on: str | None = None
    valid_on: str | None = None
    retrieved_on: str | None = None
    # Publisher identifiers, when the document states them (never derived from the URL).
    document_number: str | None = None
    year: str | None = None
    # Honesty instruments.
    unknown_elements: dict[str, int] = field(default_factory=dict)
    text_recovered_pct: float = 0.0
    body_chars: int = 0
    format: str = ""

    @property
    def text(self) -> str:
        """The document's text, provisions in order, headings inline.

        This is what the tracker would store in place of the HTML reading — no page
        chrome by construction, because none was ever in the file.
        """
        out: list[str] = []
        for p in self.provisions:
            head = " ".join(x for x in (p.number, p.heading) if x)
            if head:
                out.append(head)
            if p.text:
                out.append(p.text)
        return "\n".join(out)

    def as_dict(self) -> dict:
        """Report shape — what was read and what was not understood."""
        return {
            "format": self.format,
            "title": self.title,
            "document_number": self.document_number,
            "year": self.year,
            "enacted_on": self.enacted_on,
            "valid_on": self.valid_on,
            "retrieved_on": self.retrieved_on,
            "provisions": len(self.provisions),
            "body_chars": self.body_chars,
            "text_recovered_pct": round(100 * self.text_recovered_pct, 1),
            "unknown_elements": dict(sorted(self.unknown_elements.items())),
            "method": (
                "Read from the publisher's own XML by element local name: provisions in "
                "document order with the container path above each, and each date taken "
                "only from the field that states it."
            ),
            "caveat": (
                "Dates are reported only where the document states them; there is no "
                "fallback between enactment, consolidation and capture, so a missing one "
                "reads as unknown rather than as another date. `unknown_elements` lists "
                "tags this adapter does not model -- their text is still included, so an "
                "unfamiliar tag costs recall in the structure, never text."
            ),
        }
