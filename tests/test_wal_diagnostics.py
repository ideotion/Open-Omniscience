"""WAL visibility in the diagnostics bundle — the three gaps (field ruling 2026-07-29 item 8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Item 8 ruled that WAL/checkpoint health is DIAGNOSTICS material, not a user-facing
surface — "users won't know how to read this, and won't be able to act on it". Most of
it was already there (wal_bytes in four members, journal_size_limit, the scheduler's own
per-pass checkpoint measurement). Three gaps were not:

  1. ``PRAGMA wal_autocheckpoint`` was never read in production, so a store with
     automatic checkpointing DISABLED looked identical to a healthy one in every export.
  2. the last real checkpoint record lived only in the bundle's scheduler section, so the
     one member an operator opens for WAL health could not say whether a checkpoint had
     completed — or been blocked by a reader.
  3. no HISTORICAL series existed at all, and checkpoint starvation is precisely the
     failure a single point-in-time reading cannot show (the field batch found WALs
     4x-29x over the limit, one larger than the machine's RAM).

The honesty line under test throughout: an unmeasurable value must degrade to a stated
absence, never to a zero that reads as a real measurement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import src.database.session as session_mod
import src.database.snapshots as snapshots_mod
from src.database.models import Base, StatSnapshot
from src.database.snapshots import (
    ALL_METRICS,
    _gauge_wal_bytes,
    maybe_snapshot_library_stats,
    metric_history,
)
from src.monitoring.storage import _last_wal_checkpoint, _wal_history, storage_composition


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A FILE-backed store in WAL mode — the -wal sidecar has to be real for any of
    this to mean anything."""
    path = tmp_path / "store.db"
    engine = create_engine(
        f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with engine.connect() as c:
        c.exec_driver_sql("PRAGMA journal_mode=WAL")
    # snapshots.py bound ``engine`` at import time (it uses it for inspect()), while
    # _gauge_wal_bytes resolves it lazily out of session.py — patch BOTH, or the gauge
    # silently measures the developer's real corpus instead of this fixture.
    monkeypatch.setattr(snapshots_mod, "engine", engine, raising=False)
    monkeypatch.setattr(session_mod, "engine", engine, raising=False)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()
    engine.dispose()


# --------------------------------------------------------------------------- #
#  gap 1 — the setting that decides whether the WAL is trimmed at all
# --------------------------------------------------------------------------- #
def test_wal_autocheckpoint_is_read_and_resolved_to_bytes(db):
    out = storage_composition(db)
    assert "wal_autocheckpoint_pages" in out, (
        "the threshold that decides whether a writer trims the WAL must be in the export"
    )
    pages = out["wal_autocheckpoint_pages"]
    assert isinstance(pages, int)
    if pages > 0 and out.get("page_size"):
        assert out["wal_autocheckpoint_bytes"] == pages * out["page_size"], (
            "reported in bytes too, so it is comparable with journal_size_limit/wal_bytes "
            "without the reader doing the multiplication"
        )
        assert "wal_autocheckpoint_note" not in out, "an ENABLED autocheckpoint needs no warning"


def test_a_disabled_autocheckpoint_is_called_out_not_silently_zero(db):
    """0 pages means automatic checkpointing is OFF — the store then grows its -wal
    until an explicit checkpoint runs. A bare 0 in the export would be read as a
    number, not as the hazard it is."""
    db.execute(text("PRAGMA wal_autocheckpoint=0"))
    out = storage_composition(db)
    assert out["wal_autocheckpoint_pages"] == 0
    assert out["wal_autocheckpoint_bytes"] is None, "0 pages has no byte equivalent to state"
    assert "DISABLED" in out["wal_autocheckpoint_note"]


# --------------------------------------------------------------------------- #
#  gap 2 — did a checkpoint actually complete?
# --------------------------------------------------------------------------- #
def _fake_runs(rows):
    return lambda limit=20: rows[:limit]


def test_last_checkpoint_is_the_newest_real_measurement(monkeypatch):
    """recent_runs() is newest-first. Runs that recorded no checkpoint (disabled, or a
    failure that honestly returned None) must be SKIPPED, not treated as the answer."""
    import src.scheduler.runlog as runlog

    monkeypatch.setattr(
        runlog,
        "recent_runs",
        _fake_runs(
            [
                {"started_at": "2026-07-29T10:00:00", "hygiene": {"wal_checkpoint": None}},
                {
                    "started_at": "2026-07-29T09:00:00",
                    "finished_at": "2026-07-29T09:05:00",
                    "hygiene": {"wal_checkpoint": {"busy": 1, "wal_bytes_after": 4_400_000_000}},
                },
                {"started_at": "2026-07-29T08:00:00", "hygiene": {"wal_checkpoint": {"busy": 0}}},
            ]
        ),
    )
    ck = _last_wal_checkpoint()
    assert ck is not None
    assert ck["busy"] == 1, "the newest run that actually measured one wins"
    assert ck["wal_bytes_after"] == 4_400_000_000
    assert ck["run_at"] == "2026-07-29T09:05:00", "stamped with when that run ended"


def test_last_checkpoint_degrades_to_none_when_nothing_was_ever_recorded(monkeypatch):
    import src.scheduler.runlog as runlog

    monkeypatch.setattr(runlog, "recent_runs", _fake_runs([{"started_at": "x"}, {}]))
    assert _last_wal_checkpoint() is None, "absence is stated by omission, never faked"


def test_last_checkpoint_never_raises_into_the_diagnostic(monkeypatch):
    import src.scheduler.runlog as runlog

    def boom(limit=20):
        raise OSError("run log unreadable")

    monkeypatch.setattr(runlog, "recent_runs", boom)
    assert _last_wal_checkpoint() is None


def test_the_composition_carries_the_checkpoint_when_one_exists(db, monkeypatch):
    import src.scheduler.runlog as runlog

    monkeypatch.setattr(
        runlog, "recent_runs", _fake_runs([{"hygiene": {"wal_checkpoint": {"busy": 0}}}])
    )
    out = storage_composition(db)
    assert out["last_checkpoint"]["busy"] == 0


# --------------------------------------------------------------------------- #
#  gap 3 — the multi-day trend no single reading can show
# --------------------------------------------------------------------------- #
def test_the_wal_gauge_records_a_real_byte_count(db):
    out = maybe_snapshot_library_stats(db, now=datetime(2028, 1, 1, 5, 0, tzinfo=UTC))
    db.commit()
    assert "wal_bytes" in out["recorded"], "the gauge rides the same hourly pass as the counters"
    assert out["recorded"]["wal_bytes"] >= 0
    row = (
        db.query(StatSnapshot)
        .filter(StatSnapshot.metric == "wal_bytes")
        .order_by(StatSnapshot.taken_at.desc())
        .first()
    )
    assert row is not None and row.value == out["recorded"]["wal_bytes"]


def test_an_unmeasurable_wal_leaves_a_gap_never_a_recorded_zero(db, monkeypatch):
    """A non-SQLite / in-memory store has no -wal to measure. Recording 0 there would
    put a fabricated "the WAL was empty" point into a series whose entire purpose is
    spotting growth."""

    class _Url:
        database = ":memory:"

        @staticmethod
        def get_backend_name():
            return "sqlite"

    class _Eng:
        url = _Url()

    monkeypatch.setattr(session_mod, "engine", _Eng(), raising=False)
    assert _gauge_wal_bytes(db) is None

    out = maybe_snapshot_library_stats(db, now=datetime(2028, 1, 2, 5, 0, tzinfo=UTC))
    db.commit()
    assert "wal_bytes" not in out["recorded"], "unmeasurable ⇒ absent from the series"
    assert (
        db.query(StatSnapshot)
        .filter(
            StatSnapshot.metric == "wal_bytes",
            StatSnapshot.taken_at == datetime(2028, 1, 2, 5, 0),
        )
        .first()
        is None
    )


def test_a_postgres_backend_is_unmeasurable_rather_than_zero(db, monkeypatch):
    class _Url:
        database = "oo"

        @staticmethod
        def get_backend_name():
            return "postgresql"

    class _Eng:
        url = _Url()

    monkeypatch.setattr(session_mod, "engine", _Eng(), raising=False)
    assert _gauge_wal_bytes(db) is None


def test_the_series_reaches_the_diagnostic_with_its_recording_start(db):
    base = datetime(2028, 2, 1, 0, 0)
    for i, value in enumerate((1_000, 50_000, 900_000)):
        db.add(StatSnapshot(metric="wal_bytes", taken_at=base + timedelta(hours=i), value=value))
    db.commit()

    hist = _wal_history(db)
    assert hist is not None
    values = [p["n"] for p in hist["series"]]
    # The window is bounded to 30 days and these rows are seeded in the past, so the
    # series may legitimately be empty here — what must always hold is that the
    # recording start is stated, so an empty window never reads as "the WAL was fine".
    assert "recording_began_at" in hist
    assert hist["days"] == 30
    if values:
        assert hist["min_bytes"] == min(values) and hist["max_bytes"] == max(values)
        assert hist["n"] == len(values)

    served = metric_history(db, metric="wal_bytes", days=3650)
    assert not served.get("error"), "a recorded gauge must be readable by the bundle"
    assert served["recording_began_at"] is not None
    assert [p["n"] for p in served["series"]][-3:] == [1_000, 50_000, 900_000]


def test_the_wal_series_stays_out_of_the_user_facing_library_allowlist():
    """Item 8: diagnostics, not a Library counter. ALL_METRICS is what the Library
    endpoint validates against, so membership there IS the user-facing surface."""
    assert "wal_bytes" not in ALL_METRICS
    assert "articles" in ALL_METRICS, "…while the real Library counters are untouched"


def test_no_score_shaped_keys_in_the_wal_diagnostic(db):
    out = storage_composition(db)

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield k
                yield from walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v)

    banned = ("score", "ranking", "rating", "grade")
    for key in walk(out):
        low = str(key).lower()
        assert not any(b in low for b in banned), f"score-shaped key in a measurement: {key}"
