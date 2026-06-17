"""Tracked official-statistics fetches + their scheduled vintage refresh (ruling #12).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Ruling 2026-06-17 #12: keep figure fetching user-initiated AND add a scheduled
auto-refresh of vintages. When the user fetches figures we RECORD the fetch as a
``StatSubscription``; the scheduler later REPLAYS each DUE subscription, storing a new
vintage every time (the figure store is vintage-additive — a re-fetch is never an
overwrite). The refresh is:
  * FRESHNESS-gated — a subscription is due only when its ``interval_days`` has elapsed
    (vintages do not change daily; default 30 days), so a pass never re-hammers a fresh
    series.
  * AIRPLANE-gated — it routes through the same guarded fetch (which refuses under the
    kill switch); we also bail up front when the kill switch is engaged, so an offline
    pass opens NO socket.
  * BEST-EFFORT — one failing subscription is recorded (``last_status``) and never
    breaks the others or the pass.
No score anywhere; this only records WHAT to re-fetch and WHEN it last ran.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import StatSubscription

Getter = Callable[[str], Any]


def _params_key(params: dict[str, str] | None) -> str | None:
    if not params:
        return None
    return json.dumps(dict(sorted(params.items())), separators=(",", ":"))


def record_subscription(
    session: Session, *, source: str, indicator: str | None = None,
    country: str | None = None, dataset: str | None = None,
    params: dict[str, str] | None = None, agency: str | None = None,
    interval_days: int = 30,
) -> StatSubscription:
    """Upsert a tracked fetch (dedupe on the exact fetch parameters).

    Re-recording the same fetch is idempotent (returns the existing row). The caller
    owns the transaction.
    """
    source = (source or "").strip().lower()
    pj = _params_key(params)
    existing = session.execute(
        select(StatSubscription).where(
            StatSubscription.source == source,
            StatSubscription.indicator == (indicator or None),
            StatSubscription.country == (country or None),
            StatSubscription.dataset == (dataset or None),
            StatSubscription.params_json == pj,
            StatSubscription.agency == (agency or None),
        )
    ).scalars().first()
    if existing is not None:
        return existing
    sub = StatSubscription(
        source=source, indicator=indicator or None, country=country or None,
        dataset=dataset or None, params_json=pj, agency=agency or None,
        interval_days=max(1, int(interval_days)), enabled=True,
    )
    session.add(sub)
    session.flush()
    return sub


def _sub_dict(s: StatSubscription) -> dict:
    return {
        "id": s.id, "source": s.source, "indicator": s.indicator, "country": s.country,
        "dataset": s.dataset, "params": json.loads(s.params_json) if s.params_json else None,
        "agency": s.agency, "interval_days": s.interval_days, "enabled": bool(s.enabled),
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
        "last_status": s.last_status,
    }


def list_subscriptions(session: Session) -> list[dict]:
    rows = session.execute(
        select(StatSubscription).order_by(StatSubscription.created_at.desc())
    ).scalars().all()
    return [_sub_dict(s) for s in rows]


def set_subscription(session: Session, sub_id: int, **fields) -> StatSubscription | None:
    s = session.get(StatSubscription, sub_id)
    if s is None:
        return None
    if "enabled" in fields and fields["enabled"] is not None:
        s.enabled = bool(fields["enabled"])
    if "interval_days" in fields and fields["interval_days"] is not None:
        s.interval_days = max(1, int(fields["interval_days"]))
    session.flush()
    return s


def delete_subscription(session: Session, sub_id: int) -> bool:
    s = session.get(StatSubscription, sub_id)
    if s is None:
        return False
    session.delete(s)
    session.flush()
    return True


def due_subscriptions(session: Session, *, now: datetime | None = None) -> list[StatSubscription]:
    """Enabled subscriptions whose interval has elapsed (or that never fetched)."""
    now = (now or datetime.now(UTC)).replace(tzinfo=None)
    rows = session.execute(
        select(StatSubscription).where(StatSubscription.enabled.is_(True))
    ).scalars().all()
    due = []
    for s in rows:
        last = s.last_fetched_at
        if last is None:
            due.append(s)
            continue
        if last.tzinfo is not None:
            last = last.replace(tzinfo=None)
        if last <= now - timedelta(days=s.interval_days):
            due.append(s)
    return due


def refresh_due(
    session: Session, *, get: Getter | None = None, now: datetime | None = None,
    limit: int = 50,
) -> dict:
    """Replay every DUE subscription, storing new vintages. Airplane- + freshness-gated.

    Returns ``{checked, refreshed, stored, skipped_offline, errors}``. Opens NO socket
    when the kill switch is engaged (returns ``skipped_offline`` = number due). One bad
    subscription is recorded in ``last_status`` and never breaks the others.
    """
    from src.ingest import kill_switch_active
    from src.stats import fetch as statfetch
    from src.stats.store import store_figures

    now_dt = (now or datetime.now(UTC)).replace(tzinfo=None)
    due = due_subscriptions(session, now=now)[: max(0, int(limit))]
    if not due:
        return {"checked": 0, "refreshed": 0, "stored": 0, "skipped_offline": 0, "errors": 0}
    if kill_switch_active():
        # Offline: do not attempt any fetch (no socket); leave subscriptions untouched.
        return {"checked": len(due), "refreshed": 0, "stored": 0,
                "skipped_offline": len(due), "errors": 0}

    refreshed = stored = errors = 0
    for s in due:
        try:
            if s.source == "worldbank":
                figs = statfetch.fetch_worldbank(s.indicator or "", s.country or "all", get=get)
            else:
                params = json.loads(s.params_json) if s.params_json else None
                figs = statfetch.fetch_eurostat(
                    s.dataset or "", params=params, get=get, agency=(s.agency or "eurostat")
                )
            tally = store_figures(session, figs)
            stored += tally["stored"]
            refreshed += 1
            s.last_fetched_at = now_dt
            s.last_status = f"stored {tally['stored']} (new vintage)"
        except Exception as exc:  # noqa: BLE001 - best-effort; record + continue
            errors += 1
            s.last_fetched_at = now_dt
            s.last_status = f"error: {str(exc)[:160]}"
    session.flush()
    return {"checked": len(due), "refreshed": refreshed, "stored": stored,
            "skipped_offline": 0, "errors": errors}
