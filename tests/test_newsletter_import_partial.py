"""A multi-round ``.eml`` import that fails midway (0.5.1 item 36, audit A-006's fix, PR #1486): a STATED LIMIT, pinned.

``POST /api/newsletters/import`` stores messages in rounds (``_EML_BATCH_BYTES``). Each round commits on its own, so when a later round fails the earlier
rounds STAY committed, and the reply is a 500 naming the storage failure with NO tally of what was stored. The same was already true of the 200-row commits
inside ``ingest_emails``. This is deliberate and recorded in docs/product/RELEASE_0.5_GATE.md item 36: a re-import of the same files is idempotent because a
duplicate is recognised, so the repair for a failed import is to run it again. These tests pin what is true TODAY, so a change to it (a partial tally in the
reply, or a rollback of the earlier rounds) is a decision that has to edit them, not a drift.
"""

from __future__ import annotations

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
