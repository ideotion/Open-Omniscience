"""S05-03 — the entity spine: the ladder by QID, the Wikidata item cache, the Place entity.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row C of the 0.5 gate closes when (1) a press article's mentioned place resolves to a Place
that a wiki page with the same QID also resolves to, (2) the gazetteer carries its vintage,
and (3) the Wikidata fetch is proven consented, spaced and refused under the kill switch by
a fixture. (1) and (3) are proven here on the synthetic fixtures; (2)'s artifact is the
operator's networked build (Q805), and its SHAPE -- the vintage read and shown -- is proven
on the synthetic gazetteer.

NO TEST IN THIS FILE OPENS A SOCKET. The getter is injected, and the production path is
exercised only with the kill switch engaged and the airplane socket guard armed, counting
name resolutions -- which must stay at zero.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.analytics import equivalence
from src.analytics.ring_loader import RateGate
from src.catalog import cities
from src.database.models import (
    Article,
    ArticleEntity,
    ArticleMentionedPlace,
    Base,
    Place,
    Source,
    WikidataItem,
)
from src.entities import items as IT
from src.entities import places as PL
from src.entities import spine as SP
from src.entities.wikidata_items import BATCH_MAX, CLAIMS, batches, entities_url, parse_entities
from src.ingest import activate_kill_switch, clear_kill_switch

FIXTURE = Path(__file__).parent / "fixtures" / "places" / "gazetteer.synthetic.yml"
ZEDPORT = "node/9000000001"
ZEDPORT_QID = "Q999999001"


# --------------------------------------------------------------------------- #
#  fixtures
# --------------------------------------------------------------------------- #


def _clear_gazetteer_caches() -> None:
    from src.timemap import locextract

    cities.cached_index.cache_clear()
    cities.gazetteer_meta.cache_clear()
    locextract._patterns.cache_clear()
    locextract._dispatch.cache_clear()


@pytest.fixture
def gazetteer(monkeypatch):
    """The synthetic gazetteer as THE gazetteer, every cache that holds one cleared."""
    monkeypatch.setattr(cities, "GAZETTEER_PATH", FIXTURE)
    _clear_gazetteer_caches()
    yield
    monkeypatch.undo()
    _clear_gazetteer_caches()


@pytest.fixture
def db():
    eng = create_engine("sqlite://")

    @event.listens_for(eng, "connect")
    def _fk(dbapi_con, _rec):  # pragma: no cover - sqlite pragma plumbing
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def _article(db, text: str, url: str = "https://zz.example/a1") -> Article:
    src = db.query(Source).filter_by(domain="zz.example").first()
    if src is None:
        src = Source(name="ZZ Press", domain="zz.example", rss_url=None)
        db.add(src)
        db.flush()
    import hashlib

    art = Article(url=url, canonical_url=url, source_id=src.id, title="t", content=text,
                  language="en", hash=hashlib.sha256(text.encode()).hexdigest())
    db.add(art)
    db.commit()
    return art


def _mention(db, art, name, country, kind="city", n=1):
    db.add(ArticleMentionedPlace(article_id=art.id, name=name, country=country, kind=kind, mentions=n))
    db.commit()


# --------------------------------------------------------------------------- #
#  S2 — the pure item core
# --------------------------------------------------------------------------- #


def test_one_request_carries_a_batch_and_never_more_than_the_api_allows():
    qids = [f"Q{i}" for i in range(1, 121)]
    bs = batches(qids)
    assert [len(b) for b in bs] == [50, 50, 20]
    url = entities_url(bs[0])
    parts = urlsplit(url)
    assert parts.scheme == "https" and parts.hostname == "www.wikidata.org"
    assert "action=wbgetentities" in parts.query
    assert "props=labels%7Cdescriptions%7Cclaims" in url
    with pytest.raises(ValueError):
        entities_url([f"Q{i}" for i in range(1, BATCH_MAX + 2)])


def test_invalid_and_duplicate_ids_are_dropped_never_repaired():
    assert batches(["Q1", "q2", "Q1", "P31", "Q0", "Q03", "Q42 "]) == [["Q1"]]


def _entity(qid, labels=None, descs=None, claims=None, rev=7):
    return {
        "id": qid, "lastrevid": rev,
        "labels": {k: {"language": k, "value": v} for k, v in (labels or {}).items()},
        "descriptions": {k: {"language": k, "value": v} for k, v in (descs or {}).items()},
        "claims": claims or {},
    }


def _snak_item(q):
    return {"mainsnak": {"datavalue": {"value": {"id": q}}}, "rank": "normal"}


def test_only_the_four_named_claims_are_kept():
    claims = {
        "P31": [_snak_item("Q3957"), {"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}, "rank": "deprecated"}],
        "P17": [_snak_item("Q999999900")],
        "P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 0.15, "longitude": 0.15,
                                                       "globe": "http://www.wikidata.org/entity/Q2"}}}}],
        "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+1900-00-00T00:00:00Z", "precision": 9}}}}],
        "P1082": [{"mainsnak": {"datavalue": {"value": {"amount": "+120000"}}}}],
        "P856": [{"mainsnak": {"datavalue": {"value": "https://zz.example"}}}],
    }
    payload = {"entities": {ZEDPORT_QID: _entity(ZEDPORT_QID, {"en": "Zedport"}, {"en": "a town"}, claims)}}
    [it] = parse_entities(payload, [ZEDPORT_QID])
    assert set(it.claims) <= set(CLAIMS)
    assert it.claims["P31"] == ["Q3957"]  # the deprecated statement is not kept
    assert it.claims["P625"] == [{"lat": 0.15, "lon": 0.15}]
    # A year-precision inception stays a year: no invented month or day.
    assert it.claims["P571"] == [{"time": "+1900-00-00T00:00:00Z", "precision": 9}]


def test_a_coordinate_on_another_globe_is_not_a_place_on_this_map():
    claims = {"P625": [{"mainsnak": {"datavalue": {"value": {
        "latitude": 1.0, "longitude": 2.0, "globe": "http://www.wikidata.org/entity/Q405"}}}}]}
    [it] = parse_entities({"entities": {"Q7": _entity("Q7", claims=claims)}}, ["Q7"])
    assert "P625" not in it.claims


def test_missing_and_redirected_items_are_recorded_as_what_wikidata_said():
    payload = {"entities": {
        "Q8": {"id": "Q8", "missing": ""},
        "Q10": dict(_entity("Q10", {"en": "Target"}), redirects={"from": "Q9", "to": "Q10"}),
    }}
    got = {p.qid: p for p in parse_entities(payload, ["Q8", "Q9", "Q11"])}
    assert got["Q8"].status == "missing"
    assert got["Q9"].status == "ok" and got["Q9"].resolved_qid == "Q10"
    assert "Q11" not in got  # not mentioned in the answer: never invented


# --------------------------------------------------------------------------- #
#  S2 — the fetch: consented, spaced, refused
# --------------------------------------------------------------------------- #


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def _factory(db):
    from contextlib import contextmanager

    @contextmanager
    def _f():
        yield db

    return _f


def test_requests_are_spaced_at_least_ten_seconds_apart_R8(db):
    clock = FakeClock()
    calls: list[float] = []

    def getter(url):
        calls.append(clock())
        ids = url.split("ids=")[1].split("&")[0].split("%7C")
        return {"entities": {q: _entity(q, {"en": q}) for q in ids}}

    qids = [f"Q{i}" for i in range(1, 151)]  # three requests
    out = IT.fetch_items(qids, session_factory=_factory(db), get=getter,
                         gate=RateGate(clock=clock, sleep=clock.sleep))
    assert len(calls) == 3
    gaps = [b - a for a, b in zip(calls, calls[1:], strict=False)]
    assert all(g >= 10.0 for g in gaps), gaps
    assert out["fetched"] == 150 and out["refused"] == 0 and out["pending"] == 0
    assert db.query(WikidataItem).count() == 150


def test_one_failed_batch_is_counted_and_never_aborts_the_run(db):
    clock = FakeClock()
    n = {"i": 0}

    def getter(url):
        n["i"] += 1
        if n["i"] == 1:
            raise OSError("boom")
        ids = url.split("ids=")[1].split("&")[0].split("%7C")
        return {"entities": {q: _entity(q) for q in ids[:-1]}}  # the last id goes unanswered

    out = IT.fetch_items([f"Q{i}" for i in range(1, 61)], session_factory=_factory(db), get=getter,
                         gate=RateGate(clock=clock, sleep=clock.sleep))
    assert out["refused"] == 50 + 1
    assert out["fetched"] == 9
    assert out["fetched"] + out["missing_on_wikidata"] + out["refused"] == out["requested"]


def test_airplane_mode_refuses_by_name_with_the_socket_guard_armed_and_ZERO_resolutions(monkeypatch, db):
    from src.ingest import airplane

    lookups: list[object] = []
    monkeypatch.setattr(airplane, "_orig_getaddrinfo", lambda host, *a, **k: lookups.append(host) or [])
    airplane.install_airplane_socket_guard()
    activate_kill_switch()
    try:
        with pytest.raises(IT.AirplaneRefusal) as err:
            IT.fetch_items(["Q1"], session_factory=_factory(db))  # the PRODUCTION getter
        assert "airplane mode" in str(err.value)
        # And the production getter itself, called straight: the one fetch path refuses
        # it too, naming the kill switch.
        from src.safety.fetcher import NetworkBlocked

        with pytest.raises(NetworkBlocked, match="kill switch"):
            IT._default_getter(entities_url(["Q1"]))
    finally:
        clear_kill_switch()
        airplane.uninstall_airplane_socket_guard()
    assert lookups == []
    assert db.query(WikidataItem).count() == 0


def test_airplane_mode_engaged_MID_RUN_stops_the_run_and_says_so(db):
    clock = FakeClock()
    calls = {"n": 0}

    def getter(url):
        calls["n"] += 1
        activate_kill_switch()  # the operator flips it during the first request's wait
        ids = url.split("ids=")[1].split("&")[0].split("%7C")
        return {"entities": {q: _entity(q) for q in ids}}

    try:
        out = IT.fetch_items([f"Q{i}" for i in range(1, 101)], session_factory=_factory(db),
                             get=getter, gate=RateGate(clock=clock, sleep=clock.sleep))
    finally:
        clear_kill_switch()
    assert calls["n"] == 1
    assert out["stopped_by_airplane_mode"] is True and out["pending"] == 50


def test_the_endpoint_refuses_without_consent_and_names_airplane_mode():
    from fastapi import HTTPException

    from src.api import entities as E

    with pytest.raises(HTTPException) as e1:
        E.items_fetch(E._FetchBody(consent=False))
    assert e1.value.status_code == 400 and "consent" in e1.value.detail
    activate_kill_switch()
    try:
        with pytest.raises(HTTPException) as e2:
            E.items_fetch(E._FetchBody(consent=True))
    finally:
        clear_kill_switch()
    assert e2.value.status_code == 409 and "airplane mode" in e2.value.detail


def test_the_refusal_string_ships_in_all_twelve_locales():
    root = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
    key = "Refused: airplane mode is on. Turn the network on to fetch Wikidata items."
    for f in sorted(root.glob("*.json")):
        d = json.loads(f.read_text("utf-8"))
        assert d.get(key), f"{f.name} lacks the refusal"


# --------------------------------------------------------------------------- #
#  S1 — entities on the ladder, keyed by QID
# --------------------------------------------------------------------------- #


@pytest.fixture
def rings(monkeypatch):
    """Two generated rings with QIDs, and one name shared by two items (a collision)."""
    rs = (
        equivalence.Ring(id="zedport", qid=ZEDPORT_QID,
                         members=(("en", "zedport"), ("fr", "zedport-sur-mer"), ("ar", "زدبورت"))),
        equivalence.Ring(id="ada-quill", qid="Q999999010",
                         members=(("en", "ada quill"), ("ru", "ада квилл"))),
        equivalence.Ring(id="mercury-planet", qid="Q999999020",
                         members=(("en", "mercury"), ("fr", "mercure"))),
        equivalence.Ring(id="mercury-element", qid="Q999999021",
                         members=(("en", "mercury"), ("de", "quecksilber"))),
    )
    equivalence.invalidate_ring_caches()
    monkeypatch.setattr(equivalence, "load_rings", lambda: rs)
    equivalence._index.cache_clear()
    equivalence._multi_index.cache_clear()
    equivalence._member_languages.cache_clear()
    yield
    monkeypatch.undo()
    equivalence.invalidate_ring_caches()


def test_an_entity_round_trips_term_to_QID_to_label_in_two_locales(rings, db):
    fr = SP.resolve_entity("Zedport", "fr", language="en")
    ar = SP.resolve_entity("Zedport", "ar", language="en")
    assert fr.qid == ar.qid == ZEDPORT_QID
    assert (fr.label, fr.tier, fr.label_source) == ("zedport-sur-mer", equivalence.TIER_VERIFIED, "ring")
    assert ar.label == "زدبورت"
    # The item cache speaks first when it has the label (S2 feeds S1).
    db.add(WikidataItem(qid=ZEDPORT_QID, status="ok",
                        labels_json=json.dumps({"fr": "Zedport (ville)"}), claims_json="{}"))
    db.commit()
    fr2 = SP.resolve_entity("Zedport", "fr", language="en", session=db)
    assert (fr2.label, fr2.label_source) == ("Zedport (ville)", "wikidata")


def test_an_unresolvable_entity_stays_a_plain_term_with_no_QID(rings):
    r = SP.resolve_entity("Somebody Unknown", "fr", language="en")
    assert r.qid is None and r.label is None and r.tier == equivalence.TIER_UNTRANSLATED
    assert "qid" not in r.to_dict()


def test_a_name_that_names_several_items_is_refused_not_guessed(rings):
    r = SP.resolve_entity("mercury", "fr", language="en")
    assert r.qid is None and r.declined == SP.DECLINED_SEVERAL_ITEMS
    assert set(r.candidate_qids) == {"Q999999020", "Q999999021"}


def test_the_payload_is_the_keyword_ladders_so_one_display_helper_renders_it(rings):
    d = SP.resolve_entity("Ada Quill", "ru", language="en").to_dict()
    assert d["translation_tier"] == "verified" and d["translation"] == "ада квилл"
    assert d["translation_source_lang"] == "en" and d["translation_qid"] == "Q999999010"


# --------------------------------------------------------------------------- #
#  S3 — the Place, its names, its card; the differential
# --------------------------------------------------------------------------- #


def test_the_gazetteer_carries_its_vintage_and_the_sample_says_it_has_none(gazetteer, monkeypatch):
    assert cities.gazetteer_meta()["vintage"] == "2026-09-28"
    monkeypatch.setattr(cities, "GAZETTEER_PATH", FIXTURE.parent / "absent.yml")
    cities.gazetteer_meta.cache_clear()
    assert cities.gazetteer_meta()["vintage"] is None
    assert cities.gazetteer_meta()["artifact"] is False


def test_the_shipped_sample_names_no_OSM_object_so_it_resolves_nothing():
    """The honest default: without the built artifact, no Place is invented."""
    for c in cities.load_cities(cities.SAMPLE_PATH):
        assert c.osm is None and c.qid is None


def test_every_unresolved_mention_says_why(gazetteer, db):
    art = _article(db, "x")
    _mention(db, art, "Zedport", "zz")
    _mention(db, art, "Quorra", "zz")
    _mention(db, art, "Atlantis", "zz")
    _mention(db, art, "Zedland", "zz", kind="country")
    out = PL.resolve_mentioned(db)
    assert out["resolved"] == 1 and out["places"] == 1
    assert out["unresolved"] == {
        PL.UNRESOLVED_COUNTRY_LEVEL: 1,
        PL.UNRESOLVED_NO_OSM_OBJECT: 1,
        PL.UNRESOLVED_NOT_IN_GAZETTEER: 1,
    }
    [p] = db.query(Place).all()
    assert p.id == ZEDPORT and p.qid == ZEDPORT_QID and p.kind == "town"
    assert p.gazetteer_vintage == "2026-09-28"


def test_resolution_changes_nothing_about_WHAT_is_found_differential(gazetteer, db):
    """The gazetteer-index lesson: compare old and new over the whole result structure.

    ``place_identity`` groups mentions into identities; the Place resolution must never
    merge two identities into one Place, never split one identity across two, and must
    leave every mention row exactly as it was.
    """
    from src.analytics.place_identity import place_identity

    a1, a2 = _article(db, "one", "https://zz.example/1"), _article(db, "two", "https://zz.example/2")
    for art in (a1, a2):
        _mention(db, art, "Zedport", "zz", n=2)
        _mention(db, art, "Nullhaven", "zz")
        _mention(db, art, "Quorra", "zz")
        _mention(db, art, "Zedland", "zz", kind="country")
    before = [(m.id, m.article_id, m.name, m.country, m.kind, m.mentions, m.lat, m.lon)
              for m in db.query(ArticleMentionedPlace).order_by(ArticleMentionedPlace.id)]
    PL.resolve_mentioned(db)
    after = [(m.id, m.article_id, m.name, m.country, m.kind, m.mentions, m.lat, m.lon)
             for m in db.query(ArticleMentionedPlace).order_by(ArticleMentionedPlace.id)]
    assert before == after

    ident_to_place: dict[str, set] = {}
    place_to_ident: dict[str, set] = {}
    for m in db.query(ArticleMentionedPlace):
        key, _disp = place_identity(m.name, m.country, m.kind)
        pid = PL.resolve_mention(db, m.name, m.country, m.kind)["place_id"]
        ident_to_place.setdefault(key, set()).add(pid)
        if pid:
            place_to_ident.setdefault(pid, set()).add(key)
    assert all(len(v) == 1 for v in ident_to_place.values()), ident_to_place
    assert all(len(v) == 1 for v in place_to_ident.values()), place_to_ident


def test_names_are_OSM_first_then_Wikidata_then_an_honest_absence(gazetteer, db):
    art = _article(db, "x")
    _mention(db, art, "Zedport", "zz")
    _mention(db, art, "Nullhaven", "zz")
    PL.resolve_mentioned(db)
    db.add(WikidataItem(qid=ZEDPORT_QID, status="ok",
                        labels_json=json.dumps({"fr": "Zedport (WD)", "de": "Zedhafen"}),
                        descriptions_json=json.dumps({"en": "a synthetic town in the test country"}),
                        claims_json="{}"))
    db.commit()
    card = PL.place_card(db, ZEDPORT, "fr")
    assert card["title"] == {"name": "Zedport-sur-Mer", "source": "osm", "lang": "fr"}
    names = {n["lang"]: n for n in card["names"]}
    assert names["de"] == {"name": "Zedhafen", "source": "wikidata", "lang": "de"}  # the fallback
    assert names["ja"] == {"lang": "ja", "name": None, "source": None}  # neither: said so
    assert len(card["names"]) == 12
    # A place with neither name:xx nor a label: the LOCAL name, marked as local.
    null = PL.place_card(db, "node/9000000003", "ar")
    assert null["title"] == {"name": "Nullhaven", "source": "local", "lang": "ar"}
    assert all(n["name"] is None for n in null["names"])
    assert null["item"]["status"] == "not-fetched"  # an unknown QID is a gap, not a zero


def test_the_body_is_description_then_metadata_and_keywords_come_from_the_prose(gazetteer, db):
    art = _article(db, "x")
    _mention(db, art, "Zedport", "zz")
    PL.resolve_mentioned(db)
    card = PL.place_card(db, ZEDPORT, "en")
    assert card["body"]["description"] is None and card["keywords"] == []  # no prose, no keywords
    db.add(WikidataItem(qid=ZEDPORT_QID, status="ok", labels_json="{}",
                        descriptions_json=json.dumps({"en": "harbour town known for its lighthouse"}),
                        claims_json="{}"))
    db.commit()
    card = PL.place_card(db, ZEDPORT, "en")
    assert card["body"]["description"].startswith("harbour town")
    keys = [m["key"] for m in card["body"]["metadata"]]
    assert keys[:2] == ["osm", "kind"] and "qid" in keys
    assert any("lighthouse" in k["term"].lower() for k in card["keywords"])
    assert card["articles"] == 1


def test_places_are_searchable_in_every_language_a_source_gives(gazetteer, db):
    art = _article(db, "x")
    _mention(db, art, "Zedport", "zz")
    PL.resolve_mentioned(db)
    assert [p["id"] for p in PL.search_places(db, "sur-Mer")["items"]] == [ZEDPORT]
    assert PL.search_places(db, "زدبورت")["total"] == 1
    db.add(WikidataItem(qid=ZEDPORT_QID, status="ok", labels_json=json.dumps({"de": "Zedhafen"}),
                        claims_json="{}"))
    db.commit()
    assert PL.search_places(db, "Zedhafen")["total"] == 1
    assert PL.search_places(db, "Atlantis")["total"] == 0


def test_mentioned_qids_are_places_first_then_ringed_entities_and_nothing_else(gazetteer, rings, db):
    art = _article(db, "x")
    _mention(db, art, "Zedport", "zz")
    db.add(ArticleEntity(article_id=art.id, name="Ada Quill", entity_class="person"))
    db.add(ArticleEntity(article_id=art.id, name="Mercury", entity_class="organization"))  # ambiguous
    db.add(ArticleEntity(article_id=art.id, name="Nobody Known", entity_class="person"))
    db.commit()
    PL.resolve_mentioned(db)
    stats: dict = {}
    assert IT.mentioned_qids(db, stats=stats) == [ZEDPORT_QID, "Q999999010"]
    assert stats["from_places"] == 1 and stats["from_entities"] == 1
    s = IT.pending_summary(db)
    assert (s["mentioned"], s["pending"], s["requests_needed"]) == (2, 2, 1)


# --------------------------------------------------------------------------- #
#  S5 — Q819 step 2: the gate's closing demonstration
# --------------------------------------------------------------------------- #


def test_a_press_articles_place_and_a_wiki_page_with_the_same_QID_resolve_to_ONE_Place(
    gazetteer, db, tmp_path, monkeypatch
):
    """The row's «closes when», on the synthetic gazetteer and a synthetic lane."""
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.versioned.pipeline import ensure_entity
    from src.versioned.store import create_lane, dispose_all, lane_session

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    try:
        # 1. A press article, indexed through the ONE hook: the extractor finds the place.
        art = _article(db, "Storms closed the harbour at Zedport on Monday, officials said.")
        index_article(db, art, extractor=BaselineExtractor())
        amp = db.query(ArticleMentionedPlace).filter_by(article_id=art.id, name="Zedport").one()
        # 2. The mention resolves into its Place.
        PL.resolve_mentioned(db)
        press = PL.resolve_mention(db, amp.name, amp.country, amp.kind)["place_id"]
        assert press == ZEDPORT
        # 3. A Wikipedia lane page carrying the same QID resolves to the SAME Place.
        create_lane("wiki")
        with lane_session("wiki") as lane:
            ensure_entity(lane, "en:p4242", title="Zedport", qid=ZEDPORT_QID)
            ensure_entity(lane, "en:p4243", title="Elsewhere", qid=None)
            lane.commit()
        wiki = PL.place_for_wiki_page(db, "en:p4242")
        assert wiki["place_id"] == press
        # ...and the Place's card names the page, from the other direction.
        card = PL.place_card(db, ZEDPORT, "en")
        assert [p["external_id"] for p in card["wiki"]["pages"]] == ["en:p4242"]
        # A page with no QID resolves to nothing, and says why.
        assert PL.place_for_wiki_page(db, "en:p4243")["reason"] == "page-has-no-qid"
    finally:
        dispose_all()


def test_a_card_on_a_machine_whose_lane_never_ran_names_the_absence(gazetteer, db, tmp_path, monkeypatch):
    from src.versioned.store import dispose_all

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    dispose_all()
    art = _article(db, "x")
    _mention(db, art, "Zedport", "zz")
    PL.resolve_mentioned(db)
    card = PL.place_card(db, ZEDPORT, "en")
    assert card["wiki"] == {"available": False, "pages": [], "reason": "lane-never-run"}
    dispose_all()


def test_Place_rows_never_leave_the_machine_Q823():
    """Q823 ⛔ (ODbL) is open: no Place row rides a backup restore or an export."""
    from src.backup.merge import _MERGE_HANDLED, _MERGE_NOT_CARRIED

    assert "places" in _MERGE_NOT_CARRIED and "places" not in _MERGE_HANDLED
    assert "wikidata_items" in _MERGE_NOT_CARRIED
