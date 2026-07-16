"""
First-run consent record for the legal document set.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A tiny, self-contained helper (same pattern as ``src.config.app_settings``): it
records the Utilisateur's explicit acceptance of the legal documents under
``docs/legal/`` in a small JSON file inside the local data dir, and answers
"does this user still need to accept?". It is:

  * **local-only** — the record never leaves the machine and is never sent to the
    Éditeur (mirrors the project's no-telemetry posture);
  * **network-free and side-effect-free on import** — safe to import anywhere;
  * **version-aware** — bumping :data:`CONSENT_DOC_VERSION` re-prompts the user.

Nothing here BLOCKS the application. Enforcement (a CLI notice, a web modal, or an
opt-in hard block) is wired by the callers — see ``docs/legal/IMPLEMENTATION_NOTES.md``.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

# Schema marker for the on-disk record, so a future format change is detectable.
CONSENT_SCHEMA = "oo-legal-consent-1"

# Version of the legal document set the user is asked to accept. It MUST be kept in
# sync with the "Version" field of the documents in ``docs/legal/`` and bumped
# whenever they change substantially, so the gate asks the user to accept again.
#
# NOTE: this is the v1 document set with the first-launch acceptance gate. Open
# Omniscience is a free, non-commercial, unfunded hobby project, so these documents
# are NOT reviewed by a lawyer, permanently (see the banner in each doc) — bump this
# string whenever the documents change substantially so users are re-prompted.
CONSENT_DOC_VERSION = "1.0"

# The documents the user accepts, for display by the CLI / web GUI. Paths are
# relative to the repository root; the canonical online copies live in the repo.
LEGAL_DOCUMENTS: list[dict[str, str]] = [
    {"id": "mentions_legales", "title": "Mentions légales", "path": "docs/legal/MENTIONS_LEGALES.md"},
    {"id": "cgu", "title": "Conditions Générales d'Utilisation (CGU)", "path": "docs/legal/CGU.md"},
    {"id": "confidentialite", "title": "Politique de confidentialité (RGPD)", "path": "docs/legal/POLITIQUE_DE_CONFIDENTIALITE.md"},
    {"id": "charte_usage", "title": "Charte d'usage", "path": "docs/legal/CHARTE_USAGE.md"},
]

_DOCS_BASE_URL = "https://github.com/ideotion/Open-Omniscience/blob/HEAD"


def consent_path() -> Path:
    """Path to the local consent record (created lazily on first write)."""
    return data_dir() / "legal_consent.json"


def load_consent() -> dict | None:
    """Return the stored consent record, or ``None`` if absent/unreadable.

    Never raises: a corrupt or missing file is treated as "not yet accepted".
    """
    path = consent_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        _LOG.warning("legal consent record is unreadable; treating as not accepted")
        return None
    return data if isinstance(data, dict) else None


def is_accepted(version: str = CONSENT_DOC_VERSION) -> bool:
    """True iff a stored record accepts exactly ``version``."""
    record = load_consent()
    return bool(record) and record.get("version") == version


def needs_acceptance(version: str = CONSENT_DOC_VERSION) -> bool:
    """True iff the user has not yet accepted ``version`` (no record or stale one)."""
    return not is_accepted(version)


def record_consent(version: str = CONSENT_DOC_VERSION, *, actor: str = "local") -> dict:
    """Record explicit acceptance of ``version`` locally and return the record.

    ``accepted_at`` is an ISO-8601 UTC timestamp. The write is best-effort; an I/O
    failure is logged and re-raised so a caller can surface it honestly.
    """
    record = {
        "schema": CONSENT_SCHEMA,
        "version": version,
        "accepted_at": datetime.now(UTC).isoformat(),
        "actor": actor,
        "documents": [d["id"] for d in LEGAL_DOCUMENTS],
    }
    path = consent_path()
    try:
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        _LOG.exception("could not write the legal consent record to %s", path)
        raise
    return record


def consent_status(version: str = CONSENT_DOC_VERSION) -> dict:
    """A serialisable status for the API / CLI: what is required and what was accepted."""
    record = load_consent()
    return {
        "required": needs_acceptance(version),
        "current_version": version,
        "accepted_version": (record or {}).get("version"),
        "accepted_at": (record or {}).get("accepted_at"),
        "documents": [
            {**d, "url": f"{_DOCS_BASE_URL}/{d['path']}"} for d in LEGAL_DOCUMENTS
        ],
    }


def notice_text(version: str = CONSENT_DOC_VERSION) -> str:
    """A short, non-blocking console notice listing the documents to accept.

    Bilingual (FR/EN) and plain: the legal documents themselves are in French.
    """
    lines = [
        "",
        "── Open Omniscience — conditions d'utilisation / terms of use ──",
        "En utilisant ce logiciel, vous acceptez les documents suivants",
        "(modèles de travail, non révisés par un professionnel — voir docs/legal/) :",
        "By using this software you accept the following documents",
        "(working drafts, not reviewed by a legal professional — see docs/legal/):",
    ]
    for d in LEGAL_DOCUMENTS:
        lines.append(f"  • {d['title']} — {d['path']}")
    lines += [
        "",
        f"Version : {version}",
        "Accepter / accept :  open-omniscience accept-terms",
        "(ou via l'interface web au premier lancement / or via the web UI at first launch)",
        "───────────────────────────────────────────────────────────────",
        "",
    ]
    return "\n".join(lines)
