"""Live mailbox ingestion over IMAP / POP3 (ruling 2026-06-17 #11).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pulls newsletters live and routes them through the EXISTING anonymise-at-ingest core.
These tests pin the guardrails with ZERO real network (injected connection): newest-first
bounded fetch, the airplane gate (offline -> NO socket, the connection is never touched),
protocol dispatch, and the endpoint storing anonymised articles under a disabled,
filterable mailbox source while refusing under airplane mode.
"""

from __future__ import annotations

import contextlib
import json
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.ingest import activate_kill_switch, clear_kill_switch
from src.ingest.email import fetch_imap, fetch_mailbox, fetch_pop3

_EML = (
    b"From: News <news@example.com>\r\n"
    b"To: victim@personal.example\r\n"
    b"Subject: Weekly digest\r\n"
    b"Date: Tue, 17 Jun 2026 10:00:00 +0000\r\n"
    b"Message-ID: <abc@example.com>\r\n"
    b"\r\nHello victim@personal.example, here is your digest.\r\n"
)


class _FakeImap:
    def __init__(self, msgs):
        self.msgs = msgs
        self.touched = False

    def select(self, folder):
        self.touched = True

    def search(self, charset, criteria):
        self.touched = True
        return ("OK", [b" ".join(str(i + 1).encode() for i in range(len(self.msgs)))])

    def fetch(self, mid, parts):
        self.touched = True
        return ("OK", [(b"%s (RFC822" % mid, self.msgs[int(mid) - 1])])

    def logout(self):
        pass


class _FakePop:
    def __init__(self, msgs):
        self.msgs = msgs
        self.touched = False

    def list(self):
        self.touched = True
        return (b"+OK", [b"%d 100" % (i + 1) for i in range(len(self.msgs))])

    def retr(self, i):
        self.touched = True
        return (b"+OK", self.msgs[i - 1].split(b"\r\n"), 100)

    def quit(self):
        pass


@pytest.fixture(autouse=True)
def _net():
    clear_kill_switch()
    yield
    clear_kill_switch()


def test_fetch_imap_returns_newest_bounded():
    msgs = [b"m%d" % i for i in range(5)]
    fake = _FakeImap(msgs)
    raws = fetch_imap("h", "u", "p", limit=2, conn=fake)
    # newest two (ids 4,5 -> indexes 3,4), reversed not required by this impl (tail of ids)
    assert raws == [b"m3", b"m4"]


def test_fetch_pop3_returns_tail():
    msgs = [b"a\r\nb", b"c\r\nd", b"e\r\nf"]
    raws = fetch_pop3("h", "u", "p", limit=2, conn=_FakePop(msgs))
    assert raws == [b"c\r\nd", b"e\r\nf"]  # newest two, rejoined


def test_airplane_mode_opens_no_socket():
    fake = _FakeImap([b"x"])
    activate_kill_switch()
    try:
        with pytest.raises(RuntimeError, match="airplane"):
            fetch_imap("h", "u", "p", conn=fake)
        # The injected connection was NEVER touched (no select/search/fetch).
        assert fake.touched is False
        fakep = _FakePop([b"y"])
        with pytest.raises(RuntimeError, match="airplane"):
            fetch_pop3("h", "u", "p", conn=fakep)
        assert fakep.touched is False
    finally:
        clear_kill_switch()


def test_fetch_mailbox_dispatch():
    assert fetch_mailbox("imap", "h", "u", "p", conn=_FakeImap([b"z"])) == [b"z"]
    assert fetch_mailbox("pop3", "h", "u", "p", conn=_FakePop([b"w"])) == [b"w"]
    with pytest.raises(ValueError):
        fetch_mailbox("smtp", "h", "u", "p")


