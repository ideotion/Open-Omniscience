"""The expedition log — the unattended-run digest (2026-08-12 field ask).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Guards the four properties the feature exists for, and one it must NOT acquire:

  1. Reading it is FREE. ``digest()`` takes no session and never scans the corpus —
     that is the whole reason the operator can press it mid-run on a slow box.
  2. Writing it is BOUNDED. The events ring has a ceiling by construction, and a full
     ring SAYS it dropped older entries rather than presenting a truncated history as
     a complete one (the run-journal lesson, one subsystem over).
  3. An unrecorded counter reports null WITH a reason, never 0 — "the recorder has not
     run yet" and "there are none" are different facts.
  4. THE SAFETY ASYMMETRY. A measured shortfall declines the bulk drain; an UNMEASURED
     one does not, because refusing on a measurement we could not take is the
     fabricated-refusal mirror of a fabricated pass. Both directions are pinned, or a
     later "make it conservative" edit silently disables the drain on every platform
     that cannot read /proc/meminfo.
"""

from __future__ import annotations

import pytest

from src.monitoring import expedition


@pytest.fixture()
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def series(monkeypatch):
    """Stub the snapshot read-back so these tests never need a corpus — which is also
    the point: the digest is composed from recorded rows, not from the articles table."""
    store: dict[str, list] = {}

    def _metric_history(session, *, metric, days):  # noqa: ARG001
        return {"metric": metric, "series": store.get(metric, []), "recording_began_at": None}

    monkeypatch.setattr("src.database.snapshots.metric_history", _metric_history)
    return store


# --------------------------------------------------------------------------- #
# Bounded by construction                                                     #
# --------------------------------------------------------------------------- #

def test_the_events_ring_is_capped_and_says_so_when_it_drops(dd):
    for i in range(expedition._MAX_EVENTS + 25):
        expedition.record_event("note", f"event {i}")
    d = expedition.digest()
    assert len(d["events"]) == expedition._MAX_EVENTS
    assert d["events_dropped"] >= 25
    # the newest survive...
    assert any(f"event {expedition._MAX_EVENTS + 24}" in e["message"] for e in d["events"])
    # ...and the truncation is STATED, never silent
    assert "older event(s) dropped" in expedition.render_text(d)


def test_the_log_file_stays_small_enough_to_paste(dd):
    for i in range(expedition._MAX_EVENTS * 3):
        expedition.record_event("note", "x" * 200 + str(i))
    size = (dd / "expedition.json").stat().st_size
    # A ceiling that holds however long the run lasts: the ring cannot grow, so this
    # is the file's maximum shape, not a sample of an early moment.
    assert size < 300_000, size


def test_rearming_keeps_the_original_start_because_the_window_is_the_absence(dd):
    first = expedition.arm(safety={"safe": True}, note="ten days")["started_at"]
    again = expedition.arm(safety={"safe": False})["started_at"]
    assert again == first


# --------------------------------------------------------------------------- #
# Honest counters                                                             #
# --------------------------------------------------------------------------- #

def test_an_unrecorded_counter_is_null_with_a_reason_never_zero(dd, series):
    w = expedition._series_window(None, "articles", days=3)
    assert w["value"] is None
    assert "no snapshot recorded yet" in w["reason"]
    # the rendering must say it in words, not print a bare 0
    d = {"armed": True, "started_at": "2026-08-01T00:00:00+00:00", "counters": [w], "live": {}}
    text = expedition.render_text(d)
    assert "not recorded yet" in text
    assert "articles: 0" not in text


def test_a_recorded_counter_reports_first_last_and_delta(dd, series):
    series["articles"] = [
        {"t": "2026-08-01T00:00:00+00:00", "n": 1000},
        {"t": "2026-08-03T00:00:00+00:00", "n": 1250},
    ]
    w = expedition._series_window(None, "articles", days=3)
    assert (w["value"], w["first"], w["delta"], w["samples"]) == (1250, 1000, 250, 2)


