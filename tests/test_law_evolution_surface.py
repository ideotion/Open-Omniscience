"""0.5 row G — the law evolution surface (brief S05-07; Q905, Q908, Q914 · 3–5, Q916, Q918, Q920).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured on the synthetic jurisdiction ``ZZZ`` (tests/fixtures/law/synthetic): the
Measurement Standards Act, first captured in the version its source dates 2019-06-01,
then amended in the version dated 2024-01-01 (section 2 reworded, section 4 inserted),
plus an official translation of the first version.

The gate's closing clause is the first test: "a law's 2019 text is findable by
point-in-time search on the fixture jurisdiction". Most of the rest is negative space —
a version with no official date, a day before anything held, a document in one
language, a version with no summary, a version whose text was never stored — each of
which must come back as an honest label or a gap, never a guessed date or a neighbour's
text.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Base,
    LawDocument,
    LawRevision,
    LawRevisionSummary,
    WikiPage,
    WikiRevision,
)
from src.law.track import track_document
from src.versioned import store

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "law" / "synthetic"

#: Words only the 2019 version of section 2 contains: the amendment reworded them.
_2019_WORDS = '"comparison with a standard"'
#: Words only the 2024 version contains.
_2024_WORDS = '"published standard"'


class _Result:
    def __init__(self, body: bytes) -> None:
        self.raw_content = body
        self.content = body.decode("utf-8")
        self.content_type = "application/xml"


class _Fetcher:
    def __init__(self, name: str) -> None:
        self._body = (_FIXTURES / f"{name}.clml.xml").read_bytes()

    def fetch(self, _url, **_kw):
        return _Result(self._body)


class _TextFetcher:
    """An HTML page: no stated date, so the version is dated by observation."""

    def __init__(self, body: str) -> None:
        self._body = f"<html><body><main><p>{body}</p></main></body></html>"

    def fetch(self, _url, **_kw):
        r = _Result(self._body.encode("utf-8"))
        r.content_type = "text/html"
        return r


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
    fields = {
        "jurisdiction": "ZZZ",
        "title": "Measurement Standards Act",
        "url": "https://gazette.zzz.test/act/2019/7/data.xml",
        "official_url": "https://gazette.zzz.test/act/2019/7",
        "category": "legislation",
        "consolidated": True,
        "language": "zxx",
    } | kw
    doc = LawDocument(**fields)
    session.add(doc)
    session.commit()
    return doc


@pytest.fixture
def act(corpus, lane):
    """The Act, captured twice, and its official translation captured once."""
    with corpus() as s:
        doc = _doc(s)
        track_document(s, _Fetcher("act.v1"), doc)
        track_document(s, _Fetcher("act.v2"), doc)
        fr = _doc(
            s,
            title="Loi sur les normes de mesure",
            url="https://gazette.zzz.test/act/2019/7/fr/data.xml",
            official_url="https://gazette.zzz.test/act/2019/7/fr",
            language="zxx-fr",
        )
        track_document(s, _Fetcher("act.translation"), fr)
        revs = (
            s.query(LawRevision).filter_by(document_id=doc.id).order_by(LawRevision.id.asc()).all()
        )
        return {"doc": doc.id, "fr": fr.id, "v1": revs[0].id, "v2": revs[1].id}


# ---------------------------------------------------------------------------
# S2 — point-in-time search (Q916 = a, Q905 = a): the gate's closing clause
# ---------------------------------------------------------------------------


def test_the_2019_text_is_findable_by_point_in_time_search(corpus, act):
    """The gate row, verbatim: «a law's 2019 text is findable by point-in-time search on
    the fixture jurisdiction»."""
    from src.law.pit_search import search

    with corpus() as s:
        out = search(s, _2019_WORDS, on="2020-01-01")
    assert out["status"] == "ok"
    assert [h["version_id"] for h in out["hits"]] == [act["v1"]]
    hit = out["hits"][0]
    assert hit["valid_from"] == "2019-06-01"
    assert hit["valid_to"] == "2024-01-01"
    assert hit["dating"] == "official"
    assert hit["current"] is False
    assert "comparison with a standard" in hit["snippet"]


def test_superseded_words_are_NOT_found_on_a_day_the_amendment_was_in_force(corpus, act):
    from src.law.pit_search import search

    with corpus() as s:
        assert search(s, _2019_WORDS, on="2025-01-01")["hits"] == []
        later = search(s, _2024_WORDS, on="2025-01-01")
        assert [h["version_id"] for h in later["hits"]] == [act["v2"]]
        assert later["hits"][0]["current"] is True
        # And the amended words were not the law in 2020.
        assert search(s, _2024_WORDS, on="2020-01-01")["hits"] == []


def test_a_day_before_every_held_version_answers_not_held_never_the_oldest_text(corpus, act):
    from src.law.pit_search import search

    with corpus() as s:
        assert search(s, "measuring authority", on="2018-01-01")["hits"] == []
        # Without a date, every held version containing the words is a hit.
        both = search(s, "measuring authority")
        assert {h["version_id"] for h in both["hits"]} >= {act["v1"], act["v2"]}


def test_a_version_with_no_official_date_is_labelled_dated_by_observation(corpus, lane):
    """Q905 = a's second clause: dated by observation "and labelled so"."""
    from src.law.pit_search import search

    with corpus() as s:
        doc = _doc(
            s,
            jurisdiction="ZZZ",
            title="Plain Notice",
            url="https://gazette.zzz.test/n",
            language="zxx",
        )
        track_document(
            s,
            _TextFetcher(
                "A notice about lighthouse keepers and the lamps they keep lit at night. " * 8
            ),
            doc,
        )
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        out = search(s, "lighthouse", on=today)
    assert len(out["hits"]) == 1
    hit = out["hits"][0]
    assert hit["dating"] == "observed"
    assert hit["valid_from"] == today  # the observation day, and it SAYS so
    assert hit["dating"] != "official"


