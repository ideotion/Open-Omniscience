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
import re
import zipfile
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

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

    RAISED AS A KEYED FRAME (the 2026-09-27 re-walk, S-6). The Quality gates panel shows
    this refusal under a translated button, and as English prose it read "…: no 'verdicts'
    list" on a French page. So the error carries its frame (``i18n``, a key in all twelve
    locales) and its values (``vars``): the file name, the archive member and a parser's
    own message are DATA slots, never translated, and a number is formatted by the client.
    ``str(exc)`` is the frame filled in English -- exactly what the command line prints,
    so the two front doors still say one thing.
    """

    def __init__(self, frame: str, **values: Any) -> None:
        self.i18n = frame
        self.vars = values
        super().__init__(_fill(frame, values))


def _fill(frame: str, values: dict[str, Any]) -> str:
    """The frame in English: every ``{slot}`` replaced by its value as given."""
    return re.sub(r"\{(\w+)\}",
                  lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0),
                  frame)


def refusal_payload(frame: str, **values: Any) -> dict[str, Any]:
    """A refusal as an HTTP caller receives it: the English ``detail`` a command line
    prints, beside the ``detail_i18n`` / ``detail_vars`` a translated surface renders."""
    return {"detail": _fill(frame, values), "detail_i18n": frame, "detail_vars": values}


# Every frame this module refuses with -- the list the ×12 test keys. Kept as constants so
# the test reads the frames the code raises rather than a re-typed copy of them.
REFUSE_NO_VERDICTS = "{file}: no 'verdicts' list — is this a source-qualification export?"
REFUSE_ZIP_AS_EXPORT = (
    "{file} is a zip archive, not an export JSON. If it is an all-diagnostics bundle, hand "
    "it over as a bundle (the export rides inside it as {member})."
)
REFUSE_NOT_TEXT = "{file}: not valid JSON or YAML ({error})."
REFUSE_NOT_JSON_OR_YAML = "{file}: not valid JSON ({error}), and not valid YAML either."
REFUSE_OVERLAY = (
    "{file} reads as an overlay (a merged or shipped source_qualification.yml), not an "
    "instance's export: its rows carry no 'basis', so this merge could not tell a "
    "measurement from an echo of one. Upload what Export produced on each instance, or "
    "that instance's all-diagnostics bundle."
)
REFUSE_MEMBER_FAILED = (
    "{file}: this bundle's {member} member did not complete on that instance, so the "
    "archive carries {sidecar} instead ({detail}). There is nothing to merge from it — "
    "re-run the export on that instance."
)
REFUSE_NO_MEMBER = (
    "{file}: no {member} in this archive ({n} member(s)) — is it an all-diagnostics bundle?"
)
REFUSE_MEMBER_TOO_BIG = (
    "{file}: {member} declares {size} bytes uncompressed, past the {limit} ceiling. "
    "Refusing to decompress it."
)
REFUSE_BAD_ZIP = "{file}: not a readable zip archive ({error})."
REFUSE_MEMBER_NOT_JSON = "{file}: {member} is not valid JSON ({error})."
# The three the diagnostics route makes itself, before or around this core: they live
# here with the rest so every merge refusal is one list, keyed once.
REFUSE_TOO_MANY = (
    "{n} files were sent; this run reads at most {limit}. Merge them in batches — each run "
    "carries the previous overlay through untouched, so batching loses nothing."
)
REFUSE_TOO_BIG = "{file}: {size} bytes, past the {limit} ceiling. Refusing to read it."
REFUSE_NOTHING = (
    "Nothing to merge: no exports were uploaded and this instance's own verdicts were "
    "excluded. Writing an overlay from nothing would replace the shipped file with an "
    "empty one."
)
REFUSAL_FRAMES = (
    REFUSE_NO_VERDICTS, REFUSE_ZIP_AS_EXPORT, REFUSE_NOT_TEXT, REFUSE_NOT_JSON_OR_YAML,
    REFUSE_OVERLAY, REFUSE_MEMBER_FAILED, REFUSE_NO_MEMBER, REFUSE_MEMBER_TOO_BIG,
    REFUSE_BAD_ZIP, REFUSE_MEMBER_NOT_JSON, REFUSE_TOO_MANY, REFUSE_TOO_BIG, REFUSE_NOTHING,
)


def rows_from_payload(raw: object, origin: str) -> list[dict]:
    rows = raw.get("verdicts") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        raise MergeInputError(REFUSE_NO_VERDICTS, file=origin)
    return rows


def repair_record_flags(basis: object) -> dict:
    """What an export's ``basis`` block says about the boot repair's record, for the merge report.

    ``{}`` when the record was read in full. Otherwise the input is marked
    ``repair_record_unreadable`` (with the run ids when they are known): the rows an unreadable run
    withdrew cannot be named, so they count below as ``measured`` corroboration although an imported
    history decided them. The merge only counts ``basis: measured`` rows, so this has to travel
    beside them; it changes no verdict and refuses nothing.
    """
    if not isinstance(basis, dict) or not basis.get("repair_record_unreadable"):
        return {}
    runs = basis.get("repair_runs_unreadable")
    return {
        "repair_record_unreadable": True,
        "repair_runs_unreadable": [str(r) for r in runs] if isinstance(runs, list) else [],
    }


def repair_record_flags_of_export_bytes(data: bytes) -> dict:
    """:func:`repair_record_flags` of an uploaded export, JSON or the Export button's YAML (which carries
    the ``basis`` block as a top-level key only when the record was unreadable). Anything that does not
    parse as a mapping has no ``basis`` to read: ``{}``, never a refusal -- the rows were already
    accepted by the time this runs."""
    try:
        text = data.decode("utf-8")
        try:
            payload = json.loads(text)
        except ValueError:
            payload = yaml.safe_load(text)
    except (UnicodeDecodeError, yaml.YAMLError):
        return {}
    return repair_record_flags(payload.get("basis")) if isinstance(payload, dict) else {}


def repair_record_flags_of_bundle_bytes(data: bytes) -> dict:
    """The same flags out of an all-diagnostics bundle's qualification export member (``{}`` when it is
    absent or unreadable: the refusal for that is :func:`rows_from_bundle_bytes`'s, not this one's)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if BUNDLE_MEMBER not in z.namelist():
                return {}
            return repair_record_flags_of_export_bytes(z.read(BUNDLE_MEMBER))
    except (zipfile.BadZipFile, OSError, KeyError, RuntimeError):
        return {}


