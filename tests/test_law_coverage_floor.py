"""
v0.6.0 row C slice S1 (Q107, Q912): the coverage-floor report -- for every country the twelve UI languages put on the floor
(``configs/language_countries.yml``), where it stands: tracked, verified-not-yet-tracked, unverified or no-eligible-source,
never a blank, plus the twelve-language tally and zh as its own line.

What this pins is the NEGATIVE space: a many-country source credits no single country, a document that states no country
credits none, an IP office or a case-law site makes no country's law reachable, a catalogue that could not be read is
UNCHECKED and never "no source", a country is never counted twice, and no fraction exists anywhere in the block.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.civic.coverage_floor import load_floor
from src.database.models import Base, LawDocument
from src.law import coverage
from src.law.catalog import source_is_law_authority, source_is_verified
from src.law.coverage import (
    FLOOR_NO_SOURCE,
    FLOOR_STATES,
    FLOOR_TRACKED,
    FLOOR_UNCHECKED,
    FLOOR_UNVERIFIED,
    FLOOR_VERIFIED_UNTRACKED,
    ZH_NAMED_BEYOND_FLOOR,
    floor_report,
    law_coverage_report,
)
from tests.js_source_helper import function_body, python_function_source


def _floor(**langs):
    """A crafted floor: ``_floor(en=[("gb", "official"), ("ie", "de-facto")], zh=[("tw", "regional", True)])`` -- a third
    element marks the row contested."""
    languages = {
        code: {
            "name": code,
            "source": "test",
            "countries": [
                {"cc": row[0], "basis": row[1], **({"contested": True} if len(row) > 2 else {})} for row in rows
            ],
        }
        for code, rows in langs.items()
    }
    return {
        "as_of": "2026-01-01",
        "verification_status": "drafted for a test",
        "languages": languages,
        "countries": sorted({e["cc"] for b in languages.values() for e in b["countries"]}),
        "invalid": [],
        "contested": [],
    }


def _src(domain, country, *, status=None, tier=None, kind="legal"):
    row: dict = {"domain": domain, "country": country, "source_type": kind}
    if status:
        row["verification"] = {"status": status}
    if tier:
        row["verified"] = {"tier": tier, "as_of": "2026-01-01", "method": "test"}
    return row


def _doc(jurisdiction, country, language=None, category="legislation"):
    return SimpleNamespace(jurisdiction=jurisdiction, country=country, language=language, category=category)


def _states(report):
    return {cc: st for st, ccs in report["by_state"].items() for cc in ccs}


# --- the four states -------------------------------------------------------------------------------------------------------


def test_each_floor_country_is_in_exactly_one_of_the_four_states():
    floor = _floor(
        en=[("aa", "official"), ("bb", "official"), ("cc", "de-facto"), ("dd", "regional"), ("ee", "official")],
    )
    catalog = {
        "sources": [
            _src("aa.example", "aa", status="fetched"),
            _src("bb.example", "bb", status="fetched"),
            _src("cc.example", "cc", status="lead"),
            _src("dd.example", "dd"),
        ]
    }
    rep = floor_report([_doc("aa", "aa")], catalog, floor)
    got = _states(rep)
    assert got == {
        "aa": FLOOR_TRACKED,  # a document states it
        "bb": FLOOR_VERIFIED_UNTRACKED,  # a verified law-authority source, nothing tracked
        "cc": FLOOR_UNVERIFIED,  # a source, only a lead
        "dd": FLOOR_UNVERIFIED,  # a source, nothing recorded at all
        "ee": FLOOR_NO_SOURCE,  # none listed: a state, not a blank
    }
    assert set(rep["by_state"]) == set(FLOOR_STATES)
    assert sum(len(v) for v in rep["by_state"].values()) == rep["countries"] == 5, "every country once, none dropped"


def test_a_tracked_document_wins_over_every_catalogue_state():
    """A country with a document is tracked even where the catalogue lists no source for it: the install holds the document."""
    rep = floor_report([_doc("zz", "ee")], {"sources": []}, _floor(en=[("ee", "official")]))
    assert _states(rep) == {"ee": FLOOR_TRACKED}


def test_the_country_of_a_document_is_read_case_insensitively_and_never_from_the_jurisdiction_code():
    """`uk` documents state `gb`: the jurisdiction code is "ISO-ish" and reading it as a country would credit the wrong one."""
    floor = _floor(en=[("gb", "official"), ("uk", "official")])
    rep = floor_report([_doc("uk", "GB")], {"sources": []}, floor)
    assert _states(rep) == {"gb": FLOOR_TRACKED, "uk": FLOOR_NO_SOURCE}


def test_verified_means_either_channel_and_a_lead_is_not_one():
    cases = {
        "fetched": ({"verification": {"status": "fetched"}}, True),
        "search-verified": ({"verification": {"status": "search-verified"}}, True),
        "a live adapter read": ({"verified": {"tier": "live", "as_of": "2026-01-01"}}, True),
        "a fixture read": ({"verified": {"tier": "fixture", "as_of": "2026-01-01"}}, True),
        "a lead": ({"verification": {"status": "lead"}}, False),
        "an unknown tier": ({"verified": {"tier": "wishful"}}, False),
        "nothing recorded": ({}, False),
    }
    for label, (row, expected) in cases.items():
        assert source_is_verified({"domain": "x.example", **row}) is expected, label


def test_a_row_that_declares_no_type_is_a_law_authority_here_as_it_is_everywhere_else():
    """`source_type_for` reads a missing type as the legacy `legal`, which is a law authority: a row added without a type must
    not drop its country into no-eligible-source ("the catalogue lists no source") when it lists one."""
    row = {"domain": "x.example", "country": "aa", "verification": {"status": "fetched"}}
    assert "source_type" not in row and source_is_law_authority(row) is True
    assert _states(floor_report([], {"sources": [row]}, _floor(en=[("aa", "official")]))) == {"aa": FLOOR_VERIFIED_UNTRACKED}
    assert source_is_law_authority({**row, "source_type": ""}) is True and source_is_law_authority({**row, "source_type": None}) is True
    assert source_is_law_authority({**row, "source_type": "ip"}) is False, "a declared non-law type still is not one"


def test_a_malformed_verification_reads_as_unverified_and_never_takes_the_report_down():
    """The row is read on a rendering path (like `verified_tier`): a catalogue typo shows as an unverified row, not a 500."""
    for bad in ("fetched", ["fetched"], 7, None, {"status": None}, {"status": ["fetched"]}, {}):
        row = {"domain": "x.example", "country": "aa", "source_type": "legal", "verification": bad}
        assert source_is_verified(row) is False, bad
        assert _states(floor_report([], {"sources": [row]}, _floor(en=[("aa", "official")]))) == {"aa": FLOOR_UNVERIFIED}, bad
    # a status is compared without its case or stray spaces, as the adapter tier beside it is
    for spelled in ("Fetched", " fetched ", "SEARCH-VERIFIED"):
        assert source_is_verified({"domain": "x.example", "verification": {"status": spelled}}) is True, spelled
    assert source_is_verified({"domain": "x.example", "verification": {"status": "Lead"}}) is False


def test_a_country_with_two_law_sources_is_reachable_if_any_one_is_verified_whatever_the_order():
    """The catalogue lists several sources for one country (a code and a gazette): the country is as reachable as its best
    one, so a later unverified row must not undo an earlier verified one, nor an earlier unverified row hide a later one."""
    floor = _floor(en=[("aa", "official"), ("bb", "official"), ("cc", "official")])
    good, weak = _src("good.example", "aa", status="fetched"), _src("weak.example", "aa", status="lead")
    other_good, other_weak = _src("good.example", "bb", status="fetched"), _src("weak.example", "bb", status="lead")
    only_weak = [_src("w1.example", "cc", status="lead"), _src("w2.example", "cc")]
    for order in (1, -1):
        catalog = {"sources": [*[good, weak][::order], *[other_weak, other_good][::order], *only_weak[::order]]}
        assert _states(floor_report([], catalog, floor)) == {
            "aa": FLOOR_VERIFIED_UNTRACKED,
            "bb": FLOOR_VERIFIED_UNTRACKED,
            "cc": FLOOR_UNVERIFIED,
        }, f"order {order}"


# --- the refusals ----------------------------------------------------------------------------------------------------------


def test_an_ip_office_or_a_case_law_site_does_not_make_a_countrys_law_reachable():
    floor = _floor(en=[("aa", "official"), ("bb", "official"), ("cc", "official")])
    catalog = {
        "sources": [
            _src("ip.example", "aa", status="fetched", kind="ip"),
            _src("court.example", "bb", status="fetched", kind="case_law"),
            _src("gazette.example", "cc", status="fetched", kind="gazette"),
        ]
    }
    assert [source_is_law_authority(s) for s in catalog["sources"]] == [False, False, True]
    assert _states(floor_report([], catalog, floor)) == {"aa": FLOOR_NO_SOURCE, "bb": FLOOR_NO_SOURCE, "cc": FLOOR_VERIFIED_UNTRACKED}


def test_a_many_country_source_is_credited_to_no_single_country_and_is_listed_on_its_own():
    """EUR-Lex serves every EU country, so it is evidence for none of them; crediting Germany for it would put Germany on the
    reachable side of the floor on the strength of a source that is not its own."""
    floor = _floor(de=[("de", "official")], en=[("gb", "official")])
    catalog = {
        "sources": [
            _src("eur-lex.example", "eu", status="fetched"),
            _src("un.example", "int", status="fetched"),
            _src("lead.example", "int", status="lead"),
            _src("wipo.example", "int", status="fetched", kind="ip"),
        ]
    }
    rep = floor_report([], catalog, floor)
    assert _states(rep) == {"de": FLOOR_NO_SOURCE, "gb": FLOOR_NO_SOURCE}
    assert rep["many_country_sources"] == {
        "eu": {"eur-lex.example": True},
        "int": {"un.example": True, "lead.example": False},  # the IP office is not a law authority and is not listed
    }


def test_a_tracked_ip_or_case_law_document_credits_no_country_and_is_counted_apart():
    """The floor is a law floor: the same line the source side draws. The document is not dropped silently -- it is counted
    under its class -- and it does not count toward its language's tracked-document total either."""
    floor = _floor(en=[("aa", "official"), ("bb", "official"), ("cc", "official")])
    docs = [
        _doc("aa", "aa", "en", category="ip"),
        _doc("bb", "bb", "en", category="case-law"),
        _doc("bb", "bb", "en", category=" Case_Law "),
        _doc("cc", "cc", "en", category="gazette"),
    ]
    rep = floor_report(docs, {"sources": []}, floor)
    assert _states(rep) == {"aa": FLOOR_NO_SOURCE, "bb": FLOOR_NO_SOURCE, "cc": FLOOR_TRACKED}
    assert rep["non_law_documents"] == {"ip": 1, "case-law": 1, "case_law": 1}
    assert rep["languages"][0]["documents"] == 1
    # a document with no category (a legacy row) is still a law document, as the table's own default says
    assert _states(floor_report([_doc("aa", "aa", category=None)], {"sources": []}, floor))["aa"] == FLOOR_TRACKED


