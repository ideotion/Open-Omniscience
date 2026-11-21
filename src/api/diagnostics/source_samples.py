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
article is not skipped: it gets a manifest row saying so, and that row says WHY by a class (row 248): enabled, status,
``via:`` tag, has a feed, last qualification verdict, last feed HTTP status. The first zip also counts every never-collected
source in the set by class, so a disabled, unjudged candidate is told apart from a feed that fails.

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
from src.database.models import Article, FeedFetchState, Source, SourceQualificationAttempt
from src.database.session import get_db

from ._base import router

#: The cap on one zip, the Field data button's FIELD_PART_BYTES. Each part is sent back by hand through a chat upload; on
#: 2026-11-14 about half the parts would not upload, and every one that did was under 175 KB, so 400 KB (was 4 MB); 200 KB since 2026-11-15 (maintainer: «the loop has to
#: limit itself to 200kb files»).
#: Margin below is held back for the central directory and the compressed manifest (its rows are counted as written).
SAMPLE_ZIP_MAX_BYTES = 200 * 1000
_RESERVE_BYTES = 20 * 1000
#: One article's text is cut here, in UTF-8 bytes (and marked), so a single huge page cannot push a zip past the cap: the
#: first source of a part is always admitted, and its text compresses to well under this.
_TEXT_MAX_BYTES = 100 * 1000
#: Sources are read in batches of this many ids; one zip keeps reading batches until it is full or the set ends, so a long
#: run of never-collected sources no longer makes a part of its own (the 2026-11-14 press made five such parts in a row).
_BATCH = 5000

