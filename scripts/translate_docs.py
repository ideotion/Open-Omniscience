#!/usr/bin/env python3
"""
Draft documentation translations with the LOCAL LLM (Ollama) — docs/i18n/<lang>/.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled (2026-06-10): the in-app documentation should offer an initial
translation attempt that users perfect over time. Hand-translating ~2,400 lines
into 11 languages is not honest one-shot work for any single contributor — but
the app already ships a local translation engine (Ollama). This tool drafts the
translations on YOUR machine:

- loopback-only (the same local Ollama the app uses; no cloud, no telemetry);
- chunked by Markdown headings so structure, links and code blocks survive;
- every output file starts with an honest provenance banner (machine-drafted,
  model + date, English is authoritative) — and the in-app reader shows the
  same notice whenever it serves a translation;
- resumable: existing files are skipped unless --force.

Usage:
    python scripts/translate_docs.py --langs fr,es --docs quickstart
    python scripts/translate_docs.py                # all langs × all docs
    python scripts/translate_docs.py --model llama3.2:3b
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
_OUT_DIR = _DOCS_DIR / "i18n"

# Keep in sync with src/api/main.py:_DOCS (the in-app reader's allow-list).
_FILES = {
    "user-manual": "USER_MANUAL.md",
    "quickstart": "QUICKSTART.md",
    "ethics": "ETHICS.md",
    "governance": "GOVERNANCE.md",
    "security": "SECURITY.md",
    "design": "DESIGN.md",
    "roadmap": "ROADMAP.md",
    "architecture": "ARCHITECTURE.md",
    "contributing": "CONTRIBUTING.md",
    "changes": "CHANGES.md",
}
_LANGS = {
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "zh": "Simplified Chinese",
    "hi": "Hindi",
    "ar": "Arabic",
    "bn": "Bengali",
    "ru": "Russian",
    "pt": "Portuguese",
    "id": "Indonesian",
    "ja": "Japanese",
}
_CHUNK_CHARS = 2400  # small enough for 1–3B local models to stay faithful


def _chunks(markdown: str) -> list[str]:
    """Split on top-/second-level headings, then pack to ~_CHUNK_CHARS."""
    parts = re.split(r"(?m)^(?=#{1,2} )", markdown)
    packed: list[str] = []
    buf = ""
    for part in parts:
        if buf and len(buf) + len(part) > _CHUNK_CHARS:
            packed.append(buf)
            buf = part
        else:
            buf += part
    if buf:
        packed.append(buf)
    return packed


def _prompt(lang_name: str, chunk: str) -> str:
    return (
        f"Translate the following Markdown documentation into {lang_name}.\n"
        "Rules: keep ALL Markdown structure exactly (headings, lists, tables, links, "
        "inline code and fenced code blocks); never translate code, URLs, file paths, "
        "CLI commands or product names; translate prose faithfully and plainly; "
        "output ONLY the translated Markdown, nothing else.\n\n"
        f"{chunk}"
    )


def _banner(lang: str, model: str) -> str:
    return (
        f"<!-- MACHINE-DRAFTED TRANSLATION ({lang}) — model {model}, "
        f"{datetime.now(UTC).date().isoformat()}. The English original is "
        "authoritative. Improve this file via a pull request. -->\n\n"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Draft doc translations with local Ollama")
    ap.add_argument("--langs", default=",".join(_LANGS), help="comma-separated codes")
    ap.add_argument("--docs", default=",".join(_FILES), help="comma-separated slugs")
    ap.add_argument("--model", default=None, help="Ollama model tag (default: configured)")
    ap.add_argument("--force", action="store_true", help="re-draft existing files")
    args = ap.parse_args(argv)

    from src.llm.ollama import LLMUnavailable, OllamaClient

    client = OllamaClient()
    if not client.is_available():
        print(
            "Ollama is not running at its loopback address. Start it (ollama serve) "
            "and pull a model first — this tool is local-only by design.",
            file=sys.stderr,
        )
        return 1
    model = args.model or (client.list_installed() or [None])[0]
    if not model:
        print("No local model installed. `ollama pull llama3.2:1b` (or larger).", file=sys.stderr)
        return 1

    for lang in [c.strip() for c in args.langs.split(",") if c.strip()]:
        if lang not in _LANGS:
            print(f"  skip unknown lang {lang!r}", file=sys.stderr)
            continue
        for slug in [s.strip() for s in args.docs.split(",") if s.strip()]:
            fname = _FILES.get(slug)
            if fname is None:
                print(f"  skip unknown doc {slug!r}", file=sys.stderr)
                continue
            src = _DOCS_DIR / fname
            out = _OUT_DIR / lang / fname
            if not src.exists():
                continue
            if out.exists() and not args.force:
                print(f"  keep {out} (exists; --force to re-draft)")
                continue
            print(f"  drafting {out} with {model} …")
            pieces: list[str] = []
            for i, chunk in enumerate(_chunks(src.read_text(encoding="utf-8"))):
                try:
                    pieces.append(client.generate(_prompt(_LANGS[lang], chunk), model=model))
                except LLMUnavailable as exc:
                    print(f"    aborted at chunk {i}: {exc}", file=sys.stderr)
                    return 1
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_banner(lang, model) + "\n".join(pieces), encoding="utf-8")
            print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
