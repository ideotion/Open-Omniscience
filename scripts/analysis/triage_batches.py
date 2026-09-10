"""Prepare and merge the model-triage stage of the candidate pipeline.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Sits between `verify_candidate_feeds.py` (zero tokens: which candidates have a live feed) and
`merge_source_batch.py` (the reviewed append into the catalogue). Two subcommands:

  prepare  --verified data/candidate_feeds/verified.jsonl --out-dir data/candidate_feeds/triage
           writes batch_NNNN.json files of ~40 verified rows each (domain, name, homepage
           title, description, up to 8 recent headlines, country, language, the Wikidata type),
           plus canaries.json (two hand-known rows with EXPECTED answers, mixed into every
           batch) and vocabulary.json (the closed topic list, taken from the shipped catalogue's
           own tags so the model cannot invent a taxonomy).

  merge    --verified ... --triage-dir ... --out verified_triaged.yml
           re-validates every batch_NNNN.result.json IN PLAIN CODE -- every domain echoed
           exactly once, every kind/confidence in its enum, every topic in the vocabulary, both
           canaries classified as expected -- and writes the catalogue entries for rows that
           are (a) feed-verified, (b) journalism per the model, (c) confidence high or medium,
           (d) from a batch whose canaries passed. Everything else is listed in
           triage_rejections.csv with its reason. A batch that failed a canary is never merged,
           whatever its other rows say.

WHY THE MODEL SEES ONLY THIS. The homepage title, the description and the headlines are the
evidence a person would use; the model does not browse, so its answer is a reading of the
same evidence a reviewer can see beside it -- and a wrong reading is caught by the canaries,
the vocabulary and the reviewer, not trusted.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

import os  # noqa: E402  (kept beside the seam it serves)

# The repository root: two levels up from scripts/analysis/, or wherever a test points it.
_ROOT = Path(os.environ.get("OO_REPO_ROOT") or Path(__file__).resolve().parents[2])
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BATCH_SIZE = 40
KINDS = (
    "news", "magazine", "broadcaster", "wire-agency", "investigative", "fact-checker",
    "academic", "trade-or-corporate", "institution", "religious", "personal-blog",
    "aggregator", "other",
)
JOURNALISM_KINDS = frozenset({"news", "magazine", "broadcaster", "wire-agency", "investigative", "fact-checker"})
CONFIDENCES = ("high", "medium", "low")
MERGEABLE_CONFIDENCE = frozenset({"high", "medium"})
# The kind a catalogue entry carries, from the controlled source_type vocabulary.
_SOURCE_TYPE_OF_KIND = {
    "news": "news", "magazine": "magazine", "broadcaster": "broadcaster",
    "wire-agency": "wire-agency", "investigative": "investigative", "fact-checker": "fact-checker",
}

# Two hand-known rows. Fixed, never corpus-derived (the triage-run canary convention), so a
# batch that misreads them is a batch to distrust. Their headlines are illustrative, not
# fetched -- they exist to be classified, not verified.
CANARIES = [
    {
        "domain": "theguardian.com", "name": "The Guardian", "site_title": "The Guardian | News, sport and opinion",
        "description": "Latest news, sport, business, comment, analysis and reviews from the Guardian.",
        "titles": ["Ministers face questions over the new housing bill",
                   "Storm damage closes rail lines across the north for a second day",
                   "Central bank holds rates as inflation slows to 2.1%"],
        "country": "gb", "language": "en", "wikidata_type": "news",
        "expected": {"journalism": True, "kind": "news", "language": "en"},
    },
    {
        "domain": "ec.europa.eu", "name": "European Commission", "site_title": "European Commission, official website",
        "description": "The official website of the European Commission, providing access to information about its political priorities, policies and services.",
        "titles": ["Commission adopts the 2027 work programme",
                   "Press release: State aid decision on regional airports",
                   "Call for proposals: Horizon Europe cluster 5"],
        "country": "be", "language": "en", "wikidata_type": "institution",
        "expected": {"journalism": False, "kind": "institution", "language": "en"},
    },
]


def _vocabulary() -> list[str]:
    """The closed topic list: every topical tag the shipped catalogue uses at least 5 times,
    minus ownership/lean/provenance tags -- the catalogue's own taxonomy, not a new one."""
    from src.catalog.taxonomy import LEAN_TAGS, OWNERSHIP_TAGS

    counts: Counter = Counter()
    for name in ("configs/sources.yml", "configs/sources_spectrum.yml"):
        p = _ROOT / name
        if not p.exists():
            continue
        for s in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("sources", []) or []:
            for t in (s or {}).get("tags", []) or []:
                t = str(t).strip().lower()
                if t and not t.startswith("via:") and t not in OWNERSHIP_TAGS and t not in LEAN_TAGS:
                    counts[t] += 1
    return sorted(t for t, n in counts.items() if n >= 5)


