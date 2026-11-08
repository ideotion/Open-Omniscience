"""Field checks (R603): the manifest, the consent gate, the runners' rules, the report and the panel wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.monitoring import field_checks as fc
from tests.js_source_helper import function_body, object_literal

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "static"


@pytest.fixture(autouse=True)
def _clean():
    fc.reset_for_tests()
    yield
    fc.reset_for_tests()


def _manifest(*checks: dict) -> dict:
    return {"version": 1, "checks": list(checks)}


def _check(**over) -> dict:
    base = {"id": "x-check", "title": "t", "kind": "operator_report", "status": "active", "added_on": "2026-11-08",
            "added_by": "R603", "why": "w", "retire_when": "r", "answers": ["yes", "no"]}
    base.update(over)
    return base


# ---- the manifest ------------------------------------------------------------------------------ #

def test_the_shipped_manifest_is_valid_and_every_check_says_why_who_and_when_it_retires():
    man = fc.load_manifest()
    assert man["version"] >= 1
    ids = [c["id"] for c in man["checks"]]
    assert len(ids) == len(set(ids))
    for c in man["checks"]:
        for f in fc.REQUIRED_FIELDS:
            assert str(c.get(f) or "").strip(), (c["id"], f)
        assert c["kind"] in fc.RUNNERS


def test_the_manifest_carries_no_online_field_whether_a_check_goes_online_is_the_codes():
    # A YAML edit must not be able to switch the consent gate off.
    for c in fc.load_manifest()["checks"]:
        assert "online" not in c, c["id"]
        assert "consent" not in c, c["id"]


@pytest.mark.parametrize("bad, words", [
    (_check(kind="nope"), "no runner"),
    (_check(status="paused"), "status"),
    (_check(status="retired"), "retired_on"),
    (_check(id="Not Kebab"), "kebab"),
    (_check(why=""), "why is missing"),
    (_check(answers=[]), "lists its answers"),
    (_check(platforms=["beos"]), "platforms"),
])
def test_a_broken_manifest_is_refused_by_name(bad, words):
    assert any(words in p for p in fc.manifest_problems(_manifest(bad)))


def test_a_duplicate_id_is_refused():
    assert any("used twice" in p for p in fc.manifest_problems(_manifest(_check(), _check())))


# ---- the consent gate (invariant #14) ------------------------------------------------------------ #

@pytest.mark.parametrize("kind", sorted(fc.ONLINE_KINDS))
def test_an_online_check_is_refused_without_consent_and_its_runner_is_never_reached(kind, monkeypatch):
    reached = []
    monkeypatch.setitem(fc.RUNNERS, kind, lambda *a: reached.append(1) or {"outcome": "pass"})
    man = _manifest(_check(kind=kind))
    with pytest.raises(fc.FieldCheckError, match="consent"):
        fc.run_check("x-check", manifest=man)
    assert reached == [] and fc.results() == {}
    assert fc.run_check("x-check", manifest=man, consent=True)["outcome"] == "pass"


def test_the_shipped_online_checks_are_exactly_the_fetch_kinds():
    online = {c["id"] for c in fc.load_manifest()["checks"] if c["kind"] in fc.ONLINE_KINDS}
    assert {"live-fetch-gistemp", "live-fetch-usgs", "live-fetch-owid", "live-fetch-ipcc", "eurovoc-hosts"} <= online
    assert {"live_fetch", "host_reach"} == fc.ONLINE_KINDS


def test_the_route_refuses_an_online_check_without_consent():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as client:
        r = client.post("/api/diagnostics/field-checks/run", json={"id": "live-fetch-gistemp"})
    assert r.status_code == 400
    assert "consent" in r.json()["detail"]


def test_a_retired_check_is_not_run():
    man = _manifest(_check(status="retired", retired_on="2026-12-01", retired_by="PR #1"))
    with pytest.raises(fc.FieldCheckError, match="retired"):
        fc.run_check("x-check", manifest=man, inputs={"answer": "yes"})


def test_a_check_for_another_system_is_not_run(monkeypatch):
    monkeypatch.setattr(fc, "this_platform", lambda: "linux")
    man = _manifest(_check(platforms=["windows"]))
    with pytest.raises(fc.FieldCheckError, match="windows"):
        fc.run_check("x-check", manifest=man, inputs={"answer": "yes"})


# ---- the runners ----------------------------------------------------------------------------------- #

def test_a_runner_that_breaks_is_a_named_result_not_a_500(monkeypatch):
    def boom(*a):
        raise RuntimeError("disk on fire")

    monkeypatch.setitem(fc.RUNNERS, "operator_report", boom)
    rec = fc.run_check("x-check", manifest=_manifest(_check()))
    assert rec["outcome"] == "error" and "disk on fire" in rec["error"]


def test_the_operator_report_keeps_an_answer_from_the_list_and_numbers_only(monkeypatch):
    man = _manifest(_check())
    with pytest.raises(fc.FieldCheckError):
        fc.run_check("x-check", manifest=man, inputs={"answer": "maybe"})
    rec = fc.run_check("x-check", manifest=man, inputs={
        "answer": "yes", "note": "x" * 900,
        "client": {"files_saved_by_page": 7, "sources_total": float("nan"), "sources_covered": True,
                   "my-passphrase-as-a-key": 1, "text": "secret"}})
    assert rec["answer"] == "yes" and len(rec["note"]) == 500
    # only the fixed counter names (a key is never scrubbed), only finite numbers (NaN is not JSON)
    assert rec["page_counters"] == {"files_saved_by_page": 7}
    json.dumps(fc.build_report(manifest=man), allow_nan=False)


def test_no_passphrase_the_process_holds_survives_into_a_result_or_the_report(monkeypatch):
    secret = "correct-horse-battery-staple-91"
    monkeypatch.setenv("OO_DB_PASSPHRASE", secret)
    man = _manifest(_check())
    rec = fc.run_check("x-check", manifest=man, inputs={"answer": "yes", "note": f"my pass is {secret}"})
    assert secret not in json.dumps(rec)
    assert secret not in json.dumps(fc.build_report(manifest=man))


def test_the_drive_check_writes_a_scratch_file_deletes_it_and_names_no_path(tmp_path):
    folder = tmp_path / "usb-stick"
    folder.mkdir()
    man = _manifest(_check(kind="drive_throughput", params={"size_mib": 16}))
    rec = fc.run_check("x-check", manifest=man, inputs={"path": str(folder)})
    assert rec["outcome"] == "measured" and rec["scratch_deleted"] is True
    assert list(folder.iterdir()) == []
    assert rec["write_mib_s"] and rec["read_mib_s"]
    assert str(tmp_path) not in json.dumps(rec)


@pytest.mark.parametrize("path, words", [("", "name a folder"), ("relative/dir", "absolute"), ("/no/such/dir/x", "does not exist")])
def test_the_drive_check_refuses_a_bad_folder(path, words):
    man = _manifest(_check(kind="drive_throughput"))
    with pytest.raises(fc.FieldCheckError, match=words):
        fc.run_check("x-check", manifest=man, inputs={"path": path})


def test_the_import_check_reports_the_merge_checks_own_refusal(monkeypatch, tmp_path):
    import src.backup.merge as merge
    import src.backup.sqlite_backup as sb
    import src.database.connect as connect

    db_file = tmp_path / "oo.db"
    db_file.write_bytes(b"\0" * 4096)
    monkeypatch.setattr(sb, "live_db_path", lambda: db_file)
    monkeypatch.setattr(connect, "is_encrypted_file", lambda p: True)
    seen = {}

    def refuse(available_mb=None, floor_mb=None, incoming_rows=None):
        seen["rows"] = incoming_rows
        raise merge.MergeError("Not enough free memory to merge into an encrypted corpus: needs about 9 GB")

    monkeypatch.setattr(merge, "check_memory_for_encrypted_merge", refuse)

    class _Res:
        def scalar(self):
            return 1234

    class _DB:
        def execute(self, stmt):
            return _Res()

    rec = fc.run_check("x-check", manifest=_manifest(_check(kind="import_headroom")), db=_DB())
    assert rec["outcome"] == "short" and "Not enough free memory" in rec["memory_verdict"]
    assert seen["rows"] == dict.fromkeys(merge._ENCRYPTED_REP_BYTES_PER_ROW, 1234)
    assert rec["memory"]["total_mib"] > 0


def test_the_clock_check_finds_this_sessions_step(monkeypatch):
    from datetime import UTC, datetime

    from src.monitoring import session_history as sh

    monkeypatch.setattr(sh, "current_session", lambda: {"session_id": "S1", "uptime_s": 900.0})
    monkeypatch.setattr(sh, "read_records", lambda: [
        {"kind": "clock-step", "session_id": "S0", "step_s": 999},
        {"kind": "clock-step", "session_id": "S1", "step_s": 900, "direction": "forward", "at": "x", "basis": "b"},
    ])
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    monkeypatch.setattr(sh, "read_liveness", lambda: {"session_id": "S1", "at": now})
    monkeypatch.setattr(sh, "boottime", lambda: None)
    rec = fc.run_check("x-check", manifest=_manifest(_check(kind="clock_step")))
    assert rec["outcome"] == "pass" and rec["boot_clock_readable"] is False
    assert [s["step_s"] for s in rec["clock_steps_this_session"]] == [900]
    monkeypatch.setattr(sh, "read_records", lambda: [])
    assert fc.run_check("x-check", manifest=_manifest(_check(kind="clock_step")))["outcome"] == "no-step-recorded"


def test_the_live_fetch_names_a_kill_switch_refusal_as_a_fail(monkeypatch):
    import src.stats.fetch as sf

    def refused(*a, **k):
        raise RuntimeError("network refused: airplane mode (the kill switch) is on")

    monkeypatch.setattr(sf, "fetch_gistemp", refused)
    rec = fc.run_check("x-check", consent=True, manifest=_manifest(_check(kind="live_fetch", params={"source": "gistemp"})))
    assert rec["outcome"] == "fail" and "kill switch" in rec["error"]


def test_the_report_names_what_was_not_run_and_carries_no_score():
    man = _manifest(_check(), _check(id="y-check"))
    fc.run_check("x-check", manifest=man, inputs={"answer": "no"})
    rep = fc.build_report(manifest=man)
    assert rep["schema"] == fc.REPORT_SCHEMA and rep["manifest_version"] == 1
    assert [r["id"] for r in rep["results"]] == ["x-check"]
    assert rep["not_run"] == [{"id": "y-check", "reason": "not run yet"}]

    def keys(v):
        if isinstance(v, dict):
            for k, x in v.items():
                yield k
                yield from keys(x)
        elif isinstance(v, list):
            for x in v:
                yield from keys(x)

    assert not [k for k in keys(rep) if any(b in k.lower() for b in ("score", "rating", "grade", "ranking"))]


# ---- the panel ----------------------------------------------------------------------------------- #

def test_the_panel_sits_next_to_the_diagnostics_button_and_fetches_nothing_on_open():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    diag = html.index('id="all-diag-btn"')
    box = html.index('id="field-checks-box"')
    assert diag < box < html.index('id="session-forensics-box"')
    assert 'data-on-click="fieldChecksLoad(this)"' in html
    js = (STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    run = function_body(js, "_fcRun")
    # the one consent popup comes BEFORE the POST, and consent is what it returned
    assert run.index("ensureOnline(") < run.index("/api/diagnostics/field-checks/run")
    assert "JSON.stringify({id, consent, inputs})" in run
    # the save button uses the dispatcher's own ooOpenUrl helper (not a global, so never called from app code)
    assert "data-on-click=\"ooOpenUrl('/api/diagnostics/field-checks/report')\"" in html
    for fn in ("_fcRun", "_fcAction", "_fcRender", "_fcRowHtml", "fieldChecksLoad"):
        assert "ooOpenUrl(" not in function_body(js, fn)
    on = (STATIC / "oo-on.js").read_text(encoding="utf-8")
    table = object_literal(on, "EVENT_ACTION_NAMES")
    click_row = table[table.index("click:"):]
    assert '"fieldChecksLoad"' in click_row[:click_row.index("]")]


def test_the_temporary_sample_export_button_is_kept_and_reused():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="source-samples-btn"' in html
    js = (STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    assert "await downloadSourceSamples(btn)" in js
    man = {c["id"]: c for c in fc.load_manifest()["checks"]}
    assert man["sample-export-multi-download"]["params"]["action"] == "source_samples"


def test_the_law_residue_check_uses_the_ingest_reports_own_test_and_carries_no_text(tmp_path, monkeypatch):
    from datetime import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.database.models import Base, LawDocument
    from src.law import ingest_report

    eng = create_engine(f"sqlite:///{tmp_path / 'law.db'}")
    Base.metadata.create_all(eng, tables=[LawDocument.__table__])
    secret_body = "Section 1. The secretary of state may by regulations"
    with Session(eng) as db:
        db.add_all([
            LawDocument(jurisdiction="uk", title="Data Protection Act", url="https://x.invalid/a",
                        latest_text=f"Skip to main content {secret_body}", last_status="ok",
                        last_checked_at=datetime(2026, 11, 1, 9, 0)),
            LawDocument(jurisdiction="fr", title="Code civil", url="https://x.invalid/b",
                        baseline_text=secret_body, last_status="ok"),
        ])
        db.commit()
        rec = fc.run_check("x-check", manifest=_manifest(_check(kind="law_residue")), db=db)
    assert rec["documents"] == 2 and rec["with_residue"] == 1
    row = rec["residue"][0]
    assert row["jurisdiction"] == "uk" and row["last_checked_at"] == "2026-11-01T09:00:00"
    assert row["markers"] == ["Skip to main content"]
    assert secret_body not in json.dumps(rec) and "Data Protection Act" not in json.dumps(rec)
    assert rec["strip_version"]
    # the list is the report's own: a marker added there is found here with no edit
    monkeypatch.setattr(ingest_report, "CHROME_MARKERS", ingest_report.CHROME_MARKERS + ("Section 1.",))
    with Session(eng) as db:
        assert fc.run_check("x-check", manifest=_manifest(_check(kind="law_residue")), db=db)["with_residue"] == 2


def test_a_passphrase_typed_into_a_note_reaches_no_result_panel_or_report(monkeypatch):
    """The hard rule (no secret into a result, a screen or the report): a held passphrase the operator pastes into a note, or a
    runner's error quotes, is scrubbed where the result is kept, so the panel and the saved report never carry it."""
    secret = "Correct-Horse-Battery-Field-7"
    monkeypatch.setenv("OO_DB_PASSPHRASE", secret)
    man = _manifest(_check(), _check(id="y-check", kind="law_residue"))

    def boom(*a, **k):
        raise RuntimeError(f"could not open the store with {secret}")

    monkeypatch.setitem(fc.RUNNERS, "law_residue", boom)
    rec = fc.run_check("x-check", manifest=man, inputs={"answer": "yes", "note": f"my passphrase is {secret} by mistake"})
    err = fc.run_check("y-check", manifest=man)
    assert err["outcome"] == "error"
    for blob in (rec, err, fc.panel_view(manifest=man), fc.build_report(manifest=man)):
        assert secret not in json.dumps(blob, ensure_ascii=False)


