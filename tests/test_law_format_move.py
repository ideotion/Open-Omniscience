"""R753: a tracked act moves from its HTML page to its own XML without an invented amendment.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The German federal acts were tracked from the portal's HTML pages; the catalogue now names
the portal's own XML (``/<act>/xml.zip``) and keeps the HTML address in ``previous_urls``.
Re-pointing a stored row at the XML would make the next poll compare text read one way with
text read another and record the difference as an amendment on the legal audit trail. R753
(2026-11-19) is the rule for moving such a row, and every clause of it is pinned here:

* (a)/(b) the move happens only on a poll whose HTML reading equals the stored text, and
  records NO revision;
* (c) an HTML reading that changed is an amendment like any other, and the move waits;
* (d)/condition 4: a refused, unreachable, robots-blocked, empty, far shorter or
  different-act XML reading leaves the row on HTML with the reason visible, storing nothing;
* (e)/condition 5: exactly one more request, to the same host, through the same fetcher;
* conditions 1 and 2: a permanent history row that keeps everything the move replaced;
* condition 3: an extractor re-baseline runs on its own poll, never beside a move;
* condition 6: the next amendment is measured against the XML text, never the HTML;
* the backup merge maps a backup taken on either side of the move onto ONE document.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("bs4", reason="the HTML reading runs through the strip stage")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.api.law import _verdict_of  # noqa: E402
from src.database.models import Base, LawDocument, LawFormatChange, LawRevision  # noqa: E402
from src.ingest import FetchError, FetchResult  # noqa: E402
from src.law import track  # noqa: E402
from src.law.adapters.gii import parse_gii  # noqa: E402
from src.law.catalog import format_move_targets  # noqa: E402

GG = Path(__file__).parent / "fixtures" / "law" / "gii" / "gg_excerpt.xml"
HTML_URL = "https://www.gesetze-im-internet.de/gg/"
XML_URL = "https://www.gesetze-im-internet.de/gg/xml.zip"
TITLE = "Grundgesetz für die Bundesrepublik Deutschland"


def _zip(xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("BJNR000010949.xml", xml)
    return buf.getvalue()


XML_TEXT = parse_gii(GG.read_bytes()).text


def _html(extra: str = "") -> str:
    """The act's HTML page: its title, its provisions and the table of contents the XML sets aside."""
    paras = "".join(f"<p>{line}</p>" for line in XML_TEXT.split("\n") if line.strip())
    return f"<html><head><title>GG</title></head><body><main><h1>{TITLE}</h1>{paras}{extra}</main></body></html>"


def _result(url: str, *, body: str, raw: bytes | None = None, ctype: str = "text/html") -> FetchResult:
    return FetchResult(
        requested_url=url, final_url=url, status_code=200, content=body,
        content_type=ctype, fetched_at=datetime.now(UTC), raw_content=raw,
    )


class Portal:
    """A fetcher double: the HTML page at its address, the archive at its own, every request counted."""

    def __init__(self, html: str | None = None, archive: bytes | None = None, xml_error: Exception | None = None):
        self.html = _html() if html is None else html
        self.archive = _zip(GG.read_bytes()) if archive is None else archive
        self.xml_error = xml_error
        self.asked: list[str] = []

    def fetch(self, url, *, require_html=True, keep_bytes=False, **_kw):
        self.asked.append(url)
        if url == XML_URL:
            if self.xml_error is not None:
                raise self.xml_error
            return _result(url, body=self.archive.decode("latin-1"), raw=self.archive, ctype="application/zip")
        return _result(url, body=self.html, raw=self.html.encode("utf-8"))


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(track, "_ingest_to_corpus", lambda *a, **k: None)
    monkeypatch.setattr(track, "_record_lane", lambda *a, **k: "recorded")
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _tracked_from_html(db) -> LawDocument:
    doc = LawDocument(jurisdiction="de", title="GG", url=HTML_URL, watched=True)
    db.add(doc)
    db.commit()
    assert track.track_document(db, Portal(), doc)["status"] == "baseline"
    return doc


# --------------------------------------------------------------------------- #
# The move itself                                                             #
# --------------------------------------------------------------------------- #


