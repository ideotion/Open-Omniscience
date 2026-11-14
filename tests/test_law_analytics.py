"""Law analytics 1–2 (Q914 = a, brief S04-10 S4) — counts, with their method and caveat.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The two analytics this cycle ships, measured on the `ZZZ` synthetic jurisdiction. What
these guards are really aimed at is the ONE way this surface can lie without erroring:
"amendment velocity" reads like a property of a legislature and is a property of what
this install polls. So the tests below check the caveat and the missing division as
carefully as they check the counts.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision
from src.law.analytics import SPARSE_BAR_MAX, amendment_velocity, provision_timeline
from src.law.track import track_document
from src.versioned import store

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "law" / "synthetic"


class _Result:
    def __init__(self, body: bytes) -> None:
        self.raw_content = body
        self.content = body.decode("utf-8")
        self.content_type = "application/xml"


class _ScriptedFetcher:
    def __init__(self, names: list[str]) -> None:
        self._bodies = [(_FIXTURES / f"{n}.clml.xml").read_bytes() for n in names]
        self.calls = 0

    def fetch(self, _url, **_kw):
        body = self._bodies[min(self.calls, len(self._bodies) - 1)]
        self.calls += 1
        return _Result(body)


@pytest.fixture
def corpus(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'corpus.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, future=True)
    engine.dispose()


@pytest.fixture
def lane(tmp_path, monkeypatch):
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    try:
        store.create_lane("law")
        yield tmp_path
    finally:
        store.dispose_all()


def _doc(session, **kw) -> LawDocument:
    doc = LawDocument(
        jurisdiction="ZZZ",
        title="Measurement Standards Act",
        url="https://gazette.zzz.test/act/2019/7/data.xml",
        official_url="https://gazette.zzz.test/act/2019/7",
        category="legislation",
        consolidated=True,
        language="zxx",
        **kw,
    )
    session.add(doc)
    session.commit()
    return doc


# ---------------------------------------------------------------------------
# Analytic 1 — the per-provision timeline
# ---------------------------------------------------------------------------


def test_the_timeline_names_the_ONE_provision_that_changed_and_the_ONE_that_appeared(corpus, lane):
    """The whole point of per-provision storage.

    The amendment fixture rewords section 2 and inserts section 4, leaving sections 1 and
    3 byte-identical. A whole-document byte delta says "the Act moved by N bytes"; this
    says which sections, which is the difference between an analytic and a number.
    """
    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        track_document(session, _ScriptedFetcher(["act.v2"]), doc)
        key = doc.lane_key
        order = [
            k
            for (k,) in session.query(LawRevision.lane_key)
            .filter(LawRevision.document_id == doc.id)
            .order_by(LawRevision.observed_at.asc(), LawRevision.id.asc())
            .all()
        ]

    with store.lane_session("law") as ls:
        timeline = provision_timeline(ls, key, revision_order=order)

    changes = {(e["address"], e["change"]) for e in timeline["events"]}
    assert ("Part 1 Preliminary/2", "changed") in changes
    assert ("Part 2 Duties/4", "added") in changes
    # And the two that did NOT change produce no event at all: a timeline of everything
    # that did not happen is not a timeline.
    assert not [e for e in timeline["events"] if e["address"] == "Part 1 Preliminary/1"]
    assert not [e for e in timeline["events"] if e["address"] == "Part 2 Duties/3"]
    assert timeline["versions_compared"] == 1
    assert timeline["provisions_seen"] == 4
    assert timeline["n"] == len(timeline["events"]) == 2


def test_a_version_the_caller_could_not_order_is_REPORTED_never_appended(corpus, lane):
    """Appending it would place a version in an order nobody measured, and a timeline's
    entire value is the order."""
    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        track_document(session, _ScriptedFetcher(["act.v2"]), doc)
        key = doc.lane_key
        first = (
            session.query(LawRevision.lane_key)
            .filter(LawRevision.document_id == doc.id)
            .order_by(LawRevision.id.asc())
            .first()
        )[0]

    with store.lane_session("law") as ls:
        timeline = provision_timeline(ls, key, revision_order=[first])

    assert timeline["versions_ordered"] == 1
    assert timeline["versions_compared"] == 0
    assert len(timeline["versions_without_a_known_position"]) == 1
    assert timeline["events"] == [], "nothing is compared against a version with no position"


def test_the_timeline_carries_its_method_its_caveat_and_its_n(corpus, lane):
    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        key = doc.lane_key
    with store.lane_session("law") as ls:
        timeline = provision_timeline(ls, key, revision_order=[])
    assert timeline["method"].strip() and timeline["caveat"].strip()
    assert "not the amendments the legislature made" in timeline["caveat"]
    assert "Provision names follow each language" in timeline["caveat"], (
        "a translation's provisions carry its own container names, so cross-language "
        "addresses do not line up — a reader comparing them would be comparing nothing"
    )
    assert isinstance(timeline["n"], int)
    assert timeline["sparse"] is True


# ---------------------------------------------------------------------------
# Analytic 2 — amendment velocity, and the division it refuses to do
# ---------------------------------------------------------------------------


def test_velocity_counts_versions_per_jurisdiction_and_EXCLUDES_the_first_sighting(corpus, lane):
    """A baseline is a first sighting, not a change. Counting it would give every newly
    tracked jurisdiction a spike on the day the operator added it."""
    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        track_document(session, _ScriptedFetcher(["act.v2"]), doc)
        payload = amendment_velocity(session)

    assert payload["excluded_baseline_captures"] == 1
    zzz = next(s for s in payload["series"] if s["jurisdiction"] == "zzz")
    assert sum(p["count"] for p in zzz["points"]) == 1, "one amendment, not two captures"
    assert zzz["tracked_documents"] == 1


def test_velocity_gives_the_DENOMINATOR_and_refuses_to_divide_by_it(corpus, lane):
    """Dividing would produce a figure that reads as a legislative rate and is a
    statement about this operator's watch list."""
    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        track_document(session, _ScriptedFetcher(["act.v2"]), doc)
        payload = amendment_velocity(session)

    zzz = next(s for s in payload["series"] if s["jurisdiction"] == "zzz")
    assert "tracked_documents" in zzz
    for forbidden in ("rate", "per_document", "velocity_per", "normalised", "normalized"):
        assert forbidden not in zzz, f"no divided figure: {forbidden}"
    assert "not on a legislature" in payload["caveat"] and payload["caveat_short"]


