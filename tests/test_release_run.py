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


class _CancelInSoak(FakeCtx):
    """Cancels from the soak's first tick. The loop's own progress line proves the soak has
    begun, where a timer can only guess how long the phases before it will take."""

    def __init__(self) -> None:
        super().__init__()
        self.cancelled_in_soak = False

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        super().set_progress(done=done, total=total, detail=detail)
        if detail and detail.startswith("soak:") and not self.stopping:
            self.cancelled_in_soak = True
            self.cancel()


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
    # Row 5 is LAST (ruling FD01, 2026-09-24): the soak's evidence comes first.
    assert names == ["preflight", "p0_validation", "fresh_install_restore",
                     "arm_soak", "online_probes", "soak", "collect", "bundle", "row5_quarantine"], names
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
    # ...and it runs AFTER the bundle (FD01): a whole-corpus re-index that can take days
    # may no longer hold the soak back.
    assert fast["calls"][-2:] == ["bundle", "row5"], fast["calls"]


def test_a_cancel_during_the_soak_still_collects_and_reports(fast):
    # The cancel comes from inside the soak, never from a timer. A 0.15 s timer raced the
    # six phases before the soak. On a loaded runner they outlasted it, the cancel landed
    # first, the soak was recorded as skipped, and report["soak"] had no "ended_by" (the
    # core-only lane on main, 2026-09-24; reproduced 3 of 3 with 60 ms added to each phase).
    ctx = _CancelInSoak()
    # A backstop, never a pass: if the soak's progress line changes, this ends what would
    # be a 24 h wait, and the assertion on cancelled_in_soak still fails the test.
    backstop = threading.Timer(30, ctx.cancel)
    backstop.start()
    try:
        res = rr.run_release_run(ctx, **_params(fast["dest"], soak_hours=24))
    finally:
        backstop.cancel()
    assert ctx.cancelled_in_soak, "the cancel never came from inside the soak"
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
    """DETERMINISTIC since 2026-09-24: the first form needed MORE than three heartbeats
    inside a one-second soak, and the macOS lane's runner produced fewer (PR #1172's CI).
    The ring's bound is asserted on the ring itself; the run then only needs two beats
    (the stretch's first and its last, which every soak writes) to overflow a cap of one."""
    monkeypatch.setattr(rr, "HEARTBEAT_CAP", 3)
    ring = rr._Run(rr.RunParams(**_params(fast["dest"])))
    for i in range(5):
        ring.heartbeat({"at": str(i), "elapsed_h": float(i)})
    assert [h["at"] for h in ring.heartbeats] == ["2", "3", "4"] and ring.heartbeats_dropped == 2
    monkeypatch.setattr(rr, "HEARTBEAT_CAP", 1)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"], soak_hours=0.3 / 3600))
    rep = res["report"]
    assert len(rep["heartbeats"]) == 1
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
    mine = [p for p in paths if "/release-run" in p or p.endswith("/chronology")]
    assert len(mine) == 8, mine
    assert paths[-8:] == mine, "the release-run + chronology routes must be the LAST eight the package registers"


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


# --------------------------------------------------------------------------- #
#  Resume after a restart (2026-09-18, maintainer-asked with the chronology)
# --------------------------------------------------------------------------- #
def _interrupt_mid_soak(fast, monkeypatch, *, phases_done=("preflight", "row5_quarantine", "p0_validation",
                                                             "fresh_install_restore", "arm_soak", "online_probes")):
    """Write the state file a process that died mid-soak would leave: every phase up to
    the soak measured, the soak open with two heartbeats, another pid, no outcome."""
    from src.monitoring.release_run import _write_state

    run = rr._Run(rr.RunParams(**_params(fast["dest"], soak_hours=0.0001)))
    run.artifacts["backup_folder"] = str(fast["dest"] / "202609181200_OpenOmniscience_Backup")
    for name in phases_done:
        run.begin(name)
        if name == "p0_validation":
            run.end("measured", "ok", result={"checks": {"p0_1_verify": {"verdict": "pass"}}, "summary": {"fail": 0},
                                              "backup_folder": run.artifacts["backup_folder"]})
        elif name == "row5_quarantine":
            run.end("skipped", "not requested")
        elif name == "preflight":
            run.end("measured", "ok", result={"fresh_install_fits": True, "articles": 412, "statement_deadline_fix_present": True})
        elif name == "fresh_install_restore":
            run.end("measured", "ok", result={"child": {"restore": {"committed": True}, "integrity": {"verdict": "consistent"}}})
        else:
            run.end("measured", "ok", result={"ok": True})
    run.begin("soak")
    run.soak = {"started_at": "2026-09-18T10:00:00Z", "started_epoch": time.time() - 7200, "hours_requested": 72.0,
                "elapsed_hours": 1.9, "ended_by": None, "stretch": 1, "pid": os.getpid() + 100000}
    run.heartbeats = [{"at": "2026-09-18T10:00:00Z", "elapsed_h": 0.0, "rss_mb": 300.0},
                      {"at": "2026-09-18T11:58:00Z", "elapsed_h": 1.97, "rss_mb": 305.0}]
    state = run.snapshot()
    state["pid"] = os.getpid() + 100000
    state["phase"] = "soak"
    _write_state(state)
    return state


