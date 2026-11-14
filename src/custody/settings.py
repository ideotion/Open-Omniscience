"""
Persisted, GUI-editable chain-of-custody preferences.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ``Config`` object (src/config) is loaded once from env/YAML and is *not*
runtime-editable -- fine for deployment knobs, wrong for things an operator wants
to flip from the UI. Chain-of-custody behaviour is exactly that: whether to use
post-quantum signatures, whether to anchor to OpenTimestamps (network + privacy
implications) or stay local-only, and whether to auto-log on ingest.

So custody preferences live in their own small JSON file under the data dir,
read/written at runtime via the API and the GUI. The store is deliberately tiny
and self-describing.

**Honesty invariant.** A stored preference is a *request*, not a guarantee. The
signing/timestamping libraries may not be installed in this build. Callers must
present the *effective* state -- preference AND availability -- never the bare
toggle, so the UI can say "PQC requested but the library is not installed" rather
than showing a misleading green light. :func:`availability` exposes the reality;
the API combines the two.

Backward compatibility: when no settings file exists yet, ``auto_log_on_ingest``
defaults to the legacy ``Config.custody_on_ingest`` (env ``OO_CUSTODY_ON_INGEST``),
which is itself ON by default (maintainer ruling 2026-06-15 Item-N; the Settings UI
states "on by default"). Auto-log is a LOCAL-ONLY write -- the default anchoring
mode is ``local`` (offline, no network egress); OpenTimestamps anchoring stays a
separate opt-in. Opt out with ``OO_CUSTODY_ON_INGEST=0`` or the Settings toggle.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

from src.shared import coerce_bool

_LOG = logging.getLogger(__name__)

SETTINGS_VERSION = "oo-custody-settings-1"
VALID_ANCHORING = ("local", "opentimestamps")


class CustodySettingsError(ValueError):
    """Raised when a settings update is invalid (e.g. an unknown anchoring mode)."""


class CustodySettingsUnreadable(RuntimeError):
    """Raised on the ingest path when the stored preferences cannot be read: the custody entry is queued as owed."""


class _DamagedCustodySettingsError(CustodySettingsError):
    """The stored value is there and cannot be parsed: a user's own save may replace it (``replace_damaged``)."""


@dataclass
class CustodySettings:
    """Operator-controlled custody preferences (requests, not guarantees)."""

    pqc_enabled: bool = False
    anchoring_mode: str = "local"
    auto_log_on_ingest: bool = True
    default_actor: str | None = None
    #: The stored preferences are there and could not be read (a damaged row, a locked file, or a store keyed to
    #: another passphrase). Never stored. Then auto-log reads as OFF and the ingest path queues the entry as owed
    #: instead of writing it under guessed preferences: an operator who switched auto-log off is not logged, and one
    #: who left it on loses nothing (queue:1255).
    store_unreadable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def stored(self) -> dict:
        """The fields a save persists (``store_unreadable`` is a fact about a read, not a preference)."""
        return {k: v for k, v in asdict(self).items() if k != "store_unreadable"}


# The ``app_state`` kv key this preference blob lives under (DB-reliability D1).
_KV_KEY = "settings.custody"


def _settings_path():
    from src.paths import data_dir

    return data_dir() / "custody_settings.json"


def _store():
    """The shared read side (src/config/settings_store.py); only the names below are this module's."""
    from src.config.settings_store import SettingsStore

    return SettingsStore(
        kv_key=_KV_KEY,
        file_name="custody_settings.json",
        path_getter=lambda: _settings_path(),
        refusal=CustodySettingsError,
        damaged=_DamagedCustodySettingsError,
        log=_LOG,
        use_kv_hook=lambda: _use_kv(),
        json_hook=lambda: _read_json_file(),
    )


def _use_kv() -> bool:
    """Use the encrypted ``app_state`` store at the DEFAULT location; honour a redirected
    ``_settings_path`` (test isolation) as JSON instead."""
    return _store().use_kv()


def _read_json_file() -> dict | None:
    return _store().read_json_file()


def _read_raw() -> dict | None:
    """Preferences source of truth: the encrypted ``app_state`` row (D1), falling back to
    (and one-time migrating) the legacy ``custody_settings.json`` file."""
    return _store().read_raw()


def _read_raw_checked() -> dict | None:
    """``_read_raw`` that raises CustodySettingsError on a stored row it could not read, instead of reading it as unset.
    The reader's own open (read-only, a failed read held 2 s), never a save's."""
    return _store().read_raw_checked()


