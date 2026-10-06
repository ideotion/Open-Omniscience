"""Tests for the P0 data-safety validation kit (S1.2 / S1.5).

The integration tests drive the REAL live-corpus source path by monkeypatching
``src.backup.sqlite_backup.live_db_path`` — NEVER an injected ``corpus_source``
double, which would bypass exactly the freeze/gate/streaming path being validated
(the ZETA (c) lesson). They assert the live corpus is byte-unchanged, the backup
passphrase never leaks into the report, the throwaway restore staging is always
cleaned, and a cancelled run leaves no backup that looks complete.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

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


def test_unlock_pass_states_which_case_the_wal_evidence_covers():
    """A pass must say what it measured, because the 2026-08-12 field run passed at
    323 ms with a bare `wal_bytes_before_open: null` and the report could not tell
    the operator whether that was a clean cold boot (bankable against the bar) or a
    WAL read that failed. Three states, three different sentences."""
    base = {"synchronous_total_ms": 12.0, "phases": [{"phase": "init_db", "ms": 12.0}], "at": "x"}

    absent = p0._unlock_verdict({**base, "wal_state_before_open": {"bytes": 0, "state": "absent"}})
    assert absent["verdict"] == "pass"
    assert "steady-state" in absent["reason"] and "does NOT include WAL recovery" in absent["reason"]

    present = p0._unlock_verdict(
        {**base, "wal_state_before_open": {"bytes": 4096, "state": "present"}}
    )
    assert present["verdict"] == "pass"
    assert "INCLUDES replaying it" in present["reason"] and "4,096" in present["reason"]

    unreadable = p0._unlock_verdict(
        {**base, "wal_state_before_open": {"bytes": None, "state": "unreadable"}}
    )
    assert "unmeasured" in unreadable["reason"]

    # An OLD record carrying no state at all must not read as either of the above.
    legacy = p0._unlock_verdict(base)
    assert "no -wal state" in legacy["reason"]
    # ...and the three sentences are genuinely different, or the guard proves nothing.
    assert len({absent["reason"], present["reason"], unreadable["reason"], legacy["reason"]}) == 4


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


def _passes(maxes):
    return [
        {"kind": "summary", "pass_id": i, "rss_mb": {"max": float(m)}}
        for i, m in enumerate(maxes)
    ]


def test_a_noisy_plateau_with_isolated_spikes_is_not_a_leak():
    """The 2026-08-23 field case, replayed in miniature. `peak - first` called this
    "the OOM signature" — but 3 of 193 passes spiked while first/median/last were
    1323/1371/1303 MB, and RSS is sampled process-wide, so the largest spike sat
    inside a restore the app's own pre-restore snapshots timestamp. A fabricated FAIL
    is exactly as dishonest as a fabricated pass."""
    maxes = [1300 + (i % 7) * 30 for i in range(50)]
    maxes[19] = 2450.0  # one transient excursion, far above the floor
    c = p0._collector_verdict(_passes(maxes), _guard_state())
    assert c["verdict"] == "pass", c["reason"]
    m = c["measurements"]
    assert m["rss_sustained_rise_mb"] <= p0._COLLECTOR_CLIMB_ABS_MB
    # the excursion is REPORTED, never quietly dropped: hiding it would trade one
    # dishonest reading for another.
    assert m["rss_peak_across_passes_mb"] == 2450.0
    assert len(m["rss_spikes_above_floor"]) == 1
    assert "spike" in c["reason"] and "process-wide" in c["reason"]


def test_a_sustained_climb_over_many_passes_still_fails():
    """The twin. An over-corrected detector that never fails is the mirror defect, so
    the direction this check exists for must still bite at the same length of window
    the field case passes at."""
    maxes = [1300 + i * 20 for i in range(50)]  # +980 MB, monotone
    c = p0._collector_verdict(_passes(maxes), _guard_state())
    assert c["verdict"] == "fail", c["reason"]
    assert "rose" in c["reason"] and "stayed risen" in c["reason"]


def test_a_leak_that_saturates_early_and_stays_high_still_fails():
    """A windowed mean could miss a leak that climbs fast then plateaus — it does not,
    because the trailing window is still far above the opening one."""
    maxes = [1300.0] * 5 + [2600.0] * 45
    c = p0._collector_verdict(_passes(maxes), _guard_state())
    assert c["verdict"] == "fail", c["reason"]


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
# The passphrase and the exceptions a check catches (the coordinator's delta check of #1312, B1)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("site", ["backup", "incremental", "verify", "restore"])
def test_the_passphrase_is_out_of_every_exception_text_a_p0_report_writes_down(tmp_path, monkeypatch, site):
    """The four checks that hold the passphrase catch whatever the engine raises and write its words into
    the report: a file the debug bundle carries and, in a release run, the run's own state and report.
    Nothing in the engine names the passphrase today; this is the net where the text is made, so a message
    that did cannot reach any of them. Each site is driven with a failure whose message holds the passphrase,
    over a real backup where the site comes after one. MUTATION TARGETS: each of the four uses of
    ``_exception_text`` (replaced by the bare ``Name: message``)."""
    import src.backup.artifact as artifact
    import src.backup.stream_backup as stream_backup

    _live_corpus(tmp_path, monkeypatch)
    secret = "p0-exception-passphrase-7q3"

    def boom(*args, **kwargs):
        raise RuntimeError(f"could not reach {secret} on the drive")

    if site == "backup":
        monkeypatch.setattr(artifact, "write_volume_backup", boom)
    elif site == "incremental":
        real_backup = artifact.write_volume_backup
        taken: list[int] = []

        def once_then_boom(*args, **kwargs):
            taken.append(1)
            return real_backup(*args, **kwargs) if len(taken) == 1 else boom()

        monkeypatch.setattr(artifact, "write_volume_backup", once_then_boom)
    elif site == "verify":
        monkeypatch.setattr(stream_backup, "verify_stream_backup", boom)
    else:
        monkeypatch.setattr(artifact, "read_volume_backup", boom)

    out = p0.run_p0_validation(
        FakeCtx(), dest_dir=str(tmp_path / "drive" / "dest"), passphrase=secret,
        measure_incremental=(site == "incremental"),
    )
    checks = out["report"]["checks"]
    said = {
        "backup": checks["p0_1_backup"]["reason"],
        "incremental": (checks["p0_1_backup"]["measurements"]["incremental_refresh"] or {}).get("error"),
        "verify": checks["p0_1_verify"]["reason"],
        "restore": checks["p0_2_restore"]["reason"],
    }[site]
    assert "RuntimeError: could not reach ***redacted*** on the drive" in said, said
    assert secret not in json.dumps(out)
    assert secret not in Path(out["path"]).read_text(encoding="utf-8"), "the file the debug bundle carries"


def test_the_passphrase_is_out_of_the_failure_lines_the_engine_hands_back_as_data(tmp_path, monkeypatch):
    """The fifth way a message reaches a report, and the only one with no handler of this module in it:
    ``verify_stream_backup`` returns its failure lines as ``problems`` (a decrypt failure's line carries the
    exception's own words), and the verify check copies them into its measurements and its reason, which the P0
    file the debug bundle carries and, in a release run, the run's state hold. Every message the engine raises
    there is a literal today; this is the net where the lines are copied (the coordinator's delta check of
    #1312, F2). MUTATION TARGET: the scrub of ``problems``."""
    import src.backup.stream_backup as stream_backup

    _live_corpus(tmp_path, monkeypatch)
    secret = "p0-problem-line-passphrase-5k2"
    lines = [f"member data.db failed to decrypt: could not reach {secret} on the drive", "volume 2 failed its checksum"]
    monkeypatch.setattr(stream_backup, "verify_stream_backup", lambda *a, **k: {"ok": False, "problems": lines})
    out = p0.run_p0_validation(
        FakeCtx(), dest_dir=str(tmp_path / "drive" / "dest"), passphrase=secret, measure_incremental=False
    )
    verify = out["report"]["checks"]["p0_1_verify"]
    clean = ["member data.db failed to decrypt: could not reach ***redacted*** on the drive", "volume 2 failed its checksum"]
    assert verify["verdict"] == "fail"
    assert verify["reason"] == "verification failed: " + "; ".join(clean), verify["reason"]
    assert verify["measurements"]["problems"] == clean
    assert secret not in json.dumps(out)
    assert secret not in Path(out["path"]).read_text(encoding="utf-8"), "the file the debug bundle carries"
    assert secret in lines[0], "the engine's own list is read, never edited"


@pytest.mark.parametrize("secret", ["pass", "fail"])
def test_a_passphrase_that_is_also_a_verdict_word_leaves_the_verify_verdict_and_its_lead_alone(
        tmp_path, monkeypatch, secret):
    """The scrub is on the engine's lines and on nothing around them: the verdict is ``fail`` and the check's own
    words lead its reason whatever the passphrase is (the run puts no minimum on its length). MUTATION TARGET: a
    scrub of the check's reason, or of the whole report, in place of the lines. Only ``fail`` breaks under it
    (the lead's own ``fail`` would become the marker); ``pass`` pins the line's own replacement for a verdict
    word, and the next test pins the verdicts a whole-report scrub would turn into the marker."""
    import src.backup.stream_backup as stream_backup

    _live_corpus(tmp_path, monkeypatch)
    line = f"member data.db failed to decrypt: {secret}"
    monkeypatch.setattr(stream_backup, "verify_stream_backup", lambda *a, **k: {"ok": False, "problems": [line]})
    out = p0.run_p0_validation(
        FakeCtx(), dest_dir=str(tmp_path / "drive" / "dest"), passphrase=secret, measure_incremental=False
    )
    verify = out["report"]["checks"]["p0_1_verify"]
    assert verify["verdict"] == "fail" and verify["measurements"]["ok"] is False
    assert verify["reason"] == "verification failed: " + line.replace(secret, "***redacted***"), verify["reason"]


def test_the_passphrase_is_out_of_the_reason_when_joining_two_lines_would_rebuild_it(tmp_path, monkeypatch):
    """The reason joins the engine's lines with ``"; "``: a passphrase that holds ``"; "`` and whose halves end
    one line and start the next is in neither line and in the joined text (the coordinator's check of #1318,
    N5). The lines stay as the engine made them, and the lead stays the check's own words. MUTATION TARGET: the
    scrub of the joined tail."""
    import src.backup.stream_backup as stream_backup

    _live_corpus(tmp_path, monkeypatch)
    secret = "left half; right half"
    lines = ["volume 2 failed its checksum, left half", "right half was not read"]
    monkeypatch.setattr(stream_backup, "verify_stream_backup", lambda *a, **k: {"ok": False, "problems": lines})
    out = p0.run_p0_validation(
        FakeCtx(), dest_dir=str(tmp_path / "drive" / "dest"), passphrase=secret, measure_incremental=False
    )
    verify = out["report"]["checks"]["p0_1_verify"]
    assert verify["reason"] == "verification failed: volume 2 failed its checksum, ***redacted*** was not read", verify["reason"]
    assert verify["measurements"]["problems"] == lines
    assert secret not in json.dumps(out)
    assert secret not in Path(out["path"]).read_text(encoding="utf-8"), "the file the debug bundle carries"


def test_a_passphrase_that_is_also_a_verdict_word_leaves_the_verdicts_and_the_success_texts_alone(
        tmp_path, monkeypatch):
    """Why the scrub is on the caught texts and not on the finished report: a report holds verdicts
    (``pass``, ``fail``) that code and the panel compare, and the run puts no minimum on a passphrase's
    length. An exact-match scrub of the whole report by the passphrase ``pass`` would turn every verdict and
    the word in ``passphrase`` into the marker, and read a good backup as one that did not verify. MUTATION
    TARGET: a scrub of the report (or of a check) as a whole."""
    _live_corpus(tmp_path, monkeypatch)
    out = p0.run_p0_validation(
        FakeCtx(), dest_dir=str(tmp_path / "drive" / "dest"), passphrase="pass", measure_incremental=False
    )
    checks = out["report"]["checks"]
    assert checks["p0_1_verify"]["verdict"] == "pass" and checks["p0_2_restore"]["verdict"] == "pass", checks
    assert "the passphrase decrypted every volume" in checks["p0_1_verify"]["reason"]
    assert out["report"]["summary"]["pass"] >= 2
    assert "***redacted***" not in json.dumps(out), "nothing the run said was a message that named it"


#: What the ``traceback`` module's functions that read the exception being handled are called, for the
#: ``from traceback import format_exc`` form (``traceback.format_exc()`` is found by the module's name).
_TRACEBACK_NAMES = frozenset(
    {"format_exc", "print_exc", "format_exception", "print_exception", "format_exception_only", "exc_info"}
)


def _writes_a_traceback(call: ast.Call) -> bool:
    """Whether ``call`` writes the exception being handled: ``.exception(...)`` (a logger's, or
    ``sys.exception()``), a call into the ``traceback`` module or a name imported from it, ``sys.exc_info()``,
    or any call given an ``exc_info`` that is not the constant ``False`` or ``None``."""
    func = call.func
    if isinstance(func, ast.Attribute):
        if func.attr == "exception" or (isinstance(func.value, ast.Name) and func.value.id == "traceback"):
            return True
        if func.attr == "exc_info" and isinstance(func.value, ast.Name) and func.value.id == "sys":
            return True
    elif isinstance(func, ast.Name) and func.id in _TRACEBACK_NAMES:
        return True
    return any(
        kw.arg == "exc_info" and not (isinstance(kw.value, ast.Constant) and kw.value.value in (False, None))
        for kw in call.keywords
    )


#: The names the secret goes by where the release run, the volume job and the import queue hold it: the parameter or
#: local a helper is given it as (``passphrase``; ``secret`` and ``needle`` in ``release_run.py``'s helpers;
#: ``corpus_passphrase``, the restore job's second one) ...
_SECRET_NAMES = frozenset({"passphrase", "corpus_passphrase", "secret", "needle"})

#: ... and, as an attribute, the one the run's parameters carry (``run.params.passphrase``, a request body's
#: ``body.passphrase``) and the one the import queue keeps for the length of a run (``self._passphrase``).
_SECRET_ATTRIBUTES = frozenset({"passphrase", "_passphrase"})

#: The calls that write a caught exception as a text with the secret taken out of it: name -> (the index of the
#: argument that carries what is written, the index of the secret). A handler may use the exception only inside the
#: first, and only when the second IS the secret.
_SCRUBBING_CALLS = {
    "_exception_text": (0, 1),  # p0_validation: "Name: message", scrubbed, from the exception itself
    "_error_text": (0, 1),  # release_run_fresh_restore: the same, for the restore child
    "_scrub_value": (0, 1),  # release_run: ``secret_scrub.scrub_value`` over a text built from the exception
    "scrub_value": (0, 1),
    "_log_phase_failure": (1, 3),  # release_run: logs the whole chain, with the secret out of it
    "scrub_text": (0, 1),  # secret_scrub: the engine's words, scrubbed where ``verify_stream_backup`` makes the line
}

#: The same for the helpers of ``secret_scrub`` that take ANY NUMBER of secrets (the volume job's restore holds two,
#: the artifact's passphrase and the corpus's): name -> (the index of the argument that carries what is written, the
#: index of the first secret). Such a call routes only when EVERY argument from that index on is a secret AND together
#: they name every secret the function holds, because a text scrubbed of one of two still carries the other.
_SCRUBBING_CALLS_OVER_SECRETS = {
    "scrubbed": (0, 1),  # a text with each secret taken out
    "traceback_text": (0, 1),  # the traceback of the exception, scrubbed
    "log_failure": (2, 3),  # logs the whole chain, with each secret out of it (the logger, then the words)
}

#: What a handler of a module that answers requests (the route layer) may hand the exception to without a scrub: the
#: response the caller gets. A response is the caller's own text; the recorders that keep one scrub it where they make
#: their record (the import queue, which this guard also reads) and ``note_http_error`` records the status alone (a
#: test pins that). A log record is not a response.
_RESPONSE_BUILDERS = frozenset({"HTTPException", "_restore_error"})

#: What a caught exception may be asked for without writing its message: a phase error's two fields that are data
#: (its status and what the phase measured before it failed) -- and only the exception the run's own phases raise,
#: ``_PhaseError``, because on any other exception ``status`` and ``partial`` are the engine's -- and, in the walk, its
#: class (``type(exc)``).
_PLAIN_FIELDS = frozenset({"status", "partial"})


def _is_a_phase_error_handler(handler: ast.ExceptHandler) -> bool:
    """Whether ``handler`` catches ``_PhaseError`` by that name alone."""
    return isinstance(handler.type, ast.Name) and handler.type.id == "_PhaseError"


def _is_the_secret(node: ast.AST) -> bool:
    """Whether ``node`` IS the secret as the run holds it: a name it goes by or an attribute it is kept in
    (``run.params.passphrase``, ``self._passphrase``) -- not a constant (``""`` scrubs nothing), not a call, not any
    other name."""
    return (isinstance(node, ast.Name) and node.id in _SECRET_NAMES) or (
        isinstance(node, ast.Attribute) and node.attr in _SECRET_ATTRIBUTES
    )


def _secrets_held(fn: ast.AST) -> set[str]:
    """The secrets the function holds, by the name each goes by: a parameter (any kind) or a name it reads that is one
    of :data:`_SECRET_NAMES`, or an attribute in :data:`_SECRET_ATTRIBUTES` (the secret as ``passphrase``). The
    attribute is how ``release_run.py`` and the import queue hold it (``run.params.passphrase``,
    ``self._passphrase``), which no parameter list shows."""
    held: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.arg) and n.arg in _SECRET_NAMES:
            held.add(n.arg)
        elif isinstance(n, ast.Name) and n.id in _SECRET_NAMES:
            held.add(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in _SECRET_ATTRIBUTES:
            held.add("passphrase")
    return held


def _holds_the_secret(fn: ast.AST) -> bool:
    """Whether the function holds any secret (:func:`_secrets_held`)."""
    return bool(_secrets_held(fn))


def _names_every_secret(args: list[ast.expr], held: set[str]) -> bool:
    """Whether ``args`` (the secret arguments of a call of :data:`_SCRUBBING_CALLS_OVER_SECRETS`) are all secrets and,
    between them, name every secret in ``held`` (an attribute counts as ``passphrase``)."""
    named = {a.id if isinstance(a, ast.Name) else "passphrase" for a in args if _is_the_secret(a)}
    return bool(args) and all(_is_the_secret(a) for a in args) and held <= named


def _caught_exception_leaks(source: str, *, responses: bool = False) -> tuple[list[str], list[str], int]:
    """Read ``source`` the way the guard below does: ``(holders, offenders, routed)`` -- the functions that hold the
    secret (:func:`_holds_the_secret`; ``async`` or not), the places inside their ``except`` handlers where the caught
    exception reaches a text some way other than a call of :data:`_SCRUBBING_CALLS` that is given the secret (or of
    :data:`_SCRUBBING_CALLS_OVER_SECRETS` that is given every secret the function holds), and how many such calls the
    handlers make (a walk that routes nothing has found nothing to guard).

    A way is: the handler's own name used anywhere but inside the carrying argument of such a call (an f-string,
    ``str()``, ``.args``, a copy under another name, a call that is handed it, that call's other arguments,
    ``raise ... from exc``, which carries it on as the cause), except its class (``type(exc)``) and the ``status`` and
    ``partial`` of a ``_PhaseError``; such a call given no second argument, an empty one or one that is not the secret
    routes nothing, so the exception inside it is a way too; and, in a handler WITH OR WITHOUT a name, a call that
    writes the traceback (:func:`_writes_a_traceback`). It follows no call: a helper the handler calls that reads the
    exception itself is not seen. With ``responses`` (the route layer) the exception may also go to a call of
    :data:`_RESPONSE_BUILDERS` and be the cause of what such a call is raised as: the caller's own response."""
    tree = ast.parse(source)
    holders: list[str] = []
    offenders: dict[int, str] = {}
    routed: set[int] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        held = _secrets_held(fn)
        if not held:
            continue
        holders.append(fn.name)
        for handler in (n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)):
            allowed: set[int] = set()
            for node in ast.walk(handler):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    spec = _SCRUBBING_CALLS.get(node.func.id)
                    many = _SCRUBBING_CALLS_OVER_SECRETS.get(node.func.id)
                    if spec and len(node.args) > max(spec) and _is_the_secret(node.args[spec[1]]):
                        routed.add(id(node))
                        allowed |= {id(n) for n in ast.walk(node.args[spec[0]])}
                    elif many and len(node.args) > many[1] and _names_every_secret(node.args[many[1] :], held):
                        routed.add(id(node))
                        allowed |= {id(n) for n in ast.walk(node.args[many[0]])}
                    elif responses and node.func.id in _RESPONSE_BUILDERS:
                        allowed |= {id(n) for n in ast.walk(node)}
                    elif node.func.id == "type" and len(node.args) == 1:
                        allowed.add(id(node.args[0]))
                elif isinstance(node, ast.Attribute) and node.attr in _PLAIN_FIELDS and _is_a_phase_error_handler(handler):
                    allowed.add(id(node.value))
                elif (
                    responses
                    and isinstance(node, ast.Raise)
                    and node.cause is not None
                    and isinstance(node.exc, ast.Call)
                    and isinstance(node.exc.func, ast.Name)
                    and node.exc.func.id in _RESPONSE_BUILDERS
                ):
                    allowed |= {id(n) for n in ast.walk(node.cause)}
            for node in ast.walk(handler):
                named = handler.name and isinstance(node, ast.Name) and node.id == handler.name
                if (named and id(node) not in allowed) or (isinstance(node, ast.Call) and _writes_a_traceback(node)):
                    offenders.setdefault(id(node), f"{fn.name}, line {node.lineno}")
    return holders, sorted(offenders.values()), len(routed)


#: The modules that hold the passphrase, with where each lives under ``src/``, what the walk must find in it so that a
#: rename or a restructure cannot leave it looking at nothing (the functions it must read as holding the secret, and
#: the fewest calls of a scrubbing helper its handlers make today), and whether it answers requests (``responses``:
#: the exception may feed a response, :data:`_RESPONSE_BUILDERS`).
_GUARDED_MODULES = {
    "p0_validation": ("monitoring", {"_check_backup", "_check_restore"}, 4, False),
    "release_run": ("monitoring", {"_run_phase", "_fresh_install_restore"}, 4, False),
    "release_run_fresh_restore": ("monitoring", {"main"}, 1, False),
    "volume_job": ("backup", {"start_backup", "_run_backup", "_run_restore", "_run_verify"}, 17, False),
    "stream_backup": ("backup", {"verify_stream_backup"}, 1, False),
    "import_queue": ("backup", {"start", "_drive", "_run_corpus", "_run_legacy"}, 4, False),
    "backup_v2": ("api", {"_stage_upload", "restore_legacy_path", "volume_backup_start", "import_queue_start"}, 1, True),
    "unlock": ("api", {"unlock", "_unlock_locked", "create_db", "encrypt_db"}, 1, True),
}


@pytest.mark.parametrize("module", sorted(_GUARDED_MODULES))
def test_no_function_that_holds_the_passphrase_writes_a_caught_exception_any_way_but_through_a_scrub(module):
    """The sites there are today are pinned by behaviour tests; the next ``except ... as exc`` that puts ``{exc}``
    into a report is how the next leak is made, and no test of the existing ones would see it. Every handler inside
    a function that holds the passphrase (takes it, reads it into a local, or reads it off the run's parameters or
    the queue's ``self``) may use the caught exception only inside a call that scrubs it with the secret
    (``_exception_text``, the child's ``_error_text``, ``scrub_value``, ``_log_phase_failure``; ``secret_scrub``'s
    ``scrubbed``, ``traceback_text`` and ``log_failure``, which must be given EVERY secret the function holds, a
    restore's two), or ask for its class or a ``_PhaseError``'s ``status`` and ``partial``, and may ask for no
    traceback (``exc_info=``, ``.exception()``, the ``traceback`` module, ``sys.exc_info()``), because the text such
    a call writes carries the message too. In the route layer (``backup_v2.py``) the exception may also feed the
    RESPONSE the caller gets (``HTTPException``, ``_restore_error``): a response is outside this rule, and the one
    recorder that keeps a response's text, the import queue, is a module this guard reads. It reads the syntax of the
    modules in ``_GUARDED_MODULES`` and follows no call; what stays outside it is listed in ``LESSONS.md`` (the entry
    about a net going where the text is made) and in ``OPEN_QUEUE.md``, and the cases below pin what it sees.
    (``_check_unlock`` and ``_check_collector`` hold no secret, so they are not held to this.)"""
    package, must_hold, least_routed, responses = _GUARDED_MODULES[module]
    path = Path(p0.__file__).parents[1] / package / f"{module}.py"
    holders, offenders, routed = _caught_exception_leaks(path.read_text(encoding="utf-8"), responses=responses)
    assert must_hold <= set(holders), f"{module}: the walk found {holders}; a rename must not leave it looking at nothing"
    assert routed >= least_routed, (
        f"{module}: the walk saw {routed} calls of a scrubbing helper in the handlers and the module makes "
        f"{least_routed}: a restructure must not leave it looking at nothing"
    )
    assert not offenders, f"{module}: a caught exception reaches a text without going through a scrub: {offenders}"


#: The modules under ``src/`` whose functions hold the passphrase and write what they catch in a way
#: :func:`_caught_exception_leaks` flags (read with ``responses``, so a response does not count), that are NOT in
#: :data:`_GUARDED_MODULES`, each with why it stays outside. It is the list of what the walk does not cover, held to zero
#: slack both ways below: a module that starts to hold the passphrase and write what it catches has to be guarded or named
#: here with its reason, and an entry whose sites were fixed or went has to come out, so the list cannot go stale or grow
#: unseen. The walk reads the names in :data:`_SECRET_NAMES` and :data:`_SECRET_ATTRIBUTES`: a module that calls the
#: passphrase something else is not seen.
_NOT_GUARDED = {
    "analytics/columnar.py": (
        "NOT BUILT. Three log records written with exc_info inside functions that take the passphrase (connect, "
        "encryption_gate, refresh_persisted_read_model): an engine error can quote the statement that carried the key. "
        "They sit with the columnar store's key handling, which the key-derivation change in docs/ledger/OPEN_QUEUE.md reads."
    ),
    "llm/vllm_lifecycle.py": (
        "Not a passphrase: `needle` there is the search term failure_excerpt looks for in a server's log; nothing it "
        "handles is a secret."
    ),
    "osm/reference_run.py": (
        "Its own scrub, scrub(text, secrets_=...), applied where each text is made and pinned by "
        "tests/test_osm_reference_run.py; its handlers are not written through secret_scrub's helpers."
    ),
    "safety/crypto.py": (
        "decrypt_bytes and decrypt_stream re-raise their own literal messages from an InvalidTag or a struct.error, whose "
        "texts hold no passphrase."
    ),
    "testing/scale_bench.py": (
        "The developer benchmark: it runs on a synthetic corpus with a throwaway passphrase of its own and is never part of "
        "a shipped run."
    ),
}


def _modules_that_hold_the_passphrase_and_write_what_they_catch() -> set[str]:
    """Every module under ``src/`` where the walk finds a handler in a function that holds the secret that either writes
    the exception some way it flags or already writes it through a scrub (a response does not count)."""
    src = Path(p0.__file__).parents[1]
    found: set[str] = set()
    for path in sorted(src.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if not any(word in text for word in ("passphrase", "secret", "needle")):
            continue
        try:
            _, offenders, routed = _caught_exception_leaks(text, responses=True)
        except SyntaxError:
            continue
        if offenders or routed:
            found.add(path.relative_to(src).as_posix())
    return found


def test_every_module_that_holds_the_passphrase_and_writes_what_it_catches_is_guarded_or_listed_with_its_reason():
    """The guard above reads a table of modules, and a deleted row or a new module is something no test of the rows can see.
    This reads ``src/`` for the modules the walk would flag and holds the table and the list of what stays outside to it, both
    ways. MUTATION TARGET: a row of ``_GUARDED_MODULES`` dropped, or a module added to ``src/`` that holds the passphrase and
    writes ``{exc}``."""
    guarded = {f"{package}/{module}.py" for module, (package, *_rest) in _GUARDED_MODULES.items()}
    found = _modules_that_hold_the_passphrase_and_write_what_they_catch() - guarded
    assert found == set(_NOT_GUARDED), (
        f"hold the passphrase and write what they catch, neither guarded nor listed: {sorted(found - set(_NOT_GUARDED))}; "
        f"listed but no longer flagged (take them out): {sorted(set(_NOT_GUARDED) - found)}"
    )
    assert all(len(reason) > 60 for reason in _NOT_GUARDED.values()), "a reason, not a placeholder"


def _guarded(clause: str, body: str, head: str = "def check(ctx, passphrase):") -> str:
    """The source of a function with one handler: ``clause`` is its ``except`` line and ``body`` the one line
    under it -- the guard's question, small enough to read at a glance."""
    return f"{head}\n    try:\n        go()\n    {clause}\n        {body}\n"


_NAMED = "except Exception as exc:"
_UNNAMED = "except Exception:"
_AS_ERR = "except Exception as err:"
_PHASE = "except _PhaseError as exc:"
_TWO_SECRETS = "def check(ctx, passphrase, corpus_passphrase):"
#: A function that keeps the secret on ``self``, as the import queue does, with ``body`` in the handler.
_ON_SELF = "def check(self):\n    key = self._passphrase\n    try:\n        go()\n    except Exception as exc:\n        {}\n"

#: Each way a caught exception can reach a text, as the function the guard must flag.
_WAYS_THAT_LEAK = {
    "its text in an f-string": _guarded(_NAMED, "err = f'failed: {exc}'"),
    "str() of it": _guarded(_NAMED, "err = str(exc)"),
    "its arguments": _guarded(_NAMED, "err = exc.args[0]"),
    "a copy under another name": _guarded(_NAMED, "kept = exc"),
    "handed to another function": _guarded(_NAMED, "note(exc)"),
    "the cause of a new exception": _guarded(_NAMED, "raise RuntimeError('x') from exc"),
    "a log call asked for the traceback": _guarded(_UNNAMED, "_LOG.warning('x', exc_info=True)"),
    "a log call whose exc_info is not a constant": _guarded(_UNNAMED, "_LOG.warning('x', exc_info=want)"),
    "a logger's .exception()": _guarded(_UNNAMED, "_LOG.exception('x')"),
    "traceback.format_exc()": _guarded(_UNNAMED, "err = traceback.format_exc()"),
    "format_exc imported by name": _guarded(_UNNAMED, "err = format_exc()"),
    "sys.exc_info()": _guarded(_UNNAMED, "err = sys.exc_info()"),
    "sys.exception()": _guarded(_UNNAMED, "err = sys.exception()"),
    "an async function": _guarded(_NAMED, "err = str(exc)", head="async def check(ctx, passphrase):"),
    "a positional-only passphrase": _guarded(_NAMED, "err = str(exc)", head="def check(passphrase, /, ctx):"),
    "a keyword-only passphrase": _guarded(_NAMED, "err = str(exc)", head="def check(ctx, *, passphrase):"),
    "a closure inside the function": (
        "def check(ctx, passphrase):\n    def inner():\n        try:\n            go()\n"
        "        except Exception as exc:\n            return str(exc)\n    return inner()\n"
    ),
    # --- the name, the position and the secret are each a way of their own
    "a handler named something other than exc": _guarded(_AS_ERR, "e = str(err)"),
    "the exception as the helper's second argument": _guarded(_NAMED, "err = _exception_text(passphrase, exc)"),
    "the helper given no secret": _guarded(_NAMED, "err = _exception_text(exc)"),
    "the helper given an empty secret": _guarded(_NAMED, "err = _exception_text(exc, '')"),
    "the helper given a name that is not the secret": _guarded(_NAMED, "err = _exception_text(exc, other)"),
    "the secret in another position than the one the helper reads it at": _guarded(
        _NAMED, "err = _exception_text(exc, other, passphrase)"
    ),
    "a scrub given a name that is not the secret": _guarded(_NAMED, "err = _scrub_value(str(exc), other)"),
    "scrub_text given a name that is not the secret": _guarded(_NAMED, "err = scrub_text(str(exc), other)"),
    "a scrub given another field of the run": _guarded(_NAMED, "err = _scrub_value(str(exc), run.params.dest_dir)"),
    "the exception again beside a scrub": _guarded(_NAMED, "err = _scrub_value(str(exc), passphrase) + str(exc)"),
    "the message after the class name": _guarded(_NAMED, "err = f'{type(exc).__name__}: {exc}'"),
    "the logging helper, the exception in another place": _guarded(
        _NAMED, "_log_phase_failure(name, other, exc, passphrase)"
    ),
    "a field of the exception that is not plain": _guarded(_NAMED, "err = exc.message"),
    # --- a ``status`` or ``partial`` is data only on the run's own phase error
    "a status read off an exception that is not a phase error": _guarded(_NAMED, "end(exc.status)"),
    "a partial read off an exception that is not a phase error": _guarded(_NAMED, "end(result=exc.partial)"),
    "a phase error caught beside another type": _guarded("except (_PhaseError, RuntimeError) as exc:", "end(exc.status)"),
    # --- a function that holds the secret by another route than a parameter named passphrase
    "a secret read off the run's parameters": (
        "def check(run):\n    key = run.params.passphrase\n    try:\n        go()\n    except Exception as exc:\n"
        "        err = str(exc)\n"
    ),
    "a secret read into a local": (
        "def check(ctx):\n    passphrase = ctx.get()\n    try:\n        go()\n    except Exception as exc:\n"
        "        err = str(exc)\n"
    ),
    "a secret kept on self": _ON_SELF.format("err = str(exc)"),
    "a parameter named secret": _guarded(_NAMED, "err = str(exc)", head="def check(ctx, secret):"),
    "a parameter named needle": _guarded(_NAMED, "err = str(exc)", head="def check(ctx, needle):"),
    "a parameter named corpus_passphrase": _guarded(_NAMED, "err = str(exc)", head="def check(ctx, corpus_passphrase):"),
    # --- the helpers that take any number of secrets (secret_scrub): every secret the function holds must be named
    "a text scrubbed of one of two secrets": _guarded(
        _NAMED, "err = scrubbed(str(exc), passphrase)", head=_TWO_SECRETS
    ),
    "a text scrubbed of the other of two secrets": _guarded(
        _NAMED, "err = scrubbed(str(exc), corpus_passphrase)", head=_TWO_SECRETS
    ),
    "a text scrubbed of a name that is not a secret beside the secret": _guarded(
        _NAMED, "err = scrubbed(str(exc), passphrase, other)"
    ),
    "a text scrubbed of no secret": _guarded(_NAMED, "err = scrubbed(str(exc))"),
    "a text scrubbed of an empty secret": _guarded(_NAMED, "err = scrubbed(str(exc), '')"),
    "the exception in the place of the secrets": _guarded(_NAMED, "err = scrubbed(passphrase, exc)"),
    "a starred list in the place of the secrets": _guarded(_NAMED, "err = scrubbed(str(exc), *held)"),
    "a traceback scrubbed of one of two secrets": _guarded(
        _NAMED, "err = traceback_text(exc, corpus_passphrase)", head=_TWO_SECRETS
    ),
    "the logging helper given one of two secrets": _guarded(
        _NAMED, "log_failure(_LOG, 'x', exc, passphrase)", head=_TWO_SECRETS
    ),
    "the logging helper given no secret": _guarded(_NAMED, "log_failure(_LOG, 'x', exc)"),
    "the logging helper, the exception as its message": _guarded(
        _NAMED, "log_failure(_LOG, str(exc), other, passphrase)"
    ),
    "the logging helper, the exception in the place of the logger": _guarded(
        _NAMED, "log_failure(exc, 'x', other, passphrase)"
    ),
    "a text scrubbed of a secret kept on self, beside the exception": _ON_SELF.format(
        "err = scrubbed(str(exc), self._passphrase) + str(exc)"
    ),
    "a text scrubbed of another attribute of self": _ON_SELF.format("err = scrubbed(str(exc), self._other)"),
}

#: What the guard must leave alone, as the function it is asked about and the calls it must count as routed.
_WAYS_THAT_ARE_FINE = {
    "the helper, given the passphrase": (_guarded(_NAMED, "err = _exception_text(exc, passphrase)"), 1),
    "the child's helper, given the passphrase": (_guarded(_NAMED, "err = _error_text(exc, passphrase)"), 1),
    "scrub_text, given the passphrase": (_guarded(_NAMED, "err = scrub_text(str(exc), passphrase)"), 1),
    "a scrub of a text built from the exception": (
        _guarded(_NAMED, "err = _scrub_value(f'{type(exc).__name__}: {exc}', passphrase)[:400]"),
        1,
    ),
    "a scrub given the secret off the run's parameters": (
        "def check(run):\n    try:\n        go()\n    except Exception as exc:\n"
        "        err = scrub_value(str(exc), run.params.passphrase)\n",
        1,
    ),
    "the logging helper, given the secret": (_guarded(_NAMED, "_log_phase_failure(name, exc, why, passphrase)"), 1),
    "only the exception's class": (_guarded(_NAMED, "_LOG.warning('x (%s)', type(exc).__name__)"), 0),
    "a phase error's status and partial": (_guarded(_PHASE, "end(exc.status, result=exc.partial)"), 0),
    "a log call that asks for no traceback": (_guarded(_UNNAMED, "_LOG.warning('x', exc_info=False)"), 0),
    "a log call whose exc_info is None": (_guarded(_UNNAMED, "_LOG.warning('x', exc_info=None)"), 0),
    "a handler that only returns": (_guarded(_UNNAMED, "return None"), 0),
    "a text scrubbed of the only secret there is": (_guarded(_NAMED, "err = scrubbed(str(exc), passphrase)"), 1),
    "a text scrubbed of both of two secrets": (
        _guarded(_NAMED, "err = scrubbed(str(exc), passphrase, corpus_passphrase)", head=_TWO_SECRETS),
        1,
    ),
    "a text scrubbed of both of two secrets, in the other order": (
        _guarded(_NAMED, "err = scrubbed(str(exc), corpus_passphrase, passphrase)", head=_TWO_SECRETS),
        1,
    ),
    "a text built from the exception, scrubbed whole": (
        _guarded(
            _NAMED,
            "err = scrubbed(str(exc) if isinstance(exc, ValueError) else classify('r', exc), passphrase)[:2000]",
        ),
        1,
    ),
    "a traceback scrubbed of both secrets": (
        _guarded(_NAMED, "err = traceback_text(exc, passphrase, corpus_passphrase)[-8000:]", head=_TWO_SECRETS),
        1,
    ),
    "the logging helper, given both secrets and a level": (
        _guarded(_NAMED, "log_failure(_LOG, 'x', exc, passphrase, corpus_passphrase, level=30)", head=_TWO_SECRETS),
        1,
    ),
    "a text scrubbed of the secret a queue keeps on self": (_ON_SELF.format("err = scrubbed(str(exc), self._passphrase)"), 1),
    "the logging helper, given the secret a queue keeps on self": (
        _ON_SELF.format("log_failure(_LOG, 'x', exc, self._passphrase)"),
        1,
    ),
}

#: The route layer (``responses``): what a handler there may NOT do with its exception, and what it may.
_ROUTE = "def route(body, passphrase):"
_ROUTE_WAYS_THAT_LEAK = {
    "a log call given the exception": _guarded(_NAMED, "_LOG.warning('x %s', exc)", head=_ROUTE),
    "a log call given the exception's text": _guarded(_NAMED, "_LOG.warning('x %s', str(exc))", head=_ROUTE),
    "a log call asked for the traceback": _guarded(_NAMED, "_LOG.exception('x')", head=_ROUTE),
    "a log call asked for the traceback, the handler unnamed": _guarded(_UNNAMED, "_LOG.warning('x', exc_info=True)", head=_ROUTE),
    "the exception's text kept in a local": _guarded(_NAMED, "err = str(exc)", head=_ROUTE),
    "the exception handed to a function that is not a response": _guarded(_NAMED, "note(exc)", head=_ROUTE),
    "a response built from the exception and a log of it beside it": (
        f"{_ROUTE}\n    try:\n        go()\n    {_NAMED}\n        _LOG.warning('x %s', exc)\n"
        "        raise HTTPException(status_code=400, detail='no') from exc\n"
    ),
    "the logging helper given no secret": _guarded(_NAMED, "log_failure(_LOG, 'x', exc)", head=_ROUTE),
}
_ROUTE_WAYS_THAT_ARE_FINE = {
    "a response built from the exception's text": (
        _guarded(_NAMED, "raise HTTPException(status_code=400, detail=f'x: {exc}') from exc", head=_ROUTE),
        0,
    ),
    "a response built by the module's helper": (
        _guarded(_NAMED, "raise _restore_error('restore', exc) from exc", head=_ROUTE),
        0,
    ),
    "a response whose cause alone is the exception": (
        _guarded(_NAMED, "raise HTTPException(status_code=400, detail='no') from exc", head=_ROUTE),
        0,
    ),
    "a response built from str() of the exception": (
        _guarded(_NAMED, "raise HTTPException(status_code=409, detail=str(exc)) from exc", head=_ROUTE),
        0,
    ),
    "the logging helper, given the secret": (_guarded(_NAMED, "log_failure(_LOG, 'x', exc, passphrase)", head=_ROUTE), 1),
}


@pytest.mark.parametrize("way", sorted(_WAYS_THAT_LEAK))
def test_the_guard_on_caught_exception_texts_flags_each_way_one_can_reach_a_text(way):
    """Negative space for the guard itself: a walk that cannot see ``exc_info=True``, an unnamed handler, an
    ``async`` function, a handler named anything but ``exc``, an empty secret or a secret read off an object passes
    the real modules and sees nothing. MUTATION TARGET: any one of the walk's rules, its choice of function kinds and
    parameter kinds, its table of scrubbing calls or the position it reads the exception and the secret at."""
    holders, offenders, _ = _caught_exception_leaks(_WAYS_THAT_LEAK[way])
    assert holders, f"{way}: the function was not read as one that holds the passphrase"
    assert offenders, f"{way}: the guard did not flag it"


@pytest.mark.parametrize("way", sorted(_WAYS_THAT_ARE_FINE))
def test_the_guard_on_caught_exception_texts_leaves_the_allowed_forms_alone(way):
    source, expected_routed = _WAYS_THAT_ARE_FINE[way]
    holders, offenders, routed = _caught_exception_leaks(source)
    assert holders == ["check"] and offenders == [], (holders, offenders)
    assert routed == expected_routed, routed


@pytest.mark.parametrize("way", sorted(_ROUTE_WAYS_THAT_LEAK))
def test_the_guard_on_the_route_layer_flags_each_way_a_log_or_a_local_could_carry_the_exception(way):
    """The route layer may answer with the exception (a response is outside the rule) and may not record it: a log
    call, a traceback, a local that could reach one. MUTATION TARGET: the response builders' table, or letting the
    ``responses`` mode allow more than a call of a builder and the cause of what such a call is raised as."""
    holders, offenders, _ = _caught_exception_leaks(_ROUTE_WAYS_THAT_LEAK[way], responses=True)
    assert holders == ["route"], f"{way}: the function was not read as one that holds the passphrase"
    assert offenders, f"{way}: the guard did not flag it"


@pytest.mark.parametrize("way", sorted(_ROUTE_WAYS_THAT_ARE_FINE))
def test_the_guard_on_the_route_layer_leaves_a_response_and_a_scrubbed_record_alone(way):
    source, expected_routed = _ROUTE_WAYS_THAT_ARE_FINE[way]
    holders, offenders, routed = _caught_exception_leaks(source, responses=True)
    assert holders == ["route"] and offenders == [], (holders, offenders)
    assert routed == expected_routed, routed


def test_a_response_is_a_way_for_a_module_that_does_not_answer_requests():
    """The relaxation is the route layer's alone: the same handler in a module read without ``responses`` is a leak, by the
    exception handed to the response and, apart, by the exception that is its cause. MUTATION TARGET: either branch of the
    walk that allows a response, made to apply to every module."""
    for body in (
        "raise HTTPException(status_code=400, detail=str(exc))",
        "raise HTTPException(status_code=400, detail='no') from exc",
    ):
        source = _guarded(_NAMED, body, head=_ROUTE)
        assert _caught_exception_leaks(source)[1], f"{body}: a response is outside the rule only in the route layer"
        assert not _caught_exception_leaks(source, responses=True)[1], body


def test_the_guard_on_caught_exception_texts_does_not_read_a_function_that_is_not_given_the_passphrase():
    """``_check_unlock`` and ``_check_collector`` put ``{exc}`` into their reports on purpose; they hold no
    secret, so a guard that read every function would reject them."""
    holders, offenders, _ = _caught_exception_leaks(_guarded(_NAMED, "err = str(exc)", head="def check(ctx):"))
    assert holders == [] and offenders == []


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


def test_no_acceptance_bar_claims_a_corpus_SIZE_no_run_has_reached():
    """A bar naming a scale makes every verdict read as though it cleared that scale.

    These said "the maintainer's real 100 GB corpus" until 2026-08-03, and no run has
    ever been at 100 GB: v0.2.0 measured 2,522 MiB and the 0.3 validation 15,699 MiB
    (794,333 articles). The house rule is that a verdict must map to the bar it actually
    tested, so a bar states the PROPERTY under test (RAM does not scale with the corpus)
    and the report's own measurements carry the size the run happened at.

    Sizes are matched with a unit-aware pattern rather than the literal "100 GB", so
    swapping in "500 GB" or "5 TB" fails here too -- a guard is only as strong as the
    generality of what it searches for.
    """
    import re

    bars = p0._acceptance_bars()
    size = re.compile(r"\b\d+(?:\.\d+)?\s*(?:GB|TB|GiB|TiB)\b", re.IGNORECASE)
    for check, bar in bars.items():
        found = size.findall(bar)
        assert not found, (
            f"{check}'s acceptance bar names a corpus size {found}; state the property "
            "under test instead and let measurements carry the scale of the run"
        )


def test_the_restore_bar_says_what_a_self_restore_cannot_show():
    """The P0.2 bar is "imports on a FRESH INSTALL", and the probe is a self-restore.

    That distinction is load-bearing: on a self-restore every row reads as a duplicate,
    which is exactly why fourteen never-merged tables stayed invisible in the field
    report. The bar must keep saying so rather than letting a staged round-trip read as
    the fresh-install acceptance.
    """
    bar = p0._acceptance_bars()["p0_2_restore"]
    assert "FRESH INSTALL" in bar
    assert "duplicate" in bar, "the bar must say WHY a self-restore cannot show this"


def test_the_unlock_bar_requires_a_COLD_boot():
    """A warm re-unlock skips WAL recovery -- the phase that grows with the corpus, and
    the one the 0.3 gate's row 7 is still open on."""
    bar = p0._acceptance_bars()["p0_4_unlock"]
    assert "COLD" in bar
    assert "WAL" in bar, "the bar must name what a warm unlock fails to exercise"
