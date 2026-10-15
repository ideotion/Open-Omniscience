"""A seeded stand-in for the parts of Wikipedia the lane talks to. Zero sockets.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS IS, AND WHAT IT IS NOT. The lane's walk, its stream and its daily top-viewed list are
driven, in ``scripts/analytics45_generate.py``, through the app's OWN code: ``WikiClient`` (its
parameter builders and parsers), ``WikiWalker``, ``WikiEventStream``, ``drain_once`` and the pageview
refresh. This module is the only fake in that path: an HTTP *session* that answers in MediaWiki's
Action API shape, a Server-Sent-Events text in EventStreams' shape, and a pageviews answer in the
Wikimedia REST shape. Every page, title, size, edit and view count in it is invented by a seeded
generator (``random.Random(seed)``), so the same seed gives the same world.

So the rows that come out are ROWS THE APP'S WALK CODE WROTE, not rows Wikipedia sent. They show
that analytics 4 and 5 render what the walk stores. They are NOT a measurement of Wikipedia: the share
of redirects, the page sizes and the edit counts here are stated below and none of them is evidence
about the real service. Anything said about this world must say "stand-in".

THE ONE MEASURED INPUT is the share of a 50-title window that is NOT a redirect, read from the 2026-10-06
bundles (en 36 %, fr 58 %, de and es 91 %); ``ar`` and ``it`` were not measured and use the stand-in's
own assumption (marked ``ASSUMED`` in :data:`PLAN`). The MECHANISM, a ``gaplimit`` of 50 TITLES with the
redirects filtered out after the window, is read from MediaWiki's documentation and was not reproduced
(the sandbox cannot reach Wikipedia); ``docs/product/RELEASE_0.5_GATE.md`` row F says the same.

SIMPLIFICATIONS, stated: one answer per window (no ``pageprops`` continuation), ``articles`` in the
statistics answer is exactly the number of non-redirect pages here (the real count is made its own way),
and titles are made of syllables, so a title reads as nothing.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

LABEL = "stand-in"  # every record made from this world carries this word

#: edition -> (titles in the stand-in edition, share of titles that are NOT redirects, where the share comes from)
PLAN: dict[str, tuple[int, float, str]] = {
    "en": (3000, 0.36, "measured 2026-10-06"),
    "de": (1500, 0.91, "measured 2026-10-06"),
    "fr": (2000, 0.58, "measured 2026-10-06"),
    "es": (1200, 0.91, "measured 2026-10-06"),
    "ar": (800, 0.50, "ASSUMED"),
    "it": (600, 0.60, "ASSUMED"),
}
FOLLOWED = ("en", "de", "fr", "es", "ar")  # the editions the lane follows (the stream and the settings)
WALKED = ("en", "de", "fr", "ar", "it")  # the editions the walk ran in: es never, it once and then dropped
EN_WINDOWS = 40  # the walk stops in en after this many 50-title windows (of 60): a pass in progress
WINDOW = 50

_LATIN = ["ka", "to", "ren", "mi", "su", "vel", "dan", "por", "li", "ex", "an", "ba", "chi", "zor", "wen", "ul"]
_ARABIC = ["كا", "تو", "رن", "مي", "سو", "فل", "دان", "بور", "لي", "نا", "هم", "زار"]

#: Items the look reads on purpose: sizes in bytes per edition (the pages' ``length``), fixed so a bar is a known share.
FORCED_SIZES = {
    "Q34": {"en": 9000, "de": 12000, "fr": 300, "it": 500},
    "Q42": {"en": 64000, "de": 41000},
    "Q7001": {"en": 15000, "fr": 22000},
    "Q7002": {"de": 6100},
}
#: (edition, qid) -> edits the stream sends for that page in the window. fr gets none at all: its changes are UNKNOWN.
FORCED_EDITS = {("en", "Q34"): 3, ("en", "Q42"): 7, ("de", "Q42"): 2, ("en", "Q7001"): 2, ("de", "Q7002"): 1}
EN_FORCED_MAX_INDEX = 500  # forced en pages sit in the part of the list the partial walk reaches


@dataclass(frozen=True)
class Page:
    page_id: int
    title: str
    redirect: bool
    length: int
    revid: int
    qid: str | None


def _word(rng: random.Random, syllables: list[str]) -> str:
    w = "".join(rng.choice(syllables) for _ in range(rng.choice((2, 2, 3))))
    return w if syllables is _ARABIC else w.capitalize()


def _sort_key(title: str) -> bytes:
    return title.encode("utf-8")  # MediaWiki orders titles by byte


class World:
    """The seeded world: editions of pages, the stream's edits, the top-viewed lists and the press plan."""

    def __init__(self, seed: int = 20261015, *, now: datetime | None = None) -> None:
        self.seed = seed
        self.now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
        self.day = (self.now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
        self._rng = random.Random(seed)
        self.pages: dict[str, list[Page]] = {}
        for code, (total, share, _src) in PLAN.items():
            self.pages[code] = self._edition(code, total, share)
        self._force_items()
        self.events = self._stream_events()
        self.tops = self._tops()
        self.press = self._press_plan()

    # -- editions --------------------------------------------------------------------------- #
    def _edition(self, code: str, total: int, share: float) -> list[Page]:
        rng = self._rng
        syl = _ARABIC if code == "ar" else _LATIN
        titles: set[str] = set()
        while len(titles) < total:
            titles.add(f"{_word(rng, syl)} {_word(rng, syl)}")
        ordered = sorted(titles, key=_sort_key)
        n_non = round(total * share)
        flags = [False] * n_non + [True] * (total - n_non)  # True = redirect
        rng.shuffle(flags)
        ids = rng.sample(range(10_000, 9_000_000), total)
        pages = [
            Page(ids[i], t, flags[i], int(min(900_000, max(200, rng.lognormvariate(8.2, 1.1)))), rng.randrange(10**6, 10**7), None)
            for i, t in enumerate(ordered)
        ]
        # an item for ~85 % of the non-redirect pages (the rest carry none); an item id may repeat across editions only
        non = [i for i, p in enumerate(pages) if not p.redirect]
        pool = [f"Q{n}" for n in range(1000, 2600)]
        for i, q in zip(rng.sample(non, int(len(non) * 0.85)), rng.sample(pool, int(len(non) * 0.85)), strict=True):
            p = pages[i]
            pages[i] = Page(p.page_id, p.title, p.redirect, p.length, p.revid, q)
        return pages

    def _force_items(self) -> None:
        """Place the items the look reads on purpose, each on a page of its own (a page carries one item)."""
        rng = random.Random(self.seed + 1)
        taken: set[tuple[str, int]] = set()
        for qid, sizes in FORCED_SIZES.items():
            for code, size in sizes.items():
                pages = self.pages[code]
                non = [i for i, p in enumerate(pages) if not p.redirect]
                reach = non[:EN_FORCED_MAX_INDEX] if code == "en" else non
                i = rng.choice([j for j in reach if (code, j) not in taken])
                taken.add((code, i))
                p = pages[i]
                pages[i] = Page(p.page_id, p.title, False, size, p.revid, qid)

    # -- the stream ------------------------------------------------------------------------- #
    def page_of(self, code: str, qid: str) -> Page | None:
        return next((p for p in self.pages[code] if p.qid == qid and not p.redirect), None)

    def _stream_events(self) -> list[dict]:
        rng = random.Random(self.seed + 2)
        events: list[dict] = []

        def add(code: str, page: Page, n: int) -> None:
            for _ in range(n):
                events.append(self._event(rng, code, page))

        for (code, qid), n in FORCED_EDITS.items():
            page = self.page_of(code, qid)
            if page is not None:
                add(code, page, n)
        # Other edits go to pages carrying NO item, so they never change which items are suggested.
        for code, how_many in (("en", 14), ("de", 10), ("es", 8), ("ar", 6)):  # fr: nothing at all
            free = [p for p in self.pages[code] if not p.redirect and p.qid is None]
            for page in rng.sample(free, how_many):
                add(code, page, rng.choice((1, 1, 2, 3)))
        # noise the lane must filter: talk pages, redirect events, another edition
        en_free = [p for p in self.pages["en"] if not p.redirect and p.qid is None]
        for page in rng.sample(en_free, 6):
            events.append({**self._event(rng, "en", page), "namespace": 1})
        for page in rng.sample([p for p in self.pages["en"] if p.redirect], 4):
            events.append({**self._event(rng, "en", page), "page_is_redirect": True})
        for page in rng.sample([p for p in self.pages["it"] if not p.redirect], 5):
            events.append(self._event(rng, "it", page))
        events.sort(key=lambda e: e["timestamp"])
        return events

    def _event(self, rng: random.Random, code: str, page: Page) -> dict:
        when = self.now - timedelta(seconds=rng.randrange(600, 4 * 86400))
        old = max(100, page.length - rng.randrange(0, 400))
        new = old + rng.randrange(-120, 400)
        return {
            "$schema": "/mediawiki/recentchange/1.0.0",
            "bot": False,
            "comment": "a stand-in edit",
            "length": {"new": new, "old": old},
            "meta": {"domain": f"{code}.wikipedia.org", "dt": when.isoformat().replace("+00:00", "Z"), "stream": "mediawiki.recentchange"},
            "minor": False,
            "namespace": 0,
            "page_id": page.page_id,
            "page_is_redirect": False,
            "revision": {"new": rng.randrange(10**7, 10**8), "old": page.revid},
            "server_name": f"{code}.wikipedia.org",
            "timestamp": int(when.timestamp()),
            "title": page.title,
            "type": "edit",
            "user": "StandInEditor",
            "wiki": f"{code}wiki",
        }

    def sse_text(self) -> str:
        """The events as EventStreams sends them (the same framing ``tests/fixtures/wiki/recentchange_stream.sse`` records)."""
        out = [":ok", ""]
        for n, ev in enumerate(self.events, start=1):
            out += [
                f'id: [{{"topic": "codfw.mediawiki.recentchange", "partition": 0, "offset": {n}}}]',
                "event: message",
                "data: " + json.dumps(ev, separators=(",", ":"), ensure_ascii=False),
                "",
            ]
        return "\n".join(out) + "\n"

    def kept_edits(self) -> dict[tuple[str, int], int]:
        """(edition, page id) -> edits the lane should record: followed edition, namespace 0, not a redirect event."""
        out: dict[tuple[str, int], int] = {}
        for ev in self.events:
            code = ev["wiki"].removesuffix("wiki")
            if code in FOLLOWED and ev["namespace"] == 0 and not ev["page_is_redirect"]:
                key = (code, int(ev["page_id"]))
                out[key] = out.get(key, 0) + 1
        return out

    # -- the daily top-viewed lists ---------------------------------------------------------- #
    def _tops(self) -> dict[str, list[dict]]:
        rng = random.Random(self.seed + 3)
        tops: dict[str, list[dict]] = {}
        for code, n in (("en", 50), ("de", 30), ("fr", 40), ("es", 25), ("ar", 20)):
            reach = self._walked_non_redirects(code)
            chosen = rng.sample(reach, n)
            q34 = self.page_of(code, "Q34")
            if q34 is not None and q34 not in chosen[:3]:
                chosen = [chosen[0], chosen[1], q34, *[p for p in chosen[2:] if p is not q34][: n - 3]]
            rows, views = [], 900_000
            for rank, page in enumerate(chosen, start=1):
                title = "-" if (code == "en" and rank == 12) else page.title
                rows.append({"title": title, "rank": rank, "views": views})
                views = max(1000, int(views * rng.uniform(0.78, 0.9)))
            tops[code] = rows
        return tops

    def _walked_non_redirects(self, code: str) -> list[Page]:
        pages = self.pages[code]
        reach = EN_WINDOWS * WINDOW if code == "en" else len(pages)
        return [p for p in pages[:reach] if not p.redirect]

    def _press_plan(self) -> dict[str, dict[int, tuple[int, int]]]:
        """edition -> rank -> (articles on the list's day, articles in the 7 days ending on it)."""
        rng = random.Random(self.seed + 4)
        plan: dict[str, dict[int, tuple[int, int]]] = {}
        for code, ranks in (("en", 11), ("de", 6), ("fr", 4)):
            per: dict[int, tuple[int, int]] = {}
            for rank in range(1, ranks + 1):
                day = rng.choice((0, 1, 2, 3, 4))
                per[rank] = (day, day + rng.choice((0, 0, 1, 2, 3)))
            if code == "en":
                per[2] = (0, 0)  # a title on the list that the press corpus does not mention
            plan[code] = per
        return plan

    # -- the answers ------------------------------------------------------------------------ #
    def stats_payload(self, code: str) -> dict:
        n_non = sum(1 for p in self.pages[code] if not p.redirect)
        return {"batchcomplete": True, "query": {"statistics": {"articles": n_non, "pages": len(self.pages[code])}}}

    def walk_payload(self, code: str, params: dict) -> dict:
        """One ``generator=allpages`` answer: a window of ``gaplimit`` TITLES, redirects filtered out AFTER the window."""
        titles = self.pages[code]
        start = 0
        if params.get("gapcontinue"):
            want = str(params["gapcontinue"]).replace("_", " ")
            found = next((i for i, p in enumerate(titles) if p.title == want), None)
            if found is None:
                return {"error": {"code": "badcontinue", "info": "the stand-in does not hold that title"}}
            start = found
        limit = int(params.get("gaplimit", WINDOW))
        window = titles[start : start + limit]
        shown = []
        for p in window:
            if p.redirect:
                continue
            row = {"pageid": p.page_id, "ns": 0, "title": p.title, "length": p.length, "lastrevid": p.revid}
            if p.qid:
                row["pageprops"] = {"wikibase_item": p.qid}
            shown.append(row)
        out: dict = {"batchcomplete": True}
        if start + limit < len(titles):
            out["continue"] = {"gapcontinue": titles[start + limit].title.replace(" ", "_"), "continue": "gapcontinue||"}
        if shown:
            out["query"] = {"pages": shown}
        return out

    def pageviews_payload(self, code: str) -> dict:
        rows = [{"article": r["title"].replace(" ", "_"), "views": r["views"], "rank": r["rank"]} for r in self.tops.get(code, [])]
        return {"items": [{"project": f"{code}.wikipedia", "access": "all-access", "year": f"{self.day.year}", "articles": rows}]}


class _Response:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    @property
    def content(self) -> bytes:
        return self._body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return json.loads(self._body)


class StandInSession:
    """``requests.Session``-shaped: answers the Action API and the pageviews API from a :class:`World`, and nothing else."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.headers: dict[str, str] = {}
        #: Every request, in order: (kind, edition). A test reads this to count requests; the walk's cost is real.
        self.requests: list[tuple[str, str]] = []

    def get(self, url, params=None, timeout=None, **_kw):
        host = urlparse(url)
        m = re.fullmatch(r"([a-z]+)\.wikipedia\.org", host.netloc)
        if m and host.path == "/w/api.php":
            code = m.group(1)
            if code not in PLAN:
                raise RuntimeError(f"the stand-in holds no {code!r} edition: {url}")
            params = params or {}
            if params.get("meta") == "siteinfo":
                self.requests.append(("statistics", code))
                return _Response(self.world.stats_payload(code))
            if params.get("generator") == "allpages":
                self.requests.append(("walk", code))
                return _Response(self.world.walk_payload(code, params))
            raise RuntimeError(f"the stand-in does not answer {params.get('action')}/{params.get('prop')}: {url}")
        top = re.fullmatch(r"/api/rest_v1/metrics/pageviews/top/([a-z]+)\.wikipedia/all-access/\d+/\d+/\d+", host.path)
        if host.netloc == "wikimedia.org" and top:
            code = top.group(1)
            self.requests.append(("pageviews", code))
            return _Response(self.world.pageviews_payload(code))
        raise RuntimeError(f"the stand-in serves two APIs and nothing else: {url}")
