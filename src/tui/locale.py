"""The terminal panel's words, in the language the person chose (OPEN_QUEUE item 39; R600, R658).

The browser UI translates through ``OOI18N`` (``src/static/i18n.js``); the terminal panel runs with the browser closed, so it reads the
SAME locale files (``src/static/locales/<code>.json``, one ``{"English text": "translation"}`` table per language) from Python. The
English text is the key, as in the browser, so a string the table does not carry is shown in English, never as a blank or a key name.

WHICH LANGUAGE (:func:`choose`). In order: ``OO_PANEL_LANG`` when it names a locale file; the interface language the browser last
reported to the server (S05-08 stores it; the panel reads it over loopback, so a locked or silent app simply has none); the terminal's
own locale (``LC_ALL``, ``LC_MESSAGES``, ``LANG``); English.

RIGHT-TO-LEFT SCRIPTS STAY IN ENGLISH. curses draws characters one cell after the other, left to right, and does no shaping: Arabic would
come out as isolated letters in reversed reading order, which is worse than not translating. A locale whose ``_meta.dir`` is ``rtl`` is
therefore shown in English, and :func:`choose` returns the one line that says so (in English, since that is what the panel can draw).

WIDTHS. A terminal gives CJK characters two cells and combining marks none, so lengths are measured in cells (:func:`cols`), not in
characters, wherever the panel lines things up or cuts them to the width.

Standard library only, like the panel: it imports nothing from the app.
"""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parents[1] / "static" / "locales"
DEFAULT = "en"
#: The line the log starts with when the chosen language is written right to left. English on purpose: it is what the panel can draw.
RTL_NOTE = (
    "This terminal cannot draw {name} in its right-to-left order, so the panel is in English. "
    "The browser UI is in {name}."
)
_CODE = re.compile(r"^[a-z]{2,3}$")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_PLURAL_MARK = re.compile(r"\[(zero|one|two|few|many|other)\]")
# Grouping spaces and the bidi isolates and marks a count may be wrapped in are not part of the number (as in i18n.js).
_PLURAL_STRIP = re.compile(r"[\s\u00a0\u202f\u2066-\u2069\u200e\u200f\u061c]")
# Only plain ASCII digits are a number here, exactly as in i18n.js (float() would also take "1_1" or "١").
_PLURAL_NUMBER = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?")


def _plural_forms(value: str) -> dict[str, str] | None:
    """The forms of a plural value ("[one]...[few]...[other]..."), as the browser's i18n.js reads them; None for a plain value."""
    if not value.startswith("["):
        return None
    parts = _PLURAL_MARK.split(value)
    if parts[0] != "" or len(parts) < 3:
        return None
    forms = dict(zip(parts[1::2], parts[2::2], strict=True))
    return forms if "other" in forms else None


def _plural_fallback(code: str, forms: dict[str, str]) -> str:
    """The form for a value with no number: the one the language uses for 5, the plain plural of a whole count (Russian
    [other] is the fraction form), exactly as the browser's i18n.js chooses."""
    return forms.get(plural_category(code, 5), forms["other"])


def plural_category(code: str, x: float) -> str:
    """The CLDR plural category of ``x`` in language ``code``: the browser uses Intl.PluralRules, the terminal these rules
    (cardinal, CLDR 44) for the twelve app languages. A fraction takes the language's fractional category."""
    if not math.isfinite(x):
        return "other"
    whole = float(x).is_integer()
    i = int(abs(x)) if whole else None
    if code == "ru":
        if i is None:
            return "other"
        if i % 10 == 1 and i % 100 != 11:
            return "one"
        if 2 <= i % 10 <= 4 and not 12 <= i % 100 <= 14:
            return "few"
        return "many"
    if code == "ar":
        if i is None:
            return "other"
        if i == 0:
            return "zero"
        if i == 1:
            return "one"
        if i == 2:
            return "two"
        if 3 <= i % 100 <= 10:
            return "few"
        if 11 <= i % 100 <= 99:
            return "many"
        return "other"
    if code in ("ja", "zh", "id"):
        return "other"
    if code in ("fr", "pt"):
        return "one" if int(abs(x)) in (0, 1) else "other"
    if code in ("hi", "bn"):
        return "one" if int(abs(x)) == 0 or x == 1 else "other"
    return "one" if x == 1 and whole else "other"


