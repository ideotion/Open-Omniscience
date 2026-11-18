"""An encrypted open that meets a lock stops at the first busy candidate (row 154).

``connect`` tries up to nine SQLCipher page sizes on a file whose size it does not know, each a fresh connection with its own key
derivation and its own busy timeout. A lock another connection holds is a fact about the file, not about the page size or the key,
so every later candidate would wait out the same timeout and fail the same way: a store held by another program cost the at-rest
status about 2.3 s per store (nine candidates at its 0.25 s busy timeout). The walk now stops at the first busy error, and the error
chained into ``WrongPassphraseError`` is that busy one, so callers still read it as "in use", never as a wrong passphrase.

Every case runs on a real SQLCipher file.
"""

from __future__ import annotations

import time

import pytest

from src.database import at_rest_state
from src.database import connect as connect_mod
from src.database.connect import WrongPassphraseError, connect

_KEY = "a-long-enough-passphrase-for-r154-7Kp"
_OTHER = "another-long-enough-passphrase-2Wm"


@pytest.fixture()
def store(tmp_path):
    p = tmp_path / "lane.db"
    c = connect(p, key=_KEY, check_same_thread=False)
    c.execute("CREATE TABLE t(a)")
    c.commit()
    c.close()
    connect_mod._last_good_page_size.clear()  # the walk starts from the top, as for a file this process never opened
    at_rest_state._probed.clear()
    yield p
    connect_mod._last_good_page_size.clear()
    at_rest_state._probed.clear()


@pytest.fixture()
def attempts(monkeypatch):
    seen: list[object] = []
    real = connect_mod._try_open_encrypted

    def counting(*a, **kw):
        seen.append(kw.get("page_size", a[4] if len(a) > 4 else None))  # the candidate page size
        return real(*a, **kw)

    monkeypatch.setattr(connect_mod, "_try_open_encrypted", counting)
    return seen


def _held(p):
    holder = connect(p, key=_KEY, check_same_thread=False)
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute("INSERT INTO t VALUES (1)")
    return holder


def _count_from_here(attempts: list) -> None:
    attempts.clear()  # the holder's own open is not the one under test


def test_a_held_store_is_tried_once_and_the_busy_error_is_the_cause(store, attempts):
    holder = _held(store)
    _count_from_here(attempts)
    try:
        with pytest.raises(WrongPassphraseError) as refused:
            connect(store, key=_KEY, check_same_thread=False, timeout=0.05, read_only=True)
    finally:
        holder.rollback()
        holder.close()
    assert len(attempts) == 1, attempts
    assert isinstance(refused.value, connect_mod.StoreHeldError), "the unlock routes answer in use by this class"
    assert "passphrase does not open" not in str(refused.value)
    assert getattr(refused.value.__cause__, "sqlite_errorcode", None) == 5
    assert at_rest_state._is_busy(refused.value.__cause__)


def test_positive_control_a_wrong_key_still_walks_every_candidate(store, attempts):
    """A wrong passphrase is not busy: every page size is still tried, so a store of any size is never misread as wrong."""
    with pytest.raises(WrongPassphraseError) as refused:
        connect(store, key=_OTHER, check_same_thread=False, timeout=0.05, read_only=True)
    assert len(attempts) == len(connect_mod._PAGE_SIZE_CANDIDATES) + 1
    assert not isinstance(refused.value, connect_mod.StoreHeldError)
    assert getattr(refused.value.__cause__, "sqlite_errorcode", None) == 26


def test_the_right_key_after_the_lock_opens_and_reads(store, attempts):
    holder = _held(store)
    holder.rollback()
    holder.close()
    _count_from_here(attempts)
    c = connect(store, key=_KEY, check_same_thread=False, timeout=0.05, read_only=True)
    try:
        assert c.execute("SELECT count(*) FROM t").fetchone() == (0,)
    finally:
        c.close()
    assert attempts and len(attempts) <= len(connect_mod._PAGE_SIZE_CANDIDATES) + 1


def test_the_status_reads_a_held_store_as_busy_in_one_busy_timeout(store, attempts):
    """The at-rest status's probe of a held store costs one busy timeout, not nine."""
    holder = _held(store)
    _count_from_here(attempts)
    try:
        t0 = time.monotonic()
        out = at_rest_state._probe(store, _KEY)
        took = time.monotonic() - t0
    finally:
        holder.rollback()
        holder.close()
    assert out == {"state": "busy"}
    assert len(attempts) == 1
    # one candidate at PROBE_BUSY_S (0.25 s) plus one key derivation; nine would be well over two seconds
    assert took < 4 * at_rest_state.PROBE_BUSY_S + 1.0, took


def test_an_extended_busy_code_is_read_as_held():
    class _E(Exception):
        sqlite_errorcode = 517  # SQLITE_BUSY_SNAPSHOT

    class _Other(Exception):
        sqlite_errorcode = 26

    assert connect_mod.held_by_another(_E())
    assert not connect_mod.held_by_another(_Other())
    assert not connect_mod.held_by_another(ValueError("no code"))
    assert not connect_mod.held_by_another(None)


