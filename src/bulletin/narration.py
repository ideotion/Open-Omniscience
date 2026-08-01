"""
Layer B — the removable narration.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §4, §6, §7, §8. A local model turns each story's evidence into a
short paragraph. Strip this layer and the document is still complete, just
stiffer — that is the test of whether it was built as an addition or a dependency.

FOUR RULES, and each is enforced here rather than asked of the model:

1. **Grounded in real article text, not in Layer A's counts.** The model reads
   the opening of the story's articles. The earlier draft narrated over fact
   bundles, which could only re-word numbers — prose about prose.
2. **Every sentence is checked before it is kept.** `grounding.check_sentence`
   compares each sentence against the evidence it was given; a sentence carrying
   a figure or name that is not there is DROPPED and the deterministic template
   takes its place. The model does not get the last word on its own output.
3. **Temperature 0 by default, on both backends.** Determinism is a property of
   the edition: regenerating it should not produce different prose.
4. **Provenance per sentence.** Which story, which articles, which model, which
   prompt version, and whether it survived validation or fell back — recorded
   for every sentence, so a reader can always see which sentences a model wrote.

WHAT THE MODEL IS NEVER ASKED TO DO (§8): judge importance, rank anything,
decide what matters, or produce a number. Numbers come from Layer A and are
placed by the template; the model writes around them, and if it invents one the
grounding check removes the sentence.
"""

from __future__ import annotations

import logging
import re
from typing import Any

_LOG = logging.getLogger(__name__)

NARRATION_PROMPT_VERSION = "bulletin-narration-v1"

#: Character budget for ONE story's evidence. Well under the shipped synthesis
#: budget: narration reads one story, not a corpus, and a tighter window keeps the
#: model's attention on the text it must not stray from.
DEFAULT_STORY_BUDGET_CHARS = 6_000

#: Sampling. Temperature 0 because an edition regenerated should read the same;
#: this reaches BOTH backends now that vLLM maps `options` to OpenAI sampling.
DEFAULT_OPTIONS: dict[str, Any] = {"temperature": 0.0, "top_p": 1.0, "seed": 0}

