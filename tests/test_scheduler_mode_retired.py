"""
The scheduler ``mode`` is RETIRED; lanes run beside press (Q1020 = a, Q716 = a; S04-08 S3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What this pins, and why each is its own test:

* The MIGRATION on BOTH stores the brief names -- the encrypted ``app_state`` row (the
  default location, reached through the legacy JSON file's one-time move as well as
  directly) and the redirected JSON file tests and portable installs use. A migration
  proven on one store is a claim about the other.
* The MAPPING (the brief's design note): every lane the old mode implied is ON, press is
  ON. Four modes, four mappings, one of which is deliberately "nothing to switch".
* ONE-TIME by construction: the first save drops ``mode``, so an operator who turns a
  migrated lane back OFF is never overridden on the next load.
* The DISCLOSURE survives that save, is owed only to an install that was actually in a
  non-default mode, and ends only on Dismiss -- which is the one write ``retired_mode``
  accepts.
* The markets lane's two opt-ins do what they say, in isolation from each other and from
  the bundled feeds.
"""

from __future__ import annotations

import json

import pytest

from src.config import kv_store
from src.scheduler import settings as sset
from src.scheduler.settings import (
    SchedulerSettings,
    SchedulerSettingsError,
    load_settings,
    retired_mode_disclosure,
    save_settings,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    kv_store.kv_invalidate()
    yield
    kv_store.kv_invalidate()


def _as_json_store(tmp_path, monkeypatch, blob: dict | None):
    """Redirect to a JSON file (the non-KV store) and seed it."""
    path = tmp_path / "elsewhere" / "scheduler_settings.json"
    path.parent.mkdir()
    if blob is not None:
        path.write_text(json.dumps(blob), "utf-8")
    monkeypatch.setattr(sset, "_settings_path", lambda: path)
    assert not sset._use_kv()
    return path


def _stored(path=None) -> dict:
    if path is not None:
        return json.loads(path.read_text("utf-8"))
    kv_store.kv_invalidate()
    return kv_store.kv_get_json(sset._KV_KEY)


# --------------------------------------------------------------------------- #
# The shape of the retirement
# --------------------------------------------------------------------------- #
def test_the_mode_field_and_its_vocabulary_are_gone():
    import dataclasses

    names = {f.name for f in dataclasses.fields(SchedulerSettings)}
    assert "mode" not in names
    assert not hasattr(sset, "VALID_MODES")


def test_every_retired_mode_but_the_default_owes_a_sentence_naming_its_ruling():
    assert set(sset._RETIRED_MODE_SENTENCES) == {"crawl", "markets", "law", "wiki"}
    for mode, sentence in sset._RETIRED_MODE_SENTENCES.items():
        assert "retired" in sentence and ("Q1020" in sentence or "Q716" in sentence), mode
        # Every non-default mode STOPPED feed collection; the sentence must say it is back
        # (the crawl one words it as "reads your sources' feeds again").
        assert "feed" in sentence, mode


def test_saving_a_mode_is_refused_by_name_even_a_formerly_valid_one(tmp_path, monkeypatch):
    _as_json_store(tmp_path, monkeypatch, None)
    for value in ("rss", "crawl", "wiki"):
        with pytest.raises(SchedulerSettingsError, match="Q1020"):
            save_settings({"mode": value})


# --------------------------------------------------------------------------- #
# The mapping, on the JSON store
# --------------------------------------------------------------------------- #
def test_crawl_mode_maps_to_the_crawl_supplement_on(tmp_path, monkeypatch):
    _as_json_store(
        tmp_path, monkeypatch,
        {"mode": "crawl", "crawl_supplement": False, "crawl_per_pass": 0,
         "crawl_max_depth": 4, "crawl_max_pages": 120},
    )
    s = load_settings()
    assert s.crawl_supplement is True
    assert s.crawl_per_pass == SchedulerSettings().crawl_per_pass
    # The operator's caps survive: they now bound the supplement.
    assert (s.crawl_max_depth, s.crawl_max_pages) == (4, 120)
    assert s.retired_mode == "crawl"
    assert retired_mode_disclosure(s) == [sset._RETIRED_MODE_SENTENCES["crawl"]]


def test_crawl_mode_keeps_a_larger_per_pass_budget_it_already_had(tmp_path, monkeypatch):
    _as_json_store(tmp_path, monkeypatch, {"mode": "crawl", "crawl_per_pass": 9})
    assert load_settings().crawl_per_pass == 9


def test_markets_mode_maps_to_both_markets_opt_ins_on(tmp_path, monkeypatch):
    _as_json_store(tmp_path, monkeypatch, {"mode": "markets"})
    s = load_settings()
    assert s.auto_run_market_rules is True
    assert s.auto_refresh_stat_subscriptions is True
    assert s.retired_mode == "markets"


def test_the_markets_opt_ins_default_off_for_everyone_else(tmp_path, monkeypatch):
    # Off is what every install OUTSIDE markets mode was doing: nobody gains an egress.
    _as_json_store(tmp_path, monkeypatch, {"mode": "rss"})
    s = load_settings()
    assert s.auto_run_market_rules is False
    assert s.auto_refresh_stat_subscriptions is False


def test_wiki_mode_never_overrides_the_operators_own_lane_toggle(tmp_path, monkeypatch):
    _as_json_store(tmp_path, monkeypatch, {"mode": "wiki", "wiki_lane_state": "stopped"})
    s = load_settings()
    assert s.wiki_lane_state == "stopped"
    assert s.retired_mode == "wiki"
    assert retired_mode_disclosure(s) == [sset._RETIRED_MODE_SENTENCES["wiki"]]


def test_law_mode_flips_nothing_and_is_still_disclosed(tmp_path, monkeypatch):
    _as_json_store(tmp_path, monkeypatch, {"mode": "law"})
    s = load_settings()
    base = SchedulerSettings()
    assert s.auto_run_market_rules == base.auto_run_market_rules
    assert s.crawl_supplement == base.crawl_supplement
    assert s.retired_mode == "law"


@pytest.mark.parametrize("value", ["rss", "telepathy", 7, None])
def test_the_default_and_unknown_modes_owe_no_disclosure(tmp_path, monkeypatch, value):
    _as_json_store(tmp_path, monkeypatch, {"mode": value})
    s = load_settings()
    assert s.retired_mode == ""
    assert retired_mode_disclosure(s) == []


def test_a_manufactured_retired_mode_in_the_blob_is_not_believed(tmp_path, monkeypatch):
    _as_json_store(tmp_path, monkeypatch, {"retired_mode": "anything-else"})
    assert load_settings().retired_mode == ""


# --------------------------------------------------------------------------- #
# One-time, and the disclosure's lifetime
# --------------------------------------------------------------------------- #
def test_the_first_save_drops_mode_and_keeps_the_disclosure(tmp_path, monkeypatch):
    path = _as_json_store(tmp_path, monkeypatch, {"mode": "markets"})
    save_settings({"interval_minutes": 30})
    blob = _stored(path)
    assert "mode" not in blob
    assert blob["retired_mode"] == "markets"
    assert blob["auto_run_market_rules"] is True
    assert retired_mode_disclosure() == [sset._RETIRED_MODE_SENTENCES["markets"]]


def test_a_migrated_lane_switched_off_stays_off(tmp_path, monkeypatch):
    """The trap a flag-less migration invites: re-applying the mapping on every load
    would switch the operator's choice back on behind them."""
    _as_json_store(tmp_path, monkeypatch, {"mode": "markets"})
    save_settings({"auto_run_market_rules": False})
    assert load_settings().auto_run_market_rules is False
    assert load_settings().auto_refresh_stat_subscriptions is True


def test_dismiss_is_the_only_write_retired_mode_accepts(tmp_path, monkeypatch):
    _as_json_store(tmp_path, monkeypatch, {"mode": "crawl"})
    with pytest.raises(SchedulerSettingsError):
        save_settings({"retired_mode": "wiki"})
    assert load_settings().retired_mode == "crawl"
    save_settings({"retired_mode": ""})
    assert load_settings().retired_mode == ""
    assert retired_mode_disclosure() == []
    # And dismissing does not undo the migration it described.
    assert load_settings().crawl_supplement is True


# --------------------------------------------------------------------------- #
# The KV store (the default location), directly and via the legacy JSON move
# --------------------------------------------------------------------------- #
def test_migration_on_the_encrypted_kv_store():
    assert sset._use_kv()
    kv_store.kv_set_json(sset._KV_KEY, {"mode": "crawl", "crawl_supplement": False})
    kv_store.kv_invalidate()
    s = load_settings()
    assert s.crawl_supplement is True and s.retired_mode == "crawl"
    save_settings({})
    blob = _stored()
    assert "mode" not in blob and blob["retired_mode"] == "crawl"
    assert blob["crawl_supplement"] is True


def test_migration_through_the_legacy_json_file_into_the_kv_store(tmp_path):
    """The oldest installs carry the mode in ``scheduler_settings.json``, which
    ``_read_raw`` moves into ``app_state`` once. Both migrations must compose: the file's
    mode reaches the lane mapping, and the saved row no longer carries it."""
    (tmp_path / "scheduler_settings.json").write_text(json.dumps({"mode": "markets"}), "utf-8")
    s = load_settings()
    assert s.auto_run_market_rules is True and s.retired_mode == "markets"
    save_settings({})
    blob = _stored()
    assert "mode" not in blob and blob["retired_mode"] == "markets"


# --------------------------------------------------------------------------- #
# The API
# --------------------------------------------------------------------------- #
def test_the_config_endpoint_carries_the_disclosure_and_refuses_mode(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    _as_json_store(tmp_path, monkeypatch, {"mode": "law"})
    with TestClient(app) as client:
        cfg = client.get("/api/scheduler/config").json()
        assert "mode" not in cfg and "valid_modes" not in cfg
        assert cfg["retired"] == [sset._RETIRED_MODE_SENTENCES["law"]]
        refused = client.put("/api/scheduler/config", json={"mode": "rss"})
        assert refused.status_code == 400 and "Q1020" in refused.text
        # The two opt-ins are REACHABLE through the request model -- the recorded
        # settingUnreachable trap is a 200 that changed nothing.
        on = client.put("/api/scheduler/config", json={"auto_run_market_rules": True})
        assert on.status_code == 200 and on.json()["auto_run_market_rules"] is True
        assert client.get("/api/scheduler/config").json()["auto_run_market_rules"] is True
        dismissed = client.put("/api/scheduler/config", json={"retired_mode": ""})
        assert dismissed.status_code == 200 and dismissed.json()["retired"] == []


def test_the_targets_preview_always_applies_now():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as client:
        t = client.get("/api/scheduler/targets").json()
        assert "applies" not in t and "mode" not in t
        assert "matched" in t


# --------------------------------------------------------------------------- #
# The markets lane's two opt-ins
# --------------------------------------------------------------------------- #
class _Calls:
    def __init__(self):
        self.rules = 0
        self.stats = 0
        self.feeds = 0


def _patch_markets(monkeypatch, calls, *, rules_raise=False, stats_raise=False):
    import src.markets.pipeline as mp
    import src.stats.subscriptions as subs

    def _feeds(session, *, fetcher, now=None):
        calls.feeds += 1
        return {"imported": 2}

    def _rules(session, rules, *, fetcher):
        calls.rules += 1
        if rules_raise:
            raise RuntimeError("rule host down")
        return {"prices_stored": 1, "tally": {}}

    def _stats(session):
        calls.stats += 1
        if stats_raise:
            raise RuntimeError("stats host down")
        return {"stored": 3}

    monkeypatch.setattr(mp, "import_due_feeds", _feeds)
    monkeypatch.setattr(mp, "run_rules", _rules)
    monkeypatch.setattr(subs, "refresh_due", _stats)


class _Session:
    """Just enough session for the step: ``query`` for the rules, ``rollback`` on error."""

    def __init__(self):
        self.rolled_back = 0

    def query(self, *_a, **_k):
        return self

    def filter_by(self, **_k):
        return self

    def order_by(self, *_a):
        return self

    def limit(self, *_a):
        return self

    def all(self):
        return []

    def rollback(self):
        self.rolled_back += 1


def test_the_markets_lane_with_both_opt_ins_off_runs_only_the_feeds(monkeypatch):
    from src.scheduler.runner import _lane_step_markets

    calls = _Calls()
    _patch_markets(monkeypatch, calls)
    out = _lane_step_markets(_Session(), None, SchedulerSettings())
    assert (calls.feeds, calls.rules, calls.stats) == (1, 0, 0)
    assert out == {"feed_points": 2}


def test_the_markets_lane_runs_each_opt_in_it_is_given(monkeypatch):
    from src.scheduler.runner import _lane_step_markets

    calls = _Calls()
    _patch_markets(monkeypatch, calls)
    s = SchedulerSettings(auto_run_market_rules=True, auto_refresh_stat_subscriptions=True)
    out = _lane_step_markets(_Session(), None, s)
    assert (calls.feeds, calls.rules, calls.stats) == (1, 1, 1)
    assert out["rules_run"] == 0 and out["prices_stored"] == 1 and out["stat_vintages"] == 3


def test_one_broken_opt_in_costs_neither_the_other_nor_the_feeds(monkeypatch):
    """A failure is RECORDED under its own key, not only logged: "nothing was due" and
    "it broke" must stay two readings in the lane result."""
    from src.scheduler.runner import _lane_step_markets

    calls = _Calls()
    _patch_markets(monkeypatch, calls, rules_raise=True)
    sess = _Session()
    s = SchedulerSettings(auto_run_market_rules=True, auto_refresh_stat_subscriptions=True)
    out = _lane_step_markets(sess, None, s)
    assert out["feed_points"] == 2
    assert "rule host down" in out["rules_error"]
    assert out["stat_vintages"] == 3
    assert sess.rolled_back == 1


# --------------------------------------------------------------------------- #
# x12: the disclosure is a caveat, so it ships in every language
# --------------------------------------------------------------------------- #
def test_every_retired_mode_sentence_is_keyed_in_all_twelve_locales():
    """The UI renders the server's sentence through ``t()``, so a sentence without a key
    renders in English on eleven locales -- the informed-consent non-negotiable's failure
    shape. The key must match the server constant VERBATIM, so it is read from the module,
    never re-typed here."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
    codes = sorted(p.stem for p in root.glob("*.json"))
    assert len(codes) == 12, codes
    for code in codes:
        d = json.loads((root / f"{code}.json").read_text("utf-8"))
        for mode, sentence in sset._RETIRED_MODE_SENTENCES.items():
            assert d.get(sentence, "").strip(), f"{code}.json has no key for retired mode {mode}"


# --------------------------------------------------------------------------- #
# Q716 = a: `POST /api/wiki/pages` SURVIVES the mode, as "pin this page to HOT"
# --------------------------------------------------------------------------- #
def test_the_watch_endpoint_survives_as_pin_to_hot():
    """Anchored to the wiki router's OWN route definitions, never to the shared app
    singleton (the recorded flaky-route-guard lesson): retiring ``mode="wiki"`` must not
    take the endpoint with it, and the endpoint must still write the lane's pin."""
    import inspect

    from src.api import wiki as wiki_api

    posts = {
        getattr(r, "path", "")
        for r in wiki_api.router.routes
        if "POST" in (getattr(r, "methods", None) or ())
    }
    assert "/api/wiki/pages" in posts or "/pages" in posts, sorted(posts)
    assert "_pin_to_hot(" in inspect.getsource(wiki_api.add_page)
