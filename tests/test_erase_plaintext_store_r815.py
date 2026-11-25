"""
Row 392 (R815): a main database KNOWN to be plaintext and kept outside the data folder (DATABASE_URL) has no key to destroy, so the
erase rewrites every byte of it that holds data in place (R797), its -wal/-shm too, before the delete; it is reported apart from
"Wiped n/n" (overwritten, partially overwritten, not overwritten with the reason), its other names by count, and the crypto-erase
guarantee is said only for a store positively known to be encrypted, on the CLI and the HTTP paths.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from src.api import _panic_precheck
from src.safety import crypto_erase, data_volume

WITNESS = b"R815-WITNESS-ROW-" * 64
GUARANTEE = "permanently unrecoverable"


def _plain_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("pragma journal_mode=wal")
    con.execute("create table t(x blob)")
    for _ in range(40):
        con.execute("insert into t values (?)", (WITNESS,))
    con.commit()
    con.close()
    assert WITNESS[:34] in path.read_bytes()


def _env(tmp_path: Path, data: Path, db: Path, **extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "DATABASE_URL"))}
    env.update({"OO_DATA_DIR": str(data), "DATABASE_URL": f"sqlite:///{db}", "OO_DB_PLAINTEXT": "1", "OO_NO_SCHEDULER": "1",
                "OO_AUTOSEED": "0", "OO_LLM_AUTOSTART": "0", "OO_STORAGE_GUARD": "0", "PYTHONPATH": os.getcwd(),
                "HOME": str(tmp_path / "home"), **extra})
    return env


def _witnessed(link: Path) -> None:
    """The other name of the store remains, and the rows are gone from it: the rewrite went through every name."""
    assert link.exists(), "the other name is never removed (the erase knows only its own name)"
    assert WITNESS[:34] not in link.read_bytes(), "the row is gone from every name of the store"


# ---------------------------------------------------------------- the CLI, drive there (src/api/main.py _panic_cli)


def test_cli_rewrites_the_plaintext_store_through_every_name(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    db = tmp_path / "internal" / "main.db"
    _plain_db(db)
    link = tmp_path / "elsewhere.db"
    os.link(db, link)
    run = subprocess.run([sys.executable, "-m", "src.api.main", "panic", "--yes"], env=_env(tmp_path, data, db),
                         capture_output=True, text=True, timeout=180, cwd=os.getcwd())
    out = run.stdout
    assert "Traceback" not in run.stderr, run.stderr[-3000:]
    assert not db.exists()
    _witnessed(link)
    assert crypto_erase.PLAIN_STORE_STATE["overwritten"] in out, out
    assert crypto_erase.PLAIN_STORE_OTHER_NAMES_OVERWRITTEN.format(n=1) in out, out
    assert GUARANTEE not in out and crypto_erase._PLAINTEXT_SENTENCE in out, out
    assert "Wiped 0/0 files" in out, "the plaintext store is never counted as a wiped file"
    assert "The corpus key is destroyed" not in out and "salt" not in out, out


# ---------------------------------------------------------------- the CLI, drive not there (src/api/_panic_precheck.py)


def test_cli_with_the_drive_absent_rewrites_the_plaintext_store_outside_it(tmp_path):
    data = tmp_path / "drive" / "OOS data"
    db = tmp_path / "internal" / "main.db"
    _plain_db(db)
    link = tmp_path / "elsewhere.db"
    os.link(db, link)
    env = _env(tmp_path, data, db, **{data_volume.ENV_ID: "a1b2c3d4e5f60718"})
    run = subprocess.run([sys.executable, "-m", "src.api.main", "panic", "--yes"], env=env, capture_output=True, text=True,
                         timeout=180, cwd=os.getcwd())
    out = run.stdout
    assert run.returncode == 2, out + run.stderr
    assert not db.exists() and not data.parent.exists()
    _witnessed(link)
    assert crypto_erase.PLAIN_STORE_STATE["overwritten"] in out and crypto_erase.PLAIN_STORE_OTHER_NAMES_OVERWRITTEN.format(n=1) in out, out
    assert crypto_erase._PLAINTEXT_SENTENCE in out and GUARANTEE not in out, out
    # The store is never counted as a wiped file: what else was outside (nothing here) is said as nothing.
    assert "Files erased outside the data drive: 0 of 0." in out, out
    assert _panic_precheck.ON_THE_DRIVE in out


# ---------------------------------------------------------------- the HTTP path (POST /api/safety/panic)

_HTTP_CHILD = r"""
import json, os, sys
from sqlalchemy import text
from src.database import session
with session.engine.begin() as c:  # the app's own pool on the store, as in the running app
    c.execute(text("select count(*) from t"))