def test_an_unchanged_html_poll_moves_the_row_and_records_NO_amendment(db):
    doc = _tracked_from_html(db)
    html_hash, html_text = doc.last_hash, doc.baseline_text
    portal = Portal()

    res = track.track_document(db, portal, doc, move_to=XML_URL)

    assert res["status"] == "moved"
    assert portal.asked == [HTML_URL, XML_URL], "exactly one more request, to the new address (rule e)"
    assert doc.url == XML_URL
    assert doc.baseline_text == XML_TEXT and doc.latest_text == XML_TEXT
    assert db.query(LawRevision).filter_by(document_id=doc.id).count() == 1, "a format change is not an amendment"
    assert doc.last_status.startswith("re-read from the portal's XML (format change)")
    assert _verdict_of(doc.last_status) == "re_extracted"

    (row,) = db.query(LawFormatChange).filter_by(document_id=doc.id).all()
    assert (row.from_url, row.to_url, row.from_format, row.to_format) == (HTML_URL, XML_URL, "html", "gii")
    assert row.from_hash == html_hash and row.to_hash == doc.last_hash
    # Condition 2: everything the move replaced is kept, so it can be audited and undone.
    assert row.from_baseline_text == html_text and row.from_latest_text == html_text
    assert row.from_baseline_hash == html_hash
    assert row.changed_at is not None


def test_the_next_amendment_is_measured_against_the_XML_never_the_HTML(db):
    doc = _tracked_from_html(db)
    track.track_document(db, Portal(), doc, move_to=XML_URL)
    amended = GG.read_bytes().replace(b"</dokumente>", (
        b"<norm><metadaten><enbez>Art 999</enbez></metadaten><textdaten><text format=\"XML\"><Content>"
        b"<P>Ein neuer Artikel wird eingef\xc3\xbcgt.</P></Content></text></textdaten></norm></dokumente>"
    ))

    res = track.track_document(db, Portal(archive=_zip(amended)), doc)

    assert res["status"] == "changed"
    new_text = parse_gii(amended).text
    assert res["delta_bytes"] == len(new_text) - len(XML_TEXT), "measured against the XML text (condition 6)"
    rev = db.query(LawRevision).filter_by(document_id=doc.id).order_by(LawRevision.id.desc()).first()
    assert TITLE not in (rev.diff or ""), "the HTML-only heading must not read as a change"
    assert "Art 999" in rev.diff


def test_a_changed_html_reading_is_an_amendment_and_the_move_WAITS(db):
    doc = _tracked_from_html(db)
    portal = Portal(html=_html("<p>Artikel 147: eine Änderung, die wirklich geschah.</p>"))

    res = track.track_document(db, portal, doc, move_to=XML_URL)

    assert res["status"] == "changed"
    assert portal.asked == [HTML_URL], "no move is attempted on a poll that saw an amendment (rule c)"
    assert doc.url == HTML_URL
    assert db.query(LawFormatChange).count() == 0


def test_an_extractor_rebaseline_runs_on_its_OWN_poll_and_the_move_waits(db):
    import hashlib

    # Page chrome the strip removes and the legacy reading keeps (the shape of the re-extraction tests).
    chrome = (
        '<div id="header"><form action="/search"><h2>Suche</h2><select>'
        + "".join(f"<option>Alle Bundesgesetze Kategorie {i}</option>" for i in range(30))
        + "</select><button>Suchen</button></form></div>"
    )
    page = _html().replace("<main>", chrome + "<main>")
    doc = LawDocument(jurisdiction="de", title="GG", url=HTML_URL, watched=True)
    db.add(doc)
    db.commit()
    track.track_document(db, Portal(html=page), doc)
    # The stored hash is the LEGACY reading of the same page: the extractor changed, the law did not.
    legacy = track.page_text(page, legacy=True)
    assert legacy != doc.baseline_text, "control: the two extractors read this page differently"
    doc.last_hash = hashlib.sha256(legacy.encode("utf-8")).hexdigest()
    db.commit()
    portal = Portal(html=page)

    res = track.track_document(db, portal, doc, move_to=XML_URL)

    assert res["status"] == "re-extracted"
    assert portal.asked == [HTML_URL], "never two re-baselines in one pass (condition 3)"
    assert doc.url == HTML_URL


