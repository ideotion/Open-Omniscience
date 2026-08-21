"""
Law-ingest reliability — did the fixes actually reach this install's data?

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Ruling 34c (field feedback 2026-08-07) asked for a diagnostic that re-parses STORED law
copies offline. Investigating what there is to re-parse turned up something more useful
to report first.

The 2026-08-07 law fixes are all SELF-HEALING, and none of them is VISIBLE:

* the boilerplate strip re-reads a tracked document's own baseline on the next poll
  (``track.check_document`` detects that the extractor changed rather than the law, and
  re-baselines without inventing an amendment);
* ``corpus.upsert_law_corpus_article`` clears a publication date that was really a poll
  date, on the next sync.

Both are correct, and both happen quietly, on a schedule, only for documents whose fetch
succeeds. So on any given install the honest questions — *has the strip re-read actually
reached all 23 documents? is any of them still carrying a capture date as its publication
date?* — had no answer anywhere. A fix nobody can confirm is indistinguishable from a fix
that never ran, and the documents most likely to be missed are exactly the ones whose
portal is unreachable.

This reports that, from stored data, with no network and no heuristics:

* ``re_extracted`` — read from the status the tracker itself wrote. Exact.
* ``stored_publication_date`` — a law corpus article still carrying ``published_at``.
  Exact, and expected to be zero once each document has synced once.
* ``chrome_residue`` — chrome text that survived into the stored body.

THE RESIDUE FIELD IS NOT A PRE-STRIP DETECTOR, and must not be read as one. The strip
stage removes what the markup DECLARES to be chrome and deliberately leaves the rest: a
bare skip link and a language switch outside any landmark carry no declaration, and
``tests/test_boilerplate_strip.py`` pins that limit on purpose, because the alternative
is a text heuristic that would also eat an Act's section headings. Residue is therefore
EXPECTED after a correct strip. What it gives a reader is the measure of the stated
limit — how much undeclared chrome is actually in the corpus — not a verdict on whether
the strip ran.

The marker vocabulary is a FLOOR, not a census: it lists chrome this project has actually
observed, so a count of zero means "none of these", never "no chrome". Widening it is the
one move that could start matching real statute text, so it stays deliberately narrow and
the number stays a floor.

THE STRUCTURED HALF (the literal ruling 34c). Re-parsing stored XML needs stored XML, and
nothing captures any yet: the CLML adapter landed alongside this file, and the enumeration
that would populate it is blocked on egress. Rather than ship a mechanism over an empty
set and let it read as a working feature, the structured section reports honestly that it
has no subject, and runs the adapter against its own fixture so at least the PARSER's
health in this install is a measured fact rather than an assumption.

Read-only and network-free by construction: it opens no socket, and every field is read
from the database or computed from a bundled fixture.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.database.models import Article, LawDocument
from src.services.boilerplate import BOILERPLATE_STRIP_VERSION

# Chrome this project has actually seen survive into a stored legal document (maintainer
# field report 2026-08-07, the Data Protection Act specimen). Deliberately narrow: every
# addition is a chance to match real statute text, and a false positive here would send a
# reader hunting a defect that is not there.
CHROME_MARKERS: tuple[str, ...] = (
    "Skip to main content",
    "Cymraeg",
    "Search Legislation",
    "All UK Legislation",
    "UK Private and Personal Acts",
    "Advanced Search",
    "Cookies on",
    "Change your cookie settings",
)

# The tracker writes this prefix when it re-reads a baseline through the strip stage.
_RE_EXTRACT_PREFIX = "re-read with"

_MAX_LISTED = 200  # bounded output; the totals are always exact


def _residue_in(text: str | None) -> list[str]:
    if not text:
        return []
    return [m for m in CHROME_MARKERS if m in text]


def law_ingest_report(session: Session) -> dict:
    """Counts + per-document facts, no score. See the module docstring for the caveats."""
    docs = session.query(LawDocument).order_by(LawDocument.jurisdiction, LawDocument.id).all()

    # One query for the law corpus articles, keyed by canonical URL, rather than one per
    # document: the article rows carry full text, and pulling them one at a time is the
    # per-row codec cost this codebase has been bitten by before.
    from src.law.corpus import law_canonical_url

    urls = {law_canonical_url(d): d.id for d in docs}
    dated: dict[int, object] = {}
    if urls:
        rows = (
            session.query(Article.canonical_url, Article.published_at)
            .filter(Article.canonical_url.in_(list(urls)))
            .filter(Article.published_at.isnot(None))
            .all()
        )
        for url, published in rows:
            dated[urls[url]] = published

    per_document: list[dict] = []
    re_extracted = 0
    with_residue = 0
    marker_counts: dict[str, int] = {}
    never_checked = 0

    for d in docs:
        status = d.last_status or ""
        was_re_extracted = status.lower().startswith(_RE_EXTRACT_PREFIX)
        if was_re_extracted:
            re_extracted += 1
        if d.last_checked_at is None:
            never_checked += 1
        stored_text = d.latest_text or d.baseline_text
        markers = _residue_in(stored_text)
        if markers:
            with_residue += 1
            for m in markers:
                marker_counts[m] = marker_counts.get(m, 0) + 1
        if len(per_document) < _MAX_LISTED:
            per_document.append(
                {
                    "id": d.id,
                    "jurisdiction": d.jurisdiction,
                    "title": d.title,
                    "chars_stored": len(stored_text) if stored_text else 0,
                    "re_extracted": was_re_extracted,
                    "chrome_residue": markers,
                    # Exact: a law article should carry no publication date, because the
                    # only date we had was the day we polled it.
                    "stored_publication_date": (
                        str(dated[d.id]) if d.id in dated else None
                    ),
                    "last_status": d.last_status,
                }
            )

    return {
        "documents": len(docs),
        "never_checked": never_checked,
        "re_extracted": re_extracted,
        "awaiting_re_extraction": len(docs) - re_extracted - never_checked,
        "with_chrome_residue": with_residue,
        "chrome_markers_found": dict(sorted(marker_counts.items())),
        "stored_publication_dates": len(dated),
        "strip_version": BOILERPLATE_STRIP_VERSION,
        "per_document": per_document,
        "listed": len(per_document),
        "truncated": max(0, len(docs) - len(per_document)),
        "structured": _structured_section(),
        "method": (
            "Read from stored data only -- no fetch. `re_extracted` is the tracker's own "
            "recorded status for a baseline it re-read through the strip stage; "
            "`stored_publication_dates` counts law corpus articles still carrying a "
            "published_at, which should be zero once each document has synced once, "
            "because the only date available was the day we polled the page. "
            "`chrome_markers_found` counts occurrences of a fixed vocabulary of observed "
            "page chrome in the stored body."
        ),
        "caveat": (
            "Chrome residue is NOT evidence that the strip stage did not run: the strip "
            "removes what the markup declares to be chrome and deliberately leaves the "
            "rest, because a text heuristic would also eat an Act's section headings. "
            "Residue measures that stated limit. The marker list is a FLOOR -- zero means "
            "none of these markers, never no chrome. `awaiting_re_extraction` counts "
            "documents checked at least once whose last outcome was something other than "
            "a strip re-read; a document heals on its next successful poll, so a portal "
            "that cannot be fetched never heals and is exactly what this field surfaces."
        ),
    }


def _structured_section() -> dict:
    """The XML half of ruling 34c, and an honest account of its subject.

    Runs the adapter against its own bundled fixture: with nothing captured to re-parse
    yet, the parser's health in THIS install is the only thing here that can be measured
    rather than assumed.
    """
    from pathlib import Path

    from src.law.adapters import AdapterRefusal
    from src.law.adapters.clml import FORMAT, parse_clml

    fixture = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "law" / "example_act.clml.xml"
    selftest: dict = {"fixture": fixture.name, "ok": False}
    try:
        parsed = parse_clml(fixture.read_bytes(), retrieved_on=None)
        selftest.update(
            ok=True,
            provisions=len(parsed.provisions),
            text_recovered_pct=round(100 * parsed.text_recovered_pct, 1),
            unknown_elements=parsed.unknown_elements,
        )
    except (AdapterRefusal, OSError) as exc:
        # A diagnostic that cannot run its own check says so; it never reports a pass.
        selftest.update(ok=False, error=f"{type(exc).__name__}: {exc}")

    return {
        "adapters": [FORMAT],
        "documents_captured": 0,
        "documents_reparsed": 0,
        "adapter_selftest": selftest,
        "note": (
            "No structured (XML) legal documents are captured yet, so there is nothing to "
            "re-parse: the CLML adapter exists but the enumeration that would populate it "
            "is blocked on egress in the build environment. `documents_captured: 0` is the "
            "real subject count, not a failure. The self-test above exercises the parser "
            "against its own bundled fixture, which is hand-authored (see "
            "tests/fixtures/law/PROVENANCE.md) -- it proves the parser runs correctly HERE, "
            "and says nothing about whether it reads the live service correctly. That needs "
            "one document fetched on a machine with egress."
        ),
    }
