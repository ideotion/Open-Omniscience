"""A pass wound down by an exclusive hold does not start the detached launches of its tail.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_default_run_once`` hands the collector the pass stop, and a hold (an import, a restore) winds the pass down within a source, but
its tail then ran whole. Four steps of it start work that OUTLIVES the pass: the first-run preflight job, the housekeeping lane, the
language-detection job and the briefing refresh. A restore waits for the pass's own thread; these four are detached, so they ran on
into the restore's working-copy span with the hold standing (WAL lane's probe, 2026-10-28, two kicks seen running). Each is due again
at the next pass, so holding them back loses nothing. Only a HOLD holds them back: a plain Stop keeps its behaviour.
"""

from __future__ import annotations

import pytest

import src.scheduler.runner as runner_mod
from src.scheduler.runner import BackgroundScheduler

_LAUNCHES = ["first-run-preflight", "housekeeping-lane", "langdetect-auto", "briefing-refresh"]


class _Settings:
    continuous = True
    interval_minutes = 1
    mode = "rss"
    export_dir = ""
    auto_enrich_sources = False
    discovery_per_run = 0

    def to_dict(self):
        return {"continuous": True, "interval_minutes": 1, "mode": "rss"}


@pytest.fixture()
def tail(monkeypatch, tmp_path):
    """A scheduler whose pass tail runs for real except the four launches, which only record that they were reached."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    sch = BackgroundScheduler(settings_provider=_Settings)
    calls: list[str] = []
    hooks: dict[str, object] = {}
    answered: list[bool] = []

    def _note(name):
        calls.append(name)
        hook = hooks.get(name)
        if callable(hook):
            hook()

    def scrape(session, fetcher, settings, *, should_stop=None):
        answered.append(bool(should_stop()))
        hook = hooks.get("scrape")
        if callable(hook):
            hook()
        return {"stopped": answered[-1]}

    monkeypatch.setattr(runner_mod, "run_scrape_once", scrape)
    monkeypatch.setattr("src.monitoring.preflight_job.kick", lambda f: _note("first-run-preflight"))
    monkeypatch.setattr(sch, "_kick_housekeeping_lane", lambda: _note("housekeeping-lane"))
    monkeypatch.setattr(sch, "_refresh_briefing_async", lambda: _note("briefing-refresh"))
    monkeypatch.setattr("src.api.ai.advance_langdetect_auto_start", lambda s: (_note("langdetect-auto"), {})[1])
    # the tail steps that are not under test: no-ops
    monkeypatch.setattr("src.discovery.run_discovery", lambda *a, **k: {})
    monkeypatch.setattr("src.ai_layer.auto.run_auto_on_ingest", lambda *a, **k: {})
    sch._calls, sch._hooks, sch._answered = calls, hooks, answered  # type: ignore[attr-defined]
    return sch


def test_every_launch_is_held_back_while_the_hold_stands(tail):
    tail.hold_exclusive()
    tail._pass_stop.set()
    result = tail._default_run_once()
    assert tail._answered == [True], "premise: the pass was told to wind down"
    assert tail._calls == [], f"launched under the hold: {tail._calls}"
    assert result["tail_launches_skipped_by_exclusive_operation"] == _LAUNCHES, "a skipped launch is reported, not silently dropped"


def test_without_the_hold_every_launch_runs_and_nothing_is_reported(tail):
    result = tail._default_run_once()
    assert tail._calls == _LAUNCHES
    assert "tail_launches_skipped_by_exclusive_operation" not in result


@pytest.mark.parametrize("claimed_before", range(len(_LAUNCHES)))
def test_each_launch_reads_the_hold_for_itself(tail, claimed_before):
    """The hold can arrive mid-tail: the launch before it runs, this one and every later one do not. One read at the top would pass the
    all-held test above and fail here."""
    trigger = "scrape" if claimed_before == 0 else _LAUNCHES[claimed_before - 1]
    tail._hooks[trigger] = tail.hold_exclusive
    result = tail._default_run_once()
    assert tail._calls == _LAUNCHES[:claimed_before]
    assert result.get("tail_launches_skipped_by_exclusive_operation") == _LAUNCHES[claimed_before:]


def test_a_plain_stop_without_a_hold_keeps_todays_behaviour(tail):
    tail._stop.set()
    tail._default_run_once()
    assert tail._answered == [True]
    assert tail._calls == _LAUNCHES, "only a hold holds the launches back; a Stop trips the kill switch, which the lane honours itself"


def test_the_launches_are_due_again_once_the_hold_is_released(tail):
    tail.hold_exclusive()
    first = tail._default_run_once()
    assert tail._calls == [] and first["tail_launches_skipped_by_exclusive_operation"] == _LAUNCHES
    tail.release_exclusive()
    second = tail._default_run_once()
    assert tail._calls == _LAUNCHES
    assert "tail_launches_skipped_by_exclusive_operation" not in second