def rows_from_export_bytes(data: bytes, origin: str) -> list[dict]:
    """One instance's export -> its verdict rows: the JSON the diagnostics carry, or the
    YAML the Quality gates panel's Export button saves (``fmt=yaml``). Both hold the same
    ``verdicts`` rows, ``basis`` included, so the one loop the panel offers -- Export on
    each instance, then Merge -- has to accept what its own first half produces (the
    2026-09-26 click-through, S1: it refused it as "not valid JSON").

    A zip is refused BY NAME rather than sniffed and treated as a bundle: guessing is
    convenient right up to the archive that is not one.
    """
    if data[:4] == b"PK\x03\x04" or zipfile.is_zipfile(io.BytesIO(data)):
        raise MergeInputError(REFUSE_ZIP_AS_EXPORT, file=origin, member=BUNDLE_MEMBER)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MergeInputError(REFUSE_NOT_TEXT, file=origin, error=str(exc)) from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as json_exc:
        return _rows_from_export_yaml(text, origin, json_exc)
    return rows_from_payload(raw, origin)


def _rows_from_export_yaml(text: str, origin: str, json_exc: json.JSONDecodeError) -> list[dict]:
    """The Export button's YAML -> its rows, refusing an OVERLAY that looks like one.

    AN OVERLAY IS NOT AN EXPORT, and the two share a file name. A merged or shipped
    ``source_qualification.yml`` carries no ``basis`` on its rows, and the merge reads a
    missing ``basis`` as ``measured`` -- so feeding a previous merge back in would count
    every verdict it holds as a fresh measurement: the echo the module refuses to count
    as corroboration. An export writes ``basis`` on every row, so a row without one is
    refused by name rather than guessed at.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise MergeInputError(REFUSE_NOT_JSON_OR_YAML, file=origin, error=str(json_exc)) from exc
    rows = rows_from_payload(raw, origin)
    if any(isinstance(r, dict) and "basis" not in r for r in rows):
        raise MergeInputError(REFUSE_OVERLAY, file=origin)
    for r in rows:
        # An unquoted timestamp loads as a datetime; the merge compares and re-renders
        # the date as the string the export wrote, never as an object.
        if isinstance(r, dict) and isinstance(r.get("qualified_at"), (date, datetime)):
            r["qualified_at"] = r["qualified_at"].isoformat()
    return rows


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
                            REFUSE_MEMBER_FAILED, file=origin, member=BUNDLE_MEMBER,
                            sidecar=sidecar, detail=detail,
                        )
                raise MergeInputError(
                    REFUSE_NO_MEMBER, file=origin, member=BUNDLE_MEMBER, n=len(names)
                )
            declared = z.getinfo(BUNDLE_MEMBER).file_size
            if declared > max_member_bytes:
                raise MergeInputError(
                    REFUSE_MEMBER_TOO_BIG, file=origin, member=BUNDLE_MEMBER,
                    size=declared, limit=max_member_bytes,
                )
            raw_bytes = z.read(BUNDLE_MEMBER)
    except zipfile.BadZipFile as exc:
        raise MergeInputError(REFUSE_BAD_ZIP, file=origin, error=str(exc)) from exc
    try:
        raw = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise MergeInputError(
            REFUSE_MEMBER_NOT_JSON, file=origin, member=BUNDLE_MEMBER, error=str(exc)
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
        "# Merged from per-instance exports (GET /api/diagnostics/source-qualification-export)\n"
        "# by Settings > Advanced > Quality gates > Build a merged file, or by\n"
        "# scripts/merge_source_qualification.py -- one merge core. Do not hand-edit.\n"
        "# A domain absent from this file ships unqualified and is judged by the install's\n"
        "# own first qualification pass, exactly as before this file existed.\n"
    )
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
