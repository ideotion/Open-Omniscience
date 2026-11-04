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

HOW A DECLARATION IS TAKEN BACK. The catalogue is the only writer of these three, so each
has to be retractable from the catalogue, and they are not retracted the same way because
they do not live in the same place:

* ``translation_kind`` is per language version, so the pass writes exactly what the row
  states and ``unrecorded`` when it states nothing: delete the key and the version reads
  ``unrecorded`` on its next pass. (Moving the ``original`` from one version to another
  therefore needs no extra step.)
* ``doc_type`` belongs to the IDENTITY, which every language version's pass writes to. A
  version that states none must not undo one that does, so a row that omits it makes no
  statement and a recorded category stays; to take one back, declare ``doc_type:
  unspecified`` -- an explicit statement like any other.
* the identity is read fresh each pass: delete or change it and that version is re-filed on
  its next pass (the identity it left stays, with its other members).

A declared value must be a STRING. YAML reads an unquoted ``1.10`` as the float 1.1, ``0123``
as the octal 83 and ``yes`` as true; coercing those would have given two different laws one
identity with nothing to say so, so a non-string is refused by name.

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
    IDENTITY_SCHEMES,
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
            # `map(str, ...)`: a YAML key can be an int, a bool or null (`on:`, `yes:`, `1:`), and sorting a mix of those
            # with a string key raised TypeError out of a function the tracker and the validator both call.
            unknown = sorted(map(str, set(block) - _IDENTITY_KEYS))
            if unknown:
                problems.append(f"identity has unknown keys {unknown}; only scheme and value are read")
            # Strings only, never coerced. YAML reads an unquoted `1.10` as the float 1.1, `0123` as the octal 83 and
            # `yes` as true, so two different laws (`1.10`, `1.1`) would have shared one identity with nothing to say so.
            for field in ("scheme", "value"):
                if not isinstance(block.get(field), str):
                    problems.append(f"identity.{field} must be a string (quote it in the YAML), got {block.get(field)!r}")
            if all(isinstance(block.get(field), str) for field in ("scheme", "value")):
                problems.extend(_identity_vocabulary_problems(row, block["scheme"], block["value"]))
    for field, allowed, refused in (
        ("doc_type", DOC_TYPES, _REFUSED_DOC_TYPES),
        ("translation_kind", TRANSLATION_KINDS, {}),
    ):
        if field not in row:
            continue
        offered = row[field]
        if not isinstance(offered, str):
            problems.append(f"{field} must be a string, got {offered!r}")
            continue
        token = offered.strip().lower()
        if token in allowed:
            continue
        if token in refused:
            problems.append(f"{field}={token!r} is refused: {refused[token]}")
        else:
            problems.append(f"{field}={offered!r} is not one of {', '.join(allowed)}; the vocabulary is closed")
    return problems


def _identity_vocabulary_problems(row: Mapping, scheme: str, value: str) -> list[str]:
    """The model's three refusals for an identity, worded here from the vocabularies rather than from the exception.

    The wording is built from the offered value and the model's own constants, not from ``LawModelError``'s text:
    ``tests/test_sink_sweep_records.py`` keeps exception words out of anything that is returned, logged or stored,
    and this list is all three. :func:`document_identity_for` stays the one place the triple is FORMED (a final
    call below catches whatever these three checks did not foresee), so the two cannot quietly drift apart."""
    out: list[str] = []
    if scheme.strip().lower() not in IDENTITY_SCHEMES:
        out.append(f"identity.scheme={scheme!r} is not one of {', '.join(IDENTITY_SCHEMES)}; the vocabulary is closed")
    if not " ".join(value.split()):
        out.append("identity.value is empty; an identity nobody stated is not one")
    alpha = _alpha3(row)
    if len(alpha) != 3 or not alpha.isalpha():
        out.append(f"jurisdiction {row.get('jurisdiction')!r} is not ISO 3166-1 alpha-3 (or INT), which an identity is keyed on")
    if not out:
        try:
            document_identity_for(scheme, jurisdiction_alpha3=alpha, value=value)
        except LawModelError:
            out.append("the law model refused this identity (document_identity_for)")
    return out


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
            row["identity"]["scheme"], jurisdiction_alpha3=_alpha3(row), value=row["identity"]["value"]
        )
    kind = None
    if "doc_type" in row:
        kind = _one_of(row["doc_type"], DOC_TYPES, "doc_type")
    translation = None
    if "translation_kind" in row:
        translation = _one_of(row["translation_kind"], TRANSLATION_KINDS, "translation_kind")
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
        key = document_identity_for(block["scheme"], jurisdiction_alpha3=_alpha3(row), value=block["value"])
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

