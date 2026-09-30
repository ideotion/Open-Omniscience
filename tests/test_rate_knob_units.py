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
    # Every UI source, not a named few: if the strings move to another app-*.js file the
    # ratchet must still see them.
    files = sorted((ROOT / "src" / "static").glob("app*.js")) + [ROOT / "src" / "static" / "index.html"]
    assert len(files) > 5
    for f in files:
        src = f.read_text(encoding="utf-8")
        assert "500 KiB" not in src, f"{f.name} still names the speed target in KiB/s"
    for name in ("app-sources.js", "index.html", "app-core.js"):
        src = (ROOT / "src" / "static" / name).read_text(encoding="utf-8")
        assert "KiB/s" not in src, f"{name} still names the speed setting in KiB/s"


def test_the_setting_is_documented_in_kilobits_where_a_developer_reads_it_first():
    """A comment saying KiB/s beside the setting is how the 8.192x error comes back: the next
    session reads it, decides the new label is wrong and reverts the UI."""
    for rel in ("src/scheduler/settings.py", "src/api/scheduler.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "collect_target_kbps" in line or "download-rate" in line:
                assert "KiB/s" not in line, f"{rel}: {line.strip()}"


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
            # A byte unit in any script, and (the positive half) a KILOBIT unit in the
            # language's own or the Latin spelling: a value that said "500 KB/s" or lost
            # its unit altogether must not pass.
            for byte_word in ("KiB", "KB/s", "Ko/s", "КиБ", "Кб/с", "كيلوبايت", "কিলোবাইট", "किलोबाइट", "キロバイト", "千字节"):
                assert byte_word not in v, f"{f.name}: {k!r} still states a byte unit ({byte_word})"
            assert any(u in v for u in ("kbit/s", "кбит/с", "كيلوبت", "কিলোবিট", "किलोबिट", "キロビット", "千比特")), (
                f"{f.name}: {k!r} names no kilobit unit"
            )


def test_the_stored_setting_and_the_governor_were_not_touched():
    """The ruling moved words, not arithmetic. `collect_target_kbps` keeps its name and its
    500 default, and the governor still reads it as kilobits per second."""
    from src.scheduler.settings import SchedulerSettings

    assert SchedulerSettings().collect_target_kbps == 500


def test_the_measured_rate_the_target_is_compared_with_is_in_kilobits():
    """The other half of "kilobits per second": ``ActivityMonitor.download_rate_kbps`` must
    stay bytes x 8 / 1000. 125,000 bytes in one second is exactly 1000 kbit/s (it would read
    976.6 if someone made it bytes / 1024), so the knob's label and the governor's
    comparison keep agreeing."""
    import time

    from src.monitoring.activity import ActivityMonitor

    mon = ActivityMonitor()
    now = time.time()
    mon._rate_ring.clear()
    mon._rate_ring.append((now - 1.0, 0))
    mon._rate_ring.append((now, 125_000))
    assert mon.download_rate_kbps(window_s=8.0) == 1000.0
