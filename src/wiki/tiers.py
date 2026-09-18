"""Q707's three tiers, and the budget the lane runs under.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q707 = a, verbatim: "Three tiers under a per-edition daily budget the first-run
wizard sets (default proposed: 20 GB total, published): HOT = pages the corpus
already mentions, tracked pages, and the pageview top-1,000 (full text +
``index_article`` on every change); WARM = every other changed page (full text,
indexed lazily under the daily budget); COLD = the tail reached by the walk
(metadata now; text as budget allows)."

WHAT IS BUILT HERE AND WHAT IS ONLY DECLARED. The brief's S4 says "Q707's tiers
with WARM / COLD **DECLARED only** (ingest is 0.5)". So :func:`classify` answers for
all three and HOT is the only one this release fetches text for. The refusal is
NAMED — :data:`DEFERRED_UNTIL_WARM_TIER` — and it is deliberately a DIFFERENT reason
from "the budget ran out", which ``pipeline.py``'s module docstring already keeps
apart from a feed gap. Three states, three names: *we were never told* (a gap), *we
were told and could not afford the text* (budget), *we were told and this release
does not ingest that tier* (here). Merging the last two would make a lane that is
working exactly as ruled look like one that is starved, and would hide a real budget
stop among a hundred thousand deliberate ones.

WHY "DAILY" IS NOT A SECOND RATE AUTHORITY. Q707 says "per-edition daily budget",
and a naive reading builds a bytes-per-day allowance for the lane. Q1012 (ruled
2026-09-15) forbids exactly that: "the bandwidth budget is PER PROCESS, composed
with the collection-speed governor (``#rate-toggle``, invariant #4) — one rate
authority, never a second beside it". A per-edition daily bandwidth allowance IS a
second rate authority beside the governor, and invariant #20's own note records how
two surfaces come to disagree about one quantity. So the budget this module enforces
is a STORAGE cap — how many bytes the lane may come to hold — and the RATE at which
it is spent stays the governor's, unchanged. The wizard says so in the operator's own
words (×12) rather than leaving them to infer it.

THE TWO BYTE FIGURES ARE NEVER MERGED. ``store.lane_file_bytes`` is the lane FILE on
disk, sidecars included: the figure the operator's disk actually holds, and the only
honest answer to "how big is this". It cannot be split per edition — one file holds
twelve. The per-edition figure is a sum of ``byte_size`` over stored text, which
``models.py`` already marks as the UNCOMPRESSED length and explicitly NOT the disk
figure. Both are measured; neither is derived from the other; each carries its own
method string, because a compressed lane's disk bytes are a fraction of its text
bytes and presenting either as the other would misstate the operator's remaining room
by a multiple.

NOTHING HERE TOUCHES THE NETWORK OR OPENS A DATABASE. It takes measured sets and
measured numbers and answers questions about them, so the whole tier decision runs in
a test with the airplane socket guard armed and no lane file in existence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

#: The three tiers, in Q707's own order. A CLOSED vocabulary: an unknown tier is
#: refused at :func:`require_tier` rather than falling through to a default, for the
#: reason ``lanes.py`` gives for its kinds — a silent fall-through on a question about
#: what text to keep is the worst available failure.
Tier = Literal["hot", "warm", "cold"]
TIERS: Final[tuple[str, ...]] = ("hot", "warm", "cold")

#: Why a page is HOT. Q707 names three; Q716 = a ("pin this page to HOT") adds the
#: fourth, which is the operator's explicit choice and therefore listed FIRST — when
#: two reasons apply, the one the operator made themselves is the one worth showing.
#:
#: These are TOKENS, not sentences (``lanes.py``'s rule for its transport field): the
#: words an operator reads are composed by the UI through ``OOI18N.t`` and ship ×12.
HotReason = Literal["pinned", "tracked", "corpus_mention", "pageview_top"]
HOT_REASONS: Final[tuple[str, ...]] = ("pinned", "tracked", "corpus_mention", "pageview_top")

#: The named reason a WARM or COLD change keeps its metadata and not its text in 0.4.
#: NOT "budget" — see the module docstring.
DEFERRED_UNTIL_WARM_TIER: Final[str] = "warm_and_cold_text_is_not_ingested_in_0_4"

#: Q707's published default, verbatim from the ruling: "20 GB total, published".
#: TOTAL for the lane, not per edition — the per-edition share is derived below and
#: the arithmetic is SHOWN rather than folded in.
#:
#: WHERE THIS NUMBER WILL EVENTUALLY LIVE: S04-08's slice 4 is "a published table (a
#: versioned file under ``configs/``) of per-lane budgets sized for the reference VM",
#: and its brief's §6 says "Q707's 20 GB is S04-09's" — the number is this slice's,
#: the table is that one's, and that table does not exist yet (gate row O lists it
#: among S04-08's remaining items). It is declared HERE with its provenance so that
#: moving it later is a move, not a rediscovery.
DEFAULT_TOTAL_BUDGET_GB: Final[int] = 20

#: The bounds the wizard offers. The floor is not zero: a lane with a zero budget
#: stores no text at all, which is a lane the operator should TURN OFF rather than
#: starve — the toggle exists for that and says what it does. The ceiling is not a
#: judgement about disks, it is the largest number the wizard will accept without the
#: operator editing the settings file, so a slipped keystroke cannot commit a machine
#: to a terabyte.
BUDGET_GB_MIN: Final[int] = 1
BUDGET_GB_MAX: Final[int] = 2000

_BYTES_PER_GB: Final[int] = 1024**3


class UnknownTierError(ValueError):
    """Raised for a tier name this module does not know. Its own type so an API
    handler can turn it into a 400 without catching every ``ValueError`` a request
    body might raise."""


def require_tier(value: str) -> Tier:
    """Return ``value`` as a :data:`Tier`, or refuse by name."""
    if value in TIERS:
        return value  # type: ignore[return-value]
    raise UnknownTierError(f"unknown tier {value!r}; known tiers are {', '.join(TIERS)}")


def normalize_title(title: str) -> str:
    """The comparison form for a MediaWiki page title.

    Underscores are spaces, runs of whitespace collapse, the ends are stripped, and
    the first character is upper-cased. That last step is a PROPERTY OF THESE TWELVE
    EDITIONS, not of MediaWiki: ``$wgCapitalLinks`` is per-wiki and some wikis (wikt,
    for one) leave the first letter alone. All twelve Wikipedia editions this lane
    follows capitalise it, so the form is right here and would be wrong if this
    function were reused for a wiki outside the twelve. Said out loud because a
    normaliser that is silently wrong for one source produces misses that look like
    absent data.

    Returns ``""`` for a title that is only whitespace, which callers treat as no
    title rather than as an empty page name.
    """
    collapsed = " ".join(title.replace("_", " ").split())
    if not collapsed:
        return ""
    return collapsed[0].upper() + collapsed[1:]


@dataclass(frozen=True, slots=True)
class TierDecision:
    """One page's tier, with the reason it got there and what follows from it."""

    tier: Tier
    #: Which of :data:`HOT_REASONS` put it in HOT; ``None`` for WARM and COLD, where
    #: there is nothing to name — a page is WARM by not being HOT, and saying
    #: "reason: not_hot" would dress an absence up as a finding.
    reason: HotReason | None
    #: Whether THIS RELEASE fetches the page's text. True for HOT only.
    ingests_text: bool
    #: The named reason text was not fetched, when it was not. ``None`` when it was.
    deferred_reason: str | None

    def as_dict(self) -> dict:
        return {
            "tier": self.tier,
            "reason": self.reason,
            "ingests_text": self.ingests_text,
            "deferred_reason": self.deferred_reason,
        }


