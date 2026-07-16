"""
Serving the legal documents (per UI language) + the download bundle + the
decline-uninstall action for the first-launch consent gate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The French documents under ``docs/legal/*.md`` are the AUTHORITATIVE legal texts.
Translations live under ``docs/legal/<lang>/*.md`` (machine-drafted, flagged for
native review) and are served as a courtesy; when a translation is missing the
French canonical is served (so the gate works in every UI language from day one).

Everything here is local + network-free. Nothing is sent to the Éditeur.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

from src.legal.consent import CONSENT_DOC_VERSION, LEGAL_DOCUMENTS
from src.paths import repo_root

_LOG = logging.getLogger(__name__)

#: The authoritative language. Its documents are the canonical ``docs/legal/*.md``.
AUTHORITATIVE_LANG = "fr"

#: The 12 UI languages the gate supports (mirrors src/static/unlock.html LANGS).
UI_LANGS = ("en", "fr", "es", "de", "zh", "hi", "ar", "bn", "ru", "pt", "id", "ja")

# Chrome strings for the first-launch legal step. The English source is the
# fallback for any missing key/translation; the French copy is built in (the
# authoritative-language chrome). Other languages provide docs/legal/<lang>/ui.json
# (written by the translation pass); missing keys fall back to English. The
# typed-confirm word stays the language-neutral ASCII "UNINSTALL", like the app's
# panic "WIPE" — so the irreversible action never depends on localized input.
LEGAL_UI_EN: dict[str, str] = {
    "heading": "Legal documents",
    "intro": "Before you start, please read and accept these documents. They govern how you use this software and its AI-generated results. They add no restriction to the GNU GPL v3 (the code licence); the French version is authoritative.",
    "draft_note": "Working drafts — not legal advice; will not be reviewed by a legal professional (a deliberate, permanent choice).",
    "translation_note": "Machine translation — the French version is the authoritative text.",
    "open": "Open",
    "accept_label": "I have read and accept these documents.",
    "accept_btn": "Accept and continue",
    "decline_btn": "Decline",
    "download_btn": "Download the documents",
    "decline_warn": "Declining will UNINSTALL the app and permanently delete all of its files and data on this machine. This cannot be undone. (You can always re-install it later.)",
    "decline_type": "To confirm, type UNINSTALL:",
    "decline_confirm_btn": "Uninstall and delete everything",
    "decline_cancel_btn": "Cancel",
    "uninstalling": "Uninstalling — the app is stopping and its files are being removed. You can close this window.",
    "error": "Could not load the legal documents.",
}
LEGAL_UI_FR: dict[str, str] = {
    "heading": "Documents juridiques",
    "intro": "Avant de commencer, veuillez lire et accepter ces documents. Ils encadrent votre utilisation du logiciel et de ses résultats produits par l'IA. Ils n'ajoutent aucune restriction à la licence GNU GPL v3 (la licence du code) ; la version française fait foi.",
    "draft_note": "Modèles de travail — pas un avis juridique ; ne seront pas relus par un professionnel du droit (choix délibéré et permanent).",
    "translation_note": "Traduction automatique — la version française est le texte qui fait foi.",
    "open": "Ouvrir",
    "accept_label": "J'ai lu et j'accepte ces documents.",
    "accept_btn": "Accepter et continuer",
    "decline_btn": "Refuser",
    "download_btn": "Télécharger les documents",
    "decline_warn": "Refuser DÉSINSTALLERA l'application et supprimera définitivement tous ses fichiers et données sur cette machine. Cette action est irréversible. (Vous pourrez toujours réinstaller plus tard.)",
    "decline_type": "Pour confirmer, tapez UNINSTALL :",
    "decline_confirm_btn": "Désinstaller et tout supprimer",
    "decline_cancel_btn": "Annuler",
    "uninstalling": "Désinstallation — l'application s'arrête et ses fichiers sont supprimés. Vous pouvez fermer cette fenêtre.",
    "error": "Impossible de charger les documents juridiques.",
}

# The literal confirmation word the user must type to trigger the decline-uninstall.
# Language-neutral by design (ASCII), like the panic-wipe "WIPE".
DECLINE_CONFIRM_WORD = "UNINSTALL"


def legal_dir() -> Path:
    """Directory holding the canonical French legal documents (``docs/legal``)."""
    return repo_root() / "docs" / "legal"


def _is_lang(code: str) -> bool:
    return code in UI_LANGS


def document_path(lang: str, filename: str) -> Path:
    """Resolve the on-disk path for a document in ``lang``.

    French (or an unknown lang) → the canonical ``docs/legal/<file>``. Another
    language → ``docs/legal/<lang>/<file>`` when it exists, else the French
    canonical (so a missing translation never breaks the gate).
    """
    base = legal_dir()
    if lang and lang != AUTHORITATIVE_LANG and _is_lang(lang):
        translated = base / lang / filename
        if translated.is_file():
            return translated
    return base / filename


def load_documents(lang: str) -> list[dict]:
    """The legal documents (id, title, markdown, source-language) for ``lang``.

    Reads the markdown text (the GUI renders a safe subset). A document whose file
    is missing entirely is skipped — never fabricated.
    """
    out: list[dict] = []
    for doc in LEGAL_DOCUMENTS:
        path = document_path(lang, Path(doc["path"]).name)
        try:
            md = path.read_text(encoding="utf-8")
        except OSError:
            _LOG.warning("legal document missing: %s", path)
            continue
        is_fallback = path == (legal_dir() / Path(doc["path"]).name) and lang not in ("", AUTHORITATIVE_LANG)
        out.append({
            "id": doc["id"],
            "title": doc["title"],
            "markdown": md,
            "source_lang": AUTHORITATIVE_LANG if (lang == AUTHORITATIVE_LANG or is_fallback) else lang,
        })
    return out


def load_ui_strings(lang: str) -> dict[str, str]:
    """Chrome strings for the legal step in ``lang`` (English fallback for any gap)."""
    if lang == AUTHORITATIVE_LANG:
        return dict(LEGAL_UI_FR)
    merged = dict(LEGAL_UI_EN)
    if lang and lang != "en" and _is_lang(lang):
        path = legal_dir() / lang / "ui.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged.update({k: str(v) for k, v in data.items() if k in LEGAL_UI_EN and v})
        except (OSError, ValueError, TypeError):
            pass  # missing/invalid translation → English fallback (never fabricate)
    return merged


def documents_payload(lang: str) -> dict:
    """The full payload the first-launch GUI needs to render the legal step."""
    lang = lang if _is_lang(lang) else "en"
    docs = load_documents(lang)
    any_fallback = any(d["source_lang"] == AUTHORITATIVE_LANG for d in docs) and lang != AUTHORITATIVE_LANG
    return {
        "lang": lang,
        "authoritative_lang": AUTHORITATIVE_LANG,
        "is_translation": lang != AUTHORITATIVE_LANG,
        "has_fallback": any_fallback,
        "version": CONSENT_DOC_VERSION,
        "confirm_word": DECLINE_CONFIRM_WORD,
        "documents": docs,
        "ui": load_ui_strings(lang),
    }


def perform_decline_uninstall() -> dict:
    """Trigger the full uninstall after the user DECLINES the legal documents.

    Secure mode: removes the virtualenv + desktop launchers + the app folder AND
    wipes the data dir & keys, then stops the server (the deletion runs in a
    detached watcher after this process exits). Wrapped here so the API stays thin
    and tests can stub it (the real ``request_uninstall`` is never called in tests).
    """
    from src.safety.uninstall import request_uninstall

    return request_uninstall(confirm=True, remove_folder=True, wipe_data=True)


def build_download_zip(lang: str) -> bytes:
    """A .zip of the legal documents in ``lang`` (French canonical for any gap)."""
    lang = lang if _is_lang(lang) else AUTHORITATIVE_LANG
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc in LEGAL_DOCUMENTS:
            name = Path(doc["path"]).name
            path = document_path(lang, name)
            try:
                zf.writestr(name, path.read_text(encoding="utf-8"))
            except OSError:
                continue
        zf.writestr("README.txt",
                    f"Open Omniscience — legal documents ({lang}).\n"
                    f"The French version (docs/legal/*.md) is the authoritative text.\n"
                    f"Version: {CONSENT_DOC_VERSION}\n")
    return buf.getvalue()