# --------------------------------------------------------------------------- #
# Every refusal stays on HTML, says why, and stores nothing                   #
# --------------------------------------------------------------------------- #


def _assert_stayed(db, doc, html_text, needle):
    assert doc.url == HTML_URL
    assert doc.baseline_text == html_text and doc.latest_text == html_text
    assert db.query(LawFormatChange).count() == 0
    assert db.query(LawRevision).filter_by(document_id=doc.id).count() == 1
    assert doc.last_status.startswith("unchanged; stays on its HTML address: "), doc.last_status
    assert needle in doc.last_status, doc.last_status
    assert _verdict_of(doc.last_status) == "unchanged", "the document itself was read and has not changed"


@pytest.mark.parametrize(
    "portal, needle",
    [
        (lambda: Portal(xml_error=FetchError("robots.txt disallows https://www.gesetze-im-internet.de/gg/xml.zip")),
         "could not be fetched"),
        (lambda: Portal(xml_error=OSError("airplane mode")), "could not be fetched"),
        (lambda: Portal(archive=b"PK\x03\x04 not really an archive"), "did not read as a structured act"),
        (lambda: Portal(archive=_html().encode("utf-8")), "did not read as a structured act"),
    ],
    ids=["robots", "socket-guard", "broken-archive", "a-web-page"],
)
def test_an_xml_that_cannot_be_read_leaves_the_row_on_html(db, portal, needle):
    doc = _tracked_from_html(db)
    html_text = doc.baseline_text
    assert track.track_document(db, portal(), doc, move_to=XML_URL)["status"] == "unchanged"
    _assert_stayed(db, doc, html_text, needle)


def test_a_robots_refusal_of_the_XML_is_not_a_verdict_on_the_document(db):
    doc = _tracked_from_html(db)
    portal = Portal(xml_error=FetchError("robots.txt disallows https://www.gesetze-im-internet.de/gg/xml.zip"))
    track.track_document(db, portal, doc, move_to=XML_URL)
    assert _verdict_of(doc.last_status) == "unchanged"


def test_a_far_shorter_xml_reading_is_not_trusted(db):
    padding = "".join(f"<p>Absatz {i}: weiterer Text, den nur die Seite trägt.</p>" for i in range(2000))
    doc = LawDocument(jurisdiction="de", title="GG", url=HTML_URL, watched=True)
    db.add(doc)
    db.commit()
    track.track_document(db, Portal(html=_html(padding)), doc)
    html_text = doc.baseline_text

    track.track_document(db, Portal(html=_html(padding)), doc, move_to=XML_URL)

    _assert_stayed(db, doc, html_text, "far shorter than the HTML")


def test_an_xml_naming_another_act_is_not_trusted(db):
    doc = _tracked_from_html(db)
    html_text = doc.baseline_text
    other = GG.read_bytes().replace(TITLE.encode("utf-8"), "Ein ganz anderes Gesetz".encode())
    track.track_document(db, Portal(archive=_zip(other)), doc, move_to=XML_URL)
    _assert_stayed(db, doc, html_text, "names an act the stored HTML text does not")


def test_a_move_to_another_host_needs_its_own_ruling(db):
    doc = _tracked_from_html(db)
    html_text = doc.baseline_text
    portal = Portal()
    track.track_document(db, portal, doc, move_to="https://elsewhere.example/gg.xml")
    assert portal.asked == [HTML_URL], "nothing is requested from another host"
    _assert_stayed(db, doc, html_text, "another host")


def test_an_address_another_document_already_holds_is_not_taken(db):
    doc = _tracked_from_html(db)
    html_text = doc.baseline_text
    db.add(LawDocument(jurisdiction="deu", title="GG (xml)", url=XML_URL, watched=True))
    db.commit()
    portal = Portal()
    track.track_document(db, portal, doc, move_to=XML_URL)
    assert portal.asked == [HTML_URL]
    _assert_stayed(db, doc, html_text, "another tracked document already holds")


