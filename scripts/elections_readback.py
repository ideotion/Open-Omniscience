#!/usr/bin/env python3
"""Read the elections floor and the Wikidata snapshot run back from a returned file (row 266, 0.6 gate row A).

Usage:
    python3 scripts/elections_readback.py FILE [--json]

FILE is any of:
  * the Field data button's ``oo-field-YYYYMMDD-HHMM-<instance>-elections-floor.json`` (``/api/diagnostics/elections-floor``);
  * a Diagnostics zip, whose ``elections-floor.json`` member is read;
  * that member taken out of the zip;
  * any one piece of a set the button cut (``...-part-001-of-002.json``): the set is joined in memory, and a missing
    piece is named rather than guessed at.

Prints the curated catalogue's read state when it was not read as a catalogue with events (row 273: absent, empty,
or unreadable with the error's class), the language floor's when it was not read (row 279), the snapshot's state, its date, its age and whether it is past the staleness limit, the rows it added, shadowed
and refused; then the floor's four states and the per-country tier report's counts; then any cut the member records. A
figure the file does not have is printed with its reason, never as 0. Counts and dates only: no verdict, no score.

Stdlib only; reads the file it is given and writes nothing; no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
import zipfile
import zlib
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
MEMBER = "elections-floor.json"

#: The floor's four states, in the order the Agenda lists them, with the count key the report uses for each.
_FLOOR_STATES = (
    ("covered", "covered_n"),
    ("only a passed projection", "only_passed_projection_n"),
    ("present but dateless", "present_but_dateless_n"),
    ("missing", "missing_n"),
)

#: The tier report's states, in src/civic/calendar_report.py STATES order (a state missing from a file is said so).
_TIER_STATES = ("scheduled", "window", "projected_upcoming", "passed", "projected_passed", "dateless", "missing")

#: The snapshot counts, in print order, with the words each is printed under.
_SNAPSHOT_COUNTS = (
    ("rows", "rows in the file"),
    ("added", "added to the calendar"),
    ("shadowed", "shadowed by a curated entry"),
    ("refused", "refused when read"),
    ("generator_refused", "refused by the generator"),
)


def _pieces() -> Any:
    """``src/monitoring/field_pieces.py`` loaded by path (stdlib only), as the other read-back scripts do."""
    if "oo_field_pieces" in sys.modules:
        return sys.modules["oo_field_pieces"]
    spec = importlib.util.spec_from_file_location("oo_field_pieces", _HERE.parent / "src" / "monitoring" / "field_pieces.py")
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load src/monitoring/field_pieces.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["oo_field_pieces"] = mod
    spec.loader.exec_module(mod)
    return mod


def load(path: Path) -> dict[str, Any]:
    """The elections-floor reading in ``path``. ValueError says what is wrong with the file."""
    if _pieces().piece_of(path) is not None:
        _name, data = _pieces().join_set(path)
    else:
        data = path.read_bytes()
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if MEMBER not in zf.namelist():
                    raise ValueError(f"{path.name}: the zip has no {MEMBER} member (a build before row 266)")
                data = zf.read(MEMBER)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error) as exc:
            # a damaged, encrypted or unsupported-compression member: said, never a traceback
            raise ValueError(f"{path.name}: the zip's {MEMBER} member could not be read ({type(exc).__name__})") from exc
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{path.name}: not a JSON file ({type(exc).__name__})") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{path.name}: not an elections-floor reading (a JSON object was expected)")
    return doc


def _int(value: Any) -> int | None:
    """A count, or None for anything that is not one (a bool, a string, a missing key): never coerced into a 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _n(value: Any) -> str:
    v = _int(value)
    return f"{v:,}" if v is not None else "—"


def _count(block: dict[str, Any], key: str, words: str) -> str:
    v = _int(block.get(key))
    if v is not None:
        return f"{v:,} {words}"
    if key not in block:
        return f"{words}: not recorded in this file"
    return f"{words}: not a count in this file ({block.get(key)!r})"


def snapshot_lines(snap: Any) -> list[str]:
    if not isinstance(snap, dict):
        return ["snapshot: not recorded in this file (a build before the snapshot was layered in)"]
    state = snap.get("state")
    if state == "absent":
        return ["snapshot: absent: no Wikidata election snapshot on this machine; the operator's networked run of "
                "scripts/generate_wikidata_elections.py writes one"]
    if state == "unreadable":
        return ["snapshot: unreadable: a snapshot file is there but is not the generator's shape (an object with a "
                "rows list and an as_of date), so nothing of it was read"]
    if state != "present":
        return [f"snapshot: state {state!r} (unknown to this script)"]
    lines = [f"snapshot: present, dated {snap.get('as_of') or 'without a date'}"]
    if "age_days" not in snap:
        lines.append("age: not recorded by this build (before row 258)")
    else:
        age, limit = _int(snap.get("age_days")), _int(snap.get("stale_after_days"))
        limit_words = f"the {limit:,}-day limit" if limit is not None else "a limit this file does not state"
        raw = snap.get("age_days")
        if raw is None and snap.get("stale") is True:
            lines.append("age: not computable: the snapshot is dated after the day it was read, so the app treats it as stale")
        elif age is None:
            lines.append(f"age: not a count in this file ({raw!r}); staleness as recorded: {snap.get('stale')!r}")
        elif snap.get("stale") is True:
            lines.append(f"age: {age:,} days, past {limit_words}: STALE, run the snapshot again")
        elif snap.get("stale") is False:
            lines.append(f"age: {age:,} days, within {limit_words}")
        else:
            lines.append(f"age: {age:,} days; staleness not recorded in this file")
    lines.append("counts: " + " · ".join(_count(snap, k, w) for k, w in _SNAPSHOT_COUNTS))
    return lines


