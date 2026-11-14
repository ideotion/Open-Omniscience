#!/usr/bin/env python3
"""
Turn the candidate-sources files of one or more instances into a REVIEW TABLE of proposed catalogue additions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Field data button saves ``oo-field-<press>-candidate-sources.zip`` per instance (src/catalog/candidate_sources.py):
the sources that instance qualified by its own measurement that no shipped catalogue has. This groups them by domain
across instances and writes ``proposed-sources.md`` and ``proposed-sources.json``:

  * how many INSTANCES qualified each domain (by their random instance tags, so two presses of one instance count once);
  * the tags, languages and countries the instances gave it, with counts, and where they DISAGREE;
  * the evidence: the most articles stored, the qualification attempts, the newest date;
  * whether a shipped catalogue ALREADY carries the domain now (main moved on since the press).

IT ADDS NOTHING. Every row stays ``proposed``. A maintainer verifies each one (tags, that it is what it claims to be, its
robots and terms), and only a reviewed pull request adds it to a catalogue under configs/.

USAGE
    python scripts/propose_source_additions.py FILE_OR_FOLDER [...] --out DIR

A file is a candidate-sources zip (join numbered pieces first: ``cat name-part-*.zip > name.zip``) or the candidates.json
inside one. A folder is searched for both. Stdlib only, plus the repo's catalogue reader when it can be imported.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _doc(raw: bytes | str) -> dict[str, Any] | None:
    doc = json.loads(raw)
    return doc if isinstance(doc, dict) and isinstance(doc.get("candidates"), list) else None


def _load(path: Path) -> list[tuple[str, dict[str, Any]]]:
    """``(instance tag, candidates document)`` pairs read from one zip or json file; an unreadable file raises."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "candidates.json" not in names:
                return []
            doc = _doc(z.read("candidates.json"))
            man = json.loads(z.read("manifest.json")) if "manifest.json" in names else {}
        return [(str(man.get("instance") or path.name), doc)] if doc else []
    doc = _doc(path.read_text(encoding="utf-8"))
    sibling = path.with_name("manifest.json")   # an extracted zip: its manifest names the instance
    man = json.loads(sibling.read_text(encoding="utf-8")) if sibling.is_file() else {}
    return [(str(man.get("instance") or path.parent.name or path.name), doc)] if doc else []


def collect(inputs: list[Path]) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """Every readable candidates document, and the files that could not be read (a lone numbered piece, a damaged zip),
    which are reported and never stop the run."""
    out: list[tuple[str, dict[str, Any]]] = []
    unreadable: list[str] = []
    for p in inputs:
        files = sorted(p.rglob("*.zip")) + sorted(p.rglob("candidates.json")) if p.is_dir() else [p]
        for f in files:
            try:
                out += _load(f)
            except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, OSError, KeyError) as exc:
                unreadable.append(f"{f.name}: {type(exc).__name__}")
    return out, unreadable


def _shipped_domains() -> frozenset[str] | None:
    try:
        sys.path.insert(0, str(ROOT))
        from src.catalog.provenance_scope import curated_catalogue_domains

        return curated_catalogue_domains()
    except Exception:  # noqa: BLE001 - the table still builds; the column says it was not checked
        return None


def build(docs: list[tuple[str, dict[str, Any]]], unreadable: list[str] | None = None) -> dict[str, Any]:
    # one row per (instance, domain): the NEWEST press of an instance wins, so a second press never counts twice
    latest: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    for inst, doc in docs:
        when = str(doc.get("generated_at") or "")
        for row in doc.get("candidates") or []:
            if isinstance(row, dict) and row.get("domain"):
                key = (inst, str(row["domain"]).lower())
                if key not in latest or when >= latest[key][0]:
                    latest[key] = (when, row)
    by_domain: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for (inst, domain), (_when, row) in latest.items():
        by_domain[domain].append((inst, row))
    shipped = _shipped_domains()
    rows: list[dict[str, Any]] = []
    for domain, seen in sorted(by_domain.items()):
        instances = sorted({i for i, _ in seen})
        tags = Counter(t for _i, r in seen for t in (r.get("tags") or []))
        langs = Counter(r.get("language") for _i, r in seen if r.get("language"))
        countries = Counter(r.get("country") for _i, r in seen if r.get("country"))
        ev = [r.get("evidence") or {} for _i, r in seen]
        rows.append({
            "domain": domain,
            "proposal": "proposed",
            "names": sorted({str(r.get("name")) for _i, r in seen if r.get("name")}),
            "feeds": sorted({str(r.get("feed")) for _i, r in seen if r.get("feed")}),
            "instances": instances,
            "instances_n": len(instances),
            "tags": dict(tags.most_common()),
            "languages": dict(langs),
            "countries": dict(countries),
            "disagreement": [k for k, c in (("language", langs), ("country", countries)) if len(c) > 1],
            "max_articles_stored": max((int(e.get("articles_stored") or 0) for e in ev), default=0),
            "attempts": dict(sum((Counter(e.get("attempts") or {}) for e in ev), Counter())),
            "newest_article": max((e.get("last_article") or "" for e in ev), default="") or None,
            "already_shipped": None if shipped is None else domain in shipped,
        })
    rows.sort(key=lambda r: (-int(r["instances_n"]), -int(r["max_articles_stored"]), str(r["domain"])))
    return {
        "schema": "oo-proposed-sources-1",
        "inputs": len(docs),
        "unreadable": unreadable or [],
        "instances": sorted({i for i, _ in docs}),
        "note": "Every row is PROPOSED. Nothing is added to a shipped catalogue without a maintainer's verification and a "
                "reviewed pull request.",
        "rows": rows,
    }


def to_markdown(rep: dict[str, Any]) -> str:
    def cell(x: Any) -> str:
        return str(x).replace("|", "\\|").replace("\n", " ")

    lines = [
        "# Proposed source additions",
        "",
        f"{len(rep['rows'])} domains from {rep['inputs']} file(s), {len(rep['instances'])} instance(s). {rep['note']}",
        "",
    ]
    if rep.get("unreadable"):
        lines += [f"Not read (join numbered pieces first, or the file is damaged): {', '.join(rep['unreadable'])}", ""]
    lines += [
        "| Domain | Instances | Articles | Tags | Language | Country | Disagree | Shipped now |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rep["rows"]:
        tags = ", ".join(f"{t} ({n})" for t, n in list(r["tags"].items())[:6])
        shipped = {None: "not checked", True: "yes", False: "no"}[r["already_shipped"]]
        lines.append(
            f"| {cell(r['domain'])} | {r['instances_n']} | {r['max_articles_stored']} | {cell(tags)} | "
            f"{cell(', '.join(r['languages']) or '-')} | {cell(', '.join(r['countries']) or '-')} | "
            f"{', '.join(r['disagreement']) or '-'} | {shipped} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    docs, unreadable = collect(a.inputs)
    for u in unreadable:
        print(f"not read: {u}", file=sys.stderr)
    if not docs:
        print("no candidate-sources file found in the inputs", file=sys.stderr)
        return 2
    rep = build(docs, unreadable)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "proposed-sources.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (a.out / "proposed-sources.md").write_text(to_markdown(rep), encoding="utf-8")
    print(f"{len(rep['rows'])} proposed domains from {len(rep['instances'])} instance(s) -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
