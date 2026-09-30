"""R53: the Wikipedia lane's storage budget defaults to 150 GB, still lowerable to 20 GB.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R53 (2026-09-29): «switch the 20 GB default to 150 GB, while allowing users to lower the
default to 20 GB». A settings save writes EVERY field, so an install that ever saved anything
holds ``20`` as its budget whether or not anyone chose it, and changing the code default alone
would never reach it. What is pinned here is how that is handled without raising a cap on
anyone's disk who agreed to a smaller one:

* a machine that never saw the wizard and holds only the old default moves to the new one;
* a number somebody SET stays theirs, 20 included, and so does one an operator who went
  through the wizard kept;
* and lowering to 20 GB (or to anything down to the floor) is accepted and sticks.
"""

from __future__ import annotations

import json

import pytest

from src.scheduler import settings as sch


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "scheduler_settings.json"
    monkeypatch.setattr(sch, "_settings_path", lambda: path)

    def write(**raw):
        path.write_text(json.dumps({"version": sch.SETTINGS_VERSION, **raw}), "utf-8")

    return write


def test_the_published_default_is_150_and_the_old_one_is_kept_as_history():
    assert sch.WIKI_LANE_DEFAULT_BUDGET_GB == 150
    assert sch.WIKI_LANE_LEGACY_DEFAULT_BUDGET_GB == 20
    assert sch.SchedulerSettings().wiki_lane_budget_gb == 150


def test_a_fresh_install_gets_the_new_default(store):
    assert sch.load_settings().wiki_lane_budget_gb == 150


def test_an_untouched_old_default_follows_the_new_one_when_the_wizard_was_never_seen(store):
    store(wiki_lane_budget_gb=20)  # written before R53: no marker, the default of its day
    assert sch.load_settings().wiki_lane_budget_gb == 150


def test_a_budget_the_operator_kept_through_the_wizard_stays_at_what_they_agreed_to(store):
    store(wiki_lane_budget_gb=20, wiki_lane_wizard_done=True)
    assert sch.load_settings().wiki_lane_budget_gb == 20, "their cap on their disk is not raised silently"


def test_a_number_that_is_not_the_old_default_is_never_touched(store):
    store(wiki_lane_budget_gb=35)
    assert sch.load_settings().wiki_lane_budget_gb == 35


def test_lowering_to_20_after_the_change_is_a_choice_and_sticks(store):
    store(wiki_lane_budget_gb=20)
    assert sch.load_settings().wiki_lane_budget_gb == 150  # the follow
    saved = sch.save_settings({"wiki_lane_budget_gb": 20})  # the operator lowers it
    assert saved.wiki_lane_budget_gb == 20
    assert sch.load_settings().wiki_lane_budget_gb == 20, "a deliberate 20 is not read as the old default"
    sch.save_settings({"interval_minutes": 60})  # any later save keeps it
    assert sch.load_settings().wiki_lane_budget_gb == 20


def test_the_marker_is_written_on_every_save_and_never_taken_from_a_caller(store, tmp_path):
    sch.save_settings({"interval_minutes": 45})
    raw = json.loads((tmp_path / "scheduler_settings.json").read_text("utf-8"))
    assert raw["wiki_lane_default_seen"] == 150
    sch.save_settings({"wiki_lane_default_seen": 20})  # an undeclared key: ignored, never stored
    raw = json.loads((tmp_path / "scheduler_settings.json").read_text("utf-8"))
    assert raw["wiki_lane_default_seen"] == 150


def test_the_bounds_are_unchanged_so_20_or_anything_down_to_one_is_accepted():
    assert (sch.WIKI_LANE_BUDGET_GB_MIN, sch.WIKI_LANE_BUDGET_GB_MAX) == (1, 2000)
    for gb in (1, 20, 150, 2000):
        assert sch._require_wiki_lane_budget_gb(gb) == gb
    for bad in (0, 2001):
        with pytest.raises(sch.SchedulerSettingsError):
            sch._require_wiki_lane_budget_gb(bad)
