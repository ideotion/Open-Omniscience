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

* ``re_extracted`` — read from the status the tracker itself wrote. Exact, and TRANSIENT:
  the tracker writes "re-read with ..." on the one poll that re-baselines a document
  through the strip stage, and the next poll of the same unchanged document overwrites it
  with "unchanged". So it counts documents whose LAST poll was that re-read, never the
  documents still to heal, and on a healed install it falls back toward zero.
* ``last_status_mix`` — what each document's last check recorded, through the ONE
  classifier the Law tab and the coverage report already use (``src.api.law._verdict_of``).
  Each per-document row carries that verdict and its ``last_checked_at`` (UTC). They say
  which documents' LAST check stored no fresh body (an error, a deferral, a robots
  refusal, an empty extraction, no check at all) and when each was last attempted, and
  that is all: a re-read leaves no lasting trace (the status that names it is overwritten
  by the next poll, and no revision is written), so a document that healed in August and
  has failed since November reads the same as one that has failed since before the strip
  shipped. Such a verdict marks a CANDIDATE for still holding pre-strip text, never proof.
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
from src.monitoring.secret_scrub import record_text
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
    from src.database.country_form import order_key

    docs = sorted(session.query(LawDocument).all(), key=lambda d: order_key(d.jurisdiction, d.id))  # see order_key

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

    from src.api.law import _verdict_of  # the ONE classification, reused (never a 2nd guess)

    verdicts: dict[str, int] = {}

    for d in docs:
        status = d.last_status or ""
        verdict = _verdict_of(d.last_status)
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
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
                    "verdict": verdict,
                    "last_checked_at": (
                        d.last_checked_at.isoformat() if d.last_checked_at is not None else None
                    ),
                }
            )

    return {
        "documents": len(docs),
        "never_checked": never_checked,
        "re_extracted": re_extracted,
        "last_status_mix": dict(sorted(verdicts.items())),
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
            "recorded status for a baseline it re-read through the strip stage, on the one "
            "poll that re-read it; `last_status_mix` classifies every document's last "
            "recorded status with the Law tab's own verdicts; `never_checked` counts "
            "documents with no check time; `last_checked_at` is the time of the last "
            "attempt, in UTC; "
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
            "none of these markers, never no chrome. `re_extracted` is not a count of "
            "documents still to heal: the next unchanged poll records `unchanged`, so a "
            "fully healed install shows few or none. Whether a given document ever healed "
            "is not recorded anywhere. A `verdict` of error, deferred, robots_blocked, "
            "empty or never_checked says its last check stored no fresh body, so it is a "
            "CANDIDATE for still holding pre-strip text, never proof: a document that healed "
            "long ago and fails today reads the same."
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
        selftest.update(ok=False, error=record_text(exc, typed=True))

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
