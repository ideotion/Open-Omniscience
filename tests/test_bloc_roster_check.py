"""The bloc-roster proposal script (row 123; 0.6 gate row A, RC08.4 / register ruling G3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every test runs with a stand-in for the endpoint: nothing here leaves the machine. Most checks are refusals, because the script's
worth is what it will not do: send without consent or over an unknown transport, write the registry, turn a year into a day,
keep a library's error text, or send back more than 200 KB.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bloc_roster_check", ROOT / "scripts" / "bloc_roster_check.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def _b(**kv):
    return {k: {"type": "literal", "value": v} for k, v in kv.items()}


def _answer(*rows):
    return json.dumps({"results": {"bindings": list(rows)}}).encode()


NATO = "http://www.wikidata.org/entity/Q7184"
FI = "http://www.wikidata.org/entity/Q33"
GB = "http://www.wikidata.org/entity/Q145"


def test_the_blocs_asked_are_exactly_the_registrys_empty_political_blocs():
    from src.catalog import blocs

    empty = {g.key for g in blocs._UNPOPULATED if g.kind == "bloc"}
    assert {k for k, _ in M.BLOCS} == empty


def test_a_date_keeps_its_stated_precision_and_a_year_is_never_written_as_a_day():
    assert M.stated_date("+2023-04-04T00:00:00Z", "11") == ("2023-04-04", None)
    assert M.stated_date("+1949-01-01T00:00:00Z", "9") == ("1949", None)
    assert M.stated_date("+2020-01-01T00:00:00Z", "10") == ("2020-01", None)
    assert M.stated_date("+1900-01-01T00:00:00Z", "8")[0] is None
    assert M.stated_date("-0500-01-01T00:00:00Z", "9")[0] is None
    assert M.stated_date("", "11") == (None, None)


def test_rows_carry_their_statement_address_and_time_and_doubles_and_codeless_members_go():
    rows = M.rows_from_answer(json.loads(_answer(
        _b(bloc=NATO, blocLabel="NATO", member=FI, iso2="FI", via="P463", start="+2023-04-04T00:00:00Z", sp="11"),
        _b(bloc=NATO, blocLabel="NATO", member=FI, iso2="FI", via="P463", start="+2023-04-04T00:00:00Z", sp="11"),
        _b(bloc=NATO, blocLabel="NATO", member=GB, iso2="GB", via="P527", start="+1949-01-01T00:00:00Z", sp="9"),
        _b(bloc=NATO, blocLabel="NATO", member="http://www.wikidata.org/entity/Q1", via="P463"),
        _b(bloc=NATO, blocLabel="NATO"),
    )), bloc_key="nato", fetched_at="2026-11-17T06:00:00+00:00")
    assert rows["verdict"] == "proposed" and rows["resolved_items"] == ["Q7184"] and rows["resolved_labels"] == ["NATO"]
    fi, gb = rows["proposed"]
    assert fi == {"area": "fi", "member_item": "Q33", "joined": "2023-04-04", "left": None, "via": "P463",
                  "source": "https://www.wikidata.org/wiki/Q33#P463", "fetched_at": "2026-11-17T06:00:00+00:00"}
    assert gb["joined"] == "1949" and gb["source"] == "https://www.wikidata.org/wiki/Q7184#P527"
    assert rows["refused"] == [{"member": "Q1", "reason": "no two-letter ISO code"}]


def test_an_unresolved_title_and_an_ambiguous_one_propose_nothing_as_one_blocs():
    assert M.rows_from_answer({"results": {"bindings": []}}, bloc_key="g7", fetched_at="t")["verdict"] == "unresolved"
    amb = M.rows_from_answer(json.loads(_answer(
        _b(bloc=NATO, member=FI, iso2="FI", via="P463"),
        _b(bloc="http://www.wikidata.org/entity/Q9", member=GB, iso2="GB", via="P463"),
    )), bloc_key="nato", fetched_at="t")
    assert amb["verdict"] == "ambiguous"


def test_a_refusal_is_its_class_and_never_the_librarys_text():
    def boom(url):
        raise RuntimeError("secret proxy user:pw@10.0.0.1 refused")

    row = M.check_bloc("nato", "NATO", boom)
    assert row["verdict"] == "refused" and row["error_class"] == "RuntimeError"
    assert "secret" not in json.dumps(row)
    assert M.check_bloc("nato", "NATO", lambda u: b"<html>")["verdict"] == "not_json"
    assert M.check_bloc("nato", "NATO", lambda u: b" " * (M.MAX_ANSWER_BYTES + 1))["verdict"] == "answer_too_large"


def test_a_title_cannot_break_out_of_its_query_string():
    with pytest.raises(ValueError):
        M.build_query('NATO"@en . ?x ?y ?z . #')
    assert M.query_url(M.build_query("NATO")).startswith(M.WDQS_ENDPOINT + "?")


def test_without_online_it_names_the_host_and_transport_and_sends_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(M, "_getter", lambda: pytest.fail("a session was built without consent"))
    monkeypatch.setattr(M, "_transport", lambda: "proxy")
    assert M.main(["--out", str(tmp_path / "r.json")]) == 2
    out = capsys.readouterr()
    listed = {line.strip() for line in out.out.splitlines()}
    assert "query.wikidata.org" in listed and "transport: proxy" in out.out and "--online" in out.err
    assert not (tmp_path / "r.json").exists()
    assert M.main(["--out", str(tmp_path / "r.json"), "--only", "nope"]) == 2


@pytest.mark.parametrize("kind", ["refused", "unknown"])
def test_a_refused_or_unknown_transport_stops_before_anything_is_sent(tmp_path, monkeypatch, capsys, kind):
    monkeypatch.setattr(M, "_getter", lambda: pytest.fail("a session was built over a transport that refuses"))
    monkeypatch.setattr(M, "_transport", lambda: kind)
    assert M.main(["--online", "--out", str(tmp_path / "r.json")]) == 2
    assert f"transport is {kind}" in capsys.readouterr().err
    assert not (tmp_path / "r.json").exists()


def test_an_online_run_writes_a_report_and_never_the_registry(tmp_path, monkeypatch):
    registry = ROOT / "src" / "catalog" / "blocs.py"
    before = hashlib.sha256(registry.read_bytes()).hexdigest()
    asked = []

    def get(url):
        asked.append(url)
        return _answer(_b(bloc=NATO, blocLabel="NATO", member=FI, iso2="FI", via="P463",
                          start="+2023-04-04T00:00:00Z", sp="11"))

    monkeypatch.setattr(M, "_getter", lambda: get)
    monkeypatch.setattr(M, "_transport", lambda: "direct")
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    out = tmp_path / "r.json"
    assert M.main(["--online", "--only", "nato,brics", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert len(asked) == 2 and all(u.startswith(M.WDQS_ENDPOINT + "?") for u in asked)
    assert rep["transport"] == "direct" and rep["n_blocs"] == 2 and "LEAD for a reviewer" in rep["caveat"]
    assert rep["query_template_sha256"] == hashlib.sha256(M.QUERY_TEMPLATE.encode()).hexdigest()
    assert out.stat().st_size <= M.MAX_REPORT_BYTES
    assert hashlib.sha256(registry.read_bytes()).hexdigest() == before


def test_the_report_is_cut_to_the_send_back_size_and_the_cut_is_counted():
    row = {"area": "fi", "member_item": "Q33", "joined": "2023-04-04", "left": None, "via": "P463",
           "source": "https://www.wikidata.org/wiki/Q33#P463", "fetched_at": "2026-11-17T06:00:00+00:00"}
    blocs = [{"key": "nato", "verdict": "proposed", "proposed": [dict(row) for _ in range(3000)], "refused": []}]
    rep = M.build_report(blocs, transport="direct", queries={"nato": "NATO"})
    assert len(json.dumps(rep, ensure_ascii=False, indent=1).encode()) <= M.MAX_REPORT_BYTES
    assert rep["rows_dropped_to_fit"]["nato"] == 3000 - len(rep["blocs"][0]["proposed"]) > 0
    assert rep["query_template"] is None and rep["query_template_sha256"]


def test_the_session_is_the_apps_own_for_this_endpoint_and_asks_only_it():
    src = (ROOT / "scripts" / "bloc_roster_check.py").read_text(encoding="utf-8")
    assert "guarded_session(user_agent=DEFAULT_USER_AGENT, allowed_hosts=(WDQS_HOST,))" in src
    assert "urllib.request" not in src and "import requests" not in src
    assert "blocs.py" not in src.split('if __name__ == "__main__":')[0].split("def main(")[1]
