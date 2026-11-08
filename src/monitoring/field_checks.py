"""Field checks: what only the operator's own machine can tell us (R603, 2026-11-08).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ASK (the maintainer, 2026-11-08): «add all the currently necessary testing next to the
diagnostics button, to keep in this self recursive improvement idea of back and forth between you
and the app. This button should evolve with the repo's updates to test things that cannot be tested
by you, and remove those tests for which you already had sufficient feedback.»

So the LIST is data (``configs/field_checks.yml``, versioned, each check carrying why it exists, who
asked for it and when it retires) and the BEHAVIOUR is code: :data:`RUNNERS` maps a manifest
``kind`` to a function. Whether a runner goes online is a property of the runner here
(:data:`ONLINE_KINDS`), never a manifest field, so an edit to the YAML cannot make an online check
skip the consent popup (invariant #14): the route refuses an online kind without ``consent: true``.

THE RULES EVERY RUNNER KEEPS
* It only READS the corpus, or works on a scratch file it deletes before it returns.
* Nothing it records carries a passphrase or a secret: exception text goes through
  ``record_text`` (a database driver's words are reduced to the class), paths through
  ``tokenise_paths``, and the whole report through ``scrubbed_value`` on its way out.
* It reports what it measured and how, with an ``outcome`` word, never a score.

RESULTS LIVE IN THIS PROCESS ONLY. Nothing is written to the data directory: the report is built
from memory when it is saved, so a restart empties it, which the panel says. That keeps a
diagnostic from growing a file nobody asked for.
"""

from __future__ import annotations

import contextlib
import math
import os
import platform
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.monitoring.path_tokens import tokenise_paths
from src.monitoring.secret_scrub import record_text, scrubbed_value

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "configs" / "field_checks.yml"
REPORT_SCHEMA = "oo-field-checks-1"
STATUSES = ("active", "retired")
REQUIRED_FIELDS = ("id", "title", "kind", "status", "added_on", "added_by", "why", "retire_when")
PLATFORMS = ("linux", "windows", "darwin")
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NOTE_MAX = 500
#: The page counters an operator check may carry (the sample-export walk's own counts).
CLIENT_COUNTERS = ("files_saved_by_page", "sources_covered", "sources_total")
_ERR_MAX = 300


class FieldCheckError(ValueError):
    """A request the runner refuses before doing anything (unknown id, bad input, no consent)."""


# --------------------------------------------------------------------------- #
#  The manifest
# --------------------------------------------------------------------------- #


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """The manifest as data, validated. Raises ``FieldCheckError`` naming the first problem."""
    from src.utils.safe_yaml import load_safe_yaml

    raw = load_safe_yaml((path or MANIFEST_PATH).read_text(encoding="utf-8")) or {}
    problems = manifest_problems(raw)
    if problems:
        raise FieldCheckError("configs/field_checks.yml: " + "; ".join(problems))
    return raw


def manifest_problems(raw: Any) -> list[str]:
    """Every way ``raw`` is not a manifest this module can run; empty when it is."""
    if not isinstance(raw, dict):
        return ["the file is not a mapping"]
    out: list[str] = []
    if not isinstance(raw.get("version"), int) or raw["version"] < 1:
        out.append("version must be a whole number >= 1")
    checks = raw.get("checks")
    if not isinstance(checks, list) or not checks:
        return out + ["checks must be a non-empty list"]
    seen: set[str] = set()
    for i, c in enumerate(checks):
        if not isinstance(c, dict):
            out.append(f"check {i} is not a mapping")
            continue
        cid = str(c.get("id") or f"#{i}")
        for f in REQUIRED_FIELDS:
            if not str(c.get(f) or "").strip():
                out.append(f"{cid}: {f} is missing")
        if not _ID.match(cid):
            out.append(f"{cid}: the id is not kebab-case")
        if cid in seen:
            out.append(f"{cid}: the id is used twice")
        seen.add(cid)
        if c.get("kind") not in RUNNERS:
            out.append(f"{cid}: no runner for kind {c.get('kind')!r}")
        if c.get("status") not in STATUSES:
            out.append(f"{cid}: status must be one of {STATUSES}")
        if c.get("status") == "retired" and not (c.get("retired_on") and c.get("retired_by")):
            out.append(f"{cid}: a retired check names retired_on and retired_by")
        plats = c.get("platforms")
        if plats is not None and (not isinstance(plats, list) or any(p not in PLATFORMS for p in plats)):
            out.append(f"{cid}: platforms must be a list drawn from {PLATFORMS}")
        if c.get("kind") == "operator_report" and not (isinstance(c.get("answers"), list) and c["answers"]):
            out.append(f"{cid}: an operator_report check lists its answers")
    return out


