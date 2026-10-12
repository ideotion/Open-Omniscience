"""A background job that fails publishes the failure's text as its ``error`` (``/api/jobs``, the task manager) and logs the
exception. An engine's error can quote the statement that held the key, so both are written with every passphrase the process
holds taken out of them AND the secrets the job was started with (a backup's passphrase, a mailbox's password: the process does
not hold those), and the cut that keeps the first 300 characters of the error comes after the scrub. When the scrub cannot run
the status and the log carry the exception's class and none of its words, and a log that cannot be written never reaches the
thread's hook with the exception it was raised while handling.
"""

from __future__ import annotations

import logging
import threading

import pytest

from src.database import connect
from src.jobs.background import BackgroundJob
from src.monitoring import secret_scrub as ss

HELD = "kQ7!vLm-it's-the-held-key"
ENV = "zR4#nPt-the-env-key"


@pytest.fixture
def both_held(monkeypatch):
    monkeypatch.setattr(connect, "_passphrase", HELD)
    monkeypatch.setenv("OO_DB_PASSPHRASE", ENV)


def _run(worker) -> dict:
    job = BackgroundJob("test-scrub", "T", worker)
    job.start()
    job._thread.join(5)
    return job.status()


def test_a_crash_that_quotes_a_passphrase_is_published_and_logged_without_it(both_held, caplog):
    caplog.set_level(logging.DEBUG, logger="jobs.background")

    def boom(ctx):
        raise RuntimeError(f"near PRAGMA key = '{HELD.replace(chr(39), chr(39) * 2)}': syntax error ({ENV})")

    st = _run(boom)
    assert st["state"] == "error"
    assert st["error"] == "RuntimeError: near PRAGMA key = '***redacted***': syntax error (***redacted***)"
    assert HELD not in caplog.text and ENV not in caplog.text and "it''s-the" not in caplog.text
    (record,) = [r for r in caplog.records if r.name == "jobs.background"]
    assert record.levelno == logging.WARNING and record.exc_info is None
    assert record.getMessage().startswith("background job test-scrub failed: RuntimeError: near PRAGMA key = '***redacted***'")


def test_the_cut_of_the_error_comes_after_the_scrub_so_a_passphrase_at_the_edge_leaves_no_half_of_it(both_held):
    lead = "x" * (300 - len("RuntimeError: ") - 5)  # the passphrase starts five characters before the cut

    def boom(ctx):
        raise RuntimeError(lead + HELD + " and more")

    error = _run(boom)["error"]
    assert len(error) == 300 and HELD[:5] not in error
    assert error.endswith(ss.REDACTED[:5]), "the cut fell inside the marker that replaced it, not inside the passphrase"


def test_a_crash_that_holds_no_passphrase_is_published_as_it_always_was(both_held):
    def boom(ctx):
        raise ValueError("kaboom")

    assert _run(boom)["error"] == "ValueError: kaboom"


def test_a_crash_whose_text_cannot_be_made_still_ends_the_job_as_an_error(both_held):
    class Broken(Exception):
        def __str__(self) -> str:
            raise ValueError("no text")

    def boom(ctx):
        raise Broken()

    st = _run(boom)
    assert st["state"] == "error" and st["error"] == "Broken: its text is withheld"


def test_the_error_is_scrubbed_through_the_helpers_of_secret_scrub(both_held, monkeypatch):
    """MUTATION TARGET: the call. The scrub is the one the rest of the commit uses, not a copy of it, and it is handed no
    secret of its own when the job was started with none (the held ones it takes out itself)."""
    seen = []
    real = ss.exception_text

    def spy(exc, *secrets, **kwargs):
        seen.append(secrets)
        return real(exc, *secrets, **kwargs)

    monkeypatch.setattr("src.jobs.background.exception_text", spy)

    def boom(ctx):
        raise RuntimeError("x")

    _run(boom)
    assert seen == [()]


KEY = "typed-key-q8W#zL-not-held"
MAILBOX = "mailbox-pw-Xk3!rT"


def _run_with(worker, **kwargs) -> dict:
    job = BackgroundJob("test-scrub-args", "T", worker)
    job.start(**kwargs)
    job._thread.join(5)
    return job.status()


def test_the_secrets_a_job_was_started_with_are_taken_out_of_its_error_and_its_log_though_the_process_holds_neither(
    both_held, caplog
):
    """A route hands a job the key it was typed (``passphrase=body.passphrase``, a mailbox's ``password``, ``**body.model_dump()``):
    the process holds none of them, so the nets that read what it holds are blind, and the exception an engine raises under
    the job can quote the statement that carried one. MUTATION TARGET: the secrets read off the job's own arguments, or any
    one of the writers (the status's error, the log's message, the log's traceback)."""
    caplog.set_level(logging.DEBUG, logger="jobs.background")

    def boom(ctx, passphrase, password, dest):
        raise RuntimeError(
            f"near PRAGMA key = '{KEY}': syntax error; the mailbox said {MAILBOX} for {dest}"
        )

    st = _run_with(boom, passphrase=KEY, password=MAILBOX, dest="/tmp/out")
    assert st["state"] == "error"
    assert st["error"] == "RuntimeError: near PRAGMA key = '***redacted***': syntax error; the mailbox said ***redacted*** for /tmp/out"
    (record,) = [r for r in caplog.records if r.name == "jobs.background"]
    written = [caplog.text, record.getMessage(), getattr(record, ss.TRACEBACK_ATTRIBUTE)]
    for text in written:
        assert KEY not in text and MAILBOX not in text, text
    assert "/tmp/out" in record.getMessage(), "what is not a secret is kept"