_WARM = TierDecision(
    tier="warm",
    reason=None,
    ingests_text=False,
    deferred_reason=DEFERRED_UNTIL_WARM_TIER,
)
_COLD = TierDecision(
    tier="cold",
    reason=None,
    ingests_text=False,
    deferred_reason=DEFERRED_UNTIL_WARM_TIER,
)


def warm() -> TierDecision:
    """Q707's WARM: a changed page that is not HOT. Text is 0.5's (S05-06)."""
    return _WARM


def cold() -> TierDecision:
    """Q707's COLD: the tail the walk reaches. The walk itself is 0.5's."""
    return _COLD


class HotSet:
    """HOT membership for ONE edition, built once per pass from measured sources.

    WHY IT TAKES BOTH KEYS. Q715 keys a page ``(wiki, pageid)``, and it is right to:
    a MOVE changes the title and the identity must survive it. But every one of
    Q707's three HOT sources speaks TITLES — the corpus mentions a page by name, the
    operator tracked a name, and the pageviews endpoint answers with names. So
    membership is checked on the page id FIRST, where one is known, and falls back to
    the normalised title. The page-id path is what keeps a page HOT across a move;
    without it a renamed page would quietly drop to WARM on the very edit that
    renamed it, and no surface would say why.

    Every set handed in is MEASURED by its caller. This class computes no membership
    of its own and has no "probably hot" branch.
    """

    __slots__ = ("edition", "_pinned_ids", "_tracked", "_mentions", "_pageview_top", "_ids")

    def __init__(
        self,
        edition: str,
        *,
        pinned_ids: set[int] | None = None,
        tracked_titles: set[str] | None = None,
        corpus_mention_titles: set[str] | None = None,
        pageview_top_titles: set[str] | None = None,
        hot_page_ids: set[int] | None = None,
    ) -> None:
        self.edition = edition
        self._pinned_ids = set(pinned_ids or ())
        self._tracked = {normalize_title(t) for t in (tracked_titles or ()) if t}
        self._mentions = {normalize_title(t) for t in (corpus_mention_titles or ()) if t}
        self._pageview_top = {normalize_title(t) for t in (pageview_top_titles or ()) if t}
        #: Page ids already known to be HOT for a reason other than pinning — the
        #: move-survival path. The caller fills it from what it has resolved; an
        #: empty set is honest ("no page id is known to us yet"), never a claim.
        self._ids = set(hot_page_ids or ())

    def __len__(self) -> int:
        """How many distinct TITLES this set holds. Deliberately not a total across
        the two key spaces: a page counted once by id and once by title would
        overstate the set, and this number is shown to an operator."""
        return len(self._tracked | self._mentions | self._pageview_top)

    def sizes(self) -> dict[str, int]:
        """Each source's own count, never a blend. Shown beside the tier so an
        operator can see WHICH source is carrying the tier on their corpus."""
        return {
            "pinned": len(self._pinned_ids),
            "tracked": len(self._tracked),
            "corpus_mention": len(self._mentions),
            "pageview_top": len(self._pageview_top),
            "known_page_ids": len(self._ids),
        }

    def decide(
        self, *, titles: Sequence[str] | None, page_id: int | None = None
    ) -> TierDecision:
        """The tier for one changed page, given EVERY name the source used for it.

        Reasons are checked in :data:`HOT_REASONS` order, so a page that is both
        pinned and in the top-1,000 reports the operator's own choice. Within a
        reason, the titles are tried in the order given.

        ``titles`` IS A SEQUENCE AND A BARE STRING IS REFUSED, which is not
        pedantry: ``"Rome"`` iterates into five one-letter titles that match nothing,
        and the page would silently fall to WARM. The same trap is refused by name in
        ``scheduler/settings.py``'s edition list, for the same reason.

        Taking several names is what survives a MOVE inside one batch: a page renamed
        mid-stream is still the page the corpus mentions under its old title, and a
        decision made on the newest name alone drops it (measured on the recorded
        fixture — see ``lane.py``'s ``_seen``).
        """
        if isinstance(titles, (str, bytes)):
            raise TypeError(
                "HotSet.decide takes a SEQUENCE of titles; a bare string would "
                "iterate into single characters and match nothing"
            )
        if page_id is not None and page_id in self._pinned_ids:
            return TierDecision("hot", "pinned", True, None)
        norms = [n for n in (normalize_title(t or "") for t in (titles or ())) if n]
        for norm in norms:
            if norm in self._tracked:
                return TierDecision("hot", "tracked", True, None)
        for norm in norms:
            if norm in self._mentions:
                return TierDecision("hot", "corpus_mention", True, None)
        for norm in norms:
            if norm in self._pageview_top:
                return TierDecision("hot", "pageview_top", True, None)
        if page_id is not None and page_id in self._ids:
            # Known HOT by id and no longer matching by title: the page MOVED. Its
            # tier survives the move, which is the whole reason the id path exists.
            # The reason is the weakest true one rather than a guess at which of the
            # three it originally was — inventing that would put a fact on screen
            # that nothing measured.
            return TierDecision("hot", "tracked", True, None)
        return _WARM


