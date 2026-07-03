"""A local, network-free snapshot cache of the last open-hazard feed pull.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The open hazard feeds (USGS, GDACS) are relayed LIVE from the
network by :mod:`src.api.hazards` — nothing persists them. The severity-tiered
alert layer (:mod:`src.analytics.alerts`) is a *briefing producer*, and a producer
must NEVER touch the network (the local-first non-negotiable). So the alert layer
reads the LAST-KNOWN hazard records from this small JSON snapshot instead of
fetching. The snapshot is written by an explicit, consented action (the
``/api/signals/hazards/snapshot`` endpoint, from records the app already fetched, or
a guarded refresh) — never at boot, never by the producer.

Honesty by construction:
  * the snapshot records exactly what a provider published (severity is the
    provider's own alert level — GDACS Green/Orange/Red → info/watch/urgent —
    never our invention);
  * the ``saved_at`` timestamp is stored so a reader can DISCLOSE staleness — an
    old snapshot is reported as stale, never silently presented as current;
  * absence is honest: no snapshot → an empty record set, never a fabricated one.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

_LOG = logging.getLogger(__name__)

SNAPSHOT_VERSION = "oo-hazards-snapshot-1"
# Beyond this age a snapshot is reported STALE (the alert layer still shows it but
# says how old it is — silence is not safety, and a stale relay is not "now").
DEFAULT_MAX_AGE_HOURS = 48
# Never let a runaway feed balloon the cache: keep the most recent N records.
_MAX_RECORDS = 2000


def _snapshot_path():
    from src.paths import data_dir

    return data_dir() / "hazards_snapshot.json"


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def save_snapshot(records: list[dict], *, now: datetime | None = None) -> dict:
    """Persist the most recent hazard records to the local snapshot (atomic write).

    ``records`` are hazard dicts as produced by :mod:`src.hazards.parse` (each with a
    provider ``severity``, ``type``, ``time``, coordinates, ``url``…). Only the fields
    the alert layer needs are kept, bounded to ``_MAX_RECORDS``. Returns the saved
    payload. Best-effort, local only — never raises on a bad record (skips it).
    """
    ts = _now(now)
    clean: list[dict] = []
    for r in records or []:
        if not isinstance(r, dict):
            continue
        clean.append(
            {
                "source": r.get("source"),
                "id": r.get("id"),
                "type": r.get("type"),
                "title": r.get("title"),
                "severity": r.get("severity"),
                "magnitude": r.get("magnitude"),
                "lat": r.get("lat"),
                "lon": r.get("lon"),
                "place": r.get("place"),
                "time": r.get("time"),
                "url": r.get("url"),
            }
        )
        if len(clean) >= _MAX_RECORDS:
            break
    payload = {"version": SNAPSHOT_VERSION, "saved_at": ts.isoformat(), "records": clean}
    path = _snapshot_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)
    _LOG.info("hazards snapshot saved: %d records", len(clean))
    return payload


def load_snapshot(
    *, max_age_hours: int = DEFAULT_MAX_AGE_HOURS, now: datetime | None = None
) -> dict:
    """Read the local hazard snapshot — NEVER touches the network.

    Returns ``{"records": [...], "saved_at": iso|None, "age_hours": float|None,
    "stale": bool, "available": bool}``. An absent/corrupt/version-mismatched file
    yields an honest empty result (``available=False``, no records) rather than a
    guess. ``stale`` is True when the snapshot is older than ``max_age_hours`` — the
    reader shows the records but discloses the age (silence is not safety).
    """
    empty: dict = {"records": [], "saved_at": None, "age_hours": None, "stale": True, "available": False}
    path = _snapshot_path()
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt cache must not break the feed
        _LOG.warning("hazards_snapshot.json unreadable; treating as empty", exc_info=True)
        return empty
    if not isinstance(data, dict) or data.get("version") != SNAPSHOT_VERSION:
        return empty
    records = [r for r in (data.get("records") or []) if isinstance(r, dict)]
    saved_at = data.get("saved_at")
    age_hours: float | None = None
    stale = True
    try:
        saved_dt = datetime.fromisoformat(saved_at) if saved_at else None
    except (ValueError, TypeError):
        saved_dt = None
    if saved_dt is not None:
        if saved_dt.tzinfo is None:
            saved_dt = saved_dt.replace(tzinfo=UTC)
        age_hours = max(0.0, (_now(now) - saved_dt).total_seconds() / 3600.0)
        stale = age_hours > max_age_hours
    return {
        "records": records,
        "saved_at": saved_at,
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "stale": stale,
        "available": True,
    }
