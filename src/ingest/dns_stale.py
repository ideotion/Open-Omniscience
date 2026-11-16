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

_LOCK = threading.Lock()
_ANSWERS: OrderedDict[tuple[Any, ...], tuple[float, list[Any]]] = OrderedDict()
_SERVED: dict[str, int] = {}


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
    if not enabled() or not applies_to(host) or not infos:
        return
    try:
        key = _key(str(host), args, kwargs)
        hash(key)
    except TypeError:
        return
    at = time.monotonic() if now is None else now
    with _LOCK:
        _ANSWERS[key] = (at, list(infos))
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
        received, infos = hit
        if at - received > MAX_AGE_SECONDS:
            del _ANSWERS[key]
            return None
        name = key[0]
        first = name not in _SERVED
        _SERVED[name] = _SERVED.get(name, 0) + 1
    _LOG.log(
        logging.INFO if first else logging.DEBUG,
        "the resolver could not answer for %s just now; using its answer from %.0f s ago",
        name,
        at - received,
    )
    return list(infos)


def status() -> dict[str, Any]:
    """How often a remembered answer was handed back, per name, since this process started."""
    with _LOCK:
        return {"enabled": enabled(), "max_age_seconds": MAX_AGE_SECONDS, "served": dict(_SERVED), "remembered": len(_ANSWERS)}


def clear() -> None:
    """Forget everything (tests, and a network change an operator wants followed at once)."""
    with _LOCK:
        _ANSWERS.clear()
        _SERVED.clear()
