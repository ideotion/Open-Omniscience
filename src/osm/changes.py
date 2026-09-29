"""``.osc`` change files, parsed in pure Python, and the tag-level change rows (Q808, Q813).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q808 = a: «``.osc`` diffs are XML and stay pure Python». Q813 = a: tag-level change rows -- key
added / removed / modified, with the diff's timestamp and the object's ``version``. S05-04
defines the MODEL and leaves the daily APPLY to 0.6 (S06-01), so this module is two pure
functions and nothing that writes: :func:`parse_osc` reads a change file, :func:`tag_changes`
turns an object's old and new tags into rows. No caller in 0.5 persists a row;
``osm_tag_changes`` stays empty, and ``tests/test_osm_changes.py`` pins both halves.

THE XML IS SOMEBODY ELSE'S, so it goes through ``defusedxml`` (a core dependency): a change
file is fetched from a mirror in 0.6, and an entity-expansion bomb in one must fail as a parse
error, never as a machine out of memory.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import IO

ACTIONS = ("create", "modify", "delete")
CHANGES = ("added", "removed", "modified")


@dataclass(frozen=True, slots=True)
class OscChange:
    action: str  # create | modify | delete
    osm_type: str  # n | w | r
    osm_id: int
    version: int | None
    timestamp: datetime | None
    tags: dict[str, str]


@dataclass(frozen=True, slots=True)
class TagChange:
    key: str
    change: str  # added | removed | modified
    old_value: str | None
    new_value: str | None


def _when(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


_TYPES = {"node": "n", "way": "w", "relation": "r"}


def parse_osc(stream: IO[bytes]) -> Iterator[OscChange]:
    """Every object in an ``osmChange`` document, in document order, with its action."""
    from defusedxml.ElementTree import iterparse

    action: str | None = None
    for event, el in iterparse(stream, events=("start", "end")):
        tag = el.tag
        if event == "start":
            if tag in ACTIONS:
                action = tag
            continue
        if tag in ACTIONS:
            action = None
            el.clear()
        elif tag in _TYPES:
            if action is None:
                raise ValueError(f"a <{tag}> outside any create/modify/delete block")
            v = el.get("version")
            yield OscChange(
                action=action,
                osm_type=_TYPES[tag],
                osm_id=int(el.get("id")),
                version=int(v) if v and v.isdigit() else None,
                timestamp=_when(el.get("timestamp")),
                tags={t.get("k"): t.get("v", "") for t in el.findall("tag")},
            )
            el.clear()


def tag_changes(old: dict[str, str] | None, new: dict[str, str] | None) -> list[TagChange]:
    """The key-level difference between two tag sets, key-sorted.

    ``old`` is None for a created object and ``new`` is None for a deleted one; either way every
    key reads as added or removed. An empty value is a value: ``k=""`` to ``k="x"`` is
    ``modified``, never ``added``.
    """
    a = old or {}
    b = new or {}
    out: list[TagChange] = []
    for k in sorted(set(a) | set(b)):
        if k not in a:
            out.append(TagChange(k, "added", None, b[k]))
        elif k not in b:
            out.append(TagChange(k, "removed", a[k], None))
        elif a[k] != b[k]:
            out.append(TagChange(k, "modified", a[k], b[k]))
    return out


def change_rows(osm_type: str, osm_id: int, old, new, *, diff_timestamp, version) -> list:
    """:func:`tag_changes` as unsaved ``OsmTagChange`` rows -- the shape 0.6 will persist."""
    from src.osm.lane_models import OsmTagChange

    return [
        OsmTagChange(
            osm_type=osm_type,
            osm_id=osm_id,
            key=c.key,
            change=c.change,
            old_value=c.old_value,
            new_value=c.new_value,
            diff_timestamp=diff_timestamp,
            object_version=version,
        )
        for c in tag_changes(old, new)
    ]
