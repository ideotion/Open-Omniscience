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

_LOG = logging.getLogger(__name__)

SETTINGS_VERSION = "oo-custody-settings-1"
VALID_ANCHORING = ("local", "opentimestamps")


class CustodySettingsError(ValueError):
    """Raised when a settings update is invalid (e.g. an unknown anchoring mode)."""


@dataclass
class CustodySettings:
    """Operator-controlled custody preferences (requests, not guarantees)."""

    pqc_enabled: bool = False
    anchoring_mode: str = "local"
    auto_log_on_ingest: bool = True
    default_actor: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _settings_path():
    from src.paths import data_dir

    return data_dir() / "custody_settings.json"


def _coerce_bool(value, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return fallback


def _legacy_auto_log_default() -> bool:
    """The pre-settings default for auto-log-on-ingest, from env/YAML config."""
    try:
        from src.config import get_config

        return bool(get_config().custody_on_ingest)
    except Exception:  # noqa: BLE001 - config is optional context; never block custody
        return True  # matches the on-by-default dataclass default (Item-N ruling)


def load_settings() -> CustodySettings:
    """Load custody preferences, falling back to honest defaults.

    A missing file yields defaults (with ``auto_log_on_ingest`` seeded from the
    legacy config flag). A corrupt file is logged and treated as defaults rather
    than crashing the API.
    """
    path = _settings_path()
    if not path.exists():
        return CustodySettings(auto_log_on_ingest=_legacy_auto_log_default())
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - never let a bad file take down custody
        _LOG.warning("custody_settings.json is unreadable; using defaults", exc_info=True)
        return CustodySettings(auto_log_on_ingest=_legacy_auto_log_default())

    defaults = CustodySettings()
    mode = raw.get("anchoring_mode", defaults.anchoring_mode)
    if mode not in VALID_ANCHORING:
        _LOG.warning("ignoring invalid stored anchoring_mode %r", mode)
        mode = defaults.anchoring_mode
    actor = raw.get("default_actor")
    return CustodySettings(
        pqc_enabled=_coerce_bool(raw.get("pqc_enabled"), defaults.pqc_enabled),
        anchoring_mode=mode,
        auto_log_on_ingest=_coerce_bool(raw.get("auto_log_on_ingest"), defaults.auto_log_on_ingest),
        default_actor=str(actor) if actor else None,
    )


def save_settings(updates: dict) -> CustodySettings:
    """Apply a partial update to the stored preferences and persist them.

    Only keys present in ``updates`` are changed; unknown keys are ignored.
    Raises :class:`CustodySettingsError` on an invalid value (e.g. a bad
    anchoring mode) before anything is written.
    """
    current = load_settings()

    if "anchoring_mode" in updates and updates["anchoring_mode"] is not None:
        mode = str(updates["anchoring_mode"])
        if mode not in VALID_ANCHORING:
            raise CustodySettingsError(
                f"unknown anchoring_mode {mode!r}; use one of: {', '.join(VALID_ANCHORING)}"
            )
        current.anchoring_mode = mode
    if "pqc_enabled" in updates and updates["pqc_enabled"] is not None:
        current.pqc_enabled = _coerce_bool(updates["pqc_enabled"], current.pqc_enabled)
    if "auto_log_on_ingest" in updates and updates["auto_log_on_ingest"] is not None:
        current.auto_log_on_ingest = _coerce_bool(
            updates["auto_log_on_ingest"], current.auto_log_on_ingest
        )
    if "default_actor" in updates:
        actor = updates["default_actor"]
        current.default_actor = str(actor).strip() if actor and str(actor).strip() else None

    path = _settings_path()
    tmp = path.with_suffix(".json.tmp")
    payload = {"version": SETTINGS_VERSION, **current.to_dict()}
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
    tmp.replace(path)  # atomic on the same filesystem
    return current


def availability() -> dict:
    """Report what the *build* can actually do, independent of preferences."""
    from src.custody.signing import PQC_AVAILABLE
    from src.custody.timestamp import OTS_AVAILABLE

    return {"pqc_available": bool(PQC_AVAILABLE), "ots_available": bool(OTS_AVAILABLE)}
