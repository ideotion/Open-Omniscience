"""Tests for the legal document serving / download / decline-uninstall endpoints.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

No browser, no real uninstall: the HTTP tests mount only the legal router, and the
decline test stubs the uninstall so nothing is ever removed.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]


def _app() -> FastAPI:
    from src.api.legal import router

    a = FastAPI()
    a.include_router(router)
    return a


def test_documents_payload_fr_is_canonical():
    from src.legal.documents import documents_payload

    p = documents_payload("fr")
    assert p["lang"] == "fr" and p["authoritative_lang"] == "fr"
    assert p["is_translation"] is False
    assert p["version"]  # a concrete version, not empty
    assert p["confirm_word"] == "UNINSTALL"
    assert len(p["documents"]) == 4 and all(d["markdown"].strip() for d in p["documents"])
    assert p["ui"]["accept_btn"] and "fait foi" in p["ui"]["translation_note"]


def test_documents_unknown_lang_falls_back_to_english_chrome():
    from src.legal.documents import documents_payload

    p = documents_payload("zzz")  # unknown -> English chrome, French document fallback
    assert p["lang"] == "en"
    assert p["ui"]["accept_btn"] == "Accept and continue"
    assert len(p["documents"]) == 4


def test_documents_endpoint_marks_translation():
    c = TestClient(_app())
    body = c.get("/api/legal/documents?lang=en").json()
    assert body["lang"] == "en" and body["is_translation"] is True
    assert len(body["documents"]) == 4  # at least the French canonical (fallback)
    assert body["ui"]["heading"]


def test_download_returns_a_zip_of_the_documents():
    c = TestClient(_app())
    r = c.get("/api/legal/download?lang=fr")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    assert "attachment" in r.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "CGU.md" in names and "README.txt" in names


def test_decline_requires_typed_confirmation():
    import src.api.legal as legal_api

    calls: list[int] = []
    orig = legal_api.perform_decline_uninstall
    legal_api.perform_decline_uninstall = lambda: (calls.append(1), {"scheduled": True, "note": "stub"})[1]
    try:
        c = TestClient(_app())
        # Wrong word -> 400, no uninstall.
        assert c.post("/api/legal/decline", json={"confirm": True, "word": "nope"}).status_code == 400
        # Not confirmed -> 400, no uninstall.
        assert c.post("/api/legal/decline", json={"confirm": False, "word": "UNINSTALL"}).status_code == 400
        assert calls == []
        # Correct typed confirmation -> the (stubbed) uninstall fires.
        r = c.post("/api/legal/decline", json={"confirm": True, "word": "UNINSTALL"})
        assert r.status_code == 200 and r.json()["scheduled"] is True
        assert calls == [1]
    finally:
        legal_api.perform_decline_uninstall = orig


def test_legal_endpoints_are_reachable_while_locked():
    from src.api.unlock import ALLOWED_WHILE_LOCKED

    assert "/api/legal/" in ALLOWED_WHILE_LOCKED


def test_draft_note_is_consistent_with_the_permanent_no_review_framing():
    """Field report 2026-07-16: the consent-gate screen showed a genuine inconsistency
    -- the document banner said "will not be reviewed by a legal professional,
    permanently, a deliberate choice" while the SEPARATE chrome caption right above it
    (``LEGAL_UI_*['draft_note']`` in src/legal/documents.py, or its per-language
    docs/legal/<lang>/ui.json override) still said "to be reviewed by a qualified
    professional" -- a stale leftover from BEFORE the permanent no-lawyer-review
    decision, in a code path the earlier docs/legal/*.md sync never touched. Pin every
    UI language's draft_note as NOT reverting to that pending-review framing (the
    specific stale substring that was actually removed, one per language)."""
    from src.legal.documents import UI_LANGS, documents_payload

    stale_substrings = {
        "en": "to be reviewed by a qualified professional",
        "fr": "à faire valider par un professionnel qualifié",
        "de": "von einer qualifizierten Fachperson zu prüfen",
        "es": "deben ser revisados por un profesional cualificado",
        "zh": "须由合格的专业人士审阅",
        "ar": "يجب مراجعتها من مختصٍّ مؤهَّل",
        "bn": "একজন যোগ্য পেশাজীবী দ্বারা পর্যালোচিত হওয়া উচিত",
        "ru": "подлежат проверке квалифицированным специалистом",
        "pt": "devem ser revistos por um profissional qualificado",
        "id": "harus ditinjau oleh profesional yang berkualifikasi",
        "ja": "有資格の専門家による検討が必要です",
        "hi": "किसी योग्य पेशेवर द्वारा समीक्षित किए जाने हेतु",
    }
    assert set(stale_substrings) == set(UI_LANGS), "every UI language must be covered"
    for lang, stale in stale_substrings.items():
        note = documents_payload(lang)["ui"]["draft_note"]
        assert stale not in note, f"{lang}: draft_note reverted to the stale pending-review wording"
        # And it must still be present (not silently emptied) with the honest,
        # permanent framing -- never reviewed, by deliberate choice.
        assert note.strip()


def test_no_document_carries_an_unresolved_completer_verifier_bracket():
    """Field report 2026-07-17: the legal review/acceptance screen still showed
    "[À COMPLÉTER]" / "[À VÉRIFIER]" bracket markers -- both the META-EXPLANATORY
    sentence in every document's intro ("the bracketed mentions [À COMPLÉTER: ...]
    and [À VÉRIFIER: ...] flag information deliberately left as-is...", present in
    ALL 12 languages) and a genuinely dangling placeholder in MENTIONS_LEGALES.md
    about SIREN/SIRET/VAT registration (also in all 12 languages) that the
    maintainer wants removed outright, since the preceding sentence ("not
    applicable -- the Publisher acts in a non-professional capacity") already
    states the complete, current legal reality with nothing left open.

    Pins the fix across every UI language via documents_payload (the same access
    path the app itself uses) -- so a future translation update or new document
    can never silently reintroduce this convention. IMPLEMENTATION_NOTES.md (a
    maintainer-facing historical record, never served to a user) is deliberately
    NOT covered here -- it correctly documents that a DIFFERENT bracket type
    [À VÉRIFIER: article numbers] was resolved in the past, which is accurate
    history, not a live placeholder."""
    from src.legal.documents import UI_LANGS, documents_payload

    for lang in (*UI_LANGS, "fr"):
        p = documents_payload(lang)
        for doc in p["documents"]:
            assert "À COMPLÉTER" not in doc["markdown"], (
                f"{lang}/{doc['title']}: an unresolved [À COMPLÉTER] bracket remains"
            )
            assert "À VÉRIFIER" not in doc["markdown"], (
                f"{lang}/{doc['title']}: an unresolved [À VÉRIFIER] bracket remains"
            )


def test_unlock_first_launch_inserts_legal_step_before_passphrase():
    """The first-launch flow goes language -> ACCEPT LEGAL -> passphrase; decline needs
    a typed confirmation and uninstalls. Browser-unverified; this pins the wiring."""
    html = (_ROOT / "src" / "static" / "unlock.html").read_text(encoding="utf-8")
    assert 'id="view-legal"' in html
    # the language choice routes THROUGH the legal step (not straight to the passphrase)
    assert "showLegalStep(code)" in html
    # the four legal endpoints are used
    for ep in ("/api/legal/documents", "/api/legal/consent", "/api/legal/decline", "/api/legal/download"):
        assert ep in html, f"unlock.html must use {ep}"
    # the destructive decline requires a typed confirmation (never a bare click)
    assert 'id="lg-decline-confirm"' in html and "_legalWord" in html
    # accept records consent then advances to the passphrase view (never bypassing it)
    assert "legalToPassphrase(" in html
