"""Tests for the P0 data-safety validation kit (S1.2 / S1.5).

The integration tests drive the REAL live-corpus source path by monkeypatching
``src.backup.sqlite_backup.live_db_path`` — NEVER an injected ``corpus_source``
double, which would bypass exactly the freeze/gate/streaming path being validated
(the ZETA (c) lesson). They assert the live corpus is byte-unchanged, the backup
passphrase never leaks into the report, the throwaway restore staging is always
cleaned, and a cancelled run leaves no backup that looks complete.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from src.monitoring import p0_validation as p0


class FakeCtx:
    """A JobContext stand-in: cooperative stop + progress capture."""

    def __init__(self, stop_now: bool = False) -> None:
        self._stop = stop_now
        self.progress: list[tuple] = []

    @property
    def stopping(self) -> bool:
        return self._stop

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        self.progress.append((done, total, detail))


# --------------------------------------------------------------------------- #
# Unit: bounded-RAM assessment (pure)
# --------------------------------------------------------------------------- #
def test_ram_bounded_none_is_not_measurable():
    v, note = p0._ram_bounded_assessment(None, 50_000.0)
    assert v == "not-measurable" and "psutil" in note


def test_ram_bounded_small_corpus_is_not_measurable():
    # 1 GB corpus (< the 2 GB floor): bounded RAM is trivially satisfied.
    v, note = p0._ram_bounded_assessment(30.0, 1024.0)
    assert v == "not-measurable" and "full-scale" in note


def test_ram_bounded_large_corpus_bounded():
    # 100 GB corpus, backup added ~200 MB — RAM did not scale with the corpus.
    v, note = p0._ram_bounded_assessment(200.0, 100_000.0)
    assert v == "bounded"


def test_ram_bounded_large_corpus_unbounded_is_the_oom_signature():
    # 10 GB corpus, backup added ~8 GB — RAM scaled with the corpus.
    v, note = p0._ram_bounded_assessment(8000.0, 10_000.0)
    assert v == "unbounded" and "OOM" in note


# --------------------------------------------------------------------------- #
# Unit: unlock verdict (pure)
# --------------------------------------------------------------------------- #
def test_unlock_absent_is_not_measurable_with_howto():
    c = p0._unlock_verdict(None)
    assert c["verdict"] == "not-measurable-here"
    assert "how_to_time_next_cold_boot" in c["measurements"]


def test_unlock_under_bar_passes():
    c = p0._unlock_verdict(
        {"synchronous_total_ms": 12.0, "phases": [{"phase": "init_db", "ms": 12.0}], "at": "x"}
    )
    assert c["verdict"] == "pass"
    # the cold-boot instruction rides along even on a pass (re-measure at full scale)
    assert "how_to_time_next_cold_boot" in c["measurements"]


def test_unlock_over_bar_fails_and_names_slowest_phase():
    c = p0._unlock_verdict(
        {
            "synchronous_total_ms": 28600.0,
            "phases": [{"phase": "airplane", "ms": 5.0}, {"phase": "init_db (fts rebuild)", "ms": 28500.0}],
            "at": "x",
        }
    )
    assert c["verdict"] == "fail"
    assert "init_db" in c["reason"]


def test_unlock_sums_phases_when_total_absent():
    c = p0._unlock_verdict({"phases": [{"phase": "a", "ms": 100.0}, {"phase": "b", "ms": 50.0}]})
    assert c["measurements"]["synchronous_total_ms"] == 150.0
    assert c["verdict"] == "pass"


def test_unlock_summed_zero_phases_is_not_measurable_not_a_fabricated_pass():
    """The #B fix: a malformed record with phases present but no ms sums to 0.0, which
    must NOT be reported as a '0 ms < 2000 ms' pass."""
    c = p0._unlock_verdict({"phases": [{"phase": "a"}, {"phase": "b"}]})
    assert c["verdict"] == "not-measurable-here"


# --------------------------------------------------------------------------- #
# Unit: collector verdict (pure)
# --------------------------------------------------------------------------- #
def _guard_state():
    return {"enabled": True, "engaged": False, "readings_available": True}


def test_collector_no_passes_is_not_measurable():
    c = p0._collector_verdict([], _guard_state())
    assert c["verdict"] == "not-measurable-here"


def test_collector_flat_rss_passes():
    samples = [
        {"kind": "summary", "pass_id": 1, "rss_mb": {"first": 300, "last": 320, "max": 340}},
        {"kind": "summary", "pass_id": 2, "rss_mb": {"first": 305, "last": 315, "max": 345}},
        {"kind": "summary", "pass_id": 3, "rss_mb": {"first": 300, "last": 330, "max": 350}},
    ]
    c = p0._collector_verdict(samples, _guard_state())
    assert c["verdict"] == "pass"


def test_collector_climbing_rss_fails():
    samples = [
        {"kind": "summary", "pass_id": 1, "rss_mb": {"first": 300, "last": 320, "max": 340}},
        {"kind": "summary", "pass_id": 2, "rss_mb": {"first": 1200, "last": 1500, "max": 1600}},
    ]
    c = p0._collector_verdict(samples, _guard_state())
    assert c["verdict"] == "fail" and "rose" in c["reason"]


def test_collector_large_absolute_modest_ratio_climb_is_flagged():
    """The #A fix: a +1.9 GB climb on a 4 GB baseline (ratio only 1.48x) is the OOM
    signature at scale — an earlier ratio-AND gate hid exactly this as 'flat'."""
    samples = [
        {"kind": "summary", "pass_id": 1, "rss_mb": {"first": 3800, "last": 3900, "max": 4000}},
        {"kind": "summary", "pass_id": 2, "rss_mb": {"first": 5500, "last": 5800, "max": 5900}},
    ]
    c = p0._collector_verdict(samples, _guard_state())
    assert c["verdict"] == "fail", c["reason"]  # 5900 - 4000 = 1900 MB > 512 MB floor


def test_collector_single_pass_cannot_show_a_trend():
    samples = [{"kind": "summary", "pass_id": 1, "rss_mb": {"first": 300, "last": 320, "max": 340}}]
    c = p0._collector_verdict(samples, _guard_state())
    assert c["verdict"] == "not-measurable-here"


# --------------------------------------------------------------------------- #
# Unit: dest-dir safety guard
# --------------------------------------------------------------------------- #
def test_validate_dest_rejects_data_dir_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="overlaps the live data directory"):
        p0.validate_dest_dir(tmp_path / "inside" / "backup")
    with pytest.raises(ValueError, match="overlaps"):
        p0.validate_dest_dir(tmp_path)  # IS the data dir


def test_validate_dest_rejects_empty():
    with pytest.raises(ValueError, match="required"):
        p0.validate_dest_dir("")


def test_validate_dest_accepts_a_separate_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path / "data")
    (tmp_path / "data").mkdir()
    out = p0.validate_dest_dir(tmp_path / "drive" / "backup")
    assert out == (tmp_path / "drive" / "backup").resolve()


# --------------------------------------------------------------------------- #
# Unit: summary + text render
# --------------------------------------------------------------------------- #
def test_summarize_is_a_conjunction_not_a_score():
    checks = {
        "a": {"verdict": "pass"},
        "b": {"verdict": "fail"},
        "c": {"verdict": "not-measurable-here"},
    }
    s = p0._summarize(checks)
    assert s == {
        "pass": 1,
        "fail": 1,
        "not_measurable_here": 1,
        "no_check_failed": False,
        "note": s["note"],
    }
    assert "not a composite" in s["note"].lower()


def test_render_text_lists_each_verdict():
    report = {
        "created_at": "now",
        "app_version": "0.2.0",
        "backup_engine_format": "oo-volumes-2",
        "dest_dir": "/x",
        "summary": {"pass": 3, "fail": 0, "not_measurable_here": 2, "note": "n"},
        "checks": {
            "p0_1_backup": {"verdict": "pass", "reason": "ok"},
            "p0_4_unlock": {"verdict": "not-measurable-here", "reason": "cold boot"},
        },
    }
    txt = p0.render_p0_validation_text(report)
    assert "P0.1 backup" in txt and "PASS" in txt and "NOT-MEASURABLE-HERE" in txt


# --------------------------------------------------------------------------- #
# Integration: the full worker against the REAL live_db_path path
# --------------------------------------------------------------------------- #
def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _live_corpus(tmp_path, monkeypatch):
    """A full-schema plaintext corpus behind the REAL live_db_path (monkeypatched).

    Also isolates the report dir into tmp so a run never pollutes the shared
    data_dir/diagnostics (the #577 cross-test-pollution discipline)."""
    import src.backup.sqlite_backup as sb
    from src.database.connect import snapshot_preserving
    from src.database.session import init_db

    init_db()  # ensure the ambient schema (idempotent); the app's real init path
    corpus = tmp_path / "live_corpus.db"
    snapshot_preserving(sb.live_db_path(), corpus)  # clean single-file plaintext copy
    monkeypatch.setattr(sb, "live_db_path", lambda: corpus)
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(p0, "_report_dir", lambda: reports)
    return corpus


def test_full_worker_backs_up_verifies_restores_and_leaves_live_untouched(tmp_path, monkeypatch):
    corpus = _live_corpus(tmp_path, monkeypatch)
    before = _sha(corpus)

    dest = tmp_path / "drive" / "dest"
    secret = "s1-distinctive-backup-passphrase-9x7"
    ctx = FakeCtx()
    out = p0.run_p0_validation(ctx, dest_dir=str(dest), passphrase=secret, measure_incremental=True)

    report = out["report"]
    checks = report["checks"]
    # Data-safety core: backup completes + writes volumes, verifies, restore probes clean.
    # On this tiny fixture corpus (< 2 GB) the P0.1 SCALE bar (bounded RAM at 100 GB) is
    # honestly not-measurable-here — the backup still completed (volumes written) and the
    # sub-assessment says so; it must NOT be a fabricated 'pass' of the scale bar.
    assert checks["p0_1_backup"]["verdict"] == "not-measurable-here", checks["p0_1_backup"]["reason"]
    assert checks["p0_1_backup"]["measurements"]["volumes"] > 0  # the backup actually ran
    assert checks["p0_1_backup"]["measurements"]["ram_bounded"]["verdict"] == "not-measurable"
    assert checks["p0_1_verify"]["verdict"] == "pass", checks["p0_1_verify"]["reason"]
    # restore is still probed (backup did not FAIL and verify passed) on a sub-scale run.
    assert checks["p0_2_restore"]["verdict"] == "pass", checks["p0_2_restore"]["reason"]
    # The dry-run restore must NEVER have committed.
    assert checks["p0_2_restore"]["measurements"]["committed"] is False
    # Unlock + collector are read from instrumentation (may be not-measurable here).
    assert checks["p0_4_unlock"]["verdict"] in {"pass", "fail", "not-measurable-here"}
    assert checks["p0_3_collector"]["verdict"] in {"pass", "fail", "not-measurable-here"}

    # The LIVE corpus is byte-for-byte untouched (only ever read).
    assert _sha(corpus) == before

    # Version/format stamp so a later engine change makes this report detectably stale.
    assert report["backup_engine_format"] == "oo-volumes-2"
    assert report["schema"] == "oo-p0-validation-1"

    # The incremental refresh ran and reused the unchanged corpus slice (the
    # changed-volume re-emit property). On a tiny corpus the always-changing
    # manifest + side files dominate, so only assert SOME reuse — at scale the
    # many unchanged corpus volumes reuse and only the manifest re-emits.
    inc = checks["p0_1_backup"]["measurements"]["incremental_refresh"]
    assert inc is not None and inc["volumes_reused"] >= 1

    # The passphrase NEVER appears anywhere in the report or the job result.
    blob = json.dumps(out)
    assert secret not in blob

    # The report was persisted and is now the "last" report (available:true).
    assert out["filename"].startswith("oo-p0-validation-")
    last = p0.last_p0_validation_report()
    assert last["available"] is True


def test_worker_cleans_up_the_throwaway_restore_staging(tmp_path, monkeypatch):
    _live_corpus(tmp_path, monkeypatch)
    dest = tmp_path / "drive" / "dest"
    p0.run_p0_validation(FakeCtx(), dest_dir=str(dest), passphrase="pw", measure_incremental=False)
    # No restore-probe staging is left behind under the dest.
    leftovers = list(dest.glob(".p0-restore-probe-*")) + list(dest.glob(".restore-*"))
    assert leftovers == [], leftovers


def test_cancelled_run_leaves_no_backup_that_looks_complete(tmp_path, monkeypatch):
    _live_corpus(tmp_path, monkeypatch)
    dest = tmp_path / "drive" / "dest"
    ctx = FakeCtx(stop_now=True)  # cancelled from the first safe point
    out = p0.run_p0_validation(ctx, dest_dir=str(dest), passphrase="pw", measure_incremental=False)

    report = out["report"]
    assert report["cancelled"] is True
    # A cancel is NEVER a data-safety FAIL — it is not-measurable.
    assert report["checks"]["p0_1_backup"]["verdict"] == "not-measurable-here"
    # No complete, signed volume manifest was left (a partial must never look good).
    assert not (dest / "volumes.json").exists()


def test_worker_refuses_a_dest_that_overlaps_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="overlaps"):
        p0.run_p0_validation(FakeCtx(), dest_dir=str(tmp_path / "sub"), passphrase="pw")


