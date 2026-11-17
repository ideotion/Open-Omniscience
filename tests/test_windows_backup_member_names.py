"""A backup an older build made on Windows still restores and imports everywhere (row 109).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before row 109 the backup writers named a member from ``str(path.relative_to(base))``, so on Windows the annotations, import reports,
bulletin editions and keys of a backup were named ``import_reports\\restore-....json`` in its signed manifest. The single-file artifact's
zip entries were spelled with "/" all the same (``zipfile`` converts ``os.sep``), so read back on Linux or macOS each such member was
"missing from archive"; the volume set refused the whole backup ("unsafe member path": its guard refused every backslash); and a bulletin
or import report was refused even on Windows, where ``str(Path(name))`` never starts with "bulletin/editions". The writers now spell
names with "/" (``as_posix``) and the readers read a "\\" as "/" before any guard or join (``artifact.member_name``/``member_path``).

These tests make such a backup the way the old build did, SIGNED as it was (never a manifest edited afterwards, which would test the
signature refusal instead), and restore it through the real readers and the real side-file merge.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from src.backup import artifact as art
from src.backup import merge
from src.backup.stream_backup import (
    CorpusSource,
    MemberFile,
    _no_freeze,
    _require_safe_member_name,
    read_stream_backup,
    write_stream_backup,
)
from src.backup.volumes import VolumeError

_REPORT = "restore-20260101T000000Z-ab.json"
_EDITION = "20260101-OOS-weekly-e1.json"


def _corpus(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE)")
    con.commit()
    con.close()
    return path


def _side_files(base: Path) -> dict[str, bytes]:
    files = {
        f"import_reports/{_REPORT}": json.dumps({"kind": "restore", "outcome": "ok"}).encode(),
        f"bulletin/editions/{_EDITION}": json.dumps({"edition": "e1"}).encode(),
    }
    for rel, data in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return files


def _windows_names(members):
    """What the old build wrote on Windows: str() of a relative path, so every "/" a "\\"."""
    for m in members:
        m.name = m.name.replace("/", "\\")
    return members


def _assert_restored(staged, monkeypatch, tmp_path, files: dict[str, bytes]) -> None:
    assert not staged.hash_failures, staged.hash_failures
    names = {n for role in ("import_reports", "bulletin") for n, _p in staged.member_paths(role)}
    assert names == set(files), "member_paths gives each name spelled with '/'"
    target = tmp_path / "restored-into"
    target.mkdir()
    monkeypatch.setattr(merge, "data_dir", lambda: target)
    report = merge.merge_side_files(staged)
    for rel, data in files.items():
        # the single-file writer re-serialises a report after scrubbing it, so compare what it says, not its bytes
        assert json.loads((target / rel).read_bytes()) == json.loads(data), (
            f"{rel} was not restored where it belongs ({report})"
        )


def test_a_single_file_backup_made_on_windows_by_the_old_build_restores(tmp_path, monkeypatch):
    base = tmp_path / "made-on-windows"
    files = _side_files(base)
    monkeypatch.setattr(art, "data_dir", lambda: base)
    corpus = _corpus(tmp_path / "corpus.db")
    monkeypatch.setattr("src.backup.sqlite_backup.live_db_path", lambda: corpus)
    real_collect = art._collect_members
    monkeypatch.setattr(
        art, "_collect_members", lambda *a, **k: _windows_names(real_collect(*a, **k))
    )
    dest = tmp_path / "old.oobak"
    art.write_backup_v2(dest, passphrase=None)
    monkeypatch.undo()

    # zipfile on Windows wrote the entries with "/", whatever the manifest said: do what it did, leaving the signed manifest as written
    out = io.BytesIO()
    with zipfile.ZipFile(dest) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info.filename.replace("\\", "/"), zin.read(info))
    manifest = json.loads(zipfile.ZipFile(out).read("manifest.json"))["manifest"]
    assert {f"import_reports\\{_REPORT}", f"bulletin\\editions\\{_EDITION}"} <= {
        m["name"] for m in manifest["members"]
    }

    staged = art.read_artifact(out.getvalue(), staging_root=tmp_path)
    try:
        assert staged.signature_state == "verified", "the manifest is the one the old build signed"
        _assert_restored(staged, monkeypatch, tmp_path, files)
    finally:
        art.cleanup_staging(staged)


def test_a_volume_backup_made_on_windows_by_the_old_build_restores(tmp_path, monkeypatch):
    base = tmp_path / "made-on-windows"
    files = _side_files(base)
    corpus = _corpus(tmp_path / "corpus.db")
    roles = {"import_reports": "import_reports", "bulletin": "bulletin"}
    side = [
        MemberFile(rel.replace("/", "\\"), roles[rel.split("/", 1)[0]], base / rel) for rel in files
    ]
    dest = tmp_path / "set"
    write_stream_backup(
        dest,
        "pw",
        corpus_source=CorpusSource(
            path=corpus, member_name="corpus.db", encrypted=False, freeze=_no_freeze
        ),
        side_members=side,
        volume_size=65536,
    )
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "stage")
    try:
        assert staged.signature_state == "verified"
        _assert_restored(staged, monkeypatch, tmp_path, files)
    finally:
        art.cleanup_staging(staged)


@pytest.mark.parametrize(
    "name",
    [
        "..\\..\\x",
        "keys\\..\\..\\x",
        "C:\\windows\\x",
        "\\\\server\\share\\x",
        "/etc/x",
        "",
        # a drive in a LATER segment: on Windows a join re-reads "C:evil" as a path on drive C:, so it is refused wherever it sits
        "a/C:evil",
        "a\\C:evil",
        "x/C:..\\..\\Users\\Public\\evil.dll",
        "a/b:ads",
        "a/\\\\?\\C:\\x",
        "a/b\0",
    ],
)
def test_a_backslash_never_opens_a_way_out(tmp_path, name):
    """The "\\" is read as "/" BEFORE the guard, so it cannot hide a '..', a drive or an absolute path from it."""
    assert art.member_path(tmp_path, name) is None
    with pytest.raises(VolumeError):
        _require_safe_member_name(name)


def test_the_writers_spell_every_member_name_with_a_slash():
    """The cause, at the source: no writer builds a member name from ``str()`` of a path."""
    root = Path(__file__).resolve().parents[1] / "src" / "backup"
    for name in ("artifact.py", "stream_backup.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "str(p.relative_to(base))" not in text, (
            f"{name} names a member with the OS's separator"
        )


def test_two_spellings_of_one_member_are_refused():
    """ "a\\b" and "a/b" are one staged file: a volume manifest naming both would overwrite what the first was checked as."""
    from src.backup.stream_backup import _require_distinct_member_names

    with pytest.raises(VolumeError):
        _require_distinct_member_names({"members": [{"name": "keys/a.key"}, {"name": "keys\\a.key"}]})
    _require_distinct_member_names({"members": [{"name": "keys/a.key"}, {"name": "keys/b.key"}]})


def test_a_log_member_named_like_a_drive_is_refused_not_appended():
    """The logs reader keeps only the base name; on Windows "C:x" joined to the data dir is a path on drive C:."""
    from src.backup.artifact import member_segment_is_safe

    assert not member_segment_is_safe("C:x")
    assert member_segment_is_safe("app.log") and member_segment_is_safe("ab:c")
