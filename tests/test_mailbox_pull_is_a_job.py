"""The live mailbox pull is a task-manager job, not a frozen request.

The docket asked for this: a live IMAP/POP3 pull is a network fetch of up to `limit`
messages followed by a full anonymise-and-store pass, and it ran that whole body
SYNCHRONOUSLY in the request handler. Three consequences, all of them the project's own
stated concerns rather than tidiness:

  * it held a Starlette threadpool token AND the single-writer gate for the whole run,
    which is the FastAPI-freeze lesson `src/jobs/background.py` exists for;
  * `/api/jobs` could not enumerate it, so the operator had no way to SEE that a network
    pull to their mail provider was in flight -- on a surface whose entire honesty claim
    is that egress is visible;
  * the task manager's controls could not reach it.

The behaviour is tested in `tests/test_mailbox_ingest.py` (it runs the real worker and
asserts the anonymisation still holds, the in-flight job is listed while running, and a
failure never carries the password). THIS file is the source-level guard: the wiring is
easy to unpick by accident during a refactor, and a behaviour test cannot say "and it is
still registered as a writer".
"""

from __future__ import annotations

import inspect

from tests.js_source_helper import app_js, assert_absent, assert_present, function_source


def test_the_endpoint_starts_a_job_and_exposes_a_status_route():
    import src.api.ingestion as ing

    src = inspect.getsource(ing)
    assert 'BackgroundJob("mailbox-pull"' in src, "the job kind must be declared here"
    assert "_MAILBOX_JOB.start(" in src, "the endpoint must START the job, not do the work"
    assert '@router.get("/newsletters/mailbox/status")' in src, "a status route must exist"

    handler = inspect.getsource(ing.import_mailbox)
    assert "fetch_mailbox(" not in handler, (
        "the request handler must not fetch: that is what froze the app for minutes"
    )
    assert "ingest_emails(" not in handler, "nor store -- the worker owns both"


def test_it_is_registered_as_a_db_writer_so_it_arbitrates():
    from src.api.jobs import _DB_WRITER_KINDS
    from src.jobs.background import get_job

    job = get_job("mailbox-pull")
    assert job is not None, "an unregistered job is invisible to /api/jobs"
    assert job.is_writer is True, "it writes Articles; it must take the writer gate per unit"
    assert "mailbox-pull" in _DB_WRITER_KINDS


def test_the_refusals_that_need_no_socket_stay_in_the_request():
    """Starting a job must not turn a synchronous, network-free refusal into a polled
    error. The airplane refusal in particular is named as the KILL SWITCH (#14e
    corollary) rather than reported as the mail provider failing."""
    import src.api.ingestion as ing

    handler = inspect.getsource(ing.import_mailbox)
    assert "kill_switch_active()" in handler, "the airplane check must precede the job"
    assert "status_code=409" in handler
    assert "kill switch" in handler, "the refusal must NAME the kill switch (#14e corollary)"
    assert "status_code=422" in handler, "protocol/host validation stays synchronous"
    assert handler.index("kill_switch_active()") > handler.index("status_code=422"), (
        "validate before touching the network gate, as the sibling handlers do"
    )


def test_the_password_is_scrubbed_where_the_error_is_captured():
    import src.api.ingestion as ing

    worker = inspect.getsource(ing._mailbox_pull_worker)
    assert "_scrub(" in worker, (
        "a mail library's exception is the server's own chatter; /api/jobs is "
        "unauthenticated, so scrub at capture rather than trust the message"
    )
    assert ing._scrub("LOGIN me s3cret", "s3cret") == "LOGIN me ***"
    assert ing._scrub("nothing to hide", "") == "nothing to hide"


def test_the_frontend_reads_the_tally_from_the_status_not_the_start_response():
    """The start response's `result` is null by construction. A frontend that kept
    reading `d.tally` would render a confident row of zeros -- the failure mode the
    house `_jobStillRunning` helper exists to prevent."""
    pull = function_source(app_js(), "pullMailbox")
    assert_present(pull, "pollJobStatus(", why="the pull must poll its job to completion")
    assert_present(pull, "/api/newsletters/mailbox/status", why="poll the status route")
    assert_present(pull, "_jobStillRunning(", why="stopped watching is not finished")
    assert_absent(pull, "d.tally", why="the start response carries no tally")
    assert_present(pull, "st.result", why="the tally comes from the finished job")
    assert_present(pull, "ensureOnline(", why="still a network action (invariant #14)")
    assert_present(pull, 'mbox-pass").value = ""', why="never keep the password in the field")
