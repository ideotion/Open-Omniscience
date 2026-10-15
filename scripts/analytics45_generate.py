#!/usr/bin/env python3
"""
analytics45_generate -- rows for the Chromium look at Q712's analytics 4 and 5 that the APP'S OWN WALK CODE wrote.

``analytics45_seed.py`` writes the rows those two readers read straight into their tables. This script
does not: it runs the lane's real code against a STAND-IN for Wikipedia (``src/testing/wiki_standin.py``,
a seeded world that answers in MediaWiki's shape and nothing else) and lets that code write the rows:

  * ``WikiClient`` (its parameter builders and parsers) over the stand-in session, driven by
    ``WikiWalker``: the edition counts, every ``allpages`` window, the cursors, the throughput samples;
  * ``WikiEventStream`` -> ``WikiStreamAdapter`` -> ``drain_once``: the stream's changes into the lane;
  * the daily top-viewed lists through the service's own refresh (``_refresh_one_pageview_top``);
  * the press articles through the real ``index_article`` chokepoint.

WHAT THIS PROVES AND WHAT IT DOES NOT. It proves the readers render what the walk code stores. It does NOT
measure Wikipedia: every page, size, edit and view count is invented by a seeded generator, and the redirect shares
are the only figures read from a real source (the 2026-10-06 bundles). Row F's clause «analytics 4-5 render from
real rows» is therefore EVIDENCED here and not CLOSED: the operator's walk, on a real install, is what puts
Wikipedia's rows behind them (``docs/product/RELEASE_0.5_GATE.md``, «What only a real install can supply»).
Everything printed carries the word ``stand-in``.

Every session is injected, and a tripwire on ``socket`` refuses any non-loopback connection for the whole run, so a
request that reached the network instead of the stand-in would raise; the stand-in session is the only door. (The
kill switch is NOT engaged: the stream refuses to open under it, which is the app behaving correctly.)

Run it BEFORE booting the app against the same data directory. It refuses a data directory that already holds
anything, and a set DATABASE_URL:

    OO_DATA_DIR=/tmp/oo-a45g/state OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1 \\
        python scripts/analytics45_generate.py > truth.json

Stdout is the TRUTH: what the stand-in planned (computed from the world, not read back from the lane), which
``analytics45_look.py --truth truth.json`` compares the page against. Before printing it the script reads the lane
back and exits non-zero if the app's rows disagree with the plan (that is a finding about the app or the stand-in).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analytics45_seed import refuse_unless_scratch  # noqa: E402

SEED = 20261015
EXTRA = "it"  # the walk found Q34 here once; the edition is not followed (it is shown as an extra row)
A3 = {"en": "eng", "de": "deu", "fr": "fra", "es": "spa", "ar": "ara", "it": "ita"}


def _kib(n: int) -> str:
    """The reader's size text: bytes below 1 KiB, else KiB with one decimal, ties rounded up as the page's ``toFixed``
    does on an exact value (so 9000 reads 8.8 and 1280 reads 1.3). Sizes of 1 MiB or more are not drawn by this world."""
    if n >= 1024 * 1024:
        raise ValueError("the stand-in world holds no page of 1 MiB or more (the page's MB form is not modelled here)")
    return str(n) if n < 1024 else str((Decimal(n) / 1024).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _js_round(x: float) -> int:
    return int(x + 0.5)


#: Every refusal the tripwire made, as ``(what, host)``. The app's own code catches ``Exception`` around a fetch, so a refusal can
#: be swallowed on the spot and the run would still print a plan; ``main`` reads this at the end and fails when it is not empty.
REFUSALS: list[tuple[str, str]] = []


def _install_socket_tripwire() -> None:
    """Refuse every non-loopback connection, datagram or name lookup for the rest of this process.

    Covers the TCP path ``requests`` uses (``connect``, ``connect_ex``, ``getaddrinfo``, ``gethostbyname``), the UDP and message
    send calls (``sendto``, ``sendmsg``) and the other name lookups (``gethostbyname_ex``, ``gethostbyaddr``, ``getnameinfo``).
    ``create_connection`` resolves through ``getaddrinfo`` and connects through ``connect``, so it is covered by those two. A host
    is local only if it IS a loopback address (an IPv4-mapped IPv6 address counts as the IPv4 address it wraps) or exactly
    ``localhost``; a name that merely starts with one (``127.x.example``) is not.
    """
    import ipaddress
    import socket

    def _is_local(host) -> bool:
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if not isinstance(host, str):
            return False
        if host == "localhost":
            return True
        # a scope (``fe80::1%eth0``) belongs to an IPv6 literal only: on anything else the text after ``%`` is part of a NAME
        text = host.split("%", 1)[0] if ":" in host else host
        try:
            ip = ipaddress.ip_address(text)
        except ValueError:
            return False
        mapped = getattr(ip, "ipv4_mapped", None)
        return (mapped or ip).is_loopback

    def refuse(what: str, host) -> None:
        REFUSALS.append((what, repr(host)))
        raise OSError(f"analytics45_generate: {what} {host!r} was refused; only the stand-in may answer")

    def guarded(fn, what, take_host):
        def wrapper(self, *a, **kw):
            host = take_host(self, *a, **kw)
            if host is not None and not _is_local(host):
                refuse(what, host)
            return fn(self, *a, **kw)
        return wrapper

    def addr_host(self, address, *_a, **_kw):
        return None if self.family == socket.AF_UNIX else address[0]

    def sendto_host(self, data, *a, **_kw):
        return None if self.family == socket.AF_UNIX else a[-1][0]

    def sendmsg_host(self, buffers, ancdata=(), flags=0, address=None):
        return None if (address is None or self.family == socket.AF_UNIX) else address[0]

    for name in ("connect", "connect_ex"):
        setattr(socket.socket, name, guarded(getattr(socket.socket, name), "a connection to", addr_host))
    socket.socket.sendto = guarded(socket.socket.sendto, "a datagram to", sendto_host)  # type: ignore[method-assign]
    socket.socket.sendmsg = guarded(socket.socket.sendmsg, "a message to", sendmsg_host)  # type: ignore[method-assign]

    def name_guard(real, what, take_host):
        def wrapper(*a, **kw):
            host = take_host(*a, **kw)
            if not _is_local(host):
                refuse(what, host)
            return real(*a, **kw)
        return wrapper

    first = lambda host, *_a, **_kw: host  # noqa: E731
    socket.getaddrinfo = name_guard(socket.getaddrinfo, "a name lookup for", first)  # type: ignore[assignment]
    socket.gethostbyname = name_guard(socket.gethostbyname, "a name lookup for", first)  # type: ignore[assignment]
    socket.gethostbyname_ex = name_guard(socket.gethostbyname_ex, "a name lookup for", first)  # type: ignore[assignment]
    socket.gethostbyaddr = name_guard(socket.gethostbyaddr, "a reverse lookup for", first)  # type: ignore[assignment]
    socket.getnameinfo = name_guard(socket.getnameinfo, "a reverse lookup for", lambda sockaddr, *_a, **_kw: sockaddr[0])  # type: ignore[assignment]


def main() -> int:
    from src.config.kv_store import kv_get_json
    from src.database.session import SessionLocal, init_db
    from src.testing.wiki_standin import (
        EN_WINDOWS,
        FOLLOWED,
        LABEL,
        PLAN,
        WALKED,
        WINDOW,
        StandInSession,
        World,
    )
    from src.testing.wiki_stream_fixture import FixtureStreamSession

    _install_socket_tripwire()
    init_db()

    from sqlalchemy import func, select

    from src.analytics.extract import get_extractor
    from src.analytics.store import index_article
    from src.database.models import Article, Source
    from src.scheduler.settings import save_settings
    from src.versioned.models import VersionedChange, VersionedEntity
    from src.versioned.store import create_lane, lane_session
    from src.wiki import service
    from src.wiki.client import WikiClient
    from src.wiki.hotset import pageview_kv_key
    from src.wiki.identity import external_id_for
    from src.wiki.lane import WikiStreamAdapter
    from src.wiki.lane_models import WikiWalkCursor, WikiWalkPage
    from src.wiki.runner import drain_once
    from src.wiki.stream import WikiEventStream
    from src.wiki.tiers import HotSet, budget_state
    from src.wiki.walk import WikiWalker

    world = World(SEED)
    session = StandInSession(world)
    client = WikiClient(session=session, min_interval_s=0.0)
    save_settings({"wiki_lane_editions": list(FOLLOWED)})
    create_lane("wiki")

    # ---- the walk: the real walker over the real client ----------------------------------- #
    budget = budget_state(total_gb=20, disk_bytes=0, editions=len(FOLLOWED))
    walker = WikiWalker(
        client=client, editions=WALKED, lane_session=service.walk_lane_session,
        budget=lambda: budget, enabled=lambda: True, transport=lambda: "direct",
    )

    def en_windows() -> int:
        return sum(1 for kind, code in session.requests if kind == "walk" and code == "en")

    guard = 0
    while guard < 5000:
        guard += 1
        others_done = all(c not in walker._unfinished() for c in WALKED if c != "en")  # noqa: SLF001
        if others_done and en_windows() >= EN_WINDOWS:
            break
        walker.walk_for(60.0, max_requests=1)

    # ---- the stream: the real parser, adapter and drain ----------------------------------- #
    with tempfile.TemporaryDirectory() as tmp:
        sse = Path(tmp) / "standin.sse"
        sse.write_text(world.sse_text(), encoding="utf-8")
        adapter = WikiStreamAdapter(client=client, editions=FOLLOWED)
        stream = WikiEventStream(session=FixtureStreamSession(path=sse), editions=FOLLOWED, sleep=lambda _s: None)
        stream.run(adapter.offer, max_connections=1, on_position=adapter.note_position)
    hot = {e: HotSet(e) for e in FOLLOWED}
    for _ in range(50):
        with lane_session("wiki") as db:
            report = drain_once(db, adapter, hot_sets=hot, budget=budget)
        if report.errors:
            print(json.dumps({"problems": [f"drain: {e}" for e in report.errors]}), file=sys.stderr)
            return 3
        if not report.changes_recorded:
            break

    # ---- the daily top-viewed lists: the service's own refresh ----------------------------- #
    refreshed = []
    for _ in range(len(FOLLOWED) + 1):
        done = service._refresh_one_pageview_top(client)  # noqa: SLF001
        if done is None:
            break
        refreshed.append(done)

    # ---- the press corpus ------------------------------------------------------------------ #
    day = world.day.replace(tzinfo=None)
    extractor = get_extractor("baseline")
    press_made = 0
    with SessionLocal() as s:
        press = Source(name="Stand-in Press", domain="press.example", language="en", country="US", status="active")
        wiki = Source(name="Wikipedia", domain="en.wikipedia.org", language="en", country="US", status="active")
        s.add_all([press, wiki])
        s.commit()

        def article(url: str, source_id: int, title: str, body: str, when: datetime, lang: str) -> None:
            a = Article(
                url=url, canonical_url=url, source_id=source_id, title=title, content=body, published_at=when,
                language=lang, hash=hashlib.sha256(body.encode()).hexdigest(), author="Staff",
                word_count=len(body.split()), created_at=when, updated_at=when)
            s.add(a)
            s.commit()
            index_article(s, a, extractor=extractor, country="US")

        for code, per in world.press.items():
            rows = {r["rank"]: r["title"] for r in world.tops[code]}
            for rank, (n_day, n_week) in per.items():
                title = rows[rank]
                for i in range(n_week):
                    when = day + timedelta(hours=9 + i) if i < n_day else day - timedelta(days=1 + (i - n_day), hours=-10)
                    body = f"{title} was in the news. " * 3 + f"[{code}-{rank}-{i}]"
                    article(f"https://press.example/{code}-{rank}-{i}", press.id, f"{title} dispatch {i}", body, when, code)
                    press_made += 1
        top_en = world.tops["en"][0]["title"]  # a Wikipedia-sourced article about the first title: it is not press coverage
        article("https://en.wikipedia.org/wiki/standin-first", wiki.id, top_en, f"{top_en} is the page's own text.", day + timedelta(hours=1), "en")

    # ---- the truth: from the PLAN, not read back from the lane ------------------------------- #
    # en stopped where the stand-in's own request log says it did (the walker is round-robin, so it may have taken one
    # window past EN_WINDOWS before the others finished); the plan is read from that log, never from the lane.
    walked_reach = {c: (en_windows() * WINDOW if c == "en" else len(world.pages[c])) for c in WALKED}
    walk_truth = {}
    for c in WALKED:
        seen = [p for p in world.pages[c][: walked_reach[c]] if not p.redirect]
        complete = walked_reach[c] >= len(world.pages[c])
        walk_truth[c] = {"pages_seen": len(seen), "edition_articles": sum(1 for p in world.pages[c] if not p.redirect), "complete": complete}
    kept = world.kept_edits()
    streamed_editions = {c for (c, _pid) in kept}

    def found_in(qid: str) -> list[str]:
        out = []
        for c in WALKED:
            p = world.page_of(c, qid)
            if p is not None and world.pages[c].index(p) < walked_reach[c]:
                out.append(c)
        return out

    def divergence(qid: str) -> dict:
        wanted = list(dict.fromkeys([*FOLLOWED, *[c for c in WALKED if c not in FOLLOWED and c in found_in(qid)]]))
        found = found_in(qid)
        rows, sizes = [], {}
        for c in wanted:
            if c in found:
                p = world.page_of(c, qid)
                sizes[c] = p.length
                changes = kept.get((c, p.page_id), 0) if c in streamed_editions else None
                rows.append({"edition": A3[c], "found": True, "size": p.length, "size_text": _kib(p.length), "changes": changes})
            else:
                rows.append({"edition": A3[c], "found": False})
        top = max(sizes.values()) if sizes else 0
        for r in rows:
            r["bar"] = f"{max(1, _js_round(r['size'] * 100 / top))}%" if r["found"] and top else None  # the page floors a bar at 1 %
        return {"qid": qid, "rows": rows}

    items: dict[str, dict] = {}
    for (c, pid), n in kept.items():
        page = next(p for p in world.pages[c] if p.page_id == pid)
        if page.qid and c in WALKED and world.pages[c].index(page) < walked_reach[c]:
            items.setdefault(page.qid, {"changes": 0})["changes"] += n
    suggestions = sorted(({"qid": q, "changes": v["changes"], "found_in": len(found_in(q))} for q, v in items.items()),
                         key=lambda r: (-r["changes"], r["qid"]))
    attention = {}
    for code, rows in world.tops.items():
        per = world.press.get(code, {})
        attention[code] = [
            {"rank": r["rank"], "views": r["views"], "title": r["title"],
             "day": None if r["title"] == "-" else per.get(r["rank"], (0, 0))[0],
             "week": None if r["title"] == "-" else per.get(r["rank"], (0, 0))[1]}
            for r in rows[:50]
        ]
    truth = {
        "label": f"{LABEL} (seeded world {SEED}); NOT Wikipedia's rows",
        "day": world.day.date().isoformat(),
        "followed": list(FOLLOWED), "walked": list(WALKED), "extra": EXTRA,
        "redirect_shares": {c: {"non_redirect_share": PLAN[c][1], "source": PLAN[c][2]} for c in PLAN},
        "walk": walk_truth,
        "requests": {"walk": sum(1 for k, _c in session.requests if k == "walk"),
                     "statistics": sum(1 for k, _c in session.requests if k == "statistics"),
                     "pageviews": sum(1 for k, _c in session.requests if k == "pageviews")},
        "suggestions": suggestions,
        "divergence": {q: divergence(q) for q in ("Q34", "Q42", "Q7001", "Q7002")},
        "attention": attention,
        "attention_editions_with_list": sorted(attention),
        "press_articles_written": press_made,
        "stream_events_sent": len(world.events),
        "stream_edits_recorded": sum(kept.values()),
    }

    # ---- the agreement between the app's rows and the plan ----------------------------------- #
    problems = []
    with lane_session("wiki") as db:
        for c in WALKED:
            n = db.execute(select(func.count()).select_from(WikiWalkPage).where(WikiWalkPage.edition == c)).scalar()
            cur = db.get(WikiWalkCursor, c)
            want = walk_truth[c]
            if n != want["pages_seen"]:
                problems.append(f"walk pages {c}: lane {n}, plan {want['pages_seen']}")
            if cur is None or cur.edition_articles != want["edition_articles"] or bool(cur.completed_at) != want["complete"]:
                problems.append(f"walk cursor {c}: lane {None if cur is None else (cur.edition_articles, bool(cur.completed_at))}, plan {want}")
        if db.get(WikiWalkCursor, "es") is not None:
            problems.append("a cursor exists for es, where the walk never ran")
        n_changes = db.execute(select(func.count()).select_from(VersionedChange)).scalar()
        if n_changes != truth["stream_edits_recorded"]:
            problems.append(f"stream changes: lane {n_changes}, plan {truth['stream_edits_recorded']}")
        if db.execute(select(func.count()).select_from(VersionedEntity)).scalar():
            problems.append("the lane followed a page by itself with no admit rule")
        for (c, pid), n in kept.items():
            got = db.execute(select(func.count(VersionedChange.id)).where(VersionedChange.external_id == external_id_for(c, pid))).scalar()
            if got != n:
                problems.append(f"changes {c}:{pid}: lane {got}, plan {n}")
    for code, rows in world.tops.items():
        blob = kv_get_json(pageview_kv_key(code)) or {}
        if [r["title"] for r in (blob.get("rows") or [])] != [r["title"] for r in rows[:50]]:
            problems.append(f"top list {code}: the stored list differs from the plan")
    if sorted(refreshed) != sorted(world.tops):
        problems.append(f"pageview refresh reached {sorted(refreshed)}, plan {sorted(world.tops)}")
    if REFUSALS:  # the app's own code catches Exception around a fetch, so a refusal it swallowed is only visible here
        problems.append(f"the tripwire refused {len(REFUSALS)} call(s): {REFUSALS[:5]}")
    if problems:
        print(json.dumps({"problems": problems}, indent=1), file=sys.stderr)
        return 3
    print(json.dumps(truth, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    why = refuse_unless_scratch()
    if why:
        sys.exit(why)
    os.environ.setdefault("OO_NO_SCHEDULER", "1")
    sys.exit(main())