def test_the_index_reports_versions_whose_text_was_never_stored(corpus, act):
    from src.law.pit_search import search

    with corpus() as s:
        s.add(
            LawRevision(
                document_id=act["doc"],
                observed_at=datetime(2025, 5, 1, tzinfo=UTC),
                content_hash="legacy",
                full_text=None,
            )
        )
        s.commit()
        out = search(s, "measuring authority")
    assert out["coverage"]["versions_without_text"] == 1


def test_query_syntax_is_not_interpreted_as_fts_operators():
    from src.law.pit_search import match_expression

    assert match_expression("NOT (standard") == '"NOT" "(standard"'
    assert match_expression('"a phrase" word*') == '"a phrase" "word"*'
    assert match_expression("   ") is None


def test_search_finds_the_law_through_EITHER_language_version(corpus, act):
    """Q908 = a: cross-language search finds it through any version."""
    from src.law.pit_search import search

    with corpus() as s:
        fr = search(s, "normes", on="2020-01-01")
    assert [h["document_id"] for h in fr["hits"]] == [act["fr"]]
    assert {x["id"] for x in fr["hits"][0]["other_languages"]} == {act["doc"]}


# ---------------------------------------------------------------------------
# S1 — one version reader for law and Wikipedia (Q918 + its note)
# ---------------------------------------------------------------------------


def _wiki(s) -> int:
    page = WikiPage(wiki="en", title="Measurement")
    s.add(page)
    s.commit()
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    s.add_all(
        [
            WikiRevision(
                page_id=page.id, revid=10, timestamp=t0, full_text="Lead.\n== History ==\nOld line."
            ),
            WikiRevision(
                page_id=page.id,
                revid=11,
                timestamp=t0 + timedelta(days=1),
                full_text="Lead.\n== History ==\nNew line.\n== Units ==\nMetre.",
            ),
            WikiRevision(
                page_id=page.id, revid=12, timestamp=t0 + timedelta(days=2), full_text=None
            ),
        ]
    )
    s.commit()
    return page.id


