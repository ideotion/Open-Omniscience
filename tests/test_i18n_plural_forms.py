"""Plural forms in the locale files (2026-11-14).

A translation may hold one form per CLDR plural category, "[one]...[few]...[other]...", so a count
agrees with its noun in Russian (four categories) and Arabic (six) and not only in the languages whose
one/many pair the app always assumed. The browser picks the form with ``Intl.PluralRules``
(tests/i18n_plural_node_test.js runs the shipped i18n.js); the terminal panel reads the same files
through ``src/tui/locale.py``. This file pins the format every locale value must keep:

- only the categories CLDR defines for that language, and ``[other]`` always present;
- every form carries exactly the key's placeholders, so a form can never drop or invent a value;
- the terminal's own rules choose the same category as the browser's ``Intl.PluralRules``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tui.locale import Translator, plural_category

_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"
_MARK = re.compile(r"\[(zero|one|two|few|many|other)\]")
_HOLE = re.compile(r"\{(\w+)\}")

# CLDR cardinal categories per app language (CLDR 44). French, Spanish, Portuguese and Italian
# gained "many" for large round numbers; a file may use any subset that includes "other".
_CATEGORIES = {
    "ar": {"zero", "one", "two", "few", "many", "other"},
    "ru": {"one", "few", "many", "other"},
    "fr": {"one", "many", "other"},
    "es": {"one", "many", "other"},
    "pt": {"one", "many", "other"},
    "de": {"one", "other"},
    "en": {"one", "other"},
    "hi": {"one", "other"},
    "bn": {"one", "other"},
    "id": {"other"},
    "ja": {"other"},
    "zh": {"other"},
}


def _plural_values():
    for path in sorted(_LOCALES.glob("*.json")):
        lang = path.stem
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, value in data.items():
            if isinstance(value, str) and value.startswith("[") and _MARK.match(value):
                yield lang, key, value


def test_every_language_has_its_cldr_categories_listed():
    assert {p.stem for p in _LOCALES.glob("*.json")} <= set(_CATEGORIES)


def test_plural_values_are_well_formed():
    bad = []
    for lang, key, value in _plural_values():
        parts = _MARK.split(value)
        cats = parts[1::2]
        forms = parts[2::2]
        holes = set(_HOLE.findall(key))
        if parts[0] != "":
            bad.append((lang, key, "text before the first marker"))
        if "other" not in cats:
            bad.append((lang, key, "no [other] form"))
        if len(set(cats)) != len(cats):
            bad.append((lang, key, "a category twice"))
        if not set(cats) <= _CATEGORIES[lang]:
            bad.append(
                (lang, key, f"categories {sorted(set(cats) - _CATEGORIES[lang])} are not {lang}'s")
            )
        for cat, form in zip(cats, forms, strict=True):
            if set(_HOLE.findall(form)) != holes:
                bad.append((lang, key, f"[{cat}] placeholders differ from the key's"))
            if not form.strip():
                bad.append((lang, key, f"[{cat}] is empty"))
    assert not bad, bad


def test_terminal_translator_chooses_the_form():
    ru = Translator(
        "ru",
        {
            "{n} sources": "[one]{n} источник[few]{n} источника[many]{n} источников[other]{n} источника"
        },
    )
    assert ru.tf("{n} sources", n=1) == "1 источник"
    assert ru.tf("{n} sources", n=3) == "3 источника"
    assert ru.tf("{n} sources", n=11) == "11 источников"
    assert ru.tf("{n} sources", n=21) == "21 источник"
    assert ru.tf("{n} sources", n="many") == "many источника"  # not a number: [other]
    assert ru.t("{n} sources") == "{n} источника"  # no number: [other], never the markers
    plain = Translator("ru", {"{n} selected": "Выбрано: {n}"})
    assert plain.tf("{n} selected", n=5) == "Выбрано: 5"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_browser_plural_selection_node_suite():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "i18n_plural_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_terminal_rules_match_the_browsers_intl_plural_rules():
    numbers = list(range(0, 230)) + [1000, 1001, 1002, 1011, 100000, 1.5, 0.5, 2.25]
    script = (
        "const out = {};"
        f"for (const l of {json.dumps(sorted(_CATEGORIES))}) {{"
        "  const r = new Intl.PluralRules(l);"
        f"  out[l] = {json.dumps(numbers)}.map((x) => r.select(x));"
        "}"
        "console.log(JSON.stringify(out));"
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    browser = json.loads(proc.stdout)
    # Only the languages whose files may hold plural values must agree exactly; elsewhere the
    # terminal's one/other is a fallback the browser refines with "many" for round millions.
    for lang in ("ru", "ar"):
        mine = [plural_category(lang, x) for x in numbers]
        assert mine == browser[lang], lang
