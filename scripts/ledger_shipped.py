#!/usr/bin/env python3
"""One-file-per-row fragments for the shipped ledger, so parallel PRs never touch a shared line.

Why: every PR used to append its row at the BOTTOM of docs/ledger/shipped.csv. Locally that is
fine (`merge=union` in .gitattributes), but GitHub's merge check does not apply the union rule,
so every open PR showed as conflicting after every merge, and each owner paid a merge, a push
and a full CI run to clear it. A new PR now adds ONE new file, docs/ledger/shipped.d/
<date>-<slug>.csv, which no other PR can conflict with.

Convention (CLAUDE.md rule (5a)):

    python scripts/ledger_shipped.py new --date 2026-09-30 --area tests --item "..." \
        --status "shipped (draft)" --refs "PR #1240" --key-paths "src/a.py; tests/b.py" \
        --summary "..."               # writes docs/ledger/shipped.d/2026-09-30-<slug>.csv
    python scripts/ledger_shipped.py check    # every fragment is well formed and unique
    python scripts/ledger_shipped.py fold     # append fragments to shipped.csv, delete them

A fragment is a CSV file with the ledger's own header and exactly one row. Everything that
reads the ledger (release notes, the invariants tests) reads shipped.csv FIRST and the fragments
after it, in file-name order, so a row means the same thing wherever it lives. `fold` is for
the maintainer or a release ritual, never for a feature PR: a fold rewrites the shared file
this convention exists to stop touching. It appends in BINARY and LF, because the file is
mixed CRLF/LF and a csv-module round-trip would rewrite every line ending.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / "docs" / "ledger"
HEADER = ["date", "area", "item", "status", "refs", "key_paths", "summary"]
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fragment_dir(csv_path: Path) -> Path:
    return csv_path.parent / "shipped.d"


def fragment_files(csv_path: Path) -> list[Path]:
    d = fragment_dir(csv_path)
    return sorted(d.glob("*.csv")) if d.is_dir() else []


def read_fragment(path: Path) -> list[list[str]]:
    """The data rows of one fragment. Raises ValueError, naming the file, on a bad shape."""
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"), newline="")))
    if not rows or rows[0] != HEADER:
        raise ValueError(f"{path.name}: the first line must be the ledger header {','.join(HEADER)}")
    if len(rows) != 2:
        raise ValueError(f"{path.name}: a fragment holds exactly one row, found {len(rows) - 1}")
    if len(rows[1]) != len(HEADER):
        raise ValueError(f"{path.name}: the row has {len(rows[1])} fields, expected {len(HEADER)}")
    if not path.name.startswith(rows[1][0] + "-"):
        raise ValueError(f"{path.name}: the file name must start with the row's date ({rows[1][0]}-)")
    if not _DAY.match(rows[1][0]):
        raise ValueError(f"{path.name}: the date must be YYYY-MM-DD")
    return rows[1:]


def fragment_rows(csv_path: Path) -> list[list[str]]:
    """Every fragment's row, in file-name order (so date order, then slug)."""
    out: list[list[str]] = []
    for p in fragment_files(csv_path):
        out.extend(read_fragment(p))
    return out


def check(csv_path: Path = LEDGER / "shipped.csv") -> list[str]:
    problems: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    if csv_path.exists():
        for r in list(csv.reader(io.StringIO(csv_path.read_text(encoding="utf-8"), newline="")))[1:]:
            if len(r) >= 3:
                seen.add((r[0], r[1], r[2]))
    for p in fragment_files(csv_path):
        try:
            rows = read_fragment(p)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        key = (rows[0][0], rows[0][1], rows[0][2])
        if key in seen:
            problems.append(f"{p.name}: (date, area, item) already in the ledger: {key}")
        seen.add(key)
    return problems


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "row"


def new(fields: dict[str, str], csv_path: Path = LEDGER / "shipped.csv") -> Path:
    if not _DAY.match(fields["date"]):
        raise SystemExit("--date must be YYYY-MM-DD")
    d = fragment_dir(csv_path)
    d.mkdir(exist_ok=True)
    path = d / f"{fields['date']}-{_slug(fields['area'] + '-' + fields['item'])}.csv"
    if path.exists():
        raise SystemExit(f"{path} exists; edit it instead")
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    w.writerow([fields[k] for k in HEADER])
    path.write_text(buf.getvalue(), encoding="utf-8", newline="")
    return path


def fold(csv_path: Path = LEDGER / "shipped.csv") -> int:
    problems = check(csv_path)
    if problems:
        raise SystemExit("refusing to fold:\n" + "\n".join(problems))
    files = fragment_files(csv_path)
    if not files:
        return 0
    raw = csv_path.read_bytes()
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    for p in files:
        for row in read_fragment(p):
            w.writerow(row)
    add = buf.getvalue().encode("utf-8")
    if raw and not raw.endswith(b"\n"):
        raw += b"\n"
    tmp = csv_path.with_name(csv_path.name + ".tmp")
    tmp.write_bytes(raw + add)
    tmp.replace(csv_path)  # atomic: a crash leaves the old file, never a truncated one
    for p in files:
        p.unlink()
    return len(files)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="write a new one-row fragment")
    for k in HEADER:
        n.add_argument(f"--{k.replace('_', '-')}", required=True)
    sub.add_parser("check", help="verify every fragment")
    sub.add_parser("fold", help="append fragments to shipped.csv and delete them")
    args = ap.parse_args(argv)
    if args.cmd == "new":
        print(new({k: getattr(args, k) for k in HEADER}))
        return 0
    if args.cmd == "check":
        problems = check()
        for line in problems:
            print(line)
        return 1 if problems else 0
    print(f"folded {fold()} fragment(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
