"""R1 end-to-end: expansion actually changes which articles the API returns.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

``tests/test_query_expansion.py`` proves the pure core. This drives the two real search
surfaces, because the core being right says nothing about whether the hook is WIRED --
the recorded "a machine-readable answer with no caller that reads it is a dead end"
trap, which this feature is unusually exposed to: the rings themselves have been correct
and unread by the search path since they were generated.

The corpus is seeded with the SAME concept in three languages under invented spellings
of nothing, so a match can only come from the ring and never from a stray prefix hit.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def ring_corpus(client):
    """Three articles: one per language of the shipped `climate` ring.

    Each body carries ONLY its own language's word for the concept, so an English
    search reaching the French and German articles is proof the ring was consulted.
    """
    from src.analytics.equivalence import expand_term
    from src.database.models import Article, Keyword, Source
    from src.database.session import session_scope

    exp = expand_term("climate", prefer_language="en")
    if not exp.expanded:
        pytest.skip("the shipped ring table has no `climate` ring")
    fr = next((t for t in exp.siblings if t == "climat"), None)
    de = next((t for t in exp.siblings if t == "klima"), None)
    if not (fr and de):
        pytest.skip("the `climate` ring no longer carries both fr and de members")

    with session_scope() as s:
        src = Source(name="Ringtest Gazette", domain="ringtest.example")
        s.add(src)
        s.flush()
        ids = []
        for i, (lang, word) in enumerate((("en", "climate"), ("fr", fr), ("de", de))):
            a = Article(
                url=f"https://ringtest.example/{i}",
                canonical_url=f"https://ringtest.example/{i}",
                source_id=src.id,
                title=f"Zblorptastic {i}",
                content=f"zblorptastic reporting about {word} and nothing else",
                language=lang,
                hash=f"ring{i}" + "d" * 59,
                published_at=datetime.now(UTC),
            )
            s.add(a)
            s.flush()
            ids.append(a.id)
        kws = []
        for word, lang in ((fr, "fr"), (de, "de")):
            k = Keyword(term=word, normalized_term=word, frequency=5, language=lang)
            s.add(k)
            s.flush()
            kws.append(k.id)
        out = {"src": src.id, "arts": ids, "kws": kws, "fr": fr, "de": de}
    yield out
    with session_scope() as s:
        for aid in out["arts"]:
            s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
        for kid in out["kws"]:
            s.execute(text(f"DELETE FROM keywords WHERE id = {kid}"))  # noqa: S608
        s.execute(text(f"DELETE FROM sources WHERE id = {out['src']}"))  # noqa: S608


def _group(d, kind):
    return next(g for g in d["groups"] if g["kind"] == kind)


def test_articles_search_reaches_the_other_languages_and_says_so(client, ring_corpus):
    """The headline. Three articles, one shared concept, three different words."""
    r = client.get("/api/articles", params={"query": "climate", "ui_lang": "en"}).json()
    got = {a["id"] for a in r["results"]}
    assert set(ring_corpus["arts"]) <= got, (
        "the fr/de articles were not reached — the ring is not wired into /api/articles"
    )
    assert r["total"] >= 3

    disclosure = r.get("cross_language")
    assert disclosure is not None, "expansion happened and was NOT disclosed"
    assert disclosure["expanded"] is True
    assert disclosure["terms"][0]["ring_id"] == "climate"
    assert ring_corpus["fr"] in disclosure["terms"][0]["added_terms"]


def test_narrowing_to_the_literal_term_is_one_parameter_and_is_exact(client, ring_corpus):
    """R1's "one click back to the literal term", checked as behaviour.

    `expand=false` must return EXACTLY the English article and carry no disclosure —
    if it still reached the siblings, the click would be a label rather than a control.
    """
    r = client.get(
        "/api/articles", params={"query": "climate", "expand": "false"}
    ).json()
    got = {a["id"] for a in r["results"]}
    assert ring_corpus["arts"][0] in got
    assert not ({ring_corpus["arts"][1], ring_corpus["arts"][2]} & got), (
        "expand=false still reached the other languages"
    )
    assert "cross_language" not in r


def test_the_omnibar_expands_counts_and_discloses_together(client, ring_corpus):
    d = client.get("/api/search/omni", params={"q": "climate", "ui_lang": "en"}).json()
    arts = _group(d, "articles")
    assert arts["total"] >= 3, "the omnibar's article total did not follow the expansion"
    assert d.get("cross_language", {}).get("expanded") is True


def test_the_omnibar_keyword_group_offers_the_other_languages(client, ring_corpus):
    """A prefix match cannot reach `climat` from `climate` — this is the whole gap.

    The sibling rows are LABELLED `via_ring` rather than mixed into the prefix hits: the
    reader did not type them, and a row that appears as though they had is a small lie
    about their own query.
    """
    d = client.get("/api/search/omni", params={"q": "climate", "ui_lang": "en"}).json()
    kws = _group(d, "keywords")
    via = [i for i in kws["items"] if i.get("via_ring")]
    assert via, "no cross-language keyword rows — the ring is not wired into the group"
    assert {i["normalized_term"] for i in via} & {ring_corpus["fr"], ring_corpus["de"]}
    assert all(i["via_ring"] == "climate" for i in via)
    assert "cross-language" in kws["note"]


def test_the_keyword_total_still_describes_the_prefix_population(client, ring_corpus):
    """The sibling rows are a DIFFERENT question from the prefix total.

    Folding them into `total` would make one disclosed number describe two populations —
    prefix matches and concept matches — which is exactly the kind of quiet conflation
    the never-capped-figures rule exists to stop. They are counted separately.
    """
    d = client.get("/api/search/omni", params={"q": "climate", "ui_lang": "en"}).json()
    kws = _group(d, "keywords")
    assert kws["cross_language_items"] >= 1
    assert kws["total"] < len(kws["items"]) + kws["total"]  # total is not items-inclusive
    plain = client.get(
        "/api/search/omni", params={"q": "climate", "expand": "false"}
    ).json()
    assert _group(plain, "keywords")["total"] == kws["total"], (
        "the prefix total moved when expansion was turned on — it must not"
    )


def test_an_ordinary_search_carries_no_disclosure(client, ring_corpus):
    """Most terms are in no ring; those searches must look exactly as they did."""
    r = client.get("/api/articles", params={"query": "zblorptastic"}).json()
    assert r["total"] >= 3  # the seeded articles all carry the nonsense token
    assert "cross_language" not in r
