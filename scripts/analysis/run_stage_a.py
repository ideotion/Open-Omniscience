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
same command again after a stop and it continues. Ctrl-C stops cleanly (the in-flight hosts
finish, everything judged so far is kept).

USAGE, from the kit's folder (Python 3.12 or newer):
    python3 run_stage_a.py                      # everything: venv, deps, self-check, worklist 1 then 2, zip
    python3 run_stage_a.py --only shortlist     # worklist 1 only (the 3,588-row review shortlist)
    python3 run_stage_a.py --limit 300          # a first taste: 300 rows, then the zip
    python3 run_stage_a.py --workers 8          # gentler on a small machine (12 is the default and the cap)
On Windows use `py -3.13 run_stage_a.py`. The result is stage_a_results_<date>.zip beside this
file: attach it to a repository-connected Claude session and say "run Stage B and C on this".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON_FLOOR = (3, 12)
PROBE_HOSTS = ("pypi.org", "feeds.bbci.co.uk", "www.lemonde.fr", "theanguillian.com")
WORKLISTS = {
    "shortlist": ("worklists/worklist_1_shortlist.csv", "w1"),
    "remainder": ("worklists/worklist_2_remainder.csv", "w2"),
}
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


def results_md(root: Path = ROOT, *, now: datetime | None = None) -> str:
    """A short human summary from the scripts' own summary.json files -- counts, never claims."""
    now = now or datetime.now(UTC)
    lines = [f"# Stage A results -- {now.date().isoformat()}", ""]
    manifest = root / "KIT_MANIFEST.json"
    if manifest.exists():
        try:
            lines.append(f"Kit: `{json.loads(manifest.read_text(encoding='utf-8')).get('id', '?')}`")
        except ValueError:
            pass
    lines += [f"Python: {sys.version.split()[0]} on {sys.platform}", ""]
    for key, (csv_rel, run_dir) in WORKLISTS.items():
        s = root / "runs" / run_dir / "summary.json"
        if not s.exists():
            lines.append(f"- **{key}** (`{csv_rel}`): not run")
            continue
        try:
            d = json.loads(s.read_text(encoding="utf-8"))
        except ValueError:
            lines.append(f"- **{key}**: summary.json unreadable")
            continue
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(d.get("by_reason", {}).items(), key=lambda kv: -kv[1]))
        lines.append(
            f"- **{key}** (`{csv_rel}`): {d.get('candidates', 0)} candidates judged, "
            f"{d.get('verified', 0)} feeds verified; by reason: {reasons or 'none'}"
            + (" -- INTERRUPTED, re-run to continue" if d.get("interrupted") else "")
        )
    lines += ["", "verified means: the feed was fetched and parsed in this run, had at least 3 entries "
              "with a title and a link, and its newest dated entry was within 120 days. Nothing here "
              "judges what an outlet is -- that is Stage B's question, run elsewhere.", ""]
    return "\n".join(lines)


def package(root: Path = ROOT, *, now: datetime | None = None) -> Path:
    """``stage_a_results_<date>.zip`` beside the kit: everything under runs/, the manifest, RESULTS.md."""
    now = now or datetime.now(UTC)
    runs = root / "runs"
    runs.mkdir(exist_ok=True)
    (runs / "RESULTS.md").write_text(results_md(root, now=now), encoding="utf-8")
    out = root / f"stage_a_results_{now.date().isoformat()}.zip"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(runs.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(root).as_posix())
        if (root / "KIT_MANIFEST.json").exists():
            zf.write(root / "KIT_MANIFEST.json", "KIT_MANIFEST.json")
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", choices=sorted(WORKLISTS), default=None, help="one worklist instead of both")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"parallel hosts, at most {MAX_WORKERS}")
    ap.add_argument("--limit", type=int, default=None, help="rows to judge per worklist THIS run (resumable)")
    ap.add_argument("--timeout", type=float, default=20.0, help="seconds per request")
    ap.add_argument("--skip-selfcheck", action="store_true")
    ap.add_argument("--no-zip", action="store_true")
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
            with urllib.request.urlopen(f"https://{h}/", timeout=12) as r:  # nosec B310 - fixed https:// hosts, an informational probe
                out[h] = str(r.status)
        except Exception as exc:  # noqa: BLE001 - the answer IS the report
            out[h] = f"{type(exc).__name__}: {str(exc)[:60]}"
        print(f"   {h:<22} {out[h]}", flush=True)
    return out


def selfcheck(py: Path, root: Path = ROOT, env: dict | None = None) -> None:
    marker = root / "runs" / ".selfcheck_ok"
    if marker.exists():
        return
    _say("self-check (offline; proves the kit works here before anything is fetched)")
    subprocess.run([str(py), str(root / "selfcheck.py")], check=True, env=env, cwd=root)
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")


def stage_a(py: Path, key: str, args: argparse.Namespace, root: Path = ROOT, env: dict | None = None) -> int:
    csv_rel, run_dir = WORKLISTS[key]
    out = root / "runs" / run_dir
    out.mkdir(parents=True, exist_ok=True)
    _say(f"Stage A on {key} ({csv_rel}) -> runs/{run_dir}  [workers {args.workers}; Ctrl-C stops cleanly; re-run resumes]")
    cmd = [str(py), str(root / "scripts" / "analysis" / "verify_candidate_feeds.py"),
           "--candidates", str(root / csv_rel), "--out-dir", str(out),
           "--workers", str(args.workers), "--timeout", str(args.timeout)]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    return subprocess.run(cmd, env=env, cwd=root).returncode


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    args = parse_args(argv)
    if not python_ok():
        print(f"Python {PYTHON_FLOOR[0]}.{PYTHON_FLOOR[1]} or newer is needed (this is {sys.version.split()[0]}). "
              "Install it from python.org (or `brew install python@3.13`, or `winget install Python.Python.3.13`) "
              "and run this file with it.")
        return 2
    os.chdir(ROOT)
    env = dict(os.environ)
    env.setdefault("OO_DATA_DIR", str(ROOT / "data"))
    env.pop("PYTHONPATH", None)
    code = 0
    try:
        py = ensure_venv()
        probe()
        if not args.skip_selfcheck:
            selfcheck(py, env=env)
        for key in (sorted(WORKLISTS) if args.only is None else [args.only]):
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
            z = package()
            print(f"\n== packaged: {z}  ({z.stat().st_size / 1e6:.1f} MB) -- attach this to a repository-connected "
                  "Claude session for Stage B and C", flush=True)
    if code == 130:
        print("stopped by Ctrl-C; everything judged so far is kept -- run the same command again to continue")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
