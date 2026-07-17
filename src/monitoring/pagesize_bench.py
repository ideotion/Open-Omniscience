"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling modules).

---

Page-size A/B bench (DB-10 §1b, maintainer-asked 2026-07-17): rebuild the corpus
into fresh stores at candidate ``page_size`` values (4K vs 16K by default, each
with ``auto_vacuum=INCREMENTAL`` per the ruled §1a default for new corpora), run
the IDENTICAL bounded workload on each rebuild, and report per-size latency
percentiles SIDE BY SIDE — never a composite verdict or a "winner". The operator
runs this on corpora of DIFFERENT sizes (real backups restored on real machines)
and compares the logs: the decision signal is the TREND across sizes, not any
single point.

HONESTY BY CONSTRUCTION
  * The rebuild SELF-VERIFIES: after each rebuild the target's ``page_size`` and
    ``auto_vacuum`` are read back and the article count is compared to the
    source; a mismatch REFUSES the bench for that size (a structured error,
    never a silently mis-configured measurement). This is the ruled
    verify-before-trust probe made permanent — the pragma inheritance is proven
    on every run, never asserted from documentation.
  * Read-only on the source: the rebuild reads through ``VACUUM INTO``
    (plaintext) or ``sqlcipher_export`` into an ATTACHed target (encrypted,
    SAME passphrase — one key surface, and the codec stays IN the measurement,
    which is the whole point).
  * Numbers only: p50/p95 + n per operation class, first-pass vs second-pass
    (cold-ish vs warm) reported separately; stated caveats (OS page cache not
    controlled; the workload is a proxy of the app's hot shapes).
  * Disk preflight refuses honestly when the work dir cannot hold a rebuild;
    rebuilds are staged under a swept ``.pagesize-bench-`` prefix so a crashed
    run's leftovers are reclaimed at the next start (the P0.2 janitor lesson).
"""

from __future__ import annotations

import logging
import os
import random
import shutil
import time
from datetime import datetime
from pathlib import Path

_LOG = logging.getLogger("monitoring.pagesize_bench")

PAGESIZE_BENCH_SCHEMA = "oo-pagesize-bench-1"
_STAGE_PREFIX = ".pagesize-bench-"
_ALLOWED_PAGE_SIZES = (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
# INCREMENTAL (2) is the ruled §1a default for new corpora — benching at the
# ruled target keeps the measurement representative of what would actually ship.
_DEFAULT_AUTO_VACUUM = 2

_POINT_LOOKUPS = 200
_INDEX_WINDOW_RUNS = 20
_CONTENT_BAND_RUNS = 20
_CONTENT_BAND_ROWS = 500
_SEED = 20260717  # fixed: reproducible sampling, never a security surface


class BenchRefused(ValueError):
    """A precondition failed (disk space, bad page size, missing store) — the
    bench refuses up front instead of producing a misleading measurement."""


class BenchVerifyError(RuntimeError):
    """The rebuilt target did NOT read back the requested pragmas (or lost rows)
    — the measurement for that size is refused, never silently taken."""


# ---------------------------------------------------------------------------
#  Rebuild (the migration mechanism, self-verified per run)
# ---------------------------------------------------------------------------

def _quote_key(key: str) -> str:
    return key.replace("'", "''")


def rebuild_at_pragmas(
    src: Path | str,
    dst: Path | str,
    *,
    page_size: int,
    auto_vacuum: int = _DEFAULT_AUTO_VACUUM,
    passphrase: str | None = None,
) -> dict:
    """Rebuild ``src`` into a fresh ``dst`` carrying the requested CREATE-time
    pragmas, then SELF-VERIFY the target (pragmas read back + article count).

    Plaintext source: ``VACUUM INTO`` with the pragmas set on the connection
    (empirically verified: the target inherits them). Encrypted source:
    ``sqlcipher_export`` into an ATTACHed target keyed with the SAME passphrase,
    with ``cipher_page_size``/``auto_vacuum`` set on the target before export.
    Returns {seconds, file_bytes, verified:{...}}; raises BenchVerifyError on a
    target that does not match (never a silent mis-measurement)."""
    from src.database.connect import connect, get_passphrase, is_encrypted_file

    if page_size not in _ALLOWED_PAGE_SIZES:
        raise BenchRefused(f"page_size must be one of {_ALLOWED_PAGE_SIZES}, got {page_size}")
    src_p, dst_p = Path(src), Path(dst)
    if not src_p.exists():
        raise BenchRefused(f"source store not found: {src_p}")
    for suffix in ("", "-wal", "-shm"):
        Path(str(dst_p) + suffix).unlink(missing_ok=True)

    t0 = time.perf_counter()
    encrypted = bool(is_encrypted_file(src_p))
    key = passphrase if passphrase is not None else get_passphrase()
    con = connect(src_p, check_same_thread=False)
    try:
        src_articles = con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if encrypted:
            if not key:
                raise BenchRefused(
                    "the store is encrypted but no passphrase is available to key the rebuild"
                )
            # Filename bound; KEY quoted via the house idiom (a bound param is not
            # accepted inside ATTACH's KEY clause on all driver versions).
            con.execute(f"ATTACH DATABASE ? AS tgt KEY '{_quote_key(key)}'", (str(dst_p),))
            # CREATE-time pragmas on the still-empty target, BEFORE export creates
            # the first table (the one window in which they can be set).
            con.execute(f"PRAGMA tgt.cipher_page_size = {int(page_size)}")
            con.execute(f"PRAGMA tgt.auto_vacuum = {int(auto_vacuum)}")
            cur = con.cursor()
            try:
                cur.execute("SELECT sqlcipher_export('tgt')")
            finally:
                cur.close()
            con.execute("DETACH DATABASE tgt")
        else:
            con.execute(f"PRAGMA page_size = {int(page_size)}")
            con.execute(f"PRAGMA auto_vacuum = {int(auto_vacuum)}")
            con.execute("VACUUM INTO ?", (str(dst_p),))
    finally:
        con.close()
    seconds = time.perf_counter() - t0

    # SELF-VERIFY: never trust the mechanism — read the target back.
    vcon = connect(dst_p, check_same_thread=False)
    try:
        got_page = vcon.execute("PRAGMA page_size").fetchone()[0]
        got_av = vcon.execute("PRAGMA auto_vacuum").fetchone()[0]
        got_articles = vcon.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    finally:
        vcon.close()
    verified = {
        "page_size": got_page,
        "auto_vacuum": got_av,
        "articles_source": src_articles,
        "articles_rebuilt": got_articles,
    }
    if got_page != page_size or got_av != auto_vacuum or got_articles != src_articles:
        raise BenchVerifyError(
            f"rebuilt target does not match the request: wanted page_size={page_size} "
            f"auto_vacuum={auto_vacuum} articles={src_articles}, got {verified}"
        )
    return {
        "seconds": round(seconds, 3),
        "file_bytes": dst_p.stat().st_size,
        "verified": verified,
        "encrypted": encrypted,
    }


# ---------------------------------------------------------------------------
#  The workload (identical per size; three hot shapes, two passes)
# ---------------------------------------------------------------------------

def _pct(sorted_ms: list[float], q: float) -> float:
    if not sorted_ms:
        return 0.0
    idx = min(len(sorted_ms) - 1, max(0, round(q * (len(sorted_ms) - 1))))
    return sorted_ms[idx]


def _stats(samples_ms: list[float]) -> dict:
    s = sorted(samples_ms)
    return {
        "n": len(s),
        "p50_ms": round(_pct(s, 0.50), 3),
        "p95_ms": round(_pct(s, 0.95), 3),
        "total_ms": round(sum(s), 1),
    }


def _bench_pass(con, rng: random.Random) -> dict:
    """One pass of the three operation classes; returns per-class stats.

    * point_lookup — one row by PRIMARY KEY reading ``content`` (a 16K page
      decrypts 4x the bytes per point access: the codec-granularity cost side).
    * index_window — a windowed COUNT over ``keyword_mentions(observed_on)``
      (the covering-index hot shape trending/rollups use).
    * content_band — a bounded sequential band summing ``length(content)``
      (the range-scan side: fewer codec calls per byte favors larger pages).
    """
    lo, hi = con.execute("SELECT MIN(id), MAX(id) FROM articles").fetchone()
    out: dict[str, dict] = {}
    if lo is None:
        return {"skipped": "no articles in this store"}

    samples: list[float] = []
    for _ in range(_POINT_LOOKUPS):
        aid = rng.randint(lo, hi)
        t0 = time.perf_counter()
        con.execute("SELECT LENGTH(content) FROM articles WHERE id = ?", (aid,)).fetchone()
        samples.append((time.perf_counter() - t0) * 1000.0)
    out["point_lookup"] = _stats(samples)

    anchor = con.execute("SELECT MAX(observed_on) FROM keyword_mentions").fetchone()[0]
    if anchor:
        samples = []
        for _ in range(_INDEX_WINDOW_RUNS):
            t0 = time.perf_counter()
            con.execute(
                "SELECT COUNT(*) FROM keyword_mentions WHERE observed_on >= date(?, '-30 day')",
                (anchor,),
            ).fetchone()
            samples.append((time.perf_counter() - t0) * 1000.0)
        out["index_window"] = _stats(samples)
    else:
        out["index_window"] = {"skipped": "no keyword mentions in this store"}

    samples = []
    for _ in range(_CONTENT_BAND_RUNS):
        start = rng.randint(lo, max(lo, hi - _CONTENT_BAND_ROWS))
        t0 = time.perf_counter()
        con.execute(
            "SELECT SUM(LENGTH(content)) FROM articles WHERE id BETWEEN ? AND ?",
            (start, start + _CONTENT_BAND_ROWS),
        ).fetchone()
        samples.append((time.perf_counter() - t0) * 1000.0)
    out["content_band"] = _stats(samples)
    return out


def bench_store(db_path: Path | str) -> dict:
    """Run the two-pass workload against one store (a rebuilt target). The first
    pass runs on a freshly opened connection (cold-ish — the OS file cache is
    NOT controlled, stated in the caveats); the second re-runs the identical
    operations (warm). Deterministic sampling (fixed seed) so every size and
    every machine runs the SAME operations."""
    from src.database.connect import connect

    con = connect(Path(db_path), check_same_thread=False)
    try:
        first = _bench_pass(con, random.Random(_SEED))
        second = _bench_pass(con, random.Random(_SEED))
    finally:
        con.close()
    return {"first_pass": first, "second_pass_warm": second}


# ---------------------------------------------------------------------------
#  The A/B run
# ---------------------------------------------------------------------------

def sweep_stale_stages(work_dir: Path | str) -> int:
    """Remove leftovers from a crashed/killed previous run (our exclusive
    ``.pagesize-bench-`` prefix; the job is a singleton, so anything present at
    start is stale)."""
    n = 0
    d = Path(work_dir)
    if not d.is_dir():
        return 0
    for p in d.glob(_STAGE_PREFIX + "*"):
        try:
            p.unlink()
            n += 1
        except OSError:  # a locked/foreign file is left alone, never forced
            _LOG.warning("could not sweep stale bench stage %s", p)
    return n


def validate_work_dir(work_dir: Path | str, src_bytes: int) -> None:
    """Refuse up front when the work dir cannot hold one rebuild (built
    sequentially and deleted between sizes, so ~1.15x the source is enough)."""
    d = Path(work_dir)
    if not d.is_dir():
        raise BenchRefused(f"work dir does not exist or is not a directory: {d}")
    if not os.access(d, os.W_OK):
        raise BenchRefused(f"work dir is not writable: {d}")
    free = shutil.disk_usage(d).free
    need = int(src_bytes * 1.15)
    if free < need:
        raise BenchRefused(
            f"not enough free space in {d}: need ~{need} bytes for one rebuild "
            f"({src_bytes}-byte source x 1.15), have {free}. Pass a work dir on a "
            "larger drive (the rebuilds are staged there and deleted afterwards)."
        )


def _machine_facts() -> dict:
    import platform

    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }


def run_pagesize_ab(
    src_db: Path | str,
    work_dir: Path | str,
    *,
    page_sizes: tuple[int, ...] = (4096, 16384),
    auto_vacuum: int = _DEFAULT_AUTO_VACUUM,
    passphrase: str | None = None,
    should_stop=None,
    progress_cb=None,
) -> dict:
    """The full A/B: per candidate size, rebuild -> self-verify -> bench ->
    delete, sequentially (one rebuild on disk at a time). Returns the report
    dict (also what gets persisted). Cancellation between phases leaves no
    stage file and an honestly-marked partial report."""
    from src.database.connect import is_encrypted_file

    src_p = Path(src_db)
    if not src_p.exists():
        raise BenchRefused(f"source store not found: {src_p}")
    src_bytes = src_p.stat().st_size
    work_p = Path(work_dir)
    work_p.mkdir(parents=True, exist_ok=True)
    swept = sweep_stale_stages(work_p)
    validate_work_dir(work_p, src_bytes)

    from src.database.connect import connect

    scon = connect(src_p, check_same_thread=False)
    try:
        source_facts = {
            "db_bytes": src_bytes,
            "encrypted": bool(is_encrypted_file(src_p)),
            "page_size": scon.execute("PRAGMA page_size").fetchone()[0],
            "auto_vacuum": scon.execute("PRAGMA auto_vacuum").fetchone()[0],
            "articles": scon.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
            "keyword_mentions": scon.execute("SELECT COUNT(*) FROM keyword_mentions").fetchone()[0],
        }
    finally:
        scon.close()

    sizes: list[dict] = []
    cancelled = False
    total_steps = len(page_sizes) * 3
    step = 0
    for ps in page_sizes:
        stage = work_p / f"{_STAGE_PREFIX}{ps}.db"
        entry: dict = {"page_size": ps, "auto_vacuum": auto_vacuum}
        try:
            if should_stop is not None and should_stop():
                cancelled = True
                break
            if progress_cb is not None:
                progress_cb(step, total_steps, f"rebuilding at page_size={ps}")
            entry["rebuild"] = rebuild_at_pragmas(
                src_p, stage, page_size=ps, auto_vacuum=auto_vacuum, passphrase=passphrase
            )
            step += 1
            if should_stop is not None and should_stop():
                cancelled = True
                break
            if progress_cb is not None:
                progress_cb(step, total_steps, f"benching page_size={ps}")
            entry["workload"] = bench_store(stage)
            step += 1
            if progress_cb is not None:
                progress_cb(step, total_steps, f"cleaning page_size={ps}")
            step += 1
        except (BenchRefused, BenchVerifyError) as exc:
            entry["error"] = str(exc)
        finally:
            for suffix in ("", "-wal", "-shm"):
                Path(str(stage) + suffix).unlink(missing_ok=True)
            sizes.append(entry)
    if cancelled and progress_cb is not None:
        progress_cb(step, total_steps, "cancelled")

    return {
        "schema": PAGESIZE_BENCH_SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": source_facts,
        "machine": _machine_facts(),
        "stale_stages_swept": swept,
        "cancelled": cancelled,
        "sizes": sizes,
        "method": (
            "each candidate page_size is a full rebuild of the source store "
            "(VACUUM INTO for plaintext, sqlcipher_export for encrypted — same "
            "passphrase, so the codec stays in the measurement), self-verified by "
            "reading the target's pragmas + article count back, then the identical "
            "deterministic workload runs twice (first pass after a fresh open, "
            "second warm): point lookups by id, a 30-day covering-index window "
            "over keyword_mentions, and bounded sequential content bands. Numbers "
            "side by side; no composite verdict."
        ),
        "caveats": [
            "the OS file cache is not controlled between passes — treat first_pass as "
            "cold-ISH, and compare like against like across runs",
            "the workload is a proxy of the app's hot query shapes, not the full app",
            "compare the TREND across corpus sizes/machines, never one point alone",
            "rebuild.seconds is also the measured cost of the real store migration "
            "(the DB-10 seam rebuild) at this corpus size",
        ],
    }


# ---------------------------------------------------------------------------
#  Persistence + the job worker (mirrors the P0-validation pattern)
# ---------------------------------------------------------------------------

def _report_dir() -> Path:
    from src.paths import data_dir

    d = data_dir() / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_pagesize_bench_report(report: dict) -> Path:
    import json

    out = _report_dir() / f"oo-pagesize-bench-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, out)
    return out


def last_pagesize_bench_report() -> dict:
    """The newest saved report (for the all-diagnostics bundle), or an honest
    stub when none has been run — never fabricates a measurement."""
    import json

    try:
        files = sorted(_report_dir().glob("oo-pagesize-bench-*.json"))
        if not files:
            return {
                "schema": PAGESIZE_BENCH_SCHEMA,
                "available": False,
                "note": (
                    "no page-size bench has been run yet — run it from Settings -> "
                    "Diagnostics, or POST /api/diagnostics/pagesize-bench."
                ),
            }
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a diagnostic must degrade, never 500
        return {"schema": PAGESIZE_BENCH_SCHEMA, "available": False, "error": str(exc)[:300]}


def _live_db_path() -> Path:
    from src.backup.sqlite_backup import live_db_path

    return live_db_path()


def pagesize_bench_worker(ctx, *, work_dir: str | None = None, page_sizes=None) -> dict:
    """BackgroundJob worker: bench the LIVE corpus (read-only through the rebuild
    reads), persist the report, return {path, filename, summary facts}."""
    src = _live_db_path()
    wd = Path(work_dir) if work_dir else _report_dir() / "bench-stage"
    wd.mkdir(parents=True, exist_ok=True)
    sizes = tuple(int(p) for p in (page_sizes or (4096, 16384)))
    ctx.set_progress(done=0, total=len(sizes) * 3, detail="starting")
    report = run_pagesize_ab(
        src,
        wd,
        page_sizes=sizes,
        should_stop=lambda: ctx.stopping,
        progress_cb=lambda d, t, name: ctx.set_progress(done=d, total=t, detail=name),
    )
    path = save_pagesize_bench_report(report)
    return {
        "path": str(path),
        "filename": path.name,
        "cancelled": report.get("cancelled", False),
        "sizes_completed": [s["page_size"] for s in report.get("sizes", []) if "workload" in s],
        "db_bytes": report.get("source", {}).get("db_bytes"),
    }