def test_a_sparse_series_is_marked_for_BARS_at_the_shared_threshold(corpus, lane):
    """Invariant #16, app-wide: n < 10 datapoints renders as bars with n shown, never as
    a line through points nobody measured."""
    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        track_document(session, _ScriptedFetcher(["act.v2"]), doc)
        payload = amendment_velocity(session)
    zzz = next(s for s in payload["series"] if s["jurisdiction"] == "zzz")
    assert zzz["n"] < SPARSE_BAR_MAX
    assert zzz["sparse"] is True


def test_the_python_sparse_threshold_MATCHES_the_renderer_that_owns_it():
    """The value lives in JavaScript (`_SPARSE_BAR_MAX` in app-markets.js, shared by
    ooChart and dashChartSvg). This is a declared copy, so it is pinned equal — an
    earlier draft imported a Python name that does not exist and silently fell back."""
    import re

    js = (Path(__file__).resolve().parent.parent / "src" / "static" / "app-markets.js").read_text(
        encoding="utf-8"
    )
    match = re.search(r"_SPARSE_BAR_MAX\s*=\s*(\d+)", js)
    assert match, "the renderer's constant moved; the law analytics copy is now unpinned"
    assert int(match.group(1)) == SPARSE_BAR_MAX


def test_an_empty_corpus_produces_an_empty_series_not_a_zero(corpus, lane):
    """A jurisdiction with no captures has no row. A fabricated zero would read as
    "this legislature amended nothing", which nobody measured."""
    with corpus() as session:
        payload = amendment_velocity(session)
    assert payload["series"] == []
    assert payload["n"] == 0


# ---------------------------------------------------------------------------
# The endpoints
# ---------------------------------------------------------------------------


def _client(maker):
    from src.api.main import app
    from src.database.session import get_db

    def _db():
        d = maker()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app


def test_the_timeline_endpoint_refuses_by_name_for_a_document_with_no_model_row(corpus, lane):
    from fastapi.testclient import TestClient

    with corpus() as session:
        doc = _doc(session)
        doc_id = doc.id  # never tracked, so no lane key

    app = _client(corpus)
    try:
        with TestClient(app) as c:
            payload = c.get(f"/api/law/documents/{doc_id}/provision-timeline").json()
    finally:
        app.dependency_overrides.clear()
    assert payload["available"] is False
    assert "no law-model row" in payload["reason"]


