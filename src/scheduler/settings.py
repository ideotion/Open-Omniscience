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
from dataclasses import asdict, dataclass, field

_LOG = logging.getLogger(__name__)

SETTINGS_VERSION = "oo-scheduler-settings-1"
VALID_MODES = ("rss", "crawl", "markets", "wiki", "law")
VALID_RATE_MODES = ("target", "maximum")
# Bounds for the download-rate target (KiB/s): a generous, honest range.
_MIN_TARGET_KBPS, _MAX_TARGET_KBPS = 50, 50_000
# Hard ceiling on concurrent fetches (the governor's upper bound).
_MAX_PARALLELISM = 50
_MIN_INTERVAL, _MAX_INTERVAL = 1, 7 * 24 * 60  # minutes: 1 min .. 1 week


class SchedulerSettingsError(ValueError):
    """Raised when a scheduler settings update carries an invalid value."""


@dataclass
class SchedulerSettings:
    """Operator-controlled scheduling preferences."""

    autostart: bool = False
    interval_minutes: int = 60
    # Continuous collection (maintainer 2026-06-13: "scraping should never
    # stop"). When True (the default), the scheduler runs passes back-to-back
    # with only a short inter-pass gap instead of idling ``interval_minutes``
    # between them — so when the operator is online, collection is permanent.
    # Set False to restore the old run-once-then-wait-``interval_minutes`` cadence.
    continuous: bool = True
    # Collection speed is expressed as a DOWNLOAD-RATE target, not a raw worker
    # count (maintainer ruling 2026-06-16). The bandwidth governor varies how many
    # sources are fetched at once to APPROACH the target — always across DIFFERENT
    # hosts, each on its own Tor circuit, while the single SQLite writer keeps
    # writes serialised. Per-host politeness is never traded for speed: one host is
    # fetched by at most one worker at a time.
    #   collect_rate_mode  : "target" (track collect_target_kbps) | "maximum"
    #   collect_target_kbps: best-effort download-rate goal in KiB/s (target mode)
    #   collect_parallelism: the hard CEILING on concurrent fetches (the governor's
    #                        upper bound). 1 = the sequential loop (governor off).
    # The default is "maximum" (maintainer ruling 2026-07-23: the old 500 KiB/s
    # target deliberately parked workers and left real connections under-used —
    # field-observed as "a few kB/s average"); the governor still backs off
    # automatically under CPU/memory/writer contention (logged in
    # src/monitoring/collect_perf.py) and per-host politeness is untouched, so
    # "maximum" ramps to the ceiling only where the machine and the hosts allow.
    # "target" mode + collect_target_kbps stay available for constrained lines.
    collect_rate_mode: str = "maximum"
    collect_target_kbps: int = 500
    collect_parallelism: int = 50
    mode: str = "rss"  # "rss" (feeds) or "crawl" (bounded recursion)
    # 0 = UNBOUNDED (cover every source / watched item) -- the default. Any cap
    # silently SELECTS which sources to skip, which cannot be justified
    # (maintainer 2026-06-13). A positive value is honoured as a soft cap.
    max_sources_per_run: int = 0
    crawl_max_depth: int = 2
    crawl_max_pages: int = 50

    # Source selection for rss/crawl runs (empty list = no filter on that facet).
    # Sources are always also filtered to enabled=True. Tags match ANY (substring).
    select_languages: list[str] = field(default_factory=list)
    select_tags: list[str] = field(default_factory=list)
    select_source_types: list[str] = field(default_factory=list)

    # Opt-in drop-folder export (WP3/RM-06): after each run, the new-articles
    # delta is written into this LOCAL folder (envelope JSON). Empty = off
    # (the default) -- no file is ever written unless the operator sets it.
    export_dir: str = ""

    # Offline source-discovery budget per run (WP5/RM-19): how many candidates
    # the citation/catalog channels may stage per scheduler run. 0 disables
    # discovery entirely. Network channels do not exist here by design.
    discovery_per_run: int = 10

    # WORLD source-discovery ride-along (maintainer ruled 2026-07-15: source
    # discovery should be "background and automated"): how many COUNTRIES the
    # persisted world-discovery cursor advances per online collection pass,
    # through the same guarded transport as the pass itself. Every find stays a
    # DISABLED source for review (automation covers discovery, never enabling).
    # 0 disables the ride-along; the manual Diagnostics job remains either way.
    world_discovery_per_pass: int = 2

    # QUALIFICATION ride-along (0.3 CLOSE GATE ruling: "qualification runs as a
    # background job... like the world-discovery ride-along"): how many candidate
    # sources (never-yet-qualified, then due re-qualifications) the admission gate
    # trial-fetches + judges per online collection pass. 0 disables the ride-along
    # (candidates then simply stay unqualified/disqualified -- never auto-admitted).
    qualification_per_pass: int = 5

    # Optional per-language cadence lever (default OFF). ``language_equilibrium``
    # is a {lang: weight} TARGET the operator opts into; when set, over-
    # represented languages are re-checked LESS often (never excluded — a hard
    # freshness floor guarantees re-check). Empty {} = OFF = the pure random
    # per-tag rotation, byte-identical. ``equilibrium_floor`` is the minimum pace
    # multiplier (never fully stop a language).
    language_equilibrium: dict = field(default_factory=dict)
    equilibrium_floor: float = 0.2
    # Opt-in per-country PRIORITY LADDER (default OFF): a {iso2: weight>0} map the operator
    # sets so chosen countries scrape FIRST under constrained bandwidth. It only ORDERS,
    # never excludes (ordering != exclusion — the continuous round-robin still covers every
    # source). Empty {} = OFF = the pure stratified order, byte-identical.
    country_priority: dict = field(default_factory=dict)

    # Opt-out for the background hazard-snapshot + weather-signal refresh pass (Wave 4 J).
    # When True (default) each collect pass keeps the local hazard snapshot (the severity
    # alert tier's data) fresh via the consented USGS/GDACS fetch AND re-derives the weather
    # SIGNAL keywords from the corpus (network-free) — both freshness-gated so they are
    # usually no-ops. Set False to leave those stores to the explicit manual endpoints only.
    auto_track_signals: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


