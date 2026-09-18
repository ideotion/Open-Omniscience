"""Q706's attention signal: the daily top-1,000 per edition, twelve requests a day.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q706 = a: "The daily top-1,000 per edition (12 requests a day) + per-article daily
views for HOT pages." The ruling's own impact line says "one more Wikimedia host",
which is what put :data:`PAGEVIEWS_HOST` in ``docs/SECURITY.md`` and
``src/static/net-hosts.js`` in the same diff as this file (Q1001).

WHAT THE TOP-1,000 IS FOR. Q707 makes the pageview top-1,000 one of the three things
that put a page in the HOT tier, beside "pages the corpus already mentions" and
"tracked pages". It is the only one of the three that can tell this app about a page
it has never heard of, which is why it is worth a request a day per edition — and
why it is capped at exactly that. Q706's option (c), per-article views for every
tracked page, was refused as "millions of requests; not polite", and this module has
no code path that could drift into it: the per-article read takes an explicit list
and the caller is the HOT tier, which is bounded by the budget.

RANK IS NOT A SCORE, AND VIEWS ARE NOT QUALITY. What is stored is the SOURCE's own
ordinal and the SOURCE's own view count, both named as theirs. Nothing here computes
a blend, and no field is called a score — a number saying how many people opened a
page is a measurement of attention, and the moment it is folded with anything else it
becomes a verdict this project does not publish.

NOT REACHED FROM THIS SANDBOX. ``wikimedia.org`` answers ``000`` here (probed
2026-09-17, with ``api.github.com`` answering 200 as the control), so the URL shape
below is carried from the documentation named on :data:`PAGEVIEWS_PATH` and is
confirmed by the operator's own run (gate row V), never by a claim from here.
"""

from __future__ import annotations

from datetime import date
from typing import Any

#: The Analytics REST API's host. One more Wikimedia host, exactly as Q706 says.
PAGEVIEWS_HOST: str = "wikimedia.org"

#: The path shape. From the Wikimedia Analytics REST API as described in the roadmap
#: intake's living-Wikipedia architecture (``docs/design/
#: ROADMAP_INTAKE_2026-09-12_BETA_PATHWAY.md`` §3.7's proposal, Q706's context in the
#: answer sheet). ``{project}`` is an edition's site name (``en.wikipedia``), NOT the
#: database name (``enwiki``) the stream uses — two spellings of one edition, which is
#: why :func:`project_for` is the single place either is built.
PAGEVIEWS_PATH: str = "/api/rest_v1/metrics/pageviews/top/{project}/all-access/{y}/{m:02d}/{d:02d}"

#: How many rows the endpoint returns. Named so a caller never has to infer the cap
#: from the length of a response — an inferred cap silently becomes a reported number
#: the day the service changes it.
TOP_LIMIT: int = 1000


#: Q706's cadence, as a NUMBER rather than as a habit: "the daily top-1,000 per
#: edition (12 requests a day)". One request per edition per calendar day, UTC.
#:
#: WHY UTC AND NOT THE MACHINE'S DAY: the endpoint is per-day and its days are the
#: service's, so two installs in different timezones asking for "yesterday" would ask
#: for different days and then disagree about what the top-1,000 was. The day this app
#: reads is the day the service published.
REQUESTS_PER_EDITION_PER_DAY: int = 1


def due_day(now: Any, *, lag_days: int = 1) -> Any:
    """The day whose top-1,000 is worth asking for, given ``now`` (a UTC datetime).

    ``lag_days=1`` — YESTERDAY, not today. The service aggregates a day after it ends,
    so asking for today's returns nothing and the caller cannot tell that from "nobody
    read anything", which is the pair this module refuses to merge everywhere else.
    Named as a parameter so a caller that knows better can say so, and defaulted to the
    honest value so one that does not cannot get it wrong.
    """
    from datetime import timedelta

    return (now - timedelta(days=lag_days)).date()


def is_due(last_fetched_day: Any, want_day: Any) -> bool:
    """Whether this edition's top-1,000 should be asked for.

    ``None`` for ``last_fetched_day`` means never fetched, which is due. A stored day
    EQUAL to or LATER than the wanted one is not due — later can happen when a clock
    moves backwards, and re-asking then would spend a request to learn nothing.
    """
    if last_fetched_day is None:
        return True
    return last_fetched_day < want_day


def project_for(edition: str) -> str:
    """``en`` -> ``en.wikipedia``. The ONE place the analytics project name is built."""
    if not edition:
        raise ValueError("a pageviews project needs an edition code")
    return f"{edition}.wikipedia"


def top_url(edition: str, day: date) -> str:
    """The full URL for one edition's top-1,000 on one day.

    A DAY, explicitly, because the endpoint is per-day and a caller that passed
    "yesterday" implicitly would produce a different URL depending on the machine's
    timezone — and then two installs would disagree about which day they measured.
    """
    path = PAGEVIEWS_PATH.format(project=project_for(edition), y=day.year, m=day.month, d=day.day)
    return f"https://{PAGEVIEWS_HOST}{path}"


def parse_top(payload: dict) -> list[dict[str, Any]]:
    """Parse a top-pageviews response into ``[{title, rank, views}]``, in rank order.

    Every field is the SOURCE's. ``rank`` is its ordinal and ``views`` its count; this
    function computes neither and combines nothing. A row missing either is DROPPED
    rather than defaulted, because a rank of 0 or a view count of 0 invented here
    would be indistinguishable from a page the service genuinely reported that way.

    Returns ``[]`` for a response with no items — which the caller must not read as
    "nobody viewed anything". The two are told apart one layer up, by whether the
    request succeeded at all.
    """
    items = (payload or {}).get("items")
    if not isinstance(items, list) or not items:
        return []
    articles = items[0].get("articles") if isinstance(items[0], dict) else None
    if not isinstance(articles, list):
        return []
    out: list[dict[str, Any]] = []
    for row in articles:
        if not isinstance(row, dict):
            continue
        title = row.get("article")
        rank = row.get("rank")
        views = row.get("views")
        if not isinstance(title, str) or not isinstance(rank, int) or not isinstance(views, int):
            continue
        if isinstance(rank, bool) or isinstance(views, bool):
            # ``bool`` is an ``int`` in Python; a boolean here is a shape change, not
            # a rank of 1.
            continue
        # The API returns titles with underscores, as they appear in a URL. The lane
        # keys on page ids and the corpus on display titles, so the conversion is
        # done HERE, once, rather than at each of the places that compares them.
        out.append({"title": title.replace("_", " "), "rank": rank, "views": views})
    out.sort(key=lambda r: r["rank"])
    return out


def fetch_top(session: Any, edition: str, day: date, *, timeout: float = 30.0) -> list[dict[str, Any]]:
    """One request, one edition, one day. The session is HANDED IN.

    In production that is ``guarded_session(user_agent=WIKI_USER_AGENT)`` — so the
    kill switch, the protected-mode proxy and the honest bot UA all apply, and
    airplane mode refuses it exactly as it refuses everything else. In CI it is a
    fixture that reads a file. This module builds no session of its own, which is
    what keeps Q1018's "runs in CI without a socket" true of this path too.
    """
    response = session.get(top_url(edition, day), timeout=timeout)
    raise_for_status = getattr(response, "raise_for_status", None)
    if callable(raise_for_status):
        raise_for_status()
    return parse_top(response.json())