# ---- the 2026-11-08 additions (manifest version 2) ------------------------------------------------ #

def test_the_ghcnd_live_fetch_runs_the_apps_own_fetcher_and_reports_the_span(monkeypatch):
    import src.stats.fetch as sf
    from src.stats.ghcnd import parse_ghcnd_dly

    asked = []
    line = "USW00094728202401TMAX" + "".join(f"{v:>5}   " for v in [50] + [-9999] * 30)

    def fake(station, **k):
        asked.append(station)
        return parse_ghcnd_dly(line + "\n", station=station, extracted_at="2026-11-08T00:00:00Z")

    monkeypatch.setattr(sf, "fetch_ghcnd_station", fake)
    rec = fc.run_check("x-check", consent=True,
                       manifest=_manifest(_check(kind="live_fetch", params={"source": "ghcnd", "station": "USW00094728"})))
    assert asked == ["USW00094728"]
    assert rec["station"] == "USW00094728" and rec["lines_read"] == 1 and rec["refused_total"] == 0
    assert rec["first_period"] is not None and rec["first_period"].startswith("2024-01")
    with pytest.raises(fc.FieldCheckError):
        fc.run_check("x-check", manifest=_manifest(_check(kind="live_fetch", params={"source": "ghcnd", "station": "X"})))


