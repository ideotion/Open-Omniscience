"""Which publisher does an imported newsletter belong to?

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULING THIS IMPLEMENTS (2026-06-15, "MASS LOCAL .eml NEWSLETTER IMPORT",
clause (d)). Today every imported newsletter lands in ONE bucket source
(``newsletters.import.local``), so a BBC newsletter sent from ``email.bbc.com``
has no relationship to the scraped ``bbc.com``. The ruled ladder is:

    a proper eTLD+1 (vendored Public Suffix List, network-free)
      -> EXACT ``Source.domain`` match
      -> the ``is_equivalent_domain`` alias map (bbc.com <-> bbc.co.uk)
      -> else a NEW, DISABLED email source

and, stated in the same breath, **never fuzzy-merge -- bbc is not nbc**. Nothing
here does string similarity, prefix matching or edit distance; a resolution is
deterministic or it is refused.

THE PLATFORM INVERSION IS THE PART THAT IS EASY TO GET BACKWARDS, and it is not
redundant with the list. For a newsletter platform the publication lives on the
SUBDOMAIN or in the List-Id, so reducing to the eTLD+1 collapses every publisher
on that platform into one source -- the exact opposite of what the eTLD+1 buys
everywhere else. MEASURED 2026-09-07 against the vendored snapshot: substack.com,
beehiiv.com, ghost.io, mailchimp, buttondown.email, convertkit/kit.com and
medium.com are in NEITHER section of the Public Suffix List, so the list would
happily perform that collapse. The inversion therefore needs its own curated set,
below, and it is a REFUSAL when the sending host carries no publication label --
attaching to the bare platform is the merge the ruling forbids, and a refusal is
a gap while a merge is a fabrication.

WHAT THIS MODULE DOES NOT DO, deliberately. It decides nothing on the write path.
The ruling pairs silent auto-attach with a dedicated import UI that announces it
and an UNDO for the automated attaches; shipping the attach without those would be
half a data-placement change, which is worse than none. So the resolver is pure
and its caller today is a READ-ONLY report (``resolution_preview``) over the
newsletters already imported -- the evidence a maintainer needs to approve the
attach, computed with the real function rather than described.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.catalog.publicsuffix import list_status, registrable_domain_psl
from src.database.models import Article, Source
from src.utils.url_utils import DOMAIN_ALIASES, is_equivalent_domain, normalize_domain

# Newsletter/blog platforms whose PUBLICATIONS live on a subdomain. Curated and
# dated (2026-09-07) rather than inferred: every entry is a host where "the
# eTLD+1" and "the publisher" are different things, so collapsing to the former
# merges unrelated publishers. Kept small and evidence-based -- a host belongs
# here only when the platform genuinely gives each publication its own label.
#
# NOT a copy of SOCIAL_HOSTS, which answers a different question (should this
# link seed a source at all). Two sets that answer two questions is deliberate;
# one set serving both is how a rule ends up applied where it does not belong.
NEWSLETTER_PLATFORM_HOSTS: frozenset[str] = frozenset(
    {
        "substack.com",
        "beehiiv.com",
        "ghost.io",
        "buttondown.email",
        "buttondown.com",
        "convertkit.com",
        "kit.com",
        "campaign-archive.com",  # Mailchimp's public archive host
        "list-manage.com",  # Mailchimp sending host
        "mailchimpapp.net",
        "medium.com",
        "wordpress.com",
        "tumblr.com",
        "blogspot.com",
        "revue.email",
    }
)

_PLATFORM_HOSTS_AS_OF = "2026-09-07"

# RFC 2919 List-Id: an optional phrase then the identifier in angle brackets.
_LIST_ID_RE = re.compile(r"<([^<>@\s]+)>")

# Sending labels that name INFRASTRUCTURE rather than a publication. On a platform
# host these must never be read as the publisher: "mail.substack.com" is Substack's
# own mail server, not a publication called "mail".
_INFRA_LABELS: frozenset[str] = frozenset(
    {"mail", "email", "e", "mailer", "smtp", "mx", "bounce", "bounces", "reply",
     "noreply", "no-reply", "news", "newsletter", "newsletters", "send", "sender",
     "list", "lists", "mta", "relay", "notifications", "notification"}
)


@dataclass(frozen=True)
class PublisherKey:
    """The domain a newsletter should be filed under, and how it was derived."""

    key: str | None
    basis: str  # "etld1" | "platform-subdomain" | "platform-list-id" | "refused"
    reason: str
    send_domain: str | None = None
    platform: str | None = None


@dataclass(frozen=True)
class Resolution:
    """What WOULD happen for a newsletter from this sender, and why."""

    action: str  # attach-exact | attach-alias | new-email-source | refused
    key: str | None
    basis: str
    reason: str
    source_id: int | None = None
    source_name: str | None = None
    source_domain: str | None = None
    send_domain: str | None = None
    platform: str | None = None
    examples: list[str] = field(default_factory=list)


def parse_list_id(raw: str | None) -> str | None:
    """The bare List-Id identifier from an RFC 2919 header value.

    ``List-Id: "Weekly" <weekly.example.com>`` -> ``weekly.example.com``. Returns
    ``None`` when the header is absent or carries no bracketed identifier; a
    bare unbracketed value is NOT accepted, because the phrase before the
    brackets is free text and reading it as an identifier would invent one.
    RECIPIENT-SAFE by construction: List-Id names the LIST, never a subscriber
    (which is why the ruling keeps it and drops List-Unsubscribe).
    """
    if not raw:
        return None
    m = _LIST_ID_RE.search(raw)
    if not m:
        return None
    ident = m.group(1).strip().strip(".").lower()
    return ident or None


def sender_domain(from_addr: str | None) -> str | None:
    """The domain of a From header, whether it is bare or ``Name <a@b.com>``."""
    if not from_addr:
        return None
    raw = from_addr.strip()
    if "<" in raw and ">" in raw:
        raw = raw[raw.rfind("<") + 1 : raw.rfind(">")]
    raw = raw.strip().strip("<>").strip()
    if "@" not in raw:
        return None
    dom = raw.rsplit("@", 1)[1].strip().strip(".").lower()
    return dom or None


def _platform_for(host: str) -> str | None:
    """The platform host ``host`` sits under, if any (never the host itself)."""
    for plat in NEWSLETTER_PLATFORM_HOSTS:
        if host == plat or host.endswith("." + plat):
            return plat
    return None


def publisher_key(from_addr: str | None, list_id: str | None = None) -> PublisherKey:
    """The publisher domain for a newsletter, or a refusal with its reason.

    Order matters and is the ruling's: the PLATFORM check comes FIRST, because for
    a platform host the eTLD+1 is the wrong answer rather than a coarse one.
    """
    dom = sender_domain(from_addr)
    lid = parse_list_id(list_id)
    if not dom:
        return PublisherKey(None, "refused", "no sender domain in the From header")

    plat = _platform_for(dom)
    if plat:
        # The publication label, if the sending host carries one.
        prefix = dom[: -(len(plat) + 1)] if dom != plat else ""
        labels = [label for label in prefix.split(".") if label]
        publication = labels[-1] if labels else None
        if publication and publication not in _INFRA_LABELS:
            return PublisherKey(
                f"{publication}.{plat}", "platform-subdomain",
                f"{plat} gives each publication its own label; collapsing to {plat} "
                "would merge unrelated publishers",
                send_domain=dom, platform=plat,
            )
        # No usable label on the host — the List-Id is the ruling's stable key.
        if lid:
            lid_plat = _platform_for(lid)
            if lid_plat == plat:
                lid_prefix = lid[: -(len(plat) + 1)]
                lid_labels = [x for x in lid_prefix.split(".") if x]
                pub = lid_labels[-1] if lid_labels else None
                if pub and pub not in _INFRA_LABELS:
                    return PublisherKey(
                        f"{pub}.{plat}", "platform-list-id",
                        f"the List-Id names the publication on {plat}",
                        send_domain=dom, platform=plat,
                    )
        return PublisherKey(
            None, "refused",
            f"sent through {plat} with no publication label on the host and no "
            "List-Id naming one — attaching to the platform itself would merge "
            "every publisher on it into one source",
            send_domain=dom, platform=plat,
        )

    etld1 = registrable_domain_psl(dom, include_private=True)
    if not etld1:
        status = list_status()
        if not status["available"]:
            return PublisherKey(
                None, "refused",
                f"the Public Suffix List is unavailable ({status['reason']}), so no "
                "eTLD+1 can be derived — guessing one would invent a publisher",
                send_domain=dom,
            )
        return PublisherKey(
            None, "refused",
            f"{dom} has no registrable domain (it is a public suffix, an IP literal "
            "or not a domain at all)",
            send_domain=dom,
        )
    return PublisherKey(
        etld1, "etld1", "eTLD+1 from the vendored Public Suffix List",
        send_domain=dom,
    )


def _alias_candidates(key: str) -> set[str]:
    """Every domain the alias map says is the SAME publisher as ``key``."""
    out: set[str] = set()
    norm = normalize_domain(key)
    for left, rights in DOMAIN_ALIASES.items():
        if left == norm:
            out.update(rights)
        elif norm in rights:
            out.add(left)
            out.update(r for r in rights if r != norm)
    out.discard(norm)
    return out


def resolve_newsletter_publisher(
    session: Session, from_addr: str | None, list_id: str | None = None
) -> Resolution:
    """The ruled ladder, as a decision — it writes nothing.

    CASE-INSENSITIVE ON PURPOSE, and the reason is a recorded defect: ``Source.domain``
    is compared with SQLite's BINARY collation and ``POST /api/sources`` stores the
    domain as typed, so lowercasing only OUR side would silently miss a source added
    as ``Example.COM`` — a refusal that does not fire looks exactly like a publisher
    nobody has. Matching ``lower(Source.domain)`` costs a scan of a table with a few
    thousand rows, which is free for a report; a future write-path wiring that runs
    this per message should revisit it (a functional index would need a migration).
    """
    pk = publisher_key(from_addr, list_id)
    if not pk.key:
        return Resolution(
            "refused", None, pk.basis, pk.reason,
            send_domain=pk.send_domain, platform=pk.platform,
        )

    wanted = {pk.key} | _alias_candidates(pk.key)
    rows = (
        session.query(Source.id, Source.name, Source.domain)
        .filter(func.lower(Source.domain).in_(sorted(wanted)))
        .all()
    )
    exact = next((r for r in rows if (r.domain or "").lower() == pk.key), None)
    if exact is not None:
        return Resolution(
            "attach-exact", pk.key, pk.basis,
            f"{pk.reason}; an existing source already claims this domain",
            source_id=exact.id, source_name=exact.name, source_domain=exact.domain,
            send_domain=pk.send_domain, platform=pk.platform,
        )
    alias = next(
        (r for r in rows if r.domain and is_equivalent_domain(r.domain, pk.key)), None
    )
    if alias is not None:
        return Resolution(
            "attach-alias", pk.key, pk.basis,
            f"{pk.reason}; the alias map records {alias.domain} as the same publisher",
            source_id=alias.id, source_name=alias.name, source_domain=alias.domain,
            send_domain=pk.send_domain, platform=pk.platform,
        )
    return Resolution(
        "new-email-source", pk.key, pk.basis,
        f"{pk.reason}; no existing source claims it, so it would be registered as a "
        "new DISABLED email source",
        send_domain=pk.send_domain, platform=pk.platform,
    )


def resolution_preview(session: Session, *, limit_examples: int = 3) -> dict:
    """What the ladder WOULD do for the newsletters already in the corpus.

    Read-only: it resolves, it does not attach. Grouped by sender domain so the
    output is a decision list a person can review rather than one row per message.

    ANTI-CAPPING: ``limit_examples`` bounds how many example subjects are listed
    per group; it never bounds a reported COUNT. Every ``articles`` figure here is
    the true total for that sender.
    """
    from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

    src_ids = [
        s
        for (s,) in session.query(Source.id).filter(
            Source.domain.in_(NEWSLETTER_SOURCE_DOMAINS)
        )
    ]
    status = list_status()
    if not src_ids:
        return {
            "groups": [],
            "articles": 0,
            "senders": 0,
            "list_status": status,
            "note": "no imported newsletters in this corpus yet",
            "method": _PREVIEW_METHOD,
            "caveat": _PREVIEW_CAVEAT,
        }

    by_sender: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    no_sender = 0
    total = 0
    q = (
        session.query(Article.author, Article.title)
        .filter(Article.source_id.in_(src_ids))
        .yield_per(500)
    )
    for author, title in q:
        total += 1
        dom = sender_domain(author)
        if not dom:
            no_sender += 1
            continue
        counts[dom] = counts.get(dom, 0) + 1
        ex = by_sender.setdefault(dom, [])
        if len(ex) < limit_examples and title:
            ex.append(title)

    groups = []
    for dom, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        res = resolve_newsletter_publisher(session, f"x@{dom}")
        groups.append(
            {
                "send_domain": dom,
                "articles": n,
                "action": res.action,
                "publisher": res.key,
                "basis": res.basis,
                "reason": res.reason,
                "source_id": res.source_id,
                "source_name": res.source_name,
                "platform": res.platform,
                "examples": by_sender.get(dom, []),
            }
        )
    return {
        "groups": groups,
        "articles": total,
        "senders": len(counts),
        "articles_without_a_sender_domain": no_sender,
        "list_status": status,
        "method": _PREVIEW_METHOD,
        "caveat": _PREVIEW_CAVEAT,
    }


_PREVIEW_METHOD = (
    "sender domains read from the stored From header of every imported newsletter, "
    "resolved through the ruled ladder (Public Suffix List eTLD+1, with the platform "
    "inversion applied first) against the existing sources; nothing is written and no "
    "network call is made"
)
_PREVIEW_CAVEAT = (
    "a PREVIEW: no newsletter has been attached to any publisher. The List-Id is not "
    "stored on already-imported messages, so a platform sender whose host carries no "
    "publication label is refused here even where a List-Id would have named one."
)