def test_a_document_that_states_no_country_is_credited_to_no_country_and_is_counted_apart():
    floor = _floor(pt=[("tl", "official"), ("pt", "official")])
    docs = [_doc("tl", None), _doc("tl", ""), _doc("tl", None), _doc("pt", "pt")]
    rep = floor_report(docs, {"sources": []}, floor)
    assert _states(rep) == {"tl": FLOOR_NO_SOURCE, "pt": FLOOR_TRACKED}, "a country is never inferred from the jurisdiction code"
    assert rep["unplaced_documents"] == {"tl": 3}


def test_an_unreadable_catalogue_is_unchecked_never_no_source():
    """What is tracked comes from the database and stays true; what could be reached was never looked up, so it is
    UNCHECKED -- reading it as no-eligible-source would call a failed lookup a research gap."""
    floor = _floor(en=[("aa", "official"), ("bb", "official")])
    rep = floor_report([_doc("aa", "aa")], None, floor, reason="LawCatalogUnreadable: boom")
    assert rep["state"] == "unchecked" and rep["reason"] == "LawCatalogUnreadable: boom"
    assert _states(rep) == {"aa": FLOOR_TRACKED, "bb": FLOOR_UNCHECKED}
    assert rep["by_state"][FLOOR_NO_SOURCE] == [], "nobody is read as having no source for a lookup that never happened"
    assert rep["by_state"][FLOOR_UNCHECKED] == ["bb"] and rep["many_country_sources"] is None


