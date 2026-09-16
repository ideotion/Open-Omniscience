"""S04-13 S3 (Q1148 = a): the loopback UI call gets 1,000/hour, anything else keeps 100.

    "Raise it for loopback UI calls (1,000/hour), keep 100 for anything else."

RC15 came back BLANK, so register L4's "adapt the rate limit to what's most
ethical while keeping the app's efficiency and performance in mind" is read as THIS
guard (the app's own loopback limiter) rather than as the per-host egress politeness
-- an ASSUMPTION, recorded as one, and reversible by writing a letter at `ANSWER
RC15`. Q1013's egress politeness is untouched by anything here.

WHY IT IS NOT A LUXURY: the 2026-07-22 GUI run produced 384 console lines that were
100% rate-limit refusals under 14 concurrent agents. A local-first app whose only
caller is the operator's own browser was spending its guard on the operator.

TWO DIFFERENT CLAIMS, TWO DIFFERENT TESTS, because the recorded helper-versus-wiring
lesson says neither substitutes for the other:

  * the MECHANISM -- a loopback caller really is allowed past 100 -- driven on a
    FRESH limiter, so 101 real requests cannot consume the shared limiter's bucket
    for 127.0.0.1 and poison every later test that drives an endpoint;
  * the WIRING -- the app's one shared ``limiter`` is that kind of limiter, so all
    66 existing ``@limiter.limit`` decorators inherit it.
"""

from __future__ import annotations

import inspect

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.api.ratelimit import (
    LOOPBACK_FACTOR,
    _LoopbackAwareLimiter,
    _raised,
    is_loopback,
    limiter,
)


def _app(client_host: str) -> TestClient:
    """A minimal app on its OWN limiter, answering from ``client_host``."""
    app = FastAPI()
    own = _LoopbackAwareLimiter(key_func=lambda request: client_host)
    app.state.limiter = own
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/thing")
    @own.limit("100/hour")
    def thing(request: Request):
        return {"ok": True}

    return TestClient(app)


# --------------------------------------------------------------------------- #
# The mechanism
# --------------------------------------------------------------------------- #


def test_a_loopback_caller_is_not_refused_at_101_calls():
    """The acceptance bar, driven rather than reasoned about."""
    client = _app("127.0.0.1")
    codes = [client.get("/thing").status_code for _ in range(101)]
    assert set(codes) == {200}, (
        f"a loopback caller was refused within 101 calls: "
        f"{codes.count(429)} of 101 came back 429"
    )


def test_a_non_loopback_caller_still_gets_a_hundred():
    """The other half. A raise that applied to everyone would not be a loopback
    raise, and this is the assertion that tells the two apart."""
    client = _app("203.0.113.9")
    codes = [client.get("/thing").status_code for _ in range(101)]
    assert 200 in codes and 429 in codes, "the declared 100/hour must still bind"
    assert codes.index(429) == 100, (
        f"the non-loopback ceiling moved: first refusal at call {codes.index(429) + 1}"
    )


def test_the_window_the_429_reports_is_the_limit_that_actually_applied():
    """The handler's honesty, at its source.

    ``src/api/main.py`` builds its ``Retry-After`` from
    ``request.state.view_rate_limit`` -- the limit slowapi stamps immediately before
    raising -- rather than from a second copy of the number. So the check that
    matters is that the EVALUATED limit is the raised one for a loopback caller: if
    the raise were applied only at admission and not recorded, a loopback 429 would
    describe a 100/hour window the caller was never held to.

    (The real app's richer handler is driven against the real app elsewhere; this
    minimal app mounts slowapi's default handler, which deliberately sets no
    Retry-After -- the very gap main.py's own comment documents.)
    """
    seen: list[str] = []

    app = FastAPI()
    own = _LoopbackAwareLimiter(key_func=lambda request: "127.0.0.1")
    app.state.limiter = own
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _handler(request: Request, exc: RateLimitExceeded):
        view = getattr(request.state, "view_rate_limit", None)
        # ``view_rate_limit[0]`` IS the RateLimitItem slowapi stamped -- the same
        # object main.py hands to ``get_window_stats``. Not a wrapper with a
        # ``.limit``; checked against the live object rather than assumed.
        seen.append(str(view[0]) if view else "")
        return _rate_limit_exceeded_handler(request, exc)

    @app.get("/thing")
    @own.limit("2/hour")
    def thing(request: Request):
        return {"ok": True}

    client = TestClient(app)
    codes = [client.get("/thing").status_code for _ in range(25)]
    assert 429 in codes, "a 2/hour route raised to 20/hour must still refuse at 21"
    assert codes.index(429) == 20, (
        f"the raised ceiling was not what bound: first refusal at {codes.index(429) + 1}"
    )
    assert seen and "20 per 1 hour" in seen[0], (
        f"the 429 reported the window of {seen[0]!r}; the caller was actually held "
        "to the raised limit, so that is the window it is owed"
    )


