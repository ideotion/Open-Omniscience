#!/usr/bin/env python3
"""Measure the rule topic tagger on the labelled law-titles sample (v0.6.0 row C, Q913).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

OFFLINE: reads the labelled sample (``src/catalog/data/topic_sample_law_titles.json``) and ONE
operator-built thesaurus artifact (default ``src/catalog/data/skos/eurovoc.json``, written by
``src.catalog.skos.build_artifact`` after the licence fetch). Nothing here opens a socket.

Prints, as JSON: the measurement (``src.catalog.topic_tagging.measure``, with the ≈ share and
``n`` on every figure), the sample labels the thesaurus does not carry (``unresolved``, never
matched loosely), and the thesaurus's own vintage and licence. With no artifact built it prints
``"status": "not-measured"`` with the reason and exits 3, so "not measured yet" can never be
read as a figure.

Usage:  python scripts/topic_sample_measure.py [--artifact PATH] [--sample PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.catalog import skos  # noqa: E402
from src.catalog import topic_tagging as tt  # noqa: E402

DEFAULT_SAMPLE = ROOT / "src" / "catalog" / "data" / "topic_sample_law_titles.json"
DEFAULT_ARTIFACT = ROOT / "src" / "catalog" / "data" / "skos" / "eurovoc.json"
NOT_MEASURED = 3


def run(artifact_path: Path, sample_path: Path) -> tuple[int, dict[str, Any]]:
    doc = json.loads(sample_path.read_text(encoding="utf-8"))
    head = {"sample": str(sample_path.relative_to(ROOT)) if sample_path.is_relative_to(ROOT) else str(sample_path),
            "sample_as_of": doc.get("as_of"), "labelled_by": doc.get("labelled_by"), "n_sample": len(doc["items"])}
    if not artifact_path.exists():
        return NOT_MEASURED, {**head, "status": "not-measured",
                              "reason": f"no thesaurus artifact at {artifact_path.name}: it is built by the operator "
                                        "after the licence fetch (S06-02 S4), and nothing is measured without it"}
    try:
        art = skos.load_artifact(artifact_path)
    except (OSError, ValueError) as exc:  # SkosError is a ValueError; a JSON error is one too
        return NOT_MEASURED, {**head, "status": "not-measured", "reason": f"the artifact could not be read: {exc}"}
    res = tt.resolve_sample(doc["items"], art)
    m = tt.measure(res["sample"], tt.Index([art]))
    return 0, {**head, "status": "measured", "scheme": art.get("scheme"), "vintage": art.get("vintage"),
               "license": art.get("license"), "resolved_labels": res["resolved"], "unresolved": res["unresolved"],
               "measurement": m}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    ap.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    a = ap.parse_args(argv)
    code, out = run(a.artifact, a.sample)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    sys.exit(main())
