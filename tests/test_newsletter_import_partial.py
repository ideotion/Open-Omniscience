"""A multi-round ``.eml`` import that fails midway (0.5.1 item 36, audit A-006's fix, PR #1486): a STATED LIMIT, pinned.

``POST /api/newsletters/import`` stores messages in rounds (``_EML_BATCH_BYTES``). Each round commits on its own, so when a later round fails the earlier
rounds STAY committed, and the reply is a 500 naming the storage failure with NO tally of what was stored. The same was already true of the 200-row commits
inside ``ingest_emails``. This is deliberate and recorded in docs/product/RELEASE_0.5_GATE.md item 36: a re-import of the same files is idempotent because a
duplicate is recognised, so the repair for a failed import is to run it again. These tests pin what is true TODAY, so a change to it (a partial tally in the
reply, or a rollback of the earlier rounds) is a decision that has to edit them, not a drift.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import ingestion
from src.api.main import app


def _eml(n: int) -> bytes:
    return (
        b"From: Reporter <r@news.example>\nTo: me@example.com\nSubject: Partial %d\n"
        b"Message-ID: <partial-%d@news.example>\nDate: Mon, 05 Jan 2026 18:00:00 +0000\n"
        b"Content-Type: text/plain; charset=utf-8\n\nBody number %d of the partial import.\n" % (n, n, n)
    )


def _files(numbers):
    return [("files", (f"p{n}.eml", _eml(n), "message/rfc822")) for n in numbers]


def _imported(c: TestClient) -> int:
    return c.get("/api/newsletters/imported-count").json()["count"]


def test_a_failed_later_round_leaves_the_earlier_rounds_stored_and_answers_500_without_a_tally(monkeypatch):
    numbers = [9001, 9002, 9003, 9004]
    monkeypatch.setattr(ingestion, "_EML_BATCH_BYTES", len(_eml(9001)) * 2 + 5)  # two messages fit a round
    real = ingestion.ingest_emails
    calls: list[int] = []

    def fail_on_the_second_round(db, source, batch, **kw):
        calls.append(len(batch))
        if len(calls) == 2:
            raise RuntimeError("the second round failed")
        return real(db, source, batch, **kw)

    monkeypatch.setattr(ingestion, "ingest_emails", fail_on_the_second_round)
    with TestClient(app) as c:
        before = _imported(c)
        r = c.post("/api/newsletters/import", files=_files(numbers))
        assert calls == [2, 2], calls
        assert r.status_code == 500, r.text
        detail = r.json()["detail"]
        assert "failed while storing" in detail, detail
        assert set(r.json()) == {"detail"} and "stored" not in detail.lower() and "tally" not in detail.lower(), (
            "if the reply now carries a partial tally (as a key or inside the detail), this is the test to update (item 36)"
        )
        assert _imported(c) == before + 2, "the first round is committed and stays"


def test_a_re_import_after_the_failure_stores_only_what_is_missing(monkeypatch):
    numbers = [9101, 9102, 9103, 9104]
    monkeypatch.setattr(ingestion, "_EML_BATCH_BYTES", len(_eml(9101)) * 2 + 5)
    real = ingestion.ingest_emails
    calls: list[int] = []

    def fail_once(db, source, batch, **kw):
        calls.append(len(batch))
        if len(calls) == 2:
            raise RuntimeError("the second round failed")
        return real(db, source, batch, **kw)

    monkeypatch.setattr(ingestion, "ingest_emails", fail_once)
    with TestClient(app) as c:
        before = _imported(c)
        assert c.post("/api/newsletters/import", files=_files(numbers)).status_code == 500
        monkeypatch.setattr(ingestion, "ingest_emails", real)
        again = c.post("/api/newsletters/import", files=_files(numbers))
        assert again.status_code == 200, again.text
        tally = again.json()["tally"]
        assert tally["duplicate"] == 2 and tally["stored"] == 2, tally
        assert _imported(c) == before + 4


def _plain(mid: str, body: str) -> bytes:
    return (
        f"From: Reporter <r@news.example>\nTo: me@example.com\nSubject: {mid}\n"
        f"Message-ID: <{mid}@news.example>\nDate: Mon, 05 Jan 2026 18:00:00 +0000\n"
        f"Content-Type: text/plain; charset=utf-8\n\n{body}\n"
    ).encode()


def _session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, Source

    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    src = Source(name="N", domain="nl.test")
    s.add(src)
    s.commit()
    return s, src


def test_a_failure_inside_one_round_keeps_the_earlier_batches_loses_its_own_and_raises_without_a_tally():
    """The same limit one level down: ``ingest_emails`` commits every ``commit_batch`` rows (the endpoint's 200). A batch whose commit fails with something that is
    neither a lock nor an integrity collision is rolled back and RAISED: the batches before it stay committed, the batch itself and the rest of the round are not
    stored, and the tally of what was stored is lost with the exception (0.5.1 item 36). A lock or a collision is NOT this case: it is redone one message at a time."""
    from src.database.models import Article
    from src.ingest.email import ingest_emails

    s, src = _session()
    msgs = [_plain(f"m{i}", f"body number {i} about topic {i}") for i in range(1, 6)]
    real_commit = s.commit

    calls = {"n": 0}

    def commit_failing_on_the_second_batch():
        calls["n"] += 1  # ingest_emails commits once per batch on this path (these bodies have no links, so nothing else commits)
        if calls["n"] == 2:
            raise RuntimeError("the second batch failed to commit")
        return real_commit()

    s.commit = commit_failing_on_the_second_batch  # type: ignore[method-assign]
    try:
        ingest_emails(s, src, msgs, commit_batch=2)
    except RuntimeError as exc:
        assert "second batch" in str(exc)
    else:
        raise AssertionError("an unexpected commit failure must surface, never be swallowed into a tally")
    assert s.query(Article).count() == 2, "the first batch (m1, m2) is committed and stays; m3, m4 (the failed batch) and m5 are not stored"
    s.commit = real_commit  # type: ignore[method-assign]
    again = ingest_emails(s, src, msgs, commit_batch=2)
    assert again["stored"] == 3 and again["duplicate"] == 2, again
    assert s.query(Article).count() == 5


def _collide_or_lock(kind: str):
    from sqlalchemy.exc import IntegrityError, OperationalError

    if kind == "collision":
        return IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed: articles.hash"))
    return OperationalError("COMMIT", {}, Exception("database is locked"))


@pytest.mark.parametrize("kind", ["collision", "lock"])
def test_a_lock_or_collision_in_a_batch_is_redone_one_message_at_a_time_not_raised(kind):
    """The contrast that makes the pin above mean something: an integrity error OR a lock on a batch commit does NOT escape; the batch is redone per message.

    The commit is counted by call: on this path ``_flush`` is the only caller (the bodies have no links, so ``_maybe_index_email_links`` does not commit, and
    ``_attach_target`` only flushes), so the first call is the first batch's."""
    from src.database.models import Article, Source
    from src.ingest.email import ingest_emails

    s, src = _session()
    msgs = [_plain(f"c{i}", f"collision body {i} about subject {i}") for i in range(1, 5)]
    real_commit = s.commit
    state = {"raised": False}

    def fail_once():
        if not state["raised"]:
            state["raised"] = True
            raise _collide_or_lock(kind)
        return real_commit()

    s.commit = fail_once  # type: ignore[method-assign]
    tally = ingest_emails(s, src, msgs, commit_batch=2)
    assert state["raised"]
    assert tally["stored"] == 4 and tally["duplicate"] == 0, tally
    assert s.query(Article).count() == 4
    assert s.query(Source).filter(Source.domain == "news.example").count() == 1, "the publisher source is re-created once after the rollback, not per message"
