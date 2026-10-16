"""Record files that LEAVE the install, or join the live ones, are taken through the passphrase scrub whole-line first.

The audit of file-content readers (rc-diagnostics/file-content-readers-audit-2026-10-16) found four places that put a log's text somewhere else
raw: the single-file backup's ``logs/*`` members, the volume backup's staged copies of the same files, the restore's merge of a backup's log
lines into the live logs, and the quoted reason of a failed qualification bundle. A log an older build wrote can hold a key. Each test below
fails when its scrub is removed.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from src.database import connect
from src.monitoring import secret_scrub as ss

_KEY = "hunter2-correct-horse-9f3a"


@pytest.fixture(autouse=True)
def _held(monkeypatch):
    monkeypatch.setattr(connect, "_passphrase", _KEY)
    ss.forget_held()
    yield
    ss.forget_held()


def _log(tmp: Path, name: str = "app_errors.jsonl") -> Path:
    p = tmp / name
    p.write_text(
        json.dumps({"at": 1, "msg": "plain line"}) + "\n"
        + json.dumps({"at": 2, "msg": f"opened with {_KEY} here"}) + "\r\n"
        + json.dumps({"at": 3, "msg": "last"}),  # no final line ending
        encoding="utf-8",
    )
    return p


def test_scrubbed_copy_takes_the_key_out_and_keeps_every_other_byte(tmp_path):
    src = _log(tmp_path)
    dst = tmp_path / "out" / "copy.jsonl"
    changed = ss.scrubbed_copy(src, dst)
    got = dst.read_bytes()
    assert changed == 1 and _KEY.encode() not in got
    raw = src.read_bytes().split(b"\n")
    out = got.split(b"\n")
    assert out[0] == raw[0] and out[2] == raw[2], "untouched lines are byte-identical, the missing final line ending stays missing"
    assert out[1].endswith(b"\r"), "a CRLF ending is kept"


def test_scrubbed_copy_never_copies_an_overlong_line_in_part(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "_COPY_LINE_BYTES", 100)
    src = tmp_path / "big.jsonl"
    src.write_text("first\n" + "ZQ" * 300 + _KEY + "\nlast\n", encoding="utf-8")
    dst = tmp_path / "big.out"
    ss.scrubbed_copy(src, dst)
    text = dst.read_text(encoding="utf-8")
    assert "ZQZQ" not in text and _KEY[:8] not in text
    assert "first" in text and "last" in text and "a line of 627 bytes is not copied" in text


def test_scrubbed_copy_of_a_line_of_exactly_the_bound_is_kept_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "_COPY_LINE_BYTES", 100)
    src = tmp_path / "edge.jsonl"
    src.write_text("a\n" + "y" * 100, encoding="utf-8")  # exactly the bound, no line ending, end of file
    dst = tmp_path / "edge.out"
    ss.scrubbed_copy(src, dst)
    assert dst.read_text(encoding="utf-8") == "a\n" + "y" * 100


def test_the_single_file_backup_carries_its_log_members_scrubbed(tmp_path, monkeypatch):
    from src.backup import artifact

    monkeypatch.setattr(artifact, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("src.backup.sqlite_backup.live_db_path", lambda: tmp_path / "live.db")
    monkeypatch.setattr(artifact, "snapshot_sqlite", lambda _src, dest: Path(dest).write_bytes(b""))
    _log(tmp_path)
    out = tmp_path / "stage"
    out.mkdir()
    members = artifact._collect_members(False, out)
    logs = [m for m in members if m.role == "logs"]
    assert [m.name for m in logs] == ["logs/app_errors.jsonl"]
    assert _KEY not in logs[0].path.read_text(encoding="utf-8")
    assert _KEY in (tmp_path / "app_errors.jsonl").read_text(encoding="utf-8"), "the live log itself is not rewritten"


def test_the_volume_backup_stages_its_log_members_scrubbed(tmp_path, monkeypatch):
    from src.backup import stream_backup

    monkeypatch.setattr(stream_backup, "data_dir", lambda: tmp_path)
    _log(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    members = stream_backup._collect_side_members(stage)
    logs = [m for m in members if m.role == "logs"]
    assert logs, "the log member must be staged"
    assert _KEY not in Path(logs[0].path).read_text(encoding="utf-8")


def test_a_restored_backups_log_lines_are_scrubbed_before_they_join_the_live_log(tmp_path, monkeypatch):
    from src.backup.merge import merge_side_files
    from tests.backup_helper import staged_artifact

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "live"))
    staging = tmp_path / "staging"
    (staging / "logs").mkdir(parents=True)
    _log(staging / "logs")
    staged = staged_artifact(staging, members=[{"name": "logs/app_errors.jsonl", "role": "logs"}], origin_fingerprint="ab" * 32)
    report = merge_side_files(staged)
    live = Path(tmp_path / "live" / "app_errors.jsonl")
    assert report["logs"]["app_errors.jsonl"]["appended"] >= 1
    text = live.read_text(encoding="utf-8")
    assert _KEY not in text and "plain line" in text


def _bundle(sidecar_name: str, body: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "x")
        z.writestr(sidecar_name, body)
    return buf.getvalue()


def test_a_failed_bundles_quoted_reason_is_scrubbed_before_it_is_cut(monkeypatch):
    from src.catalog import qualification_merge as qm

    body = ("p" * 1990 + _KEY + " tail").encode()  # the 2,000-character cut falls inside the key
    data = _bundle(qm.BUNDLE_MEMBER + ".error.txt", body)
    with pytest.raises(qm.MergeInputError) as raised:
        qm.rows_from_bundle_bytes(data, "bundle.zip")
    shown = json.dumps(getattr(raised.value, "__dict__", {}), default=str) + str(raised.value)
    assert _KEY[:8] not in shown and "ppppp" in shown


def test_a_failed_bundles_reason_over_the_read_bound_is_not_quoted_in_part(monkeypatch):
    from src.catalog import qualification_merge as qm

    monkeypatch.setattr(qm, "_SIDECAR_READ_BYTES", 100)
    data = _bundle(qm.BUNDLE_MEMBER + ".error.txt", b"q" * 500)
    with pytest.raises(qm.MergeInputError) as raised:
        qm.rows_from_bundle_bytes(data, "bundle.zip")
    shown = json.dumps(getattr(raised.value, "__dict__", {}), default=str) + str(raised.value)
    assert "qqqq" not in shown and "too long to quote" in shown


def test_the_standalone_session_forensics_route_scrubs_what_it_serves(monkeypatch):
    from src.api.diagnostics import system as route
    from src.monitoring import forensics

    monkeypatch.setattr(forensics, "session_forensics", lambda: {"kernel": {"lines": [f"oom killed python (cmd {_KEY})"]}, "ok": True})
    monkeypatch.setattr(forensics, "render_text", lambda payload: f"report: {json.dumps(payload)} and the renderer adds {_KEY} itself")
    served = route.session_forensics_report(download=False)
    assert _KEY not in json.dumps(served) and served["ok"] is True
    text = route.session_forensics_report(download=True).body.decode()
    assert _KEY not in text


def test_a_line_that_is_not_valid_utf8_is_withheld_whole_with_its_size_not_repaired(tmp_path):
    src = tmp_path / "bin.jsonl"
    src.write_bytes(b"ok\n" + b"\xff\xfe bad " + _KEY.encode() + b"\nlast\n")
    dst = tmp_path / "bin.out"
    assert ss.scrubbed_copy(src, dst) == 1
    got = dst.read_bytes()
    assert _KEY.encode() not in got and b"\xff" not in got
    assert got.startswith(b"ok\n") and got.endswith(b"last\n") and b"is not valid UTF-8" in got
    assert got.count(b"\n") == 3, "the line count stays as it was"


def test_a_line_of_the_bound_followed_by_its_line_ending_counts_as_too_long(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "_COPY_LINE_BYTES", 100)
    src = tmp_path / "b.jsonl"
    src.write_text("y" * 100 + "\n" + "z" * 98 + "\n", encoding="utf-8")
    dst = tmp_path / "b.out"
    ss.scrubbed_copy(src, dst)
    text = dst.read_text(encoding="utf-8")
    assert "y" * 99 not in text and "a line of 101 bytes is not copied" in text and "z" * 98 in text


def test_a_log_that_cannot_be_checked_is_withheld_not_copied_raw(tmp_path, monkeypatch):
    """When what the process holds cannot be read, ``scrubbed`` withholds: the copy never holds the raw line."""
    monkeypatch.setattr(connect, "_passphrase", None)
    monkeypatch.setattr(ss, "held_passphrases", lambda: None)
    ss.forget_held()
    src = _log(tmp_path)
    dst = tmp_path / "w.out"
    ss.scrubbed_copy(src, dst)
    got = dst.read_text(encoding="utf-8")
    assert "plain line" not in got and "withheld" in got


def test_a_restore_of_a_log_nothing_can_check_appends_one_withheld_line_not_n(tmp_path, monkeypatch):
    from src.backup.merge import merge_side_files
    from tests.backup_helper import staged_artifact

    monkeypatch.setattr(ss, "held_passphrases", lambda: None)
    ss.forget_held()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "live"))
    staging = tmp_path / "staging"
    (staging / "logs").mkdir(parents=True)
    _log(staging / "logs")
    staged = staged_artifact(staging, members=[{"name": "logs/app_errors.jsonl", "role": "logs"}], origin_fingerprint="ab" * 32)
    report = merge_side_files(staged)
    assert report["logs"]["app_errors.jsonl"]["appended"] == 1


def test_the_release_run_report_is_scrubbed_as_it_is_written(tmp_path, monkeypatch):
    """A phase result is carried into the report verbatim; the report as a whole passes the scrub, taking out what the process holds."""
    from src.monitoring import release_run as rr

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    run = rr._Run(rr.RunParams(str(tmp_path / "dest"), "the-runs-own-pass-88"))
    run.phases.append({"name": "collect", "status": "ok", "result": {"session_forensics": {"kernel": [f"killed (cmd {_KEY})"]}}})
    path = rr._write_report(run, interim=False)
    text = path.read_text(encoding="utf-8")
    assert _KEY not in text and "killed (cmd" in text


def test_the_release_runs_session_forensics_block_is_scrubbed_where_it_enters(tmp_path, monkeypatch):
    import contextlib as _cl

    import src.api.wiki_lane as wl
    import src.catalog.qualification_integrity as qi
    import src.database.session as dbs
    import src.monitoring.expedition as ex
    import src.monitoring.forensics as fo
    import src.monitoring.p0_validation as p0
    import src.monitoring.soak_window as sw
    from src.monitoring import release_run as rr

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(sw, "soak_window", lambda db, bar_hours: {"window": {"hours": 72.1, "reaches_bar": True}, "unmeasured": []})
    monkeypatch.setattr(qi, "qualification_integrity_report", lambda db: {"measured": True})
    monkeypatch.setattr(p0, "_check_collector", lambda: {"verdict": "pass"})
    monkeypatch.setattr(dbs, "session_scope", lambda: _cl.nullcontext(None))
    monkeypatch.setattr(wl, "lane_counters_route", lambda window_days: {"measured": False})
    monkeypatch.setattr(ex, "digest", lambda: {})
    monkeypatch.setattr(fo, "session_forensics", lambda: {"kernel": [f"oom (cmd {_KEY})", "killed with run-pass-planted-77 in argv"]})
    monkeypatch.setattr(rr, "_network_state", lambda: {})

    class _Ctx:
        stopping = False

        def set_progress(self, **kw):
            pass

    run = rr._Run(rr.RunParams(str(tmp_path / "d"), "run-pass-planted-77", online_probes=False))
    out = rr._collect(_Ctx(), run)
    shown = json.dumps(out["session_forensics"])
    assert _KEY not in shown and "run-pass-planted-77" not in shown and "oom (cmd" in shown, "the held passphrase AND the run's own are taken out"


def test_a_scheduler_run_report_is_scrubbed_where_it_is_recorded_and_where_it_is_read(monkeypatch, tmp_path):
    """The run's result carries free text; record_run takes the held passphrase out as it writes, and recent_runs checks a line an older
    build left raw."""
    from src.scheduler import runlog

    monkeypatch.setattr(runlog, "_runs_path", lambda: tmp_path / "scheduler_runs.jsonl")
    runlog.record_run({"ok": True, "result": {"failures": [f"fetch failed for https://x/?k={_KEY}"]}, "error": None})
    raw = (tmp_path / "scheduler_runs.jsonl").read_text(encoding="utf-8")
    assert _KEY not in raw and "fetch failed" in raw, "the line is kept, the key is not"
    with (tmp_path / "scheduler_runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ok": False, "result": {"note": f"older build wrote {_KEY}"}}) + "\n")
    rows = runlog.recent_runs()
    assert len(rows) == 2 and _KEY not in json.dumps(rows)
    assert any("older build wrote" in json.dumps(r) for r in rows)


def test_a_skipped_ledger_note_is_checked_whole_before_it_is_cut():
    """The note is cut at 200 characters: a key that straddles the cut must not leave its first half behind."""
    from src.monitoring import activity_ledger as al

    reason = "x" * (200 - len(_KEY) // 2) + _KEY + " tail"
    e = al.build_entry("lane:world_discovery", {"enabled": True, "skipped": reason})
    note = e.as_record()["note"]
    assert _KEY not in note and _KEY[: len(_KEY) // 2] not in note, "the first half of a cut key stays too"
    assert len(note) <= 200 and note.startswith("x")


def test_a_field_test_step_that_fails_does_not_record_the_key(monkeypatch, tmp_path):
    from src.monitoring import field_test as ft

    monkeypatch.setattr(ft, "_log_path", lambda: tmp_path / "field_test.jsonl")

    def boom():
        raise RuntimeError(f"driver said PRAGMA key = '{_KEY}'")

    ft._run_step("probe", boom)
    raw = (tmp_path / "field_test.jsonl").read_text(encoding="utf-8")
    assert _KEY not in raw and "probe" in raw and "false" in raw


def test_the_single_file_backup_carries_older_import_reports_scrubbed(tmp_path, monkeypatch):
    """``import_reports/*.json`` ride the single-file backup; a report an older build wrote holds an engine's error text. MUTATION TARGET:
    the ``scrubbed_copy`` of the reports in ``_collect_members``."""
    from src.backup import artifact

    monkeypatch.setattr(artifact, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("src.backup.sqlite_backup.live_db_path", lambda: tmp_path / "live.db")
    monkeypatch.setattr(artifact, "snapshot_sqlite", lambda _src, dest: Path(dest).write_bytes(b""))
    d = tmp_path / "import_reports"
    d.mkdir()
    old = {"kind": "restore", "errors": [{"msg": f"near '{_KEY}' syntax", "esc": json.dumps(_KEY)[1:-1]}]}
    (d / "restore-20260101T000000Z-ab.json").write_text(json.dumps(old, indent=2), encoding="utf-8")
    out = tmp_path / "stage"
    out.mkdir()
    members = [m for m in artifact._collect_members(False, out) if m.role == "import_reports"]
    assert [m.name for m in members] == ["import_reports/restore-20260101T000000Z-ab.json"]
    staged = members[0].path.read_text(encoding="utf-8")
    assert _KEY not in staged and json.loads(staged)["kind"] == "restore"
    assert _KEY in (d / "restore-20260101T000000Z-ab.json").read_text(encoding="utf-8"), "the live report is not rewritten"
