"""One randomly chosen stored article per source, as zips of at most 4 MB (TEMPORARY diagnostic).

THROWAWAY: delete this slice, its entry in ``__init__.py`` / ``test_diagnostics_package_split.py``
and the Diagnostics button once the analyst has seen how articles and sources are ingested and
stored. Imported LAST, like every route added after the split, so no pinned position moves.

STATELESS BY DESIGN. Nothing is written to disk and nothing is kept between requests: each GET
returns ONE zip and a cursor (the last source id it covered) in ``X-Source-Samples-Next``; the page
asks again with ``after=<that id>`` until the header is empty. The pick for a source is a pure
function of ``(seed, source id)``, so a second walk with the same seed gives the same articles.

READ-ONLY, no network. Every mapped column of the article and of its source is exported (binary
columns are described by size + SHA-256, not inlined: the full text is already in ``content``).
Neither table holds a credential, a token or the passphrase; the check below refuses any column
whose name looks like one, so a future column cannot slip in unnoticed. A source with no stored
article is not skipped: it gets a manifest row saying so.
"""

from __future__ import annotations

import hashlib
import io
import json
import random
import re
import zipfile
from datetime import date, datetime
from typing import Any

from fastapi import Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from src.api.cross_site import refuse_cross_site_get
from src.database.models import Article, Source
from src.database.session import get_db

from ._base import router

#: The cap on one zip. Margin below is held back for the central directory and the manifest.
SAMPLE_ZIP_MAX_BYTES = 4 * 1000 * 1000
_RESERVE_BYTES = 120 * 1000
#: One article's text is cut here (and marked) so a single huge page can never push a zip past the cap.
_TEXT_MAX_CHARS = 1_000_000

_SECRETISH = re.compile(r"pass(word|phrase)|secret|token|api_?key|cookie|credential", re.I)


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {"binary_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return value


def _row_dict(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for prop in inspect(type(obj)).column_attrs:
        if _SECRETISH.search(prop.key):
            continue
        out[prop.key] = _plain(getattr(obj, prop.key))
    return out


def _pick(db: Session, source_id: int, seed: int) -> tuple[Article | None, int]:
    n = db.execute(
        select(func.count()).select_from(Article).where(Article.source_id == source_id)
    ).scalar_one()
    if not n:
        return None, 0
    offset = random.Random(f"{seed}:{source_id}").randrange(n)  # noqa: S311 -- sampling, not security
    art = db.execute(
        select(Article).where(Article.source_id == source_id).order_by(Article.id).offset(offset).limit(1)
    ).scalar_one_or_none()
    return art, n


def build_sample_zip(db: Session, *, after: int, seed: int, cap: int) -> tuple[bytes, int | None, int, int]:
    """Return ``(zip bytes, next cursor or None, sources covered, sources in the whole set)``."""
    total = db.execute(select(func.count()).select_from(Source)).scalar_one()
    ids = [r[0] for r in db.execute(
        select(Source.id).where(Source.id > after).order_by(Source.id).limit(5000)
    ).all()]
    buf = io.BytesIO()
    manifest: list[dict[str, Any]] = []
    last = None
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for sid in ids:
            src = db.get(Source, sid)
            if src is None:
                continue
            art, n = _pick(db, sid, seed)
            row: dict[str, Any] = {"source_id": sid, "domain": src.domain, "name": src.name,
                                   "articles_in_source": n}
            if art is None:
                row["article_id"] = None
                row["note"] = "no stored article for this source"
                data = None
            else:
                a = _row_dict(art)
                text = a.get("content")
                if isinstance(text, str) and len(text) > _TEXT_MAX_CHARS:
                    a["content"] = text[:_TEXT_MAX_CHARS]
                    a["content_truncated_from_chars"] = len(text)
                    row["text_truncated"] = True
                doc = {"source": _row_dict(src), "article": a, "articles_in_source": n,
                       "pick": f"random.Random('{seed}:{sid}').randrange({n}) over articles ordered by id",
                       "raw_html": "not stored by this app (only extracted text is kept)"}
                data = json.dumps(doc, ensure_ascii=False, indent=1, default=str).encode("utf-8")
                row["article_id"] = art.id
                row["bytes"] = len(data)
            used = buf.tell() + _RESERVE_BYTES + 400 * (len(manifest) + 1)
            if manifest and used + len(data or b"") > cap:   # empty sources count too: their manifest rows add up
                break   # nothing is added that could breach the cap; the next request resumes here
            if data is not None:
                z.writestr(f"samples/source-{sid:07d}.json", data)
            manifest.append(row)
            last = sid
            db.expire_all()   # keep the session small across thousands of rows
        z.writestr("manifest.json", json.dumps({
            "temporary_diagnostic": True,
            "seed": seed,
            "cursor_after": after,
            "sources_in_this_zip": len(manifest),
            "sources_in_set": total,
            "sources": manifest,
        }, ensure_ascii=False, indent=1).encode("utf-8"))
    done = last is None or last == ids[-1] and len(ids) < 5000
    return buf.getvalue(), (None if done else last), len(manifest), total


# --------------------------------------------------------------------------- #
# TEMPORARY / REMOVABLE diagnostic -- delete with its Diagnostics button.
# --------------------------------------------------------------------------- #
@router.get("/source-samples", dependencies=[Depends(refuse_cross_site_get)])
def source_samples(
    after: int = Query(0, ge=0),
    seed: int = Query(20261108),
    db: Session = Depends(get_db),
) -> Response:
    """ONE zip (<= 4 MB) holding one randomly chosen article per source for the next run of sources
    after ``after``; ``X-Source-Samples-Next`` carries the cursor for the next call (empty = done).
    Plain ``def`` -> threadpool. Read-only."""
    data, nxt, covered, total = build_sample_zip(db, after=after, seed=seed, cap=SAMPLE_ZIP_MAX_BYTES)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="oo-source-samples-{stamp}-after-{after:07d}.zip"',
            "X-Source-Samples-Next": "" if nxt is None else str(nxt),
            "X-Source-Samples-Covered": str(covered),
            "X-Source-Samples-Total": str(total),
            "Access-Control-Expose-Headers": "X-Source-Samples-Next, X-Source-Samples-Covered, "
                                             "X-Source-Samples-Total, Content-Disposition",
        },
    )
