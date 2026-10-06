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
import logging
import os
import re
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from src.monitoring import release_run as rr

_ROOT = Path(__file__).resolve().parent.parent
NEEDLE = "hunter2-never-on-disk"


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
                                        "auto_repairable_total": 3, "not_auto_repaired_total": 2,
                                        "not_auto_repaired_measured_here_total": 1, "not_auto_repaired_held_total": 1,
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
                "qualification_integrity_live": {"verdict": "consistent", "laundered_total": 0, "demoted_total": 0,
                                                 "auto_repairable_total": 5, "not_auto_repaired_measured_here_total": 4},
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
    base = {"dest_dir": str(dest), "passphrase": NEEDLE, "soak_hours": 0.00005}
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
    # Row 5 of 0.3 is 0.4 board row W (ruling RC01 = a, 2026-09-27); "G" is the maintainer's flip.
    assert set(rows) == {"A", "B", "C", "D", "E", "W", "J", "K", "I", "P", "Q", "T"}
    assert rows["A"]["status"] == "measured" and rows["A"]["evidence"]["integrity_verdict"] == "consistent"
    # which inversions the boot repair takes and which it leaves on purpose ride the board rows
    a_ev = rows["A"]["evidence"]
    assert (a_ev["auto_repairable_total"], a_ev["not_auto_repaired_total"],
            a_ev["not_auto_repaired_measured_here_total"], a_ev["not_auto_repaired_held_total"]) == (3, 2, 1, 1)
    e_live = rows["E"]["evidence"]["live_corpus_after_drain"]
    assert (e_live["auto_repairable_total"], e_live["not_auto_repaired_measured_here_total"]) == (5, 4)
    assert rows["W"]["status"] == "skipped"
    assert "row W stays open" in rows["W"]["note"] and "ruling A1" not in rows["W"]["clause"]
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
        assert NEEDLE not in p.read_text(encoding="utf-8"), p
    assert NEEDLE not in json.dumps(res["report"])
    assert NEEDLE not in json.dumps(rr.read_state())


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
    reading wearing a three-day label. The final run report then supersedes it.

    About the SOAK'S OWN interim, deterministically, since 2026-09-24. Every phase now writes
    an interim as it ends (RR-8), so "an interim file exists by collection time" held even
    when the soak loop wrote none: with a 0.6 s pause at the soak's first heartbeat the loop
    skipped its interim and this test still passed. It now asserts on the interim only the
    loop writes -- the window still OPEN (``ended_by`` is None) -- makes it due on the loop's
    first pass, and ends the window there with "collect now" instead of racing a sub-second
    deadline. The 10 s deadline is only how a loop that never writes it fails, fast."""
    monkeypatch.setattr(rr, "INTERIM_REPORT_INTERVAL_S", 0.0)
    mid_soak: list[dict] = []
    original_write = rr._write_report

    def _write_report(run, *, interim):
        path = original_write(run, interim=interim)
        if interim:
            written = json.loads(path.read_text(encoding="utf-8"))
            if written["soak"].get("started_at") and written["soak"].get("ended_by") is None:
                mid_soak.append(written)
                rr.request_collect_now()
        return path
    monkeypatch.setattr(rr, "_write_report", _write_report)
    try:
        res = rr.run_release_run(FakeCtx(), **_params(fast["dest"], soak_hours=10.0 / 3600))
    finally:
        rr._COLLECT_NOW.clear()
    assert mid_soak, "the soak loop wrote no interim report while its window was open"
    assert all(r["interim"] is True for r in mid_soak), [r["interim"] for r in mid_soak]
    assert all(r["outcome"] is None for r in mid_soak)
    assert res["report"]["soak"]["ended_by"] == "collect-now"
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
    for row in "ABCDEIJKPQTW":
        assert f"row {row} --" in text, row
    assert "never a score" in text
    assert "[MEASURED]" in text and "[SKIPPED]" in text
    assert NEEDLE not in text


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
    run = rr._Run(rr.RunParams(str(tmp_path / "data" / "inside"), NEEDLE))
    with pytest.raises(ValueError):
        rr._preflight(run)


def test_the_real_preflight_records_the_facts_a_reader_needs(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(rr, "_article_count", lambda: 412)
    run = rr._Run(rr.RunParams(str(dest), NEEDLE, profile="million"))
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
    assert '.restore-release-run-' in body, (
        "the throwaway install keeps its recognisable name: nothing sweeps the destination, so a directory a "
        "killed parent left behind is found, by a person and by these tests, through that prefix"
    )


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
                    json={"dest_dir": str(tmp_path / "elsewhere"), "passphrase": NEEDLE, "profile": "million"})
    assert r.status_code == 200 and r.json()["started"] is True
    assert NEEDLE not in r.text
    deadline = time.time() + 10
    while time.time() < deadline and not ran:
        time.sleep(0.05)
    assert ran.get("profile") == "million" and ran.get("passphrase") == NEEDLE
    st = client.get("/api/diagnostics/release-run/status")
    assert st.status_code == 200 and NEEDLE not in st.text
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
    assert r.status_code == 200 and "BOARD ROWS" in r.text and NEEDLE not in r.text
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
    assert 'data-on-click="releaseRunCollect(this)"' in sec and 'data-on-click="releaseRunCancel()"' in sec
    assert 'data-on-click="releaseRunStatus(this)"' in sec
    # The row-W opt-in (0.3's row 5) defaults OFF: ticking it is the operator's act, never the button's.
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
            # The shape the real helper writes: its own ok and its exit status are what make a restore one.
            run.end("measured", "ok", result={"returncode": 0, "child": {
                "ok": True, "restore": {"committed": True}, "integrity": {"verdict": "consistent"}}})
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
    assert NEEDLE not in json.dumps(rep)


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
    assert resume_preflight(NEEDLE)["unlock_needed"] is True
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
    r = client.post("/api/diagnostics/release-run/resume", json={"passphrase": NEEDLE})
    assert r.status_code == 200 and r.json()["started"] is True and NEEDLE not in r.text
    deadline = time.time() + 10
    while time.time() < deadline and not ran:
        time.sleep(0.05)
    assert ran.get("resume") is True and ran.get("passphrase") == NEEDLE


# --------------------------------------------------------------------------- #
#  The chronology box and the resume button (2026-09-18)
# --------------------------------------------------------------------------- #
def test_the_chronology_box_sits_above_the_run_box_with_its_controls_and_the_module_loaded():
    html = _html()
    box = html.index('id="chronology-box"')
    assert box < html.index('id="release-run-box"'), "the chronology reads first: it is what a returning operator opens"
    assert html.index('data-adv="diagnostics"') < box
    for needle in ('data-on-click="loadChronology(this)"', 'id="chrono-anchor"', '<option value="run">', '<option value="install">',
                   'id="chrono-summary"', 'id="chrono-timeline"', 'id="chrono-legend"', 'id="chrono-status"'):
        assert needle in html, needle
    assert '<script src="/static/ootimeline.js"></script>' in html, "the layout module must be loaded"
    assert html.index('/static/ootimeline.js') < html.index('/static/app-diagnostics.js'), "geometry before its wiring"
    # the resume button: hidden until a status says the run is resumable
    seg = html[html.index('id="rr-resume-btn"'):]
    seg = seg[:seg.index(">")]
    assert 'data-on-click="releaseRunResume(this)"' in seg and 'display:none' in seg


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
    w = res["report"]["board_rows"][[r["row"] for r in res["report"]["board_rows"]].index("W")]
    assert w["status"] == "measured" and "v0.4.0" in w["note"] and "v0.3.0" not in w["note"]


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
    run = rr._Run(rr.RunParams(str(tmp_path / "d"), NEEDLE, online_probes=False))
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
    run = rr._Run(rr.RunParams(str(tmp_path / "d"), NEEDLE))
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
    run = rr._Run(rr.RunParams(str(tmp_path / "d"), NEEDLE, run_row5_quarantine=True))
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
                        ("fresh_install_restore", {"result": {"returncode": 0, "child": {
                            "ok": True, "restore": {"committed": True}, "integrity": {"verdict": "consistent"}}}}),
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
    assert NEEDLE not in json.dumps(last)
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
    # RC01 = a (2026-09-27): the pass is 0.4 row W, required before the v0.4.0 tag, no longer "deferred".
    assert "row W" in label and "v0.4.0" in label and "ruling A1" not in label
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
        assert not [k for k in data if "deferred by ruling A1" in k], (loc, "the pre-RC01 label is re-keyed")


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


# --------------------------------------------------------------------------- #
#  A restore is what its child reports (2026-10-01; the diagnostics round of 2026-09-30)
# --------------------------------------------------------------------------- #
# Two of the sixteen bundles held a run whose fresh-install restore had FAILED (both restores ran
# on 2026-09-26) -- the engine's own staging check refused it after 128 s (20260930-085218),
# another died with "Error creating function" after 53 minutes (20260930-085230) -- and both
# recorded the phase as ``measured`` and rows A and I as ``measured`` over an empty ``restore``
# block (row K read ``measured`` from the P0 trio, its scan of the restored corpus empty): the
# phase was ok whenever the PARENT returned. The tests drive the REAL parent function (its
# polling, its reading of the child's result, its clean-up) against a child whose outcome they
# choose.
_REAL_RESTORE = rr._fresh_install_restore  # the `fast` fixture replaces it per test; this is the real one
_REAL_P0 = rr._p0_into_dated_folder  # likewise: the P0 phase the run really has, to drive with the engine stubbed

_SPACE_ERROR = ("BackupSpaceError: Not enough free space for the restore staging: needs about 38.0 GB, only 14.7 GB "
                "free at /d/.restore-release-run-own-backup-1/restore-staging. Free up space or choose another "
                "location, or use the large-data/volume backup for a big corpus.")

_OK_CHILD = {"ok": True, "restore": {"kind": "volume-set", "committed": True},
             "counts": {"articles": 412, "sources": 9, "keywords": 30},
             "integrity": {"verdict": "consistent", "laundered_total": 0, "demoted_total": 0},
             "country_code_scan": {"duplicates": 0}, "peak_rss_mb": 120.0}


def _child_process(monkeypatch, *, payload, returncode,
                   stderr="INFO  [alembic.runtime.migration] Context impl SQLiteImpl."):
    """Put a stand-in for the restore child behind the REAL ``_fresh_install_restore``: a
    process that has already exited with ``returncode`` and wrote ``payload`` where the parent
    asked (``OO_RELEASE_RUN_OUT``), or wrote nothing when ``payload`` is None, and said
    ``stderr``. Replaced inside release_run only, so nothing else in the process loses
    ``subprocess``."""

    class _Proc:
        def __init__(self, argv, **kw):
            self.returncode = returncode
            if payload is not None:
                Path(kw["env"]["OO_RELEASE_RUN_OUT"]).write_text(json.dumps(payload), encoding="utf-8")

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            return (json.dumps(payload) if payload is not None else ""), stderr

    monkeypatch.setattr(rr, "subprocess", types.SimpleNamespace(
        Popen=_Proc, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(rr, "_fresh_install_restore", _REAL_RESTORE)


_FAILED_RESTORES = {
    # 20260930-085218: refused by the engine's staging check
    "no-room": ({"ok": False, "error": _SPACE_ERROR, "elapsed_s": 125.8}, 1, "38.0 GB"),
    # 20260930-085230: died after 53 minutes
    "died": ({"ok": False, "error": "OperationalError: Error creating function", "elapsed_s": 3192.7}, 1,
             "Error creating function"),
    # killed (an OOM kill, a crash): no result at all
    "killed": (None, -9, "left no result (exit status -9)"),
    # a result that says ok, from a process that did not end cleanly
    "unclean": (dict(_OK_CHILD), 139, "did not end cleanly"),
    # run_restore RETURNS a refusal (no exception), so the child goes on and says ok over nothing
    "refused": ({**_OK_CHILD, "restore": {"kind": "volume-set", "committed": False,
                                          "refused": "post-merge verification failed; live database untouched"}},
                0, "post-merge verification failed"),
}


@pytest.mark.parametrize("shape", sorted(_FAILED_RESTORES))
def test_a_restore_whose_child_failed_reads_error_and_is_no_evidence_for_rows_a_e_i_k(fast, monkeypatch, shape):
    payload, rc, fragment = _FAILED_RESTORES[shape]
    _child_process(monkeypatch, payload=payload, returncode=rc)
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))["report"]
    phase = {ph["name"]: ph for ph in rep["phases"]}["fresh_install_restore"]
    assert phase["status"] == "error" and fragment in phase["detail"], phase
    # what the child DID leave stays in the record (RR-2): its exit status and its own words
    kept = rep["phase_results"]["fresh_install_restore"]
    assert kept["returncode"] == rc and kept["child"] == payload
    rows = {r["row"]: r for r in rep["board_rows"]}
    for letter in ("A", "I"):
        assert rows[letter]["status"] == "error", (letter, rows[letter])
        assert fragment in rows[letter]["note"], (letter, rows[letter]["note"])
    assert rows["I"]["evidence"]["restore"] is None and rows["I"]["evidence"]["elapsed_s"] is None
    # row E keeps the LIVE corpus's own reading and says the restored install's is not counted
    assert rows["E"]["evidence"]["restored_corpus"] is None and "NOT COUNTED" in rows["E"]["note"]
    # row K's status is the P0 trio's; the scan that needs the restore is not counted and says why
    assert rows["K"]["status"] == "measured"
    assert rows["K"]["evidence"]["duplicate_key_scan_on_restored_corpus"] is None
    assert "NOT COUNTED" in rows["K"]["note"] and "NOT taken" not in rows["K"]["note"], rows["K"]["note"]
    for letter in "EK":  # row A leads with the reason, and the two rows say so
        assert rows[letter]["note"].endswith("(row A names why)"), (letter, rows[letter]["note"])
    # row A leads with the fact that matters: a restore that ended is not COUNTED (not "did not complete":
    # a child that committed and then crashed did complete one)
    assert rows["A"]["note"].startswith("this run does NOT COUNT its fresh-install restore"), rows["A"]["note"]
    assert "did not complete" not in rows["A"]["note"] and "FAILED" not in rows["A"]["note"]
    assert rep["summary"]["any_phase_error"] is True
    # a failed restore does not end the run: the soak was armed and the end-of-window readings taken
    assert "arm" in fast["calls"] and "collect" in fast["calls"] and rep["outcome"] == "done"
    assert not list(fast["dest"].glob(".restore-release-run-*")), "the throwaway install and its result file go on a failure too"
    assert NEEDLE not in json.dumps(rep)


def test_a_restore_whose_child_reports_ok_and_exits_zero_still_reads_measured(fast, monkeypatch):
    _child_process(monkeypatch, payload=dict(_OK_CHILD), returncode=0)
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))["report"]
    assert {ph["name"]: ph["status"] for ph in rep["phases"]}["fresh_install_restore"] == "measured"
    rows = {r["row"]: r for r in rep["board_rows"]}
    assert rows["A"]["status"] == "measured" and rows["A"]["evidence"]["integrity_verdict"] == "consistent"
    assert rows["I"]["status"] == "measured" and rows["I"]["evidence"]["restore"]["committed"] is True
    assert rows["K"]["evidence"]["duplicate_key_scan_on_restored_corpus"] == {"duplicates": 0}
    assert "NOT COUNTED" not in rows["K"]["note"] and "NOT COUNTED" not in rows["E"]["note"]
    assert "NOT COUNT" not in rows["A"]["note"] and "NOT COUNT" not in rows["I"]["note"]
    assert not list(fast["dest"].glob(".restore-release-run-*"))


def test_a_cancel_while_the_child_runs_stays_cancelled_and_is_not_a_failed_restore(fast, monkeypatch):
    class _Proc:
        def __init__(self, argv, **kw):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(rr, "subprocess", types.SimpleNamespace(
        Popen=_Proc, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired))
    run = rr._Run(rr.RunParams(**_params(fast["dest"])))
    ctx = FakeCtx()
    ctx.cancel()
    ph = rr._run_phase(run, ctx, "fresh_install_restore",
                       lambda: _REAL_RESTORE(ctx, run, fast["dest"] / "backup", label="own-backup"))
    assert ph["status"] == "cancelled" and ph["result"]["returncode"] == -15, ph
    rows = {r["row"]: r for r in rr.board_rows(run)}
    assert rows["A"]["status"] == "cancelled" and "NOT COUNT" not in rows["A"]["note"]
    assert rows["I"]["status"] == "cancelled"


def test_a_child_that_cannot_be_started_is_no_restore_that_ended_so_no_row_says_it_was_not_counted(
        fast, monkeypatch):
    """The other end of ``test_a_restore_whose_child_failed_...``: the interpreter cannot be executed, so there
    is no restore that ended and was left out of the count. Row A says the restore did not complete, with the
    phase's own detail, and no row claims a restore was NOT COUNTED."""
    def cannot_start(*a, **k):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'python'")

    monkeypatch.setattr(rr, "subprocess", types.SimpleNamespace(
        Popen=cannot_start, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(rr, "_fresh_install_restore", _REAL_RESTORE)
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))["report"]
    phase = {ph["name"]: ph for ph in rep["phases"]}["fresh_install_restore"]
    assert phase["status"] == "error" and "No such file or directory" in phase["detail"], phase
    assert "fresh_install_restore" not in rep["phase_results"], "no child ran, so there is no result to keep"
    rows = {r["row"]: r for r in rep["board_rows"]}
    assert rows["A"]["status"] == "error"
    assert rows["A"]["note"].startswith("the fresh-install restore did not complete here -- FileNotFoundError"), rows["A"]["note"]
    assert rows["I"]["status"] == "error" and "did not complete here" in rows["I"]["note"]
    for letter in ("A", "E", "I", "K"):
        assert "NOT COUNT" not in rows[letter]["note"], (letter, rows[letter]["note"])
    assert "absent because its restore did not complete here" in rows["K"]["note"]
    assert rows["K"]["evidence"]["duplicate_key_scan_on_restored_corpus"] is None
    assert NEEDLE not in json.dumps(rep)
    assert not list(fast["dest"].glob(".restore-release-run-*")), "no empty throwaway directory is left for a child that never ran"


