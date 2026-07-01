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

    items = collect_items(include_wiki=True, include_osm=True, include_models=True)
    by_cat: dict[str, dict] = {}
    for it in items:
        c = by_cat.setdefault(it.category, {"count": 0, "bytes": 0})
        c["count"] += 1
        c["bytes"] += it.size
    return by_cat


def backup_inventory(session=None) -> dict:
    """Return ``{corpus, models, maps, wiki}`` — each with what it holds + bytes.

    ``corpus`` carries a breakdown (articles, sources, dates, keywords) so the user
    SEES that everything in the database is included in the one encrypted item. The
    blob categories are counts of completed downloads only (a partial download is
    never offered — the ongoing-downloads-never-backed-up principle).
    """
    blobs = _blob_totals()
    corpus: dict = {"bytes": _db_bytes(), "always": True}
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
        "models": blobs.get("models", {"count": 0, "bytes": 0}),
        "maps": blobs.get("osm_regions", {"count": 0, "bytes": 0}),
        "wiki": blobs.get("wiki_dumps", {"count": 0, "bytes": 0}),
    }
