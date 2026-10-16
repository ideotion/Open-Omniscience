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
    monkeypatch.setattr(forensics, "render_text", lambda payload: "report: " + json.dumps(payload))
    served = route.session_forensics_report(download=False)
    assert _KEY not in json.dumps(served) and served["ok"] is True
    text = route.session_forensics_report(download=True).body.decode()
    assert _KEY not in text