@pytest.mark.parametrize("keep", [False, True], ids=["install removed", "install kept"])
def test_a_child_that_cannot_be_started_leaves_no_directory_behind_kept_install_or_not(fast, monkeypatch, keep):
    """The directory is made BEFORE the child starts, so a start that fails (no interpreter, no process
    slot, no memory) left an empty one in a destination nothing sweeps. MUTATION TARGET: the cleanup on
    that path, and a cleanup that only runs when the run does not keep the install (an empty directory is
    nothing a kept install's reader wants)."""
    def cannot_start(*a, **k):
        raise PermissionError("[Errno 13] Permission denied: 'python'")

    monkeypatch.setattr(rr, "subprocess", types.SimpleNamespace(
        Popen=cannot_start, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired))
    run = rr._Run(rr.RunParams(**_params(fast["dest"], keep_fresh_install=keep)))
    ctx = FakeCtx()
    ph = rr._run_phase(run, ctx, "fresh_install_restore",
                       lambda: _REAL_RESTORE(ctx, run, fast["dest"] / "backup", label="own-backup"))
    assert ph["status"] == "error" and "Permission denied" in ph["detail"], ph
    assert not list(fast["dest"].glob(".restore-release-run-*")), "the directory made for a child that never ran is removed"


def test_each_restore_attempt_has_a_directory_of_its_own_so_a_later_run_never_restores_into_or_removes_an_earlier_one(
        fast, monkeypatch):
    """The directory was named after the label and the process id and made with ``exist_ok``, so a second run in
    the same server process (allowed once the first has finished) restored INTO the install an earlier run had
    kept, and a run that did not keep its install deleted it. Measured with the real child before the fix: the
    second run's kept install held two journals, a third run with another passphrase could not open the
    database, and a fourth that kept nothing left no directory at all. MUTATION TARGETS: the random part of
    the name, and the name's process id and label (the prefix a person looks for stays)."""
    _journalling_child(monkeypatch, returncode=0)
    # what an earlier build, an earlier run or a killed parent left, under the name this attempt used to get
    earlier = fast["dest"] / f".restore-release-run-own-backup-{os.getpid()}"
    earlier.mkdir()
    (earlier / "earlier.txt").write_text("an earlier install", encoding="utf-8")
    made: list[Path] = []
    for keep in (True, True, False):
        run = rr._Run(rr.RunParams(**_params(fast["dest"], keep_fresh_install=keep)))
        ctx = FakeCtx()
        ph = rr._run_phase(run, ctx, "fresh_install_restore",
                           lambda run=run, ctx=ctx: _REAL_RESTORE(ctx, run, fast["dest"] / "backup", label="own-backup"))
        made.append(Path(ph["result"]["fresh_dir"]))
    assert len({d.name for d in made}) == 3 and earlier not in made, [d.name for d in made]
    assert all(d.name.startswith(f".restore-release-run-own-backup-{os.getpid()}-") for d in made), made
    assert made[0].is_dir() and made[1].is_dir(), "a kept install stays, whatever runs after it"
    assert not made[2].exists(), "a run that keeps nothing removes its own directory"
    assert (earlier / "earlier.txt").read_text(encoding="utf-8") == "an earlier install", (
        "the directory an earlier attempt left is neither restored into nor removed by this one"
    )
    left = sorted(d.name for d in fast["dest"].glob(".restore-release-run-*") if d.is_dir())
    assert left == sorted([earlier.name, made[0].name, made[1].name]), left


