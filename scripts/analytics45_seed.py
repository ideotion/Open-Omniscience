#!/usr/bin/env python3
"""
analytics45_seed -- a small fixture state for the Chromium look at Q712's analytics 4 and 5
(Living sources -> Wikipedia: "One item across editions", "Most-viewed pages beside your corpus").

It writes the rows those two readers read, and nothing else, through the app's own tables:
walk pages and cursors (src.wiki.lane_models), stream changes (src.versioned.models), the
once-a-day top-viewed list in the corpus key-value store (``pageview_kv_key``), a handful of
press articles through the real ``index_article`` chokepoint, and the followed-editions
setting. Every number the look reads back is therefore a number this script wrote on purpose,
listed in ``TRUTH`` and printed as JSON so a walk can compare the page against it.

Run it BEFORE booting the app against the same data directory (the single-writer gate is a
per-process lock):

    OO_DATA_DIR=/tmp/oo-a45/state OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1 \\
        python scripts/analytics45_seed.py

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FOLLOWED = ["en", "de", "fr", "es", "ar"]
# Q34 is read across editions: found in en, de, fr and (not followed) it; es was never walked;
# ar was walked to the end and holds no page for it.
QID = "Q34"
SECOND_QID = "Q42"

# The top-viewed list per edition (rank, title, views as the source would give them) and how many
# press articles the seed publishes for each title on the list's day and in the week before it.
TOP_TITLES = [
    ("Fixture Alpha", 905_113, 4, 6),
    ("Fixture Beta", 410_220, 0, 0),
    ("Salt", 233_871, 2, 3),
    ("-", 120_004, None, None),  # nothing the index can match: counted as "unsearchable"
    ("Fixture Gamma", 98_330, 1, 1),
]


def main() -> int:
    from src.config.kv_store import kv_set_json
    from src.database.session import SessionLocal, init_db

    init_db()

    from src.analytics.extract import get_extractor
    from src.analytics.store import index_article
    from src.database.models import Article, Source
    from src.scheduler.settings import save_settings
    from src.versioned.models import VersionedChange, VersionedEntity
    from src.versioned.store import create_lane, lane_session
    from src.wiki.hotset import pageview_kv_key
    from src.wiki.identity import external_id_for
    from src.wiki.lane_models import WikiWalkCursor, WikiWalkPage

    lane_now = datetime.now(UTC)  # the lane refuses a naive timestamp
    now = lane_now.replace(tzinfo=None)  # the press corpus stores naive UTC
    day = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    save_settings({"wiki_lane_editions": FOLLOWED})

    # ---- the lane: walk pages, cursors, stream changes ------------------------------------ #
    create_lane("wiki")
    with lane_session("wiki") as db:
        walked = lambda ed, pid, title, qid, n: db.add(WikiWalkPage(  # noqa: E731
            edition=ed, page_id=pid, title=title, qid=qid, length_bytes=n, last_revid=1,
            walked_at=lane_now - timedelta(days=1), pass_no=1))
        walked("en", 1, "Salt", QID, 9000)
        walked("de", 2, "Salz", QID, 12000)
        walked("fr", 3, "Sel", QID, 300)
        walked("it", 4, "Sale", QID, 500)
        walked("en", 5, "Douglas Adams", SECOND_QID, 64000)
        walked("de", 6, "Douglas Adams", SECOND_QID, 41000)
        cursor = lambda ed, seen, total, done: db.add(WikiWalkCursor(  # noqa: E731
            edition=ed, pass_no=1, pages_seen=seen, requests=1, response_bytes=1,
            edition_articles=total, completed_at=lane_now if done else None))
        cursor("en", 10, 10, True)
        cursor("de", 30, 1000, False)
        cursor("fr", 500, 500, True)
        cursor("ar", 80, 80, True)
        # es: no cursor at all, the walk never ran there.

        def changes(ed, pid, n, *, entity=False):
            ext = external_id_for(ed, pid)
            if entity:
                db.add(VersionedEntity(external_id=ext, title="t"))
            for i in range(n):
                db.add(VersionedChange(
                    change_ref=f"{ext}-{i}", feed=f"stream:{ed}", change_kind="edit", external_id=ext,
                    recorded_at=lane_now - timedelta(days=1, minutes=i), byte_delta=5))

        changes("en", 1, 3, entity=True)   # Salt in en: 3 recorded changes
        changes("fr", 3, 0, entity=True)   # a followed page with no change recorded anywhere in fr: the edition is UNKNOWN
        changes("en", 5, 7)                # the second item's pages, for the suggestions
        changes("de", 6, 2)
        db.flush()
        db.commit()

    # ---- the top-viewed lists (one per edition that has one) ------------------------------ #
    for ed in ("en", "de"):
        rows = [{"rank": i + 1, "title": t, "views": v} for i, (t, v, _d, _w) in enumerate(TOP_TITLES)]
        if ed == "de":
            rows = rows[:3]
        kv_set_json(pageview_kv_key(ed), {"day": day.date().isoformat(), "n": 1000, "rows": rows})

    # ---- the press corpus: articles on the list's day and in the week before it ----------- #
    extractor = get_extractor("baseline")
    with SessionLocal() as s:
        press = Source(name="Fixture Press", domain="press.example", language="en", country="US",
                       status="active")
        wiki = Source(name="Wikipedia", domain="en.wikipedia.org", language="en", country="US",
                      status="active")
        s.add_all([press, wiki])
        s.commit()
        n = 0
        for title, _v, on_day, in_week in TOP_TITLES:
            if on_day is None:
                continue
            for i in range(on_day + (in_week - on_day)):
                when = day + timedelta(hours=9 + i) if i < on_day else day - timedelta(days=1 + i)
                body = f"{title} was in the news. " * 3 + f"[{title}-{i}]"
                a = Article(
                    url=f"https://press.example/{title.replace(' ', '-')}-{i}",
                    canonical_url=f"https://press.example/{title.replace(' ', '-')}-{i}",
                    source_id=press.id, title=f"{title} dispatch {i}", content=body, published_at=when,
                    language="en", hash=hashlib.sha256(body.encode()).hexdigest(),
                    author="Staff", word_count=len(body.split()), created_at=when, updated_at=when)
                s.add(a)
                s.commit()
                index_article(s, a, extractor=extractor, country="US")
                n += 1
        # a Wikipedia-sourced article about the same title: must NOT be counted as press coverage
        body = "Fixture Alpha is the page's own text."
        a = Article(
            url="https://en.wikipedia.org/wiki/Fixture_Alpha", canonical_url="https://en.wikipedia.org/wiki/Fixture_Alpha",
            source_id=wiki.id, title="Fixture Alpha", content=body, published_at=day + timedelta(hours=1),
            language="en", hash=hashlib.sha256(body.encode()).hexdigest(), author="", word_count=6,
            created_at=day, updated_at=day)
        s.add(a)
        s.commit()
        index_article(s, a, extractor=extractor, country="US")

    truth = {
        "day": day.date().isoformat(),
        "qid": QID,
        "followed": FOLLOWED,
        "divergence": {
            "found": ["en", "de", "fr", "it"], "sizes": {"en": 9000, "de": 12000, "fr": 300, "it": 500},
            "smallest": "fr", "largest": "de", "changes": {"en": 3, "de": 0, "fr": None, "it": None},  # de: the edition has recorded changes (for another page), this page none; fr: nothing recorded for the edition at all
            "es": "walk never ran", "ar": "walk finished, no page", "de_walk": "30 of 1000",
        },
        "attention": {t: {"views": v, "day": d, "week": w} for t, v, d, w in TOP_TITLES},
        "attention_editions_with_list": ["en", "de"],
        "press_articles_written": n,
    }
    print(json.dumps(truth, indent=1))
    return 0


if __name__ == "__main__":
    if not os.environ.get("OO_DATA_DIR"):
        sys.exit("refusing: set OO_DATA_DIR to a scratch directory (this writes a database)")
    sys.exit(main())
