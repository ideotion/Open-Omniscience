"""A stopword file named for a language must not silently hold another script.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``global_stopwords()`` unions every ``configs/stopwords_extra/*.yml`` file
LANGUAGE-AGNOSTICALLY, so a word in the wrong file is filtered exactly as if it were in
the right one -- the split is a readability convenience, and the loader's own docstring
says so. That is precisely why misfiling is easy to do and hard to notice: nothing
behaves differently, and the only cost is that **a filename becomes false about its
contents**.

It has already cost a measurement. The 2026-09-05 keyword-translation research pass read
``_multilingual.yml`` alone, reported that the month stoplist covered "exactly two of the
twelve UI languages", and was wrong by five -- because the Spanish, German and Russian
month names were sitting in a file called ``hi.yml``. Auditing the rest then found a
second block: 61 Polish/Hungarian/Danish/BCS function words in ``ru.yml``. Both were
re-filed into ``_multilingual.yml`` (set-identical; the digest test in
``test_analytics_extract.py`` proves it). This guard is what stops the class regrowing.

HONEST REACH -- stated because the test cannot deliver more than this. A script check can
only separate scripts. It catches a Cyrillic word in ``hi.yml`` and a Latin word in
``ru.yml``; it can say NOTHING about Polish sitting in ``en.yml``, because Polish and
English are the same script. The Latin-script half of this class stays uncaught, and no
assertion here should be read as covering it.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest
import yaml

_DIR = Path(__file__).resolve().parents[1] / "configs" / "stopwords_extra"

#: Files named for a language whose script is NOT Latin. The value is the unicodedata
#: name prefix every alphabetic character in that file must carry. Only these can be
#: checked -- a Latin-script file is unguardable by this mechanism (see the module
#: docstring), and listing one here would claim a coverage the check does not have.
_NON_LATIN_FILES = {
    "ar.yml": ("ARABIC",),
    "bg.yml": ("CYRILLIC",),
    "bn.yml": ("BENGALI",),
    "el.yml": ("GREEK",),
    "hi.yml": ("DEVANAGARI",),
    "ko.yml": ("HANGUL",),
    "mr.yml": ("DEVANAGARI",),
    "ru.yml": ("CYRILLIC",),
    "uk.yml": ("CYRILLIC",),
}

#: Deliberately unchecked, with the reason. ``_multilingual.yml`` is the ONE file whose
#: name is true of a mixed-script block -- it is where a misfiled block is re-filed TO,
#: so guarding it would forbid the fix. ``sr.yml`` is Serbian, which is genuinely written
#: in both Cyrillic and Latin (the file is currently all-Latin, which is legitimate).
_UNCHECKED = {"_multilingual.yml": "the mixed-language file by design", "sr.yml": "Serbian is digraphic"}


def _words(path: Path) -> list[str]:
    data = yaml.safe_load(path.read_text("utf-8")) or {}
    return [str(w) for w in (data.get("stopwords") or [])]


def _scripts(word: str) -> set[str]:
    """The unicodedata script-name prefixes of a word's ALPHABETIC characters.

    Digits, hyphens and apostrophes carry no script and are ignored, so ``font-size``
    and ``don't`` are judged on their letters alone.
    """
    out: set[str] = set()
    for ch in word:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        out.add(name.split(" ")[0] if name else "UNNAMED")
    return out


@pytest.mark.parametrize("filename", sorted(_NON_LATIN_FILES))
def test_a_non_latin_language_file_holds_only_its_own_script(filename: str) -> None:
    """Every alphabetic character in these files belongs to that language's script.

    A failure means a block was filed under a language it does not belong to. The fix is
    to MOVE it (to ``_multilingual.yml`` when it spans languages, per PROVENANCE.md) --
    never to relax this list, and never to delete the words, which would change the union
    and redden the byte-identity digest.
    """
    path = _DIR / filename
    assert path.exists(), f"{filename} is listed here but missing from {_DIR}"
    allowed = set(_NON_LATIN_FILES[filename])
    offenders = [w for w in _words(path) if _scripts(w) - allowed]
    assert not offenders, (
        f"{filename} is named for a {'/'.join(sorted(allowed)).title()}-script language but "
        f"holds {len(offenders)} entr{'y' if len(offenders) == 1 else 'ies'} in another "
        f"script: {offenders[:12]}{' …' if len(offenders) > 12 else ''}. "
        f"Move them (see configs/stopwords_extra/PROVENANCE.md, "
        f"'Re-filing the two misfiled blocks') rather than deleting them or widening this test."
    )


def test_the_guard_covers_every_non_latin_file_that_exists() -> None:
    """A new non-Latin-script language file must join the checked set, not slip past it.

    Without this, adding ``fa.yml`` or ``he.yml`` would leave the new file unguarded while
    every existing assertion still passed -- a guard that silently stops growing with the
    directory. Latin-script files are exempt BY MECHANISM (a script check cannot read
    them), which is why the assertion is about non-Latin files only.
    """
    seen: dict[str, set[str]] = {}
    for path in sorted(_DIR.glob("*.yml")):
        if path.name in _NON_LATIN_FILES or path.name in _UNCHECKED:
            continue
        scripts: set[str] = set()
        for word in _words(path):
            scripts |= _scripts(word)
        if scripts - {"LATIN"}:
            seen[path.name] = scripts
    assert not seen, (
        f"these files carry a non-Latin script but are not in _NON_LATIN_FILES: {seen}. "
        f"Either the file is named for a non-Latin language (add it, with its script) or a "
        f"foreign block was misfiled into a Latin-script file (move it to _multilingual.yml)."
    )


def test_the_re_filed_blocks_are_still_present_in_the_union() -> None:
    """The 2026-09-05 move was a MOVE: the words must still be filtered, from their new home.

    The digest test in ``test_analytics_extract.py`` proves the whole union is unchanged;
    this one names the specific words, so a future "cleanup" that deletes them instead of
    re-filing them fails HERE with the reason attached rather than only as a hash mismatch.
    """
    from src.analytics.extract import global_stopwords

    gs = global_stopwords()
    for word in ("abril", "märz", "января", "enero", "augustus"):  # ex-hi.yml months
        assert word in gs, f"{word!r} left the union — the 2026-09-05 re-filing was a move, not a delete"
    for word in ("aby", "ahogy", "ikke", "pročitajte", "roku"):  # ex-ru.yml function words
        assert word in gs, f"{word!r} left the union — the 2026-09-05 re-filing was a move, not a delete"

    multilingual = set(_words(_DIR / "_multilingual.yml"))
    assert {"abril", "января", "aby", "ikke"} <= multilingual, (
        "the re-filed blocks are expected in _multilingual.yml"
    )
