"""The 0.4 release acceptance run (2026-09-18): the worker's sequence, its honesty, its
routes, the fresh-install helper, and the panel.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The phases are stubbed at the MODULE THAT READS THEM (``src.monitoring.release_run``),
never at the package that re-exports them -- the recorded post-split lesson. What is
driven for real: the sequencing, the state file, the report, the closed vocabulary, the
passphrase's absence from every artifact, the routes through ``TestClient``, and the
fresh-install helper end to end on the row-K fixture artifact in its own subprocess.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.monitoring import release_run as rr

_ROOT = Path(__file__).resolve().parent.parent
SECRET = "hunter2-never-on-disk"


class FakeCtx:
    """A JobContext stand-in: cooperative stop + progress capture."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self.progress: list[tuple] = []

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        self.progress.append((done, total, detail))

    def cancel(self) -> None:
        self._stop.set()


@pytest.fixture
def fast(monkeypatch, tmp_path):
    """Every phase stubbed, every wait shortened, the data dir isolated. Returns the
    call log so a test can assert WHICH phases ran (and which must not have)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    dest = tmp_path / "dest"
    dest.mkdir()
    calls: list[str] = []
    monkeypatch.setattr(rr, "_TICK_S", 0.02)
    monkeypatch.setattr(rr, "HEARTBEAT_INTERVAL_S", 0.05)
    monkeypatch.setattr(rr, "INTERIM_REPORT_INTERVAL_S", 3600.0)

    def _pre(run):
        calls.append("preflight")
        return {"app_version": "t", "backup_engine_format": "oo-volumes-2", "statement_deadline_fix_present": True,
                "dest_dir": str(dest), "corpus_bytes": 10, "dest_free_bytes": 10**9, "fresh_install_fits": True,
                "articles": 412, "backup_schema": "oo-backup-3"}

    def _p0(ctx, run):
        calls.append("p0")
        run.artifacts["backup_folder"] = str(dest / "202609181200_OpenOmniscience_Backup")
        return {"backup_folder": run.artifacts["backup_folder"], "p0_report_path": "x.json",
                "checks": {"p0_1_backup": {"verdict": "not-measurable", "reason": "sub-scale"},
                           "p0_1_verify": {"verdict": "pass", "reason": "ok"},
                           "p0_2_restore": {"verdict": "pass", "reason": "ok"},
                           "p0_4_unlock": {"verdict": "pass", "reason": "ok"},
                           "p0_3_collector": {"verdict": "not-measurable-here", "reason": "soak"}},
                "summary": {"pass": 3, "fail": 0}, "backup_engine_format": "oo-volumes-2"}

    def _fresh(ctx, run, backup, *, label):
        calls.append(f"fresh:{label}")
        return {"label": label, "elapsed_s": 1.0, "returncode": 0,
                "child": {"ok": True, "restore": {"kind": "volume-set", "committed": True},
                          "counts": {"articles": 412, "sources": 9, "keywords": 30},
                          "integrity": {"verdict": "consistent", "laundered_total": 0, "demoted_total": 0,
                                        "checked": {"with_judging_attempt": 4}, "verified_disqualified_sample": ["x.example"]},
                          "country_code_scan": {"duplicates": 0}, "peak_rss_mb": 120.0}}

    def _arm(run):
        calls.append("arm")
        return {"network": {"online": True}, "unattended": {"armed": True}, "after": {"scheduler_running": True}}

    def _law():
        calls.append("law")
        return {"legislation.gov.uk": {"measured": True, "status_code": 200}}

    def _weights():
        calls.append("weights")
        return {"hf": {"measured": True, "sha": "a" * 40}, "ollama": {"measured": False, "reason": "off"}}

    def _collect(ctx, run):
        calls.append("collect")
        return {"soak_window": {"window": {"hours": run.soak.get("elapsed_hours"), "reaches_bar": False}, "unmeasured": ["wal"]},
                "qualification_integrity_live": {"verdict": "consistent", "laundered_total": 0, "demoted_total": 0},
                "collector": {"verdict": "not-measurable-here", "reason": "short window"},
                "wiki_lane_counters": {"measured": False, "reason": "lane-never-run", "detail": "no file"},
                "wiki_lane_service": {"streaming": False}}

    def _bundle(ctx):
        calls.append("bundle")
        return {"measured": True, "path": "/tmp/x.zip", "bytes": 10, "members_total": 74,
                "zero_byte_members": [], "coverage_complete": True, "job_state": "done"}

    def _row5(ctx, run):
        calls.append("row5")
        return {"mode_ok": True, "composition": {"rows": []}}

    monkeypatch.setattr(rr, "_preflight", _pre)
    monkeypatch.setattr(rr, "_p0_into_dated_folder", _p0)
    monkeypatch.setattr(rr, "_fresh_install_restore", _fresh)
    monkeypatch.setattr(rr, "_arm_soak", _arm)
    monkeypatch.setattr(rr, "_law_live_checks", _law)
    monkeypatch.setattr(rr, "_weights_digest_proposal", _weights)
    monkeypatch.setattr(rr, "_collect", _collect)
    monkeypatch.setattr(rr, "_bundle", _bundle)
    monkeypatch.setattr(rr, "_row5_quarantine", _row5)
    return {"calls": calls, "dest": dest, "data": tmp_path / "data"}


def _params(dest, **kw):
    base = {"dest_dir": str(dest), "passphrase": SECRET, "soak_hours": 0.00005}
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
#  Parameters
# --------------------------------------------------------------------------- #
def test_params_refuse_a_bad_profile_a_blank_passphrase_and_a_bad_window():
    with pytest.raises(ValueError):
        rr.RunParams("d", "p", profile="huge").validate()
    with pytest.raises(ValueError):
        rr.RunParams("d", "").validate()
    with pytest.raises(ValueError):
        rr.RunParams("d", "p", soak_hours=0).validate()
    rr.RunParams("d", "p", profile="million", soak_hours=72).validate()


# --------------------------------------------------------------------------- #
#  The sequence, the report, the absence of the secret
# --------------------------------------------------------------------------- #
def test_a_full_run_sequences_the_phases_and_writes_one_report(fast):
    ctx = FakeCtx()
    res = rr.run_release_run(ctx, **_params(fast["dest"]))
    assert fast["calls"] == ["preflight", "p0", "fresh:own-backup", "arm", "law", "weights", "collect", "bundle"], fast["calls"]
    report = res["report"]
    assert report["schema"] == rr.RELEASE_RUN_SCHEMA
    assert report["outcome"] == "done" and report["interim"] is False
    names = [ph["name"] for ph in report["phases"]]
    assert names == ["preflight", "row5_quarantine", "p0_validation", "fresh_install_restore",
                     "arm_soak", "online_probes", "soak", "collect", "bundle"], names
    assert {ph["name"]: ph["status"] for ph in report["phases"]}["row5_quarantine"] == "skipped"
    rows = {r["row"]: r for r in report["board_rows"]}
    assert set(rows) == {"A", "B", "C", "D", "E", "G", "J", "K", "I", "P", "Q", "T"}
    assert rows["A"]["status"] == "measured" and rows["A"]["evidence"]["integrity_verdict"] == "consistent"
    assert rows["G"]["status"] == "skipped"
    assert rows["P"]["status"] == "not-measurable-here"
    for r in rows.values():
        assert r["status"] in rr.PHASE_STATUSES, r
    # The summary is a tally, never a score.
    assert isinstance(report["summary"]["rows_by_status"], dict)
    assert "never a score" in report["summary"]["note"]
    assert Path(res["path"]).exists() and res["path"].endswith("-final.json")


def test_the_passphrase_reaches_no_artifact(fast):
    ctx = FakeCtx()
    res = rr.run_release_run(ctx, **_params(fast["dest"]))
    for p in (Path(res["path"]), rr._state_path()):
        assert SECRET not in p.read_text(encoding="utf-8"), p
    assert SECRET not in json.dumps(res["report"])
    assert SECRET not in json.dumps(rr.read_state())


def test_row5_runs_ONLY_when_ticked(fast):
    """Ruling A1 deferred the quarantine pass; the button may not decide it. The default
    must not call it, and the opt-in must."""
    rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    assert "row5" not in fast["calls"]
    fast["calls"].clear()
    rr.run_release_run(FakeCtx(), **_params(fast["dest"], run_row5_quarantine=True))
    assert fast["calls"][:2] == ["preflight", "row5"], fast["calls"]


def test_a_cancel_during_the_soak_still_collects_and_reports(fast):
    ctx = FakeCtx()
    threading.Timer(0.15, ctx.cancel).start()
    res = rr.run_release_run(ctx, **_params(fast["dest"], soak_hours=24))
    report = res["report"]
    assert report["outcome"] == "cancelled"
    assert report["soak"]["ended_by"] == "cancelled"
    assert "collect" in fast["calls"] and "bundle" in fast["calls"]
    statuses = {ph["name"]: ph["status"] for ph in report["phases"]}
    assert statuses["soak"] == "cancelled"


def test_collect_now_ends_the_window_early_and_says_so(fast):
    ctx = FakeCtx()
    threading.Timer(0.15, rr.request_collect_now).start()
    t0 = time.monotonic()
    res = rr.run_release_run(ctx, **_params(fast["dest"], soak_hours=24))
    assert time.monotonic() - t0 < 20
    assert res["report"]["soak"]["ended_by"] == "collect-now"
    assert res["report"]["outcome"] == "done"
    # The window it got is recorded, not the window it asked for.
    assert res["report"]["soak"]["elapsed_hours"] < 1 and res["report"]["soak"]["hours_requested"] == 24


def test_a_preflight_refusal_writes_a_report_and_runs_nothing_else(fast, monkeypatch):
    def _refuse(run):
        raise ValueError("the destination overlaps the live data directory")
    monkeypatch.setattr(rr, "_preflight", _refuse)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    assert res["report"]["outcome"] == "refused"
    assert fast["calls"] == []
    assert res["report"]["phases"][0]["status"] == "refused"
    assert "overlaps" in res["report"]["phases"][0]["detail"]


def test_a_phase_that_raises_is_recorded_as_error_and_the_run_goes_on(fast, monkeypatch):
    def _boom(ctx):
        raise RuntimeError("zip exploded")
    monkeypatch.setattr(rr, "_bundle", _boom)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    statuses = {ph["name"]: ph["status"] for ph in res["report"]["phases"]}
    assert statuses["bundle"] == "error"
    assert res["report"]["summary"]["any_phase_error"] is True
    assert res["report"]["outcome"] == "done"  # the run finished and reported
    rows = {r["row"]: r for r in res["report"]["board_rows"]}
    assert rows["C"]["status"] != "measured"


def test_the_fresh_install_is_not_attempted_on_an_unverified_backup(fast, monkeypatch):
    def _p0_bad(ctx, run):
        run.artifacts["backup_folder"] = str(fast["dest"] / "x")
        return {"backup_folder": str(fast["dest"] / "x"),
                "checks": {"p0_1_verify": {"verdict": "fail", "reason": "bad volume"}}, "summary": {"fail": 1}}
    monkeypatch.setattr(rr, "_p0_into_dated_folder", _p0_bad)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    assert not any(c.startswith("fresh") for c in fast["calls"])
    statuses = {ph["name"]: ph["status"] for ph in res["report"]["phases"]}
    assert statuses["fresh_install_restore"] == "not-measurable-here"
    rows = {r["row"]: r for r in res["report"]["board_rows"]}
    assert rows["A"]["status"] == "not-measurable-here"


def test_the_fresh_install_is_declined_when_the_disk_cannot_hold_it(fast, monkeypatch):
    base = rr._preflight

    def _pre(run):
        out = base(run)
        out["fresh_install_fits"] = False
        return out
    monkeypatch.setattr(rr, "_preflight", _pre)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    statuses = {ph["name"]: ph["status"] for ph in res["report"]["phases"]}
    assert statuses["fresh_install_restore"] == "not-measurable-here"
    assert "room" in {ph["name"]: ph for ph in res["report"]["phases"]}["fresh_install_restore"]["detail"]


def test_a_legacy_backup_path_gets_its_own_restore_and_a_missing_one_is_refused(fast, tmp_path):
    legacy = tmp_path / "old.oobak"
    legacy.write_bytes(b"x")
    rr.run_release_run(FakeCtx(), **_params(fast["dest"], legacy_backup_path=str(legacy)))
    assert "fresh:pre-migration" in fast["calls"]
    fast["calls"].clear()
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"], legacy_backup_path=str(tmp_path / "nope.oobak")))
    assert "fresh:pre-migration" not in fast["calls"]
    statuses = {ph["name"]: ph["status"] for ph in res["report"]["phases"]}
    assert statuses["legacy_restore"] == "refused"


def test_the_heartbeat_ring_is_bounded_and_says_what_it_dropped(fast, monkeypatch):
    monkeypatch.setattr(rr, "HEARTBEAT_CAP", 3)
    monkeypatch.setattr(rr, "HEARTBEAT_INTERVAL_S", 0.03)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"], soak_hours=0.3 / 3600))
    rep = res["report"]
    assert len(rep["heartbeats"]) == 3
    assert rep["heartbeats_dropped"] >= 1
    assert rep["board_rows"][1]["row"] == "B" and rep["board_rows"][1]["evidence"]["heartbeats_dropped"] == rep["heartbeats_dropped"]


def test_an_interim_report_is_written_during_the_soak_marked_as_one_and_superseded(fast, monkeypatch):
    """An operator who returns early downloads a PARTIAL reading rather than nothing --
    and it says INTERIM, because a partial reading presented as final is the two-hour
    reading wearing a three-day label. The final run report then supersedes it."""
    monkeypatch.setattr(rr, "INTERIM_REPORT_INTERVAL_S", 0.05)
    seen: list[dict] = []
    original_collect = rr._collect

    def _collect(ctx, run):
        # Read the interim while the run is still in flight (before the final is written).
        for p in rr._run_dir().glob("oo-release-run-*-interim.json"):
            seen.append(json.loads(p.read_text(encoding="utf-8")))
        return original_collect(ctx, run)
    monkeypatch.setattr(rr, "_collect", _collect)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"], soak_hours=0.4 / 3600))
    assert seen, "no interim report was written during the soak"
    assert all(r["interim"] is True for r in seen), [r["interim"] for r in seen]
    assert all(r["outcome"] is None for r in seen)
    assert res["report"]["interim"] is False
    assert not list(rr._run_dir().glob("oo-release-run-*-interim.json")), "the final supersedes the interim"


def test_the_state_file_records_the_phase_while_a_run_is_in_flight(fast, monkeypatch):
    seen: list[str | None] = []

    def _arm(run):
        seen.append(rr.read_state().get("phase"))
        return {"network": {"online": True}}
    monkeypatch.setattr(rr, "_arm_soak", _arm)
    rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    assert seen == ["arm_soak"]
    st = rr.read_state()
    assert st["outcome"] == "done" and st["phase"] is None and st["pid"] == os.getpid()


def test_the_million_profile_marks_the_bundle_required_and_a_zero_byte_member_fails_the_bar(fast, monkeypatch):
    def _bundle(ctx):
        return {"measured": True, "path": "/tmp/x.zip", "bytes": 10, "members_total": 74,
                "zero_byte_members": ["law-coverage.json"], "coverage_complete": True, "job_state": "done"}
    monkeypatch.setattr(rr, "_bundle", _bundle)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"], profile="million"))
    rows = {r["row"]: r for r in res["report"]["board_rows"]}
    c = rows["C"]["evidence"]
    assert c["required_on_this_profile"] is True
    assert c["bar_satisfied_by_this_bundle"] is False
    assert c["zero_byte_members"] == ["law-coverage.json"]
    # ...and the release-scale profile says its bundle is evidence at this scale only.
    res2 = rr.run_release_run(FakeCtx(), **_params(fast["dest"], profile="release-scale"))
    rows2 = {r["row"]: r for r in res2["report"]["board_rows"]}
    assert rows2["C"]["evidence"]["required_on_this_profile"] is False
    assert "this scale only" in rows2["C"]["note"]


def test_render_text_names_every_row_and_the_no_score_note(fast):
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    text = rr.render_release_run_text(res["report"])
    for row in "ABCDEGIJKPQT":
        assert f"row {row} --" in text, row
    assert "never a score" in text
    assert "[MEASURED]" in text and "[SKIPPED]" in text
    assert SECRET not in text


def test_last_report_is_honest_about_absence_and_finds_the_newest(fast):
    assert rr.last_release_run_report()["available"] is False
    rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    last = rr.last_release_run_report()
    assert last["available"] is True and last["source_file"].endswith("-final.json")


# --------------------------------------------------------------------------- #
#  Real readers, degrading honestly
# --------------------------------------------------------------------------- #
def test_the_real_preflight_refuses_a_destination_inside_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    run = rr._Run(rr.RunParams(str(tmp_path / "data" / "inside"), SECRET))
    with pytest.raises(ValueError):
        rr._preflight(run)


def test_the_real_preflight_records_the_facts_a_reader_needs(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(rr, "_article_count", lambda: 412)
    run = rr._Run(rr.RunParams(str(dest), SECRET, profile="million"))
    facts = rr._preflight(run)
    assert facts["statement_deadline_fix_present"] is True
    assert facts["articles"] == 412 and "COUNT(*)" in facts["articles_method"]
    assert facts["dest_free_bytes"] is None or facts["dest_free_bytes"] > 0
    assert any("million" in w for w in run.warnings), run.warnings


def test_bundle_reader_reports_an_unfinished_job_as_unmeasured(monkeypatch):
    class _Job:
        def start(self):
            raise RuntimeError("already running")

        def status(self):
            return {"state": "error", "error": "boom", "result": None}

        def cancel(self):
            pass

    import src.api.diagnostics.bundle as bundle_mod

    monkeypatch.setattr(bundle_mod, "_ALL_DIAG_JOB", _Job())
    out = rr._bundle(FakeCtx())
    assert out["measured"] is False and out["job_state"] == "error"


# --------------------------------------------------------------------------- #
#  The fresh-install helper, END TO END, in its own process on the row-K fixture
# --------------------------------------------------------------------------- #
_HELPER = _ROOT / "tests" / "_fixture_backup_helper.py"


def _seed_legacy_fixture(base: Path) -> Path:
    dest = base / "open-omniscience-fixture.oobak"
    env = {
        **os.environ,
        "OO_DATA_DIR": str(base / "origin"),
        "OO_DB_PLAINTEXT": "1",
        "OO_NO_SCHEDULER": "1",
        "OO_AUTOSEED": "0",
        "OO_FIXTURE_DEST": str(dest),
        "OO_FIXTURE_SCHEMA": "oo-backup-2",
        "OO_FIXTURE_TRUST": "1",
    }
    env.pop("OO_DB_PASSPHRASE", None)
    proc = subprocess.run([sys.executable, str(_HELPER), "seed"], capture_output=True, text=True,
                          cwd=_ROOT, env=env, timeout=600)
    assert proc.returncode == 0, proc.stderr
    return dest


def test_the_fresh_install_helper_restores_committed_and_reads_the_two_clauses(tmp_path):
    """The child process boots ITS OWN data dir, restores the artifact COMMITTED and
    answers row A's clause (the integrity report) and row K's (the duplicate-key scan)
    from the restored corpus. Plaintext here for speed; the parent's environment is what
    makes the production run encrypted, and that is pinned by name below."""
    backup = _seed_legacy_fixture(tmp_path)
    fresh = tmp_path / ".restore-release-run-test"
    out_json = tmp_path / "result.json"
    env = {
        **os.environ,
        "OO_DATA_DIR": str(fresh),
        "OO_DB_PLAINTEXT": "1",
        "OO_NO_SCHEDULER": "1",
        "OO_AUTOSEED": "0",
        "OO_RELEASE_RUN_BACKUP": str(backup),
        "OO_RELEASE_RUN_OUT": str(out_json),
    }
    env.pop("OO_DB_PASSPHRASE", None)
    proc = subprocess.run([sys.executable, "-m", "src.monitoring.release_run_fresh_restore"],
                          capture_output=True, text=True, cwd=_ROOT, env=env, timeout=600)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    result = json.loads(out_json.read_text(encoding="utf-8"))
    assert result["ok"] is True, result
    assert result["restore"]["kind"] == "legacy-single-file"
    assert result["restore"]["committed"] is True
    assert result["restore"]["reindex_imported"] is False
    assert result["counts"]["articles"] == 3 and result["counts"]["sources"] == 3
    assert result["integrity"]["verdict"] in {"consistent", "not-measurable-here", "inversions-found"}
    assert result["country_code_scan"]["duplicates"] == 0
    assert result["peak_rss_mb"] is None or result["peak_rss_mb"] > 0
    # the last stdout line is the same object, for a parent that lost the file
    assert json.loads(proc.stdout.strip().splitlines()[-1])["ok"] is True


def test_the_parent_runs_the_child_encrypted_and_never_plaintext():
    """The child's corpus is ciphertext under the backup passphrase: OO_DB_PLAINTEXT is
    popped and OO_DB_PASSPHRASE is set on the child's environment, never the reverse."""
    from tests.js_source_helper import python_function_source

    src = (_ROOT / "src" / "monitoring" / "release_run.py").read_text(encoding="utf-8")
    body = python_function_source(src, "_fresh_install_restore")
    assert '"OO_DB_PASSPHRASE": run.params.passphrase' in body
    assert 'env.pop("OO_DB_PLAINTEXT", None)' in body
    assert '"OO_NO_SCHEDULER": "1"' in body
    assert "shutil.rmtree(fresh" in body, "the throwaway install must be removed"
    assert '.restore-release-run-' in body, "the dir must carry the sweeper's prefix"


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as c:
        yield c


