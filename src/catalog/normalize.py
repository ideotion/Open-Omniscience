"""
Normalise catalog entries: registrable domain, social-host exclusion, dedup.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure, network-free helpers used by the catalog generator (and unit-tested without
any live calls). They turn raw "official website" URLs into the Source-catalog
schema, drop social-network hosts (out of scope for now), and deduplicate by
domain both within a batch and against the already-shipped catalogs.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Hosts excluded for now: social networks / link aggregators / video & chat
# platforms. Matched by registrable domain or as a suffix (so m.facebook.com,
# x.com, fb.me etc. are all caught).
SOCIAL_HOSTS: frozenset[str] = frozenset(
    {
        "facebook.com",
        "fb.com",
        "fb.me",
        "instagram.com",
        "threads.net",
        "twitter.com",
        "x.com",
        "t.co",
        "tiktok.com",
        "youtube.com",
        "youtu.be",
        "reddit.com",
        "linkedin.com",
        "lnkd.in",
        "telegram.org",
        "t.me",
        "whatsapp.com",
        "wa.me",
        "snapchat.com",
        "pinterest.com",
        "tumblr.com",
        "mastodon.social",
        "bsky.app",
        "vk.com",
        "ok.ru",
        "weibo.com",
        "medium.com",
        "substack.com",
    }
)


def registrable_domain(url_or_host: str | None) -> str | None:
    """Reduce a URL or host to a lowercase ``host`` without scheme/path/port/www.

    Not a full Public-Suffix-List reduction (no dependency): it strips a leading
    ``www.`` and any port, which is sufficient for dedup keys and exclusion checks.
    Returns ``None`` for empty/malformed input.
    """
    if not url_or_host:
        return None
    raw = url_or_host.strip()
    if not raw:
        return None
    # Ensure urlparse sees a netloc even for a bare host.
    parsed = urlparse(raw if "//" in raw else f"//{raw}", scheme="https")
    host = (parsed.netloc or parsed.path).strip().lower()
    host = host.split("@")[-1]  # drop any userinfo
    host = host.split(":")[0]  # drop port
    host = host.rstrip(".")  # drop trailing dot
    if host.startswith("www."):
        host = host[4:]
    return host or None


def is_social(domain: str | None) -> bool:
    """True if ``domain`` is (or is a subdomain of) an excluded social host."""
    if not domain:
        return False
    d = domain.lower()
    return any(d == h or d.endswith("." + h) for h in SOCIAL_HOSTS)


def to_entry(
    *,
    name: str | None,
    url: str | None,
    country: str | None = None,
    language: str | None = None,
    source_type: str = "news",
    tags: list[str] | None = None,
) -> dict | None:
    """Build one catalog entry, or ``None`` if it should be dropped.

    Dropped when there is no name, no usable domain, or the domain is a social
    host. ``country`` is normalised to a lowercase 2-letter code; ``tags`` always
    include the source_type bucket for easy filtering.
    """
    domain = registrable_domain(url)
    if not name or not name.strip() or not domain or is_social(domain):
        return None
    cc = (country or "").strip().lower() or None
    if cc is not None and len(cc) != 2:
        cc = None
    entry: dict = {
        "name": name.strip(),
        "domain": domain,
        "source_type": source_type,
    }
    if cc:
        entry["country"] = cc
    lang = (language or "").strip().lower() or None
    if lang:
        entry["language"] = lang
    base_tags = list(tags or [])
    if source_type not in base_tags:
        base_tags.append(source_type)
    entry["tags"] = base_tags
    return entry


def dedup_entries(entries: list[dict], existing_domains: set[str] | None = None) -> dict:
    """Deduplicate entries by domain, within the batch and against ``existing_domains``.

    Returns ``{"kept": [...], "skipped_existing": int, "skipped_dupes": int}``.
    The first occurrence of a domain wins.
    """
    seen = set(existing_domains or set())
    kept: list[dict] = []
    skipped_existing = 0
    skipped_dupes = 0
    for e in entries:
        d = e.get("domain")
        if not d:
            continue
        if existing_domains and d in (existing_domains or set()):
            skipped_existing += 1
            continue
        if d in seen:
            skipped_dupes += 1
            continue
        seen.add(d)
        kept.append(e)
    return {"kept": kept, "skipped_existing": skipped_existing, "skipped_dupes": skipped_dupes}