def test_digest_needs_no_session_so_reading_it_cannot_scan_the_corpus(dd):
    """Behavioural, not a source grep: the call signature is the guarantee. If someone
    later threads a Session in to enrich it, this fails and the cost question gets
    asked again."""
    import inspect

    assert list(inspect.signature(expedition.digest).parameters) == []
    expedition.arm(safety={"safe": True})
    assert expedition.digest()["armed"] is True


# --------------------------------------------------------------------------- #
# The safety asymmetry — both directions                                      #
# --------------------------------------------------------------------------- #

def test_a_measured_shortfall_declines_the_bulk_drain(dd, series, monkeypatch):
    series["articles"] = [{"t": "2026-08-01T00:00:00+00:00", "n": 1_000_000}]
    monkeypatch.setattr(expedition, "_memory", lambda: {"available_mb": 900})
    s = expedition.qualification_safety(None)
    assert s["safe"] is False
    assert s["basis"] == "estimated"
    assert "NOT started" in s["reason"]


def test_a_measured_sufficiency_allows_it(dd, series, monkeypatch):
    series["articles"] = [{"t": "2026-08-01T00:00:00+00:00", "n": 1_000_000}]
    monkeypatch.setattr(expedition, "_memory", lambda: {"available_mb": 8000})
    s = expedition.qualification_safety(None)
    assert s["safe"] is True
    assert s["basis"] == "estimated"


def test_unmeasurable_memory_does_NOT_decline(dd, series, monkeypatch):
    """The mirror of a fabricated pass. A platform whose free RAM we cannot read is not
    thereby a platform that will run out — and the memory guard still pauses the job
    between batches, which is the net it has always been."""
    series["articles"] = [{"t": "2026-08-01T00:00:00+00:00", "n": 1_000_000}]
    monkeypatch.setattr(expedition, "_memory", lambda: {"available_mb": None, "reason": "n/a"})
    s = expedition.qualification_safety(None)
    assert s["safe"] is True
    assert s["basis"] == "unmeasured"
    assert "memory guard" in s["reason"]


def test_unmeasurable_corpus_size_does_NOT_decline(dd, series, monkeypatch):
    monkeypatch.setattr(expedition, "_memory", lambda: {"available_mb": 500})
    s = expedition.qualification_safety(None)  # no 'articles' series recorded
    assert s["safe"] is True
    assert s["basis"] == "unmeasured"


def test_the_decision_always_travels_with_its_basis(dd, series, monkeypatch):
    """Every verdict names how it was reached, so a run that declined to qualify reads
    as a decision rather than as one that simply found nothing to do."""
    for avail, articles in ((900, 1_000_000), (8000, 1_000_000), (None, 1_000_000), (500, None)):
        series.clear()
        if articles:
            series["articles"] = [{"t": "2026-08-01T00:00:00+00:00", "n": articles}]
        monkeypatch.setattr(expedition, "_memory", lambda a=avail: {"available_mb": a})
        s = expedition.qualification_safety(None)
        assert s["basis"] in {"estimated", "unmeasured"}
        assert s["reason"]


# --------------------------------------------------------------------------- #
# Wiring                                                                      #
# --------------------------------------------------------------------------- #

def test_the_button_and_the_log_are_wired_on_the_system_router():
    from pathlib import Path

    src = Path("src/api/system.py").read_text(encoding="utf-8")
    assert '@router.post("/unattended/start")' in src
    assert '@router.get("/unattended/log")' in src
    # the one button must reuse the RULED online path, not open a second way in
    assert "clear_kill_switch()" in src and "note_operator_crossed_online()" in src


def test_the_refresh_rides_the_hourly_recorder_it_reads_from():
    """Not a poller of its own: the digest is refreshed right after the snapshot it
    reads back, inside work that is already happening."""
    from pathlib import Path

    src = Path("src/scheduler/maintenance.py").read_text(encoding="utf-8")
    snap = src.index("maybe_snapshot_library_stats(session)")
    ref = src.index("expedition.refresh(session)")
    assert ref > snap, "the digest must refresh AFTER the snapshot it composes from"
    assert 'get("armed")' in src, "an unarmed machine must write nothing"
