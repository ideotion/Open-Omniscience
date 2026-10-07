"""What the diagnostics may say about a request: its route's TEMPLATE and a standard method, never the raw path (2026-10-07).

A path is typed by whoever calls: a passphrase typed into the address bar is a path, and a locked app holds no key to scrub
it with. So the journals the debug bundle carries (the error journal's HTTP entries, the latency log's routes and its
in-flight list, the pool's endpoint) name a request by the template of the route that served it (``/api/articles/{id}/view``),
which the code wrote and the caller did not, or by a fixed label where no route did (an unmatched path, a request a middleware
answered before routing). The method is written only when it is one of the standard ones, for the same reason: an HTTP method
is any token the client sends. Stdlib only.
"""

from __future__ import annotations

from typing import Any

#: The methods a route can answer; any other token is the client's own.
STANDARD_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"})
#: Where no route served the request (an unmatched path, a middleware's early answer, a request still being routed).
UNMATCHED_ROUTE = "(no route matched)"
#: A method that is not one of the standard ones.
OTHER_METHOD = "(other method)"
#: What an older journal line's path is replaced by when it is read (the line was written before only templates were).
PATH_WITHHELD = "(path withheld: written before only route templates were recorded)"


def safe_method(method: object) -> str:
    """``method`` when it is a standard one, else :data:`OTHER_METHOD`."""
    return method if isinstance(method, str) and method in STANDARD_METHODS else OTHER_METHOD


def route_template(scope: Any) -> str | None:
    """The template of the route routing put in the ASGI ``scope``, or ``None`` while there is none. Never raises."""
    try:
        template = getattr(scope.get("route"), "path", None)
        if not (isinstance(template, str) and template):
            template = _mount_path(scope)
    except Exception:  # noqa: BLE001 - an instrument must never break a request
        return None
    return template if isinstance(template, str) and template else None


def _mount_path(scope: Any) -> str | None:
    """The path of the ``Mount`` that is serving the request, when routing put no route in the scope (Starlette's ``Mount`` never
    sets ``scope["route"]``: it sets ``scope["endpoint"]`` to the mounted app). Found as the mount of the app's own routes whose
    ``.app`` is that endpoint, so what is named is the prefix the code mounted (``/static``, ``/metrics``) and never the rest of the
    path the caller typed under it."""
    endpoint = scope.get("endpoint")
    if endpoint is None:
        return None
    routes = getattr(scope.get("app"), "routes", None) or []
    for route in routes:
        if getattr(route, "app", None) is endpoint and isinstance(getattr(route, "path", None), str):
            return route.path
    return None


#: The one place a log line names a request: the route (never the path) and a standard method.
def request_phrase(method: object, scope: Any) -> str:
    """``route GET /api/x/{id}``: how a log line of this app names the request it is about (the word ``route`` is what tells a
    line written by this wording from one written before it, whose path is the client's)."""
    return f"route {safe_method(method)} {safe_route(scope)}"


def safe_route(scope: Any) -> str:
    """The route template of the request, or :data:`UNMATCHED_ROUTE`."""
    return route_template(scope) or UNMATCHED_ROUTE
