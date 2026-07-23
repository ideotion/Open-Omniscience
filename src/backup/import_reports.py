"""
Persisted, downloadable import reports (S3.5, 2026-07-23 field-feedback workflow).

The 2026-07-20 maintainer ruling (field-feedback A1) asked for import-run reports
"downloadable ... JSON + Markdown, PERSISTED on disk, and the persisted reports RIDE
the backup export/import". The restore-merge path already computes a rich report
(src/backup/merge.py's ``run_restore``: corpus-delta before/after, per-table plan
tally, quarantine summary) but only persists it INSIDE the corpus DB itself
(``merge_batches.report_json``), which is not directly downloadable and does not
survive being a separate file a user can keep. This module is the missing piece: a
standalone JSON + Markdown FILE per import run, written under
``data_dir()/import_reports/``, so it (a) can be listed/downloaded via a small API
surface and (b) rides the encrypted oo-backup-2 export (wired into
``src.backup.artifact._collect_members`` alongside this module).

No fabricated numbers: every field in a persisted report is copied verbatim from a
real report dict already built by the restore-merge or newsletter-import path.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DIR_NAME = "import_reports"


def _reports_dir() -> Path:
    from src.paths import data_dir

    return data_dir() / _DIR_NAME


def _short_id() -> str:
    import secrets

    return secrets.token_hex(4)


def persist_import_report(kind: str, report: dict[str, Any], *, run_id: str | None = None) -> Path:
    """Write ``report`` as a standalone JSON file under
    ``data_dir()/import_reports/<kind>-<UTC timestamp>-<run_id or a random short id>.json``.

    Atomic (temp file + ``os.replace``, mirroring ``src/backup/folder_backup.py``'s
    ``_atomic_copy`` / ``src/backup/volumes.py``'s reassembly pattern) so a crash mid-write
    never leaves a half-written report file. UTF-8 explicit. Returns the final path.
    """
    d = _reports_dir()
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = run_id if run_id else _short_id()
    name = f"{kind}-{ts}-{suffix}.json"
    dest = d / name
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        tmp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def _fmt_count(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def render_import_report_markdown(report: dict[str, Any]) -> str:
    """A short, honest, human-readable Markdown rendering of an import/restore report.

    Pure function -- takes exactly the numbers already present in ``report`` (never
    invents one). The headline is stated in the ARTICLES unit specifically (never a
    cross-table row-sum across every merged table -- the maintainer's own 2026-07-20
    complaint: "4,855,433 imported ... I'm sure it doesn't contain 5 million articles").
    """
    lines: list[str] = []
    kind = report.get("kind") or report.get("artifact_kind") or "import"
    lines.append(f"# Import report ({kind})")
    lines.append("")

    plan = report.get("plan") or {}
    articles_plan = plan.get("articles") or {}
    new_articles = articles_plan.get("new")
    dup_articles = articles_plan.get("duplicate")
    if new_articles is not None:
        headline = f"**{_fmt_count(new_articles)} new articles**"
        if dup_articles:
            headline += f" ({_fmt_count(dup_articles)} duplicates skipped)"
        lines.append(headline)
    elif "tally" in report:
        tally = report["tally"] or {}
        headline_n = tally.get("new") or tally.get("imported")
        if headline_n is not None:
            lines.append(f"**{_fmt_count(headline_n)} new articles imported**")
    lines.append("")

    if plan:
        lines.append("## Per-table breakdown")
        lines.append("")
        lines.append("| table | new | duplicate | conflict |")
        lines.append("| --- | ---: | ---: | ---: |")
        for table_name, counts in sorted(plan.items()):
            if not isinstance(counts, dict):
                continue
            lines.append(
                f"| {table_name} | {_fmt_count(counts.get('new'))} "
                f"| {_fmt_count(counts.get('duplicate'))} | {_fmt_count(counts.get('conflict'))} |"
            )
        lines.append("")

    delta = report.get("corpus_delta")
    if delta and "before" in delta and "after" in delta:
        lines.append("## Corpus growth (before → after)")
        lines.append("")
        lines.append("| dimension | before | after |")
        lines.append("| --- | ---: | ---: |")
        before, after = delta["before"], delta["after"]
        for dim in ("articles", "sources", "languages", "countries", "keywords"):
            if dim in before or dim in after:
                lines.append(f"| {dim} | {_fmt_count(before.get(dim))} | {_fmt_count(after.get(dim))} |")
        if before.get("date_min") or after.get("date_max"):
            lines.append(
                f"| date span | {before.get('date_min') or '—'} .. {before.get('date_max') or '—'} "
                f"| {after.get('date_min') or '—'} .. {after.get('date_max') or '—'} |"
            )
        lines.append("")

    work = report.get("work_induced")
    if work:
        lines.append("## Work induced")
        lines.append("")
        if "sources_pending" in work:
            lines.append(
                f"- {_fmt_count(work['sources_pending'])} sources in the corpus are enabled "
                "but not yet qualified (total across the whole corpus, not just this import)."
            )
        if "sources_candidates" in work:
            lines.append(
                f"- {_fmt_count(work['sources_candidates'])} discovered source candidates "
                "await qualification review (corpus-wide total)."
            )
        lines.append("")

    qs = report.get("quarantine_summary")
    if qs:
        lines.append("## Quarantine screening")
        lines.append("")
        lines.append(
            f"- Scanned {_fmt_count(qs.get('scanned'))} of the newly-imported articles; "
            f"quarantined {_fmt_count(qs.get('quarantined'))} as likely non-article junk "
            f"({_fmt_count(qs.get('newly_written'))} newly stamped, "
            f"{_fmt_count(qs.get('already_quarantined'))} already flagged)."
        )
        by_reason = qs.get("by_reason") or {}
        for reason, n in sorted(by_reason.items()):
            lines.append(f"  - {reason}: {_fmt_count(n)}")
        lines.append("")

    return "\n".join(lines)


def _safe_report_path(filename: str) -> Path | None:
    """Resolve ``filename`` under the reports dir, refusing any path traversal (the same
    resolve()-and-contain check ``src/backup/folder_backup.py``'s ``_safe_member_path``
    uses). Rejects a name containing a path separator or ``..`` outright before ever
    touching the filesystem."""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return None
    base = _reports_dir()
    candidate = base / filename
    try:
        base_r = base.resolve()
        cand_r = candidate.resolve()
    except OSError:
        return None
    if cand_r != base_r and base_r not in cand_r.parents:
        return None
    return candidate


def list_import_reports() -> list[dict[str, Any]]:
    """Every persisted report, newest first. Read-only; an empty/missing directory is
    simply an empty list (never an error -- a fresh install has no reports yet)."""
    d = _reports_dir()
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(d.glob("*.json")):
        try:
            stat = p.stat()
        except OSError:
            continue
        # filename shape: <kind>-<timestamp>-<id>.json
        kind = p.stem.split("-", 1)[0]
        out.append(
            {
                "filename": p.name,
                "kind": kind,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                "size_bytes": stat.st_size,
            }
        )
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return out


def read_import_report(filename: str) -> dict[str, Any]:
    """Read + parse a persisted report by its exact filename. Raises ``FileNotFoundError``
    for an unknown/invalid/traversal-attempting name (never silently returns another
    file's contents)."""
    p = _safe_report_path(filename)
    if p is None or not p.is_file():
        raise FileNotFoundError(filename)
    return json.loads(p.read_text(encoding="utf-8"))
