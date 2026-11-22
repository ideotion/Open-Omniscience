"""Row 185, S07-03 S1 (the report half): the law coverage report covers every country of the world, not only the floor.

The floor block keeps its countries and its numbers; the new ``world`` block takes every other ISO 3166-1 country (plus
Kosovo's ``xk``) with the floor's same four states, so the two blocks together place each country exactly once. What this pins
is the negative space: no country in both blocks, none in neither, an unreadable catalogue is unchecked and never "no
source", a tracked code neither block lists is named rather than dropped, and no fraction exists in the block.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from sqlalchemy.orm import sessionmaker

from src.catalog.countries import ISO_3166_1_ALPHA2
from src.civic.coverage_floor import load_floor
from src.database.models import Base, LawDocument
from src.law.catalog import load_legal_catalog, source_is_law_authority, source_is_verified
from src.law.coverage import (
    FLOOR_NO_SOURCE,
    FLOOR_STATES,
    FLOOR_TRACKED,
    FLOOR_UNCHECKED,
    FLOOR_UNVERIFIED,
    FLOOR_VERIFIED_UNTRACKED,
    floor_report,
    law_coverage_report,
    world_report,
)
from tests._app_engine import app_sqlite_engine

_NO_POP = {"status": "absent", "reason": "no population table has been placed (an operator step)", "weights": {}}


def _floor(*codes):
    return {"as_of": "2026-01-01", "verification_status": "test", "countries": sorted(codes),
            "languages": {"en": {"name": "en", "source": "t", "countries": [{"cc": c, "basis": "official"} for c in codes]}},
            "invalid": [], "contested": []}


def _src(domain, country, *, tier=None, kind="legal"):
    row: dict = {"domain": domain, "country": country, "source_type": kind}
    if tier:
        row["verified"] = {"tier": tier, "as_of": "2026-01-01", "method": "test"}
    return row


def _doc(country, category="legislation"):
    return SimpleNamespace(jurisdiction=country or "xx", country=country, language=None, category=category)


def _states(block):
    return {cc: st for st, ccs in block["by_state"].items() for cc in (ccs or [])}


def _session():
    engine = app_sqlite_engine(":memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_the_world_block_takes_every_country_off_the_floor_once():
    floor = _floor("fr", "gb")
    block = world_report([], {"sources": []}, floor, population=_NO_POP)
    placed = _states(block)
    assert set(placed) == (set(ISO_3166_1_ALPHA2) | {"xk"}) - {"fr", "gb"}
    assert block["countries"] == len(placed) == sum(block["states"].values())
    assert block["floor_countries_excluded"] == 2
    assert "fr" not in placed and "xk" in placed and "aq" in placed  # ISO lists territories and uninhabited codes


def test_floor_and_world_together_place_each_country_exactly_once_on_the_real_files():
    s = _session()
    rep = law_coverage_report(s, enumerations={})
    floor_cc = set(_states(rep["floor"]))
    world_cc = set(_states(rep["world"]))
    assert not floor_cc & world_cc, "no country is in both blocks"
    assert (floor_cc | world_cc) >= set(ISO_3166_1_ALPHA2), "every ISO country is in one of them"
    assert rep["world"]["countries"] + rep["world"]["floor_countries_excluded"] == len(set(ISO_3166_1_ALPHA2) | {"xk"})
    assert rep["world"]["state"] == "checked" and set(rep["world"]["states"]) == set(FLOOR_STATES)


def test_the_floor_block_is_unchanged_by_the_world_block():
    s = _session()
    s.add(LawDocument(jurisdiction="fr", title="Loi", url="https://law.example/fr", country="fr"))
    s.commit()
    rep = law_coverage_report(s, enumerations={})
    catalog = load_legal_catalog()
    docs = s.query(LawDocument).all()
    from src.stats.population import load_population_table

    assert rep["floor"] == floor_report(docs, catalog, population=load_population_table())


def test_the_world_states_are_read_the_same_way_as_the_floor():
    catalog = {"sources": [
        _src("a.example", "ar"),                                   # listed, none verified: unverified
        _src("b.example", "br", tier="live"),                      # verified, nothing tracked
        _src("c.example", "cl", kind="ip"),                        # an IP office is not a law authority: no source
        _src("eu.example", "eu", tier="live"),                     # many-country: credits no country
    ]}
    placed = _states(world_report([_doc("it")], catalog, _floor("fr"), population=_NO_POP))
    assert (placed["ar"], placed["br"], placed["cl"]) == (FLOOR_UNVERIFIED, FLOOR_VERIFIED_UNTRACKED, FLOOR_NO_SOURCE)
    assert placed["it"] == FLOOR_TRACKED and placed["de"] == FLOOR_NO_SOURCE
    assert "eu" not in placed and "int" not in placed


def test_an_unreadable_catalogue_leaves_the_world_unchecked_never_no_source():
    block = world_report([_doc("it")], None, _floor("fr"), reason="the catalogue could not be read", population=_NO_POP)
    assert block["state"] == "unchecked" and block["reason"] == "the catalogue could not be read"
    assert block["by_state"][FLOOR_NO_SOURCE] is None and block["by_state"][FLOOR_TRACKED] == ["it"]
    assert len(block["by_state"][FLOOR_UNCHECKED]) == block["countries"] - 1


def test_the_report_with_an_unreadable_catalogue_keeps_the_world_unchecked(monkeypatch):
    from src.law import catalog as law_catalog

    def boom(*_a, **_k):
        raise law_catalog.LawCatalogUnreadable("the law catalogue legal_sources.yml could not be read (PermissionError)")

    monkeypatch.setattr(law_catalog, "load_legal_catalog", boom)
    world = law_coverage_report(_session())["world"]
    assert world["state"] == "unchecked" and "PermissionError" in world["reason"]
    assert world["by_state"][FLOOR_NO_SOURCE] is None and world["by_state"][FLOOR_UNCHECKED]


def test_a_tracked_code_neither_block_lists_is_named_not_dropped():
    block = world_report([_doc("zz"), _doc("it"), _doc("", category="legislation")], {"sources": []}, _floor("fr"),
                         population=_NO_POP)
    assert block["tracked_codes_not_listed"] == ["zz"]
    assert _states(block)["it"] == FLOOR_TRACKED


def test_a_tracked_ip_or_case_law_document_credits_no_country_in_the_world_either():
    block = world_report([_doc("it", category="ip"), _doc("es", category="case-law")], {"sources": []}, _floor("fr"),
                         population=_NO_POP)
    assert _states(block)["it"] == FLOOR_NO_SOURCE and _states(block)["es"] == FLOOR_NO_SOURCE


def test_with_no_floor_every_country_is_in_the_world_and_the_block_says_why():
    block = world_report([], {"sources": []}, {"countries": []}, population=_NO_POP)
    # row 279: no floor was read, so how many were set aside is unknown (None), never 0
    assert block["countries"] == len(set(ISO_3166_1_ALPHA2) | {"xk"}) and block["floor_countries_excluded"] is None
    assert block["floor"] == {"state": "empty"}
    assert "no country is set aside" in block["floor_note"]


def test_within_a_state_countries_go_by_population_and_the_order_says_so():
    pop = {"status": "ok", "reason": None, "weights": {"de": 80.0, "it": 60.0, "br": 200.0}, "source": "UN WPP (test)",
           "as_of": "2024-07-11"}
    block = world_report([], {"sources": []}, _floor("fr"), population=pop)
    assert block["by_state"][FLOOR_NO_SOURCE][:3] == ["br", "de", "it"]
    assert block["order"]["by"] == "population" and "br" not in block["order"]["missing"]
    assert "200" not in json.dumps(block), "the order is stated, not the populations"


def test_no_fraction_or_score_and_the_block_stays_inside_its_byte_ceiling():
    block = law_coverage_report(_session(), enumerations={})["world"]
    text = json.dumps(block, separators=(",", ":"), ensure_ascii=False)
    for word in ("score", "share", "ratio", "percent", "rating"):
        assert f'"{word}' not in text
    assert not any(isinstance(v, float) for v in block["states"].values())
    # Measured at ship: the shipped catalogue with no population table. Every code is listed once in by_state (and, with a
    # population table, the ones it lacks once more in order.missing), so the ceiling leaves room for that second list.
    assert len(text.encode()) <= 4_000, f"the world block is {len(text.encode()):,} bytes; measure the diagnostics room again"


def test_the_real_world_states_agree_with_an_independent_reading_of_the_catalogue():
    rep = law_coverage_report(_session(), enumerations={})["world"]
    placed = _states(rep)
    law_rows = [x for x in load_legal_catalog()["sources"] if source_is_law_authority(x)]
    with_source = {str(x.get("country") or "").strip().lower() for x in law_rows}
    for cc, st in placed.items():
        assert (st == FLOOR_NO_SOURCE) == (cc not in with_source), cc
        if st in (FLOOR_VERIFIED_UNTRACKED, FLOOR_UNVERIFIED):
            mine = [x for x in law_rows if str(x.get("country") or "").strip().lower() == cc]
            assert (st == FLOOR_VERIFIED_UNTRACKED) == any(source_is_verified(x) for x in mine), cc
    assert load_floor()["countries"], "the shipped floor is readable, so this compares the off-floor countries"


def test_the_codes_with_no_permanent_population_keep_their_state_and_are_named_apart():
    from src.law.coverage import WORLD_NO_PERMANENT_POPULATION

    block = world_report([], {"sources": []}, _floor("fr"), population=_NO_POP)
    assert block["no_permanent_population"] == list(WORLD_NO_PERMANENT_POPULATION)
    placed = _states(block)
    assert all(placed[cc] == FLOOR_NO_SOURCE for cc in WORLD_NO_PERMANENT_POPULATION), "still placed, never dropped"
    assert set(WORLD_NO_PERMANENT_POPULATION) <= set(ISO_3166_1_ALPHA2)
    assert "no_permanent_population" in block["method"] and "not research to do" in block["caveat"]
    # R752: they keep their entry and state, and the research count leaves them out.
    n_none = len(block["by_state"][FLOOR_NO_SOURCE])
    assert block["no_eligible_source_no_permanent_population"] == len(WORLD_NO_PERMANENT_POPULATION)
    assert block["no_eligible_source_to_research"] == n_none - len(WORLD_NO_PERMANENT_POPULATION)
    assert block["states"][FLOOR_NO_SOURCE] == n_none, "the state count itself is unchanged"


def test_a_code_with_no_permanent_population_that_has_a_source_is_not_subtracted_from_research():
    block = world_report([], {"sources": [_src("aq.example", "aq", tier="live")]}, _floor("fr"), population=_NO_POP)
    assert _states(block)["aq"] == FLOOR_VERIFIED_UNTRACKED
    assert block["no_eligible_source_no_permanent_population"] == 6
    assert block["no_eligible_source_to_research"] == len(block["by_state"][FLOOR_NO_SOURCE]) - 6


def test_hong_kong_and_macau_are_in_the_world_and_beside_zh_with_the_same_state():
    rep = law_coverage_report(_session(), enumerations={})
    world = _states(rep["world"])
    for cc, st in rep["floor"]["zh_beyond_floor"].items():
        assert world[cc] == st, cc


def test_the_byte_ceiling_holds_with_a_population_table_that_lacks_every_country():
    """The worst case for size: a usable table that names none of the world's countries, so order.missing lists them all."""
    pop = {"status": "ok", "reason": None, "weights": {"fr": 1.0}, "source": "UN WPP (test)", "as_of": "2024-07-11"}
    block = world_report([], load_legal_catalog(), load_floor(), population=pop)
    assert len(block["order"]["missing"]) == block["countries"]
    size = len(json.dumps(block, separators=(",", ":"), ensure_ascii=False).encode())
    assert size <= 4_000, f"the world block is {size:,} bytes at its widest; measure the diagnostics room again"


def test_an_unreadable_catalogue_reads_the_population_table_once(monkeypatch):
    from src.law import catalog as law_catalog
    from src.stats import population as pop_mod

    calls: list[int] = []
    real = pop_mod.load_population_table

    def counted(*a, **k):
        calls.append(1)
        return real(*a, **k)

    def boom(*_a, **_k):
        raise law_catalog.LawCatalogUnreadable("unreadable (test)")

    monkeypatch.setattr(pop_mod, "load_population_table", counted)
    monkeypatch.setattr(law_catalog, "load_legal_catalog", boom)
    law_coverage_report(_session())
    assert calls == [1], "the floor and the world order by the one table read"
