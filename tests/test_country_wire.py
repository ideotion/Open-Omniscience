"""The wire boundary: alpha-3 out, every spelling in (S05-02 S2, Q304, Q313).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Four things are pinned here, because each is a way this change quietly stops being true:

1. THE REWRITE (``src/api/country_wire.py``) converts what is a country CODE in a registered
   field and nothing else: a name stays a name, an unrecognised code stays itself, an aggregate
   is not promoted to a nation, a field that names its own form (``iso2``, ``cc`` ...) is never
   changed, a cached payload is never mutated, and doing it twice changes nothing.
2. THE BOUNDARY IS UNAVOIDABLE: the app's default response class is the wired one and no module
   under ``src/api`` builds a JSON response from the plain class. Both are mutation-checked below
   by running the same checker over text that breaks the rule.
3. EVERY COUNTRY PARAMETER takes ``fr``, ``FR``, ``FRA``, ``fra`` and answers the same, and garbage
   answers empty rather than something else (a parameter is never guessed into a country).
4. THE KEY WALK (the brief's pre-push step): no payload these endpoints send carries a key named
   for a score, rating, ranking or grade, and the rewrite itself adds no key.
"""

from __future__ import annotations

import ast
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.api import country_wire as cw

_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
#  1. The rewrite
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("stored", "wire"),
    [("fr", "FRA"), ("FR", "FRA"), ("FRA", "FRA"), ("fra", "FRA"), ("uk", "GBR"), ("eu", "EUU"), ("int", "INT"),
     ("xk", "XKX"), ("an", "ANT")],
)
def test_a_registered_field_carrying_a_code_leaves_as_its_alpha3(stored, wire):
    for field in sorted(cw.CODE_FIELDS):
        assert cw.to_wire({field: stored}) == {field: wire}, field


@pytest.mark.parametrize("kept", ["Niger", "France", "United Kingdom", "all", "", "floop", "zz", "ZZZ", "12", "wld", "WLD", "oecd"])
def test_what_is_not_a_recognised_code_travels_exactly_as_it_was(kept):
    """A NAME is never converted (``Niger`` resolves to ``ne`` through ``normalize_country`` -- the rewrite must not use that
    door), an unrecognised code is not blanked (that would claim "no country"), and an aggregate is not laundered into a nation."""
    out = cw.to_wire({"country": kept})
    assert out == {"country": kept}


def test_a_field_that_names_its_own_form_is_never_changed():
    payload = {"iso2": "fr", "alpha2": "fr", "cc": "fr", "country_iso2": "fr", "iso3": "fra", "alpha3": "fra", "code": "fr"}
    assert cw.to_wire(payload) == payload


def test_nothing_to_convert_returns_the_very_same_object_and_a_conversion_never_mutates_its_input():
    quiet = {"a": [1, 2, {"b": "fr"}], "name": "France"}
    assert cw.to_wire(quiet) is quiet
    loud = {"rows": [{"country": "fr", "n": 1}, {"country": "FRA", "n": 2}], "countries": ["fr", {"code": "de"}],
            "jurisdictions": {"uk": 2, "gbr": 3}}
    before = copy.deepcopy(loud)
    out = cw.to_wire(loud)
    assert loud == before, "a cached payload was mutated in place: the next request would see the first one's rewrite"
    assert out is not loud and out["rows"][0]["country"] == "FRA"
    assert out["rows"][1] is loud["rows"][1], "an already-wire row was copied for nothing"


def test_the_rewrite_is_idempotent_and_adds_no_key():
    payload = {"country": "fr", "rows": [{"country": "uk", "n": 1, "jurisdiction": "eu"}], "countries": ["de", "us"],
               "jurisdictions": {"uk": 1, "fr": 2}, "geometry": {"country": {"rings": [[1, 2]]}}}
    once = cw.to_wire(payload)
    assert cw.to_wire(once) == once

    def keys(o, acc=None):
        acc = set() if acc is None else acc
        if isinstance(o, dict):
            for k, v in o.items():
                acc.add(k)
                keys(v, acc)
        elif isinstance(o, list):
            for v in o:
                keys(v, acc)
        return acc

    # `jurisdictions` is keyed BY country, so its keys are the data being rewritten; every other key is untouched.
    own = lambda o: keys({k: v for k, v in o.items() if k != "jurisdictions"})  # noqa: E731
    assert own(once) == own(payload), "the rewrite added or removed a key"


