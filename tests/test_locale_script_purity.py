"""No locale string may spell one word in two scripts.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``hi.json``'s ``"mentions"`` read ``उল्लेख`` — six characters, of which the second was
U+09B2 BENGALI LETTER LA inside an otherwise Devanagari word, while the SAME word is
spelled correctly in thirty-nine other keys of the same file. It rendered on every Hindi
surface that counts anything, for as long as the key has existed.

Nothing could catch it. ``--min 100`` counts keys, so a present-but-wrong value is a
complete locale. The unkeyed-``t()`` ratchet asks whether a key exists. A human reviewer
reads a script they do not know. And a spell-checker is not available here for eleven
languages. What IS decidable, mechanically and with no language knowledge at all, is that
a single word must not mix two writing systems — one character from the neighbouring
block is a typo or a bad paste, never a word.

DELIBERATELY NARROW, so the rule is one a future session can trust rather than silence:

* Per TOKEN, never per string. A sentence may legitimately hold a Latin brand, an
  acronym, a number, or — as ``ar.json`` does on purpose — the example
  ``USA / США / EUA``.
* The shared Indic DANDA (U+0964/U+0965) belongs to both Devanagari and Bengali and is
  not evidence of a mix.
* Only the four blocks where a neighbour-key slip is plausible and invisible to a Latin
  reader. Latin is excluded entirely: it turns up inside every language's tokens for
  good reasons.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_LOCALES = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"

# Shared between Devanagari and Bengali (and other Indic scripts): a full stop, not a
# letter, and its presence in a Bengali token says nothing about the token's script.
_SHARED = {0x0964, 0x0965}
_BLOCKS = (
    ("Devanagari", 0x0900, 0x097F),
    ("Bengali", 0x0980, 0x09FF),
    ("Arabic", 0x0600, 0x06FF),
    ("Cyrillic", 0x0400, 0x04FF),
)


def _script(ch: str) -> str | None:
    o = ord(ch)
    if o in _SHARED:
        return None
    for name, lo, hi in _BLOCKS:
        if lo <= o <= hi:
            return name
    return None


def _mixed_tokens(value: str) -> list[tuple[str, list[str]]]:
    out: list[tuple[str, list[str]]] = []
    for token in re.split(r"[\s ]+", value):
        scripts = sorted({s for s in (_script(c) for c in token) if s})
        if len(scripts) > 1:
            out.append((token, scripts))
    return out


def test_no_locale_word_is_spelled_in_two_scripts() -> None:
    offenders: list[str] = []
    for path in sorted(_LOCALES.glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        for key, value in table.items():
            if not isinstance(value, str):
                continue
            for token, scripts in _mixed_tokens(value):
                codes = " ".join(f"{c}=U+{ord(c):04X}" for c in token)
                offenders.append(
                    f"{path.name}[{key[:50]!r}] token {token!r} mixes {scripts}: {codes}"
                )
    assert not offenders, (
        "a locale string spells one word in two writing systems, which renders as a "
        "misspelling to every reader of that language and to no reviewer who does not "
        "read it:\n  " + "\n  ".join(offenders)
    )


def test_the_detector_finds_the_defect_it_was_written_for() -> None:
    """Otherwise the test above passes because the rule never fires.

    The exact string that shipped: `उल्लेख` with U+09B2 BENGALI LETTER LA in place of
    U+0932 DEVANAGARI LETTER LA.
    """
    broken = "उল्लेख"
    assert _mixed_tokens(broken) == [(broken, ["Bengali", "Devanagari"])]
    # ...and the corrected word, which is what `hi.json` now carries, is clean.
    assert _mixed_tokens("उल्लेख") == []
    # A sentence that mixes scripts ACROSS tokens is fine and must not be flagged --
    # `ar.json` carries `USA / США / EUA` as a deliberate example of exactly that.
    assert _mixed_tokens("الكيانات USA / США") == []
    # The Bengali danda is shared punctuation, not a Devanagari intrusion.
    assert _mixed_tokens("বিশ্ব।") == []
