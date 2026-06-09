"""
Persisted safety settings — fetch mode + proxy (the same small-JSON pattern as the rest).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``fetch_mode`` chooses how the ethical fetcher behaves:

  * ``transparent`` (default) — identifying User-Agent, no proxy: honest, ethical broad
    collection (announces the bot, as a good crawler should).
  * ``protected`` — route through ``http_proxy`` (e.g. Tor at ``socks5://127.0.0.1:9050``)
    and send a generic User-Agent, so investigating a powerful target need not announce the
    journalist from their real IP. Source protection is itself a journalistic duty; it is
    opt-in and never the silent default.

Environment overrides (for ephemeral/headless use): ``OO_FETCH_MODE``, ``OO_HTTP_PROXY``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass

_LOG = logging.getLogger(__name__)
SETTINGS_VERSION = "oo-safety-settings-1"
VALID_MODES = ("transparent", "protected")
# A neutral, common User-Agent for Protected mode (does not name this tool).
GENERIC_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


class SafetySettingsError(ValueError):
    """Raised when a safety settings update carries an invalid value."""


@dataclass
class SafetySettings:
    fetch_mode: str = "transparent"
    http_proxy: str = ""              # e.g. socks5://127.0.0.1:9050 or http://127.0.0.1:8118

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_protected(self) -> bool:
        return self.fetch_mode == "protected"


def _path():
    from src.paths import data_dir

    return data_dir() / "safety_settings.json"


def load_settings() -> SafetySettings:
    """Load safety settings; env vars override the persisted file (for headless use)."""
    s = SafetySettings()
    path = _path()
    if path.exists():
        try:
            raw = json.loads(path.read_text("utf-8"))
            mode = raw.get("fetch_mode", s.fetch_mode)
            if mode in VALID_MODES:
                s.fetch_mode = mode
            if isinstance(raw.get("http_proxy"), str):
                s.http_proxy = raw["http_proxy"].strip()
        except Exception:  # noqa: BLE001 - a bad file must not break startup
            _LOG.warning("safety_settings.json unreadable; using defaults", exc_info=True)
    env_mode = os.getenv("OO_FETCH_MODE")
    if env_mode in VALID_MODES:
        s.fetch_mode = env_mode
    env_proxy = os.getenv("OO_HTTP_PROXY")
    if env_proxy is not None:
        s.http_proxy = env_proxy.strip()
    return s


def save_settings(updates: dict) -> SafetySettings:
    """Apply a partial update and persist atomically. Validates before writing."""
    current = load_settings()
    if "fetch_mode" in updates and updates["fetch_mode"] is not None:
        mode = str(updates["fetch_mode"])
        if mode not in VALID_MODES:
            raise SafetySettingsError(f"fetch_mode must be one of {VALID_MODES}")
        current.fetch_mode = mode
    if "http_proxy" in updates and updates["http_proxy"] is not None:
        current.http_proxy = str(updates["http_proxy"]).strip()
    if current.is_protected and not current.http_proxy:
        raise SafetySettingsError("protected mode requires an http_proxy (e.g. socks5://127.0.0.1:9050)")
    path = _path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": SETTINGS_VERSION, **current.to_dict()},
                              indent=2, sort_keys=True), "utf-8")
    tmp.replace(path)
    return current