def test_an_attempt_that_finds_its_directory_taken_restores_nothing_and_removes_nothing(fast, monkeypatch):
    """MUTATION TARGET: ``exist_ok=False``. Should the random part ever repeat, the attempt refuses to go on
    rather than restore into what is there, and what is there is not removed (it was not made by this attempt)."""
    monkeypatch.setattr(rr, "secrets", types.SimpleNamespace(token_hex=lambda n=4: "same"))
    taken = fast["dest"] / f".restore-release-run-own-backup-{os.getpid()}-same"
    taken.mkdir()
    (taken / "earlier.txt").write_text("an earlier install", encoding="utf-8")
    started: list[int] = []
    monkeypatch.setattr(rr, "subprocess", types.SimpleNamespace(
        Popen=lambda *a, **k: started.append(1), PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired))
    run = rr._Run(rr.RunParams(**_params(fast["dest"], keep_fresh_install=False)))
    ctx = FakeCtx()
    ph = rr._run_phase(run, ctx, "fresh_install_restore",
                       lambda: _REAL_RESTORE(ctx, run, fast["dest"] / "backup", label="own-backup"))
    assert ph["status"] == "error" and "FileExistsError" in ph["detail"], ph
    assert started == [], "no child was started into a directory that was not new"
    assert (taken / "earlier.txt").read_text(encoding="utf-8") == "an earlier install"


def test_a_child_that_writes_more_than_a_pipe_holds_is_read_while_it_runs_and_is_not_left_blocked(fast, monkeypatch):
    """The parent waited for the child with ``poll`` and read its pipes only after it had exited, so a child that
    wrote more than a pipe holds (64 KiB on Linux) blocked in its write until the cancel: 60,000 bytes returned,
    70,000 did not (measured). The real results are about 10 KB; what nothing caps is a repair list or a long
    traceback, and a hang that looks like a slow restore is the failure the operator cannot tell from one. A real
    child here writes 300,000 bytes to each pipe, goes on for most of a second, and then writes its result. A
    watchdog cancels the run after 40 s, so a regression fails with that fact rather than hanging the suite.
    MUTATION TARGETS: the read inside the wait, and a wait that ends at its first timeout instead of going on in
    turns (a restore takes hours: each turn renews the progress line and is where a cancel lands)."""
    real_popen = subprocess.Popen
    script = (
        "import json, os, sys, time\n"
        "sys.stdout.write('o' * 300_000)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('e' * 300_000 + 'THE-END')\n"
        "sys.stderr.flush()\n"
        "time.sleep(0.8)\n"
        "open(os.environ['OO_RELEASE_RUN_OUT'], 'w', encoding='utf-8').write(json.dumps(" + repr(_OK_CHILD) + "))\n"
    )
    monkeypatch.setattr(rr, "_RESTORE_POLL_S", 0.1)
    monkeypatch.setattr(rr, "subprocess", types.SimpleNamespace(
        Popen=lambda argv, **kw: real_popen([sys.executable, "-c", script], **kw),
        PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired))
    run = rr._Run(rr.RunParams(**_params(fast["dest"])))
    ctx = FakeCtx()
    watchdog = threading.Timer(40.0, ctx.cancel)
    watchdog.start()
    t0 = time.monotonic()
    try:
        ph = rr._run_phase(run, ctx, "fresh_install_restore",
                           lambda: _REAL_RESTORE(ctx, run, fast["dest"] / "backup", label="own-backup"))
    finally:
        watchdog.cancel()
    assert not ctx.stopping, "the child was still blocked on a full pipe when the watchdog cancelled the run"
    assert ph["status"] == "measured", ph
    assert time.monotonic() - t0 < 30
    turns = [d for _done, _total, d in ctx.progress if d and d.startswith("fresh install (")]
    assert len(turns) >= 3, f"the wait went on in turns while the child ran: {turns}"
    tail = ph["result"]["stderr_tail"]
    assert len(tail) == 4000 and tail.endswith("e" * 3993 + "THE-END"), "the end of what the child wrote is kept"
    assert not list(fast["dest"].glob(".restore-release-run-*"))


def test_the_passphrase_is_out_of_what_any_phases_exception_says_in_the_report_and_in_the_log(
        fast, monkeypatch, caplog):
    """The module docstring says the passphrase is in no log line and no field of the report. The restore's
    own text was scrubbed where it is built; this is every OTHER phase, whose exception could name it (a
    command line, a path the operator typed). MUTATION TARGETS: the detail of an error, of a refusal and of
    a phase that failed part of the way, and the log record of each (the traceback included, which the error
    log keeps and a debug bundle carries)."""
    class _Refusal(Exception):
        pass

    def boom(ctx):
        raise RuntimeError(f"could not open the backup with {NEEDLE}")

    monkeypatch.setattr(rr, "_bundle", boom)
    with caplog.at_level(logging.WARNING, logger="monitoring.release_run"):
        res = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    rep = res["report"]
    detail = {ph["name"]: ph for ph in rep["phases"]}["bundle"]["detail"]
    assert {ph["name"]: ph["status"] for ph in rep["phases"]}["bundle"] == "error"
    assert detail.startswith("RuntimeError: could not open the backup with ") and "***redacted***" in detail
    for artifact in (Path(res["path"]), rr._state_path()):
        assert NEEDLE not in artifact.read_text(encoding="utf-8"), artifact
    assert NEEDLE not in json.dumps(rep)
    records = [r for r in caplog.records if r.name == "monitoring.release_run" and "bundle" in r.getMessage()]
    assert records, "the failure is still logged"
    for r in records:
        assert NEEDLE not in r.getMessage() and not r.exc_text and NEEDLE not in str(r.exc_info), r.getMessage()
    assert NEEDLE not in caplog.text
    assert "RuntimeError" in caplog.text, "the exception line is still there to read, scrubbed"

    # A refusal and a phase that failed part of the way read the same.
    run = rr._Run(rr.RunParams(**_params(fast["dest"])))
    ctx = FakeCtx()

    def refuse():
        raise _Refusal(f"{NEEDLE} is not a valid destination")

    def part_way():
        raise rr._PhaseError(f"row 5 stopped after reading {NEEDLE}", partial={"seen": 3})

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="monitoring.release_run"):
        refused = rr._run_phase(run, ctx, "refusing", refuse, refusals=(_Refusal,))
        partial = rr._run_phase(run, ctx, "part_way", part_way)
    assert refused["status"] == "refused" and "***redacted***" in refused["detail"], refused
    assert partial["status"] == "error" and "***redacted***" in partial["detail"] and partial["result"] == {"seen": 3}, partial
    assert NEEDLE not in json.dumps([refused, partial]) and NEEDLE not in caplog.text

    # The cut to 400 characters comes AFTER the scrub: a cut through the passphrase would leave a fragment
    # of it that no replacement can find (the restore's own text is held to the same rule).
    def straddles():
        raise RuntimeError("x" * 381 + NEEDLE)  # "RuntimeError: " is 14 characters: the passphrase starts at 395

    cut = rr._run_phase(run, ctx, "straddling", straddles)
    assert len(cut["detail"]) == 400 and cut["detail"].endswith("x***re"), cut["detail"][-12:]
    assert NEEDLE[:3] not in cut["detail"], "no fragment of the passphrase survives the cut"


@pytest.mark.parametrize("chain", ["cause", "context"])
def test_a_passphrase_only_the_cause_of_an_exception_names_is_out_of_the_log_too(fast, caplog, chain):
    """The coordinator's delta check of #1312, N4. The failure's own message is scrubbed, and the log record
    is scrubbed whenever the passphrase is anywhere in the TRACEBACK, including the failure it wraps:
    ``raise X from Y`` (``__cause__``) or a failure raised while another was being handled (``__context__``)
    puts Y's words in the traceback beneath a message that is clean. MUTATION TARGET: a check made on the
    exception's own text instead of the whole formatted traceback (the record would then carry the
    exception, and the error log or any handler would print the chain)."""
    run = rr._Run(rr.RunParams(**_params(fast["dest"])))

    def wrapped():
        if chain == "cause":
            raise RuntimeError("could not open the backup") from OSError(f"cannot read {NEEDLE}")
        try:
            raise OSError(f"cannot read {NEEDLE}")
        except OSError:
            raise RuntimeError("could not open the backup")  # noqa: B904 - the implicit chain is the case

    with caplog.at_level(logging.WARNING, logger="monitoring.release_run"):
        ph = rr._run_phase(run, FakeCtx(), "chained", wrapped)
    assert ph["status"] == "error" and ph["detail"] == "RuntimeError: could not open the backup", ph
    assert NEEDLE not in json.dumps(ph)
    (record,) = [r for r in caplog.records if r.name == "monitoring.release_run" and "chained" in r.getMessage()]
    # What a handler would print: the message, the traceback text a formatter caches, and a formatted exc_info.
    shown = record.getMessage() + (record.exc_text or "") + (
        logging.Formatter().formatException(record.exc_info) if record.exc_info else ""
    )
    assert NEEDLE not in shown and NEEDLE not in caplog.text
    assert "cannot read" in caplog.text, "the cause is still there to read, scrubbed"


