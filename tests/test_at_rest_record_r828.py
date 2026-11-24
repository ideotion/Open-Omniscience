"""R828: the at-rest record keeps a MAC, never page 1's bytes (1); the erase overwrites and unlinks it in its key-material pass,
before any bulk work, and says "key material may remain" when it cannot (2); it is excluded from every backup, export,
field-data file and diagnostic bundle (3); an entry goes when its file is erased, replaced or decrypted (4)."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

import pytest

from src.database import at_rest_state
from src.database import connect as connect_module
from src.database.connect import connect, have_driver
from src.safety import crypto_erase

_PW = "row-400-r828-test-passphrase"

posix_only = pytest.mark.skipif(not crypto_erase.plaintext_body_rewrite_supported(), reason="the R817 path is POSIX only")
sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
_ROOT = Path(__file__).resolve().parent.parent


def _encrypted_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(path, key=_PW, create_encrypted=True)
    con.execute("CREATE TABLE t(x)")
    con.executemany("INSERT INTO t VALUES (?)", [("row" * 50,)] * 200)
    con.commit()
    con.close()


def _ident(p: Path) -> tuple[int, int]:
    st = os.stat(p)
    return (st.st_dev, st.st_ino)


def _record(main: Path) -> Path:
    key = os.urandom(32)
    entry = {"encrypted_at": "2026-11-24T00:00:00Z", "read_back_with_key": True, "dev": _ident(main)[0], "ino": _ident(main)[1],
             "mac": at_rest_state._mac(key, main.read_bytes()[:16])}
    p = main.parent / at_rest_state.RECORD_NAME
    p.write_text(json.dumps({"version": 1, "binding_key": key.hex(), "stores": {"corpus": entry}}), encoding="utf-8")
    return p


class _Kept:
    """A read handle on a file, kept open across the erase: it sees the bytes written over the file in place."""

    def __init__(self, path: Path) -> None:
        self.fd = os.open(path, os.O_RDONLY)

    def read(self) -> bytes:
        return os.pread(self.fd, os.fstat(self.fd).st_size, 0)

    def __del__(self) -> None:
        with contextlib.suppress(OSError):
            os.close(self.fd)


def _forget_evidence() -> None:
    with connect_module._lock:
        connect_module._opened_with_key.clear()
        connect_module._opened_plain.clear()


# ---------------------------------------------------------------- (1) a MAC, never the bytes


def test_the_mac_needs_the_bytes_and_never_holds_them():
    key, head = os.urandom(32), os.urandom(16)
    mac = at_rest_state._mac(key, head)
    assert len(bytes.fromhex(mac)) == 32 and head.hex() not in mac
    assert mac == at_rest_state._mac(key, head) and mac != at_rest_state._mac(os.urandom(32), head)
    assert mac != at_rest_state._mac(key, os.urandom(16))


@sqlcipher_only
def test_a_keyed_open_writes_no_byte_of_page_one(tmp_path):
    db = tmp_path / "open_omniscience.db"
    _encrypted_db(db)
    connect(db, key=_PW).close()
    at_rest_state.note_main_open(db)
    raw = (tmp_path / at_rest_state.RECORD_NAME).read_text(encoding="utf-8")
    doc = json.loads(raw)
    page1 = db.read_bytes()[:4096]
    for start in range(0, 16):  # not the salt, nor any 4-byte run of it, in any case
        assert page1[start:start + 4].hex() not in raw.lower()
    entry = doc["stores"]["corpus"]
    assert set(entry) == {"encrypted_at", "read_back_with_key", "dev", "ino", "mac"} and "head" not in entry
    assert at_rest_state.record_names_identity(raw.encode(), _ident(db), page1[:16])


# ---------------------------------------------------------------- (2) the erase's key-material pass


def test_the_record_is_overwritten_before_it_is_unlinked(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    rec = folder / at_rest_state.RECORD_NAME
    before = b'{"version": 1, "binding_key": "' + os.urandom(32).hex().encode() + b'", "stores": {}}'
    rec.write_bytes(before)
    kept = _Kept(rec)  # an open handle sees what was written over the name (a second NAME would make the erase refuse it)
    raw, outcome = crypto_erase._take_record(folder)
    assert raw == before and outcome == "destroyed"
    assert not rec.exists() and kept.read() != before and len(kept.read()) == len(before)


def test_a_record_that_cannot_be_overwritten_is_left_never_destroyed(tmp_path, monkeypatch):
    folder = tmp_path / "f"
    folder.mkdir()
    rec = folder / at_rest_state.RECORD_NAME
    rec.write_bytes(b"{}")
    real_open = os.open

    def refuse(path, flags, *a, **k):
        if str(path).endswith(at_rest_state.RECORD_NAME) and flags & os.O_RDWR:
            raise PermissionError("read-only")
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", refuse)
    assert crypto_erase._take_record(folder)[1] == "left"
    assert rec.exists()


def test_a_record_that_cannot_be_unlinked_is_left_never_destroyed(tmp_path, monkeypatch):
    folder = tmp_path / "f"
    folder.mkdir()
    rec = folder / at_rest_state.RECORD_NAME
    rec.write_bytes(b'{"stores": {}}')
    real_unlink = os.unlink

    def refuse(path, *a, **k):
        if str(path).endswith(at_rest_state.RECORD_NAME):
            raise PermissionError("busy")
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(os, "unlink", refuse)
    raw, outcome = crypto_erase._take_record(folder)
    assert outcome == "left" and raw == b'{"stores": {}}'
    assert rec.read_bytes() != b'{"stores": {}}', "overwritten all the same"


def test_a_link_at_the_record_s_name_is_never_written(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    target = tmp_path / "elsewhere.json"
    target.write_bytes(b"{}")
    (folder / at_rest_state.RECORD_NAME).symlink_to(target)
    assert crypto_erase._take_record(folder) == (None, "absent")
    assert target.read_bytes() == b"{}"


def test_no_record_is_absent_and_nothing_is_created(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    assert crypto_erase._take_record(folder) == (None, "absent")
    assert list(folder.iterdir()) == []


@sqlcipher_only
def test_the_erase_destroys_the_record_before_the_keys_and_the_bulk_steps(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    data.mkdir()
    main = data / crypto_erase._MAIN_DB
    _encrypted_db(main)
    _forget_evidence()
    rec = _record(main)
    before = rec.read_bytes()
    kept = _Kept(rec)
    seen: list[bool] = []
    real_keys = crypto_erase._destroy_keys_folder

    def keys_step(*a, **k):
        seen.append(rec.exists())
        return real_keys(*a, **k)

    monkeypatch.setattr(crypto_erase, "_destroy_keys_folder", keys_step)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert seen == [False], "gone before the key files, so before every bulk step after them"
    assert report["at_rest_record"] == "destroyed" and report["corpus_encryption"] == "encrypted"
    assert kept.read() != before


@posix_only
def test_the_plaintext_path_destroys_the_record_with_the_first_page(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    data.mkdir()
    main = data / crypto_erase._MAIN_DB
    main.write_bytes(os.urandom(8192))
    rec = main.parent / at_rest_state.RECORD_NAME
    rec.write_text(json.dumps({"version": 1, "stores": {}}), encoding="utf-8")
    before = rec.read_bytes()
    kept = _Kept(rec)
    seen: list[bool] = []
    real_rewrite = crypto_erase._rewrite_plain

    def rewrite(*a, **k):
        seen.append(rec.exists() or kept.read() == before)
        return real_rewrite(*a, **k)

    monkeypatch.setattr(crypto_erase, "_rewrite_plain", rewrite)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["at_rest_record"] == "destroyed"
    assert kept.read() != before
    assert seen and True not in seen, "never still there when the body rewrite (the bulk work) runs"


def test_a_record_left_says_key_material_may_remain_and_is_never_clean(tmp_path, monkeypatch):
    data = tmp_path / "OOS data"
    data.mkdir()
    main = data / crypto_erase._MAIN_DB
    main.write_bytes(os.urandom(8192))
    monkeypatch.setattr(crypto_erase, "_take_record", lambda folder, dfd=None: (None, "left"))
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["at_rest_record"] == "left"
    assert "key material may remain" in report["limit"]
    assert "permanently unrecoverable" not in report["limit"]
    js = (_ROOT / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    assert 'const recordLeft = r.at_rest_record === "left";' in js and "&& !recordLeft;" in js
    assert "so key material may remain on the disk: the erase may be incomplete." in js


def test_the_record_left_sentence_is_in_every_locale():
    key = ("The app’s at-rest record could not be overwritten and removed, so key material may remain on the disk: the erase may be "
           "incomplete.")
    for f in (_ROOT / "src" / "static" / "locales").glob("*.json"):
        assert json.loads(f.read_text(encoding="utf-8")).get(key), f.name


# ---------------------------------------------------------------- (3) never carried


def test_no_writer_of_a_backup_export_field_file_or_bundle_names_the_record():
    """Every backup, export, field-data and diagnostic writer takes named files; none may name the record. Only the module that
    keeps it, the erase that destroys it and the scope list of the app's own names (which lets the erase remove it) may."""
    allowed = {"src/database/at_rest_state.py", "src/safety/crypto_erase.py", "src/safety/data_scope.py"}
    hits = []
    for path in sorted((_ROOT / "src").rglob("*")):
        if path.suffix not in (".py", ".js", ".html") or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        named = at_rest_state.RECORD_NAME in text or "at_rest_state import RECORD_NAME" in text \
            or "at_rest_state.RECORD_NAME" in text or "_read_record_at(" in text or "_record_bytes(" in text
        if named and rel not in allowed:
            hits.append(rel)
    assert hits == []
    from src.backup import artifact

    for names in (artifact._STATE_FILES, artifact._LOG_FILES):
        assert not set(names) & at_rest_state.NEVER_CARRIED


