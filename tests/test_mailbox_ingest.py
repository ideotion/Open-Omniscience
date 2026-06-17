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


def test_mailbox_endpoint_ingests_anonymised(client, monkeypatch):
    c, Sess = client
    clear_kill_switch()
    # Mock the live fetch to return our sample email (no network).
    import src.api.ingestion as ing
    monkeypatch.setattr(ing, "fetch_mailbox", lambda *a, **k: [_EML])

    r = c.post("/api/newsletters/mailbox",
               json={"protocol": "imap", "host": "mail.example", "user": "me", "password": "pw"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fetched"] == 1 and body["source"] == "Imported mailbox (IMAP/POP3)"
    assert "anonymised at ingest" in body["disclosure"]

    # The stored article is anonymised: the recipient address is NOT in the corpus.
    with Sess() as s:
        arts = s.query(Article).all()
        assert arts, "the newsletter should be stored"
        blob = " ".join((a.content or "") + " " + (a.title or "") for a in arts)
        assert "victim@personal.example" not in blob  # recipient redacted, never stored
        src = s.query(Source).filter_by(domain="mailbox.import.local").first()
        assert src is not None and src.enabled is False  # disabled, filterable bucket


def test_mailbox_endpoint_refuses_under_airplane(client):
    c, _ = client
    activate_kill_switch()
    try:
        r = c.post("/api/newsletters/mailbox",
                   json={"protocol": "imap", "host": "mail.example", "user": "me", "password": "pw"})
        assert r.status_code == 409 and "airplane" in r.json()["detail"].lower()
    finally:
        clear_kill_switch()