def this_platform() -> str:
    s = platform.system().lower()
    return "windows" if s.startswith("win") else s


def applies_here(check: dict[str, Any]) -> bool:
    plats = check.get("platforms")
    return not plats or this_platform() in plats


def _check(manifest: dict[str, Any], check_id: str) -> dict[str, Any]:
    for c in manifest["checks"]:
        if c["id"] == check_id:
            return c
    raise FieldCheckError(f"no field check named {check_id!r}")


# --------------------------------------------------------------------------- #
#  Results (this process only)
# --------------------------------------------------------------------------- #

_RESULTS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_RUNNING: set[str] = set()


def results() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return {k: dict(v) for k, v in _RESULTS.items()}


def reset_for_tests() -> None:
    with _LOCK:
        _RESULTS.clear()
        _RUNNING.clear()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(exc: BaseException) -> str:
    return tokenise_paths(record_text(exc, limit=_ERR_MAX, typed=True))


def run_check(
    check_id: str,
    *,
    consent: bool = False,
    inputs: dict[str, Any] | None = None,
    db: Any = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one ACTIVE check and keep its result. Refusals (``FieldCheckError``) keep nothing."""
    man = manifest or load_manifest()
    check = _check(man, check_id)
    if check["status"] != "active":
        raise FieldCheckError(f"{check_id} is retired; it is kept in the manifest as a record and is not run")
    if not applies_here(check):
        raise FieldCheckError(f"{check_id} runs only on {', '.join(check['platforms'])}")
    kind = check["kind"]
    if kind in ONLINE_KINDS and not consent:
        raise FieldCheckError(f"{check_id} goes online; it runs only after the network consent popup")
    with _LOCK:
        if check_id in _RUNNING:
            raise FieldCheckError(f"{check_id} is already running")
        _RUNNING.add(check_id)
    started = _now()
    t0 = time.monotonic()
    try:
        try:
            body = RUNNERS[kind](dict(check.get("params") or {}), dict(inputs or {}), db, check)
        except FieldCheckError:
            raise
        except Exception as exc:  # noqa: BLE001 - a runner that broke is a result, named
            body = {"outcome": "error", "error": _err(exc)}
    finally:
        with _LOCK:
            _RUNNING.discard(check_id)
    rec = {
        "id": check_id,
        "kind": kind,
        "online": kind in ONLINE_KINDS,
        "started_at": started,
        "elapsed_s": round(time.monotonic() - t0, 2),
        **body,
    }
    rec = scrubbed_value(rec)
    with _LOCK:
        _RESULTS[check_id] = rec
    return rec


def build_report(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """The one file the operator brings back: what was run, against which manifest, on what."""
    man = manifest or load_manifest()
    build: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        from src.monitoring.build_id import build_identity

        build = build_identity()
    version = None
    with contextlib.suppress(Exception):
        from importlib.metadata import version as _v

        version = _v("open-omniscience")
    res = results()
    active = [c for c in man["checks"] if c["status"] == "active"]
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": _now(),
        "manifest_version": man["version"],
        "app_version": version,
        "build": build,
        "platform": {
            "system": this_platform(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "note": "Results are kept by the running app only; a restart empties them. Nothing here is a score.",
        "results": [res[c["id"]] for c in active if c["id"] in res],
        "not_run": [
            {"id": c["id"], "reason": "does not apply on this system" if not applies_here(c) else "not run yet"}
            for c in active
            if c["id"] not in res
        ],
    }
    return scrubbed_value(report)


def panel_view(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the panel draws: every check with its record, whether it applies here, its last result."""
    man = manifest or load_manifest()
    res = results()
    rows = []
    for c in man["checks"]:
        rows.append({
            "id": c["id"],
            "title": c["title"],
            "kind": c["kind"],
            "status": c["status"],
            "online": c["kind"] in ONLINE_KINDS,
            "needs_input": c["kind"] in INPUT_KINDS,
            "applies_here": applies_here(c),
            "added_on": str(c["added_on"]),
            "added_by": c["added_by"],
            "why": c["why"],
            "retire_when": c["retire_when"],
            "retired_on": str(c.get("retired_on") or "") or None,
            "retired_by": c.get("retired_by"),
            "steps": list(c.get("steps") or []),
            "answers": list(c.get("answers") or []),
            "action": (c.get("params") or {}).get("action"),
            "platforms": c.get("platforms"),
            "result": res.get(c["id"]),
        })
    return {"manifest_version": man["version"], "platform": this_platform(), "checks": rows}


# --------------------------------------------------------------------------- #
#  Runners. Each takes (params from the manifest, inputs from the request, db, the check)
#  and returns a dict with an ``outcome`` word and what it measured.
# --------------------------------------------------------------------------- #

_MIB = 1024 * 1024


def _import_headroom(params: dict, inputs: dict, db: Any, check: dict) -> dict[str, Any]:
    """The memory, swap and disk now, and the app's own encrypted-merge memory verdict for a backup
    the size of THIS corpus (its own row counts stand in for the incoming ones)."""
    import psutil
    from sqlalchemy import text

    from src.backup.merge import (
        _ENCRYPTED_REP_BYTES_PER_ROW,
        MergeError,
        check_memory_for_encrypted_merge,
    )
    from src.backup.sqlite_backup import live_db_path
    from src.database.connect import is_encrypted_file

    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    out: dict[str, Any] = {
        "memory": {"total_mib": round(vm.total / _MIB), "available_mib": round(vm.available / _MIB),
                   "swap_total_mib": round(sw.total / _MIB), "swap_free_mib": round(sw.free / _MIB)},
        "cpu_count": os.cpu_count(),
    }
    db_path = live_db_path()
    corpus_bytes = None
    with contextlib.suppress(OSError):
        corpus_bytes = db_path.stat().st_size
    du = psutil.disk_usage(str(db_path.parent))
    out["disk"] = {
        "corpus_mib": round(corpus_bytes / _MIB) if corpus_bytes is not None else None,
        "free_mib": round(du.free / _MIB),
        "filesystem": _fs_type(db_path.parent),
        "free_over_corpus": round(du.free / corpus_bytes, 2) if corpus_bytes else None,
    }
    rows: dict[str, int | None] = {}
    for table in _ENCRYPTED_REP_BYTES_PER_ROW:  # literal names from the merge module, never input
        try:
            rows[table] = int(db.execute(text(f'SELECT MAX(rowid) FROM "{table}"')).scalar() or 0)
        except Exception as exc:  # noqa: BLE001
            rows[table] = None
            out.setdefault("row_errors", {})[table] = _err(exc)
    out["rows_upper_bound"] = rows
    out["method"] = (
        "Rows are each table's highest rowid (an upper bound, read instantly). The memory verdict is the "
        "app's own check_memory_for_encrypted_merge, asked as if a backup the size of this corpus were "
        "imported now. The disk line compares free space with the corpus file; a staged import needs "
        "room for about three copies."
    )
    encrypted = None
    with contextlib.suppress(Exception):
        encrypted = is_encrypted_file(db_path)
    out["encrypted"] = encrypted
    known = {k: v for k, v in rows.items() if v is not None}
    if encrypted is False:
        out["memory_verdict"] = "not-applicable: this corpus is not encrypted, so the in-memory merge check does not run"
        mem_ok = True
    else:
        try:
            check_memory_for_encrypted_merge(available_mb=vm.available / _MIB, incoming_rows=known)
            out["memory_verdict"] = "enough memory now"
            mem_ok = True
        except MergeError as exc:
            out["memory_verdict"] = _err(exc)
            mem_ok = False
    disk_ok = corpus_bytes is not None and corpus_bytes > 0 and du.free >= 3 * corpus_bytes
    out["disk_verdict"] = "room for three copies" if disk_ok else "less than three copies of free space"
    out["outcome"] = "pass" if mem_ok and disk_ok else "short"
    return out


def _fs_type(path: Path) -> str | None:
    try:
        import psutil

        best = None
        p = str(path.resolve())
        for part in psutil.disk_partitions(all=True):
            mp = part.mountpoint
            inside = p == mp or p.startswith(mp.rstrip("/\\") + os.sep)
            if inside and (best is None or len(mp) > len(best.mountpoint)):
                best = part
        return best.fstype if best is not None else None
    except Exception:  # noqa: BLE001
        return None


_THROUGHPUT_CHUNK = 4 * _MIB
_THROUGHPUT_MAX_MIB = 2048


def _drive_throughput(params: dict, inputs: dict, db: Any, check: dict) -> dict[str, Any]:
    """Write one scratch file in the folder the operator named, read it back, delete it."""
    import shutil

    raw = str(inputs.get("path") or "").strip()
    if not raw:
        raise FieldCheckError("name a folder on the drive to measure")
    folder = Path(raw).expanduser()
    if not folder.is_absolute():
        raise FieldCheckError("the folder must be an absolute path")
    if not folder.is_dir():
        raise FieldCheckError("that folder does not exist")
    if not os.access(folder, os.W_OK):
        raise FieldCheckError("this app cannot write in that folder")
    size_mib = max(16, min(int(params.get("size_mib") or 256), _THROUGHPUT_MAX_MIB))
    size = size_mib * _MIB
    free = shutil.disk_usage(folder).free
    if free < 2 * size:
        raise FieldCheckError(f"that drive has {free // _MIB} MiB free; the check needs {2 * size_mib} MiB")
    scratch = folder / f"oo-field-check-{secrets.token_hex(6)}.tmp"
    buf = os.urandom(_THROUGHPUT_CHUNK)
    out: dict[str, Any] = {"folder": tokenise_paths(str(folder)), "filesystem": _fs_type(folder), "size_mib": size_mib}
    with contextlib.suppress(Exception):
        from src.paths import data_dir

        out["same_drive_as_data"] = os.stat(folder).st_dev == os.stat(data_dir()).st_dev
    try:
        t0 = time.monotonic()
        with open(scratch, "wb", buffering=0) as f:
            written = 0
            while written < size:
                written += f.write(buf)
            os.fsync(f.fileno())
        write_s = time.monotonic() - t0
        dropped = False
        with open(scratch, "rb", buffering=0) as f:
            if hasattr(os, "posix_fadvise"):
                with contextlib.suppress(OSError):
                    os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)  # type: ignore[attr-defined]
                    dropped = True
            t1 = time.monotonic()
            while f.read(_THROUGHPUT_CHUNK):
                pass
            read_s = time.monotonic() - t1
    finally:
        with contextlib.suppress(OSError):
            scratch.unlink()
    out["scratch_deleted"] = not scratch.exists()
    out["write_mib_s"] = round(size_mib / write_s, 1) if write_s > 0 else None
    out["read_mib_s"] = round(size_mib / read_s, 1) if read_s > 0 else None
    out["read_cache_dropped"] = dropped
    out["method"] = (
        f"One {size_mib} MiB file written in 4 MiB blocks and flushed to the drive (fsync), then read back. "
        + ("The page cache was asked to drop the file before the read." if dropped else
           "This system cannot be asked to drop its cache, so the read speed may be the memory's, not the drive's.")
    )
    out["outcome"] = "measured"
    return out