def test_start_refuses_a_bad_profile_and_a_destination_inside_the_data_dir(client, tmp_path):
    r = client.post("/api/diagnostics/release-run",
                    json={"dest_dir": str(tmp_path / "elsewhere"), "passphrase": "x", "profile": "huge"})
    assert r.status_code == 400
    r = client.post("/api/diagnostics/release-run",
                    json={"dest_dir": str(tmp_path / "data" / "in"), "passphrase": "x"})
    assert r.status_code == 400 and "overlaps" in r.json()["detail"]
    r = client.post("/api/diagnostics/release-run", json={"dest_dir": str(tmp_path / "elsewhere"), "passphrase": ""})
    assert r.status_code == 400


def test_start_launches_the_job_and_the_status_carries_no_secret(client, tmp_path, monkeypatch):
    import src.monitoring.release_run as mod

    ran: dict = {}

    def _stub(ctx, **kwargs):
        ran.update(kwargs)
        return {"path": None, "filename": None, "report": {"ok": True}}
    monkeypatch.setattr(mod, "run_release_run", _stub)
    (tmp_path / "elsewhere").mkdir()
    r = client.post("/api/diagnostics/release-run",
                    json={"dest_dir": str(tmp_path / "elsewhere"), "passphrase": SECRET, "profile": "million"})
    assert r.status_code == 200 and r.json()["started"] is True
    assert SECRET not in r.text
    deadline = time.time() + 10
    while time.time() < deadline and not ran:
        time.sleep(0.05)
    assert ran.get("profile") == "million" and ran.get("passphrase") == SECRET
    st = client.get("/api/diagnostics/release-run/status")
    assert st.status_code == 200 and SECRET not in st.text
    assert "persisted" in st.json()


