"""Going online starts the background collector; airplane stops it.

Maintainer 2026-06-18: "as soon as the app goes online, the automated scraping
and downloading … should start in the background, immediately" and "the only
reason to stop it is airplane mode". So the network toggle (the top-bar airplane
button AND the first-launch wizard's "Go online", both POST /api/system/network)
must drive the scheduler — there is no separate Collect/Start step.

The behaviour is gated by OO_NO_SCHEDULER so the rest of the suite (which sets it
to "1" in conftest) keeps managing the scheduler itself and is untouched.
"""

from __future__ import annotations


class _FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start(self) -> bool:
        self.calls.append("start")
        return True

    def stop(self) -> bool:
        self.calls.append("stop")
        return True


def test_going_online_starts_then_airplane_stops_the_collector(monkeypatch):
    monkeypatch.delenv("OO_NO_SCHEDULER", raising=False)  # behave like production
    fake = _FakeScheduler()
    import src.scheduler.runner as runner

    monkeypatch.setattr(runner, "get_scheduler", lambda: fake)

    from src.api.system import set_network_mode
    from src.ingest import clear_kill_switch, kill_switch_active

    try:
        out = set_network_mode({"online": True})
        assert out["online"] is True  # kill switch cleared (online)
        assert fake.calls == ["start"], "crossing online must start the collector at once"

        out = set_network_mode({"online": False})
        assert out["online"] is False  # airplane engaged
        assert fake.calls == ["start", "stop"], "airplane mode must stop the collector"
    finally:
        clear_kill_switch()
        assert not kill_switch_active()


def test_network_toggle_leaves_scheduler_alone_under_oo_no_scheduler(monkeypatch):
    """The default test/headless mode (OO_NO_SCHEDULER=1) drives the scheduler
    itself, so the network endpoint must NOT spawn a real scraping thread."""
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    fake = _FakeScheduler()
    import src.scheduler.runner as runner

    monkeypatch.setattr(runner, "get_scheduler", lambda: fake)

    from src.api.system import set_network_mode
    from src.ingest import clear_kill_switch

    try:
        set_network_mode({"online": True})
        set_network_mode({"online": False})
        assert fake.calls == [], "with OO_NO_SCHEDULER=1 the toggle must not touch the scheduler"
    finally:
        clear_kill_switch()