def _live_fetch(params: dict, inputs: dict, db: Any, check: dict) -> dict[str, Any]:
    """The app's own fetcher and parser, once; nothing is stored."""
    source = params.get("source")
    try:
        if source == "gistemp":
            from src.stats.fetch import fetch_gistemp

            g = fetch_gistemp("GLB")
            return {"outcome": "pass" if not g.refused_total else "partial", "figures": len(g.figures),
                    "rows_read": g.rows_read, "refused_total": g.refused_total, "refused_first": g.refused[:3]}
        if source == "usgs":
            from src.stats.fetch import fetch_usgs_quakes

            first = (datetime.now(UTC).replace(day=1) - timedelta(days=40)).strftime("%Y-%m")
            q = fetch_usgs_quakes(first, first, 5.0)
            return {"outcome": "pass" if not q.refused_total else "partial", "month": first,
                    "declared_count": getattr(q, "declared_count", None), "rows_read": q.rows_read, "figures": len(q.figures),
                    "refused_total": q.refused_total, "refused_first": q.refused[:3]}
        if source == "owid":
            from src.stats.fetch import fetch_owid_dataset

            o = fetch_owid_dataset("co2")
            return {"outcome": "pass" if not o.refused_total and not o.columns_missing else "partial",
                    "figures": len(o.figures), "rows_read": o.rows_read, "columns_present": len(o.columns_present),
                    "columns_missing": list(o.columns_missing), "refused_total": o.refused_total}
        if source == "ipcc":
            return _ipcc_all()
    except Exception as exc:  # noqa: BLE001 - the refusal or the break is the finding
        return {"outcome": "fail", "source": source, "error": _err(exc)}
    raise FieldCheckError(f"unknown live_fetch source {source!r}")