def test_collect_and_download_are_honest_when_nothing_is_running(client):
    r = client.post("/api/diagnostics/release-run/collect")
    assert r.status_code == 200 and r.json()["requested"] is False
    assert client.get("/api/diagnostics/release-run/last").json()["available"] is False
    assert client.get("/api/diagnostics/release-run/download").status_code == 404


def test_the_status_reports_a_run_the_process_lost_as_interrupted(client, tmp_path):
    """A state file with no outcome and another pid is a run that died with the
    process -- the panel must say so rather than show an idle job."""
    from src.monitoring.release_run import _write_state

    _write_state({"schema": rr.RELEASE_RUN_SCHEMA, "run_id": "r", "profile": "million", "phase": "soak",
                  "outcome": None, "pid": os.getpid() + 100000, "phases": [], "heartbeats": [1, 2, 3],
                  "soak": {"elapsed_hours": 20.5}})
    st = client.get("/api/diagnostics/release-run/status").json()
    assert st["interrupted"] is True
    assert st["persisted"]["phase"] == "soak" and st["persisted"]["heartbeats"] == 3
    # ...and a finished run is NOT interrupted.
    _write_state({"schema": rr.RELEASE_RUN_SCHEMA, "run_id": "r", "phase": None, "outcome": "done",
                  "pid": os.getpid() + 100000, "phases": [], "heartbeats": []})
    assert client.get("/api/diagnostics/release-run/status").json()["interrupted"] is False


