"""Keyword families: canonicalisation + grouping into the mind-map / top lists.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Assert the deterministic, honest grouping: surface variants of one entity collapse
(Trump / Trump's / Donald Trump -> one family), but different kinds and topical
terms never get falsely merged, and the raw members stay listed.
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import families as fam_mod
from src.analytics import queries as q
from src.analytics.families import _lemma, build_families, canonical_key, strip_honorifics
from src.database.models import Article, Base, Keyword, KeywordMention, Source

# P4.3 lemmatization needs the optional simplemma ([analysis] extra). The unit + grouping
# tests below skip on a core install and run in CI / the analysis venv.
_HAS_SIMPLEMMA = fam_mod._simplemma is not None
_needs_simplemma = pytest.mark.skipif(not _HAS_SIMPLEMMA, reason="simplemma ([analysis]) not installed")


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


def test_plural_prefers_real_singular_over_bogus_es_stem():
    """Regression (keyword log 2026-06-17): 'states' merged into a stray 'stat'
    keyword instead of 'state', because the -es candidate ('stat') was tried
    before the -s candidate ('state') and that junk stem existed. -es is only a
    real plural for sibilant/-o bases (boxes->box, heroes->hero), so 'stat' is
    never offered and 'states' correctly joins 'state'."""
    items = [
        {"normalized": "state", "term": "state", "kind": "term", "mentions": 225},
        {"normalized": "states", "term": "states", "kind": "term", "mentions": 144},
        {"normalized": "stat", "term": "stat", "kind": "term", "mentions": 3},
        # genuine -es plurals (>=6 chars) must still collapse onto their sibilant/-o singular
        {"normalized": "dish", "term": "dish", "kind": "term", "mentions": 8},
        {"normalized": "dishes", "term": "dishes", "kind": "term", "mentions": 4},
        {"normalized": "hero", "term": "hero", "kind": "term", "mentions": 6},
        {"normalized": "heroes", "term": "heroes", "kind": "term", "mentions": 5},
    ]
    fams = build_families(items)
    assert _members(fams, "state") == {"state", "states"}  # not 'stat'
    assert _members(fams, "stat") == {"stat"}  # the junk stem stays standalone
    assert _members(fams, "dish") == {"dish", "dishes"}  # sibilant -es still merges
    assert _members(fams, "hero") == {"hero", "heroes"}  # -o -es still merges


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


# --------------------------------------------------------------------------- #
# P4.3: OPT-IN display-time lemmatization (study/studied -> study, Wahlen -> Wahl)
# --------------------------------------------------------------------------- #


@_needs_simplemma
def test_lemma_unit_lemmatizes_supported_langs_and_respects_guards():
    # supported languages, single-token terms
    assert _lemma("studied", "en") == "study"
    assert _lemma("running", "en") == "run"
    assert _lemma("Wahlen", "de") == "wahl"  # casefolded
    assert _lemma("élections", "fr") == "élection"
    # guards: denylisted meaning-changers, unknown/unsupported language, multi-token -> unchanged
    assert _lemma("media", "en") == "media"  # NOT "medium" (denylist)
    assert _lemma("data", "en") == "data"    # NOT "datum"
    assert _lemma("election", "zh") == "election"  # unsupported language -> no-op
    assert _lemma("climate change", "en") == "climate change"  # multi-token -> no-op
    assert _lemma("", "en") == ""


@_needs_simplemma
def test_lemma_collapses_verb_and_irregular_variants_when_enabled(monkeypatch):
    monkeypatch.setenv("OO_FAMILY_LEMMA", "1")
    items = [
        {"normalized": "study", "term": "study", "kind": "term", "language": "en", "mentions": 40},
        {"normalized": "studies", "term": "studies", "kind": "term", "language": "en", "mentions": 20},
        {"normalized": "studied", "term": "studied", "kind": "term", "language": "en", "mentions": 7},
        {"normalized": "children", "term": "children", "kind": "term", "language": "en", "mentions": 9},
        {"normalized": "child", "term": "child", "kind": "term", "language": "en", "mentions": 5},
        {"normalized": "climate", "term": "climate", "kind": "term", "language": "en", "mentions": 30},
    ]
    fams = build_families(items)
    # all three study-forms collapse (the plural rule alone would miss "studied")
    assert _members(fams, "study") == {"study", "studies", "studied"}
    assert _members(fams, "child") == {"child", "children"}  # irregular plural
    assert _members(fams, "climate") == {"climate"}  # unique lemma -> stands alone
    # the conflated family carries visible provenance; an unmerged one does not
    study_fam = next(f for f in fams if "study" in {m["normalized"] for m in f.members})
    climate_fam = next(f for f in fams if "climate" in {m["normalized"] for m in f.members})
    assert study_fam.conflated_by == ["lemma"]
    assert climate_fam.conflated_by == []
    assert "conflated_by" in study_fam.to_dict()


@_needs_simplemma
def test_lemma_is_on_by_default_and_opt_out_restores_byte_identical(monkeypatch):
    # Ruled 2026-07-18: lemmatization is ON BY DEFAULT (the measure-before-trust gate was
    # satisfied by a maintainer precision review of the live-corpus lemma_preview, not an
    # IR-harness A/B -- lemmatization is a display-layer change, invisible to retrieval).
    # "studied" is NOT a regular plural, so ONLY the lemma step (not the plural rule) can
    # merge it -- proving the default is really on, not an artifact of the plural heuristic.
    monkeypatch.delenv("OO_FAMILY_LEMMA", raising=False)
    items = [
        {"normalized": "study", "term": "study", "kind": "term", "language": "en", "mentions": 40},
        {"normalized": "studied", "term": "studied", "kind": "term", "language": "en", "mentions": 7},
    ]
    fams = build_families(items)
    assert _members(fams, "study") == {"study", "studied"}
    study_fam = next(f for f in fams if "study" in {m["normalized"] for m in f.members})
    assert study_fam.conflated_by == ["lemma"]

    # The reversibility half is load-bearing: OO_FAMILY_LEMMA=0 must restore the exact
    # pre-lemma (byte-identical) grouping -- the opt-OUT, not just an opt-in that happens
    # to default on.
    monkeypatch.setenv("OO_FAMILY_LEMMA", "0")
    fams_off = build_families(items)
    assert _members(fams_off, "study") == {"study"}
    assert _members(fams_off, "studied") == {"studied"}
    assert all(f.conflated_by == [] for f in fams_off)


def test_lemma_off_by_default_without_simplemma_installed(monkeypatch):
    # A core install (simplemma absent) must be byte-identical regardless of the new
    # default -- _lemma_enabled() checks `_simplemma is not None` before the env var, so
    # the on-by-default flip can never fabricate a merge without the optional dependency.
    monkeypatch.delenv("OO_FAMILY_LEMMA", raising=False)
    monkeypatch.setattr(fam_mod, "_simplemma", None)
    items = [
        {"normalized": "study", "term": "study", "kind": "term", "language": "en", "mentions": 40},
        {"normalized": "studied", "term": "studied", "kind": "term", "language": "en", "mentions": 7},
    ]
    fams = build_families(items)
    assert _members(fams, "study") == {"study"}
    assert _members(fams, "studied") == {"studied"}
    assert all(f.conflated_by == [] for f in fams)


@_needs_simplemma
def test_lemma_never_merges_entities_or_denylisted_and_is_reversible(monkeypatch):
    monkeypatch.setenv("OO_FAMILY_LEMMA", "1")
    items = [
        # entity NAMES that would lemma-collapse must NOT merge (a name plural is a referent)
        {"normalized": "leaders", "term": "Leaders", "kind": "org", "language": "en", "mentions": 8},
        {"normalized": "leader", "term": "Leader", "kind": "org", "language": "en", "mentions": 6},
        # denylisted: media must not become medium
        {"normalized": "media", "term": "media", "kind": "term", "language": "en", "mentions": 20},
        {"normalized": "medium", "term": "medium", "kind": "term", "language": "en", "mentions": 4},
        # plain terms in a supported language DO merge (and are reversible, below)
        {"normalized": "studied", "term": "studied", "kind": "term", "language": "en", "mentions": 7},
        {"normalized": "study", "term": "study", "kind": "term", "language": "en", "mentions": 9},
    ]
    fams = build_families(items)
    assert _members(fams, "leaders") == {"leaders"}  # entity names never lemma-merge
    assert _members(fams, "media") == {"media"}      # denylist holds
    assert _members(fams, "medium") == {"medium"}
    assert _members(fams, "study") == {"study", "studied"}  # terms do merge
    # reversible: a split override on "studied" keeps it standalone even with lemma on
    fams2 = build_families(items, {"studied": {"family_key": "studied", "label": None, "kind": "term"}})
    assert _members(fams2, "studied") == {"studied"}
    assert _members(fams2, "study") == {"study"}


def test_lemma_degrades_gracefully_without_simplemma(monkeypatch):
    # Even with the feature enabled, a missing simplemma is a no-op (never a crash) — the
    # core-install path. Force the absent-dependency branch regardless of what's installed.
    monkeypatch.setenv("OO_FAMILY_LEMMA", "1")
    monkeypatch.setattr(fam_mod, "_simplemma", None)
    items = [
        {"normalized": "study", "term": "study", "kind": "term", "language": "en", "mentions": 40},
        {"normalized": "studied", "term": "studied", "kind": "term", "language": "en", "mentions": 7},
    ]
    fams = build_families(items)
    assert _members(fams, "study") == {"study"} and _members(fams, "studied") == {"studied"}
    assert _lemma("studied", "en") == "studied"  # no-op without the lemmatizer


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
