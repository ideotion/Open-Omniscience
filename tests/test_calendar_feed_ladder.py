"""
The calendar-feed re-check LADDER and the progressive verification that rides
collect passes (maintainer rulings 10/11/12, 2026-07-31).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Ruling 11: verification becomes PROGRESSIVE, riding each collection pass, and is
VISIBLE in the task manager -- it must NEVER run at boot (airplane-mode /
zero-network boot is a non-negotiable).

Ruling 12: a dysfunctional feed is re-checked on the SAME ladder shape as the
source re-qualification one (1 -> 2 -> 4 -> 6 months, capped, append-only
attempts, bounded per pass) -- "never a permanent exclusion". The cap is what
makes that true, so it is asserted directly rather than inferred.

The ladder core is pure, so it is tested exactly; the fetch layer is driven with
a stub fetcher (no network anywhere in this file).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.events import feeds as F


# --------------------------------------------------------------------------- #
#  The pure ladder
# --------------------------------------------------------------------------- #
def test_the_ladder_is_1_2_4_6_and_CAPPED():
    """The exact rungs the ruling names, and — the load-bearing half — a cap that
    holds forever, so a feed is deferred but never written off."""
    assert [F.feed_backoff_months(n) for n in (1, 2, 3, 4)] == [1, 2, 4, 6]
    # "never a permanent exclusion": no failure count, however large, ever pushes
    # the next check beyond the cap.
    assert all(F.feed_backoff_months(n) == 6 for n in (5, 9, 50, 10_000))
    # A feed with NO failures still gets a rung: a working feed can break, and a
    # stale "ok" is a claim about the past.
    assert F.feed_backoff_months(0) == 1


def test_the_ladder_mirrors_the_source_requalification_ladder():
    """Ruling 12 says "MIRRORING the source ladder", so a divergence between the
    two is a defect in this file's subject, not a coincidence worth ignoring."""
    from src.catalog import qualification as Q

    assert [F.feed_backoff_months(n) for n in range(1, 8)] == [
        Q.backoff_months(n) for n in range(1, 8)
    ]


def test_a_success_resets_the_ladder_and_only_the_trailing_run_counts():
    f = F.consecutive_failures_from_attempts
    assert f([]) == 0
    assert f(["unreachable"]) == 1
    assert f(["unreachable", "not_ical", "empty"]) == 3
    # newest-first: a success at the FRONT stops the count dead
    assert f(["ok", "unreachable", "unreachable"]) == 0
    # ...and one further back only truncates it
    assert f(["unreachable", "ok", "unreachable"]) == 1


def test_recheck_due_at_uses_the_rung():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert F.feed_recheck_due_at(now, 1) == now + timedelta(days=30)
    assert F.feed_recheck_due_at(now, 3) == now + timedelta(days=120)
    assert F.feed_recheck_due_at(now, 99) == now + timedelta(days=180)  # capped


# --------------------------------------------------------------------------- #
#  Selection: bounded, never-checked first, and never permanently stuck
# --------------------------------------------------------------------------- #
def _att(at: datetime, *statuses: str) -> list[dict]:
    """An attempt history ending at ``at`` (newest LAST, as stored)."""
    return [
        {"at": (at - timedelta(days=len(statuses) - 1 - i)).isoformat(), "status": s}
        for i, s in enumerate(statuses)
    ]


def test_never_checked_feeds_come_first_and_the_batch_is_bounded():
    now = datetime(2026, 6, 1, tzinfo=UTC)
    ids = ["a", "b", "c", "d"]
    attempts = {"a": _att(now - timedelta(days=400), "ok")}  # long overdue
    # b/c/d were never checked -> the initial sweep takes them first, in catalog order
    assert F.select_feeds_to_verify(ids, attempts, now=now, limit=2) == ["b", "c"]
    assert F.select_feeds_to_verify(ids, attempts, now=now, limit=99) == ["b", "c", "d", "a"]
    assert F.select_feeds_to_verify(ids, attempts, now=now, limit=0) == []