def test_law_and_wiki_readers_return_ONE_payload_shape(corpus, act):
    """The note is a requirement: "homogenous with ... wikipedia articles". Same keys at
    the document level and on every version row, so one component draws both."""
    from src.law.versions import reader_payload as law_payload
    from src.wiki.versions import reader_payload as wiki_payload

    with corpus() as s:
        law = law_payload(s, s.get(LawDocument, act["doc"]))
        wiki = wiki_payload(s, s.get(WikiPage, _wiki(s)))
    shared = {
        "kind",
        "id",
        "title",
        "language",
        "versions",
        "total",
        "permalink",
        "identifier",
        "licence",
        "provenance",
        "languages",
        "parts_name",
        "method",
        "caveat",
    }
    assert shared <= set(law) and shared <= set(wiki)
    assert set(law["versions"][0]) == set(wiki["versions"][0])
    # Newest first in both, and 'until' is the next held version.
    assert law["versions"][0]["valid_from"] == "2024-01-01"
    assert law["versions"][1]["valid_to"] == "2024-01-01"
    assert wiki["versions"][0]["dating"] == "edit"
    assert wiki["licence"]["name"] == "CC BY-SA 4.0"


def test_the_comparison_names_the_provisions_that_changed(corpus, act):
    from src.law.versions import compare_payload

    with corpus() as s:
        out = compare_payload(s, s.get(LawDocument, act["doc"]), act["v1"], act["v2"])
    assert out["method"] == "line"
    status = {p["address"]: p["status"] for p in out["parts"]}
    assert status["Part 1 Preliminary/2"] == "changed"
    assert status["Part 2 Duties/4"] == "added"
    assert status["Part 1 Preliminary/1"] == "unchanged"
    ops = {r["op"] for r in out["rows"]}
    assert "chg" in ops or {"del", "ins"} <= ops


def test_a_scoped_comparison_shows_only_that_provision(corpus, act):
    from src.law.versions import compare_payload

    with corpus() as s:
        out = compare_payload(
            s, s.get(LawDocument, act["doc"]), act["v1"], act["v2"], part="Part 2 Duties/4"
        )
    assert [r["op"] for r in out["rows"] if r["op"] != "eq"] == ["ins"]


def test_a_version_without_stored_text_refuses_by_name(corpus, act):
    from src.wiki.versions import compare_payload

    with corpus() as s:
        pid = _wiki(s)
        ids = [
            f"t{r.id}"
            for r in s.query(WikiRevision).filter_by(page_id=pid).order_by(WikiRevision.revid)
        ]
        out = compare_payload(s, s.get(WikiPage, pid), ids[1], ids[2])
    assert out["method"] == "text-not-held"
    assert out["missing"] == [ids[2]]
    assert out["rows"] == []


def test_wiki_sections_are_the_part_navigation(corpus, act):
    from src.wiki.versions import compare_payload

    with corpus() as s:
        pid = _wiki(s)
        ids = [
            f"t{r.id}"
            for r in s.query(WikiRevision).filter_by(page_id=pid).order_by(WikiRevision.revid)
        ]
        out = compare_payload(s, s.get(WikiPage, pid), ids[0], ids[1])
    status = {p["address"]: p["status"] for p in out["parts"]}
    assert status == {"(lead)": "unchanged", "History": "changed", "Units": "added"}


@pytest.fixture
def wiki_lane(tmp_path, monkeypatch):
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    try:
        store.create_lane("wiki")
        yield tmp_path
    finally:
        store.dispose_all()


