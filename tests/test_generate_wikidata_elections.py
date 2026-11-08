"""The Wikidata election-snapshot generator: pure conversion, refusals pinned, no network."""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

from src.civic.calendar_report import snapshot_to_events

TODAY = date(2026, 11, 8)


def _mod():
    path = Path(__file__).resolve().parents[1] / "scripts" / "generate_wikidata_elections.py"
    spec = importlib.util.spec_from_file_location("generate_wikidata_elections", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


gen = _mod()


def _b(qid, iso2="FR", office="President of France", time=None, precision=None, start=None, end=None, url=None):
    def lit(v):
        return {"type": "literal", "value": v}

    b = {"election": {"type": "uri", "value": f"http://www.wikidata.org/entity/{qid}"}}
    for key, v in (("iso2", iso2), ("officeLabel", office), ("time", time), ("precision", precision),
                   ("start", start), ("end", end), ("url", url)):
        if v is not None:
            b[key] = lit(v)
    return b


def _payload(*bindings):
    return {"head": {"vars": []}, "results": {"bindings": list(bindings)}}


def test_rows_carry_the_converter_shape_and_its_precision():
    rows, refused = gen.rows_from_sparql(_payload(
        _b("Q1", time="2027-04-10T00:00:00Z", precision="11", url="https://www.conseil-constitutionnel.fr/"),
        _b("Q2", iso2="DE", office="Bundestag", time="2029-01-01T00:00:00Z", precision="9"),
        _b("Q3", iso2="ES", office="Cortes Generales", start="2027-07-01T00:00:00Z", end="2027-07-31T00:00:00Z"),
    ))
    assert refused == []
    by = {r["qid"]: r for r in rows}
    assert by["Q1"] == {"qid": "Q1", "country": "fr", "office": "President of France",
                        "point_in_time": "2027-04-10", "precision": "day",
                        "official_url": "https://www.conseil-constitutionnel.fr/"}
    assert by["Q2"]["precision"] == "year" and "official_url" not in by["Q2"]
    assert by["Q3"]["start"] == "2027-07-01" and by["Q3"]["end"] == "2027-07-31" and "point_in_time" not in by["Q3"]
    events, ref = snapshot_to_events(rows, TODAY)  # the offline converter reads them as written
    ev = {e["source_qid"]: e for e in events}
    assert ref == [] and ev["Q1"]["confirmed"] and ev["Q2"]["window_year"] == 2029 and ev["Q3"]["month"] == 7


def test_conflicting_dates_are_refused_with_both_values_never_picked():
    rows, refused = gen.rows_from_sparql(_payload(
        _b("Q9", time="2027-04-10T00:00:00Z", precision="11"),
        _b("Q9", time="2027-04-24T00:00:00Z", precision="11"),
    ))
    assert rows == []
    assert refused[0]["qid"] == "Q9" and "2027-04-10" in refused[0]["reason"] and "2027-04-24" in refused[0]["reason"]


def test_no_iso_code_or_no_office_is_refused_once_with_the_reason():
    rows, refused = gen.rows_from_sparql(_payload(
        _b("Q5", iso2=None), _b("Q5", iso2=None), _b("Q6", office=None),
    ))
    assert rows == []
    assert [r["qid"] for r in refused] == ["Q5", "Q6"]
    assert "P297" in refused[0]["reason"] and "P541" in refused[1]["reason"]


def test_one_row_per_office_and_repeated_bindings_collapse():
    rows, _ = gen.rows_from_sparql(_payload(
        _b("Q7", office="President", time="2027-05-01T00:00:00Z", precision="10"),
        _b("Q7", office="President", time="2027-05-01T00:00:00Z", precision="10", url="https://example.org/"),
        _b("Q7", office="Senate", time="2027-05-01T00:00:00Z", precision="10"),
    ))
    assert [(r["qid"], r["office"]) for r in rows] == [("Q7", "President"), ("Q7", "Senate")]
    assert rows[0]["official_url"] == "https://example.org/"


def test_an_unknown_precision_is_kept_visible_for_the_converter_to_refuse():
    rows, _ = gen.rows_from_sparql(_payload(_b("Q8", time="2027-01-01T00:00:00Z", precision="8")))
    assert rows[0]["precision"] == "unknown:8"
    events, _ = snapshot_to_events(rows, TODAY)
    assert events[0]["date_reason"].startswith("unknown date precision")


@pytest.mark.parametrize("payload", [{}, {"results": {}}, {"results": {"bindings": "x"}}, []])
def test_an_answer_that_is_not_a_sparql_result_raises(payload):
    with pytest.raises(ValueError, match="SPARQL"):
        gen.rows_from_sparql(payload)


def test_build_snapshot_records_its_query_and_refusals_without_a_socket():
    asked: list[str] = []

    def getter(url):
        asked.append(url)
        return json.dumps(_payload(_b("Q1", time="2027-04-10T00:00:00Z", precision="11"), _b("Q5", iso2=None))).encode()

    snap = gen.build_snapshot(TODAY, getter=getter)
    assert len(asked) == 1 and asked[0].startswith(gen.WDQS_ENDPOINT + "?")
    assert "2026-11-08T00:00:00Z" in snap["query"] and "wd:Q40231" in snap["query"]
    assert snap["as_of"] == "2026-11-08" and snap["n_rows"] == 1 and len(snap["refused"]) == 1
    assert len(snap["query_sha256"]) == 64


def test_the_output_is_never_written_over_a_non_empty_file(tmp_path, monkeypatch):
    out = tmp_path / "snap.json"
    out.write_text("{}", "utf-8")
    monkeypatch.setattr(gen, "build_snapshot", lambda today: pytest.fail("must refuse before fetching"))
    assert gen.main(["-o", str(out)]) == 2
    assert out.read_text("utf-8") == "{}"
