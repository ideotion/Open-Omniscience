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


class _DamagedSettings(SafetySettingsError):
    """The stored settings are there and cannot be parsed (as against a store that could not be opened). A save that supplies the
    whole connection choice replaces them: choosing the connection again is the remedy, and the user's own action."""


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

    #: True on the settings :func:`load_settings` makes when the stored choice could not be READ (locked, keyed to another
    #: passphrase, damaged). Not a field, so it is in no saved or served dict. Such settings are protected with no proxy, which
    #: no fetcher or session turns into a direct connection (``TransportUnavailable`` / a transport refusal): offline, as the app
    #: starts (R117), until the store reads again.
    read_failed = False


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
    """The legacy ``safety_settings.json``: ``None`` when there is no file. A file that is there and cannot be read, or is not a
    JSON object, raises ``KvReadError`` (the class only): it is the user's saved choice, damaged, and reading it as the defaults
    would be the direct connection."""
    from src.config.kv_store import KvReadError

    path = _path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception as exc:  # noqa: BLE001 - failed closed, by class
        _LOG.warning("safety_settings.json unreadable (%s); the transport stays closed", type(exc).__name__)
        raise KvReadError(type(exc).__name__, damaged=isinstance(exc, ValueError)) from None
    if not isinstance(raw, dict):
        _LOG.warning("safety_settings.json is not an object; the transport stays closed")
        raise KvReadError("NotAnObject", damaged=True)
    return raw


def _read_raw() -> dict | None:
    """Safety prefs source of truth: the encrypted ``app_state`` row (D1), falling back
    to (and one-time migrating) the legacy ``safety_settings.json`` file."""
    if not _use_kv():
        return _read_json_file()
    from src.config.kv_store import kv_get_json_checked, kv_set_json

    raw = kv_get_json_checked(_KV_KEY)  # raises KvReadError on a failed read: that is not "no settings"
    if raw is not None:
        return raw
    raw = _read_json_file()
    if raw is None:
        return None
    try:
        kv_set_json(_KV_KEY, raw)
    except Exception as exc:  # noqa: BLE001 - migration is best-effort; retried next load
        _LOG.debug("safety_settings migration into app_state deferred (%s)", type(exc).__name__)
    return raw


def _clean_proxy_list(raw) -> list[str]:
    """Best-effort normalise a persisted/env proxy-pool value into a list of
    non-empty, stripped strings -- never crashes, never invents an entry."""
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        return []
    return [p.strip() for p in raw if isinstance(p, str) and p.strip()]


def _read_raw_strict() -> dict | None:
    """``_read_raw`` for a caller that will REWRITE what it read: a stored blob that cannot be read raises ``SafetySettingsError``
    (the class only, never the engine's text) instead of reading as the defaults, because writing the defaults back over a saved
    protected mode and proxy list is the loss this prevents."""
    from src.config.kv_store import is_damaged, kv_get_json_strict, kv_set_json

    def refused(exc: BaseException) -> SafetySettingsError:
        damaged = is_damaged(exc)
        return (_DamagedSettings if damaged else SafetySettingsError)(
            f"the stored safety settings could not be read ({type(exc).__name__}); nothing was changed"
            + (" - choose the connection again in the safety settings to replace them" if damaged else "")
        )

    if not _use_kv():
        try:
            return _read_json_file()
        except Exception as exc:  # noqa: BLE001 - refused, by class
            raise refused(exc) from None
    try:
        raw = kv_get_json_strict(_KV_KEY)
    except Exception as exc:  # noqa: BLE001 - refused, by class
        raise refused(exc) from None
    if raw is not None:
        return raw
    try:
        raw = _read_json_file()
    except Exception as exc:  # noqa: BLE001 - refused, by class
        raise refused(exc) from None
    if raw is None:
        return None
    try:
        kv_set_json(_KV_KEY, raw)
    except Exception as exc:  # noqa: BLE001 - migration is best-effort; retried next load
        _LOG.debug("safety_settings migration into app_state deferred (%s)", type(exc).__name__)
    return raw


def load_settings() -> SafetySettings:
    """Load safety settings; env vars override the persisted value (for headless use).

    A stored choice that cannot be READ never reads as the defaults (which are the direct connection): the settings come back
    protected with no proxy and ``read_failed`` set, which every transport builder refuses. Absent is still the defaults."""
    from src.config.kv_store import KvReadError

    try:
        raw = _read_raw()
    except KvReadError:
        # The environment decides when it names a mode (the headless path never reads the store for it); otherwise the choice is
        # UNKNOWN, not absent: protected, and with nothing to route through unless the environment names a proxy.
        s = _settings_from(None)
        if os.getenv("OO_FETCH_MODE") not in VALID_MODES:
            s.fetch_mode = "protected"
            s.read_failed = not (s.http_proxy or s.http_proxies)
        return s
    return _settings_from(raw)


def _settings_from(raw: dict | None) -> SafetySettings:
    """The settings a stored blob (or none) and the environment make."""
    s = SafetySettings()
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

    reset: list[str]
    try:
        stored = _read_raw_strict()
    except _DamagedSettings:
        if updates.get("fetch_mode") is None or updates.get("http_proxy") is None:
            raise  # a partial update would write the defaults over what the damaged value may still say
        stored = None  # the whole choice is supplied: it replaces the damaged value
        reset = [f for f in ("http_proxies", "discovery_external_enabled") if updates.get(f) is None]
    else:
        reset = []
    current = _settings_from(stored)
    current.reset_fields = reset  # type: ignore[attr-defined]
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