def test_an_absent_or_empty_floor_is_unchecked_with_a_reason_not_zero_of_zero():
    rep = floor_report([], {"sources": []}, {"countries": [], "languages": {}})
    assert rep["state"] == "unchecked" and rep["reason"]
    assert rep["by_state"] is None and rep["languages"] is None and rep["countries"] == 0


def test_no_fraction_or_score_exists_anywhere_in_the_block():
    """A coverage fraction is the one number this report must never publish, and it could arrive under any key."""
    floor = _floor(en=[("aa", "official"), ("bb", "official"), ("cc", "regional")])
    rep = floor_report([_doc("aa", "aa")], {"sources": [_src("b.example", "bb", status="fetched")]}, floor)
    forbidden = {round(1 / 3, 4), round(100 / 3, 1), round(2 / 3, 4), round(200 / 3, 1)}
    seen = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(w in str(k).lower() for w in ("score", "pct", "percent", "ratio", "fraction", "coverage_rate")), k
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, float):
            seen.append(node)

    walk(rep)
    assert not (set(seen) & forbidden), seen
    assert not seen, "the block holds counts and lists, no float at all"


# --- the twelve-language tally and zh --------------------------------------------------------------------------------------


def test_the_language_tally_keeps_each_basis_and_counts_a_shared_country_in_both_rows_and_once_overall():
    floor = _floor(
        en=[("aa", "official"), ("bb", "de-facto"), ("cc", "regional")],
        fr=[("aa", "official"), ("dd", "official")],
    )
    docs = [_doc("aa", "aa", "en"), _doc("aa", "aa", "fr"), _doc("aa", "aa", "fr"), _doc("zz", "dd", None), _doc("zz", "dd", "xx")]
    rep = floor_report(docs, {"sources": [_src("b.example", "bb", status="fetched")]}, floor)
    by_lang = {r["language"]: r for r in rep["languages"]}
    assert by_lang["en"]["official"] == ["aa"] and by_lang["en"]["de-facto"] == ["bb"] and by_lang["en"]["regional"] == ["cc"]
    assert by_lang["en"]["states"] == {FLOOR_TRACKED: 1, FLOOR_VERIFIED_UNTRACKED: 1, FLOOR_UNVERIFIED: 0, FLOOR_NO_SOURCE: 1}
    assert by_lang["fr"]["states"] == {FLOOR_TRACKED: 2, FLOOR_VERIFIED_UNTRACKED: 0, FLOOR_UNVERIFIED: 0, FLOOR_NO_SOURCE: 0}
    assert "regional" not in by_lang["fr"], "a basis nobody holds is not listed"
    assert (by_lang["en"]["documents"], by_lang["fr"]["documents"]) == (1, 2), "documents by their own stated language"
    assert rep["countries"] == 4 and sum(len(v) for v in rep["by_state"].values()) == 4, "aa is in two rows and counted once"