def test_a_resume_keeps_the_measured_phases_and_starts_a_new_stretch(fast, monkeypatch):
    state = _interrupt_mid_soak(fast, monkeypatch)
    ctx = FakeCtx()
    out = rr.run_release_run(ctx, resume=True, passphrase="")
    rep = out["report"]
    calls = fast["calls"]
    # never again: the backup, the restore, the probes; again: the arming, the soak, the collect, the bundle
    assert "p0" not in calls and not any(c.startswith("fresh") for c in calls)
    assert "law" not in calls and "weights" not in calls
    assert calls == ["arm", "collect", "bundle"], calls
    assert rep["run_id"] == state["run_id"] and rep["started_at"] == state["started_at"]
    assert rep["resumed"] == 1 and rep["outcome"] == "done"
    kinds = [s["kind"] for s in rep["sessions"]]
    assert kinds == ["start", "resume"] and rep["sessions"][1]["interrupted_phase"] == "soak"
    stretches = rep["soak_stretches"]
    assert len(stretches) == 2, stretches
    assert stretches[0]["ended_by"] == "restart" and stretches[0]["ended_at"] == "2026-09-18T11:58:00Z"
    assert stretches[0]["elapsed_hours"] == 1.97, "the cut stretch is dated from its last heartbeat"
    assert stretches[1]["ended_by"] == "window-complete" and stretches[1]["stretch"] == 2
    # the phases already measured are still there, once each; the soak's record is the new one
    names = [p["name"] for p in rep["phases"]]
    assert names.count("p0_validation") == 1 and names.count("fresh_install_restore") == 1
    assert names.count("arm_soak") == 1 and names.count("soak") == 1
    row_b = next(r for r in rep["board_rows"] if r["row"] == "B")
    assert row_b["evidence"]["stretches"] == 2 and row_b["evidence"]["resumed"] == 1
    assert "continuous" in row_b["note"]
    assert any("resumed after a restart" in w for w in rep["warnings"])
    assert SECRET not in json.dumps(rep)


def test_a_resume_reruns_a_phase_that_ended_in_error_and_keeps_a_refused_one(fast, monkeypatch):
    from src.monitoring.release_run import _write_state, read_state

    _interrupt_mid_soak(fast, monkeypatch, phases_done=("preflight", "row5_quarantine", "p0_validation",
                                                        "fresh_install_restore", "arm_soak"))
    st = read_state()
    st["phases"].append({"name": "online_probes", "started_at": "x", "ended_at": "y", "status": "error", "detail": "boom"})
    st["phases"].append({"name": "legacy_restore", "started_at": "x", "ended_at": "y", "status": "refused", "detail": "no such path"})
    st["params"]["legacy_backup_path"] = "/nowhere"
    _write_state(st)
    out = rr.run_release_run(FakeCtx(), resume=True, passphrase="")
    calls = fast["calls"]
    assert "law" in calls and "weights" in calls, "an errored phase is run again"
    assert not any(c.startswith("fresh:pre-migration") for c in calls), "a refused phase is kept as refused"
    names = [p["name"] for p in out["report"]["phases"]]
    assert names.count("online_probes") == 1 and names.count("legacy_restore") == 1
    assert out["report"]["sessions"][-1]["phases_rerun"] == ["arm_soak:measured", "online_probes:error"], \
        "the arming is always redone (the process that armed the soak is gone); the errored probe is retried"


def test_resume_preflight_refuses_when_nothing_is_interrupted_or_the_passphrase_is_owed(fast, monkeypatch):
    from src.monitoring.release_run import _write_state, resume_preflight

    with pytest.raises(ValueError, match="no release run"):
        resume_preflight("")
    _write_state({"schema": rr.RELEASE_RUN_SCHEMA, "run_id": "r", "outcome": "done", "pid": os.getpid() + 5, "phases": []})
    with pytest.raises(ValueError, match="finished"):
        resume_preflight("")
    _write_state({"schema": rr.RELEASE_RUN_SCHEMA, "run_id": "r", "outcome": None, "pid": os.getpid(), "phases": []})
    with pytest.raises(ValueError, match="this process"):
        resume_preflight("")
    # interrupted during the backup: the passphrase is owed, and the plan says so
    _write_state({"schema": rr.RELEASE_RUN_SCHEMA, "run_id": "r", "outcome": None, "pid": os.getpid() + 5,
                  "phase": "p0_validation", "phases": [{"name": "preflight", "status": "measured"}],
                  "params": {"dest_dir": str(fast["dest"])}})
    with pytest.raises(ValueError, match="passphrase"):
        resume_preflight("")
    plan = resume_preflight("", check_passphrase=False)
    assert plan["unlock_needed"] is True and plan["interrupted_phase"] == "p0_validation"
    assert resume_preflight(SECRET)["unlock_needed"] is True
    # interrupted after the restore: no passphrase needed
    _interrupt_mid_soak(fast, monkeypatch)
    plan = resume_preflight("")
    assert plan["unlock_needed"] is False and plan["soak_stretches_so_far"] == 1
    assert set(plan["phases_done"]) >= {"p0_validation", "fresh_install_restore"}


def test_the_resume_route_and_the_status_offer_it_only_when_it_is_honest(client, tmp_path, monkeypatch):
    from src.monitoring.release_run import _write_state

    r = client.post("/api/diagnostics/release-run/resume", json={})
    assert r.status_code == 400 and "no release run" in r.json()["detail"]
    _write_state({"schema": rr.RELEASE_RUN_SCHEMA, "run_id": "r", "profile": "million", "outcome": None,
                  "pid": os.getpid() + 100000, "phase": "p0_validation",
                  "phases": [{"name": "preflight", "status": "measured"}], "params": {"dest_dir": str(tmp_path / "d")},
                  "heartbeats": []})
    st = client.get("/api/diagnostics/release-run/status").json()
    assert st["interrupted"] is True and st["resumable"] is True
    assert st["resume"]["unlock_needed"] is True and st["resume"]["interrupted_phase"] == "p0_validation"
    r = client.post("/api/diagnostics/release-run/resume", json={"passphrase": ""})
    assert r.status_code == 400 and "passphrase" in r.json()["detail"]
    import src.monitoring.release_run as mod

    ran: dict = {}

    def _stub(ctx, **kwargs):
        ran.update(kwargs)
        return {"path": None, "filename": None, "report": {"ok": True}}
    monkeypatch.setattr(mod, "run_release_run", _stub)
    r = client.post("/api/diagnostics/release-run/resume", json={"passphrase": SECRET})
    assert r.status_code == 200 and r.json()["started"] is True and SECRET not in r.text
    deadline = time.time() + 10
    while time.time() < deadline and not ran:
        time.sleep(0.05)
    assert ran.get("resume") is True and ran.get("passphrase") == SECRET


