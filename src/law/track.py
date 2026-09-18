"""
Law change-tracking — baseline snapshot → per-change diff → honest flag.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mirrors the Wikipedia tracker (``src/wiki/track.py``) for arbitrary legal documents
fetched through the **ethical, robots-fail-closed** fetcher. The first successful fetch
is the immutable **baseline** ("the law as it stood on date X"); every later fetch whose
*normalised visible text* differs records a :class:`LawRevision` carrying the byte delta,
a capped unified **diff** against the baseline, and an honest large-change flag (reusing
the wiki flagging thresholds — mutualisation). Nothing is interpreted; a change is
*surfaced*, never judged. A fetch error degrades **loudly** (recorded status), never
fabricated.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import re
from datetime import UTC, datetime

from src.database.models import LawDocument, LawRevision
from src.database.write import is_integrity_error
from src.law.model import mint_lane_key
from src.services.boilerplate import BOILERPLATE_STRIP_VERSION
from src.wiki.flagging import flag_revision

_LOG = logging.getLogger(__name__)

_MIN_TEXT = 200  # below this we treat extraction as failed, not a real document
_MAX_DIFF_LINES = 4000  # cap stored diff size (bounded, like the crawler)
_WS_RE = re.compile(r"[ \t]+")


def _lines_of(soup) -> str:
    lines = [_WS_RE.sub(" ", ln).strip() for ln in soup.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def page_text(html: str, *, legacy: bool = False) -> str:
    """Normalised visible text of an HTML page — a stable basis for change detection.

    Removes chrome the markup DECLARES to be chrome (see
    :mod:`src.services.boilerplate`) and collapses whitespace, so a real amendment
    produces a diff while cosmetic re-rendering does not.

    ``legacy=True`` reproduces the reading this function gave before the strip stage
    (script/style/nav/footer/header only). That is not a fallback: it is how
    :func:`check_document` tells "our extractor improved" from "the law changed" on the
    one poll where both could look identical.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover - bs4 is a core dependency
        return re.sub(r"<[^>]+>", " ", html)
    from src.services.boilerplate import strip_boilerplate, strip_enabled, strip_legacy

    soup = BeautifulSoup(html, "html.parser")
    if legacy or not strip_enabled():
        strip_legacy(soup)
    else:
        strip_boilerplate(soup)
    return _lines_of(soup)


