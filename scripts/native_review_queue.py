#!/usr/bin/env python3
"""
Generate the native-review queue from the locale diffs of the merges that added keys.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Several shipped features added chrome strings whose non-English text was AI-drafted and
flagged "waiting for native review" (OPEN_QUEUE item 33, and the C6 and A-S6 rows). A
native reader should not have to read the ledger to act on that, so this script rebuilds,
from the merge commits themselves, for each group: the exact keys, the English source, the
files that use the key, and per language how many keys were added and how many still read
exactly like English.

It READS the locale files at the named commits (git history) and writes only:
    docs/product/NATIVE_REVIEW_QUEUE.md           the overview
    docs/product/native-review/<lang>.md          one sheet per language (key, English, current text)

Usage (needs the merge commits, so a full clone, not a shallow one):
    python scripts/native_review_queue.py           # write the files
    python scripts/native_review_queue.py --check   # exit 1 if the committed files differ
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = "src/static/locales"
OUT_DOC = ROOT / "docs" / "product" / "NATIVE_REVIEW_QUEUE.md"
OUT_DIR = ROOT / "docs" / "product" / "native-review"

# (id, OPEN_QUEUE reference, title, PR, merge sha or None). A group with no sha is read from the
# PR head (``refs/remotes/pr/<n>``, fetched with ``git fetch origin refs/pull/<n>/head:refs/remotes/pr/<n>``)
# against its merge base with origin/main, and is labelled PENDING until that head is on origin/main.
GROUPS = [
    ("33a", "item 33 (a)", "Law coverage floor (C-L1)", 1710, "743fb4cc2"),
    ("33c", "item 33 (c)", "OSM trends B3a: tag adoption, openings and closures", 1730, "726de08"),
    ("33d", "item 33 (d)", "OSM B3b: brands, contact channels, freshness", 1735, "33f9940"),
    ("33e", "item 33 (e)", "OSM B3c: places by country and by region", 1736, "cac50c6"),
    ("33f", "item 33 (f)", "OSM stored monthly summary (R435)", 1738, "a47a9fb"),
    (
        "33g",
        "item 33 (g), C6",
        "oo-on: confirmations for the irreversible actions",
        1746,
        "0982a0b",
    ),
    (
        "33h",
        "item 33 (h), E2",
        "Help coverage banner",
        1748,
        "bf4cbbf41",
    ),
    (
        "33i",
        "item 33 (i), A-S6",
        "Population-weighted figures state their weighting",
        1750,
        "2a621dc",
    ),
    ("33j", "item 33 (j)", "Climate series", 1751, "45851f526"),
    ("extra-1", "not in item 33", "OSM daily change files: update a country (J1)", 1720, "ea88a6e"),
    ("extra-2", "not in item 33", "Living sources: OSM daily change files (B1)", 1725, "c0c66ff"),
    ("extra-3", "not in item 33", "Living sources: per-edition coverage group", 1727, "7139c68"),
    (
        "extra-4",
        "not in item 33, R611",
        "Start-up step: the links' covering index",
        1839,
        "328a996b2",
    ),
]

# Item 33 (b) asks for no translation (a tree and operator fact).
NOTES = [
    "(b) of item 33 is an operator step (a dated population table) and adds no key.",
    "Item 33 has (a) to (j); (h) and (j) were added with their merges (#1748, #1751).",
    "A group marked PENDING is read from its open PR head and changes on a re-run until it merges.",
]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def lang_codes() -> list[str]:
    return sorted(p.stem for p in (ROOT / LOCALES).glob("*.json"))


def span(pr: int, sha: str | None) -> tuple[str, str, bool]:
    """(base, head, pending) for a group."""
    if sha:
        return f"{sha}^1", sha, False
    head = f"refs/remotes/pr/{pr}"
    try:
        base = git("merge-base", "origin/main", head).strip()
    except subprocess.CalledProcessError:
        sys.exit(f"PR #{pr} head is not fetched: git fetch origin refs/pull/{pr}/head:{head}")
    merged = (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", head, "origin/main"], cwd=ROOT
        ).returncode
        == 0
    )
    if merged:
        sys.exit(f"PR #{pr} is merged: set its merge sha in GROUPS and re-run")
    return base, head, True


def added_keys(base: str, head: str, lang: str) -> dict[str, str]:
    """Keys the span added to <lang>.json, with their value at its head."""
    path = f"{LOCALES}/{lang}.json"
    before = json.loads(git("show", f"{base}:{path}"))
    after = json.loads(git("show", f"{head}:{path}"))
    return {k: v for k, v in after.items() if k not in before}


def users(key: str) -> list[str]:
    """Source files (not locales) that carry the key text literally."""
    needle = key.replace("\\", "\\\\").replace('"', '\\"')
    out = subprocess.run(
        ["git", "grep", "-l", "-F", "--", needle, "--", "src", f":!{LOCALES}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.split()
    return sorted(out)


def cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def help_drafts() -> list[str]:
    """The translated Help documents on disk (``docs/i18n/<lang>/``), each read from its own banner comment.

    A Help draft is a whole document, not a key, so it has no merge diff to read: the file itself says what it
    is (AI-drafted, its coverage) in the comment that opens it, and this section lists exactly that.
    """
    base = ROOT / "docs" / "i18n"
    rows = []
    for path in sorted(base.glob("*/*.md")):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"\s*<!--(.*?)-->", text, re.S)
        banner = " ".join(m.group(1).split()) if m else ""
        cov = re.search(r"Coverage: ([^.]*)\.", banner)
        reviewed = "not yet reviewed" not in banner
        rows.append(
            f"| {path.parent.name} | `docs/i18n/{path.parent.name}/{path.name}` | "
            f"{cell(cov.group(1)) if cov else 'not stated'} | {'yes' if reviewed else 'no'} |"
        )
    if not rows:
        return []
    return [
        "## Help documents",
        "",
        "Translated Help documents served by Help in that language (the English original is authoritative).",
        "To act: read the draft beside the English document, correct it with a pull request, and when a native",
        'speaker has read it, replace "not yet reviewed by a native speaker" in its opening comment.',
        "",
        "| Language | File | Coverage (from its opening comment) | Native-reviewed |",
        "|---|---|---|---|",
        *rows,
        "",
    ]


def build() -> dict[Path, str]:
    langs = lang_codes()
    others = [lang for lang in langs if lang != "en"]
    data = []
    for gid, ref, title, pr, sha in GROUPS:
        base, head, pending = span(pr, sha)
        en = added_keys(base, head, "en")
        per = {lang: added_keys(base, head, lang) for lang in others}
        label = (
            f"PENDING, open head `{git('rev-parse', '--short', head).strip()}`"
            if pending
            else f"`{sha or git('rev-parse', '--short', head).strip()}`"
        )
        data.append((gid, ref, title, pr, label, en, per))

    doc = [
        "# Native translation review queue",
        "",
        "Generated by `python scripts/native_review_queue.py` from the merge commits named below;",
        "do not edit by hand. English (`en.json`) is the source. Every non-English text listed here",
        "was AI-drafted and has not been read by a native speaker. A key counted as",
        "**same as English** carries English text in that language, which is either a deliberate",
        "carry-over (a name, a code) or a string still waiting for a translation.",
        "",
        "One sheet per language lists, for each key, the English source and the text at the commit named for the group (the head, for a pending group):",
        "",
        " ".join(f"[{lang}](native-review/{lang}.md)" for lang in others),
        "",
        "To act: open your language's sheet, correct the third column in",
        f"`{LOCALES}/<lang>.json` (the key is the English text), and keep every `{{placeholder}}`",
        "exactly as written. `zh` and `ja` should use full-width punctuation; some drafts use",
        "half-width (item 33 (a)).",
        "",
        "## Totals",
        "",
        "| Group | Where it is recorded | PR | Merge | New keys |",
        "|---|---|---|---|---|",
    ]
    total = 0
    for gid, ref, title, pr, sha, en, _per in data:
        doc.append(f"| {gid} {title} | {ref} | #{pr} | {sha} | {len(en)} |")
        total += len(en)
    doc += [f"| **All** | | | | **{total}** |", ""]
    for n in NOTES:
        doc.append(f"- {n}")
    doc.append("")
    doc += help_drafts()

    sheets: dict[str, list[str]] = {lang: [] for lang in others}
    for gid, ref, title, pr, sha, en, per in data:
        doc += [
            f"## {gid}: {title}",
            "",
            f"Recorded: {ref}. PR #{pr}, {'merge ' + sha if not sha.startswith('PENDING') else sha}. {len(en)} new key{'' if len(en) == 1 else 's'}.",
            "",
            "Per-language counts (keys added / same as English / missing):",
            "",
            "| Language | Added | Same as English | Missing |",
            "|---|---|---|---|",
        ]
        for lang in others:
            got = per[lang]
            same = sum(1 for k in en if got.get(k) == k or got.get(k) == en[k])
            missing = sum(1 for k in en if k not in got)
            doc.append(f"| {lang} | {sum(k in got for k in en)} | {same} | {missing} |")
        doc += ["", "Keys (English source, then the files that use it):", ""]
        doc += ["| # | English source | Files |", "|---|---|---|"]
        for i, key in enumerate(sorted(en), 1):
            files = users(key)
            shown = (
                ", ".join(f"`{f}`" for f in files)
                if files
                else "built at runtime (no literal match)"
            )
            doc.append(f"| {i} | {cell(en[key])} | {shown} |")
        doc.append("")
        for lang in others:
            sheets[lang] += [
                f"## {gid}: {title} (PR #{pr})",
                "",
                "| # | English source | Current text in this language |",
                "|---|---|---|",
            ]
            for i, key in enumerate(sorted(en), 1):
                cur = per[lang].get(key)
                shown = cell(cur) if cur is not None else "**missing**"
                sheets[lang].append(f"| {i} | {cell(en[key])} | {shown} |")
            sheets[lang].append("")

    out = {OUT_DOC: "\n".join(doc).rstrip() + "\n"}
    for lang in others:
        intro = [
            f"# Native review sheet: {lang}",
            "",
            "Generated by `python scripts/native_review_queue.py`; see",
            "[NATIVE_REVIEW_QUEUE.md](../NATIVE_REVIEW_QUEUE.md) for how to act on it.",
            f"Correct the text in `{LOCALES}/{lang}.json` (the key is the English text).",
            "",
        ]
        out[OUT_DIR / f"{lang}.md"] = "\n".join(intro + sheets[lang]).rstrip() + "\n"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    files = build()
    if args.check:
        bad = [p for p, t in files.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        for p in bad:
            print(f"out of date: {p.relative_to(ROOT)}", file=sys.stderr)
        return 1 if bad else 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p, t in files.items():
        p.write_text(t, encoding="utf-8")
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
