"""R686: a volume restore never writes decrypted data into the backup's own folder, a manifest that lists a
volume twice is refused, and what a restore writes is bounded by the plaintext size the manifest declares.

Each test fails on the code before R686: the legacy reassembly decrypted every volume to ``<volume>.plain``
beside it (a crash left plaintext on the user's backup drive), read a repeated volume again, and wrote
whatever the volumes held; the member-streamed reader did the last two as well."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.backup import folder_backup
from src.backup.import_scan import leftover_plaintext, scan_import_folder
from src.backup.volumes import (
    MANIFEST_NAME,
    VolumeError,
    read_volume_set,
    remove_leftover_plaintext,
    write_volume_set,
)

ROOT = Path(__file__).resolve().parents[1]
PW = "pw-r686"
SECRET = b"THE-PLAINTEXT-MARKER-" * 4000  # about 84 KB, several volumes at 16 KiB


def _legacy_set(tmp: Path) -> Path:
    src = tmp / "archive.bin"
    src.write_bytes(SECRET)
    out = tmp / "backup-drive"
    write_volume_set(src, out, PW, volume_size=16 * 1024)
    src.unlink()
    return out


def _rewrite(out: Path, edit) -> None:
    m = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    edit(m)
    (out / MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")


def _plaintext_files(folder: Path) -> list[str]:
    return sorted(
        p.name
        for p in folder.rglob("*")
        if p.is_file() and b"THE-PLAINTEXT-MARKER" in p.read_bytes()
    )


def test_a_restore_killed_midway_leaves_no_plaintext_beside_the_backup(tmp_path):
    out = _legacy_set(tmp_path)
    staging = tmp_path / "data" / ".restore-test"
    staging.mkdir(parents=True)
    # A hard crash: the process dies right after the first volume is decrypted, so no finally runs.
    script = f"""
import os, sys
sys.path.insert(0, {str(ROOT)!r})
import src.backup.volumes as v
real = v.decrypt_file
def dying(src, dst, pw):
    real(src, dst, pw)
    os._exit(7)