# --------------------------------------------------------------------------- #
# What decides "loopback"
# --------------------------------------------------------------------------- #


def test_loopback_recognises_the_real_spellings_and_refuses_everything_else():
    for yes in ("127.0.0.1", "127.0.0.5", "::1", "[::1]", "localhost", "::1%lo0"):
        assert is_loopback(yes) is True, yes
    for no in ("10.0.0.5", "192.168.1.4", "203.0.113.9", "", None, "not-an-address"):
        assert is_loopback(no) is False, no


def test_an_unreadable_address_does_not_get_the_raise():
    """The safe direction: an address we cannot parse is not one we can vouch for."""
    assert _raised("100/hour")("garbage") == "100/hour"


def test_the_raise_scales_rather_than_flattening_every_route_to_one_number():
    """The decorators are not all "100/hour" -- there are 50, 300 and 10/hour
    variants, and those differences are a deliberate statement about how expensive
    each endpoint is. Substituting a constant would erase that."""
    assert _raised("100/hour")("127.0.0.1") == f"{100 * LOOPBACK_FACTOR}/hour"
    assert _raised("50/hour")("127.0.0.1") == f"{50 * LOOPBACK_FACTOR}/hour"
    assert _raised("10/hour")("127.0.0.1") == f"{10 * LOOPBACK_FACTOR}/hour"
    assert _raised("300/hour")("203.0.113.9") == "300/hour"


def test_an_unparseable_declaration_is_left_exactly_as_written():
    """Substituting a default would silently re-limit a route at a number nobody
    chose -- worse than leaving a malformed declaration to fail loudly at parse."""
    assert _raised("nonsense")("127.0.0.1") == "nonsense"


def test_the_provider_parameter_is_named_key_because_slowapi_dispatches_on_that():
    """The mechanism hangs on this name.

    ``LimitGroup.__iter__`` passes the key function's answer in ONLY when the
    provider declares a parameter called ``key``; with any other name it calls the
    provider with no arguments, every caller gets the same limit, and the whole
    raise silently disappears while every other test here still passes.
    """
    assert list(inspect.signature(_raised("100/hour")).parameters) == ["key"]


# --------------------------------------------------------------------------- #
# The wiring
# --------------------------------------------------------------------------- #


def test_the_one_shared_limiter_is_the_loopback_aware_one():
    """All 66 ``@limiter.limit`` decorators inherit the raise through this, and so
    does one added tomorrow -- which is the point of overriding ``limit`` once
    instead of editing 66 call sites (an enumeration always leaves one behind)."""
    assert isinstance(limiter, _LoopbackAwareLimiter)


def test_the_app_attaches_that_same_instance():
    """Read from the wiring source rather than the mutable app singleton: the
    recorded rule is never to assert a POSITIVE fact against ``app.routes`` or
    process-global app state, which other tests mutate."""
    import pathlib

    src = pathlib.Path("src/api/main.py").read_text("utf-8")
    assert "from src.api.ratelimit import limiter" in src
    assert "app.state.limiter = limiter" in src


def test_every_api_module_imports_the_shared_limiter_not_its_own():
    """A router that built its own ``Limiter`` would bypass both the middleware and
    this raise -- the defect ``ratelimit.py`` was created to fix, which no behavioural
    test can see because a private limiter's decorators simply do nothing."""
    import pathlib

    offenders = []
    for path in sorted(pathlib.Path("src/api").rglob("*.py")):
        text = path.read_text("utf-8")
        if "Limiter(" in text and path.name != "ratelimit.py":
            offenders.append(str(path))
    assert not offenders, f"these build their own Limiter: {offenders}"
