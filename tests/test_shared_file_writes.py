"""Detector for unconverted writes to files several servers share (R176).

Before: a module could ``os.replace`` a fixed ``.tmp``, append to, or ``write_text`` a data-folder file with no cross-process lock, and nothing said so.
Now every such site outside ``src/safety/file_lock.py`` is listed here with the lane that will convert it and why it is waiting, and a NEW site fails this test and
names its line. An entry whose site no longer exists also fails (a stale allowlist hides the next regression). This is a position-based scan of the source: it finds
the call shapes, not what the path is (a call inside a ``with file_lock(...)`` block is held and passes), so it refuses on a site that writes a path outside the data folder too; such a site gets an entry with that reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OWNER = "src/safety/file_lock.py"
REASON = "awaiting owner conversion"

#: ``module path -> (number of unconverted sites, the lane that converts them;)``. Every entry's reason is REASON. A conversion lowers its count; a module at zero is removed.
_ALLOWED: dict[str, tuple[int, str]] = {
    "src/ai_layer/activity.py": (1, "rc2"),
    "src/ai_layer/bench_batch.py": (2, "rc2"),
    "src/ai_layer/model_bench.py": (3, "rc2"),
    "src/ai_layer/perception_job.py": (1, "rc2"),
    "src/ai_layer/qualification_assist.py": (1, "qual"),
    "src/ai_layer/triage.py": (1, "rc2"),
    "src/analytics/columnar.py": (1, "keyword"),
    "src/analytics/criteria_calibration.py": (2, "keyword"),
    "src/analytics/filters.py": (1, "keyword"),
    "src/analytics/gold_builder.py": (2, "keyword"),
    "src/analytics/keyword_fold.py": (2, "keyword"),
    "src/analytics/quarantine_job.py": (1, "keyword"),
    "src/analytics/reindex_job.py": (1, "keyword"),
    "src/analytics/ring_loader.py": (1, "keyword"),
    "src/analytics/rollup_hold.py": (2, "keyword"),
    "src/analytics/rollup_marker.py": (2, "keyword"),
    "src/analytics/source_topics.py": (1, "keyword"),
    "src/analytics/stoplist_recompute.py": (1, "keyword"),
    "src/analytics/store.py": (1, "keyword"),
    "src/analytics/upload_parts.py": (1, "keyword"),
    "src/analytics/weather_signals.py": (1, "keyword"),
    "src/api/ai.py": (1, "rc2"),
    "src/api/diagnostics/bundle.py": (1, "rc2"),
    "src/api/diagnostics/keywords.py": (1, "keyword"),
    "src/api/diagnostics_volumes.py": (4, "export"),
    "src/api/markets.py": (1, "Plan J"),
    "src/backup/artifact.py": (5, "export"),
    "src/backup/country_migration.py": (2, "export"),
    "src/backup/export_folder.py": (2, "export"),
    "src/backup/export_summary.py": (2, "export"),
    "src/backup/folder_backup.py": (2, "WAL"),
    "src/backup/import_queue.py": (2, "WAL"),
    "src/backup/import_reports.py": (4, "WAL"),
    "src/backup/merge.py": (14, "export"),
    "src/backup/newsletter_export.py": (1, "export"),
    "src/backup/parity.py": (4, "export"),
    "src/backup/runlog.py": (5, "export"),
    "src/backup/stream_backup.py": (6, "export"),
    "src/backup/volumes.py": (2, "export"),
    "src/briefing/card_audit.py": (1, "keyword"),
    "src/bulletin/evidence.py": (1, "Plan J"),
    "src/bulletin/store.py": (6, "Plan J"),
    "src/catalog/build.py": (1, "qual"),
    "src/catalog/discover_job.py": (2, "qual"),
    "src/custody/pending.py": (3, "Q"),
    "src/custody/settings.py": (1, "Q"),
    "src/custody/signing.py": (2, "Q"),
    "src/database/article_indexes.py": (2, "WAL"),
    "src/database/damage.py": (2, "WAL"),
    "src/database/encrypt_tool.py": (1, "WAL"),
    "src/database/fts_reindex.py": (2, "WAL"),
    "src/database/maintenance.py": (1, "WAL"),
    "src/database/repair.py": (6, "WAL"),
    "src/entities/gazetteer_build.py": (1, "Plan J"),
    "src/events/feeds.py": (2, "Plan J"),
    "src/geo/osm_downloads.py": (2, "OSM"),
    "src/hazards/store.py": (1, "Plan J"),
    "src/ingest/__init__.py": (2, "export"),
    "src/ingest/archive_backfill.py": (2, "export"),
    "src/ingest/import_job.py": (1, "export"),
    "src/integrity/collapse.py": (1, "Plan J"),
    "src/jobs/progress_state.py": (2, "Q"),
    "src/legal/consent.py": (1, "Q"),
    "src/llm/installer.py": (1, "rc2"),
    # the one left: the preserved failed-start log copy; its name carries the second, the pid and the exit code, so no two servers share its temp
    "src/llm/vllm_lifecycle.py": (1, "rc2"),
    "src/monitoring/ai_check.py": (1, "rc2"),
    "src/monitoring/collect_perf.py": (2, "export"),
    "src/monitoring/feed_preflight.py": (1, "rc2"),
    "src/monitoring/field_test.py": (1, "rc2"),
    "src/monitoring/forensics.py": (2, "rc2"),
    "src/monitoring/kpi.py": (4, "rc2"),
    "src/monitoring/p0_validation.py": (2, "rc2"),
    "src/monitoring/preflight.py": (1, "rc2"),
    "src/monitoring/release_run.py": (4, "rc2"),
    "src/monitoring/release_run_fresh_restore.py": (1, "rc2"),
    "src/monitoring/search_timing.py": (3, "rc2"),
    "src/monitoring/secret_scrub.py": (2, "rc2"),
    "src/monitoring/storage_events.py": (2, "WAL"),
    "src/osm/reference_run.py": (2, "OSM"),
    "src/reporting/evidence.py": (1, "Plan J"),
    "src/safety/data_location.py": (1, "Q"),
    "src/safety/data_volume.py": (5, "Q"),
    "src/scheduler/runlog.py": (2, "rc2"),
    "src/weather/openmeteo.py": (1, "Plan J"),
    "src/wiki/dumps.py": (2, "export"),
}


def _append_mode(call: ast.Call) -> bool:
    """True for ``open(path, "a")``, ``path.open("a")`` and the ``mode="a..."`` keyword forms."""
    f = call.func
    if isinstance(f, ast.Name) and f.id == "open":
        pos = call.args[1] if len(call.args) > 1 else None
    elif isinstance(f, ast.Attribute) and f.attr == "open":
        pos = call.args[0] if call.args else None
    else:
        return False
    mode = {k.arg: k.value for k in call.keywords}.get("mode", pos)
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and mode.value.startswith("a")


def _under_file_lock(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """True when ``node`` sits inside a ``with file_lock(...)`` block, which is how a converted site that must also touch the file directly proves it holds the lock."""
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.With):
            for item in cur.items:
                call = item.context_expr
                if isinstance(call, ast.Call):
                    name = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")
                    if name == "file_lock":
                        return True
        cur = parents.get(cur)
    return False


def _sites(tree: ast.AST) -> list[int]:
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        replaces = isinstance(f, ast.Attribute) and f.attr == "replace" and isinstance(f.value, ast.Name) and f.value.id == "os"
        writes = isinstance(f, ast.Attribute) and f.attr in {"write_text", "write_bytes"}
        if (replaces or writes or _append_mode(n)) and not _under_file_lock(n, parents):
            found.append(n.lineno)
    return found


def _scan() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel == OWNER:
            continue
        lines = _sites(ast.parse(p.read_text(encoding="utf-8")))
        if lines:
            out[rel] = sorted(set(lines))
    return out


def test_no_new_unlocked_write_site_and_no_stale_allowance():
    found = _scan()
    new = {m: ls for m, ls in found.items() if len(ls) > _ALLOWED.get(m, (0, ''))[0]}
    stale = {m: n for m, (n, _lane) in _ALLOWED.items() if len(found.get(m, [])) < n}
    assert not new, f"unconverted write sites ({REASON}) -- use src.safety.file_lock, or list the module here with its lane: {new}"
    assert not stale, f"allowed more sites than exist (lower the count): {stale}"
