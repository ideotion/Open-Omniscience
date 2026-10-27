"""Refuse the requests another site's page makes to a GET that does work (the Origin middleware only covers state-changing methods).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from fastapi import HTTPException, Request


def refuse_cross_site_get(request: Request) -> None:
    """403 unless this GET comes from the app's own page or from a caller that is not a browser.

    A browser cannot be stopped from sending a GET to a loopback address (an ``<img src>`` or a no-cors ``fetch`` from any page the
    person visits), and the Origin middleware looks only at state-changing methods. The response stays unreadable to that page, so
    what this protects is what the GET DOES: heavy compute, a live outbound request, a signing key minted. Every check must pass:

    * ``Host``: one of the names the app's DNS-rebinding guard serves (loopback names, the test client's, ``OO_ALLOWED_HOSTS``).
    * ``Sec-Fetch-Site`` when sent: ``same-origin`` and ``none`` (a typed address or a bookmark) pass; ``same-site`` and
      ``cross-site`` do not.
    * ``Origin``, else ``Referer``, when sent: judged by the POST middleware's own ``_foreign_origin`` (scheme-default ports
      normalised, so ``Host: oo.lan:443`` with ``Origin: https://oo.lan`` is the same server; the hostname must be one the app
      serves; ``Origin: null`` is refused).
    * None sent: a command line, a script, or a navigation from the app's own page (``Referrer-Policy: no-referrer``). Allowed.

    **The stated limit:** a browser that sends no Fetch Metadata (Firefox before 90, Safari before 16.4, an old webview) and any
    browser asked for a name that is not a potentially trustworthy address send none of the three for a referrer-less
    ``<img>``, so that request is served; the page still cannot read the answer. Same checks as the backup route's own copy
    (``src/api/database.py``), which compares Origin to Host as raw strings and is to be pointed here later.
    """
    from src.api.main import _allowed_hosts, _foreign_origin, _host_without_port

    refusal = HTTPException(
        status_code=403,
        detail="Refused: this request does work on your machine and is served to the app's own page, not to a request from another site or origin.",
    )
    if _host_without_port(request.headers.get("host", "")) not in _allowed_hosts():
        raise refusal
    site = request.headers.get("sec-fetch-site")
    if site is not None and site.strip().lower() not in ("same-origin", "none"):
        raise refusal
    sent = request.headers.get("origin")
    if sent is None:
        sent = request.headers.get("referer")
    if sent is None:
        return
    if _foreign_origin(request, sent):
        raise refusal
