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
#: A bare language code as the perception gate keys it (``fr``, ``pt``, ``zh``).
_LANG_CODE_RE = re.compile(r"^[a-z]{2,3}$")
# Ollama keep_alive grammar: a Go duration ("30m", "1h", "300ms", "10s"), a plain
# number of seconds, "0" (unload immediately) or "-1" (keep loaded indefinitely).
_KEEP_ALIVE_RE = re.compile(r"^(-1|\d+(\.\d+)?(ms|s|m|h)?)$")
_DEFAULT_KEEP_ALIVE = "30m"
_MAX_PROMPT_CHARS = 4000
# Mirrors src.backup.import_queue.CHECKPOINT_K_MAX. Duplicated as a literal ON
# PURPOSE rather than imported: this module is read on the settings path and by the
# boot sequence, and importing the backup engine from it would pull the whole merge
# stack in for one integer. A test pins the two against each other, so the copy
# cannot drift.
_CHECKPOINT_K_MAX = 24
# Mirrors src.database.fts.NEAR_MIN / NEAR_MAX, as a literal for the reason the
# checkpoint bound above gives (this module is on the boot path); a test pins the two.
_NEAR_MIN, _NEAR_MAX = 0, 1000


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
    # Settings restructure PR-7 (2026-07-31): the SAME mechanism widened from the 4
    # recipe producers to every Lead producer, rather than a second list beside it.
    # The loader seeds this from recipes_disabled, so an existing settings file keeps
    # working and recipes_disabled stays readable for one cycle.
    cards_disabled: list = None  # type: ignore[assignment]
    # PERCEPTION LANGUAGES SWITCHED OFF BY THE OPERATOR (Q1144 = a, S05-08 S6). The
    # measured gate decides where extraction MAY run; this list only takes a cleared
    # language back out. It can never turn a failed or unmeasured one on -- there is
    # no "on" list to put it in, which is the negation the brief asks for.
    perception_languages_off: list = None  # type: ignore[assignment]
    # Per-producer tunables: {producer_name: {tunable_key: value}}. Only keys the
    # catalog declares survive, always clamped to the declared safe range -- see
    # src/briefing/catalog.py, which owns the ranges and the reasons for them.
    card_settings: dict = None  # type: ignore[assignment]
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
    # DUAL BACKEND (B1, 2026-07-24 field-feedback Session B, RULED A12): which
    # backend to use. "auto" (default) = src.llm.backend.resolve_backend()'s own
    # GPU+installed+running detection; "ollama"/"vllm" is an explicit operator
    # override that always wins (disclosed in the Settings -> AI tab).
    llm_backend: str = "auto"
    # The active model tag for vLLM (a Hugging Face repo id, e.g.
    # "org/Model-Name-AWQ" — a DIFFERENT grammar than an Ollama tag in spirit,
    # though the same permissive charset covers both). None = whatever model the
    # running vLLM server was last started with (vLLM serves exactly ONE model at
    # a time, unlike Ollama's multi-model catalog).
    llm_model_vllm: str | None = None
    # AUTO-START language detection (2026-07-24 field-feedback Session A §1, ruled
    # default-ON): a scheduler ride-along (re)starts the opt-in AI language-detection
    # job whenever the local model is available and unknown-language candidates exist.
    # Set False in Settings -> AI to opt out; the manual "Detect languages" button
    # still works either way.
    ai_langdetect_auto: bool = True
    # HARDWARE SUITABILITY OVERRIDE (2026-07-30, maintainer-ruled). Local inference
    # is impractical without a dedicated GPU (or Apple Silicon unified memory), so
    # AI features DEFAULT TO OFF there -- see src.llm.backend.inference_capability().
    # This is never a hard block: setting this True runs them anyway, and the
    # verdict then reports overridden=True so the disclosure still shows. Env
    # equivalent: OO_LLM_ALLOW_IMPRACTICAL_HW=1.
    llm_allow_impractical_hw: bool = False
    # BACKGROUND-AI COORDINATOR (2026-08-01 ruling 12a). ONE master switch runs the
    # enabled sweeps round-robin through the single backend instead of each having
    # its own toggle that would silently queue behind the others (Ollama serves one
    # generation at a time). The per-sweep flags below stay, so the master is a
    # convenience, never a hider: the operator can always see and set which sweeps
    # are included. The master's DEFAULT is hardware-aware -- see
    # coordinator.coordinator_default_enabled() -- and, like every other AI gate
    # here, is a default rather than a block.
    ai_background_enabled: bool = False
    ai_sweep_keyword_triage: bool = True
    ai_sweep_source_tags: bool = True
    ai_sweep_perception_extract: bool = True
    # THE TRANSLATION SWEEPS (S05-08). Keyword translation is a member like the three
    # above, on by default under the master (Q405: "shown by default once persisted ...
    # when the AI coordinator is on"). The article-title sweep is OPT-IN (Q513 = b says
    # so in as many words), so it starts False and the master never turns it on.
    ai_sweep_keyword_translation: bool = True
    ai_sweep_article_titles: bool = False
    # THE BULLETIN'S OPENING (register ruling D2, placed beside row H by RC08.2 = a):
    # an edition opens on the DETERMINISTIC introduction, and the model-written one is
    # opt-in. This is the opt-in; the narration job reads it when a caller does not
    # say, so the default path never asks a model to write the first paragraph.
    bulletin_narrate_introduction: bool = False
    # THE IMPORT CHECKPOINT INTERVAL K (2026-09-07; the 2026-08-08 queue entry's
    # item (b)). How many corpus backups of a multi-backup import share ONE
    # verify + working-copy snapshot + atomic swap. 1 = today's behaviour, every
    # backup written to the corpus as soon as it finishes. Above 1 the working
    # copy is carried across K backups and the whole-file checks and the swap are
    # paid once -- which is faster and strictly less durable, because nothing is
    # durable until a swap and a Stop, a failure or a crash discards the group.
    # Range 1..CHECKPOINT_K_MAX. RULED 2026-09-15 (Q216 = a): the default is 3.
    # The reasoning and the resolution order live in
    # src.backup.import_queue.import_checkpoint_k, which is the ONE place that
    # decides -- this is the stored value it prefers, and its default is kept
    # equal to CHECKPOINT_K_DEFAULT there by a test rather than by memory.
    import_checkpoint_k: int = 3
    # TRUST THE BACKUP'S SCRAPING HISTORY (the Q701 NOTE, 2026-09-15; gate row K).
    # The note asks that "web fetch/web scrapping history should be backed-up, and at
    # install and import, users should be given the choice to trust or not the
    # history". This is that choice's persisted default -- offered at first launch and
    # overridable per import. TRUE means a restore ADOPTS the incoming corpus's fetch
    # state (per-feed ETag / Last-Modified / backoff), so the next collection pass asks
    # each feed conditionally instead of re-downloading it; FALSE discards it, so every
    # feed is re-fetched from scratch.
    #
    # THE DEFAULT IS A LABELLED ASSUMPTION, not a ruling. The note gives the CHOICE and
    # says nothing about the default, and brief S04-04 SS6 forbids this slice deciding
    # it. TRUE is shipped because it is the behaviour the note's own motivation asks
    # for ("so that a fresh install with an old backup doesn't re-download the same
    # pages"), and because what it risks is bounded: a stale ETag costs at most one
    # unchanged pass per feed, and `skip_until` is capped at BACKOFF_CAP_S (~6 h), so
    # an adopted backoff always expires. Flipping it is this one literal; both settings
    # are pinned by tests, so the flip cannot silently change what the app claims.
    trust_backup_fetch_history: bool = True
    # ADOPT THE SHIPPED QUALIFICATION VERDICTS AT STARTUP (Q1106 = a, the overlay
    # editor's third operation). TRUE is the behaviour that shipped: every boot adopts
    # `configs/source_qualification.yml` onto rows this instance has never judged.
    #
    # IT EXISTS BECAUSE "REVERT" HAS TO HOLD. Reverting puts the adopted rows back to
    # `unqualified` -- which is exactly the state adoption looks for, so the next boot
    # would re-adopt them and the operator's decision would survive until they closed
    # the app. A revert the app quietly undoes is not a revert, so reverting also turns
    # this off and says so; Adopt turns it back on. The overlay FILE is untouched either
    # way: this is about what this install does with it, not about what ships.
    adopt_shipped_verdicts: bool = True
    # LOCAL SEARCH HISTORY (Q614 = a): OFF unless the reader turns it on -- offered once
    # after the legal screen at first launch (the Q614 note) and in the advanced search.
    search_history_enabled: bool = False
    # THE NEAR DEFAULT (Q612 = a + note): the distance a NEAR without one takes. Ruled
    # 10; "the user should be able to change the default number", so it is a stored
    # preference, edited beside the builder's own NEAR stepper.
    search_near_default: int = 10

    def __post_init__(self) -> None:
        if self.recipes_disabled is None:
            self.recipes_disabled = []
        if self.cards_disabled is None:
            # Seed from the legacy key so an operator who switched a recipe off
            # before this field existed keeps that choice.
            self.cards_disabled = list(self.recipes_disabled)
        if self.card_settings is None:
            self.card_settings = {}
        if self.perception_languages_off is None:
            self.perception_languages_off = []

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
    raw_cards = raw.get("cards_disabled")
    cards_disabled = (
        [str(x) for x in raw_cards] if isinstance(raw_cards, list) else list(recipes_disabled)
    )
    raw_pe_off = raw.get("perception_languages_off")
    perception_languages_off = (
        sorted({str(x) for x in raw_pe_off if _LANG_CODE_RE.match(str(x))})
        if isinstance(raw_pe_off, list)
        else []
    )
    raw_card_settings = raw.get("card_settings")
    card_settings = raw_card_settings if isinstance(raw_card_settings, dict) else {}
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

    llm_allow_impractical_hw = raw.get(
        "llm_allow_impractical_hw", defaults.llm_allow_impractical_hw
    )
    if not isinstance(llm_allow_impractical_hw, bool):
        llm_allow_impractical_hw = defaults.llm_allow_impractical_hw

    # The coordinator's master switch + its per-sweep membership flags, and the
    # restore trust toggle. Same read-then-type-check shape as every sibling boolean:
    # a stored non-boolean is ignored in favour of the documented default rather than
    # coerced into a meaning it never had.
    _bool_flags = {}
    for _name in (
        "ai_background_enabled",
        "ai_sweep_keyword_triage",
        "ai_sweep_source_tags",
        "ai_sweep_perception_extract",
        "ai_sweep_keyword_translation",
        "ai_sweep_article_titles",
        "bulletin_narrate_introduction",
        "trust_backup_fetch_history",
        "adopt_shipped_verdicts",
        "search_history_enabled",
    ):
        _val = raw.get(_name, getattr(defaults, _name))
        if not isinstance(_val, bool):
            _val = getattr(defaults, _name)
        _bool_flags[_name] = _val

    llm_backend = raw.get("llm_backend", defaults.llm_backend)
    if llm_backend not in ("auto", "ollama", "vllm"):
        _LOG.warning("ignoring invalid stored llm_backend %r", llm_backend)
        llm_backend = defaults.llm_backend

    llm_model_vllm = raw.get("llm_model_vllm")
    if llm_model_vllm is not None and not _MODEL_RE.match(str(llm_model_vllm)):
        _LOG.warning("ignoring invalid stored llm_model_vllm %r", llm_model_vllm)
        llm_model_vllm = None

    # The import checkpoint interval. Out of range or unreadable falls back to the
    # DEFAULT (1 = commit every backup), never to the stored number: the safe
    # direction for a durability knob is fewer items per checkpoint, and a value
    # nobody meant must not be able to widen the window in which a crash costs work.
    checkpoint_k = raw.get("import_checkpoint_k", defaults.import_checkpoint_k)
    try:
        checkpoint_k = int(checkpoint_k)
    except (TypeError, ValueError):
        checkpoint_k = defaults.import_checkpoint_k
    if not (1 <= checkpoint_k <= _CHECKPOINT_K_MAX):
        _LOG.warning("ignoring out-of-range stored import_checkpoint_k %r", checkpoint_k)
        checkpoint_k = defaults.import_checkpoint_k

    # The NEAR default: out of range or unreadable falls back to the ruled 10 (Q612).
    near_default = raw.get("search_near_default", defaults.search_near_default)
    try:
        near_default = int(near_default)
    except (TypeError, ValueError):
        near_default = defaults.search_near_default
    if not (_NEAR_MIN <= near_default <= _NEAR_MAX):
        near_default = defaults.search_near_default

    return AppSettings(
        search_near_default=near_default,
        import_checkpoint_k=checkpoint_k,
        theme=theme,
        default_result_limit=limit,
        recipes_disabled=recipes_disabled,
        cards_disabled=cards_disabled,
        perception_languages_off=perception_languages_off,
        card_settings=card_settings,
        llm_model=str(llm_model) if llm_model else None,
        llm_keep_alive=keep_alive,
        llm_prompt_summary=_prompt("llm_prompt_summary"),
        llm_prompt_translate=_prompt("llm_prompt_translate"),
        llm_prompt_synthesis=_prompt("llm_prompt_synthesis"),
        llm_prompt_ai_keywords=_prompt("llm_prompt_ai_keywords"),
        ai_langdetect_auto=ai_langdetect_auto,
        llm_backend=llm_backend,
        llm_model_vllm=str(llm_model_vllm) if llm_model_vllm else None,
        llm_allow_impractical_hw=llm_allow_impractical_hw,
        **_bool_flags,
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
    if "cards_disabled" in updates and updates["cards_disabled"] is not None:
        names = updates["cards_disabled"]
        if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
            raise AppSettingsError("cards_disabled must be a list of producer names")
        current.cards_disabled = sorted(set(names))
    if (
        "perception_languages_off" in updates
        and updates["perception_languages_off"] is not None
    ):
        codes = updates["perception_languages_off"]
        if not isinstance(codes, list) or not all(
            isinstance(x, str) and _LANG_CODE_RE.match(x) for x in codes
        ):
            raise AppSettingsError(
                "perception_languages_off must be a list of language codes"
            )
        current.perception_languages_off = sorted(set(codes))
    if "card_settings" in updates and updates["card_settings"] is not None:
        raw = updates["card_settings"]
        if not isinstance(raw, dict):
            raise AppSettingsError("card_settings must be a mapping of producer -> settings")
        # CLAMPED HERE, at the one write point, so no path can persist a value
        # outside a producer's safe range. The notes are attached to the settings
        # object for the caller to surface -- a clamp the operator is not told
        # about is exactly what ruling 3 forbids.
        from src.briefing.catalog import clamp_settings

        cleaned: dict = {}
        notes: list[dict] = []
        for producer, values in raw.items():
            kept, why = clamp_settings(str(producer), values)
            notes.extend(why)
            if kept:
                cleaned[str(producer)] = kept
        current.card_settings = cleaned
        # Attached as an UNDECLARED attribute on purpose: persistence goes through
        # asdict(), which walks declared fields only, so these notes reach the caller
        # (the endpoint, which shows them) and can never leak into settings.json.
        # They describe one request, not a stored preference.
        current.last_clamp_notes = notes  # type: ignore[attr-defined]
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
    if (
        "llm_allow_impractical_hw" in updates
        and updates["llm_allow_impractical_hw"] is not None
    ):
        val = updates["llm_allow_impractical_hw"]
        if not isinstance(val, bool):
            raise AppSettingsError("llm_allow_impractical_hw must be a boolean")
        current.llm_allow_impractical_hw = val
    # The coordinator flags: validated as booleans and REJECTED loudly otherwise
    # (never silently coerced -- a truthy string must not be able to switch on
    # hours of background inference the operator did not ask for).
    for _name in (
        "ai_background_enabled",
        "ai_sweep_keyword_triage",
        "ai_sweep_source_tags",
        "ai_sweep_perception_extract",
        "ai_sweep_keyword_translation",
        "ai_sweep_article_titles",
        "bulletin_narrate_introduction",
        # The Q701-note trust toggle joins them: a truthy STRING must not be able to
        # make a restore adopt somebody else's fetch history, which is a decision about
        # what this machine will and will not go and download.
        "trust_backup_fetch_history",
        # And the overlay-adoption preference, for the same reason: a truthy string must
        # not be able to re-admit sources an operator reverted.
        "adopt_shipped_verdicts",
        # Search history is a privacy decision: a truthy string must not switch it on.
        "search_history_enabled",
    ):
        if _name in updates and updates[_name] is not None:
            _val = updates[_name]
            if not isinstance(_val, bool):
                raise AppSettingsError(f"{_name} must be a boolean")
            setattr(current, _name, _val)
    if "search_near_default" in updates and updates["search_near_default"] is not None:
        try:
            nd = int(updates["search_near_default"])
        except (TypeError, ValueError) as exc:
            raise AppSettingsError("search_near_default must be a whole number") from exc
        if not (_NEAR_MIN <= nd <= _NEAR_MAX):
            raise AppSettingsError(
                f"search_near_default must be between {_NEAR_MIN} and {_NEAR_MAX}"
            )
        current.search_near_default = nd
    if "llm_backend" in updates and updates["llm_backend"] is not None:
        val = updates["llm_backend"]
        if val not in ("auto", "ollama", "vllm"):
            raise AppSettingsError("llm_backend must be one of: auto, ollama, vllm")
        current.llm_backend = val
    if "llm_model_vllm" in updates:
        val = updates["llm_model_vllm"]
        if val in (None, ""):
            current.llm_model_vllm = None
        elif isinstance(val, str) and _MODEL_RE.match(val):
            current.llm_model_vllm = val
        else:
            raise AppSettingsError(f"invalid llm_model_vllm {val!r} (must be a model id)")
    if "import_checkpoint_k" in updates and updates["import_checkpoint_k"] is not None:
        # REJECTED loudly, never clamped: K is a durability decision, and silently
        # turning a 30 into a 24 would hand the operator a window they did not
        # choose while telling them nothing. A bool is refused for the same reason
        # the AI flags refuse a string -- True is an int in Python, and "1 backup
        # per checkpoint" is not what anyone means by True.
        val = updates["import_checkpoint_k"]
        if isinstance(val, bool):
            raise AppSettingsError("import_checkpoint_k must be an integer, not a boolean")
        try:
            k = int(val)
        except (TypeError, ValueError) as exc:
            raise AppSettingsError("import_checkpoint_k must be an integer") from exc
        if not (1 <= k <= _CHECKPOINT_K_MAX):
            raise AppSettingsError(
                f"import_checkpoint_k must be between 1 and {_CHECKPOINT_K_MAX} "
                "(1 writes every backup to your corpus as soon as it finishes; "
                "higher values are faster and lose more work if the import is "
                "stopped or crashes)"
            )
        current.import_checkpoint_k = k

    _write_raw({"version": SETTINGS_VERSION, **current.to_dict()})
    return current
