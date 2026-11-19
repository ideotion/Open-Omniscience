"""The UCDP GED / Candidate parser (brief S08-01 S1, R747): ranges, classes, and gaps that stay gaps.

Fixture only: the fixture is invented rows in UCDP's published field shape (see its README), because the
sandbox cannot reach UCDP and R747 leaves the host probe to the operator.
"""

from __future__ import annotations

import ast
import dataclasses
import io
import json
from pathlib import Path

import pytest

from src.conflict import ucdp

FIXTURE = Path(__file__).parent / "fixtures" / "conflict" / "ucdp_ged_sample.csv"


def _parse(data: bytes, dataset: str = "ged", version: str = "23.1"):
    tally = ucdp.ParseTally()
    events = list(ucdp.parse_ged_csv(io.BytesIO(data), dataset=dataset, version=version, tally=tally))
    return {e.event_id: e for e in events}, tally


@pytest.fixture(scope="module")
def parsed():
    return _parse(FIXTURE.read_bytes())


def test_a_clean_event_keeps_its_fields_and_its_range(parsed):
    events, _ = parsed
    e = events[101]
    assert (e.dataset, e.version, e.status) == ("ged", "23.1", "final")
    assert e.violence_kind == "state_based" and e.violence_code == "1"
    assert (e.side_a, e.side_b) == ("Government of Testland", "Front A")
    assert (e.conflict_id, e.dyad_id, e.country_gw) == (9001, 8001, 999)
    assert (e.date_start, e.date_end, e.date_prec) == ("2023-03-03", "2023-03-03", 1)
    assert (e.latitude, e.longitude) == (12.5, -3.25)
    assert (e.fatalities.low, e.fatalities.best, e.fatalities.high) == (10, 12, 20)
    assert e.fatalities.complete and not e.fatalities.inverted
    assert e.deaths_by_side == {"a": 4, "b": 6, "civilians": 2, "unknown": 0}
    assert e.number_of_sources == 2 and e.source_original == "Invented Wire;Local radio"


def test_the_range_has_no_single_number_accessor():
    names = {f.name for f in dataclasses.fields(ucdp.Fatalities)}
    names |= {n for n in dir(ucdp.Fatalities) if not n.startswith("_")}
    assert names == {"low", "best", "high", "complete", "inverted"}, names


def test_an_event_without_coordinates_is_still_an_event(parsed):
    events, tally = parsed
    e = events[102]
    assert e.latitude is None and e.longitude is None
    assert e.violence_kind == "one_sided"
    assert (e.date_start, e.date_end, e.date_prec) == ("2023-05-01", "2023-05-31", 4)
    assert tally.no_coordinates == 1


def test_gaps_stay_gaps_and_are_counted(parsed):
    events, tally = parsed
    e = events[103]
    # Type 7 is not one of UCDP's three: the code is kept, no kind is invented.
    assert e.violence_code == "7" and e.violence_kind is None
    # A latitude off the globe is dropped, never clamped.
    assert e.latitude is None and e.longitude is None
    # 30 February is not a date: no ISO date, the raw text kept.
    assert e.date_start is None and e.date_start_raw == "2023-02-30"
    assert e.date_end == "2023-03-01"
    # No bounds at all: three gaps, never zeros.
    assert (e.fatalities.low, e.fatalities.best, e.fatalities.high) == (None, None, None)
    assert not e.fatalities.complete and not e.fatalities.inverted
    assert e.deaths_by_side == {"a": None, "b": None, "civilians": None, "unknown": None}
    assert tally.unknown_violence_type == 1
    assert tally.bad_coordinates == 1
    assert tally.bad_dates == 1
    assert tally.incomplete_ranges == 1


def test_an_inverted_range_is_kept_as_published_and_flagged(parsed):
    events, tally = parsed
    f = events[104].fatalities
    assert (f.low, f.best, f.high) == (3, 15, 12)
    assert f.inverted and f.complete
    assert tally.inverted_ranges == 1