# --------------------------------------------------------------------------- #
#  The chronology box and the resume button (2026-09-18)
# --------------------------------------------------------------------------- #
def test_the_chronology_box_sits_above_the_run_box_with_its_controls_and_the_module_loaded():
    html = _html()
    box = html.index('id="chronology-box"')
    assert box < html.index('id="release-run-box"'), "the chronology reads first: it is what a returning operator opens"
    assert html.index('data-adv="diagnostics"') < box
    for needle in ('onclick="loadChronology(this)"', 'id="chrono-anchor"', '<option value="run">', '<option value="install">',
                   'id="chrono-summary"', 'id="chrono-timeline"', 'id="chrono-legend"', 'id="chrono-status"'):
        assert needle in html, needle
    assert '<script src="/static/ootimeline.js"></script>' in html, "the layout module must be loaded"
    assert html.index('/static/ootimeline.js') < html.index('/static/app-diagnostics.js'), "geometry before its wiring"
    # the resume button: hidden until a status says the run is resumable
    seg = html[html.index('id="rr-resume-btn"'):]
    seg = seg[:seg.index(">")]
    assert 'onclick="releaseRunResume(this)"' in seg and 'display:none' in seg


def test_the_resume_handler_gates_on_consent_and_asks_for_the_passphrase_only_when_owed():
    from tests.js_source_helper import function_source

    js = _diag_js()
    src = function_source(js, "releaseRunResume")
    assert re.search(r'if \(typeof ensureOnline === "function"\s*&& !await ensureOnline\(', src), \
        "the resume goes online again, so it passes the ONE consent popup on the CONDITION line"
    assert 'plan.unlock_needed && !pass' in src, "the passphrase is demanded only when the plan says the backup/restore is owed"
    assert '"/api/diagnostics/release-run/resume"' in src
    assert '$("rr-pass").value = ""' in src, "the secret leaves the DOM after the hand-off"
    poll = function_source(js, "_rrPoll")
    assert "s.resumable" in poll and 'rr-resume-btn' in poll, "the interrupted branch offers the resume"


def test_the_chronology_wiring_reads_on_a_press_never_on_open_and_binds_the_drag_once():
    from tests.js_source_helper import function_source, object_literal

    js = _diag_js()
    load = function_source(js, "loadChronology")
    assert '"/api/diagnostics/chronology?anchor="' in load
    draw = function_source(js, "_chronoDraw")
    assert "ooTimeline.layout(" in draw and "ooTimeline.zoomAround(" in draw and "ooTimeline.pan(" in draw
    assert draw.count('window.addEventListener("mousemove"') == 1 and "_chronoWindowBound" in draw, \
        "the SVG is re-created per render; the window listeners must be bound once"
    assert 'chrono-hatch' in draw and 'stroke-dasharray' in draw, "suspends hatched, no-record gaps dotted"
    from tests.js_source_helper import app_js

    loaders = object_literal(app_js(), "_ADV_LOADERS")
    assert "diagnostics:" not in loaders, "the section still fetches nothing on open"
    summary = function_source(js, "_chronoSummaryHtml")
    assert "not the bar" in summary and "chrono-since-restart" in summary


def test_the_vitals_session_line_is_drawn_from_the_ledger_block_and_never_fabricates_a_count():
    from tests.js_source_helper import function_source, read_static

    core = read_static("app-core.js")
    src = function_source(core, "_sessionHtml")
    assert 'if (!s) return "";' in src, "no ledger block, no line -- never a zero"
    assert "restarts_since_ledger_start" in src and "since_last_restart_s" in src and "previous_session_end" in src
    assert "_sessionHtml(v.session)" in function_source(core, "_renderVitals")


