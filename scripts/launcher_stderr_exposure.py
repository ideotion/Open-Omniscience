"""Measure the launcher stderr filter's summary-row EXPOSURE: how long after the launcher returns the filter's summary row is on disk.

The launcher can return before the filter's END has written its summary row (the filter reads a COPY of stderr through tee, so it can
trail the launcher); until then a reader finds the abort lines with no summary. This runs the real scripts/launch.sh against a fake
server, once per launch, and polls the record until the summary row appears. A launch whose summary was already there when the
launcher returned has exposure 0; one whose summary never appears within the wait is reported as "missing", not as a long number.

    python scripts/launcher_stderr_exposure.py --launches 60 --load 8 --out table.jsonl

Every launch is one raw row in --out (the table is the evidence); a one-line summary per mode goes to stdout. POSIX only (bash, awk, tee).
Run nothing else on the machine while it measures: the load, when asked for, is the only load.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tests.test_exit_evidence import _launcher_tree  # noqa: E402

SERVER = "sleep 0.2\necho 'free(): invalid pointer' >&2\nexit 3\n"
WAIT_S = 10.0


def _summary_present(record: Path) -> bool:
    try:
        return any('"summary":true' in ln for ln in record.read_text(encoding="utf-8").splitlines())
    except OSError:
        return False


def _one(base: Path) -> dict:
    root, env = _launcher_tree(base, SERVER)
    record = root / "data" / "diagnostics" / "launcher_stderr.jsonl"
    # stdout and stderr go to /dev/null, NOT a pipe: a pipe would be held open by the filter and the wait for it would hide the very gap measured
    started = time.monotonic()
    proc = subprocess.run(["bash", str(root / "scripts" / "launch.sh")], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    returned = time.monotonic()
    row = {"returncode": proc.returncode, "launch_s": round(returned - started, 4)}
    if _summary_present(record):
        row["exposure_ms"] = 0.0
        return row
    deadline = returned + WAIT_S
    while time.monotonic() < deadline:
        if _summary_present(record):
            row["exposure_ms"] = round((time.monotonic() - returned) * 1000, 2)
            return row
        time.sleep(0.0005)
    row["exposure_ms"] = None
    row["missing"] = f"no summary row within {WAIT_S:g} s of the launcher returning"
    return row


def _measure(mode: str, launches: int, load: int, out) -> list[dict]:
    hogs: list[subprocess.Popen] = []
    rows = []
    try:
        hogs.extend(subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(load))
        if load:
            time.sleep(1.0)  # let the load settle before the first launch
        for i in range(launches):
            with tempfile.TemporaryDirectory(prefix="oo-exposure-") as d:
                row = {"mode": mode, "launch": i + 1, "load_processes": load, **_one(Path(d))}
            rows.append(row)
            out.write(json.dumps(row) + "\n")
            out.flush()
    finally:
        for h in hogs:
            h.kill()
            h.wait()
    return rows


def _say(mode: str, rows: list[dict]) -> str:
    vals = [r["exposure_ms"] for r in rows if r["exposure_ms"] is not None]
    missing = len(rows) - len(vals)
    if not vals:
        return f"{mode}: {len(rows)} launches, {missing} missing, no figure"
    return (
        f"{mode}: {len(rows)} launches, exposure ms min {min(vals):g} median {statistics.median(vals):g} max {max(vals):g}, "
        f"{sum(1 for v in vals if v == 0)} at 0, {missing} missing"
    )


def _environment() -> dict:
    """What the figures depend on, written as the table's first row so the table backs the statement made about it."""
    awk = shutil.which("awk")
    try:
        first = subprocess.run([awk, "--version"], capture_output=True, text=True, timeout=10).stdout.splitlines()
        version = first[0] if first else None
    except (OSError, subprocess.SubprocessError, TypeError):
        version = None
    bash = subprocess.run(["bash", "--version"], capture_output=True, text=True, timeout=10).stdout.splitlines()
    return {"environment": True, "cpu_count": os.cpu_count(), "awk": version, "bash": bash[0] if bash else None, "platform": sys.platform}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--launches", type=int, default=60)
    ap.add_argument("--load", type=int, default=0, help="busy-loop processes to run beside the launches; 0 = idle only, else idle then loaded")
    ap.add_argument("--out", required=True, help="the raw table, one JSON row per launch")
    a = ap.parse_args()
    with open(a.out, "w", encoding="utf-8") as out:
        out.write(json.dumps(_environment()) + "\n")
        print(_say("idle", _measure("idle", a.launches, 0, out)))
        if a.load:
            print(_say(f"loaded x{a.load}", _measure("loaded", a.launches, a.load, out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
