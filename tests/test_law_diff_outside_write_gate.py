"""H1-3 (WAL lane audit, 2026-11-07): the changed-document path of ``track_document`` computes
its difflib over the full texts with the single-writer gate FREE.

The audit read the SELECT at ``track.py`` ``seen = ...`` as an autoflush that takes the gate
before ``_diff_anchor`` / ``_diff`` run. It does not: ``SessionLocal`` is ``autoflush=False``
(the same property that refutes F14, tests/test_write_gate_riders.py), so nothing reaches the
database, and nothing takes the gate, until the explicit ``session.flush()`` that follows the
diff. This pins the ORDER so a refactor (an autoflush session, a flush moved above the diff)
cannot quietly put a CPU-bound diff of up to 10 MiB inside the gate.

The negative twin proves the revision still passes THROUGH the gate: "the diff ran unheld" is
satisfied just as well by a gate that is never taken."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from src.database.models import LawDocument, LawRevision
from src.database.session import init_db, session_scope
from src.database.writer import write_gate, write_lock
from src.ingest import FetchResult
from src.law import track as track_mod
from src.law.track import track_document

_BODY = " ".join(f"Section {i}: every person shall have the right to liberty." for i in range(40))


class _Fetcher:
    page = ""

    def fetch(self, url, *, require_html=True, **_kw):
        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            content=self.page,
            content_type="text/html",
            fetched_at=datetime.now(UTC),
        )


def _html(body):
    return f"<html><head><title>Act</title></head><body><main>{body}</main></body></html>"


def _second_thread_can_take_the_gate() -> bool:
    got: list[bool] = []

    def other():
        with write_lock(timeout=2):
            got.append(True)

    t = threading.Thread(target=other)
    t.start()
    t.join(5)
    return bool(got)


def test_the_diff_and_its_anchor_run_with_the_write_gate_free(monkeypatch):
    init_db()
    seen: dict[str, tuple[bool, bool]] = {}
    for name in ("_diff_anchor", "_diff"):
        real = getattr(track_mod, name)

        def probe(*a, _real=real, _name=name, **k):
            seen[_name] = (write_gate.stats()["held"], _second_thread_can_take_the_gate())
            return _real(*a, **k)

        monkeypatch.setattr(track_mod, name, probe)

    fetcher = _Fetcher()
    with session_scope() as s:
        doc = LawDocument(jurisdiction="uk", title="Act", url="https://h13.example/act")
        s.add(doc)
        s.commit()
        fetcher.page = _html(_BODY)
        assert track_document(s, fetcher, doc)["status"] == "baseline"
        grants_before = write_gate.stats()["grants"]
        fetcher.page = _html(_BODY + " Amendment: a new clause is substituted here.")
        assert track_document(s, fetcher, doc)["status"] == "changed"
        assert s.query(LawRevision).filter_by(document_id=doc.id).count() == 2

    assert set(seen) == {"_diff_anchor", "_diff"}
    assert all(held is False and free for held, free in seen.values()), seen
    assert write_gate.stats()["grants"] > grants_before  # the revision itself went through the gate
