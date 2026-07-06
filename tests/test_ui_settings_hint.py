"""
Wave 3 H — the stale Settings storage hint corrected to the truth.

The Save-preferences hint claimed settings are "Stored locally in app_settings.json under
the data directory" — false since settings moved into the encrypted corpus DB (app_state
kv). The honest wording says they live in the encrypted database and ride backups. Keyed
×12 (the old key was renamed in place across every locale).

Browser-unverified per fork-3 — grep-guarded here.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.test_repo_invariants import _ui_source

_LOCALES = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"


def test_stale_app_settings_json_claim_is_gone():
    ui = _ui_source()
    assert "app_settings.json" not in ui, "the false app_settings.json storage claim must be removed"


def test_settings_hint_states_the_encrypted_db_truth():
    ui = _ui_source()
    assert "encrypted corpus database (app_state)" in ui, "the hint must name the real store"
    assert "ride your backups" in ui, "the hint must state that settings ride backups"


def test_settings_hint_key_is_translated_in_every_locale():
    new_key = ("Stored in your encrypted corpus database (app_state) — your settings ride "
               "your backups; no telemetry, nothing leaves the machine.")
    old_key = ("Stored locally in app_settings.json under the data directory — no telemetry, "
               "nothing leaves the machine.")
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert new_key in data, f"{path.stem}: the corrected hint key is missing"
        assert old_key not in data, f"{path.stem}: the stale hint key must be removed"
        assert str(data[new_key]).strip(), f"{path.stem}: the corrected hint has an empty value"