def _ipcc_all() -> dict[str, Any]:
    """Every catalogue PDF once (the four AR6 summaries), each checked whole; none stored. One that
    fails is named and the others still run, so a report says WHICH address moved."""
    import hashlib

    from src.ingest.ipcc_spm import SPM_CATALOG, fetch_spm

    rows = []
    for e in SPM_CATALOG:
        t0 = time.monotonic()
        try:
            data = fetch_spm(e.key)
            rows.append({"key": e.key, "url": e.url, "reached": True, "bytes": len(data),
                         "sha256": hashlib.sha256(data).hexdigest(), "elapsed_s": round(time.monotonic() - t0, 2)})
        except Exception as exc:  # noqa: BLE001
            rows.append({"key": e.key, "url": e.url, "reached": False, "error": _err(exc),
                         "elapsed_s": round(time.monotonic() - t0, 2)})
    ok = sum(1 for r in rows if r["reached"])
    return {"outcome": "pass" if ok == len(rows) else ("partial" if ok else "fail"), "pdfs_ok": ok,
            "asked": len(rows), "pdfs": rows}


_TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)


def _host_reach(params: dict, inputs: dict, db: Any, check: dict) -> dict[str, Any]:
    """Each URL once through the ethical fetcher (robots.txt honoured); status, size and page title."""
    from src.ingest import EthicalFetcher, FetchError

    fetcher = EthicalFetcher(timeout=45.0)
    rows = []
    for url in params.get("urls") or []:
        entry: dict[str, Any] = {"url": url}
        t0 = time.monotonic()
        try:
            r = fetcher.fetch(str(url), require_html=False, keep_bytes=True)
            body: bytes = r.raw_content or (r.content or "").encode("utf-8")
            m = _TITLE.search(body[:200_000])
            entry.update({"reached": True, "status_code": r.status_code, "bytes": len(body),
                          "title": re.sub(r"\s+", " ", m.group(1).decode("utf-8", "replace")).strip()[:200] if m else None})
        except FetchError as exc:
            entry.update({"reached": False, "refusal": type(exc).__name__, "detail": _err(exc)})
        except Exception as exc:  # noqa: BLE001
            entry.update({"reached": False, "error": _err(exc)})
        entry["elapsed_s"] = round(time.monotonic() - t0, 2)
        rows.append(entry)
    ok = sum(1 for e in rows if e.get("reached") and 200 <= int(e.get("status_code") or 0) < 300)
    return {"outcome": "pass" if rows and ok == len(rows) else ("partial" if ok else "fail"),
            "reached_ok": ok, "asked": len(rows), "hosts": rows}