def test_the_status_carries_no_field_of_the_record_but_its_time(tmp_path):
    main = tmp_path / "open_omniscience.db"
    main.write_bytes(os.urandom(8192))
    rec = _record(main)
    secret = json.loads(rec.read_text(encoding="utf-8"))["binding_key"]
    st = at_rest_state.status(main)
    flat = json.dumps(st, default=str)
    assert secret not in flat and '"mac"' not in flat and '"ino"' not in flat


def test_a_backup_never_carries_the_record(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.backup.artifact import write_backup_v2
    from src.paths import data_dir

    with TestClient(app):
        rec = data_dir() / at_rest_state.RECORD_NAME
        planted = not rec.exists()
        marker = os.urandom(32).hex()
        if planted:
            rec.write_text(json.dumps({"version": 1, "binding_key": marker, "stores": {}}), encoding="utf-8")
        else:
            marker = json.loads(rec.read_text(encoding="utf-8")).get("binding_key") or marker
        try:
            dest = tmp_path / "b.oobak"
            write_backup_v2(dest)
            import zipfile

            with zipfile.ZipFile(dest) as zf:
                for info in zf.infolist():
                    assert Path(info.filename).name not in at_rest_state.NEVER_CARRIED
                    assert marker.encode() not in zf.read(info.filename)
        finally:
            if planted:
                rec.unlink(missing_ok=True)


# ---------------------------------------------------------------- (4) an entry goes with its file


def test_forget_removes_the_entry_and_never_makes_a_record(tmp_path):
    main = tmp_path / "open_omniscience.db"
    main.write_bytes(os.urandom(8192))
    at_rest_state.forget("corpus", main)
    assert not (tmp_path / at_rest_state.RECORD_NAME).exists(), "no record: nothing is made"
    rec = _record(main)
    at_rest_state.forget("corpus", main)
    doc = json.loads(rec.read_text(encoding="utf-8"))
    assert "corpus" not in doc["stores"] and doc["binding_key"]


def test_a_plaintext_open_removes_the_entry_whole(tmp_path):
    db = tmp_path / "open_omniscience.db"
    db.write_bytes(os.urandom(8192))
    rec = _record(db)
    connect_module._note_open(db, keyed=False)  # what a plaintext open of the same file does (a decrypted store)
    at_rest_state.note_main_open(db)
    assert "corpus" not in json.loads(rec.read_text(encoding="utf-8"))["stores"]


def test_the_corpus_swap_and_the_lane_switch_forget_the_entry():
    import inspect

    from src.backup import merge
    from src.database import rebuild

    swap = inspect.getsource(merge.swap_in_corpus)
    assert 'at_rest_state.forget("corpus", target)' in swap and swap.index("finally:") < swap.index("at_rest_state.forget")
    lane = inspect.getsource(rebuild._switch_lane_held)
    assert 'at_rest_state.forget(f"lane:{kind}", target)' in lane


def test_a_replaced_corpus_loses_its_entry(tmp_path, monkeypatch):
    from src.backup import merge
    from src.database import library_generation

    target = tmp_path / "open_omniscience.db"
    target.write_bytes(os.urandom(8192))
    rec = _record(target)
    working = tmp_path / "working.db"
    working.write_bytes(os.urandom(8192))
    import contextlib as _cl

    monkeypatch.setattr(library_generation, "swap_window", lambda w: _cl.nullcontext())
    monkeypatch.setattr(library_generation, "disk_changing", lambda: None)
    monkeypatch.setattr(merge, "_clear_stale_side_files", lambda *a, **k: None)
    merge.swap_in_corpus(working, target)
    assert "corpus" not in json.loads(rec.read_text(encoding="utf-8"))["stores"]


# ---------------------------------------------------------------- the two security reads' findings


def test_a_record_with_a_second_name_is_never_written_or_removed(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    rec = folder / at_rest_state.RECORD_NAME
    rec.write_bytes(b'{"version": 1, "stores": {}}')
    other = tmp_path / "someone-else.json"
    os.link(rec, other)  # the name is a hard link to another file: writing it would write that file
    assert crypto_erase._take_record(folder) == (None, "left")
    assert rec.exists() and other.read_bytes() == b'{"version": 1, "stores": {}}'


@pytest.mark.parametrize("mac", ["é" * 64, "zz" * 32, "ab", 7, None])
def test_a_crafted_mac_is_no_match_and_never_an_error(tmp_path, mac):
    key, head = os.urandom(32), os.urandom(16)
    doc = {"binding_key": key.hex(), "stores": {}}
    entry = {"read_back_with_key": True, "dev": 1, "ino": 2, "mac": mac}
    assert at_rest_state.entry_names(entry, (1, 2, head), doc) is False
    raw = json.dumps({"version": 1, "binding_key": key.hex(), "stores": {"corpus": entry}}).encode()
    assert at_rest_state.record_names_identity(raw, (1, 2), head) is False


def _legacy_record(folder: Path) -> Path:
    rec = folder / at_rest_state.RECORD_NAME
    salt = os.urandom(16).hex()
    rec.write_text(json.dumps({"version": 1, "stores": {
        "corpus": {"read_back_with_key": True, "dev": 1, "ino": 2, "head": salt},
        "lane:osm": {"read_back_with_key": True, "dev": 1, "ino": 3, "head": os.urandom(16).hex()},
    }}), encoding="utf-8")
    return rec


def test_a_salt_older_builds_wrote_is_dropped_from_every_entry_on_read_and_write(tmp_path):
    rec = _legacy_record(tmp_path)
    doc = at_rest_state._read_record_at(rec)
    assert all("head" not in e for e in doc["stores"].values())
    assert all("head" not in e for e in at_rest_state._serialisable(
        {"stores": json.loads(rec.read_text(encoding="utf-8"))["stores"]})["stores"].values())
    at_rest_state.forget("custody", tmp_path / "open_omniscience.db")  # no such entry: the record is still rewritten clean
    on_disk = json.loads(rec.read_text(encoding="utf-8"))
    assert set(on_disk["stores"]) == {"corpus", "lane:osm"}
    assert all("head" not in e for e in on_disk["stores"].values())


def test_the_scrub_on_open_rewrites_only_a_legacy_record_and_never_makes_one(tmp_path):
    at_rest_state._scrub_legacy(tmp_path / at_rest_state.RECORD_NAME)
    assert list(tmp_path.iterdir()) == []
    rec = _legacy_record(tmp_path)
    at_rest_state._scrub_legacy(rec)
    assert "head" not in rec.read_text(encoding="utf-8")
    ino = os.stat(rec).st_ino
    at_rest_state._scrub_legacy(rec)  # clean now: left as it is
    assert os.stat(rec).st_ino == ino


def test_the_erase_takes_the_record_in_the_data_folder_with_no_main_database(tmp_path):
    data = tmp_path / "OOS data"
    data.mkdir()
    rec = data / at_rest_state.RECORD_NAME
    before = b'{"version": 1, "stores": {}}'
    rec.write_bytes(before)
    kept = _Kept(rec)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["at_rest_record"] == "destroyed"
    assert not rec.exists() and kept.read() != before
