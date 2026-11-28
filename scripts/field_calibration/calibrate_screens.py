#!/usr/bin/env python3
"""Row 453 (R846): calibrate the stub screens and the proposed door rules against field samples.

Calibration only: it marks nothing, writes nothing to any corpus, and fetches nothing.

What it runs, on every article of the source-samples export (one seeded-random stored article per
source, the same set as quality.md section 1.2), with main's own code:

  S1  paywall_stub / menu_stub  src.ingest.furniture.stub_verdict on thin bodies (word_count < 100),
                                after the URL-shape rules, exactly as the quarantine job's include_stubs
  S2  non-article (stored)      the quarantine job's default screen: URL-shape rules, then the prose gate
                                on bodies >= 100 words
  S3  non-article (door)        classify_non_article(door=True) with the body: S2 plus the bare-homepage
                                and feed-path shapes the ingest door already applies
  S4  raw HTML                  count of real tags (the keyword extractor's own _MARKUP_TAG_RE) in the
                                stored body; fires at >= 3, >= 10 and >= 30 tags (three candidate thresholds)

With a LABELS file (JSONL, one object per labelled article: {"instance": "<label>", "article_id": N,
"category": "<one of CATEGORIES>"}), it cross-tabulates every screen against the hand labels and gives
precision and the false-positive count per screen, with Wilson 95% intervals.

Output is AGGREGATE ONLY: counts and rates per instance and screen. No text, titles, domains or ids
are printed. With --private-dir it also writes, per screen, the ids it fired on (private, for a reader
to check by hand); that directory must stay on the analysing machine.

Usage (run with -I, from a folder outside the data):
  python3 -I calibrate_screens.py REPO DATA_ROOT INSTANCES_JSON [--labels LABELS.jsonl] [--private-dir DIR]
REPO is a checkout of main (the screens are imported from it, read-only).
DATA_ROOT/INSTANCES_JSON are the same inputs as docs/field-analysis-2026-11/scripts.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from collections import Counter, defaultdict

CATEGORIES = {
    "ok": "keep",
    "ok_furniture": "keep",
    "reference": "keep",
    "stub": "junk",
    "consent_wall": "junk",
    "bot_wall": "junk",
    "non_article": "junk",
}
TAG_THRESHOLDS = (3, 10, 30)


def wilson(k: int, n: int) -> str:
    if n == 0:
        return "n=0"
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{100 * p:.1f}% [{100 * max(0, c - h):.1f}-{100 * min(1, c + h):.1f}]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("data_root")
    ap.add_argument("instances_json")
    ap.add_argument("--labels")
    ap.add_argument("--private-dir")
    args = ap.parse_args()

    sys.path.insert(0, os.path.abspath(args.repo))
    os.environ.setdefault(
        "OO_DB_PLAINTEXT", "1"
    )  # nothing is opened; some imports read the setting
    from src.analytics.extract import _MARKUP_TAG_RE
    from src.ingest.furniture import stub_verdict
    from src.ingest.non_article import _ARTICLE_MIN_WORDS, classify_non_article
    from src.services.prose_gate import prose_gate_verdict

    with open(args.instances_json, encoding="utf-8") as fh:
        instances = json.load(fh)
    labels: dict[tuple[str, int], str] = {}
    if args.labels:
        with open(args.labels, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        for r in rows:
            cat = r["category"]
            if cat not in CATEGORIES:
                raise SystemExit(f"unknown category {cat!r}; expected one of {sorted(CATEGORIES)}")
            labels[(r["instance"], int(r["article_id"]))] = cat

    screens = ["S1_paywall_stub", "S1_menu_stub", "S2_stored", "S3_door"] + [
        f"S4_html_ge{t}" for t in TAG_THRESHOLDS
    ]
    fires: dict[str, Counter] = defaultdict(Counter)  # instance -> screen -> count
    totals: Counter = Counter()
    thin: Counter = Counter()
    s2_reasons: dict[str, Counter] = defaultdict(Counter)
    s3_reasons: dict[str, Counter] = defaultdict(Counter)
    xtab: dict[str, Counter] = defaultdict(Counter)  # screen -> (category) count, labelled only
    lab_n: Counter = Counter()
    private: dict[str, list] = defaultdict(list)
    unread = Counter()

    for folder, inst in instances.items():
        for f in sorted(glob.glob(f"{args.data_root}/{folder}/*source-samples-*/samples/*.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError):
                unread[inst] += 1
                continue
            a = doc.get("article") or {}
            if a.get("body_withheld"):
                unread[inst] += 1
                continue
            aid = a.get("id")
            text = a.get("content") or ""
            url = a.get("url") or ""
            wc = a.get("word_count")
            if wc is None:
                wc = len(text.split())
            lang = a.get("language") or a.get("detected_language")
            totals[inst] += 1
            hit: set[str] = set()

            # S1 + S2, the quarantine job's own order
            v = classify_non_article(url, word_count=wc)
            sig = v.signal if v is not None else None
            if sig is None and wc >= _ARTICLE_MIN_WORDS:
                pv = prose_gate_verdict(text, language=lang)
                sig = pv.signal if pv is not None else None
            if sig is not None:
                hit.add("S2_stored")
                s2_reasons[inst][sig] += 1
            if wc < _ARTICLE_MIN_WORDS:
                thin[inst] += 1
                if sig is None:
                    st = stub_verdict(text)
                    if st is not None:
                        hit.add(f"S1_{st[0]}")
            # S3, the door's rules with the body
            dv = classify_non_article(url, text=text, word_count=wc, language=lang, door=True)
            if dv is not None:
                hit.add("S3_door")
                s3_reasons[inst][dv.signal] += 1
            # S4
            tags = sum(1 for _ in _MARKUP_TAG_RE.finditer(text[:200_000]))
            for t in TAG_THRESHOLDS:
                if tags >= t:
                    hit.add(f"S4_html_ge{t}")

            for s in hit:
                fires[inst][s] += 1
                if args.private_dir:
                    private[s].append([inst, aid])
            cat = labels.get((inst, int(aid))) if aid is not None else None
            if cat is not None:
                lab_n[cat] += 1
                for s in screens:
                    if s in hit:
                        xtab[s][cat] += 1

    insts = list(instances.values())
    print("## Fires per source (share of sampled sources)\n")
    print("| screen | " + " | ".join(insts) + " | all |")
    print("|---|" + "---:|" * (len(insts) + 1))
    for s in screens:
        cells = [wilson(fires[i][s], totals[i]) + f" ({fires[i][s]})" for i in insts]
        k, n = sum(fires[i][s] for i in insts), sum(totals[i] for i in insts)
        print(f"| {s} | " + " | ".join(cells) + f" | {wilson(k, n)} ({k}) |")
    print(
        "| sampled sources | "
        + " | ".join(str(totals[i]) for i in insts)
        + f" | {sum(totals.values())} |"
    )
    print(
        "| of which thin (< 100 words) | "
        + " | ".join(str(thin[i]) for i in insts)
        + f" | {sum(thin.values())} |"
    )
    print(
        "| not read (body withheld or unreadable) | "
        + " | ".join(str(unread[i]) for i in insts)
        + f" | {sum(unread.values())} |"
    )
    for name, rs in (("S2 by reason", s2_reasons), ("S3 by reason", s3_reasons)):
        allr = Counter()
        for i in insts:
            allr.update(rs[i])
        print(f"\n{name}: " + ", ".join(f"{k} {v}" for k, v in allr.most_common()))

    if labels:
        keep_n = sum(n for c, n in lab_n.items() if CATEGORIES[c] == "keep")
        junk_n = sum(n for c, n in lab_n.items() if CATEGORIES[c] == "junk")
        print(
            f"\n## Against the hand labels ({sum(lab_n.values())} matched of {len(labels)} labels; keep {keep_n}, junk {junk_n})\n"
        )
        print(
            "| screen | fired | on junk | on keep (false positives) | precision [95%] | junk caught [95%] | FP rate on keep [95%] |"
        )
        print("|---|---:|---:|---:|---:|---:|---:|")
        for s in screens:
            on_junk = sum(v for c, v in xtab[s].items() if CATEGORIES[c] == "junk")
            on_keep = sum(v for c, v in xtab[s].items() if CATEGORIES[c] == "keep")
            fired = on_junk + on_keep
            print(
                f"| {s} | {fired} | {on_junk} | {on_keep} | {wilson(on_junk, fired)} | {wilson(on_junk, junk_n)} | {wilson(on_keep, keep_n)} |"
            )
        print(
            "\nfalse positives by category: "
            + "; ".join(
                f"{s}: "
                + ", ".join(f"{c} {v}" for c, v in xtab[s].items() if CATEGORIES[c] == "keep")
                for s in screens
                if any(CATEGORIES[c] == "keep" for c in xtab[s])
            )
            or "none"
        )

    if args.private_dir:
        os.makedirs(args.private_dir, mode=0o700, exist_ok=True)
        with open(os.path.join(args.private_dir, "fired-ids.json"), "w", encoding="utf-8") as out:
            json.dump(private, out)
        print(
            f"\nprivate: fired ids per screen written to {args.private_dir}/fired-ids.json (keep it local)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
