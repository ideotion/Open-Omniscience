"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

"""
URL Utilities for Open Omniscience

This module provides centralized functions for:
- Canonicalizing URLs (removing tracking parameters, normalizing schemes)
- Resolving redirects to final URLs
- Generating content hashes for duplicate detection
- Normalizing domains (e.g., stripping www., lowercase)
- Deduplicating URLs (e.g., bbc.com = bbc.co.uk)

Author: Ideotion
"""

import hashlib
import logging
from urllib.parse import parse_qs, urlparse, urlunparse

from src.monitoring.secret_scrub import log_failure

# Configure logging
logger = logging.getLogger(__name__)

# Known domain aliases for equivalent domain checking.
#
# NOTE: "washingtonpost.com" used to appear here mapped to itself
# (["washingtonpost.com"]) -- a self-referential no-op. is_equivalent_domain()
# already returns True on the domain1 == domain2 short-circuit before this
# table is ever consulted, so that entry could never affect its result for any
# input; it was removed rather than kept as dead weight. No genuine alternate
# domain for washingtonpost.com has been independently verified, so no
# replacement entry was added -- add one here only once a real alias domain
# has been confirmed (see git history / PR discussion for this comment).
DOMAIN_ALIASES: dict[str, list[str]] = {
    "bbc.com": ["bbc.co.uk"],
    "theguardian.com": ["guardian.co.uk"],
    "independent.co.uk": ["independent.com"],
    "nytimes.com": ["nyt.com"],
}


def normalize_domain(domain: str) -> str:
    """
    Normalize a domain by:
    1. Lowercasing
    2. Stripping www. prefix
    3. Stripping trailing slashes
    4. Removing default ports (80, 443)

    Args:
        domain: The domain to normalize.

    Returns:
        The normalized domain.
    """
    if not domain:
        return domain

    domain = domain.lower().strip()

    # Remove default ports
    if domain.endswith(":80"):
        domain = domain[:-3]
    elif domain.endswith(":443"):
        domain = domain[:-4]

    # Strip www. prefix
    if domain.startswith("www."):
        domain = domain[4:]

    return domain.rstrip("/")


def is_equivalent_domain(domain1: str, domain2: str) -> bool:
    """
    Check if two domains are equivalent after normalization.
    Also handles known aliases (e.g., bbc.com = bbc.co.uk).

    Args:
        domain1: First domain.
        domain2: Second domain.

    Returns:
        True if domains are equivalent, False otherwise.
    """
    domain1 = normalize_domain(domain1)
    domain2 = normalize_domain(domain2)

    if domain1 == domain2:
        return True

    # Check if domain1 is an alias of domain2 or vice versa
    if domain1 in DOMAIN_ALIASES and domain2 in DOMAIN_ALIASES[domain1]:
        return True
    if domain2 in DOMAIN_ALIASES and domain1 in DOMAIN_ALIASES[domain2]:
        return True

    return False


# K2 identity seam (data-architecture Slice 5): a stable label for WHICH
# canonicalization produced an Article.canonical_url, stamped on each article. Bump
# this string (url-v2, ...) whenever :func:`canonicalize_url` changes its rules, so a
# corpus spanning a canonicaliser change can tell which articles were normalised by
# which version (and re-canonicalise only the stale ones) instead of silently mixing
# them. Additive; never reformats the existing canonical_url.
#
# url-v2 (R628): the userinfo is no longer part of a canonical URL. url-v1 kept it, so
# https://alice:pw@a.example/x and https://a.example/x were two pages to the dedup and
# the credentials reached the stored canonical_url. An article stamped url-v1 differs
# from its url-v2 form only when its canonical_url holds a userinfo;
# :func:`url_v1_canonical` gives that form back for the pre-fetch dedup.
CANON_VERSION = "url-v2"


def _authority_host(netloc: str) -> str:
    """The host and port of ``netloc``: the userinfo is everything before the LAST ``@``, as ``urllib.parse`` reads it (R628)."""
    return netloc.rpartition("@")[2]


