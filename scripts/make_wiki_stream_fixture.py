#!/usr/bin/env python3
"""Record a synthetic EventStreams SSE file from the synthetic wiki fixture.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHOLLY SYNTHETIC, AND DERIVED FROM THE FIXTURE THAT IS ALREADY WHOLLY SYNTHETIC. The
edition code ``oo`` is not an ISO 639 code and names no real wiki; every page, user
and comment comes from ``tests/fixtures/wiki/oowiki.json``, whose own provenance note
says the same. Nothing here is derived from Wikipedia.

WHY A RECORDED FILE RATHER THAN A GENERATOR IN THE TEST. The thing under test is a
WIRE FORMAT. A generator that builds events by calling the same helpers the parser
uses would prove only that the code agrees with itself; a file of bytes proves the
parser reads what a server would actually send — including the parts a generator
never thinks to emit: keep-alive comments, a multi-line ``data``, an event whose
``id`` arrives before its ``data``, a malformed body, and a stretch with no ``id`` at
all. Those are written in deliberately, because each one is a defect class the
recorded lessons say a positive-only fixture walks straight past.

THE FILE IS BYTE-STABLE. Same input, same bytes — no timestamps of the run, no
randomness, no dict ordering left to chance — so a diff on it means the format
changed and never that it was regenerated.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = _ROOT / "tests" / "fixtures" / "wiki" / "oowiki.json"
_TARGET = _ROOT / "tests" / "fixtures" / "wiki" / "recentchange_stream.sse"

#: A second edition code, so the client's edition FILTER has something real to
#: exclude. Also not an ISO 639 code.
_OTHER_EDITION = "zz"


def _epoch(stamp: str) -> int:
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())


def _event(*, event_id: str, body: dict, event: str = "message") -> str:
    """One SSE event as a server would frame it: id, event, data, blank line."""
    return (
        f"id: {event_id}\n"
        f"event: {event}\n"
        f"data: {json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}\n"
        "\n"
    )


def _change(
    *,
    wiki: str,
    page_id: int,
    title: str,
    revid: int,
    parent: int | None,
    when: int,
    user: str,
    comment: str,
    new_len: int,
    old_len: int | None,
    kind: str = "edit",
    namespace: int = 0,
    redirect: bool = False,
    log_type: str | None = None,
    log_action: str | None = None,
) -> dict:
    """One ``mediawiki.recentchange`` body, in the service's own field names."""
    body: dict = {
        "$schema": "/mediawiki/recentchange/1.0.0",
        "meta": {"domain": f"{wiki}.example.invalid", "dt": _iso(when), "stream": "mediawiki.recentchange"},
        "wiki": f"{wiki}wiki",
        "type": kind,
        "namespace": namespace,
        "title": title,
        "page_id": page_id,
        "page_is_redirect": redirect,
        "comment": comment,
        "timestamp": when,
        "user": user,
        "bot": user.endswith("Bot"),
        "minor": False,
        "length": {"new": new_len},
        "revision": {"new": revid},
        "server_name": f"{wiki}.example.invalid",
    }
    if old_len is not None:
        body["length"]["old"] = old_len
    if parent is not None:
        body["revision"]["old"] = parent
    if revid <= 0:
        # A LOG event carries no revision at all. Emitting ``revision.new = 0`` was
        # this fixture's own bug and it hid a real one: two log events then shared a
        # change ref and the substrate deduped one away. A fixture that is wrong in
        # the source's favour makes the code look right.
        body.pop("revision", None)
    if log_type:
        body["log_type"] = log_type
        body["log_action"] = log_action or log_type
    return body


def _iso(epoch: int) -> str:
    from datetime import UTC

    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