def _load_verified(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            if d.get("status") == "verified":
                rows.append(d)
    return rows


def _triage_row(v: dict) -> dict:
    return {
        "domain": v["domain"], "name": v.get("name", ""), "site_title": v.get("site_title", ""),
        "description": v.get("description", ""), "titles": list(v.get("titles", []))[:8],
        "country": v.get("country", ""), "language": v.get("language_detected", ""),
        "wikidata_type": v.get("source_type", ""),
    }


def prepare(verified_path: Path, out_dir: Path, *, batch_size: int = BATCH_SIZE) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [_triage_row(v) for v in _load_verified(verified_path)]
    canary_rows = [{k: c[k] for k in c if k != "expected"} for c in CANARIES]
    (out_dir / "canaries.json").write_text(json.dumps(CANARIES, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "vocabulary.json").write_text(json.dumps(_vocabulary(), indent=1), encoding="utf-8")
    batches = []
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        # canaries at two fixed positions, never first or last (a model attends to the edges)
        mixed = chunk[:1] + [canary_rows[0]] + chunk[1:-1] + [canary_rows[1]] + chunk[-1:] if len(chunk) > 2 else chunk + canary_rows
        p = out_dir / f"batch_{len(batches) + 1:04d}.json"
        p.write_text(json.dumps(mixed, indent=1, ensure_ascii=False), encoding="utf-8")
        batches.append(str(p))
    manifest = {"batches": batches, "rows": len(rows), "batch_size": batch_size,
                "canaries": str(out_dir / "canaries.json"), "vocabulary": str(out_dir / "vocabulary.json")}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def validate_result(batch_rows: list[dict], result: dict, vocabulary: set[str]) -> tuple[dict[str, dict], list[str]]:
    """``(answers_by_domain, problems)``. PURE. A problem is a reason the whole batch is
    untrusted; an individual row's out-of-vocabulary topic is DROPPED from that row (the row
    keeps its other fields) and noted, because the vocabulary is the model's leash, not the
    reviewer's."""
    problems: list[str] = []
    rows = result.get("rows") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        return {}, ["result has no rows list"]
    expected = {r["domain"] for r in batch_rows}
    by_domain: dict[str, dict] = {}
    for r in rows:
        if not isinstance(r, dict) or not r.get("domain"):
            problems.append("a row without a domain")
            continue
        d = str(r["domain"])
        if d not in expected:
            problems.append(f"unknown domain answered: {d}")
            continue
        if d in by_domain:
            problems.append(f"domain answered twice: {d}")
            continue
        if r.get("kind") not in KINDS or r.get("confidence") not in CONFIDENCES or not isinstance(r.get("journalism"), bool):
            problems.append(f"out-of-enum answer for {d}")
            continue
        topics = [t for t in (r.get("topics") or []) if isinstance(t, str) and t in vocabulary]
        r = dict(r, topics=topics[:3])
        by_domain[d] = r
    missing = expected - set(by_domain)
    if missing:
        problems.append(f"{len(missing)} row(s) unanswered")
    for c in CANARIES:
        a = by_domain.get(c["domain"])
        exp = c["expected"]
        if not a or a["journalism"] != exp["journalism"] or a["kind"] != exp["kind"]:
            problems.append(f"canary failed: {c['domain']}")
    return by_domain, problems


def merge(verified_path: Path, triage_dir: Path, out_path: Path, *, today: str) -> dict:
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "verify_candidate_feeds", Path(__file__).with_name("verify_candidate_feeds.py")
    )
    vcf = sys.modules.get(spec.name)
    if vcf is None:
        vcf = module_from_spec(spec)
        sys.modules[spec.name] = vcf  # the dataclass in it resolves its module through here
        spec.loader.exec_module(vcf)

    manifest = json.loads((triage_dir / "manifest.json").read_text(encoding="utf-8"))
    vocabulary = set(json.loads((triage_dir / "vocabulary.json").read_text(encoding="utf-8")))
    verified = {v["domain"]: v for v in _load_verified(verified_path)}
    canary_domains = {c["domain"] for c in CANARIES}

    entries: list[dict] = []
    rejections: list[tuple[str, str]] = []
    untrusted_batches: list[str] = []
    for b in manifest["batches"]:
        bp = Path(b)
        rp = bp.with_name(bp.name.replace(".json", ".result.json"))
        batch_rows = json.loads(bp.read_text(encoding="utf-8"))
        if not rp.exists():
            untrusted_batches.append(f"{bp.name}: no result file")
            for r in batch_rows:
                if r["domain"] not in canary_domains:
                    rejections.append((r["domain"], "batch_without_result"))
            continue
        try:
            result = json.loads(rp.read_text(encoding="utf-8"))
        except ValueError:
            result = {}
        answers, problems = validate_result(batch_rows, result, vocabulary)
        if problems:
            untrusted_batches.append(f"{bp.name}: " + "; ".join(problems[:4]))
            for r in batch_rows:
                if r["domain"] not in canary_domains:
                    rejections.append((r["domain"], "batch_untrusted"))
            continue
        for d, a in answers.items():
            if d in canary_domains:
                continue
            v = verified.get(d)
            if v is None:
                rejections.append((d, "not_in_verified"))
                continue
            if not a["journalism"]:
                rejections.append((d, f"not_journalism:{a['kind']}"))
                continue
            if a["confidence"] not in MERGEABLE_CONFIDENCE:
                rejections.append((d, "low_confidence"))
                continue
            verdict = vcf.Verdict(**{k: v[k] for k in v if k in vcf.Verdict.__dataclass_fields__})
            entry = vcf.to_catalogue_entry(verdict, today=today)
            entry["source_type"] = _SOURCE_TYPE_OF_KIND.get(a["kind"], "news")
            lang = a.get("language")
            if lang and lang != "unknown" and not verdict.language_detected:
                entry["language"] = lang  # the model's reading fills a gap, never overrides a detection
            for t in a.get("topics", []):
                if t not in entry["tags"]:
                    entry["tags"].append(t)
            entries.append(entry)
    header = (
        "# Candidate sources: feed-VERIFIED (verify_candidate_feeds.py) and model-TRIAGED as\n"
        "# journalism (triage_batches.py merge; canaries and vocabulary re-checked in code).\n"
        f"# {len(entries)} entries, {today}. Review, then merge with scripts/merge_source_batch.py.\n"
    )
    out_path.write_text(header + yaml.safe_dump({"sources": entries}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    with out_path.with_name("triage_rejections.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["domain", "reason"])
        w.writerows(rejections)
    summary = {
        "entries": len(entries), "rejected": len(rejections),
        "by_reason": dict(Counter(r for _, r in rejections)),
        "untrusted_batches": untrusted_batches,
    }
    out_path.with_name("triage_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("prepare")
    p1.add_argument("--verified", required=True, type=Path)
    p1.add_argument("--out-dir", required=True, type=Path)
    p1.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    p2 = sub.add_parser("merge")
    p2.add_argument("--verified", required=True, type=Path)
    p2.add_argument("--triage-dir", required=True, type=Path)
    p2.add_argument("--out", required=True, type=Path)
    p2.add_argument("--today", required=True, help="YYYY-MM-DD, the verification date")
    args = ap.parse_args(argv)
    if args.cmd == "prepare":
        m = prepare(args.verified, args.out_dir, batch_size=args.batch_size)
        print(json.dumps({k: v for k, v in m.items() if k != "batches"} | {"batches": len(m["batches"])}, indent=1))
    else:
        print(json.dumps(merge(args.verified, args.triage_dir, args.out, today=args.today), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
