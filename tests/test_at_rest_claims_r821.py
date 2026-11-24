"""
Row 400 (R821): "encrypted" is said only on evidence, at every place that says it. A keyed open in this process, or this
installation's record naming the very file (R820), is evidence; a header that is not SQLite's only LOOKS encrypted, and SQLite's
own header is not encrypted. Each place is tested with a PLAINTEXT store whose page 1 is randomised: it looks encrypted to a header
read, and no key opens it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

import src.api.unlock as unlock_mod
from src.database import at_rest_state, encrypt_tool
from src.database import connect as connect_module
from src.database.connect import set_passphrase

ROOT = Path(__file__).resolve().parents[1]
_KEY = "row-400-test-passphrase"
WITNESS = b"R821-WITNESS-ROW-" * 64


@pytest.fixture(autouse=True)
def _clean_process_state():
    with connect_module._lock:
        saved = (set(connect_module._opened_with_key), set(connect_module._opened_plain))
        connect_module._opened_with_key.clear()
        connect_module._opened_plain.clear()
    at_rest_state._probed.clear()
    yield
    set_passphrase(None)
    at_rest_state._probed.clear()
    with connect_module._lock:
        connect_module._opened_with_key.clear()
        connect_module._opened_with_key.update(saved[0])
        connect_module._opened_plain.clear()
        connect_module._opened_plain.update(saved[1])


def _randomised_plaintext(path: Path) -> None:
    """A real plaintext SQLite store whose first page is then overwritten with random bytes: it looks encrypted to a header read."""
    con = sqlite3.connect(path)
    con.execute("create table t(x blob)")
    for _ in range(20):
        con.execute("insert into t values (?)", (WITNESS,))
    con.commit()
    con.close()
    with open(path, "r+b") as fh:
        fh.write(os.urandom(4096))


def _ident(p: Path) -> tuple[int, int]:
    st = os.stat(p)
    return (st.st_dev, st.st_ino)


def _record(main: Path, name: str = "corpus") -> None:
    ident = _ident(main)
    key = os.urandom(32)
    entry = {"encrypted_at": "2026-11-24T00:00:00Z", "read_back_with_key": True, "dev": ident[0], "ino": ident[1],
             "mac": at_rest_state._mac(key, main.read_bytes()[:16])}
    doc = {"version": 1, "binding_key": key.hex(), "stores": {name: entry}}
    (main.parent / at_rest_state.RECORD_NAME).write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    main = tmp_path / "open_omniscience.db"
    _randomised_plaintext(main)
    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: main)
    return main


# ---------------------------------------------------------------- the status and the doctor (sites 1 and 4)


def test_the_status_says_looks_encrypted_never_encrypted_on_a_header(data):
    st = at_rest_state.status(data)
    row = st["stores"][0]
    assert row["state"] == "looks_encrypted" and row["evidence"] == "header"
    assert st["corpus_encrypted"] is False and st["complete"] is False and st["pending"] == []
    assert "corpus" in st["looks_encrypted"]


def test_the_record_naming_the_very_file_is_evidence_and_another_identity_is_not(data, tmp_path):
    _record(data)
    row = at_rest_state.status(data)["stores"][0]
    assert row["state"] == "encrypted" and row["evidence"] == "record"
    # a replaced file at the same name: the record's identity no longer matches
    other = tmp_path / "incoming.db"
    _randomised_plaintext(other)
    os.replace(other, data)
    assert at_rest_state.status(data)["stores"][0]["state"] == "looks_encrypted"


def test_a_keyed_read_held_in_this_process_is_evidence(data, monkeypatch):
    ident = _ident(data)
    monkeypatch.setattr(connect_module, "opened_with_key", lambda i: tuple(i) == ident)
    row = at_rest_state.status(data)["stores"][0]
    assert row["state"] == "encrypted" and row["evidence"] == "key"


def test_a_sqlite_header_is_plaintext_whatever_the_record_says(tmp_path):
    main = tmp_path / "open_omniscience.db"
    sqlite3.connect(main).execute("create table t(a)").connection.commit()
    _record(main)
    assert at_rest_state.status(main)["stores"][0]["state"] == "plaintext"
    assert at_rest_state.claim_for(main) == "plaintext"


def test_the_doctor_says_looks_encrypted_and_lists_it(data):
    out = unlock_mod.doctor()
    assert out["corpus"]["state"] == "looks_encrypted" and out["corpus"].get("evidence") == "header"
    assert out["at_rest"]["looks_encrypted"] == ["corpus"] and out["at_rest"]["complete"] is False


def test_the_doctor_s_fallback_line_says_encrypted_only_once_the_key_opened_it(data):
    src = (ROOT / "src" / "api" / "unlock.py").read_text(encoding="utf-8")
    fallback = src.split("def _store(p: Path | None) -> dict:")[1].split("keys_dir = ")[0]
    assert '"state": "looks_encrypted", "evidence": "header"' in fallback
    assert '"state": "encrypted", "evidence": "key"' in fallback
    assert fallback.index('"looks_encrypted"') < fallback.index('"state": "encrypted"'), "header first, key evidence only after"


# ---------------------------------------------------------------- the lock state and the reports (sites 2 and 5)


def test_the_lock_state_keeps_its_control_word_and_says_the_claim_beside_it(data, monkeypatch):
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    connect_module.invalidate_header_cache()
    out = unlock_mod.lock_state()
    assert out["state"] == "locked", "the lock screen stays (R821 (5))"
    assert out["at_rest_claim"] == "looks_encrypted"
    _record(data)
    assert unlock_mod.lock_state()["at_rest_claim"] == "encrypted"


def test_a_report_never_says_unlocked_encrypted_without_evidence(data):
    assert at_rest_state.lock_state_claim("unlocked-encrypted", data) == "unlocked-looks-encrypted"
    _record(data)
    assert at_rest_state.lock_state_claim("unlocked-encrypted", data) == "unlocked-encrypted"
    assert at_rest_state.lock_state_claim("locked", data) == "locked"
    for rel in ("src/monitoring/benchmark.py", "src/api/diagnostics/performance.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert '"at_rest_state": at_rest_state.lock_state_claim(locked_state(db_file))' in src, rel


def test_the_lock_screen_says_looks_encrypted_unless_the_record_names_the_file():
    html = (ROOT / "src" / "static" / "unlock.html").read_text(encoding="utf-8")
    js = (ROOT / "src" / "static" / "unlock.js").read_text(encoding="utf-8")
    assert "This database looks encrypted at rest; it has not been checked with your key yet." in html
    assert "This database is encrypted at rest (SQLCipher 4). Enter" not in html
    assert 's.at_rest_claim === "encrypted"' in js and "per this installation's record" in js


def test_the_settings_panel_has_words_for_each_claim():
    js = (ROOT / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    assert 's.state === "looks_encrypted" ? t("Looks encrypted; not yet checked with your key")' in js
    assert 's.evidence === "record"' in js
    assert "Encrypted, but this passphrase does not open it" not in js


def test_a_failed_unlock_with_no_record_asserts_nothing_about_encryption(data, monkeypatch):
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    with pytest.raises(HTTPException) as refused:
        unlock_mod._file_opens_with(data, _KEY)
    assert refused.value.status_code == 403
    assert "encrypt" not in str(refused.value.detail).lower()


# ---------------------------------------------------------------- the encrypt tool and its script (site 3)


def test_the_encrypt_tool_changes_nothing_and_never_says_encrypted_on_a_header(data):
    before = data.read_bytes()
    with pytest.raises(encrypt_tool.EncryptToolError) as refused:
        encrypt_tool.encrypt_store("corpus", data, _KEY, main=data, library=True)
    assert str(refused.value) == encrypt_tool.NOT_THIS_KEY
    assert "already encrypted" not in encrypt_tool.NOT_THIS_KEY and "already encrypted" not in encrypt_tool.ALREADY_ENCRYPTED_IN_USE
    assert data.read_bytes() == before
    assert "corpus" not in at_rest_state.read_record(data)["stores"], "never recorded without a keyed check"


def _encrypt_db_main():
    spec = importlib.util.spec_from_file_location("encrypt_db_r821", ROOT / "scripts" / "encrypt_db.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.main


def test_the_script_cannot_tell_changes_nothing_and_says_the_way_forward(data, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["encrypt_db.py"])
    monkeypatch.setattr("builtins.input", lambda *_a: pytest.fail("never asks for anything on a header alone"))
    before = data.read_bytes()
    assert _encrypt_db_main()() == 1
    out = capsys.readouterr().out
    assert "looks encrypted" in out and "nothing was changed" in out and "unlock it once" in out
    assert "already encrypted" not in out and data.read_bytes() == before


def test_the_script_says_encrypted_on_the_record(data, monkeypatch, capsys):
    _record(data)
    monkeypatch.setattr(sys, "argv", ["encrypt_db.py"])
    assert _encrypt_db_main()() == 0
    assert "per this installation's record" in capsys.readouterr().out


# ---------------------------------------------------------------- the click-through report (site 5)


def _runner():
    from tests.test_encrypted_clickthrough import (
        _load_runner,  # its browserless stub, never a second copy of it
    )

    return _load_runner()


def test_no_lock_word_maps_to_encrypted():
    runner = _runner()
    assert "encrypted" not in runner._LOCK_STATE_TO_AT_REST.values()
    assert runner._LOCK_STATE_TO_AT_REST["locked"] == "looks_encrypted"


def test_the_lock_state_fallback_reads_the_server_s_claim(monkeypatch):
    runner = _runner()

    def fake(url):
        if url.endswith("/doctor"):
            raise OSError("locked")
        return {"state": "locked", "at_rest_claim": "looks_encrypted", "at_rest_evidence": "header", "driver": True}

    monkeypatch.setattr(runner, "_get_json", fake)
    row = runner._probe_at_rest("B", "http://127.0.0.1:1", "before-walk")
    assert row["detected"] == "looks_encrypted" and row["evidence"] == "header"


def test_require_encrypted_needs_the_keyed_reading_after_the_walk():
    src = (ROOT / "scripts" / "ui_clickthrough_run.py").read_text(encoding="utf-8")
    after = src.split('_record_at_rest(report, label, url, "after-walk")')[1]
    assert 'r.get("evidence") == "key"' in after and "NOT VERIFIED" in after and "SystemExit(2)" in after


# ---------------------------------------------------------------- the security reads (row 400)


def test_a_file_that_took_the_same_inode_is_not_named_by_the_record(data):
    """The record carries the file's own first 16 bytes (its salt: random per file, not a secret): a randomised file that later
    takes the same (device, inode) does not match them."""
    _record(data)
    with open(data, "r+b") as fh:  # the same inode, another file's first page
        fh.write(os.urandom(16))
    assert at_rest_state.status(data)["stores"][0]["state"] == "looks_encrypted"
    assert at_rest_state.claim_for(data) == "looks_encrypted"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO")
def test_the_record_is_never_read_through_a_link_a_fifo_or_at_any_size(data):
    rec = data.parent / at_rest_state.RECORD_NAME
    os.mkfifo(data.parent / "fifo")
    rec.symlink_to(data.parent / "fifo")
    assert at_rest_state.read_record(data) == {"version": at_rest_state.RECORD_VERSION, "stores": {}}, "never blocks, never follows"
    rec.unlink()
    rec.write_bytes(b" " * (at_rest_state.RECORD_MAX_BYTES + 1))
    assert at_rest_state.read_record(data)["stores"] == {}


def test_the_proof_records_nothing_when_the_file_changes_under_the_probe(data, monkeypatch):
    calls: list[int] = []

    def swapping_probe(path, key):
        calls.append(1)
        other = path.parent / "other.db"
        _randomised_plaintext(other)
        os.replace(other, path)  # a restore or a repair between the two marks
        return {"state": "encrypted", "key_checked": True}

    monkeypatch.setattr(at_rest_state, "_probe", swapping_probe)
    assert at_rest_state.prove_corpus(_KEY, data) is False and calls == [1]
    assert "corpus" not in at_rest_state.read_record(data)["stores"]


def test_the_proof_records_the_very_file_it_opened(data, monkeypatch):
    monkeypatch.setattr(at_rest_state, "_probe", lambda path, key: {"state": "encrypted", "key_checked": True})
    assert at_rest_state.prove_corpus(_KEY, data) is True
    row = at_rest_state.status(data)["stores"][0]
    assert row["state"] == "encrypted" and row["evidence"] == "record"


def test_nothing_is_finished_under_a_key_that_does_not_open_the_library(data):
    _record(data)  # the record alone: not proof that THIS key opens it
    called: list[str] = []
    out = at_rest_state.finish_pending(_KEY, data, encrypt=lambda *a, **kw: called.append(a[0]) or {})
    assert out["finished"] == [] and called == []


def test_a_retry_never_says_every_store_is_encrypted_beside_a_library_that_only_looks_so():
    words = unlock_mod._nothing_left_words({"looks_encrypted": ["corpus"], "busy": [], "unchecked": [], "not_this_key": []})
    assert words == unlock_mod.NOTHING_LEFT_BUT_UNCHECKED


def test_the_lock_state_says_what_its_claim_rests_on(data):
    out = unlock_mod.lock_state()
    assert out["at_rest_claim"] == "looks_encrypted" and out["at_rest_evidence"] == "header"
    _record(data)
    out = unlock_mod.lock_state()
    assert out["at_rest_claim"] == "encrypted" and out["at_rest_evidence"] == "record"


@pytest.mark.skipif(not connect_module.have_driver(), reason="sqlcipher3 not installed")
def test_the_doctor_carries_the_keyed_reading_when_the_held_key_opens_the_library(tmp_path, monkeypatch):
    """--require-encrypted reads the doctor's evidence after the walk: a library the held key opens says "key", never the
    record's or the header's word."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    main = tmp_path / "open_omniscience.db"
    con = connect_module.connect(main, key=_KEY, create_encrypted=True)
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: main)
    set_passphrase(_KEY)
    corpus = unlock_mod.doctor()["corpus"]
    assert corpus["state"] == "encrypted" and corpus["evidence"] == "key" and corpus.get("cipher")
