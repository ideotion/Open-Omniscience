"""The pinned-Chromium finder (row 157, F1): an installed build is found in today's layout, and a build it cannot read
fails by name instead of reading as "no browser".

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.monitoring.pinned_chromium import ChromiumLayoutUnknown, find_pinned_chromium


@pytest.fixture
def browsers(tmp_path, monkeypatch):
    monkeypatch.delenv("OO_TEST_CHROMIUM_PATH", raising=False)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    return tmp_path


def _exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_no_build_installed_is_none_so_a_caller_may_skip(browsers):
    (browsers / "ffmpeg-1011").mkdir()
    (browsers / "chromium_headless_shell-1243").mkdir()  # not a chromium-<n> build folder
    assert find_pinned_chromium() is None


def test_todays_linux64_layout_is_found(browsers):
    exe = _exe(browsers / "chromium-1243" / "chrome-linux64" / "chrome")
    assert find_pinned_chromium() == str(exe)


def test_the_older_linux_layout_is_still_found(browsers):
    exe = _exe(browsers / "chromium-1100" / "chrome-linux" / "chrome")
    assert find_pinned_chromium() == str(exe)


def test_a_build_in_an_unknown_layout_fails_by_name_and_never_reads_as_absent(browsers):
    _exe(browsers / "chromium-1300" / "chrome-somewhere-new" / "chrome")
    with pytest.raises(ChromiumLayoutUnknown, match="chromium-1300"):
        find_pinned_chromium()


def test_the_newest_build_wins_by_number_not_by_text(browsers):
    _exe(browsers / "chromium-999" / "chrome-linux64" / "chrome")
    newest = _exe(browsers / "chromium-1243" / "chrome-linux64" / "chrome")
    assert find_pinned_chromium() == str(newest)


def test_an_override_that_does_not_exist_is_an_error_not_a_skip(browsers, monkeypatch):
    monkeypatch.setenv("OO_TEST_CHROMIUM_PATH", str(browsers / "missing" / "chrome"))
    with pytest.raises(ChromiumLayoutUnknown, match="does not exist"):
        find_pinned_chromium()


def test_an_existing_override_wins(browsers, monkeypatch):
    _exe(browsers / "chromium-1243" / "chrome-linux64" / "chrome")
    mine = _exe(browsers / "mine" / "chrome")
    monkeypatch.setenv("OO_TEST_CHROMIUM_PATH", str(mine))
    assert find_pinned_chromium() == str(mine)