def test_download_txt_serves_the_newest_report_on_disk(client, fast):
    rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    r = client.get("/api/diagnostics/release-run/download?format=txt")
    assert r.status_code == 200 and "BOARD ROWS" in r.text and SECRET not in r.text
    r = client.get("/api/diagnostics/release-run/download")
    assert r.status_code == 200 and r.json()["schema"] == rr.RELEASE_RUN_SCHEMA


# --------------------------------------------------------------------------- #
#  The bundle wiring
# --------------------------------------------------------------------------- #
def test_the_bundle_carries_the_last_report_and_classifies_the_routes(monkeypatch, tmp_path):
    import src.api.diagnostics.bundle as bundle_mod

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    assert bundle_mod._DIAG_COVERAGE_MAP["/release-run/last"] == "release-run.json"
    for path in ("/release-run/status", "/release-run/download"):
        assert path in bundle_mod._DIAG_COVERAGE_EXEMPT
    # The bundle's OWN completeness checker, driven rather than re-derived: the member
    # is in the members list, the route is classified, and nothing is stale.
    cov = bundle_mod._diagnostics_coverage_report()
    assert cov["available"] is True, cov
    assert "release-run.json" not in cov["missing_bundle_members"], cov
    assert "/release-run/last" not in cov["unclassified"], cov
    assert cov["complete"] is True, cov
    assert bundle_mod._release_run_last()["available"] is False


