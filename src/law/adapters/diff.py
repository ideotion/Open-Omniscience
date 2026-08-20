"""
Per-provision diff — which SECTIONS changed, not which lines.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The existing law tracker diffs normalised text (``src.law.track._diff``), which answers
"did this document change, and by how many bytes". That is the right question for a
document read from a web page, because a web page has no addressable structure to speak
of. Once a document is read from the publisher's own XML it does: every provision has a
citable identity, so the question can become the one a reader actually asks — *which
sections changed?*

This layer is ADDITIVE and EXPERIMENTAL. It does not replace the normalised-text diff:
that one still runs, still decides whether a revision is recorded, and still carries the
large-change flag. This only says, of a change already detected, which provisions it
touched.

IDENTITY, AND ITS ONE HONEST LIMIT. A provision is matched by
:attr:`~src.law.adapters.Provision.identifier` — its container path plus its number —
never by position, because inserting a section renumbers every index below it and a
position-matched diff would then report the entire rest of the Act as amended. The limit
that buys: a provision that is renumbered AND amended in the same revision appears as one
removal plus one addition rather than as a change. That is reported as such (``moved``
covers the renumbered-but-identical case), and it is stated rather than smoothed over,
because guessing that two differently-numbered provisions are "the same one, edited"
means guessing at an amendment nobody made.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.law.adapters import ParsedLaw, Provision


@dataclass
class ProvisionChange:
    """One provision's fate between two readings. Text lengths, never a similarity score."""

    identifier: str
    status: str  # added | removed | changed | moved
    heading: str | None = None
    chars_before: int | None = None
    chars_after: int | None = None

    @property
    def delta_chars(self) -> int | None:
        if self.chars_before is None or self.chars_after is None:
            return None
        return self.chars_after - self.chars_before

    def as_dict(self) -> dict:
        return {
            "identifier": self.identifier,
            "status": self.status,
            "heading": self.heading,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "delta_chars": self.delta_chars,
        }


@dataclass
class SectionDiff:
    """Which provisions changed between two parses of one document."""

    changes: list[ProvisionChange] = field(default_factory=list)
    unchanged: int = 0
    provisions_before: int = 0
    provisions_after: int = 0

    @property
    def touched(self) -> int:
        return len(self.changes)

    def by_status(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.changes:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    def as_dict(self) -> dict:
        return {
            "provisions_before": self.provisions_before,
            "provisions_after": self.provisions_after,
            "unchanged": self.unchanged,
            "touched": self.touched,
            "by_status": dict(sorted(self.by_status().items())),
            "changes": [c.as_dict() for c in self.changes],
            "method": (
                "Provisions matched by citable identity (container path + number), never "
                "by position: inserting one section must not report every section below "
                "it as amended. `moved` is a provision whose text is unchanged but whose "
                "path or number is not."
            ),
            "caveat": (
                "A provision that is renumbered AND amended in the same revision appears "
                "as one removal plus one addition, because matching it to its former self "
                "would mean guessing which of two differently-numbered provisions is "
                "\"the same one, edited\". Experimental, and additive: the document-level "
                "text diff is unchanged and still decides whether a revision is recorded."
            ),
        }


def _index(doc: ParsedLaw) -> dict[str, Provision]:
    """Provisions by identifier.

    A duplicate identifier (two provisions the document numbers identically) would
    silently overwrite: keep the FIRST and leave the later one to surface as an
    add/remove rather than replacing a provision the reader can cite.
    """
    out: dict[str, Provision] = {}
    for p in doc.provisions:
        out.setdefault(p.identifier, p)
    return out


def diff_provisions(before: ParsedLaw, after: ParsedLaw) -> SectionDiff:
    """Which provisions were added, removed, changed or moved."""
    old, new = _index(before), _index(after)
    changes: list[ProvisionChange] = []
    unchanged = 0

    # Text-identical provisions that only moved: matched on text so a renumbering is
    # reported as a move rather than as a deletion plus an unrelated insertion.
    old_by_text: dict[str, list[str]] = {}
    for ident, p in old.items():
        if ident not in new:
            old_by_text.setdefault(p.text, []).append(ident)

    for ident, p in new.items():
        prior = old.get(ident)
        if prior is None:
            moved_from = old_by_text.get(p.text)
            if moved_from and p.text:
                origin = moved_from.pop(0)
                changes.append(
                    ProvisionChange(
                        identifier=f"{origin} -> {ident}",
                        status="moved",
                        heading=p.heading,
                        chars_before=len(p.text),
                        chars_after=len(p.text),
                    )
                )
                continue
            changes.append(
                ProvisionChange(
                    identifier=ident,
                    status="added",
                    heading=p.heading,
                    chars_before=None,
                    chars_after=len(p.text),
                )
            )
        elif prior.text != p.text or prior.heading != p.heading:
            changes.append(
                ProvisionChange(
                    identifier=ident,
                    status="changed",
                    heading=p.heading,
                    chars_before=len(prior.text),
                    chars_after=len(p.text),
                )
            )
        else:
            unchanged += 1

    # Whatever is LEFT in old_by_text was never claimed as a move origin, so it really
    # did go. (Reading the leftovers, rather than re-deriving the set, is what keeps this
    # in step with the pops above.)
    still_removed = {i for ids in old_by_text.values() for i in ids}
    for ident, p in old.items():
        if ident in new or ident not in still_removed:
            continue  # present in the new reading, or already reported as a move origin
        changes.append(
            ProvisionChange(
                identifier=ident,
                status="removed",
                heading=p.heading,
                chars_before=len(p.text),
                chars_after=None,
            )
        )

    changes.sort(key=lambda c: (c.status, c.identifier))
    return SectionDiff(
        changes=changes,
        unchanged=unchanged,
        provisions_before=len(before.provisions),
        provisions_after=len(after.provisions),
    )
