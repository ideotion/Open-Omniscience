"""
Single shared rate limiter.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

SlowAPIMiddleware enforces limits registered on ``app.state.limiter``. Previously
each router built its OWN ``Limiter`` instance, so the ``@limiter.limit`` decorators
on router endpoints registered on instances the middleware never saw -- i.e. they
did nothing. Everything now imports this one instance, which main.py attaches to
the app, so the decorators are actually enforced.

THE LOOPBACK RAISE (S04-13 S3; RULED 2026-09-15, answer sheet Q1148 = a, with
RC15 left blank so register L4's "adapt the rate limit to what's most ethical" is
read as THIS guard rather than as the per-host egress politeness):

    "Raise it for loopback UI calls (1,000/hour), keep 100 for anything else."

WHAT IT FIXES. The app is a LOCAL-FIRST, loopback-only tool: the only caller of
``GET /api/articles`` in ordinary use is the operator's own browser, on this
machine, and a person clicking around a data-dense UI trips 100/hour easily. The
2026-07-22 GUI run measured **384 console lines that were 100% rate-limit
refusals** under 14 concurrent agents -- the guard firing on its own user. A rate
limit that mostly refuses the person it is protecting is not protecting anyone.

HOW, and why it is not 66 edits. The raise rides the ONE ``Limiter``'s key
function, exactly as the ruling frames it: slowapi accepts a CALLABLE limit
provider, and when that callable declares a parameter named ``key`` it is invoked
as ``provider(key_func(request))`` (``slowapi.extension.LimitGroup.__iter__``).
``key_func`` here is ``get_remote_address``, so the provider is handed the
caller's own address and decides the ceiling from it. ``limit()`` is overridden
once, so all 66 existing ``@limiter.limit("100/hour")`` decorators across
``src/api/*.py`` inherit the behaviour with no per-decorator edit -- and, more
importantly, so a decorator ADDED LATER cannot forget it. An enumeration of 66
call sites is the recorded shape that leaves one behind.

WHAT "ANYTHING ELSE" MEANS, stated rather than assumed (the brief's §6 asks for
exactly this). The server binds loopback, so a non-loopback client address can
only arise when an operator has deliberately widened it: ``OO_HOST`` set to a
routable interface, a port-forward, or a reverse proxy / hidden service in front.
Those callers are not the local UI and keep 100/hour.

THE LIMIT OF THAT, which is real and is not papered over: ``get_remote_address``
reads ``request.client.host`` and deliberately does NOT trust ``X-Forwarded-For``
(trusting a header any client can set would let anyone claim the raise). So a
reverse proxy running ON THIS MACHINE presents as loopback, and every caller it
forwards inherits the 1,000/hour ceiling. That is a consequence of refusing to
trust a spoofable header, it is the safer of the two failure modes for a
local-first app, and it is written down here rather than left for someone to
discover. An operator fronting this app with a same-box proxy should not treat
these limits as an access control -- they never were one.

THE 429 STAYS HONEST BY CONSTRUCTION. ``main.py``'s handler reads the window off
the limit that ACTUALLY failed (``request.state.view_rate_limit``), so it reports
the real window of whichever ceiling applied, with no second copy of these numbers
to drift.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from typing import Any

from slowapi import Limiter
from slowapi.util import get_remote_address

#: The ceiling for a call from this machine's own UI.
LOOPBACK_LIMIT = "1000/hour"

#: The multiplier the raise applies to any other declared limit. The ruling names
#: the pair 1,000 / 100, i.e. ten times, and the decorators are not all "100/hour"
#: (there are "50/hour", "300/hour" and "10/hour" variants): scaling keeps their
#: RELATIVE ordering -- which is a deliberate statement about how expensive each
#: endpoint is -- instead of flattening every route onto one number, which is what
#: substituting a constant would do.
LOOPBACK_FACTOR = 10


def is_loopback(address: str | None) -> bool:
    """Is this client address this machine talking to itself?

    Accepts the textual address the key function produced. Anything unparseable is
    NOT loopback: an address we cannot read is not one we can vouch for, and the
    safe direction for a raise is to withhold it.
    """
    if not address:
        return False
    host = address.strip()
    if host == "localhost":
        return True
    # A bracketed or zone-suffixed IPv6 literal reaches here from some servers.
    host = host.strip("[]").split("%", 1)[0]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _raised(limit_value: str) -> Callable[[str], str]:
    """Wrap a declared limit string in a provider that raises it for loopback.

    The parameter MUST be named ``key``: that name is what makes slowapi pass the
    key function's answer in rather than calling the provider with no arguments
    (``LimitGroup.__iter__``). Renaming it would silently return the same limit for
    every caller -- a change that looks cosmetic and disables the whole mechanism,
    which is why a test pins the parameter name.
    """

    def provider(key: str) -> str:
        if not is_loopback(key):
            return limit_value
        try:
            count, _, window = limit_value.partition("/")
            return f"{int(count.strip()) * LOOPBACK_FACTOR}/{window.strip()}"
        except (AttributeError, TypeError, ValueError):
            # An unparseable declaration is left EXACTLY as written. Substituting a
            # default here would silently re-limit a route at a number nobody chose.
            return limit_value

    return provider


class _LoopbackAwareLimiter(Limiter):
    """The one Limiter, with the loopback raise applied to every decorator."""

    def limit(self, limit_value: Any, *args: Any, **kwargs: Any) -> Callable:
        # A caller that already passes its own callable has made a deliberate
        # per-route decision; it is handed straight through rather than wrapped,
        # because wrapping it would override a choice made closer to the route.
        if isinstance(limit_value, str):
            limit_value = _raised(limit_value)
        return super().limit(limit_value, *args, **kwargs)


limiter = _LoopbackAwareLimiter(key_func=get_remote_address)
