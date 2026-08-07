"""The one poll after the strip ships must not invent an amendment.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The boilerplate strip changes what ``page_text`` returns, so on the first poll after it
lands every tracked document's stored text legitimately changes. Left alone, the tracker
would read that as a new version: a ``LawRevision``, a large NEGATIVE delta and -- since
real portal chrome runs past ``LARGE_CHANGE_BYTES`` (1000) -- a ``large_removal`` FLAG.
A fabricated, flagged amendment on a legal audit trail is a worse defect than the chrome
it came from.

``check_document`` therefore asks the question directly rather than guessing: it re-reads
the same bytes the OLD way and checks whether that still matches what was stored. These
pin both answers, because getting only the first one right would silently swallow a real
amendment that happened to land in the same window.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytest.importorskip("bs4", reason="bs4 is the parser the strip stage runs through")

from src.database.models import Base, LawDocument, LawRevision  # noqa: E402
from src.ingest import FetchResult  # noqa: E402
from src.law.track import page_text, track_document  # noqa: E402

#: Long enough that removing it clears LARGE_CHANGE_BYTES -- i.e. the case where the
#: fabricated revision would also have been FLAGGED, which is what makes this matter.
_CHROME = (
    '<div id="header">'
    '<form action="/search"><h2>Search Legislation</h2>'
    '<label for="t">Title:</label><label for="y">Year:</label>'
    "<select>"
    + "".join(
        f"<option>All UK Legislation category {i} excluding originating from the EU</option>"
        for i in range(30)
    )
    + "</select><button>Search</button></form></div>"
)

_ACT = " ".join(
    f"Section {i}: every person shall have the right to liberty and security."
    for i in range(40)
)
_AMENDED = _ACT + " Amendment 1: this provision is hereby substituted across the realm."


def _page(act: str, *, chrome: bool = True) -> str:
    return (
        "<html><head><title>Act</title></head><body>"
        f"{_CHROME if chrome else ''}<main>{act}</main></body></html>"
    )


class StubFetcher:
    def __init__(self, page: str = ""):
        self.page = page

    def fetch(self, url: str, *, require_html: bool = True, **_kw) -> FetchResult:
        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            content=self.page,
            content_type="text/html",
            fetched_at=datetime.now(UTC),
        )


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _doc(db) -> LawDocument:
    d = LawDocument(jurisdiction="uk", title="Data Protection Act 2018",
                    url="https://law.test/dpa", watched=True)
    db.add(d)
    db.commit()
    return d


def _baseline_the_old_way(db, doc, page: str) -> None:
    """Put the document in the state a pre-strip install is in: baselined on text that
    still contains the chrome."""
    legacy = page_text(page, legacy=True)
    import hashlib

    h = hashlib.sha256(legacy.encode("utf-8")).hexdigest()
    doc.baseline_text = legacy
    doc.baseline_hash = h
    doc.last_hash = h
    doc.last_size = len(legacy)
    doc.latest_text = legacy
    db.add(LawRevision(document_id=doc.id, observed_at=datetime.now(UTC),
                       content_hash=h, size=len(legacy), delta_bytes=0,
                       full_text=legacy, flagged=False))
    db.commit()


def test_the_chrome_removal_would_have_been_a_flagged_amendment():
    """The control. Without this, the fix below could be guarding nothing."""
    from src.wiki.flagging import flag_revision

    page = _page(_ACT)
    delta = len(page_text(page)) - len(page_text(page, legacy=True))
    assert delta < 0, "the specimen must actually lose bytes to the strip"
    assert flag_revision(delta_bytes=delta).flagged, (
        "the specimen must be big enough to trip large_removal -- otherwise this whole "
        "file is testing a case that could not have hurt"
    )


def test_an_extractor_change_re_baselines_and_records_no_revision(db):
    page = _page(_ACT)
    doc = _doc(db)
    _baseline_the_old_way(db, doc, page)
    before = db.query(LawRevision).filter_by(document_id=doc.id).count()

    res = track_document(db, StubFetcher(page), doc)

    assert res["status"] == "re-extracted", res
    assert db.query(LawRevision).filter_by(document_id=doc.id).count() == before, (
        "no revision may be written for a change that happened in our reader"
    )
    assert doc.baseline_text == page_text(page), "the baseline moves to the clean reading"
    assert "UK Private and Personal Acts" not in (doc.latest_text or "")
    assert "unchanged" in (doc.last_status or ""), doc.last_status
    assert res["chrome_bytes_removed"] > 0


def test_it_is_idempotent_and_the_next_poll_is_simply_unchanged(db):
    page = _page(_ACT)
    doc = _doc(db)
    _baseline_the_old_way(db, doc, page)
    fetcher = StubFetcher(page)

    assert track_document(db, fetcher, doc)["status"] == "re-extracted"
    # Self-limiting: last_hash now holds a STRIPPED hash, which a legacy reading can
    # never equal, so the branch cannot fire twice.
    assert track_document(db, fetcher, doc)["status"] == "unchanged"
    assert track_document(db, fetcher, doc)["status"] == "unchanged"


def test_a_real_amendment_in_the_same_window_is_never_absorbed(db):
    """The twin, and the reason the check re-reads rather than trusting a version stamp.

    If the law changes on the SAME poll the extractor changes, the old reading no longer
    matches either -- so this must fall through to the normal path and record the
    amendment, not quietly fold it into a re-baseline.
    """
    doc = _doc(db)
    _baseline_the_old_way(db, doc, _page(_ACT))
    before = db.query(LawRevision).filter_by(document_id=doc.id).count()

    res = track_document(db, StubFetcher(_page(_AMENDED)), doc)

    assert res["status"] == "changed", res
    assert db.query(LawRevision).filter_by(document_id=doc.id).count() == before + 1
    rev = (
        db.query(LawRevision)
        .filter_by(document_id=doc.id)
        .order_by(LawRevision.id.desc())
        .first()
    )
    assert "substituted across the realm" in (rev.full_text or ""), (
        "the amendment's own text must be what got recorded"
    )


def test_a_genuine_amendment_after_the_re_baseline_still_records(db):
    """And the pipeline keeps working afterwards -- a re-baseline must not leave the
    document unable to notice its next real change."""
    doc = _doc(db)
    _baseline_the_old_way(db, doc, _page(_ACT))
    assert track_document(db, StubFetcher(_page(_ACT)), doc)["status"] == "re-extracted"

    res = track_document(db, StubFetcher(_page(_AMENDED)), doc)
    assert res["status"] == "changed", res
    assert res["delta_bytes"] > 0, "an addition after the re-baseline reads as an addition"


def test_a_first_sighting_is_still_a_baseline_not_a_re_extraction(db):
    """The branch is guarded on an EXISTING baseline; a brand-new document must take
    the ordinary path."""
    doc = _doc(db)
    assert track_document(db, StubFetcher(_page(_ACT)), doc)["status"] == "baseline"
    assert "UK Private and Personal Acts" not in (doc.baseline_text or "")