# The ``app_state`` kv key this preference blob lives under (DB-reliability D1).
_KV_KEY = "settings.scheduler"


def _settings_path():
    from src.paths import data_dir

    return data_dir() / "scheduler_settings.json"


def _use_kv() -> bool:
    """Use the encrypted ``app_state`` store at the DEFAULT location; honour a redirected
    ``_settings_path`` (test isolation) as JSON instead. See app_settings._use_kv."""
    from src.paths import data_dir

    return _settings_path() == data_dir() / "scheduler_settings.json"


def _read_json_file() -> dict | None:
    path = _settings_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a bad file must not break startup
        _LOG.warning("scheduler_settings.json unreadable; using defaults", exc_info=True)
        return None


def _read_raw() -> dict | None:
    """Scheduler prefs source of truth: the encrypted ``app_state`` row (D1), falling
    back to (and one-time migrating) the legacy ``scheduler_settings.json`` file."""
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
        _LOG.debug("scheduler_settings migration into app_state deferred", exc_info=True)
    return raw


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


def _coerce_float(value, fallback: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return fallback


def _coerce_target(value) -> dict:
    """A {lang: weight} language-equilibrium target → cleaned {lang: float>0}.

    Only positive weights on non-empty lowercased language keys survive; anything
    malformed is dropped. An empty result means the lever is OFF.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in value.items():
        try:
            w = float(v)
        except (TypeError, ValueError):
            continue
        key = str(k).strip().lower()
        if key and w > 0:
            out[key] = w
    return out


def _coerce_list(value) -> list[str]:
    """Normalise a selection facet to a deduped list of lowercase, non-empty tokens."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    out, seen = [], set()
    for item in value:
        token = str(item).strip().lower()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def load_settings() -> SchedulerSettings:
    """Load scheduler settings, falling back to safe defaults."""
    d = SchedulerSettings()
    raw = _read_raw()
    if raw is None:
        return d
    mode = raw.get("mode", d.mode)
    if mode not in VALID_MODES:
        _LOG.warning("ignoring invalid stored scheduler mode %r", mode)
        mode = d.mode
    rate_mode = raw.get("collect_rate_mode", d.collect_rate_mode)
    if rate_mode not in VALID_RATE_MODES:
        rate_mode = d.collect_rate_mode
    return SchedulerSettings(
        autostart=_coerce_bool(raw.get("autostart"), d.autostart),
        interval_minutes=_coerce_int(
            raw.get("interval_minutes"), d.interval_minutes, _MIN_INTERVAL, _MAX_INTERVAL
        ),
        continuous=_coerce_bool(raw.get("continuous"), d.continuous),
        collect_rate_mode=rate_mode,
        collect_target_kbps=_coerce_int(
            raw.get("collect_target_kbps"), d.collect_target_kbps, _MIN_TARGET_KBPS, _MAX_TARGET_KBPS
        ),
        collect_parallelism=_coerce_int(
            raw.get("collect_parallelism"), d.collect_parallelism, 1, _MAX_PARALLELISM
        ),
        mode=mode,
        # lo=0 allows the unbounded default; hi is a generous safety ceiling for
        # an explicit soft cap, never a selection imposed by us.
        max_sources_per_run=_coerce_int(
            raw.get("max_sources_per_run"), d.max_sources_per_run, 0, 1_000_000
        ),
        crawl_max_depth=_coerce_int(raw.get("crawl_max_depth"), d.crawl_max_depth, 0, 6),
        crawl_max_pages=_coerce_int(raw.get("crawl_max_pages"), d.crawl_max_pages, 1, 500),
        select_languages=_coerce_list(raw.get("select_languages")),
        select_tags=_coerce_list(raw.get("select_tags")),
        select_source_types=_coerce_list(raw.get("select_source_types")),
        export_dir=str(raw.get("export_dir") or "").strip(),
        discovery_per_run=_coerce_int(raw.get("discovery_per_run"), d.discovery_per_run, 0, 100),
        world_discovery_per_pass=_coerce_int(
            raw.get("world_discovery_per_pass"), d.world_discovery_per_pass, 0, 12
        ),
        qualification_per_pass=_coerce_int(
            raw.get("qualification_per_pass"), d.qualification_per_pass, 0, 100
        ),
        language_equilibrium=_coerce_target(raw.get("language_equilibrium")),
        equilibrium_floor=_coerce_float(raw.get("equilibrium_floor"), d.equilibrium_floor, 0.0, 1.0),
        # Reuses _coerce_target: a {iso2: weight} map cleaned to {lowercased-key: float>0},
        # exactly the shape the priority ladder needs (empty = OFF).
        country_priority=_coerce_target(raw.get("country_priority")),
        auto_track_signals=_coerce_bool(raw.get("auto_track_signals"), d.auto_track_signals),
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
    if "continuous" in updates and updates["continuous"] is not None:
        current.continuous = _coerce_bool(updates["continuous"], current.continuous)
    if "auto_track_signals" in updates and updates["auto_track_signals"] is not None:
        current.auto_track_signals = _coerce_bool(
            updates["auto_track_signals"], current.auto_track_signals
        )
    if "collect_rate_mode" in updates and updates["collect_rate_mode"] is not None:
        rm = str(updates["collect_rate_mode"])
        if rm not in VALID_RATE_MODES:
            raise SchedulerSettingsError(
                f"collect_rate_mode must be one of: {', '.join(VALID_RATE_MODES)}"
            )
        current.collect_rate_mode = rm

    def _ranged(key: str, lo: int, hi: int, label: str) -> None:
        if key in updates and updates[key] is not None:
            try:
                v = int(updates[key])
            except (TypeError, ValueError) as exc:
                raise SchedulerSettingsError(f"{label} must be an integer") from exc
            if not (lo <= v <= hi):
                raise SchedulerSettingsError(f"{label} must be between {lo} and {hi}")
            setattr(current, key, v)

    if "export_dir" in updates and updates["export_dir"] is not None:
        current.export_dir = str(updates["export_dir"]).strip()

    _ranged("discovery_per_run", 0, 100, "discovery_per_run")
    _ranged("world_discovery_per_pass", 0, 12, "world_discovery_per_pass")
    _ranged("qualification_per_pass", 0, 100, "qualification_per_pass")
    _ranged("collect_parallelism", 1, _MAX_PARALLELISM, "collect_parallelism")
    _ranged("collect_target_kbps", _MIN_TARGET_KBPS, _MAX_TARGET_KBPS, "collect_target_kbps")
    _ranged("interval_minutes", _MIN_INTERVAL, _MAX_INTERVAL, "interval_minutes")
    # Audit finding 2026-07-17: this was `1, 1000` -- but max_sources_per_run is
    # documented + tested (tests/test_no_source_cap.py) as "0 = UNBOUNDED (cover
    # every source) -- the default. Any cap silently SELECTS which sources to
    # skip, which cannot be justified (maintainer 2026-06-13)", and load_settings
    # (above) already coerces it with bounds (0, 1_000_000). The stale 1..1000
    # range here meant a client could never explicitly PUT {"max_sources_per_
    # run": 0} to reset the cap to unbounded, and could never set a cap above
    # 1000 either -- a real regression relative to the maintainer's own ruling.
    _ranged("max_sources_per_run", 0, 1_000_000, "max_sources_per_run")
    _ranged("crawl_max_depth", 0, 6, "crawl_max_depth")
    _ranged("crawl_max_pages", 1, 500, "crawl_max_pages")

    for key in ("select_languages", "select_tags", "select_source_types"):
        if key in updates:
            setattr(current, key, _coerce_list(updates[key]))

    if "language_equilibrium" in updates:
        # A dict target (or None/empty to turn the lever OFF). Malformed entries
        # are dropped by _coerce_target; an all-invalid target becomes {} = OFF.
        val = updates["language_equilibrium"]
        if val is not None and not isinstance(val, dict):
            raise SchedulerSettingsError(
                "language_equilibrium must be an object of {language: weight}"
            )
        current.language_equilibrium = _coerce_target(val)
    if "equilibrium_floor" in updates and updates["equilibrium_floor"] is not None:
        try:
            f = float(updates["equilibrium_floor"])
        except (TypeError, ValueError) as exc:
            raise SchedulerSettingsError("equilibrium_floor must be a number") from exc
        if not (0.0 <= f <= 1.0):
            raise SchedulerSettingsError("equilibrium_floor must be between 0 and 1")
        current.equilibrium_floor = f

    if "country_priority" in updates:
        # A {iso2: weight} map (or None/empty to turn the ladder OFF). Malformed entries
        # are dropped by _coerce_target; an all-invalid map becomes {} = OFF.
        val = updates["country_priority"]
        if val is not None and not isinstance(val, dict):
            raise SchedulerSettingsError(
                "country_priority must be an object of {country: weight}"
            )
        current.country_priority = _coerce_target(val)

    payload = {"version": SETTINGS_VERSION, **current.to_dict()}
    if not _use_kv():
        path = _settings_path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
        tmp.replace(path)
        return current
    from src.config.kv_store import kv_set_json

    kv_set_json(_KV_KEY, payload)
    return current