def _lane_versions(title: str = "Measurement") -> None:
    """The lane's baseline (revid 11, which the tracker ALSO holds, without text here)
    and one later lane revision (revid 13) for the same page."""
    from src.versioned.adapters.wiki import external_id_for
    from src.versioned.models import VersionedBaseline, VersionedEntity, VersionedRevision

    t0 = datetime(2026, 1, 2, tzinfo=UTC)
    with store.lane_session("wiki") as lane:
        ent = VersionedEntity(external_id=external_id_for("en", title), title=title, language="en")
        lane.add(ent)
        lane.flush()
        lane.add(
            VersionedBaseline(
                entity_id=ent.id,
                revision_ref="11",
                revised_at=t0,
                content_hash="h11",
                content="Lead.\n== History ==\nNew line.\n== Units ==\nMetre.",
            )
        )
        lane.add(
            VersionedRevision(
                entity_id=ent.id,
                revision_ref="13",
                revised_at=t0 + timedelta(days=3),
                content_hash="h13",
                content="Lead.\n== History ==\nNew line.\n== Units ==\nMetre and second.",
            )
        )


def test_the_wiki_reader_lists_the_lanes_versions_beside_the_trackers(corpus, wiki_lane):
    """Since Q1020 the scheduler's captures land in the Wikipedia lane, not in
    wiki_revisions: a reader of the tracker's store alone would show a lane-running
    instance only what "Track now" caught. One edit held in both is listed ONCE."""
    from src.wiki.versions import compare_payload, reader_payload

    _lane_versions()
    with corpus() as s:
        pid = _wiki(s)
        # The tracker's copy of revid 11 loses its text, so the lane's copy must win.
        s.query(WikiRevision).filter_by(page_id=pid, revid=11).update({"full_text": None})
        s.commit()
        page = s.get(WikiPage, pid)
        out = reader_payload(s, page)
        ids = [v["id"] for v in out["versions"]]
        assert ids[0].startswith("l") and ids[1].startswith("t")  # revid 13 (lane) newest, then 12
        assert out["total"] == 4  # revids 10, 11, 12, 13: 11 once, not twice
        assert out["stores"] == ["lane", "tracker"]
        eleven = next(v for v in out["versions"] if v["id"].startswith("b"))
        assert eleven["has_text"] and eleven["dating"] == "edit"
        cmp = compare_payload(s, page, eleven["id"], ids[0])
    assert cmp["method"] == "line"
    assert {p["address"]: p["status"] for p in cmp["parts"]}["Units"] == "changed"


def test_the_wiki_reader_without_a_lane_reads_the_tracker_alone(corpus, tmp_path, monkeypatch):
    from src.wiki.versions import reader_payload

    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "empty"))
    with corpus() as s:
        out = reader_payload(s, s.get(WikiPage, _wiki(s)))
    assert out["stores"] == ["tracker"] and out["total"] == 3


def test_a_version_of_another_document_is_a_404_never_a_neighbour(corpus, act):
    from src.law.versions import compare_payload

    with corpus() as s:
        fr_rev = s.query(LawRevision).filter_by(document_id=act["fr"]).first().id
        with pytest.raises(LookupError):
            compare_payload(s, s.get(LawDocument, act["doc"]), act["v1"], fr_rev)


# ---------------------------------------------------------------------------
# S3 — identity, permalink, the language switch (Q908, Q918)
# ---------------------------------------------------------------------------


def test_a_two_language_document_offers_its_other_version_locally(corpus, act):
    from src.law.versions import reader_payload

    with corpus() as s:
        out = reader_payload(s, s.get(LawDocument, act["doc"]))
    langs = {x["language"]: x for x in out["languages"]}
    assert set(langs) == {"zxx", "zxx-fr"}
    assert langs["zxx"]["current"] is True
    assert langs["zxx-fr"]["id"] == act["fr"]
    assert out["identifier"]["scheme"] == "act-number"
    # act-number has no resolver: no external permalink is invented for it.
    assert out["identifier"]["url"] is None


def test_a_one_language_document_offers_no_switch(corpus, lane):
    from src.law.versions import reader_payload

    with corpus() as s:
        doc = _doc(s)
        track_document(s, _Fetcher("act.v1"), doc)
        out = reader_payload(s, doc)
    assert len(out["languages"]) <= 1