def test_rows_without_an_id_and_repeated_ids_are_skipped_and_counted(parsed):
    events, tally = parsed
    assert sorted(events) == [101, 102, 103, 104]
    assert events[101].conflict_name == "Testland: Government", "the first row with an id wins"
    assert tally.skipped_no_id == 1 and tally.skipped_duplicate_id == 1
    assert (tally.rows, tally.events) == (6, 4)
    assert "seen_ids" not in tally.as_dict()


def test_candidate_events_are_preliminary_and_versions_are_vintages():
    events, _ = _parse(FIXTURE.read_bytes(), dataset="candidate", version="24.0.10")
    assert {e.status for e in events.values()} == {"preliminary"}
    assert {(e.dataset, e.version) for e in events.values()} == {("candidate", "24.0.10")}


def test_the_caller_must_name_the_dataset_and_the_version():
    with pytest.raises(ValueError):
        list(ucdp.parse_ged_rows([], dataset="acled", version="1"))
    with pytest.raises(ValueError):
        list(ucdp.parse_ged_rows([], dataset="ged", version="  "))


def test_a_file_that_is_not_ucdp_is_refused_loudly():
    with pytest.raises(ucdp.UcdpFormatError):
        list(ucdp.parse_ged_csv(io.BytesIO(b"name,value\na,1\n"), dataset="ged", version="23.1"))
    with pytest.raises(ucdp.UcdpFormatError):
        ucdp.parse_ged_page(b'{"rows": []}', dataset="ged", version="23.1")


def test_an_empty_candidate_page_is_zero_events_not_an_error():
    page = {"TotalCount": 0, "TotalPages": 0, "PreviousPageUrl": "", "NextPageUrl": "", "Result": []}
    tally = ucdp.ParseTally()
    events, info = ucdp.parse_ged_page(json.dumps(page), dataset="candidate", version="24.0.10", tally=tally)
    assert events == [] and (tally.rows, tally.events) == (0, 0)
    assert info == ucdp.PageInfo(total_count=0, total_pages=0, next_page_url=None)


def test_an_api_page_reads_the_same_fields_with_json_types():
    row = {
        "id": 501, "relid": "R-501", "type_of_violence": 2, "side_a": "A", "side_b": "B",
        "country": "Testland", "country_id": 999, "latitude": -1.5, "longitude": 30.25,
        "date_start": "2022-01-02T00:00:00", "date_end": "2022-01-03T00:00:00", "date_prec": 2,
        "low": 1, "best": 2, "high": 5, "deaths_a": 1, "deaths_b": 1, "deaths_civilians": 0, "deaths_unknown": 0,
    }
    page = {"TotalCount": 9, "TotalPages": 2, "NextPageUrl": "https://example.invalid/next", "Result": [row, "junk"]}
    tally = ucdp.ParseTally()
    events, info = ucdp.parse_ged_page(page, dataset="ged", version="22.1", tally=tally)
    (e,) = events
    assert (e.event_id, e.violence_kind, e.date_start, e.date_end) == (501, "non_state", "2022-01-02", "2022-01-03")
    assert (e.latitude, e.longitude) == (-1.5, 30.25)
    assert (e.fatalities.low, e.fatalities.best, e.fatalities.high) == (1, 2, 5)
    assert info.next_page_url == "https://example.invalid/next" and info.total_pages == 2
    assert tally.skipped_no_id == 1, "a row that is not a mapping cannot be identified"


@pytest.mark.parametrize(
    "value, expected, bad",
    [("12", 12, 0), ("12.0", 12, 0), (12, 12, 0), (12.0, 12, 0), ("", None, 0), ("NULL", None, 0),
     ("-3", None, 1), ("１２", None, 1), ("1e3", None, 1), (True, None, 1), (-1, None, 1), (1.5, None, 1)],
)
def test_counts_are_whole_ascii_numbers_or_gaps(value, expected, bad):
    tally = ucdp.ParseTally()
    assert ucdp._int({"best": value}, "best", tally) == expected
    assert tally.bad_numbers == bad


def test_the_module_opens_no_socket_and_reads_no_path():
    tree = ast.parse(Path(ucdp.__file__).read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"socket", "requests", "httpx", "urllib", "http", "pathlib", "os", "sqlalchemy", "src"}, imported
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "open" not in calls
