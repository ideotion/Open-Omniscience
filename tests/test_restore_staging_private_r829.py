"""R829 (B): a restore's staging is a fresh private folder (0700) whose files are owner-only (0600), and the boot sweep
removes only a real folder of ours: never a link, a junction, a file or another user's folder named like ours.

The staging holds the decrypted members and, until R829 (A) keys it, a plaintext copy of the incoming corpus. Before
R829 it was made with ``mkdir`` and its files with the umask's mode (typically 0755 and 0644), so only the data folder's
own best-effort 0700 kept other local users out of it, and the sweep followed ``is_dir()`` through a link."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import stat
import zipfile
from pathlib import Path

import pytest

from src.backup import stream_backup as sb
from src.backup.stream_backup import (
    CorpusSource,
    MemberFile,
    _no_freeze,
    read_stream_backup,
    write_stream_backup,
)
from tests.os_scope import scope_os

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX modes and owners")


def _mode(p: Path) -> int:
    return stat.S_IMODE(os.lstat(p).st_mode)


def _assert_private_tree(staging: Path) -> None:
    assert _mode(staging) == 0o700, oct(_mode(staging))
    seen = 0
    for top, dirs, files in os.walk(staging):
        for d in dirs:
            assert _mode(Path(top, d)) & 0o077 == 0, (d, oct(_mode(Path(top, d))))
        for f in files:
            if top == str(staging) and f == ".owner.json":
                continue  # the owner marker: a process id and its start time, nothing from the backup (inside the 0700 folder)
            seen += 1
            assert _mode(Path(top, f)) & 0o077 == 0, (f, oct(_mode(Path(top, f))))
    assert seen, "the staging held no file to check"


def _corpus(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);"
    )
    con.executemany("INSERT INTO articles(hash, content) VALUES(?,?)", [(f"h{i}", "x" * 500) for i in range(50)])
    con.commit()
    con.close()


@pytest.fixture
def permissive_umask():
    old = os.umask(0o022)  # the common default: without R829, folders 0755 and files 0644
    try:
        yield
    finally:
        os.umask(old)


def test_make_restore_staging_is_a_new_private_folder(tmp_path, permissive_umask):
    a = sb.make_restore_staging(tmp_path)
    b = sb.make_restore_staging(tmp_path)
    assert a != b and a.parent == tmp_path and b.parent == tmp_path
    assert a.name.startswith(".restore-") and b.name.startswith(".restore-")
    if os.name != "nt":
        assert _mode(a) == 0o700 and _mode(b) == 0o700
    g = sb.make_restore_staging(tmp_path / "missing" / "root", prefix=".restore-group-")
    assert g.name.startswith(".restore-group-") and g.is_dir()


@posix_only
def test_a_volume_set_restore_stages_owner_only(tmp_path, permissive_umask):
    corpus = tmp_path / "corpus.db"
    _corpus(corpus)
    settings = tmp_path / "app_settings.json"
    settings.write_text('{"k": 1}', encoding="utf-8")
    log = tmp_path / "x.log"
    log.write_text("line", encoding="utf-8")
    dest = tmp_path / "dest"
    write_stream_backup(
        dest, "pw",
        corpus_source=CorpusSource(path=corpus, member_name="corpus.db", encrypted=False, freeze=_no_freeze),
        side_members=[MemberFile("app_settings.json", "state", settings), MemberFile("logs/x.log", "logs", log)],
        volume_size=65536,
    )
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes()[:16] == b"SQLite format 3\x00"
    _assert_private_tree(staged.staging_dir)


def _sqlcipher_available() -> bool:
    try:
        import sqlcipher3  # noqa: F401
    except ImportError:
        return False
    return True


@posix_only
@pytest.mark.skipif(not _sqlcipher_available(), reason="sqlcipher3 not installed")
def test_the_plaintext_export_of_an_encrypted_corpus_is_owner_only(tmp_path, permissive_umask):
    from src.database.connect import connect

    corpus = tmp_path / "corpus.db"
    con = connect(corpus, key="corpus-secret")
    con.executescript("CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT, content TEXT);")
    con.executemany("INSERT INTO articles(hash, content) VALUES(?,?)", [(f"h{i}", "y" * 500) for i in range(40)])
    con.commit()
    con.close()
    dest = tmp_path / "dest"
    write_stream_backup(
        dest, "backup-pw",
        corpus_source=CorpusSource(
            path=corpus, member_name="corpus.db.sqlcipher", encrypted=True, freeze=_no_freeze, facts_key="corpus-secret"
        ),
        side_members=[], volume_size=65536,
    )
    staged = read_stream_backup(dest, "backup-pw", staging_root=tmp_path / "st", corpus_passphrase="corpus-secret")
    assert staged.corpus_path.read_bytes()[:16] == b"SQLite format 3\x00"  # still plaintext until R829 (A)
    assert _mode(staged.corpus_path) == 0o600
    _assert_private_tree(staged.staging_dir)


def _zip_artifact() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"manifest": {"backup_schema": "oo-backup-2", "members": []}}))
        zf.writestr("corpus.db", b"SQLite format 3\x00" + b"\x00" * 100)
        zf.writestr("keys/", b"")
        zf.writestr("logs/a.log", b"x")
    return buf.getvalue()


@posix_only
@pytest.mark.parametrize("kind", ["bare", "zip"])
def test_an_uploaded_artifact_stages_owner_only(tmp_path, permissive_umask, monkeypatch, kind):
    from src.backup import artifact

    seen: dict[str, Path] = {}
    real = artifact._finalize_staged

    def _spy(staging, *a, **k):
        seen["staging"] = staging
        try:
            _assert_private_tree(staging)
        except AssertionError as exc:  # kept, not raised: the reader below may turn any exception into a refusal
            seen["problem"] = exc
        return real(staging, *a, **k)

    monkeypatch.setattr(artifact, "_finalize_staged", _spy)
    if kind == "bare":
        con = sqlite3.connect(tmp_path / "bare.db")
        con.execute("CREATE TABLE t(x)")
        con.commit()
        con.close()
        staged = artifact.read_artifact((tmp_path / "bare.db").read_bytes(), staging_root=tmp_path / "st")
        _assert_private_tree(staged.staging_dir)
        assert _mode(staged.corpus_path) == 0o600
        return
    # The made-up manifest may be refused after extraction; the modes were checked first, by the spy.
    with contextlib.suppress(Exception):
        artifact.read_artifact(_zip_artifact(), staging_root=tmp_path / "st")
    assert "staging" in seen, "the zip was never extracted"
    assert "problem" not in seen, seen.get("problem")


def test_the_sweep_never_follows_or_removes_a_link_named_like_a_staging(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "precious.txt").write_text("keep", encoding="utf-8")
    old = 0  # every leftover is old enough to sweep
    link = tmp_path / ".restore-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot make a symbolic link here")
    os.utime(link, (old, old), follow_symlinks=False)
    os.utime(target / "precious.txt", (old, old))
    os.utime(target, (old, old))
    assert sb.sweep_stale_backup_temps(tmp_path) == 0
    assert link.is_symlink() and (target / "precious.txt").read_text(encoding="utf-8") == "keep"


def test_the_sweep_leaves_a_file_named_like_a_staging(tmp_path):
    f = tmp_path / ".restore-file"
    f.write_text("not ours to judge", encoding="utf-8")
    os.utime(f, (0, 0))
    assert sb.sweep_stale_backup_temps(tmp_path) == 0
    assert f.exists()


@posix_only
def test_the_sweep_leaves_another_users_staging(tmp_path, monkeypatch):
    d = sb.make_restore_staging(tmp_path)
    (d / "corpus.db").write_bytes(b"x")
    os.utime(d / "corpus.db", (0, 0))
    os.utime(d, (0, 0))
    me = os.getuid()
    with monkeypatch.context() as mp:
        scope_os(mp, sb, getuid=lambda: me + 1)  # as the sweep sees it, the folder now belongs to "someone else"
        assert sb.sweep_stale_backup_temps(tmp_path) == 0
    assert d.is_dir()
    assert sb.sweep_stale_backup_temps(tmp_path) == 1  # our own old leftover goes
    assert not d.exists()


def test_the_sweep_does_not_enter_a_link_inside_our_own_staging(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "precious.txt").write_text("keep", encoding="utf-8")
    d = sb.make_restore_staging(tmp_path)
    try:
        (d / "inner").symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot make a symbolic link here")
    (d / "corpus.db").write_bytes(b"x")
    for p in (d / "corpus.db", d):
        os.utime(p, (0, 0))
    os.utime(d / "inner", (0, 0), follow_symlinks=False)
    assert sb.sweep_stale_backup_temps(tmp_path) == 1
    assert not d.exists()
    assert (target / "precious.txt").read_text(encoding="utf-8") == "keep"


def test_every_staging_maker_goes_through_the_private_helper():
    root = Path(__file__).resolve().parents[1]
    for rel in ("src/backup/stream_backup.py", "src/backup/artifact.py", "src/backup/import_queue.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert 'f".restore-{' not in text and 'f".restore-group-{' not in text, rel