def test_eli_and_celex_permalinks_come_from_the_identifier_by_rule():
    from src.law.versions import external_permalink

    assert external_permalink("celex", "32016r0679") == (
        "https://eur-lex.europa.eu/legal-content/AUTO/?uri=CELEX:32016R0679"
    )
    assert external_permalink("eli", "https://www.legislation.gov.uk/eli/ukpga/2018/12") == (
        "https://www.legislation.gov.uk/eli/ukpga/2018/12"
    )
    assert external_permalink("eli", "ukpga/2018/12") is None  # not a URI: no guess
    assert external_permalink("local", "anything") is None
    assert external_permalink("celex", "x'; drop") is None


# ---------------------------------------------------------------------------
# S4 — AI summaries only, labelled (Q920)
# ---------------------------------------------------------------------------


def test_a_summary_carries_the_ai_label_and_a_missing_one_is_absent(corpus, act):
    from src.law.versions import AI_LABEL, reader_payload

    with corpus() as s:
        s.add(
            LawRevisionSummary(
                revision_id=act["v2"],
                summary="Section 2 now names a published standard.",
                model="m",
            )
        )
        s.commit()
        out = reader_payload(s, s.get(LawDocument, act["doc"]))
    by_id = {v["id"]: v for v in out["versions"]}
    assert by_id[act["v2"]]["summary"]["label"] == AI_LABEL == "≈ AI-derived · unreliable"
    assert by_id[act["v1"]]["summary"] is None
    # Dates never come from the model: the version's date is its source's.
    assert by_id[act["v2"]]["valid_from"] == "2024-01-01"


# ---------------------------------------------------------------------------
# S5 — analytics 3–5 (Q914)
# ---------------------------------------------------------------------------


def test_topic_comparison_counts_and_never_divides(corpus, act):
    from src.law.analytics import topic_by_jurisdiction

    with corpus() as s:
        out = topic_by_jurisdiction(s, _2019_WORDS)
    assert out["rows"] == [
        {
            "jurisdiction": "zzz",
            "versions_matching": 1,
            "documents_matching": 1,
            "documents_current_matching": 0,  # the amendment removed the words
            "tracked_documents": 2,
        }
    ]
    assert "ratio" in out["method"]


def test_the_amendment_map_states_its_vintage_and_keeps_non_countries_off_it(corpus, act):
    from src.law.analytics import amendment_map

    with corpus() as s:
        s.add(LawDocument(jurisdiction="fr", title="Code", url="https://x.test/fr"))
        s.add(LawDocument(jurisdiction="eu", title="Reg", url="https://x.test/eu"))
        s.commit()
        fr = s.query(LawDocument).filter_by(jurisdiction="fr").one()
        s.add(
            LawRevision(
                document_id=fr.id,
                observed_at=datetime.now(UTC),
                content_hash="h",
                diff_basis="previous",
            )
        )
        s.add(
            LawRevision(
                document_id=fr.id,
                observed_at=datetime.now(UTC),
                content_hash="h0",
                diff_basis="first",
            )
        )
        s.commit()
        out = amendment_map(s, days=30)
    assert out["values"] == {"fr": 1}
    assert out["excluded_first_captures"] >= 1
    assert out["window_from"] and out["window_to"] and out["newest_capture"]
    off = {r["jurisdiction"] for r in out["not_on_the_map"]}
    assert {"eu", "zzz"} <= off


def test_what_changed_this_week_lists_followed_documents_only(corpus, act):
    from src.law.analytics import changed_this_week

    with corpus() as s:
        out = changed_this_week(s, days=7)
        assert [i["document_id"] for i in out["items"]] == [act["doc"]]
        s.get(LawDocument, act["doc"]).watched = False
        s.commit()
        assert changed_this_week(s, days=7)["items"] == []


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