def _operator_report(params: dict, inputs: dict, db: Any, check: dict) -> dict[str, Any]:
    """What the operator saw, in their words: one of the manifest's answers, a short note, and the
    page's own counters (numbers only)."""
    answer = inputs.get("answer")
    if answer not in (check.get("answers") or []):
        raise FieldCheckError("pick one of the listed answers")
    note = str(inputs.get("note") or "")[:_NOTE_MAX]
    client = inputs.get("client") or {}
    numbers: dict[str, float] = {}
    if isinstance(client, dict):
        for k in CLIENT_COUNTERS:  # fixed names: a key is never scrubbed, so none comes from the request
            v = client.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                numbers[k] = v
    return {"outcome": "answered", "answer": answer, "note": tokenise_paths(note) or None, "page_counters": numbers}


def _clock_step(params: dict, inputs: dict, db: Any, check: dict) -> dict[str, Any]:
    """This session's clock-step records and how fresh the liveness file is."""
    from src.monitoring import session_history as sh

    cur = sh.current_session()
    sid = cur.get("session_id")
    mine = [r for r in sh.read_records() if sid and r.get("session_id") == sid]
    steps = [{k: r.get(k) for k in ("at", "step_s", "direction", "basis")} for r in mine if r.get("kind") == "clock-step"]
    # Where the boot-time clock cannot be read (everywhere but Linux), a FORWARD move cannot be told
    # from a suspend and is recorded as one; only a BACKWARD move is a clock-step everywhere.
    suspends = [{k: r.get(k) for k in ("to", "gap_s", "basis")} for r in mine if r.get("kind") == "suspend"]
    live = sh.read_liveness() or {}
    age = None
    with contextlib.suppress(Exception):
        at = datetime.fromisoformat(str(live["at"]).replace("Z", "+00:00"))
        age = round((datetime.now(UTC) - at).total_seconds())
    fresh = live.get("session_id") == sid and age is not None and abs(age) <= 3 * sh.TICK_S
    return {
        "outcome": "pass" if steps and fresh else ("no-step-recorded" if fresh else "liveness-stale"),
        "session_uptime_s": cur.get("uptime_s"),
        "clock_steps_this_session": steps[-5:],
        "suspends_this_session": suspends[-5:],
        "boot_clock_readable": sh.boottime() is not None,
        "liveness_age_s": age,
        "liveness_same_session": live.get("session_id") == sid,
        "threshold_s": sh.CLOCK_STEP_MIN_S,
        "method": "A clock-step record is written when the wall clock moves more than "
                  f"{int(sh.CLOCK_STEP_MIN_S)} s against the running clocks between two liveness ticks "
                  f"({int(sh.TICK_S)} s apart). The liveness age is read against the clock as it is now.",
    }


RUNNERS: dict[str, Callable[[dict, dict, Any, dict], dict[str, Any]]] = {
    "import_headroom": _import_headroom,
    "drive_throughput": _drive_throughput,
    "live_fetch": _live_fetch,
    "host_reach": _host_reach,
    "operator_report": _operator_report,
    "clock_step": _clock_step,
}
#: The kinds that go online. The route refuses them without the consent the popup gives.
ONLINE_KINDS = frozenset({"live_fetch", "host_reach"})
#: The kinds that take an input from the panel (a folder; an answer).
INPUT_KINDS = frozenset({"drive_throughput", "operator_report"})
