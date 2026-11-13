"""
Reanalysis slices held on this machine, in the encrypted store (R675, R683).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A slice names a place, and a place a person types is probably where they live. So every slice
(the Climate tab's "Your place" view and the Home card's weather context alike) lives in the
``app_state`` table of the (encrypted) corpus database, never in a loose file, keyed by a hash of
the exact request URL, which carries only the ROUNDED place
(:func:`src.weather.openmeteo.round_place`). The plaintext folder older versions wrote is deleted
at startup (:func:`src.weather.openmeteo.purge_plaintext_cache`). Nothing here logs a URL or a coordinate. Local only: this
module never fetches.
"""

from __future__ import annotations

import hashlib

KEY_PREFIX = "weather.slice."


def slice_key(url: str) -> str:
    """The ``app_state`` key for the slice fetched from ``url``."""
    return KEY_PREFIX + hashlib.sha256(url.encode("utf-8")).hexdigest()[:40]


class HeldSlices:
    """``get(url)`` / ``put(url, payload)`` over the encrypted key-value store."""

    def get(self, url: str) -> dict | None:
        from src.config.kv_store import kv_get_json

        payload = kv_get_json(slice_key(url))
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        prov = payload.get("provenance")
        # A hash collision, or a row written for another URL, is a miss, never another place's numbers.
        if not isinstance(prov, dict) or prov.get("requested_url") != url:
            return None
        return payload

    def put(self, url: str, payload: dict) -> None:
        from src.config.kv_store import kv_set_json

        kv_set_json(slice_key(url), payload)


__all__ = ["KEY_PREFIX", "HeldSlices", "slice_key"]
