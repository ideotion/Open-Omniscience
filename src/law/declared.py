"""A document identity the CATALOGUE declares, read back by URL (v0.6.0 C-L2; Q908, Q901's note).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. ``src/law/lane_sync.py`` keys a law on the publisher's own number where
an adapter read one and otherwise on the document's URL (``local``). Every adapter this
tree has reads a number out of the BODY, and a treaty page offers none a parser could
trust: a treaty published in six languages is six URLs, so it landed as six unrelated
``local`` identities and Q908's "one document identity, N language versions" never held
for the one kind of instrument that is published in several languages by construction.

THE FIX IS A DECLARATION, NOT A GUESS. A ``documents:`` row in the catalogue may state

``identity: {scheme: act-number, value: "..."}``
    which law this row is a version of. The value is the operator's statement, written
    where the operator already writes down the URL, and NEVER derived from the URL: a
    path segment that happens to repeat across six languages is exactly the "looks
    unique" evidence the model's own docstring warns against.
``doc_type``
    one of Q902's categories (``treaty`` for an instrument between states).
``translation_kind``
    what THIS language version is (Q901's a/b/c, ``original``, or ``unrecorded``).

All three are optional and independent. A row declaring none behaves byte-for-byte as it
did before this module existed -- which is why the lookup returns ``None`` rather than a
default, and why a malformed declaration is treated as ABSENT (logged, and named by the
catalogue validator) instead of half-applied: a typo that quietly files a language
version under the wrong law is worse than one that leaves it ungrouped and says so.

THE LOOKUP KEY IS THE ROW'S OWN ``(jurisdiction, url)`` -- the pair the corpus roster is
keyed on -- by exact string equality. It is not a host match (``source_for_url`` is, and
for a different question): six languages share a host, and a host match would hand one
declaration to every document the host serves.

Pure functions only. No database, no network, no filesystem: the caller hands in the
already-loaded catalogue.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.catalog.countries import country_display_code
from src.law.catalog import law_jurisdiction
from src.law.model import (
    _REFUSED_DOC_TYPES,
    DOC_TYPES,
    TRANSLATION_KINDS,
    LawModelError,
    _one_of,
    document_identity_for,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Mapping

_LOG = logging.getLogger(__name__)

#: The three keys a document row may use to declare. Anything else is the catalogue's own
#: (``title``, ``language``...) and none of this module's business.
DECLARATION_KEYS: tuple[str, ...] = ("identity", "doc_type", "translation_kind")
_IDENTITY_KEYS = frozenset({"scheme", "value"})


@dataclass(frozen=True, slots=True)
class Declared:
    """What one catalogue row declares, normalised. Every field is ``None`` when unstated."""

    scheme: str | None = None
    value: str | None = None
    doc_type: str | None = None
    translation_kind: str | None = None

    @property
    def has_identity(self) -> bool:
        return bool(self.scheme and self.value)


def _alpha3(row: Mapping) -> str:
    return (country_display_code(row.get("jurisdiction")) or "").strip().upper()


def declaration_problems(row: Mapping) -> list[str]:
    """Every reason this row's declaration is unusable, in words. ``[]`` when it is fine or absent.

    The same function serves the catalogue validator, the repo-wide test over the committed
    files, and the runtime lookup, so what CI accepts is exactly what the tracker applies --
    two copies of a rule is how a validator comes to pass what the tracker then ignores.
    """
    problems: list[str] = []
    if "identity" in row:
        block = row["identity"]
        if not isinstance(block, dict):
            problems.append("identity must be a mapping {scheme, value}")
        else:
            unknown = sorted(set(block) - _IDENTITY_KEYS)
            if unknown:
                problems.append(f"identity has unknown keys {unknown}; only scheme and value are read")
            try:
                document_identity_for(
                    str(block.get("scheme") or ""),
                    jurisdiction_alpha3=_alpha3(row),
                    value=str(block.get("value") or ""),
                )
            except LawModelError as exc:
                problems.append(f"identity refused: {exc}")
    if "doc_type" in row:
        try:
            _one_of(str(row["doc_type"] or ""), DOC_TYPES, "doc_type", refused=_REFUSED_DOC_TYPES)
        except LawModelError as exc:
            problems.append(str(exc))
    if "translation_kind" in row:
        try:
            _one_of(str(row["translation_kind"] or ""), TRANSLATION_KINDS, "translation_kind")
        except LawModelError as exc:
            problems.append(str(exc))
    return problems


def declared_of(row: Mapping) -> Declared | None:
    """The normalised declaration on one catalogue row, or ``None`` if it declares nothing usable.

    A row with ANY problem yields ``None`` as a whole: the three declarations describe one
    document, and applying the two that parse while dropping the one that did not would
    record a half-statement nobody made.
    """
    if not any(key in row for key in DECLARATION_KEYS):
        return None
    problems = declaration_problems(row)
    if problems:
        _LOG.warning(
            "law catalogue row %r declares an identity the model refuses; treated as undeclared: %s",
            row.get("url"),
            "; ".join(problems),
        )
        return None
    scheme = value = None
    if "identity" in row:
        scheme, _juris, value = document_identity_for(
            str(row["identity"].get("scheme")),
            jurisdiction_alpha3=_alpha3(row),
            value=str(row["identity"].get("value")),
        )
    kind = None
    if "doc_type" in row:
        kind = _one_of(str(row["doc_type"]), DOC_TYPES, "doc_type")
    translation = None
    if "translation_kind" in row:
        translation = _one_of(str(row["translation_kind"]), TRANSLATION_KINDS, "translation_kind")
    return Declared(scheme=scheme, value=value, doc_type=kind, translation_kind=translation)


def declared_for(catalog: Mapping | None, *, jurisdiction: str | None, url: str | None) -> Declared | None:
    """What the catalogue declares for the document ``(jurisdiction, url)``, or ``None``. Pure.

    Exact equality on both halves of the key. A row for the same URL in another
    jurisdiction, or for a neighbouring URL in the same one, is a different document and
    declares nothing for this one.
    """
    if not catalog or not url or not jurisdiction:
        return None
    wanted = (law_jurisdiction(jurisdiction), url)
    for row in catalog.get("documents") or ():
        # Both sides in the stored spelling: a catalogue read through the loader already is, a hand-built one may not be.
        if (law_jurisdiction(row.get("jurisdiction")), row.get("url")) == wanted:
            return declared_of(row)
    return None


def consistency_problems(documents: Iterable[Mapping]) -> list[str]:
    """Contradictions BETWEEN rows that declare the same law. ``[]`` when there are none.

    Two rows sharing an identity are two language versions of one law, so they must not
    disagree about what KIND of law it is, and at most one may call itself its
    ``original``: the group reader promotes the first and demotes the rest with a log line
    nobody reads, so the contradiction belongs in the catalogue check where a person does.
    """
    by_identity: dict[tuple[str, str, str], list[Mapping]] = {}
    for row in documents:
        if "identity" not in row or declaration_problems(row):
            continue  # per-row problems are reported by declaration_problems itself
        block = row["identity"]
        key = document_identity_for(
            str(block.get("scheme")), jurisdiction_alpha3=_alpha3(row), value=str(block.get("value"))
        )
        by_identity.setdefault(key, []).append(row)

    problems: list[str] = []
    for key, rows in sorted(by_identity.items()):
        declared = [declared_of(r) or Declared() for r in rows]
        types = {d.doc_type for d in declared if d.doc_type}
        if len(types) > 1:
            problems.append(f"identity {key} is declared as {sorted(types)} by different rows; one law has one doc_type")
        originals = [r.get("url") for r, d in zip(rows, declared, strict=True) if d.translation_kind == "original"]
        if len(originals) > 1:
            problems.append(f"identity {key} has {len(originals)} rows declared translation_kind=original: {originals}")
    return problems

