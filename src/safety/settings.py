"""
Persisted safety settings — fetch mode + proxy (the same small-JSON pattern as the rest).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``fetch_mode`` chooses how the ethical fetcher behaves:

  * ``transparent`` (default) — identifying User-Agent, no proxy: honest, ethical broad
    collection (announces the bot, as a good crawler should).
  * ``protected`` — route through ``http_proxy`` (e.g. Tor at ``socks5h://127.0.0.1:9050``)
    and send a generic User-Agent, so investigating a powerful target need not announce the
    journalist from their real IP. Source protection is itself a journalistic duty; it is
    opt-in and never the silent default. The recommended scheme is ``socks5h`` (not
    ``socks5``) — the trailing "h" means the PROXY resolves the hostname (the curl/PySocks
    convention), so DNS queries never reach the local/ISP resolver either; a plain
    ``socks5``/``socks4`` proxy still works but resolves locally (see
    ``src.ingest._is_remote_resolving_proxy``, 2026-07-24 throughput brief C8).

Environment overrides (for ephemeral/headless use): ``OO_FETCH_MODE``, ``OO_HTTP_PROXY``,
``OO_HTTP_PROXIES`` (comma-separated pool, see ``http_proxies`` below).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field

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
    http_proxy: str = ""  # e.g. socks5h://127.0.0.1:9050 (recommended) or http://127.0.0.1:8118
    # C10 (2026-07-24 throughput brief, §6b): an OPERATOR-RUN pool of SOCKS
    # endpoints (e.g. several independent Tor instances on different ports/
    # bridges), so raising collect_parallelism (C9) doesn't hit a single Tor
    # client's own circuit ceiling. TAKES PRECEDENCE over http_proxy when
    # non-empty (see make_fetcher). ALL-TOR OR REFUSED: every entry must be a
    # SOCKS proxy (socks5h/socks4a recommended, same DNS-leak reasoning as
    # http_proxy above) -- save_settings refuses the WHOLE update if even one
    # entry is not SOCKS (never a silent per-host downgrade). The app never
    # spawns these processes; the operator runs and trusts them.
    http_proxies: list[str] = field(default_factory=list)
    # The ONE external-service call in the app (audit finding ETH-02 / RM-03):
    # topic discovery sends the user's query to DuckDuckGo. OFF by default --
    # an at-risk operator must opt in knowingly; the UI states plainly that the
    # query leaves the machine. RSS discovery of operator-added sources is NOT
    # affected (it fetches those sites via the EthicalFetcher, no third party).
    discovery_external_enabled: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_protected(self) -> bool:
        return self.fetch_mode == "protected"


# The ``app_state`` kv key this preference blob lives under (DB-reliability D1).
_KV_KEY = "settings.safety"


def _path():
    from src.paths import data_dir

    return data_dir() / "safety_settings.json"


def _use_kv() -> bool:
    """Use the encrypted ``app_state`` store at the DEFAULT location; honour a redirected
    ``_path`` (test isolation) as JSON instead. See app_settings._use_kv."""
    from src.paths import data_dir

    return _path() == data_dir() / "safety_settings.json"


def _read_json_file() -> dict | None:
    path = _path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a bad file must not break startup
        _LOG.warning("safety_settings.json unreadable; using defaults", exc_info=True)
        return None


def _read_raw() -> dict | None:
    """Safety prefs source of truth: the encrypted ``app_state`` row (D1), falling back
    to (and one-time migrating) the legacy ``safety_settings.json`` file."""
    if not _use_kv():
        return _read_json_file()
    from src.config.kv_store import kv_get_json, kv_set_json

    raw = kv_get_json(_KV_KEY)
    if raw is not None:
        return raw
    raw = _read_json_file()
    if raw is None:
        return None
    try:
        kv_set_json(_KV_KEY, raw)
    except Exception:  # noqa: BLE001 - migration is best-effort; retried next load
        _LOG.debug("safety_settings migration into app_state deferred", exc_info=True)
    return raw


def _clean_proxy_list(raw) -> list[str]:
    """Best-effort normalise a persisted/env proxy-pool value into a list of
    non-empty, stripped strings -- never crashes, never invents an entry."""
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        return []
    return [p.strip() for p in raw if isinstance(p, str) and p.strip()]


def load_settings() -> SafetySettings:
    """Load safety settings; env vars override the persisted value (for headless use)."""
    s = SafetySettings()
    raw = _read_raw()
    if raw is not None:
        mode = raw.get("fetch_mode", s.fetch_mode)
        if mode in VALID_MODES:
            s.fetch_mode = mode
        if isinstance(raw.get("http_proxy"), str):
            s.http_proxy = raw["http_proxy"].strip()
        if "http_proxies" in raw:
            s.http_proxies = _clean_proxy_list(raw.get("http_proxies"))
        if isinstance(raw.get("discovery_external_enabled"), bool):
            s.discovery_external_enabled = raw["discovery_external_enabled"]
    env_mode = os.getenv("OO_FETCH_MODE")
    if env_mode in VALID_MODES:
        s.fetch_mode = env_mode
    env_proxy = os.getenv("OO_HTTP_PROXY")
    if env_proxy is not None:
        s.http_proxy = env_proxy.strip()
    env_pool = os.getenv("OO_HTTP_PROXIES")
    if env_pool is not None:
        s.http_proxies = _clean_proxy_list(env_pool)
    env_discovery = os.getenv("OO_DISCOVERY_EXTERNAL")
    if env_discovery is not None:
        s.discovery_external_enabled = env_discovery.strip().lower() in ("1", "true", "yes")
    return s


def save_settings(updates: dict) -> SafetySettings:
    """Apply a partial update and persist atomically. Validates before writing."""
    from src.safety.fetcher import validate_socks_pool

    current = load_settings()
    if "fetch_mode" in updates and updates["fetch_mode"] is not None:
        mode = str(updates["fetch_mode"])
        if mode not in VALID_MODES:
            raise SafetySettingsError(f"fetch_mode must be one of {VALID_MODES}")
        current.fetch_mode = mode
    if "http_proxy" in updates and updates["http_proxy"] is not None:
        current.http_proxy = str(updates["http_proxy"]).strip()
    if "http_proxies" in updates and updates["http_proxies"] is not None:
        pool_raw = updates["http_proxies"]
        if not isinstance(pool_raw, list) or not all(isinstance(p, str) for p in pool_raw):
            raise SafetySettingsError("http_proxies must be a list of proxy URL strings")
        pool = _clean_proxy_list(pool_raw)
        if pool:
            try:
                validate_socks_pool(pool)
            except ValueError as exc:
                # ALL-TOR OR REFUSED (C10, transport honesty): a single non-SOCKS
                # entry refuses the WHOLE update -- never partially applied, never
                # a silent per-host downgrade to clearnet.
                raise SafetySettingsError(str(exc)) from exc
        current.http_proxies = pool
    if "discovery_external_enabled" in updates and updates["discovery_external_enabled"] is not None:
        current.discovery_external_enabled = bool(updates["discovery_external_enabled"])
    if current.is_protected and not current.http_proxy and not current.http_proxies:
        raise SafetySettingsError(
            "protected mode requires an http_proxy (e.g. socks5h://127.0.0.1:9050)"
        )
    payload = {"version": SETTINGS_VERSION, **current.to_dict()}
    if not _use_kv():
        path = _path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
        tmp.replace(path)
        return current
    from src.config.kv_store import kv_set_json

    kv_set_json(_KV_KEY, payload)
    return current