def test_the_import_journal_keeps_outcomes_and_seconds_but_not_the_file_name_or_other_messages(monkeypatch):
    from src.backup import runlog

    monkeypatch.setattr(runlog, "list_runs", lambda: [
        {"run_id": "r2", "kind": "import", "started_at": "2026-11-08T10:00:00+00:00"},
        {"run_id": "b1", "kind": "backup", "started_at": "2026-11-08T09:00:00+00:00"},
        {"run_id": "r1", "kind": "import", "started_at": "2026-11-07T10:00:00+00:00"},
    ])
    summaries = {
        "r2": {"started_at": "2026-11-08T10:00:00+00:00", "label": "secret-name.oob", "complete": True, "outcome": "error",
               "wall_s": 300.0, "stages": {"verify": 120.0}, "hardware": {"ram_total_bytes": 3 << 30, "machine_label": "desk"},
               "errors": [{"t": "2026-11-08T10:04:30+00:00", "cls": "MergeError",
                           "msg": "Not enough free memory to merge into an encrypted corpus: needs about 5 GB, only 2 GB available."}]},
        "r1": {"started_at": "2026-11-07T10:00:00+00:00", "label": "/home/someone/b.oob", "complete": False, "outcome": "incomplete",
               "stages": {}, "died_in_stage": "validate",
               "errors": [{"t": "x", "cls": "OSError", "msg": "/home/someone/b.oob: disk full"}]},
    }
    monkeypatch.setattr(runlog, "summarise", lambda rid: summaries[rid])
    rec = fc.run_check("x-check", manifest=_manifest(_check(kind="import_journal")))
    assert rec["outcome"] == "read" and len(rec["imports"]) == 2
    new, old = rec["imports"]
    assert new["memory_refused"] and new["memory_refusal_after_s"] == 270.0 and new["stages_s"] == {"verify": 120.0}
    assert new["hardware"] == {"ram_total_bytes": 3 << 30}
    assert not old["memory_refused"] and old["error_classes"] == ["OSError"] and old["died_in_stage"] == "validate"
    flat = json.dumps(rec)
    assert "secret-name" not in flat and "/home/someone" not in flat and "desk" not in flat and "disk full" not in flat

    monkeypatch.setattr(runlog, "list_runs", lambda: [])
    assert fc.run_check("x-check", manifest=_manifest(_check(kind="import_journal")))["outcome"] == "no-import-recorded"


def test_an_operator_report_probe_is_named_in_code_and_runs_locally():
    rec = fc.run_check("x-check", manifest=_manifest(_check(params={"probe": "python_curses"})), inputs={"answer": "yes"})
    assert rec["probe"]["name"] == "python_curses" and isinstance(rec["probe"]["curses_imports"], bool)
    assert "windows_curses" in rec["probe"]
    assert any("no probe named" in p for p in fc.manifest_problems(_manifest(_check(params={"probe": "rm-rf"}))))


def test_the_windows_terminal_panel_check_applies_only_on_windows():
    c = next(c for c in fc.load_manifest()["checks"] if c["id"] == "terminal-panel-windows")
    assert c["platforms"] == ["windows"] and c["params"]["probe"] in fc.PROBES
    assert c["kind"] not in fc.ONLINE_KINDS
