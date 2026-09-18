#!/usr/bin/env python3
"""The Wikipedia lane, end to end on the recorded fixture, with its counters read back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The operator's >= 72 h run is theirs (see docs/product/WIKI_LANE_SOAK_RUNBOOK.md); this
is the proof that can be produced HERE, and it is deliberately the SAME reading path:
the stream fills the adapter, the runner's drain stores what the tier admits, and the
counters are read from the rows rather than from anything this script counted itself.

WITH THE AIRPLANE SOCKET GUARD ARMED, and resolutions COUNTED rather than requests --
a DNS lookup is itself egress, so counting `socket.getaddrinfo` is the honest bar
(Q1018's own property, applied to the runner).

Run:  OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 OO_DATA_DIR=<tmp> .venv/bin/python run.py --out <dir>
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

EDITION = "oo"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    from src.database.session import init_db

    init_db()

    from src.ingest.airplane import install_airplane_socket_guard
    from src.testing.wiki_fixture import FixtureWikiClient
    from src.testing.wiki_stream_fixture import FixtureStreamSession
    from src.versioned.store import create_lane, lane_file_bytes, lane_session
    from src.wiki.counters import lane_counters, record_size_sample
    from src.wiki.lane import WikiStreamAdapter
    from src.wiki.runner import drain_once
    from src.wiki.stream import WikiEventStream
    from src.wiki.tiers import HotSet, budget_state

    install_airplane_socket_guard()

    # THE BAR: every name this process resolves, counted at the one function every
    # egress must pass through. Wrapped AFTER the guard so the guard itself is inside
    # the count rather than hidden behind it.
    resolutions: list[str] = []
    real_getaddrinfo = socket.getaddrinfo

    def counting_getaddrinfo(*a, **kw):
        resolutions.append(str(a[0]) if a else "?")
        return real_getaddrinfo(*a, **kw)

    socket.getaddrinfo = counting_getaddrinfo  # type: ignore[assignment]

    create_lane("wiki")
    adapter = WikiStreamAdapter(client=FixtureWikiClient(), editions=(EDITION,))
    stream = WikiEventStream(
        session=FixtureStreamSession(), editions=(EDITION,), sleep=lambda _s: None
    )
    stream.run(adapter.offer, max_connections=1, on_position=adapter.note_position)

    hot = {EDITION: HotSet(EDITION, corpus_mention_titles={"Fixture Alpha", "Fixture Beta"})}
    budget = budget_state(total_gb=20, disk_bytes=lane_file_bytes("wiki"), editions=1)
    with lane_session("wiki") as lane:
        report = drain_once(lane, adapter, hot_sets=hot, budget=budget)

    # A SECOND sample, an hour on, so the growth block has the two readings a rate
    # needs. Stamped explicitly rather than by sleeping: the point is the arithmetic,
    # and a script that slept an hour to prove it would be proving patience.
    with lane_session("wiki") as lane:
        record_size_sample(
            lane, lane_file_bytes("wiki"), now=datetime.now(UTC) + timedelta(hours=2)
        )

    with lane_session("wiki") as lane:
        counters = lane_counters(lane, file_bytes=lane_file_bytes("wiki"))

    out = {
        "stream_counters": stream.counters.as_dict(),
        "drain": report.as_dict(),
        "lane_counters": counters,
        "name_resolutions": len(resolutions),
        "resolved_names": sorted(set(resolutions)),
        "bar": (
            "every figure above is read from the lane's own rows; the resolution count "
            "is taken at socket.getaddrinfo, because a DNS lookup is itself egress"
        ),
    }
    (args.out / "report.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    if resolutions:
        print(f"\nFINDING: {len(resolutions)} name resolution(s): {sorted(set(resolutions))}")
        return 1
    print("\n0 name resolutions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
