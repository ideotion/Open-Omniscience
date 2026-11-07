"""The OWID CO2/Energy bulk CSV parser and fetch, and the negative space.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FIXTURES ARE HAND-BUILT in the published wide-CSV shape, with a few of the curated columns
(not real OWID data). The sandbox cannot reach the host, so the column set and units are
documented, not verified live.
"""

from __future__ import annotations

import pytest

import src.stats.fetch as fetch
from src.stats.owid_climate import CATALOG, MAX_REFUSALS_KEPT, parse_owid

V = "2026-11-07T00:00:00Z"
CO2 = """country,year,iso_code,population,co2,co2_per_capita,cumulative_co2
France,1990,FRA,56000000,380.5,6.8,9000.1
France,1991,FRA,56500000,,6.7,9380.6
World,1990,,5300000000,22000.0,4.1,
Africa (GCP),1990,,630000000,NA,0.9,100
"""


def test_curated_columns_become_figures_with_catalog_units():
    r = parse_owid(CO2, dataset="co2", extracted_at=V)
    assert r.rows_read == 4 and not r.refused_total and not r.looks_unrecognised
    assert r.columns_present == ["co2", "co2_per_capita", "cumulative_co2"]
    assert "total_ghg" in r.columns_missing and "methane" in r.columns_missing
    f = next(f for f in r.figures if f.series_id == "co2.co2" and f.ref_area == "FRA" and f.time_period == "1990")
    assert (f.value, f.unit, f.agency, f.extracted_at) == (380.5, "Mt CO2", "owid", V)
    assert "population" not in {x.series_id.split(".", 1)[1] for x in r.figures}


def test_blank_and_na_are_gaps_not_zero():
    r = parse_owid(CO2, dataset="co2", extracted_at=V)
    gaps = [f for f in r.figures if f.value is None]
    assert {(f.series_id, f.ref_area, f.time_period) for f in gaps} == {
        ("co2.co2", "FRA", "1991"), ("co2.cumulative_co2", "World", "1990"), ("co2.co2", "Africa (GCP)", "1990")}
    assert all(f.value != 0 for f in r.figures if f.value is not None)


def test_aggregates_keep_their_name_and_are_flagged():
    r = parse_owid(CO2, dataset="co2", extracted_at=V)
    assert {f.ref_area for f in r.figures} == {"FRA", "World", "Africa (GCP)"}
    assert r.aggregate_areas == {"World", "Africa (GCP)"}


def test_scientific_notation_that_owid_emits_is_accepted_but_not_inf():
    ok = parse_owid("country,year,iso_code,co2\nFrance,1990,FRA,4.6e-05\n", dataset="co2", extracted_at=V)
    assert ok.figures[0].value == pytest.approx(4.6e-05)
    for bad in ("inf", "-inf", "1e999", "1_0", "0x10", "١٢"):
        r = parse_owid(f"country,year,iso_code,co2\nFrance,1990,FRA,{bad}\n", dataset="co2", extracted_at=V)
        assert r.figures == [] and r.refused_total == 1 and r.looks_unrecognised, bad


@pytest.mark.parametrize(
    "body",
    ["", "<html>404</html>", "country,year\nFrance,1990\n", "iso_code,co2\nFRA,1\n", "country,year,iso_code,population\nFrance,1990,FRA,5\n"],
)
def test_a_wrong_file_is_unrecognised_never_an_empty_series(body):
    r = parse_owid(body, dataset="co2", extracted_at=V)
    assert r.figures == [] and r.looks_unrecognised


@pytest.mark.parametrize(
    "row,reason",
    [
        ("France,19x0,FRA,1", "no country or year"),
        ("France,١٩٩٠,FRA,1", "no country or year"),
        (",1990,FRA,1", "no country or year"),
        ("France,1990,FRA", "expected 4 fields"),
        ("France,9999,FRA,1", "no country or year"),
        ("France,1990,FRA,abc", "non-numeric value"),
    ],
)
def test_malformed_rows_are_refused_counted_and_do_not_poison_good_ones(row, reason):
    r = parse_owid(f"country,year,iso_code,co2\nGermany,1990,DEU,2\n{row}\n", dataset="co2", extracted_at=V)
    assert r.rows_read == 1 and r.refused_total == 1 and reason in r.refused[0]["reason"]
    assert not r.looks_unrecognised