_SYSTEM = (
    "You summarise news coverage. You are given excerpts from several articles that "
    "cover the same story.\n"
    "Write 1 to 3 plain sentences describing WHAT THE COVERAGE SAYS.\n"
    "RULES:\n"
    "- Use ONLY facts stated in the excerpts. Do not add background you happen to know.\n"
    "- Do not invent figures, names, dates or places. If the excerpts do not say it, "
    "do not write it.\n"
    "- Do not say whether anything is important, significant, major or notable.\n"
    "- Do not rank, compare or evaluate the sources.\n"
    "- No preamble, no heading, no closing line. Sentences only."
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _prompt(evidence: dict) -> str:
    parts = ["Excerpts:", ""]
    for e in evidence.get("excerpts") or []:
        title = e.get("title") or "(untitled)"
        parts.append(f"--- article {e['article_id']}: {title}")
        parts.append(e.get("text") or "")
        parts.append("")
    parts.append(
        "Write 1 to 3 sentences describing what this coverage says. "
        "Use only what is above. Do not invent figures or names."
    )
    return "\n".join(parts)


def _evidence_text(evidence: dict) -> str:
    """Everything the model was shown, as one string — the grounding corpus.

    Titles are included: a name that appears only in a headline is still something
    the model was given, and excluding it would produce a false invention report.
    """
    bits: list[str] = []
    for e in evidence.get("excerpts") or []:
        if e.get("title"):
            bits.append(str(e["title"]))
        if e.get("text"):
            bits.append(str(e["text"]))
    return "\n".join(bits)


def deterministic_paragraph(story: dict) -> str:
    """The template a story gets when narration is off, unavailable, or rejected.

    Stiffer than prose and entirely made of Layer A's own counts — which is the
    point: it is what the document says without a model, so the model's absence
    costs style, never substance.
    """
    n = story.get("articles", 0)
    srcs = story.get("distinct_sources", 0)
    terms = story.get("shared_terms") or []
    lead = ", ".join(terms[:4]) if terms else "no shared terms"
    voice = (
        " All of it came from one source, so this is repetition rather than corroboration."
        if story.get("single_source")
        else ""
    )
    return (
        f"{n} article{'s' if n != 1 else ''} from {srcs} "
        f"source{'s' if srcs != 1 else ''} shared the terms: {lead}.{voice}"
    )


def narrate_story(
    story: dict,
    evidence: dict,
    *,
    client,
    model: str,
    backend: str,
    language: str | None = None,
    options: dict | None = None,
) -> dict:
    """Narrate ONE story, and validate every sentence before keeping it.

    Returns the paragraph plus per-sentence provenance. A model failure, an empty
    answer, or a paragraph whose every sentence fails validation all resolve the
    same way: the deterministic template, with the reason recorded. The document
    is never left with a gap where a model should have been.
    """
    ev_text = _evidence_text(evidence)
    base = {
        "article_ids": list(evidence.get("article_ids") or []),
        "model": model,
        "backend": backend,
        "prompt_version": NARRATION_PROMPT_VERSION,
        "language": language,
    }

    if not ev_text.strip():
        return {
            **base,
            "text": deterministic_paragraph(story),
            "narrated": False,
            "fallback_reason": "no article text was available to ground a sentence in",
            "sentences": [],
        }

    try:
        result = client.generate(
            _prompt(evidence),
            model=model,
            system=_SYSTEM,
            options=dict(options or DEFAULT_OPTIONS),
        )
        raw = (getattr(result, "text", "") or "").strip()
    except Exception as exc:  # noqa: BLE001 - a model failure degrades to the template
        _LOG.warning("bulletin: narration call failed", exc_info=True)
        return {
            **base,
            "text": deterministic_paragraph(story),
            "narrated": False,
            "fallback_reason": f"the model call failed: {type(exc).__name__}: {exc}",
            "sentences": [],
        }

    if not raw:
        return {
            **base,
            "text": deterministic_paragraph(story),
            "narrated": False,
            "fallback_reason": "the model returned nothing",
            "sentences": [],
        }

    from src.bulletin.grounding import check_sentence

    kept: list[str] = []
    sentences: list[dict] = []
    for sentence in [s.strip() for s in _SENTENCE_SPLIT.split(raw) if s.strip()]:
        verdict = check_sentence(sentence, ev_text, language=language)
        sentences.append(
            {
                "text": sentence,
                "kept": verdict["supported"],
                "checks_applied": verdict["checks_applied"],
                "unsupported": verdict["unsupported"],
                "reason": None
                if verdict["supported"]
                else "dropped: " + "; ".join(verdict["unsupported"]),
            }
        )
        if verdict["supported"]:
            kept.append(sentence)

    if not kept:
        return {
            **base,
            "text": deterministic_paragraph(story),
            "narrated": False,
            "fallback_reason": (
                "every generated sentence carried a figure or name that is not in the "
                "evidence"
            ),
            "sentences": sentences,
            "raw": raw,
        }

    dropped = [s for s in sentences if not s["kept"]]
    return {
        **base,
        "text": " ".join(kept),
        "narrated": True,
        "sentences": sentences,
        "sentences_kept": len(kept),
        "sentences_dropped": len(dropped),
        # A partially-validated paragraph is still a model's paragraph with pieces
        # removed. Saying so is the difference between "checked" and "clean".
        "partial": bool(dropped),
    }


def narrate(
    stories: list[dict],
    evidence_of,
    *,
    language: str | None = None,
    model: str | None = None,
    backend: str | None = None,
    options: dict | None = None,
    client=None,
    max_stories: int = 8,
) -> dict:
    """Narrate a period's stories. Layer B's entry point.

    ``evidence_of(story) -> dict`` supplies each story's grounding text, so this
    function never touches the database and can be driven in a test with no model
    and no corpus at all.

    Degrades WHOLE: if no backend is reachable, every story gets its deterministic
    paragraph and the report says why once, rather than repeating a failure per
    story. Stripping Layer B entirely leaves exactly this output.
    """
    if client is None:
        try:
            from src.api.llm import active_model
            from src.llm.backend import get_client_with_name

            backend_name, client = get_client_with_name(backend=backend)
            model = model or active_model()
        except Exception as exc:  # noqa: BLE001 - no backend is a degrade, not a failure
            _LOG.warning("bulletin: no LLM backend for narration", exc_info=True)
            return _all_deterministic(
                stories, f"no local model is available: {type(exc).__name__}: {exc}"
            )
    else:
        backend_name = backend or "injected"
        model = model or "injected"

    shown = stories[:max_stories]
    paragraphs: list[dict] = []
    for story in shown:
        try:
            ev = evidence_of(story)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("bulletin: evidence unavailable for a story", exc_info=True)
            paragraphs.append(
                {
                    "article_ids": list(story.get("article_ids") or []),
                    "text": deterministic_paragraph(story),
                    "narrated": False,
                    "fallback_reason": f"evidence unavailable: {exc}",
                    "sentences": [],
                }
            )
            continue
        paragraphs.append(
            narrate_story(
                story,
                ev,
                client=client,
                model=model,
                backend=backend_name,
                language=language,
                options=options,
            )
        )

    narrated = sum(1 for p in paragraphs if p.get("narrated"))
    return {
        "layer": "B",
        "paragraphs": paragraphs,
        "stories_narrated": narrated,
        "stories_shown": len(shown),
        "stories_available": len(stories),
        "model": model,
        "backend": backend_name,
        "prompt_version": NARRATION_PROMPT_VERSION,
        "options": dict(options or DEFAULT_OPTIONS),
        "method": (
            "one constrained call per story over the opening text of that story's "
            "articles; every sentence checked against that same text before it is kept, "
            "and a story whose sentences all fail falls back to a deterministic template"
        ),
        "caveat": (
            "AI-derived — unreliable. These sentences were written by a local model and "
            "kept only because every figure and name in them appears in the articles it "
            "was shown. That check catches invented facts; it does NOT catch real facts "
            "arranged into a false claim. Remove this layer and the document is still "
            "complete."
        ),
    }


def _all_deterministic(stories: list[dict], reason: str) -> dict:
    return {
        "layer": "B",
        "paragraphs": [
            {
                "article_ids": list(s.get("article_ids") or []),
                "text": deterministic_paragraph(s),
                "narrated": False,
                "fallback_reason": reason,
                "sentences": [],
            }
            for s in stories
        ],
        "stories_narrated": 0,
        "stories_shown": len(stories),
        "stories_available": len(stories),
        "available": False,
        "reason": reason,
        "method": "no model was reached; every story carries its deterministic paragraph",
        "caveat": (
            "No model output is present. The document is complete without it — that is "
            "what makes this layer removable rather than required."
        ),
    }
