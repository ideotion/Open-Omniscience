"""
IPCC AR6 Summaries for Policymakers (SPMs) as text sources.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Row A S3 of the v0.6.0 plan (Q1133 = a: AR6 SPMs first, ``pypdf`` acceptable). Four
published PDFs on ``www.ipcc.ch`` (WGI, WGII, WGIII and the Synthesis Report SPM), each
fetched on a click under the consent popup, extracted with ``src/ingest/pdf.py`` and stored
as ONE corpus Article through the single ``index_article`` hook.

Honesty by construction:
  * the fetch refuses UP FRONT under the kill switch and says so by the shared sentence;
  * a body that is not a PDF, whose length disagrees with the length the server declared
    (a truncated transfer) or that yields no real prose stores NOTHING, with the reason;
  * provenance is a dedicated, filterable source ("IPCC reports", synthetic domain,
    ``source_type="document"``), distinct from "Imported PDFs";
  * the same URL with changed bytes is NEVER overwritten (an erratum is the reader's
    decision): the stored copy is kept and the result says ``changed``;
  * ``published_at`` is the approval date the catalog states, ``None`` if it was not stated;
  * the surface says the reports TRACK PREDICTIONS over time and assert no future
    (:data:`DISCLOSURE`, a translated string).

The catalog is dated (:data:`IPCC_AS_OF`) and registered in ``configs/external_artifacts.yml``.
The URLs and approval dates are documented from the IPCC's own site, NOT verified against a
live download (the build sandbox has no route to ``www.ipcc.ch``): a wrong path fails LOUDLY
(HTTP error or "not a pdf").
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.models import Article, Source
from src.database.source_lookup import source_for_domain
from src.ingest import DEFAULT_USER_AGENT, kill_switch_active
from src.ingest.fetch_verdict import NETWORK_REFUSED
from src.monitoring.secret_scrub import log_failure
from src.safety.fetcher import guarded_session

_LOG = logging.getLogger(__name__)

IPCC_AS_OF = "2026-11-07"
IPCC_HOST = "www.ipcc.ch"
IPCC_SOURCE_DOMAIN = "ipcc.reports.local"
IPCC_SOURCE_NAME = "IPCC reports"
#: Translated (x12) as an i18n key; the surface follow-up renders it beside every SPM.
DISCLOSURE = "IPCC reports track predictions over time; they never assert futures."
# Generous: a fetch may egress over Tor, which is slow. Seconds.
_TIMEOUT_S = 120

Getter = Callable[[str], Any]


@dataclass(frozen=True)
class SpmEntry:
    key: str
    title: str
    working_group: str
    url: str
    approved: str | None  # ISO date of the approval, as the IPCC states it; None = not stated


SPM_CATALOG: tuple[SpmEntry, ...] = (
    SpmEntry(
        "wg1",
        "Climate Change 2021: The Physical Science Basis. Summary for Policymakers",
        "WGI",
        f"https://{IPCC_HOST}/report/ar6/wg1/downloads/report/IPCC_AR6_WGI_SPM.pdf",
        "2021-08-07",
    ),
    SpmEntry(
        "wg2",
        "Climate Change 2022: Impacts, Adaptation and Vulnerability. Summary for Policymakers",
        "WGII",
        f"https://{IPCC_HOST}/report/ar6/wg2/downloads/report/IPCC_AR6_WGII_SummaryForPolicymakers.pdf",
        "2022-02-27",
    ),
    SpmEntry(
        "wg3",
        "Climate Change 2022: Mitigation of Climate Change. Summary for Policymakers",
        "WGIII",
        f"https://{IPCC_HOST}/report/ar6/wg3/downloads/report/IPCC_AR6_WGIII_SummaryForPolicymakers.pdf",
        "2022-04-04",
    ),
    SpmEntry(
        "syr",
        "Climate Change 2023: Synthesis Report. Summary for Policymakers",
        "SYR",
        f"https://{IPCC_HOST}/report/ar6/syr/downloads/report/IPCC_AR6_SYR_SPM.pdf",
        "2023-03-19",
    ),
)


def spm_entry(key: str) -> SpmEntry:
    for e in SPM_CATALOG:
        if e.key == key:
            return e
    raise ValueError(f"unknown IPCC SPM {key!r}; known: {[e.key for e in SPM_CATALOG]}")


def _default_getter(url: str) -> Any:
    """A guarded GET held to the IPCC host (a redirect off it is refused), streamed,
    and asked for the identity encoding so the declared length is the body's own."""
    session = guarded_session(
        user_agent=DEFAULT_USER_AGENT, isolation_token=url, allowed_hosts=(IPCC_HOST,)
    )
    return session.get(
        url, timeout=_TIMEOUT_S, stream=True, headers={"Accept-Encoding": "identity"}
    )


