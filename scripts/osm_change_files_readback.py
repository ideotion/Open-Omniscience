#!/usr/bin/env python3
"""Read the OSM daily change-file cost back from a returned Field data file (row 263, 0.6 gate row B).

Usage:
    python3 scripts/osm_change_files_readback.py oo-field-YYYYMMDD-HHMM-<instance>-osm-change-files.json [--json]

The file is what the Field data button saved from ``/api/osm/change-files``: the Diagnostics zip's own ``osm-change-files.json`` member
(``src/osm/diagnostics.py:diagnostics_member``). A file the button cut into numbered pieces (``...-part-001-of-002.json``) can be given
as any one of its pieces: the set is joined in memory, and a missing piece is named rather than guessed at. The member taken out of a
Diagnostics zip is read the same way, and so is the zip itself (only that one member is read from it).

Prints, per country the daily files have touched: where its objects stand, how many change files were applied and what they cost
(bytes fetched, seconds to fetch and to apply: n files measured, the total, the mean per file and the largest), its gaps by kind
(a re-baseline or a hand re-cut) and the newest runs; then the countries no file has touched, by code, what the member cut to fit its
budget, the machine kind and the street view's frame budget state. A figure the file does not have is printed with its reason, never
as 0. Counts, country codes, sequence numbers and dates only: nothing else in the file is printed. No verdict, no score.

Stdlib only; reads the file it is given and writes nothing; no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
#: The member's name inside a Diagnostics zip (src/api/diagnostics_slots.py).
MEMBER = "osm-change-files.json"
#: The largest member read out of a zip. The slot's budget is 20,000 bytes; anything far past it is not the member.
_MAX_MEMBER_BYTES = 2_000_000
_COST_KEYS = (("bytes_fetched", "bytes fetched", ""), ("fetch_seconds", "fetch", " s"), ("apply_seconds", "apply", " s"))


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


def _from_zip(path: Path) -> bytes:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n == MEMBER or n.endswith("/" + MEMBER)]
        if not names:
            raise ValueError(f"{path.name}: a zip without {MEMBER} (a Diagnostics zip from a build before the OSM member?)")
        info = zf.getinfo(names[0])
        if info.file_size > _MAX_MEMBER_BYTES:
            raise ValueError(f"{path.name}: {MEMBER} is {info.file_size:,} bytes, far past the member's budget; not read")
        return zf.read(info)


def load(path: Path) -> dict[str, Any]:
    """The member in ``path`` (a piece of a set is joined first). ValueError says what is wrong with the file."""
    if zipfile.is_zipfile(path):
        data = _from_zip(path)
    elif _pieces().piece_of(path) is not None:
        _name, data = _pieces().join_set(path)
    else:
        data = path.read_bytes()
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name}: not a JSON file ({type(exc).__name__})") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{path.name}: not a change-files reading (a JSON object was expected)")
    return doc


def _int(value: Any) -> int | None:
    """A count, or None for anything that is not one (a bool, a string, a missing key): never coerced into a 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _num(value: Any) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _code(value: Any) -> str:
    """A country code as the member writes it (three capital letters); anything else is not printed."""
    return value if isinstance(value, str) and len(value) == 3 and value.isascii() and value.isalpha() and value.isupper() else "?"


def _when(iso: Any) -> str | None:
    """An ISO time cut to the minute, or None for anything that is not one (free text is never printed)."""
    if not isinstance(iso, str) or len(iso) < 10 or not iso[:4].isdigit() or iso[4] != "-":
        return None
    out = iso[:16].replace("T", " ")
    return out + " UTC" if len(out) > 10 else out


def _n(value: Any, unit: str = "") -> str:
    v = _num(value)
    if v is None:
        return "—"
    if isinstance(v, int):
        return f"{v:,}{unit}"
    if 0 < v < 0.0005:
        return f"<0.001{unit}"  # measured, but below the printed precision: never shown as a 0
    return f"{v:,.3f}".rstrip("0").rstrip(".") + unit


#: The shape of the member's reasons: the code's own fixed words (letters and plain punctuation, no digit, slash or @). A reason
#: outside it (a hand-edited or foreign file) is not printed, so nothing but the member's words can reach the read-back (R734/R736).
_FIXED_WORDS = re.compile(r"[A-Za-z_ ,;:'()\-.]{1,240}")


