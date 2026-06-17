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
    assert canonical_key("workers'") == "workers"  # plural possessive keeps the s
    assert canonical_key("inflation") == "inflation"
    assert strip_honorifics("president donald trump") == "donald trump"
    assert strip_honorifics("trump") == "trump"


def test_families_merge_variants_same_kind_only():
    items = [
        {"normalized": "trump", "term": "Trump", "kind": "person", "mentions": 50},
        {"normalized": "trump's", "term": "Trump's", "kind": "person", "mentions": 12},
        {"normalized": "donald trump", "term": "Donald Trump", "kind": "person", "mentions": 30},
        {
            "normalized": "president donald trump",
            "term": "President Donald Trump",
            "kind": "person",
            "mentions": 8,
        },
        {
            "normalized": "trump administration",
            "term": "Trump administration",
            "kind": "org",
            "mentions": 15,
        },
        {"normalized": "paris", "term": "Paris", "kind": "location", "mentions": 20},
        {"normalized": "paris hilton", "term": "Paris Hilton", "kind": "person", "mentions": 5},
        {"normalized": "climate", "term": "climate", "kind": "term", "mentions": 40},
        {"normalized": "climate policy", "term": "climate policy", "kind": "term", "mentions": 10},
    ]
    fams = {(f.canonical, f.kind): f for f in build_families(items)}

    trump = next(f for (name, k), f in fams.items() if k == "person" and "Trump" in name)
    assert trump.variant_count == 4 and trump.mentions == 100  # 50+12+30+8

    assert ("Trump administration", "org") in fams  # different concept, kept
    assert fams[("Paris", "location")].variant_count == 1  # not merged into the person
    assert fams[("climate", "term")].variant_count == 1  # topical terms never subsumed
    assert fams[("climate policy", "term")].variant_count == 1


def _members(fams, stem):
    f = next(f for f in fams if stem in {m["normalized"] for m in f.members})
    return {m["normalized"] for m in f.members}


def test_plural_collapses_into_singular_term_family():
    items = [
        {"normalized": "state", "term": "state", "kind": "term", "mentions": 100},
        {"normalized": "states", "term": "states", "kind": "term", "mentions": 56},
        {"normalized": "country", "term": "country", "kind": "term", "mentions": 40},
        {"normalized": "countries", "term": "countries", "kind": "term", "mentions": 13},
        {"normalized": "climate", "term": "climate", "kind": "term", "mentions": 30},
    ]
    fams = build_families(items)
    assert _members(fams, "state") == {"state", "states"}
    assert _members(fams, "country") == {"country", "countries"}  # -ies -> -y
    assert _members(fams, "climate") == {"climate"}  # no plural -> stands alone
    state_fam = next(f for f in fams if f.normalized == "state")
    assert state_fam.mentions == 156  # 100 + 56


def test_plural_never_merges_entities_or_denylisted_bases():
    items = [
        {"normalized": "tiger", "term": "Tiger", "kind": "org", "mentions": 5},
        {"normalized": "tigers", "term": "Tigers", "kind": "org", "mentions": 9},
        {"normalized": "mean", "term": "mean", "kind": "term", "mentions": 10},
        {"normalized": "means", "term": "means", "kind": "term", "mentions": 20},
    ]
    fams = build_families(items)
    assert _members(fams, "tiger") == {"tiger"}  # entity NAME plural: never merged
    assert _members(fams, "tigers") == {"tigers"}
    assert _members(fams, "mean") == {"mean"}  # denylisted base (mean/means differ)
    assert _members(fams, "means") == {"means"}


def test_plural_merge_respects_override_and_env(monkeypatch):
    items = [
        {"normalized": "state", "term": "state", "kind": "term", "mentions": 100},
        {"normalized": "states", "term": "states", "kind": "term", "mentions": 56},
    ]
    # a split override on "states" keeps it standalone (any override excludes a form
    # from the auto plural pass)
    fams = build_families(items, {"states": {"family_key": "states", "label": None, "kind": "term"}})
    assert _members(fams, "states") == {"states"}
    # the env kill-switch disables the whole pass
    monkeypatch.setenv("OO_FAMILY_PLURALS", "0")
    assert all(f.variant_count == 1 for f in build_families(items))


