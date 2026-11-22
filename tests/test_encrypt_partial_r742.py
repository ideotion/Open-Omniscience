"""An encryption that stops after the library is ciphertext (R742, row 146).

"Encrypt" covers the corpus first, then the custody log, then the versioned-source lanes, under one passphrase. Before R742 a later
store's failure (a file another program holds, a full disk) raised out of the route before the key was set: the app ran keyless against
an encrypted corpus, the other stores stayed in the clear, and a retry was refused (409, "only a plaintext store"). What is pinned:

* a fault after each step leaves the library encrypted AND the key held, and names the stores still pending;
* the state is read from the files' own headers: never "complete" while any store is plaintext, and an install that hit the old failure
  (no record at all) is found and finished the same way;
* a store is recorded only once it reads back with the key; an encrypted store this key does not open is never recorded;
* the retry route resumes under the passphrase the library is open with (and refuses another one), and the next unlock finishes the rest;
* the replaced plaintext file goes through the overwrite path, also when the read-back fails, and a crash's leftover is removed at the
  next unlock only once its store reads as encrypted; the deliberate pre-encrypt snapshot stays and is named.

The faults are injected; the Windows "file held" refusal is simulated with the attribute the product keys on (``winerror`` 32), so every
case runs on every OS.
"""

from __future__ import annotations

import inspect
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException

import src.api.unlock as unlock_mod
from src.database import at_rest_state, encrypt_tool
from src.database import connect as connect_mod
from src.database.connect import is_encrypted_file
from src.database.writer import write_gate
from src.versioned.lanes import all_lanes
from tests.os_scope import scope_os

_REAL_ENCRYPT = encrypt_tool.encrypt_database
_REAL_RECORD = at_rest_state.record_encrypted
_KEY = "a-long-enough-passphrase-for-r742-7Kq"
_OTHER = "another-long-enough-passphrase-0Zx"


class _HeldOpen(PermissionError):
    """What Windows raises for a file another handle holds: the code the product reads, on any OS."""

    winerror = 32


def _sqlite(path: Path, value: str = "saved") -> None:
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE notes(x TEXT)")
    c.execute("INSERT INTO notes VALUES (?)", (value,))
    c.commit()
    c.close()


@pytest.fixture(autouse=True)
def _clean_gate():
    write_gate._reset_for_tests()
    yield
    write_gate._reset_for_tests()


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    """A data folder with every at-rest store in the clear: the corpus, the custody log and each lane."""
    main = tmp_path / "corpus.db"
    _sqlite(main)
    _sqlite(tmp_path / "custody_log.db")
    for spec in all_lanes():
        _sqlite(tmp_path / spec.filename)
    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: main)
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)

    @contextmanager
    def window(_enc_tmp):  # the library's swap window needs a live engine; the file steps inside it are what is tested here
        yield

    monkeypatch.setattr(encrypt_tool, "_library_window", window)
    monkeypatch.setattr(encrypt_tool, "dispose_lane_engines", lambda: None)
    return main


def _fail_for(monkeypatch, *names: str, exc: BaseException | None = None):
    """``encrypt_database`` raises for the stores whose file name is listed; the others run for real."""
    def run(path, key, *, library=False, **_kw):
        if Path(path).name in names:
            raise exc or OSError(28, "No space left on device")
        return _REAL_ENCRYPT(path, key, library=library, **_kw)

    monkeypatch.setattr(encrypt_tool, "encrypt_database", run)


def _record(main: Path) -> dict:
    return json.loads((main.parent / at_rest_state.RECORD_NAME).read_text(encoding="utf-8"))["stores"]


# --- a fault after each step ------------------------------------------------------------------------------------------


def _steps() -> list[str]:
    return ["custody_log.db"] + [spec.filename for spec in all_lanes()]


