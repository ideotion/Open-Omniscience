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


S_FI = "http://www.wikidata.org/entity/statement/Q33-0A1B2C3D-1111-2222-3333-444455556666"


def test_rows_carry_their_statement_address_and_time_and_doubles_and_codeless_members_go():
    rows = M.rows_from_answer(json.loads(_answer(
        _b(bloc=NATO, blocLabel="NATO", member=FI, iso2="FI", via="P463", stmt=S_FI, start="+2023-04-04T00:00:00Z", sp="11"),
        _b(bloc=NATO, blocLabel="NATO", member=FI, iso2="FI", via="P463", stmt=S_FI, start="+2023-04-04T00:00:00Z", sp="11"),
        _b(bloc=NATO, blocLabel="NATO", member=GB, iso2="GB", via="P527", start="+1949-01-01T00:00:00Z", sp="9"),
        _b(bloc=NATO, blocLabel="NATO", member="http://www.wikidata.org/entity/Q1", iso2="1X", via="P463"),
        _b(bloc=NATO, blocLabel="NATO"),
    )), bloc_key="nato", fetched_at="2026-11-17T06:00:00+00:00")
    assert rows["verdict"] == "proposed" and rows["resolved_items"] == ["Q7184"] and rows["resolved_labels"] == ["NATO"]
    fi, gb = rows["proposed"]
    assert fi == {"area": "fi", "member_item": "Q33", "joined": "2023-04-04", "left": None, "via": "P463",
                  "source": "https://www.wikidata.org/wiki/Q33#Q33$0A1B2C3D-1111-2222-3333-444455556666",
                  "fetched_at": "2026-11-17T06:00:00+00:00",
                  "notes": ["no end date stated: a member that left may read as current"]}
    assert gb["joined"] == "1949" and gb["source"] == "https://www.wikidata.org/wiki/Q7184#P527"
    assert "the statement id was not given: the link opens the property, not the statement" in gb["notes"]
    assert rows["refused"] == {"no two-letter ISO code": 1}


def test_two_members_sharing_a_code_and_dates_both_stay():
    rows = M.rows_from_answer(json.loads(_answer(
        _b(bloc=NATO, member="http://www.wikidata.org/entity/Q35", iso2="DK", via="P463"),
        _b(bloc=NATO, member="http://www.wikidata.org/entity/Q756617", iso2="DK", via="P463"),
    )), bloc_key="nato", fetched_at="t")
    assert [r["member_item"] for r in rows["proposed"]] == ["Q35", "Q756617"]


def test_an_unresolved_title_and_an_ambiguous_one_propose_nothing():
    assert M.rows_from_answer({"results": {"bindings": []}}, bloc_key="g7", fetched_at="t")["verdict"] == "unresolved"
    amb = M.rows_from_answer(json.loads(_answer(
        _b(bloc=NATO, member=FI, iso2="FI", via="P463"),
        _b(bloc="http://www.wikidata.org/entity/Q9", member=GB, iso2="GB", via="P463"),
    )), bloc_key="nato", fetched_at="t")
    assert amb["verdict"] == "ambiguous" and amb["proposed"] == [] and amb["n_items"] == 2


def test_hostile_values_never_reach_a_link_or_a_date():
    rows = M.rows_from_answer(json.loads(_answer(
        _b(bloc=NATO, member="evil/../../w/index.php?title=X&action=raw", iso2="FI", via="P463"),
        _b(bloc=NATO, member=FI, iso2="FI", via="P31"),
        _b(bloc=NATO, member=GB, iso2="GB", via="P463", stmt="http://x/statement/Q145-not-a-guid",
           start="abcdefghijklmnop", sp="11"),
    )), bloc_key="nato", fetched_at="t")
    assert rows["refused"] == {"the member is not an item id": 1, "the statement is neither P463 nor P527": 1}
    (gb,) = rows["proposed"]
    assert gb["joined"] is None and "start: the time value does not read as a date" in gb["notes"]
    assert gb["source"] == "https://www.wikidata.org/wiki/Q145#P463"
    assert M.stated_date("abcdefghijklmnop", "11") == (None, "the time value does not read as a date")


@pytest.mark.parametrize("body", [b"[]", b'{"results":[1]}', b'{"results":{"bindings":"ab"}}', b'{"results":{"bindings":[1]}}',
                                  b"[" * 100_000, b"<html>"])
def test_a_malformed_answer_is_this_blocs_verdict_and_never_ends_the_run(body):
    row = M.check_bloc("nato", "NATO", lambda u: body)
    assert row["verdict"] in ("bad_shape", "bad_answer", "unresolved") and row["proposed"] == []


