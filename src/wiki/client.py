"""
Live MediaWiki Action API client (ethical: UA + maxlag + rate limit).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Thin network layer over the pure builders/parsers in ``mediawiki.py``. Honours
the MediaWiki API etiquette (identifying User-Agent, ``maxlag``, a per-process
minimum request interval). ``session`` is injectable so the client is testable
with no network.
"""

from __future__ import annotations

import time

from src.ingest import OO_VERSION
from src.wiki import mediawiki as mw

WIKI_USER_AGENT = (
    f"OpenOmniscienceBot/{OO_VERSION} (+https://github.com/ideotion/Open-Omniscience; "
    "Wikipedia change-tracker; contact open-omniscience@ideotion.com)"
)


class WikiClient:
    def __init__(
        self,
        *,
        session=None,
        user_agent: str = WIKI_USER_AGENT,
        min_interval_s: float = 1.0,
        timeout: float = 30.0,
        maxlag: int = 5,
    ):
        # Route through the one guarded factory: the kill switch and the
        # protected-mode proxy now apply to MediaWiki API calls too. ``session``
        # stays injectable for tests (no network).
        if session is None:
            from src.safety.fetcher import guarded_session

            session = guarded_session(user_agent=user_agent)
        else:
            session.headers.update({"User-Agent": user_agent})
        self.session = session
        self.min_interval_s = min_interval_s
        self.timeout = timeout
        self.maxlag = maxlag
        self._last = 0.0
        self._sleep = time.sleep
        self._now = time.monotonic

    def _respect_rate_limit(self) -> None:
        if self._last:
            elapsed = self._now() - self._last
            if elapsed < self.min_interval_s:
                self._sleep(self.min_interval_s - elapsed)

    def _get(self, wiki: str, params: dict) -> dict:
        self._respect_rate_limit()
        try:
            resp = self.session.get(
                mw.api_endpoint(wiki),
                params={**params, "maxlag": self.maxlag},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            self._last = self._now()

    # -- typed helpers ----------------------------------------------------- #

    def fetch_revisions(
        self, wiki: str, title: str, *, limit: int = 20, older_than: int | None = None
    ) -> list[dict]:
        return mw.parse_revisions(
            self._get(wiki, mw.build_revisions_params(title, limit=limit, older_than=older_than))
        )

    def fetch_recentchanges(self, wiki: str, *, namespace: int = 0, limit: int = 50) -> list[dict]:
        return mw.parse_recentchanges(
            self._get(wiki, mw.build_recentchanges_params(namespace=namespace, limit=limit))
        )

    def fetch_revision_texts(self, wiki: str, revids: list[int]) -> dict[int, str]:
        """Full text of specific revisions, one batched call (<=50 revids)."""
        if not revids:
            return {}
        return mw.parse_revision_texts(
            self._get(wiki, mw.build_revision_texts_params(revids))
        )

    def fetch_current_text(self, wiki: str, title: str) -> dict:
        return mw.parse_current_text(self._get(wiki, mw.build_current_text_params(title)))

    def fetch_categories(self, wiki: str, title: str) -> list[str]:
        return mw.parse_categories(self._get(wiki, mw.build_categories_params(title)))

    def fetch_compare(self, wiki: str, from_rev: int, to_rev: int) -> dict:
        return mw.parse_compare(self._get(wiki, mw.build_compare_params(from_rev, to_rev)))