def test_lists_keyed_dicts_and_geometry_are_walked():
    out = cw.to_wire({"countries": ["fr", "de", {"code": "us", "top": [{"country": "gb"}]}],
                      "jurisdictions": {"uk": 2, "gbr": 3, "fr": 1}, "country": {"rings": [], "name": "France"}})
    assert out["countries"] == ["FRA", "DEU", {"code": "USA", "top": [{"country": "GBR"}]}]
    assert out["jurisdictions"] == {"GBR": 5, "FRA": 1}, "two spellings of one country must add up, not replace each other"
    assert out["country"] == {"rings": [], "name": "France"}, "only a STRING can be a code, but anything can contain one"


# --------------------------------------------------------------------------- #
#  2. The boundary cannot be walked around
# --------------------------------------------------------------------------- #
def _plain_json_response_imports(source: str) -> list[int]:
    """Lines that bring the PLAIN ``JSONResponse`` into a module (from fastapi or starlette)."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module in {"fastapi.responses", "starlette.responses", "fastapi"}
            and any(a.name == "JSONResponse" for a in node.names)
        ):
            hits.append(node.lineno)
    return hits


def test_no_api_module_builds_a_json_response_from_the_plain_class():
    offenders = {}
    scanned = 0
    for path in sorted((_ROOT / "src" / "api").rglob("*.py")):
        if path.name == "country_wire.py":
            continue
        scanned += 1
        lines = _plain_json_response_imports(path.read_text(encoding="utf-8"))
        if lines:
            offenders[str(path.relative_to(_ROOT))] = lines
    assert scanned > 40, "the scan found almost nothing: it is looking in the wrong place and an empty search passes for free"
    assert not offenders, (
        f"{offenders}: import `CountryWireResponse as JSONResponse` from src.api.country_wire instead, so the payload leaves "
        "through the wire boundary"
    )


def test_the_checker_would_notice_a_plain_import():
    """MUTATION CHECK for the guard above: the same checker reddens on the text it exists to refuse."""
    assert _plain_json_response_imports("from fastapi.responses import JSONResponse\n") == [1]
    assert _plain_json_response_imports("from starlette.responses import FileResponse, JSONResponse\n") == [1]
    assert _plain_json_response_imports("from src.api.country_wire import CountryWireResponse as JSONResponse\n") == []


def test_the_app_default_response_class_is_the_wired_one():
    main = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(main)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "FastAPI":
            found += [kw.value.id for kw in node.keywords if kw.arg == "default_response_class" and isinstance(kw.value, ast.Name)]
    assert found == ["CountryWireResponse"], found
    from src.api.main import app

    assert app.router.default_response_class is cw.CountryWireResponse


def test_a_route_on_an_app_with_the_wired_class_sends_alpha3_over_http():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    private = FastAPI(default_response_class=cw.CountryWireResponse)

    @private.get("/plain")
    def plain() -> dict:
        return {"country": "fr", "iso2": "fr"}

    @private.get("/direct")
    def direct():
        return cw.CountryWireResponse({"jurisdiction": "uk"})

    client = TestClient(private)
    assert client.get("/plain").json() == {"country": "FRA", "iso2": "fr"}
    assert client.get("/direct").json() == {"jurisdiction": "GBR"}


# --------------------------------------------------------------------------- #
#  3. Every country parameter takes every spelling
# --------------------------------------------------------------------------- #
@pytest.fixture()
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    monkeypatch.setenv("OO_AUTOSEED", "0")
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as client:
        yield client


_SPELLINGS = ["fr", "FR", "FRA", "fra"]
_GARBAGE = "floopland"


@pytest.fixture()
def corpus(api):
    """A French and a German source, two indexed articles each, places and a law row, so every endpoint under test has
    something to find for ``fr`` and something different for ``de``."""
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.database.models import Article, ArticleMentionedPlace, LawDocument, Source
    from src.database.session import session_scope

    with session_scope() as db:
        # The app's engine outlives one test, so the corpus is made once and found again (a second insert would collide).
        if db.query(Source).filter_by(domain="param-fr.example").first() is not None:
            return api
        fr = Source(name="ParamFr", domain="param-fr.example", country="fr", source_type="news", enabled=True)
        de = Source(name="ParamDe", domain="param-de.example", country="de", source_type="news", enabled=True)
        db.add_all([fr, de])
        db.flush()
        texts = {
            "fr": "The wildfire response and the wildfire funding dominated the wildfire debate across the region this week.",
            "de": "The drought relief and the drought funding dominated the drought debate across the region this week.",
        }
        for cc, src in (("fr", fr), ("de", de)):
            for i in range(2):
                a = Article(
                    url=f"https://param-{cc}.example/{i}", canonical_url=f"https://param-{cc}.example/{i}", source_id=src.id,
                    title=f"{cc}{i}", content=texts[cc], hash=f"param{cc}{i}".ljust(64, "7"), country=cc, language="en",
                    published_at=datetime.now(UTC), created_at=datetime.now(UTC),
                )
                db.add(a)
                db.commit()
                index_article(db, a, extractor=BaselineExtractor(), country=cc, city=None)
                db.add(ArticleMentionedPlace(article_id=a.id, name=f"ParamTown-{cc}", country=cc, kind="city", mentions=2,
                                             snippet="seed", note="seed"))
        db.add(LawDocument(jurisdiction="uk", title="ParamLaw UK", url="https://param.example/uk", category="legislation",
                           consolidated=False, watched=True))
        db.add(LawDocument(jurisdiction="fr", title="ParamLaw FR", url="https://param.example/fr", category="legislation",
                           consolidated=False, watched=True))
        db.commit()
    return api


def _norm(obj):
    """A payload without the fields that legitimately differ between two identical requests."""
    drop = {"as_of", "computed_at", "elapsed_ms", "generated_at", "cache", "cached", "ms", "took_ms", "served_at"}
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items() if k not in drop}
    if isinstance(obj, list):
        return [_norm(v) for v in obj]
    return obj


def _get(client, path, **params):
    r = client.get(path, params=params)
    assert r.status_code == 200, (path, params, r.status_code, r.text[:300])
    return r.json()


def _names(payload, *keys):
    """The set of ``name``/``title``/``term`` strings anywhere in a payload, for a coarse 'did it find this' comparison."""
    out: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in keys and isinstance(v, str):
                    out.add(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(payload)
    return out


_SEEN_PAYLOADS: list = []


def _remember(payload):
    _SEEN_PAYLOADS.append(payload)
    return payload


def test_the_sources_listing_filters_by_every_spelling(corpus):
    def domains(path, param, value):
        body = _remember(_get(corpus, path, **{param: value, "limit": 1000}))
        rows = body["sources"] if isinstance(body, dict) else body
        return {r["domain"] for r in rows if r.get("domain", "").startswith("param-")}

    for path, param in (("/api/catalog/sources", "country"), ("/api/sources/", "countries")):
        want = domains(path, param, "fr")
        assert want == {"param-fr.example"}, (path, want)
        for spelling in _SPELLINGS:
            assert domains(path, param, spelling) == want, (path, spelling)
        assert domains(path, param, _GARBAGE) == set(), (path, "garbage matched something")


def test_the_registered_statistics_sources_filter_by_every_spelling(corpus):
    def domains(value):
        body = _remember(_get(corpus, "/api/stats/sources", country=value))
        return {r["domain"] for r in body["sources"] if r["domain"].startswith("param-")}

    want = domains("fr")
    for spelling in _SPELLINGS:
        assert domains(spelling) == want, spelling
    assert domains(_GARBAGE) == set()
    assert all(r["country"] == "FRA" for r in _get(corpus, "/api/stats/sources", country="FRA")["sources"] if r["domain"].startswith("param-"))


def test_the_law_filter_takes_every_spelling_of_both_the_stored_and_the_displayed_code(corpus):
    def titles(value):
        body = _remember(_get(corpus, "/api/law/documents", jurisdiction=value))
        return {d["title"] for d in body["documents"] if d["title"].startswith("ParamLaw")}

    assert titles("fr") == {"ParamLaw FR"}
    for spelling in _SPELLINGS:
        assert titles(spelling) == {"ParamLaw FR"}, spelling
    # `uk` is stored, GBR is what the payload shows: the operator reads GBR and types GBR.
    for spelling in ("uk", "UK", "GBR", "gbr"):
        assert titles(spelling) == {"ParamLaw UK"}, spelling
    assert titles(_GARBAGE) == set()
    shown = {d["title"]: d["jurisdiction"] for d in _get(corpus, "/api/law/documents")["documents"] if d["title"].startswith("ParamLaw")}
    assert shown == {"ParamLaw FR": "FRA", "ParamLaw UK": "GBR"}


def test_the_law_add_form_files_the_same_document_under_every_spelling_of_one_jurisdiction(corpus, monkeypatch):
    """The displayed code is what an operator re-types: GBR for a row stored as `uk` must find that row, not file a second."""
    import src.law.track as track

    monkeypatch.setattr(track, "track_document", lambda db, fetcher, doc: {"status": "stubbed"})
    body = {"jurisdiction": "GBR", "title": "ParamLaw UK", "url": "https://param.example/uk"}
    r = corpus.post("/api/law/documents", json=body)
    assert r.status_code == 409, r.text  # already tracked: found through every spelling, not filed twice


def test_the_agenda_filters_by_every_spelling(corpus):
    def ids(value):
        body = _remember(_get(corpus, "/api/events", country=value))
        return sorted(json.dumps(e, sort_keys=True) for e in body["events"]) if "events" in body else sorted(map(str, body))

    want = ids("fr")
    assert want, "no event carries France: the comparison below would prove nothing"
    for spelling in _SPELLINGS:
        assert ids(spelling) == want, spelling
    assert ids(_GARBAGE) == [] or ids(_GARBAGE) != want


@pytest.mark.parametrize(
    ("path", "extra"),
    [
        ("/api/insights/top", {}),
        ("/api/insights/trending", {}),
        ("/api/insights/trending-windows", {}),
        ("/api/insights/trend", {"term": "wildfire"}),
        ("/api/insights/who", {}),
        ("/api/insights/where", {}),
    ],
)
def test_the_insights_endpoints_answer_every_spelling_the_same_and_garbage_with_nothing_else(corpus, path, extra):
    fr = _norm(_remember(_get(corpus, path, country="fr", **extra)))
    for spelling in _SPELLINGS:
        assert _norm(_get(corpus, path, country=spelling, **extra)) == fr, (path, spelling)
    junk = _norm(_remember(_get(corpus, path, country=_GARBAGE, **extra)))
    assert junk != fr or not _names(fr, "term", "name", "label"), (
        f"{path}: a country nobody named answered what France did -- the parameter was guessed into a country"
    )


def test_a_french_filter_finds_the_french_rows_and_the_german_filter_does_not(corpus):
    """The positive half, so the equalities above cannot all be 'empty equals empty'."""
    top_fr = _names(_get(corpus, "/api/insights/top", country="FRA"), "term", "label", "name")
    top_de = _names(_get(corpus, "/api/insights/top", country="deu"), "term", "label", "name")
    assert any("wildfire" in t for t in top_fr), top_fr
    assert not any("wildfire" in t for t in top_de), top_de
    where_fr = _names(_get(corpus, "/api/insights/where", country="FRA"), "name")
    assert "ParamTown-fr" in where_fr and "ParamTown-de" not in where_fr, where_fr


class _Spied(Exception):
    pass


@pytest.mark.parametrize(
    ("path", "extra", "target"),
    [
        ("/api/insights/top", {}, ("rm", "top_terms")),
        ("/api/insights/trending", {}, ("rm", "trending")),
        ("/api/insights/trending-windows", {}, ("rm", "trending_windows")),
        ("/api/insights/trend", {"term": "wildfire"}, ("q", "trend")),
        ("/api/insights/who", {}, ("q", "who_aggregate")),
        ("/api/insights/where", {}, ("q", "where_aggregate")),
        ("/api/insights/ring-country-articles", {"ring_id": "inflation"}, ("q", "ring_country_article_ids")),
    ],
)
def test_every_insights_handler_hands_the_analytics_ONE_spelling_whatever_was_typed(api, monkeypatch, path, extra, target):
    """The store-form-independent proof of 'every parameter accepts both forms'. The equality tests above run in an alpha-3
    store, where the column's own bind step converts ``fra`` and would hide a handler that forgot to normalise; a store that
    has not migrated binds the value as given. So the argument the handler passes DOWN is asserted here, spelling by spelling:
    always the lowercase alpha-2 the analytics speak, and garbage stays itself (matching nothing) rather than being guessed."""
    from fastapi.testclient import TestClient

    from src.analytics import queries as q
    from src.analytics import readmodel as rm
    from src.api import insights as insights_api
    from src.api.main import app

    # A hit on the endpoints' own read cache (filled by an earlier test for the same key) never reaches the analytics, and
    # this test is about what is handed to them.
    insights_api._read_cache.clear()
    seen: list = []
    module = {"rm": rm, "q": q}[target[0]]

    def spy(*args, **kwargs):
        seen.append(kwargs.get("country"))
        raise _Spied

    monkeypatch.setattr(module, target[1], spy)
    client = TestClient(app, raise_server_exceptions=False)
    for spelling in [*_SPELLINGS, _GARBAGE]:
        client.get(path, params={"country": spelling, **extra})
    assert seen == ["fr", "fr", "fr", "fr", _GARBAGE.lower()], f"{path}: handed down {seen}"


def test_the_ring_drill_takes_every_spelling(corpus):
    def call(value):
        return _get(corpus, "/api/insights/ring-country-articles", ring_id="inflation", country=value)

    first = _norm(call("fr"))
    for spelling in _SPELLINGS:
        assert _norm(call(spelling)) == first, spelling
    assert call("FR")["country"] == "FRA", "the echoed parameter must leave in wire form too"


def test_the_gazetteer_resolver_takes_every_spelling(corpus):
    def call(value):
        r = corpus.post("/api/entities/places/resolve", json={"name": "Paris", "country": value})
        assert r.status_code == 200, r.text
        return r.json()

    first = call("fr")
    for spelling in _SPELLINGS:
        assert call(spelling) == first, spelling


def test_the_discovery_endpoint_reads_alpha3_and_refuses_junk_before_any_network():
    """No network is touched: the refusals happen before the discovery call. (The accepted path is a Wikidata query, which
    this suite never makes.)"""
    src = (_ROOT / "src" / "api" / "diagnostics" / "discovery.py").read_text(encoding="utf-8")
    assert "to_iso2(c.strip())" in src, "the discovery endpoint stopped converting the alpha-3 it now accepts"
    from src.catalog.countries import to_iso2

    assert [to_iso2(c) for c in ("KEN", "ng", "BRA")] == ["ke", "ng", "br"]
    assert to_iso2(_GARBAGE) is None


# --------------------------------------------------------------------------- #
#  4. The key walk
# --------------------------------------------------------------------------- #
_FORBIDDEN = ("score", "rating", "ranking", "grade")
#: Operator-asserted provenance metadata (1-10), never computed by the app: the one deliberate exemption
#: (docs/ETHICS.md; test_reliability_score_is_operator_set_never_computed).
_EXEMPT = {"reliability_score"}


def _all_keys(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(str(k))
            _all_keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _all_keys(v, acc)
    return acc


def test_no_payload_these_endpoints_send_carries_a_score_rating_ranking_or_grade_key(corpus):
    # Run AFTER the fixtures above have filled the cache of payloads; fetch a fresh representative set here too, so the test
    # stands alone when selected by itself.
    for path, params in (
        ("/api/catalog/sources", {"limit": 50}),
        ("/api/sources/", {"limit": 50}),
        ("/api/law/documents", {}),
        ("/api/insights/where", {}),
        ("/api/insights/top", {"country": "FRA"}),
    ):
        _remember(_get(corpus, path, **params))
    keys: set[str] = set()
    for payload in _SEEN_PAYLOADS:
        _all_keys(payload, keys)
    assert len(keys) > 40, f"the walk saw {len(keys)} keys: it measured almost nothing"
    bad = sorted(k for k in keys if k not in _EXEMPT and any(w in k.lower() for w in _FORBIDDEN))
    assert not bad, f"payload keys named for a verdict: {bad}"


def test_the_key_walk_would_notice_a_score_key():
    """MUTATION CHECK: the walk reddens on the key it exists to refuse, and exempts only the named one."""
    keys = _all_keys({"rows": [{"credibility_score": 1}, {"reliability_score": 7}, {"country_rank": 2}]})
    bad = sorted(k for k in keys if k not in _EXEMPT and any(w in k.lower() for w in _FORBIDDEN))
    assert bad == ["credibility_score"]