def test_a_feed_that_is_not_yet_due_is_deferred_but_never_dropped():
    """The whole point of ruling 12: a failing feed leaves the queue for a while
    and comes back on its own — it is never excluded."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    ids = ["x"]
    # one failure -> the 1-month rung
    attempts = {"x": _att(now - timedelta(days=10), "unreachable")}
    assert F.select_feeds_to_verify(ids, attempts, now=now, limit=9) == []
    later = now + timedelta(days=25)  # 35 days after the attempt
    assert F.select_feeds_to_verify(ids, attempts, now=later, limit=9) == ["x"]


def test_repeated_failures_lengthen_the_wait_but_never_past_the_cap():
    base = datetime(2026, 6, 1, tzinfo=UTC)
    ids = ["x"]
    four_fails = {"x": _att(base, "unreachable", "unreachable", "unreachable", "unreachable")}
    # at the 6-month cap: not due at 5 months...
    assert F.select_feeds_to_verify(
        ids, four_fails, now=base + timedelta(days=150), limit=9
    ) == []
    # ...due at 6, and STILL due later — the cap means it always comes back.
    assert F.select_feeds_to_verify(
        ids, four_fails, now=base + timedelta(days=181), limit=9
    ) == ["x"]
    ten_fails = {"x": _att(base, *["unreachable"] * 10)}
    assert F.select_feeds_to_verify(
        ids, ten_fails, now=base + timedelta(days=181), limit=9
    ) == ["x"], "a long failure run must not push the next check past the cap"


def test_an_unreadable_timestamp_is_due_now_never_permanently_stuck():
    """Negative space: corrupt state must fail toward re-checking. Treating an
    unparseable date as 'not due' would retire the feed silently and forever —
    exactly the permanent exclusion the ruling forbids."""
    now = datetime(2026, 6, 1, tzinfo=UTC)
    for bad in ("", "not-a-date", None, 12345):
        attempts = {"x": [{"at": bad, "status": "unreachable"}]}
        assert F.select_feeds_to_verify(["x"], attempts, now=now, limit=9) == ["x"], bad


def test_selection_prefers_the_most_overdue():
    now = datetime(2026, 6, 1, tzinfo=UTC)
    attempts = {
        "recent": _att(now - timedelta(days=40), "ok"),
        "ancient": _att(now - timedelta(days=900), "ok"),
    }
    assert F.select_feeds_to_verify(["recent", "ancient"], attempts, now=now, limit=1) == [
        "ancient"
    ]


# --------------------------------------------------------------------------- #
#  The store: append-only, bounded
# --------------------------------------------------------------------------- #
@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "data_dir", lambda: tmp_path)
    # _save_json mirrors into the DB; this file is about the JSON layer only.
    monkeypatch.setattr(F, "_save_json", lambda name, data, mirror=True: F._store_path(name)
                        .write_text(__import__("json").dumps(data), encoding="utf-8"))
    return tmp_path


def test_attempts_append_and_stay_bounded(store):
    for i in range(F._MAX_ATTEMPTS_PER_FEED + 5):
        F.record_attempt("x", "ok" if i % 2 else "unreachable")
    history = F.load_attempts()["x"]
    assert len(history) == F._MAX_ATTEMPTS_PER_FEED, "the history must be bounded"
    # append-only: the NEWEST is last, and the oldest were dropped from the front
    assert history == sorted(history, key=lambda a: a["at"])


def test_record_attempt_never_loses_another_feeds_history(store):
    F.record_attempt("a", "ok")
    F.record_attempt("b", "unreachable")
    attempts = F.load_attempts()
    assert set(attempts) == {"a", "b"} and len(attempts["a"]) == 1


# --------------------------------------------------------------------------- #
#  The ride-along
# --------------------------------------------------------------------------- #
class _Fetcher:
    """Records every URL asked for; answers with a minimal valid iCalendar."""

    ICS = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:X\r\n"
        "DTSTART;VALUE=DATE:20260101\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    def __init__(self):
        self.urls = []

    def fetch(self, url, require_html=False):
        self.urls.append(url)
        return type("R", (), {"content": self.ICS})()


def _one_family(monkeypatch, n=3):
    fams = [
        {
            "key": "fam",
            "name": "Fam",
            "kind": "holiday",
            "country": None,
            "feeds": [
                {"id": f"f{i}", "name": f"F{i}", "url": f"https://e.example/{i}.ics"}
                for i in range(n)
            ],
        }
    ]
    monkeypatch.setattr(F, "load_families", lambda: fams)
    return fams


def test_verify_due_feeds_is_bounded_and_records_every_attempt(store, monkeypatch):
    _one_family(monkeypatch, n=5)
    fetcher = _Fetcher()
    out = F.verify_due_feeds(fetcher, batch=2)
    assert out["checked"] == 2 and out["ok"] == 2
    assert len(fetcher.urls) == 2, "the batch bound is the whole point of 'progressive'"
    assert set(F.load_attempts()) == {"f0", "f1"}
    # the next pass picks up where this one left off, never repeating
    F.verify_due_feeds(fetcher, batch=2)
    assert set(F.load_attempts()) == {"f0", "f1", "f2", "f3"}


def test_a_failing_feed_still_advances_its_rung(store, monkeypatch):
    """A feed that cannot be fetched must record the ATTEMPT, or it would be
    retried every single pass forever (the opposite failure of a permanent
    exclusion, and just as wrong)."""
    _one_family(monkeypatch, n=1)

    class _Dead:
        def fetch(self, url, require_html=False):
            raise OSError("nope")

    out = F.verify_due_feeds(_Dead(), batch=5)
    assert out["checked"] == 1 and out["failed"] == 1
    history = F.load_attempts()["f0"]
    assert len(history) == 1 and history[0]["status"] != "ok"
    # and it is now deferred rather than re-picked immediately
    assert F.verify_due_feeds(_Dead(), batch=5)["checked"] == 0


def test_verification_status_buckets_are_disjoint_and_add_up(store, monkeypatch):
    _one_family(monkeypatch, n=4)
    st = F.verification_status()
    assert st["total"] == 4 and st["unchecked"] == 4
    assert st["unchecked"] + st["due_now"] + st["waiting"] == st["total"]
    F.verify_due_feeds(_Fetcher(), batch=4)
    st = F.verification_status()
    assert st["unchecked"] == 0 and st["ok"] == 4 and st["waiting"] == 4
    assert st["unchecked"] + st["due_now"] + st["waiting"] == st["total"]
    assert "score" not in repr(st).lower()  # counts only, never a score


def test_the_import_round_robin_backs_off_a_failing_feed_but_not_a_healthy_one(
    store, monkeypatch
):
    """Ruling 12 applied to the IMPORT half: re-importing a feed whose last check
    failed just re-runs the same failing fetch. It is deferred on the same capped
    ladder — never excluded — and a healthy or never-checked feed is untouched."""
    _one_family(monkeypatch, n=3)
    now = datetime.now(UTC)
    monkeypatch.setattr(
        F,
        "load_attempts",
        lambda: {
            "f0": [{"at": (now - timedelta(days=2)).isoformat(), "status": "unreachable"}],
            "f1": [{"at": (now - timedelta(days=2)).isoformat(), "status": "ok"}],
            # f2 has never been checked
        },
    )
    imported = []
    monkeypatch.setattr(F, "import_feed", lambda fetcher, fid: imported.append(fid))
    out = F.auto_import_due_feeds(_Fetcher(), batch=9)
    assert out["backed_off"] == 1, "the recently-failed feed must be deferred"
    assert set(imported) == {"f1", "f2"}, "healthy + never-checked feeds still import"
