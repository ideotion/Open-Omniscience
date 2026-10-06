"""A route that takes a key typed into the request has it in no place a net can read until the key is accepted, and an engine's
error can quote the statement that carried it (``near PRAGMA key = '...'``).

The nets that sit under every module (the global exception handler, the error journal, a failed job's error line) scrub what the
process HOLDS, which a key still being tried is not. So each route that takes one wraps its work in
``secret_scrub.scrub_and_reraise``: what escapes the block is written to the log with the key out of it and raised again as a
``RuntimeError`` carrying the scrubbed text, ``from None``, and every answer the route builds from the exception's words
(``HTTPException(detail=...)``) is written through ``scrubbed`` with the key. ``tests/test_p0_validation.py`` reads these routes'
source; the cases here are the behaviour the walk cannot see, one route at a time: the key the request typed, an engine that
quotes it in every shape the code writes one in, and neither the answer, the log nor a traceback a consumer prints holds it.
"""

from __future__ import annotations

import contextlib
import json
import logging
import traceback
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.api import backup_v2 as v2
from src.api import safety as safety_mod
from src.api import unlock as unlock_mod
from src.database import connect as connect_mod
from src.monitoring import secret_scrub as ss

#: The key typed into the request: an apostrophe, so that the statement that carries it quotes it twice. Not held: the process
#: holds nothing in these cases, which is what makes the routes' own scrub the only one there is.
TYPED = "typed-key-7Qz!it's-here"
#: The restore's second key, the corpus's.
CORPUS = "corpus-key-Lm4#zz-there"


@pytest.fixture(autouse=True)
def _nothing_held(monkeypatch):
    monkeypatch.setattr(connect_mod, "_passphrase", None)
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    assert ss.held_passphrases() == ()


def _sql(secret: str) -> str:
    return f"PRAGMA key = '{secret.replace(chr(39), chr(39) * 2)}'"


def _shapes(secret: str) -> set[str]:
    """The ways the code writes a secret, listed here and not by the helper under test."""
    doubled = secret.replace("'", "''")
    return {
        secret,
        doubled,
        repr(secret)[1:-1],
        repr(doubled)[1:-1],
        json.dumps(secret)[1:-1],
        json.dumps(secret, ensure_ascii=False)[1:-1],
    }


def _engine_error(*secrets: str) -> str:
    """What an engine says of a statement that held the keys: the statements, quoted."""
    return "; ".join(f"near {_sql(s)}: syntax error" for s in secrets)


def _assert_none_of(text: str, *secrets: str) -> None:
    for secret in secrets:
        for shape in _shapes(secret):
            assert shape not in text, (shape, text)


def _everything_written(caplog, *exceptions: BaseException) -> str:
    """Every place the key could be read from after a failure: the formatted log, each record's message, arguments and attached
    traceback, and the traceback a consumer prints for each exception (``from None`` is honoured by it)."""
    parts = [caplog.text]
    for record in caplog.records:
        parts += [record.getMessage(), repr(record.args), record.exc_text or "", str(getattr(record, ss.TRACEBACK_ATTRIBUTE, ""))]
        if record.exc_info:
            parts.append(repr(record.exc_info[1]))
    for exc in exceptions:
        parts.append(str(exc))
        if isinstance(exc, HTTPException):
            # An answer the route built: its text is the writer's to scrub (``detail=scrubbed(...)``). Its cause is the raw
            # exception, which the framework never prints and this module does not read (docs/ledger/OPEN_QUEUE.md).
            parts.append(str(exc.detail))
        else:
            parts.append("".join(traceback.format_exception(exc)))
    return "\n".join(parts)


def _converted(call, caplog, *secrets: str, logger: str) -> RuntimeError:
    """Run ``call`` (a route whose engine failed quoting ``secrets``), and check what escapes it: a ``RuntimeError`` with the
    scrubbed text, ``from None``, one record in the route's logger, and the secrets in none of what was written."""
    caplog.set_level(logging.DEBUG, logger=logger)
    with pytest.raises(RuntimeError) as err:
        call()
    exc = err.value
    assert not isinstance(exc, HTTPException)
    assert exc.__suppress_context__ is True and exc.__cause__ is None, "raised from None: a traceback prints no original"
    assert ss.REDACTED in str(exc), "the words are kept with the keys taken out of them, not withheld"
    assert "syntax error" in str(exc)
    records = [r for r in caplog.records if r.name == logger]
    assert len(records) == 1 and records[0].levelno == logging.ERROR and records[0].exc_info is None
    _assert_none_of(_everything_written(caplog, exc), *secrets)
    return exc