def _canonical_form(url: str, *, keep_userinfo: bool) -> str:
    """:func:`canonicalize_url`'s rules, raising what ``urllib.parse`` raises; ``keep_userinfo`` is url-v1's netloc."""
    parsed = urlparse(url)

    # Normalize scheme (force https)
    scheme = "https"

    # Normalize domain (lowercase, strip www., remove default ports), its userinfo out (R628)
    netloc = normalize_domain(parsed.netloc if keep_userinfo else _authority_host(parsed.netloc))

    # Remove tracking parameters
    query = parse_qs(parsed.query, keep_blank_values=True)
    tracking_params = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "dclid",
        "msclkid",
    }
    filtered_query = {k: v for k, v in query.items() if k.lower() not in tracking_params}

    # Sort remaining query parameters for consistency, preserving ALL values of
    # multi-valued params (a=1&a=2 must not collapse to a=1 -- that changes
    # semantics and dedup).
    sorted_query = dict(sorted(filtered_query.items()))
    clean_query = "&".join(f"{k}={val}" for k, vals in sorted_query.items() for val in vals)

    # Normalize path
    path = parsed.path
    if not path:
        path = "/"
    elif len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Rebuild URL
    return urlunparse(
        (
            scheme,
            netloc,
            path,
            parsed.params,
            clean_query,
            "",  # Remove fragment
        )
    )


def canonicalize_url(url: str) -> str:
    """
    Canonicalize a URL by:
    1. Stripping tracking parameters (e.g., utm_*, gclid)
    2. Normalizing the scheme (http:// → https://)
    3. Removing fragments (#)
    4. Lowercasing the domain
    5. Normalizing the domain (strip www., remove default ports)
    6. Removing empty path (set to /)
    7. Removing trailing slash from path (except root)
    8. Removing the userinfo (R628, url-v2): what precedes the LAST ``@`` of the
       authority, as urllib.parse reads it. The request itself still carries the
       URL as given; only the canonical form, the dedup key, loses it.

    Args:
        url: The URL to canonicalize.

    Returns:
        The canonicalized URL.
    """
    if not url:
        return url

    try:
        return _canonical_form(url, keep_userinfo=False)

    except Exception as e:
        # imported on use: this module must not load src.ingest (R621)
        from src.ingest.fetch_verdict import failure_url

        log_failure(logger, f"Error canonicalizing URL {failure_url(url)}", e)
        return url


def url_v1_canonical(url: str) -> str | None:
    """The canonical form ``url-v1`` gave ``url``, or ``None`` when it is today's (R628).

    Only a URL whose authority holds a userinfo (an ``@``, as ``urllib.parse`` reads it) has one: url-v1 kept the userinfo and
    url-v2 drops it, and nothing else changed. An article stored before R628 from such a URL keeps that form in its
    ``canonical_url``, so the pre-fetch dedup asks for it too and does not fetch the page again. ``None`` as well for a URL
    :func:`canonicalize_url` cannot read (it logs that once; this adds nothing). Never raises."""
    if not url:
        return None
    try:
        if "@" not in urlparse(url).netloc:
            return None
        return _canonical_form(url, keep_userinfo=True)
    except Exception:  # noqa: BLE001 - canonicalize_url already logged this URL's failure; the fallback has nothing to add
        return None


# NOTE (audit 0.0.9): a resolve_redirects() helper used to live here, making raw
# requests.head() calls. It was never called anywhere — and the single-fetch-path
# rule means any future redirect resolution must go through the EthicalFetcher,
# never a bare requests call. Removed rather than kept as an attractive nuisance.


def generate_content_hash(content: str) -> str:
    """
    Generate a SHA-256 hash of the content for duplicate detection.

    Args:
        content: The text content to hash.

    Returns:
        The SHA-256 hash as a hexadecimal string.
    """
    if not content:
        return ""

    # Clean content: remove extra whitespace and normalize
    cleaned_content = " ".join(content.split())
    return hashlib.sha256(cleaned_content.encode("utf-8")).hexdigest()


# K1 identity seam (data-architecture Slice 5): the SELF-DESCRIBING content hash.
# ``Article.hash`` is a bare SHA-256 hex string and is load-bearing for dedup (unique
# index) -- it must NEVER be reformatted. ``content_multihash`` lives ALONGSIDE it,
# naming the algorithm explicitly (``sha2-256:<hex>``) so that if the content-hash
# algorithm ever changes, new articles carry e.g. ``blake3:<hex>`` while old keep
# ``sha2-256:<hex>`` -- the column is unambiguous about which produced a given digest.
# Today's value is derived from the same digest as ``hash`` (so they are consistent by
# construction); the backfill is a pure string prefix, no content re-hash.
CONTENT_HASH_ALGO = "sha2-256"