def test_a_refusal_is_its_class_and_never_the_librarys_text():
    def boom(url):
        raise RuntimeError("secret proxy user:pw@10.0.0.1 refused")

    row = M.check_bloc("nato", "NATO", boom)
    assert row["verdict"] == "refused" and row["error_class"] == "RuntimeError"
    assert "secret" not in json.dumps(row)

    def status(url):
        raise M.HttpStatus(429)

    assert M.check_bloc("nato", "NATO", status)["http_status"] == 429
    assert M.check_bloc("nato", "NATO", lambda u: b" " * (M.MAX_ANSWER_BYTES + 1))["verdict"] == "answer_too_large"

    def big(url):
        raise M.AnswerTooLarge()

    assert M.check_bloc("nato", "NATO", big)["verdict"] == "answer_too_large"


class _Resp:
    def __init__(self, status=200, chunks=(), length=None):
        self.status_code, self._chunks, self.closed = status, list(chunks), False
        self.headers = {"Content-Length": str(length)} if length is not None else {}

    def iter_content(self, n):
        yield from self._chunks

    def close(self):
        self.closed = True


def _getter_with(monkeypatch, resp):
    from src.safety import fetcher

    class _S:
        def get(self, url, **kw):
            assert kw["stream"] is True and kw["timeout"] == (10, 30)
            return resp

    monkeypatch.setattr(fetcher, "_session_for", lambda settings, **kw: _S())
    return M._getter(object())