# --------------------------------------------------------------------------- #
#  The lock screen's routes
# --------------------------------------------------------------------------- #
@pytest.fixture()
def unlock_ready(monkeypatch, tmp_path):
    """An unlock that reaches the verify: nothing is forensic, the notice is a no-op and the file is a path."""
    from src.monitoring import forensics

    monkeypatch.setattr(forensics, "wal_state_before_open", lambda: None)
    monkeypatch.setattr(unlock_mod, "_begin_recovery_notice", lambda wal_state: None)
    monkeypatch.setattr(unlock_mod, "_end_recovery_notice", lambda token: None)
    monkeypatch.setattr(unlock_mod, "_close_after_checkpoint", lambda conn, passphrase=None: None)
    return tmp_path / "oo.db"


def test_an_unlock_whose_verify_fails_some_other_way_than_a_wrong_key_has_the_typed_key_out_of_everything_it_writes(
        unlock_ready, monkeypatch, caplog):
    """MUTATION TARGET: the block around the whole of ``_unlock_locked``. The verify raised an engine error quoting the key the
    request typed: the key is not held yet, so no net reads it, and the exception used to reach the server's own log as raised."""

    def verify(*args, **kwargs):
        raise RuntimeError(_engine_error(TYPED))

    monkeypatch.setattr(connect_mod, "connect", verify)
    exc = _converted(
        lambda: unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=TYPED), unlock_ready),
        caplog,
        TYPED,
        logger="api.unlock",
    )
    assert str(exc) == f"RuntimeError: near PRAGMA key = '{ss.REDACTED}': syntax error"


def test_a_wrong_key_is_still_answered_403_and_its_detail_has_the_typed_key_out_of_it(unlock_ready, monkeypatch, caplog):
    def refuse(*args, **kwargs):
        raise connect_mod.WrongPassphraseError(f"the passphrase {TYPED} did not open it")

    monkeypatch.setattr(connect_mod, "connect", refuse)
    caplog.set_level(logging.DEBUG, logger="api.unlock")
    with pytest.raises(HTTPException) as err:
        unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=TYPED), unlock_ready)
    assert err.value.status_code == 403 and err.value.detail == f"the passphrase {ss.REDACTED} did not open it"
    _assert_none_of(_everything_written(caplog, err.value), TYPED)
    assert not [r for r in caplog.records if r.name == "api.unlock"], "an answer the code wrote is not logged as a failure"


def test_a_finish_that_fails_after_the_key_was_accepted_is_converted_too(unlock_ready, monkeypatch, caplog):
    monkeypatch.setattr(connect_mod, "connect", lambda *a, **k: object())
    held = []
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: held.append(p))

    def finish(**kwargs):
        raise RuntimeError(_engine_error(TYPED))

    monkeypatch.setattr(unlock_mod, "_finish_unlock", finish)
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)
    exc = _converted(
        lambda: unlock_mod._unlock_locked(unlock_mod.PassphraseBody(passphrase=TYPED), unlock_ready),
        caplog,
        TYPED,
        logger="api.unlock",
    )
    assert held == [TYPED, None], "the key is still put back to locked: the block converts what escapes, it does not swallow it"
    assert str(exc).startswith("RuntimeError: near PRAGMA key = ")


def test_the_encrypt_in_place_route_converts_what_the_encrypt_raises_and_scrubs_its_own_answer(monkeypatch, caplog):
    from src.database import encrypt_tool

    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-plaintext")
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: None)
    body = unlock_mod.EncryptBody(passphrase=TYPED, confirm=TYPED, consent=True)

    def engine(passphrase):
        raise RuntimeError(_engine_error(passphrase))

    monkeypatch.setattr(encrypt_tool, "encrypt_all", engine)
    _converted(lambda: unlock_mod.encrypt_db(body), caplog, TYPED, logger="api.unlock")

    def refusal(passphrase):
        raise encrypt_tool.EncryptToolError(f"cannot encrypt with {passphrase}")

    monkeypatch.setattr(encrypt_tool, "encrypt_all", refusal)
    caplog.clear()
    with pytest.raises(HTTPException) as err:
        unlock_mod.encrypt_db(body)
    assert err.value.status_code == 400 and err.value.detail == f"cannot encrypt with {ss.REDACTED}"
    _assert_none_of(_everything_written(caplog, err.value), TYPED)


