"""
Review — what the operator decides before an edition leaves this machine.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §12 (per-producer toggles driven by the actual content), §13
(draft → review → publish; automation reaches a draft and stops, because the
operator is the byline).

THE MECHANIC, and the reason this module is pure: **toggling re-renders from the
persisted JSON. Output is never hand-edited.** Excluding a section does not
recompute anything and does not touch the record on disk — it filters a COPY of
the edition on its way to the renderer. So a number in a published document is
always a number the record contains, and an operator cannot, even by accident,
produce a document the record cannot account for.

TWO choices here are deliberate and easy to get backwards:

* Selections are **exclusions, not inclusions.** A stale selection made before a
  section existed must not silently drop it — the same trap as an aggregation
  keyed only by observed entries, where "absent" quietly reads as "judged and
  rejected". Absent means included.
* An exclusion is **disclosed in the rendered document.** The operator chooses
  what to publish, but a reader of a document that silently omits three of its
  seven sections has no way to know they are reading a selection. The count of
  what was left out travels with the document.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# A story is identified by the articles it is made of. That identity is stable
# across a re-render (the record does not change) and meaningless to anything
# else, which is exactly what an operator's selection should be keyed on.
StoryKey = str


def story_key(story: dict[str, Any]) -> StoryKey:
    """The identity of a story, as a selection key."""
    return ",".join(str(int(i)) for i in (story.get("article_ids") or []))


def review_view(edition: dict[str, Any]) -> dict[str, Any]:
    """The edition as a set of decisions, with the evidence for each one.

    Per §13 the review screen shows, per sentence, whether it passed validation
    or fell back to a template — so this joins the story facts to the per-sentence
    verdicts the narration recorded, which the edition keeps in two places (the
    summary beside each story, the detail in the narration block).

    Read-only and pure. Nothing here decides anything; it lays out what there is
    to decide.
    """
    sections = []
    for s in edition.get("sections") or []:
        key = str(s.get("section") or "")
        row: dict[str, Any] = {
            "section": key,
            "window": s.get("window") or {},
            "caveat": s.get("caveat"),
            "method": s.get("method"),
            "rows": _row_count(s),
        }
        # A section that failed or skipped is SHOWN as such rather than hidden:
        # an operator deciding what to publish should see that a producer had
        # nothing to say and why, not find it missing from the list.
        if s.get("error"):
            row["error"] = s["error"]
        if s.get("skipped"):
            row["skipped"] = s["skipped"]
        sections.append(row)

    by_key = {}
    for para in (edition.get("narration") or {}).get("paragraphs") or []:
        by_key[",".join(str(int(i)) for i in (para.get("article_ids") or []))] = para

    stories = []
    for st in (edition.get("stories") or {}).get("stories") or []:
        k = story_key(st)
        para = by_key.get(k) or {}
        nar = st.get("narration") or {}
        stories.append(
            {
                "key": k,
                "articles": st.get("articles"),
                "distinct_sources": st.get("distinct_sources"),
                "single_source": st.get("single_source", False),
                "shared_terms": st.get("shared_terms") or [],
                "narrated": bool(nar.get("narrated")),
                "partial": bool(nar.get("partial")),
                "fallback_reason": nar.get("fallback_reason"),
                "text": nar.get("text"),
                # The per-sentence verdicts: kept, or dropped and why. This is the
                # §13 requirement — a sentence the operator can see was checked is
                # a different thing from a paragraph labelled "validated".
                "sentences": [
                    {
                        "text": sent.get("text"),
                        "kept": bool(sent.get("kept")),
                        "unsupported": sent.get("unsupported") or [],
                        "checks_applied": sent.get("checks_applied") or [],
                    }
                    for sent in (para.get("sentences") or [])
                ],
            }
        )

    return {
        "filename": edition.get("filename"),
        "state": edition.get("state", "draft"),
        "period": edition.get("period") or {},
        "sections": sections,
        "stories": stories,
        "method": (
            "Every section and story is included unless excluded here. Excluding one "
            "re-renders from the persisted record — it recomputes nothing and edits "
            "nothing, so a published number is always a number the record contains."
        ),
        "caveat": (
            "This is a DRAFT until you publish it. Nothing here has left this machine. "
            "What you exclude is left out of the rendered document and the exclusion is "
            "stated in it, so a reader knows they are reading a selection."
        ),
    }


def _row_count(section: dict[str, Any]) -> int:
    """How many rows a section would render — the operator's basis for keeping it."""
    n = 0
    for key in ("terms", "topics", "channels", "by_event_type", "years"):
        n += len(section.get(key) or [])
    for key in ("law_revisions", "wiki_revisions"):
        if section.get(key) is not None:
            n += 1
    return n


def apply_selection(
    edition: dict[str, Any],
    *,
    exclude_sections: Iterable[str] | None = (),
    exclude_stories: Iterable[str] | None = (),
) -> dict[str, Any]:
    """A COPY of ``edition`` with the operator's exclusions applied.

    The record on disk is never touched. Exclusions are applied on the way to the
    renderer, which is what makes a toggle a re-render rather than a
    re-computation — and what makes it impossible for a published document to
    contain a number the record does not.

    Unknown names are ignored rather than refused: a selection saved before a
    section was renamed should drop the stale entry, not fail the render. What it
    must never do is silently drop a section it does not recognise, which is why
    this takes exclusions rather than inclusions.
    """
    drop_s = {str(x) for x in (exclude_sections or ())}
    drop_t = {str(x) for x in (exclude_stories or ())}
    if not drop_s and not drop_t:
        return edition

    out = dict(edition)

    sections = list(edition.get("sections") or [])
    kept_sections = [s for s in sections if str(s.get("section") or "") not in drop_s]
    out["sections"] = kept_sections

    stories_block = edition.get("stories") or {}
    all_stories = list(stories_block.get("stories") or [])
    kept_stories = [s for s in all_stories if story_key(s) not in drop_t]
    if stories_block:
        out["stories"] = dict(stories_block, stories=kept_stories)

    out["selection"] = {
        "sections_shown": len(kept_sections),
        "sections_total": len(sections),
        "stories_shown": len(kept_stories),
        "stories_total": len(all_stories),
        "sections_excluded": sorted(
            {str(s.get("section") or "") for s in sections} & drop_s
        ),
        "note": (
            "The operator excluded part of this edition before publishing it. The "
            "record it was rendered from is unchanged and still contains everything."
        ),
    }
    return out