from src.api import safety
rep = safety.panic(safety.PanicBody(confirm=True))
print("REPORT " + json.dumps(rep, default=str))
"""


def test_http_rewrites_the_plaintext_store_and_never_claims_the_guarantee(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    db = tmp_path / "internal" / "main.db"
    _plain_db(db)
    link = tmp_path / "elsewhere.db"
    os.link(db, link)
    script = tmp_path / "child.py"
    script.write_text(_HTTP_CHILD, encoding="utf-8")
    run = subprocess.run([sys.executable, str(script)], env=_env(tmp_path, data, db), capture_output=True, text=True, timeout=180,
                         cwd=os.getcwd())
    line = next((ln for ln in run.stdout.splitlines() if ln.startswith("REPORT ")), None)
    assert line is not None, run.stdout[-3000:] + run.stderr[-3000:]
    rep = json.loads(line.removeprefix("REPORT "))
    assert rep["encrypted_corpus"] is False
    assert rep["plaintext_store"] == {"state": "overwritten", "reason": None, "other_names": 1, "deleted": True, "touched": True,
                                   "form": "plain"}, \
        rep["plaintext_store"]
    assert GUARANTEE not in rep["limit"] and crypto_erase._PLAINTEXT_SENTENCE in rep["limit"], rep["limit"]
    assert not db.exists()
    _witnessed(link)


# ---------------------------------------------------------------- the rewrite itself


def _erase_plain(db: Path, pin) -> dict:
    """The two halves the erase runs (R817): open, keep and unlink in step 1; rewrite through the kept handles at the end."""
    generation = crypto_erase.new_hold_generation()
    try:
        rec = crypto_erase._open_and_unlink_plain(db, pin, generation, [])
        crypto_erase._rewrite_plain(rec, may_write=True)
    finally:
        crypto_erase.rescrub_held(close=True, generation=generation, settle=False)
    return rec


def _rewrite_path(p: Path, **kw):
    fd = os.open(p, os.O_RDWR)
    try:
        return crypto_erase._rewrite_fd(fd, **kw)
    finally:
        os.close(fd)


# ---------------------------------------------------------------- the CLI, plaintext store INSIDE the data folder (R817)


@pytest.mark.skipif(os.name != "posix", reason="Windows takes the first-page fallback (R817 (4))")
def test_cli_rewrites_a_plaintext_store_inside_the_data_folder_through_every_name(tmp_path):
    data = tmp_path / "data"
    db = data / "open_omniscience.db"
    _plain_db(db)
    link = tmp_path / "elsewhere.db"  # a second name for it, outside the folder the erase removes
    os.link(db, link)
    env = _env(tmp_path, data, db)
    del env["DATABASE_URL"]
    run = subprocess.run([sys.executable, "-m", "src.api.main", "panic", "--yes"], env=env, capture_output=True, text=True,
                         timeout=180, cwd=os.getcwd())
    out = run.stdout
    assert "Traceback" not in run.stderr, run.stderr[-3000:]
    assert not db.exists()
    _witnessed(link)
    assert crypto_erase.PLAIN_STORE_STATE["overwritten"] in out and crypto_erase.PLAIN_STORE_DELETED in out, out
    assert crypto_erase.PLAIN_STORE_OTHER_NAMES_OVERWRITTEN.format(n=1) in out, out
    assert crypto_erase.PLAIN_STORE_NOTICE in out, "R818 (a): said as the rewrite starts"
    assert GUARANTEE not in out and crypto_erase._PLAINTEXT_SENTENCE in out, out


# ---------------------------------------------------------------- the rewrite itself


def test_every_data_region_is_rewritten_and_a_hole_is_never_filled(tmp_path):
    p = tmp_path / "sparse.db"
    with open(p, "wb") as f:
        f.write(WITNESS)
        f.seek(512 * 1024 * 1024)  # a hole of 512 MiB: rewriting it would take that much new space on the disk
        f.write(WITNESS)
    before = os.stat(p).st_blocks if hasattr(os.stat_result, "st_blocks") else None
    written, total, stop = _rewrite_path(p)
    assert stop is None and written == total
    assert WITNESS[:34] not in p.read_bytes()
    fd = os.open(p, os.O_RDONLY)
    try:
        regions = crypto_erase._data_regions(fd, os.stat(p).st_size)
    finally:
        os.close(fd)
    if before is not None and regions is not None:
        assert total < 64 * 1024 * 1024 and os.stat(p).st_blocks <= before * 2, "only the regions holding data were written"


def test_without_regions_the_logical_size_stops_at_the_reserve(tmp_path, monkeypatch):
    p = tmp_path / "store.db"
    p.write_bytes(WITNESS * 2000)
    monkeypatch.setattr(crypto_erase, "_data_regions", lambda fd, size: None)
    monkeypatch.setattr(crypto_erase, "_fd_free_bytes", lambda fd: crypto_erase._DISK_RESERVE + 10)
    written, total, stop = _rewrite_path(p)
    assert stop == "reserve" and written == 0 and total == p.stat().st_size


@pytest.mark.skipif(os.name != "posix", reason="Windows takes the first-page fallback (R817 (4))")
def test_the_store_is_unlinked_before_its_rewrite_and_a_stop_is_partially_overwritten(tmp_path, monkeypatch):
    db = tmp_path / "main.db"
    _plain_db(db)
    link = tmp_path / "other.db"
    os.link(db, link)
    pin = crypto_erase._pin_file(db)
    generation = crypto_erase.new_hold_generation()
    try:
        rec = crypto_erase._open_and_unlink_plain(db, pin, generation, [])
        assert not db.exists() and rec["deleted"] is True, "deleted before a byte of its contents is rewritten (R817 (1)/(2))"
        assert WITNESS[:34] in link.read_bytes(), "the contents wait for the end of the erase"
        real = crypto_erase._rewrite_fd
        calls: list[int] = []

        def stop_mid_way(fd, **kw):  # the main file: a quarter written, then the drive is nearly full
            calls.append(fd)
            if len(calls) == 1:
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, os.urandom(4096))
                return 4096, 16384, "reserve"
            return real(fd, **kw)

        monkeypatch.setattr(crypto_erase, "_rewrite_fd", stop_mid_way)
        crypto_erase._rewrite_plain(rec, may_write=True)
    finally:
        crypto_erase.rescrub_held(close=True, generation=generation, settle=False)
    assert rec["state"] == "partially_overwritten" and rec["reason"] == "reserve" and rec["other_names"] == 1
    words = crypto_erase.plaintext_store_sentences({"plaintext_store": rec})
    assert crypto_erase.PLAIN_STORE_STATE["partially_overwritten"] in words and crypto_erase.PLAIN_STORE_DELETED in words


@pytest.mark.skipif(os.name != "posix", reason="Windows takes the first-page fallback (R817 (4))")
def test_a_drive_that_changed_rewrites_nothing(tmp_path):
    db = tmp_path / "main.db"
    _plain_db(db)
    link = tmp_path / "other.db"
    os.link(db, link)
    generation = crypto_erase.new_hold_generation()
    try:
        rec = crypto_erase._open_and_unlink_plain(db, crypto_erase._pin_file(db), generation, [])
        crypto_erase._rewrite_plain(rec, may_write=False)
    finally:
        crypto_erase.rescrub_held(close=True, generation=generation, settle=False)
    assert rec["state"] == "first_page" and rec["reason"] == "drive" and rec["deleted"] is True
    assert WITNESS[:34] in link.read_bytes(), "nothing past the first page was written on a drive that changed"
    words = crypto_erase.plaintext_store_sentences({"plaintext_store": rec})
    assert words[:3] == [crypto_erase.PLAIN_STORE_STATE["first_page"], crypto_erase.PLAIN_STORE_REST,
                         crypto_erase.PLAIN_STORE_REASON["drive"]]


@pytest.mark.parametrize("change", ["swapped", "gone", "link"])
def test_another_file_or_a_link_at_its_place_is_never_touched(tmp_path, change):
    db = tmp_path / "main.db"
    _plain_db(db)
    pin = crypto_erase._pin_file(db)
    db.rename(tmp_path / "moved.db")
    target = tmp_path / "target.db"
    target.write_bytes(WITNESS)
    if change == "swapped":
        db.write_bytes(WITNESS)
    elif change == "link":
        db.symlink_to(target)  # a link swapped in at the path: never followed, never removed
    rec = _erase_plain(db, pin)
    assert rec["state"] == "not_overwritten" and rec["touched"] is False
    assert rec["reason"] == {"swapped": "changed", "gone": "absent", "link": "changed"}[change]
    if change == "swapped":
        assert db.read_bytes() == WITNESS, "nothing at that place is touched"
    if change == "link":
        assert db.is_symlink() and target.read_bytes() == WITNESS
    words = crypto_erase.plaintext_store_sentences({"plaintext_store": rec})
    assert crypto_erase.PLAIN_STORE_NOT_DELETED not in words and crypto_erase.PLAIN_STORE_DELETED not in words


@pytest.mark.skipif(os.name != "posix", reason="O_NOFOLLOW")
def test_a_log_swapped_for_a_link_is_never_written_through(tmp_path):
    db = tmp_path / "main.db"
    _plain_db(db)
    target = tmp_path / "target.bin"
    target.write_bytes(WITNESS)
    wal = db.with_name(db.name + "-wal")
    with contextlib.suppress(FileNotFoundError):
        wal.unlink()
    wal.symlink_to(target)
    rec = _erase_plain(db, crypto_erase._pin_file(db))
    assert target.read_bytes() == WITNESS, "the link's target is never written"
    assert not os.path.lexists(wal), "the link itself is removed"
    assert rec["state"] != "overwritten" and rec["reason"] == "changed", rec


def test_the_first_page_fallback_is_said_as_such():
    rec = {"state": "first_page", "reason": None, "other_names": 0, "deleted": True, "touched": True}
    assert crypto_erase.plaintext_store_sentences({"plaintext_store": rec}) == [
        crypto_erase.PLAIN_STORE_STATE["first_page"], crypto_erase.PLAIN_STORE_DELETED]


def test_the_scrub_claims_the_guarantee_only_after_an_encrypted_erase(tmp_path, monkeypatch):
    for found, guaranteed in ((True, True), (False, False), (None, False)):
        monkeypatch.setattr(crypto_erase, "_LAST_ERASE_ENCRYPTED", found)
        out = crypto_erase.full_secure_erase(1, base_dir=tmp_path, _cap_bytes=4096)
        if out["scrub_not_done"]:
            continue
        assert (out["limit"] == crypto_erase._LIMIT_NOTE) is guaranteed, (found, out["limit"])
        assert (GUARANTEE in out["limit"]) is guaranteed


def test_the_clean_note_fails_closed_and_tells_plaintext_from_unknown():
    assert crypto_erase._clean_note(True) == crypto_erase._LIMIT_NOTE
    assert crypto_erase._PLAINTEXT_SENTENCE in crypto_erase._clean_note(False)
    assert crypto_erase._UNKNOWN_SENTENCE in crypto_erase._clean_note(None)
    for state in (False, None):
        assert GUARANTEE not in crypto_erase._clean_note(state)
    for state, sentence in ((False, crypto_erase._PLAINTEXT_SENTENCE), (None, crypto_erase._UNKNOWN_SENTENCE)):
        held = {"encrypted_corpus": state, "files_not_kept": True}
        crypto_erase.finish_holder_check(held, crypto_erase.new_hold_generation())
        assert GUARANTEE not in held["limit"] and "salt" not in held["limit"] and sentence in held["limit"]


def test_the_page_fails_closed_and_says_the_store_apart():
    js = Path("src/static/app-backup.js").read_text(encoding="utf-8")
    assert "const plaintext = r.encrypted_corpus !== true;" in js
    assert "&& !plaintext && !keyLeft;" in js, "a plaintext erase (or a key left on the disk) is never the clean, crypto-erased result"
    words = [*crypto_erase.PLAIN_STORE_STATE.values(), *crypto_erase.PLAIN_STORE_REASON.values(), crypto_erase.PLAIN_STORE_DELETED,
             crypto_erase.PLAIN_STORE_NOT_DELETED, crypto_erase.PLAIN_STORE_OTHER_NAMES, crypto_erase._PLAINTEXT_SENTENCE,
             crypto_erase._UNKNOWN_SENTENCE, crypto_erase.PLAIN_STORE_REST, crypto_erase.PLAIN_STORE_NOTICE,
             crypto_erase.PLAIN_STORE_OTHER_NAMES_OVERWRITTEN, crypto_erase.PLAIN_STORE_OTHER_NAMES_PARTIAL]
    assert "atRest.erase_rewrites_plaintext_body === true" in js, "the notice only where the body is rewritten (not Windows)"
    tables = {lang: json.loads(Path(f"src/static/locales/{lang}.json").read_text(encoding="utf-8"))
              for lang in ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")}
    for w in words:
        assert w in js, w
        for lang, table in tables.items():
            assert table.get(w), (lang, w)


# ---------------------------------------------------------------- R818: fast destruction first, body after the pool


def _store_with_log(tmp_path: Path) -> tuple[Path, Path, int, bytes]:
    """A plaintext store, a log beside it holding the rows, a second name for the store and a read-only descriptor on the log (a
    second NAME for a log is refused by the erase, so the log is read after the unlink through this descriptor)."""
    db = tmp_path / "main.db"
    _plain_db(db)
    wal = db.with_name(db.name + "-wal")
    wal.write_bytes(WITNESS * 8)
    link = tmp_path / "other.db"
    os.link(db, link)
    wal_fd = os.open(wal, os.O_RDONLY)
    return db, link, wal_fd, link.read_bytes()[:4096]


def _read_fd(fd: int) -> bytes:
    try:
        return os.pread(fd, os.fstat(fd).st_size, 0)
    finally:
        os.close(fd)


@pytest.mark.skipif(os.name != "posix", reason="Windows takes the first-page fallback (R817 (4))")
def test_a_stop_before_the_body_rewrite_finds_page_one_and_the_log_already_destroyed(tmp_path):
    db, link, wal_fd, page1 = _store_with_log(tmp_path)
    generation = crypto_erase.new_hold_generation()
    try:
        rec = crypto_erase._open_and_unlink_plain(db, crypto_erase._pin_file(db), generation, [])
        # the erase stops here: no body rewrite has run
        assert not db.exists() and rec["deleted"] is True
        assert link.read_bytes()[:4096] != page1, "page 1 is destroyed before the unlink (R818)"
        assert WITNESS[:34] not in _read_fd(wal_fd), "the log is destroyed whole before the unlink (R818)"
        assert WITNESS[:34] in link.read_bytes()[4096:], "only the body waits for the rewrite"
    finally:
        crypto_erase.rescrub_held(close=True, generation=generation, settle=False)


@pytest.mark.skipif(os.name != "posix", reason="Windows takes the first-page fallback (R817 (4))")
@pytest.mark.parametrize("own_open", [1, None])
def test_a_pool_not_confirmed_closed_leaves_the_body_and_says_so(tmp_path, own_open):
    db, link, wal_fd, page1 = _store_with_log(tmp_path)
    os.close(wal_fd)
    generation = crypto_erase.new_hold_generation()
    report: dict = {}
    try:
        rec = crypto_erase._open_and_unlink_plain(db, crypto_erase._pin_file(db), generation, [])
        crypto_erase._PLAIN_PENDING[generation] = (rec, True, [str(db)])
        crypto_erase.finish_plaintext_rewrite(report, generation, own_open)
    finally:
        crypto_erase.rescrub_held(close=True, generation=generation, settle=False)
    ps = report["plaintext_store"]
    assert ps["state"] == "first_page" and ps["reason"] == "pool" and ps["deleted"] is True, ps
    assert link.read_bytes()[:4096] != page1 and WITNESS[:34] in link.read_bytes(), "page 1 gone; the rest not written, as said"
    words = crypto_erase.plaintext_store_sentences(report)
    assert words[:4] == [crypto_erase.PLAIN_STORE_STATE["first_page"], crypto_erase.PLAIN_STORE_REST,
                         crypto_erase.PLAIN_STORE_REASON["pool"], crypto_erase.PLAIN_STORE_DELETED], words
    assert crypto_erase.PLAIN_STORE_OTHER_NAMES.format(n=1) in words, "not overwritten: its other names still lead to the rows"


@pytest.mark.skipif(os.name != "posix", reason="Windows takes the first-page fallback (R817 (4))")
def test_a_confirmed_closed_pool_rewrites_the_body_after_the_notice(tmp_path, monkeypatch):
    db, link, wal_fd, _page1 = _store_with_log(tmp_path)
    os.close(wal_fd)
    said: list[int] = []
    monkeypatch.setattr(crypto_erase, "plain_rewrite_notice", lambda: said.append(1))
    generation = crypto_erase.new_hold_generation()
    report: dict = {}
    try:
        rec = crypto_erase._open_and_unlink_plain(db, crypto_erase._pin_file(db), generation, [])
        crypto_erase._PLAIN_PENDING[generation] = (rec, True, [str(db)])
        crypto_erase.finish_plaintext_rewrite(report, generation, 0)
    finally:
        crypto_erase.rescrub_held(close=True, generation=generation, settle=False)
    assert said == [1], "the notice is said once, as the rewrite starts (R818 (a))"
    assert report["plaintext_store"]["state"] == "overwritten"
    _witnessed(link)
    assert crypto_erase.PLAIN_STORE_OTHER_NAMES_OVERWRITTEN.format(n=1) in crypto_erase.plaintext_store_sentences(report)


@pytest.mark.skipif(os.name != "posix", reason="Windows takes the first-page fallback (R817 (4))")
def test_a_stop_during_the_body_rewrite_is_partially_overwritten(tmp_path, monkeypatch):
    db, link, wal_fd, _page1 = _store_with_log(tmp_path)
    os.close(wal_fd)
    generation = crypto_erase.new_hold_generation()
    try:
        rec = crypto_erase._open_and_unlink_plain(db, crypto_erase._pin_file(db), generation, [])

        def killed(fd, **kw):  # the operator closes the app partway (a Ctrl-C on the CLI)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, os.urandom(8192))
            raise KeyboardInterrupt

        monkeypatch.setattr(crypto_erase, "_rewrite_fd", killed)
        crypto_erase._rewrite_plain(rec, may_write=True)
    finally:
        crypto_erase.rescrub_held(close=True, generation=generation, settle=False)
    assert rec["state"] == "partially_overwritten" and rec["reason"] == "stopped", rec
    words = crypto_erase.plaintext_store_sentences({"plaintext_store": rec})
    assert crypto_erase.PLAIN_STORE_REASON["stopped"] in words and crypto_erase.PLAIN_STORE_REST not in words


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs a FIFO")
def test_a_log_that_is_not_a_regular_file_is_never_said_rewritten_in_full(tmp_path):
    """Security read: a sidecar the erase skips (not a regular file, another device, unreadable) gives a reason, so the result is
    never "overwritten in full"; it is never written."""
    db = tmp_path / "main.db"
    _plain_db(db)
    wal = db.with_name(db.name + "-wal")
    with contextlib.suppress(FileNotFoundError):
        wal.unlink()
    os.mkfifo(wal)
    rec = _erase_plain(db, crypto_erase._pin_file(db))
    assert rec["state"] != "overwritten" and rec["reason"] == "changed", rec


def test_the_panic_late_pass_is_armed_only_after_the_last_use_of_the_kept_descriptors():
    """Security read (row 392): the late pass closes the kept descriptors; armed before a body rewrite of minutes, it would close
    them under the holder check that follows (an empty probe read as "none", or a lock taken on a reused descriptor number)."""
    import inspect

    from src.safety import panic

    src = inspect.getsource(panic.panic_wipe)
    assert "_dispose_after_erase(generation, arm_late=not erased)" in src
    assert src.index("finish_plaintext_rewrite(report, generation, own_open)") < src.index("finish_holder_check(report, generation)") \
        < src.rindex("_arm_late_rescrub(generation)")


@pytest.mark.skipif(os.name != "posix", reason="Windows takes the first-page fallback (R817 (4))")
def test_a_log_name_linked_to_another_file_is_never_written(tmp_path):
    """Security read: a sidecar name that is a hard link (it may lead to a file that is not the store's) is never written."""
    db = tmp_path / "main.db"
    _plain_db(db)
    other = tmp_path / "unrelated.bin"
    other.write_bytes(WITNESS)
    wal = db.with_name(db.name + "-wal")
    with contextlib.suppress(FileNotFoundError):
        wal.unlink()
    os.link(other, wal)
    rec = _erase_plain(db, crypto_erase._pin_file(db))
    assert other.read_bytes() == WITNESS, "the other file is never written"
    assert rec["state"] != "overwritten" and rec["reason"] == "changed", rec


def test_the_notice_is_said_only_when_the_file_is_deleted(monkeypatch):
    said: list[int] = []
    monkeypatch.setattr(crypto_erase, "plain_rewrite_notice", lambda: said.append(1))
    generation = crypto_erase.new_hold_generation()
    rec = {"state": None, "reason": None, "other_names": 0, "deleted": False, "touched": True, "_held": []}
    crypto_erase._PLAIN_PENDING[generation] = (rec, True, [])
    report: dict = {}
    crypto_erase.finish_plaintext_rewrite(report, generation, 0)
    assert said == [] and report["plaintext_store"]["state"] != "overwritten"


def test_a_stop_outside_the_rewrite_is_said_and_the_report_kept(monkeypatch):
    def stop():
        raise KeyboardInterrupt

    monkeypatch.setattr(crypto_erase, "plain_rewrite_notice", stop)
    monkeypatch.setattr(crypto_erase, "_rewrite_plain", lambda rec, may_write: (_ for _ in ()).throw(KeyboardInterrupt))
    generation = crypto_erase.new_hold_generation()
    rec = {"state": None, "reason": None, "other_names": 0, "deleted": True, "touched": True, "_held": [[-1, "head", (0, 0), 4096, False]]}
    crypto_erase._PLAIN_PENDING[generation] = (rec, True, [])
    report: dict = {}
    crypto_erase.finish_plaintext_rewrite(report, generation, 0)
    assert report["plaintext_store"]["state"] == "first_page" and report["plaintext_store"]["reason"] == "stopped"


def test_other_names_after_a_partial_overwrite_say_the_old_content_may_remain():
    rec = {"state": "partially_overwritten", "reason": "reserve", "other_names": 2, "deleted": True, "touched": True}
    words = crypto_erase.plaintext_store_sentences({"plaintext_store": rec})
    assert crypto_erase.PLAIN_STORE_OTHER_NAMES_PARTIAL.format(n=2) in words
    assert crypto_erase.PLAIN_STORE_OTHER_NAMES_OVERWRITTEN.format(n=2) not in words


def test_the_doctor_says_whether_the_body_is_rewritten_here():
    from src.api import unlock

    assert "erase_rewrites_plaintext_body" in inspect_source(unlock.doctor)
    assert crypto_erase.plaintext_body_rewrite_supported() is (os.name == "posix" and os.unlink in os.supports_dir_fd
                                                                and os.open in os.supports_dir_fd)


def inspect_source(fn) -> str:
    import inspect

    return inspect.getsource(fn)


@pytest.mark.skipif(os.name != "posix", reason="Windows takes the first-page fallback (R817 (4))")
def test_a_sidecar_in_the_data_folder_linked_to_another_file_is_never_written(tmp_path):
    """Security re-read: a name of the plaintext store the erase refused to write (here a -journal hard-linked to a file outside
    the data folder) is only removed by the walk of the folder, never shredded by path."""
    folder = tmp_path / "OOS data"
    db = folder / "open_omniscience.db"
    _plain_db(db)
    victim = tmp_path / "victim.bin"
    victim.write_bytes(WITNESS)
    os.link(victim, db.with_name(db.name + "-journal"))
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=folder)
    assert victim.read_bytes() == WITNESS, "the other file is never written"
    assert not os.path.lexists(db.with_name(db.name + "-journal"))


@pytest.mark.skipif(os.name != "posix", reason="Windows takes the first-page fallback (R817 (4))")
def test_a_left_name_is_known_by_identity_whatever_the_folder_is_called(tmp_path):
    """Security read: the walks spell the data folder their own way (here through a link to it), so a file the erase left is known
    by its identity, never by its path's spelling."""
    real = tmp_path / "real data"
    db = real / "open_omniscience.db"
    _plain_db(db)
    victim = tmp_path / "victim.bin"
    victim.write_bytes(WITNESS)
    os.link(victim, db.with_name(db.name + "-wal"))
    linked = tmp_path / "linked data"
    linked.symlink_to(real, target_is_directory=True)
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=linked)
    assert victim.read_bytes() == WITNESS, "the other file is never written"
