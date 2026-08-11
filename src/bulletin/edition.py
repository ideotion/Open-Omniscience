"""
The edition — Layer A, optionally narrated.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §4. This is the only place the two layers meet, and they meet by
ADJACENCY: Layer B's paragraphs sit beside the story facts they narrate, never
interleaved into them, so a reader can always see which sentences a model wrote.

Narration is off by default. An edition built without it is complete; an edition
built with it is the same document plus prose. That asymmetry is deliberate — it
is what "removable" means in practice rather than in a docstring.
"""

from __future__ import annotations

import logging

from src.bulletin.period import Period

_LOG = logging.getLogger(__name__)


def build_edition(
    session,
    period: Period,
    *,
    narrate: bool = False,
    rising_limit: int = 20,
    target_lang: str | None = None,
    max_stories: int = 8,
    story_budget_chars: int | None = None,
    story_articles: int = 4,
    cluster_stories: bool = True,
    model: str | None = None,
    client=None,
) -> dict:
    """Assemble one edition.

    ``narrate=False`` (the default) returns PHASE ONE: everything this corpus can
    answer without a model. Turning narration on ADDS a ``narration`` block and
    sentences beside the stories; it changes no number already there.

    STORY CLUSTERING IS PHASE ONE, NOT PHASE TWO (2026-08-11). It used to run only
    when narration did, on the stated ground that "there is nothing to narrate
    without one" — which explains why clustering runs WITH narration and not why it
    cannot run without it. Clustering is MinHash over stored keywords: no model, no
    network, deterministic. Coupling it to narration meant the AI-less document had
    no stories at all, so the deterministic half of the maintainer's two-phase design
    was missing its narrative spine and phase 2's worklist had nothing to list.
    ``cluster_stories=False`` restores the older, narrower behaviour exactly.

    Everything degrades independently: a clustering failure leaves the deterministic
    record intact, and a narration failure leaves the clusters intact.
    """
    from src.bulletin.facts import layer_a

    edition = layer_a(session, period, rising_limit=rising_limit, target_lang=target_lang)
    edition["narration_requested"] = bool(narrate)

    if not cluster_stories:
        return edition

    from src.bulletin.stories import build_stories

    try:
        stories = build_stories(session, period, limit=max_stories)
    except Exception as exc:  # noqa: BLE001 - the record survives a clustering failure
        _LOG.warning("bulletin: story clustering failed", exc_info=True)
        edition["stories"] = {"stories": [], "error": f"{type(exc).__name__}: {exc}"}
        if narrate:
            edition["narration"] = {
                "layer": "B",
                "available": False,
                "reason": "stories could not be built, so there was nothing to narrate",
                "paragraphs": [],
            }
        return edition

    edition["stories"] = stories

    # A story is a set of articles, so the document can name them. Bounded per story
    # and best-effort: the clusters are the record, and an unreadable body must not
    # cost them.
    if story_articles > 0:
        from src.bulletin.articles import article_rows

        for story in stories.get("stories") or []:
            try:
                story["article_rows"] = article_rows(
                    session, list(story.get("article_ids") or []), limit=int(story_articles)
                )
            except Exception:  # noqa: BLE001
                _LOG.debug("bulletin: could not describe a story's articles", exc_info=True)

    if not narrate:
        return edition

    from src.bulletin.narration import DEFAULT_STORY_BUDGET_CHARS
    from src.bulletin.narration import narrate as run_narration
    from src.bulletin.stories import story_evidence

    budget = int(story_budget_chars or DEFAULT_STORY_BUDGET_CHARS)

    edition["narration"] = run_narration(
        stories.get("stories") or [],
        lambda story: story_evidence(session, story["article_ids"], budget_chars=budget),
        language=target_lang,
        model=model,
        client=client,
        max_stories=max_stories,
    )

    # Adjacency, not interleaving: each paragraph is attached to its story by the
    # article ids both already carry, so a renderer can place them side by side
    # without either layer having to know the other's shape.
    #
    # A DANGLING JOIN IS REPORTED, never absorbed. This join silently produced
    # nothing for a year because the two sides populated the key differently — the
    # story's full cluster against the subset the model was shown — and an empty
    # `story["narration"]` looks exactly like a story nobody tried to narrate. The
    # key is fixed at the source (narration.narrate_story); the count below is what
    # makes a future divergence say so instead of vanishing.
    by_ids = {
        tuple(p.get("article_ids") or []): p for p in edition["narration"].get("paragraphs") or []
    }
    attached = 0
    for story in stories.get("stories") or []:
        para = by_ids.get(tuple(story.get("article_ids") or []))
        if para is not None:
            attached += 1
            story["narration"] = {
                "text": para.get("text"),
                "narrated": para.get("narrated", False),
                "model": para.get("model"),
                "prompt_version": para.get("prompt_version"),
                "partial": para.get("partial", False),
                "fallback_reason": para.get("fallback_reason"),
            }
    shown = len(stories.get("stories") or [])
    edition["narration"]["paragraphs_attached"] = attached
    if attached < shown:
        edition["narration"]["attach_gap"] = (
            f"{shown - attached} of {shown} stories could not be matched to a paragraph "
            "by article ids — the two sides disagree about the key, so those stories "
            "carry no sentence here even though one may have been written."
        )

    # What the edition SAYS about its narration is built from what happened, not
    # from what was requested. The unconditional version claimed "the sentences
    # under each story were written by a local model" on an edition where the model
    # was unreachable and nought of eight stories had been narrated.
    narrated = int(edition["narration"].get("stories_narrated") or 0)
    if narrated:
        edition["caveat"] = (
            edition.get("caveat", "")
            + f" This edition carries a narration layer over {narrated} of {shown} "
            "stories: those sentences were written by a local model and kept only "
            "because every figure and name in them appears in the articles it was "
            "shown. They are marked AI-derived and can be removed without losing "
            "anything the record states."
        )
    else:
        edition["caveat"] = (
            edition.get("caveat", "")
            + " Narration was requested and produced nothing: no sentence here was "
            "written by a model. Each story carries a deterministic sentence composed "
            "from its own counts, and the reason the model produced nothing is "
            "recorded beside it."
        )
    return edition
