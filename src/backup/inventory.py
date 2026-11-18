"""
Backup inventory — "what's available to back up" for the unified Export dialog.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The unified Export/Backup flow asks ONE question -- "what do you want to back up?"
-- over a checklist of what actually EXISTS, with sizes. This module builds that
inventory. Most of the app's data (articles, sources, dates/events, agenda,
keywords, law, markets, annotations, settings, custody) lives in ONE encrypted
database, so it is one atomic "Corpus" item with a breakdown shown (so nothing --
e.g. dates -- feels forgotten). The only separately-selectable items are the big,
re-downloadable file blobs: LLM models, offline maps, Wikipedia dumps.

Read-only + cheap: counts + on-disk sizes only. The actual backup reuses the
always-works streaming engines (write_volume_backup for the corpus, the folder
backup for blobs); this only reports what they would carry.
"""

from __future__ import annotations

from pathlib import Path


def _db_bytes() -> int:
    """On-disk size of the encrypted corpus database (+ WAL/SHM if present)."""
    from src.paths import data_dir

    total = 0
    base = data_dir() / "open_omniscience.db"
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(base) + suffix)
        if p.exists():
            total += p.stat().st_size
    return total


def _blob_totals() -> dict[str, dict]:
    """Per-category file-blob counts + bytes (only DONE downloads are counted)."""
    from src.backup.folder_backup import collect_items

    items = collect_items(include_wiki=True, include_osm=True, include_models=True, include_hf=True)
    by_cat: dict[str, dict] = {}
    for it in items:
        c = by_cat.setdefault(it.category, {"count": 0, "bytes": 0})
        c["count"] += 1
        c["bytes"] += it.size
    return by_cat


#: THE MEMBER HOOK (Q219 = a). An export is "the corpus always; the Wikipedia, OSM and
#: law lanes as opt-in members with their sizes shown BEFORE the export starts". The
#: lanes do not exist yet (0.4 brings wiki, 0.5 brings OSM and law), so what ships here
#: is the SHAPE they will slot into: one ordered list of opt-in members, each naming the
#: folder-backup categories it carries. The dialog renders this list rather than three
#: hardcoded rows, and the run maps a ticked member to its categories through the same
#: list -- so a new lane becomes a row with a real size by appending ONE entry here,
#: with no change to the UI and no second mapping to keep in step.
#:
#: ``key`` is the checkbox id suffix and the wire name; ``label`` is the English string
#: the locale files key on; ``categories`` are the folder-backup categories the member
#: writes. The corpus is NOT in this list: it is always available and is described by
#: its own breakdown.
_BLOB_MEMBERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # One tick, both model stores -- Ollama's and the Hugging Face cache vLLM serves
    # from -- because "my models" means the ones this machine can run.
    ("models", "LLM models", ("models", "hf_models")),
    ("maps", "Offline maps", ("osm_regions",)),
    ("wiki", "Wikipedia dumps", ("wiki_dumps",)),
)


def _lane_member() -> dict:
    """The versioned-source lanes as ONE opt-in member, sized from the files themselves.

    WHY IT IS NOT A FOLDER-BACKUP CATEGORY, which is the whole substance of this hook.
    Every ``_BLOB_MEMBERS`` row names categories the FOLDER backup copies byte for byte,
    and that is right for a finished download: a wiki dump on disk is inert. A lane is
    not. It is a LIVE, WAL-dirty, encrypted SQLCipher database, and a byte copy taken
    while the app is writing produces a file that may simply not open — a backup that
    reports success and restores nothing. Lanes are snapshotted through
    ``connect.snapshot_preserving`` (the corpus's own path, which keeps the source's
    encryption state), so the member declares ``via: "snapshot"`` and carries NO folder
    categories. A future slice that wires the export reads that field rather than
    guessing from the presence of ``categories``.

    THE FORMAT EXISTS NOW (R729, 2026-11-16): ``src/backup/lane_merge.py``. A lane rides as a
    ``lanes/<kind>.db`` member of the encrypted volume set (snapshotted with its own
    encryption kept) and is merged back additively on import. ``exportable`` is True as
    soon as a lane this build can merge back exists; a present lane it cannot carry yet is
    listed in ``waiting`` with its real size, and when ONLY such lanes exist the row stays
    disabled with the reason beside it (a disabled row with no explanation reads as a bug).
    """
    from src.backup.lane_merge import MERGEABLE_KINDS
    from src.versioned.lanes import all_lanes
    from src.versioned.store import lane_file_bytes

    # R729: a lane rides only when this build can also merge it back, so the row counts
    # exactly what the export would write; a present lane this build cannot carry yet is
    # named in ``waiting`` with its size, never silently left out of the picture.
    breakdown: dict[str, dict] = {}
    waiting: dict[str, dict] = {}
    for spec in all_lanes():
        size = lane_file_bytes(spec.kind)
        # ``None`` means ABSENT, which is not zero: a lane that does not exist is not a
        # lane of size nothing, and merging them would put a row in front of an operator
        # for a store they have never opened.
        if size is None:
            continue
        target = breakdown if spec.kind in MERGEABLE_KINDS else waiting
        target[spec.kind] = {"count": 1, "bytes": int(size)}
    out = {
        "key": "lanes",
        "label": "Living sources",
        "categories": [],
        # Lanes always ride INSIDE the encrypted artifact (a live database is never byte-
        # copied beside it), so the row needs the corpus and ignores "carry them inside".
        "via": "snapshot",
        "needs_corpus": True,
        "exportable": True,
        "count": sum(int(p["count"]) for p in breakdown.values()),
        "bytes": sum(int(p["bytes"]) for p in breakdown.values()),
        "breakdown": breakdown,
        "waiting": waiting,
    }
    if not breakdown:
        out["exportable"] = False
        out["not_exportable_reason"] = LANES_WAITING if waiting else LANES_ABSENT
    else:
        out["note"] = LANES_NOTE
    return out


