"""BETA wave — B4: i18n English-fallback sweep of the backup/import/restore subsystem.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Recent panels shipped strings via t() English-fallback ("keyable later"). B4 keys a
COHERENT batch — the backup / import / restore subsystem (Settings → Data & backup: the
volume-backup panel status, the folder import/export controls, the legacy restore) —
across all 12 locales in one commit. Pure locale JSON + file-reads; no app import.
"""

from __future__ import annotations

import json
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_LOCALES = _STATIC / "locales"
_LANGS = ["en", "ar", "bn", "de", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"]
_SRC = (_STATIC / "app.js").read_text(encoding="utf-8") + (_STATIC / "index.html").read_text(encoding="utf-8")

# The coherent backup/import/restore batch keyed by B4.
_BATCH = [
    "Corpus backup", "Large data", "Legacy", "Backing up…", "Building encrypted volumes…",
    "Writing encrypted volumes…", "Writing parity…", "Verifying volumes…", "Reassembling the archive…",
    "Restoring…", "Restore complete.", "Merging (additive)…", "Preparing…", "Choose a destination folder.",
    "Choose a folder to restore from.", "This folder is not writable — pick another for a backup destination.",
    "Enter a passphrase.", "Enter the passphrase.", "Plaintext archive — no passphrase needed.",
    "Encrypted backup — enter its passphrase.", "(volumes only — parity needs the analysis features)",
    "Import successful", "Import failed:", "Import continues in the background — watch it in the task manager.",
    "Backup complete:", "Export / Backup", "Destination folder (on this machine / a mounted drive)",
    "Folder to import from", "Passphrase (to decrypt the corpus backup)",
    "Passphrase — encrypts the corpus (no recovery for a lost passphrase)", "Restore a legacy backup file",
]


def test_batch_keys_present_and_nonempty_in_all_twelve_locales():
    for lang in _LANGS:
        data = json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        for k in _BATCH:
            assert k in data, f"{lang}.json missing backup-batch key {k!r}"
            assert str(data[k]).strip(), f"{lang}.json empty value for {k!r}"


def test_non_english_values_are_actually_translated_not_stubs():
    """A stub locale would echo the English string; every non-en value must differ from en
    (these are genuine translations, flagged for native review)."""
    en = json.loads((_LOCALES / "en.json").read_text(encoding="utf-8"))
    for lang in [l for l in _LANGS if l != "en"]:
        data = json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        for k in _BATCH:
            assert data[k] != en[k], f"{lang}.json left {k!r} untranslated (English stub)"


def test_every_batch_key_is_actually_used_in_the_ui():
    """No dead keys — each batch string appears literally in app.js or index.html."""
    for k in _BATCH:
        assert k in _SRC, f"batch key {k!r} is not used in the UI source"


def test_en_is_identity_for_the_batch():
    en = json.loads((_LOCALES / "en.json").read_text(encoding="utf-8"))
    for k in _BATCH:
        assert en[k] == k, f"en.json must map {k!r} to itself"
