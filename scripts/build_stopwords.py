#!/usr/bin/env python3
"""Vendor the stopwords-iso subset the keyword engine needs (networked step).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

stopwords-iso (MIT) ships complete per-language stopword lists. The engine had
NO complete stoplist for many space-segmented languages, so their function words
leaked as keywords. Two waves:

  2026-06-23 — the original no_stoplist set (tr/ro/uk/fi/ur/cs/ca/sk/et/hi/vi/bn/
               fa/sw), ~88k of the 406k keywords.
  2026-07-01 — a live 36k-article / 727k-keyword corpus showed German/Russian/
               Spanish/Italian/Portuguese/Dutch STILL leaking grammar (gestern,
               wurden, вчера, …). They were "claimed managed" via small hand-grown
               ``_EXTRA_STOPWORD_TEXT`` batches, but those were PARTIAL. The full
               stopwords-iso lists for the space-segmented managed languages are
               added here (ar/bg/da/de/el/es/hr/hu/id/it/nl/no/pl/pt/ru/sl/sv).

Every list is written to ``configs/stopwords_iso/<lang>.txt`` and applied
LANGUAGE-SCOPED at extraction (``get_stopwords(lang)`` returns it only for THAT
language) — it is deliberately kept OUT of the language-agnostic
``global_stopwords()`` union, so a word grammatical in one language can never hide
a same-spelled content word in another. That scoping is what makes adding the FULL
Latin-script lists (de 620, es 732, …) collision-free, unlike the global batches.

``stopwordsiso`` bundles the data, so this runs OFFLINE (no network). After a
refresh, bump ``STOPWORDS_ISO_AS_OF`` in src/services/stopwords.py + the
configs/external_artifacts.yml ``stopwords-iso`` entry's ``last_verified``.

    pip install stopwordsiso
    python scripts/build_stopwords.py
"""

from __future__ import annotations

import pathlib
import sys

# The space-segmented managed languages we vendor a full stoplist for.
# (zh/ja/th are UNSEGMENTED — a stoplist can't help; not fetched here. sr/bs/az are
# managed but ABSENT from stopwords-iso, so they keep their hand-grown batches.)
LANGS = [
    # 2026-06-23 original no_stoplist wave
    "tr", "ro", "uk", "fi", "ur", "cs", "ca", "sk", "et", "hi", "vi", "bn", "fa", "sw",
    # 2026-07-01 wave: managed languages that had only PARTIAL hand-grown batches
    "ar", "bg", "da", "de", "el", "es", "hr", "hu", "id", "it",
    "nl", "no", "pl", "pt", "ru", "sl", "sv",
    # nb (Norwegian Bokmål) is managed but absent from stopwords-iso; the "no" list
    # is Bokmål-based, so alias it (recorded below).
    "nb",
]

# Languages whose list is sourced from a stopwords-iso code that differs from the
# file name (documented alias, not a fabricated list).
ALIASES = {"nb": "no"}

OUT = pathlib.Path(__file__).resolve().parents[1] / "configs" / "stopwords_iso"


def main() -> int:
    try:
        import stopwordsiso
    except ImportError:
        print("pip install stopwordsiso first.", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for lang in LANGS:
        src = ALIASES.get(lang, lang)
        words = sorted({w.strip().lower() for w in stopwordsiso.stopwords(src) if w.strip()})
        if not words:
            print(f"  WARN: no words for {lang} (source {src})", file=sys.stderr)
            continue
        (OUT / f"{lang}.txt").write_text("\n".join(words) + "\n", encoding="utf-8")
        total += len(words)
        note = f" (from {src})" if src != lang else ""
        print(f"  {lang}: {len(words)}{note}")
    print(f"TOTAL: {total} words across {len(LANGS)} languages -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