def test_the_routes_sit_last_so_the_split_snapshot_is_undisturbed():
    import src.api.diagnostics as pkg

    paths = [r.path for r in pkg.router.routes]
    mine = [p for p in paths if "/release-run" in p]
    assert len(mine) == 6
    assert paths[-6:] == mine, "the release-run routes must be the LAST six the package registers"


# --------------------------------------------------------------------------- #
#  The panel
# --------------------------------------------------------------------------- #
def _html() -> str:
    return (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")


def _diag_js() -> str:
    from tests.js_source_helper import strip_comments

    return strip_comments((_ROOT / "src" / "static" / "app-diagnostics.js").read_text(encoding="utf-8"))


def test_the_box_lives_in_the_diagnostics_section_with_its_controls():
    html = _html()
    sec = html[html.index('data-adv="diagnostics"'):]
    sec = sec[:sec.index("</details>")]
    assert 'id="release-run-box"' in sec
    for el in ("rr-dest", "rr-pass", "rr-legacy", "rr-hours", "rr-newsletters", "rr-probes", "rr-row5",
               "rr-run-btn", "rr-run-million-btn", "rr-status", "rr-result"):
        assert f'id="{el}"' in sec, el
    assert "releaseRunStart(this, 'release-scale')" in sec and "releaseRunStart(this, 'million')" in sec
    assert 'onclick="releaseRunCollect(this)"' in sec and 'onclick="releaseRunCancel()"' in sec
    assert 'onclick="releaseRunStatus(this)"' in sec
    # The row-5 opt-in defaults OFF: ruling A1 deferred it, the button may not decide it.
    m = re.search(r'<input id="rr-row5"[^>]*>', sec)
    assert m and "checked" not in m.group(0), m.group(0)
    # The passphrase field is a password field that is never autofilled.
    m = re.search(r'<input id="rr-pass"[^>]*>', sec)
    assert m and 'type="password"' in m.group(0) and 'autocomplete="new-password"' in m.group(0)
    # Checkboxes escape the global input{width:100%} rule (the recorded 2026-09-16 defect).
    for cb in ("rr-newsletters", "rr-probes", "rr-row5"):
        m = re.search(rf'<input id="{cb}"[^>]*>', sec)
        assert m and 'style="width:auto"' in m.group(0), cb


def test_the_handlers_exist_gate_on_consent_and_drop_the_secret_from_the_dom():
    from tests.js_source_helper import function_body

    js = _diag_js()
    for fn in ("releaseRunStart", "releaseRunStatus", "releaseRunCollect", "releaseRunCancel", "_rrRenderReport", "_rrPoll", "_rrParams"):
        assert f"function {fn}(" in js, fn
    start = function_body(js, "releaseRunStart")
    # The CONDITION that admits the gate, not a token that also survives in a disabled
    # branch (the recorded needle-inside-the-dead-branch lesson): a mutant that turned the
    # condition to `false` and kept the call text must redden here.
    gate = re.compile(r'if \(typeof ensureOnline === "function"\s*&& !await ensureOnline\(')
    assert gate.search(start), "the run goes online: the press must pass the ONE consent popup"
    assert '$("rr-pass").value = ""' in start, "the passphrase leaves the DOM after the hand-off"
    assert '"/api/diagnostics/release-run"' in start
    # The unattended button is the same offline->online transition and is gated the same way.
    un = function_body(js, "unattendedStart")
    assert gate.search(un), "the unattended arming goes online too, and is gated the same way"


def test_the_diagnostics_section_still_fetches_nothing_on_open():
    """The box adds buttons only -- no _ADV_LOADERS entry (the standing property of the
    section, pinned separately; asserted here so THIS change cannot be the one that
    breaks it)."""
    from tests.js_source_helper import app_js, object_literal

    loaders = object_literal(app_js(), "_ADV_LOADERS")
    assert "diagnostics:" not in loaders and "release" not in loaders


def test_every_new_string_is_keyed_in_all_twelve_locales():
    keys = [
        "0.4 release run (the board's operator rows)", "Run on this instance",
        "Run as the ~1M-article instance", "soak hours", "include newsletters",
        "Not running.", "No run is in progress.",
    ]
    for loc in ("en", "fr", "de", "es", "pt", "ru", "ar", "bn", "hi", "id", "ja", "zh"):
        data = json.loads((_ROOT / "src" / "static" / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        for k in keys:
            assert k in data and str(data[k]).strip(), (loc, k)


def test_release_run_panel_node_suite() -> None:
    proc = subprocess.run(["node", str(_ROOT / "tests" / "release_run_panel_node_test.js")],
                          capture_output=True, text=True, cwd=_ROOT, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "6 checks passed" in proc.stdout
