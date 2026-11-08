"""The custody "keys:" pill's hover says what the key files hold, for each value the signer reports (R484 (3)).

Before, one hover told every install to "Set OO_KEY_PASSPHRASE to encrypt keys at rest": wrong on an
install whose keys ARE encrypted, and wrong on one encrypted by the database passphrase, which wraps
the signing keys too (``src.custody.signing._passphrase``). Now ``_KEY_PROTECTION_TIPS`` in
``src/static/app-ai-tools.js`` holds one English hover per value of ``HybridSigner.key_protection``, and
the i18n engine translates a ``title`` by its English text, so each one is keyed in the 12 locales.

What these pin: the map names exactly the values the signer can return (a new value without a hover,
or a hover for a value that no longer exists, fails here); each hover is keyed and translated in every
locale and keeps the names a reader types or looks up; the two encrypted values state the at-rest threat
model, and the two warning values say when the app cannot fix the file itself; the old instruction is
gone; and the pill gets no ``title`` at all for a value with no entry, rather than a wrong one.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from tests.js_source_helper import app_js, function_body, object_literal

_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"
_SIGNING = _ROOT / "src" / "custody" / "signing.py"
_OLD = "Set OO_KEY_PASSPHRASE to encrypt keys at rest"

# The names a hover must carry through translation: a reader types the variable, and the
# algorithms and the file mode are what they would look up.
_KEEP = {
    "aes256gcm-scrypt": ("scrypt", "AES-256-GCM"),
    "pkcs8-pbkdf2": ("PKCS8", "PBKDF2"),
    "plaintext-0600": ("0600", "OO_KEY_PASSPHRASE"),
}


def _tips() -> dict[str, str]:
    """The JS map, read as data: its block, with each ``"a" + "b"`` concatenation joined."""
    block = re.sub(r'"\s*\+\s*"', "", object_literal(app_js(), "_KEY_PROTECTION_TIPS"))
    tips = dict(re.findall(r'"([a-z0-9-]+)":\s*"([^"]*)"', block))
    assert tips, "no entry parsed out of _KEY_PROTECTION_TIPS"
    return tips


def _signer_values() -> set[str]:
    """Every string ``HybridSigner.key_protection`` can return, read from its own source."""
    tree = ast.parse(_SIGNING.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "key_protection":
            returns = [r for r in ast.walk(node) if isinstance(r, ast.Return)]
            assert returns and all(
                isinstance(r.value, ast.Constant) and isinstance(r.value.value, str)
                for r in returns
            ), "key_protection returns something other than a string constant"
            return {
                r.value.value
                for r in returns
                if isinstance(r.value, ast.Constant) and isinstance(r.value.value, str)
            }
    raise AssertionError("HybridSigner.key_protection is gone")


def test_the_map_names_exactly_the_values_the_signer_reports():
    assert set(_tips()) == _signer_values() == set(_KEEP)


def test_every_hover_is_keyed_and_translated_in_all_twelve_locales():
    tips = _tips()
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12
    wrong: list[str] = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for value, english in tips.items():
            text = str(data.get(english, "")).strip()
            if not text:
                wrong.append(f"{path.name}: {value} is not keyed")
                continue
            if path.stem != "en" and text == english:
                wrong.append(f"{path.name}: {value} is still the English")
            if path.stem == "en" and text != english:
                wrong.append(f"en.json: {value} differs from its key")
            for name in _KEEP[value]:
                if name not in text:
                    wrong.append(f"{path.name}: {value} lost {name!r}")
    assert not wrong, "\n".join(wrong)


def test_the_hovers_name_both_passphrases_the_threat_model_and_the_stuck_case():
    tips = _tips()
    # The database passphrase wraps the keys too, so the plaintext hover may not name only the variable.
    assert "database passphrase" in tips["plaintext-0600"]
    # The at-rest threat model is stated wherever encryption is shown (CLAUDE.md non-negotiables).
    for value in ("aes256gcm-scrypt", "pkcs8-pbkdf2"):
        assert "never a compromised running session" in tips[value], value
    # The older form is a warning because it is cheap to guess against; the hover says so.
    assert "costs far less to guess against" in tips["pkcs8-pbkdf2"]
    # keyfile.replace_in_place stands down when the file cannot be replaced, and each load tries again:
    # both warning hovers name that case rather than promising the next load fixes it.
    for value in ("pkcs8-pbkdf2", "plaintext-0600"):
        assert "a read-only folder, or a linked file" in tips[value], value
    # The value describes the keys in use, never every file under keys/ (docs/SECURITY.md stated limit).
    assert tips["aes256gcm-scrypt"].startswith("The signing keys in use ")


def test_the_old_instruction_is_gone():
    assert _OLD not in app_js()
    for path in sorted(_LOCALES.glob("*.json")):
        assert _OLD not in json.loads(path.read_text(encoding="utf-8")), path.name


def test_a_value_with_no_entry_gets_no_title():
    body = function_body(app_js(), "renderCustodyStatus")
    assert "Object.prototype.hasOwnProperty.call(_KEY_PROTECTION_TIPS, s.key_protection)" in body
    assert '(keyTip ? ` title="${esc(keyTip)}"` : "")' in body
    assert 'title="Set' not in body
