"""A short-lived memory of good DNS answers, served ONLY when the resolver fails for a moment.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field test 2026-11-14 (P10 / R15, row 72): on a machine whose name service comes and goes
(a Qubes net VM is the recorded case), every Wikipedia call made in a resolver blip failed
with "Temporary failure in name resolution", although the same name had resolved a minute
earlier and would again a minute later. This keeps the last good answer for a few Wikimedia
names and hands it back for exactly that failure.

WHAT IT IS NOT. It is not a cache in front of the resolver: every lookup still asks the
resolver first, and a fresh answer always wins. It answers only ``EAI_AGAIN`` (the resolver
could not answer NOW); a name that does not exist (``EAI_NONAME``) or any other failure
raises as before. It never answers in airplane mode, because the airplane refusal runs
before any lookup. And it sits BEHIND the SSRF guard, never in front of it: a remembered
answer goes through ``check_resolution`` exactly as a fresh one does, and the connection is
then checked at connect time (``check_connect_target``) on the address actually used.

TWO MORE LIMITS, from the two security reads (2026-11-16). Only an answer whose every address
is PUBLIC is kept, so the memory can never replay an internal address anywhere, a stood-down
scope included. And an answer is handed back only on the SAME NETWORK it was received on (the
set of this machine's own interface addresses, read from the kernel's tables, never a network
call), and the memory is emptied whenever airplane mode engages: ``EAI_AGAIN`` is also what a
resolver's SERVFAIL or REFUSED becomes, so a network that blocks these names by DNS must not
be ridden over with an answer from another network. On the same network such a block is
ridden over for at most :data:`MAX_AGE_SECONDS` after the last good answer, and then honoured.

Memory only, never disk; bounded; a few names; ``OO_DNS_STALE=0`` turns it off.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

_LOG = logging.getLogger(__name__)

#: How long a good answer may be handed back after it was received, in seconds. Short on
#: purpose: long enough to ride out a resolver blip, short enough that a moved service is
#: followed within minutes once the resolver answers again.
MAX_AGE_SECONDS: float = 600.0

#: How many distinct lookups are remembered. A handful of Wikimedia names times a few
#: call shapes; the bound only stops a pathological caller growing it.
MAX_ENTRIES: int = 64

#: The names this applies to: the Wikimedia family the Wikipedia lane talks to
#: (``src.wiki.client.WIKI_SESSION_HOSTS`` plus Wikidata). A suffix matches the name itself
#: or any subdomain of it.
SUFFIXES: tuple[str, ...] = ("wikipedia.org", "wikimedia.org", "wikidata.org")

#: How long a reading of this machine's own interface addresses is reused, in seconds.
NETWORK_READ_SECONDS: float = 5.0

_LOCK = threading.Lock()
_ANSWERS: OrderedDict[tuple[Any, ...], tuple[float, list[Any], frozenset[str] | None]] = OrderedDict()
_SERVED: dict[str, int] = {}
_NETWORK: list[Any] = [None, -1e18]  # [the last reading, when it was taken]


def _read_network() -> frozenset[str] | None:
    """This machine's own non-loopback, non-link-local interface addresses, or ``None``.

    The kernel's interface tables through psutil, the reading the network consent popup uses;
    never a network call. ``None`` (psutil absent or failing) means "network unknown", and an
    unknown network never matches, so nothing is handed back.
    """
    try:
        import psutil

        out = set()
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if getattr(getattr(a, "family", None), "name", "") not in ("AF_INET", "AF_INET6"):
                    continue  # a hardware (link-layer) address names a card, not a network
                ip = str(getattr(a, "address", "") or "").split("%")[0]
                if not ip or ip.startswith(("127.", "169.254.", "fe80")) or ip == "::1":
                    continue
                out.add(ip)
        return frozenset(out)
    except Exception:  # noqa: BLE001 - an unreadable network is an unknown one, which never matches
        return None


def _network(now: float) -> frozenset[str] | None:
    with _LOCK:
        reading, at = _NETWORK
        if now - at <= NETWORK_READ_SECONDS:
            return reading
    reading = _read_network()
    with _LOCK:
        _NETWORK[0], _NETWORK[1] = reading, now
    return reading


def _all_public(infos: Any) -> bool:
    from src.ingest.ssrf_guard import _as_ip, is_blocked_ip

    seen = False
    for info in infos:
        try:
            ip = _as_ip(info[4][0])
        except (IndexError, TypeError):
            return False
        if ip is None or is_blocked_ip(ip):
            return False
        seen = True
    return seen


def enabled() -> bool:
    return os.getenv("OO_DNS_STALE", "1") != "0"


def applies_to(host: object) -> bool:
    """Whether ``host`` is one of the names this memory serves."""
    if not isinstance(host, str) or not host:
        return False
    name = host.strip().rstrip(".").lower()
    return any(name == s or name.endswith("." + s) for s in SUFFIXES)


def _key(host: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, ...]:
    return (host.strip().rstrip(".").lower(), args, tuple(sorted(kwargs.items())))


def remember(host: object, args: tuple[Any, ...], kwargs: dict[str, Any], infos: Any, *, now: float | None = None) -> None:
    """Keep a good answer for ``host``. Never raises; an unhashable call shape is skipped."""
    if not enabled() or not applies_to(host) or not infos or not _all_public(infos):
        return
    try:
        key = _key(str(host), args, kwargs)
        hash(key)
    except TypeError:
        return
    at = time.monotonic() if now is None else now
    network = _network(at)
    with _LOCK:
        _ANSWERS[key] = (at, list(infos), network)
        _ANSWERS.move_to_end(key)
        while len(_ANSWERS) > MAX_ENTRIES:
            _ANSWERS.popitem(last=False)


def recall(
    host: object, args: tuple[Any, ...], kwargs: dict[str, Any], *, temporary: bool, now: float | None = None
) -> list[Any] | None:
    """The remembered answer for a lookup that just failed, or ``None``.

    ``temporary`` is the caller's reading of the failure: ``True`` only for ``EAI_AGAIN``. This
    module takes no socket import (tests/test_network_consent.py's ratchet), so the caller,
    which already holds the socket module, tells it.

    ``None`` means "raise the resolver's own error": the failure was not temporary, the
    name is not one of :data:`SUFFIXES`, nothing good is remembered, or it is older than
    :data:`MAX_AGE_SECONDS`.
    """
    if not enabled() or not temporary or not applies_to(host):
        return None
    try:
        key = _key(str(host), args, kwargs)
        hash(key)
    except TypeError:
        return None
    at = time.monotonic() if now is None else now
    with _LOCK:
        hit = _ANSWERS.get(key)
    if hit is None:
        return None
    received, infos, network = hit
    if at - received > MAX_AGE_SECONDS:
        with _LOCK:
            _ANSWERS.pop(key, None)
        return None
    current = _network(at)
    if network is None or current is None or current != network:
        # Another network (or an unknown one): its resolver's failure may be its policy.
        return None
    name = key[0]
    with _LOCK:
        first = name not in _SERVED
        if first and len(_SERVED) >= MAX_ENTRIES:
            _SERVED.clear()
        _SERVED[name] = _SERVED.get(name, 0) + 1
    _LOG.log(
        logging.INFO if first else logging.DEBUG,
        "the resolver could not answer for %s just now; using its answer from %.0f s ago",
        name,
        at - received,
    )
    return list(infos)


def status() -> dict[str, Any]:
    """How often a remembered answer was handed back (before the SSRF check, which may still
    refuse it), per name, since this process started or was last emptied."""
    with _LOCK:
        return {"enabled": enabled(), "max_age_seconds": MAX_AGE_SECONDS, "served": dict(_SERVED), "remembered": len(_ANSWERS)}


def clear() -> None:
    """Forget everything. Called when airplane mode engages, and by tests."""
    with _LOCK:
        _ANSWERS.clear()
        _SERVED.clear()
        _NETWORK[0], _NETWORK[1] = None, -1e18