def test_overrides_force_merge_and_split():
    items = [
        {"normalized": "world bank", "term": "World Bank", "kind": "org", "mentions": 30},
        {"normalized": "wb", "term": "WB", "kind": "org", "mentions": 10},
        {"normalized": "trump", "term": "Trump", "kind": "person", "mentions": 50},
        {"normalized": "donald trump", "term": "Donald Trump", "kind": "person", "mentions": 30},
    ]
    # Merge "WB" into "World Bank" (auto rules never would — no shared tokens);
    # split "trump" out of the auto Trump family.
    overrides = {
        "world bank": {"family_key": "world bank", "label": "World Bank", "kind": "org"},
        "wb": {"family_key": "world bank", "label": "World Bank", "kind": "org"},
        "trump": {"family_key": "__alone__:trump", "label": "Trump", "kind": "person"},
    }
    fams = {f.canonical: f for f in build_families(items, overrides)}
    wb = fams["World Bank"]
    assert wb.variant_count == 2 and wb.manual is True and wb.mentions == 40
    # trump pinned alone; donald trump stays its own auto family (not merged with trump)
    trump = next(f for f in fams.values() if f.normalized == "__alone__:trump")
    assert trump.variant_count == 1 and trump.manual is True
    assert fams["Donald Trump"].variant_count == 1


def _kw(s, term, normalized, *, kind):
    k = Keyword(
        term=term,
        normalized_term=normalized,
        language="en",
        frequency=0,
        is_entity=(kind != "term"),
        entity_type=(None if kind == "term" else kind),
    )
    s.add(k)
    s.flush()
    return k


def test_associations_grouping_merges_entity_variants():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Src", domain="s.test"))
        s.flush()
        arts = []
        for i in range(4):
            a = Article(
                url=f"https://s.test/{i}",
                canonical_url=f"https://s.test/{i}",
                source_id=1,
                title=f"t{i}",
                content="x",
                hash=f"h{i}",
            )
            s.add(a)
            arts.append(a)
        s.flush()
        policy = _kw(s, "policy", "policy", kind="term")
        trump = _kw(s, "Trump", "trump", kind="person")
        donald = _kw(s, "Donald Trump", "donald trump", kind="person")
        # All four articles mention policy + both Trump surface forms (co-occurrence).
        for a in arts:
            for kw in (policy, trump, donald):
                s.add(
                    KeywordMention(
                        keyword_id=kw.id, article_id=a.id, count=1, observed_on=date.today()
                    )
                )
        s.commit()

        ungrouped = q.associations(s, "policy", min_cooccur=1, group=False)["pairs"]
        grouped = q.associations(s, "policy", min_cooccur=1, group=True)["pairs"]

    # Ungrouped: two separate Trump neighbours; grouped: one family of two.
    assert {p["normalized"] for p in ungrouped} == {"trump", "donald trump"}
    assert len(grouped) == 1
    fam = grouped[0]
    assert fam["variants"] == 2
    assert set(fam["members"]) == {"Trump", "Donald Trump"}


def test_family_override_api_merge_split_and_clear(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ov.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            # Merge needs >= 2 forms.
            assert (
                c.post("/api/insights/family/merge", json={"normalized": ["wb"]}).status_code == 400
            )
            r = c.post(
                "/api/insights/family/merge",
                json={"normalized": ["World Bank", "WB"], "label": "World Bank", "kind": "org"},
            ).json()
            assert set(r["merged"]) == {"world bank", "wb"}

            c.post("/api/insights/family/split", json={"normalized": "Trump", "kind": "person"})

            ov = c.get("/api/insights/family/overrides").json()
            assert ov["count"] == 3
            keys = {f["family_key"] for f in ov["families"]}
            assert "__alone__:trump" in keys
            assert any(f["split"] for f in ov["families"])

            # Clear the split -> back to automatic.
            d = c.request(
                "DELETE", "/api/insights/family/override", params={"normalized": "trump"}
            ).json()
            assert d["deleted"] == 1
            assert c.get("/api/insights/family/overrides").json()["count"] == 2
    finally:
        app.dependency_overrides.clear()
