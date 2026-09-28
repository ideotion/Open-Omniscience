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
        return self._get_measured(wiki, params)[0]

    def _get_measured(self, wiki: str, params: dict) -> tuple[dict, int | None]:
        """``_get``, plus the answer's size in bytes -- the body as it was READ, after any
        transfer decompression: what the JSON weighed, not what crossed the wire. The walk
        records it per transport (S05-06's S3). ``None`` when the response carries no body
        to measure (a test double), which is an absence, never a size of 0."""
        self._respect_rate_limit()
        try:
            resp = self.session.get(
                mw.api_endpoint(wiki),
                params={**params, "maxlag": self.maxlag},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            body = getattr(resp, "content", None)
            size = len(body) if isinstance(body, (bytes, bytearray)) else None
            return resp.json(), size
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

    def fetch_hot_pages(
        self, wiki: str, pageids: list[int], *, with_assessments: bool = False
    ) -> dict[int, dict]:
        """Current text + Q705 metadata for up to 50 pages, ONE request.

        THE UNIT IS PAGES AND THE CAP IS 50 -- see
        ``mediawiki.MAX_PAGES_PER_REQUEST`` for where that was read. This method
        does NOT chunk: a caller handing it 200 ids would silently get 50 back and
        believe it had 200, which is the shape of an undercount nothing reports.
        Chunking belongs to the caller that knows its budget
        (``src.wiki.hot.fetch_hot_batch``), and this refuses rather than truncates.
        """
        if not pageids:
            return {}
        if len(pageids) > mw.MAX_PAGES_PER_REQUEST:
            raise ValueError(
                f"{len(pageids)} pages asked for in one request; the Action API serves "
                f"{mw.MAX_PAGES_PER_REQUEST} to an anonymous client. Chunk before calling."
            )
        return mw.parse_hot_pages(
            self._get(wiki, mw.build_hot_pages_params(pageids, with_assessments=with_assessments))
        )

    def fetch_current_text_by_id(self, wiki: str, pageid: int) -> dict:
        """One page's current wikitext, addressed by ID rather than by title.

        A title can have MOVED between the change arriving and this call; an id
        cannot. Returns the same shape ``fetch_current_text`` does, so the two are
        interchangeable at a call site that has either key.
        """
        pages = self.fetch_hot_pages(wiki, [pageid])
        page = pages.get(pageid)
        if page is None or page.get("missing"):
            return {"missing": True, "pageid": pageid}
        return page

    def fetch_walk_batch(
        self, wiki: str, *, continue_params: dict | None = None, limit: int = mw.MAX_PAGES_PER_REQUEST
    ) -> dict:
        """ONE batch of the ``allpages`` walk: up to 50 article pages and the next bookmark.

        Returns :func:`src.wiki.mediawiki.parse_walk_batch`'s shape plus
        ``response_bytes``. An HTTP refusal RAISES (``requests.HTTPError``, with the
        status on its response), exactly as every other method here does; an API
        refusal carried in a 200 -- ``maxlag`` above all -- comes back as ``error``, so
        the walker names both and advances neither.
        """
        payload, size = self._get_measured(
            wiki, mw.build_walk_params(continue_params, limit=limit)
        )
        return {**mw.parse_walk_batch(payload), "response_bytes": size}

    def fetch_edition_statistics(self, wiki: str) -> dict:
        """The edition's own ``articles`` / ``pages`` counts: the walk's denominator."""
        return mw.parse_statistics(self._get(wiki, mw.build_statistics_params()))

    def fetch_categories(self, wiki: str, title: str) -> list[str]:
        return mw.parse_categories(self._get(wiki, mw.build_categories_params(title)))

    def fetch_compare(self, wiki: str, from_rev: int, to_rev: int) -> dict:
        return mw.parse_compare(self._get(wiki, mw.build_compare_params(from_rev, to_rev)))