def test_worker_requires_a_passphrase(tmp_path):
    with pytest.raises(ValueError, match="passphrase is required"):
        p0.run_p0_validation(FakeCtx(), dest_dir=str(tmp_path / "d"), passphrase="")


# --------------------------------------------------------------------------- #
# Endpoint wiring (call the diagnostics endpoint functions directly)
# --------------------------------------------------------------------------- #
def _reset_p0_job():
    from src.api import diagnostics as d

    job = d._P0_VALIDATION_JOB
    with job._lock:
        job._state = "idle"
        job._result = None
        job._thread = None
        job._error = None
    return job


def test_endpoint_rejects_a_dest_overlapping_the_data_dir(monkeypatch, tmp_path):
    from fastapi import HTTPException

    from src.api import diagnostics as d

    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    body = d.P0ValidationBody(dest_dir=str(tmp_path / "sub"), passphrase="pw")
    with pytest.raises(HTTPException) as ei:
        d.p0_validation_start(body)
    assert ei.value.status_code == 400


def test_endpoint_requires_a_passphrase():
    from fastapi import HTTPException

    from src.api import diagnostics as d

    body = d.P0ValidationBody(dest_dir="/tmp/whatever", passphrase="")
    with pytest.raises(HTTPException) as ei:
        d.p0_validation_start(body)
    assert ei.value.status_code == 400