def test_a_repr_of_the_run_parameters_never_prints_the_passphrase():
    """A log line that formats the parameters, a traceback that shows a dataclass and a debugger all print the
    repr, which listed ``passphrase=...`` (the coordinator's delta check of #1312, B1, latent). MUTATION
    TARGET: ``repr=False`` on the field."""
    params = rr.RunParams("some-dest", NEEDLE)
    assert NEEDLE not in repr(params) and NEEDLE not in str(params)
    assert "dest_dir='some-dest'" in repr(params), "the other fields still print"


def test_a_p0_failure_that_names_the_passphrase_leaves_it_in_no_file_the_run_or_the_phase_writes(fast, monkeypatch):
    """The coordinator's delta check of #1312, B1, through the REAL P0 phase: the backup engine raises with the
    passphrase in its message, the P0 check catches it and writes the words into its report, the phase copies
    the check's reason into its result, and the run writes that to its state file and its reports. The P0
    report is a file the debug bundle carries. MUTATION TARGET: the scrub where the check makes the text
    (``p0_validation._exception_text``), which nothing downstream replaces: no file under the data directory
    or the destination may hold the passphrase."""
    def boom(*args, **kwargs):
        raise RuntimeError(f"could not write the backup of {NEEDLE} to the drive")

    monkeypatch.setattr("src.backup.artifact.write_volume_backup", boom)
    monkeypatch.setattr(rr, "_p0_into_dated_folder", _REAL_P0)
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    report = res["report"]
    reason = report["phase_results"]["p0_validation"]["checks"]["p0_1_backup"]["reason"]
    assert reason.endswith("RuntimeError: could not write the backup of ***redacted*** to the drive"), reason
    p0_files = sorted((fast["data"] / "diagnostics").glob("oo-p0-validation-*.json"))
    assert len(p0_files) == 1 and "***redacted***" in p0_files[0].read_text(encoding="utf-8"), (
        "the P0 report is where the words were written: the scan below must have looked at it"
    )
    holders = [p for root in (fast["data"], fast["dest"]) for p in _all_files(root) if NEEDLE.encode() in p.read_bytes()]
    assert holders == [], holders
    assert NEEDLE not in json.dumps(report) and NEEDLE not in json.dumps(rr.read_state())


def test_a_passphrase_that_is_also_a_verdict_word_does_not_close_the_restore_gate(fast):
    """Why the P0 phase's exception texts are scrubbed where they are made and its RESULT is not scrubbed as a
    whole: the result holds verdicts (``pass``, ``fail``, ``not-measurable``), the restore phase reads one of
    them (``p0_1_verify`` is ``pass``) and the run puts no minimum on a passphrase's length. An exact-match
    scrub of the whole result by the passphrase ``pass`` turns every verdict into the marker and reads a good
    backup as one that did not verify. MUTATION TARGET: ``_scrub_value`` over a phase's result in
    ``_run_phase`` (the restore's own result is scrubbed as a whole, and holds no verdict a later phase
    reads)."""
    res = rr.run_release_run(FakeCtx(), **_params(fast["dest"], passphrase="pass"))
    assert "fresh:own-backup" in fast["calls"], fast["calls"]
    phases = {ph["name"]: ph for ph in res["report"]["phases"]}
    assert phases["fresh_install_restore"]["status"] == "measured", phases["fresh_install_restore"]
    assert res["report"]["phase_results"]["p0_validation"]["checks"]["p0_1_verify"]["verdict"] == "pass"


def test_a_failed_start_removes_the_directory_with_rmdir_so_nothing_in_it_is_ever_deleted(fast, monkeypatch):
    """The coordinator's delta check of #1312, N1: the cleanup on a failed start takes away a directory this
    call just made, and ``rmdir`` is the removal that cannot do more than that: it takes an empty directory
    and refuses one with anything in it, where ``rmtree`` takes whatever is there. MUTATION TARGET: ``rmdir``
    -> ``rmtree`` (here a start that fails after something was written into the directory)."""
    def cannot_start(*a, **k):
        (fresh,) = list(fast["dest"].glob(".restore-release-run-*"))
        (fresh / "something.txt").write_text("not this call's to delete", encoding="utf-8")
        raise PermissionError("[Errno 13] Permission denied: 'python'")

    monkeypatch.setattr(rr, "subprocess", types.SimpleNamespace(
        Popen=cannot_start, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired))
    run = rr._Run(rr.RunParams(**_params(fast["dest"])))
    ctx = FakeCtx()
    ph = rr._run_phase(run, ctx, "fresh_install_restore",
                       lambda: _REAL_RESTORE(ctx, run, fast["dest"] / "backup", label="own-backup"))
    assert ph["status"] == "error" and "Permission denied" in ph["detail"], ph
    (fresh,) = list(fast["dest"].glob(".restore-release-run-*"))
    assert (fresh / "something.txt").read_text(encoding="utf-8") == "not this call's to delete"


def test_a_failure_that_does_not_name_the_passphrase_is_logged_with_its_traceback_as_before(fast, caplog):
    """The scrubbing replaces the record only where the passphrase is in it: the error log keeps a
    traceback's tail, and every failure that never named the passphrase keeps it."""
    run = rr._Run(rr.RunParams(**_params(fast["dest"])))

    def boom():
        raise RuntimeError("an ordinary failure")

    with caplog.at_level(logging.WARNING, logger="monitoring.release_run"):
        rr._run_phase(run, FakeCtx(), "ordinary", boom)
    (record,) = [r for r in caplog.records if "ordinary" in r.getMessage()]
    assert record.exc_info and record.exc_info[0] is RuntimeError, "the traceback rides the record, not the text"
    assert "an ordinary failure" in caplog.text


def test_the_real_child_on_a_missing_backup_exits_nonzero_and_reads_as_a_failed_restore(fast, tmp_path):
    """The contract the parent now relies on, end to end: the real helper, in its own process and
    encrypted under the passphrase, exits non-zero with ok false when it cannot restore."""
    run = rr._Run(rr.RunParams(**_params(fast["dest"])))
    ctx = FakeCtx()
    ph = rr._run_phase(run, ctx, "fresh_install_restore",
                       lambda: _REAL_RESTORE(ctx, run, tmp_path / "no-such-backup", label="own-backup"))
    assert ph["status"] == "error", ph
    assert ph["result"]["returncode"] == 1 and ph["result"]["child"]["ok"] is False
    assert "no-such-backup" in ph["detail"] and "exited 1" in ph["detail"], ph["detail"]
    assert not list(fast["dest"].glob(".restore-release-run-*"))
    assert NEEDLE not in json.dumps(ph)


def test_restore_failure_reads_the_childs_own_ok_the_exit_status_and_the_commit():
    f = rr._restore_failure
    committed = {"ok": True, "restore": {"committed": True}}
    assert f({"returncode": 0, "child": committed}) is None
    assert f({"child": committed}) is None, "a record that never stored an exit status is read by the child's ok alone"
    assert "exited 1 and reported: boom" in f({"returncode": 1, "child": {"ok": False, "error": "boom"}})
    assert "reported: no error text" in f({"returncode": 0, "child": {"ok": False}})
    assert "reported ok but its process exited 139" in f({"returncode": 139, "child": committed})
    assert "left no result (exit status -9)" in f({"returncode": -9, "child": None})
    assert "left no result (exit status 0)" in f({"returncode": 0})
    assert f(None) == "the phase recorded no result"
    assert f({"returncode": 0, "child": {**committed, "ok": 1}}) is not None, "only a True ok is a restore"
    # ok and a clean exit are not enough: run_restore RETURNS a refusal, and only a COMMITTED restore is one
    refused = {"ok": True, "restore": {"committed": False, "refused": "post-merge verification failed; live database untouched"}}
    why = f({"returncode": 0, "child": refused})
    assert why == ("the restore child reported ok but its restore was not committed "
                   "(refused: post-merge verification failed; live database untouched)"), why
    assert "was not committed" in f({"returncode": 0, "child": {"ok": True, "restore": {"committed": False}}})
    assert "(refused" not in f({"returncode": 0, "child": {"ok": True, "restore": {"committed": False}}})
    assert "was not committed" in f({"returncode": 0, "child": {"ok": True}}), "no restore block: nothing says it committed"
    assert "was not committed" in f({"returncode": 0, "child": {"ok": True, "restore": {"committed": 1}}}), "only a True commit"
    assert len(f({"returncode": 0, "child": {"ok": True, "restore": {"committed": False, "refused": "x" * 900}}})) < 200 + 120


def test_the_rows_refuse_a_restore_phase_recorded_measured_over_a_failed_child(fast):
    """Whatever status a phase was given, the rows read the restore only through its record: this
    is the second line behind the phase's own error, and the guard for a record an earlier build
    wrote. A legacy restore whose child left NO result used to raise out of the report builder
    (``None.get`` in row K), which would have cost a run its final report."""
    run = rr._Run(rr.RunParams(str(fast["dest"]), NEEDLE, legacy_backup_path="/old/pre-migration.oobak"))
    run.begin("fresh_install_restore")
    run.end("measured", "ok", result={"returncode": 1, "child": {"ok": False, "error": _SPACE_ERROR}})
    run.begin("legacy_restore")
    run.end("measured", "ok", result={"returncode": -9, "child": None})
    rows = {r["row"]: r for r in rr.board_rows(run)}
    assert rows["A"]["status"] == "error" and "38.0 GB" in rows["A"]["note"]
    assert rows["I"]["status"] == "error"
    assert rows["K"]["evidence"]["legacy_backup"].startswith("the pre-migration restore is not counted as a restore: ")
    assert "left no result (exit status -9)" in rows["K"]["evidence"]["legacy_backup"]
    assert rows["K"]["evidence"]["duplicate_key_scan_on_restored_corpus"] is None
    for r in rows.values():
        assert r["status"] in rr.PHASE_STATUSES, r


