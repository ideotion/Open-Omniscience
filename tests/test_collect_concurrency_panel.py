"""P5: why a pass is running fewer workers than configured, where the operator looks.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Both caps already existed and NEITHER reached the task manager: ``state_report`` was
rendered only inside the diagnostics report payload, and the machine-floor worker cap
only into a log line. A pass running one worker of a configured fifty -- measured at
1.91 -> 0.45 articles/s over a slow transport, and persisting across restarts because
``collect_capacity.json`` does -- was therefore indistinguishable, from the window an
operator actually watches, from "the app got slow".

The properties worth pinning are mostly NEGATIVE: the two caps stay apart because they
have different remedies, an unreadable reading says so rather than reporting a quiet
"nothing is capping this", and a healthy machine carries no cap at all.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.scheduler import capacity

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def state(tmp_path):
    return tmp_path / "collect_capacity.json"


def _pin_floor(monkeypatch, *, capped: int, w_max: int, reason: str = "small machine"):
    """Force the machine-floor cap, so the test measures the composition rather than
    whatever RAM the CI runner happens to have."""
    import src.config.machine_floor as mf

    monkeypatch.setattr(
        mf, "capped_workers",
        lambda w, **kw: (capped, {"reason": reason, "override_env": "OO_ALLOW_BIG_SCANS",
                                  "declines": capped < w_max}),
    )


# --------------------------------------------------------------------------- #
#  The composition: two caps, kept apart.
# --------------------------------------------------------------------------- #


def test_a_healthy_machine_reports_no_cap_at_all(state, monkeypatch):
    _pin_floor(monkeypatch, capped=50, w_max=50)
    r = capacity.concurrency_report(50, state)
    assert r["configured"] == 50
    assert r["learned_ceiling"] is None
    assert r["floor_cap"] is None
    assert r["effective_max"] == 50
    assert r["capped"] is False
    assert r["measured"] is False  # never measured is not the same as measured-at-50


def test_a_learned_ceiling_and_the_machine_floor_stay_separate(state, monkeypatch):
    """Folding them into one 'effective' number would leave a reader unable to tell
    which lever they are looking at -- and the remedies differ: one is a measurement
    that heals itself, the other a policy with a documented override."""
    state.write_text(
        json.dumps({"schema": capacity.SCHEMA, "ceiling": 4, "w_max_at_record": 50}), "utf-8"
    )
    _pin_floor(monkeypatch, capped=8, w_max=50)
    r = capacity.concurrency_report(50, state)
    assert r["learned_ceiling"] == 4
    assert r["floor_cap"] == 8
    assert r["effective_max"] == 4, "effective_max must be the SMALLER of the two"
    assert r["capped"] is True
    assert r["override_env"] == "OO_ALLOW_BIG_SCANS"


def test_the_floor_cap_is_absent_when_it_does_not_apply(state, monkeypatch):
    """A cap that is not capping must be absent, not reported equal to the configured
    maximum -- a reader scanning for "is anything limiting me" would read that as yes."""
    _pin_floor(monkeypatch, capped=50, w_max=50)
    assert capacity.concurrency_report(50, state)["floor_cap"] is None


def test_effective_max_is_a_bound_not_a_predicted_permit_count(state):
    """Where a pass STARTS is the governor's own rate-mode default, which this module
    does not know and must not guess (the ``seed_for`` contract)."""
    state.write_text(
        json.dumps({"schema": capacity.SCHEMA, "ceiling": 4, "w_max_at_record": 50}), "utf-8"
    )
    r = capacity.concurrency_report(50, state)
    assert r["effective_max"] == 4
    assert "seed" not in r and "starting_permits" not in r


def test_an_unreadable_machine_floor_says_so_rather_than_reporting_no_cap(state, monkeypatch):
    import src.config.machine_floor as mf

    def _boom(*_a, **_kw):
        raise RuntimeError("psutil is not installed")

    monkeypatch.setattr(mf, "capped_workers", _boom)
    r = capacity.concurrency_report(50, state)
    assert r["floor_read"] is False
    assert r["floor_cap"] is None  # unknown, and NOT claimed as "nothing is capping it"


def test_the_guarantee_lives_at_the_caller_not_in_two_places(state, monkeypatch):
    """``concurrency_report`` does NOT swallow everything, on purpose.

    ``load_ceiling`` already cannot fail this way, and the one guarantee that matters --
    a panel reading never breaks the polled status -- belongs in one place. This pins
    which place, so a later edit does not add a second, unfalsifiable guard here.
    """
    monkeypatch.setattr(capacity, "load_ceiling", lambda *_a, **_kw: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        capacity.concurrency_report(50, state)


def test_the_status_block_swallows_a_failure_and_names_it(monkeypatch):
    """...and the SCHEDULER's wrapper is what must not, because that is the polled path.
    A quiet {} there would render as a healthy uncapped machine."""
    from src.scheduler import runner
    from src.scheduler.settings import SchedulerSettings

    monkeypatch.setattr(
        capacity, "concurrency_report",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("psutil exploded")),
    )
    block = runner._concurrency_block(SchedulerSettings(collect_parallelism=50))
    assert block["read"] is False
    assert "psutil exploded" in block["reason"]


def test_the_block_rides_the_status_payload_the_window_already_polls():
    """Not a new endpoint and not a new poll: the task manager reads
    /api/scheduler/activity, which spreads status()."""
    from src.scheduler.runner import get_scheduler

    status = get_scheduler().status()
    assert "concurrency" in status
    c = status["concurrency"]
    assert c.get("read") is not False
    assert c["configured"] >= 1


# --------------------------------------------------------------------------- #
#  The render, driven for real.
# --------------------------------------------------------------------------- #


def test_the_panel_is_driven_for_real_in_node() -> None:
    """The half a source grep cannot do.

    ``tests/concurrency_panel_node_test.js`` EXECUTES the shipped
    ``_concurrencyHtml``, so "no pass in flight draws no permit count" is checked as
    behaviour rather than as the presence of a substring -- and a measured 0, which
    MUST still draw, is checked beside it, because those two are one character apart in
    the source and opposite facts on the screen. Seven mutants, seven dead -- the
    seventh being a hover that carries the backend's English `method` instead of a
    translated string, added after the browser run caught exactly that.
    """
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "concurrency_panel_node_test.js")],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "all checks passed" in proc.stdout, proc.stdout


def test_every_panel_string_is_keyed_in_all_twelve_locales() -> None:
    """A t() call whose literal has no en.json key falls back to English forever, and
    the untranslatable ratchet counts index.html rather than the engine modules -- so
    nothing else would notice."""
    locales = _ROOT / "src" / "static" / "locales"
    needed = [
        "Workers", "Fetching now", "Limit this pass", "Configured maximum",
        "Why the limit", "the concurrency limits could not be read",
        "both a measured memory back-off and the machine floor",
        "this machine backed off under memory pressure, so the ramp is capped",
        "this machine is below the memory floor, so the fan-out is capped",
        "nothing is holding it back — the full configured maximum is available",
    ]
    files = sorted(locales.glob("*.json"))
    assert len(files) == 12, f"expected 12 locales, found {len(files)}"
    for path in files:
        table = json.loads(path.read_text("utf-8"))
        missing = [k for k in needed if k not in table]
        assert not missing, f"{path.name} is missing {missing}"
        if path.name != "en.json":
            untranslated = [k for k in needed if table[k] == k]
            assert not untranslated, f"{path.name} left {untranslated} in English"