def content_multihash(content: str) -> str:
    """Self-describing content hash (``sha2-256:<hex>``) over the same bytes as
    :func:`generate_content_hash`. Empty string for empty content (honest, never a
    fabricated digest of nothing)."""
    digest = generate_content_hash(content)
    return f"{CONTENT_HASH_ALGO}:{digest}" if digest else ""


def get_domain_from_url(url: str) -> str | None:
    """
    Extract the domain from a URL.

    Args:
        url: The URL to extract domain from.

    Returns:
        The domain (netloc) or None if URL is invalid.
    """
    try:
        parsed = urlparse(url)
        if parsed.netloc:
            return normalize_domain(_authority_host(parsed.netloc))  # the host, its userinfo out (R628)
        return None
    except Exception as e:
        # imported on use: this module must not load src.ingest (R621)
        from src.ingest.fetch_verdict import failure_url

        log_failure(logger, f"Error extracting domain from {failure_url(url)}", e)
        return None


def fetched_host(url: str | None) -> str | None:
    """The host a fetch that ended on ``url`` was answered by (``Article.fetched_host``, queue item 61). Never raises.

    ``urllib.parse``'s ``.hostname``: lower-cased, with no login, no port, an IPv6 literal without its brackets, cut at 255
    characters (a DNS name is at most 253). ``None`` when ``url`` names no host or cannot be read: not recorded, never a guess.
    Read from the address the fetch ENDED on (its final URL, after the redirects the fetcher followed), not the one it was asked
    for, since that is where the stored bytes came from.
    """
    if not url:
        return None
    try:
        host = urlparse(url).hostname
    except ValueError:  # an unreadable port or bracket: the fetcher would have refused it, so nothing names a host here
        return None
    return host[:255] if host else None


def off_the_source_site(host: str | None, source_domain: str | None) -> bool | None:
    """Whether ``host``, where an article was fetched from (``Article.fetched_host``), is another site than its source's
    ``source_domain`` (queue item 61). ``None`` when nothing can be said.

    Sites are compared by registrable domain, the comparison the quarantine host-mismatch report already makes
    (:func:`src.ingest.host_mismatch.check_host`): ``en.yna.co.kr`` is Yonhap's own site beside ``yna.co.kr``, ``www.`` and
    other subdomains are the same site, a Unicode name and its punycode agree, and ``example.co.uk`` is never ``co.uk``. Its
    UNKNOWN is ``None`` here, never "another site": a missing or unreadable host or domain, an IP address, a top-level domain
    the Public Suffix List has no rule for. NOT the crawl's same-site rule (:func:`src.ingest.crawl._off_site`), which reads
    every other host as off the site: right for keeping a crawl in bounds, wrong as a statement shown to the reader, since
    many sources publish on a subdomain of the domain they are listed under. Never raises.
    """
    if not host or not source_domain:
        return None
    # Imported here: this module is imported by src.ingest's own modules, and check_host is network-free (urllib.parse and
    # the bundled Public Suffix List), so a reader that only shows a stored host never needs the fetcher.
    from src.ingest.host_mismatch import check_host

    state = check_host(host, source_domain).state
    return True if state == "mismatch" else False if state == "same" else None


def fetched_host_fields(host: str | None, source_domain: str | None) -> dict:
    """``fetched_host`` and ``fetched_off_site`` for a payload that credits an article to its source (queue item 61): the host
    as stored (null when not recorded) and :func:`off_the_source_site` against the source's domain. One place, so the article
    rows, the Home feed's cards and the briefing's evidence audit cannot come to disagree about the same article."""
    return {"fetched_host": host, "fetched_off_site": off_the_source_site(host, source_domain)}


def get_base_url(url: str) -> str | None:
    """
    Get the base URL (scheme + netloc) from a URL.

    Args:
        url: The URL to get base URL from.

    Returns:
        The base URL or None if URL is invalid.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{normalize_domain(_authority_host(parsed.netloc))}"  # its userinfo out (R628)
        return None
    except Exception as e:
        # imported on use: this module must not load src.ingest (R621)
        from src.ingest.fetch_verdict import failure_url

        log_failure(logger, f"Error getting base URL from {failure_url(url)}", e)
        return None
