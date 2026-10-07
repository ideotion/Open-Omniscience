"""The lock screen holds THE passphrase, so a failure it writes down is written with the passphrase taken out.

``_unlock_locked`` puts the key back to "locked" when the finish of an unlock fails, and drops the pool's
connections with it. That second step can fail too, and its handler wrote the failure with ``exc_info=True``: the
exception exactly as it made its message, inside a function that holds ``body.passphrase``. It writes through
``secret_scrub.log_failure`` now, like every other handler that holds the passphrase, and
``tests/test_p0_validation.py`` reads this module with the rest. The cases here pin what the walk cannot: that
the line is still written, that what it writes is scrubbed, and that the unlock still ends the way it did.
"""

from __future__ import annotations

import logging
import types

import pytest

from src.api import unlock as unlock_mod
from src.api.unlock import PassphraseBody
from src.database import connect as connect_mod
from src.database import session as session_mod

#: Long and odd enough that it can only be in a record because it was put there.
_PASS = "sync-the-unlock-passphrase-7Qz!"


@pytest.fixture()
def failing_unlock(monkeypatch, tmp_path):
    """An unlock whose verify passes, whose finish fails and whose pool dispose fails, each saying the passphrase: the
    key held through the attempt is recorded in ``held`` (the passphrase, then ``None`` when the unlock is undone)."""
    from src.monitoring import forensics

    held: list = []
    monkeypatch.setattr(forensics, "wal_state_before_open", lambda: None)
    monkeypatch.setattr(unlock_mod, "_begin_recovery_notice", lambda wal_state: None)
    monkeypatch.setattr(unlock_mod, "_end_recovery_notice", lambda token: None)
    monkeypatch.setattr(connect_mod, "connect", lambda *a, **k: object())
    monkeypatch.setattr(unlock_mod, "_close_after_checkpoint", lambda conn, passphrase=None: None)
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: held.append(p))

    def finish(**kw):
        raise RuntimeError("the finish failed")

    def dispose():
        raise RuntimeError(f"the pool could not be disposed, and says the key {_PASS} twice: {_PASS}")

    monkeypatch.setattr(unlock_mod, "_finish_unlock", finish)
    monkeypatch.setattr(session_mod, "dispose_engine", dispose)
    return held, tmp_path / "oo.db"


def _record_text(record: logging.LogRecord) -> str:
    """Everything a handler could write from one record: its message, its arguments and the traceback it carries."""
    parts = [record.getMessage(), repr(record.args), record.exc_text or ""]
    if record.exc_info:
        parts.append(repr(record.exc_info[1]))
    return "\n".join(parts)


def test_a_dispose_that_fails_after_a_failed_finish_is_written_without_the_passphrase(failing_unlock, caplog):
    held, path = failing_unlock
    with caplog.at_level(logging.DEBUG, logger="api.unlock"), pytest.raises(RuntimeError, match="the finish failed"):
        unlock_mod._unlock_locked(PassphraseBody(passphrase=_PASS), path)
    written = [r for r in caplog.records if "engine dispose after a failed unlock finish failed" in r.getMessage()]
    assert len(written) == 1, "the failure of the dispose is still written: a net that drops the line is not a scrub"
    assert written[0].levelno == logging.DEBUG, "the line was a debug line and a net must not turn it into a warning"
    assert "RuntimeError" in written[0].getMessage(), "what failed leads the record"
    assert "***redacted***" in written[0].getMessage()
    assert all(_PASS not in _record_text(r) for r in caplog.records), "the passphrase reached a log record"
    assert _PASS not in caplog.text, "the passphrase reached the formatted log"
    assert written[0].exc_info is None, "a record that carries exc_info is formatted with the exception's own message"


def test_the_unlock_still_ends_as_it_did_when_the_dispose_fails(failing_unlock):
    """The handler only writes: the key is put back, and what propagates is the finish's failure and not the dispose's. It leaves
    the function as the block around it converts it (``scrub_and_reraise``: the class and the words, the key taken out, raised
    from None), which is the finish's own text and none of the dispose's."""
    held, path = failing_unlock
    with pytest.raises(RuntimeError) as err:
        unlock_mod._unlock_locked(PassphraseBody(passphrase=_PASS), path)
    assert str(err.value) == "RuntimeError: the finish failed", "the dispose's failure replaced the finish's"
    assert err.value.__suppress_context__ is True
    assert held == [_PASS, None], "the unlock must be undone: the key set for the finish, then cleared"


class _CheckpointConn:
    """A verify connection whose write-back of the recovered log fails with the words it is given."""

    def __init__(self, says: str) -> None:
        self._says = says
        self.closed = False

    def execute(self, sql: str):
        if "wal_checkpoint" in sql:
            raise RuntimeError(self._says)
        return types.SimpleNamespace(fetchone=lambda: None)

    def close(self) -> None:
        self.closed = True


