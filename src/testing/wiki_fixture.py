"""An offline MediaWiki client over the synthetic fixture edition. Zero sockets.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1018 = a: the lane's pipeline must run end to end in CI *without a socket*. This is
the client that makes that true. It answers the same methods
``src.wiki.client.WikiClient`` answers, from ``tests/fixtures/wiki/oowiki.json``,
and it opens nothing.

IT IS PINNED TO THE REAL CLIENT, NOT WRITTEN BESIDE IT. The recorded lesson is that
a hand-written double drifts — one omitted a field for months, one invented a method
that did not exist — and that the remedy is ``inspect.signature``:
``tests/test_versioned_wiki_adapter.py`` asserts every method this class offers has
the SAME parameter names and kinds as ``WikiClient``'s. Without that, a green suite
would prove only that the fixture agrees with itself.

IT LIVES IN ``src/`` DELIBERATELY. ``src/testing/`` already holds ``corpus_gen`` and
``scale_bench`` for the same reason: a fixture driver that several test files and the
click-through harness all need is not a test, and copying it into each of them is how
fifteen hand-rolled copies of one path came to exist once before.

THE RETENTION WINDOW IS THE POINT OF ``max_recentchanges``. A real
``list=recentchanges`` is a bounded window over a log that forgets; a fixture that
always returned everything could never produce the ``retention`` gap the substrate
exists to publish. Setting it small is how a test makes a REAL gap happen rather
than fabricating one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Where the generated fixture lives. One constant, so a test and the harness cannot
#: disagree about which file they are driving.
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "wiki" / "oowiki.json"


class FixtureNetworkAttempt(RuntimeError):
    """Raised if anything asks this client for an edition it does not hold.

    A LOUD refusal rather than an empty answer: an empty list reads as "that wiki had
    no changes", which is exactly the fabricated-quiet result a test would believe.
    """


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


class FixtureWikiClient:
    """A ``WikiClient``-shaped reader over the synthetic edition.

    ``max_recentchanges`` is the retention window (see the module docstring).
    ``calls`` counts every method invocation by name, so a test can assert a budget
    was honoured by counting REQUESTS rather than by trusting a returned number —
    the recorded rule that a harness measuring an effect must independently assert
    the work happened.
    """

    def __init__(
        self,
        *,
        path: Path | None = None,
        max_recentchanges: int = 50,
        as_of: datetime | None = None,
    ) -> None:
        self._path = path or FIXTURE_PATH
        self._data: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
        self._edition: str = self._data["edition"]
        self._max_rc = max_recentchanges
        #: Everything at or after this instant is treated as not yet having happened.
        #: Lets one fixture serve several "days" without a second file.
        self._as_of = as_of
        self.calls: dict[str, int] = {}

    # -- bookkeeping -------------------------------------------------------- #
    def _note(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def _check(self, wiki: str) -> None:
        if wiki != self._edition:
            raise FixtureNetworkAttempt(
                f"the fixture holds only the {self._edition!r} edition; "
                f"something asked for {wiki!r}, which in production would be a fetch"
            )

    def _visible(self, rev: dict) -> bool:
        if self._as_of is None:
            return True
        ts = _parse_ts(rev.get("timestamp"))
        return ts is None or ts < self._as_of

    def _pages(self) -> dict[str, dict]:
        return self._data["pages"]

    def _deleted(self, page: dict) -> bool:
        when = _parse_ts(page.get("deleted_at"))
        if when is None:
            return False
        return self._as_of is None or when < self._as_of

    # -- the WikiClient surface --------------------------------------------- #
    def fetch_recentchanges(self, wiki: str, *, namespace: int = 0, limit: int = 50) -> list[dict]:
        """Newest-first, bounded by BOTH ``limit`` and the fixture's retention window."""
        self._note("fetch_recentchanges")
        self._check(wiki)
        rows: list[dict] = []
        for title, page in self._pages().items():
            prev_size: int | None = None
            for rev in page["revisions"]:
                if not self._visible(rev):
                    continue
                size = len(rev["text"].encode("utf-8"))
                rows.append(
                    {
                        "revid": rev["revid"],
                        "parent_revid": None,
                        "title": title,
                        "timestamp": _parse_ts(rev["timestamp"]),
                        "editor": rev["user"],
                        "editor_anon": False,
                        "bot": False,
                        "minor": False,
                        "comment": rev["comment"],
                        "size": size,
                        "delta_bytes": None if prev_size is None else size - prev_size,
                        "tags": [],
                        "type": rev.get("type", "edit"),
                    }
                )
                prev_size = size
            if self._deleted(page):
                rows.append(
                    {
                        "revid": page["delete_logid"],
                        "parent_revid": None,
                        "title": title,
                        "timestamp": _parse_ts(page["deleted_at"]),
                        "editor": "FixtureAdmin",
                        "editor_anon": False,
                        "bot": False,
                        "minor": False,
                        "comment": "deleted",
                        "size": None,
                        "delta_bytes": None,
                        "tags": [],
                        "type": "log",
                        "logtype": "delete",
                    }
                )
        rows.sort(key=lambda r: r["timestamp"] or datetime.min.replace(tzinfo=UTC), reverse=True)
        return rows[: min(limit, self._max_rc)]

    def fetch_current_text(self, wiki: str, title: str) -> dict:
        """The newest visible revision, or ``{"missing": True}`` for a deleted page."""
        self._note("fetch_current_text")
        self._check(wiki)
        page = self._pages().get(title)
        if page is None or self._deleted(page):
            return {"missing": True, "title": title}
        visible = [r for r in page["revisions"] if self._visible(r)]
        if not visible:
            return {}
        rev = visible[-1]
        return {
            "revid": rev["revid"],
            "text": rev["text"],
            "size": len(rev["text"].encode("utf-8")),
            "pageid": page["pageid"],
            "title": title,
            "timestamp": _parse_ts(rev["timestamp"]),
        }

    def fetch_revisions(
        self, wiki: str, title: str, *, limit: int = 20, older_than: int | None = None
    ) -> list[dict]:
        """This page's revisions, newest first."""
        self._note("fetch_revisions")
        self._check(wiki)
        page = self._pages().get(title)
        if page is None:
            return []
        out = []
        for rev in reversed(page["revisions"]):
            if not self._visible(rev):
                continue
            if older_than is not None and rev["revid"] >= older_than:
                continue
            out.append(
                {
                    "revid": rev["revid"],
                    "parent_revid": None,
                    "timestamp": _parse_ts(rev["timestamp"]),
                    "editor": rev["user"],
                    "editor_anon": False,
                    "bot": False,
                    "minor": False,
                    "comment": rev["comment"],
                    "size": len(rev["text"].encode("utf-8")),
                    "tags": [],
                }
            )
        return out[:limit]

    def fetch_revision_texts(self, wiki: str, revids: list[int]) -> dict[int, str]:
        """Texts for the given revids. Batched exactly as the real client batches."""
        self._note("fetch_revision_texts")
        self._check(wiki)
        wanted = set(revids)
        out: dict[int, str] = {}
        for page in self._pages().values():
            for rev in page["revisions"]:
                if rev["revid"] in wanted and self._visible(rev):
                    out[rev["revid"]] = rev["text"]
        return out

    def fetch_categories(self, wiki: str, title: str) -> list[str]:
        """The fixture declares no categories; an empty list is the honest answer."""
        self._note("fetch_categories")
        self._check(wiki)
        return []

    def fetch_compare(self, wiki: str, from_rev: int, to_rev: int) -> dict:
        """Not served by the fixture, and it says so rather than returning ``{}``.

        The substrate computes its own diffs from the two texts it holds, so nothing
        in the versioned lane calls this. A caller that does is asking the fixture
        for something it cannot honestly answer, and an empty dict would read as
        "the two revisions are identical".
        """
        self._note("fetch_compare")
        self._check(wiki)
        raise FixtureNetworkAttempt(
            "the fixture serves no server-side diffs; the lane computes its own"
        )