def _read_declared(resp: Any, label: str) -> bytes:
    """Read the body, bounded by the length the server DECLARED (never a constant).

    No declared length means no bound to hold the read to, so it is refused; a body that
    runs past the declared length or stops short of it is refused too.
    """
    headers = getattr(resp, "headers", None) or {}
    declared = headers.get("Content-Length")
    if declared is None or not str(declared).isdigit():
        raise ValueError(f"{label}: the server declared no length, so the read cannot be bounded")
    encoding = str(headers.get("Content-Encoding") or "identity").lower()
    if encoding != "identity":
        raise ValueError(
            f"{label}: the server compressed the body ({encoding}) despite the identity request, "
            "so its declared length is not the document's"
        )
    limit = int(declared)
    iterator = getattr(resp, "iter_content", None)
    if iterator is None:  # a test double that only carries .content
        data = resp.content
    else:
        buf = bytearray()
        try:
            for chunk in iterator(chunk_size=65536):
                buf.extend(chunk)
                if len(buf) > limit:
                    raise ValueError(
                        f"{label}: the body runs past the {limit} bytes the server declared"
                    )
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - urllib3 raises its own error on a short body
            raise ValueError(
                f"{label}: the transfer ended early ({type(exc).__name__}); "
                f"{len(buf)} of the {limit} declared bytes arrived (truncated transfer)"
            ) from None
        data = bytes(buf)
    if len(data) != limit:
        raise ValueError(
            f"{label}: received {len(data)} bytes, the server declared {limit} (truncated transfer)"
        )
    return data


def fetch_spm(key: str, *, get: Getter | None = None) -> bytes:
    """Fetch one SPM PDF live (kill switch refuses UP FRONT) and return its bytes.

    Raises ``ValueError`` for a body that cannot be the document: not a PDF, empty, or a
    length that disagrees with the one the server declared (truncated). The bound is the
    server's own declared length, never a constant.
    """
    from src.ingest.pdf import looks_like_pdf

    entry = spm_entry(key)
    if kill_switch_active():
        raise RuntimeError(NETWORK_REFUSED)
    resp = (get or _default_getter)(entry.url)
    label = f"IPCC {entry.working_group} SPM"
    try:
        resp.raise_for_status()
        data = _read_declared(resp, label)
    finally:
        close = getattr(resp, "close", None)  # a streamed response holds its socket until closed
        if close is not None:
            close()
    if not data:
        raise ValueError(f"{label}: empty response")
    if not looks_like_pdf(data):
        raise ValueError(f"{label}: the response is not a PDF")
    return data


def ensure_ipcc_source(session: Session) -> Source:
    """ONE catalog source for the IPCC reports: a filterable provenance class."""
    src = source_for_domain(session, IPCC_SOURCE_DOMAIN)
    if src is None:
        src = Source(
            name=IPCC_SOURCE_NAME,
            domain=IPCC_SOURCE_DOMAIN,
            rss_url=None,
            enabled=False,  # a provenance sink, never scraped
            source_type="document",
        )
        session.add(src)
        session.flush()
    return src


def ingest_spm(
    session: Session,
    key: str,
    data: bytes,
    *,
    extractor=None,
) -> dict:
    """Extract one SPM's text and store it as an Article. Honest result, never a fabricated body.

    Returns ``{status: imported|duplicate|changed|skipped, ...}``.
    """
    from src.ingest.pdf import extract_pdf_text

    entry = spm_entry(key)
    text, reason = extract_pdf_text(data, ocr=False)
    if not text:
        return {"status": "skipped", "key": key, "reason": reason}

    content_hash = hashlib.sha256(text.encode()).hexdigest()
    dup = session.query(Article).filter_by(hash=content_hash).first()
    if dup is not None:
        return {"status": "duplicate", "key": key, "article_id": dup.id}
    prior = session.query(Article).filter_by(url=entry.url).first()
    if prior is not None:
        return {
            "status": "changed",
            "key": key,
            "article_id": prior.id,
            "reason": "the IPCC file at this address differs from the stored copy; the stored copy was kept",
        }

    source = ensure_ipcc_source(session)
    published = datetime.fromisoformat(entry.approved) if entry.approved else None
    art = Article(
        url=entry.url,
        canonical_url=entry.url,
        source_id=source.id,
        title=entry.title,
        content=text,
        language="en",  # the catalog states it: the SPMs are published in English
        hash=content_hash,
        published_at=published,
    )
    session.add(art)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        dup = session.query(Article).filter_by(hash=content_hash).first()
        return {"status": "duplicate", "key": key, "article_id": dup.id if dup else None}

    if extractor is None:
        from src.analytics.extract import BaselineExtractor

        extractor = BaselineExtractor()
    from src.analytics.store import index_article

    try:
        tally = index_article(session, art, extractor=extractor)
    except Exception as exc:  # noqa: BLE001 - the Article is stored; indexing can be retried
        session.rollback()
        log_failure(_LOG, "ipcc spm indexing failed", exc, level=logging.WARNING)
        return {
            "status": "imported",
            "key": key,
            "article_id": art.id,
            "mentions": None,
            "reason": "stored, but indexing failed",
        }
    return {
        "status": "imported",
        "key": key,
        "article_id": art.id,
        "mentions": tally.get("mentions", 0),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
