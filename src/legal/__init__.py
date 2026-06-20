"""
Legal / governance support (consent gate).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This package holds the small, self-contained mechanism that records the
Utilisateur's explicit acceptance of the legal document set under ``docs/legal/``
(Mentions légales, CGU, Politique de confidentialité, Charte d'usage). It NEVER
touches the network and stores the consent record only on the local machine.

See ``docs/legal/IMPLEMENTATION_NOTES.md`` for how the CLI and web GUI wire into it.
"""

from src.legal.consent import (
    CONSENT_DOC_VERSION,
    LEGAL_DOCUMENTS,
    consent_path,
    consent_status,
    is_accepted,
    load_consent,
    needs_acceptance,
    notice_text,
    record_consent,
)

__all__ = [
    "CONSENT_DOC_VERSION",
    "LEGAL_DOCUMENTS",
    "consent_path",
    "consent_status",
    "is_accepted",
    "load_consent",
    "needs_acceptance",
    "notice_text",
    "record_consent",
]
