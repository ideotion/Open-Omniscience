#!/usr/bin/env python3
"""Vendor the stopwords-iso subset the keyword engine needs (networked step).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

stopwords-iso (MIT) ships complete per-language stopword lists. The engine had
NO stoplist for several space-segmented languages (the 2026-06-23 keyword-engine
report: tr/ro/uk/fi/ur/cs/ca/sk/et/hi/vi/bn/fa/sw were "no_stoplist", ~88k of the
406k keywords leaking function words). This writes a SUBSET (only those languages)
to ``configs/stopwords_iso/<lang>.txt`` — applied LANGUAGE-SCOPED at extraction so
a word grammatical in one language can never hide content in another.

Run on a NETWORKED machine (Wikidata/Ollama-style: the sandbox can't reach it):

    pip install stopwordsiso
    python scripts/build_stopwords.py

then bump ``STOPWORDS_ISO_AS_OF`` in src/services/stopwords.py + the
configs/external_artifacts.yml ``stopwords-iso`` entry's ``last_verified``.
"""

from __future__ import annotations

import pathlib
import sys

# The space-segmented languages that were no_stoplist (per the engine report).
# (zh/ja/th are UNSEGMENTED — a stoplist can't help; not fetched here.)
LANGS = ["tr", "ro", "uk", "fi", "ur", "cs", "ca", "sk", "et", "hi", "vi", "bn", "fa", "sw"]

OUT = pathlib.Path(__file__).resolve().parents[1] / "configs" / "stopwords_iso"


def main() -> int:
    try:
        import stopwordsiso
    except ImportError:
        print("pip install stopwordsiso first (run this on a networked machine).", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for lang in LANGS:
        words = sorted({w.strip().lower() for w in stopwordsiso.stopwords(lang) if w.strip()})
        if not words:
            print(f"  WARN: no words for {lang}", file=sys.stderr)
            continue
        (OUT / f"{lang}.txt").write_text("\n".join(words) + "\n", encoding="utf-8")
        total += len(words)
        print(f"  {lang}: {len(words)}")
    print(f"TOTAL: {total} words across {len(LANGS)} languages -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
