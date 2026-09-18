"""The law lane's own tables in ``law.db`` — identity, per-language document, provisions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q906 = a asks for "Akoma-Ntoso-lite: document → versions → provisions with stable
addresses, plus a metadata block". This module is the metadata block and the
provisions. THE VERSIONS ARE NOT HERE, and that is the shape of the whole slice:
``law_documents`` / ``law_revisions`` in ``corpus.db`` already ARE the roster and the
text store — 23 documents on a fresh install, with their baselines, their latest text
and their revision history — and S04-10's slice list does not ask for that polling path
to be retired. So this lane holds ONLY what the legacy schema cannot express, and NO
FACT IS STORED IN BOTH: title, url, jurisdiction, baseline and latest text stay there;
identity, translation provenance, licence and provisions are only here.

(``S04-08_versioned-source-substrate-and-lanes.md:170-172`` records a DESIGN NOTE
preferring the opposite — the substrate's tables starting fresh while the legacy ones
go read-only — and records the question as one that slice may not decide. A design note
binds nobody, so this slice states the tension in its PR and takes the shape that does
not build a second roster over the same 23 documents.)

WHY TWO TABLES AND NOT ONE. Every fact about the LAW — its type, its status, its
issuing body, its dates — belongs to the law, not to one rendering of it. A single
table with a row per tracked document would store each of those once PER LANGUAGE
VERSION, so an EU act in 24 languages would carry 24 copies of "repealed" and the
French row could say ``amended`` while the German row still said ``in-force`` because
only one adapter re-ran. That disagreement is the thing Q908's "one document identity"
exists to prevent, and a link table would only have moved it. ``LawIdentity`` is the
law; ``LawDocumentMeta`` is one language version of it.

It also makes a REMINT cheap. When a document's identity turns out to be wrong (the
adapter guessed ``local`` before the portal published an ELI), the correction updates
ONE row and every language version follows by foreign key — instead of N rows that can
fail halfway.

CROSS-FILE LINKS ARE STABLE STRINGS HERE, NOT ROW IDS — A DELIBERATE DEPARTURE.
``src/versioned/models.py`` documents the house pattern: a link into ``corpus.db`` is a
plain integer with no referential integrity, checked after the fact by
``integrity.check_article_links``. That is right for ``article_id``, where the failure
mode of a restore that renumbers rows is a link pointing somewhere visibly wrong. It is
NOT right here. The fact at the end of this link is a LICENCE and a translation
PROVENANCE — claims this app repeats at every export point (Q1008) about somebody
else's material — and ``src/backup/merge.py`` genuinely does renumber ``law_documents``
on an incoming merge (``temp.map_law_doc`` exists for that reason). An integer link
would then attach the wrong licence to the wrong law, silently and plausibly. A minted
string survives renumbering untouched, so the worst a merge can do is leave a document
with NO metadata, which every reader below reports as absent. Failing to absent beats
failing to wrong, and that is the whole argument.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.versioned.models import LaneBase, LaneUTCDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LawIdentity(LaneBase):
    """ONE row per law, whatever languages it is published in (Q908 = a).

    The identity is the TRIPLE ``(identity_scheme, jurisdiction_alpha3,
    document_identity)``, not the identifier alone. Q908's own text scopes the identity
    to "(CELEX/ELI)", both globally namespaced by construction — but this model also
    serves jurisdictions that publish neither, through the ``act-number`` and ``local``
    schemes, and "Act 5 of 2020" is not unique on Earth. Folding the jurisdiction into
    the key is what stops two countries' Act 5 merging into one law; the minting
    function in ``src/law/model.py`` is the one place the triple is ever formed.
    """

    __tablename__ = "law_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: One of ``model.IDENTITY_SCHEMES``. A closed vocabulary, refused at the setter.
    identity_scheme: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The identifier as the publisher writes it, normalised for case and whitespace
    #: by ``document_identity_for`` and never otherwise touched.
    document_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    #: ISO 3166-1 alpha-3 (Q312 = a), or ``INT`` for a treaty or other international
    #: instrument (Q902 = d). Never alpha-2.
    jurisdiction_alpha3: Mapped[str] = mapped_column(String(3), nullable=False)
    #: ``national`` · ``supranational`` · ``international``. Subnational is ABSENT on
    #: purpose: Q903 is a recorded CONFLICT, so nothing subnational is built and the
    #: setter refuses the value by name rather than letting one through unruled.
    jurisdiction_level: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Q902's (a), (b) and (d). ``bill``/``draft`` (Q902's (c), post-beta) and case law
    #: (Q902's (e), not chosen) are refused by name, not merely absent.
    doc_type: Mapped[str] = mapped_column(String(24), nullable=False)
    #: ``civil`` · ``common`` · ``mixed`` · ``religious`` · ``customary`` · ``unknown``.
    legal_system: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    #: ``in-force`` · ``amended`` · ``repealed`` · ``unknown``. ``unknown`` is a REAL
    #: value here rather than a NULL, because "the source did not say" and "we have not
    #: looked" are both honest and neither is "in force".
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    issuing_body: Mapped[str | None] = mapped_column(String(256))
    #: The four one-time document dates (Q907). Stored as the source states them, which
    #: is why they are strings: a publisher writing "2018" or "2018-05" states a real
    #: fact less precisely than a date column can hold, and widening it to a full date
    #: would invent a day nobody published.
    #:
    #: "Amended" is deliberately NOT among them: a law is amended many times, and the
    #: amendment history is the revisions, not a column. "In force" is not among them
    #: either — that is ``status`` plus the version's own ``valid_on``.
    enacted_on: Mapped[str | None] = mapped_column(String(32))
    published_on: Mapped[str | None] = mapped_column(String(32))
    commenced_on: Mapped[str | None] = mapped_column(String(32))
    repealed_on: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "identity_scheme",
            "jurisdiction_alpha3",
            "document_identity",
            name="uq_law_identity",
        ),
        Index("ix_law_identity_jurisdiction", "jurisdiction_alpha3", "doc_type"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<LawIdentity({self.identity_scheme}:{self.jurisdiction_alpha3}:"
            f"{self.document_identity!r})>"
        )


class LawDocumentMeta(LaneBase):
    """ONE row per TRACKED DOCUMENT — that is, per language version (Q901's NOTE).

    The note is verbatim: "each translation should be accessible with their own rich
    metadata and individually tracked for changes, same as the official laws, with
    links to the other existing translations and to the original untranslated text".
    So a translation is not a field on the original — it is its own row here and its
    own ``law_documents`` row in ``corpus.db``, polled and diffed like any other. The
    links in both directions are the shared ``identity_id``: every member of a group
    finds every other through it, with no link table to fall out of step.

    ``translated_by`` NULL means two different things depending on ``translation_kind``
    — "there is no translator" on an original, "we do not know which body" on an
    official translation — so every renderer reads the PAIR. The one place that
    sentence is composed is ``model.provenance_of``.
    """

    __tablename__ = "law_document_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The link into ``corpus.db``'s ``law_documents.lane_key``. See the module
    #: docstring for why this is a minted string rather than that table's row id.
    lane_key: Mapped[str] = mapped_column(String(36), nullable=False)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("law_identities.id", ondelete="CASCADE"), nullable=False
    )
    #: The language THIS rendering is in. Raw from the source, normalised on read.
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The title in THIS language (Q907's "title ×languages" — one row per language is
    #: how the model holds several without a second table).
    title: Mapped[str | None] = mapped_column(String(512))
    #: ``original`` · ``official`` · ``intergovernmental`` · ``foreign-government``
    #: (Q901's a, b and c). Closed; the setter normalises and refuses anything else,
    #: because the partial unique index below compares this column BYTE-EXACTLY and
    #: would give ``Original`` no protection at all.
    translation_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    translated_by: Mapped[str | None] = mapped_column(String(256))
    #: A token from ``model.LICENCES`` (Q927). The licence's NAME, URL and whether it
    #: permits redistribution are NOT stored: they are properties of the licence, and a
    #: copy per document is a copy that can disagree about what OGL v3.0 says.
    licence_id: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    source_authority: Mapped[str | None] = mapped_column(String(256))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    #: Q904 = a: ``act`` by default, ``provision`` for sources that arrive pre-split.
    granularity: Mapped[str] = mapped_column(String(16), nullable=False, default="act")
    first_seen_at: Mapped[datetime] = mapped_column(
        LaneUTCDateTime, nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("lane_key", name="uq_law_document_meta_lane_key"),
        Index("ix_law_document_meta_identity", "identity_id", "language"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LawDocumentMeta({self.lane_key} {self.language} {self.translation_kind})>"


class LawProvision(LaneBase):
    """One addressable provision of one VERSION of one document (Q904, Q906).

    The address is ``Provision.identifier`` from the adapter — the chain of containers
    above the provision plus its own number — never its position in a list, because a
    section inserted above would silently re-point every address below it.

    THE TEXT IS STORED, AND THAT IS A DUPLICATION THIS DOCSTRING OWNS. The version's
    full text already lives in ``law_revisions.full_text``; the provisions are that
    same text, split. Per-provision diffs (Q914's analytic 1) need per-provision text
    to diff, and reconstructing it from byte offsets into a compressed column would
    break the first time a whitespace rule changed. So the law corpus costs roughly
    twice its text, knowingly, and the alternative was an address that could not be
    read.
    """

    __tablename__ = "law_provisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Which VERSION this provision belongs to: ``law_revisions.lane_key``.
    revision_lane_key: Mapped[str] = mapped_column(String(36), nullable=False)
    #: Which DOCUMENT, denormalised so "every provision this document ever had" is one
    #: query in this file rather than a join across two databases. Written ONLY by
    #: ``model.store_provisions``, from the revision's own document, so the two cannot
    #: disagree unless that function is wrong — which a test pins.
    document_lane_key: Mapped[str] = mapped_column(String(36), nullable=False)
    #: The stable address. Unique WITHIN a version; the same address in the next
    #: version is the same provision, which is what makes a timeline possible.
    address: Mapped[str] = mapped_column(String(512), nullable=False)
    #: Document order, for rendering. NOT part of the address, deliberately.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    num: Mapped[str | None] = mapped_column(String(64))
    heading: Mapped[str | None] = mapped_column(String(512))
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(LaneUTCDateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("revision_lane_key", "address", name="uq_law_provision_address"),
        Index("ix_law_provision_document", "document_lane_key", "address"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LawProvision({self.address!r} of {self.revision_lane_key})>"


#: The law lane's own tables. ``src/versioned/store.create_schema`` materialises these
#: in ``law.db`` ONLY — a wiki lane gets the shared tables and none of these, so an
#: operator who never tracked a law does not carry three empty law tables in wiki.db.
LAW_LANE_MODELS: tuple[type[LaneBase], ...] = (LawIdentity, LawDocumentMeta, LawProvision)
