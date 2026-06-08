"""
Wikimedia ORES (edit-quality model) client + response parser.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ORES is a Wikimedia service giving per-revision "damaging" and "good-faith"
probabilities. We use it as an *attributed* signal: scores are stored with their
provenance and presented as "labelled-by-ORES", never as ground truth. Optional
and fail-open — if the service is unavailable, tracking proceeds without scores.

The parser is pure (unit-tested with a fixture); the HTTP call is injectable.
"""

from __future__ import annotations

import logging

_LOG = logging.getLogger(__name__)
ORES_ENDPOINT = "https://ores.wikimedia.org/v3/scores"
PROVENANCE = "ores:damaging,goodfaith"


def dbname(wiki: str) -> str:
    """Wiki code -> ORES database name (e.g. 'en' -> 'enwiki')."""
    return f"{(wiki or 'en').strip().lower()}wiki"


def _prob_true(model_block: dict) -> float | None:
    try:
        return float(model_block["score"]["probability"]["true"])
    except (KeyError, TypeError, ValueError):
        return None


def parse_ores(payload: dict, wiki: str) -> dict:
    """Parse an ORES v3 response into {revid: {damaging, goodfaith, provenance}}."""
    out: dict[int, dict] = {}
    scores = (payload or {}).get(dbname(wiki), {}).get("scores", {})
    for revid_str, models in scores.items():
        try:
            revid = int(revid_str)
        except (TypeError, ValueError):
            continue
        out[revid] = {
            "damaging": _prob_true(models.get("damaging", {})),
            "goodfaith": _prob_true(models.get("goodfaith", {})),
            "provenance": PROVENANCE,
        }
    return out


class OresClient:
    """Score revisions via ORES. ``session`` is injectable for testing."""

    def __init__(self, *, session=None, timeout: float = 20.0,
                 user_agent: str = "OpenOmniscienceBot/0.4 (+https://github.com/ideotion/Open-Omniscience)"):
        import requests

        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.timeout = timeout

    def score(self, wiki: str, revids: list[int]) -> dict:
        """Return {revid: {...}} for the given revids (empty on any failure)."""
        if not revids:
            return {}
        params = {"models": "damaging|goodfaith", "revids": "|".join(str(r) for r in revids)}
        try:
            resp = self.session.get(f"{ORES_ENDPOINT}/{dbname(wiki)}/", params=params, timeout=self.timeout)
            resp.raise_for_status()
            return parse_ores(resp.json(), wiki)
        except Exception:  # noqa: BLE001 - ORES is optional; never break tracking
            _LOG.warning("ORES scoring failed for %s", wiki, exc_info=True)
            return {}
