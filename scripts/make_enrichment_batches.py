#!/usr/bin/env python3
"""
Generate parallel-session worklists for enriching source metadata in sources.yml.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Most of the ~3000 catalog sources carry at most a single topical tag (often just
``news``). This script selects the UNDER-ENRICHED sources, groups them by language
(so one research session builds context once and stays in one linguistic/regional
lane), chunks them into bounded batches, and writes:

  - a compact INPUT list per batch (domain | name | country | language) -- the
    minimum context a classifier needs, to keep the prompt token-cheap; and
  - a ready-to-paste PROMPT per batch = the shared template (docs/design/
    source_enrichment/PROMPT_TEMPLATE.md) with the batch's input inlined.

The batches are sized for a single Opus run with a LIMITED tool-call budget: the
prompt instructs the model to lean on parametric knowledge and spend at most one
web search per uncertain outlet, then emit all rows in one pass. See the strategy
doc (docs/design/SOURCE_METADATA_ENRICHMENT_STRATEGY.md) for the full rationale.

Nothing here touches the network or mutates sources.yml. It only reads the catalog
and writes worklists under --out. Re-run it any time; the catalog changes as the
parallel coding sessions merge, so regenerate rather than relying on stale chunks.

Examples:
  python scripts/make_enrichment_batches.py                       # default run
  python scripts/make_enrichment_batches.py --batch-size 40 --max-tags 0
  python scripts/make_enrichment_batches.py --languages en,fr --out /tmp/work
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = _ROOT / "configs" / "sources.yml"
_TEMPLATE = _ROOT / "docs" / "design" / "source_enrichment" / "PROMPT_TEMPLATE.md"
_DEFAULT_OUT = _ROOT / "docs" / "design" / "source_enrichment" / "batches"

# The bucket word a source_type leaves in tags; it is not a topical signal.
_BUCKET_WORDS = {"news"}


def _topical_tag_count(src: dict) -> int:
    """Tags that actually classify the source by subject, minus the bucket word."""
    tags = [t for t in (src.get("tags") or []) if t not in _BUCKET_WORDS]
    return len(tags)


def select_under_enriched(sources: list[dict], *, max_tags: int) -> list[dict]:
    """Sources carrying at most ``max_tags`` topical tags (the enrichment target)."""
    return [s for s in sources if _topical_tag_count(s) <= max_tags]


def group_by_language(sources: list[dict]) -> dict[str, list[dict]]:
    """Bucket by ISO-639-1 language ('und' when unknown), each bucket name-sorted."""
    groups: dict[str, list[dict]] = {}
    for s in sources:
        lang = (s.get("language") or "und").strip().lower() or "und"
        groups.setdefault(lang, []).append(s)
    for lang in groups:
        groups[lang].sort(key=lambda s: (s.get("name") or s.get("domain") or "").lower())
    return groups


def chunk(items: list[dict], size: int) -> list[list[dict]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def input_block(batch: list[dict]) -> str:
    """A compact, token-cheap input table for the prompt."""
    lines = ["# domain | name | country | language"]
    for s in batch:
        lines.append(
            " | ".join(
                [
                    str(s.get("domain") or "?"),
                    str(s.get("name") or "?"),
                    str(s.get("country") or "?"),
                    str(s.get("language") or "?"),
                ]
            )
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sources", type=Path, default=_SOURCES)
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    ap.add_argument("--batch-size", type=int, default=50)
    ap.add_argument(
        "--max-tags",
        type=int,
        default=1,
        help="select sources with at most this many topical tags (default 1)",
    )
    ap.add_argument(
        "--languages",
        type=str,
        default="",
        help="comma-separated ISO-639-1 filter, e.g. en,fr (default: all)",
    )
    ap.add_argument(
        "--no-prompts",
        action="store_true",
        help="write only input lists, skip the inlined prompt files",
    )
    args = ap.parse_args(argv)

    data = yaml.safe_load(args.sources.read_text(encoding="utf-8"))
    sources = data.get("sources") or []
    under = select_under_enriched(sources, max_tags=args.max_tags)
    groups = group_by_language(under)

    lang_filter = {x.strip().lower() for x in args.languages.split(",") if x.strip()}
    if lang_filter:
        groups = {k: v for k, v in groups.items() if k in lang_filter}

    template = ""
    if not args.no_prompts:
        if not _TEMPLATE.exists():
            print(f"WARN: template not found at {_TEMPLATE}; writing inputs only", file=sys.stderr)
            args.no_prompts = True
        else:
            template = _TEMPLATE.read_text(encoding="utf-8")

    args.out.mkdir(parents=True, exist_ok=True)
    manifest: list[str] = []
    total_batches = 0
    for lang in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        batches = chunk(groups[lang], args.batch_size)
        for i, batch in enumerate(batches, start=1):
            total_batches += 1
            stem = f"{lang}-{i:03d}"
            block = input_block(batch)
            (args.out / f"input_{stem}.txt").write_text(block + "\n", encoding="utf-8")
            if not args.no_prompts:
                prompt = template.replace("{{INPUT_BLOCK}}", block).replace(
                    "{{BATCH_ID}}", stem
                )
                (args.out / f"prompt_{stem}.md").write_text(prompt, encoding="utf-8")
            manifest.append(f"{stem}\t{len(batch)} sources")

    (args.out / "MANIFEST.txt").write_text(
        f"Generated {total_batches} batches from {len(under)} under-enriched sources "
        f"(<= {args.max_tags} topical tags) of {len(sources)} total.\n\n"
        + "\n".join(manifest)
        + "\n",
        encoding="utf-8",
    )

    print(f"Under-enriched: {len(under)} / {len(sources)} sources")
    print(f"Wrote {total_batches} batch(es) to {args.out}")
    print("Per-language batch counts:")
    for lang in sorted(groups, key=lambda k: (-len(groups[k]), k)):
        n = len(groups[lang])
        print(f"  {lang}: {n} sources -> {len(chunk(groups[lang], args.batch_size))} batch(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