def _read_raw_strict() -> dict | None:
    """``_read_raw`` for a caller that will REWRITE what it read: a stored row that cannot be read raises CustodySettingsError (the class only)
    instead of reading as the defaults, because saving the defaults back over the user's settings is the loss this prevents."""
    return _store().read_raw_strict()


_LEGACY_TMP_MIN_AGE_S = 60.0


def _sweep_legacy_tmp() -> None:
    """Remove a ``custody_settings.json.tmp`` an older writer left behind (0.6.1, R552).

    No writer uses that fixed name since #1796 (the temp is now named per process and thread),
    so a file under it is only ever a leftover from a write that died before its rename. It
    never holds the settings of record, so removing it loses nothing; a failure is ignored. Only a
    file older than a minute goes: an older build sharing the folder (R176) may be mid-write.
    """
    import time

    tmp = _settings_path().with_suffix(".json.tmp")
    try:
        if time.time() - tmp.stat().st_mtime > _LEGACY_TMP_MIN_AGE_S:
            tmp.unlink(missing_ok=True)
    except OSError:
        pass  # absent (the usual case), or not ours to remove


def _write_raw(payload: dict) -> None:
    if not _use_kv():
        from src.safety.file_lock import atomic_replace

        # A temp named for the process and thread, moved over the file (R176): the fixed ".json.tmp" two writers shared is gone.
        atomic_replace(_settings_path(), json.dumps(payload, indent=2, sort_keys=True), fsync=False)
        _sweep_legacy_tmp()
        return
    from src.config.kv_store import kv_set_json

    kv_set_json(_KV_KEY, payload)
    _sweep_legacy_tmp()


def _legacy_auto_log_default() -> bool:
    """The pre-settings default for auto-log-on-ingest, from env/YAML config."""
    try:
        # Not ``get_config()``: that builds the whole Config, source catalogue included (seconds of YAML on the first custody read).
        from src.config.settings import legacy_custody_on_ingest

        return legacy_custody_on_ingest()
    except Exception:  # noqa: BLE001 - config is optional context; never block custody
        return True  # matches the on-by-default dataclass default (Item-N ruling)


def load_settings(*, strict: bool = False) -> CustodySettings:
    """Load custody preferences, falling back to honest defaults.

    A missing file yields defaults (with ``auto_log_on_ingest`` seeded from the
    legacy config flag). A stored row that cannot be read (damaged, locked, keyed otherwise) is NOT read as
    unset: it yields the defaults with ``store_unreadable`` set and auto-log OFF, so nothing is logged under preferences
    the operator may have changed; the ingest path queues that entry as owed. ``strict`` raises instead (a save).
    """
    if strict:
        raw = _read_raw_strict()  # a save that rewrites what it read: an unreadable store refuses
    else:
        try:
            raw = _read_raw_checked()
        except CustodySettingsError as exc:
            # Unreadable is not unset: the legacy default (ON) would log an operator who switched auto-log off.
            # DEBUG: in a pool storm this is every ingest; each one's owed entry is logged by the ingest path already.
            _LOG.debug("custody settings are unreadable; auto-log on ingest waits (%s)", type(exc).__name__)
            return CustodySettings(auto_log_on_ingest=False, store_unreadable=True)
    if raw is None:
        return CustodySettings(auto_log_on_ingest=_legacy_auto_log_default())

    defaults = CustodySettings()
    mode = raw.get("anchoring_mode", defaults.anchoring_mode)
    if mode not in VALID_ANCHORING:
        _LOG.warning("ignoring invalid stored anchoring_mode %r", mode)
        mode = defaults.anchoring_mode
    actor = raw.get("default_actor")
    return CustodySettings(
        pqc_enabled=coerce_bool(raw.get("pqc_enabled"), defaults.pqc_enabled),
        anchoring_mode=mode,
        auto_log_on_ingest=coerce_bool(raw.get("auto_log_on_ingest"), defaults.auto_log_on_ingest),
        default_actor=str(actor) if actor else None,
    )