@dataclass(frozen=True, slots=True)
class BudgetState:
    """What the lane's storage budget is, and how much of it is spent.

    Every number here is measured or declared; none is estimated. ``disk_bytes`` is
    ``None`` when the lane file does not exist, which is NOT zero — a lane that has
    never run and a lane holding an empty file are different states, and
    ``store.lane_file_bytes`` already refuses to merge them.
    """

    total_gb: int
    total_bytes: int
    #: The lane FILE, sidecars included, or ``None`` when there is no file yet.
    disk_bytes: int | None
    editions: int
    #: ``total_bytes // editions``, stated rather than folded in: the wizard shows
    #: the division so an operator adding a thirteenth edition can see the share fall.
    per_edition_bytes: int

    @property
    def measured(self) -> bool:
        """Whether a spend figure exists at all. False before the lane's first run."""
        return self.disk_bytes is not None

    @property
    def remaining_bytes(self) -> int | None:
        """Room left, or ``None`` when nothing has been measured. Never negative:
        an over-budget lane reports ``0`` remaining AND ``exhausted``, because a
        negative remainder reads as a countdown that has more to give."""
        if self.disk_bytes is None:
            return None
        return max(0, self.total_bytes - self.disk_bytes)

    @property
    def exhausted(self) -> bool:
        """True only when a MEASUREMENT says so. An unmeasured budget is not
        exhausted — refusing to ingest because nothing has been measured yet would
        stop a lane on its first pass, forever."""
        return self.disk_bytes is not None and self.disk_bytes >= self.total_bytes

    def as_dict(self) -> dict:
        return {
            "total_gb": self.total_gb,
            "total_bytes": self.total_bytes,
            "disk_bytes": self.disk_bytes,
            "editions": self.editions,
            "per_edition_bytes": self.per_edition_bytes,
            "remaining_bytes": self.remaining_bytes,
            "measured": self.measured,
            "exhausted": self.exhausted,
            # The method travels WITH the numbers, never in a doc a caller may not
            # read: every figure this app shows carries how it was obtained.
            "method": (
                "budget: the operator's total, set in the first-run wizard "
                "(default 20 GB, published). spend: the lane file on disk including "
                "its -wal/-shm sidecars. rate is the collection-speed governor's, "
                "not a second budget."
            ),
        }