#: The three sentences the Living sources row can show, each a key in all 12 locale files
#: (the dialog looks them up with t(); tests/test_backup_inventory.py is their gate).
LANES_ABSENT = "No living-source store on this computer yet."
#: Since R739 this build carries every lane it knows, so LANES_WAITING is shown only for a
#: store this build cannot merge back (a lane a later version adds), never for maps.
LANES_WAITING = "This version cannot back up the living-source stores on this computer yet; a later version will."
LANES_NOTE = (
    "Living sources always travel inside the encrypted backup, so they need the corpus ticked. "
    "They carry the Wikipedia, law and maps stores."
)


def _members(blobs: dict[str, dict]) -> list[dict]:
    """Each opt-in member with the size the export would ACTUALLY write for it.

    The size is the sum over the member's categories, never one of them: a member whose
    tick exports two stores and whose figure counts one understates exactly the number
    Q219 exists to put in front of the operator.
    """
    out: list[dict] = []
    for key, label, cats in _BLOB_MEMBERS:
        parts = {c: blobs.get(c, {"count": 0, "bytes": 0}) for c in cats}
        out.append(
            {
                "key": key,
                "label": label,
                "categories": list(cats),
                # The folder backup copies these byte for byte, which is correct for a
                # finished download and is stated rather than implied, so the lane
                # member's different answer is a value and not an absence.
                "via": "folder",
                "exportable": True,
                "count": sum(int(p.get("count", 0)) for p in parts.values()),
                "bytes": sum(int(p.get("bytes", 0)) for p in parts.values()),
                # Named per store, because "which of these is the big one" is a real
                # question the combined number can no longer answer.
                "breakdown": parts,
            }
        )
    out.append(_lane_member())
    return out


def backup_inventory(session=None) -> dict:
    """Return ``{corpus, models, maps, wiki}`` — each with what it holds + bytes.

    ``corpus`` carries a breakdown (articles, sources, dates, keywords) so the user
    SEES that everything in the database is included in the one encrypted item. The
    blob categories are counts of completed downloads only (a partial download is
    never offered — the ongoing-downloads-never-backed-up principle).

    ``models`` is BOTH model stores (Ollama's and the Hugging Face cache), because one
    tickbox exports both; each is still named under ``breakdown``.
    """
    blobs = _blob_totals()
    corpus: dict = {"bytes": _db_bytes(), "always": True}
    # The "LLM models" TICK exports BOTH model stores (the export sends `models` and
    # `hf_models` together — src/static/app-backup.js), so the size beside it has to be
    # both. It used to read `models` alone, which understated what the tick would write
    # by the whole Hugging Face cache — and Q219 = a is precisely about the sizes an
    # operator sees BEFORE the export starts, which is the one moment the figure can
    # still change their mind about a 32 GB stick. The two stores stay named in the
    # breakdown, because "which of my model stores is the big one" is a real question
    # the combined number can no longer answer.
    members = _members(blobs)
    by_key = {m["key"]: m for m in members}
    if session is not None:
        from sqlalchemy import func, select

        from src.database.models import (
            Article,
            ArticleMentionedDate,
            Keyword,
            Source,
        )

        def _count(model) -> int:
            return int(session.execute(select(func.count()).select_from(model)).scalar() or 0)

        corpus["breakdown"] = {
            "articles": _count(Article),
            "sources": _count(Source),
            "dates": _count(ArticleMentionedDate),
            "keywords": _count(Keyword),
        }
    return {
        "corpus": corpus,  # articles, sources, dates, agenda, law, markets, annotations, settings…
        "members": members,
        # The flat per-member keys stay beside the list. They are what every existing
        # caller and test reads, and dropping them to "clean up" would break them for a
        # rename rather than for a behaviour.
        "models": by_key["models"],
        "maps": by_key["maps"],
        "wiki": by_key["wiki"],
        "lanes": by_key["lanes"],
    }