def save_settings(updates: dict, *, replace_damaged: bool = False) -> CustodySettings:
    """Apply a partial update to the stored preferences and persist them.

    Only keys present in ``updates`` are changed; unknown keys are ignored.
    Raises :class:`CustodySettingsError` on an invalid value (e.g. a bad
    anchoring mode) before anything is written.

    **Consent gate (P1 audit finding, UI invariant #14/#14e).** Turning
    ``anchoring_mode`` ON to ``"opentimestamps"`` starts a RECURRING, silent,
    per-article network submission to public OpenTimestamps calendar servers (see
    ``src.custody.log._default_timestamp`` / ``src.ingest.pipeline._maybe_record_custody``)
    that can fire minutes or hours after this call, with no button click of its own
    -- there is no later moment to gate the way every other network-triggering
    action in this app is gated (``ensureOnline``). So the ONE transactional
    confirmation has to happen HERE, at the moment the preference is saved: this
    call refuses (rather than silently persisting) a transition INTO
    ``"opentimestamps"`` unless ``updates["ots_consent"]`` is truthy. It is a
    transition check, not a standing requirement -- re-saving other fields while
    already anchoring via OpenTimestamps does not re-demand consent every time
    (that would be a rubber stamp, not an informed decision); turning it off, or
    saving while it stays "local", never needs it. ``ots_consent`` itself is never
    persisted -- it is a one-shot instruction to this call, not a preference.
    """
    reset: list[str] = []
    try:
        current = load_settings(strict=True)  # an unreadable store refuses; it does not save the defaults over it
    except _DamagedCustodySettingsError:
        if not replace_damaged:
            raise
        # The value is there and cannot be parsed, and this is the user's own save (the route says so): it replaces it, over the
        # defaults. Nothing readable is lost; what this save does not supply is reported as reset. One uncached read first, so a
        # value another process repaired in the meantime is kept, not overwritten.
        from src.config.kv_store import kv_invalidate

        kv_invalidate(_KV_KEY)
        try:
            current = load_settings(strict=True)
        except _DamagedCustodySettingsError:
            current = CustodySettings(auto_log_on_ingest=_legacy_auto_log_default())
            reset = sorted(set(current.stored()) - {k for k, v in updates.items() if v is not None})
    current.reset_fields = reset  # type: ignore[attr-defined]

    if "anchoring_mode" in updates and updates["anchoring_mode"] is not None:
        mode = str(updates["anchoring_mode"])
        if mode not in VALID_ANCHORING:
            raise CustodySettingsError(
                f"unknown anchoring_mode {mode!r}; use one of: {', '.join(VALID_ANCHORING)}"
            )
        if (
            mode == "opentimestamps"
            and current.anchoring_mode != "opentimestamps"
            and not updates.get("ots_consent")
        ):
            raise CustodySettingsError(
                "turning on OpenTimestamps anchoring requires explicit consent "
                "(ots_consent: true) -- it submits a hash to public Bitcoin calendar "
                "servers, revealing your IP and timing, on every future ingested "
                "article for as long as this stays on"
            )
        current.anchoring_mode = mode
    if "pqc_enabled" in updates and updates["pqc_enabled"] is not None:
        current.pqc_enabled = coerce_bool(updates["pqc_enabled"], current.pqc_enabled)
    if "auto_log_on_ingest" in updates and updates["auto_log_on_ingest"] is not None:
        current.auto_log_on_ingest = coerce_bool(
            updates["auto_log_on_ingest"], current.auto_log_on_ingest
        )
    if "default_actor" in updates:
        actor = updates["default_actor"]
        current.default_actor = str(actor).strip() if actor and str(actor).strip() else None

    _write_raw({"version": SETTINGS_VERSION, **current.stored()})
    return current


def availability() -> dict:
    """Report what the *build* can actually do, independent of preferences.

    THE FLAGS NOW MEAN WHAT THIS DOCSTRING ALWAYS PROMISED (D7). Until 2026-09-07 they
    were set by a bare ``import`` succeeding, so this function published
    ``{"pqc_available": true}`` for a library that could not sign -- a fabricated
    capability claim under a sentence saying "what the build can ACTUALLY do". Both are
    now round-trip probes.

    THE REASONS TRAVEL WITH THEM, because "not installed" and "installed but it cannot
    sign" call for opposite actions -- one is a pip install, the other is a version
    problem nobody can fix by installing harder -- and a lone boolean cannot say which.
    Added ALONGSIDE the existing keys, never replacing them: every caller of
    ``pqc_available``/``ots_available`` keeps reading exactly what it read before.
    """
    from src.custody.signing import PQC_AVAILABLE, PQC_REASON
    from src.custody.timestamp import OTS_AVAILABLE, OTS_REASON

    return {
        "pqc_available": bool(PQC_AVAILABLE),
        "pqc_reason": PQC_REASON,
        "ots_available": bool(OTS_AVAILABLE),
        "ots_reason": OTS_REASON,
    }
