"""Q711's section-awareness: WHICH part of a page changed, from the wikitext itself.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q711 = a: "Against the previous ingested version, section-aware (which section
changed), per-mention revid anchoring per the standing ruling."

THE ANCHOR HALF NEEDS NO CODE HERE, AND THAT IS A FINDING RATHER THAN AN OMISSION.
The standing ruling (``OPEN_QUEUE.md``, 2026-09-07) records that the mechanism
deliberately deviates from the "per-mention revid anchoring" shorthand: the anchor is
``Article.source_revision`` and mentions inherit it through their article. So there is
no new column and no per-mention write — the shorthand names an outcome the existing
shape already delivers. Written down because the obvious reading of Q711 is a schema
change, and a session that made one would be undoing a decision nobody recorded here.

"AGAINST THE PREVIOUS INGESTED VERSION" IS ALREADY THE SUBSTRATE'S. ``revisions.py``
diffs each stored version against its predecessor and says so in its own docstring,
including the honest caveat that a budget may have skipped the version in force. This
module adds only the SECTION dimension, and it adds it as a PURE function over two
texts — no database, no network — so the whole of it runs in a test and can be called
on a pair of strings from anywhere.

WHAT A "SECTION" IS HERE, STATED BECAUSE IT IS AN APPROXIMATION. MediaWiki section
headings are ``== Title ==`` on a line of their own, one ``=`` per level. This module
reads exactly that and nothing else: it does not expand templates, so a heading
produced by a template is invisible to it; it does not parse ``<nowiki>`` or comment
blocks, so a heading-shaped line inside one is counted as a heading. Both limits are
DISCLOSED on the result rather than silently absorbed, because a "which section
changed" answer that is confidently wrong is worse than one that says where its
confidence ends.

THE LEAD IS A SECTION AND IT IS NAMED. Text before the first heading is the article's
lead, which is the part a reader sees first and the part most edits touch. Reporting
it as "no section" would hide the most common change there is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: ``== Heading ==`` on its own line. Up to six levels, MediaWiki's own limit. The
#: trailing ``=`` run is matched independently of the leading one on purpose: real
#: wikitext carries mismatched pairs, MediaWiki renders them, and refusing to read one
#: would silently merge two sections into one.
_HEADING = re.compile(r"^[ \t]*(={1,6})[ \t]*(.+?)[ \t]*=+[ \t]*$", re.M)

#: The name for text before the first heading. A TOKEN, not a sentence: the words an
#: operator reads are composed by the UI and ship ×12.
LEAD: str = "__lead__"

#: How many changed sections one result will name. A page rewritten end to end changes
#: every section, and a list of two hundred is not an answer to "what changed" — it is
#: the diff again, longer. Past this the result says ``truncated`` and the count stays
#: exact, because the COUNT is cheap and honest even when the list is not useful.
MAX_REPORTED: int = 40


@dataclass(frozen=True, slots=True)
class Section:
    """One section of a wikitext page, as the source wrote it."""

    #: ``1``–``6``; ``0`` for the lead, which has no heading of its own.
    level: int
    #: The heading text, or :data:`LEAD`. Raw — markup inside a heading is the
    #: source's, and cleaning it here would make two pages with different markup look
    #: like the same section.
    title: str
    body: str

    @property
    def is_lead(self) -> bool:
        return self.title == LEAD


@dataclass(frozen=True, slots=True)
class SectionChange:
    """One section's fate between two versions."""

    #: ``added`` | ``removed`` | ``changed``. A closed vocabulary; there is no
    #: "unchanged" member, because this list is the changes and an unchanged section
    #: belongs in it as much as a page nobody edited belongs in a change feed.
    kind: str
    title: str
    level: int
    #: Characters gained and lost, from the section bodies. NOT a percentage and not a
    #: significance: a one-character change to a date can matter more than a rewritten
    #: paragraph, and this app does not rank other people's edits.
    added_chars: int = 0
    removed_chars: int = 0


@dataclass(frozen=True, slots=True)
class SectionDiff:
    """What changed between two versions, by section, with its own limits attached."""

    changes: tuple[SectionChange, ...] = ()
    #: How many sections changed IN TOTAL, which may exceed ``len(changes)``.
    total_changed: int = 0
    truncated: bool = False
    #: Sections present in both and identical. Reported as a COUNT so a reader can see
    #: how much of the page the edit did not touch — the denominator without which
    #: "three sections changed" says nothing.
    unchanged: int = 0
    #: True when either side had no headings at all, so the whole page is one lead
    #: section and "which section changed" has no finer answer to give.
    flat: bool = False
    caveat: str = ""
    duplicate_titles: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "changes": [
                {
                    "kind": c.kind,
                    "title": c.title,
                    "level": c.level,
                    "added_chars": c.added_chars,
                    "removed_chars": c.removed_chars,
                }
                for c in self.changes
            ],
            "total_changed": self.total_changed,
            "truncated": self.truncated,
            "unchanged": self.unchanged,
            "flat": self.flat,
            "duplicate_titles": list(self.duplicate_titles),
            "method": (
                "wikitext '== heading ==' lines only: templates are not expanded, and "
                "<nowiki>/comment blocks are not parsed. Sizes are characters of the "
                "section body, never a percentage or a significance."
            ),
            "caveat": self.caveat,
        }


