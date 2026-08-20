"""The indicator verifier refuses the strongest tier for a response it did not ask for.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two networked sessions failed to verify the 36 curated World Bank codes. The second
failed in the dangerous direction: asking for one URL, being SERVED another, and
reporting the answer as though it had asked the right question. That is the failure
this file pins, and the fixture for it is deliberately a PERFECTLY VALID response --
if the payload were malformed the test would pass for a reason unrelated to its claim.

The other half is the tri-state. "This code is wrong" and "this country reported
nothing for a perfectly good code" are opposite findings that look identical if
collapsed, and collapsing them either condemns a working series or passes a broken
one -- both of which reach a reader as a published figure.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "verify_worldbank_indicators",
    Path(__file__).resolve().parent.parent / "scripts" / "verify_worldbank_indicators.py",
)
vwi = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vwi)


def _ok_payload(name="GDP (current US$)", n=3):
    return [
        {"page": 1, "pages": 1, "per_page": 5, "total": n},
        [
            {"indicator": {"id": "NY.GDP.MKTP.CD", "value": name},
             "country": {"id": "FR", "value": "France"},
             "countryiso3code": "FRA", "date": str(2020 + i), "value": 1.0 + i}
            for i in range(n)
        ],
    ]


# --------------------------------------------------------------------------- #
#  Rule 5 -- the URL you were served, not the one you asked for
# --------------------------------------------------------------------------- #

def test_a_rewritten_url_is_refused_even_though_the_payload_is_perfectly_valid():
    """THE discriminating test. The response is a good OK payload; the ONLY thing wrong
    is that it answers a different question. An implementation that reads the body and
    never compares the URL reports OK here, which is precisely the 2026-08-13 failure."""
    entry = {"id": "SP.POP.TOTL", "label": "Population, total"}

    def getter(_requested):
        # Served page 1 of a DIFFERENT indicator -- the shape the real tool substituted.
        return (
            __import__("json").dumps(_ok_payload()).encode(),
            vwi.indicator_url("NY.GDP.MKTP.CD", "FRA", 5),
        )

    row = vwi.check_one(entry, "FRA", 5, getter)
    assert row["verdict"] == vwi.REWRITTEN
    assert row["verdict"] != vwi.OK, "a substituted response must never wear the OK tier"
    assert "different URL" in row["note"]


def test_the_url_we_asked_for_passes():
    """The twin. A guard that refused everything would satisfy the test above while
    destroying the tool, and nothing else here would notice."""
    entry = {"id": "SP.POP.TOTL", "label": "Population, total"}

    def getter(requested):
        return (__import__("json").dumps(_ok_payload("Population, total")).encode(), requested)

    assert vwi.check_one(entry, "FRA", 5, getter)["verdict"] == vwi.OK


def test_same_endpoint_tolerates_query_reordering_but_not_a_changed_parameter():
    base = vwi.indicator_url("SP.POP.TOTL", "FRA", 5)
    assert vwi.same_endpoint(base, base)
    assert vwi.same_endpoint(base, base.replace("format=json&per_page=5", "per_page=5&format=json"))
    assert not vwi.same_endpoint(base, base.replace("per_page=5", "per_page=1000"))
    assert not vwi.same_endpoint(base, vwi.indicator_url("SP.POP.TOTL", "DEU", 5))
    assert not vwi.same_endpoint(base, ""), "an unreportable served URL is not agreement"


# --------------------------------------------------------------------------- #
#  The tri-state -- a wrong code and an unreported series are opposite findings
# --------------------------------------------------------------------------- #

def test_an_unknown_code_is_reported_as_invalid_not_as_no_data():
    payload = [{"message": [{"id": "120", "key": "Invalid value",
                             "value": "The provided parameter value is not valid"}]}]
    verdict, name, rows, note = vwi.classify(payload)
    assert verdict == vwi.DEAD_INVALID
    assert name is None and rows == 0
    assert "not valid" in note


def test_a_valid_code_with_no_rows_is_EMPTY_and_says_the_code_is_fine():
    """`EMPTY` must not read as a verdict on the code -- it is a prompt to re-run
    against another area. Condemning the code here is how a working series gets
    deleted from the catalog."""
    verdict, name, rows, note = vwi.classify([{"page": 1, "pages": 0, "total": 0}, None])
    assert verdict == vwi.EMPTY
    assert verdict != vwi.DEAD_INVALID
    assert "code is valid" in note


def test_rows_yield_the_publishers_own_indicator_name():
    verdict, name, rows, _ = vwi.classify(_ok_payload("GDP (current US$)", n=2))
    assert (verdict, name, rows) == (vwi.OK, "GDP (current US$)", 2)


def test_an_unrecognised_shape_is_an_error_not_a_guess():
    for payload in ({"unexpected": True}, [], "nonsense", None):
        assert vwi.classify(payload)[0] == vwi.ERROR


# --------------------------------------------------------------------------- #
#  Label drift -- a code that still resolves while the series behind it moved
# --------------------------------------------------------------------------- #

def test_a_diverging_official_name_is_flagged_rather_than_silently_accepted():
    entry = {"id": "EN.ATM.CO2E.PC", "label": "CO2 emissions (metric tons per capita)"}

    def getter(requested):
        served = _ok_payload("Carbon dioxide (CO2) emissions excluding LULUCF per capita")
        return (__import__("json").dumps(served).encode(), requested)

    row = vwi.check_one(entry, "FRA", 5, getter)
    assert row["verdict"] == vwi.OK, "the code resolves -- the divergence is about the LABEL"
    assert row["label_matches"] is False
    assert row["official_name"].startswith("Carbon dioxide")


def test_a_matching_name_differing_only_in_case_is_not_flagged():
    entry = {"id": "SP.POP.TOTL", "label": "Population, total"}

    def getter(requested):
        return (__import__("json").dumps(_ok_payload("population, TOTAL")).encode(), requested)

    assert vwi.check_one(entry, "FRA", 5, getter)["label_matches"] is True


# --------------------------------------------------------------------------- #
#  Wiring
# --------------------------------------------------------------------------- #

def test_the_codes_come_from_the_catalog_so_the_list_cannot_drift():
    """A pasted list is a second copy of the catalog that goes stale silently."""
    from src.stats.indicators import indicator_ids

    report = vwi.run(getter=lambda u: (__import__("json").dumps(_ok_payload()).encode(), u))
    assert [r["code"] for r in report["results"]] == indicator_ids()
    assert report["catalog_count"] == len(indicator_ids())
    assert report["summary"] == {vwi.OK: len(indicator_ids())}
    # The literal is pinned deliberately: three documents say "36 codes" (the handoff
    # prompt, CLAUDE.md's operator to-do, scripts/README.md). A catalog addition is
    # legitimate -- update those three in the same change rather than only this number.
    assert len(indicator_ids()) == 36, (
        "the catalog grew or shrank; update the '36 codes' claim in "
        "docs/design/INTERNET_SESSION_PROMPT_2026-08-07_GOVERNMENTS_DATA.md, CLAUDE.md "
        "and scripts/README.md in the same change"
    )


def test_a_transport_failure_is_one_reported_row_not_an_abandoned_run():
    """One dead code must not cost the other 35 their verification."""
    calls = {"n": 0}

    def getter(requested):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("connection reset")
        return (__import__("json").dumps(_ok_payload()).encode(), requested)

    report = vwi.run(getter=getter)
    assert len(report["results"]) == 36
    assert report["summary"][vwi.ERROR] == 1
    assert report["results"][1]["note"].startswith("OSError")


def test_a_probed_url_names_the_code_and_never_smuggles_a_query():
    url = vwi.indicator_url("NY.GDP.MKTP.CD", "FRA", 5)
    assert url.endswith("/country/FRA/indicator/NY.GDP.MKTP.CD?format=json&per_page=5")
    assert "&" not in vwi.indicator_url("A&page=9", "FRA", 5).split("?", 1)[0]
