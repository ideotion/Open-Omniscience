"""Build the self-contained candidate KIT -- the pipeline for a session with no repository.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULING (maintainer, 2026-09-10): the internet-connected session that verifies the candidate
sources has NO GitHub access -- no clone, no PR, no push -- and must run autonomously from an
attachment. So everything the run needs travels in one zip: the three pipeline scripts, the
repository modules they import (the ONE ethical fetcher, domain normalisation, the country
tables, the tag taxonomy, the guarded language detector), the shipped catalogues they dedupe
against, the worklists derived from the maintainer's export, a self-check that proves the kit
works BEFORE any credit is spent, and the runbook the session follows.

WHAT IS COPIED, AND WHAT IS NOT. ``src/`` travels whole, minus ``static/`` (the UI), the IP
geolocation table and bytecode -- the closure the scripts import is a couple of dozen modules
but several of them import lazily, and a hand-picked list that missed one would fail in the one
place it cannot be fixed. ``configs/`` travels whole (the catalogues for dedupe, the tag
vocabulary, the stopword lists the detector's neighbours read). Nothing of the app shell, no
database, no ``CLAUDE.md`` (the kit's subagents get no ledger injected -- that is most of the
per-batch token cost gone). The export travels verbatim under ``export/`` as provenance.

THE WORKLISTS are derived here, with ``complement_candidates.analyse``, so the session does not
re-derive them: worklist 1 is the review shortlist (the T1-T3 gap classes, capped 100 per
country -- the same 3,588 rows the research report holds); worklist 2 is every other discovered
news row, the capped-out T1-T3 overflow first and then T4 -- an ORDER, never an exclusion.

DETERMINISTIC: the same tree, export and date give the same bytes; the manifest records the
build commit and a sha256 per file; the zip's timestamps are the build date.

RUN:
  .venv/bin/python scripts/analysis/build_candidate_kit.py \\
      --export path/to/open-omniscience-sources.csv[.zip] --out-dir /tmp/kit
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

KIT_VERSION = 1
KIT_MARKER = "KIT_MANIFEST.json"
PYTHON_FLOOR = "3.12"   # the locked numpy 2.5 needs 3.12+; measured: 3.11 cannot install the pins
RUNBOOK = "docs/design/CANDIDATE_KIT_RUNBOOK.md"
SELFCHECK = "scripts/analysis/candidate_kit_selfcheck.py"
SCRIPT_FILES = (
    "scripts/analysis/verify_candidate_feeds.py",
    "scripts/analysis/triage_batches.py",
    "scripts/analysis/triage_verified_feeds.workflow.js",
    "scripts/analysis/complement_candidates.py",
    "scripts/merge_source_batch.py",
)
TEST_FILES = (
    "tests/test_verify_candidate_feeds.py",
    "tests/test_candidate_pipeline_glue.py",
)
# What the scripts and their src closure import, plus those wheels' own dependencies -- pinned
# from requirements.lock so the kit installs exactly what the repository tested with.
KIT_PACKAGES = (
    "requests", "urllib3", "certifi", "charset-normalizer", "idna", "PyYAML", "feedparser",
    "sgmllib3k", "py3langid", "numpy", "bleach", "webencodings", "cryptography", "cffi",
    "pycparser", "pytest", "pluggy", "iniconfig", "packaging", "pygments",
)
SRC_SKIP_PARTS = frozenset({"static", "__pycache__"})   # any path component under src/
SRC_SKIP_PREFIXES = ("geo/data/",)                       # relative to src/: the 4.5 MB IP table
SRC_SKIP_SUFFIXES = (".pyc", ".pyo")
WORKLIST_FIELDS = (
    "tier", "name", "domain", "source_type", "country", "language", "language_basis", "tags",
    "catalogue_sources_in_country", "catalogue_sources_in_language", "flags",
)
SHORTLIST_CAP = 100
_TIER_ORDER = {"T1": 0, "T2": 1, "T3": 2, "T4": 3}

_CONFTEST = '''"""The kit's test bootstrap: its own src first, an isolated data directory."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("OO_DATA_DIR", tempfile.mkdtemp(prefix="oo-kit-tests-"))
'''


# --------------------------------------------------------------------------- helpers

def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git_commit(root: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                             text=True, timeout=10, check=False)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_requirements(root: Path, packages: tuple[str, ...] = KIT_PACKAGES) -> list[str]:
    """``name==version`` per kit package: the lock's pin, else the installed distribution's
    version, else a refusal -- the builder never guesses a version."""
    pins: dict[str, str] = {}
    lock = root / "requirements.lock"
    if lock.exists():
        for line in lock.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Za-z0-9_.\-]+)==([^\s;\\]+)", line)
            if m:
                pins[_norm(m.group(1))] = m.group(2)
    out: list[str] = []
    for name in packages:
        ver = pins.get(_norm(name))
        if ver is None:
            from importlib.metadata import PackageNotFoundError, version

            try:
                ver = version(name)
            except PackageNotFoundError as exc:
                raise RuntimeError(f"no pin for {name}: not in requirements.lock and not installed") from exc
        out.append(f"{name}=={ver}")
    return out


def load_export(path: Path) -> tuple[list[dict], str]:
    """The export rows from a CSV or a zip holding one CSV; returns ``(rows, member name)``."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError(f"{path.name}: expected exactly one CSV inside, found {members}")
            text = zf.read(members[0]).decode("utf-8-sig")
            return list(csv.DictReader(io.StringIO(text))), members[0]
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh)), path.name


# --------------------------------------------------------------------------- worklists

def build_worklists(rows: list[dict], root: Path, out_dir: Path, *, cap: int = SHORTLIST_CAP) -> dict:
    cc = _load_module(root / "scripts" / "analysis" / "complement_candidates.py", "complement_candidates")
    result = cc.analyse(rows, per_country_cap=cap)
    by_domain: dict[str, dict] = {}
    for r in rows:
        dom = cc._reg(r.get("domain") or "")
        if dom and dom not in by_domain:
            by_domain[dom] = r

    def _row(k: dict) -> dict:
        src = by_domain.get(k["domain"], {})
        return {
            "tier": k["tier"], "name": k["name"], "domain": k["domain"],
            "source_type": src.get("source_type") or "news", "country": k["country"],
            "language": k["language"], "language_basis": k["language_basis"],
            "tags": src.get("tags") or "",
            "catalogue_sources_in_country": k.get("catalogue_sources_in_country", ""),
            "catalogue_sources_in_language": k.get("catalogue_sources_in_language", ""),
            "flags": k.get("flags", ""),
        }

    shortlist = [_row(k) for k in result["shortlist"]]
    short_domains = {r["domain"] for r in shortlist}
    rest = [k for k in result["kept"] if k["domain"] not in short_domains]
    rest.sort(key=lambda k: (_TIER_ORDER.get(k["tier"], 9), k["country"], k["name"].lower()))
    remainder = [_row(k) for k in rest]

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (("worklist_1_shortlist.csv", shortlist), ("worklist_2_remainder.csv", remainder)):
        with (out_dir / name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(WORKLIST_FIELDS), lineterminator="\n")
            w.writeheader()
            w.writerows(data)
    counts = {
        "export_rows": len(rows), "catalogue_rows": result["catalogue"], "discovered_rows": result["discovered"],
        "news_rows": result["news"], "news_kept": result["news_kept"], "tiers": dict(sorted(result["tiers"].items())),
        "worklist_1_shortlist": len(shortlist), "worklist_2_remainder": len(remainder), "shortlist_cap": cap,
        "capped_countries": dict(sorted(result["shortlist_capped_countries"].items())),
    }
    (out_dir / "WORKLISTS.md").write_text(_worklists_md(counts), encoding="utf-8")
    return counts


def _worklists_md(c: dict) -> str:
    tiers = ", ".join(f"{k} {v:,}" for k, v in c["tiers"].items())
    capped = ", ".join(f"{k} ({v})" for k, v in c["capped_countries"].items()) or "none"
    return (
        "# The worklists\n\n"
        f"Derived at build time from the maintainer's sources export ({c['export_rows']:,} rows: "
        f"{c['catalogue_rows']:,} enabled catalogue rows, {c['discovered_rows']:,} discovered rows) with "
        "`scripts/analysis/complement_candidates.py` -- offline, from the file alone. Only the discovered rows "
        f"typed `news` are candidates ({c['news_rows']:,}; institutions and religious organisations stay out by "
        "type); rows duplicating a catalogue domain or alias are dropped; a missing language is filled from a "
        "single-language ccTLD where one exists, with the basis recorded.\n\n"
        f"Gap classes against the catalogue's own per-country and per-language counts (a class, never a score): {tiers}.\n\n"
        f"- `worklist_1_shortlist.csv` -- {c['worklist_1_shortlist']:,} rows: T1 + T2 + T3, capped at {c['shortlist_cap']} per "
        f"country, ordered by class, country, name. Countries the cap truncated (totals): {capped}.\n"
        f"- `worklist_2_remainder.csv` -- {c['worklist_2_remainder']:,} rows: every other candidate, the capped-out "
        "T1-T3 overflow first, then T4, in the same order. An order of work, never an exclusion.\n\n"
        "Columns: " + ", ".join(f"`{f}`" for f in WORKLIST_FIELDS) + ". `verify_candidate_feeds.py` reads "
        "`domain`, `name`, `source_type`, `country`, `language` and `tags`; the rest is for the reviewer.\n"
    )


# --------------------------------------------------------------------------- the tree

def _copy_src(root: Path, kit: Path) -> int:
    n = 0
    for p in sorted((root / "src").rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root / "src")
        if SRC_SKIP_PARTS & set(rel.parts) or rel.suffix in SRC_SKIP_SUFFIXES:
            continue
        if any(rel.as_posix().startswith(pre) for pre in SRC_SKIP_PREFIXES):
            continue
        dst = kit / "src" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
        n += 1
    return n


def _copy_configs(root: Path, kit: Path) -> int:
    n = 0
    for p in sorted((root / "configs").rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            dst = kit / "configs" / p.relative_to(root / "configs")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            n += 1
    return n


def _hash_tree(kit: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(kit.rglob("*")):
        if p.is_file() and p.name != KIT_MARKER:
            out[p.relative_to(kit).as_posix()] = _sha256(p)
    return out


def build_kit(*, export: Path, out_dir: Path, root: Path = _ROOT, date_str: str | None = None,
              commit: str | None = None) -> Path:
    """Assemble the kit folder ``out_dir/oo-candidate-kit-<date>/`` and return it."""
    date_str = date_str or datetime.now(UTC).date().isoformat()
    commit = commit or _git_commit(root)
    kit = out_dir / f"oo-candidate-kit-{date_str}"
    if kit.exists():
        shutil.rmtree(kit)
    kit.mkdir(parents=True)

    for rel in SCRIPT_FILES + TEST_FILES:
        dst = kit / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
    shutil.copy2(root / SELFCHECK, kit / "selfcheck.py")
    shutil.copy2(root / RUNBOOK, kit / "RUN.md")
    shutil.copy2(root / "LICENSE", kit / "LICENSE")
    (kit / "tests" / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    (kit / "requirements.txt").write_text(
        f"# Pinned from the repository's requirements.lock at build ({commit}); Python >= {PYTHON_FLOOR}.\n"
        + "\n".join(resolve_requirements(root)) + "\n", encoding="utf-8")
    n_src = _copy_src(root, kit)
    n_cfg = _copy_configs(root, kit)

    rows, member = load_export(export)
    (kit / "export").mkdir()
    shutil.copy2(export, kit / "export" / export.name)
    counts = build_worklists(rows, root, kit / "worklists")

    manifest = {
        "id": f"oo-candidate-kit-{date_str}-{commit}",
        "kit_version": KIT_VERSION,
        "built": date_str,
        "commit": commit,
        "repository": "ideotion/Open-Omniscience",
        "python_floor": PYTHON_FLOOR,
        "export": {"file": export.name, "member": member, "rows": len(rows), "sha256": _sha256(export)},
        "worklists": counts,
        "copied": {"src_files": n_src, "config_files": n_cfg},
        "files": _hash_tree(kit),
    }
    (kit / KIT_MARKER).write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return kit


def zip_kit(kit: Path, *, date_str: str | None = None) -> Path:
    """``<kit>.zip`` beside the folder, timestamps fixed to the build date (reproducible)."""
    manifest = json.loads((kit / KIT_MARKER).read_text(encoding="utf-8"))
    y, m, d = (int(x) for x in (date_str or manifest["built"]).split("-"))
    out = kit.with_suffix(".zip")
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(kit.rglob("*")):
            if not p.is_file():
                continue
            info = zipfile.ZipInfo((kit.name + "/" + p.relative_to(kit).as_posix()), date_time=(y, m, d, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o644 << 16)
            zf.writestr(info, p.read_bytes())
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--export", required=True, type=Path, help="the sources export: a CSV, or a zip holding one")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today, UTC)")
    ap.add_argument("--commit", default=None, help="build commit label (default: git rev-parse --short HEAD)")
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args(argv)
    kit = build_kit(export=args.export, out_dir=args.out_dir, date_str=args.date, commit=args.commit)
    manifest = json.loads((kit / KIT_MARKER).read_text(encoding="utf-8"))
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"} | {"files": len(manifest["files"])}, indent=1))
    if not args.no_zip:
        z = zip_kit(kit)
        print(f"zip: {z} ({z.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
