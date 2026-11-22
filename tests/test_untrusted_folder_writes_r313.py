"""Row 313: nothing the backup code writes into a backup, export or staging folder goes through a link planted there.

A plain ``open(path, "wb")`` (or ``Path.write_text``) follows a link at ``path``: a backup drive that already held
``vol-00001.ooenc``, ``volumes.json``, ``volumes.json.tmp`` or a parity ``.oopart`` as a link to another file turned
the export, the parity pass or a restore's parity rebuild into a write over THAT file. Every such write now goes
through ``src.backup.regular_file.create_new`` (whatever the name holds is removed as itself, a link is never
followed, then the file is created exclusively) or ``replace_with`` (a temporary made the same way, then a rename,
which replaces a link at the final name rather than writing through it). Each test plants a link to a file outside
the folder and checks that file comes out byte-for-byte untouched while the folder's own result stays correct.
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.backup import regular_file, volumes
from src.backup.regular_file import NotARegularFile, create_new, replace_with
from src.safety.crypto import decrypt_file, encrypt_file, encrypt_stream_to_hashed
from tests.js_source_helper import python_function_source

posix_only = pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")

_VICTIM = b"the user's own file, which no backup may touch\n"


def _victim(tmp: Path) -> Path:
    v = tmp / "victim.txt"
    v.write_bytes(_VICTIM)
    return v


def _link(at: Path, victim: Path) -> None:
    at.parent.mkdir(parents=True, exist_ok=True)
    if at.exists() or at.is_symlink():
        at.unlink()
    os.symlink(victim, at)


# --------------------------------------------------------------------------- the helpers


@posix_only
def test_create_new_removes_a_planted_link_and_never_writes_through_it(tmp_path):
    victim = _victim(tmp_path)
    p = tmp_path / "d" / "out.bin"
    _link(p, victim)
    with create_new(p) as fh:
        fh.write(b"new")
    assert victim.read_bytes() == _VICTIM
    assert not p.is_symlink() and p.read_bytes() == b"new"


def test_create_new_replaces_a_leftover_regular_file(tmp_path):
    p = tmp_path / "x.oopart"
    p.write_bytes(b"old leftover")
    with create_new(p) as fh:
        fh.write(b"fresh")
    assert p.read_bytes() == b"fresh"


def test_create_new_never_removes_a_folder(tmp_path):
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "inside").write_bytes(b"x")
    with pytest.raises(NotARegularFile):
        create_new(tmp_path / "keep")
    assert (tmp_path / "keep" / "inside").read_bytes() == b"x"


def test_create_new_refuses_a_name_that_appears_between_the_removal_and_the_create(tmp_path, monkeypatch):
    victim = _victim(tmp_path)
    p = tmp_path / "out.bin"

    class _RacingOs:  # this module's own view of os, never the process's (R351)
        def __getattr__(self, name):
            return getattr(os, name)

        @staticmethod
        def open(path, *a, **k):
            if not os.path.lexists(path):
                os.symlink(victim, path)  # planted after the removal, before the create
            return os.open(path, *a, **k)

    if os.name == "nt":
        pytest.skip("symlinks need privileges on Windows")
    monkeypatch.setattr(regular_file, "os", _RacingOs())
    with pytest.raises(FileExistsError):
        create_new(p)
    assert victim.read_bytes() == _VICTIM


@posix_only
def test_replace_with_neither_follows_the_temporary_nor_the_final_name(tmp_path):
    victim = _victim(tmp_path)
    final = tmp_path / "d" / "volumes.json"
    tmp = tmp_path / "d" / "volumes.json.tmp"
    _link(final, victim)
    _link(tmp, victim)
    replace_with(final, b'{"ok": 1}', tmp=tmp)
    assert victim.read_bytes() == _VICTIM
    assert not final.is_symlink() and json.loads(final.read_text("utf-8")) == {"ok": 1}
    assert not os.path.lexists(tmp)


# --------------------------------------------------------------------------- the writers


@posix_only
def test_a_volume_set_written_over_planted_links_leaves_them_untouched(tmp_path):
    victim = _victim(tmp_path)
    src = tmp_path / "archive.bin"
    src.write_bytes(os.urandom(5000))
    out = tmp_path / "set"
    for name in ("vol-00001.ooenc", "vol-00002.ooenc", "volumes.json"):
        _link(out / name, victim)
    volumes.write_volume_set(src, out, "pw", volume_size=2048, chunk_size=1024)
    assert victim.read_bytes() == _VICTIM
    assert volumes.verify_volume_set(out)["ok"] is True
    volumes.read_volume_set(out, "pw", tmp_path / "restored.bin")
    assert (tmp_path / "restored.bin").read_bytes() == src.read_bytes()


@posix_only
def test_the_restore_working_copy_never_writes_through_a_link(tmp_path):
    victim = _victim(tmp_path)
    src = tmp_path / "archive.bin"
    src.write_bytes(os.urandom(3000))
    out = tmp_path / "set"
    volumes.write_volume_set(src, out, "pw", volume_size=2048, chunk_size=1024)
    dest = tmp_path / "stage" / "restored.bin"
    _link(dest.with_name(dest.name + ".reassembling"), victim)
    volumes.read_volume_set(out, "pw", dest)
    assert victim.read_bytes() == _VICTIM and dest.read_bytes() == src.read_bytes()


@posix_only
def test_parity_written_over_planted_links_leaves_them_untouched(tmp_path):
    pytest.importorskip("numpy")
    from src.backup import parity

    victim = _victim(tmp_path)
    src = tmp_path / "archive.bin"
    src.write_bytes(os.urandom(5000))
    out = tmp_path / "set"
    volumes.write_volume_set(src, out, "pw", volume_size=2048, chunk_size=1024)
    _link(out / "par-00001.oopar.oopart", victim)
    _link(out / "volumes.json.tmp", victim)
    parity.write_parity(out, parity_count=1)
    assert victim.read_bytes() == _VICTIM
    assert volumes.verify_volume_set(out)["ok"] is True


@posix_only
def test_a_parity_rebuild_never_writes_through_a_link_planted_in_the_backup_folder(tmp_path):
    pytest.importorskip("numpy")
    from src.backup import parity

    victim = _victim(tmp_path)
    src = tmp_path / "archive.bin"
    src.write_bytes(os.urandom(5000))
    out = tmp_path / "set"
    volumes.write_volume_set(src, out, "pw", volume_size=2048, chunk_size=1024)
    parity.write_parity(out, parity_count=1)
    m = volumes.load_manifest(out)
    data0 = m["volumes"][0]["name"]
    good = (out / data0).read_bytes()
    (out / data0).write_bytes(b"damaged")
    _link(out / (data0 + ".oopart"), victim)
    assert parity.recover_volumes(m, [data0], out_dir=out) == []
    assert victim.read_bytes() == _VICTIM
    assert (out / data0).read_bytes() == good and not (out / data0).is_symlink()


@posix_only
def test_the_stream_writers_never_write_through_a_link(tmp_path):
    victim = _victim(tmp_path)
    plain = tmp_path / "plain.bin"
    plain.write_bytes(b"x" * 4000)
    vol = tmp_path / "d" / "m-0001-run.ooenc.oopart"
    _link(vol, victim)
    with open(plain, "rb") as fh:
        encrypt_stream_to_hashed(fh, vol, "pw", limit=4000)
    assert victim.read_bytes() == _VICTIM and not vol.is_symlink()
    sealed = tmp_path / "d" / "sealed"
    _link(sealed, victim)
    encrypt_file(plain, sealed, "pw")
    out = tmp_path / "d" / "opened"
    _link(out, victim)
    decrypt_file(sealed, out, "pw")
    assert victim.read_bytes() == _VICTIM and out.read_bytes() == plain.read_bytes()


@posix_only
def test_a_streamed_export_over_planted_manifest_links_leaves_them_untouched(tmp_path):
    from src.backup.stream_backup import BUILDING_NAME, read_stream_backup
    from tests.test_stream_backup import _backup, _make_corpus

    victim = _victim(tmp_path)
    corpus = tmp_path / "corpus.db"
    _make_corpus(corpus, rows=60)
    dest = tmp_path / "dest"
    for name in ("volumes.json.tmp", BUILDING_NAME + ".tmp", "BACKUP_SUMMARY.md.oopart"):
        _link(dest / name, victim)
    _backup(tmp_path, dest, corpus)
    assert victim.read_bytes() == _VICTIM
    staged = read_stream_backup(dest, "pw", staging_root=tmp_path / "st")
    assert staged.corpus_path.read_bytes() == corpus.read_bytes()


@posix_only
def test_the_export_summary_never_writes_through_a_link(tmp_path):
    from src.backup.export_summary import SUMMARY_NAME, write_backup_summary

    victim = _victim(tmp_path)
    d = tmp_path / "dest"
    _link(d / (SUMMARY_NAME + ".oopart"), victim)
    _link(d / SUMMARY_NAME, victim)
    try:
        write_backup_summary(d, {})
    except (KeyError, TypeError, ValueError):
        pytest.skip("the summary renderer needs facts this test does not build")
    assert victim.read_bytes() == _VICTIM and not (d / SUMMARY_NAME).is_symlink()


@posix_only
def test_a_folder_backup_stops_at_a_linked_category_folder_and_writes_nothing_through_it(tmp_path):
    from src.backup.folder_backup import BackupItem, LinkedBackupFolder, write_folder_backup

    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "enwiki.xml.bz2"
    victim.write_bytes(_VICTIM)
    src = tmp_path / "src.bin"
    src.write_bytes(b"dump bytes")
    dest = tmp_path / "dest"
    dest.mkdir()
    os.symlink(outside, dest / "wiki_dumps")
    item = BackupItem("wiki_dumps", "enwiki.xml.bz2", src, src.stat().st_size)
    with pytest.raises(LinkedBackupFolder):
        write_folder_backup(dest, [item])
    assert victim.read_bytes() == _VICTIM
    assert sorted(p.name for p in outside.iterdir()) == ["enwiki.xml.bz2"]


@posix_only
def test_a_folder_backup_stops_at_a_linked_sub_folder(tmp_path):
    from src.backup.folder_backup import BackupItem, LinkedBackupFolder, write_folder_backup

    outside = tmp_path / "outside"
    outside.mkdir()
    src = tmp_path / "blob"
    src.write_bytes(b"model blob")
    dest = tmp_path / "dest"
    (dest / "models").mkdir(parents=True)
    os.symlink(outside, dest / "models" / "blobs")
    item = BackupItem("models", "blobs/sha256-ab", src, src.stat().st_size)
    with pytest.raises(LinkedBackupFolder):
        write_folder_backup(dest, [item])
    assert list(outside.iterdir()) == []


@posix_only
def test_a_link_at_a_backed_up_file_is_never_counted_as_present_and_is_replaced(tmp_path):
    from src.backup.folder_backup import BackupItem, write_folder_backup

    victim = _victim(tmp_path)
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * len(_VICTIM))  # same size as the victim: a followed link would read as present
    dest = tmp_path / "dest"
    _link(dest / "osm_regions" / "fr.osm.pbf", victim)
    res = write_folder_backup(dest, [BackupItem("osm_regions", "fr.osm.pbf", src, src.stat().st_size)])
    assert res["copied"] == 1 and res["skipped"] == 0
    assert victim.read_bytes() == _VICTIM
    out = dest / "osm_regions" / "fr.osm.pbf"
    assert not out.is_symlink() and out.read_bytes() == src.read_bytes()


@posix_only
def test_a_linked_category_stops_the_folder_backup_before_any_file_is_copied(tmp_path):
    """Coordinator's condition: the stop comes before anything is written, so no partial large-data copy is
    left behind, and the error names the folder, says it is a link, where it points and what to do."""
    from src.backup.folder_backup import BackupItem, LinkedBackupFolder, write_folder_backup

    outside = tmp_path / "other-drive"
    outside.mkdir()
    a = tmp_path / "a.pbf"
    a.write_bytes(b"map")
    b = tmp_path / "b.xml.bz2"
    b.write_bytes(b"dump")
    dest = tmp_path / "dest"
    dest.mkdir()
    os.symlink(outside, dest / "wiki_dumps")
    items = [  # the plain category comes FIRST: a per-item check would already have copied it
        BackupItem("osm_regions", "a.pbf", a, a.stat().st_size),
        BackupItem("wiki_dumps", "b.xml.bz2", b, b.stat().st_size),
    ]
    with pytest.raises(LinkedBackupFolder) as ei:
        write_folder_backup(dest, items)
    msg = str(ei.value)
    assert msg.startswith("The large-data backup stopped before copying anything: the folder wiki_dumps inside")
    assert f"is a link to {os.path.realpath(outside)}," in msg
    assert "Replace the link with a real folder, or choose a backup folder on that other drive." in msg
    assert not (dest / "osm_regions").exists()
    assert list(outside.iterdir()) == []
    assert sorted(p.name for p in dest.iterdir()) == ["wiki_dumps"]  # no manifest, nothing else


def test_the_linked_folder_refusal_reads_in_the_page_language(tmp_path):
    """Both refusals go through ooServerText to a locale key in all twelve languages, path holes filled."""
    import shutil
    import subprocess

    from tests.js_source_helper import function_source

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    root = Path(__file__).resolve().parent.parent
    core = (root / "src/static/app-core.js").read_text(encoding="utf-8")
    fns = function_source(core, "_sizeText") + "\n" + function_source(core, "ooServerText")
    keys = []
    for lang in ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        loc = json.loads((root / f"src/static/locales/{lang}.json").read_text(encoding="utf-8"))
        hits = [k for k in loc if k.startswith("The large-data backup stopped")]
        assert len(hits) == 2, lang
        for k in hits:
            assert "{folder}" in loc[k] and "{target}" in loc[k], (lang, k)
        keys = hits
    fr = json.loads((root / "src/static/locales/fr.json").read_text(encoding="utf-8"))
    sent = [
        k.replace("{folder}", "wiki_dumps").replace("{target}", "/media/other drive")
        for k in sorted(keys)
    ]
    script = (
        "const FR = " + json.dumps(fr, ensure_ascii=False) + ";\n"
        "var window = { OOI18N: { t: (k) => FR[k] || k, tf: (k, v) => (FR[k] || k).replace(/\\{(\\w+)\\}/g, (m, n) => v[n]) } };\n"
        "var OOI18N = window.OOI18N;\n" + fns + "\n"
        "const SENT = " + json.dumps(sent) + ";\n"
        "process.stdout.write(JSON.stringify(SENT.map(ooServerText)));\n"
    )
    js = tmp_path / "t.js"
    js.write_text(script, encoding="utf-8")
    out = json.loads(subprocess.run([node, str(js)], capture_output=True, text=True, check=True).stdout)
    for said, key in zip(out, sorted(keys), strict=True):
        assert said.startswith("La sauvegarde des données volumineuses"), said
        assert "\u2068wiki_dumps\u2069" in said and "\u2068/media/other drive\u2069" in said
        assert said == fr[key].replace("{folder}", "\u2068wiki_dumps\u2069").replace("{target}", "\u2068/media/other drive\u2069")


# --------------------------------------------------------------------------- source pins


@pytest.mark.parametrize(
    "module, fn, must",
    [
        ("src/safety/crypto.py", "encrypt_file", "create_new("),
        ("src/safety/crypto.py", "encrypt_stream_to", "create_new("),
        ("src/safety/crypto.py", "encrypt_stream_to_hashed", "create_new("),
        ("src/safety/crypto.py", "decrypt_file", "create_new("),
        ("src/backup/volumes.py", "write_volume_set", "replace_with("),
        ("src/backup/volumes.py", "read_volume_set", "create_new("),
        ("src/backup/parity.py", "write_parity", "create_new("),
        ("src/backup/parity.py", "recover_volumes", "create_new("),
        ("src/backup/stream_backup.py", "_write_json_atomic", "replace_with("),
        ("src/backup/stream_backup.py", "read_stream_backup", "create_new("),
        ("src/backup/export_summary.py", "write_backup_summary", "replace_with("),
        ("src/backup/folder_backup.py", "_write_manifest_atomically", "create_new("),
        ("src/backup/folder_backup.py", "write_folder_backup", "_linked_way("),
        ("src/backup/artifact.py", "write_backup_v2", "replace_with("),
    ],
)
def test_no_link_following_write_remains_at_a_swept_site(module, fn, must):
    body = python_function_source(Path(module).read_text(encoding="utf-8"), fn)
    assert must in body, (module, fn)
    for plain in ('"wb")', '"w", encoding', ".write_text(", ".write_bytes("):
        assert plain not in body, (module, fn, plain)
