"""A background job that fails publishes the failure's text as its ``error`` (``/api/jobs``, the task manager) and logs the
exception. An engine's error can quote the statement that held the key, so both are written with every passphrase the process
holds taken out of them, and the cut that keeps the first 300 characters of the error comes after the scrub.
"""

from __future__ import annotations

import logging

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
    """MUTATION TARGET: the call. The scrub is the one the rest of the commit uses, not a copy of it."""
    seen = []
    real = ss.scrubbed

    def spy(text, *secrets):
        seen.append(secrets)
        return real(text, *secrets)

    monkeypatch.setattr("src.jobs.background.scrubbed", spy)

    def boom(ctx):
        raise RuntimeError("x")

    _run(boom)
    assert seen and seen[0] == (HELD, ENV)