# --- the unlock routes say "in use", never "wrong passphrase", for a held store ---------------------------------------


@pytest.fixture()
def short_wait(monkeypatch):
    """The unlock routes open with the default 30 s busy timeout; the held cases here wait 0.05 s, the answer is the same."""
    real = connect_mod.connect

    def quick(p, **kw):
        kw["timeout"] = 0.05
        return real(p, **kw)

    monkeypatch.setattr(connect_mod, "connect", quick)


def test_the_file_question_answers_409_in_use_for_a_held_store_and_403_for_a_wrong_key(store, short_wait):
    from fastapi import HTTPException

    import src.api.unlock as unlock_mod

    holder = _held(store)
    try:
        with pytest.raises(HTTPException) as held:
            unlock_mod._file_opens_with(store, _KEY)
    finally:
        holder.rollback()
        holder.close()
    assert held.value.status_code == 409 and held.value.detail == unlock_mod.STORE_IN_USE
    with pytest.raises(HTTPException) as wrong:
        unlock_mod._file_opens_with(store, _OTHER)
    assert wrong.value.status_code == 403, "positive control: a wrong key is still a wrong key"


def test_an_unlock_that_meets_a_held_store_is_409_and_not_counted_as_a_refused_key(store, short_wait, monkeypatch):
    from fastapi import HTTPException

    import src.api.unlock as unlock_mod

    monkeypatch.setattr(unlock_mod, "_begin_recovery_notice", lambda state: None)
    monkeypatch.setattr(unlock_mod, "_end_recovery_notice", lambda token: None)
    monkeypatch.setattr(unlock_mod, "_REFUSED_ATTEMPTS", 0)
    holder = _held(store)
    try:
        with pytest.raises(HTTPException) as held:
            unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=_KEY), store)
    finally:
        holder.rollback()
        holder.close()
    assert held.value.status_code == 409 and held.value.detail == unlock_mod.STORE_IN_USE
    assert unlock_mod._REFUSED_ATTEMPTS == 0, "nothing was checked, so no refusal is counted"
    with pytest.raises(HTTPException) as wrong:
        unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=_OTHER), store)
    assert wrong.value.status_code == 403 and unlock_mod._REFUSED_ATTEMPTS == 1


def test_the_database_check_reads_a_held_store_as_busy_not_as_a_wrong_passphrase():
    """Planner's sweep of every WrongPassphraseError catch: verify.classify_error answers a person, so a held store is busy there."""
    from src.database import verify

    assert verify.classify_error(connect_mod.StoreHeldError("held")) == (verify.VERDICT_UNCHECKED, "the file was busy")
    assert verify.classify_error(WrongPassphraseError("wrong"))[1] == "the passphrase did not open the file"


def test_encrypting_again_over_a_held_encrypted_store_says_in_use_not_another_passphrase(monkeypatch, tmp_path):
    """Security read A on the StoreHeldError head: encrypt_store's read-back of an already-encrypted store said "not with this
    passphrase" for any failure, a held store included."""
    from src.database import encrypt_tool

    monkeypatch.setattr(encrypt_tool, "encrypt_database", lambda *a, **kw: {"skipped": "already encrypted"})

    def held(*_a, **_kw):
        raise connect_mod.StoreHeldError("held")

    monkeypatch.setattr(encrypt_tool, "_table_counts_safe", held)
    with pytest.raises(encrypt_tool.EncryptToolError) as refused:
        encrypt_tool.encrypt_store("custody", tmp_path / "custody_log.db", _KEY, main=tmp_path / "x.db")
    assert str(refused.value) == encrypt_tool.ALREADY_ENCRYPTED_IN_USE and refused.value.__suppress_context__

    def wrong(*_a, **_kw):
        raise WrongPassphraseError("wrong")

    monkeypatch.setattr(encrypt_tool, "_table_counts_safe", wrong)
    with pytest.raises(encrypt_tool.EncryptToolError) as refused:
        encrypt_tool.encrypt_store("custody", tmp_path / "custody_log.db", _KEY, main=tmp_path / "x.db")
    assert str(refused.value) == encrypt_tool.NOT_THIS_KEY


def test_the_in_use_words_are_keyed_in_every_locale():
    """Security read B: test_unlock_errors_are_translated reads only literal ``detail=`` strings, and these are constants."""
    import json
    from pathlib import Path

    import src.api.unlock as unlock_mod
    from src.database import encrypt_tool

    locales = sorted((Path(__file__).resolve().parents[1] / "src" / "static" / "locales").glob("*.json"))
    assert len(locales) == 12
    for loc in locales:
        d = json.loads(loc.read_text(encoding="utf-8"))
        for k in (unlock_mod.STORE_IN_USE, encrypt_tool.ALREADY_ENCRYPTED_IN_USE):
            assert d.get(k), f"{loc.name} lacks {k[:40]!r}"
