"""
Scheduler run log + opt-in delta drop-folder (0.0.8 part 2, WP3 / RM-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every scheduler run appends one JSON line to ``data/scheduler_runs.jsonl`` --
an auditable, local record of what ran, when, and what it produced (the §0.5
auditability invariant applied to the background ingester). Optionally, when
the operator sets ``export_dir``, each run also drops the new-articles delta
as a self-describing JSON file into that local folder (no network, no inbound
service -- a pure file drop a newsroom pipeline can watch). Off by default.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

_LOG = logging.getLogger(__name__)

_MAX_RUNS_READ = 200


def _runs_path() -> Path:
    from src.paths import data_dir

    return data_dir() / "scheduler_runs.jsonl"


def record_run(report: dict) -> None:
    """Append one run report line. Best-effort: never raises into the scheduler."""
    try:
        path = _runs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(report, sort_keys=True, default=str) + "\n")
    except Exception:  # noqa: BLE001 - the log must never break a scrape
        _LOG.warning("could not append scheduler run report", exc_info=True)


def recent_runs(limit: int = 20) -> list[dict]:
    """The most recent run reports, newest first (tail of the JSONL)."""
    path = _runs_path()
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        lines = path.read_text("utf-8").splitlines()[-_MAX_RUNS_READ:]
        for line in lines:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn line (crash mid-write) is skipped, not fatal
    except Exception:  # noqa: BLE001
        _LOG.warning("could not read scheduler run log", exc_info=True)
    return list(reversed(rows))[: max(1, min(limit, _MAX_RUNS_READ))]


def export_delta(session, *, started_at: datetime, export_dir: str) -> str | None:
    """Write the articles stored since ``started_at`` into ``export_dir``.

    Returns the written file path, or None when there is nothing new. The file
    carries the standard versioned export envelope, so downstream pipelines get
    the same contract as the API exports.
    """
    from src.database.models import Article
    from src.utils.export_envelope import envelope

    cutoff = started_at.replace(tzinfo=None) if started_at.tzinfo else started_at
    rows = (
        session.query(Article)
        .filter(Article.created_at >= cutoff)
        .order_by(Article.id)
        .all()
    )
    if not rows:
        return None
    payload = [
        {
            "id": a.id,
            "title": a.title,
            "url": a.url,
            "canonical_url": a.canonical_url,
            "source": a.source.name if a.source else None,
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "language": a.language,
            "hash": a.hash,
        }
        for a in rows
    ]
    out_dir = Path(export_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"oo-delta-{stamp}.json"
    doc = envelope(
        kind="scheduler-delta",
        query={"created_since": started_at.isoformat()},
        count=len(payload),
        payload=payload,
    )
    path.write_text(json.dumps(doc, indent=1, default=str), "utf-8")
    return str(path)