def test_the_answer_is_streamed_and_cut_at_the_cap_and_always_closed(monkeypatch):
    ok = _Resp(chunks=[b'{"a":', b"1}"])
    assert _getter_with(monkeypatch, ok)(M.query_url("x")) == b'{"a":1}' and ok.closed
    declared = _Resp(length=M.MAX_ANSWER_BYTES + 1)
    with pytest.raises(M.AnswerTooLarge):
        _getter_with(monkeypatch, declared)(M.query_url("x"))
    assert declared.closed
    endless = _Resp(chunks=[b"x" * 65536] * (M.MAX_ANSWER_BYTES // 65536 + 2))
    with pytest.raises(M.AnswerTooLarge):
        _getter_with(monkeypatch, endless)(M.query_url("x"))
    assert endless.closed
    with pytest.raises(M.HttpStatus):
        _getter_with(monkeypatch, _Resp(status=503))(M.query_url("x"))
    with pytest.raises(ValueError):
        _getter_with(monkeypatch, ok)("https://example.org/sparql?x")


def test_a_title_cannot_break_out_of_its_query_string():
    for bad in ('NATO"@en . ?x ?y ?z . #', "NATO\\", "NATO\r", "NATO\n"):
        with pytest.raises(ValueError):
            M.build_query(bad)
    assert M.query_url(M.build_query("NATO")).startswith(M.WDQS_ENDPOINT + "?")


def test_without_online_it_names_the_host_and_transport_and_sends_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(M, "_getter", lambda s: pytest.fail("a session was built without consent"))
    monkeypatch.setattr(M, "_transport", lambda s: "proxy")
    assert M.main(["--out", str(tmp_path / "r.json")]) == 2
    out = capsys.readouterr()
    listed = {line.strip() for line in out.out.splitlines()}
    assert "query.wikidata.org" in listed and "transport: proxy" in out.out and "--online" in out.err
    assert not (tmp_path / "r.json").exists()
    assert M.main(["--out", str(tmp_path / "r.json"), "--only", "nope"]) == 2


@pytest.mark.parametrize("kind", ["refused", "unknown"])
def test_a_refused_or_unknown_transport_stops_before_anything_is_sent(tmp_path, monkeypatch, capsys, kind):
    monkeypatch.setattr(M, "_getter", lambda s: pytest.fail("a session was built over a transport that refuses"))
    monkeypatch.setattr(M, "_transport", lambda s: kind)
    assert M.main(["--online", "--out", str(tmp_path / "r.json")]) == 2
    assert f"transport is {kind}" in capsys.readouterr().err
    assert not (tmp_path / "r.json").exists()


def test_unreadable_settings_read_as_unknown_and_the_session_gets_the_settings_the_transport_was_read_from(monkeypatch):
    assert M._transport(None) == "unknown"
    seen = []
    monkeypatch.setattr(M, "_settings_once", lambda: "S1")
    monkeypatch.setattr(M, "_transport", lambda s: (seen.append(("transport", s)), "direct")[1])
    monkeypatch.setattr(M, "_getter", lambda s: (seen.append(("session", s)), (lambda u: _answer()))[1])
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        assert M.main(["--online", "--only", "nato", "--out", str(pathlib.Path(d) / "r.json")]) == 0
    assert seen == [("transport", "S1"), ("session", "S1")]


def test_an_online_run_writes_a_report_and_never_the_registry(tmp_path, monkeypatch):
    registry = ROOT / "src" / "catalog" / "blocs.py"
    before = hashlib.sha256(registry.read_bytes()).hexdigest()
    asked = []

    def get(url):
        asked.append(url)
        return _answer(_b(bloc=NATO, blocLabel="NATO", member=FI, iso2="FI", via="P463",
                          start="+2023-04-04T00:00:00Z", sp="11"))

    monkeypatch.setattr(M, "_getter", lambda s: get)
    monkeypatch.setattr(M, "_transport", lambda s: "direct")
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    out = tmp_path / "r.json"
    assert M.main(["--online", "--only", "nato,brics", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert len(asked) == 2 and all(u.startswith(M.WDQS_ENDPOINT + "?") for u in asked)
    assert rep["transport"] == "direct" and rep["n_blocs"] == 2 and "LEAD for a reviewer" in rep["caveat"]
    assert rep["interrupted"] is False
    assert rep["query_template_sha256"] == hashlib.sha256(M.QUERY_TEMPLATE.encode()).hexdigest()
    assert out.stat().st_size <= M.MAX_REPORT_BYTES
    assert hashlib.sha256(registry.read_bytes()).hexdigest() == before


def test_an_interrupted_run_still_writes_the_blocs_it_read(tmp_path, monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return _answer(_b(bloc=NATO, member=FI, iso2="FI", via="P463"))

    monkeypatch.setattr(M, "_getter", lambda s: get)
    monkeypatch.setattr(M, "_transport", lambda s: "direct")
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    out = tmp_path / "r.json"
    assert M.main(["--online", "--only", "nato,brics", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["interrupted"] is True and rep["n_blocs"] == 1


def _row(i):
    return {"area": "fi", "member_item": f"Q{i + 1}", "joined": "2023-04-04", "left": None, "via": "P463",
            "source": f"https://www.wikidata.org/wiki/Q{i + 1}#P463", "fetched_at": "2026-11-17T06:00:00+00:00", "notes": []}


def test_the_report_is_cut_to_the_send_back_size_quickly_and_the_cut_is_counted():
    import time as _t

    blocs = [{"key": "nato", "verdict": "proposed", "proposed": [_row(i) for i in range(40_000)], "refused": {}},
             {"key": "asean", "verdict": "proposed", "proposed": [_row(i) for i in range(10)], "refused": {}}]
    t0 = _t.monotonic()
    rep = M.build_report(blocs, transport="direct", queries={"nato": "NATO"})
    assert _t.monotonic() - t0 < 20
    assert len(json.dumps(rep, ensure_ascii=False, indent=1).encode()) + 1 <= M.MAX_REPORT_BYTES
    assert rep["rows_dropped_to_fit"]["nato"] == 40_000 - len(rep["blocs"][0]["proposed"]) > 0
    assert len(rep["blocs"][1]["proposed"]) == 10, "the cut comes from the largest bloc"
    assert rep["query_template"] is None and rep["query_template_sha256"]


def test_a_report_that_cannot_fit_is_refused_never_written_oversized():
    blocs = [{"key": "nato", "verdict": "proposed", "proposed": [], "refused": {}, "title": "x" * 300_000}]
    with pytest.raises(ValueError):
        M.build_report(blocs, transport="direct", queries={})


def test_strings_from_the_answer_are_cut_and_lists_are_capped():
    huge = "N" * 4_000_000
    rows = M.rows_from_answer(json.loads(_answer(_b(bloc=NATO, blocLabel=huge))), bloc_key="nato", fetched_at="t")
    assert all(len(x) <= M.MAX_TEXT for x in rows["resolved_labels"])
    many = M.rows_from_answer(json.loads(_answer(*[_b(bloc=f"http://www.wikidata.org/entity/Q{i + 1}") for i in range(50)])),
                              bloc_key="nato", fetched_at="t")
    assert many["verdict"] == "ambiguous" and len(many["resolved_items"]) <= M.MAX_LISTED and many["n_items"] == 50


def test_the_session_is_the_apps_own_for_this_endpoint_and_asks_only_it():
    src = (ROOT / "scripts" / "bloc_roster_check.py").read_text(encoding="utf-8")
    assert "_session_for(settings, user_agent=DEFAULT_USER_AGENT, allowed_hosts=(WDQS_HOST,))" in src
    assert "urllib.request" not in src and "import requests" not in src
    assert "blocs.py" not in src.split('if __name__ == "__main__":')[0].split("def main(")[1]
