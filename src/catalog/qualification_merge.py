"""
Accumulate source-qualification verdicts from several instances -- the PURE core.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

B5 (2026-09-15, register artifact; complements Q1106 = a): the export + merge run
"becomes an automated diagnostics action, not an operator script". This module is the
half that had to move for that to be true -- the merge logic and the bundle reader,
lifted out of ``scripts/merge_source_qualification.py`` with their behaviour unchanged,
so that the CLI and ``POST /api/diagnostics/source-qualification-merge`` run ONE
implementation instead of two that agree today.

THE SPLIT IS BY INPUT, NOT BY CONVENIENCE. Everything here works on BYTES and returns
data: what a merge decides can then be tested, and driven from an upload, without a
filesystem. The script keeps the path handling (its ``--from-bundle`` flag, its
``SystemExit`` exit codes, its ``-o`` write), because those are a command line's job and
an endpoint has no use for them.

WHAT IT REFUSES TO DO, and why each refusal matters more than the convenience it costs:

  * IT NEVER RESOLVES A DISAGREEMENT. If one instance qualified a domain and another
    disqualified it, that is a finding -- possibly a site that changed, possibly a
    criteria difference, possibly a cohort that firmed up. It is REPORTED and the domain
    is left at whatever the existing overlay said, because picking a winner automatically
    would ship a verdict no human ever looked at, to every install, silently.
    ``accept_newest`` exists for when the maintainer HAS looked; it is never the default.

  * IT NEVER COUNTS AN ECHO AS CORROBORATION. A verdict an instance INHERITED is one
    measurement seen twice, not two -- so agreement is counted over ``basis: measured``
    rows only. Without that, importing one backup into eight instances would manufacture
    eightfold "agreement" out of a single trial.

  * IT NEVER RE-STAMPS A DATE. ``qualified_at`` stays the date the verdict was REACHED.
    Refreshing it on merge would restart the six-month re-verification clock on every
    accumulation run, so a shipped verdict could never grow old enough to be re-checked.

  * IT NEVER REWRITES A ROW IT WAS NOT GIVEN. Existing overlay entries the exports do not
    mention are carried through untouched, so merging one instance's export cannot
    silently drop what the others contributed.

  * IT NEVER WRITES THE SHIPPED FILE. ``render`` returns text. The overlay stays
    operator-generated (brief S04-12 S2): the CLI writes it because an operator asked for
    that on their own machine, and the diagnostics action hands it back as a download to
    review and commit. An endpoint that wrote into ``configs/`` would be the app editing
    what it ships, which is nobody's decision to automate.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections import defaultdict
from datetime import UTC, datetime

import yaml

SHIPPABLE = ("qualified", "disqualified")

# The all-diagnostics bundle writes every member flat at the archive root under this
# exact name (the diagnostics package's member table). Read it by name -- never by a
# glob, and never by falling back to whatever else in the archive looks close enough.
BUNDLE_MEMBER = "source-qualification-export.json"

# A ceiling on the member we decompress. The export is a few hundred KB even from the
# largest instance measured, so this is orders of magnitude of headroom -- and it is the
# only thing between an untrusted archive and a decompression bomb, since a zip's
# declared uncompressed size is cheap to inflate. Nothing is ever EXTRACTED to disk: the
# member is read into memory and parsed, so there is no path for an archive to write
# anywhere. The callers pass their own limit so each can be driven against a small one
# in a test without writing gigabytes.
MAX_MEMBER_BYTES = 64 * 1024 * 1024


class MergeInputError(ValueError):
    """An input this merge will not read, with the reason a human can act on.

    A DOMAIN error rather than ``SystemExit``: the same refusals have to reach a command
    line as an exit code AND an HTTP caller as a 400, and a core that raises ``SystemExit``
    would tear down a web worker on a bad upload. The CLI converts; nothing is softened.
    """


def rows_from_payload(raw: object, origin: str) -> list[dict]:
    rows = raw.get("verdicts") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise MergeInputError(
            f"{origin}: no 'verdicts' list -- is this a source-qualification export?"
        )
    return rows


def rows_from_export_bytes(data: bytes, origin: str) -> list[dict]:
    """One instance's export JSON -> its verdict rows.

    A zip is refused BY NAME rather than sniffed and treated as a bundle: guessing is
    convenient right up to the archive that is not one.
    """
    if data[:4] == b"PK\x03\x04" or zipfile.is_zipfile(io.BytesIO(data)):
        raise MergeInputError(
            f"{origin} is a zip archive, not an export JSON. If it is an all-diagnostics "
            f"bundle, hand it over as a bundle (the export rides inside it as "
            f"{BUNDLE_MEMBER})."
        )
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MergeInputError(f"{origin}: not valid JSON ({exc}).") from exc
    return rows_from_payload(raw, origin)


def rows_from_bundle_bytes(
    data: bytes, origin: str, *, max_member_bytes: int = MAX_MEMBER_BYTES,
) -> list[dict]:
    """The qualification export out of an all-diagnostics bundle.

    A bundle whose export member did not complete carries a sidecar in its place
    (``<member>.error.txt`` or ``.skipped-deadline.txt``). That is a DIFFERENT problem
    from "wrong file" -- the instance is fine, its export run was not -- and the remedy
    differs, so it is reported as itself with the recorded reason rather than folded into
    a generic not-found.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            if BUNDLE_MEMBER not in names:
                for suffix in (".error.txt", ".skipped-deadline.txt"):
                    sidecar = BUNDLE_MEMBER + suffix
                    if sidecar in names:
                        detail = z.read(sidecar)[:2000].decode("utf-8", "replace").strip()
                        raise MergeInputError(
                            f"{origin}: this bundle's {BUNDLE_MEMBER} member did not "
                            f"complete on that instance, so the archive carries "
                            f"{sidecar} instead:\n  {detail}\n"
                            "There is nothing to merge from it -- re-run the export on "
                            "that instance."
                        )
                raise MergeInputError(
                    f"{origin}: no {BUNDLE_MEMBER} in this archive ({len(names)} member(s)) "
                    "-- is it an all-diagnostics bundle?"
                )
            declared = z.getinfo(BUNDLE_MEMBER).file_size
            if declared > max_member_bytes:
                raise MergeInputError(
                    f"{origin}: {BUNDLE_MEMBER} declares {declared} bytes uncompressed, "
                    f"past the {max_member_bytes} ceiling. Refusing to decompress it."
                )
            raw_bytes = z.read(BUNDLE_MEMBER)
    except zipfile.BadZipFile as exc:
        raise MergeInputError(f"{origin}: not a readable zip archive ({exc}).") from exc
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise MergeInputError(
            f"{origin}: {BUNDLE_MEMBER} is not valid JSON ({exc})."
        ) from exc
    return rows_from_payload(raw, f"{origin}::{BUNDLE_MEMBER}")


def existing_from_text(text: str) -> dict[str, dict]:
    """The overlay already on disk (or shipped), keyed by domain. Empty text = no rows,
    which is how a first merge starts and is not an error."""
    raw = yaml.safe_load(text) or {} if text.strip() else {}
    return {
        str(r["domain"]): r
        for r in ((raw.get("verdicts") or []) if isinstance(raw, dict) else [])
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