def test_the_routes_serve_the_same_payloads(corpus, act):
    from src.api.main import app
    from src.api.ratelimit import limiter
    from src.database.session import get_db

    def _db():
        d = corpus()
        try:
            yield d
        finally:
            d.close()

    limiter.reset()
    app.dependency_overrides[get_db] = _db
    try:
        c = TestClient(app)
        v = c.get(f"/api/law/documents/{act['doc']}/versions")
        assert v.status_code == 200 and v.json()["kind"] == "law"
        cmp_ = c.get(
            f"/api/law/documents/{act['doc']}/compare", params={"from": act["v1"], "to": act["v2"]}
        )
        assert cmp_.status_code == 200 and cmp_.json()["parts"]
        pit = c.get("/api/law/versions/search", params={"q": _2019_WORDS, "on": "2020-01-01"})
        assert [h["version_id"] for h in pit.json()["hits"]] == [act["v1"]]
        assert (
            c.get("/api/law/versions/search", params={"q": "x", "on": "2020-1-1"}).status_code
            == 422
        )
        assert c.get("/api/law/amendment-map").json()["window_to"]
        assert c.get("/api/law/this-week").status_code == 200
        assert c.get("/api/law/topics", params={"q": "standard"}).json()["rows"]
        assert (
            c.get(
                f"/api/law/documents/{act['doc']}/compare", params={"from": 99999, "to": act["v2"]}
            ).status_code
            == 404
        )
        with corpus() as s:
            pid = _wiki(s)
            ids = [
                f"t{r.id}"
                for r in s.query(WikiRevision).filter_by(page_id=pid).order_by(WikiRevision.revid)
            ]
        wv = c.get(f"/api/wiki/pages/{pid}/versions").json()
        assert {v["id"] for v in wv["versions"]} == set(ids)
        assert (
            c.get(f"/api/wiki/pages/{pid}/compare", params={"from": ids[0], "to": ids[1]}).json()[
                "method"
            ]
            == "line"
        )
        assert (
            c.get(f"/api/wiki/pages/{pid}/compare", params={"from": "x1", "to": ids[1]}).status_code
            == 422
        )
        assert (
            c.get(
                f"/api/wiki/pages/{pid}/compare", params={"from": "t99999", "to": ids[1]}
            ).status_code
            == 404
        )
        reader = c.get(f"/api/law/documents/{act['doc']}/view").text
        assert "ooversions.js" in reader and 'data-ov-base="/api/law/documents/' in reader
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_every_line_the_payloads_send_to_the_screen_is_keyed_in_all_twelve_locales(corpus, act):
    """The component translates ``method``, ``caveat`` and ``parts_reason`` with t() on a
    VARIABLE, which no i18n gate can see: a reworded payload line silently shows in
    English in eleven languages. So the lines the server sends are checked here."""
    import json

    from src.law import versions as law_versions
    from src.law.analytics import amendment_map, changed_this_week, topic_by_jurisdiction
    from src.law.pit_search import search
    from src.wiki.versions import reader_payload as wiki_payload

    with corpus() as s:
        doc = s.get(LawDocument, act["doc"])
        payloads = [
            law_versions.reader_payload(s, doc),
            wiki_payload(s, s.get(WikiPage, _wiki(s))),
            search(s, _2019_WORDS),
            topic_by_jurisdiction(s, _2019_WORDS),
            amendment_map(s, days=30),
            changed_this_week(s, days=7),
        ]
    lines = {p[k] for p in payloads for k in ("method", "caveat") if p.get(k)}
    lines.add(
        "No provisions were parsed for one of these versions (its text did not arrive "
        "in a structured format), so it can only be compared as a whole."
    )
    assert "No provisions were parsed" in Path(law_versions.__file__).read_text(encoding="utf-8")
    locales = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    for path in sorted(locales.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = sorted(line[:60] for line in lines if not data.get(line))
        assert not missing, f"{path.name} lacks {missing}"
