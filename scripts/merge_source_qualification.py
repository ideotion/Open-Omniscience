#!/usr/bin/env python3
"""
Accumulate source-qualification verdicts from several instances into the shipped overlay.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer runs many instances; each exports what it measured
(``GET /api/diagnostics/source-qualification-export``). This merges those exports into
``configs/source_qualification.yml``, which ships and is adopted by every fresh install.

THIS FILE IS NOW THE COMMAND LINE ONLY. The merge itself -- the four refusals, the
report, the rendering, the bundle reader -- lives in ``src.catalog.qualification_merge``,
because B5 (2026-09-15) makes the same run available as a diagnostics action and two
copies of a rule about what may ship to every install is one copy too many. Behaviour,
flags and exit codes are unchanged; ``MergeInputError`` is converted to ``SystemExit``
here, where a command line wants it.

The refusals, in short (the module documents each in full): it never resolves a
disagreement, never counts an inherited verdict as corroboration, never re-stamps a
date, and never rewrites a row it was not given.

TWO WAYS IN, same data either way. An instance can hand over the export on its own
(``GET /api/diagnostics/source-qualification-export``), or the whole all-diagnostics
bundle, which already carries that export as a member -- so a maintainer who collected
bundles for some other reason does not have to go back and re-export. ``--from-bundle``
reads the member out of the zip; nothing else about the merge changes.

USAGE
    python scripts/merge_source_qualification.py export1.json [export2.json ...] \\
        [--from-bundle oo-all-diagnostics-*.zip ...] \\
        [-o configs/source_qualification.yml] [--dry-run] [--accept-newest]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:  # run from anywhere, including a bare checkout
    sys.path.insert(0, str(_ROOT))

from src.catalog.qualification_merge import (  # noqa: E402
    BUNDLE_MEMBER,
    MAX_MEMBER_BYTES,
    SHIPPABLE,
    MergeInputError,
    existing_from_text,
    merge,
    render,
)

DEFAULT_OUT = _ROOT / "configs" / "source_qualification.yml"

# The module's ceiling, re-exported so it can be lowered for one run (a test drives the
# refusal by compressing the ceiling rather than by writing gigabytes). It is PASSED to
# the reader rather than read by it, so lowering it here actually takes effect.
_MAX_MEMBER_BYTES = MAX_MEMBER_BYTES

__all__ = [
    "BUNDLE_MEMBER", "DEFAULT_OUT", "SHIPPABLE", "main", "merge", "render",
]


def _load_export(path: Path) -> list[dict]:
    from src.catalog.qualification_merge import rows_from_export_bytes

    try:
        return rows_from_export_bytes(path.read_bytes(), str(path))
    except MergeInputError as exc:
        # The zip refusal names the flag on a command line; the module cannot, because it
        # has no flags. Same refusal, said in the reader's own vocabulary.
        msg = str(exc).replace(
            "hand it over as a bundle", f"pass it as --from-bundle {path}"
        )
        raise SystemExit(msg) from exc


def _load_bundle(path: Path) -> list[dict]:
    from src.catalog.qualification_merge import rows_from_bundle_bytes

    try:
        return rows_from_bundle_bytes(
            path.read_bytes(), str(path), max_member_bytes=_MAX_MEMBER_BYTES
        )
    except MergeInputError as exc:
        raise SystemExit(str(exc)) from exc


def _load_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return existing_from_text(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "exports", nargs="*", type=Path,
        help="per-instance export JSON files (GET /api/diagnostics/source-qualification-export)",
    )
    ap.add_argument(
        "--from-bundle", action="append", default=[], type=Path, metavar="BUNDLE.zip",
        help=f"read the export out of an all-diagnostics bundle instead (its {BUNDLE_MEMBER} "
             "member). Repeatable, and mixes freely with positional export files",
    )
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    ap.add_argument(
        "--accept-newest", action="store_true",
        help="resolve disagreements in favour of the newest verdict (never the default: a "
             "disagreement is a finding, and an auto-resolved one ships unreviewed)",
    )
    args = ap.parse_args(argv)
    # ``exports`` went from required to optional so a bundle-only run is possible; that
    # makes "no inputs at all" reachable, and it must fail loudly rather than write an
    # overlay from nothing.
    if not args.exports and not args.from_bundle:
        ap.error("give at least one export JSON, or --from-bundle BUNDLE.zip, or both")

    out = merge(
        [_load_export(p) for p in args.exports] + [_load_bundle(p) for p in args.from_bundle],
        _load_existing(args.out),
        accept_newest=args.accept_newest,
    )
    report = out["report"]
    # Where the merged rows came from. Recorded in the printed artifact because an
    # overlay reviewed weeks later should say how many instances it rests on and by
    # which route, and the pure core deliberately does not know.
    report["sources"] = {
        "export_files": len(args.exports),
        "bundles": len(args.from_bundle),
    }
    print(json.dumps(report, indent=2))
    if report["conflicts"] and not args.accept_newest:
        print(
            f"\n{len(report['conflicts'])} domain(s) disagree across instances and were left "
            "unchanged. Review them, then re-run with --accept-newest if the newest verdict "
            "should win.",
            file=sys.stderr,
        )
    if args.dry_run:
        print("\n(dry run -- nothing written)", file=sys.stderr)
        return 0
    args.out.write_text(render(out["merged"]), encoding="utf-8")
    print(f"\nwrote {len(out['merged'])} verdict(s) to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
