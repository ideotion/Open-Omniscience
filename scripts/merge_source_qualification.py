#!/usr/bin/env python3
"""
Accumulate source-qualification verdicts from several instances into the shipped overlay.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer runs many instances; each exports what it measured
(``GET /api/diagnostics/source-qualification-export``). This merges those exports into
``configs/source_qualification.yml``, which ships and is adopted by every fresh install.

WHAT IT REFUSES TO DO, and why each refusal matters more than the convenience it costs:

  * IT NEVER RESOLVES A DISAGREEMENT. If one instance qualified a domain and another
    disqualified it, that is a finding -- possibly a site that changed, possibly a criteria
    difference, possibly a cohort that firmed up. It is REPORTED and the domain is left at
    whatever the existing overlay said (or omitted entirely if it said nothing), because
    picking a winner automatically would ship a verdict no human ever looked at, to every
    install, silently. ``--accept-newest`` exists for when the maintainer HAS looked and
    wants the newest verdict to win; it is never the default.

  * IT NEVER COUNTS AN ECHO AS CORROBORATION. A verdict an instance INHERITED (from a backup
    or an earlier overlay) is one measurement seen twice, not two -- so agreement is counted
    over ``basis: measured`` rows only. Without that, importing one backup into eight
    instances would manufacture eightfold "agreement" out of a single trial.

  * IT NEVER RE-STAMPS A DATE. ``qualified_at`` stays the date the verdict was REACHED.
    Refreshing it on merge would restart the six-month re-verification clock on every
    accumulation run, so a shipped verdict could never grow old enough to be re-checked --
    an expiry that never fires.

  * IT NEVER REWRITES A ROW IT WAS NOT GIVEN. Existing overlay entries the exports do not
    mention are carried through untouched, so merging one instance's export cannot silently
    drop what the others contributed.

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
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = _ROOT / "configs" / "source_qualification.yml"

SHIPPABLE = ("qualified", "disqualified")

# The all-diagnostics bundle writes every member flat at the archive root under this
# exact name (src/api/diagnostics.py's member table). Read it by name -- never by a
# glob, and never by falling back to whatever else in the archive looks close enough.
BUNDLE_MEMBER = "source-qualification-export.json"

# A ceiling on the member we decompress. The export is a few hundred KB even from the
# largest instance measured, so this is orders of magnitude of headroom -- and it is the
# only thing between an untrusted archive and a decompression bomb, since a zip's
# declared uncompressed size is cheap to inflate. Nothing is ever EXTRACTED to disk:
# the member is read into memory and parsed, so there is no path for an archive to
# write anywhere.
_MAX_MEMBER_BYTES = 64 * 1024 * 1024


def _rows_from_payload(raw: object, origin: str) -> list[dict]:
    rows = raw.get("verdicts") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise SystemExit(f"{origin}: no 'verdicts' list -- is this a source-qualification export?")
    return rows


def _load_export(path: Path) -> list[dict]:
    if zipfile.is_zipfile(path):
        # Say which flag to use rather than quietly treating it as a bundle. Guessing
        # would be convenient right up to the archive that is not one.
        raise SystemExit(
            f"{path} is a zip archive, not an export JSON. If it is an all-diagnostics "
            f"bundle, pass it as --from-bundle {path} (the export rides inside it as "
            f"{BUNDLE_MEMBER})."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: not valid JSON ({exc}).") from exc
    return _rows_from_payload(raw, str(path))


def _load_bundle(path: Path) -> list[dict]:
    """Read the qualification export out of an all-diagnostics bundle.

    A bundle whose export member did not complete carries a sidecar in its place
    (``<member>.error.txt`` or ``.skipped-deadline.txt``). That is a DIFFERENT problem
    from "wrong file" -- the instance is fine, its export run was not -- and the remedy
    differs, so it is reported as itself with the recorded reason, rather than folded
    into a generic not-found.
    """
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if BUNDLE_MEMBER not in names:
                for suffix in (".error.txt", ".skipped-deadline.txt"):
                    sidecar = BUNDLE_MEMBER + suffix
                    if sidecar in names:
                        detail = z.read(sidecar)[:2000].decode("utf-8", "replace").strip()
                        raise SystemExit(
                            f"{path}: this bundle's {BUNDLE_MEMBER} member did not "
                            f"complete on that instance, so the archive carries "
                            f"{sidecar} instead:\n  {detail}\n"
                            "There is nothing to merge from it -- re-run the export on "
                            "that instance."
                        )
                raise SystemExit(
                    f"{path}: no {BUNDLE_MEMBER} in this archive ({len(names)} member(s)) "
                    "-- is it an all-diagnostics bundle?"
                )
            declared = z.getinfo(BUNDLE_MEMBER).file_size
            if declared > _MAX_MEMBER_BYTES:
                raise SystemExit(
                    f"{path}: {BUNDLE_MEMBER} declares {declared} bytes uncompressed, "
                    f"past the {_MAX_MEMBER_BYTES} ceiling. Refusing to decompress it."
                )
            raw_bytes = z.read(BUNDLE_MEMBER)
    except zipfile.BadZipFile as exc:
        raise SystemExit(f"{path}: not a readable zip archive ({exc}).") from exc
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: {BUNDLE_MEMBER} is not valid JSON ({exc}).") from exc
    return _rows_from_payload(raw, f"{path}::{BUNDLE_MEMBER}")


def _load_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        str(r["domain"]): r
        for r in (raw.get("verdicts") or [])
        if isinstance(r, dict) and r.get("domain")
    }


def _stamp(row: dict) -> str:
    """Sort key for 'newest verdict'. A row with no date sorts oldest, so a dateless verdict
    can never win a disagreement by default -- being undated is not being recent."""
    return str(row.get("qualified_at") or "")


def merge(exports: list[list[dict]], existing: dict[str, dict], *, accept_newest: bool) -> dict:
    """Pure core: existing overlay + N exports -> merged overlay + a report."""
    proposed: dict[str, list[dict]] = defaultdict(list)
    skipped = 0
    for rows in exports:
        for row in rows:
            domain = str(row.get("domain") or "").strip().lower()
            if not domain or row.get("status") not in SHIPPABLE:
                skipped += 1
                continue
            proposed[domain].append(row)

    merged = dict(existing)
    added: list[str] = []
    updated: list[str] = []
    unchanged = 0
    conflicts: list[dict] = []

    for domain, rows in sorted(proposed.items()):
        # Agreement is counted over MEASURED rows only -- an inherited row is an echo.
        measured = [r for r in rows if r.get("basis", "measured") == "measured"]
        verdicts = {r["status"] for r in (measured or rows)}
        if len(verdicts) > 1:
            conflicts.append({
                "domain": domain,
                "verdicts": sorted(verdicts),
                "measured_by": len(measured),
                "resolution": "newest" if accept_newest else "left as-is (needs review)",
            })
            if not accept_newest:
                continue
        winner = max(measured or rows, key=_stamp)
        entry = {
            "domain": domain,
            "status": winner["status"],
            # NEVER re-stamped -- see the module docstring.
            "qualified_at": winner.get("qualified_at"),
            "criteria_version": winner.get("criteria_version"),
        }
        prior = existing.get(domain)
        if prior is None:
            added.append(domain)
        elif {k: prior.get(k) for k in entry} != entry:
            updated.append(domain)
        else:
            unchanged += 1
            continue
        merged[domain] = entry

    return {
        "merged": merged,
        "report": {
            "exports": len(exports),
            "domains_proposed": len(proposed),
            "added": len(added),
            "updated": len(updated),
            "unchanged": unchanged,
            "carried_through_untouched": len(set(existing) - set(proposed)),
            "conflicts": conflicts,
            "skipped_rows": skipped,
        },
    }


def render(merged: dict[str, dict]) -> str:
    doc = {
        "generated_at": datetime.now(UTC).date().isoformat(),
        "verdicts": [merged[d] for d in sorted(merged)],
    }
    header = (
        "# Source qualification verdicts, EARNED BY MEASUREMENT on real instances.\n"
        "# Merged by scripts/merge_source_qualification.py from per-instance exports\n"
        "# (GET /api/diagnostics/source-qualification-export). Do not hand-edit.\n"
        "# A domain absent from this file ships unqualified and is judged by the install's\n"
        "# own first qualification pass, exactly as before this file existed.\n"
    )
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


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
