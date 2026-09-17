#!/usr/bin/env python3
"""Generate the synthetic wiki-edition fixture the versioned lane's CI pass runs on.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1018 = a asks for "a synthetic wiki edition ... in ``tests/fixtures/``, so every
lane's pipeline runs end-to-end in CI without a socket". This writes it.

FULLY SYNTHETIC, AND THE EDITION CODE SAYS SO. The edition is ``oo``, which is not
an ISO 639 language code and therefore cannot be a real Wikipedia edition — so a
fixture path can never be mistaken for a real one, and a bug that let a fixture
address escape into a live fetch would ask for a host that does not exist rather
than for somebody's server. Every page title, body and editor name is invented. No
byte of this file comes from Wikipedia, so no attribution obligation attaches to it
(the recorded shape of the Q823 hazard, avoided by construction rather than argued).

DETERMINISTIC. The generator takes no clock and no RNG — the timestamps are computed
from a fixed epoch and the bodies are written out literally — so re-running it
produces a byte-identical file and a test can pin the fixture's own SHA-256. The
recorded lesson is the reason: ``hash()`` and unseeded randomness make a
cross-process differential compare different inputs, and a fixture that changes
under its own test is worse than no fixture.

WHAT THE FIXTURE IS SHAPED TO EXERCISE — one page per property, so a failing test
names the property rather than "the fixture":

* ``Fixture Alpha``   a page CREATED then MODIFIED twice. The ordinary path:
                      baseline -> change -> revision -> Article, and a point-in-time
                      read that must return the middle version.
* ``Fixture Beta``    a page whose second edit restores its first text exactly. The
                      NULL-EDIT case: a new revid, an identical body, which must
                      store as ``unchanged`` rather than as an empty diff.
* ``Fixture Gamma``   a page DELETED after two edits, so the delete arrives as a log
                      event and ``fetch_version`` answers "no such item" while the
                      history stays.
* ``Fixture Delta``   a page with a LARGE body, so the budget has something worth
                      refusing and the deferral is visible as a real byte count.
* ``Fixture Epsilon`` a page whose only edits are OLDER than the retention window
                      the fixture client is asked to serve, which is what produces
                      the ``retention`` gap without anyone faking one.

REVISION IDS RISE WITH TIME, ACROSS PAGES. A real MediaWiki's revision id is a
per-wiki counter, so the newest change always carries the largest id. The first
version of this fixture numbered ids in per-page blocks (1001-1003, 1010-1012, ...),
which no wiki can produce — and the end-to-end round trip duly went quiet: three of
five pages stopped receiving changes, every counter read zero, and nothing reported a
fault. The adapter's cursor was corrected to a TIMESTAMP so it no longer depends on
this ordering at all, and the ids were corrected too, because a fixture that models
something the source cannot do will mislead the next reader in some other way.

Run: ``python scripts/make_wiki_fixture.py`` (writes in place; prints the digest).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

EDITION = "oo"
EPOCH = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "wiki" / "oowiki.json"


def _ts(days: int, minutes: int = 0) -> str:
    return (EPOCH + timedelta(days=days, minutes=minutes)).isoformat().replace("+00:00", "Z")


def _body(title: str, para: str, *, extra_lines: int = 0) -> str:
    """A small, plausible wikitext body. Deliberately mundane: the pipeline is under
    test, not the prose, and a body that reads like a real article invites someone to
    check it against a real one."""
    lines = [
        f"'''{title}''' is a synthetic page in the Open Omniscience test fixture.",
        "",
        para,
        "",
        "== Background ==",
        "This section exists so a diff has more than one hunk to find.",
    ]
    lines += [f"Filler line {i} for the {title} body." for i in range(extra_lines)]
    return "\n".join(lines) + "\n"


PAGES: dict[str, dict] = {
    "Fixture Alpha": {
        "pageid": 101,
        "revisions": [
            {
                "revid": 1001,
                "type": "new",
                "timestamp": _ts(0),
                "user": "FixtureEditorOne",
                "comment": "create the page",
                "text": _body("Fixture Alpha", "The first version mentions rivers and bridges."),
            },
            {
                "revid": 1005,
                "type": "edit",
                "timestamp": _ts(3),
                "user": "FixtureEditorTwo",
                "comment": "expand the background",
                "text": _body(
                    "Fixture Alpha",
                    "The second version mentions rivers, bridges and a canal.",
                ),
            },
            {
                "revid": 1011,
                "type": "edit",
                "timestamp": _ts(9),
                "user": "FixtureEditorOne",
                "comment": "add a sentence",
                "text": _body(
                    "Fixture Alpha",
                    "The third version mentions rivers, bridges, a canal and a harbour.",
                )
                + "The harbour was added last.\n",
            },
        ],
    },
    "Fixture Beta": {
        "pageid": 102,
        "revisions": [
            {
                "revid": 1002,
                "type": "new",
                "timestamp": _ts(1),
                "user": "FixtureEditorThree",
                "comment": "create the page",
                "text": _body("Fixture Beta", "Beta describes a mountain range."),
            },
            {
                "revid": 1006,
                "type": "edit",
                "timestamp": _ts(4),
                "user": "FixtureEditorTwo",
                "comment": "vandalise",
                "text": _body("Fixture Beta", "Beta describes NOTHING AT ALL."),
            },
            {
                # Byte-identical to 1002: a revert. A NEW revid, the SAME text.
                "revid": 1007,
                "type": "edit",
                "timestamp": _ts(5),
                "user": "FixtureEditorThree",
                "comment": "revert",
                "text": _body("Fixture Beta", "Beta describes a mountain range."),
            },
        ],
    },
    "Fixture Gamma": {
        "pageid": 103,
        "deleted_at": _ts(8),
        "delete_logid": 1010,
        "revisions": [
            {
                "revid": 1003,
                "type": "new",
                "timestamp": _ts(2),
                "user": "FixtureEditorFour",
                "comment": "create the page",
                "text": _body("Fixture Gamma", "Gamma describes a disputed statistic."),
            },
            {
                "revid": 1008,
                "type": "edit",
                "timestamp": _ts(6),
                "user": "FixtureEditorFour",
                "comment": "correct the figure",
                "text": _body("Fixture Gamma", "Gamma describes a corrected statistic."),
            },
        ],
    },
    "Fixture Delta": {
        "pageid": 104,
        "revisions": [
            {
                "revid": 1004,
                "type": "new",
                "timestamp": _ts(2, 30),
                "user": "FixtureEditorFive",
                "comment": "create a long page",
                "text": _body(
                    "Fixture Delta",
                    "Delta is deliberately long so a byte budget has something to refuse.",
                    extra_lines=400,
                ),
            },
            {
                "revid": 1009,
                "type": "edit",
                "timestamp": _ts(7),
                "user": "FixtureEditorFive",
                "comment": "extend the long page",
                "text": _body(
                    "Fixture Delta",
                    "Delta is deliberately long so a byte budget has something to refuse.",
                    extra_lines=800,
                ),
            },
        ],
    },
    "Fixture Epsilon": {
        "pageid": 105,
        "revisions": [
            {
                # Far older than every other change, so a retention-bounded window
                # that serves the newest N changes cannot reach it.
                "revid": 900,
                "type": "new",
                "timestamp": _ts(-400),
                "user": "FixtureEditorSix",
                "comment": "create an old page",
                "text": _body("Fixture Epsilon", "Epsilon was written long ago."),
            },
            {
                "revid": 901,
                "type": "edit",
                "timestamp": _ts(-390),
                "user": "FixtureEditorSix",
                "comment": "tidy",
                "text": _body("Fixture Epsilon", "Epsilon was written long ago and tidied."),
            },
        ],
    },
}


def build() -> dict:
    return {
        "_provenance": (
            "Wholly synthetic. Generated by scripts/make_wiki_fixture.py. "
            "No content is derived from Wikipedia or any other source; the edition "
            "code 'oo' is not an ISO 639 code and names no real wiki."
        ),
        "edition": EDITION,
        "generated_from": "scripts/make_wiki_fixture.py",
        "pages": PAGES,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT,
        help=(
            "where to write the fixture. Exists so a test can regenerate into a "
            "temporary path and compare digests WITHOUT overwriting the committed "
            "file — a determinism check that rewrites its own subject proves nothing."
        ),
    )
    args = parser.parse_args(argv)

    payload = json.dumps(build(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    print(f"wrote {out} ({len(payload)} bytes)")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
