"""Every error the first-launch / unlock screen can show ships x12 locales.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS SURFACE SPECIFICALLY. The non-negotiables require every consent/caveat
string to ship in all 12 locales. The unlock screen is where that matters most:
it is the first screen a new user sees, it is where they choose a passphrase,
and it is the screen that tells them THERE IS NO RECOVERY. An operator who
fat-fingers the confirmation there and is answered in a language they do not
read is being asked to make the single most irreversible decision in the product
without the explanation.

The mechanism was already in place -- unlock.html runs the backend's `detail`
through t() precisely so these render in the chosen language. Only the keys were
missing, so six of the seven fell back to English everywhere. This test is what
stops the seventh from being added without them.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"
_UNLOCK_PY = _ROOT / "src" / "api" / "unlock.py"


def _detail_strings() -> set[str]:
    """Every literal `detail=` on an HTTPException raised in unlock.py.

    Parsed with ast, not grep: the longest of these is written as two adjacent
    string literals, which the parser folds and a line-oriented regex splits in
    half -- and half a key matches nothing at runtime.
    """
    tree = ast.parse(_UNLOCK_PY.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "detail" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str) and len(kw.value.value) > 6:
                    out.add(kw.value.value)
    return out


def test_the_unlock_screen_has_errors_worth_translating() -> None:
    """Guard the guard: if the extraction silently stopped finding anything, every
    assertion below would pass over an empty set."""
    found = _detail_strings()
    assert len(found) >= 6, f"expected the unlock error set, extracted {found}"
    assert "passphrases do not match" in found


def test_every_unlock_error_is_keyed_in_english() -> None:
    en = json.loads((_LOCALES / "en.json").read_text(encoding="utf-8"))
    missing = sorted(s for s in _detail_strings() if s not in en)
    assert not missing, (
        "unlock.html renders these through t(), so a string with no en.json key is "
        "English in all 11 other locales on the no-recovery screen: " + repr(missing)
    )


def test_every_unlock_error_is_translated_in_all_twelve_locales() -> None:
    details = _detail_strings()
    gaps: list[str] = []
    for path in sorted(_LOCALES.glob("*.json")):
        if path.stem == "en":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in details:
            value = data.get(s)
            if not value or not str(value).strip():
                gaps.append(f"{path.stem}: {s[:60]}")
    assert not gaps, "untranslated unlock errors: " + "; ".join(sorted(gaps))


def test_the_no_recovery_consent_error_survives_string_folding() -> None:
    """The consent message is the one that matters most and the one most easily
    broken: it is written as two adjacent literals in the source. If a future edit
    reflows it, the key changes and every locale silently falls back to English --
    with no test failure anywhere unless this one exists."""
    details = _detail_strings()
    consent = [s for s in details if s.startswith("explicit consent required")]
    assert len(consent) == 1, f"expected exactly one consent detail, got {consent}"
    assert "no recovery" in consent[0] and "decryption alternative" in consent[0], (
        "the folded halves must both be present in the key that is looked up"
    )
    en = json.loads((_LOCALES / "en.json").read_text(encoding="utf-8"))
    assert consent[0] in en