def test_a_restore_that_errored_says_why_from_its_result_or_from_its_own_detail(fast):
    """The two places the reason can come from: the child's record when there is one (a restore that ENDED
    and is not counted), the phase's own detail when it failed before a child ran (no restore to discount,
    so the rows say it did not complete, and say no restore was NOT COUNTED), and the plain fact when
    ``measured`` stands over nothing. The pre-migration restore reads the same way, whatever status a
    build gave it."""
    run = rr._Run(rr.RunParams(str(fast["dest"]), NEEDLE, legacy_backup_path="/old/pre-migration.oobak"))
    run.begin("fresh_install_restore")
    run.end("error", "BackupSpaceError: no room for the staging, before any child ran")  # no result at all
    run.begin("legacy_restore")
    run.end("error", "the legacy child failed", result={"returncode": 1, "child": {"ok": False, "error": "boom"}})
    rows = {r["row"]: r for r in rr.board_rows(run)}
    assert rows["A"]["note"] == ("the fresh-install restore did not complete here -- "
                                 "BackupSpaceError: no room for the staging, before any child ran"), rows["A"]["note"]
    assert "no room for the staging" in rows["I"]["note"] and rows["I"]["status"] == "error"
    assert "did not complete here" in rows["I"]["note"] and "NOT COUNT" not in rows["I"]["note"]
    assert "absent because its restore did not complete here" in rows["E"]["note"], rows["E"]["note"]
    assert "absent because its restore did not complete here" in rows["K"]["note"], rows["K"]["note"]
    assert "NOT COUNT" not in rows["E"]["note"] + rows["K"]["note"], "no restore ended, so none was left out of the count"
    assert rows["K"]["evidence"]["legacy_backup"] == "the pre-migration restore is not counted as a restore: " \
        "the restore child exited 1 and reported: boom", "an errored legacy phase reads from its child's record"

    # a legacy phase that errored with only its detail to go on: no restore ended, so none is "not counted"
    run2 = rr._Run(rr.RunParams(str(fast["dest"]), NEEDLE, legacy_backup_path="/old/pre-migration.oobak"))
    run2.begin("legacy_restore")
    run2.end("error", "the legacy child could not start")
    assert {r["row"]: r for r in rr.board_rows(run2)}["K"]["evidence"]["legacy_backup"] == \
        "the pre-migration restore gave no scan: it read error (the legacy child could not start)"

    # ``measured`` over no result at all: the fact, never the phase's bare "ok"
    run3 = rr._Run(rr.RunParams(str(fast["dest"]), NEEDLE))
    run3.begin("fresh_install_restore")
    run3.end("measured", "ok")
    note = {r["row"]: r for r in rr.board_rows(run3)}["A"]["note"]
    assert "the phase recorded no result" in note and not note.endswith("-- ok"), note


def test_a_pre_migration_restore_that_gave_no_scan_says_what_it_read_not_a_bare_null(fast):
    for status, detail in (("refused", "the legacy backup path is not a file"), ("cancelled", ""), (None, "")):
        run = rr._Run(rr.RunParams(str(fast["dest"]), NEEDLE, legacy_backup_path="/old/pre-migration.oobak"))
        if status:
            run.begin("legacy_restore")
            run.end(status, detail)
        text = {r["row"]: r for r in rr.board_rows(run)}["K"]["evidence"]["legacy_backup"]
        assert text.startswith("the pre-migration restore gave no scan: it read "), text
        assert (status or "not run") in text and (detail in text if detail else True), text
    # a pre-migration restore that did restore carries its scan, and one never asked for says so
    good = rr._Run(rr.RunParams(str(fast["dest"]), NEEDLE, legacy_backup_path="/old/pre-migration.oobak"))
    good.begin("legacy_restore")
    good.end("measured", "ok", result={"returncode": 0, "child": dict(_OK_CHILD)})
    assert {r["row"]: r for r in rr.board_rows(good)}["K"]["evidence"]["legacy_backup"] == {"duplicates": 0}
    none = rr._Run(rr.RunParams(str(fast["dest"]), NEEDLE))
    assert {r["row"]: r for r in rr.board_rows(none)}["K"]["evidence"]["legacy_backup"] == "no pre-migration backup path was given"


def test_a_restore_recorded_measured_over_a_refusal_is_not_done_for_a_resume():
    refused = {"returncode": 0, "child": {"ok": True, "restore": {"committed": False, "refused": "x"}}}
    good = {"returncode": 0, "child": {"ok": True, "restore": {"committed": True}}}
    for name in ("fresh_install_restore", "legacy_restore"):
        assert rr._phase_done({"name": name, "status": "measured", "result": refused}) is False
        assert rr._phase_done({"name": name, "status": "measured", "result": good}) is True
    assert rr._phase_done({"name": "p0_validation", "status": "measured", "result": refused}) is True, "only a restore phase is read this way"


def test_a_resume_retakes_a_restore_a_build_recorded_as_measured_over_a_failed_child(fast, monkeypatch):
    from src.monitoring.release_run import _write_state, read_state, resume_preflight

    _interrupt_mid_soak(fast, monkeypatch)
    state = read_state()
    for ph in state["phases"]:
        if ph["name"] == "fresh_install_restore":
            ph["result"] = {"returncode": 1, "child": {"ok": False, "error": _SPACE_ERROR}}
    _write_state(state)
    plan = resume_preflight("", check_passphrase=False)
    assert plan["unlock_needed"] is True and "fresh_install_restore" not in plan["phases_done"]
    assert "p0_validation" in plan["phases_done"], "the backup that verified is not owed again"
    with pytest.raises(ValueError, match="passphrase"):
        resume_preflight("")
    rep = rr.run_release_run(FakeCtx(), resume=True, passphrase=NEEDLE)["report"]
    assert "fresh:own-backup" in fast["calls"] and "p0" not in fast["calls"], fast["calls"]
    assert "fresh_install_restore:measured (not counted as a restore)" in rep["sessions"][-1]["phases_rerun"]
    assert [p["name"] for p in rep["phases"]].count("fresh_install_restore") == 1
    assert {r["row"]: r for r in rep["board_rows"]}["A"]["status"] == "measured", "the retaken restore is the row's reading now"


# --------------------------------------------------------------------------- #
#  The passphrase, on a failed restore and on its retake (2026-10-01)
# --------------------------------------------------------------------------- #
# The module's promise is that the passphrase is in no state file, no report and no log line. What
# the restore child SAYS (its result, its stderr) enters all three beside a passphrase it was
# handed, and the endpoint scrubber redacts by KEY name, so a passphrase inside a value would ride
# out. These tests drive a child that echoes it, through the real parent, on a first failure and on
# the retake a resume makes.
def _echoing_child(monkeypatch):
    echoed = {"ok": False, "elapsed_s": 1.0,
              "error": f"OperationalError: cannot open the store with key '{NEEDLE}'",
              "restore": {"detail": f"the passphrase {NEEDLE} was refused"}}
    _child_process(monkeypatch, payload=echoed, returncode=1,
                   stderr=f"Traceback (most recent call last):\n  File x\nOperationalError: key {NEEDLE}")


def _the_secret_is_nowhere(root: Path, report: dict, caplog) -> None:
    """Every file under ``root`` (the run's destination, its data dir and its state file), the
    report as returned and the log, none of which may carry the passphrase."""
    for p in root.rglob("*"):
        if p.is_file():
            assert NEEDLE.encode() not in p.read_bytes(), p
    assert NEEDLE not in json.dumps(report) and NEEDLE not in json.dumps(rr.read_state())
    assert NEEDLE not in caplog.text


def _watch_every_write(monkeypatch) -> list[str]:
    """Check each state file and each report AS IT IS WRITTEN, and return what was written: ``state``,
    ``interim`` or ``final``, and ``LEAK:<kind>`` for one that carried the passphrase. An interim report
    is written after every phase and the final report deletes the run's interim ones, so a passphrase that
    rode into one would be gone before ``_the_secret_is_nowhere`` looks.

    The check RECORDS and the test asserts on the record (:func:`_no_write_leaked`): the run writes its
    interim reports and its soak's state under ``contextlib.suppress(Exception)``, and an
    ``AssertionError`` is an ``Exception``, so an assert raised here would be swallowed by the run and the
    test would pass whatever was written."""
    seen: list[str] = []
    real_state, real_report = rr._write_state, rr._write_report

    def state(st):
        seen.append("state" if NEEDLE not in json.dumps(st, default=str) else "LEAK:state")
        return real_state(st)

    def report(run, *, interim):
        path = real_report(run, interim=interim)
        kind = "interim" if interim else "final"
        seen.append(kind if NEEDLE.encode() not in Path(path).read_bytes() else f"LEAK:{kind}")
        return path

    monkeypatch.setattr(rr, "_write_state", state)
    monkeypatch.setattr(rr, "_write_report", report)
    return seen


def _no_write_leaked(writes: list[str]) -> None:
    assert not [w for w in writes if w.startswith("LEAK:")], f"written with the passphrase in it: {writes}"
    assert {"state", "interim", "final"} <= set(writes), f"the watcher saw too little to mean anything: {writes}"


def test_the_release_run_scrubs_with_the_shared_helper():
    """One definition of the scrub (``src/monitoring/secret_scrub.py``, tested in test_secret_scrub.py),
    used by the parent that records the child's words and by the child that writes them."""
    from src.monitoring import secret_scrub

    assert rr._scrub_value is secret_scrub.scrub_value
    assert rr._scrub_value(f"a {NEEDLE} b", NEEDLE) == "a ***redacted*** b"


