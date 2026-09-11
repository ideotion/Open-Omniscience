"""Run Stage A of the candidate pipeline on YOUR OWN machine -- one command, zero model tokens.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (maintainer, 2026-09-10): the internet-connected cloud session's "real connection
is extremely limited". Stage A is the only stage that needs the publishers' hosts, and it needs
no model at all -- so it runs wherever the connection is real (a laptop, the machine that runs
the app) and hands its results back as one zip. Stage B (the model triage) and Stage C (the
splice into the catalogue, the tests, the pull request) need no publisher access and run in a
repository-connected Claude session on that zip.

Standard library only, so it runs before the venv exists. Every step is re-runnable: run the
same command again after a stop and it continues. Ctrl-C (once) stops cleanly: the in-flight
hosts finish, everything judged so far is kept, the zip is written. No host can hold the run:
a host's declared robots Crawl-delay bounds its own feed probes, and when nothing finishes for
twenty minutes the hosts still in flight are written as host_timeout (not judged) and the
worklist moves on -- `--retry host_timeout,crawl_delay_too_long` re-judges them later.

USAGE, from the kit's folder (Python 3.12 or newer):
    python3 run_stage_a.py                      # everything: venv, deps, self-check, worklist 1 then 2, zip
    python3 run_stage_a.py --only shortlist     # worklist 1 only (the 3,588-row review shortlist)
    python3 run_stage_a.py --limit 300          # a first taste: 300 rows per worklist, then the zip
    python3 run_stage_a.py --workers 8          # gentler on a small machine (12 is the default and the cap)
    python3 run_stage_a.py --retry host_timeout # re-judge the rows a previous run could not finish
    python3 run_stage_a.py --status             # WHILE IT RUNS, from a second terminal: progress, the
                                                # reasons so far, this session's rate, and a snapshot zip
On Windows use `py -3.13 run_stage_a.py`. The result is stage_a_results_<date>.zip beside this
file (a --status snapshot is stage_a_snapshot_<date>T<time>.zip): attach it to a
repository-connected Claude session and say "run Stage B and C on this".
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON_FLOOR = (3, 12)
PROBE_HOSTS = ("pypi.org", "feeds.bbci.co.uk", "www.lemonde.fr", "theanguillian.com")
WORKLISTS = {  # insertion order is the RUN order: the review shortlist first, then the remainder
    "shortlist": ("worklists/worklist_1_shortlist.csv", "w1"),
    "remainder": ("worklists/worklist_2_remainder.csv", "w2"),
    "institutions": ("worklists/worklist_3_institutions.csv", "w3"),
    "religious": ("worklists/worklist_4_religious.csv", "w4"),
    # The RETRY worklist (2026-09-11 ruling: a deferred row is never dropped). Built by
    # scripts/analysis/build_retry_worklist.py from finished runs, so it only exists in a kit
    # whose operator asked for one -- every worklist here is skipped when its CSV is absent.
    "retry": ("worklists/worklist_5_retry.csv", "w5"),
}
# What a BARE `run_stage_a.py` runs. The news worklists only, deliberately: institutions and
# religious are a different question (primary sources, not reporting), they are three times the
# rows, and an operator who typed no flag has not asked for a 79,000-row job. They are reached
# with `--only institutions`. Every OTHER use of WORKLISTS -- --status, RESULTS.md, packaging --
# iterates all four, so a run that HAS happened is always reported.
DEFAULT_WORKLISTS = ("shortlist", "remainder")
MAX_WORKERS = 12   # concurrency is across hosts; each host still sees one request every 2 s


# --------------------------------------------------------------------------- pure helpers

def python_ok(version: tuple[int, ...] = sys.version_info[:2]) -> bool:
    return tuple(version[:2]) >= PYTHON_FLOOR


def venv_python(root: Path = ROOT) -> Path:
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def requirements_stamp(root: Path = ROOT) -> str:
    return hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest()[:16]


def _worklist_rows(root: Path, csv_rel: str) -> int:
    p = root / csv_rel
    if not p.exists():
        return 0
    with p.open(encoding="utf-8", newline="") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def tally(root: Path = ROOT, key: str = "shortlist", *, now: datetime | None = None) -> dict | None:
    """Progress of one worklist from ``runs/<dir>/verified.jsonl`` ITSELF -- the resume cursor,
    flushed one complete line per judged host -- so it is exact while the run is still writing.
    A torn last line (the row being written this instant) is skipped and counted as ``torn``.
    The rate is THIS session's: the rows stamped with the latest ``checked_at`` (one stamp per
    invocation) over the time since that stamp -- measured, never a projection."""
    now = now or datetime.now(UTC)
    csv_rel, run_dir = WORKLISTS[key]
    path = root / "runs" / run_dir / "verified.jsonl"
    if not path.exists():
        return None
    by_reason: Counter = Counter()
    by_session: Counter = Counter()
    n = torn = 0
    with path.open("rb") as fh:
        for raw in fh:
            if not raw.endswith(b"\n"):
                torn += 1
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                torn += 1
                continue
            n += 1
            by_reason[str(d.get("reason") or "?")] += 1
            by_session[str(d.get("checked_at") or "")] += 1
    out: dict = {
        "judged": n, "total": _worklist_rows(root, csv_rel), "verified": by_reason.get("verified", 0),
        "by_reason": dict(by_reason.most_common()), "torn": torn,
        "session_rows": 0, "session_started": "", "rate_per_hour": None, "eta_hours": None,
    }
    latest = max((k for k in by_session if k), default="")
    if latest:
        try:
            started = datetime.fromisoformat(latest)
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            hours = max((now - started).total_seconds(), 1.0) / 3600.0
            rate = by_session[latest] / hours
            out["session_rows"] = by_session[latest]
            out["session_started"] = latest
            out["rate_per_hour"] = round(rate, 1)
            remaining = max(0, out["total"] - n)
            out["eta_hours"] = round(remaining / rate, 2) if rate > 0 else None
        except ValueError:
            pass
    return out


def status_lines(root: Path = ROOT, *, now: datetime | None = None) -> list[str]:
    lines = []
    for key, (csv_rel, _run_dir) in WORKLISTS.items():
        t = tally(root, key, now=now)
        if t is None:
            lines.append(f"{key:<10} not started ({csv_rel})")
            continue
        reasons = ", ".join(f"{k} {v}" for k, v in t["by_reason"].items())
        line = f"{key:<10} {t['judged']}/{t['total']} judged, {t['verified']} feeds verified -- {reasons or 'nothing yet'}"
        if t["rate_per_hour"]:
            line += (f"\n{'':<10} this session: {t['session_rows']} rows since {t['session_started']} = "
                     f"{t['rate_per_hour']:.0f} hosts/hour")
            if t["eta_hours"] is not None:
                line += f"; at that rate the rest of this worklist takes ~{t['eta_hours']:.1f} h"
        if t["torn"]:
            line += f"\n{'':<10} ({t['torn']} line still being written -- a snapshot skips it; the run keeps it)"
        lines.append(line)
    return lines


def results_md(root: Path = ROOT, *, now: datetime | None = None) -> str:
    """A short human summary from the JSONL cursors -- counts, never claims."""
    now = now or datetime.now(UTC)
    lines = [f"# Stage A results -- {now.strftime('%Y-%m-%d %H:%M UTC')}", ""]
    manifest = root / "KIT_MANIFEST.json"
    if manifest.exists():
        with contextlib.suppress(ValueError):
            lines.append(f"Kit: `{json.loads(manifest.read_text(encoding='utf-8')).get('id', '?')}`")
    lines += [f"Python: {sys.version.split()[0]} on {sys.platform}", ""]
    for key, (csv_rel, run_dir) in WORKLISTS.items():
        t = tally(root, key, now=now)
        if t is None:
            lines.append(f"- **{key}** (`{csv_rel}`): not run")
            continue
        reasons = ", ".join(f"{k} {v}" for k, v in t["by_reason"].items())
        note = ""
        s = root / "runs" / run_dir / "summary.json"
        if s.exists():
            with contextlib.suppress(ValueError):
                if json.loads(s.read_text(encoding="utf-8")).get("interrupted"):
                    note = " -- INTERRUPTED, re-run to continue"
        if t["judged"] < t["total"]:
            note += f" -- IN PROGRESS, {t['total'] - t['judged']} rows not yet judged"
        lines.append(
            f"- **{key}** (`{csv_rel}`): {t['judged']} of {t['total']} candidates judged, "
            f"{t['verified']} feeds verified; by reason: {reasons or 'none'}{note}"
        )
    lines += ["", "verified means: the feed was fetched and parsed in this run, had at least 3 entries "
              "with a title and a link, and its newest dated entry was within 120 days. Nothing here "
              "judges what an outlet is -- that is Stage B's question, run elsewhere.", ""]
    return "\n".join(lines)


def _complete_lines(path: Path) -> bytes:
    """The JSONL with only its COMPLETE lines -- a snapshot taken mid-run must not carry the row
    being written, which a reader would otherwise choke on."""
    out = bytearray()
    with path.open("rb") as fh:
        for raw in fh:
            if raw.endswith(b"\n"):
                try:
                    json.loads(raw)
                except ValueError:
                    continue
                out += raw
    return bytes(out)


def package(root: Path = ROOT, *, now: datetime | None = None, snapshot: bool = False,
            shard: str | None = None) -> Path:
    """``stage_a_results_<date>.zip`` (or ``stage_a_snapshot_<date>T<HHMM>.zip`` while a run is
    still going) beside the kit: everything under runs/, the manifest, RESULTS.md. Every
    ``verified.jsonl`` goes in with complete lines only, so the zip is readable whenever it is
    taken; the running process is never touched."""
    now = now or datetime.now(UTC)
    runs = root / "runs"
    runs.mkdir(exist_ok=True)
    (runs / "RESULTS.md").write_text(results_md(root, now=now), encoding="utf-8")
    stamp = now.strftime("%Y-%m-%dT%H%M") if snapshot else now.date().isoformat()
    # Eight machines returning eight files called stage_a_results_<date>.zip is how a shard gets
    # silently overwritten and its slice of the worklist is never seen again. The name carries it.
    tag = f"_shard{shard.replace('/', 'of')}" if shard else ""
    out = root / (f"stage_a_snapshot_{stamp}{tag}.zip" if snapshot else f"stage_a_results_{stamp}{tag}.zip")
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(runs.rglob("*")):
            if not p.is_file():
                continue
            arc = p.relative_to(root).as_posix()
            if p.name == "verified.jsonl":
                zf.writestr(arc, _complete_lines(p))
            else:
                zf.write(p, arc)
        if (root / "KIT_MANIFEST.json").exists():
            zf.write(root / "KIT_MANIFEST.json", "KIT_MANIFEST.json")
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", choices=list(WORKLISTS), default=None,
                    help="run ONE worklist. Without it: shortlist then remainder (the news rows). "
                         "institutions and religious are opt-in -- they are a different question and "
                         "three times the rows.")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"parallel hosts, at most {MAX_WORKERS}")
    ap.add_argument("--limit", type=int, default=None, help="rows to judge per worklist THIS run (resumable)")
    ap.add_argument("--timeout", type=float, default=20.0, help="seconds per request")
    ap.add_argument("--retry", default=None,
                    help="re-judge rows whose last verdict has one of these reasons (comma-separated), "
                         "e.g. host_timeout,crawl_delay_too_long")
    ap.add_argument("--shard", default=None, metavar="I/N",
                    help="run only this machine's slice, e.g. --shard 3/8. Split by host, so the "
                         "8 machines never test the same source twice and each host still sees one "
                         "request per interval. The results zip is named for the shard.")
    ap.add_argument("--skip-selfcheck", action="store_true")
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--status", action="store_true",
                    help="from a second terminal while a run is going: progress, reasons, this session's "
                         "rate, and a snapshot zip; touches nothing")
    args = ap.parse_args(argv)
    args.workers = max(1, min(MAX_WORKERS, args.workers))
    return args


# --------------------------------------------------------------------------- steps (subprocesses)

def _say(msg: str) -> None:
    print(f"\n== {msg}", flush=True)


def ensure_venv(root: Path = ROOT) -> Path:
    py = venv_python(root)
    if not py.exists():
        _say("creating the virtual environment (.venv)")
        subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], check=True)
    stamp = root / ".venv" / ".kit-requirements"
    want = requirements_stamp(root)
    if not stamp.exists() or stamp.read_text(encoding="utf-8").strip() != want:
        _say("installing the pinned requirements (once; needs PyPI)")
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                        "-r", str(root / "requirements.txt")], check=True)
        stamp.write_text(want, encoding="utf-8")
    return py


def probe() -> dict[str, str]:
    _say("probing four hosts (informational; the run itself is the real test)")
    out: dict[str, str] = {}
    for h in PROBE_HOSTS:
        try:
            # fixed https:// hosts, an informational probe
            with urllib.request.urlopen(f"https://{h}/", timeout=12) as r:  # nosec B310
                out[h] = str(r.status)
        except Exception as exc:  # noqa: BLE001 - the answer IS the report
            out[h] = f"{type(exc).__name__}: {str(exc)[:60]}"
        print(f"   {h:<22} {out[h]}", flush=True)
    return out


def kit_id(root: Path = ROOT) -> str:
    try:
        return str(json.loads((root / "KIT_MANIFEST.json").read_text(encoding="utf-8")).get("id") or "")
    except Exception:  # noqa: BLE001 - no readable manifest: keyed on nothing, so the check runs
        return ""


def selfcheck(py: Path, root: Path = ROOT, env: dict | None = None) -> None:
    # The marker holds the id of the kit it passed for, so an updated kit extracted over this
    # folder (new code, same runs/ and .venv) proves itself once more before it fetches.
    marker = root / "runs" / ".selfcheck_ok"
    want = kit_id(root)
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == want:
        return
    _say("self-check (offline; proves the kit works here before anything is fetched)")
    subprocess.run([str(py), str(root / "selfcheck.py")], check=True, env=env, cwd=root)
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(want, encoding="utf-8")


def stage_a(py: Path, key: str, args: argparse.Namespace, root: Path = ROOT, env: dict | None = None) -> int:
    csv_rel, run_dir = WORKLISTS[key]
    out = root / "runs" / run_dir
    out.mkdir(parents=True, exist_ok=True)
    _say(f"Stage A on {key} ({csv_rel}) -> runs/{run_dir}  [workers {args.workers}; Ctrl-C once stops cleanly; re-run resumes]")
    cmd = [str(py), str(root / "scripts" / "analysis" / "verify_candidate_feeds.py"),
           "--candidates", str(root / csv_rel), "--out-dir", str(out),
           "--workers", str(args.workers), "--timeout", str(args.timeout)]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if args.retry:
        cmd += ["--retry", args.retry]
    if getattr(args, "shard", None):
        cmd += ["--shard", args.shard]
    # Popen + wait, not subprocess.run: run() would SIGKILL the child a quarter-second after a
    # Ctrl-C, before it could finish the in-flight hosts and write its outputs. The child gets the
    # same Ctrl-C from the terminal and handles it itself; here we only wait for it.
    proc = subprocess.Popen(cmd, env=env, cwd=root)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        print("\n== stopping: letting the in-flight hosts finish and the outputs be written (up to a few "
              "minutes; everything judged so far is already on disk) ...", flush=True)
        try:
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=30)
        raise


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    args = parse_args(argv)
    if not python_ok():
        print(f"Python {PYTHON_FLOOR[0]}.{PYTHON_FLOOR[1]} or newer is needed (this is {sys.version.split()[0]}). "
              "Install it from python.org (or `brew install python@3.13`, or `winget install Python.Python.3.13`) "
              "and run this file with it.")
        return 2
    os.chdir(ROOT)
    if args.status:
        now = datetime.now(UTC)
        print(f"== Stage A status at {now.strftime('%Y-%m-%d %H:%M UTC')} (reads the run's own files; the run is not touched)")
        for line in status_lines(now=now):
            print(line)
        if not args.no_zip and (ROOT / "runs").exists():
            z = package(now=now, snapshot=True, shard=getattr(args, 'shard', None))
            print(f"\n== snapshot: {z}  ({z.stat().st_size / 1e6:.1f} MB) -- attach it to a repository-connected "
                  "Claude session to have Stage B and C run on what exists so far", flush=True)
        return 0
    env = dict(os.environ)
    env.setdefault("OO_DATA_DIR", str(ROOT / "data"))
    env.pop("PYTHONPATH", None)
    code = 0
    try:
        py = ensure_venv()
        probe()
        if not args.skip_selfcheck:
            selfcheck(py, env=env)
        for key in (list(DEFAULT_WORKLISTS) if args.only is None else [args.only]):  # the shortlist first
            rc = stage_a(py, key, args, env=env)
            if rc != 0:
                code = rc
                break
    except KeyboardInterrupt:
        code = 130
    except subprocess.CalledProcessError as exc:
        print(f"\nstep failed (exit {exc.returncode}): {' '.join(map(str, exc.cmd))[:200]}")
        code = exc.returncode or 1
    finally:
        if not args.no_zip and (ROOT / "runs").exists():
            z = package(shard=getattr(args, 'shard', None))
            print(f"\n== packaged: {z}  ({z.stat().st_size / 1e6:.1f} MB) -- attach this to a repository-connected "
                  "Claude session for Stage B and C", flush=True)
    if code == 130:
        print("stopped by Ctrl-C; everything judged so far is kept -- run the same command again to continue")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