@pytest.mark.parametrize("failing", _steps())
def test_a_store_that_fails_after_the_library_leaves_the_library_encrypted_the_key_held_and_it_pending(stores, monkeypatch, failing):
    held: list[bool | None] = []
    _fail_for(monkeypatch, failing)
    with pytest.raises(encrypt_tool.EncryptPartial) as partial:
        encrypt_tool.encrypt_all(_KEY, on_library_encrypted=lambda: held.append(is_encrypted_file(stores)))
    assert held == [True], "the key is handed over once, as soon as the library is ciphertext and before any other store"
    assert str(partial.value) == encrypt_tool.PARTIAL
    name = {p.name: n for n, p in at_rest_state.stores(stores)}[failing]
    assert partial.value.pending == [name]
    st = at_rest_state.status(stores)
    assert st["corpus_encrypted"] and not st["complete"] and st["pending"] == [name]
    # every other store went on and is encrypted, and recorded; the failed one is plaintext and not recorded
    for n, p in at_rest_state.stores(stores):
        assert is_encrypted_file(p) is (n != name), n
    assert set(_record(stores)) == {n for n, _p in at_rest_state.stores(stores)} - {name}
    assert write_gate.stats()["held"] is False


def test_the_library_failing_raises_as_before_and_hands_over_no_key(stores, monkeypatch):
    held: list[int] = []
    _fail_for(monkeypatch, "corpus.db", exc=encrypt_tool.EncryptToolError("disk full"))
    with pytest.raises(encrypt_tool.EncryptToolError) as refused:
        encrypt_tool.encrypt_all(_KEY, on_library_encrypted=lambda: held.append(1))
    assert not isinstance(refused.value, encrypt_tool.EncryptPartial)
    assert held == [] and not is_encrypted_file(stores)
    assert at_rest_state.status(stores)["pending"] == [], "nothing is pending beside a plaintext library"


def test_a_windows_held_later_store_is_pending_and_never_called_the_library_untouched(stores, monkeypatch):
    real_replace = encrypt_tool.os.replace

    def replace(src, dst):
        if Path(dst).name == "custody_log.db":
            raise _HeldOpen(13, "The process cannot access the file because it is being used by another process", str(dst))
        return real_replace(src, dst)

    scope_os(monkeypatch, encrypt_tool, replace=replace)
    with pytest.raises(encrypt_tool.EncryptPartial) as partial:
        encrypt_tool.encrypt_all(_KEY)
    assert partial.value.pending == ["custody"]
    assert str(partial.value) not in (encrypt_tool.HELD_UNTOUCHED, encrypt_tool.HELD_LOG_REMOVED)
    assert is_encrypted_file(stores) is True and is_encrypted_file(stores.parent / "custody_log.db") is False
    assert not list(stores.parent.glob("custody_log.db.replaced-*")), "a refused swap drops the second name it made"


# --- the route: the key held after a partial run, and the retry resumes -----------------------------------------------


@pytest.fixture()
def route(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: seen.append(p))
    return seen


def _body(key: str = _KEY):
    return unlock_mod.EncryptBody(passphrase=key, confirm=key, consent=True)


def test_a_partial_run_answers_409_with_the_fixed_words_and_the_key_is_held(route, monkeypatch):
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-plaintext")

    def partial(key, *, on_library_encrypted=None):
        on_library_encrypted()
        raise encrypt_tool.EncryptPartial(["custody"])

    monkeypatch.setattr(encrypt_tool, "encrypt_all", partial)
    with pytest.raises(HTTPException) as refused:
        unlock_mod.encrypt_db(_body())
    assert refused.value.status_code == 409 and refused.value.detail == encrypt_tool.PARTIAL
    assert route == [_KEY], "the key is held so the app goes on with the library it can read"


def _pending(monkeypatch, pending: list[str]) -> None:
    monkeypatch.setattr(
        at_rest_state,
        "status",
        lambda main=None: {"corpus_encrypted": True, "complete": not pending, "pending": pending, "stores": [],
                           "plaintext_snapshots": []},
    )


def test_the_retry_resumes_only_with_the_passphrase_the_library_is_open_with(route, monkeypatch):
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")
    monkeypatch.setattr(connect_mod, "get_passphrase", lambda: _KEY)
    called: list[str] = []
    monkeypatch.setattr(encrypt_tool, "encrypt_all", lambda key, **_kw: called.append(key) or {})
    _pending(monkeypatch, ["custody"])
    with pytest.raises(HTTPException) as refused:
        unlock_mod.encrypt_db(_body(_OTHER))
    assert refused.value.status_code == 403 and refused.value.detail == unlock_mod.FINISH_NEEDS_THE_SAME_PASSPHRASE
    assert called == [], "no store is ever encrypted under a second key"
    unlock_mod.encrypt_db(_body(_KEY))
    assert called == [_KEY]


