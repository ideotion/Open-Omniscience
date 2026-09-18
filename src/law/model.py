"""The ONE read/write path for the law metadata model (Q901, Q902, Q904–Q908, Q927).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``lane_models.py`` is the schema; this is the only module that should form an identity,
classify a translation, resolve a licence or read a language group. The discipline is
the one ``src/versioned/revisions.py`` and ``src/wiki/identity.py`` already use here:
a rule written twice is a rule that will be written differently twice.

THE VOCABULARIES ARE CLOSED AND THE SETTERS REFUSE. Every ``*_KINDS`` tuple below is a
complete list, and the normalising functions raise ``LawModelError`` on anything else
rather than storing it. That is not tidiness. ``LawDocumentMeta`` is queried by exact
string — "every ``original`` in this identity group" — so ``Original``, ``ORIGINAL`` and
``original `` are three documents the group cannot see, and a reader asking for the
untranslated text would be told there is none. A byte-exact comparison gives a
vocabulary no protection; the refusal is the protection.

WHAT IS DELIBERATELY NOT HERE, AND WHY. A reclassification — ``translation_kind``
moving from ``original`` to ``official`` — is this app changing what it told readers,
and the shape for that in this tree is an APPENDED FACT (``VersionedEntityFact`` exists
precisely so a changed statement does not silently overwrite the old one). It is not
appended here, because that table is keyed on a ``VersionedEntity`` row and a law
document has none in this shape: ``law_documents`` in ``corpus.db`` is the roster, and
minting a parallel substrate entity for every law purely to hold an audit row would
build the second roster this slice exists to avoid. ``set_translation_kind`` therefore
refuses an unknown value, records ``updated_at``, and LOGS the transition — and the
audit trail is recorded as a deliberate omission rather than implied.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from src.law.lane_models import LawDocumentMeta, LawIdentity, LawProvision

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Sequence

    from src.law.adapters import Provision

_LOG = logging.getLogger(__name__)


class LawModelError(ValueError):
    """A value outside a closed vocabulary, or an identity that would collide.

    A distinct type because callers legitimately catch it (an adapter turns it into a
    refusal it can report) while never wanting to swallow a genuine programming
    ``ValueError`` from the same block.
    """


#: How a law is identified. ``eli``/``celex``/``ecli`` are globally namespaced by
#: construction (Q908 names the first two); ``act-number`` and ``local`` are this
#: model's extension for jurisdictions that publish neither, and are exactly the two
#: that need the jurisdiction folded into the key to stay unique.
IDENTITY_SCHEMES: tuple[str, ...] = ("eli", "celex", "ecli", "act-number", "local")

#: Q902's (a), (b) and (d). Two absences are DELIBERATE and are refused BY NAME below,
#: because a silent absence reads as an oversight: ``bill``/``draft`` are Q902's (c),
#: recorded for post-beta, and case law is Q902's (e), which was not chosen.
DOC_TYPES: tuple[str, ...] = (
    "constitution",
    "statute",
    "code",
    "regulation",
    "decree",
    "ordinance",
    "treaty",
    # NOT one of Q902's categories: the state of not having been told which one this is.
    # A legacy row carrying only `category="legislation"` has not said whether it is a
    # statute or a code, and choosing for it would put a category on a legal document
    # that its publisher never stated. Named rather than NULL so a surface can SAY it.
    "unspecified",
)
_REFUSED_DOC_TYPES: dict[str, str] = {
    "bill": "Q902's (c): bills and drafts are recorded for post-beta (S09-01), not 0.4",
    "draft": "Q902's (c): bills and drafts are recorded for post-beta (S09-01), not 0.4",
    "case-law": "Q902's (e) was not chosen; case law has no ruling to build on",
    "judgment": "Q902's (e) was not chosen; case law has no ruling to build on",
}

#: ``INT`` in ``jurisdiction_alpha3`` carries Q902's (d) — treaties and international
#: instruments belong to no one state.
JURISDICTION_LEVELS: tuple[str, ...] = ("national", "supranational", "international")
_REFUSED_LEVELS: dict[str, str] = {
    "subnational": (
        "Q903 is a RECORDED CONFLICT on subnational timing, never resolved; nothing "
        "subnational is built in 0.4 and storing one would pick a side"
    ),
    "state": "see 'subnational': Q903 is an unresolved conflict",
    "provincial": "see 'subnational': Q903 is an unresolved conflict",
    "municipal": "see 'subnational': Q903 is an unresolved conflict",
}

LEGAL_SYSTEMS: tuple[str, ...] = ("civil", "common", "mixed", "religious", "customary", "unknown")

#: Q907's status list minus ``draft`` — see ``_REFUSED_DOC_TYPES``. ``unknown`` is a
#: real value rather than a NULL: "the source did not say" is a fact, and it is
#: emphatically not "in force".
STATUSES: tuple[str, ...] = ("in-force", "amended", "repealed", "unknown")

#: Q901's (a), (b) and (c), plus the untranslated text itself.
TRANSLATION_KINDS: tuple[str, ...] = (
    "original",
    "official",
    "intergovernmental",
    "foreign-government",
    # Nobody has stated which of the four this is. It is NOT a fifth kind of document
    # and it is emphatically not a synonym for "original": defaulting an unstated
    # provenance to "the original text as issued" would put a false provenance claim on
    # a legal text, which is the one claim on this surface a reader would act on. A
    # group whose members are all `unrecorded` correctly reports NO original.
    "unrecorded",
)

#: Q904 = a: act/code level by DEFAULT; per-provision for sources that arrive pre-split.
GRANULARITIES: tuple[str, ...] = ("act", "provision")


@dataclass(frozen=True, slots=True)
class Licence:
    """One licence, once. See ``LICENCES``."""

    licence_id: str
    name: str
    url: str | None
    #: ``permitted`` · ``forbidden`` · ``unknown``. Q927: a source whose terms FORBID
    #: redistribution is excluded under V1-3, and ``unknown`` is not a quiet yes.
    redistribution: str


#: Q927's licences, as the ruling names them. The NAME, the URL and whether redistribution
#: is permitted live HERE and are never copied onto a document row: a per-document copy is
#: a copy that can disagree about what OGL v3.0 says, and the one that is wrong is the one
#: this app repeats at an export point about somebody else's material.
LICENCES: dict[str, Licence] = {
    "ogl-3.0": Licence(
        "ogl-3.0",
        "Open Government Licence v3.0",
        "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        "permitted",
    ),
    "licence-ouverte-2.0": Licence(
        "licence-ouverte-2.0",
        "Licence Ouverte 2.0",
        "https://www.etalab.gouv.fr/licence-ouverte-open-licence/",
        "permitted",
    ),
    "jp-standard-terms": Licence(
        "jp-standard-terms",
        "Japan Standard Terms of Use (ver. 2.0)",
        None,
        "permitted",
    ),
    "eu-reuse": Licence(
        "eu-reuse",
        "European Commission reuse notice (Decision 2011/833/EU)",
        None,
        "permitted",
    ),
    "us-public-domain": Licence(
        "us-public-domain",
        "United States federal edict — public domain",
        None,
        "permitted",
    ),
    "cc0-1.0": Licence("cc0-1.0", "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/", "permitted"),
    "cc-by-4.0": Licence("cc-by-4.0", "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/", "permitted"),
    # The two honest non-answers. They are DIFFERENT: one says nobody looked, the other
    # says somebody looked and the terms said no, and Q927's V1-3 exclusion turns only on
    # the second. Collapsing them into a single falsy value is how a forbidden source
    # gets redistributed by a caller writing `if not licence.permitted`.
    "unknown": Licence("unknown", "Licence not recorded", None, "unknown"),
    "all-rights-reserved": Licence(
        "all-rights-reserved", "All rights reserved — redistribution forbidden", None, "forbidden"
    ),
}


def _one_of(value: str | None, allowed: tuple[str, ...], field: str, *, refused: dict | None = None) -> str:
    """Normalise case/whitespace and refuse anything outside ``allowed``, by name."""
    token = (value or "").strip().lower()
    if token in allowed:
        return token
    if refused and token in refused:
        raise LawModelError(f"{field}={token!r} is refused: {refused[token]}")
    raise LawModelError(
        f"{field}={value!r} is not one of {', '.join(allowed)}; the vocabulary is closed "
        "because these columns are compared byte-exactly"
    )


def document_identity_for(scheme: str, *, jurisdiction_alpha3: str, value: str) -> tuple[str, str, str]:
    """The ONE place a law's identity triple is formed (Q908).

    Modelled on ``src/wiki/identity.py``'s ``external_id_for`` — "the ONE place the
    format is written" — and it closes the two failure directions that matter:

    * two jurisdictions' "Act 5 of 2020" cannot merge into one law, because the
      jurisdiction is part of the key rather than a column beside it;
    * one document's CELEX cannot fragment into two identities because one adapter wrote
      ``32019L0790`` and another ``32019l0790 ``.

    Returns ``(scheme, jurisdiction_alpha3, document_identity)``.
    """
    token = _one_of(scheme, IDENTITY_SCHEMES, "identity_scheme")
    juris = (jurisdiction_alpha3 or "").strip().upper()
    if len(juris) != 3 or not juris.isalpha():
        raise LawModelError(
            f"jurisdiction_alpha3={jurisdiction_alpha3!r} must be ISO 3166-1 alpha-3 "
            "(or INT for an international instrument) — alpha-2 was ruled out in 0.4"
        )
    ident = " ".join((value or "").split()).strip()
    if not ident:
        raise LawModelError("document_identity is empty; an identity nobody stated is not one")
    # Case folding is safe for every scheme here: ELI and CELEX are defined
    # case-insensitively, and an act number that distinguishes `5a` from `5A` has not
    # been seen. Recorded as an assumption rather than left implicit.
    return token, juris, ident.lower()


def mint_lane_key() -> str:
    """A fresh link key. Random, never derived, never reused.

    Derived keys (a hash of the URL, say) look tidier and are a trap: a document whose
    URL is corrected would mint a *different* key and silently orphan its own metadata.
    """
    return str(uuid.uuid4())


def ensure_identity(
    session: Session,
    *,
    scheme: str,
    jurisdiction_alpha3: str,
    value: str,
    doc_type: str,
    jurisdiction_level: str,
    legal_system: str = "unknown",
    status: str = "unknown",
    issuing_body: str | None = None,
    enacted_on: str | None = None,
    published_on: str | None = None,
    commenced_on: str | None = None,
    repealed_on: str | None = None,
) -> LawIdentity:
    """Find or create the identity row. Every vocabulary is checked BEFORE any write.

    Checking first is the difference between a refusal and a half-written group: an
    adapter that hands in ``doc_type="bill"`` gets one exception and leaves the database
    exactly as it found it.
    """
    s, j, ident = document_identity_for(scheme, jurisdiction_alpha3=jurisdiction_alpha3, value=value)
    kind = _one_of(doc_type, DOC_TYPES, "doc_type", refused=_REFUSED_DOC_TYPES)
    level = _one_of(jurisdiction_level, JURISDICTION_LEVELS, "jurisdiction_level", refused=_REFUSED_LEVELS)
    system = _one_of(legal_system, LEGAL_SYSTEMS, "legal_system")
    state = _one_of(status, STATUSES, "status")

    row = (
        session.query(LawIdentity)
        .filter_by(identity_scheme=s, jurisdiction_alpha3=j, document_identity=ident)
        .first()
    )
    if row is None:
        row = LawIdentity(
            identity_scheme=s,
            jurisdiction_alpha3=j,
            document_identity=ident,
            doc_type=kind,
            jurisdiction_level=level,
            legal_system=system,
            status=state,
            issuing_body=issuing_body,
            enacted_on=enacted_on,
            published_on=published_on,
            commenced_on=commenced_on,
            repealed_on=repealed_on,
        )
        session.add(row)
        session.flush()
        return row

    # An existing identity is UPDATED only where the new reading says something and the
    # old row said nothing. A later pass that cannot see a date must never erase one an
    # earlier pass read: "the source stopped mentioning it" is not "it never happened".
    row.doc_type = kind
    row.jurisdiction_level = level
    if system != "unknown":
        row.legal_system = system
    if state != "unknown":
        row.status = state
    for field, incoming in (
        ("issuing_body", issuing_body),
        ("enacted_on", enacted_on),
        ("published_on", published_on),
        ("commenced_on", commenced_on),
        ("repealed_on", repealed_on),
    ):
        if incoming:
            setattr(row, field, incoming)
    session.flush()
    return row


def remint_identity(
    session: Session,
    meta: LawDocumentMeta,
    *,
    scheme: str,
    jurisdiction_alpha3: str,
    value: str,
) -> LawIdentity:
    """Move ONE document to a corrected identity, or refuse — never merge silently.

    Modelled on ``src/wiki/identity.py``'s ``reconcile_to_page_id``, whose docstring
    states the reason this refuses rather than merges: a wrong merge is neither visible
    nor repairable. Two laws folded into one identity lose the boundary between them,
    and no later pass can tell which provisions belonged to which.

    It exists because a ``local`` identity is PROVISIONAL by construction: a document
    whose publisher states no identifier this app can read is keyed by its URL, and the
    day the portal publishes an ELI the real identity arrives. With ``LawIdentity`` as
    its own row that correction is one row and every language version follows by foreign
    key — there is no N-row fan-out to fail halfway through.
    """
    target_key = document_identity_for(scheme, jurisdiction_alpha3=jurisdiction_alpha3, value=value)
    current = session.get(LawIdentity, meta.identity_id)
    if current is not None and (
        current.identity_scheme,
        current.jurisdiction_alpha3,
        current.document_identity,
    ) == target_key:
        return current

    s, j, ident = target_key
    existing = (
        session.query(LawIdentity)
        .filter_by(identity_scheme=s, jurisdiction_alpha3=j, document_identity=ident)
        .first()
    )
    if existing is not None and current is not None:
        others = (
            session.query(LawDocumentMeta)
            .filter(LawDocumentMeta.identity_id == current.id, LawDocumentMeta.id != meta.id)
            .count()
        )
        if others:
            raise LawModelError(
                f"refusing to remint {meta.lane_key}: its current identity still has "
                f"{others} other language version(s), so moving this one alone would "
                "split a group that the identity is supposed to hold together"
            )
    if existing is None:
        if current is None:
            raise LawModelError(f"{meta.lane_key} has no identity row to remint from")
        current.identity_scheme, current.jurisdiction_alpha3, current.document_identity = s, j, ident
        session.flush()
        return current
    meta.identity_id = existing.id
    session.flush()
    _LOG.info("law document %s reminted onto identity %s:%s:%s", meta.lane_key, s, j, ident)
    return existing


def set_translation_kind(meta: LawDocumentMeta, kind: str) -> str:
    """Normalise and set ``translation_kind``, refusing anything outside the vocabulary.

    The partial-uniqueness question this guards is worth stating: a per-group index on
    ``translation_kind = 'original'`` compares the column byte-exactly, so it gives zero
    protection against ``Original`` — the near-miss spelling simply sits outside the
    predicate and a second "original" walks straight in. The refusal here is what makes
    the vocabulary mean anything; this codebase uses no ``CheckConstraint`` anywhere.
    """
    token = _one_of(kind, TRANSLATION_KINDS, "translation_kind")
    previous = meta.translation_kind
    if previous and previous != token:
        # A reclassification is this app changing what it told readers. See the module
        # docstring for why it is logged rather than appended as a fact.
        _LOG.info(
            "law document %s reclassified: translation_kind %s -> %s",
            meta.lane_key,
            previous,
            token,
        )
    meta.translation_kind = token
    return token


def licence_of(meta: LawDocumentMeta) -> Licence:
    """The licence this document is under, from the registry. Never a stored copy.

    An unregistered token degrades to ``unknown`` rather than raising, because this is
    read on a rendering path: a reader should see "licence not recorded" rather than a
    500, and the log line is how the operator learns the token needs an entry.
    """
    licence = LICENCES.get(meta.licence_id or "")
    if licence is None:
        _LOG.warning("law document %s carries unregistered licence %r", meta.lane_key, meta.licence_id)
        return LICENCES["unknown"]
    return licence


def redistribution_state(meta: LawDocumentMeta) -> str:
    """``permitted`` | ``forbidden`` | ``unknown`` — Q927's V1-3 input, never a bool.

    A bool would have to fold ``unknown`` into one of the other two, and whichever way
    it folded would be wrong: folding to True redistributes terms nobody read, folding
    to False hides a corpus the operator is entitled to.
    """
    return licence_of(meta).redistribution


def register_document(
    session: Session,
    *,
    lane_key: str,
    identity: LawIdentity,
    language: str,
    translation_kind: str,
    title: str | None = None,
    translated_by: str | None = None,
    licence_id: str = "unknown",
    source_authority: str | None = None,
    source_url: str | None = None,
    granularity: str = "act",
) -> LawDocumentMeta:
    """Create or update ONE language version's metadata row (Q901's NOTE).

    A translation is registered exactly like an original — same function, same table,
    its own row — which is what "individually tracked for changes, same as the official
    laws" means in a schema.
    """
    from datetime import UTC, datetime

    # EVERY vocabulary is checked BEFORE the session is touched. The first draft added
    # the row first and validated after, so a refused `translation_kind` left a
    # half-written row that failed on flush with a NOT NULL IntegrityError -- the caller
    # could not tell "you handed me a value outside the vocabulary" from "the database
    # is broken", and the transaction was already dirty. `ensure_identity` had this
    # right; this function did not, and the skeptic matrix is what said so.
    kind = _one_of(translation_kind, TRANSLATION_KINDS, "translation_kind")
    grain = _one_of(granularity, GRANULARITIES, "granularity")

    row = session.query(LawDocumentMeta).filter_by(lane_key=lane_key).first()
    if row is None:
        row = LawDocumentMeta(
            lane_key=lane_key,
            identity_id=identity.id,
            language="",
            translation_kind=kind,
        )
        session.add(row)
    row.identity_id = identity.id
    row.language = (language or "").strip().lower() or "und"
    set_translation_kind(row, kind)
    row.title = title
    row.translated_by = translated_by
    row.licence_id = licence_id if licence_id in LICENCES else "unknown"
    row.source_authority = source_authority
    row.source_url = source_url
    row.granularity = grain
    row.updated_at = datetime.now(UTC)
    session.flush()
    return row


@dataclass(frozen=True, slots=True)
class IdentityGroup:
    """Every language version of one law, read through ONE path.

    ``original_state`` is a named state rather than "``original`` is None, work it out":
    a group whose untranslated text this instance does not track is a REAL and common
    situation (an operator who added only the English translation of a Japanese Act),
    and every caller that re-derived it from a ``None`` would re-derive it differently.

    IT HAS TWO STATES, NOT THREE, AND THAT IS A REFUSAL RATHER THAN AN OVERSIGHT.
    ``absent`` says there is no ``original``-kind document in this group. It does NOT
    say whether one was never added or was removed, because ``law.db`` holds no removal
    record for a law document — the watch flag lives in ``corpus.db`` — and a function
    that reads one file cannot honestly report a fact stored in another.
    """

    identity: LawIdentity
    original: LawDocumentMeta | None
    original_state: str  # "tracked" | "absent"
    translations: tuple[LawDocumentMeta, ...]

    @property
    def members(self) -> tuple[LawDocumentMeta, ...]:
        return ((self.original,) if self.original is not None else ()) + self.translations

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(m.language for m in self.members)


def identity_group(session: Session, identity_id: int) -> IdentityGroup | None:
    """Every tracked language version of one law. The ONE read path (Q908).

    Returns ``None`` when the identity itself does not exist — distinct from an identity
    with no documents, which returns a group with an empty membership and says so.
    """
    identity = session.get(LawIdentity, identity_id)
    if identity is None:
        return None
    rows = (
        session.query(LawDocumentMeta)
        .filter_by(identity_id=identity_id)
        .order_by(LawDocumentMeta.language, LawDocumentMeta.id)
        .all()
    )
    originals = [r for r in rows if r.translation_kind == "original"]
    if len(originals) > 1:
        # Two documents claiming to be the untranslated text is a real defect (two
        # adapters, one law), and picking one silently would hide it. The FIRST by
        # language/id is returned and the rest are reported as translations, so the
        # group still renders -- and the log line is how anybody finds out.
        _LOG.warning(
            "law identity %s has %d documents claiming translation_kind='original': %s",
            identity_id,
            len(originals),
            ", ".join(r.lane_key for r in originals),
        )
    original = originals[0] if originals else None
    others = tuple(r for r in rows if r is not original)
    return IdentityGroup(
        identity=identity,
        original=original,
        original_state="tracked" if original is not None else "absent",
        translations=others,
    )


def group_for_lane_key(session: Session, lane_key: str) -> IdentityGroup | None:
    """The group one tracked document belongs to. Convenience over ``identity_group``."""
    meta = session.query(LawDocumentMeta).filter_by(lane_key=lane_key).first()
    if meta is None:
        return None
    return identity_group(session, meta.identity_id)


def provenance_of(meta: LawDocumentMeta) -> tuple[str, str | None]:
    """The provenance as a (PHRASE, body) pair — never one rendered string.

    ``translated_by`` NULL means two different things: on an ``original`` there is no
    translator, and on an ``official`` translation we do not know which body published
    it. So the pair is read, never the field alone.

    EVERY PHRASE IS A COMPLETE SENTENCE AND THE BODY IS DATA BESIDE IT. The first draft
    returned templates ("An official translation published by {body}") and the caller
    filled them in — which produces a text node that can match no key in any locale,
    because the i18n walker compares a node's whole text EXACTLY. There is no ``tf`` on
    a server-rendered page, so the fix is not a better template: it is phrases that need
    none. The body renders as a sibling element, in parentheses, which also spares every
    translator a sentence whose word order is fixed by English.
    """
    kind = meta.translation_kind
    who = (meta.translated_by or "").strip() or None
    if kind == "unrecorded":
        return "Whether this is the original text or a translation is not recorded", None
    if kind == "original":
        return "The original text as issued", None
    if kind == "official":
        if who:
            return "An official translation", who
        return "An official translation; the publishing body is not recorded", None
    if kind == "intergovernmental":
        if who:
            return "A translation published by an intergovernmental body", who
        return (
            "A translation published by an intergovernmental body; which one is not recorded",
            None,
        )
    if who:
        return "A translation published by another government", who
    return "A translation published by another government; which one is not recorded", None


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_provisions(
    session: Session,
    *,
    document_lane_key: str,
    revision_lane_key: str,
    provisions: Iterable[Provision],
) -> int:
    """Store one version's provisions at their stable addresses (Q904, Q906).

    REPLACES this version's provisions rather than merging: a re-parse of the same
    version with a better adapter should leave the version's provision set exactly as
    the new parse says, and a merge would leave orphans from the old parse that no
    longer exist in the document.

    A DUPLICATE ADDRESS IN ONE VERSION IS DROPPED, NOT STORED. ``Provision.identifier``
    falls back to the heading and then to the element name, so two unnumbered provisions
    under one path can genuinely collide; the unique index would raise on the second.
    Dropping it loses text, which is why the count returned is the count STORED — a
    caller comparing it against the provisions it handed in sees the loss rather than
    being told everything landed.
    """
    session.query(LawProvision).filter_by(revision_lane_key=revision_lane_key).delete()
    seen: set[str] = set()
    stored = 0
    for ordinal, prov in enumerate(provisions):
        address = prov.identifier
        if address in seen:
            _LOG.warning(
                "law revision %s: duplicate provision address %r dropped",
                revision_lane_key,
                address,
            )
            continue
        seen.add(address)
        session.add(
            LawProvision(
                revision_lane_key=revision_lane_key,
                document_lane_key=document_lane_key,
                address=address[:512],
                ordinal=ordinal,
                num=prov.number,
                heading=prov.heading,
                text=prov.text or "",
                content_hash=_hash(prov.text or ""),
            )
        )
        stored += 1
    session.flush()
    return stored


def provisions_for(session: Session, revision_lane_key: str) -> Sequence[LawProvision]:
    """One version's provisions in document order."""
    return (
        session.query(LawProvision)
        .filter_by(revision_lane_key=revision_lane_key)
        .order_by(LawProvision.ordinal, LawProvision.id)
        .all()
    )
