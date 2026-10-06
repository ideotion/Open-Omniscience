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
    monkeypatch.setattr(unlock_mod, "_close_after_checkpoint", lambda conn: None)
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
    with caplog.at_level(logging.DEBUG, logger="api.unlock"):
        with pytest.raises(RuntimeError, match="the finish failed"):
            unlock_mod._unlock_locked(PassphraseBody(passphrase=_PASS), path)
    written = [r for r in caplog.records if "engine dispose after a failed unlock finish failed" in r.getMessage()]
    assert len(written) == 1, "the failure of the dispose is still written: a net that drops the line is not a scrub"
    assert "RuntimeError" in written[0].getMessage(), "what failed leads the record"
    assert "***redacted***" in written[0].getMessage()
    assert all(_PASS not in _record_text(r) for r in caplog.records), "the passphrase reached a log record"
    assert _PASS not in caplog.text, "the passphrase reached the formatted log"
    assert written[0].exc_info is None, "a record that carries exc_info is formatted with the exception's own message"


def test_the_unlock_still_ends_as_it_did_when_the_dispose_fails(failing_unlock):
    """The handler only writes: the key is put back, and what propagates is the finish's failure and not the dispose's."""
    held, path = failing_unlock
    with pytest.raises(RuntimeError) as err:
        unlock_mod._unlock_locked(PassphraseBody(passphrase=_PASS), path)
    assert str(err.value) == "the finish failed", "the dispose's failure replaced the finish's"
    assert held == [_PASS, None], "the unlock must be undone: the key set for the finish, then cleared"
