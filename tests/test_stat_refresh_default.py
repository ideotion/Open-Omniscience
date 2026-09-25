"""
R31 (2026-09-25): the refresh of tracked statistics figures defaults ON.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's answer to the question PR #1178 left open, verbatim: «turn it on by
default». Before Q1020 retired the scheduler ``mode``, the refresh ran only in the markets
mode; #1178 made it a per-lane switch and, lacking a ruling, kept it off. Ruling #12
(2026-06-17) had asked for exactly this refresh ("add a scheduled auto-refresh of
vintages"), and the country-data ride-along was written on the assumption that it ran.

What this pins, each as its own test:

* the DEFAULT, on both settings stores, for a fresh install and for a blob written before
  the switch existed;
* a STORED ``False`` is the operator's and is never re-flipped -- the default reaches only
  a blob without the key, which is also why an install that saved between #1178 and R31
  keeps the old value;
* the lane really runs the refresh on a fresh install, and the price rules (not part of
  R31) stay off;
* the checkbox's hover says "on by default" in all twelve locales, and names BOTH
  populations the refresh reaches.

The consent popup's half -- the "Official statistics" row counted as on while EITHER of
its two switches is -- is run as real code in ``net_lane_state_node_test.js``, driven from
``tests/test_security_endpoint_enumeration.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import kv_store
from src.scheduler import settings as sset
from src.scheduler.settings import SchedulerSettings, load_settings, save_settings

_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

#: The checkbox's hover, verbatim from index.html. Read from the page below rather than
#: trusted: a key that matches no rendered title is a translation nobody sees.
_HOVER = (
    "Tracked statistics figures (every figure you fetched, and the standard country "
    "indicators loaded in the background) are re-fetched from their publisher when a newer "
    "vintage is due — each at most once per its own interval, and never in airplane mode. "
    "On by default. Untick it to stop the background refresh; “Refresh due now” in "
    "Governments → Statistics still works."
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    kv_store.kv_invalidate()
    yield
    kv_store.kv_invalidate()


def _as_json_store(tmp_path, monkeypatch, blob: dict | None) -> Path:
    path = tmp_path / "elsewhere" / "scheduler_settings.json"
    path.parent.mkdir()
    if blob is not None:
        path.write_text(json.dumps(blob), "utf-8")
    monkeypatch.setattr(sset, "_settings_path", lambda: path)
    assert not sset._use_kv()
    return path


# --------------------------------------------------------------------------- #
# The default
# --------------------------------------------------------------------------- #
def test_the_dataclass_default_is_on_and_the_price_rules_stay_off():
    s = SchedulerSettings()
    assert s.auto_refresh_stat_subscriptions is True
    # R31 answered the statistics question only; the rules fetch pages the operator typed.
    assert s.auto_run_market_rules is False


def test_a_fresh_install_loads_it_on_from_either_store(tmp_path, monkeypatch):
    assert sset._use_kv()
    assert load_settings().auto_refresh_stat_subscriptions is True  # the encrypted row
    kv_store.kv_invalidate()
    _as_json_store(tmp_path, monkeypatch, None)
    assert load_settings().auto_refresh_stat_subscriptions is True  # the redirected file


def test_a_blob_from_before_the_switch_existed_gets_the_new_default(tmp_path, monkeypatch):
    """Every install older than PR #1178 has a blob WITHOUT the key -- the default is what
    reaches them, on both stores."""
    kv_store.kv_set_json(sset._KV_KEY, {"interval_minutes": 30})
    kv_store.kv_invalidate()
    assert load_settings().auto_refresh_stat_subscriptions is True
    kv_store.kv_invalidate()
    _as_json_store(tmp_path, monkeypatch, {"interval_minutes": 30})
    assert load_settings().auto_refresh_stat_subscriptions is True


def test_a_stored_false_is_the_operators_and_is_never_re_flipped(tmp_path, monkeypatch):
    """The default reaches only a blob without the key. A stored ``False`` -- an operator
    who unticked the box, or an install that saved between #1178 and R31 -- stays, through
    a load and through a save of an unrelated field: this module cannot tell a default
    that was written down from a choice, and overriding a choice is the worse error."""
    path = _as_json_store(tmp_path, monkeypatch, {"auto_refresh_stat_subscriptions": False})
    assert load_settings().auto_refresh_stat_subscriptions is False
    save_settings({"interval_minutes": 45})
    assert load_settings().auto_refresh_stat_subscriptions is False
    assert json.loads(path.read_text("utf-8"))["auto_refresh_stat_subscriptions"] is False


def test_the_switch_still_turns_off_and_back_on(tmp_path, monkeypatch):
    _as_json_store(tmp_path, monkeypatch, None)
    assert save_settings({"auto_refresh_stat_subscriptions": False}).auto_refresh_stat_subscriptions is False
    assert load_settings().auto_refresh_stat_subscriptions is False
    assert save_settings({"auto_refresh_stat_subscriptions": True}).auto_refresh_stat_subscriptions is True


def test_the_config_endpoint_reports_it_on_for_a_fresh_install(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    _as_json_store(tmp_path, monkeypatch, None)
    with TestClient(app) as client:
        cfg = client.get("/api/scheduler/config").json()
        assert cfg["auto_refresh_stat_subscriptions"] is True
        assert cfg["auto_run_market_rules"] is False


# --------------------------------------------------------------------------- #
# The lane does what the default says
# --------------------------------------------------------------------------- #
def test_the_markets_lane_refreshes_on_a_fresh_install(monkeypatch):
    import src.markets.pipeline as mp
    import src.stats.subscriptions as subs
    from src.scheduler.runner import _lane_step_markets

    calls = {"feeds": 0, "rules": 0, "stats": 0}

    def _feeds(session, *, fetcher, now=None):
        calls["feeds"] += 1
        return {"imported": 0}

    def _rules(session, rules, *, fetcher):
        calls["rules"] += 1
        return {"prices_stored": 0}

    def _stats(session):
        calls["stats"] += 1
        return {"stored": 4}

    monkeypatch.setattr(mp, "import_due_feeds", _feeds)
    monkeypatch.setattr(mp, "run_rules", _rules)
    monkeypatch.setattr(subs, "refresh_due", _stats)

    out = _lane_step_markets(object(), None, SchedulerSettings())
    assert calls == {"feeds": 1, "rules": 0, "stats": 1}
    assert out["stat_vintages"] == 4 and "rules_run" not in out


# --------------------------------------------------------------------------- #
# The hover, x12
# --------------------------------------------------------------------------- #
def test_the_hover_is_the_one_on_the_page_and_the_old_wording_is_gone():
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    assert f'title="{_HOVER}"' in html, "the checkbox hover changed -- update _HOVER and the locales"
    assert "Off by default: before this release they refreshed only" not in html


def test_the_hover_is_keyed_in_all_twelve_locales_and_says_on():
    codes = sorted(p.stem for p in _LOCALES.glob("*.json"))
    assert len(codes) == 12, codes
    for code in codes:
        d = json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))
        assert d.get(_HOVER, "").strip(), f"{code}.json has no translation of the hover"
        # The retired wording must not linger as a stale key a later edit could revive.
        assert not any(k.startswith("Statistics figures you subscribed to are re-fetched")
                       for k in d), f"{code}.json still carries the off-by-default key"