def _reason(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value:
        return fallback
    return value if _FIXED_WORDS.fullmatch(value) else "a reason not in the member's fixed words (not printed)"


def cost_lines(row: dict[str, Any]) -> list[str]:
    """The country's measured cost, or its reason. ``n`` below ``diffs_recorded`` is said: some files did not measure that figure."""
    cost = row.get("cost")
    if not isinstance(cost, dict):
        return [f"  cost: not measured: {_reason(row.get('cost_reason'), 'no reason given in this file')}"]
    recorded = _int(row.get("diffs_recorded"))
    unmeasured = _dict(cost.get("unmeasured"))
    out = []
    for key, label, unit in _COST_KEYS:
        st = cost.get(key)
        if not isinstance(st, dict) or _int(st.get("n")) is None:
            out.append(f"  {label}: not measured: {_reason(unmeasured.get(key), 'absent from this file')}")
            continue
        n, total, top = _int(st.get("n")), _num(st.get("total")), _num(st.get("max"))
        mean = round(total / n, 3) if n and total is not None else None
        line = f"  {label}: {_n(n)} files measured, total {_n(total, unit)}, mean per file {_n(mean, unit)}, largest {_n(top, unit)}"
        if recorded is not None and n is not None and n < recorded:
            line += f" ({_n(recorded - n)} of {_n(recorded)} files did not measure it)"
        out.append(line)
    return out


def _run_figure(run: dict[str, Any], key: str, label: str, unit: str) -> str:
    """One run's figure, or that it was not measured (a run's null measurement is the member's own, left out of the cost's n)."""
    if _num(run.get(key)) is None:
        return f"{label} not measured by this file's run"
    return f"{label} {_n(run.get(key), unit)}"


_TAG_PARTS = (("created", "created"), ("deleted", "deleted"), ("left_class", "left their class"), ("tags_changed", "tags changed"))


def _tag_text(holder: dict[str, Any], key: str, reason_key: str) -> str:
    """Row 276: what a file (or a country's files) did to tags, as counts: rows by change and objects by how they took part.

    A block the member left null says its reason; a key the file does not carry is an older build's file, said so, never a 0."""
    if key not in holder:
        return "tag changes: not in this file (an older build)"
    block = holder.get(key)
    if not isinstance(block, dict):
        return f"tag changes: not given: {_reason(holder.get(reason_key), 'no reason given in this file')}"
    rows = _int(block.get("rows"))
    if rows is None:
        return "tag changes: not recorded in this file"
    changes = ", ".join(f"{c} {_n(block.get(c))}" for c in ("added", "removed", "modified"))
    objects = ", ".join(f"{label} {_n(block.get('objects_' + part))}" for part, label in _TAG_PARTS)
    return f"tag changes: {_n(rows)} key rows ({changes}); objects {objects}"


def country_lines(row: dict[str, Any]) -> list[str]:
    code = _code(row.get("alpha3"))
    status = row.get("status") if isinstance(row.get("status"), str) and row.get("status", "").isidentifier() else "?"
    pos = _dict(row.get("position"))
    seq, ts = _int(pos.get("sequence")), _when(pos.get("timestamp"))
    src = pos.get("from") if pos.get("from") in ("change file", "extract") else None
    if seq is None:
        where = f"position not recorded: {_reason(pos.get('reason'), 'no reason given in this file')}"
    else:
        where = f"position {seq} from the {src or 'unnamed source'}" + (f", {ts}" if ts else f" (no time: {_reason(pos.get('reason'), 'none recorded')})")
    recorded = _int(row.get("diffs_recorded"))
    files = (f"{_n(recorded)} change files applied" if recorded is not None
             else f"change files: not recorded: {_reason(row.get('cost_reason'), 'absent from this file')}")
    last = _when(row.get("last_applied_at"))
    lines = [f"{code} ({status}): {where} · {files}" + (f" · last applied {last}" if last else "")]
    lines += cost_lines(row)
    gaps = _int(row.get("gaps_total"))
    if gaps is None:
        lines.append(f"  gaps: not recorded: {_reason(row.get('gaps_reason'), 'absent from this file')}")
    else:
        lines.append(f"  gaps: {_n(gaps)} (re-baselines {_n(row.get('rebaselines'))}, hand re-cuts {_n(row.get('hand_recuts_seen'))})"
                     + (f", {_n(row.get('gaps_not_shown'))} not shown" if _int(row.get("gaps_not_shown")) else ""))
    lines.append("  all files, " + _tag_text(row, "tag_changes_total", "tag_changes_reason"))
    untimed = _int(row.get("tag_rows_time_not_recorded"))
    if untimed:
        lines.append(f"  {_n(untimed)} key rows whose file stated no time (counted above, in no file below)")
    runs = [r for r in _list(row.get("runs")) if isinstance(r, dict)]
    for r in runs:
        seq = _int(r.get("sequence"))
        lines.append(f"  file {seq if seq is not None else '(sequence not recorded)'} of {_when(r.get('diff_timestamp')) or 'an unrecorded date'}: "
                     + ", ".join(_run_figure(r, key, label, unit) for key, label, unit in _COST_KEYS))
        lines.append("    " + _tag_text(r, "tag_changes", "tag_changes_reason"))
    hidden = _int(row.get("runs_not_shown"))
    if hidden:
        lines.append(f"  {_n(hidden)} older files not shown (they are in the cost above)")
    return lines


def report(doc: dict[str, Any]) -> list[str]:
    """The read-back, one line per fact. An absent lane or a cut member says why instead of printing figures it does not have."""
    if "error" in doc and "countries" not in doc:
        return [f"the member could not be built: {_reason(doc.get('reason'), 'no reason given')}"]
    if doc.get("lane") == "absent":
        return [f"the OSM lane was not read: {_reason(doc.get('reason'), 'no reason given')}"] + _street_view_lines(doc)
    if doc.get("over_budget") is True:
        need = _int(doc.get("needs_at_least_bytes"))
        lane = doc.get("lane") if doc.get("lane") in ("present", "absent") else "not stated"
        return [f"the member was omitted: {_reason(doc.get('omitted'), 'over its budget')}"
                + (f" (needs at least {_n(need)} bytes)" if need is not None else "") + f"; the lane: {lane}"]
    rows = [r for r in _list(doc.get("countries")) if isinstance(r, dict)]
    rows_hidden = _int(doc.get("countries_not_shown")) or 0
    lines = [f"{len(rows) + rows_hidden} countries with change files or gaps"
             + (f" ({rows_hidden} not shown: cut to fit the member's budget)" if rows_hidden else "")]
    for r in rows:
        lines += country_lines(r)
    without = [_code(c) for c in _list(doc.get("countries_without_updates"))]
    untouched_hidden = _int(doc.get("countries_without_updates_not_shown")) or 0
    listed = ", ".join(without) if without else ("none" if not untouched_hidden else "")
    more = f"{untouched_hidden} not shown (cut to fit the member's budget)" if untouched_hidden else ""
    lines.append("countries no change file has touched: " + "; ".join(x for x in (listed, more) if x))
    cut = _dict(doc.get("dropped_to_fit"))
    dropped = [(k, _int(v)) for k, v in (("runs", cut.get("runs")), ("gaps", cut.get("gaps")),
                                         ("countries", doc.get("countries_not_shown")),
                                         ("untouched countries", doc.get("countries_without_updates_not_shown")))]
    shown = [f"{label} {_n(v)}" for label, v in dropped if v]
    lines.append("cut to fit the member's budget: " + (", ".join(shown) if shown else "nothing"))
    m = _dict(doc.get("measured_on"))
    if m:
        unreported = _dict(m.get("unreported"))

        def _fact(key: str, ok: bool, text: str) -> str:
            return text if ok else f"{key} not reported ({_reason(unreported.get(key), 'absent from this file')})"

        os_, arch, cpus = m.get("os"), m.get("arch"), _int(m.get("cpus"))
        lines.append("measured on: " + ", ".join((
            _fact("os", isinstance(os_, str) and os_.isalnum(), str(os_)),
            _fact("arch", isinstance(arch, str) and arch.replace("_", "").isalnum(), str(arch)),
            _fact("cpus", cpus is not None, f"{cpus} CPUs"),
        )))
    else:
        lines.append("measured on: absent from this file")
    return lines + _street_view_lines(doc)


def _street_view_lines(doc: dict[str, Any]) -> list[str]:
    sv = doc.get("street_view")
    if not isinstance(sv, dict):
        return ["street view frame budget: absent from this file"]
    state = sv.get("state") if sv.get("state") in ("measured", "not measured", "unreadable") else "?"
    when = _when(sv.get("measured_at"))
    return [f"street view frame budget: {state}" + (f", {when}" if when else "")
            + (f": {_reason(sv.get('reason'), 'no reason given')}" if state != "measured" else "")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--json", action="store_true", help="print the member itself, as read")
    args = ap.parse_args(argv)
    try:
        doc = load(args.file)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"cannot read {args.file.name}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=2, ensure_ascii=False) if args.json else "\n".join(report(doc)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
