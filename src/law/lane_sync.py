"""The one bridge between ``corpus.db``'s law roster and ``law.db``'s metadata model.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/law/track.py`` owns the roster, the text and the revision history; ``law.db`` owns
the identity group, the translation provenance, the licence and the provisions. This
module is the only place the two meet, and it has one rule above every other:

    **A LANE FAILURE NEVER BREAKS TRACKING.**

The corpus write is the primary record — the text of a law and the fact that it changed.
The lane write is metadata about that record. An operator running with the lane file
absent, locked, or on a build where ``law.db`` cannot be created must still collect, so
every path here returns a NAMED OUTCOME instead of raising, and the outcome is logged.
That is not a swallowed exception: the caller gets a string saying which of the six
things happened, and ``"failed"`` carries the reason.

WHAT IT REFUSES TO GUESS. Two fields could easily have been defaulted and are not,
because both are claims a reader would act on:

* ``translation_kind`` defaults to ``unrecorded``, NEVER to ``original``. A document
  fetched from a national gazette usually IS the original — and "usually" is how a
  translation ends up labelled as the authentic text of a law.
* ``doc_type`` defaults to ``unspecified``. The legacy ``category`` column says
  ``legislation``, which is not one of Q902's categories and does not imply one.

Both are visible in the reader as the states they are, so an operator can correct them
rather than discovering later that the app decided for them.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.catalog.countries import country_display_code
from src.law.catalog import source_for_url
from src.law.model import (
    LawModelError,
    ensure_identity,
    register_document,
    store_provisions,
)
from src.versioned.store import create_lane, lane_session

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from src.database.models import LawDocument, LawRevision
    from src.law.adapters import Provision

_LOG = logging.getLogger(__name__)

#: What ``record_document`` did. One vocabulary, so a caller never parses a sentence.
OUTCOMES: tuple[str, ...] = ("recorded", "no-lane-key", "no-jurisdiction", "refused", "failed")


def _identity_inputs(doc: LawDocument, parsed: object | None) -> tuple[str, str, str, str]:
    """``(scheme, value, jurisdiction_alpha3, jurisdiction_level)`` for one document.

    The scheme is the publisher's own identifier where the adapter read one, and
    ``local`` otherwise. A ``local`` identity is keyed on the document's OFFICIAL URL,
    which is the only stable publisher-scoped string a text-only source offers — and it
    is provisional by construction, which is what ``model.remint_identity`` exists for:
    the day the portal publishes an ELI, the identity is corrected in one row.
    """
    alpha3 = (country_display_code(doc.jurisdiction) or "").strip().upper()
    level = "national"
    if alpha3 == "INT":
        level = "international"
    elif alpha3 == "EUU":
        # The World Bank code this app already uses for the EU (`SPECIAL_ALPHA3`), so
        # the law model does not invent a second convention for the same body.
        level = "supranational"

    number = getattr(parsed, "document_number", None)
    year = getattr(parsed, "year", None)
    if number and year:
        return "act-number", f"{year}/{number}", alpha3, level
    if number:
        return "act-number", str(number), alpha3, level
    return "local", (doc.official_url or doc.url or "").strip(), alpha3, level


def record_document(
    doc: LawDocument,
    revision: LawRevision | None,
    parsed: object | None = None,
    *,
    provisions: Sequence[Provision] | None = None,
) -> str:
    """Record one tracked document (and optionally one version's provisions) in ``law.db``.

    Returns one of :data:`OUTCOMES`. Never raises.
    """
    lane_key = getattr(doc, "lane_key", None)
    if not lane_key:
        # The tracker mints it; a document that reached here without one is a wiring
        # defect, and inventing one here would create a second key for the same law.
        _LOG.warning("law document %s has no lane_key; nothing recorded", doc.id)
        return "no-lane-key"

    alpha3 = (country_display_code(doc.jurisdiction) or "").strip().upper()
    if len(alpha3) != 3 or not alpha3.isalpha():
        # An unrecognised jurisdiction comes back from `country_display_code` as the raw
        # value. Storing it would put junk in a column the whole identity is keyed on.
        _LOG.warning(
            "law document %s: jurisdiction %r does not resolve to an alpha-3 code; "
            "nothing recorded",
            doc.id,
            doc.jurisdiction,
        )
        return "no-jurisdiction"

    scheme, value, _alpha3, level = _identity_inputs(doc, parsed)
    if not value:
        _LOG.warning("law document %s states no identifier and has no URL", doc.id)
        return "no-jurisdiction"

    try:
        # `lane_engine(create=True)` brings the FILE into existence and nothing else;
        # `create_lane` is the one that also materialises the schema, and it is
        # idempotent by design ("safe to call from an enablement path that may be
        # clicked twice"). Called per document rather than cached behind a flag,
        # because a cached "already created" outlives the file it describes -- an
        # operator who deletes law.db between passes would then get every write
        # refused for the lifetime of the process.
        create_lane("law")
        with lane_session("law") as session:
            identity = ensure_identity(
                session,
                scheme=scheme,
                jurisdiction_alpha3=alpha3,
                value=value,
                doc_type="unspecified",
                jurisdiction_level=level,
                enacted_on=getattr(doc, "enacted_on", None),
            )
            # Q927: the licence is INHERITED from the catalogue row that serves this
            # URL, as a default. A document may later carry its own and override it; what
            # this must never do is invent one, so a source that states no licence yields
            # `unknown` and the reader says "licence not recorded" rather than implying
            # somebody read the terms of this particular document.
            source = source_for_url(doc.official_url or doc.url)
            meta = register_document(
                session,
                lane_key=lane_key,
                identity=identity,
                language=doc.language or "und",
                translation_kind="unrecorded",
                title=doc.title,
                licence_id=str((source or {}).get("licence") or "unknown"),
                source_authority=str((source or {}).get("name") or "") or None,
                source_url=doc.official_url or doc.url,
                granularity="provision" if provisions else "act",
            )
            rev_key = getattr(revision, "lane_key", None) if revision is not None else None
            if provisions and rev_key:
                store_provisions(
                    session,
                    document_lane_key=meta.lane_key,
                    revision_lane_key=rev_key,
                    provisions=provisions,
                )
    except LawModelError as exc:
        # A closed-vocabulary refusal is a REFUSAL, not a crash: it means this document
        # states something the model will not record, and the operator should see which.
        _LOG.warning("law document %s refused by the model: %s", doc.id, exc)
        return "refused"
    except Exception as exc:  # noqa: BLE001 - the lane is optional; tracking is not
        _LOG.warning("law document %s: lane write failed (%s: %s)", doc.id, type(exc).__name__, exc)
        return "failed"
    return "recorded"