def catalogue_read(doc: dict[str, Any]) -> bool:
    """Whether the curated catalogue was read as one with events. A file from before row 273 carries no
    ``catalogue`` block; its counts are printed as recorded."""
    cat = doc.get("catalogue")
    return not isinstance(cat, dict) or cat.get("state") == "present" or doc.get("counts_from") == "snapshot_only"


def catalogue_lines(doc: dict[str, Any]) -> list[str]:
    cat = doc.get("catalogue")
    if not isinstance(cat, dict) or cat.get("state") == "present":
        return []
    state = cat.get("state")
    if doc.get("counts_from") == "snapshot_only":
        error = f" ({cat.get('error')})" if cat.get("error") else ""
        return [f"catalogue: {state}{error}: curated catalogue not read; the counts below come from the Wikidata "
                "snapshot only"]
    if state == "absent":
        return ["catalogue: absent: no curated events catalogue on that machine, so the floor states were not counted"]
    if state == "empty":
        return ["catalogue: empty: the curated events catalogue was read and holds no events, so the floor states "
                "were not counted"]
    if state == "unreadable":
        return [f"catalogue: unreadable ({cat.get('error') or 'no error named'}): the curated events catalogue could "
                "not be read, so the floor states were not counted"]
    return [f"catalogue: state {state!r} (unknown to this script), so the floor states are not printed"]


_FLOOR_WORDS = {
    "absent": "absent: no language-to-country list (configs/language_countries.yml) on that machine",
    "empty": "empty: the language-to-country list was read and lists no country",
}


def floor_lines(doc: dict[str, Any]) -> list[str]:
    fl = doc.get("floor")
    if isinstance(fl, dict) and fl.get("state") not in (None, "present"):
        # Row 279: no floor was read, so there is no denominator and no state was counted.
        state = fl.get("state")
        words = _FLOOR_WORDS.get(str(state)) or (
            f"unreadable ({fl.get('error') or 'no error named'}): the language-to-country list could not be read"
            if state == "unreadable" else f"state {state!r} (unknown to this script)")
        return [f"floor: {words}, so no floor figure was counted"]
    total = _int(doc.get("floor_countries"))
    if total is None:
        return ["floor: no floor figures in this file"]
    lines = [f"floor: {total:,} countries (mapping as of {doc.get('as_of') or 'an undated mapping'}; "
             f"verification: {doc.get('verification_status') or 'not stated'})"]
    if not catalogue_read(doc):
        return lines + ["states: not counted (see the catalogue line)"]
    lines.append("states: " + " · ".join(_count(doc, k, w) for w, k in _FLOOR_STATES))
    outside = doc.get("covered_outside_floor")
    if isinstance(outside, list):
        lines.append(f"covered outside the floor: {len(outside):,}")
    elif "covered_outside_floor" not in doc:
        lines.append("covered outside the floor: not recorded in this file")
    else:
        lines.append(f"covered outside the floor: not a list in this file ({type(outside).__name__})")
    return lines


def tier_lines(rep: Any) -> list[str]:
    if not isinstance(rep, dict):
        return ["tier report: not recorded in this file"]
    fl = rep.get("floor")
    if isinstance(fl, dict) and fl.get("state") not in (None, "present"):
        return ["tier report: not counted (see the floor line)"]
    cat = rep.get("catalogue")
    if isinstance(cat, dict) and cat.get("state") != "present" and rep.get("counts_from") != "snapshot_only":
        return ["tier report: not counted (see the catalogue line)"]
    counts = rep.get("counts")
    if not isinstance(counts, dict) or not counts:
        return ["tier report: no state counts in this file"]
    known = [k for k in _TIER_STATES if k in counts] + [k for k in counts if k not in _TIER_STATES]
    parts = [_count(counts, k, k) for k in known]
    parts += [f"{k}: not recorded in this file" for k in _TIER_STATES if k not in counts]
    return ["tier report: " + " · ".join(parts)]


def cut_lines(cut: Any) -> list[str]:
    if not isinstance(cut, dict):
        return []
    what = cut.get("what") if isinstance(cut.get("what"), list) else []
    lines = [f"cut to fit {_n(cut.get('limit_bytes'))} bytes (was {_n(cut.get('bytes_before'))}): "
             + ("; ".join(map(str, what)) if what else "nothing named")]
    if cut.get("bound") == "field_data_piece":
        lines.append("  (the member is held to one Field data piece so the file sent back is never cut; "
                     f"{cut.get('full_answer') or 'its route'} still answers in full)")
    if cut.get("still_over") is True:
        lines.append(f"still over the limit after the cut: {_n(cut.get('bytes_after'))} bytes written")
    return lines


def report(doc: dict[str, Any]) -> list[str]:
    """The read-back, one line per fact. A member that failed or was omitted says why instead of printing figures."""
    if doc.get("omitted") is True:
        return [f"{MEMBER} was left out of the archive: {doc.get('reason') or 'no reason given'}"]
    if doc.get("available") is False:
        return [f"{MEMBER} could not be built on that machine: {doc.get('error') or doc.get('reason') or 'no reason given'}"]
    return catalogue_lines(doc) + snapshot_lines(doc.get("snapshot")) + floor_lines(doc) + tier_lines(doc.get("tier_report")) + cut_lines(doc.get("cut"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--json", action="store_true", help="print the snapshot block itself, as read")
    args = ap.parse_args(argv)
    try:
        doc = load(args.file)
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.file.name}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        if not isinstance(doc.get("snapshot"), dict):
            print("no snapshot block in this file (" + "; ".join(report(doc)[:1]) + ")", file=sys.stderr)
            return 1
        print(json.dumps(doc["snapshot"], indent=2, ensure_ascii=False))
    else:
        print("\n".join(report(doc)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