def require_budget_gb(value: object) -> int:
    """Return ``value`` as a budget in whole GB, or refuse by name.

    Refuses rather than clamps. A clamp turns "2" typed into a field meant for
    "2000" into a silent 2 GB lane, and the operator finds out when their corpus
    stops growing; a refusal puts the disagreement on screen while they are looking
    at it.
    """
    try:
        gb = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        raise ValueError(f"the lane budget must be a whole number of GB, got {value!r}") from None
    if gb < BUDGET_GB_MIN or gb > BUDGET_GB_MAX:
        raise ValueError(
            f"the lane budget must be between {BUDGET_GB_MIN} and {BUDGET_GB_MAX} GB, got {gb}"
        )
    return gb


def budget_state(*, total_gb: int, disk_bytes: int | None, editions: int) -> BudgetState:
    """Compose a :class:`BudgetState`. ``editions`` of 0 is refused, not defaulted —
    a lane with no editions has no per-edition share to report and the caller asking
    for one has a bug a divide-by-zero guard would hide."""
    if editions <= 0:
        raise ValueError("a budget needs at least one edition to divide between")
    total_bytes = require_budget_gb(total_gb) * _BYTES_PER_GB
    return BudgetState(
        total_gb=total_gb,
        total_bytes=total_bytes,
        disk_bytes=disk_bytes,
        editions=editions,
        per_edition_bytes=total_bytes // editions,
    )