def test_a_contested_row_is_counted_and_labelled_not_dropped():
    floor = _floor(zh=[("cn", "official"), ("tw", "regional", True)])
    rep = floor_report([], {"sources": []}, floor)
    row = rep["languages"][0]
    assert row["contested"] == ["tw"] and "tw" in row["regional"] and rep["countries"] == 2


def test_zh_is_its_own_row_and_the_territories_its_seed_names_sit_beside_it_not_on_the_floor():
    floor = _floor(zh=[("cn", "official"), ("sg", "official"), ("tw", "regional")], en=[("gb", "official")])
    catalog = {"sources": [_src("hk.example", "hk", status="fetched"), _src("mo.example", "mo")]}
    rep = floor_report([_doc("hk", "hk")], catalog, floor)
    assert [r["language"] for r in rep["languages"]] == ["zh", "en"]
    assert rep["zh_beyond_floor"] == {"hk": FLOOR_TRACKED, "mo": FLOOR_UNVERIFIED}
    assert set(rep["zh_beyond_floor"]) == set(ZH_NAMED_BEYOND_FLOOR) == {"hk", "mo"}
    assert {"hk", "mo"}.isdisjoint(_states(rep)), "the floor's country set is not edited"


# --- the report carries it, and the real files -----------------------------------------------------------------------------


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_law_coverage_report_carries_the_floor_block_beside_the_old_keys():
    s = _session()
    s.add(LawDocument(jurisdiction="fr", title="Loi", url="https://law.example/fr", country="fr"))
    s.commit()
    rep = law_coverage_report(s, enumerations={})
    assert {"jurisdictions", "enumeration", "extraction", "floor", "coverage_reasons"} <= set(rep)
    assert rep["floor"]["state"] == "checked" and "fr" in rep["floor"]["by_state"][FLOOR_TRACKED]


