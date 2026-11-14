#!/usr/bin/env python3
"""Card quality report from a returned field-data file (the card improvement loop, Lane X 2026-11-14).

Usage:
    python3 scripts/card_quality_report.py oo-field-cards-YYYYMMDD-HHMM.zip [--previous OLDER] [--out DIR]

The input is what the Field data button saved (``oo-field-cards-*.zip``), the folder it was
unzipped into, a deep card audit (``oo-card-audit-*.json``), or a Home cache
(``briefing_cache.json``). ``--previous`` is the last loop round's input or its
``card-quality-*.json`` report; the new report then says which findings are new, which are gone and
how each check's count moved.

Writes ``card-quality-<input name>.json`` and ``.md`` into ``--out`` (default: the
input's folder) and prints the Markdown path. Stdlib only: it loads ``src/briefing/card_quality.py``
by path, the same checks the app runs after every Home refresh, so it needs no install and the
two cannot drift apart. Reads the file it is given; writes only the two reports; no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_MODULE = _HERE.parent / "src" / "briefing" / "card_quality.py"
#: Findings listed per check in the Markdown (the JSON carries all of them).
MD_FINDINGS_PER_CHECK = 15


def load_checks():
    spec = importlib.util.spec_from_file_location("oo_card_quality", _MODULE)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {_MODULE}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["oo_card_quality"] = mod
    spec.loader.exec_module(mod)
    return mod


def _read_members(path: Path) -> dict[str, str]:
    if path.is_dir():
        return {p.name: p.read_text("utf-8") for p in path.iterdir() if p.is_file() and p.suffix in (".json", ".jsonl")}
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return {Path(n).name: z.read(n).decode("utf-8") for n in z.namelist() if n.endswith((".json", ".jsonl"))}
    return {path.name: path.read_text("utf-8")}


def load_input(path: Path) -> dict[str, Any]:
    """Normalise any accepted input to ``{"kind", "cards", "meta", "registered", "per_card", "selfcheck"}``."""
    members = _read_members(path)
    if "feed.json" in members:
        feed = json.loads(members["feed.json"])
        cards_doc = json.loads(members.get("cards.json") or "{}")
        per_card: dict[str, dict] = {}
        for row in cards_doc.get("cards") or []:
            extra: dict[str, Any] = {"arithmetic": row.get("arithmetic")}
            ev = row.get("evidence")
            if isinstance(ev, dict) and "skipped" not in ev:
                extra["evidence"] = ev
            per_card[str(row.get("card_id"))] = extra
        history = [json.loads(ln) for ln in (members.get("selfcheck.jsonl") or "").splitlines() if ln.strip()]
        return {
            "kind": "field-cards",
            "cards": feed.get("cards") or [],
            "meta": feed.get("feed") or {},
            "registered": feed.get("registered_producers"),
            "per_card": per_card,
            "selfcheck": history,
            "manifest": json.loads(members["manifest.json"]) if "manifest.json" in members else None,
            "stale_by_corpus_growth": feed.get("stale_by_corpus_growth"),
        }
    if len(members) != 1:
        raise SystemExit(f"{path}: no feed.json inside, and not a single JSON file")
    doc = json.loads(next(iter(members.values())))
    if str(doc.get("schema", "")).startswith("oo-card-audit"):
        cards, per_card = [], {}
        for row in doc.get("cards") or []:
            card = dict(row.get("card") or {})
            card.setdefault("produced_by", row.get("producer"))
            card["dismissed"] = row.get("dismissed")
            cards.append(card)
            per_card[str(card.get("id"))] = {"arithmetic": row.get("arithmetic"), "evidence": row.get("articles")}
        inv = doc.get("producer_inventory") or {}
        timings = [
            {"name": p.get("producer"), "seconds": p.get("elapsed_s"), "outcome": p.get("outcome"),
             "cards": p.get("cards_proposed"), "error_type": p.get("error_type")}
            for p in inv.get("producers") or [] if isinstance(p, dict)
        ]
        return {"kind": "card-audit", "cards": cards, "meta": {"generated_at": doc.get("generated_at"),
                "producer_timings": timings}, "registered": [t["name"] for t in timings] or None,
                "per_card": per_card, "selfcheck": [], "manifest": None, "stale_by_corpus_growth": None}
    if "cards" in doc:  # a Home cache, briefing_cache.json
        return {"kind": "briefing-cache", "cards": doc.get("cards") or [], "meta": doc, "registered": None,
                "per_card": {}, "selfcheck": [], "manifest": None, "stale_by_corpus_growth": None}
    raise SystemExit(f"{path}: not a field-cards file, a card audit or a Home cache")


def build(mod, data: dict[str, Any], *, now: datetime | None = None) -> dict:
    report = mod.quality_report(
        data["cards"], meta=data["meta"], registered=data["registered"], per_card=data["per_card"], now=now,
    )
    report["input_kind"] = data["kind"]
    report["stale_by_corpus_growth"] = data.get("stale_by_corpus_growth")
    hist = data.get("selfcheck") or []
    report["selfcheck_history"] = {
        "records": len(hist),
        "first_at": hist[0].get("at") if hist else None,
        "last_at": hist[-1].get("at") if hist else None,
        "high_n_series": [h.get("high_n") for h in hist][-30:],
        "note": "one record per Home refresh, written by the app; the newest 30 high-severity counts are shown",
    }
    if data.get("manifest"):
        report["manifest_personal_content"] = data["manifest"].get("personal_content")
    return report


def load_previous(mod, path: Path) -> dict:
    members = _read_members(path)
    if len(members) == 1:
        doc = json.loads(next(iter(members.values())))
        if doc.get("schema") == mod.SCHEMA:
            return doc
    return build(mod, load_input(path))


def _md_escape(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def to_markdown(mod, report: dict, compare: dict | None, source: str) -> str:
    out = [
        "# Card quality report",
        "",
        f"Input: `{source}` ({report.get('input_kind')}). Feed computed {report.get('feed_generated_at') or 'unknown'}; "
        f"report made {report['generated_at']}. Cards: {report['cards']}.",
        "",
        report["note"],
        "",
        "## Counts by check",
        "",
        "| Severity | Dimension | Check | Findings |",
        "|---|---|---|---|",
    ]
    for c in sorted(report["counts"], key=lambda c: (mod._SEVERITY_ORDER[c["severity"]], -c["n"], c["check"])):
        out.append(f"| {c['severity']} | {c['dimension']} | `{c['check']}` | {c['n']} |")
    if report.get("checks_not_run"):
        out += ["", "Not run (their input is not in this file): " + ", ".join(f"`{c}`" for c in report["checks_not_run"])]
    d = report["direction"]
    out += ["", f"Direction check: {d['checked']} cards checkable, {d['not_checkable']} not checkable (not passes)."]
    if report.get("stale_by_corpus_growth") is not None:
        out.append(f"Stale by corpus growth when saved: {report['stale_by_corpus_growth']}.")
    if compare:
        vc = compare["verdict_counts"]
        out += ["", "## Compared with the previous round", "",
                f"Previous report {compare.get('previous_generated_at')}. Checks: "
                + ", ".join(f"{k} {v}" for k, v in sorted(vc.items()))
                + f". New findings {len(compare['new_findings'])}, resolved {len(compare['resolved_findings'])}.", "",
                "| Check | Previous | Now | Verdict |", "|---|---|---|---|"]
        for p in compare["per_check"]:
            if p["previous"] != p["current"]:
                out.append(f"| `{p['check']}` | {p['previous']} | {p['current']} | {p['verdict']} |")
    out += ["", "## Findings, ranked", "",
            "Sorted by severity, then by how many cards the check hit; no weighting, no score.", ""]
    by_check: dict[str, list[dict]] = {}
    for f in report["findings"]:
        by_check.setdefault(f["check"], []).append(f)
    for check, items in by_check.items():
        spec = mod.CHECKS[check]
        out += [f"### `{check}` ({spec['severity']}, {spec['dimension']}): {len(items)}", "", spec["what"], "",
                "| Kind | Producer | Card | Detail |", "|---|---|---|---|"]
        for f in items[:MD_FINDINGS_PER_CHECK]:
            out.append(f"| {_md_escape(f.get('card_type'))} | {_md_escape(f.get('producer'))} | "
                       f"{_md_escape(f.get('title') or f.get('card_id'))} | {_md_escape(f.get('detail'))} |")
        if len(items) > MD_FINDINGS_PER_CHECK:
            out.append(f"| | | | {len(items) - MD_FINDINGS_PER_CHECK} more in the JSON report |")
        out.append("")
    out += ["## Per card kind", "", "| Kind | Cards | Findings |", "|---|---|---|"]
    for kind, v in report["per_kind"].items():
        fs = ", ".join(f"{x['check']} {x['n']}" for x in v["findings"]) or "none"
        out.append(f"| {_md_escape(kind)} | {v['cards']} | {fs} |")
    hist = report.get("selfcheck_history") or {}
    if hist.get("records"):
        out += ["", "## In-app self-check history", "",
                f"{hist['records']} records from {hist['first_at']} to {hist['last_at']}. "
                f"High-severity counts, oldest to newest: {hist['high_n_series']}."]
    pc = report.get("manifest_personal_content")
    if pc:
        out += ["", "## What the file carried (its own manifest)", ""]
        out += [f"- {k}: {v}" for k, v in pc.items()]
    out += ["", "## What each check means", ""]
    out += [f"- `{k}` ({v['dimension']}, {v['severity']}): {v['what']}" for k, v in mod.CHECKS.items()]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", type=Path)
    ap.add_argument("--previous", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    mod = load_checks()
    report = build(mod, load_input(args.input))
    compare = mod.compare_reports(load_previous(mod, args.previous), report) if args.previous else None
    if compare:
        report["compare"] = compare
    out_dir = args.out or (args.input if args.input.is_dir() else args.input.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Named after the input, so each returned file has one report and a re-run replaces it.
    stem = args.input.name.removesuffix(".zip").removesuffix(".json")
    jpath = out_dir / f"card-quality-{stem}.json"
    mpath = out_dir / f"card-quality-{stem}.md"
    jpath.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    mpath.write_text(to_markdown(mod, report, compare, args.input.name), "utf-8")
    tally = Counter(f["severity"] for f in report["findings"])
    print(mpath)
    print(f"{report['cards']} cards; findings: " + ", ".join(f"{k} {tally.get(k, 0)}" for k in ("high", "medium", "low", "info")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