def test_a_move_that_was_undone_is_not_made_again_on_its_own(db):
    doc = _tracked_from_html(db)
    html_text = doc.baseline_text
    db.add(LawFormatChange(document_id=doc.id, from_url=HTML_URL, to_url=XML_URL, from_format="html",
                           to_format="gii", from_hash=doc.last_hash, to_hash="x" * 64))
    db.commit()
    portal = Portal()
    track.track_document(db, portal, doc, move_to=XML_URL)
    assert portal.asked == [HTML_URL]
    assert doc.url == HTML_URL and doc.baseline_text == html_text
    assert "made once and undone" in doc.last_status


# --------------------------------------------------------------------------- #
# The catalogue and the batch                                                 #
# --------------------------------------------------------------------------- #


def test_the_catalogue_names_each_move_once_and_a_contested_address_nowhere():
    catalog = {"documents": [
        {"jurisdiction": "de", "url": XML_URL, "previous_urls": [HTML_URL]},
        {"jurisdiction": "de", "url": "https://x.test/b.zip", "previous_urls": ["https://x.test/shared"]},
        {"jurisdiction": "de", "url": "https://x.test/c.zip", "previous_urls": ["https://x.test/shared"]},
        {"jurisdiction": "de", "url": "https://x.test/same", "previous_urls": ["https://x.test/same"]},
    ]}
    targets = format_move_targets(catalog)
    assert targets[("de", HTML_URL)] == XML_URL
    assert ("de", "https://x.test/shared") not in targets, "two rows claim it: which act it was is not decided here"
    assert ("de", "https://x.test/same") not in targets
    assert format_move_targets(None) == {}


def test_the_real_catalogue_moves_the_two_german_acts():
    from src.law.catalog import load_legal_catalog

    targets = format_move_targets(load_legal_catalog())
    german = {k: v for k, v in targets.items() if "gesetze-im-internet.de" in v}
    assert len(german) == 2 and all(v.endswith("/xml.zip") for v in german.values()), german


def test_the_batch_tracker_reads_the_moves_and_counts_them(db, monkeypatch):
    doc = _tracked_from_html(db)
    monkeypatch.setattr(track, "_move_targets", lambda _s: {("de", HTML_URL): XML_URL})
    tally = track.track_watched(db, Portal(), limit_documents=0)
    assert tally["moved"] == 1 and tally["documents"] == 1
    assert doc.url == XML_URL


# --------------------------------------------------------------------------- #
# Backups taken on either side of the move restore as ONE document            #
# --------------------------------------------------------------------------- #

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.5.0",
    "alembic_rev": "head",
    "manifest": None,
}
_T0 = datetime(2026, 11, 1, 12, 0, 0)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _store(s, *, moved: bool, revisions: tuple[str, ...]) -> None:
    doc = LawDocument(jurisdiction="de", title="GG", url=XML_URL if moved else HTML_URL, watched=True,
                      baseline_text="XML" if moved else "HTML", latest_text="XML" if moved else "HTML")
    s.add(doc)
    s.flush()
    for i, h in enumerate(revisions):
        s.add(LawRevision(document_id=doc.id, observed_at=_T0.replace(day=1 + i), content_hash=h, full_text=h))
    if moved:
        s.add(LawFormatChange(document_id=doc.id, changed_at=_T0, from_url=HTML_URL, to_url=XML_URL,
                              from_format="html", to_format="gii", from_hash="h-html", to_hash="h-xml",
                              from_baseline_text="HTML", from_latest_text="HTML"))
    s.commit()


def _merge(tmp_path, *, local_moved: bool, incoming_moved: bool, local_revs=("r1",), incoming_revs=("r1", "r2")):
    from src.backup.merge import merge_corpus

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        _store(s, moved=incoming_moved, revisions=incoming_revs)
    with _corpus(working)() as s:
        _store(s, moved=local_moved, revisions=local_revs)
    report = merge_corpus(staged, working, _BATCH_META)
    return _corpus(working), report


def _domain(report, name):
    results = report[0] if isinstance(report, tuple) else report  # merge_corpus returns (results, batch_id)
    got = results.get(name)
    return got if isinstance(got, dict) else (got.as_dict() if got is not None else None)