def test_a_duplicate_area_year_is_refused():
    r = parse_owid("country,year,iso_code,co2\nFrance,1990,FRA,1\nFrance,1990,FRA,2\n", dataset="co2", extracted_at=V)
    assert r.rows_read == 1 and [x["reason"] for x in r.refused] == ["duplicate area and year"]


def test_refusals_are_a_sample_with_an_exact_count():
    body = "country,year,iso_code,co2\nFrance,1990,FRA,1\n" + "x,y\n" * 500
    s = parse_owid(body, dataset="co2", extracted_at=V).summary()
    assert s["refused_total"] == 500 and len(s["refused_sample"]) == MAX_REFUSALS_KEPT and s["refused_is_sample"] is True


def test_an_all_gap_table_is_a_success_marked_all_gap():
    r = parse_owid("country,year,iso_code,co2\nFrance,1990,FRA,NA\n", dataset="co2", extracted_at=V)
    assert r.all_gap and not r.looks_unrecognised


def test_the_energy_dataset_uses_its_own_columns():
    r = parse_owid("country,year,iso_code,primary_energy_consumption,renewables_share_energy\nFrance,2000,FRA,2900.5,6.1\n", dataset="energy", extracted_at=V)
    assert {f.series_id for f in r.figures} == {"energy.primary_energy_consumption", "energy.renewables_share_energy"}
    assert {f.unit for f in r.figures} == {"TWh", "% of primary energy"}


def test_unknown_dataset_is_a_programming_error():
    with pytest.raises(ValueError):
        parse_owid(CO2, dataset="gdp", extracted_at=V)


# ---------------------------------------------------------------- fetch
class _Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_urls_are_pinned_to_the_owid_org_and_catalog_file_names():
    assert fetch.owid_dataset_url("co2") == "https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv"
    assert fetch.owid_dataset_url("energy") == "https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv"
    assert set(fetch.OWID_BULK_REPOS) == set(CATALOG)
    with pytest.raises(ValueError):
        fetch.owid_dataset_url("../x")


def test_fetch_delegates_and_raises_on_an_unrecognised_body():
    seen = []
    r = fetch.fetch_owid_dataset("co2", get=lambda u: seen.append(u) or _Resp(CO2), extracted_at=V)
    assert seen == [fetch.owid_dataset_url("co2")] and r.rows_read == 4
    with pytest.raises(ValueError):
        fetch.fetch_owid_dataset("co2", get=lambda u: _Resp("<html></html>"), extracted_at=V)
    with pytest.raises(RuntimeError):
        fetch.fetch_owid_dataset("co2", get=lambda u: _Resp("", 503), extracted_at=V)


def test_the_body_bound_grows_with_the_data():
    assert fetch.owid_max_chars(2027) > fetch.owid_max_chars(2026) > 100_000_000
    with pytest.raises(ValueError, match="over the"):
        fetch.fetch_owid_dataset("co2", get=lambda u: _Resp("x" * (fetch.owid_max_chars() + 1)), extracted_at=V)


def test_kill_switch_refuses_before_any_getter_runs(monkeypatch):
    monkeypatch.setattr(fetch, "kill_switch_active", lambda: True)
    called = []
    with pytest.raises(RuntimeError):
        fetch.fetch_owid_dataset("co2", get=lambda u: called.append(u) or _Resp(CO2))
    assert called == []


def test_a_literal_nan_is_a_gap_like_bulk_py_not_a_figure():
    r = parse_owid("country,year,iso_code,co2\nFrance,1990,FRA,NaN\n", dataset="co2", extracted_at=V)
    assert r.figures[0].value is None and r.all_gap
