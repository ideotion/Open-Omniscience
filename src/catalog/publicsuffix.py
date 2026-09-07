"""Offline Public Suffix List: the eTLD+1 of a host, computed from a vendored snapshot.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. ``catalog.normalize.registrable_domain`` says in its own docstring
that it is "not a full Public-Suffix-List reduction (no dependency): it strips a
leading ``www.`` and any port". That is honest and it is enough for a dedup key --
but the newsletter ruling (2026-06-15) asks a question it cannot answer: *is a BBC
newsletter sent from ``email.bbc.com`` the same publisher as the scraped
``bbc.com``?* Answering that needs a real eTLD+1, and a real eTLD+1 needs the list,
because no arithmetic over labels can know that ``co.uk`` is a suffix while
``bbc.uk`` would not be. The naive "keep the last two labels" rule reduces
``bbc.co.uk`` to ``co.uk`` -- a public suffix presented as a publisher, which would
merge every British site into one source.

ZERO NETWORK. The list is a vendored, dated snapshot (``data/public_suffix_list.dat``)
verified against ``PUBLIC_SUFFIX_LIST_SHA256`` before it is parsed. Nothing here ever
opens a socket; the refresh is an operator step recorded in the external-artifact
registry.

IT DEGRADES, IT NEVER GUESSES. If the snapshot is missing, unreadable or fails its
digest, every lookup returns ``None`` and ``list_status()`` says why. It does NOT
fall back to a two-label heuristic: a wrong eTLD+1 does not read as an error, it
reads as a publisher, and merging two publishers is exactly the damage the ruling
forbids ("NEVER fuzzy-merge -- bbc is not nbc").

ICANN vs PRIVATE IS THE CALLER'S CHOICE, NOT A DEFAULT WE HIDE. The list has two
sections. ICANN rules are the real registry suffixes (``co.uk``); PRIVATE rules are
hosting platforms that behave like suffixes for their tenants (``github.io``,
``blogspot.com``), so ``someone.github.io`` is one publisher under the private rules
and merely a subdomain of GitHub without them. Both readings are legitimate and they
answer different questions, so ``include_private`` is an explicit argument at every
entry point rather than a silent default -- the two-surfaces-disagreeing defect the
ledger records happens exactly where one of two defensible rules is picked quietly.

MEASURED, 2026-09-07, and worth keeping because it decides a design elsewhere: the
newsletter platforms the ruling names -- substack.com, beehiiv.com, ghost.io,
mailchimp, buttondown.email, convertkit/kit.com, medium.com -- are in NEITHER
section of the list. So the PSL alone reduces ``someones-letter.substack.com`` to
``substack.com`` and collapses every Substack publisher into one source, which is
precisely what the ruling's platform-inversion clause forbids. That clause is
therefore load-bearing rather than a restatement of the list, and the inversion
lives in ``src/ingest/newsletter_source.py`` as an explicit, dated, curated set.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path

# The vintage of the vendored snapshot (the external-artifact registry pins this
# constant; tests/test_external_freshness.py fails if it is not registered).
PUBLIC_SUFFIX_LIST_AS_OF = "2026-09-07"

# The exact bytes we vendored. Verified before the file is parsed, so a truncated
# download or an edited list is a loud refusal rather than a quietly wrong suffix.
PUBLIC_SUFFIX_LIST_SHA256 = "ad47cebef5f86eb77e2c9514d42cde4bd07f591a1f93384a63568624ec3f1f37"

# Where the bytes came from, stated exactly. The list's own header asks that it be
# pulled "only from https://publicsuffix.org/list/public_suffix_list.dat, rather than
# any other VCS sites"; that host is not reachable from the build sandbox
# (CONNECT refused), so this snapshot was taken from the project's OWN upstream
# repository at the commit below. That is a real deviation from the publisher's
# stated preference and it is recorded here rather than glossed: an operator with
# clearnet should refresh from the canonical URL, which the registry's `refresh`
# step names.
PUBLIC_SUFFIX_LIST_UPSTREAM = "https://github.com/publicsuffix/list @ 24fdb5107983c3997144ca19e0d7e1e8fc714f03"

_LIST_PATH = Path(__file__).resolve().parent / "data" / "public_suffix_list.dat"

_ICANN_BEGIN = "===BEGIN ICANN DOMAINS==="
_ICANN_END = "===END ICANN DOMAINS==="
_PRIVATE_BEGIN = "===BEGIN PRIVATE DOMAINS==="
_PRIVATE_END = "===END PRIVATE DOMAINS==="


@dataclass(frozen=True)
class _Rules:
    """Parsed rules, split by section. Sets, because the lookup is by suffix."""

    icann: frozenset[str]
    private: frozenset[str]
    icann_exceptions: frozenset[str]
    private_exceptions: frozenset[str]
    available: bool
    reason: str


_LOCK = threading.Lock()
_CACHE: _Rules | None = None


def _to_ace(rule: str) -> str | None:
    """The punycode (IDNA A-label) form of a rule that carries non-ASCII labels.

    The list stores internationalised rules in UNICODE (``公司.cn``) while hosts
    reach us in either form — an email's From domain is very often already
    punycode. Registering BOTH forms at parse time is what makes the two agree,
    and it is safer than transcoding the INPUT: a host we cannot encode would then
    have no suffix at all, where here an unencodable rule simply keeps its unicode
    form and nothing is lost. Returns ``None`` when the rule is already ASCII or
    cannot be encoded.
    """
    if rule.isascii():
        return None
    out: list[str] = []
    for label in rule.split("."):
        if label in ("*", "") or label.isascii():
            out.append(label)
            continue
        try:
            out.append(label.encode("idna").decode("ascii"))
        except (UnicodeError, ValueError):
            return None
    ace = ".".join(out)
    return ace if ace != rule else None


def _parse(text: str) -> tuple[set[str], set[str], set[str], set[str]]:
    """Split the list into (icann, private, icann-exceptions, private-exceptions).

    Wildcard rules keep their ``*`` label; exception rules are stored WITHOUT the
    leading ``!`` in their own set, because the algorithm needs to know a rule is an
    exception rather than merely that it exists.
    """
    icann: set[str] = set()
    private: set[str] = set()
    icann_x: set[str] = set()
    private_x: set[str] = set()
    section: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("//"):
            if _ICANN_BEGIN in line:
                section = "icann"
            elif _PRIVATE_BEGIN in line:
                section = "private"
            elif _ICANN_END in line or _PRIVATE_END in line:
                section = None
            continue
        if not line:
            continue
        # A rule ends at the first whitespace (the list has no inline comments today,
        # but the spec allows trailing content and a stray tab must not become a label).
        rule = line.split()[0].lower().rstrip(".")
        if not rule:
            continue
        if rule.startswith("!"):
            target_x = icann_x if section == "icann" else private_x
            target_x.add(rule[1:])
            ace = _to_ace(rule[1:])
            if ace:
                target_x.add(ace)
        else:
            target = icann if section == "icann" else private
            target.add(rule)
            ace = _to_ace(rule)
            if ace:
                target.add(ace)
    return icann, private, icann_x, private_x


def _load() -> _Rules:
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        try:
            data = _LIST_PATH.read_bytes()
        except OSError as exc:
            _CACHE = _Rules(
                frozenset(), frozenset(), frozenset(), frozenset(), False,
                f"the vendored Public Suffix List could not be read: {exc}",
            )
            return _CACHE
        digest = hashlib.sha256(data).hexdigest()
        if digest != PUBLIC_SUFFIX_LIST_SHA256:
            _CACHE = _Rules(
                frozenset(), frozenset(), frozenset(), frozenset(), False,
                "the vendored Public Suffix List does not match its recorded digest "
                f"(expected {PUBLIC_SUFFIX_LIST_SHA256[:12]}…, read {digest[:12]}…) — "
                "refusing to parse it rather than deriving publishers from unknown bytes",
            )
            return _CACHE
        icann, private, icann_x, private_x = _parse(data.decode("utf-8"))
        if not icann:
            _CACHE = _Rules(
                frozenset(), frozenset(), frozenset(), frozenset(), False,
                "the vendored Public Suffix List parsed to zero ICANN rules",
            )
            return _CACHE
        _CACHE = _Rules(
            frozenset(icann), frozenset(private), frozenset(icann_x),
            frozenset(private_x), True, "",
        )
        return _CACHE


def _reset_cache_for_tests() -> None:
    """Drop the parsed list so a test can drive the degrade path."""
    global _CACHE
    with _LOCK:
        _CACHE = None


def list_status() -> dict:
    """Whether the list is usable, and — when it is not — WHY.

    ``available: False`` is a real answer with a reason, never an empty result that
    reads like "this host has no registrable domain".
    """
    r = _load()
    return {
        "available": r.available,
        "reason": r.reason or None,
        "as_of": PUBLIC_SUFFIX_LIST_AS_OF,
        "upstream": PUBLIC_SUFFIX_LIST_UPSTREAM,
        "icann_rules": len(r.icann),
        "private_rules": len(r.private),
        "method": (
            "offline Public Suffix List snapshot, digest-verified before parsing; "
            "no network call at any point"
        ),
    }


def _clean_host(host: str | None) -> str | None:
    """A bare, lowercase host: no scheme, userinfo, port, path or trailing dot."""
    if not host:
        return None
    h = host.strip().lower()
    if "//" in h:
        h = h.split("//", 1)[1]
    h = h.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    h = h.split("@")[-1]
    if h.startswith("[") and "]" in h:  # IPv6 literal — never has a public suffix
        return None
    # A LEADING dot is not a fully-qualified name, it is a malformed one, and the
    # canonical vectors say so (".example.com" -> null). Stripping it instead would
    # silently accept a broken input and answer with a publisher.
    if h.startswith("."):
        return None
    h = h.split(":")[0].rstrip(".")
    if not h or " " in h or ".." in h:
        return None
    # A bare IPv4 literal is not a domain; returning "1.2" for "192.168.1.2" would be
    # a fabricated publisher.
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return None
    if any(not p for p in parts):
        return None
    return h


def public_suffix(host: str | None, *, include_private: bool) -> str | None:
    """The public suffix of ``host`` per the list's own matching algorithm.

    Returns ``None`` when the list is unavailable or the input is not a domain.
    Implements the four steps published at publicsuffix.org: match every rule from
    the right (``*`` matches one label), prefer an exception rule, otherwise the
    longest match, and fall back to the implicit ``*`` rule (the rightmost label).
    """
    h = _clean_host(host)
    if h is None:
        return None
    r = _load()
    if not r.available:
        return None
    rules = r.icann | r.private if include_private else r.icann
    exceptions = r.icann_exceptions | r.private_exceptions if include_private else r.icann_exceptions

    labels = h.split(".")
    # An exception rule wins outright; its suffix is the rule MINUS its first label.
    for i in range(len(labels)):
        candidate = ".".join(labels[i:])
        if candidate in exceptions:
            return ".".join(candidate.split(".")[1:]) or None

    best: str | None = None
    for i in range(len(labels)):
        tail = labels[i:]
        candidate = ".".join(tail)
        wildcard = ".".join(["*", *tail[1:]]) if len(tail) > 1 else None
        matched = candidate if candidate in rules else (
            candidate if wildcard and wildcard in rules else None
        )
        if matched is not None and (best is None or len(matched.split(".")) > len(best.split("."))):
            best = matched
    if best is None:
        # Step 4: no rule matched, so the prevailing rule is "*" — the last label.
        return labels[-1]
    return best


def registrable_domain_psl(host: str | None, *, include_private: bool) -> str | None:
    """The eTLD+1 of ``host``: its public suffix plus one more label.

    ``None`` when the list is unavailable, the input is not a domain, or the host
    IS a public suffix with nothing in front of it (``co.uk`` names no registrant,
    and answering ``co.uk`` there would present a suffix as a publisher).
    """
    h = _clean_host(host)
    if h is None:
        return None
    suffix = public_suffix(h, include_private=include_private)
    if suffix is None:
        return None
    if h == suffix:
        return None
    suffix_len = len(suffix.split("."))
    labels = h.split(".")
    if len(labels) <= suffix_len:
        return None
    return ".".join(labels[-(suffix_len + 1):])
