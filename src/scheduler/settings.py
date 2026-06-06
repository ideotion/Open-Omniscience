"""
Persisted, GUI-editable scheduler configuration.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Same small-JSON-file pattern as custody/app settings. ``autostart`` records
whether the scheduler should begin running on app launch; the live running state
is separate (the operator can start/stop without changing the preference).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

_LOG = logging.getLogger(__name__)

SETTINGS_VERSION = "oo-scheduler-settings-1"
VALID_MODES = ("rss", "crawl")
_MIN_INTERVAL, _MAX_INTERVAL = 1, 7 * 24 * 60  # minutes: 1 min .. 1 week


class SchedulerSettingsError(ValueError):
    """Raised when a scheduler settings update carries an invalid value."""


@dataclass
class SchedulerSettings:
    """Operator-controlled scheduling preferences."""

    autostart: bool = False
    interval_minutes: int = 60
    mode: str = "rss"               # "rss" (feeds) or "crawl" (bounded recursion)
    max_sources_per_run: int = 25
    crawl_max_depth: int = 2
    crawl_max_pages: int = 50

    def to_dict(self) -> dict:
        return asdict(self)


def _settings_path():
    from src.paths import data_dir

    return data_dir() / "scheduler_settings.json"


def _coerce_bool(value, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return fallback


def _coerce_int(value, fallback: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return fallback


def load_settings() -> SchedulerSettings:
    """Load scheduler settings, falling back to safe defaults."""
    path = _settings_path()
    d = SchedulerSettings()
    if not path.exists():
        return d
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a bad file must not break startup
        _LOG.warning("scheduler_settings.json unreadable; using defaults", exc_info=True)
        return d
    mode = raw.get("mode", d.mode)
    if mode not in VALID_MODES:
        _LOG.warning("ignoring invalid stored scheduler mode %r", mode)
        mode = d.mode
    return SchedulerSettings(
        autostart=_coerce_bool(raw.get("autostart"), d.autostart),
        interval_minutes=_coerce_int(raw.get("interval_minutes"), d.interval_minutes, _MIN_INTERVAL, _MAX_INTERVAL),
        mode=mode,
        max_sources_per_run=_coerce_int(raw.get("max_sources_per_run"), d.max_sources_per_run, 1, 1000),
        crawl_max_depth=_coerce_int(raw.get("crawl_max_depth"), d.crawl_max_depth, 0, 6),
        crawl_max_pages=_coerce_int(raw.get("crawl_max_pages"), d.crawl_max_pages, 1, 500),
    )


def save_settings(updates: dict) -> SchedulerSettings:
    """Apply a partial update and persist atomically. Validates before writing."""
    current = load_settings()

    if "mode" in updates and updates["mode"] is not None:
        mode = str(updates["mode"])
        if mode not in VALID_MODES:
            raise SchedulerSettingsError(
                f"unknown mode {mode!r}; use one of: {', '.join(VALID_MODES)}"
            )
        current.mode = mode
    if "autostart" in updates and updates["autostart"] is not None:
        current.autostart = _coerce_bool(updates["autostart"], current.autostart)

    def _ranged(key: str, lo: int, hi: int, label: str) -> None:
        if key in updates and updates[key] is not None:
            try:
                v = int(updates[key])
            except (TypeError, ValueError) as exc:
                raise SchedulerSettingsError(f"{label} must be an integer") from exc
            if not (lo <= v <= hi):
                raise SchedulerSettingsError(f"{label} must be between {lo} and {hi}")
            setattr(current, key, v)

    _ranged("interval_minutes", _MIN_INTERVAL, _MAX_INTERVAL, "interval_minutes")
    _ranged("max_sources_per_run", 1, 1000, "max_sources_per_run")
    _ranged("crawl_max_depth", 0, 6, "crawl_max_depth")
    _ranged("crawl_max_pages", 1, 500, "crawl_max_pages")

    path = _settings_path()
    tmp = path.with_suffix(".json.tmp")
    payload = {"version": SETTINGS_VERSION, **current.to_dict()}
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
    tmp.replace(path)
    return current