def test_a_restore_child_that_echoes_the_passphrase_leaves_it_in_no_state_report_or_log(fast, monkeypatch, caplog):
    _echoing_child(monkeypatch)
    writes = _watch_every_write(monkeypatch)
    with caplog.at_level(logging.WARNING):
        res = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))
    _no_write_leaked(writes)
    rep = res["report"]
    phase = {ph["name"]: ph for ph in rep["phases"]}["fresh_install_restore"]
    # the failure still reads in the child's own words, the secret taken out of them
    assert phase["status"] == "error", phase
    assert "cannot open the store with key '***redacted***'" in phase["detail"], phase["detail"]
    kept = rep["phase_results"]["fresh_install_restore"]
    assert "***redacted***" in kept["stderr_tail"] and "***redacted***" in kept["child"]["restore"]["detail"]
    assert "release run phase fresh_install_restore failed part of the way" in caplog.text, "it is logged, scrubbed"
    rows = {r["row"]: r for r in rep["board_rows"]}
    assert rows["A"]["status"] == "error" and "***redacted***" in rows["A"]["note"]
    _the_secret_is_nowhere(fast["dest"].parent, rep, caplog)
    assert NEEDLE not in rr.render_release_run_text(rep)


def test_a_retaken_restore_asks_for_the_passphrase_like_a_first_run_and_leaves_it_in_no_record(
        fast, client, monkeypatch, caplog):
    from src.monitoring.release_run import _write_state

    _interrupt_mid_soak(fast, monkeypatch)
    state = rr.read_state()
    for ph in state["phases"]:
        if ph["name"] == "fresh_install_restore":
            ph["result"] = {"returncode": 1, "child": {"ok": False, "error": _SPACE_ERROR}}
    _write_state(state)
    # The panel is told the passphrase is owed (so it asks, in the same password box a first run
    # uses), and the route refuses a resume without it before anything runs.
    st = client.get("/api/diagnostics/release-run/status").json()
    assert st["resumable"] is True and st["resume"]["unlock_needed"] is True
    assert "fresh_install_restore" not in st["resume"]["phases_done"]
    r = client.post("/api/diagnostics/release-run/resume", json={"passphrase": ""})
    assert r.status_code == 400 and "passphrase" in r.json()["detail"], r.text
    assert not any(c.startswith("fresh") for c in fast["calls"]), "nothing ran on the refusal"
    # With it, the restore is taken again -- by the real function, against a child that echoes it.
    _echoing_child(monkeypatch)
    writes = _watch_every_write(monkeypatch)
    with caplog.at_level(logging.WARNING):
        rep = rr.run_release_run(FakeCtx(), resume=True, passphrase=NEEDLE)["report"]
    again = {ph["name"]: ph for ph in rep["phases"]}["fresh_install_restore"]
    assert again["status"] == "error" and "key '***redacted***'" in again["detail"], again
    assert [p["name"] for p in rep["phases"]].count("fresh_install_restore") == 1
    assert "fresh_install_restore:measured (not counted as a restore)" in rep["sessions"][-1]["phases_rerun"]
    _the_secret_is_nowhere(fast["dest"].parent, rep, caplog)
    assert NEEDLE not in client.get("/api/diagnostics/release-run/status").text
    _no_write_leaked(writes)


def test_the_scrub_comes_before_every_cut_so_a_cut_through_the_passphrase_leaves_no_fragment(fast, monkeypatch):
    """A stderr whose 4,000-character tail starts INSIDE the passphrase: scrubbing the tail afterwards
    would find nothing to match and leave its last ten characters in the report."""
    _child_process(monkeypatch, payload={"ok": False, "error": "boom"}, returncode=1,
                   stderr=NEEDLE + "y" * 3990)
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))["report"]
    tail = rep["phase_results"]["fresh_install_restore"]["stderr_tail"]
    assert len(tail) == 4000 and "y" * 100 in tail
    assert NEEDLE[-10:] not in tail and NEEDLE[:10] not in tail, tail[:40]


def test_the_child_scrubs_its_own_error_text_before_cutting_it_to_600_characters():
    from src.monitoring import release_run_fresh_restore as child

    # the passphrase starts at character 594 of the text, so a cut at 600 would keep its first six
    text = child._error_text(RuntimeError("a" * 580 + NEEDLE + " tail"), NEEDLE)
    assert len(text) == 600 and "hunter" not in text and "***red" in text, text[580:]
    assert child._error_text(RuntimeError("boom"), "") == "RuntimeError: boom", "no passphrase, nothing replaced"
    assert child._error_text(RuntimeError(f"key {NEEDLE} refused"), NEEDLE) == "RuntimeError: key ***redacted*** refused"


def test_a_resume_owes_the_passphrase_for_a_pre_migration_restore_it_has_not_finished(fast, monkeypatch):
    """Every restore is a child that is handed the passphrase, the pre-migration one included, so a resume
    that has only THAT restore left asks for it as a first run does; a restore that finished, or was refused
    for good, owes nothing."""
    from src.monitoring.release_run import _write_state, read_state, resume_preflight

    _interrupt_mid_soak(fast, monkeypatch)  # the backup and the run's own restore are done
    assert resume_preflight("")["unlock_needed"] is False, "no pre-migration backup was given: nothing is owed"
    state = read_state()
    state["params"]["legacy_backup_path"] = "/old/pre-migration.oobak"
    _write_state(state)

    def legacy(status, result=None):
        st = read_state()
        st["phases"] = [ph for ph in st["phases"] if ph["name"] != "legacy_restore"]
        if status:
            ph = {"name": "legacy_restore", "started_at": "x", "ended_at": "y", "status": status, "detail": "d"}
            if result is not None:
                ph["result"] = result
            st["phases"].append(ph)
        _write_state(st)

    # never reached, failed, or recorded measured over a failed child: owed
    for status, result in ((None, None), ("error", None),
                           ("measured", {"returncode": 1, "child": {"ok": False, "error": "x"}})):
        legacy(status, result)
        assert resume_preflight("", check_passphrase=False)["unlock_needed"] is True, status
        with pytest.raises(ValueError, match="passphrase"):
            resume_preflight("")
        assert resume_preflight(NEEDLE)["unlock_needed"] is True
    # finished, or refused for good (the path does not exist): nothing owed
    for status, result in (("measured", {"returncode": 0, "child": {"ok": True, "restore": {"committed": True}}}),
                           ("refused", None)):
        legacy(status, result)
        assert resume_preflight("")["unlock_needed"] is False, status


def test_the_worker_asks_for_the_passphrase_itself_and_runs_no_restore_without_it(fast, monkeypatch):
    """The route refuses a resume without the passphrase, and the worker re-checks the same thing before it
    starts, so a job started any other way cannot hand a restore child an empty passphrase."""
    from src.monitoring.release_run import _write_state, read_state

    _interrupt_mid_soak(fast, monkeypatch)  # the backup and the run's own restore are done
    legacy = fast["dest"] / "pre-migration.oobak"
    legacy.write_bytes(b"x")
    state = read_state()
    state["params"]["legacy_backup_path"] = str(legacy)
    _write_state(state)
    with pytest.raises(ValueError, match="passphrase"):
        rr.run_release_run(FakeCtx(), resume=True, passphrase="")
    assert not any(c.startswith("fresh") for c in fast["calls"]), fast["calls"]
    # given the passphrase, the pre-migration restore it owes is the one thing taken again
    rr.run_release_run(FakeCtx(), resume=True, passphrase=NEEDLE)
    assert [c for c in fast["calls"] if c.startswith("fresh")] == ["fresh:pre-migration"], fast["calls"]


@pytest.mark.parametrize("needle", ["ok", "commit", "store", "e", "child", "restore", "returncode"])
def test_a_passphrase_that_is_a_piece_of_a_field_name_does_not_turn_a_good_restore_into_an_error(
        fast, monkeypatch, needle):
    """The scrub once renamed dict KEYS, and the record is read by ``ok``, ``restore``, ``committed``,
    ``child`` and ``returncode``: a passphrase equal to a piece of one of them (the run puts no minimum on
    its length) read a restore that committed as one that did not. Keys are field names; only values are
    scrubbed."""
    _child_process(monkeypatch, payload=dict(_OK_CHILD), returncode=0)
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"], passphrase=needle))["report"]
    phase = {ph["name"]: ph for ph in rep["phases"]}["fresh_install_restore"]
    assert phase["status"] == "measured", phase
    recorded = {**phase, "result": rep["phase_results"]["fresh_install_restore"]}
    assert rr._phase_done(recorded) is True, "a resume must not retake a restore that committed"
    rows = {r["row"]: r for r in rep["board_rows"]}
    assert rows["A"]["status"] == "measured" and rows["I"]["status"] == "measured"
    assert rows["A"]["evidence"]["restore"]["committed"] is True


@pytest.mark.parametrize("shape", sorted(_FAILED_RESTORES))
@pytest.mark.parametrize("needle", ["returncode", "ok", "child", "restore", "committed"])
def test_a_passphrase_that_is_a_piece_of_a_field_name_hides_no_failure_either(fast, monkeypatch, needle, shape):
    """The same fault the other way round: a renamed ``returncode`` would have hidden a child that exited 139
    (the record would have had no exit status to read), a renamed ``ok`` or ``committed`` a restore that was
    refused. Every failed shape still reads ``error`` under a passphrase that is a piece of the keys."""
    payload, rc, fragment = _FAILED_RESTORES[shape]
    _child_process(monkeypatch, payload=payload, returncode=rc)
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"], passphrase=needle))["report"]
    phase = {ph["name"]: ph for ph in rep["phases"]}["fresh_install_restore"]
    assert phase["status"] == "error" and fragment in phase["detail"], (needle, shape, phase)
    assert rep["phase_results"]["fresh_install_restore"]["returncode"] == rc
    rows = {r["row"]: r for r in rep["board_rows"]}
    assert rows["A"]["status"] == "error" and rows["I"]["status"] == "error"