def test_every_chronology_string_is_keyed_in_all_twelve_locales():
    import json as _json

    keys = ["Chronology (this install's process sessions)", "Show chronology", "Resume run", "Since the last restart",
            "Longest continuous stretch", "{h} h continuous bar", "{n} suspend(s)", "clean shutdown", "unclean end",
            "Suspend (clock jump): {from} → {to}. The wall clock ran ahead of the monotonic clock; a sleep, a hibernation and a clock change leave the same record.",
            "Up since the last restart", "{n} since {when}"]
    for loc in ("en", "fr", "de", "es", "pt", "ru", "ar", "bn", "hi", "id", "ja", "zh"):
        data = _json.loads((_ROOT / "src" / "static" / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        for k in keys:
            assert k in data and data[k], (loc, k)


def test_ootimeline_node_suite() -> None:
    import shutil

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    proc = subprocess.run([node, str(_ROOT / "tests" / "ootimeline_node_test.js")], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ootimeline checks passed" in proc.stdout


# --------------------------------------------------------------------------- #
#  Row C and the light bundle (ruling R28, 2026-09-22)
# --------------------------------------------------------------------------- #
def _bundle_result(**kw):
    base = {"measured": True, "path": "/tmp/x.zip", "bytes": 10, "members_total": 74,
            "zero_byte_members": [], "coverage_complete": True, "job_state": "done"}
    base.update(kw)
    return base


def _row_c(fast, monkeypatch, result):
    monkeypatch.setattr(rr, "_bundle", lambda ctx: result)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    return next(r for r in res["report"]["board_rows"] if r["row"] == "C")


def test_a_LIGHT_bundle_cannot_satisfy_row_C(fast, monkeypatch):
    """THE HOLE THE TOGGLE OPENED, closed in the same PR. Row C's clause is "every member
    non-zero", and a member a light bundle declined is ABSENT rather than zero-byte -- so
    the two checks the row already made (`coverage_complete`, `zero_byte_members`) would
    both pass on a bundle carrying four fewer members. The run ASKS for a full bundle, but
    when one is already building it rides that one, and an operator may have started a
    light build a minute earlier."""
    row = _row_c(fast, monkeypatch, _bundle_result(
        profile="light", complete_profile=False,
        declined_members=["benchmark.json", "fixity.json"]))

    assert row["evidence"]["bar_satisfied_by_this_bundle"] is False
    assert row["evidence"]["bundle_profile"] == "light"
    assert "benchmark.json" in row["note"] and "R28" in row["note"]
    # ...and the row is still MEASURED: the bundle exists and is reported, it just does
    # not close the clause. Dropping it would lose evidence the operator did collect.
    assert row["status"] == "measured"


def test_a_FULL_bundle_still_satisfies_row_C(fast, monkeypatch):
    row = _row_c(fast, monkeypatch, _bundle_result(profile="full", complete_profile=True))
    assert row["evidence"]["bar_satisfied_by_this_bundle"] is True
    assert "R28" not in row["note"]


def test_a_bundle_TAKEN_BEFORE_THE_TOGGLE_EXISTED_still_satisfies_row_C(fast, monkeypatch):
    """Only an explicit `false` may block the row. An archive with no profile block was
    built when every bundle ran every member, so reading its silence as "light" would
    retroactively invalidate every bundle the operator has already taken."""
    row = _row_c(fast, monkeypatch, _bundle_result())
    assert row["evidence"]["complete_profile"] is None
    assert row["evidence"]["bar_satisfied_by_this_bundle"] is True


def test_the_bundle_phase_READS_the_profile_out_of_the_real_archive(tmp_path, monkeypatch):
    """The reader itself, against a real zip -- so the row-C tests above are not asserting
    against a dict no code path produces. Stubbing only the JOB, never the archive."""
    import zipfile

    from src.api.diagnostics import bundle as bundle_mod

    path = tmp_path / "oo-all-diagnostics-test.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("debug-bundle.json", json.dumps({"runtime_coverage": {"complete": True}}))
        z.writestr("manifest.json", json.dumps({
            "profile": {"name": "light", "complete_profile": False,
                        "declined": [{"file": "fixity.json", "reason": "heavy"}]}}))
        z.writestr("ordinary.json", json.dumps({"ran": True}))

    class _Job:
        def start(self, **kw):
            return {"started": True}

        def status(self):
            return {"state": "done", "result": {"path": str(path), "bytes": path.stat().st_size}}

    monkeypatch.setattr(bundle_mod, "_ALL_DIAG_JOB", _Job())
    out = rr._bundle(FakeCtx())

    assert out["measured"] is True
    assert out["profile"] == "light"
    assert out["complete_profile"] is False
    assert out["declined_members"] == ["fixity.json"]


# --------------------------------------------------------------------------- #
#  The field round (2026-09-24, docs/audit/16_…): RR-1 to RR-4, RR-6 to RR-8
# --------------------------------------------------------------------------- #
def _pool_timeout():
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    return PoolTimeout("QueuePool limit of size 6 overflow 2 reached, connection timed out, timeout 30.00")


def test_row5_starts_only_after_an_interim_report_already_holds_the_soak(fast, monkeypatch):
    """FD01: the soak's evidence is on disk before a job that can take days begins."""
    seen: list[dict] = []

    def _row5(ctx, run):
        fast["calls"].append("row5")
        for p in rr._run_dir().glob("oo-release-run-*-interim.json"):
            seen.append(json.loads(p.read_text(encoding="utf-8")))
        return {"mode_ok": True}
    monkeypatch.setattr(rr, "_row5_quarantine", _row5)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"], run_row5_quarantine=True))
    assert seen and seen[-1]["interim"] is True and seen[-1]["outcome"] is None
    done = {ph["name"]: ph["status"] for ph in seen[-1]["phases"]}
    assert done["soak"] == "measured" and done["collect"] == "measured" and done["bundle"] == "measured"
    assert "row5_quarantine" not in done
    assert res["report"]["board_rows"][[r["row"] for r in res["report"]["board_rows"]].index("G")]["status"] == "measured"


def test_collect_retries_a_pool_timeout_and_keeps_every_block_it_read(monkeypatch, tmp_path):
    """RR-2: one pool timeout used to discard every end-of-window reading. Now each block
    has its own session and the retry, and a block that still fails is named beside the
    others, which are kept."""
    import contextlib as _cl

    import src.api.wiki_lane as wl
    import src.catalog.qualification_integrity as qi
    import src.database.session as dbs
    import src.monitoring.expedition as ex
    import src.monitoring.forensics as fo
    import src.monitoring.p0_validation as p0
    import src.monitoring.soak_window as sw

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(rr, "POOL_RETRY_DELAYS_S", (0.01, 0.01, 0.01, 0.01))
    calls = {"sw": 0}

    def _soak_window(db, bar_hours):
        calls["sw"] += 1
        if calls["sw"] <= 2:
            raise _pool_timeout()
        return {"window": {"hours": 72.1, "reaches_bar": True}, "unmeasured": []}

    def _integrity(db):
        raise RuntimeError("integrity blew up")

    monkeypatch.setattr(sw, "soak_window", _soak_window)
    monkeypatch.setattr(qi, "qualification_integrity_report", _integrity)
    monkeypatch.setattr(p0, "_check_collector", lambda: {"verdict": "pass"})
    monkeypatch.setattr(dbs, "session_scope", lambda: _cl.nullcontext(None))
    monkeypatch.setattr(wl, "lane_counters_route", lambda window_days: {"measured": False, "reason": "lane-never-run"})
    monkeypatch.setattr(ex, "digest", lambda: {})
    monkeypatch.setattr(fo, "session_forensics", lambda: {})
    monkeypatch.setattr(rr, "_network_state", lambda: {})
    run = rr._Run(rr.RunParams(str(tmp_path / "d"), SECRET, online_probes=False))
    with pytest.raises(rr._PhaseError) as ei:
        rr._collect(FakeCtx(), run)
    part = ei.value.partial
    assert part["soak_window"]["window"]["reaches_bar"] is True, "the block that recovered is kept"
    assert calls["sw"] == 3 and [r["what"] for r in part["pool_retries"]] == ["soak_window", "soak_window"]
    assert part["qualification_integrity_live"] == {"measured": False, "error": "RuntimeError: integrity blew up"}
    assert part["collector"] == {"verdict": "pass"}
    assert "qualification_integrity_live" in str(ei.value)
    # ...and through the phase runner, the partial result lands in the phase record.
    ph = rr._run_phase(run, FakeCtx(), "collect", lambda: rr._collect(FakeCtx(), run))
    assert ph["status"] == "error" and ph["result"]["soak_window"]["window"]["hours"] == 72.1


def test_a_phase_that_raises_a_non_pool_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(rr, "POOL_RETRY_DELAYS_S", (0.01,))
    n = {"i": 0}

    def _boom():
        n["i"] += 1
        raise ValueError("not a pool timeout")
    with pytest.raises(ValueError):
        rr._retrying(FakeCtx(), "x", _boom, [])
    assert n["i"] == 1


def test_row_statuses_name_a_failed_reading_as_an_error_not_a_skip(fast, monkeypatch):
    """RR-3: the NUC's report said row B 'measured' with reaches_bar null and row D
    'skipped', after a 72-hour soak whose end-of-window reading failed."""
    def _collect(ctx, run):
        raise RuntimeError("QueuePool limit of size 6 overflow 2 reached")

    def _bundle(ctx):
        raise RuntimeError("zip exploded")
    monkeypatch.setattr(rr, "_collect", _collect)
    monkeypatch.setattr(rr, "_bundle", _bundle)
    rows = {r["row"]: r for r in rr.run_release_run(FakeCtx(), **_params(fast["dest"]))["report"]["board_rows"]}
    assert rows["B"]["status"] == "error" and "end-of-window reading failed" in rows["B"]["note"]
    assert rows["D"]["status"] == "error"
    assert rows["C"]["status"] == "error"
    assert rows["P"]["status"] == "error"
    assert rows["E"]["status"] == "measured", "the restored install's reading is still there"


def test_a_partial_collect_keeps_the_rows_it_can_answer(fast, monkeypatch):
    def _collect(ctx, run):
        raise rr._PhaseError("1 end-of-window reading(s) failed: qualification_integrity_live", partial={
            "soak_window": {"window": {"hours": 72.0, "reaches_bar": True}, "unmeasured": []},
            "qualification_integrity_live": {"measured": False, "error": "TimeoutError: pool"},
            "wiki_lane_counters": {"measured": False, "reason": "lane-never-run"}})
    monkeypatch.setattr(rr, "_collect", _collect)
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))["report"]
    rows = {r["row"]: r for r in rep["board_rows"]}
    assert {ph["name"]: ph["status"] for ph in rep["phases"]}["collect"] == "error"
    assert rows["B"]["status"] == "measured" and rows["B"]["evidence"]["reaches_bar"] is True
    assert rows["D"]["status"] == "measured"
    assert rows["E"]["evidence"]["live_corpus_after_drain"]["error"] == "TimeoutError: pool"
    assert rows["P"]["status"] == "not-measurable-here"


def test_a_suspend_during_the_soak_ends_the_stretch_and_starts_a_new_one(fast, monkeypatch):
    """RR-4: the bar is continuous collection, and a machine that slept was not
    collecting. The rule is the restart's: a new stretch, with the full window."""
    n = {"i": 0}

    def _advance(self):
        # The FIRST tick: every soak makes at least one, so no runner is too slow for it.
        n["i"] += 1
        return (900.0, 0.0, "boot-time") if n["i"] == 1 else (0.0, 0.0, "boot-time")
    monkeypatch.setattr(rr._Clocks, "advance", _advance)
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"], soak_hours=0.2 / 3600))["report"]
    assert len(rep["soak_stretches"]) == 2
    assert rep["soak_stretches"][0]["ended_by"] == "suspend" and rep["soak_stretches"][1]["ended_by"] == "window-complete"
    assert rep["suspends"] == [dict(rep["suspends"][0], seconds=900, clocks="boot-time", stretch=1)]
    b = next(r for r in rep["board_rows"] if r["row"] == "B")
    assert b["evidence"]["stretches"] == 2 and len(b["evidence"]["suspends_during_soak"]) == 1
    assert any("suspended for 900 s" in w for w in rep["warnings"])
    assert all("started_mono" not in st for st in rep["soak_stretches"]), "a process-local clock never reaches the report"


def test_a_clock_change_during_the_soak_is_recorded_and_moves_nothing(fast, monkeypatch):
    n = {"i": 0}

    def _advance(self):
        n["i"] += 1
        return (0.0, -43200.0, "boot-time") if n["i"] == 1 else (0.0, 0.0, "boot-time")
    monkeypatch.setattr(rr._Clocks, "advance", _advance)
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"], soak_hours=0.2 / 3600))["report"]
    assert len(rep["soak_stretches"]) == 1 and rep["soak_stretches"][0]["ended_by"] == "window-complete"
    adj = [c for c in rep["clock_adjustments"] if c.get("phase") == "soak"]
    assert adj and adj[0]["clock_moved_s"] == -43200
    assert rep["soak"]["elapsed_hours"] < 1, "the window is monotonic: a 12-hour step did not end it"


def test_every_phase_has_a_monotonic_duration_and_a_disagreeing_stamp_pair_is_recorded(monkeypatch, tmp_path):
    """RR-4, the NUC: p0_validation 'ended' at 08:02 before it 'started' at 19:29."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    run = rr._Run(rr.RunParams(str(tmp_path / "d"), SECRET))
    stamps = iter(["2026-09-19T19:29:21+02:00", "2026-09-19T08:02:55+02:00"])
    monkeypatch.setattr(rr, "_now_iso", lambda: next(stamps, "2026-09-19T08:02:56+02:00"))
    run.begin("p0_validation")
    ph = run.end("measured", "ok")
    assert ph["wall_s"] is not None and 0 <= ph["wall_s"] < 60
    adj = run.clock_adjustments[0]
    assert adj["phase"] == "p0_validation" and adj["clock_moved_s"] < -40000
    assert "wall_s is the duration" in adj["basis"]


def _build_real_archive(tmp_path, members, monkeypatch):
    """An archive written by the bundle's REAL writer -- never a hand-made zip (RR-1's
    lesson: the reader was tested against a layout the writer does not produce)."""
    import zipfile

    from src.api.diagnostics import bundle as bundle_mod

    monkeypatch.setattr(bundle_mod, "_all_diag_nondb_member_deadline_s", lambda: 0.2)
    path = tmp_path / "oo-all-diagnostics-real.zip"
    with zipfile.ZipFile(path, "w") as z:
        bundle_mod._write_all_diagnostics_zip(members, z)
    return path


def test_row_C_reads_coverage_and_member_outcomes_from_an_archive_the_real_writer_built(tmp_path, monkeypatch, fast):
    """RR-1 and RR-1b, against the real writer: the coverage block is at manifest.json ->
    run.runtime_coverage (it was read from debug-bundle.json and was always null), and a
    member skipped at its deadline or failed is ABSENT, replaced by a marker the zero-byte
    check cannot see."""
    def _slow():
        time.sleep(1.0)
        return {"late": True}

    def _boom():
        raise RuntimeError("member exploded")
    path = _build_real_archive(tmp_path, [("ok.json", lambda: {"ran": True}), ("slow.json", _slow),
                                          ("boom.json", _boom)], monkeypatch)
    read = rr._read_bundle_archive(str(path))
    assert read["runtime_coverage_from"] == "manifest.json run.runtime_coverage"
    assert read["coverage_complete"] is True
    assert read["skipped_deadline_members"] == ["slow.json"]
    assert read["error_members"] == ["boom.json"]
    assert read["zero_byte_members"] == [], "the markers are not empty: this is exactly the blind spot"
    assert read["outcomes_from"] == "manifest.json members[].outcome"
    monkeypatch.setattr(rr, "_bundle", lambda ctx: {**read, "measured": True, "path": str(path), "job_state": "done"})
    c = next(r for r in rr.run_release_run(FakeCtx(), **_params(fast["dest"]))["report"]["board_rows"] if r["row"] == "C")
    assert c["evidence"]["bar_satisfied_by_this_bundle"] is False
    assert "slow.json" in c["note"] and "boom.json" in c["note"]
    # ...and a clean archive from the same writer satisfies the clause.
    (tmp_path / "c").mkdir()
    clean = rr._read_bundle_archive(str(_build_real_archive(tmp_path / "c", [("ok.json", lambda: {"ran": True})], monkeypatch)))
    monkeypatch.setattr(rr, "_bundle", lambda ctx: {**clean, "measured": True, "path": "x", "job_state": "done"})
    c2 = next(r for r in rr.run_release_run(FakeCtx(), **_params(fast["dest"]))["report"]["board_rows"] if r["row"] == "C")
    assert c2["evidence"]["bar_satisfied_by_this_bundle"] is True


# -- row 5 with fake managers ------------------------------------------------ #
class _FakeJob:
    """A resumable manager whose status walks a script, one entry per poll."""

    def __init__(self, script, *, after_resume=None):
        self.script = list(script)
        self.after_resume = list(after_resume or [])
        self.calls: list[str] = []

    def start(self, **kw):
        self.calls.append("start")
        return {"state": "running"}

    def status(self):
        if len(self.script) > 1:
            return dict(self.script.pop(0))
        return dict(self.script[0])

    def resume(self):
        self.calls.append("resume")
        self.script = self.after_resume or self.script
        return {"state": "running"}

    def pause(self):
        self.calls.append("pause")
        self.script = [dict(self.script[0], state="paused", running=False)]


class _FakeSched:
    def __init__(self, running=True):
        self.running, self.calls = running, []

    def is_running(self):
        return self.running

    def stop(self, timeout=10.0):
        self.calls.append("stop")
        self.running = False
        return True

    def start(self):
        self.calls.append("start")
        self.running = True
        return True


@pytest.fixture
def row5(monkeypatch, tmp_path):
    import contextlib as _cl

    import src.analytics.figures as figs
    import src.analytics.quarantine_job as qj
    import src.analytics.reindex_job as rj
    import src.database.session as dbs
    import src.ingest as ingest
    import src.scheduler.runner as runner
    import src.wiki.service as ws

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(rr, "_TICK_S", 0.005)
    monkeypatch.setattr(rr, "POOL_RETRY_DELAYS_S", (0.01, 0.01))
    sched = _FakeSched()
    lane = {"streaming": True, "calls": []}
    monkeypatch.setattr(runner, "get_scheduler", lambda: sched)
    monkeypatch.setattr(runner, "exclusive_window_open", lambda: False)
    monkeypatch.setattr(ws, "lane_service_status", lambda: {"streaming": lane["streaming"]})
    monkeypatch.setattr(ws, "stop_wiki_lane", lambda timeout=5.0: lane["calls"].append("stop"))
    monkeypatch.setattr(ws, "start_wiki_lane", lambda: lane["calls"].append("start") or True)
    monkeypatch.setattr(ingest, "kill_switch_active", lambda: False)
    monkeypatch.setattr(dbs, "session_scope", lambda: _cl.nullcontext(None))
    monkeypatch.setattr(figs, "quarantine_composition", lambda db, limit=40: {"rows": [{"reason": "nav-soup-v2", "n": 8}]})
    jobs: dict = {}
    monkeypatch.setattr(qj, "get_quarantine_manager", lambda: jobs["q"])
    monkeypatch.setattr(rj, "get_reindex_manager", lambda: jobs["r"])
    run = rr._Run(rr.RunParams(str(tmp_path / "d"), SECRET, run_row5_quarantine=True))
    return {"sched": sched, "lane": lane, "jobs": jobs, "run": run}


_Q_DONE = {"state": "done", "running": False, "dry_run": False, "include_prose_gate": False,
           "articles_done": 10, "articles_total": 10, "percent": 100.0}
_R_DONE = {"state": "done", "running": False, "articles_done": 10, "articles_total": 10, "percent": 100.0}


def test_row5_pauses_collection_resumes_a_pool_timeout_and_puts_collection_back(row5):
    """RR-6 and RR-7: collection off for the re-index (FD02: 4 GB and 1 GB of swap), a
    job that died on a pool timeout resumed from its cursor, and collection put back."""
    row5["jobs"]["q"] = _FakeJob(
        [{"state": "running", "running": True, "articles_done": 3, "articles_total": 10},
         {"state": "error", "running": False, "error": "QueuePool limit of size 6 overflow 2 reached, connection timed out"}],
        after_resume=[_Q_DONE])
    row5["jobs"]["r"] = _FakeJob([{"state": "running", "running": True, "articles_done": 5, "articles_total": 10}, _R_DONE])
    out = rr._row5_quarantine(FakeCtx(), row5["run"])
    assert out["collection_paused"]["scheduler_was_running"] is True and out["collection_paused"]["wiki_lane_was_streaming"]
    assert row5["sched"].calls == ["stop", "start"] and row5["lane"]["calls"] == ["stop", "start"]
    assert out["collection_resumed"]["scheduler_restarted"] is True and out["collection_resumed"]["wiki_lane_restarted"] is True
    assert row5["jobs"]["q"].calls == ["start", "resume"]
    assert [r["what"] for r in out["retries"]] == ["quarantine job"]
    assert out["mode_ok"] is True and out["composition"]["rows"][0]["n"] == 8
    assert out["quarantine_progress"] and out["reindex_progress"], "the progress is sampled into the record"


def test_row5_never_reindexes_over_a_failed_quarantine_and_keeps_its_tally(row5):
    row5["jobs"]["q"] = _FakeJob([{"state": "error", "running": False, "error": "disk I/O error",
                                   "tally": {"scanned": 400}}])
    row5["jobs"]["r"] = _FakeJob([_R_DONE])
    with pytest.raises(rr._PhaseError) as ei:
        rr._row5_quarantine(FakeCtx(), row5["run"])
    part = ei.value.partial
    assert part["quarantine_final"]["tally"] == {"scanned": 400}
    assert "half-applied quarantine" in part["reindex_skipped"]
    assert row5["jobs"]["r"].calls == [], "no re-index over an incomplete quarantine"
    assert part["collection_resumed"]["scheduler_restarted"] is True, "collection comes back on the failure path too"


def test_a_stalled_row5_job_is_paused_and_reported_never_waited_on_forever(row5, monkeypatch):
    monkeypatch.setattr(rr, "ROW5_STALL_S", 0.05)
    row5["jobs"]["q"] = _FakeJob([_Q_DONE])
    row5["jobs"]["r"] = _FakeJob([{"state": "running", "running": True, "articles_done": 5, "articles_total": 10}])
    out = rr._row5_quarantine(FakeCtx(), row5["run"])
    assert row5["jobs"]["r"].calls == ["start", "pause"]
    assert out["reindex_final"]["stalled"]["at_count"] == 5 and "PAUSED" in out["reindex_final"]["stalled"]["basis"]
    assert "composition" not in out


def test_a_job_in_its_uncounted_tail_or_parked_for_an_import_is_not_stalled(row5, monkeypatch):
    monkeypatch.setattr(rr, "ROW5_STALL_S", 0.02)
    tail = {"state": "running", "running": True, "articles_done": 10, "articles_total": 10}
    parked = {"state": "running", "running": True, "articles_done": 4, "articles_total": 10, "parked_for_exclusive": True}
    row5["jobs"]["q"] = _FakeJob([_Q_DONE])
    row5["jobs"]["r"] = _FakeJob([parked] * 20 + [tail] * 20 + [_R_DONE])
    out = rr._row5_quarantine(FakeCtx(), row5["run"])
    assert "pause" not in row5["jobs"]["r"].calls and out["reindex_final"]["state"] == "done"


def test_a_cancel_during_row5_pauses_the_job_rather_than_leaving_it_running(row5):
    row5["jobs"]["q"] = _FakeJob([{"state": "running", "running": True, "articles_done": 1, "articles_total": 10}])
    ctx = FakeCtx()
    ctx.cancel()
    out = rr._row5_quarantine(ctx, row5["run"])
    assert row5["jobs"]["q"].calls == ["start", "pause"]
    assert "not discarded" in out["quarantine_final"]["paused_by"]


def test_row5_never_turns_collection_back_on_over_airplane_mode(row5, monkeypatch):
    import src.ingest as ingest

    row5["jobs"]["q"] = _FakeJob([_Q_DONE])
    row5["jobs"]["r"] = _FakeJob([_R_DONE])
    monkeypatch.setattr(ingest, "kill_switch_active", lambda: True)
    out = rr._row5_quarantine(FakeCtx(), row5["run"])
    assert row5["sched"].calls == ["stop"] and "airplane mode" in out["collection_resumed"]["scheduler"]


def test_row5_is_not_an_exclusive_window_because_both_its_jobs_park_inside_one():
    """Claiming the window would park the quarantine and the re-index -- they stand aside
    for an import -- so row 5 would wait on jobs waiting on it. Pinned on the source:
    the pause stops the collector directly and never opens the window."""
    from tests.js_source_helper import python_function_source

    src = (_ROOT / "src" / "monitoring" / "release_run.py").read_text(encoding="utf-8")
    body = python_function_source(src, "_pause_collection")
    assert "sched.stop(" in body and "exclusive_window(" not in body and "pause_for_exclusive_operation" not in body
    assert "set_network_mode" not in body, "no offline->online transition the operator did not consent to"


def _interrupted_in_row5(fast, *, collect_status="measured"):
    from src.monitoring.release_run import _write_state

    run = rr._Run(rr.RunParams(**_params(fast["dest"], run_row5_quarantine=True)))
    run.artifacts["backup_folder"] = str(fast["dest"] / "202609181200_OpenOmniscience_Backup")
    for name, extra in (("preflight", {"result": {"fresh_install_fits": True}}),
                        ("p0_validation", {"result": {"checks": {"p0_1_verify": {"verdict": "pass"}}}}),
                        ("fresh_install_restore", {"result": {"child": {"integrity": {"verdict": "consistent"}}}}),
                        ("arm_soak", {}), ("online_probes", {}),
                        ("soak", {"ended_by": "window-complete"}),
                        ("collect", {"result": {"soak_window": {"window": {"hours": 72.0, "reaches_bar": True}}}}),
                        ("bundle", {"result": {"measured": True, "coverage_complete": True}})):
        run.begin(name)
        status = collect_status if name == "collect" else "measured"
        run.end(status, "ok", **extra)
    run.soak = {"started_at": "2026-09-19T10:00:00+02:00", "elapsed_hours": 72.0, "ended_by": "window-complete",
                "ended_at": "2026-09-22T10:00:00+02:00", "stretch": 1, "hours_requested": 72.0}
    run.soak_stretches = [dict(run.soak)]
    run.begin("row5_quarantine")
    state = run.snapshot()
    state["pid"] = os.getpid() + 100000
    _write_state(state)
    return state


def test_a_restart_inside_row5_keeps_the_completed_soak(fast):
    """Row 5 now runs last and can take days: a restart inside it must not throw away a
    72-hour soak that finished."""
    state = _interrupted_in_row5(fast)
    rep = rr.run_release_run(FakeCtx(), resume=True, passphrase="")["report"]
    assert fast["calls"] == ["row5"], fast["calls"]
    names = [p["name"] for p in rep["phases"]]
    assert names.count("soak") == 1 and names[-1] == "row5_quarantine"
    assert rep["soak"]["ended_by"] == "window-complete" and rep["run_id"] == state["run_id"]
    assert any("including the completed soak" in w for w in rep["warnings"])
    b = next(r for r in rep["board_rows"] if r["row"] == "B")
    assert b["status"] == "measured" and b["evidence"]["reaches_bar"] is True


def test_a_resume_retakes_a_failed_reading_without_redoing_the_soak(fast):
    _interrupted_in_row5(fast, collect_status="error")
    rep = rr.run_release_run(FakeCtx(), resume=True, passphrase="")["report"]
    assert fast["calls"] == ["collect", "row5"], fast["calls"]
    assert any("taken again after a restart" in w for w in rep["warnings"])


def test_the_bundle_member_carries_the_live_run_when_no_saved_report_describes_it(fast):
    """RR-8: three bundles said "no 0.4 release run has been made yet" 61 hours into a run."""
    state = _interrupted_in_row5(fast)
    last = rr.last_release_run_report()
    assert last["available"] is False
    assert last["live_run"]["run_id"] == state["run_id"] and last["live_run"]["phase"] == "row5_quarantine"
    assert "interrupted" in last["live_run"]["status"] and state["run_id"] in last["note"]
    assert SECRET not in json.dumps(last)
    from src.api.diagnostics.bundle import _release_run_last

    assert _release_run_last()["live_run"]["run_id"] == state["run_id"], "the bundle member is the same reading"
    # An interim report of the same run is saved -> still shown beside it; a final one -> not.
    rr._write_report(rr._Run.from_state(rr.read_state(), ""), interim=True)
    assert rr.last_release_run_report()["live_run"]["run_id"] == state["run_id"]
    rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    assert "live_run" not in rr.last_release_run_report()


def test_the_text_rendering_shows_durations_and_clock_adjustments(fast):
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    rep = dict(res["report"], clock_adjustments=[{"phase": "p0_validation", "clock_moved_s": -43200}],
               suspends=[{"at": "x", "seconds": 900, "clocks": "boot-time"}])
    text = rr.render_release_run_text(rep)
    assert " took " in text and "CLOCK ADJUSTMENTS" in text and "SUSPENDS DURING THE SOAK" in text


def test_the_row5_label_states_the_cost_and_the_order_in_all_twelve_locales():
    html = _html()
    m = re.search(r'<input id="rr-row5"[^>]*> <span>([^<]+)</span>', html)
    assert m, "the row-5 checkbox keeps its label"
    label = m.group(1)
    assert "LAST" in label and "whole-corpus keyword re-index" in label and "collection paused" in label
    assert "days on a slow machine" in label, "the cost is stated where the choice is made (FD01)"
    new = ["unknown — nothing in this window recorded when collection ran",
           "not yet — {h} h more on the current collection stretch (stopping collection, a restart or a suspend starts it over)",
           "not yet — collection is not running", "Longest collection stretch", "Process up without a break",
           "{h} h reached at {when} — the process's half of the clause, not the bar",
           "not yet — {h} h more on the current stretch", label]
    for loc in ("en", "fr", "de", "es", "pt", "ru", "ar", "bn", "hi", "id", "ja", "zh"):
        data = json.loads((_ROOT / "src" / "static" / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        for k in new:
            assert k in data and str(data[k]).strip(), (loc, k)
        assert "also run 0.3 row 5 — the Tier-A quarantine pass (deferred by ruling A1; tick only to run it now)" not in data


def test_the_summary_draws_an_unknown_bar_as_unknown_and_the_process_half_beside_it():
    from tests.js_source_helper import function_source

    src = function_source(_diag_js(), "_chronoSummaryHtml")
    assert "s.bar_reached == null" in src, "an unrecorded window reads UNKNOWN, never 'not yet'"
    assert "s.process_bar" in src and "Process up without a break" in src
    assert "Longest collection stretch" in src
    from tests.js_source_helper import read_static

    tl = read_static("ootimeline.js")
    assert '("bar_current_stretch" in sm) ? sm.bar_current_stretch : sm.current_stretch' in tl


def test_a_row5_quarantine_paused_by_a_restart_is_continued_not_rescanned(row5):
    q = _FakeJob([dict(_Q_DONE, state="paused", running=False, articles_done=6)], after_resume=[_Q_DONE])
    row5["jobs"]["q"] = q
    row5["jobs"]["r"] = _FakeJob([_R_DONE])
    out = rr._row5_quarantine(FakeCtx(), row5["run"])
    assert q.calls == ["resume"] and out["quarantine_continued_from"] == 6


def test_a_paused_quarantine_in_ANOTHER_mode_is_refused_by_name_not_overwritten(row5):
    row5["jobs"]["q"] = _FakeJob([dict(_Q_DONE, state="paused", running=False, articles_done=6, dry_run=True)])
    row5["jobs"]["r"] = _FakeJob([_R_DONE])
    with pytest.raises(RuntimeError, match="different quarantine run is paused"):
        rr._row5_quarantine(FakeCtx(), row5["run"])
    assert row5["sched"].calls == ["stop", "start"], "collection is put back on a refusal too"