def build(source: Path) -> str:
    data = json.loads(source.read_text(encoding="utf-8"))
    edition = data["edition"]
    out: list[str] = []
    seq = 0

    def nid() -> str:
        nonlocal seq
        seq += 1
        # EventStreams' Last-Event-ID is a JSON array of Kafka partition offsets.
        # Mirroring that SHAPE matters: the client must treat the id as an opaque
        # string, and a plain integer would let a bug that parses it pass unnoticed.
        return json.dumps([{"topic": "codfw.mediawiki.recentchange", "partition": 0, "offset": 1000 + seq}])

    # A server greets with a comment. A client that dispatched on it would inject an
    # empty event into the corpus every few seconds.
    out.append(":ok\n\n")

    for title, page in sorted(data["pages"].items()):
        prev_len: int | None = None
        parent: int | None = None
        for i, rev in enumerate(page["revisions"]):
            new_len = len(rev["text"].encode("utf-8"))
            out.append(
                _event(
                    event_id=nid(),
                    body=_change(
                        wiki=edition,
                        page_id=page["pageid"],
                        title=title,
                        revid=rev["revid"],
                        parent=parent,
                        when=_epoch(rev["timestamp"]),
                        user=rev["user"],
                        comment=rev["comment"],
                        new_len=new_len,
                        old_len=prev_len,
                        kind="new" if i == 0 else "edit",
                    ),
                )
            )
            prev_len = new_len
            parent = rev["revid"]
            if i == 0:
                # A keep-alive between two real events.
                out.append(":\n\n")

        if page.get("deleted_at"):
            out.append(
                _event(
                    event_id=nid(),
                    body=_change(
                        wiki=edition,
                        page_id=page["pageid"],
                        title=title,
                        revid=0,
                        parent=None,
                        when=_epoch(page["deleted_at"]),
                        user="FixtureAdmin",
                        comment="deleted",
                        new_len=0,
                        old_len=prev_len,
                        kind="log",
                        log_type="delete",
                        log_action="delete",
                    ),
                )
            )

    # --- the negative space, written in deliberately -------------------------- #
    # A page MOVE: same page id, new title. The whole reason Q715 keys on the id.
    out.append(
        _event(
            event_id=nid(),
            body=_change(
                wiki=edition,
                page_id=101,
                title="Fixture Alpha (renamed)",
                revid=0,
                parent=None,
                when=_epoch("2026-03-10T09:00:00Z"),
                user="FixtureAdmin",
                comment="moved",
                new_len=0,
                old_len=None,
                kind="log",
                log_type="move",
                log_action="move",
            ),
        )
    )
    # Another wiki entirely. Must be filtered out, and COUNTED as such.
    out.append(
        _event(
            event_id=nid(),
            body=_change(
                wiki=_OTHER_EDITION,
                page_id=900,
                title="Somewhere Else",
                revid=9001,
                parent=None,
                when=_epoch("2026-03-10T09:05:00Z"),
                user="Someone",
                comment="not ours",
                new_len=10,
                old_len=None,
            ),
        )
    )
    # Namespace 14 (a category) in OUR edition. Q703 keeps namespace 0 only.
    out.append(
        _event(
            event_id=nid(),
            body=_change(
                wiki=edition,
                page_id=901,
                title="Category:Fixtures",
                revid=9002,
                parent=None,
                when=_epoch("2026-03-10T09:06:00Z"),
                user="Someone",
                comment="category",
                new_len=10,
                old_len=None,
                namespace=14,
            ),
        )
    )
    # A REDIRECT in namespace 0. Q703 excludes redirects specifically.
    out.append(
        _event(
            event_id=nid(),
            body=_change(
                wiki=edition,
                page_id=902,
                title="Fixture Alpha (redirect)",
                revid=9003,
                parent=None,
                when=_epoch("2026-03-10T09:07:00Z"),
                user="Someone",
                comment="redirect",
                new_len=30,
                old_len=None,
                redirect=True,
            ),
        )
    )
    # A malformed body. Must be COUNTED, never crash the run and never be stored.
    out.append("id: " + nid() + "\nevent: message\ndata: {\"wiki\": \"oowiki\", truncated\n\n")
    # A multi-line data payload: the JSON split across two ``data:`` lines, which the
    # parser must rejoin with a newline before it is valid JSON at all.
    body = json.dumps(
        _change(
            wiki=edition,
            page_id=105,
            title="Fixture Epsilon",
            revid=9100,
            parent=None,
            when=_epoch("2026-03-10T09:08:00Z"),
            user="Multiline",
            comment="split across lines",
            new_len=44,
            old_len=40,
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    # Split at a point where a newline is LEGAL JSON whitespace -- between two
    # top-level members. Splitting at the midpoint lands inside a string literal, so
    # the rejoined payload is invalid JSON and the test proves only that a broken
    # payload is counted. A real server never splits a token in half either.
    cut = body.index('","bot"') + 2
    out.append(f"id: {nid()}\nevent: message\ndata: {body[:cut]}\ndata: {body[cut:]}\n\n")
    # An event of a DIFFERENT type. Not a recentchange; must be ignored.
    out.append(_event(event_id=nid(), body={"note": "unrelated"}, event="other"))
    # A trailing keep-alive, so the file does not end on a dispatch.
    out.append(":\n\n")
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=_SOURCE)
    ap.add_argument("--out", type=Path, default=_TARGET)
    args = ap.parse_args()
    text = build(args.source)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