def test_the_create_route_converts_a_failed_creation_and_still_leaves_the_fresh_state_intact(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: tmp_path / "oo.db")
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "fresh")
    held = []
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: held.append(p))
    monkeypatch.setattr(connect_mod, "invalidate_header_cache", lambda: held.append("invalidated"))

    def finish():
        raise RuntimeError(_engine_error(TYPED))

    monkeypatch.setattr(unlock_mod, "_finish_unlock", finish)
    body = unlock_mod.CreateBody(passphrase=TYPED, confirm=TYPED)
    _converted(lambda: unlock_mod.create_db(body), caplog, TYPED, logger="api.unlock")
    assert held == [TYPED, None, "invalidated"], "the key is set, put back, and the stale header cache is dropped"


# --------------------------------------------------------------------------- #
#  The backup routes
# --------------------------------------------------------------------------- #
def test_the_encrypted_backup_route_converts_what_the_backup_raises_and_scrubs_its_own_answer(monkeypatch, caplog):
    from src.backup.sqlite_backup import BackupError

    body = safety_mod.PassphraseBody(passphrase=TYPED)

    def engine(passphrase):
        raise RuntimeError(_engine_error(passphrase))

    monkeypatch.setattr("src.safety.make_encrypted_backup", engine)
    _converted(lambda: safety_mod.encrypted_backup(body), caplog, TYPED, logger="api.safety")

    def refusal(passphrase):
        raise BackupError(f"the store refused {passphrase}")

    monkeypatch.setattr("src.safety.make_encrypted_backup", refusal)
    caplog.clear()
    with pytest.raises(HTTPException) as err:
        safety_mod.encrypted_backup(body)
    assert err.value.status_code == 400 and err.value.detail == f"the store refused {ss.REDACTED}"
    _assert_none_of(_everything_written(caplog, err.value), TYPED)


class _Manager:
    """A manager whose every start fails with ``error`` (a callable that builds it from the arguments it was given)."""

    def __init__(self, error):
        self._error = error

    def _fail(self, *args, **kwargs):
        raise self._error(*args, **kwargs)

    start_backup = start_restore = start_verify = start = _fail


def _patch_manager(monkeypatch, where: str, getter: str, error) -> None:
    monkeypatch.setattr(f"src.backup.{where}.{getter}", lambda: _Manager(error))


@pytest.mark.parametrize(
    "route,body,where,getter,secrets",
    [
        ("volume_backup_start", lambda: v2.VolumeBackupBody(dest="/x", passphrase=TYPED), "volume_job", "get_volume_manager", (TYPED,)),
        (
            "volume_backup_restore",
            lambda: v2.VolumeRestoreBody(src="/x", passphrase=TYPED, corpus_passphrase=CORPUS),
            "volume_job",
            "get_volume_manager",
            (TYPED, CORPUS),
        ),
        ("volume_backup_verify", lambda: v2.VolumeVerifyBody(src="/x", passphrase=TYPED), "volume_job", "get_volume_manager", (TYPED,)),
        (
            "import_queue_start",
            lambda: v2.ImportQueueBody(items=[], passphrase=TYPED),
            "import_queue",
            "get_import_queue",
            (TYPED,),
        ),
    ],
)
def test_each_route_that_starts_a_job_with_a_typed_key_converts_an_error_it_did_not_expect_and_scrubs_the_ones_it_answers(
        monkeypatch, caplog, route, body, where, getter, secrets):
    """MUTATION TARGET: the block around the start, the ``detail=scrubbed(...)`` of either answer, or a key left out of the
    secrets of the block (the restore holds TWO, and a text scrubbed of one still carries the other)."""
    handler = getattr(v2, route)

    _patch_manager(monkeypatch, where, getter, lambda *a, **k: OSError(_engine_error(*secrets)))
    _converted(lambda: handler(body()), caplog, *secrets, logger="api.backup_v2")

    for status, error in ((400, ValueError), (409, RuntimeError)):
        _patch_manager(monkeypatch, where, getter, lambda *a, _e=error, **k: _e(f"refused: {_engine_error(*secrets)}"))
        caplog.clear()
        with pytest.raises(HTTPException) as err:
            handler(body())
        assert err.value.status_code == status, (route, err.value.status_code)
        assert err.value.detail.count(ss.REDACTED) == len(secrets) and "syntax error" in err.value.detail
        _assert_none_of(_everything_written(caplog, err.value), *secrets)


class _Staged:
    """What ``restore_legacy_path`` hands to the merge: nothing it reads here."""