_SECRETISH = re.compile(r"pass(word|phrase)|secret|token|api_?key|cookie|credential", re.I)


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {"binary_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return value


#: A value that IS an address (a scheme and ``://``, or a scheme-relative ``//host``), with nothing around it: written as a report
#: writes an address (R734). A text that only CONTAINS one (an article's body) is not matched, so its words are left as stored.
_WHOLE_ADDRESS = re.compile(r"\s*(?:[A-Za-z][A-Za-z0-9+.\-]*:)?//\S*\s*")
#: A JSON text is read only when it looks like one, and only this long: a catalogue baseline is a few hundred bytes.
_JSON_TEXT_MAX = 64 * 1000


def _reported_addresses(value: Any, report: Callable[[str], Any]) -> Any:
    """``value`` with every string that is a whole address written through ``report``, at any depth of a list or a dict."""
    if isinstance(value, str):
        return report(value) if _WHOLE_ADDRESS.fullmatch(value) else value
    if isinstance(value, list):
        return [_reported_addresses(v, report) for v in value]
    if isinstance(value, dict):
        return {k: _reported_addresses(v, report) for k, v in value.items()}
    return value


def _reported_column(value: Any, report: Callable[[str], Any]) -> Any:
    """A column's value with any address in it written as a report writes it (row 104 on R734): a whole-address value, and every
    address inside a JSON text (``sources.catalog_baseline`` holds the catalogue's ``rss_url``). Any column, not a named list, so a
    column added later that holds an address is covered without anyone remembering it here."""
    if not isinstance(value, str):
        return value
    if _WHOLE_ADDRESS.fullmatch(value):
        return report(value)
    stripped = value.lstrip()
    if stripped[:1] in ("{", "[") and len(value) <= _JSON_TEXT_MAX:
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        written = _reported_addresses(parsed, report)
        return value if written == parsed else json.dumps(written, ensure_ascii=False)
    return value


def _row_dict(obj: Any, shown: dict[str, Callable[[Any], Any]] | None = None) -> dict[str, Any]:
    """Every mapped column of ``obj`` but a secret-looking one, each named in ``shown`` written through its function, and every
    other column's addresses as a report writes them (R734, :func:`_reported_column`). The body columns are left as stored: an
    article's text is the sample, and its own links are words in it."""
    from src.ingest.fetch_verdict import reported_url

    out: dict[str, Any] = {}
    state = inspect(obj)   # the instance state: its attrs read each loaded column without a dynamic getattr
    for prop in inspect(type(obj)).column_attrs:
        if _SECRETISH.search(prop.key):
            continue
        value = _plain(state.attrs[prop.key].value)
        if shown and prop.key in shown:
            out[prop.key] = shown[prop.key](value)
        elif prop.key in _BODY_COLUMNS:
            out[prop.key] = value
        else:
            out[prop.key] = _reported_column(value, reported_url)
    return out


def _shown_source_columns() -> dict[str, Callable[[Any], Any]]:
    """A source's columns that carry its feed address, each with what writes it as the app shows it (the independent read's M1 on
    R637), and since R734 as a report writes it: the address with its userinfo as ``***@`` and its query's values masked but for an
    allowlisted harmless one (``reported_url``) and a kept pre-R628 key the same way (``shown_feed_key``). Imported here, on a
    request, as the rest of this slice's work is."""
    from src.database.feed_key import shown_feed_key
    from src.ingest.fetch_verdict import reported_url

    return {"rss_url": reported_url, "feed_key": shown_feed_key}


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


#: WHY A SOURCE HAS NO ARTICLE (row 248, from row 39: about 25,000 sources of one press had never stored one, and the
#: compact list could not say why). Each never-collected row carries an index into ``classes``: whether collection may
#: take it (``enabled``, ``status``), where it came from (its ``via:`` tag), whether it has a feed address to try,
#: the last qualification verdict recorded for it, and the last HTTP status its feed answered (null = never fetched).
#: Booleans and short codes only: never an address (R734), never free text, so a row grows by a few bytes.
CLASS_COLUMNS = ["enabled", "status", "via", "has_feed", "last_qualification", "last_feed_status"]
_KNOWN_STATUS = ("qualified", "unqualified", "disqualified")
_VERDICT = re.compile(r"[a-z_]{1,20}")
#: The whole-set tally lists at most this many classes (about 80 bytes each), so it can never crowd the first zip.
_TALLY_MAX_CLASSES = 150
_FEED_STATUS_NOTE = ("last_feed_status: null = the collector never checked this source's feed; 0 = it checked and got "
                     "no HTTP status (a network error or a refusal); any other number is the HTTP status it saw")


def _known_via() -> frozenset[str]:
    """The provenances the app's own code stamps: the shipped catalogues, the generated law catalogue and
    world discovery. A catalogue entry can carry a ``via:`` tag of its own, so the value is matched against
    this fixed set and never copied out (review of #2203)."""
    from src.catalog.discover import _PROVENANCE as discovery
    from src.catalog.provenance_scope import APP_PROVIDED_PROVENANCES, CURATED_PROVENANCES

    return frozenset(APP_PROVIDED_PROVENANCES | CURATED_PROVENANCES | {discovery})


def _via(tags: str | None) -> str | None:
    """The source's provenance class from its whole ``via:`` tag: a known code, ``other`` for any other
    ``via:`` value, None when there is no ``via:`` tag. Never free text."""
    vias = [t.strip()[4:] for t in (tags or "").split(",") if t.strip().startswith("via:")]
    if not vias:
        return None
    known = sorted(v for v in vias if v in _known_via())
    return known[0] if known else "other"


def _last_by_source(db: Session, ids: list[int]) -> tuple[dict[int, str], dict[int, int | None]]:
    """``({source id: last qualification verdict}, {source id: last feed HTTP status})`` for these ids."""
    verdicts: dict[int, str] = {}
    for sid, verdict in db.execute(
        select(SourceQualificationAttempt.source_id, SourceQualificationAttempt.verdict)
        .where(SourceQualificationAttempt.source_id.in_(ids))
        .order_by(SourceQualificationAttempt.attempted_at, SourceQualificationAttempt.id)
    ).all():
        v = str(verdict or "")
        verdicts[int(sid)] = v if _VERDICT.fullmatch(v) else "other"
    fetched: dict[int, int | None] = {}
    for sid, status, checked in db.execute(
        select(FeedFetchState.source_id, FeedFetchState.last_status, FeedFetchState.last_checked_at)
        .where(FeedFetchState.source_id.in_(ids))
    ).all():
        if checked is not None or status is not None:
            fetched[int(sid)] = int(status) if isinstance(status, int) else 0
    return verdicts, fetched


def _class_of(enabled: Any, status: Any, tags: Any, rss_url: Any, verdict: str | None, feed_status: int | None) -> tuple:
    st = str(status or "")
    return (
        bool(enabled), st if st in _KNOWN_STATUS else "other", _via(tags),
        bool(rss_url), verdict, feed_status,
    )


def never_collected_in_set(db: Session) -> dict[str, Any]:
    """Counts only: every source with no stored article, by class, across the whole set (in the first zip)."""
    has_article = select(Article.id).where(Article.source_id == Source.id).exists()
    rows = db.execute(
        select(Source.id, Source.enabled, Source.status, Source.tags, Source.rss_url)
        .where(~has_article).order_by(Source.id)
    ).all()
    counts: dict[tuple, int] = {}
    for start in range(0, len(rows), 900):   # under SQLite's bound-parameter limit
        chunk = rows[start:start + 900]
        verdicts, fetched = _last_by_source(db, [int(r[0]) for r in chunk])
        for sid, enabled, status, tags, rss in chunk:
            k = _class_of(enabled, status, tags, rss, verdicts.get(int(sid)), fetched.get(int(sid)))
            counts[k] = counts.get(k, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], [str(x) for x in kv[0]]))
    kept, left = ordered[:_TALLY_MAX_CLASSES], ordered[_TALLY_MAX_CLASSES:]
    return {
        "note": "every source in the set with no stored article, counted by class; a source is collected only when it is "
                "enabled and qualified, so a disabled or unjudged one is a candidate, not a failing feed",
        "feed_status_note": _FEED_STATUS_NOTE,
        "sources": len(rows),
        "columns": CLASS_COLUMNS + ["sources"],
        "rows": [list(k) + [n] for k, n in kept],
        # the largest classes are listed; the rest are counted, so the tally stays a few KB whatever the set holds
        "classes_left_out": len(left),
        "sources_in_classes_left_out": sum(n for _, n in left),
    }


