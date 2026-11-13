"""One randomly chosen stored article per source, as zips of at most 4 MB (saved by the Field data button).

KEPT FOR THE FIELD DATA BUTTON (R664, 2026-11-13): it was a temporary export with its own
Diagnostics button (R587, queue item 37); that button went when the ONE Field data button
replaced it (R654, #1910), and ``FIELD_DATA_EXPORTS`` in ``src/static/app-diagnostics.js`` walks
this route. Delete it only together with that entry. Imported LAST, like every route added after
the split, so no pinned position moves.

STATELESS BY DESIGN. Nothing is written to disk and nothing is kept between requests: each GET
returns ONE zip and a cursor (the last source id it covered) in ``X-Source-Samples-Next``; the page
asks again with ``after=<that id>`` until the header is empty. The pick for a source is a pure
function of ``(seed, source id)``, so a second walk with the same seed gives the same articles.

READ-ONLY, no network. Every mapped column of the article and of its source is exported (binary
columns are described by size + SHA-256, not inlined: the full text is already in ``content``).
Neither table holds a token or the passphrase; the check below refuses any column whose name looks
like one, so a future column cannot slip in unnoticed. A source's feed address CAN hold a user name
and password (R637), and a key stored before R628 keeps them (R634): the two columns that carry the
address are written as the app shows it (``_SHOWN_SOURCE_COLUMNS``, the independent read's M1 on
R637), and a test pins the source's column list, so a new column is a decision, never a default.
The article's columns are written as stored (its ``url`` as given, R621). A source with no stored
article is not skipped: it gets a manifest row saying so.

NEWSLETTER BODIES STAY HOME (R655, 2026-11-09), by the same gate and the same switch as
``/source-quality``: an article is a newsletter when its source is one of the mailbox sources
(``NEWSLETTER_SOURCE_DOMAINS``) or it was filed under a publisher by the auto-attach
(``newsletter_attached_via``, Q1151), and its body (``content`` and ``compressed_content``) leaves
only when ``OO_QUALITY_INCLUDE_NEWSLETTER_TEXT`` is set. Its other columns are written, as there.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import re
import zipfile
from collections.abc import Callable
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


def _row_dict(obj: Any, shown: dict[str, Callable[[Any], Any]] | None = None) -> dict[str, Any]:
    """Every mapped column of ``obj`` but a secret-looking one, each named in ``shown`` written through its function."""
    out: dict[str, Any] = {}
    state = inspect(obj)   # the instance state: its attrs read each loaded column without a dynamic getattr
    for prop in inspect(type(obj)).column_attrs:
        if _SECRETISH.search(prop.key):
            continue
        value = _plain(state.attrs[prop.key].value)
        out[prop.key] = shown[prop.key](value) if shown and prop.key in shown else value
    return out


def _shown_source_columns() -> dict[str, Callable[[Any], Any]]:
    """A source's columns that carry its feed address, each with what writes it as the app shows it (the independent read's M1 on
    R637): the address with its userinfo as ``***@`` (``shown_url``, the answers' form) and a kept pre-R628 key the same way
    (``shown_feed_key``). Imported here, on a request, as the rest of this slice's work is."""
    from src.database.feed_key import shown_feed_key
    from src.ingest.fetch_verdict import shown_url

    return {"rss_url": shown_url, "feed_key": shown_feed_key}


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


#: The columns that hold a newsletter's body: withheld unless the switch is on (R655).
_BODY_COLUMNS = ("content", "compressed_content")


def include_newsletter_text() -> bool:
    """The ``/source-quality`` switch, read the same way: off unless the operator set it."""
    return os.getenv("OO_QUALITY_INCLUDE_NEWSLETTER_TEXT", "").strip().lower() in ("1", "true", "yes", "on")


def _newsletter_source_ids(db: Session) -> set[int]:
    from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

    return {int(sid) for (sid,) in db.execute(
        select(Source.id).where(Source.domain.in_(NEWSLETTER_SOURCE_DOMAINS))
    ).all()}


def build_sample_zip(
    db: Session, *, after: int, seed: int, cap: int, include_newsletters: bool = False,
) -> tuple[bytes, int | None, int, int]:
    """Return ``(zip bytes, next cursor or None, sources covered, sources in the whole set)``.

    A newsletter's body is written only when ``include_newsletters`` is true (R655)."""
    newsletter_sources = set() if include_newsletters else _newsletter_source_ids(db)
    total = db.execute(select(func.count()).select_from(Source)).scalar_one()
    ids = [r[0] for r in db.execute(
        select(Source.id).where(Source.id > after).order_by(Source.id).limit(5000)
    ).all()]
    buf = io.BytesIO()
    manifest: list[dict[str, Any]] = []
    last = None
    shown = _shown_source_columns()
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
                if not include_newsletters and (sid in newsletter_sources or art.newsletter_attached_via):
                    for col in _BODY_COLUMNS:
                        a[col] = None
                    a["body_withheld"] = "a newsletter: its body stays on this machine (OO_QUALITY_INCLUDE_NEWSLETTER_TEXT)"
                    row["body_withheld"] = True
                text = a.get("content")
                if isinstance(text, str) and len(text) > _TEXT_MAX_CHARS:
                    a["content"] = text[:_TEXT_MAX_CHARS]
                    a["content_truncated_from_chars"] = len(text)
                    row["text_truncated"] = True
                doc = {"source": _row_dict(src, shown), "article": a, "articles_in_source": n,
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
# Saved by the Field data button (R654, R664) -- delete only with its FIELD_DATA_EXPORTS entry.
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
    data, nxt, covered, total = build_sample_zip(
        db, after=after, seed=seed, cap=SAMPLE_ZIP_MAX_BYTES, include_newsletters=include_newsletter_text(),
    )
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