def test_download_is_404_until_a_run_completes():
    from fastapi import HTTPException

    from src.api import diagnostics as d

    _reset_p0_job()
    with pytest.raises(HTTPException) as ei:
        d.p0_validation_download()
    assert ei.value.status_code == 404


def test_cancel_is_idempotent_and_returns_status():
    from src.api import diagnostics as d

    resp = d.p0_validation_cancel()
    body = json.loads(bytes(resp.body))
    assert "state" in body and body["kind"] == "p0-validation"


def test_last_endpoint_returns_a_report_block(monkeypatch, tmp_path):
    from src.api import diagnostics as d

    # isolate the report dir so this reads a known-empty channel
    monkeypatch.setattr(p0, "_report_dir", lambda: tmp_path)
    resp = d.p0_validation_last()
    body = json.loads(bytes(resp.body))
    assert body["available"] is False and body["schema"] == "oo-p0-validation-1"


def test_debug_bundle_member_is_read_only_and_honest(monkeypatch, tmp_path):
    """The debug-bundle P0 member reads the LAST report — it must NEVER run a
    backup, and returns an honest stub when none has run."""
    from src.api import diagnostics as d

    monkeypatch.setattr(p0, "_report_dir", lambda: tmp_path)
    block = d._p0_validation_last()
    assert block["available"] is False


def test_p0_scrub_redacts_secret_keyed_values_recursively():
    """Defense-in-depth (secret skeptic): _p0_scrub redacts any value under a
    secret-looking key so a future report field named e.g. 'passphrase' can never
    ride out on /status. The report is passphrase-free today; this makes it a property."""
    from src.api import diagnostics as d

    payload = {"state": "done", "result": {"report": {"dest_dir": "/x", "passphrase": "leak-me",
               "nested": [{"api_secret": "also"}, {"ok": 1}]}}}
    scrubbed = d._p0_scrub(payload)
    blob = json.dumps(scrubbed)
    assert "leak-me" not in blob and "also" not in blob
    assert scrubbed["state"] == "done"  # non-secret fields preserved
    assert scrubbed["result"]["report"]["nested"][1]["ok"] == 1
