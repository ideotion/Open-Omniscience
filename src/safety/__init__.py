"""
At-risk-user safety — encrypted backup, panic-wipe, ephemeral mode, protected fetch.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

An investigative journalist may work under surveillance, face device seizure, or endanger
a source merely by *announcing interest* in a target. This package extends the app's
local-first privacy with **application-level** protections — for data at rest, in transit,
and the act of researching itself — each labelled with exactly what it does and does **not**
guarantee (the honest-crypto rule: a feature that *claims* a protection it cannot deliver is
worse than its absence). Full-disk encryption remains the host's job (Qubes / LUKS / Tails);
these add protection on top, not instead. See ``docs/NEXT_VERSION.md`` (Theme 2).
"""

from __future__ import annotations

from src.safety.backup import make_encrypted_backup, restore_encrypted_backup
from src.safety.crypto import EncryptionError, decrypt_bytes, encrypt_bytes
from src.safety.fetcher import make_fetcher
from src.safety.panic import panic_wipe
from src.safety.settings import SafetySettings, load_settings, save_settings

__all__ = [
    "encrypt_bytes",
    "decrypt_bytes",
    "EncryptionError",
    "make_encrypted_backup",
    "restore_encrypted_backup",
    "panic_wipe",
    "make_fetcher",
    "SafetySettings",
    "load_settings",
    "save_settings",
]