def test_the_real_child_scrubs_the_whole_of_the_file_it_leaves_not_only_its_error(fast, tmp_path):
    """The child scrubs its OWN result before it writes it: the parent's scrub of a kept install comes later
    and is the net beneath this one, so this test has to show the child did it, and not the parent. The real
    helper is handed a backup path that contains the passphrase, so it reports it in a field other than its
    error text; the file it leaves must not carry it, and the parent must have had nothing to rewrite."""
    run = rr._Run(rr.RunParams(**_params(fast["dest"], keep_fresh_install=True)))
    ctx = FakeCtx()
    backup = tmp_path / f"no-such-backup-{NEEDLE}"
    ph = rr._run_phase(run, ctx, "fresh_install_restore",
                       lambda: _REAL_RESTORE(ctx, run, backup, label="own-backup"))
    assert ph["status"] == "error", ph
    left = sorted(fast["dest"].glob(".restore-release-run-*.json"))
    assert len(left) == 1, f"keep_fresh_install leaves the child's out file: {list(fast['dest'].iterdir())}"
    written = json.loads(left[0].read_text(encoding="utf-8"))
    assert written["ok"] is False and written["backup"].endswith("no-such-backup-***redacted***"), written["backup"]
    assert NEEDLE not in left[0].read_text(encoding="utf-8")
    assert NEEDLE not in json.dumps(ph)
    assert ph["result"]["kept_install_scrub"] == {"rewritten": [], "removed": [], "failed": []}, (
        "the child's own file was already clean when the parent looked: the parent's scrub did not do the child's"
    )


def _all_files(root: Path):
    return sorted(p for p in root.rglob("*") if p.is_file())


def test_a_kept_install_holds_the_passphrase_in_no_file_the_real_child_leaves(fast, tmp_path):
    """``keep_fresh_install`` leaves the child's whole data directory on the drive. Its database is encrypted
    under the passphrase, but the run journal the app writes while it restores records the backup's NAME (as
    ``label`` and ``dest``), and a backup is a file a person names. The real child restores a real fixture
    whose file name holds the passphrase; once it has exited the parent cleans what it left, and no file
    under the destination carries the passphrase -- the encrypted database and its write-ahead log included."""
    seeded = _seed_legacy_fixture(tmp_path)
    named = seeded.with_name(f"fixture-{NEEDLE}.oobak")
    seeded.rename(named)
    run = rr._Run(rr.RunParams(**_params(fast["dest"], keep_fresh_install=True)))
    ctx = FakeCtx()
    ph = rr._run_phase(run, ctx, "fresh_install_restore",
                       lambda: _REAL_RESTORE(ctx, run, named, label="own-backup"))
    assert ph["status"] == "measured", ph
    scrub = ph["result"]["kept_install_scrub"]
    assert scrub["failed"] == [] and scrub["removed"] == [], scrub
    # the control: the journal really did hold the name, so the scrub had something to take out
    assert any(n.startswith("imp-") and n.endswith(".jsonl") for n in scrub["rewritten"]), scrub
    kept = [d for d in fast["dest"].glob(".restore-release-run-*") if d.is_dir()]
    assert len(kept) == 1, list(fast["dest"].iterdir())
    files = _all_files(fast["dest"])
    assert any(f.suffix == ".db" for f in files), "the restored install is the thing that is kept"
    assert [str(f) for f in files if NEEDLE.encode() in f.read_bytes()] == [], "a file still holds the passphrase"
    # ... and what was cleaned is still a journal a reader can read: every line parses, the name is redacted
    journals = [f for f in files if f.parent.name == "run_logs" and not f.name.endswith(".beat.jsonl")]
    assert len(journals) == 1
    records = [json.loads(line) for line in journals[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    begin = next(r for r in records if r["ev"] == "run_begin")
    assert begin["label"] == "fixture-***redacted***.oobak" and begin["dest"].endswith("fixture-***redacted***.oobak")
    assert {"hardware", "pid", "run_id", "kind"} <= set(begin), "the record keeps its other fields"
    assert NEEDLE not in json.dumps(ph)


def _kept_install_with(tmp_path: Path, needle: str = NEEDLE):
    """A directory shaped like the one the child leaves, with the passphrase in its journal and its report."""
    fresh = tmp_path / ".restore-release-run-own-backup-1"
    (fresh / "run_logs").mkdir(parents=True)
    (fresh / "import_reports").mkdir()
    (fresh / "rings").mkdir()
    journal = fresh / "run_logs" / "imp-1.jsonl"
    journal.write_text(json.dumps({"ev": "run_begin", "label": f"b-{needle}.oobak"}) + "\n", encoding="utf-8")
    beat = fresh / "run_logs" / "imp-1.beat.jsonl"
    beat.write_text(json.dumps({"ev": "beat", "rss": 1}) + "\n", encoding="utf-8")
    report = fresh / "import_reports" / "restore-1.json"
    report.write_text(json.dumps({"import_run": {"label": f"b-{needle}.oobak"}}, indent=2), encoding="utf-8")
    other = fresh / "rings" / "keyword_rings_local.yml"
    other.write_text("rings: []\n", encoding="utf-8")
    out_json = fresh.with_suffix(".json")
    out_json.write_text(json.dumps({"ok": True}), encoding="utf-8")
    return fresh, out_json, journal, beat, report, other


def test_the_kept_install_scrub_cleans_the_journals_and_reports_and_leaves_every_other_file(tmp_path):
    fresh, out_json, journal, beat, report, other = _kept_install_with(tmp_path)
    before = {p: p.stat().st_mtime_ns for p in (beat, other, out_json)}
    done = rr._scrub_kept_install(fresh, out_json, NEEDLE)
    assert done == {"rewritten": ["imp-1.jsonl", "restore-1.json"], "removed": [], "failed": []}, done
    assert json.loads(journal.read_text(encoding="utf-8"))["label"] == "b-***redacted***.oobak"
    assert json.loads(report.read_text(encoding="utf-8"))["import_run"]["label"] == "b-***redacted***.oobak"
    assert {p: p.stat().st_mtime_ns for p in (beat, other, out_json)} == before, "files with nothing in them are not rewritten"
    assert rr._scrub_kept_install(fresh, out_json, NEEDLE) == {"rewritten": [], "removed": [], "failed": []}, "a second pass finds nothing"
    assert rr._scrub_kept_install(fresh, out_json, "") == {"rewritten": [], "removed": [], "failed": []}, "no passphrase, no needle"
    assert rr._scrub_kept_install(tmp_path / "gone", tmp_path / "gone.json", NEEDLE) == {
        "rewritten": [], "removed": [], "failed": []}, "a child that died before it wrote anything left nothing to clean"


def test_a_report_a_killed_child_left_half_written_is_cleaned_with_the_finished_ones(tmp_path):
    """A report is written to ``<name>.json.tmp`` and renamed, so a child killed in between leaves the half-written
    file beside the finished ones, with the backup's name (here the passphrase) in it. MUTATION TARGET: the
    pattern that picks the reports (``*.json`` alone misses it)."""
    fresh, out_json, journal, beat, report, other = _kept_install_with(tmp_path)
    half = fresh / "import_reports" / "restore-2.json.tmp"
    half.write_text('{\n  "import_run": {\n    "label": "b-' + NEEDLE + '.oobak",\n    "ev', encoding="utf-8")
    done = rr._scrub_kept_install(fresh, out_json, NEEDLE)
    assert done == {"rewritten": ["imp-1.jsonl", "restore-1.json", "restore-2.json.tmp"], "removed": [], "failed": []}, done
    assert NEEDLE not in half.read_text(encoding="utf-8") and "b-***redacted***.oobak" in half.read_text(encoding="utf-8")


def test_the_kept_install_scrub_removes_a_file_it_cannot_rewrite_and_names_one_it_cannot_remove(
        tmp_path, monkeypatch, caplog):
    """A journal that still holds the passphrase is the one thing a kept install may not carry: when it cannot
    be rewritten (a full disk is the likely reason, and one this product meets) it is removed instead."""
    fresh, out_json, journal, beat, report, other = _kept_install_with(tmp_path)

    def cannot_rewrite(path, needle):
        raise OSError("No space left on device")

    monkeypatch.setattr(rr, "_scrub_file", cannot_rewrite)
    done = rr._scrub_kept_install(fresh, out_json, NEEDLE)
    assert sorted(done["removed"]) == sorted(["imp-1.beat.jsonl", "imp-1.jsonl", "restore-1.json", out_json.name]), done
    assert done["rewritten"] == [] and done["failed"] == []
    assert not journal.exists() and not report.exists(), "what could not be cleaned is gone, not kept"
    assert other.exists(), "only the files the scrub is responsible for are touched"

    fresh2, out2, journal2, *_ = _kept_install_with(tmp_path / "second")
    real_unlink = Path.unlink

    def stuck(self, *a, **k):
        if self.name == "imp-1.jsonl":
            raise PermissionError("held open")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", stuck)
    with caplog.at_level(logging.WARNING):
        done2 = rr._scrub_kept_install(fresh2, out2, NEEDLE)
    assert done2["failed"] == ["imp-1.jsonl"] and journal2.exists(), done2
    assert "could not be taken out of imp-1.jsonl" in caplog.text
    assert NEEDLE not in caplog.text, "the warning names the file, never what it holds"


def test_a_kept_run_cleans_the_out_file_a_child_left_with_the_passphrase_in_it(fast, monkeypatch, caplog):
    """The stand-in child writes its result raw, as an older or a broken child would. A run that keeps its
    fresh install cleans that file on the way out, says so in the phase's record, and carries no passphrase
    anywhere; a run that does not keep it has nothing to clean and records nothing of the kind."""
    _echoing_child(monkeypatch)
    writes = _watch_every_write(monkeypatch)
    with caplog.at_level(logging.WARNING):
        res = rr.run_release_run(FakeCtx(), **_params(fast["dest"], keep_fresh_install=True))
    rep = res["report"]
    kept = rep["phase_results"]["fresh_install_restore"]
    out_name = next(f.name for f in fast["dest"].glob(".restore-release-run-*.json"))
    assert kept["kept_install_scrub"] == {"rewritten": [out_name], "removed": [], "failed": []}, kept["kept_install_scrub"]
    assert json.loads((fast["dest"] / out_name).read_text(encoding="utf-8"))["error"].endswith("key '***redacted***'")
    _the_secret_is_nowhere(fast["dest"].parent, rep, caplog)
    _no_write_leaked(writes)


def test_a_run_that_does_not_keep_its_fresh_install_has_nothing_to_clean(fast, monkeypatch):
    _child_process(monkeypatch, payload=dict(_OK_CHILD), returncode=0)
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))["report"]
    assert "kept_install_scrub" not in rep["phase_results"]["fresh_install_restore"]
    assert not list(fast["dest"].glob(".restore-release-run-*"))


