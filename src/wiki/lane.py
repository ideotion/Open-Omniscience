"""The stream-backed lane adapter: a firehose on one side, the substrate on the other.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The substrate PULLS (``read_changes(feed, since, budget) -> ChangeBatch``) and
EventStreams PUSHES. This module is the one place those two shapes meet, and it is a
module rather than a few lines at a call site because the meeting point is where a
stream quietly loses data: a buffer with no ceiling becomes a memory figure, and a
buffer with a ceiling and no accounting becomes a silent hole.

THE BUFFER IS BOUNDED AND ITS OVERFLOW IS PUBLISHED. When the reader falls behind the
firehose, the oldest buffered changes are dropped — there is no other option that
does not end in an OOM — and every drop is COUNTED and turned into a
``GapReport(reason="budget")`` on the next batch. So the lane's own record says "we
stopped looking between here and here" instead of showing an unbroken sequence with a
stretch missing from the middle. That is the same distinction the substrate's gap
machinery exists for; this module simply refuses to be the place it is lost.

Q713 = a ("tracked from the stream's log events; a deleted page keeps its last text
and is marked deleted") is implemented HERE rather than in the substrate, because
``delete`` and ``move`` are MediaWiki's vocabulary. The substrate already carries
both in ``KNOWN_CHANGE_KINDS``; what this module adds is what they MEAN for a wiki
entity, and the meaning is deliberately conservative: a delete sets ``missing`` and
leaves every stored revision alone, and a move rewrites the title while keeping the
page id — which is the whole reason Q715 keys on the id.

NO NETWORK IN THIS FILE. The stream is handed in, the client is handed in. That is
what keeps Q1018's "runs end to end in CI without a socket" true of the pipeline and
not only of the parts nobody wired.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from src.versioned.adapters.base import FetchedVersion, ReadBudget
from src.versioned.feed import ChangeBatch, FeedChange, GapReport
from src.wiki.identity import external_id_for, legacy_external_id_for, parse_external_id
from src.wiki.stream import StreamChange

_LOG = logging.getLogger("wiki.lane")

#: The i18n KEYS this lane owes its reader (Q726 = a). Keys, never sentences: the
#: record of what an operator was shown has to survive a locale change.
WIKI_DISCLOSURE_KEYS: tuple[str, ...] = (
    "Wikipedia text is licensed CC BY-SA 4.0; the reader links to the page history.",
    "This lane records every change it is told about, and fetches the text of some.",
    "A version this lane did not fetch is shown as a gap, never as no change.",
    "Wikimedia's API and stream are public services this app uses under their own etiquette, not under robots.txt.",
)

#: How many changes one edition may buffer before the oldest are dropped AND a gap
#: is published. Sized for the measured order of the firehose rather than guessed:
#: the answer sheet's SEARCH-VERIFIED figure is enwiki at ~80-160 k edits/day, i.e.
#: roughly 1-2 a second, and the other eleven together are of the same order (FROM
#: MEMORY, unconfirmed here). 20,000 is therefore several HOURS of one edition's
#: changes — long enough that a drop means the reader is genuinely broken, short
#: enough that the buffer is tens of megabytes rather than gigabytes.
DEFAULT_BUFFER_MAX: int = 20_000


def feed_name(edition: str) -> str:
    """``stream:<edition>``. Distinct from the adapter's ``recentchanges:<edition>``.

    Two names, because they are two feeds with two cursors and two retention stories.
    A shared name would make a gap in the fallback look like a gap in the stream —
    and Q727 is precisely about moving between them.
    """
    return f"stream:{edition}"


def edition_of(feed: str) -> str:
    """``stream:en`` -> ``en``."""
    prefix, _, code = feed.partition(":")
    if prefix != "stream" or not code:
        raise ValueError(f"not a wiki stream feed name: {feed!r}")
    return code


#: The declared width of ``VersionedCursor.token`` / ``VersionedChange.cursor_token``.
#: Kept here as a NAMED number so the refusal below cannot drift away from the column
#: it protects; ``tests/test_wiki_stream.py`` asserts the two are equal.
CURSOR_TOKEN_MAX: int = 256

#: How many distinct titles one entity's seen-list keeps per batch. See the
#: ``_seen`` comment: a page renamed back and forth would otherwise grow one list
#: without limit, and the earliest names are the ones a corpus mention matches.
SEEN_TITLES_MAX: int = 8


def change_token(change: StreamChange) -> str | None:
    """The cursor position for one change: the stream's OWN event id.

    ``Last-Event-ID`` is the only token EventStreams accepts for a resume, so it is
    the only honest cursor. A token of ours (a timestamp, a revid) would read back as
    a position and be refused by the service, which is the worst combination: it
    looks resumable and is not.

    A token too long for its column returns ``None`` rather than a truncation. A
    truncated resume token is the worst of the three outcomes available here: it
    LOOKS like a position, the service rejects or misreads it, and the lane resumes
    from somewhere it never chose while every counter reads normal. ``None`` means
    "this change carries no position", which the substrate already handles -- the
    cursor simply does not advance on it, and the next event with a usable token
    moves it. The refusal is counted by the caller, never silent.
    """
    token = change.event_id
    if token is None:
        return None
    if len(token) > CURSOR_TOKEN_MAX:
        _LOG.warning(
            "wiki stream: dropping a %d-character resume token (column holds %d); "
            "the cursor will not advance on this event",
            len(token),
            CURSOR_TOKEN_MAX,
        )
        return None
    return token


class StreamBuffer:
    """A bounded, thread-safe queue of changes for ONE edition, with honest overflow."""

    def __init__(self, *, maxlen: int = DEFAULT_BUFFER_MAX) -> None:
        self._items: deque[StreamChange] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        #: Changes dropped because the reader fell behind. Never reset by a read:
        #: it is the count the gap report is built from.
        self.dropped: int = 0
        #: The last token we HELD when a drop happened, and the first token we held
        #: after — the two ends of the hole, in the feed's own vocabulary.
        self.drop_from: str | None = None
        self.drop_to: str | None = None

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def push(self, change: StreamChange) -> None:
        """Append, dropping the oldest when full and RECORDING that it happened."""
        with self._lock:
            if self._items.maxlen is not None and len(self._items) >= self._items.maxlen:
                oldest = self._items[0]
                if self.drop_from is None:
                    self.drop_from = change_token(oldest)
                self.dropped += 1
                # ``deque(maxlen=)`` would drop it for us; doing it explicitly is
                # what makes the count and the token real rather than inferred.
                self._items.popleft()
                self.drop_to = change_token(self._items[0]) if self._items else None
            self._items.append(change)

    def drain(self, limit: int | None = None) -> list[StreamChange]:
        """Remove and return up to ``limit`` changes, oldest first."""
        with self._lock:
            if limit is None or limit >= len(self._items):
                out = list(self._items)
                self._items.clear()
                return out
            out = [self._items.popleft() for _ in range(max(0, limit))]
            return out

    def take_gap(self) -> GapReport | None:
        """The overflow gap, if any, CLEARING it so it is reported exactly once."""
        with self._lock:
            if not self.dropped:
                return None
            report = GapReport(
                reason="budget",
                from_token=self.drop_from,
                to_token=self.drop_to,
            )
            self.dropped = 0
            self.drop_from = None
            self.drop_to = None
            return report


def external_id_of(change: StreamChange) -> str | None:
    """The entity id one streamed change belongs to, or ``None`` when it names none.

    ONE function rather than an expression inlined wherever it is needed: the seen-map
    in :class:`WikiStreamAdapter` and the :class:`FeedChange` it builds must agree
    about which entity a change belongs to, and two copies of this three-branch
    decision are two chances to disagree — which would show up as a HOT page whose
    text never arrives, with nothing anywhere saying why.
    """
    if change.page_id is not None and change.page_id > 0:
        return external_id_for(change.wiki, change.page_id)
    if change.title:
        return legacy_external_id_for(change.wiki, change.title)
    return None


def to_feed_change(change: StreamChange) -> FeedChange:
    """One stream change in the substrate's vocabulary.

    ``external_id`` is the RULED one (Q715) whenever the event carries a page id, and
    the legacy title form ONLY when it does not — some log events omit it. That
    fallback is why :func:`src.wiki.identity.parse_external_id` must read both forms
    rather than the lane declaring a cut-over date it cannot enforce.
    """
    external = external_id_of(change)
    ref = _change_ref(change)
    return FeedChange(
        change_ref=ref,
        change_kind=_change_kind(change),
        external_id=external,
        occurred_at=_when(change),
        cursor_token=change_token(change),
        byte_delta=change.delta_bytes,
    )


class WikiStreamAdapter:
    """The ``VersionedAdapter`` the substrate drives for the stream. ``kind='wiki'``."""

    kind = "wiki"

    def __init__(
        self,
        *,
        client: Any,
        editions: Sequence[str],
        buffers: dict[str, StreamBuffer] | None = None,
        buffer_max: int = DEFAULT_BUFFER_MAX,
        extractor: Any | None = None,
    ) -> None:
        if not editions:
            raise ValueError("a wiki stream adapter needs at least one edition")
        self._client = client
        self._editions = tuple(editions)
        self._extractor = extractor
        self.buffers: dict[str, StreamBuffer] = buffers or {
            code: StreamBuffer(maxlen=buffer_max) for code in self._editions
        }
        #: The newest stream position this adapter has been TOLD about per edition,
        #: including for events it filtered. See ``read_changes`` for why.
        self._positions: dict[str, str] = {}
        self._positions_lock = threading.Lock()
        #: EVERY name the SOURCE used for each entity in the batch this adapter last
        #: drained: ``external_id -> (titles, page_id)``. Kept because the identity
        #: Q715 rules is ``(wiki, pageid)`` while every one of Q707's HOT sources
        #: speaks TITLES, and the stream is the one place both are in hand at once.
        #:
        #: ALL the titles, not the newest, and that is a MEASURED correction rather
        #: than caution. The recorded fixture moves page 101 from "Fixture Alpha" to
        #: "Fixture Alpha (renamed)" mid-batch; a map keeping only the last name
        #: offered the tier the new title alone, so a page the corpus plainly mentions
        #: was not admitted — and nothing anywhere would have said why. A move event
        #: carries only the NEW title (verified against the fixture's own payload), so
        #: the earlier edits in the same batch are the only in-batch record of the old
        #: one. What this still cannot do is match a page whose move happened BEFORE
        #: this run: the corpus then mentions a title the wiki no longer has, and no
        #: local lookup can bridge that. Stated rather than silently half-solved.
        #:
        #: Bounded twice: REPLACED on each ``read_changes`` rather than appended to,
        #: and at :data:`SEEN_TITLES_MAX` distinct names per id, keeping the FIRST
        #: seen — a move war would otherwise let one page's name list grow without
        #: limit, and the oldest names are the ones a corpus mention is likeliest to
        #: match.
        self._seen: dict[str, tuple[tuple[str, ...], int | None]] = {}

    # -- the contract ------------------------------------------------------- #
    def feeds(self) -> tuple[str, ...]:
        return tuple(feed_name(code) for code in self._editions)

    def note_position(self, edition: str, token: str | None) -> None:
        """Record where the stream is for ``edition``, whatever became of the event.

        Called for EVERY event the stream decodes, kept or filtered. Separate from
        :meth:`offer` on purpose: what we STORE and where we ARE are different facts,
        and conflating them is what left the cursor trailing the stream.
        """
        if not token or edition not in self.buffers:
            return
        with self._positions_lock:
            self._positions[edition] = token

    def offer(self, change: StreamChange) -> bool:
        """Hand one streamed change to its edition's buffer. ``False`` when unwatched.

        This is the stream's ``on_change`` callback. It returns rather than raises
        for an edition we do not watch, because the stream carries every wiki there
        is and an exception per foreign event would be the ordinary case.
        """
        buf = self.buffers.get(change.wiki)
        if buf is None:
            return False
        buf.push(change)
        return True

    def read_changes(self, *, feed: str, since: str | None, budget: ReadBudget) -> ChangeBatch:
        """Drain one edition's buffer into a batch.

        ``since`` is NOT used to filter. The stream already resumed from it — the
        service replayed from that id and sent us only what follows — so filtering
        again here would drop changes on a second, independent comparison of a token
        whose ordering this app does not define. That is the recorded defect the
        ``recentchanges`` adapter was corrected for twice; it is not repeated by
        re-deriving it, it is avoided by not comparing at all. The substrate's
        ``change_ref`` dedup is what makes a replayed overlap free.
        """
        code = edition_of(feed)
        buf = self.buffers.get(code)
        if buf is None:
            raise ValueError(f"{feed!r} is not a feed of this adapter")
        drained = buf.drain(budget.max_requests if budget.max_requests else None)
        changes = [to_feed_change(c) for c in drained]
        self._seen = {}
        for c in drained:
            eid = external_id_of(c)
            if not eid:
                continue
            titles, page_id = self._seen.get(eid, ((), None))
            if c.title and c.title not in titles and len(titles) < SEEN_TITLES_MAX:
                titles = titles + (c.title,)
            self._seen[eid] = (titles, page_id if page_id is not None else c.page_id)
        last_token = None
        for change in reversed(changes):
            if change.cursor_token:
                last_token = change.cursor_token
                break
        # THE CURSOR MUST ADVANCE PAST WHAT WE DELIBERATELY FILTERED, and this line
        # is the reason the adapter is told the stream's position at all. MEASURED on
        # the fixture: the last six events were a foreign edition, a category, a
        # redirect, a malformed body and an event of another type, so the newest KEPT
        # change sat six events behind the stream's own head. Storing that as the
        # cursor is safe for a moment and wrong over days -- an edition that is quiet
        # while the others are busy would hold a cursor further and further back,
        # until it fell outside EventStreams' retention and the lane reported a GAP
        # over a stretch in which nothing was missed. A fabricated gap is exactly as
        # dishonest as a fabricated measurement.
        #
        # Only used when the drain produced no positioned change of its own, and only
        # for a position the stream has actually PASSED, so it can never jump ahead of
        # what was read. ``since`` remains the floor: the cursor never goes backwards
        # to ``None``, which the substrate reads as a cold start.
        if last_token is None and self._positions.get(code):
            last_token = self._positions[code]
        return ChangeBatch(
            feed=feed,
            changes=tuple(changes),
            next_token=last_token or since,
            resumed_from=since,
            gap=buf.take_gap(),
        )

    def seen(self, external_id: str) -> tuple[tuple[str, ...], int | None]:
        """Every name the source used for ``external_id`` in the batch just drained.

        ``((), None)`` for an id this adapter has not just seen — an absence, not an
        error, and callers treat it as "decide without a title" rather than inventing
        one. The titles are in FIRST-SEEN order, so ``[0]`` is the oldest name in this
        batch and ``[-1]`` the newest.
        """
        return self._seen.get(external_id, ((), None))

    def fetch_version(self, external_id: str) -> FetchedVersion | None:
        """The current wikitext of one page, or ``None`` when the wiki says it is gone."""
        ident = parse_external_id(external_id)
        if ident.page_id is not None:
            data = self._client.fetch_current_text_by_id(ident.wiki, ident.page_id)
        else:
            data = self._client.fetch_current_text(ident.wiki, ident.title)
        if not data or data.get("missing"):
            # The wiki ANSWERED and said there is no such page. A failure raises out
            # of the client; the two must not share this return value.
            return None
        return FetchedVersion(
            external_id=external_id,
            revision_ref=str(data.get("revid")),
            text=data.get("text") or "",
            revised_at=_aware(data.get("timestamp")),
            title=data.get("title") or ident.title,
            language=ident.wiki,
        )

    def to_article(self, session, version: FetchedVersion) -> int | None:
        """Into the corpus through the EXISTING wiki upsert. Never a second path."""
        from src.wiki.corpus import plain_from_wikitext, upsert_wiki_corpus_article

        ident = parse_external_id(version.external_id)
        title = version.title or ident.title
        if not title:
            # Without a title there is no canonical URL and no reader link. Refusing
            # beats storing an Article that every surface would show as untitled.
            return None
        plain = plain_from_wikitext(version.text)
        if not plain.strip():
            # A page whose wikitext reduces to nothing produces no Article. Saying so
            # beats storing an empty one, which every corpus figure would count.
            return None
        out = upsert_wiki_corpus_article(
            session,
            wiki=ident.wiki,
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
# Helpers.
# --------------------------------------------------------------------------- #
def _change_ref(change: StreamChange) -> str:
    """A ref unique per change, for the substrate's dedup.

    Prefers the revid because it is the change's own identity on the wiki. A LOG
    event has no revid, so it falls back to the stream's event id, and last to a
    composite — each step named so a reader can see which one produced a given row
    rather than guessing from its shape.
    """
    # ``> 0``, not ``is not None``. MEASURED, not anticipated: the first fixture run
    # gave a delete and a move the SAME ref (``oo:r0``), because both carried a revid
    # of 0 and 0 is not None. The substrate dedups on ``(feed, change_ref)``, so the
    # second event was silently discarded as a duplicate of the first -- two distinct
    # log events becoming one, with nothing anywhere reporting a loss. A revision id
    # of 0 is not a revision id.
    if change.revid is not None and change.revid > 0:
        return f"{change.wiki}:r{change.revid}"
    if change.event_id:
        # DIGESTED, not embedded. EventStreams' Last-Event-ID is a JSON array with one
        # object per Kafka partition, so it is ~80 characters for one partition and
        # grows with the topic's partitioning -- while ``VersionedChange.change_ref``
        # is ``String(128)``. SQLite would not complain; it would simply store an
        # over-long value, and the day this lane runs on a backend that enforces the
        # declared width, or the day the service adds a partition, the failure would
        # arrive in the field. A 16-hex digest is bounded, stable, and collides at a
        # rate far below the number of events any corpus will ever hold.
        digest = hashlib.blake2b(change.event_id.encode("utf-8"), digest_size=8).hexdigest()
        return f"{change.wiki}:e{digest}"
    return f"{change.wiki}:{change.change_kind}:{change.title}:{change.timestamp_ms or 0}"


def _change_kind(change: StreamChange) -> str:
    """MediaWiki's vocabulary onto the substrate's. Unknown values pass VERBATIM.

    Q713's log events are the point: ``log`` with ``log_type='delete'`` is a
    deletion, with ``'move'`` a move. Anything else keeps the name the service gave
    it, because mapping a value we do not understand onto the nearest one we do
    invents a fact about someone else's data.
    """
    kind = (change.change_kind or "").strip()
    if kind in ("", "edit"):
        return "edit"
    if kind == "new":
        return "create"
    if kind == "log":
        log_type = (change.log_type or "").strip()
        if log_type in ("delete", "move"):
            return log_type
        return log_type or "log"
    return kind


def _when(change: StreamChange) -> datetime | None:
    if change.timestamp_ms is None:
        return None
    return datetime.fromtimestamp(change.timestamp_ms / 1000.0, tz=UTC)


def _aware(value: Any) -> datetime | None:
    """A tz-aware datetime, or ``None``. MediaWiki documents its timestamps as UTC."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _default_extractor():
    """The baseline extractor, resolved lazily so mere construction stays cheap."""
    from src.analytics.extract import get_extractor

    return get_extractor()
