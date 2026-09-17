"""The wiki adapter — the substrate's first, over the existing MediaWiki client.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1003 = a: "``src/versioned/`` shared by the wiki, law and OSM lanes, **the wiki
adapter first**". This is that adapter. It owns MediaWiki's vocabulary — what a
change looks like on ``list=recentchanges``, how a page's current wikitext is
fetched, how wikitext becomes the plain text the corpus indexes — and nothing else.

IT IS HANDED ITS CLIENT. ``WikiLaneAdapter(client=...)`` takes anything with the
three methods it calls. Production passes ``src.wiki.client.WikiClient``, which goes
through ``guarded_session`` and therefore through the kill switch, the SSRF guard
and the airplane socket guard. CI passes a fixture client that reads files. The code
between them is the same code, which is what makes Q1018's "end-to-end in CI without
a socket" a property rather than a claim — and it is why this module builds no
client of its own, not even as a default.

IDENTITY IN 0.4 IS ``{wiki}:{title}``, AND THE SEAM IS NAMED. Q715 rules the wiki
lane's identity to be ``WikiPage(wiki, pageid)`` + QID — and Q715 belongs to S04-09,
not here. This adapter uses the title because the CHANGE FEED can produce it:
``list=recentchanges`` reports ``title`` and no ``pageid`` (verified against
``src.wiki.mediawiki.parse_recentchanges``), so a pageid-keyed identity could not be
built from a change without a second request per change. The substrate treats
``external_id`` as opaque exactly so this can move later without a schema migration.
THE KNOWN COST, stated rather than discovered: a page MOVE changes the title, so a
moved page would look like a new entity. MediaWiki reports moves as their own log
event, which is why ``move`` is in the substrate's change vocabulary — following it
is S04-09's to build, and until then a move is RECORDED and visible rather than
silently re-keyed.

WIKITEXT BECOMES PLAIN TEXT THROUGH THE EXISTING REDUCER, AND THAT IS A LOSS. The
corpus stores what ``plain_from_wikitext`` produces, whose own docstring targets
"keyword/WWW-quality text, not rendering fidelity": it PEELS templates and DROPS
tables, so an infobox figure is gone rather than laid out differently. The lane
keeps the WIKITEXT — ``VersionedRevision.content`` is what the source served — so
the reduction is a property of the corpus copy, not of the record.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.versioned.adapters.base import FetchedVersion, ReadBudget
from src.versioned.feed import ChangeBatch, FeedChange, GapReport

_LOG = logging.getLogger("versioned.adapters.wiki")

#: The i18n KEYS this lane owes its reader. Keys, never sentences — see
#: ``VersionedDisclosure``'s docstring for why the record stores a key.
WIKI_DISCLOSURE_KEYS: tuple[str, ...] = (
    "Wikipedia text is licensed CC BY-SA 4.0; the reader links to the page history.",
    "This lane records every change it is told about, and fetches the text of some.",
    "A version this lane did not fetch is shown as a gap, never as no change.",
)


def external_id_for(wiki: str, title: str) -> str:
    """``{wiki}:{title}``. The one place the format is written.

    A second spelling of an identity is how two rows come to mean one page, so
    every construction and every parse in this module goes through this pair.
    """
    return f"{wiki}:{title}"


def split_external_id(external_id: str) -> tuple[str, str]:
    """Inverse of :func:`external_id_for`. Splits on the FIRST colon only.

    Titles legitimately contain colons (``Category:Physics``, ``Talk:X``), so a
    naive ``split(":")`` would truncate a namespaced title and address the wrong
    page — silently, because the truncated title is itself a plausible one.
    """
    wiki, _, title = external_id.partition(":")
    if not wiki or not title:
        raise ValueError(f"not a wiki lane external id: {external_id!r}")
    return (wiki, title)


class WikiLaneAdapter:
    """One wiki edition's adapter. ``kind`` is ``"wiki"``.

    ``editions`` is the set of edition codes this adapter reads, and it is REQUIRED:
    defaulting to "all twelve" would make a first run's blast radius a property of a
    constant rather than of the operator's choice.
    """

    kind = "wiki"

    def __init__(
        self,
        *,
        client: Any,
        editions: tuple[str, ...],
        extractor: Any | None = None,
    ) -> None:
        if not editions:
            raise ValueError("a wiki lane adapter needs at least one edition")
        self._client = client
        self._editions = tuple(editions)
        self._extractor = extractor

    # -- the contract ------------------------------------------------------- #

    def feeds(self) -> tuple[str, ...]:
        """One feed per edition. Named ``recentchanges:<edition>``.

        Per-edition rather than one feed for all of them because a CURSOR is
        per-edition: MediaWiki's continuation token belongs to one wiki, and a
        shared cursor would make a gap in one edition look like a gap in every
        other.
        """
        return tuple(f"recentchanges:{code}" for code in self._editions)

    def read_changes(self, *, feed: str, since: str | None, budget: ReadBudget) -> ChangeBatch:
        """One read of one edition's recent changes.

        ``since`` is a ``"<iso8601>|<revid>"`` token naming the newest change this
        lane has recorded for this edition. MediaWiki's ``list=recentchanges`` is a
        newest-first window over a RETENTION-BOUNDED log, so the honest resume is:
        ask for a window, keep everything newer than ``since``, and if the OLDEST
        change in the window is STILL newer than ``since``, the window did not reach
        back to where we were — a gap with reason ``retention``, reported rather
        than inferred away.

        **THE TOKEN IS A TIMESTAMP, AND THAT IS A CORRECTION.** The first version of
        this adapter resumed on ``revid`` alone, on the assumption that a wiki's
        revision ids rise with time. That assumption may well hold for a real
        MediaWiki — its revision counter is per-wiki — but this session cannot
        verify it (the Wikimedia hosts are egress-blocked here), and the round-trip
        against the fixture proved what an unverified ordering assumption costs:
        three of five pages silently stopped receiving changes, with every counter
        reading zero and nothing anywhere reporting a fault. A change log is defined
        by its CHRONOLOGY — that is what makes it a log — so the cursor is the
        chronology, with the revid as a tie-break for same-instant changes. It also
        mirrors the shape of MediaWiki's own ``rccontinue`` (``timestamp|id``), which
        is the strongest available evidence about what the API is ordered on.

        A change with NO timestamp is KEPT rather than compared: it cannot be placed
        against the cursor, and the safe direction is to record it again (dedup on
        ``change_ref`` makes that free) rather than to drop it once, permanently.
        """
        code = _edition_of(feed)
        if code not in self._editions:
            raise ValueError(f"{feed!r} is not a feed of this adapter")

        limit = 50 if budget.max_requests is None else max(1, min(500, 50))
        rows = self._client.fetch_recentchanges(code, namespace=0, limit=limit)

        mark = parse_token(since)
        changes: list[FeedChange] = []
        oldest: tuple[datetime, int] | None = None
        newest: tuple[datetime, int] | None = None
        for row in rows:
            revid = _as_int(row.get("revid"))
            if revid is None:
                # A change with no id cannot be deduped, so recording it would
                # double-count on every later read. Skipped deliberately, and the
                # skip is visible as a shorter batch than the window served.
                continue
            when = _aware(row.get("timestamp"))
            here = (when, revid) if when is not None else None
            if here is not None:
                oldest = here if oldest is None else min(oldest, here)
                newest = here if newest is None else max(newest, here)
                if mark is not None and here <= mark:
                    continue
            title = row.get("title") or ""
            changes.append(
                FeedChange(
                    change_ref=f"{code}:{revid}",
                    change_kind=_change_kind(row),
                    external_id=external_id_for(code, title) if title else None,
                    occurred_at=when,
                    cursor_token=make_token(when, revid),
                    byte_delta=row.get("delta_bytes"),
                )
            )

        gap: GapReport | None = None
        if mark is not None and oldest is not None and oldest > mark:
            # Every change in the window is newer than where we left off, so the
            # window did not reach our position: whatever sat between is outside
            # this feed's retention as far as this read can tell.
            gap = GapReport(
                reason="retention",
                from_token=since,
                to_token=make_token(*oldest),
                from_time=mark[0],
                to_time=oldest[0],
            )

        return ChangeBatch(
            feed=feed,
            changes=tuple(changes),
            next_token=make_token(*newest) if newest is not None else since,
            resumed_from=since,
            gap=gap,
        )

    def fetch_version(self, external_id: str) -> FetchedVersion | None:
        """The current wikitext of one page, or ``None`` when the wiki says it is gone."""
        code, title = split_external_id(external_id)
        data = self._client.fetch_current_text(code, title)
        if not data or data.get("missing"):
            # The wiki answered and said there is no such page. A FAILURE would have
            # raised out of the client — the two must not share this return value.
            return None
        text = data.get("text") or ""
        return FetchedVersion(
            external_id=external_id,
            revision_ref=str(data.get("revid")),
            text=text,
            revised_at=_aware(data.get("timestamp")),
            title=data.get("title") or title,
            language=code,
        )

    def to_article(self, session: Session, version: FetchedVersion) -> int | None:
        """Put this version into the corpus through the EXISTING wiki upsert.

        Reused rather than reimplemented, because that function already owns the
        canonical URL, the content-hash idempotence, the source row and the ONE
        ``index_article`` call. A second path into the corpus for wiki text is how
        two surfaces come to disagree about what a wiki article is.
        """
        from src.wiki.corpus import plain_from_wikitext, upsert_wiki_corpus_article

        code, title = split_external_id(version.external_id)
        plain = plain_from_wikitext(version.text)
        if not plain.strip():
            # A page whose wikitext reduces to nothing (a redirect, a stub of
            # templates) produces no Article. Saying so beats storing an empty one,
            # which would be counted by every corpus figure as a real document.
            return None
        out = upsert_wiki_corpus_article(
            session,
            wiki=code,
            title=title,
            plain=plain,
            published_at=version.revised_at,
            revid=_as_int(version.revision_ref),
            extractor=self._extractor or _default_extractor(),
        )
        return out.get("article_id")

    def disclosure_keys(self) -> tuple[str, ...]:
        return WIKI_DISCLOSURE_KEYS


# --------------------------------------------------------------------------- #
# Helpers — small, pure, and individually testable.
# --------------------------------------------------------------------------- #
def make_token(when: datetime | None, revid: int) -> str:
    """``"<iso8601>|<revid>"``. The ONE place the cursor format is written.

    Mirrors MediaWiki's own ``rccontinue`` shape (``timestamp|id``). A ``None``
    timestamp yields a token with an empty time half, which :func:`parse_token`
    then refuses — so an unplaceable change can never become a cursor position.
    """
    stamp = when.astimezone(UTC).isoformat() if when is not None else ""
    return f"{stamp}|{revid}"


def parse_token(token: str | None) -> tuple[datetime, int] | None:
    """Inverse of :func:`make_token`. ``None`` for anything that cannot be compared.

    Returns ``None`` — never raises and never guesses — for a missing token, a
    malformed one, or one whose time half is empty. A cursor this function cannot
    read is treated exactly like no cursor at all, which re-reads a stretch already
    covered (free, thanks to dedup) instead of skipping one (permanent).
    """
    if not token:
        return None
    stamp, _, rev = token.partition("|")
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    revid = _as_int(rev)
    return (when.astimezone(UTC), revid if revid is not None else 0)


def _edition_of(feed: str) -> str:
    """``recentchanges:en`` -> ``en``."""
    prefix, _, code = feed.partition(":")
    if prefix != "recentchanges" or not code:
        raise ValueError(f"not a wiki lane feed name: {feed!r}")
    return code


def _as_int(value: Any) -> int | None:
    """Best-effort int, ``None`` on anything else. Never raises on foreign input."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _aware(value: Any) -> datetime | None:
    """A tz-aware datetime, or ``None``.

    The lane's timestamp type REFUSES a naive value on write, so this is where a
    source's naive timestamp is given the zone MediaWiki documents its own
    timestamps in (UTC). That assumption is made HERE, once, in the adapter that
    knows whose timestamps these are — never inside the storage layer, which has no
    way to know.
    """
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _change_kind(row: dict) -> str:
    """Map one recentchanges row onto the substrate's change vocabulary.

    Anything unrecognised is returned VERBATIM: the substrate counts it as an
    unknown kind and stores it, because mapping a value we do not understand onto
    the nearest one we do invents a fact about someone else's data.
    """
    kind = row.get("type")
    if kind in (None, "edit"):
        return "edit"
    if kind == "new":
        return "create"
    if kind == "log":
        action = (row.get("logtype") or "").strip()
        if action in ("delete", "move"):
            return action
        return action or "log"
    return str(kind)


def _default_extractor():
    """The baseline extractor, resolved lazily.

    Lazy because ``src.analytics.extract`` pulls in the stopword machinery, and an
    adapter that is merely CONSTRUCTED (by a registry walk, by a test listing the
    lanes) must not pay for it.
    """
    from src.analytics.extract import get_extractor

    return get_extractor()
