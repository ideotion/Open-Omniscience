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
# Ollama keep_alive grammar: a Go duration ("30m", "1h", "300ms", "10s"), a plain
# number of seconds, "0" (unload immediately) or "-1" (keep loaded indefinitely).
_KEEP_ALIVE_RE = re.compile(r"^(-1|\d+(\.\d+)?(ms|s|m|h)?)$")
_DEFAULT_KEEP_ALIVE = "30m"
_MAX_PROMPT_CHARS = 4000


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
    # How long Ollama keeps a model loaded after a request (maintainer 2026-06-17:
    # "the unloading isn't necessary"). "30m" keeps it warm across a work session;
    # "-1" never unloads; "0" unloads immediately. Passed verbatim to /api/generate.
    llm_keep_alive: str = _DEFAULT_KEEP_ALIVE
    # Operator-editable SYSTEM PROMPTS (maintainer 2026-06-17). Empty = use the
    # built-in default (defined in src.api.llm). The effective text used is recorded
    # per result (article_analyses.prompt_text) so provenance stays exact. The
    # translate prompt may contain a {target} placeholder for the target language.
    llm_prompt_summary: str = ""
    llm_prompt_translate: str = ""
    llm_prompt_synthesis: str = ""
    # The built-in AI-keyword EXTRACTION prompt (Part B) — tunable like the three above;
    # the default (_EXTRACT_SYSTEM) lives in src.ai_layer.extract. "" = use the built-in.
    llm_prompt_ai_keywords: str = ""
    # AUTO-START language detection (2026-07-24 field-feedback Session A §1, ruled
    # default-ON): a scheduler ride-along (re)starts the opt-in AI language-detection
    # job whenever the local model is available and unknown-language candidates exist.
    # Set False in Settings -> AI to opt out; the manual "Detect languages" button
    # still works either way.
    ai_langdetect_auto: bool = True

    def __post_init__(self) -> None:
        if self.recipes_disabled is None:
            self.recipes_disabled = []

    def to_dict(self) -> dict:
        return asdict(self)


# The ``app_state`` kv key this preference blob lives under (DB-reliability D1).
_KV_KEY = "settings.app"


def _settings_path():
    from src.paths import data_dir

    return data_dir() / "app_settings.json"


def _use_kv() -> bool:
    """Use the encrypted ``app_state`` store at the DEFAULT data-dir location; if the
    settings path has been redirected (a test that monkeypatches ``_settings_path`` to
    isolate to its own file), honour that file as JSON instead — so both production
    durability and the existing per-file test isolation keep working."""
    from src.paths import data_dir

    return _settings_path() == data_dir() / "app_settings.json"


def _read_json_file() -> dict | None:
    path = _settings_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a bad file must not take down the API
        _LOG.warning("app_settings.json is unreadable; using defaults", exc_info=True)
        return None


def _read_raw() -> dict | None:
    """Preferences source of truth: the encrypted ``app_state`` row (D1), falling back
    to (and one-time migrating) the legacy ``app_settings.json`` file.

    Returns the stored dict (with its ``version`` tag) or ``None`` when nothing is
    stored yet. Any failure degrades to the file / ``None`` — a settings read must
    never take down the API.
    """
    if not _use_kv():
        return _read_json_file()
    from src.config.kv_store import kv_get_json, kv_set_json

    raw = kv_get_json(_KV_KEY)
    if raw is not None:
        return raw
    # No DB row yet: migrate the legacy JSON file if present (best-effort, one-time).
    raw = _read_json_file()
    if raw is None:
        return None
    try:
        kv_set_json(_KV_KEY, raw)  # adopt into the durable store
    except Exception:  # noqa: BLE001 - migration is best-effort; retried next load
        _LOG.debug("app_settings migration into app_state deferred", exc_info=True)
    return raw


def _write_raw(payload: dict) -> None:
    if not _use_kv():
        path = _settings_path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
        tmp.replace(path)  # atomic on the same filesystem
        return
    from src.config.kv_store import kv_set_json

    kv_set_json(_KV_KEY, payload)  # transactional, encrypted, backed up (D1)


def load_settings() -> AppSettings:
    """Load preferences, falling back to defaults on a missing/corrupt store."""
    raw = _read_raw()
    if raw is None:
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
    keep_alive = str(raw.get("llm_keep_alive", defaults.llm_keep_alive))
    if not _KEEP_ALIVE_RE.match(keep_alive):
        _LOG.warning("ignoring invalid stored llm_keep_alive %r", keep_alive)
        keep_alive = defaults.llm_keep_alive

    def _prompt(key: str) -> str:
        v = raw.get(key, "")
        return str(v)[:_MAX_PROMPT_CHARS] if isinstance(v, str) else ""

    ai_langdetect_auto = raw.get("ai_langdetect_auto", defaults.ai_langdetect_auto)
    if not isinstance(ai_langdetect_auto, bool):
        ai_langdetect_auto = defaults.ai_langdetect_auto

    return AppSettings(
        theme=theme,
        default_result_limit=limit,
        recipes_disabled=recipes_disabled,
        llm_model=str(llm_model) if llm_model else None,
        llm_keep_alive=keep_alive,
        llm_prompt_summary=_prompt("llm_prompt_summary"),
        llm_prompt_translate=_prompt("llm_prompt_translate"),
        llm_prompt_synthesis=_prompt("llm_prompt_synthesis"),
        llm_prompt_ai_keywords=_prompt("llm_prompt_ai_keywords"),
        ai_langdetect_auto=ai_langdetect_auto,
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
    if "llm_keep_alive" in updates and updates["llm_keep_alive"] is not None:
        ka = str(updates["llm_keep_alive"]).strip()
        if not _KEEP_ALIVE_RE.match(ka):
            raise AppSettingsError(
                "llm_keep_alive must be a duration like '30m', '1h', '300ms', a number of "
                "seconds, '0' (unload now) or '-1' (never unload)"
            )
        current.llm_keep_alive = ka
    for _field in ("llm_prompt_summary", "llm_prompt_translate", "llm_prompt_synthesis",
                   "llm_prompt_ai_keywords"):
        if _field in updates and updates[_field] is not None:
            val = updates[_field]
            if not isinstance(val, str):
                raise AppSettingsError(f"{_field} must be a string")
            if len(val) > _MAX_PROMPT_CHARS:
                raise AppSettingsError(f"{_field} is too long (max {_MAX_PROMPT_CHARS} characters)")
            setattr(current, _field, val.strip())
    if "ai_langdetect_auto" in updates and updates["ai_langdetect_auto"] is not None:
        val = updates["ai_langdetect_auto"]
        if not isinstance(val, bool):
            raise AppSettingsError("ai_langdetect_auto must be a boolean")
        current.ai_langdetect_auto = val

    _write_raw({"version": SETTINGS_VERSION, **current.to_dict()})
    return current