def _checkpoint_warning(caplog, conn, **kwargs) -> logging.LogRecord:
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="api.unlock"):
        unlock_mod._close_after_checkpoint(conn, **kwargs)
    (record,) = [r for r in caplog.records if "could not be written back" in r.getMessage()]
    assert conn.closed, "the connection is closed whatever the write-back said"
    return record


def test_the_checkpoint_before_the_close_writes_a_failure_with_the_typed_key_out_of_it(caplog, monkeypatch):
    """The key the verify connection was opened with is typed into the request and held by nothing until the verify has accepted
    it, so a driver that quotes what it was handed writes it through this line unless the caller names it. MUTATION TARGET: the
    typed key not handed to the scrub, or the first line taken and cut BEFORE it (a key that holds a newline would leave its first
    half in the line)."""
    monkeypatch.setattr(connect_mod, "_passphrase", None)
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    record = _checkpoint_warning(caplog, _CheckpointConn(f"disk I/O error near PRAGMA key = '{_PASS}'"), passphrase=_PASS)
    assert record.getMessage().endswith("(RuntimeError: disk I/O error near PRAGMA key = '***redacted***'); close() will try again")
    assert _PASS not in caplog.text and record.exc_info is None

    split = "first-half-of-the-key\nsecond-half-of-the-key"
    record = _checkpoint_warning(caplog, _CheckpointConn(f"bad page near {split} end"), passphrase=split)
    assert "(RuntimeError: bad page near ***redacted*** end)" in record.getMessage()
    assert "first-half" not in caplog.text and "second-half" not in caplog.text


def test_the_checkpoint_before_the_close_also_takes_out_what_the_process_holds_and_withholds_a_short_key(caplog, monkeypatch):
    monkeypatch.setattr(connect_mod, "_passphrase", _PASS)
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    record = _checkpoint_warning(caplog, _CheckpointConn(f"I/O error with {_PASS}"))  # nothing handed in: the held one
    assert "(RuntimeError: I/O error with ***redacted***)" in record.getMessage() and _PASS not in caplog.text
    monkeypatch.setattr(connect_mod, "_passphrase", None)
    record = _checkpoint_warning(caplog, _CheckpointConn("I/O error with zq"), passphrase="zq")  # one that cannot be taken out
    assert "(RuntimeError: its text is withheld)" in record.getMessage() and "zq" not in record.getMessage()
    record = _checkpoint_warning(caplog, _CheckpointConn("I/O error on the file"), passphrase="zq")
    assert "(RuntimeError: I/O error on the file)" in record.getMessage(), "a text that holds none of its shapes is kept"


def test_the_unlock_hands_the_typed_key_to_the_checkpoint_close(failing_unlock, monkeypatch):
    """The verify connection is closed BEFORE the process holds the key, so the close's own scrub knows it only if the unlock flow
    names it. MUTATION TARGET: the call in ``_unlock_locked`` that leaves ``passphrase=`` out."""
    held, path = failing_unlock
    seen: list = []
    monkeypatch.setattr(unlock_mod, "_close_after_checkpoint", lambda conn, passphrase=None: seen.append(passphrase))
    with pytest.raises(RuntimeError, match="the finish failed"):
        unlock_mod._unlock_locked(PassphraseBody(passphrase=_PASS), path)
    assert seen == [_PASS]


def test_a_short_wrong_key_at_the_lock_screen_is_answered_in_the_messages_fixed_words(failing_unlock, monkeypatch):
    """A wrong key under the floor of what can be taken out of a text (``MIN_SECRET_CHARS``) withholds the message whole, and a
    mistyped short key is the lock screen's commonest answer: the 403 says the message's own fixed words, not the scrub's notice
    about the passphrases the process holds. A key that is not in the text leaves the message as it was. MUTATION TARGET: the
    ``withheld=`` of the 403's ``detail``."""
    from fastapi import HTTPException

    held, path = failing_unlock

    def wrong(*_a, **_k):
        raise connect_mod.WrongPassphraseError(f"the passphrase does not open {path.name} (or the file is damaged)")

    monkeypatch.setattr(connect_mod, "connect", wrong)
    with pytest.raises(HTTPException) as short:
        unlock_mod._unlock_locked(PassphraseBody(passphrase="oo"), path)  # "oo" is in "oo.db"
    assert short.value.status_code == 403
    assert short.value.detail == "the passphrase does not open this file (or the file is damaged)"
    with pytest.raises(HTTPException) as longer:
        unlock_mod._unlock_locked(PassphraseBody(passphrase="a-wrong-key-Wm3#"), path)
    assert longer.value.status_code == 403
    assert longer.value.detail == f"the passphrase does not open {path.name} (or the file is damaged)"
    assert held == [], "a refused key is never held"