def test_a_PRE_MOVE_backup_restores_into_a_moved_store_as_one_document(tmp_path):
    Session, _report = _merge(tmp_path, local_moved=True, incoming_moved=False)
    with Session() as s:
        (doc,) = s.query(LawDocument).all()
        assert doc.url == XML_URL, "local wins: the moved row stays moved"
        assert doc.latest_text == "XML"
        hashes = sorted(r.content_hash for r in s.query(LawRevision).filter_by(document_id=doc.id))
        assert hashes == ["r1", "r2"], "the backup's own revisions join the one document"
        assert s.query(LawFormatChange).count() == 1


def test_a_MOVED_backup_restores_into_a_pre_move_store_as_one_document_and_the_move_is_REPORTED(tmp_path):
    Session, report = _merge(tmp_path, local_moved=False, incoming_moved=True)
    with Session() as s:
        (doc,) = s.query(LawDocument).all()
        assert doc.url == HTML_URL, "local wins: this copy moves on its own next poll"
        assert doc.latest_text == "HTML"
        assert sorted(r.content_hash for r in s.query(LawRevision)) == ["r1", "r2"]
        assert s.query(LawFormatChange).count() == 0, "a move this copy never made is not recorded as made"
    fc = _domain(report, "law_format_changes")
    assert fc is not None and fc["conflict"] == 1, report


def test_a_moved_backup_into_an_EMPTY_store_carries_its_history(tmp_path):
    from src.backup.merge import merge_corpus

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        _store(s, moved=True, revisions=("r1",))
    _corpus(working)
    merge_corpus(staged, working, _BATCH_META)
    with _corpus(working)() as s:
        (doc,) = s.query(LawDocument).all()
        (row,) = s.query(LawFormatChange).all()
        assert row.document_id == doc.id and (row.from_url, row.to_url) == (HTML_URL, XML_URL)
        assert row.from_baseline_text == "HTML"


def test_two_stores_that_both_moved_merge_without_a_second_history_row(tmp_path):
    Session, _report = _merge(tmp_path, local_moved=True, incoming_moved=True)
    with Session() as s:
        assert s.query(LawDocument).count() == 1
        assert s.query(LawFormatChange).count() == 1


def test_a_backup_from_before_the_table_existed_still_merges(tmp_path):
    """An older backup has no ``law_format_changes`` at all: the merge reads it as no moves."""
    import sqlite3

    from src.backup.merge import merge_corpus

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        _store(s, moved=False, revisions=("r1",))
    con = sqlite3.connect(staged)
    con.execute("DROP TABLE law_format_changes")
    con.commit()
    con.close()
    with _corpus(working)() as s:
        _store(s, moved=True, revisions=("r1",))
    merge_corpus(staged, working, _BATCH_META)
    with _corpus(working)() as s:
        assert s.query(LawDocument).count() == 1


# --------------------------------------------------------------------------- #
# Condition 1: the move is a visible entry in the document's history          #
# --------------------------------------------------------------------------- #


def test_the_move_shows_in_the_history_and_is_never_counted_as_an_amendment(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.api.ratelimit import limiter
    from src.database.session import get_db

    monkeypatch.setattr(track, "_ingest_to_corpus", lambda *a, **k: None)
    monkeypatch.setattr(track, "_record_lane", lambda *a, **k: "recorded")
    Session = _corpus(tmp_path / "live.db")
    with Session() as s:
        doc = LawDocument(jurisdiction="de", title="GG", url=HTML_URL, watched=True)
        s.add(doc)
        s.commit()
        track.track_document(s, Portal(), doc)
        assert track.track_document(s, Portal(), doc, move_to=XML_URL)["status"] == "moved"
        doc_id = doc.id

    def _db():
        d = Session()
        try:
            yield d
        finally:
            d.close()

    limiter.reset()
    app.dependency_overrides[get_db] = _db
    try:
        c = TestClient(app)
        body = c.get(f"/api/law/documents/{doc_id}").json()
        assert len(body["revisions"]) == 1, "the move is not a revision"
        (fc,) = body["format_changes"]
        assert (fc["from_url"], fc["to_url"], fc["previous_reading_kept"]) == (HTML_URL, XML_URL, True)
        page = c.get(f"/api/law/documents/{doc_id}/view").text
        assert "format change: now read from the publisher's own XML" in page
        assert "Not an amendment" in page and HTML_URL in page and XML_URL in page
        assert "The previous reading is kept with this entry." in page
    finally:
        app.dependency_overrides.pop(get_db, None)
