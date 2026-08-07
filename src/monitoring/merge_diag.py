"""Where a merge's time and memory actually go — measured on THIS machine.

Four hypotheses about a 22-hour import died in one session because every one of
them was reasoned from an artifact instead of measured on the engine that ships.
This module exists so the next answer comes from the operator's own bundle rather
than from a script somebody has to remember to run and a file too large to send.

FIVE BLOCKS, each stating what it could not measure rather than reporting zero:

  ``engine``      the compile-time defaults that differ between the bundled
                  sqlcipher3 and the stdlib -- the fact that made every earlier
                  plaintext probe measure the opposite of production.
  ``window``      this corpus's real average row size, and the window the merge
                  will therefore derive. Read-only, sampled, bounded.
  ``sampled``     which SQL statement was in flight, from the BEAT ring. Works on
                  every run from 2026-08-06 onward, costs a capped file read, and
                  is a sampling profiler: 15 s resolution over up to 24 h.
  ``attributed``  exact per-statement seconds from the MILESTONE journal. Works
                  only on journals written BEFORE 2026-08-06, when a per-statement
                  record was still emitted -- which is precisely the 1.6 GB file
                  the field incident left behind, and the only place the answer to
                  that incident lives.
  ``probe``       a bounded synthetic INSERT..SELECT at this corpus's real row
                  size, timed and RSS-sampled with temp storage in RAM and on
                  disk. This is the measurement that named the 5 KB/row cost.

The two attribution blocks are deliberately BOTH here. They read different files
for different eras, and a session that had only the forward-looking one could not
explain the incident that motivated it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

#: Bytes read per milestone journal. The field artifact was 1.6 GB and ~8.7M
#: statement records; parsing all of it costs ~90 s of CPU, which is too much to
#: spend unconditionally inside a bundle. Read a head and a tail and STATE the
#: coverage: which end matters depends on the question (the head shows what the
#: run spent its time on, the tail shows what it was doing when it stopped), so
#: keeping only one would be a bet on the failure shape.
_JOURNAL_HEAD_BYTES = 48 * 1024 * 1024
_JOURNAL_TAIL_BYTES = 16 * 1024 * 1024

#: Journals to attribute. Newest first; the rest are named, never silently ignored.
_MAX_JOURNALS = 3

#: Source bytes the synthetic probe writes per arm. Small enough to sit inside a
#: bundle, large enough that the per-row cost is well above timer noise.
_PROBE_BYTES = 48 * 1024 * 1024
_PROBE_MAX_ROWS = 40_000

#: Rows sampled to estimate the live corpus's average row size.
_SAMPLE_ROWS = 300

#: Temp directories this module creates carry this prefix so a hard kill leaves
#: something a later run can recognise and reclaim, rather than anonymous bytes
#: on the operator's disk (the P0.2 swept-prefix lesson).
_PROBE_PREFIX = ".merge-probe-"


def _rss_mb() -> float:
    """Peak RSS in MB. A HIGH-WATER MARK that never falls -- only meaningful as a
    delta across a window in which nothing else grew, which is why the probe below
    reports the delta from its own immediately-preceding baseline and says so."""
    kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KB, macOS bytes.
    return (kb / 1024.0) if kb > 1024 * 1024 else (kb / 1024.0)


# --------------------------------------------------------------------------- #
#  engine
# --------------------------------------------------------------------------- #
def engine_facts() -> dict[str, Any]:
    """The compile-time defaults, read rather than remembered.

    ``PRAGMA temp_store`` returns 0 meaning "the compile default", which is not
    self-describing -- you have to read ``compile_options`` to learn what 0 means.
    The bundled sqlcipher3 says TEMP_STORE=2 (MEMORY); the stdlib says 1 (FILE).
    That difference is why plaintext probes measured the opposite of production
    for as long as anyone had been running them.
    """
    out: dict[str, Any] = {}
    for name in ("sqlcipher3", "sqlite3"):
        try:
            mod = __import__(name)
            con = mod.connect(":memory:")
            try:
                opts = [r[0] for r in con.execute("PRAGMA compile_options")]
                temp = next((o for o in opts if o.startswith("TEMP_STORE=")), None)
                out[name] = {
                    "temp_store_compile_option": temp,
                    "temp_store_default": {
                        "TEMP_STORE=0": "always file",
                        "TEMP_STORE=1": "file",
                        "TEMP_STORE=2": "MEMORY",
                        "TEMP_STORE=3": "always memory",
                    }.get(temp or "", "unknown"),
                    "sqlite_version": con.execute("select sqlite_version()").fetchone()[0],
                }
            finally:
                con.close()
        except Exception as exc:  # noqa: BLE001 - an absent driver is a fact, not a failure
            out[name] = {"unavailable": f"{type(exc).__name__}: {exc}"}
    out["note"] = (
        "The merge sets PRAGMA temp_store=FILE explicitly. Where the default is MEMORY, "
        "every statement journal and temp table would otherwise be held in RAM, unbounded "
        "by cache_size."
    )
    return out


# --------------------------------------------------------------------------- #
#  window
# --------------------------------------------------------------------------- #
def window_facts(db_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """This corpus's real average article size, and the window it implies.

    Read-only and sampled. Reported because the window is derived rather than
    fixed: an operator seeing "20,000 ids" has no way to know whether that is
    180 MB or 950 MB of work on THEIR corpus, which is the whole reason the
    bound is denominated in bytes.
    """
    from src.backup.merge import _MERGE_WINDOW_BYTES, _MERGE_WINDOW_MAX_IDS, _MERGE_WINDOW_MIN_IDS

    out: dict[str, Any] = {
        "budget_bytes": _MERGE_WINDOW_BYTES,
        "min_ids": _MERGE_WINDOW_MIN_IDS,
        "max_ids": _MERGE_WINDOW_MAX_IDS,
    }
    try:
        from src.backup.sqlite_backup import live_db_path
        from src.database.connect import connect

        path = Path(db_path) if db_path is not None else live_db_path()
        if not Path(path).exists():
            out["measured"] = None
            out["reason"] = "no corpus at the live path yet"
            return out
        con = connect(path)
        try:
            row = con.execute(
                "SELECT COUNT(*), AVG(n) FROM (SELECT LENGTH(CAST(COALESCE(content,'') AS BLOB))"  # nosec B608 - the only interpolation is _SAMPLE_ROWS, a module-level int constant; no caller input reaches this string
                " + LENGTH(CAST(COALESCE(title,'') AS BLOB)) AS n FROM articles"
                f" ORDER BY id DESC LIMIT {int(_SAMPLE_ROWS)})"
            ).fetchone()
            sampled, avg = int(row[0] or 0), float(row[1] or 0.0)
            total = int(con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] or 0)
        finally:
            con.close()
        out["articles"] = total
        out["sampled_rows"] = sampled
        if sampled == 0 or avg <= 0:
            out["measured"] = None
            out["reason"] = "no articles to sample"
            return out
        out["avg_article_bytes"] = round(avg)
        ids = int(_MERGE_WINDOW_BYTES / avg)
        out["derived_window_ids"] = max(_MERGE_WINDOW_MIN_IDS, min(_MERGE_WINDOW_MAX_IDS, ids))
        out["note"] = (
            "sampled from the NEWEST rows, so a corpus whose article size has drifted over "
            "time is represented by its recent shape; the merge itself samples three blocks "
            "spread across the incoming id range"
        )
    except Exception as exc:  # noqa: BLE001 - a diagnostic degrades, it never raises
        out["measured"] = None
        out["reason"] = f"{type(exc).__name__}: {exc}"
    return out


# --------------------------------------------------------------------------- #
#  sampled attribution -- from the BEAT ring (every run, cheap, capped)
# --------------------------------------------------------------------------- #
def sampled_statements(max_runs: int = _MAX_JOURNALS) -> dict[str, Any]:
    """Which statement was in flight, sampled from the capped beat ring.

    A sampling profiler, and reported as one: the beat fires every 15 s, so the
    share of beats a statement holds is proportional to the time it owned, and a
    statement that never spans a sample interval CANNOT appear here. That is a
    real limitation and it is the right trade -- the alternative (a record per
    statement) is what wrote 1.6 GB and stopped the app booting.

    ``max_sql_s`` is the strongest single number in this block: it is how long
    ONE run of that statement had been going at the moment it was sampled, so a
    four-hour statement is visible even if it was sampled only once.
    """
    from src.backup.runlog import run_logs_dir

    out: dict[str, Any] = {"resolution_s": 15.0, "runs": []}
    try:
        d = run_logs_dir()
        beats = sorted(d.glob("*.beat.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": f"{type(exc).__name__}: {exc}"}
    if not beats:
        return {**out, "note": "no beat files yet — nothing has run since this build"}

    for p in beats[:max_runs]:
        seen: Counter[str] = Counter()
        longest: dict[str, float] = {}
        total = with_sql = 0
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    total += 1
                    if '"sql"' not in line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:  # noqa: BLE001 - a truncated tail on a killed run
                        continue
                    sql = r.get("sql")
                    if not sql:
                        continue
                    with_sql += 1
                    seen[sql] += 1
                    s = r.get("sql_s")
                    if isinstance(s, (int, float)):
                        longest[sql] = max(longest.get(sql, 0.0), float(s))
        except Exception as exc:  # noqa: BLE001
            out["runs"].append({"run": p.name, "unavailable": f"{type(exc).__name__}: {exc}"})
            continue
        rows = [
            {
                "sql": sql,
                "beats": n,
                "approx_seconds": round(n * 15.0),
                "max_sql_s": round(longest.get(sql, 0.0), 1),
            }
            for sql, n in seen.most_common(12)
        ]
        out["runs"].append({
            "run": p.name.replace(".beat.jsonl", ""),
            "beats_total": total,
            "beats_with_a_statement": with_sql,
            "statements": rows,
            **({} if with_sql else {
                "note": "no statement was ever in flight at a sample — either no merge ran, "
                        "or every statement finished inside one 15 s interval"
            }),
        })
    if len(beats) > max_runs:
        out["not_read"] = [p.name for p in beats[max_runs:]]
    return out


# --------------------------------------------------------------------------- #
#  exact attribution -- from PRE-2026-08-06 milestone journals
# --------------------------------------------------------------------------- #
def _attribute(path: Path) -> dict[str, Any]:
    """Per-statement seconds from consecutive ``merge_statement_begin`` records.

    Each record is stamped ``el_s`` as its statement BEGINS, so statement N ends
    when N+1 begins: consecutive records give every statement's duration, not
    only the four that crossed the 30 s durable bar. Bounded head+tail, with the
    covered span reported so a partial read can never read as a whole one.
    """
    size = path.stat().st_size
    chunks: list[bytes] = []
    with open(path, "rb") as fh:
        chunks.append(fh.read(_JOURNAL_HEAD_BYTES))
        if size > _JOURNAL_HEAD_BYTES + _JOURNAL_TAIL_BYTES:
            fh.seek(size - _JOURNAL_TAIL_BYTES)
            chunks.append(fh.read(_JOURNAL_TAIL_BYTES))

    # Plain dicts, not Counter: these accumulate SECONDS (float), and Counter is
    # int-valued by contract -- silently truncating fractional statement times.
    total: dict[str, float] = {}
    count: dict[str, int] = {}
    last: dict | None = None
    spans: list[tuple[float, float]] = []
    for blob in chunks:
        prev_lab: str | None = None
        prev_el: float | None = None
        lo: float | None = None
        hi: float | None = None
        for line in blob.decode("utf-8", errors="replace").splitlines():
            if '"merge_statement' not in line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001 - a clipped first/last line of a chunk
                continue
            if r.get("ev") != "merge_statement_begin":
                continue
            el, lab = r.get("el_s"), (r.get("sql") or "?")
            if not isinstance(el, (int, float)):
                continue
            if lo is None:
                lo = el
            hi = el
            if prev_lab is not None and prev_el is not None:
                # Never attribute across the head/tail gap: the elapsed distance
                # there is hours of unread records, not one statement's duration.
                total[prev_lab] = total.get(prev_lab, 0.0) + max(0.0, el - prev_el)
                count[prev_lab] = count.get(prev_lab, 0) + 1
            prev_lab, prev_el = lab, el
            last = r
        if lo is not None and hi is not None:
            spans.append((lo, hi))

    rows = [
        {
            "sql": lab,
            "seconds": round(sec, 1),
            "hours": round(sec / 3600.0, 2),
            "n": count[lab],
            "avg_s": round(sec / max(count[lab], 1), 3),
        }
        for lab, sec in sorted(total.items(), key=lambda kv: kv[1], reverse=True)[:15]
    ]
    return {
        "file": path.name,
        "file_bytes": size,
        "bytes_read": sum(len(c) for c in chunks),
        "complete": size <= _JOURNAL_HEAD_BYTES + _JOURNAL_TAIL_BYTES,
        "covered_spans_el_s": [[round(a, 1), round(b, 1)] for a, b in spans],
        "statements_by_time": rows,
        "last_statement_begun": last,
    }


def attributed_statements(max_runs: int = _MAX_JOURNALS) -> dict[str, Any]:
    """Exact attribution over journals that still carry per-statement records.

    Only journals written before 2026-08-06 have them: the per-statement
    milestone was retired that day for writing 1.6 GB in one run and leaving the
    app unable to boot. So this block is EMPTY on a healthy modern run, and that
    is not a defect -- ``sampled`` is the forward-looking instrument. It stays
    because the run that motivated all of this left exactly such a journal.
    """
    from src.backup.runlog import run_logs_dir

    try:
        d = run_logs_dir()
        cands = [p for p in d.glob("*.jsonl") if not p.name.endswith(".beat.jsonl")]
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": f"{type(exc).__name__}: {exc}"}

    # Cheapest possible filter: only files that mention a statement record at all.
    hits: list[Path] = []
    for p in sorted(cands, key=lambda q: q.stat().st_size, reverse=True):
        try:
            with open(p, "rb") as fh:
                if b'"merge_statement' in fh.read(2 * 1024 * 1024):
                    hits.append(p)
        except Exception:  # noqa: BLE001
            continue
        if len(hits) >= max_runs:
            break
    if not hits:
        return {
            "runs": [],
            "note": (
                "no journal carries per-statement records. Expected on any run from "
                "2026-08-06 onward — the per-statement milestone was retired that day. "
                "See the 'sampled' block, which is the forward-looking instrument."
            ),
        }
    return {"runs": [_attribute(p) for p in hits]}


# --------------------------------------------------------------------------- #
#  the synthetic cost probe
# --------------------------------------------------------------------------- #
def _sweep(root: Path) -> list[str]:
    """Reclaim leftovers from a hard-killed probe. Named, never silent."""
    gone: list[str] = []
    try:
        for p in root.glob(_PROBE_PREFIX + "*"):
            try:
                shutil.rmtree(p, ignore_errors=True)
                gone.append(p.name)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return gone


def _probe_arm(work: Path, rows: int, body: bytes, temp_store: str) -> dict[str, Any]:
    """One INSERT..SELECT of ``rows`` rows with the FTS trigger live."""
    import sqlite3 as drv

    try:
        import sqlcipher3 as drv  # type: ignore[no-redef]  # noqa: F811
    except Exception:  # noqa: BLE001 - plaintext is a valid, stated fallback
        pass

    src, dst = work / f"src-{temp_store}.db", work / f"dst-{temp_store}.db"
    text = body.decode("utf-8", errors="replace")
    con = drv.connect(str(src))
    con.isolation_level = None
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, content TEXT, hash TEXT)")
    con.execute("BEGIN")
    con.executemany(
        "INSERT INTO articles (title, content, hash) VALUES (?, ?, ?)",
        [(f"t{i}", text, f"{i:064d}") for i in range(rows)],
    )
    con.execute("COMMIT")
    con.close()

    d = drv.connect(str(dst))
    d.isolation_level = None
    d.execute(f"PRAGMA temp_store={temp_store}")
    d.execute("PRAGMA cache_size=-262144")
    d.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, content TEXT, hash TEXT)")
    d.execute("CREATE UNIQUE INDEX idx_article_hash ON articles(hash)")
    d.execute("CREATE VIRTUAL TABLE article_fts USING fts5(title, content, content='articles',"
              " content_rowid='id')")
    d.execute("CREATE TRIGGER ai AFTER INSERT ON articles BEGIN INSERT INTO"
              " article_fts(rowid, title, content) VALUES (new.id, new.title, new.content); END")
    d.execute(f"ATTACH DATABASE '{src}' AS inc")
    base = _rss_mb()
    t0 = time.monotonic()
    d.execute("BEGIN IMMEDIATE")
    d.execute("INSERT INTO articles (title, content, hash) SELECT i.title, i.content, i.hash"
              " FROM inc.articles i WHERE NOT EXISTS"
              " (SELECT 1 FROM articles m WHERE m.hash = i.hash)")
    peak = _rss_mb()
    d.execute("COMMIT")
    el = time.monotonic() - t0
    d.close()
    return {
        "temp_store": temp_store,
        "rows": rows,
        "seconds": round(el, 2),
        "rows_per_s": round(rows / el) if el > 0 else None,
        "rss_before_mb": round(base),
        "rss_peak_mb": round(peak),
        "rss_delta_mb": round(peak - base),
        "kb_per_row": round((peak - base) * 1024 / rows, 1) if rows else None,
    }


def cost_probe(avg_row_bytes: int | None = None) -> dict[str, Any]:
    """Measure the per-row cost of a merge-shaped insert, at THIS corpus's row size.

    Bounded to ``_PROBE_BYTES`` of source data per arm, so the cost is the same
    on every corpus even though the row size is not.

    THE MEMORY ARM IS ORDER-DEPENDENT AND SAYS SO: ``ru_maxrss`` is a process
    high-water mark that never falls, so the SECOND arm can only report a delta
    if it exceeds the first. MEMORY runs first for exactly that reason -- if FILE
    ran first, MEMORY's real cost would still show, but FILE's zero would be
    unprovable. A FILE delta of 0 here means "did not exceed the MEMORY arm's
    peak", which is the claim being made, not "allocated nothing".
    """
    from src.paths import data_dir

    out: dict[str, Any] = {}
    avg = int(avg_row_bytes or 4096)
    avg = max(256, min(262_144, avg))
    rows = max(500, min(_PROBE_MAX_ROWS, _PROBE_BYTES // avg))
    body = (b"lorem ipsum dolor sit amet consectetur adipiscing elit " * 4096)[:avg]

    root = data_dir()
    swept = _sweep(root)
    work = root / f"{_PROBE_PREFIX}{os.getpid()}"
    try:
        work.mkdir(parents=True, exist_ok=True)
        out["row_bytes"] = avg
        out["rows_per_arm"] = rows
        out["source_bytes_per_arm"] = rows * avg
        out["arms"] = [
            _probe_arm(work, rows, body, "MEMORY"),
            _probe_arm(work, rows, body, "FILE"),
        ]
        out["note"] = (
            "MEMORY runs first deliberately: peak RSS never falls, so a later arm's delta "
            "is only meaningful when it EXCEEDS an earlier one. Read FILE's delta as 'did "
            "not exceed the MEMORY arm', not as 'allocated nothing'."
        )
    except Exception as exc:  # noqa: BLE001 - a probe that cannot run says so
        out["unavailable"] = f"{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if swept:
        out["swept_leftovers"] = swept
    return out


# --------------------------------------------------------------------------- #
#  the report
# --------------------------------------------------------------------------- #
def merge_diagnostics(*, probe: bool = True) -> dict[str, Any]:
    """The whole picture, with every block degrading independently.

    One failing block must never cost the others: this report exists because a
    24-hour import failed and the evidence was unreadable, and a diagnostic that
    is all-or-nothing reproduces exactly that.
    """
    def safe(name: str, fn) -> Any:  # noqa: ANN001
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            return {"block_ok": False, "error": f"{type(exc).__name__}: {exc}"}

    win = safe("window", window_facts)
    avg = win.get("avg_article_bytes") if isinstance(win, dict) else None
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "engine": safe("engine", engine_facts),
        "window": win,
        "sampled": safe("sampled", sampled_statements),
        "attributed": safe("attributed", attributed_statements),
        "probe": (
            safe("probe", lambda: cost_probe(avg))
            if probe
            else {"skipped": "probe=0 — pass probe=1 to measure the per-row cost here"}
        ),
    }