def test_the_report_with_an_unreadable_catalogue_keeps_what_the_database_knows_and_says_why_the_rest_is_unchecked(monkeypatch):
    from src.law import catalog as law_catalog

    def boom(*_a, **_k):
        raise law_catalog.LawCatalogUnreadable("the law catalogue legal_sources.yml could not be read (PermissionError)")

    monkeypatch.setattr(law_catalog, "load_legal_catalog", boom)
    s = _session()
    s.add(LawDocument(jurisdiction="fr", title="Loi", url="https://law.example/fr", country="fr"))
    s.commit()
    floor = law_coverage_report(s)["floor"]
    assert floor["state"] == "unchecked" and "PermissionError" in floor["reason"]
    assert "fr" in floor["by_state"][FLOOR_TRACKED], "the database half is still true"
    assert floor["by_state"][FLOOR_NO_SOURCE] == [] and floor["by_state"][FLOOR_UNCHECKED], "no lookup, so no 'no source'"


def test_the_real_floor_lists_every_country_once_with_a_state_and_the_floor_files_own_status():
    s = _session()
    rep = law_coverage_report(s, enumerations={})["floor"]
    floor = load_floor()
    assert rep["countries"] == len(floor["countries"]) >= 100
    placed = _states(rep)
    assert set(placed) == set(floor["countries"]), "every floor country has a state"
    assert sum(len(v) for v in rep["by_state"].values()) == rep["countries"], "and exactly one"
    assert set(placed.values()) <= set(FLOOR_STATES)
    assert rep["as_of"] == floor["as_of"] and rep["verification_status"] == floor["verification_status"]
    assert rep["verification_status"], "the floor file's own unverified status travels with every answer"
    # the twelve UI languages, each present, zh among them
    assert {r["language"] for r in rep["languages"]} == set(floor["languages"]) and "zh" in {r["language"] for r in rep["languages"]}
    assert len(rep["languages"]) == 12
    # a language row lists exactly the floor file's countries, bases kept
    for row in rep["languages"]:
        listed = {cc for basis in ("official", "de-facto", "regional") for cc in row.get(basis, [])}
        assert listed == {e["cc"] for e in floor["languages"][row["language"]]["countries"]}
        assert sum(row["states"].values()) == len(listed)
    # the states agree with the shipped catalogue itself: no-eligible-source is exactly "no law-authority source lists the
    # country" (a research gap, a state and never a blank), and a country that has one is never in it
    from src.law.catalog import load_legal_catalog

    with_source = {str(x.get("country") or "").lower() for x in load_legal_catalog()["sources"] if source_is_law_authority(x)}
    for cc in floor["countries"]:
        assert (placed[cc] == FLOOR_NO_SOURCE) == (cc not in with_source), cc
    # and the reachable half agrees with an independent reading of the same catalogue: a country is verified-not-yet-tracked
    # when ANY of its law-authority sources is verified, unverified when none is -- written here as `any`, not as the loop
    # the report uses, so a change to how several sources for one country combine is caught on real data
    law_rows = [x for x in load_legal_catalog()["sources"] if source_is_law_authority(x)]
    for cc in floor["countries"]:
        mine = [x for x in law_rows if str(x.get("country") or "").strip().lower() == cc]
        if placed[cc] in (FLOOR_VERIFIED_UNTRACKED, FLOOR_UNVERIFIED):
            assert (placed[cc] == FLOOR_VERIFIED_UNTRACKED) == any(source_is_verified(x) for x in mine), cc
    assert any(
        len([x for x in law_rows if str(x.get("country") or "").lower() == cc]) > 1 for cc in floor["countries"]
    ), "the shipped catalogue has no country with two law sources, so this comparison pins nothing"
    assert FLOOR_NO_SOURCE in set(placed.values()), "the shipped catalogue still has a floor country with no source to research"


def test_the_real_floor_block_is_json_and_stays_inside_its_byte_ceiling():
    """The diagnostics room is net-zero: this block is the part of law-coverage.json the floor adds, and it is held to the
    figure measured when it shipped (5,774 bytes compact) plus the slack a longer country list needs."""
    s = _session()
    block = law_coverage_report(s, enumerations={})["floor"]
    size = len(json.dumps(block, separators=(",", ":"), ensure_ascii=False).encode())
    assert size <= 6_000, f"the floor block is {size:,} bytes; measure the diagnostics room again before raising this"


def test_the_module_reads_the_floor_through_the_one_loader_and_never_copies_it():
    src = Path(coverage.__file__).read_text("utf-8")
    assert "from src.civic.coverage_floor import load_floor" in src
    assert "language_countries.yml" in src  # named in prose only: the file is never opened here
    floor_src = python_function_source(src, "floor_report")
    assert "yaml.safe_load" not in src and "open(" not in floor_src