def _code(raw: str | None) -> str | None:
    """``fr_FR.UTF-8`` / ``pt-BR`` / ``ZH`` -> ``fr`` / ``pt`` / ``zh``; None for anything that is not a plain language code
    (``C``, ``POSIX``, empty)."""
    if not raw:
        return None
    c = re.split(r"[_.@-]", raw.strip(), maxsplit=1)[0].lower()
    return c if _CODE.match(c) and c not in ("c",) else None


def available() -> set[str]:
    """The language codes a locale file exists for."""
    try:
        return {p.stem for p in LOCALES_DIR.glob("*.json") if _CODE.match(p.stem)}
    except OSError:
        return {DEFAULT}


def _read(code: str) -> dict:
    try:
        data = json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class Translator:
    """One language's table. ``t`` returns the translation of an English string, or the English itself when the table has none."""

    def __init__(self, code: str = DEFAULT, table: Mapping[str, object] | None = None) -> None:
        self.code = code
        self._table = {
            k: v
            for k, v in (table or {}).items()
            if isinstance(v, str) and v and not k.startswith("_")
        }

    def t(self, text: str) -> str:
        value = self._table.get(text, text)
        forms = _plural_forms(value)
        return value if forms is None else _plural_fallback(self.code, forms)

    def tf(self, text: str, **values: object) -> str:
        """``t`` then ``{name}`` filled from ``values``. A placeholder with no value is left as written, as in the browser's ``tf``;
        never ``str.format``, so a brace in a translation or in a value (a host name, a job label) cannot raise."""
        out = self._table.get(text, text)
        forms = _plural_forms(out)
        if forms is not None:
            out = _plural_fallback(self.code, forms)
            name = (
                "n"
                if "n" in values
                else "count"
                if "count" in values
                else next(iter(_PLACEHOLDER.findall(text)), None)
            )
            try:
                raw = (
                    _PLURAL_STRIP.sub("", str(values[name]))
                    if name is not None and name in values
                    else ""
                )
                x = float(raw) if _PLURAL_NUMBER.fullmatch(raw) else None
            except (TypeError, ValueError):
                x = None
            if x is not None and math.isfinite(x):
                out = forms.get(plural_category(self.code, x), forms["other"])
        return _PLACEHOLDER.sub(
            lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), out
        )


def load(code: str | None) -> tuple[Translator, str | None]:
    """The translator for ``code`` and, when it had to fall back to English for a right-to-left language, the line saying so."""
    c = _code(code) or DEFAULT
    if c == DEFAULT or c not in available():
        return Translator(DEFAULT), None
    data = _read(c)
    raw_meta = data.get("_meta")
    meta: dict = raw_meta if isinstance(raw_meta, dict) else {}
    if str(meta.get("dir") or "").lower() == "rtl":
        name = str(_read(DEFAULT).get(str(meta.get("name") or ""), "") or meta.get("name") or c)
        return Translator(DEFAULT), RTL_NOTE.format(name=name)
    if not data:
        return Translator(DEFAULT), None
    return Translator(c, data), None


def terminal_code(env: Mapping[str, str] | None = None) -> str | None:
    """The language of the terminal's own locale, the way POSIX ranks the variables (the first one set wins)."""
    env = os.environ if env is None else env
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if env.get(name):
            return _code(env[name])
    return None


def choose(
    reported: str | None, env: Mapping[str, str] | None = None
) -> tuple[Translator, str | None]:
    """The panel's language: ``OO_PANEL_LANG``, else what the browser reported, else the terminal's locale, else English. A code no
    locale file exists for is passed over, not shown as English while a later source names a language the panel has."""
    env = os.environ if env is None else env
    have = available()
    for cand in (_code(env.get("OO_PANEL_LANG")), _code(reported), terminal_code(env)):
        if cand and (cand == DEFAULT or cand in have):
            return load(cand)
    return load(DEFAULT)


# --------------------------------------------------------------------------- widths, in terminal cells


def char_cols(ch: str) -> int:
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def cols(text: str) -> int:
    """How many terminal cells ``text`` takes."""
    return sum(char_cols(ch) for ch in text)


def clip(text: str, width: int) -> str:
    """The longest start of ``text`` that fits in ``width`` cells (a wide character that would straddle the edge is left out)."""
    if width <= 0:
        return ""
    used = 0
    for i, ch in enumerate(text):
        w = char_cols(ch)
        if used + w > width:
            return text[:i]
        used += w
    return text


def pad(text: str, width: int) -> str:
    """``text`` clipped to ``width`` cells and padded with spaces to exactly that many."""
    out = clip(text, width)
    return out + " " * max(width - cols(out), 0)
