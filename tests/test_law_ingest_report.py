"""Law-ingest reliability: did the 2026-08-07 fixes actually reach the data?

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Both law fixes heal on a document's next SUCCESSFUL poll and neither is reported
anywhere, so "has this reached all 23 documents?" had no answer -- and a portal that
cannot be fetched never heals, which is exactly the case a maintainer needs to see.

The delicate assertion here is the one about chrome residue: it is NOT a pre-strip
detector, because the strip stage deliberately leaves undeclared chrome (a text heuristic
would eat an Act's section headings -- pinned in tests/test_boilerplate_strip.py). A
future reader who mistakes residue for "the strip did not run" would go hunting a defect
that is not there, so the distinction is tested in both directions.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, LawDocument, Source
from src.law.ingest_report import CHROME_MARKERS, law_ingest_report

_RE_EXTRACTED = "re-read with strip-1 (-2100 bytes of page chrome); the document itself is unchanged"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _doc(session, **kw) -> LawDocument:
    d = LawDocument(
        jurisdiction=kw.pop("jurisdiction", "uk"),
        title=kw.pop("title", "An Act 2018"),
        url=kw.pop("url", "https://example.test/act"),
        last_checked_at=kw.pop("last_checked_at", datetime.now(UTC)),
        **kw,
    )
    session.add(d)
    session.commit()
    return d


# ------------------------------------------------------------ the healing is visible


def test_a_re_extracted_document_is_counted_as_healed(db):
    _doc(db, last_status=_RE_EXTRACTED, baseline_text="Clean Act text.")
    r = law_ingest_report(db)
    assert r["re_extracted"] == 1
    assert r["awaiting_re_extraction"] == 0
    assert r["per_document"][0]["re_extracted"] is True


def test_a_document_still_awaiting_the_re_read_is_the_one_worth_seeing(db):
    """A portal that cannot be fetched never heals -- the whole point of the field."""
    _doc(db, last_status="fetch error: robots.txt disallows https://example.test/act")
    r = law_ingest_report(db)
    assert r["re_extracted"] == 0
    assert r["awaiting_re_extraction"] == 1


def test_a_never_checked_document_is_not_smeared_into_awaiting(db):
    """No outcome to classify yet is its own fact, counted once and only once.

    (The same rule law_coverage already applies to its verdict tally: a document with no
    outcome must not be counted both as "never checked" and as a bad outcome.)
    """
    _doc(db, last_checked_at=None, last_status=None)
    r = law_ingest_report(db)
    assert r["never_checked"] == 1
    assert r["awaiting_re_extraction"] == 0
    assert r["re_extracted"] == 0


# --------------------------------------------------------------- the residue measure


def test_chrome_that_survived_into_the_stored_body_is_reported(db):
    _doc(db, baseline_text="Skip to main content Cymraeg\n1 Overview\nThis Act provides.")
    r = law_ingest_report(db)
    assert r["with_chrome_residue"] == 1
    assert r["chrome_markers_found"] == {"Cymraeg": 1, "Skip to main content": 1}
    assert set(r["per_document"][0]["chrome_residue"]) == {"Skip to main content", "Cymraeg"}


def test_residue_does_not_contradict_a_successful_re_read(db):
    """The direction that matters: residue is EXPECTED after a correct strip.

    The strip removes what the markup declares to be chrome and leaves the rest, so a
    document can be correctly re-read AND still contain a skip link. Reporting that as
    "the strip did not run" would send a reader after a defect that is not there.
    """
    _doc(db, last_status=_RE_EXTRACTED, baseline_text="Skip to main content\n1 Overview\nThe Act.")
    r = law_ingest_report(db)
    assert r["re_extracted"] == 1
    assert r["with_chrome_residue"] == 1
    assert r["per_document"][0]["re_extracted"] is True
    assert "NOT evidence" in r["caveat"]


def test_clean_stored_text_reports_no_residue(db):
    """The twin: an over-eager marker list would flag ordinary statute text."""
    _doc(
        db,
        baseline_text=(
            "1 Overview\nThis Act makes provision about the protection of personal data. "
            "Part 2 contains general processing provisions and applies to all controllers."
        ),
    )
    r = law_ingest_report(db)
    assert r["with_chrome_residue"] == 0
    assert r["chrome_markers_found"] == {}


def test_the_marker_vocabulary_is_declared_a_floor(db):
    _doc(db, baseline_text="Some text.")
    r = law_ingest_report(db)
    assert "FLOOR" in r["caveat"]
    assert len(CHROME_MARKERS) > 0


# --------------------------------------------------------- the poll-date-as-pub-date


def test_a_law_article_still_carrying_a_publication_date_is_counted(db):
    """The exact residue of the "Published 2026-07-31 for a 2018 Act" defect.

    upsert_law_corpus_article clears this on the next sync, so a non-zero count means
    the sync has not reached that document yet -- a fact, not a heuristic.
    """
    from src.law.corpus import law_canonical_url

    d = _doc(db, baseline_text="The Act.")
    src = Source(name="Law (uk)", domain="law.uk.local")
    db.add(src)
    db.commit()
    db.add(
        Article(
            url=law_canonical_url(d),
            canonical_url=law_canonical_url(d),
            source_id=src.id,
            title=d.title,
            content="The Act.",
            hash="h1",
            published_at=datetime(2026, 7, 31, tzinfo=UTC),
        )
    )
    db.commit()
    r = law_ingest_report(db)
    assert r["stored_publication_dates"] == 1
    assert r["per_document"][0]["stored_publication_date"] is not None


def test_a_healed_article_reports_no_publication_date(db):
    """The twin -- after the sync clears it, the field must go quiet."""
    from src.law.corpus import law_canonical_url

    d = _doc(db, baseline_text="The Act.")
    src = Source(name="Law (uk)", domain="law.uk.local")
    db.add(src)
    db.commit()
    db.add(
        Article(
            url=law_canonical_url(d),
            canonical_url=law_canonical_url(d),
            source_id=src.id,
            title=d.title,
            content="The Act.",
            hash="h1",
            published_at=None,
        )
    )
    db.commit()
    r = law_ingest_report(db)
    assert r["stored_publication_dates"] == 0
    assert r["per_document"][0]["stored_publication_date"] is None


# ------------------------------------------------------------------- shape + honesty


def test_an_install_with_no_tracked_law_reports_an_honest_empty(db):
    r = law_ingest_report(db)
    assert r["documents"] == 0
    assert r["per_document"] == []
    assert r["method"] and r["caveat"]


def test_the_structured_half_says_it_has_no_subject_yet(db):
    """Ruling 34c literally asks for XML re-parsing; nothing captures XML yet.

    Reporting a mechanism over an empty set as if it were working is the defect this
    project calls a dead end, so the section states its subject count instead.
    """
    s = law_ingest_report(db)["structured"]
    assert s["documents_captured"] == 0
    assert s["documents_reparsed"] == 0
    assert "clml" in s["adapters"]
    assert "blocked on egress" in s["note"]


def test_the_adapter_selftest_proves_the_parser_runs_in_this_install(db):
    s = law_ingest_report(db)["structured"]["adapter_selftest"]
    assert s["ok"] is True
    assert s["provisions"] == 3
    assert s["text_recovered_pct"] >= 80.0


def test_no_field_in_the_report_is_score_shaped(db):
    _doc(db, baseline_text="Skip to main content The Act.", last_status=_RE_EXTRACTED)
    r = law_ingest_report(db)
    banned = ("score", "ranking", "rating", "grade", "quality", "health_score")

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(b in str(k).lower() for b in banned), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(r)


def test_the_per_document_list_is_bounded_and_says_so(db):
    from src.law.ingest_report import _MAX_LISTED

    for i in range(_MAX_LISTED + 5):
        _doc(db, title=f"Act {i}", url=f"https://example.test/act/{i}", baseline_text="x")
    r = law_ingest_report(db)
    assert r["documents"] == _MAX_LISTED + 5
    assert r["listed"] == _MAX_LISTED
    assert r["truncated"] == 5  # stated, never a silent cut


# ------------------------------------------------------------------- the verdict badge


def test_a_re_read_is_its_own_verdict_and_not_other():
    """Ruling 35 succeeding must not read as "we do not know what happened"."""
    from src.api.law import _verdict_of

    assert _verdict_of(_RE_EXTRACTED) == "re_extracted"


def test_the_neighbouring_verdicts_are_unchanged():
    """The twin: a new branch must not capture outcomes that already had a verdict."""
    from src.api.law import _verdict_of

    assert _verdict_of("unchanged") == "unchanged"
    assert _verdict_of("changed (+120 bytes vs baseline)") == "changed"
    assert _verdict_of("baseline captured") == "baselined"
    assert _verdict_of("version already recorded") == "other"


# ------------------------------------------------------------------ zero network


def test_the_report_opens_no_socket_at_all(db, monkeypatch):
    """Network-free BY CONSTRUCTION, not merely by convention.

    Stronger than engaging the kill switch, which would only prove the guard works: here
    every socket entry point RAISES, so the report completing at all is proof it never
    tried. A diagnostic an operator runs to understand a stalled install must not be the
    thing that reaches for the network.
    """
    import socket

    def _boom(*a, **kw):  # pragma: no cover - the point is that it never runs
        raise AssertionError("law_ingest_report attempted a network call")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(socket.socket, "connect", _boom)

    _doc(db, last_status=_RE_EXTRACTED, baseline_text="Skip to main content\n1 The Act.")
    r = law_ingest_report(db)
    assert r["documents"] == 1
    assert r["structured"]["adapter_selftest"]["ok"] is True  # the fixture read is local
