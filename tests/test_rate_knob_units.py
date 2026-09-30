"""PF08 = a (2026-09-30): the collection-speed knob says kbit/s, because that is what it is.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``collect_target_kbps`` is kilobits per second. The top-bar knob's hover and two toasts
called the same 500 "500 KiB/s" -- 8.192x too much -- for as long as the knob existed. The
maintainer chose to change the WORDS (the stored setting and the governor stay exactly as
they are), so this pins the words, in the source and in every locale.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = sorted((ROOT / "src" / "static" / "locales").glob("*.json"))
# The three strings the knob shows: the hover in each state and the toast that names 500.
_MARK = "500 kbit/s"


def test_no_user_facing_string_calls_the_setting_kib():
    for name in ("app-sources.js", "index.html", "app-core.js"):
        src = (ROOT / "src" / "static" / name).read_text(encoding="utf-8")
        assert "KiB/s" not in src, f"{name} still names the speed setting in KiB/s"


def test_the_three_knob_strings_are_rekeyed_in_all_twelve_locales_never_duplicated():
    assert len(LOCALES) == 12
    for f in LOCALES:
        data = json.loads(f.read_text(encoding="utf-8"))
        keyed = [k for k in data if _MARK in k]
        assert len(keyed) == 3, f"{f.name}: expected the three knob strings, found {len(keyed)}"
        stale = [k for k in data if "500 KiB/s" in k]
        assert not stale, f"{f.name} keeps the old key beside the new one: {stale}"
        for k in keyed:
            v = data[k]
            assert "KiB" not in v and "КиБ" not in v and "كيلوبايت" not in v and "কিলোবাইট" not in v, (
                f"{f.name}: {k!r} still states a byte unit"
            )


def test_the_stored_setting_and_the_governor_were_not_touched():
    """The ruling moved words, not arithmetic. `collect_target_kbps` keeps its name and its
    500 default, and the governor still reads it as kilobits per second."""
    from src.scheduler.settings import SchedulerSettings

    assert SchedulerSettings().collect_target_kbps == 500