def _diff(baseline: str, new: str) -> str:
    """A capped unified diff of baseline → new (added/removed lines only)."""
    diff_lines = list(
        difflib.unified_diff(baseline.splitlines(), new.splitlines(), lineterm="", n=1)
    )
    changed = [ln for ln in diff_lines if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
    return "\n".join(changed[:_MAX_DIFF_LINES])


def _document_text(result, *, retrieved_on: str | None = None) -> tuple[str | None, str, object | None]:
    """The document's normalised visible text, an honest status, and the parse behind it.

    THE THIRD ELEMENT IS THE L0 DATE FIX (Q917). Until 2026-09-18 this function
    returned ``parsed.text`` and dropped the :class:`~src.law.adapters.ParsedLaw`
    it came from, so the three dates the adapter had already read -- the whole
    reason the date discipline in its package docstring exists -- reached nothing
    that could store them, and the reader's only date was the day we captured the
    document. It is ``None`` for every non-CLML body, which is the honest state:
    an HTML page states no dates this adapter can read, and inventing one from the
    fetch is exactly the collapse the discipline forbids.

    A PDF body (detected by the ``%PDF`` magic bytes or the content-type) is
    routed to the optional PDF extractor, which returns ``(None, reason)`` for a
    scanned / encrypted / mis-decoded file — degrade LOUDLY, never a fabricated
    body.

    A CLML body (legislation.gov.uk's structured XML, served at ``.../data.xml``)
    is READ rather than reconstructed. ``src/law/adapters/clml.py`` was written
    for exactly this — adapter #1 of the law brief's S6, ruled adapter-first —
    and until 2026-09-09 it had no caller at all: ``track.py`` sent every
    non-PDF body through the HTML boilerplate strip, so a document available as
    marked-up law was reduced by guessing which parts of a web page were chrome.

    THE ADAPTER IS ITS OWN GATE, which is why this branch can be attempted on
    any XML-ish body. ``parse_clml`` refuses a root element it does not know
    ("an HTML error page, a search result, a redirect notice — all parse as
    'some XML'"), refuses malformed or unsafe XML, and refuses when recovered
    text falls below ``TEXT_RECOVERY_FLOOR`` — so a refusal is cheap, happens at
    the root check, and simply falls back to the HTML path. Nothing is decided
    from the URL: a host allow-list would send the site's own HTML pages into an
    XML parser and would miss the same markup served from anywhere else.

    The status is ``"clml"``, deliberately NOT ``"ok"``. The caller uses
    ``reason == "ok"`` to decide whether it holds HTML worth re-checking for an
    extractor change; XML has no chrome to strip, so claiming "ok" here would
    put a structured document through a comparison written for web pages.
    """
    raw = getattr(result, "raw_content", None)
    content_type = getattr(result, "content_type", "") or ""
    from src.ingest.pdf import looks_like_pdf

    if looks_like_pdf(raw, content_type=content_type):
        from src.ingest.pdf import extract_pdf_text

        pdf_text, pdf_reason = extract_pdf_text(raw)
        return pdf_text, pdf_reason, None

    body = result.content
    if _looks_like_xml(body, content_type=content_type):
        from src.law.adapters import AdapterRefusal
        from src.law.adapters.clml import parse_clml

        try:
            parsed = parse_clml(body, retrieved_on=retrieved_on)
        except AdapterRefusal:
            pass  # not CLML (or not enough of it) — the HTML path below is correct
        except Exception:  # noqa: BLE001 - an adapter must never break tracking
            _LOG.warning("law: CLML adapter raised; falling back to HTML", exc_info=True)
        else:
            return parsed.text, "clml", parsed

    return page_text(body), "ok", None


def _looks_like_xml(body, *, content_type: str) -> bool:
    """Cheap pre-check so an ordinary HTML page is never handed to an XML parser.

    Deliberately permissive on the content type (a server may send
    ``text/plain`` for a ``.xml``) and deliberately strict on the body: it must
    actually START with a declaration or a tag. ``parse_clml`` does the real
    deciding; this only avoids paying for a parse on every web page.
    """
    if not isinstance(body, str) or not body:
        return False
    head = body.lstrip()[:200].lower()
    if not head.startswith(("<?xml", "<legislation", "<clml")):
        return False
    return "html" not in (content_type or "").lower() or "xml" in (content_type or "").lower()


def _adapter_date(parsed: object | None, field: str) -> str | None:
    """One date off a :class:`~src.law.adapters.ParsedLaw`, or ``None``.

    ``None`` here always means *the document did not state it* — there is no fallback
    chain between the three dates, which is the whole point of the adapter's date
    discipline: falling back is how a capture date becomes a publication date.
    """
    if parsed is None:
        return None
    value = getattr(parsed, field, None)
    return value if isinstance(value, str) and value.strip() else None


def _diff_anchor(session, doc: LawDocument) -> tuple[LawRevision | None, str, str]:
    """The revision a new change is measured against, the text to measure against, and
    the NAME of that anchor.

    Q917 anchors a change on the PREVIOUS revision. Three things stop that being a
    one-liner, and each produces a DIFFERENT recorded basis rather than a silent fallback.

    ``"previous"`` — the ordinary case: the previous revision's stored ``full_text``, and
    ``diff_base_revision_id`` names it. ``latest_text_revid`` is the document's own pointer
    at its newest revision and is the right first question; it can be NULL on a document
    baselined before that column shipped, so the newest row by ``(observed_at, id)`` is the
    fallback. Ordering on ``id`` as well as ``observed_at`` matters — two revisions can
    share an observed instant, and ``ORDER BY observed_at`` alone then returns whichever
    the planner likes, which is a resume-cursor-shaped hazard on a table that grows.

    ``"previous-text"`` — the document's materialised ``latest_text`` differs from every
    stored revision's text. This is the RE-EXTRACTION path directly above: when the
    boilerplate strip improves, the tracker deliberately records NO revision (nothing was
    amended) and re-baselines, so the text the document held before this change is real
    and correct while no revision reproduces it byte for byte. Anchoring on the stale
    revision instead would charge the next genuine amendment with the chrome the strip
    removed. ``diff_base_revision_id`` is NULL here because there is honestly no revision
    to name.

    ``"baseline"`` — neither is available: the previous revision carries no stored
    ``full_text`` (a row from before that column shipped) and the document has no
    materialised latest text either. The baseline is a different quantity and saying so is
    the whole reason the basis is stored.

    Returns ``(previous_revision_or_None, text_to_measure_against, basis)``.
    """
    prev: LawRevision | None = None
    if doc.latest_text_revid:
        prev = session.query(LawRevision).filter_by(id=doc.latest_text_revid).first()
    if prev is None or prev.document_id != doc.id:
        prev = (
            session.query(LawRevision)
            .filter_by(document_id=doc.id)
            .order_by(LawRevision.observed_at.desc(), LawRevision.id.desc())
            .first()
        )
    if prev is not None and prev.full_text is not None:
        if doc.latest_text is None or doc.latest_text == prev.full_text:
            return prev, prev.full_text, "previous"
        return prev, doc.latest_text, "previous-text"
    if doc.latest_text is not None:
        return prev, doc.latest_text, "previous-text"
    return prev, (doc.baseline_text or ""), "baseline"


def baseline_diff(doc: LawDocument, revision: LawRevision) -> dict:
    """The baseline comparison as a DERIVED view, computed on demand (Q917).

    The stored ``diff``/``delta_bytes`` measure a revision against the one before it, which
    is the question a reader of an amendment history asks. "How far has this document
    moved since we first saw it" is a different and also useful question, and it needs no
    second stored column: both texts are already on disk, so it is derived here.

    REFUSES RATHER THAN GUESSES. A revision with no stored ``full_text`` (recorded before
    that column shipped) cannot be compared to anything, and a document with no captured
    baseline has nothing to compare against — each returns ``available: False`` with the
    reason named, never a diff of one side against the empty string, which would render as
    "the entire document was added".
    """
    if revision.full_text is None:
        return {
            "available": False,
            "reason": "this revision was recorded before the full text of each version was stored",
        }
    if doc.baseline_text is None:
        return {"available": False, "reason": "no baseline text has been captured for this document"}
    return {
        "available": True,
        "delta_bytes": len(revision.full_text) - len(doc.baseline_text),
        "diff": _diff(doc.baseline_text, revision.full_text),
        "method": (
            "Derived on demand: this version's stored text compared with the document's "
            "immutable baseline. The amendment history above measures each change against "
            "the version before it, which is a different quantity."
        ),
    }


def _ingest_to_corpus(session, doc: LawDocument, extractor) -> None:
    """Ingest the document's newest text into the corpus (laws are Articles too).

    Best-effort by construction: the text + revision are ALREADY committed before
    this runs, so a corpus-sync failure must NEVER block or roll back tracking —
    it is rolled back locally and logged (the wiki-corpus pattern).
    """
    try:
        from src.law.corpus import sync_law_to_corpus

        sync_law_to_corpus(session, doc, extractor=extractor)
    except Exception:  # noqa: BLE001 - corpus ingest is best-effort, never blocks tracking
        session.rollback()
        _LOG.warning("law corpus ingest failed for doc %s", doc.id, exc_info=True)


def _record_lane(doc: LawDocument, revision: LawRevision | None, parsed: object | None) -> str:
    """Mirror this pass into ``law.db``'s metadata model, and never let it break tracking.

    Imported lazily: the lane opens a second encrypted database, and ``track.py`` is on
    the collect path of an install that may never have tracked a law. The bridge itself
    returns a named outcome rather than raising -- see ``src/law/lane_sync.py`` for why
    the corpus write is the primary record and this one is not.
    """
    from src.law.lane_sync import record_document

    provisions = getattr(parsed, "provisions", None)
    return record_document(doc, revision, parsed, provisions=provisions)


def track_document(session, fetcher, doc: LawDocument, *, extractor=None) -> dict:
    """Fetch one tracked legal document and record a baseline or a change. Honest status.

    On a successful baseline / change / revert (and a first-time backfill on an
    unchanged poll) the document's NEWEST text is materialised on the document
    (``latest_text`` / ``latest_text_revid``) and, for a new version, stored in
    full on the :class:`LawRevision` (``full_text``) — the versioned-sources
    model (a law = an Article + a linked revision/audit trail). The text is then
    ingested into the corpus through the one ``index_article`` hook.
    """
    from src.ingest import FetchError

    now = datetime.now(UTC)
    doc.last_checked_at = now
    try:
        # require_html=False so an official-gazette PDF is not rejected up front;
        # keep_bytes so the PDF extractor sees the real bytes (the text decode
        # destroys them). Both are additive — a fetcher double without keep_bytes
        # simply won't set raw_content, and the HTML path is unchanged.
        result = fetcher.fetch(doc.url, require_html=False, keep_bytes=True)
    except FetchError as exc:
        doc.last_status = f"fetch error: {exc}"
        session.commit()
        return {"document_id": doc.id, "status": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - record, never crash the batch
        doc.last_status = f"error: {exc}"
        session.commit()
        return {"document_id": doc.id, "status": "error", "detail": str(exc)}

    text, reason, parsed = _document_text(result, retrieved_on=now.date().isoformat())
    # Kept for the extractor-change check below. Only HTML has chrome to strip, so a
    # PDF body leaves this None and the check is simply skipped -- never a re-baseline
    # decided on a comparison we could not make.
    raw_html = result.content if reason == "ok" else None
    if not text or len(text) < _MIN_TEXT:
        # Degrade loudly: a scanned/encrypted/mis-decoded PDF (or too-short HTML)
        # records WHY and stores NO body — never a fabricated one.
        doc.last_status = reason if reason != "ok" else "no usable text extracted"
        session.commit()
        return {"document_id": doc.id, "status": "empty", "detail": doc.last_status}

    h = hashlib.sha256(text.encode("utf-8")).hexdigest()

    # L0 defect 3 (Q917): the adapter's dates reach storage. FILL-A-NULL on the document,
    # because a later parse stating a DIFFERENT enactment date is two readings disagreeing
    # and picking the newer one silently would re-date a statute. `valid_on` is per-version
    # and is written on the revision below, where it describes the text it came from.
    valid_on = _adapter_date(parsed, "valid_on")
    enacted_on = _adapter_date(parsed, "enacted_on")
    if enacted_on and not doc.enacted_on:
        doc.enacted_on = enacted_on

    # Q905 = a's second clause: "an observed snapshot without official dating becomes a
    # version dated by observation and labelled so". The LABEL is what makes the fallback
    # honest -- without it a surface reading `valid_on or observed_at` would print a
    # capture date as a consolidation date, which is the fabrication the ruling names.
    valid_on_dating = "official" if valid_on else "observed"

    # The stable link into `law.db`. Minted ONCE per document and kept: a new key on a
    # later pass would orphan the identity group, the licence and the provenance this
    # document already has. See src/law/lane_models.py for why it is a string.
    if not doc.lane_key:
        doc.lane_key = mint_lane_key()

    # First sighting → immutable baseline + a baseline revision (delta 0, not flagged).
    if doc.baseline_text is None:
        doc.baseline_text = text
        doc.baseline_hash = h
        doc.last_hash = h
        doc.last_size = len(text)
        doc.last_status = "baseline captured"
        doc.latest_text = text  # the CURRENT text, shown without replaying diffs
        rev = LawRevision(
            document_id=doc.id,
            observed_at=now,
            content_hash=h,
            size=len(text),
            delta_bytes=0,
            full_text=text,  # the exact baseline text, locally reconstructable
            flagged=False,
            # "first", never "baseline". They are different facts and one value cannot
            # carry both: on a LATER row "baseline" means "measured against the first
            # capture" (the fallback when the previous revision has no stored text),
            # while this row IS that first capture and has nothing earlier to measure
            # against at all. Reusing the value would put two meanings under one key on
            # the exact column added to stop that happening.
            diff_basis="first",
            valid_on=valid_on,
            valid_on_dating=valid_on_dating,
            lane_key=mint_lane_key(),
        )
        session.add(rev)
        try:
            session.flush()  # materialise rev.id so latest_text_revid can anchor it
            doc.latest_text_revid = rev.id
            session.commit()
        except Exception as exc:  # noqa: BLE001 - is_integrity_error is the precise discriminator
            # Audit finding 2026-07-17: `except IntegrityError` (sqlalchemy.exc) never
            # matched on the encrypted (sqlcipher3) store, whose driver raises its OWN
            # unwrapped exception class -- the same cross-driver divergence already
            # fixed for is_locked_error/classify_restore_error/_is_integrity_error.
            # A genuinely unexpected failure must still surface, never be swallowed.
            if not is_integrity_error(exc):
                raise
            # This (document_id, content_hash) baseline revision already exists (a
            # concurrent pass or a re-process). IDEMPOTENT: roll back the poisoned
            # transaction so it can NEVER roll back the whole scrape pass, then cache
            # the baseline so the next pass takes the fast "unchanged" path.
            session.rollback()
            doc.baseline_text = text
            doc.baseline_hash = h
            doc.last_checked_at = now
            doc.last_hash = h
            doc.last_size = len(text)
            doc.last_status = "baseline already recorded"
            doc.latest_text = text
            existing = (
                session.query(LawRevision)
                .filter_by(document_id=doc.id, content_hash=h)
                .first()
            )
            if existing:  # keep any prior anchor rather than nulling it on a miss
                doc.latest_text_revid = existing.id
            session.commit()
            _ingest_to_corpus(session, doc, extractor)
            return {"document_id": doc.id, "status": "duplicate"}
        _ingest_to_corpus(session, doc, extractor)
        _record_lane(doc, rev, parsed)
        return {"document_id": doc.id, "status": "baseline", "size": len(text)}

    if h == doc.last_hash:
        doc.last_status = "unchanged"
        # Backfill the materialised text for a document baselined before this
        # feature shipped, then ingest it once (idempotent: an unchanged corpus
        # hash re-index is skipped, so a steady-state poll adds no work).
        backfilled = doc.latest_text is None
        if backfilled:
            doc.latest_text = text
            doc.latest_text_revid = doc.latest_text_revid or (
                session.query(LawRevision.id)
                .filter_by(document_id=doc.id, content_hash=h)
                .order_by(LawRevision.id.asc())
                .limit(1)
                .scalar()
            )
        session.commit()
        if backfilled:
            _ingest_to_corpus(session, doc, extractor)
        # An UNCHANGED document still gets its lane row. This is the path that carries
        # the 23 documents a fresh install already tracks into the model: they change
        # rarely, and a metadata model that only reached a law on the day it was amended
        # would leave most of the corpus without an identity, a licence or a provenance
        # for as long as the law stood.
        _record_lane(doc, None, parsed)
        return {"document_id": doc.id, "status": "unchanged"}

    # THE EXTRACTOR CHANGED, NOT THE LAW. The boilerplate strip removes chrome this
    # function used to keep, so on the ONE poll after it ships every tracked document's
    # text legitimately changes -- and the code below would read that as an amendment,
    # write a LawRevision for it, and (chrome on a real portal runs past
    # LARGE_CHANGE_BYTES) very likely FLAG it as a large removal. A fabricated
    # amendment, flagged, on a legal audit trail whose whole value is being trustworthy.
    #
    # So ask the question directly instead of guessing: re-read the SAME bytes the way
    # this function used to, and see whether THAT still matches what we stored. If it
    # does, the page did not change and the delta is entirely ours -- re-baseline, and
    # record no revision, because none happened. If it does not, the page really did
    # change too, and it falls through to the normal path below: a real amendment is
    # never silently absorbed into the re-baseline.
    #
    # No schema column is needed for this: the legacy reading IS the stamp, derived
    # from the bytes in hand. It is also self-limiting -- once re-baselined, last_hash
    # holds a stripped hash, which a legacy reading can never equal again.
    if raw_html is not None and doc.baseline_text is not None:
        legacy = page_text(raw_html, legacy=True)
        if hashlib.sha256(legacy.encode("utf-8")).hexdigest() == doc.last_hash:
            removed = len(doc.baseline_text) - len(text)
            doc.baseline_text = text
            doc.baseline_hash = h
            doc.last_hash = h
            doc.last_size = len(text)
            doc.latest_text = text
            doc.last_status = (
                f"re-read with {BOILERPLATE_STRIP_VERSION} "
                f"({removed:+d} bytes of page chrome); the document itself is unchanged"
            )
            session.commit()
            _ingest_to_corpus(session, doc, extractor)
            return {
                "document_id": doc.id,
                "status": "re-extracted",
                "chrome_bytes_removed": removed,
            }

    # A revision with this exact text was seen before → a revert to a known version.
    seen = session.query(LawRevision).filter_by(document_id=doc.id, content_hash=h).first()
    if seen is not None:
        doc.last_hash = h
        doc.last_size = len(text)
        doc.last_status = "reverted to a previously-seen version"
        doc.latest_text = text
        doc.latest_text_revid = seen.id
        session.commit()
        _ingest_to_corpus(session, doc, extractor)
        return {"document_id": doc.id, "status": "reverted"}

    # A genuine new version. L0 defect 2 (Q917): the change is measured against the
    # PREVIOUS REVISION, not the immutable baseline. Anchoring on the baseline made
    # `delta_bytes` cumulative -- a document that grows 100 bytes per amendment reported
    # +100, +200, +300 on rows that each read as one amendment -- and made
    # `flag_revision` fire forever once a document had drifted far from its first capture,
    # because the quantity it judges never came back down. The baseline comparison is not
    # lost: `baseline_diff()` derives it on demand from the stored `full_text`.
    #
    # THE ANCHOR IS NAMED, NEVER GUESSED. A previous revision that carries no stored
    # `full_text` (a row recorded before that column shipped) cannot be measured against,
    # so this falls back to the baseline AND records `diff_basis="baseline"` -- a reader
    # can then see that this one row measures a different quantity from its neighbours.
    prev_rev, base_text, basis = _diff_anchor(session, doc)
    delta = len(text) - len(base_text)
    flag = flag_revision(delta_bytes=delta)
    rev = LawRevision(
        document_id=doc.id,
        observed_at=now,
        content_hash=h,
        size=len(text),
        delta_bytes=delta,
        diff=_diff(base_text, text),
        full_text=text,  # the exact new version, locally reconstructable
        flagged=flag.flagged,
        flag_reasons=flag.reasons_csv() if flag.flagged else None,
        diff_basis=basis,
        diff_base_revision_id=prev_rev.id if (prev_rev is not None and basis == "previous") else None,
        valid_on=valid_on,
        valid_on_dating=valid_on_dating,
        lane_key=mint_lane_key(),
    )
    session.add(rev)
    doc.last_hash = h
    doc.last_size = len(text)
    # The sentence names its own anchor, because the number means a different thing under
    # each one and a status that said "vs baseline" while measuring the previous revision
    # would be the more convincing kind of wrong.
    anchor = "baseline" if basis == "baseline" else "the previous version"
    doc.last_status = f"changed ({delta:+d} bytes vs {anchor})"
    doc.latest_text = text
    try:
        session.flush()  # materialise rev.id so latest_text_revid can anchor it
        doc.latest_text_revid = rev.id
        session.commit()
    except Exception as exc:  # noqa: BLE001 - is_integrity_error is the precise discriminator
        # Audit finding 2026-07-17: same cross-driver fix as the baseline-capture
        # branch above -- see its comment.
        if not is_integrity_error(exc):
            raise
        # This (document_id, content_hash) revision already exists — a concurrent pass or
        # a re-process. IDEMPOTENT: roll back so a duplicate can never poison and roll back
        # the whole scrape pass, then just advance the doc's last-seen state.
        session.rollback()
        doc.last_checked_at = now
        doc.last_hash = h
        doc.last_size = len(text)
        doc.last_status = "version already recorded"
        doc.latest_text = text
        existing = (
            session.query(LawRevision)
            .filter_by(document_id=doc.id, content_hash=h)
            .first()
        )
        if existing:  # keep any prior anchor rather than nulling it on a miss
            doc.latest_text_revid = existing.id
        session.commit()
        _ingest_to_corpus(session, doc, extractor)
        return {"document_id": doc.id, "status": "duplicate"}
    _ingest_to_corpus(session, doc, extractor)
    _record_lane(doc, rev, parsed)
    return {
        "document_id": doc.id,
        "status": "changed",
        "delta_bytes": delta,
        "flagged": flag.flagged,
        "flag_reasons": flag.reasons,
    }


def _batch_extractor(extractor):
    """Build the keyword extractor ONCE per batch (laws index like any article)."""
    if extractor is not None:
        return extractor
    from src.analytics.extract import BaselineExtractor

    return BaselineExtractor()


def track_watched(session, fetcher, *, limit_documents: int = 50, extractor=None) -> dict:
    """Track all watched legal documents, returning an aggregate tally."""
    from src.database.query import capped

    extractor = _batch_extractor(extractor)
    docs = capped(
        session.query(LawDocument).filter_by(watched=True).order_by(LawDocument.id.asc()),
        limit_documents,  # 0 = every watched document (no cap)
    ).all()
    tally = {
        "documents": 0,
        "baselines": 0,
        "changed": 0,
        "flagged": 0,
        "errors": 0,
        "unchanged": 0,
    }
    for doc in docs:
        try:
            res = track_document(session, fetcher, doc, extractor=extractor)
        except Exception:  # noqa: BLE001 - one bad document must not abort the batch
            _LOG.warning("law tracking: document %s failed", doc.id, exc_info=True)
            session.rollback()  # clear a poisoned transaction so it can't roll back the batch
            tally["errors"] += 1
            continue
        tally["documents"] += 1
        status = res.get("status")
        if status == "baseline":
            tally["baselines"] += 1
        elif status == "changed":
            tally["changed"] += 1
            if res.get("flagged"):
                tally["flagged"] += 1
        elif status == "error":
            tally["errors"] += 1
        elif status == "unchanged":
            tally["unchanged"] += 1
    return tally


def adaptive_track_budget(
    watched_count: int, *, min_batch: int = 5, max_batch: int = 25, divisor: int = 20
) -> int:
    """The per-pass tracking budget, SCALED to the size of the watched-document set
    (2026-07-24 field-feedback Session A, item 3: "auto_track_due's batch=5/24h
    cannot baseline hundreds of docs -- make the per-pass budget adaptive").

    Bounded both ways: today's small watched set (~23 documents) still resolves to
    ``min_batch`` — the ORIGINAL hardcoded default, so nothing changes on a typical
    install — while a large one (once enumeration adapters register hundreds of
    documents per jurisdiction) climbs toward ``max_batch`` instead of crawling at
    5/pass forever, but a single pass never floods legal sites beyond that cap."""
    if watched_count <= 0:
        return min_batch
    return max(min_batch, min(max_batch, watched_count // max(1, divisor)))


def auto_track_due(
    session, fetcher, *, batch: int | None = None, min_interval_hours: float = 24.0, extractor=None
) -> dict:
    """Track a BOUNDED, freshness-gated batch of watched legal documents per collect pass
    (field test 2026-06-22, #18: the World-law tab was empty because law is only tracked
    in mode=="law", never in the default rss pass).

    Mirrors the calendar/markets auto-load: at most ``batch`` documents per call, chosen
    ROUND-ROBIN by least-recently-checked (never-checked first), and a document checked
    within ``min_interval_hours`` is skipped — so legal sites are polled politely over
    successive passes (per-host politeness + robots fail-closed + the kill switch all ride
    the shared fetcher; this only schedules the existing tracker). Best-effort + idempotent
    (track_document dedups by content hash); never raises for one bad document. Returns the
    same tally shape as track_watched plus ``due`` (how many were eligible).

    ``batch=None`` (the default) computes an ADAPTIVE budget from the total watched
    count via :func:`adaptive_track_budget` — pass an explicit int to keep the old
    fixed-batch behaviour (tests do, deliberately, for determinism)."""
    from datetime import timedelta

    extractor = _batch_extractor(extractor)
    if batch is None:
        watched_count = session.query(LawDocument).filter_by(watched=True).count()
        batch = adaptive_track_budget(watched_count)
    cutoff = datetime.now(UTC) - timedelta(hours=min_interval_hours)
    q = session.query(LawDocument).filter_by(watched=True).filter(
        # never-checked (NULL) OR stale beyond the interval
        (LawDocument.last_checked_at.is_(None)) | (LawDocument.last_checked_at < cutoff)
    )
    due_total = q.count()
    # least-recently-checked first; NULLs (never checked) sort first so a fresh corpus
    # builds its baselines before re-checking anything.
    docs = (
        q.order_by(LawDocument.last_checked_at.is_(None).desc(), LawDocument.last_checked_at.asc())
        .limit(max(0, batch))
        .all()
    )
    tally = {"documents": 0, "baselines": 0, "changed": 0, "flagged": 0,
             "errors": 0, "unchanged": 0, "due": due_total}
    for doc in docs:
        try:
            res = track_document(session, fetcher, doc, extractor=extractor)
        except Exception:  # noqa: BLE001 - one bad document must not abort the batch
            _LOG.warning("law auto-track: document %s failed", doc.id, exc_info=True)
            session.rollback()  # clear a poisoned txn so one dup can't roll back the WHOLE pass
            tally["errors"] += 1
            continue
        tally["documents"] += 1
        status = res.get("status")
        if status == "baseline":
            tally["baselines"] += 1
        elif status == "changed":
            tally["changed"] += 1
            if res.get("flagged"):
                tally["flagged"] += 1
        elif status == "error":
            tally["errors"] += 1
        elif status == "unchanged":
            tally["unchanged"] += 1
    return tally
