"""
The owner-only evidence archive.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §9 ("two exits, one record") and §18 (privacy of the exported
artifact). The edition JSON rides the encrypted backup free; THIS is the other
exit — every article the edition's numbers were computed over, with full
metadata, written as a plain ZIP for archival and quality assurance.

Three things about it are load-bearing and are stated in the archive itself, not
only here:

* **It is PLAINTEXT leaving an encrypted store.** The corpus is encrypted at
  rest; this archive is not. Writing one is a deliberate act with a real
  consequence, so it is disclosed at the plan step, in the README, and in the
  manifest — never assumed because the operator clicked a button.
* **It is OWNER-ONLY.** It is not the published document and must not be
  distributed: it carries the corpus, not a summary of it.
* **Its article set is the period's, EXACTLY.** Not a sample, not the top N.
  The point of an evidence archive is that someone can recompute the edition's
  numbers from it; a sampled archive cannot do that, and would quietly turn the
  edition's exact counts into unverifiable ones.

The plan step exists because that last property has a price: a period's articles
can be large. The operator sees the real count and the real byte estimate before
anything is written, and decides.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func

from src.bulletin.period import Period
from src.database.models import Article, Source

_LOG = logging.getLogger(__name__)

_CLOCK = func.coalesce(Article.published_at, Article.created_at)

#: Articles are read and written one at a time; this only bounds how many ids are
#: resolved per round trip, never how many are exported.
_PAGE = 200

DISCLOSURE = (
    "PLAINTEXT. Your corpus is encrypted at rest; this archive is not. It contains "
    "the full text and metadata of every article this edition's numbers were computed "
    "over. It is for YOUR archive and quality assurance — it is not the published "
    "document and is not meant to be shared. Store it where you would store the "
    "corpus itself."
)


def _period_article_ids(session, period: Period) -> list[int]:
    """Every non-quarantined article in the period, in a stable order.

    Ids only — the ids are small, and holding the full rows for a large period is
    exactly the whole-set materialisation this file exists to avoid.
    """
    lo = datetime.combine(period.start, datetime.min.time())
    hi = datetime.combine(period.end, datetime.min.time())
    rows = (
        session.query(Article.id)
        .filter(and_(_CLOCK >= lo, _CLOCK < hi, Article.quarantined.isnot(True)))
        .order_by(Article.id)
        .all()
    )
    return [int(r[0]) for r in rows]


def evidence_plan(session, period: Period, *, dest: str | os.PathLike | None = None) -> dict:
    """What an evidence archive for this period would contain, before writing it.

    The article count is EXACT. The byte figure is an ESTIMATE and says so: it is
    the stored content length summed, which is neither the compressed size on disk
    nor the compressed size in the ZIP. An estimate labelled as one is useful; an
    estimate presented as a size is a number that will be wrong.
    """
    ids = _period_article_ids(session, period)
    # Sample the first page rather than summing the whole period: the estimate is
    # labelled an estimate, so paying a full content scan to sharpen it would cost
    # a decrypt of everything to improve a number that is approximate either way.
    sample = ids[:_PAGE]
    try:
        content_bytes = int(
            session.query(func.sum(func.length(Article.content)))
            .filter(Article.id.in_(sample))
            .scalar()
            or 0
        )
        sampled = len(sample)
        estimate = int(content_bytes / sampled * len(ids)) if sampled else 0
    except Exception:  # noqa: BLE001 - an estimate that cannot be made is stated as unknown
        _LOG.warning("bulletin: evidence size estimate failed", exc_info=True)
        estimate, sampled = 0, 0

    out: dict[str, Any] = {
        "articles": len(ids),
        "estimated_bytes": estimate or None,
        "estimate_basis": (
            f"mean stored content length over the first {sampled} articles, times the "
            "exact article count; the archive is compressed, so the file will be smaller"
        )
        if sampled
        else "not measurable — the size is unknown, not zero",
        "period": period.to_dict(),
        "disclosure": DISCLOSURE,
    }
    if dest is not None:
        d = Path(dest)
        try:
            out["destination"] = str(d)
            out["destination_writable"] = d.is_dir() and os.access(d, os.W_OK)
            out["free_bytes"] = shutil.disk_usage(d).free if d.is_dir() else None
        except OSError as exc:
            out["destination_writable"] = False
            out["destination_error"] = str(exc)
    return out


def _toc(edition: dict) -> str:
    """A table of contents for the archive (§11 ruling 11).

    Built from what the edition actually contains — a fixed list would drift the
    moment a section is added or one of them skips.
    """
    lines = ["## Contents", "", "| file | what it is |", "|---|---|"]
    lines.append("| `edition.json` | the edition record these numbers come from |")
    lines.append("| `manifest.json` | every file in this archive with its SHA-256 |")
    lines.append("| `sources.json` | every source that contributed during the period |")
    lines.append("| `articles/<id>.json` | one file per article, full text and metadata |")
    lines.append("")
    lines.append("## Sections in this edition")
    lines.append("")
    for s in edition.get("sections") or []:
        key = s.get("section", "?")
        if s.get("error"):
            lines.append(f"- **{key}** — failed to build: `{s['error']}`")
        elif s.get("skipped"):
            lines.append(f"- **{key}** — skipped: {s['skipped']}")
        else:
            w = s.get("window") or {}
            lines.append(f"- **{key}** — window {w.get('days', '?')} days")
    return "\n".join(lines)


def _readme(edition: dict, period: Period, article_count: int) -> str:
    m = edition.get("masthead") or {}
    return "\n".join(
        [
            f"# Bulletin evidence archive — {period.start} to {period.last_day}",
            "",
            f"> **{DISCLOSURE}**",
            "",
            "This archive holds the articles this edition's numbers were computed over —",
            "**all of them**, not a sample. That is the point: the counts in the edition can",
            "be recomputed from what is here. A sampled archive could not do that.",
            "",
            f"- Period: `{period.start}` to `{period.end}` (end exclusive), {period.days} days",
            f"- Cadence: {period.cadence}",
            f"- Articles: {article_count:,}",
            f"- Sources that contributed: {m.get('sources_contributing', '—')}",
            f"- Generated: {datetime.now(UTC).isoformat()}",
            "",
            "Quarantined articles are excluded here exactly as they are excluded from the",
            "edition; the edition's disclosures state how many there were.",
            "",
            _toc(edition),
        ]
    )


def build_evidence_archive(
    session,
    edition: dict,
    period: Period,
    dest: str | os.PathLike,
    *,
    should_stop=None,
    progress_cb=None,
) -> dict:
    """Write the evidence archive for one edition. Returns a report.

    Streams: one article is read, serialised and written at a time, so peak memory
    is one article rather than a period of them. The ZIP is built under a temp name
    and moved into place only when complete — a half-written archive must never be
    mistaken for a finished one.

    ``should_stop`` is honoured between articles; a cancelled build removes its
    partial file rather than leaving something that looks like an archive.
    """
    d = Path(dest)
    if not d.is_dir():
        raise ValueError(f"destination is not a directory: {d}")

    ids = _period_article_ids(session, period)
    name = f"{period.last_day.strftime('%Y%m%d')}-OOS-{period.cadence}-evidence.zip"
    final = d / name
    tmp = d / (name + ".oopart")

    members: list[dict] = []
    written = 0
    cancelled = False

    def _add(zf: zipfile.ZipFile, arcname: str, text: str) -> None:
        data = text.encode("utf-8")
        zf.writestr(arcname, data)
        members.append(
            {
                "name": arcname,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            _add(zf, "README.md", _readme(edition, period, len(ids)))
            _add(zf, "edition.json", json.dumps(edition, indent=2, default=str))

            srcs = {
                int(sid): {
                    "id": int(sid),
                    "name": nm,
                    "domain": dom,
                    "country": ctry,
                    "source_type": st,
                }
                for sid, nm, dom, ctry, st in session.query(
                    Source.id, Source.name, Source.domain, Source.country, Source.source_type
                )
            }

            contributed: set[int] = set()
            for i in range(0, len(ids), _PAGE):
                if should_stop is not None and should_stop():
                    cancelled = True
                    break
                chunk = ids[i : i + _PAGE]
                for art in session.query(Article).filter(Article.id.in_(chunk)):
                    contributed.add(int(art.source_id))
                    _add(
                        zf,
                        f"articles/{art.id}.json",
                        json.dumps(
                            {
                                "id": int(art.id),
                                "title": art.title,
                                "url": art.url,
                                "canonical_url": art.canonical_url,
                                "source_id": int(art.source_id),
                                "source": srcs.get(int(art.source_id), {}).get("domain"),
                                "published_at": str(art.published_at) if art.published_at else None,
                                "created_at": str(art.created_at) if art.created_at else None,
                                "language": art.language,
                                "detected_language": art.detected_language,
                                "country": art.country,
                                "author": art.author,
                                "word_count": art.word_count,
                                "hash": art.hash,
                                "content": art.get_content(),
                            },
                            indent=2,
                            default=str,
                        ),
                    )
                    written += 1
                if progress_cb is not None:
                    try:
                        progress_cb(written, len(ids))
                    except Exception:  # noqa: BLE001 - progress never breaks the build
                        pass

            _add(
                zf,
                "sources.json",
                json.dumps(
                    [srcs[s] for s in sorted(contributed) if s in srcs], indent=2, default=str
                ),
            )
            # The manifest describes every member EXCEPT itself — a file cannot
            # carry its own hash. Said plainly rather than left to be noticed.
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "schema": "oo-bulletin-evidence-1",
                        "generated_at": datetime.now(UTC).isoformat(),
                        "period": period.to_dict(),
                        "articles": written,
                        "articles_expected": len(ids),
                        "complete": not cancelled,
                        "disclosure": DISCLOSURE,
                        "note": (
                            "manifest.json is not listed in its own members — a file "
                            "cannot contain its own hash"
                        ),
                        "members": members,
                    },
                    indent=2,
                    default=str,
                ),
            )
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    if cancelled:
        tmp.unlink(missing_ok=True)
        return {
            "cancelled": True,
            "articles_written": written,
            "articles_expected": len(ids),
            "note": "the partial archive was removed — it must never look like a finished one",
        }

    os.replace(tmp, final)
    return {
        "path": str(final),
        "filename": name,
        "articles": written,
        "articles_expected": len(ids),
        "complete": written == len(ids),
        "bytes": final.stat().st_size,
        "disclosure": DISCLOSURE,
        "method": (
            "every non-quarantined article in the period on the "
            "coalesce(published_at, created_at) clock, streamed one at a time"
        ),
    }
