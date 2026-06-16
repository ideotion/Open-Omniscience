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
import re
from dataclasses import asdict, dataclass

_LOG = logging.getLogger(__name__)

SETTINGS_VERSION = "oo-app-settings-1"
VALID_THEMES = ("system", "dark", "light")
_MIN_LIMIT, _MAX_LIMIT = 1, 1000
# Ollama model tag grammar (registry/name:tag) — validated so a stored model name
# can never inject into the LLM request path (mirrors src.api.llm._MODEL_RE).
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class AppSettingsError(ValueError):
    """Raised when a settings update carries an invalid value."""


@dataclass
class AppSettings:
    """Operator-controlled UI preferences."""

    theme: str = "system"
    default_result_limit: int = 50
    # Investigation-recipe producers the operator switched off (0.0.8 WP8 /
    # RM-20). All recipes are on by default; a name in this list makes that
    # producer yield no cards.
    recipes_disabled: list = None  # type: ignore[assignment]
    # Active local LLM model tag (maintainer Q10, 2026-06-16): a STORED UI setting
    # that replaces the env-only OO_LLM_MODEL as the operator's default. None =
    # fall back to DEFAULT_MODEL (env/built-in).
    llm_model: str | None = None

    def __post_init__(self) -> None:
        if self.recipes_disabled is None:
            self.recipes_disabled = []

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
    raw_disabled = raw.get("recipes_disabled", [])
    recipes_disabled = (
        [str(x) for x in raw_disabled] if isinstance(raw_disabled, list) else []
    )
    llm_model = raw.get("llm_model")
    if llm_model is not None and not _MODEL_RE.match(str(llm_model)):
        _LOG.warning("ignoring invalid stored llm_model %r", llm_model)
        llm_model = None
    return AppSettings(
        theme=theme,
        default_result_limit=limit,
        recipes_disabled=recipes_disabled,
        llm_model=str(llm_model) if llm_model else None,
    )


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
    if "recipes_disabled" in updates and updates["recipes_disabled"] is not None:
        names = updates["recipes_disabled"]
        if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
            raise AppSettingsError("recipes_disabled must be a list of producer names")
        current.recipes_disabled = sorted(set(names))
    if "llm_model" in updates:
        val = updates["llm_model"]
        # Empty string / None clears the override (back to DEFAULT_MODEL).
        if val in (None, ""):
            current.llm_model = None
        elif isinstance(val, str) and _MODEL_RE.match(val):
            current.llm_model = val
        else:
            raise AppSettingsError(f"invalid llm_model {val!r} (must be an Ollama model tag)")

    path = _settings_path()
    tmp = path.with_suffix(".json.tmp")
    payload = {"version": SETTINGS_VERSION, **current.to_dict()}
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
    tmp.replace(path)  # atomic on the same filesystem
    return current