def test_with_nothing_pending_an_encrypted_library_is_refused_as_done(route, monkeypatch):
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")
    monkeypatch.setattr(connect_mod, "get_passphrase", lambda: _KEY)
    _pending(monkeypatch, [])
    with pytest.raises(HTTPException) as refused:
        unlock_mod.encrypt_db(_body())
    assert refused.value.status_code == 409 and refused.value.detail == "every store is already encrypted"


def test_encrypted_is_true_only_when_every_store_is(route, monkeypatch):
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-plaintext")
    monkeypatch.setattr(encrypt_tool, "encrypt_all", lambda key, **_kw: {})
    _pending(monkeypatch, ["lane:wiki"])
    assert unlock_mod.encrypt_db(_body())["encrypted"] is False
    _pending(monkeypatch, [])
    assert unlock_mod.encrypt_db(_body())["encrypted"] is True


def test_the_real_retry_finishes_what_a_partial_run_left(stores, monkeypatch):
    """End to end on real files: the run fails on the custody log, the retry (``encrypt_all`` again, same key) finishes it without
    touching the encrypted stores again."""
    _fail_for(monkeypatch, "custody_log.db")
    with pytest.raises(encrypt_tool.EncryptPartial):
        encrypt_tool.encrypt_all(_KEY)
    corpus_bytes = stores.read_bytes()
    monkeypatch.setattr(encrypt_tool, "encrypt_database", _REAL_ENCRYPT)
    reports = encrypt_tool.encrypt_all(_KEY)
    assert reports["corpus"]["skipped"] == "already encrypted" and stores.read_bytes() == corpus_bytes
    assert at_rest_state.status(stores)["complete"] is True
    assert "custody" in _record(stores)


# --- the next unlock finishes the rest --------------------------------------------------------------------------------


def test_the_next_unlock_finishes_the_pending_stores(stores, monkeypatch):
    _fail_for(monkeypatch, "custody_log.db", "wiki.db")
    with pytest.raises(encrypt_tool.EncryptPartial):
        encrypt_tool.encrypt_all(_KEY)
    before = at_rest_state.status(stores)["pending"]
    assert before == ["custody", "lane:wiki"]
    monkeypatch.setattr(encrypt_tool, "encrypt_database", _REAL_ENCRYPT)
    out = at_rest_state.finish_pending(_KEY, stores)
    assert out["finished"] == before
    assert out["still_pending"] == [] and at_rest_state.status(stores)["complete"] is True


def test_a_store_that_fails_again_at_the_unlock_stays_pending_and_the_others_finish(stores, monkeypatch):
    _fail_for(monkeypatch, "custody_log.db", "law.db")
    with pytest.raises(encrypt_tool.EncryptPartial):
        encrypt_tool.encrypt_all(_KEY)
    _fail_for(monkeypatch, "law.db")  # still held by another program
    out = at_rest_state.finish_pending(_KEY, stores)
    assert out == {"finished": ["custody"], "still_pending": ["lane:law"]}
    st = at_rest_state.status(stores)
    assert st["pending"] == ["lane:law"] and st["complete"] is False


def test_an_install_that_hit_the_old_failure_has_no_record_and_is_still_found_and_finished(stores):
    """Before R742 nothing was recorded: the corpus is ciphertext, the custody log and the lanes are not, and no record file exists."""
    encrypt_tool.encrypt_database(stores, _KEY, library=True)
    assert not (stores.parent / at_rest_state.RECORD_NAME).exists()
    st = at_rest_state.status(stores)
    assert st["corpus_encrypted"] and set(st["pending"]) == {n for n, _p in at_rest_state.stores(stores)} - {"corpus"}
    out = at_rest_state.finish_pending(_KEY, stores)
    assert out["still_pending"] == [] and at_rest_state.status(stores)["complete"] is True


def test_finishing_does_nothing_beside_a_plaintext_library(stores, monkeypatch):
    called: list[str] = []
    out = at_rest_state.finish_pending(_KEY, stores, encrypt=lambda *a, **kw: called.append(a[0]) or {})
    assert out == {"finished": [], "still_pending": []} and called == []
    assert not is_encrypted_file(stores), "a plaintext library is encrypted only by the operator's own request"


