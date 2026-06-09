"""Keyword families: canonicalisation + grouping into the mind-map / top lists.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Assert the deterministic, honest grouping: surface variants of one entity collapse
(Trump / Trump's / Donald Trump -> one family), but different kinds and topical
terms never get falsely merged, and the raw members stay listed.
"""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.analytics.families import build_families, canonical_key, strip_honorifics
from src.database.models import Article, Base, Keyword, KeywordMention, Source


def test_canonical_key_and_honorifics():
    assert canonical_key("trump's") == "trump"
    assert canonical_key("workers'") == "workers"      # plural possessive keeps the s
    assert canonical_key("inflation") == "inflation"
    assert strip_honorifics("president donald trump") == "donald trump"
    assert strip_honorifics("trump") == "trump"


def test_families_merge_variants_same_kind_only():
    items = [
        {"normalized": "trump", "term": "Trump", "kind": "person", "mentions": 50},
        {"normalized": "trump's", "term": "Trump's", "kind": "person", "mentions": 12},
        {"normalized": "donald trump", "term": "Donald Trump", "kind": "person", "mentions": 30},
        {"normalized": "president donald trump", "term": "President Donald Trump",
         "kind": "person", "mentions": 8},
        {"normalized": "trump administration", "term": "Trump administration",
         "kind": "org", "mentions": 15},
        {"normalized": "paris", "term": "Paris", "kind": "location", "mentions": 20},
        {"normalized": "paris hilton", "term": "Paris Hilton", "kind": "person", "mentions": 5},
        {"normalized": "climate", "term": "climate", "kind": "term", "mentions": 40},
        {"normalized": "climate policy", "term": "climate policy", "kind": "term", "mentions": 10},
    ]
    fams = {(f.canonical, f.kind): f for f in build_families(items)}

    trump = next(f for (name, k), f in fams.items() if k == "person" and "Trump" in name)
    assert trump.variant_count == 4 and trump.mentions == 100   # 50+12+30+8

    assert ("Trump administration", "org") in fams                # different concept, kept
    assert fams[("Paris", "location")].variant_count == 1         # not merged into the person
    assert fams[("climate", "term")].variant_count == 1           # topical terms never subsumed
    assert fams[("climate policy", "term")].variant_count == 1


def _kw(s, term, normalized, *, kind):
    k = Keyword(term=term, normalized_term=normalized, language="en", frequency=0,
                is_entity=(kind != "term"), entity_type=(None if kind == "term" else kind))
    s.add(k)
    s.flush()
    return k


def test_associations_grouping_merges_entity_variants():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        arts = []
        for i in range(4):
            a = Article(url=f"https://s.test/{i}", canonical_url=f"https://s.test/{i}",
                        source_id=1, title=f"t{i}", content="x", hash=f"h{i}")
            s.add(a)
            arts.append(a)
        s.flush()
        policy = _kw(s, "policy", "policy", kind="term")
        trump = _kw(s, "Trump", "trump", kind="person")
        donald = _kw(s, "Donald Trump", "donald trump", kind="person")
        # All four articles mention policy + both Trump surface forms (co-occurrence).
        for a in arts:
            for kw in (policy, trump, donald):
                s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1,
                                     observed_on=date.today()))
        s.commit()

        ungrouped = q.associations(s, "policy", min_cooccur=1, group=False)["pairs"]
        grouped = q.associations(s, "policy", min_cooccur=1, group=True)["pairs"]

    # Ungrouped: two separate Trump neighbours; grouped: one family of two.
    assert {p["normalized"] for p in ungrouped} == {"trump", "donald trump"}
    assert len(grouped) == 1
    fam = grouped[0]
    assert fam["variants"] == 2
    assert set(fam["members"]) == {"Trump", "Donald Trump"}
