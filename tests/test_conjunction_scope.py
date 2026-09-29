"""S05-11 S3 — the Conjunction Lens reached from every vertical's corpus.

The lens reads ONE scope: the whole corpus, one content-provenance channel (press and the web,
Wikipedia, law …) or the articles naming one Place. Every count is within that scope, the per-term
``n`` included; the vocabulary contrast compares two combinations the reader names in the same
scope; and every public name of ``src/analytics/conjunction.py`` has a caller outside the tests.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import ast
import hashlib
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import conjunction
from src.analytics.conjunction import corpus_algebra, lens_scope, public_scope, set_contrast
from src.database.models import (
    Article,
    ArticleMentionedPlace,
    Base,
    Keyword,
    KeywordMention,
    Place,
    Source,
)

ROOT = Path(__file__).resolve().parents[1]

# article id -> (source domain, keywords)
_ARTICLES = {
    1: ("press.example", ["drought", "river", "harvest"]),
    2: ("press.example", ["drought", "river"]),
    3: ("en.wikipedia.org", ["drought", "river", "glacier"]),
    4: ("en.wikipedia.org", ["drought", "glacier"]),
    5: ("law.fr.local", ["drought", "water permit"]),
    6: ("blog.example", ["drought", "harvest"]),
}


def _engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(s) -> None:
    srcs: dict[str, int] = {}
    for dom in sorted({d for d, _ in _ARTICLES.values()}):
        src = Source(name=dom, domain=dom, rss_url=None)
        s.add(src)
        s.flush()
        srcs[dom] = src.id
    kws: dict[str, int] = {}
    for aid, (dom, terms) in _ARTICLES.items():
        text = f"article {aid}"
        s.add(Article(id=aid, url=f"https://x.example/{aid}", canonical_url=f"https://x.example/{aid}",
                      source_id=srcs[dom], title=f"Article {aid}",
                      content=text, language="en", hash=hashlib.sha256(text.encode()).hexdigest()))
        s.flush()
        for term in terms:
            if term not in kws:
                k = Keyword(term=term, normalized_term=term)
                s.add(k)
                s.flush()
                kws[term] = k.id
            s.add(KeywordMention(keyword_id=kws[term], article_id=aid, count=aid,
                                 observed_on=date(2026, 3, aid)))
    s.add(Place(id="node/1", name="Zermatt", country="CH", kind="village"))
    for aid in (1, 3):
        s.add(ArticleMentionedPlace(article_id=aid, name="Zermatt", country="CH", kind="village", mentions=1))
    # a country-level mention is not the place (the place card's own rule)
    s.add(ArticleMentionedPlace(article_id=2, name="Zermatt", country="CH", kind="country", mentions=1))
    s.commit()


@pytest.fixture
def db():
    eng = _engine()
    s = sessionmaker(bind=eng)()
    _seed(s)
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


# --------------------------------------------------------------------------- #
#  the scope
# --------------------------------------------------------------------------- #


def test_the_whole_corpus_is_the_default_scope(db):
    sc = lens_scope(db)
    assert sc["kind"] == "all" and sc["n_articles"] == 6
    assert corpus_algebra(db, ["drought"], scope=sc)["article_ids"] == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize(
    ("channel", "expected"),
    [("wikipedia", [3, 4]), ("law", [5]), ("web", [1, 2, 6])],
)
def test_a_channel_reads_only_its_own_articles(db, channel, expected):
    sc = lens_scope(db, channel=channel)
    assert sc["n_articles"] == len(expected)
    r = corpus_algebra(db, ["drought"], scope=sc)
    assert r["article_ids"] == expected
    # the per-term n is within the scope too, never the corpus-wide figure
    assert r["terms"][0]["n"] == len(expected)
    assert r["scope"]["channel"] == channel and r["scope"]["n_articles"] == len(expected)


def test_the_web_channel_joins_every_plain_domain(db):
    assert 6 in corpus_algebra(db, ["harvest"], scope=lens_scope(db, channel="web"))["article_ids"]
    assert corpus_algebra(db, ["harvest"], scope=lens_scope(db, channel="wikipedia"))["article_ids"] == []


def test_a_place_reads_the_articles_the_place_card_counts(db):
    sc = lens_scope(db, place_id="node/1")
    assert sc["kind"] == "place" and sc["label"] == "Zermatt"
    assert sc["n_articles"] == 2 and sc["bounded"] is False  # the country-level row is not counted
    r = corpus_algebra(db, ["drought", "river"], op="intersection", scope=sc)
    assert r["article_ids"] == [1, 3]
    assert {t["normalized"]: t["n"] for t in r["terms"]} == {"drought": 2, "river": 2}


def test_a_place_over_the_cap_is_read_in_part_and_says_so(db, monkeypatch):
    monkeypatch.setattr(conjunction, "_SCOPE_ID_CAP", 1)
    sc = lens_scope(db, place_id="node/1")
    assert sc["n_articles"] == 2 and sc["bounded"] is True and sc["article_ids"] == [1]


@pytest.mark.parametrize(
    "kwargs",
    [{"channel": "gossip"}, {"place_id": "node/404"}, {"channel": "law", "place_id": "node/1"}],
)
def test_an_unknown_or_double_scope_fails_loud(db, kwargs):
    with pytest.raises(ValueError):
        lens_scope(db, **kwargs)


def test_the_public_scope_never_carries_the_id_lists(db):
    pub = public_scope(lens_scope(db, place_id="node/1"))
    assert set(pub) == {"kind", "channel", "place_id", "label", "n_articles", "bounded"}
    assert public_scope(None) is None


# --------------------------------------------------------------------------- #
#  the vocabulary contrast
# --------------------------------------------------------------------------- #


def test_set_contrast_counts_every_candidate_exactly_on_both_sides(db):
    # side A = river articles {1,2,3}; side B = glacier articles {3,4}
    out = set_contrast(db, [1, 2, 3], [3, 4], exclude=["river", "glacier"])
    rows = {r["term"]: r for r in out["contrasts"]}
    assert "river" not in rows and "glacier" not in rows  # the defining terms are left out
    assert rows["drought"]["a_articles"] == 3 and rows["drought"]["b_articles"] == 2
    assert rows["harvest"]["a_articles"] == 1 and rows["harvest"]["b_articles"] == 0
    assert out["n_a"] == 3 and out["n_b"] == 2
    assert out["excluded"] == ["glacier", "river"]


def test_set_contrast_with_an_empty_side_is_honest(db):
    out = set_contrast(db, [1, 2], [], exclude=[])
    assert out["n_b"] == 0
    assert all(r["b_articles"] == 0 for r in out["contrasts"])


# --------------------------------------------------------------------------- #
#  the API
# --------------------------------------------------------------------------- #


@pytest.fixture
def client(db):
    # the insights router on its own app: never the shared src.api.main singleton
    from fastapi import FastAPI

    from src.api.insights import router
    from src.database.session import get_db

    app = FastAPI()
    app.include_router(router)

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def test_the_algebra_endpoint_reads_a_scope_and_names_it(client):
    r = client.get("/api/insights/corpus-algebra", params={"terms": "drought", "channel": "wikipedia"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["article_ids"] == [3, 4] and body["scope"]["channel"] == "wikipedia"
    r = client.get("/api/insights/corpus-algebra", params={"terms": "drought", "place": "node/1"})
    assert r.json()["article_ids"] == [1, 3] and r.json()["scope"]["label"] == "Zermatt"


def test_the_algebra_endpoint_offers_the_near_search_for_two_terms(client):
    one = client.get("/api/insights/corpus-algebra", params={"terms": "drought"}).json()
    assert one["near"] is None
    two = client.get("/api/insights/corpus-algebra", params={"terms": "drought,river"}).json()
    assert two["near"]["query"] == 'NEAR("drought" "river", 10)' and two["near"]["distance"] == 10


def test_the_intensity_rows_name_their_articles(client):
    body = client.get("/api/insights/corpus-algebra",
                      params={"terms": "drought,river", "expand": "intensity,trend"}).json()
    first = body["intensity"]["articles"][0]
    assert first["title"].startswith("Article ") and "published_at" in first
    assert body["trend"]["points"]


@pytest.mark.parametrize(
    "params",
    [
        {"terms": "drought", "op": "xor"},
        {"terms": "drought", "channel": "gossip"},
        {"terms": "drought", "place": "node/404"},
        {"terms": "drought", "channel": "law", "place": "node/1"},
    ],
)
def test_the_algebra_endpoint_refuses_a_bad_request(client, params):
    assert client.get("/api/insights/corpus-algebra", params=params).status_code == 400


def test_the_contrast_endpoint_compares_two_named_combinations_in_one_scope(client):
    r = client.get("/api/insights/corpus-contrast", params={"terms": "river", "vs_terms": "harvest"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["a"]["n_combined"] == 3 and body["b"]["n_combined"] == 2  # river {1,2,3}, harvest {1,6}
    rows = {x["term"]: x for x in body["contrasts"]}
    assert "river" not in rows and "harvest" not in rows
    assert rows["drought"]["a_articles"] == 3 and rows["drought"]["b_articles"] == 2
    scoped = client.get("/api/insights/corpus-contrast",
                        params={"terms": "river", "vs_terms": "glacier", "channel": "wikipedia"}).json()
    assert scoped["a"]["n_combined"] == 1 and scoped["b"]["n_combined"] == 2
    assert scoped["scope"]["channel"] == "wikipedia"


@pytest.mark.parametrize(
    "params",
    [
        {"terms": "river", "vs_terms": " , "},
        {"terms": "river", "vs_terms": "harvest", "vs_op": "xor"},
        {"terms": "river", "vs_terms": "harvest", "place": "node/404"},
    ],
)
def test_the_contrast_endpoint_refuses_a_bad_request(client, params):
    assert client.get("/api/insights/corpus-contrast", params=params).status_code == 400


def test_no_score_key_in_either_response(client):
    banned = ("score", "ranking", "rating", "grade")

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in banned), k
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(client.get("/api/insights/corpus-algebra",
                    params={"terms": "drought,river", "expand": "intensity,trend", "place": "node/1"}).json())
    walk(client.get("/api/insights/corpus-contrast", params={"terms": "river", "vs_terms": "glacier"}).json())


# --------------------------------------------------------------------------- #
#  every public name has a caller (the S3 acceptance grep)
# --------------------------------------------------------------------------- #


def _module_tree() -> ast.Module:
    return ast.parse((ROOT / "src/analytics/conjunction.py").read_text(encoding="utf-8"))


def _public_names(tree: ast.Module) -> list[str]:
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names += [t.id for t in node.targets if isinstance(t, ast.Name) and not t.id.startswith("_")]
    return names


def _names_used_by_other_public_functions(tree: ast.Module, name: str) -> bool:
    """True when another PUBLIC function of the module uses ``name`` (``vocabulary_contrast`` is
    reached through ``set_contrast``, the one DB seam the API calls)."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_") and node.name != name:
            if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node)):
                return True
    return False


def test_every_public_name_of_the_lens_core_has_a_caller_outside_its_tests():
    tree = _module_tree()
    names = _public_names(tree)
    assert {"corpus_algebra", "set_contrast", "lens_scope", "ALGEBRA_OPS"} <= set(names)
    others = "\n".join(
        p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py")
        if p != ROOT / "src/analytics/conjunction.py"
    )
    missing = [
        n for n in names
        if not re.search(rf"\b{n}\b", others) and not _names_used_by_other_public_functions(tree, n)
    ]
    assert not missing, f"public names with no caller outside the tests: {missing}"