def build_sample_zip(
    db: Session, *, after: int, seed: int, cap: int, include_newsletters: bool = False,
) -> tuple[bytes, int | None, int, int]:
    """Return ``(zip bytes, next cursor or None, sources covered, sources in the whole set)``.

    A newsletter's body is written only when ``include_newsletters`` is true (R655)."""
    newsletter_sources = set() if include_newsletters else _newsletter_source_ids(db)
    total = db.execute(select(func.count()).select_from(Source)).scalar_one()
    buf = io.BytesIO()
    manifest: list[dict[str, Any]] = []
    empty: list[list[Any]] = []   # [source_id, domain, feed_key, class] for each source with no stored article
    classes: dict[tuple, int] = {}   # a never-collected source's class -> its index in the manifest's ``classes``
    class_counts: list[int] = []
    rows_bytes = 0   # the manifest's rows as written, before compression: a bound the compressed manifest stays under
    # the whole set's never-collected tally rides in the first zip only: counts, a few hundred bytes
    in_set = never_collected_in_set(db) if after == 0 else None
    if in_set is not None:
        rows_bytes += len(json.dumps(in_set, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
    last = None
    done = False
    full = False
    cursor = after
    shown = _shown_source_columns()
    shown_feed_key = shown["feed_key"]  # the manifest rows write a kept pre-R628 key masked, as the samples do
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        while not full and not done:
            ids = [r[0] for r in db.execute(
                select(Source.id).where(Source.id > cursor).order_by(Source.id).limit(_BATCH)
            ).all()]
            if not ids:
                done = True
                break
            verdicts: dict[int, str] = {}
            fetched: dict[int, int | None] = {}
            for start in range(0, len(ids), 900):   # under SQLite's bound-parameter limit
                v, f = _last_by_source(db, ids[start:start + 900])
                verdicts.update(v)
                fetched.update(f)
            for sid in ids:
                src = db.get(Source, sid)
                if src is None:
                    continue
                art, n = _pick(db, sid, seed)
                data = None
                row: dict[str, Any] | None = None
                if art is not None:
                    row = {"source_id": sid, "domain": src.domain, "feed_key": shown_feed_key(src.feed_key), "name": src.name, "articles_in_source": n}
                    a = _row_dict(art)
                    if not include_newsletters and (sid in newsletter_sources or art.newsletter_attached_via):
                        for col in _BODY_COLUMNS:
                            a[col] = None
                        a["body_withheld"] = "a newsletter: its body stays on this machine (OO_QUALITY_INCLUDE_NEWSLETTER_TEXT)"
                        row["body_withheld"] = True
                    text = a.get("content")
                    raw = text.encode("utf-8") if isinstance(text, str) else b""
                    if isinstance(text, str) and len(raw) > _TEXT_MAX_BYTES:
                        # cut by UTF-8 bytes, not characters: 200k CJK characters are 600 KB (the 2026-11-14 read)
                        a["content"] = raw[:_TEXT_MAX_BYTES].decode("utf-8", errors="ignore")
                        a["content_truncated_from_chars"] = len(text)
                        row["text_truncated"] = True
                    doc = {"source": _row_dict(src, shown), "article": a, "articles_in_source": n,
                           "pick": f"random.Random('{seed}:{sid}').randrange({n}) over articles ordered by id",
                           "raw_html": "not stored by this app (only extracted text is kept)"}
                    data = json.dumps(doc, ensure_ascii=False, default=str).encode("utf-8")
                    row["article_id"] = art.id
                    row["bytes"] = len(data)
                new_class: tuple | None = None
                if row is None:
                    k = _class_of(src.enabled, src.status, src.tags, src.rss_url, verdicts.get(sid), fetched.get(sid))
                    idx = classes.get(k)
                    if idx is None:
                        idx, new_class = len(classes), k
                    entry: Any = [sid, src.domain, shown_feed_key(src.feed_key), idx]
                else:
                    entry = row
                row_bytes = len(json.dumps(entry, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")) + 1
                if new_class is not None:   # a class is written once, beside its count
                    row_bytes += len(json.dumps(list(new_class) + [99999], separators=(",", ":"), default=str).encode("utf-8")) + 1
                used = buf.tell() + _RESERVE_BYTES + rows_bytes + row_bytes
                if (manifest or empty) and used + len(data or b"") > cap:   # empty sources count too: their rows add up
                    full = True   # nothing is added that could breach the cap; the next request resumes here
                    break
                rows_bytes += row_bytes
                if row is None:
                    if new_class is not None:
                        classes[new_class] = len(class_counts)
                        class_counts.append(0)
                    class_counts[entry[3]] += 1
                    empty.append(entry)
                else:
                    z.writestr(f"samples/source-{sid:07d}.json", data or b"")
                    manifest.append(row)
                last = sid
                db.expire_all()   # keep the session small across thousands of rows
            if not full:
                cursor = ids[-1]
                done = len(ids) < _BATCH
        # which data folder this came from: a random tag kept in it, nothing about its path
        from src.paths import instance_tag

        z.writestr("manifest.json", json.dumps({
            "temporary_diagnostic": True,
            "instance": instance_tag(),
            "seed": seed,
            "cursor_after": after,
            "last_source_id": last,
            "sources_in_this_zip": len(manifest) + len(empty),
            "sources_in_set": total,
            "sources": manifest,
            "sources_without_article": {
                "note": "no stored article for these sources",
                # a source id is this instance's own above the shipped catalogue (field report 2026-11-14 5.4):
                # domain + feed_key is what joins one instance's rows to another's
                "columns": ["source_id", "domain", "feed_key", "class"],
                "rows": empty,
                # ``class`` indexes these rows; why a source has no article is read here, not guessed (row 248)
                "classes": {
                    "feed_status_note": _FEED_STATUS_NOTE,
                    "columns": CLASS_COLUMNS + ["sources_in_this_zip"],
                    "rows": [list(k) + [class_counts[i]] for k, i in sorted(classes.items(), key=lambda kv: kv[1])],
                },
            },
            **({"never_collected_in_set": in_set} if in_set is not None else {}),
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if not done and last is None:
        done = True   # defensive: a zip that took nothing must not hand back the same cursor forever
    return buf.getvalue(), (None if done else last), len(manifest) + len(empty), total


# --------------------------------------------------------------------------- #
# Saved by the Field data button (R654, R664) -- delete only with its FIELD_DATA_EXPORTS entry.
# --------------------------------------------------------------------------- #
@router.get("/source-samples", dependencies=[Depends(refuse_cross_site_get)])
def source_samples(
    after: int = Query(0, ge=0),
    seed: int = Query(20261108),
    db: Session = Depends(get_db),
) -> Response:
    """ONE zip (<= 200 KB) holding one randomly chosen article per source for the next run of sources
    after ``after``; ``X-Source-Samples-Next`` carries the cursor for the next call (empty = done).
    Plain ``def`` -> threadpool. Read-only."""
    data, nxt, covered, total = build_sample_zip(
        db, after=after, seed=seed, cap=SAMPLE_ZIP_MAX_BYTES, include_newsletters=include_newsletter_text(),
    )
    from src.paths import instance_tag

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="oo-source-samples-{stamp}-after-{after:07d}.zip"',
            "X-Source-Samples-Next": "" if nxt is None else str(nxt),
            "X-Source-Samples-Covered": str(covered),
            "X-Source-Samples-Total": str(total),
            "X-OO-Instance": instance_tag(),
            "Access-Control-Expose-Headers": "X-Source-Samples-Next, X-Source-Samples-Covered, "
                                             "X-Source-Samples-Total, X-OO-Instance, Content-Disposition",
        },
    )
