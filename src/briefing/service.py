"""
Briefing assembly, caching, and dismissal — the feed behind Home.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

App-efficiency rule (offline, single machine): **precompute, cache, serve cached.**
The briefing never computes per request — Home reads a cached card set and loads
instantly. The cache is refreshed by the background scheduler after each scrape (or
on an explicit user "Refresh"). Dismissals are stored separately so a dismissed card
can be restored and a later recompute re-applies the user's choice, not overwrites it.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from src.briefing.card import BUCKET_LABELS, BUCKETS
from src.briefing.producers import register_default_producers
from src.briefing.registry import run_all

_LOG = logging.getLogger(__name__)

CACHE_VERSION = "oo-briefing-cache-1"

# Register the built-in producers once, at import.
register_default_producers()


def _cache_path():
    from src.paths import data_dir

    return data_dir() / "briefing_cache.json"


def _dismissed_path():
    from src.paths import data_dir

    return data_dir() / "briefing_dismissed.json"


def _bucket_rank(bucket: str) -> int:
    try:
        return BUCKETS.index(bucket)
    except ValueError:
        return len(BUCKETS)


def _magnitude(card: dict) -> float:
    """A within-bucket ordering proxy: the size of the measured signal, else n."""
    value = (card.get("signal") or {}).get("value")
    if isinstance(value, (int, float)):
        return abs(float(value))
    n = card.get("n")
    return float(n) if isinstance(n, (int, float)) else 0.0


def _sorted(cards: list[dict]) -> list[dict]:
    return sorted(cards, key=lambda c: (_bucket_rank(c["bucket"]), -_magnitude(c)))


def dismissed_ids() -> set[str]:
    path = _dismissed_path()
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text("utf-8")).get("ids", []))
    except Exception:  # noqa: BLE001 - a bad file must not break the feed
        _LOG.warning("briefing_dismissed.json unreadable; treating as empty", exc_info=True)
        return set()


def _save_dismissed(ids: set[str]) -> None:
    path = _dismissed_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": CACHE_VERSION, "ids": sorted(ids)}, indent=2), "utf-8")
    tmp.replace(path)


def dismiss(card_id: str) -> set[str]:
    ids = dismissed_ids()
    ids.add(card_id)
    _save_dismissed(ids)
    return ids


def restore(card_id: str) -> set[str]:
    ids = dismissed_ids()
    ids.discard(card_id)
    _save_dismissed(ids)
    return ids


def clear_dismissed() -> None:
    _save_dismissed(set())


def refresh_briefing(session) -> dict:
    """Recompute the briefing from all producers and write the cache. Returns it."""
    cards = [c.to_dict() for c in run_all(session)]
    payload = {
        "version": CACHE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "cards": _sorted(cards),
    }
    path = _cache_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)
    _LOG.info("briefing refreshed: %d cards", len(cards))
    return payload


def _read_cache() -> dict | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        if data.get("version") != CACHE_VERSION:
            return None
        return data
    except Exception:  # noqa: BLE001 - a corrupt cache just triggers a recompute
        _LOG.warning("briefing_cache.json unreadable; will recompute", exc_info=True)
        return None


def _present(payload: dict, *, include_dismissed: bool) -> dict:
    """Shape a cache payload into the API view, applying dismissals + grouping."""
    dismissed = dismissed_ids()
    cards = payload.get("cards", [])
    if not include_dismissed:
        visible = [c for c in cards if c["id"] not in dismissed]
    else:
        visible = [{**c, "dismissed": c["id"] in dismissed} for c in cards]
    buckets = []
    for b in BUCKETS:
        items = [c for c in visible if c["bucket"] == b]
        if items:
            buckets.append({"bucket": b, "label": BUCKET_LABELS[b], "cards": items})
    return {
        "generated_at": payload.get("generated_at"),
        "count": len(visible),
        "total": len(cards),
        "dismissed_count": len(dismissed),
        "buckets": buckets,
        "cards": visible,
    }


def get_briefing(session, *, force: bool = False, include_dismissed: bool = False) -> dict:
    """Return the cached briefing (computing once if absent or ``force``)."""
    payload = None if force else _read_cache()
    if payload is None:
        payload = refresh_briefing(session)
    return _present(payload, include_dismissed=include_dismissed)