@pytest.fixture()
def client(tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'mbox.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            yield c, Sess
    finally:
        app.dependency_overrides.clear()


@contextlib.contextmanager
def _scope_over(Sess):
    """A ``session_scope``-shaped context over the fixture's engine.

    The pull now runs on a background thread, and a worker thread cannot use FastAPI's
    request-scoped ``get_db`` override -- it opens its OWN session, as every other
    background writer does. The worker imports ``session_scope`` INSIDE its body, so
    pointing the module attribute at the fixture's engine is enough to keep the
    end-to-end anonymisation assertions below testing the real path.
    """
    s = Sess()
    try:
        yield s
        s.commit()
    finally:
        s.close()


def _run_pull(c, ing, Sess, monkeypatch, *, password="pw", fetch=None):
    """POST the pull, then wait for its worker. Returns the response body."""
    monkeypatch.setattr(ing, "fetch_mailbox", fetch or (lambda *a, **k: [_EML]))
    monkeypatch.setattr(
        "src.database.session.session_scope", lambda: _scope_over(Sess)
    )
    r = c.post("/api/newsletters/mailbox",
               json={"protocol": "imap", "host": "mail.example", "user": "me",
                     "password": password})
    assert r.status_code == 200, r.text
    t = ing._MAILBOX_JOB._thread
    if t is not None:
        t.join(10)
        assert not t.is_alive(), "the mailbox worker did not finish"
    return r.json()


def test_mailbox_endpoint_ingests_anonymised(client, monkeypatch):
    c, Sess = client
    clear_kill_switch()
    import src.api.ingestion as ing

    body = _run_pull(c, ing, Sess, monkeypatch)
    assert body["started"] is True
    assert body["job"]["kind"] == "mailbox-pull"
    assert "anonymised at ingest" in body["disclosure"]

    st = c.get("/api/newsletters/mailbox/status").json()
    assert st["state"] == "done", st
    assert st["result"]["fetched"] == 1
    assert st["result"]["source"] == "Imported mailbox (IMAP/POP3)"

    # The stored article is anonymised: the recipient address is NOT in the corpus.
    with Sess() as s:
        arts = s.query(Article).all()
        assert arts, "the newsletter should be stored"
        blob = " ".join((a.content or "") + " " + (a.title or "") for a in arts)
        assert "victim@personal.example" not in blob  # recipient redacted, never stored
        src = s.query(Source).filter_by(domain="mailbox.import.local").first()
        assert src is not None and src.enabled is False  # disabled, filterable bucket


def test_the_pull_is_a_task_manager_job_the_operator_can_see(client, monkeypatch):
    """It ran its whole multi-minute body in the request handler, so it froze the app
    and /api/jobs could not show it at all -- the operator had no way to see that a
    network pull was in flight, and the task manager's Stop could not reach it."""
    from src.api.jobs import _DB_WRITER_KINDS
    from src.jobs.background import get_job

    c, Sess = client
    clear_kill_switch()
    import src.api.ingestion as ing

    assert get_job("mailbox-pull") is not None, "the job kind must be registered"
    assert "mailbox-pull" in _DB_WRITER_KINDS, "it writes articles; it must arbitrate"

    # Observed WHILE THE PULL IS IN FLIGHT, which is the only moment the claim means
    # anything: /api/jobs deliberately lists running + failed, so joining the worker
    # first would let a synchronous implementation pass this too.
    entered, release = threading.Event(), threading.Event()

    def _slow_fetch(*a, **k):
        entered.set()
        release.wait(10)
        return [_EML]

    monkeypatch.setattr(ing, "fetch_mailbox", _slow_fetch)
    monkeypatch.setattr("src.database.session.session_scope", lambda: _scope_over(Sess))
    r = c.post("/api/newsletters/mailbox",
               json={"protocol": "imap", "host": "mail.example", "user": "me", "password": "pw"})
    assert r.status_code == 200, r.text
    try:
        assert entered.wait(10), "the worker never started"
        # The request already came back -- a synchronous handler could not have.
        jobs = c.get("/api/jobs").json().get("jobs", [])
        mine = [j for j in jobs if j.get("kind") == "mailbox-pull"]
        assert mine, f"the in-flight pull must be enumerable in /api/jobs; saw {jobs}"
        assert mine[0]["state"] == "running"
        assert mine[0]["actions"] == [], "an opaque worker must not advertise Cancel"
    finally:
        release.set()
        t = ing._MAILBOX_JOB._thread
        if t is not None:
            t.join(10)


def test_the_job_offers_no_cancel_it_cannot_honour(client):
    """`fetch_mailbox` is one opaque imaplib/poplib call and `ingest_emails` loops with
    no ctx, so nothing checks ctx.stopping. A Cancel button here would be theater --
    the background-job module's own docstring rules that out, so pin it."""
    import src.api.ingestion as ing

    assert ing._MAILBOX_JOB.cancellable is False


def test_a_failed_pull_never_puts_the_password_in_the_job_status(client, monkeypatch):
    """`status()` does not expose the worker's kwargs, so the credential itself stays on
    the thread -- but it DOES expose `error`, and a mail library's exception is the
    server's own chatter. /api/jobs is unauthenticated, so the message is scrubbed where
    it is captured rather than trusted."""
    c, Sess = client
    clear_kill_switch()
    import src.api.ingestion as ing

    secret = "hunter2-s3cret"

    def _boom(*a, **k):
        raise RuntimeError(f"LOGIN me {secret} failed")

    _run_pull(c, ing, Sess, monkeypatch, password=secret, fetch=_boom)
    st = c.get("/api/newsletters/mailbox/status").json()
    assert st["state"] == "error"
    assert secret not in (st["error"] or ""), "the password reached the job status"
    assert "***" in st["error"]
    assert secret not in json.dumps(c.get("/api/jobs").json())


def test_the_network_free_refusals_still_answer_synchronously(client):
    """Starting a job must not swallow the checks that need no socket: an unknown
    protocol and a missing host are still an immediate 422, not a polled job error."""
    c, _ = client
    clear_kill_switch()
    r = c.post("/api/newsletters/mailbox",
               json={"protocol": "smtp", "host": "mail.example", "user": "me", "password": "pw"})
    assert r.status_code == 422 and "protocol" in r.json()["detail"]
    r = c.post("/api/newsletters/mailbox",
               json={"protocol": "imap", "host": "  ", "user": "me", "password": "pw"})
    assert r.status_code == 422


def test_mailbox_endpoint_refuses_under_airplane(client):
    c, _ = client
    activate_kill_switch()
    try:
        r = c.post("/api/newsletters/mailbox",
                   json={"protocol": "imap", "host": "mail.example", "user": "me", "password": "pw"})
        detail = r.json()["detail"].lower()
        assert r.status_code == 409 and "airplane" in detail
        # #14e corollary: a refusal BY THE KILL SWITCH is named as such, never
        # reported as someone else's server failing.
        assert "kill switch" in detail
    finally:
        clear_kill_switch()
