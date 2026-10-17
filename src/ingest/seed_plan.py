"""What a catalogue registers when a source is keyed on ``(domain, feed)`` (row J, S05-10 J3).

``seed_sources`` used to keep the FIRST entry of a domain and drop the rest, which lost BBC's thirty language services
and the lean-tagged spectrum catalogue (475 of 6,670 entries on a real boot). With ``UNIQUE (domain, feed_key)`` an
entry is one of three things, decided here, purely, from the loaded catalogue and nothing else:

* a ROW -- an entry with a feed whose ``(domain, feed)`` no earlier entry claimed, or a feed-less entry whose domain
  carries no feed entry at all (the outlet's one feed-less row);
* a MERGE -- a feed-less entry whose domain DOES carry a feed row. It describes that outlet from a catalogue that has
  no feed (210 of 235 are the lean-tagged spectrum), so it creates no second, uncollectable copy of the outlet: its
  TAGS go onto the outlet's first feed row;
* UNREGISTERED, with a reason -- the same feed claimed twice, a feed-less duplicate of a feed-less domain, or a
  second entry of the legal catalogue for a host (the ruled 2026-07-17 collapse: "registration must collapse them").

Pure: no database, no network. The answer is named per entry, so the seeder's report can say which entries stayed out and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.database.feed_key import feed_key

#: A tag from this family is EXCLUSIVE on one row: a row carries one lean, and a second, different one is a conflict.
EXCLUSIVE_TAG_PREFIXES = ("lean-",)

REASON_FEEDLESS_DUPLICATE = "feedless_duplicate"
REASON_LEGAL_COLLAPSE = "legal_collapse"


@dataclass
class Plan:
    rows: list[dict] = field(default_factory=list)
    #: ``(feed-less entry, the row entry that receives its tags)``
    merges: list[tuple[dict, dict]] = field(default_factory=list)
    #: ``(entry, reason)``
    unregistered: list[tuple[dict, str]] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        by_reason: dict[str, int] = {}
        for _entry, reason in self.unregistered:
            by_reason[reason] = by_reason.get(reason, 0) + 1
        return {"rows": len(self.rows), "merged": len(self.merges), "unregistered": len(self.unregistered), **{
            f"unregistered_{k}": v for k, v in sorted(by_reason.items())}}


def entry_key(entry: dict) -> tuple[str, str]:
    """The ``(domain, feed_key)`` an entry would register under: the ONE normaliser, never re-derived."""
    return (str(entry.get("domain") or "").strip().lower(), feed_key(entry.get("rss_url")))


def plan_registration(entries: list[dict]) -> Plan:
    """Decide every entry's fate, in catalogue order (the order ``seed_sources`` inserts in)."""
    plan = Plan()
    live: list[dict] = []
    legal_seen: set[str] = set()
    for e in entries:
        domain = str(e.get("domain") or "").strip().lower()
        if not domain:
            continue  # malformed: the seeder reports these apart
        if str(e.get("_provenance") or "").startswith("legal"):
            if domain in legal_seen:
                plan.unregistered.append((e, REASON_LEGAL_COLLAPSE))
                continue
            legal_seen.add(domain)
        live.append(e)

    first_feed_row: dict[str, dict] = {}
    for e in live:
        domain, fk = entry_key(e)
        if fk and domain not in first_feed_row:
            first_feed_row[domain] = e

    claimed: dict[tuple[str, str], dict] = {}
    for e in live:
        domain, fk = entry_key(e)
        if not fk and domain in first_feed_row:
            plan.merges.append((e, first_feed_row[domain]))
            continue
        if (domain, fk) in claimed:
            if fk:
                # The SAME feed named by a second catalogue: the same source described twice (the spectrum catalogue's
                # CNN beside the curated one), so its tags go on the row that claimed it.
                plan.merges.append((e, claimed[(domain, fk)]))
            else:
                plan.unregistered.append((e, REASON_FEEDLESS_DUPLICATE))
            continue
        claimed[(domain, fk)] = e
        plan.rows.append(e)
    return plan


def split_tags(value: str | None) -> list[str]:
    return [t.strip() for t in str(value or "").split(",") if t.strip()]


def entry_tags(entry: dict) -> list[str]:
    """The descriptive tags an entry carries: never the ``via:`` provenance marker, which is a fact about a row's origin."""
    tags = entry.get("tags")
    raw = [str(t) for t in tags] if isinstance(tags, list) else ([str(tags)] if tags else [])
    return [t.strip() for t in raw if t.strip() and not t.strip().startswith("via:")]


def exclusive_family(tag: str) -> str | None:
    for p in EXCLUSIVE_TAG_PREFIXES:
        if tag.startswith(p):
            return p
    return None