v.decrypt_file = dying
v.read_volume_set({str(out)!r}, {PW!r}, {str(staging / "_reassembled.zip")!r})
"""
    res = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "OO_DATA_DIR": str(tmp_path / "data")},
    )
    assert res.returncode == 7, res.stderr
    assert _plaintext_files(out) == [], "nothing decrypted is left on the backup drive"
    assert not list(out.glob("*.plain"))
    assert _plaintext_files(staging), (
        "the working copy was in the restore's own staging, which the janitor removes"
    )


def test_a_completed_restore_leaves_no_working_copy_anywhere(tmp_path):
    out = _legacy_set(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir()
    read_volume_set(out, PW, staging / "_reassembled.zip")
    assert (staging / "_reassembled.zip").read_bytes() == SECRET
    assert sorted(p.name for p in staging.iterdir()) == ["_reassembled.zip"]
    assert _plaintext_files(out) == []


def test_a_manifest_that_lists_a_volume_twice_is_refused(tmp_path):
    out = _legacy_set(tmp_path)
    _rewrite(out, lambda m: m["volumes"].append(dict(m["volumes"][0])))
    (tmp_path / "st").mkdir()
    with pytest.raises(VolumeError, match="more than once"):
        read_volume_set(out, PW, tmp_path / "st" / "_reassembled.zip")
    assert list((tmp_path / "st").iterdir()) == []


def test_what_is_written_is_bounded_by_the_declared_plaintext_size(tmp_path):
    out = _legacy_set(tmp_path)
    _rewrite(out, lambda m: m.__setitem__("plaintext_bytes", 1000))
    (tmp_path / "st").mkdir()
    with pytest.raises(VolumeError, match="more data than its manifest declares"):
        read_volume_set(out, PW, tmp_path / "st" / "_reassembled.zip")
    assert list((tmp_path / "st").iterdir()) == [], (
        "the partial archive and the working copy are gone"
    )


def test_the_reassembly_preflights_what_it_will_really_write(tmp_path, monkeypatch):
    out = _legacy_set(tmp_path)
    (tmp_path / "st").mkdir()
    monkeypatch.setattr(folder_backup, "free_bytes", lambda _p: 10 * 1024)
    from src.backup.artifact import BackupSpaceError

    with pytest.raises(BackupSpaceError):
        read_volume_set(out, PW, tmp_path / "st" / "_reassembled.zip")
    assert list((tmp_path / "st").iterdir()) == []


# ------------------------------------------------------------------ the member-streamed set (oo-volumes-2)
def _stream_set(tmp: Path) -> Path:
    from tests.test_stream_backup import _backup, _make_corpus

    corpus = tmp / "corpus.db"
    _make_corpus(corpus, rows=60)
    dest = tmp / "stream-drive"
    _backup(tmp, dest, corpus)
    return dest


def test_a_streamed_set_that_lists_a_volume_twice_is_refused(tmp_path):
    dest = _stream_set(tmp_path)

    def dup(m):
        corpus = next(mm for mm in m["members"] if mm["name"] == "corpus.db")
        corpus["volumes"].append(corpus["volumes"][0])

    _rewrite(dest, dup)
    from src.backup.stream_backup import read_stream_backup

    with pytest.raises(VolumeError, match="more than once"):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")


def test_a_streamed_member_is_bounded_by_its_declared_plaintext_size(tmp_path):
    dest = _stream_set(tmp_path)

    def shrink(m):
        m.pop(
            "signature", None
        )  # anyone can strip or re-sign: the bound must hold for an unsigned set too
        corpus = next(mm for mm in m["members"] if mm["name"] == "corpus.db")
        corpus["plaintext_bytes"] = 100

    _rewrite(dest, shrink)
    from src.backup.stream_backup import read_stream_backup

    with pytest.raises(VolumeError, match="more data than the backup's manifest declares"):
        read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert not list((tmp_path / "st").glob(".restore-*")), "the staging dir is removed"


# ------------------------------------------------------------------ copies an earlier interrupted restore left
def _with_leftovers(tmp: Path) -> Path:
    out = _legacy_set(tmp)
    m = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    first = m["volumes"][0]["name"]
    (out / (first + ".plain")).write_bytes(SECRET[:100])
    (out / "my-notes.plain").write_text("the user's own file", encoding="utf-8")
    return out


def test_the_scan_names_only_the_copies_the_manifest_explains(tmp_path):
    out = _with_leftovers(tmp_path)
    first = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][0]["name"]
    assert leftover_plaintext(out) == [first + ".plain"]
    found = scan_import_folder(tmp_path)["found"]["corpus"]
    assert found[0]["leftover_plaintext"] == [first + ".plain"]
    assert (out / (first + ".plain")).exists(), "a scan deletes nothing"


def test_removal_takes_only_named_leftovers_and_never_anything_else(tmp_path):
    out = _with_leftovers(tmp_path)
    first = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][0]["name"]
    removed = remove_leftover_plaintext(
        out, [first + ".plain", "my-notes.plain", "../archive.bin", first]
    )
    assert removed == [first + ".plain"]
    assert (out / "my-notes.plain").exists() and (out / first).exists()
    assert leftover_plaintext(out) == []


def test_the_removal_endpoint_and_the_page_offer_it_only_on_the_operators_yes(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    out = _with_leftovers(tmp_path)
    first = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))["volumes"][0]["name"]
    with TestClient(app) as c:
        r = c.post(
            "/api/backup/import-scan/remove-leftover-plaintext",
            json={"path": str(out), "names": [first + ".plain", "my-notes.plain"]},
        )
    assert r.status_code == 200 and r.json() == {"removed": [first + ".plain"]}
    js = (ROOT / "src/static/app-backup.js").read_text("utf-8")
    body = js[js.index("function _uxImLeftoverPlaintext(") :]
    body = body[: body.index("\n    }\n")]
    assert "confirm(" in body and body.index("confirm(") < body.index(
        "remove-leftover-plaintext"
    ), "the yes comes first"