def test_a_secret_is_found_by_the_name_a_job_is_handed_it_under_and_a_string_that_is_not_one_is_left_alone(both_held):
    seen = []
    real = ss.exception_text

    def spy(exc, *secrets, **kwargs):
        seen.append(secrets)
        return real(exc, *secrets, **kwargs)

    def boom(ctx, **kwargs):
        raise RuntimeError("x")

    import src.jobs.background as bg

    original = bg.exception_text
    bg.exception_text = spy
    try:
        _run_with(
            boom,
            corpus_passphrase=KEY,
            Mailbox_Password=MAILBOX,
            api_key="k-" + KEY,
            label="a label",
            retries=3,
            password="",
            token=None,
            nested={"passphrase": "not read: only the top level is"},
        )
    finally:
        bg.exception_text = original
    assert [sorted(secrets) for secrets in seen] == [sorted((KEY, MAILBOX, "k-" + KEY))]


def test_an_error_whose_scrub_cannot_run_is_published_and_logged_as_its_class_alone(both_held, caplog, monkeypatch):
    """MUTATION TARGET: the words kept when the scrub cannot run, in the status AND in the log."""
    caplog.set_level(logging.DEBUG, logger="jobs.background")

    def broken(*args, **kwargs):
        raise ValueError("the scrub broke")

    monkeypatch.setattr("src.jobs.background.exception_text", broken)
    monkeypatch.setattr("src.jobs.background.log_failure", broken)

    def boom(ctx, passphrase):
        raise RuntimeError(f"near {KEY} and {HELD}")

    st = _run_with(boom, passphrase=KEY)
    assert st["state"] == "error" and st["error"] == "RuntimeError: its text is withheld"
    (record,) = [r for r in caplog.records if r.name == "jobs.background"]
    assert "RuntimeError" in record.getMessage() and "its text is withheld" in record.getMessage()
    assert KEY not in caplog.text and HELD not in caplog.text and record.exc_info is None


def test_a_job_whose_held_passphrases_cannot_be_read_is_published_and_logged_as_its_class_alone(caplog, monkeypatch):
    """The nets withhold what they cannot rule out: ``held_passphrases`` answers ``None``, so no text of the exception is kept."""
    caplog.set_level(logging.DEBUG, logger="jobs.background")
    monkeypatch.setattr(ss, "held_passphrases", lambda: None)

    def boom(ctx):
        raise RuntimeError(f"near PRAGMA key = '{KEY}'")

    st = _run(boom)
    assert st["error"] == "RuntimeError: its text is withheld"
    assert KEY not in caplog.text
    (record,) = [r for r in caplog.records if r.name == "jobs.background"]
    assert "RuntimeError: its text is withheld" in record.getMessage()


def test_a_log_that_cannot_be_written_ends_the_job_as_an_error_and_never_reaches_the_threads_hook(both_held, monkeypatch):
    """The record is written AFTER the handler and inside a catch, so a log that raises ends nowhere: the thread's excepthook
    prints what is raised AND the exception it was raised while handling, as it made its message.
    MUTATION TARGET: the catch around the log call (and, with it, the call moved back inside the handler)."""
    hooked = []
    monkeypatch.setattr(threading, "excepthook", lambda args: hooked.append(args))

    def broken(*args, **kwargs):
        raise OSError("the log is full")

    monkeypatch.setattr("src.jobs.background.log_failure", broken)

    def boom(ctx, passphrase):
        raise RuntimeError(f"near PRAGMA key = '{KEY}'")

    st = _run_with(boom, passphrase=KEY)
    assert st["state"] == "error" and KEY not in (st["error"] or "")
    assert hooked == [], "nothing was raised out of the job's thread"


def test_a_crash_with_a_unicode_error_in_its_chain_is_published_by_class_and_a_fixed_note(both_held, caplog):
    """The error a job publishes is the class and a fixed note when a ``UnicodeError`` (its text names a character and its offset)
    is the cause. MUTATION TARGET: the published text going through ``exception_text``."""
    caplog.set_level(logging.DEBUG, logger="jobs.background")

    def boom(ctx):
        try:
            "held\udcffkey".encode()
        except UnicodeError as inner:
            raise RuntimeError("could not encode the key") from inner

    st = _run(boom)
    assert st["state"] == "error"
    assert "UnicodeEncodeError" in st["error"] and "udcff" not in st["error"] and "position" not in st["error"], st["error"]
    assert "udcff" not in caplog.text and "position" not in caplog.text, caplog.text


def test_a_crash_that_is_the_encode_error_itself_is_published_by_class_and_a_fixed_note(both_held, caplog):
    """The shape that leaked: the worker's own exception is the ``UnicodeError`` (its text names the character and the offset),
    not the cause of another. MUTATION TARGET: the published text going through ``exception_text``."""
    caplog.set_level(logging.DEBUG, logger="jobs.background")

    def boom(ctx):
        ("held" + chr(0xDCFF)).encode()  # the frames print this line: no escape in the source

    st = _run(boom)
    assert st["state"] == "error"
    assert st["error"].startswith("UnicodeEncodeError: ") and "udcff" not in st["error"] and "position" not in st["error"], st["error"]
    assert "udcff" not in caplog.text and "position" not in caplog.text, caplog.text
