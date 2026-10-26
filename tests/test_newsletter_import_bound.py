"""POST /api/newsletters/import holds a bounded amount of mail in memory (audit E4, 2026-10-26).

The endpoint used to read every uploaded ``.eml`` whole into one list before parsing any of it, so
one request's memory was the sum of all the files plus the parse of the largest (measured: the
parse holds about 7.8 times the message). Now a file over ``_MAX_EML_BYTES`` is refused with 413
BEFORE anything is stored (fail closed, nothing half-imported, the body never read or echoed), and
messages are stored in rounds whose held bytes stay under ``_EML_BATCH_BYTES``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api import ingestion
from src.api.main import app

_MARK = b"SECRET-BODY-MARKER-4471"


def _eml(n: int, extra: bytes = b"") -> bytes:
    return (
        b"From: Reporter <r@news.example>\nTo: me@example.com\nSubject: Item %d\n"
        b"Message-ID: <bound-%d@news.example>\nDate: Mon, 05 Jan 2026 18:00:00 +0000\n"
        b"Content-Type: text/plain; charset=utf-8\n\nBody number %d of the bounded import.\n" % (n, n, n)
    ) + extra


def _post(files):
    with TestClient(app) as c:
        return c.post("/api/newsletters/import", files=[("files", (n, d, "message/rfc822")) for n, d in files])


def test_a_file_over_the_cap_is_skipped_unread_and_counted_while_the_rest_imports(monkeypatch):
    monkeypatch.setattr(ingestion, "_MAX_EML_BYTES", 2000)
    seen: list[list[bytes]] = []
    real = ingestion.ingest_emails

    def spy(db, source, batch, **kw):
        seen.append(list(batch))
        return real(db, source, batch, **kw)

    monkeypatch.setattr(ingestion, "ingest_emails", spy)
    r = _post([("small.eml", _eml(31)), ("big.eml", _eml(32, _MARK * 200))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tally"]["skipped_oversize"] == 1 and body["tally"]["stored"] == 1, body
    assert body["max_eml_bytes"] == 2000 and body["received"] == 2
    assert _MARK.decode() not in r.text, "the response must not echo any of the message"
    assert all(_MARK not in m for batch in seen for m in batch), "an oversize file must never reach the parser"


def test_files_are_stored_in_rounds_that_stay_under_the_batch_budget(monkeypatch):
    sizes = [len(_eml(i)) for i in range(12)]
    budget = sum(sizes[:3]) + 5          # three messages fit a round, a fourth does not
    monkeypatch.setattr(ingestion, "_EML_BATCH_BYTES", budget)
    rounds: list[list[int]] = []
    real = ingestion.ingest_emails

    def spy(db, source, batch, **kw):
        rounds.append([len(b) for b in batch])
        return real(db, source, batch, **kw)

    monkeypatch.setattr(ingestion, "ingest_emails", spy)
    r = _post([(f"m{i}.eml", _eml(i)) for i in range(12)])
    assert r.status_code == 200, r.text
    assert len(rounds) >= 3, rounds
    assert all(sum(rd) <= budget for rd in rounds), (budget, rounds)
    assert sum(len(rd) for rd in rounds) == 12
    tally = r.json()["tally"]
    assert tally["stored"] + tally["duplicate"] == 12, tally
    assert r.json()["received"] == 12


def test_a_single_message_larger_than_the_batch_budget_is_still_stored_alone(monkeypatch):
    monkeypatch.setattr(ingestion, "_EML_BATCH_BYTES", 10)
    rounds: list[int] = []
    real = ingestion.ingest_emails
    monkeypatch.setattr(ingestion, "ingest_emails", lambda db, s, batch, **k: rounds.append(len(batch)) or real(db, s, batch, **k))
    r = _post([("a.eml", _eml(101)), ("b.eml", _eml(102))])
    assert r.status_code == 200, r.text
    assert rounds == [1, 1], rounds


def test_no_eml_in_the_upload_still_answers_with_the_old_tally_shape(monkeypatch):
    r = _post([("notes.txt", b"not an email")])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tally"]["skipped_non_eml"] == 1 and body["tally"]["stored"] == 0
    assert body["tally"]["skipped_oversize"] == 0
    assert body["received"] == 1


def test_the_caps_are_the_measured_ones():
    mib = 1024 * 1024
    cap = ingestion._MAX_EML_BYTES
    assert cap >= 25 * mib, "must carry the largest message Gmail and Yahoo deliver (25 MiB)"
    assert cap * 8 <= 300 * mib, "parse holds about 7.8x the message; one message must stay near 281 MiB"
    assert cap * 2 > ingestion._EML_BATCH_BYTES
