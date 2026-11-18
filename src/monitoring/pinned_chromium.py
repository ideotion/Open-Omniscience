"""Find the pinned Chromium build the UI walk drives, and say so loudly when a build is there but unreadable (row 157, F1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. Three callers (``scripts/ui_clickthrough_run.py``, ``scripts/appjs_decomposition_check.py`` and
``tests/test_ui_walk_playwright.py``) each globbed ``chromium-*/chrome-linux/chrome``. Playwright's builds now unpack to
``chrome-linux64/chrome``, so the glob found nothing on a machine that HAS a browser: the click-through refused to start,
and the 31 driver tests skipped as if no browser were installed (they pass 31 of 31 once pointed at the binary). A skip
that hides a present browser is a failure reading as an absence, so this module tells the two apart:

* no ``chromium-*`` build folder at all -> :func:`find_pinned_chromium` returns ``None`` (nothing installed; a test may
  skip on that, and says why);
* a build folder whose binary is in no layout listed here -> :class:`ChromiumLayoutUnknown`, naming the folders it looked
  in, so the next layout change fails by name instead of skipping.

``OO_TEST_CHROMIUM_PATH`` always wins, and a path given there that does not exist is an error too, never a skip.
Nothing here downloads a browser (never ``playwright install``, which fetches one over the network).
"""

from __future__ import annotations

import os
from pathlib import Path

#: The executable inside a Playwright Chromium build folder, per layout (newest first). ``chrome-linux`` is the older
#: Linux layout; the others are the current Linux, Windows and macOS ones.
_BINARY_LAYOUTS: tuple[tuple[str, ...], ...] = (
    ("chrome-linux64", "chrome"),
    ("chrome-linux", "chrome"),
    ("chrome-win64", "chrome.exe"),
    ("chrome-win", "chrome.exe"),
    ("chrome-mac-arm64", "Chromium.app", "Contents", "MacOS", "Chromium"),
    ("chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
)


class ChromiumLayoutUnknown(RuntimeError):
    """A Chromium build is present but its executable is in none of the known layouts (or the override is missing)."""


def browsers_dir() -> Path:
    """Where pinned builds live: ``PLAYWRIGHT_BROWSERS_PATH``, else ``/opt/pw-browsers``."""
    return Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))


def find_pinned_chromium() -> str | None:
    """The Chromium executable to drive, ``None`` when no build is installed at all, or :class:`ChromiumLayoutUnknown`.

    The newest build folder wins (``chromium-1243`` before ``chromium-1200``), compared by its number, not as text.
    """
    override = os.environ.get("OO_TEST_CHROMIUM_PATH")
    if override:
        if not Path(override).exists():
            raise ChromiumLayoutUnknown(f"OO_TEST_CHROMIUM_PATH names {override}, which does not exist")
        return override
    base = browsers_dir()
    builds = [d for d in base.glob("chromium-*") if d.is_dir() and d.name.split("-", 1)[1].isdigit()]
    if not builds:
        return None
    builds.sort(key=lambda d: int(d.name.split("-", 1)[1]), reverse=True)
    for build in builds:
        for layout in _BINARY_LAYOUTS:
            exe = build.joinpath(*layout)
            if exe.is_file():
                return str(exe)
    looked = ", ".join(str(d) for d in builds)
    raise ChromiumLayoutUnknown(
        f"a Chromium build is installed ({looked}) but its executable is in none of the known layouts "
        f"({', '.join('/'.join(x) for x in _BINARY_LAYOUTS)}); add the new layout to "
        "src/monitoring/pinned_chromium.py or set OO_TEST_CHROMIUM_PATH"
    )