def test_the_startup_upkeep_finishes_under_the_key_it_holds_and_never_blocks_startup():
    from src.api import main as main_mod

    src = inspect.getsource(main_mod._run_startup_upkeep)
    assert "at_rest_state.finish_pending(_key)" in src and "get_passphrase()" in src
    head = src.split("at_rest_state.finish_pending(_key)")[0]
    assert head.count("try:") >= 1 and "except Exception" in src.split("at_rest_state.finish_pending(_key)")[1].split("mark_phase")[0]


# --- recorded only once read back with the key ------------------------------------------------------------------------


def test_a_crash_after_a_swap_before_the_record_is_found_from_the_file_and_recorded_on_the_retry(stores, monkeypatch):
    monkeypatch.setattr(at_rest_state, "record_encrypted", lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        encrypt_tool.encrypt_store("corpus", stores, _KEY, main=stores, library=True)
    monkeypatch.setattr(at_rest_state, "record_encrypted", _REAL_RECORD)
    assert is_encrypted_file(stores) is True and not (stores.parent / at_rest_state.RECORD_NAME).exists()
    assert at_rest_state.status(stores)["corpus_encrypted"] is True, "the file, not the record, says it is encrypted"
    encrypt_tool.encrypt_store("corpus", stores, _KEY, main=stores, library=True)
    assert _record(stores)["corpus"]["read_back_with_key"] is True


def test_an_encrypted_store_this_key_does_not_open_is_left_as_it_is_and_never_recorded(stores):
    custody = stores.parent / "custody_log.db"
    encrypt_tool.encrypt_database(custody, _OTHER)
    before = custody.read_bytes()
    with pytest.raises(encrypt_tool.EncryptToolError) as refused:
        encrypt_tool.encrypt_store("custody", custody, _KEY, main=stores)
    assert str(refused.value) == encrypt_tool.NOT_THIS_KEY and refused.value.__suppress_context__
    assert custody.read_bytes() == before and "custody" not in at_rest_state.read_record(stores)["stores"]


def test_the_record_holds_names_and_times_only(stores):
    encrypt_tool.encrypt_all(_KEY)
    raw = (stores.parent / at_rest_state.RECORD_NAME).read_text(encoding="utf-8")
    assert _KEY not in raw and str(stores.parent) not in raw
    for entry in json.loads(raw)["stores"].values():
        assert set(entry) == {"encrypted_at", "read_back_with_key"}


def test_an_unreadable_record_reads_as_empty_and_the_state_still_comes_from_the_files(stores):
    (stores.parent / at_rest_state.RECORD_NAME).write_text("{not json", encoding="utf-8")
    encrypt_tool.encrypt_all(_KEY)
    assert at_rest_state.status(stores)["complete"] is True


# --- never complete while a store is plaintext; the plaintext still on the disk is named ------------------------------


@pytest.mark.parametrize("plain", _steps())
def test_complete_is_never_true_while_any_store_is_plaintext(stores, monkeypatch, plain):
    _fail_for(monkeypatch, plain)
    with pytest.raises(encrypt_tool.EncryptPartial):
        encrypt_tool.encrypt_all(_KEY)
    st = at_rest_state.status(stores)
    assert st["complete"] is False and len(st["pending"]) == 1


def test_an_absent_store_is_not_pending(stores):
    for spec in all_lanes():
        (stores.parent / spec.filename).unlink()
    encrypt_tool.encrypt_all(_KEY)
    st = at_rest_state.status(stores)
    assert st["complete"] is True and {r["state"] for r in st["stores"] if r["store"].startswith("lane:")} == {"absent"}


def test_the_pre_encrypt_snapshot_stays_and_is_named_beside_complete(stores):
    encrypt_tool.encrypt_all(_KEY)
    st = at_rest_state.status(stores)
    assert st["complete"] is True
    assert "pre-encrypt-" in " ".join(st["plaintext_snapshots"]) and any(n.endswith("-corpus.db") for n in st["plaintext_snapshots"])
    for name in st["plaintext_snapshots"]:
        assert is_encrypted_file(stores.parent / name) is False, "the escape hatch is plaintext, and said to be"


def test_the_doctor_carries_the_whole_set(stores, monkeypatch):
    _fail_for(monkeypatch, "custody_log.db")
    with pytest.raises(encrypt_tool.EncryptPartial):
        encrypt_tool.encrypt_all(_KEY)
    d = unlock_mod.doctor()
    assert d["at_rest"]["complete"] is False and d["at_rest"]["pending"] == ["custody"]
    assert d["at_rest"]["plaintext_snapshots"]


# --- the replaced plaintext file goes through the overwrite path ------------------------------------------------------


def _shred_spy(monkeypatch) -> list[tuple[Path, bool]]:
    from src.safety import crypto_erase

    seen: list[tuple[Path, bool]] = []
    real = crypto_erase._shred

    def spy(path, **kw):
        seen.append((Path(path), is_encrypted_file(path) is False))
        return real(path, **kw)

    monkeypatch.setattr(crypto_erase, "_shred", spy)
    return seen


def test_the_replaced_plaintext_file_is_overwritten_and_removed_after_the_read_back(stores, monkeypatch):
    seen = _shred_spy(monkeypatch)
    report = encrypt_tool.encrypt_database(stores, _KEY, library=True)
    assert report["replaced_file_overwritten"] is True and report["tables"] >= 1
    assert len(seen) == 1 and seen[0][1], "what is overwritten is the replaced PLAINTEXT file, under its second name"
    assert seen[0][0].name.startswith("corpus.db.replaced-") and not seen[0][0].exists()
    assert is_encrypted_file(stores) is True
    assert list(stores.parent.glob("pre-encrypt-*-corpus.db")), "the deliberate snapshot is not this path's to remove"


def test_a_file_system_that_cannot_link_still_encrypts_and_says_nothing_was_overwritten(stores, monkeypatch):
    def link(*_a, **_kw):
        raise OSError(1, "Operation not permitted")

    scope_os(monkeypatch, encrypt_tool, link=link)
    report = encrypt_tool.encrypt_database(stores, _KEY, library=True)
    assert report["replaced_file_overwritten"] is False and is_encrypted_file(stores) is True
    assert not list(stores.parent.glob("corpus.db.replaced-*"))


def test_a_read_back_that_fails_still_overwrites_the_replaced_file(stores, monkeypatch):
    seen = _shred_spy(monkeypatch)

    def unreadable(_p, _key):
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(encrypt_tool, "_table_counts_safe", unreadable)
    with pytest.raises(sqlite3.DatabaseError):
        encrypt_tool.encrypt_database(stores, _KEY, library=True)
    assert len(seen) == 1 and not list(stores.parent.glob("corpus.db.replaced-*"))


def test_a_crash_leftover_is_removed_at_the_next_unlock_only_beside_an_encrypted_store(stores, monkeypatch):
    leftover = stores.parent / "custody_log.db.replaced-20261118T000000Z"
    _sqlite(leftover, "old plaintext")
    # beside a PLAINTEXT custody log the leftover may be the readable copy: it stays
    assert at_rest_state.remove_leftover_replaced(stores, key=_KEY) == 0 and leftover.exists()
    assert leftover.name in at_rest_state.status(stores)["plaintext_snapshots"]
    encrypt_tool.encrypt_all(_KEY)
    assert at_rest_state.remove_leftover_replaced(stores, key=_KEY) == 1 and not leftover.exists()
    assert leftover.name not in at_rest_state.status(stores)["plaintext_snapshots"]


def test_a_second_name_of_the_store_itself_is_never_overwritten(stores):
    encrypt_tool.encrypt_all(_KEY)
    twin = stores.parent / "corpus.db.replaced-20261118T000000Z"
    try:
        twin.hardlink_to(stores)
    except OSError:
        pytest.skip("this file system cannot make a hard link")
    before = stores.read_bytes()
    assert at_rest_state.remove_leftover_replaced(stores, key=_KEY) == 0
    assert stores.read_bytes() == before and twin.exists()


# --- the words reach the page in every language -----------------------------------------------------------------------


def test_every_new_sentence_is_keyed_in_every_locale_and_the_page_uses_the_status():
    root = Path(__file__).resolve().parents[1] / "src" / "static"
    keys = [
        encrypt_tool.PARTIAL,
        encrypt_tool.NOT_THIS_KEY,
        encrypt_tool.ALREADY_ENCRYPTED_IN_USE,
        unlock_mod.FINISH_NEEDS_THE_SAME_PASSPHRASE,
        "every store is already encrypted",
        "Every store is encrypted.",
        "Source store ({kind})",
    ]
    js = (root / "app-backup.js").read_text(encoding="utf-8")
    for k in ("Every store is encrypted.", "Source store ({kind})", "Not finished: {n} store(s)", "Plaintext pre-encrypt copies"):
        assert k in js
    assert "if (r && r.encrypted)" in js, "the success toast says encrypted only when every store is"
    for loc in sorted((root / "locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        for k in keys:
            assert d.get(k), f"{loc.name} lacks {k[:40]!r}"


# --- the review's findings (two security reads and an Opus read) -------------------------------------------------------


def test_a_library_read_back_that_fails_after_the_swap_still_hands_the_key_over(stores, monkeypatch):
    """The key is handed over the moment the library is ciphertext, before its read-back: a read-back that fails (an I/O error)
    must not leave the app keyless against the file it has just encrypted."""
    held: list[bool | None] = []

    def unreadable(_p, _key):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(encrypt_tool, "_table_counts_safe", unreadable)
    with pytest.raises(encrypt_tool.EncryptPartial) as partial:
        encrypt_tool.encrypt_all(_KEY, on_library_encrypted=lambda: held.append(is_encrypted_file(stores)))
    assert held == [True], "the key is held before the read-back"
    # the caller takes the partial path (keyed pool, plaintext serves retired); the other stores wait for the next unlock
    assert set(partial.value.pending) == {n for n, _p in at_rest_state.stores(stores)} - {"corpus"}
    assert not list(stores.parent.glob("corpus.db.replaced-*"))


def test_an_already_encrypted_library_hands_the_key_over_once_on_the_retry(stores, monkeypatch):
    encrypt_tool.encrypt_database(stores, _KEY, library=True)
    held: list[int] = []
    encrypt_tool.encrypt_all(_KEY, on_library_encrypted=lambda: held.append(1))
    assert held == [1]


def test_an_automatic_retry_that_fails_before_touching_a_store_leaves_no_new_plaintext_copy(stores, monkeypatch):
    _fail_for(monkeypatch, "custody_log.db")
    with pytest.raises(encrypt_tool.EncryptPartial):
        encrypt_tool.encrypt_all(_KEY)
    kept = sorted(stores.parent.glob("pre-encrypt-*-custody_log.db"))
    assert kept == [], "the injected failure came before any snapshot of the custody log"
    monkeypatch.setattr(encrypt_tool, "encrypt_database", _REAL_ENCRYPT)

    def full(_p, _enc, _key):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(encrypt_tool, "reencrypt_plain_to", full)
    for _boot in range(3):
        assert at_rest_state.finish_pending(_KEY, stores)["still_pending"] == ["custody"]
    assert sorted(stores.parent.glob("pre-encrypt-*-custody_log.db")) == [], "one more plaintext copy at every start"


def test_the_operators_own_run_keeps_its_snapshot_when_a_store_fails(stores, monkeypatch):
    def full(_p, _enc, _key):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(encrypt_tool, "reencrypt_plain_to", full)
    with pytest.raises(OSError):
        encrypt_tool.encrypt_database(stores.parent / "custody_log.db", _KEY)
    assert list(stores.parent.glob("pre-encrypt-*-custody_log.db")), "the documented escape hatch of the operator's own run"


def test_a_store_that_is_there_but_cannot_be_read_is_never_counted_absent(stores, monkeypatch):
    encrypt_tool.encrypt_all(_KEY)
    lane = stores.parent / "wiki.db"
    real_header_file = at_rest_state._header_file

    def refusing(p, *a, **kw):  # the status reads each header itself (row 149): a read error on the lane's
        if Path(p) == lane:
            raise OSError(5, "Input/output error")
        return real_header_file(p, *a, **kw)

    monkeypatch.setattr(at_rest_state, "_header_file", refusing)
    st = at_rest_state.status(stores)
    row = next(r for r in st["stores"] if r["store"] == "lane:wiki")
    assert row["state"] == "unreadable" and row["reason"] == "io"
    assert st["complete"] is False and "lane:wiki" in st["pending"]


def test_the_finish_takes_the_machine_and_leaves_everything_pending_while_work_is_in_flight(stores, monkeypatch):
    _fail_for(monkeypatch, "custody_log.db")
    with pytest.raises(encrypt_tool.EncryptPartial):
        encrypt_tool.encrypt_all(_KEY)
    monkeypatch.setattr(encrypt_tool, "encrypt_database", _REAL_ENCRYPT)
    from src.scheduler import runner

    seen: list[bool] = []
    monkeypatch.setattr("src.database.corpus_lease.wait_for_quiescence",
                        lambda timeout=0, **kw: seen.append(runner.owns_the_machine()) or ["a re-index batch"])
    out = at_rest_state.finish_pending(_KEY, stores)
    assert seen == [True], "the wait runs inside the exclusive window, as the encrypt route's does"
    assert out == {"finished": [], "still_pending": ["custody"]}
    assert is_encrypted_file(stores.parent / "custody_log.db") is False, "nothing is touched while work is in flight"


def test_the_custody_log_is_swapped_holding_its_own_append_lock(stores, monkeypatch):
    from src.custody.log import _APPEND_LOCK

    owned: dict[str, bool] = {}

    def run(path, key, *, library=False, **kw):
        owned[Path(path).name] = _APPEND_LOCK._is_owned()
        return _REAL_ENCRYPT(path, key, library=library, **kw)

    monkeypatch.setattr(encrypt_tool, "encrypt_database", run)
    encrypt_tool.encrypt_all(_KEY)
    assert owned["custody_log.db"] is True and owned["corpus.db"] is False


def test_a_leftover_beside_a_store_this_key_does_not_open_stays(stores):
    custody = stores.parent / "custody_log.db"
    encrypt_tool.encrypt_database(custody, _OTHER)
    leftover = stores.parent / "custody_log.db.replaced-20261118T000000Z"
    _sqlite(leftover, "maybe the only readable copy")
    assert at_rest_state.remove_leftover_replaced(stores, key=_KEY) == 0 and leftover.exists()


def test_the_doctor_reads_the_lanes_the_status_reads(stores, monkeypatch, tmp_path_factory):
    """When ``data_dir()`` and the corpus folder differ, the per-lane lines and ``complete`` come from the same files."""
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    monkeypatch.setattr("src.paths.data_dir", lambda: elsewhere)
    _sqlite(elsewhere / "custody_log.db")
    encrypt_tool.encrypt_all(_KEY)
    d = unlock_mod.doctor()
    assert d["at_rest"]["complete"] is True
    assert {v["state"] if isinstance(v, dict) else v for v in d["lanes"].values()} <= {"encrypted", "absent"}, d["lanes"]


def test_an_automatic_retry_whose_snapshot_is_cut_short_leaves_no_partial_copy(stores, monkeypatch):
    _fail_for(monkeypatch, "custody_log.db")
    with pytest.raises(encrypt_tool.EncryptPartial):
        encrypt_tool.encrypt_all(_KEY)
    monkeypatch.setattr(encrypt_tool, "encrypt_database", _REAL_ENCRYPT)

    def cut_short(_src, dest):
        Path(dest).write_bytes(b"SQLite format 3\x00 half a copy")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(encrypt_tool, "snapshot_to_plaintext", cut_short)
    assert at_rest_state.finish_pending(_KEY, stores)["still_pending"] == ["custody"]
    assert sorted(stores.parent.glob("pre-encrypt-*-custody_log.db")) == []


def test_the_finish_at_unlock_leaves_a_store_pending_without_room_for_its_two_copies(stores, monkeypatch):
    _fail_for(monkeypatch, "custody_log.db")
    with pytest.raises(encrypt_tool.EncryptPartial):
        encrypt_tool.encrypt_all(_KEY)
    monkeypatch.setattr(encrypt_tool, "encrypt_database", _REAL_ENCRYPT)
    monkeypatch.setattr(at_rest_state, "_room_for", lambda _p: False)
    assert at_rest_state.finish_pending(_KEY, stores) == {"finished": [], "still_pending": ["custody"]}
    assert is_encrypted_file(stores.parent / "custody_log.db") is False
    assert sorted(stores.parent.glob("pre-encrypt-*-custody_log.db")) == []