def split_sections(wikitext: str) -> list[Section]:
    """Split a page into its sections, the lead first.

    A page with no headings is ONE lead section holding the whole text — not an empty
    list. An empty list would make "the page changed but no section did", which is
    never true of a page that has text.
    """
    text = wikitext or ""
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [Section(level=0, title=LEAD, body=text)]
    out = [Section(level=0, title=LEAD, body=text[: matches[0].start()])]
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append(
            Section(level=len(m.group(1)), title=m.group(2), body=text[m.end() : end])
        )
    return out


def _by_title(sections: list[Section]) -> tuple[dict[str, Section], list[str]]:
    """Index sections by title, and report the titles that appeared more than once.

    DUPLICATE HEADINGS ARE REAL and this is where they are handled honestly. Wikipedia
    pages carry repeated "References" or "History" headings under different parents,
    and a plain dict keeps only the last. The FIRST wins here — it is the one a reader
    reaches first — and every repeated title is reported, so a caller can say that the
    section answer is ambiguous for those rather than presenting a guess as a fact.
    """
    index: dict[str, Section] = {}
    duplicates: list[str] = []
    for section in sections:
        if section.title in index:
            if section.title not in duplicates:
                duplicates.append(section.title)
            continue
        index[section.title] = section
    return index, duplicates


def section_diff(previous: str | None, current: str, *, limit: int = MAX_REPORTED) -> SectionDiff:
    """Which sections changed between two versions of one page.

    ``previous is None`` means there is no earlier version here — a baseline. The
    result is then EMPTY rather than "every section was added": a first sighting is not
    an edit, and reporting one as a page rewritten from nothing would put a fabricated
    event in every timeline this feeds.
    """
    if previous is None:
        return SectionDiff(
            caveat="This is the first version stored here, so there is nothing to compare it with."
        )
    old_sections = split_sections(previous)
    new_sections = split_sections(current)
    flat = len(old_sections) == 1 and len(new_sections) == 1
    old_index, old_dupes = _by_title(old_sections)
    new_index, new_dupes = _by_title(new_sections)
    duplicates = tuple(dict.fromkeys(old_dupes + new_dupes))

    changes: list[SectionChange] = []
    unchanged = 0
    # NEW-SIDE ORDER, so the list reads down the page as it now stands rather than in
    # whatever order a set happened to yield.
    #
    # ONE ENTRY PER DISTINCT TITLE, and the guard is load-bearing rather than tidy.
    # Walking the LIST on a page with a repeated heading emitted that title twice and
    # compared the SECOND occurrence's body against the FIRST occurrence's old body --
    # two sections that are not the same section, reported as a change that did not
    # happen. The index above already picked the first occurrence as the one this
    # answer is about; this makes the walk agree with it, and ``duplicate_titles``
    # carries the ambiguity to the reader instead of a fabricated second row.
    emitted: set[str] = set()
    for section in new_sections:
        if section.title in emitted:
            continue
        emitted.add(section.title)
        before = old_index.get(section.title)
        if before is None:
            changes.append(
                SectionChange("added", section.title, section.level, len(section.body), 0)
            )
        elif before.body != section.body:
            gained = max(0, len(section.body) - len(before.body))
            lost = max(0, len(before.body) - len(section.body))
            changes.append(SectionChange("changed", section.title, section.level, gained, lost))
        else:
            unchanged += 1
    for section in old_sections:
        if section.title not in new_index:
            changes.append(
                SectionChange("removed", section.title, section.level, 0, len(section.body))
            )

    total = len(changes)
    truncated = total > limit
    caveat = (
        "Sections are matched by heading text, so a renamed section reads as one "
        "removed and one added."
    )
    if duplicates:
        caveat += (
            " This page repeats a heading, so the section named for it is the first "
            "one on the page and the answer is ambiguous for it."
        )
    if truncated:
        caveat += f" {total} sections changed; the first {limit} are listed."
    return SectionDiff(
        changes=tuple(changes[:limit]),
        total_changed=total,
        truncated=truncated,
        unchanged=unchanged,
        flat=flat,
        caveat=caveat,
        duplicate_titles=duplicates,
    )
