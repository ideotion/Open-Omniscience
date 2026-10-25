"""
Host mismatch between a stored article's URL and its source's own site (qualification lane, 2026-10-25).

A source row names a site (``Source.domain``); an article stored under it normally lives on that
site. When it does not, the page may be a syndicated or aggregated item, a redirect target, or a
feed that points elsewhere. That is a fact about WHERE the page lives, not a verdict that it is
junk: a mismatching page can be a perfectly good article. So this module only REPORTS the fact; the
quarantine job counts it and samples it for the operator and never marks an article for it.

Sites are compared by registrable domain (public suffix plus one label, from the ICANN part of the
Public Suffix List only), so ``www.``/``m.``/``amp.`` hosts and ``news.bbc.co.uk`` vs ``bbc.co.uk``
are the same site, while ``example.co.uk`` and ``co.uk`` are never confused. Private-suffix hosts
(``blogspot.com``, ``github.io``) are therefore compared as the platform, which is the conservative
reading: two blogs on one platform read as the same site, never as a mismatch. Hosts are compared in
their ASCII (punycode) form, so a Unicode and a punycode spelling of one site agree. UNKNOWN is its
own answer and is never counted as a mismatch: a missing, empty or malformed domain or URL, an IP
address, a top-level domain the list has no rule for, or a host the list cannot reduce.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from typing import NamedTuple
from urllib.parse import urlparse


class HostCheck(NamedTuple):
    """``state`` is ``"same"``, ``"mismatch"`` or ``"unknown"``; the sites are None when unknown."""

    state: str
    source_site: str | None
    article_site: str | None


def _ace(host: str) -> str | None:
    """``host`` in its ASCII (punycode) form, so the Unicode and punycode spellings of one site agree."""
    if host.isascii():
        return host
    try:
        return host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None


def _site(host_or_url: str | None) -> str | None:
    from src.catalog.publicsuffix import _load, registrable_domain_psl

    if not host_or_url or not host_or_url.strip():
        return None
    raw = host_or_url.strip()
    try:
        parsed = urlparse(raw if "//" in raw else f"//{raw}")
        host = parsed.hostname
    except ValueError:
        return None
    if not host:
        return None
    host = _ace(host)
    if host is None:
        return None
    # A top-level domain the list has no rule for (foo.invalidtld, .local) would otherwise be reduced by
    # the list's implicit "*" rule and read as a site; it is UNKNOWN, not a site to compare.
    rules = _load()
    if not rules.available or host.rsplit(".", 1)[-1] not in rules.icann:
        return None
    return registrable_domain_psl(host, include_private=False)


def check_host(article_url: str | None, source_domain: str | None) -> HostCheck:
    """Compare the registrable site of ``article_url`` with that of ``source_domain``."""
    src, art = _site(source_domain), _site(article_url)
    if src is None or art is None:
        return HostCheck("unknown", src, art)
    return HostCheck("same" if src == art else "mismatch", src, art)
