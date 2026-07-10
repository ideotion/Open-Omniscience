"""Optional word segmentation for space-less scripts (zh / ja / th).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

License-clean, pure-local, OFFLINE segmenters behind the optional ``[segmentation]``
extra (a core install never needs them):

  * jieba (MIT)                    -> Chinese  (zh) — ``tokenize`` yields (word, start, end)
  * janome (Apache-2.0, dict)      -> Japanese (ja) — surface tokens, offsets reconstructed
  * pythainlp newmm (Apache-2.0)   -> Thai     (th) — word list, offsets reconstructed

WHY. Without segmentation the whitespace tokenizer (``extract._WORD_RE``) sees a whole
zh/ja sentence as ONE giant "word" and shatters a Thai run at its combining marks, so
zh/ja/th minted tens of thousands of junk keywords (field test 2026-07-08: zh 46k +
th 21k + ja 12k junk; Heaps beta ~= 0.95; pruning finds no orphans — segmentation is the
ONLY lever). These languages were therefore honestly reported ``unsegmented``.

GRACEFUL DEGRADE BY CONSTRUCTION. When the extra is absent, :func:`segmenter_available`
is ``False`` for every language and :func:`segment` returns ``None``, so the extractor
keeps its byte-identical whitespace/mark tokenization and the languages stay
``unsegmented`` — a core install is unchanged.

NO NETWORK. Every segmenter tokenizes over a dictionary bundled INSIDE its wheel; no
model is fetched, ever. ``OO_SEGMENTATION=0`` disables the whole layer (a kill switch
mirroring ``OO_FAMILY_LEMMA``).
"""

from __future__ import annotations

import os
from functools import lru_cache

# The space-less scripts a word segmenter can rescue. Kept as a literal here (mirrors
# managed.UNSEGMENTED) so there is no import cycle managed <-> segmentation.
SEGMENTED_LANGUAGES: frozenset[str] = frozenset({"zh", "ja", "th"})


def _enabled() -> bool:
    return os.getenv("OO_SEGMENTATION", "1") != "0"


def _norm(language: str) -> str:
    # Bare ISO-639-1 code: 'zh-CN'/'zh_Hans'/'ZH' -> 'zh'. Mirrors managed.normalize_lang
    # (inlined to avoid an import cycle) so segment()/segmenter_available() agree with
    # managed.language_status(), which normalizes — a region/script subtag must NOT make
    # the status say 'functional' while extraction silently skips segmentation.
    if not language:
        return ""
    return language.strip().lower().replace("_", "-").split("-")[0]


@lru_cache(maxsize=1)
def _importable() -> dict[str, bool]:
    """Which segmenter packages are IMPORTABLE — lightweight, loads no dictionary.

    Importing the package does not build jieba's prefix dict / janome's system
    dictionary / pythainlp's newmm trie (those load lazily on first tokenize), so this
    stays cheap enough to call from a status/gating check.
    """
    out: dict[str, bool] = {}
    for lang, mod in (("zh", "jieba"), ("ja", "janome"), ("th", "pythainlp")):
        try:
            __import__(mod)
            out[lang] = True
        except Exception:  # noqa: BLE001 - a core install simply has no segmenter
            out[lang] = False
    return out


def segmenter_available(language: str) -> bool:
    """True when an offline word segmenter is installed for this language."""
    if not _enabled():
        return False
    return _importable().get(_norm(language), False)


@lru_cache(maxsize=1)
def _jieba():
    try:
        import jieba

        jieba.setLogLevel(60)  # silence the "Building prefix dict …" chatter
        jieba.initialize()  # build the prefix dict once (this process)
        return jieba
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=1)
def _janome():
    try:
        from janome.tokenizer import Tokenizer

        return Tokenizer(wakati=True)  # surface strings only (we do not need POS)
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=1)
def _pythainlp():
    try:
        from pythainlp.tokenize import word_tokenize

        word_tokenize("ทดสอบ", engine="newmm")  # warm the newmm trie once
        return word_tokenize
    except Exception:  # noqa: BLE001
        return None


def _has_letter(tok: str) -> bool:
    # CJK ideographs and Thai consonants are alphabetic; punctuation / whitespace /
    # pure-digit tokens are not — the same class the Latin _WORD_RE keeps.
    return any(ch.isalpha() for ch in tok)


def segment(text: str, language: str) -> list[tuple[str, int]] | None:
    """Return ``[(word, char_offset), ...]`` for a space-less script, else ``None``.

    ``None`` means "not segmentable here" — the caller MUST fall back to its default
    tokenizer (byte-identical behaviour). Only word-ish tokens (>= 1 letter) are
    returned; punctuation / whitespace / pure-number tokens are dropped, matching what
    the Latin ``_WORD_RE`` would have kept. Offsets index into ``text`` (character
    positions) so the surrounding sentence can still be sliced for provenance.
    """
    language = _norm(language)
    if not _enabled() or not text or language not in SEGMENTED_LANGUAGES:
        return None
    try:
        if language == "zh":
            eng = _jieba()
            if eng is None:
                return None
            # jieba.tokenize yields (word, start, end) with real character offsets.
            return [(w, s) for (w, s, _e) in eng.tokenize(text) if _has_letter(w)]

        if language == "ja":
            eng = _janome()
            if eng is None:
                return None
            surfaces = list(eng.tokenize(text))  # wakati=True -> surface strings, in order
        else:  # th
            eng = _pythainlp()
            if eng is None:
                return None
            surfaces = eng(text, engine="newmm", keep_whitespace=True)

        # janome / pythainlp emit contiguous surface tokens in order (their
        # concatenation == the input), so a forward cursor reconstructs exact offsets.
        out: list[tuple[str, int]] = []
        cursor = 0
        for s in surfaces:
            if not s:
                continue
            idx = text.find(s, cursor)
            if idx < 0:  # defensive: a surface not found verbatim -> skip, keep cursor
                continue
            cursor = idx + len(s)
            if _has_letter(s):
                out.append((s, idx))
        return out
    except Exception:  # noqa: BLE001 - any segmenter error falls back to the default path
        return None