def test_a_missing_file_error_from_the_rewrite_is_not_mistaken_for_a_file_that_is_not_there(tmp_path, monkeypatch):
    """A missing-file error also comes out of the rewrite itself -- a ``.part`` path the platform refuses, a
    directory that went away between the read and the write -- with the journal in place and still holding the
    passphrase. Reading every such error as "nothing to clean" kept the file and recorded a clean scrub."""
    from src.monitoring import secret_scrub

    real_write_bytes = Path.write_bytes

    def no_part(self, data):
        if self.name.endswith(".part"):
            raise FileNotFoundError(2, "No such file or directory")
        return real_write_bytes(self, data)

    fresh, out_json, journal, beat, report, other = _kept_install_with(tmp_path / "a")
    with monkeypatch.context() as m:
        m.setattr(Path, "write_bytes", no_part)
        done = rr._scrub_kept_install(fresh, out_json, NEEDLE)
    assert done == {"rewritten": [], "removed": ["imp-1.jsonl", "restore-1.json"], "failed": []}, done
    assert not journal.exists() and not report.exists(), "what could not be cleaned is gone, not kept"
    assert beat.exists() and other.exists() and out_json.exists(), "files with nothing in them are not touched"

    def no_target(src, dst):
        raise FileNotFoundError(2, "No such file or directory")

    fresh2, out2, journal2, beat2, report2, _ = _kept_install_with(tmp_path / "b")
    with monkeypatch.context() as m:
        m.setattr(secret_scrub.os, "replace", no_target)
        done2 = rr._scrub_kept_install(fresh2, out2, NEEDLE)
    assert done2["removed"] == ["imp-1.jsonl", "restore-1.json"] and done2["failed"] == [], done2
    assert not journal2.exists() and not report2.exists()
    assert not list((tmp_path / "b").rglob("*.part")), "no half-made copy is left either"


def test_a_failure_that_is_no_oserror_loses_neither_the_result_nor_the_other_files(tmp_path, monkeypatch):
    """Whatever stops one file's rewrite (here a RecursionError, which an OSError handler lets through and which
    would have taken the phase's whole result with it), that file is removed and the others are still cleaned."""
    fresh, out_json, journal, beat, report, other = _kept_install_with(tmp_path)
    real = rr._scrub_file

    def odd(path, needle):
        if path.name == "imp-1.jsonl":
            raise RecursionError("maximum recursion depth exceeded")
        return real(path, needle)

    monkeypatch.setattr(rr, "_scrub_file", odd)
    done = rr._scrub_kept_install(fresh, out_json, NEEDLE)
    assert done == {"rewritten": ["restore-1.json"], "removed": ["imp-1.jsonl"], "failed": []}, done
    assert not journal.exists() and NEEDLE not in report.read_text(encoding="utf-8")


def _journalling_child(monkeypatch, *, returncode, terminate_to=-15, communicate_raises=None):
    """A stand-in for the restore child that does what the real one does at its start -- writes its run journal
    into its own data dir, with the backup's name (which here holds the passphrase) in it -- and then ends the way
    the test says. Returns the stand-ins that were started."""
    made: list = []

    class _Proc:
        def __init__(self, argv, **kw):
            logs = Path(kw["env"]["OO_DATA_DIR"]) / "run_logs"
            logs.mkdir(parents=True, exist_ok=True)
            (logs / "imp-1.jsonl").write_text(
                json.dumps({"ev": "run_begin", "label": f"b-{NEEDLE}.oobak"}) + "\n", encoding="utf-8")
            self.returncode = returncode
            self.killed = False
            made.append(self)

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = terminate_to

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

        def communicate(self, timeout=None):
            if communicate_raises is not None:
                raise communicate_raises
            return "", ""

    monkeypatch.setattr(rr, "subprocess", types.SimpleNamespace(
        Popen=_Proc, PIPE=subprocess.PIPE, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(rr, "_fresh_install_restore", _REAL_RESTORE)
    return made


class _ProgressFails(FakeCtx):
    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        if detail and detail.startswith("fresh install ("):
            raise RuntimeError("the progress callback broke")
        super().set_progress(done=done, total=total, detail=detail)


# (status the phase reads, the child's state when started, the context, the child ends by terminate, what
# communicate raises, a child still running at the end is killed)
_ENDINGS = {
    "cancelled": ("cancelled", None, FakeCtx, -15, None, False),
    "killed by a signal": ("error", -9, FakeCtx, -9, None, False),
    "its progress callback raises": ("error", None, _ProgressFails, -15, None, True),
    "its pipes cannot be read": ("error", None, FakeCtx, None, subprocess.TimeoutExpired("python", 30), True),
}


@pytest.mark.parametrize("ending", sorted(_ENDINGS))
def test_a_kept_install_is_scrubbed_however_the_child_ended_and_a_running_child_is_ended_first(
        fast, monkeypatch, ending):
    """The scrub is not a step of the happy path: a cancel, a kill, a callback that raises and a pipe that cannot be
    read all leave the child's journal on the drive, and each must leave it clean. A child still running when an
    exception gets out is killed first, or it would go on writing into the directory being scrubbed."""
    status, started_as, ctx_class, terminate_to, raises, must_kill = _ENDINGS[ending]
    made = _journalling_child(monkeypatch, returncode=started_as, terminate_to=terminate_to, communicate_raises=raises)
    run = rr._Run(rr.RunParams(**_params(fast["dest"], keep_fresh_install=True)))
    ctx = ctx_class()
    if ending in ("cancelled", "its pipes cannot be read"):
        ctx.cancel()
    ph = rr._run_phase(run, ctx, "fresh_install_restore",
                       lambda: _REAL_RESTORE(ctx, run, fast["dest"] / "backup", label="own-backup"))
    assert ph["status"] == status, ph
    (kept,) = [d for d in fast["dest"].glob(".restore-release-run-*") if d.is_dir()]
    text = (kept / "run_logs" / "imp-1.jsonl").read_text(encoding="utf-8")
    assert NEEDLE not in text and "b-***redacted***.oobak" in text, text
    assert made[0].killed is must_kill, f"killed={made[0].killed}"
    for p in fast["dest"].rglob("*"):
        if p.is_file():
            assert NEEDLE.encode() not in p.read_bytes(), p
    assert NEEDLE not in json.dumps(ph, default=str)


def test_rows_e_and_k_say_why_the_restored_installs_reading_is_absent_when_no_restore_ran(fast, monkeypatch):
    """A restore that never started (here: no room for a second copy) is no restore that ended and was left out of
    the count, so no row says NOT COUNTED -- but its rows must not show a bare null either: each says the reading
    is absent because the restore did not complete, and row A names the phase's own reason."""
    pre = rr._preflight
    monkeypatch.setattr(rr, "_preflight", lambda run: {**pre(run), "fresh_install_fits": False})
    rep = rr.run_release_run(FakeCtx(), **_params(fast["dest"]))["report"]
    phase = {ph["name"]: ph for ph in rep["phases"]}["fresh_install_restore"]
    assert phase["status"] == "not-measurable-here" and "lacks the room" in phase["detail"], phase
    rows = {r["row"]: r for r in rep["board_rows"]}
    assert rows["A"]["status"] == "not-measurable-here" and "lacks the room" in rows["A"]["note"], rows["A"]["note"]
    assert "absent because its restore did not complete here" in rows["E"]["note"], rows["E"]["note"]
    assert "absent because its restore did not complete here" in rows["K"]["note"], rows["K"]["note"]
    assert "lacks the room" in rows["I"]["note"], rows["I"]["note"]
    assert not any("NOT COUNT" in rows[letter]["note"] for letter in "AEIK")


def test_rows_e_and_k_point_to_row_a_only_when_row_a_says_why(fast):
    """The pointer is for a reader who wants the reason. A phase that ended with one (its detail) or a restore that
    is not counted has it in row A; a phase that was skipped has none, and "row A names why" would send the reader
    to a row with no more to say than the one they are on."""
    run = rr._Run(rr.RunParams(**_params(fast["dest"])))
    run.phases.append({"name": "fresh_install_restore", "status": "skipped"})
    rows = {r["row"]: r for r in rr.board_rows(run)}
    for letter in "EK":
        assert "absent because its restore did not complete here" in rows[letter]["note"], rows[letter]["note"]
        assert "row A names why" not in rows[letter]["note"], (letter, rows[letter]["note"])
    run.phases[-1]["detail"] = "the destination lacks the room for a second copy"
    rows = {r["row"]: r for r in rr.board_rows(run)}
    assert "lacks the room" in rows["A"]["note"]
    for letter in "EK":
        assert rows[letter]["note"].endswith("did not complete here (row A names why)"), (letter, rows[letter]["note"])
    # a restore recorded ``measured`` over nothing (an earlier build's state file) is not counted, whatever its
    # detail says: row A leads with that reason, so the pointer is there with no detail at all
    run.phases[-1] = {"name": "fresh_install_restore", "status": "measured"}
    rows = {r["row"]: r for r in rr.board_rows(run)}
    assert rows["A"]["note"].startswith("this run does NOT COUNT its fresh-install restore"), rows["A"]["note"]
    for letter in "EK":
        assert rows[letter]["note"].endswith("is NOT COUNTED because its restore is not counted as one (row A names why)"), (
            letter, rows[letter]["note"])


def test_the_child_writes_a_result_with_the_passphrase_taken_out_of_every_string_in_it():
    from src.monitoring import release_run_fresh_restore as child

    result = {"backup": f"/b/{NEEDLE}", "path": Path(f"/x/{NEEDLE}"), "n": 2,
              "restore": {"refused": f"bad {NEEDLE}", "committed": False}, "rows": [f"{NEEDLE}!", 1.5, None]}
    text = child._result_text(result, NEEDLE)
    assert NEEDLE not in text
    out = json.loads(text)
    assert out["backup"] == "/b/***redacted***" and out["path"] == "/x/***redacted***", "a default=str value too"
    assert out["restore"] == {"refused": "bad ***redacted***", "committed": False}
    assert out["rows"] == ["***redacted***!", 1.5, None] and out["n"] == 2
    assert json.loads(child._result_text({"ok": True}, "")) == {"ok": True}, "no passphrase, nothing replaced"
