"""
Persisted, GUI-editable application preferences.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src.config.Config`` is loaded once from env/YAML and is deployment-scoped --
not the right home for things the operator flips from the Settings tab. Those
live here, in a small self-describing JSON file under the data dir, read/written
at runtime (same pattern as ``src.custody.settings``).

Deliberately tiny: only genuine UI preferences belong here. Heavier subsystems
(scheduler, crawl, market rules) keep their own stores so each can evolve and be
tested independently.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

_LOG = logging.getLogger(__name__)

SETTINGS_VERSION = "oo-app-settings-1"
VALID_THEMES = ("system", "dark", "light")
_MIN_LIMIT, _MAX_LIMIT = 1, 1000


class AppSettingsError(ValueError):
    """Raised when a settings update carries an invalid value."""


@dataclass
class AppSettings:
    """Operator-controlled UI preferences."""

    theme: str = "system"
    default_result_limit: int = 50

    def to_dict(self) -> dict:
        return asdict(self)


def _settings_path():
    from src.paths import data_dir

    return data_dir() / "app_settings.json"


def load_settings() -> AppSettings:
    """Load preferences, falling back to defaults on a missing/corrupt file."""
    path = _settings_path()
    if not path.exists():
        return AppSettings()
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a bad file must not take down the API
        _LOG.warning("app_settings.json is unreadable; using defaults", exc_info=True)
        return AppSettings()

    defaults = AppSettings()
    theme = raw.get("theme", defaults.theme)
    if theme not in VALID_THEMES:
        _LOG.warning("ignoring invalid stored theme %r", theme)
        theme = defaults.theme
    try:
        limit = int(raw.get("default_result_limit", defaults.default_result_limit))
    except (TypeError, ValueError):
        limit = defaults.default_result_limit
    limit = max(_MIN_LIMIT, min(_MAX_LIMIT, limit))
    return AppSettings(theme=theme, default_result_limit=limit)


def save_settings(updates: dict) -> AppSettings:
    """Apply a partial update and persist atomically. Validates before writing."""
    current = load_settings()

    if "theme" in updates and updates["theme"] is not None:
        theme = str(updates["theme"])
        if theme not in VALID_THEMES:
            raise AppSettingsError(
                f"unknown theme {theme!r}; use one of: {', '.join(VALID_THEMES)}"
            )
        current.theme = theme
    if "default_result_limit" in updates and updates["default_result_limit"] is not None:
        try:
            limit = int(updates["default_result_limit"])
        except (TypeError, ValueError) as exc:
            raise AppSettingsError("default_result_limit must be an integer") from exc
        if not (_MIN_LIMIT <= limit <= _MAX_LIMIT):
            raise AppSettingsError(
                f"default_result_limit must be between {_MIN_LIMIT} and {_MAX_LIMIT}"
            )
        current.default_result_limit = limit

    path = _settings_path()
    tmp = path.with_suffix(".json.tmp")
    payload = {"version": SETTINGS_VERSION, **current.to_dict()}
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
    tmp.replace(path)  # atomic on the same filesystem
    return current