def test_the_velocity_endpoint_rejects_a_period_it_cannot_bucket(corpus, lane):
    from fastapi.testclient import TestClient

    app = _client(corpus)
    try:
        with TestClient(app) as c:
            assert c.get("/api/law/amendment-velocity?period=fortnight").status_code == 422
            assert c.get("/api/law/amendment-velocity?period=year").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_the_timeline_endpoint_returns_the_events_for_a_tracked_document(corpus, lane):
    from fastapi.testclient import TestClient

    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        track_document(session, _ScriptedFetcher(["act.v2"]), doc)
        doc_id = doc.id

    app = _client(corpus)
    try:
        with TestClient(app) as c:
            payload = c.get(f"/api/law/documents/{doc_id}/provision-timeline").json()
    finally:
        app.dependency_overrides.clear()
    assert payload["available"] is True
    assert {(e["address"], e["change"]) for e in payload["events"]} == {
        ("Part 1 Preliminary/2", "changed"),
        ("Part 2 Duties/4", "added"),
    }

    # And the dates the events hang off come from the document's own history, oldest
    # first — not from the order the lane rows were written.
    assert payload["versions_compared"] == 1


_T0 = datetime(2026, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# The reader: where the timeline is reachable from a button-free route
# ---------------------------------------------------------------------------


def test_the_reader_carries_the_provision_fold_with_its_short_caveat_in_the_summary(corpus, lane):
    """The finding and the short caveat sit in the closed fold's summary; the per-version
    list links each date to that stored version; method and caveat are inside the fold."""
    from fastapi.testclient import TestClient

    from src.law.analytics import CAVEAT_SHORT_TIMELINE

    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        track_document(session, _ScriptedFetcher(["act.v2"]), doc)
        doc_id = doc.id

    app = _client(corpus)
    try:
        with TestClient(app) as c:
            page = c.get(f"/api/law/documents/{doc_id}/view").text
            payload = c.get(f"/api/law/documents/{doc_id}/provision-timeline").json()
    finally:
        app.dependency_overrides.clear()
    start = page.index("<details class='versions provisions'>")
    fold = page[start : page.index("</details>", start)]
    summary = fold[: fold.index("</summary>")]
    assert "Provisions that changed" in summary and "<span class='count'>2</span>" in summary
    assert html.escape(CAVEAT_SHORT_TIMELINE) in summary, "the short caveat is visible with the fold closed"
    assert "<code>Part 1 Preliminary/2</code> <span>changed</span>" in fold
    assert "<code>Part 2 Duties/4</code> <span>added</span>" in fold
    assert "?version=" in fold
    assert "not the amendments the legislature made" in fold.split("</summary>", 1)[1]
    # The payload names every version it placed, oldest first, with its own revision id.
    stamps = [v["observed_at"] for v in payload["versions"]]
    assert len(stamps) == 2 and all(isinstance(s, str) for s in stamps), stamps
    assert stamps == sorted(stamps)
    assert all(isinstance(v["revision_id"], int) for v in payload["versions"])


def test_the_reader_fold_says_why_it_is_empty_for_an_untracked_document(corpus, lane):
    from fastapi.testclient import TestClient

    with corpus() as session:
        doc_id = _doc(session).id

    app = _client(corpus)
    try:
        with TestClient(app) as c:
            page = c.get(f"/api/law/documents/{doc_id}/view").text
    finally:
        app.dependency_overrides.clear()
    start = page.index("<details class='versions provisions'>")
    fold = page[start : page.index("</details>", start)]
    assert "<span class='count'>—</span>" in fold, "no fabricated zero"
    assert "no law-model row" in fold


def test_the_reader_count_is_DISTINCT_provisions_not_change_events(corpus, lane):
    """v1 -> v2 -> v3 changes section 2 twice and adds section 4 once: three events over
    two provisions. The label says provisions, so the count is 2."""
    from fastapi.testclient import TestClient

    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        track_document(session, _ScriptedFetcher(["act.v2"]), doc)
        # A third version rewords section 2 again; nothing else moves.
        v3 = _ScriptedFetcher(["act.v2"])
        v3._bodies = [v3._bodies[0].replace(b"a published standard", b"a published national standard")]
        track_document(session, v3, doc)
        doc_id = doc.id

    app = _client(corpus)
    try:
        with TestClient(app) as c:
            page = c.get(f"/api/law/documents/{doc_id}/view").text
            payload = c.get(f"/api/law/documents/{doc_id}/provision-timeline").json()
    finally:
        app.dependency_overrides.clear()
    assert payload["n"] == 3 and len(payload["changes_per_provision"]) == 2, payload
    start = page.index("<details class='versions provisions'>")
    assert "<span class='count'>2</span>" in page[start : page.index("</summary>", start)]