@pytest.fixture()
def legacy(monkeypatch, tmp_path):
    """A legacy restore that reaches the merge: a file that is a file, a staging that is nothing, a journal that writes nothing."""
    path = tmp_path / "old.oobak"
    path.write_bytes(b"x")
    monkeypatch.setattr(v2, "_apply_restore_selection", lambda staged, include_newsletters: None)
    monkeypatch.setattr(v2, "cleanup_staging", lambda staged: None)
    monkeypatch.setattr("src.backup.runlog.run", lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(v2, "exclusive_window_open", lambda: False)
    return path


def test_the_legacy_restore_converts_a_staging_that_fails_unexpectedly(legacy, monkeypatch, caplog):
    def stage(data, passphrase):
        raise RuntimeError(_engine_error(TYPED))

    monkeypatch.setattr(v2, "_stage_upload", stage)
    _converted(lambda: v2.restore_legacy_path(str(legacy), TYPED), caplog, TYPED, logger="api.backup_v2")


def test_the_legacy_restore_answers_a_refused_artifact_with_the_typed_key_out_of_its_detail(legacy, monkeypatch, caplog):
    def read(data, passphrase=None):
        raise v2.ArtifactError(f"the artifact refused {passphrase}")

    monkeypatch.setattr(v2, "read_artifact", read)
    caplog.set_level(logging.DEBUG, logger="api.backup_v2")
    with pytest.raises(HTTPException) as err:
        v2.restore_legacy_path(str(legacy), TYPED)
    assert err.value.status_code == 400 and err.value.detail == f"the artifact refused {ss.REDACTED}"
    _assert_none_of(_everything_written(caplog, err.value), TYPED)


def test_a_legacy_merge_that_fails_is_answered_500_with_the_key_out_of_the_detail_and_logged_once_with_it_out_of_the_record(
        legacy, monkeypatch, caplog):
    """The one handler in this module that catches ``Exception`` with the key in scope: the response is built from the scrubbed
    text, the record is written through ``log_failure``, and the answer is an ``HTTPException`` the block lets through."""
    monkeypatch.setattr(v2, "_stage_upload", lambda data, passphrase: _Staged())

    def merge(staged, **kwargs):
        raise RuntimeError(_engine_error(TYPED))

    monkeypatch.setattr(v2, "run_restore", merge)
    caplog.set_level(logging.DEBUG, logger="api.backup_v2")
    with pytest.raises(HTTPException) as err:
        v2.restore_legacy_path(str(legacy), TYPED)
    assert err.value.status_code == 500
    assert ss.REDACTED in err.value.detail and "syntax error" in err.value.detail
    records = [r for r in caplog.records if r.name == "api.backup_v2"]
    assert len(records) == 1, "logged once, by the handler: the block does not log an answer again"
    _assert_none_of(_everything_written(caplog, err.value), TYPED)


def test_a_legacy_restore_that_cannot_read_its_file_says_so_without_the_key(legacy, monkeypatch, caplog):
    def broken(self):
        raise OSError(f"cannot read {TYPED}")

    monkeypatch.setattr(Path, "read_bytes", broken)
    with pytest.raises(HTTPException) as err:
        v2.restore_legacy_path(str(legacy), TYPED)
    assert err.value.status_code == 400 and TYPED not in err.value.detail and ss.REDACTED in err.value.detail


# --------------------------------------------------------------------------- #
#  The diagnostics routes that take the backup passphrase
# --------------------------------------------------------------------------- #
def test_the_diagnostics_routes_that_take_the_backup_passphrase_answer_their_400s_with_it_out_of_the_detail(monkeypatch):
    """The destination check and the resume's preflight quote what they were given in their ValueError, and the answer's detail is
    the caller's own text, which a typed key does not come back in (the browser can send it on to the error journal, which knows
    only what the process holds). MUTATION TARGET: the ``scrubbed`` of any of the three."""
    from src.api import diagnostics as d
    from src.monitoring import p0_validation, release_run

    def refuse_dest(dest):
        raise ValueError(f"{dest} cannot be used: the key {TYPED} is in the path")

    def refuse_resume(passphrase):
        raise ValueError(f"the passphrase {passphrase} is still needed")

    monkeypatch.setattr(p0_validation, "validate_dest_dir", refuse_dest)
    monkeypatch.setattr(release_run, "resume_preflight", refuse_resume)
    calls = {
        "p0": lambda: d.p0_validation_start(d.P0ValidationBody(dest_dir=f"/x/{TYPED}", passphrase=TYPED)),
        "release run": lambda: d.release_run_start(d.ReleaseRunBody(dest_dir=f"/x/{TYPED}", passphrase=TYPED)),
        "resume": lambda: d.release_run_resume(d.ResumeBody(passphrase=TYPED)),
    }
    for name, call in calls.items():
        with pytest.raises(HTTPException) as err:
            call()
        assert err.value.status_code == 400, name
        assert ss.REDACTED in err.value.detail, name
        _assert_none_of(str(err.value.detail), TYPED)


# --------------------------------------------------------------------------- #
#  The mailbox password
# --------------------------------------------------------------------------- #
#: A mailbox password is typed into the request and is not the store's passphrase, so no net holds it: an apostrophe and a
#: backslash, so that the shapes it is written in differ from the typed one.
MAILBOX = "mail-pass-9Xk'q\\w-2"


def _mail_error(secret: str) -> str:
    """What a mail library says of a login that failed: the line it was sent, in the shapes a library writes it in."""
    return f"LOGIN me {secret} failed: sent {secret!r} and {json.dumps(secret)} and {secret.replace(chr(39), chr(39) * 2)}"


def _the_ingest_email_route(monkeypatch, fetch):
    """``ingest_email_endpoint`` over a fetch that raises, with nothing else in its way."""
    from types import SimpleNamespace

    from src.api import ingestion as ing

    monkeypatch.setattr(ing, "_get_source", lambda db, source_id: SimpleNamespace(name="mailbox"))
    monkeypatch.setattr(ing, "fetch_imap", fetch)
    body = ing.IngestEmailRequest(host="mail.example", user="me", password=MAILBOX)
    return lambda: ing.ingest_email_endpoint(7, body, db=None)


def test_a_mail_library_error_that_quotes_the_password_leaves_the_ingest_email_route_with_it_out_of_everything(monkeypatch, caplog):
    """MUTATION TARGET: the ``scrub_and_reraise`` around the fetch. ``imaplib``, ``ssl`` and ``OSError`` are not the
    ``RuntimeError`` the route maps to a 409, so they used to reach the global handler, the server's log and the journal as raised,
    carrying a password no net holds."""
    import imaplib

    caplog.set_level(logging.DEBUG, logger="api.ingestion")
    for error in (imaplib.IMAP4.error(_mail_error(MAILBOX)), OSError(_mail_error(MAILBOX)), ValueError(_mail_error(MAILBOX))):

        def fetch(*args, _error=error, **kwargs):
            raise _error

        caplog.clear()
        with pytest.raises(RuntimeError) as err:
            _the_ingest_email_route(monkeypatch, fetch)()
        exc = err.value
        assert exc.__suppress_context__ is True and exc.__cause__ is None, "raised from None: a traceback prints no original"
        assert type(error).__name__ in str(exc) and ss.REDACTED in str(exc)
        records = [r for r in caplog.records if r.name == "api.ingestion"]
        assert len(records) == 1 and records[0].levelno == logging.ERROR and records[0].exc_info is None
        _assert_none_of(_everything_written(caplog, exc), MAILBOX)


def test_the_airplane_refusal_is_still_a_409_and_a_refusal_that_quotes_the_password_has_it_out_of_the_detail(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="api.ingestion")

    def refuse(*args, **kwargs):
        raise RuntimeError("network refused: airplane mode is engaged")

    with pytest.raises(HTTPException) as err:
        _the_ingest_email_route(monkeypatch, refuse)()
    assert err.value.status_code == 409 and err.value.detail == "network refused: airplane mode is engaged"
    assert not [r for r in caplog.records if r.name == "api.ingestion"], "an answer the code wrote is not logged as a failure"

    def chatter(*args, **kwargs):
        raise RuntimeError(_mail_error(MAILBOX))

    with pytest.raises(HTTPException) as err:
        _the_ingest_email_route(monkeypatch, chatter)()
    assert err.value.status_code == 409 and ss.REDACTED in err.value.detail
    _assert_none_of(_everything_written(caplog, err.value), MAILBOX)


def test_a_mailbox_pull_that_fails_leaves_its_job_status_with_the_password_out_of_it_in_every_shape(monkeypatch):
    """The pull runs as a background job whose ``error`` ``/api/jobs`` serves: the worker's own text is scrubbed where it is made,
    in every shape and not only the one typed (the replace it used knew only that one). MUTATION TARGET: the ``scrubbed`` in
    the worker."""
    from types import SimpleNamespace

    from src.api import ingestion as ing

    def fetch(*args, **kwargs):
        raise OSError(_mail_error(MAILBOX))

    monkeypatch.setattr(ing, "fetch_mailbox", fetch)
    ctx = SimpleNamespace(set_progress=lambda **kwargs: None)
    with pytest.raises(RuntimeError) as err:
        ing._mailbox_pull_worker(
            ctx, protocol="imap", host="mail.example", user="me", password=MAILBOX, port=0, folder="INBOX", limit=5, use_ssl=True
        )
    assert err.value.__suppress_context__ is True and ss.REDACTED in str(err.value)
    _assert_none_of(str(err.value) + "".join(traceback.format_exception(err.value)), MAILBOX)