# --- the Living sources law entry reads the same block ----------------------------------------------------------------------

_STATIC = Path(coverage.__file__).resolve().parents[1] / "static"


def test_the_living_sources_law_panel_carries_the_floor_section_and_reads_the_members_own_block():
    html = (_STATIC / "index.html").read_text("utf-8")
    law = html[html.index('id="living-law"') :]
    law = law[: law.index('id="living-osm"')] if 'id="living-osm"' in law else law
    assert 'id="living-law-floor"' in law, "the floor section is inside the Living sources law entry"
    js = (_STATIC / "app-living.js").read_text("utf-8")
    # ONE source of truth: the panel reads the diagnostics member's own report, not a second computation in the browser
    assert 'api("/api/diagnostics/law-coverage")' in js and "env.data" in js
    assert "loadLawFloor();" in function_body(js, "loadLawEvolution"), "the panel loads with the law entry"
    assert "renderLawFloor();" in function_body(js, "repaintLawEvolutionFromCache"), "a language switch redraws it from the cache, without a request"


def test_the_route_the_panel_reads_returns_the_floor_beside_the_old_keys():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as client:
        body = client.get("/api/diagnostics/law-coverage").json()
    data = body["data"]
    assert {"jurisdictions", "enumeration", "floor", "coverage_reasons"} <= set(data)
    assert data["floor"]["state"] == "checked" and data["floor"]["countries"] == len(load_floor()["countries"])


# --- the order within a state (R679): population reached, from the operator's DATED table -------------------------------


def _pop(rows, *, source="UN WPP 2024 (test)", as_of="2024-07-11"):
    return {"status": "ok", "reason": None, "weights": rows, "source": source, "as_of": as_of}


def test_within_a_state_countries_go_by_population_and_the_table_is_named_with_its_date():
    floor = _floor(en=[("aa", "official"), ("bb", "official"), ("cc", "official"), ("dd", "official")])
    rep = floor_report([], {"sources": []}, floor, population=_pop({"bb": 10.0, "cc": 300.0, "dd": 20.0}))
    assert rep["by_state"][FLOOR_NO_SOURCE] == ["cc", "dd", "bb", "aa"], "largest first; the one the table lacks last"
    order = rep["order"]
    assert order["by"] == "population" and order["source"] == "UN WPP 2024 (test)" and order["as_of"] == "2024-07-11"
    assert order["missing"] == ["aa"], "a country the table lacks is named, never given a figure"
    assert "300" not in json.dumps(rep), "the report states the order and the table, not the populations themselves"


def test_countries_the_table_lacks_follow_by_code_and_a_tie_falls_back_to_code():
    floor = _floor(en=[("zz", "official"), ("yy", "official"), ("bb", "official"), ("aa", "official")])
    rep = floor_report([], {"sources": []}, floor, population=_pop({"bb": 5.0, "aa": 5.0}))
    assert rep["by_state"][FLOOR_NO_SOURCE] == ["aa", "bb", "yy", "zz"]
    assert rep["order"]["missing"] == ["yy", "zz"]


def test_with_no_usable_table_every_country_is_listed_by_code_and_the_block_says_why():
    floor = _floor(en=[("cc", "official"), ("aa", "official"), ("bb", "official")])
    for refusal in (
        {"status": "absent", "reason": "no population table has been placed (an operator step)", "weights": {}},
        {"status": "undated", "reason": "the population table names no source", "weights": {"aa": 9.0}},
    ):
        rep = floor_report([], {"sources": []}, floor, population=refusal)
        assert rep["by_state"][FLOOR_NO_SOURCE] == ["aa", "bb", "cc"]
        assert rep["order"] == {"by": "code", "source": None, "as_of": None, "reason": refusal["reason"], "missing": []}


def test_the_order_comes_from_the_one_population_loader_by_default(tmp_path, monkeypatch):
    from src.stats import population

    table = tmp_path / "population_table.json"
    table.write_text(json.dumps({"source": "a dated test table", "as_of": "2024-01", "rows": {"AA": 1, "BB": 2}}), "utf-8")
    monkeypatch.setattr(population, "DEFAULT_PATH", table)
    rep = floor_report([], {"sources": []}, _floor(en=[("aa", "official"), ("bb", "official")]))
    assert rep["by_state"][FLOOR_NO_SOURCE] == ["bb", "aa"] and rep["order"]["source"] == "a dated test table"
    assert "load_population_table" in python_function_source(Path(coverage.__file__).read_text("utf-8"), "floor_order")
