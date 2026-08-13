"""Turn a FINISHED keyword-triage log into a reviewable, language-SCOPED proposal.

The sweep (``triage_job``) writes an append-only JSONL: a run header, then per batch a
counts record and a verdicts record carrying the echo-validated ``term -> {verdict, kind}``.
That log is the raw material. It is not yet a decision, and two things stood between the
two:

  * ``propose_stoplist_additions`` / ``propose_kind_overrides`` (``triage.py``) existed with
    NO production caller -- built so a caller could use them, and none ever did. This module
    is that caller.
  * The verdicts record carries the term but NOT its LANGUAGE, and language is what decides
    whether an addition is safe. The recorded stoplist architecture: a per-language SCOPED
    addition is collision-free by construction, a GLOBAL one is collision-prone (English
    "content" is French *content* = happy). So a proposal derived from the log alone could
    only ever feed the dangerous channel. Here the terms are joined back to the live
    ``Keyword`` rows, which is where the language lives -- so an overnight GPU run does not
    have to be repeated to become usable.

Read-only by construction: it opens the log, reads keyword rows, and returns a dict. It
writes nothing, and it applies nothing -- the standing rule is that the analyzer PROPOSES,
a human judges, and only a reviewed, committed data file ever changes what the app hides.

Three honesty rules the join forced, each reported rather than resolved by guessing:

  * A term that resolves to MORE THAN ONE language is AMBIGUOUS. ``Keyword.term`` carries no
    unique constraint (deliberately -- see the merge notes), so the same spelling can exist
    as separate rows in separate languages. Picking one would be inventing the very
    cross-language collision the scoping exists to prevent, so those terms are held back in
    their own bucket with the languages listed.
  * A term no longer in the corpus (pruned since the run) has no language to scope by and
    lands in the '?' bucket the proposal already warns about.
  * The CANARIES ride every batch by design, so their verdicts appear thousands of times and
    are not corpus judgements at all. They are excluded by name, and the count of what was
    excluded is published -- a silent drop would read as "the model never saw them".
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from src.ai_layer import triage as T
from src.ai_layer.triage_job import (
    CANARIES,
    KEYWORD_TRIAGE_RUN_SUMMARY_SCHEMA,
    KEYWORD_TRIAGE_VERDICTS_SCHEMA,
    _triage_dir,
)

PROPOSAL_SCHEMA = "oo-keyword-triage-proposal-1"

# The reader's OWN ceiling, independent of the writer's discipline: a sweep left running
# for days writes a log whose size tracks how much there was to judge, and by the time this
# runs the oversized file already exists. Distinct terms, not bytes -- the file is streamed
# line by line, so what grows is the accumulated verdict map and the items resolved from it.
#
# WHICH terms survive the cap is not arbitrary: the sweep pages in article-spread order, so
# a log is written most-widespread-first and the kept prefix is the part of the corpus a
# stoplist decision actually turns on. Hitting it is reported (`terms_truncated`) rather
# than left to be inferred from a short list.
_MAX_TERMS = int(os.getenv("OO_TRIAGE_PROPOSAL_MAX_TERMS", "250000"))

# SQLite's bound-variable ceiling is 999 on older builds; chunk well under it.
_IN_CHUNK = 900

_CANARY_TERMS: frozenset[str] = frozenset(c.term for c in CANARIES)


def newest_triage_log() -> pathlib.Path | None:
    """The newest finished-or-in-flight run log, or None when no run has ever been made."""
    try:
        files = sorted(_triage_dir().glob("oo-keyword-triage-*.jsonl"))
        return files[-1] if files else None
    except OSError:
        return None


def read_log_verdicts(path: pathlib.Path, *, max_terms: int = _MAX_TERMS) -> dict[str, Any]:
    """Stream a run log and collect its echo-validated verdicts.

    Returns ``{verdicts, disagreements, canaries_excluded, terms_truncated, batches, header,
    footer}``. A term repeated across batches keeps the FIRST verdict; a repeat that
    DISAGREES is counted and sampled rather than silently collapsed -- the sweep pages by a
    keyset cursor so a term should appear once, and a disagreement means either a resumed
    run re-judged it or the pagination overlapped. Either way it is a fact about the run,
    not something to average away.
    """
    verdicts: dict[str, dict] = {}
    log_languages: dict[str, str] = {}
    disagreements: list[dict] = []
    header: dict = {}
    footer: dict | None = None
    batches = 0
    canaries_excluded = 0
    truncated = False

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # A hard kill can leave a half-written final line. Skipping it is honest;
                # refusing the whole log over one truncated tail would throw away the run.
                continue
            schema = rec.get("schema")
            if schema == "oo-keyword-triage-run-1":
                header = rec
                continue
            if schema == KEYWORD_TRIAGE_RUN_SUMMARY_SCHEMA:
                footer = rec
                continue
            if schema != KEYWORD_TRIAGE_VERDICTS_SCHEMA:
                continue
            batches += 1
            # Runs since 2026-08-13 carry the language in the record itself; older ones do
            # not, and fall back to the corpus join. Both paths, one proposal.
            for term, lang in (rec.get("languages") or {}).items():
                if term not in _CANARY_TERMS and lang:
                    log_languages.setdefault(term, lang)
            for term, v in (rec.get("verdicts") or {}).items():
                if term in _CANARY_TERMS:
                    canaries_excluded += 1
                    continue
                prev = verdicts.get(term)
                if prev is None:
                    if len(verdicts) >= max_terms:
                        truncated = True
                        continue
                    verdicts[term] = {"verdict": v.get("verdict"), "kind": v.get("kind")}
                elif prev.get("verdict") != v.get("verdict") and len(disagreements) < 200:
                    disagreements.append(
                        {"term": term, "first": prev.get("verdict"), "later": v.get("verdict")}
                    )

    return {
        "verdicts": verdicts,
        "log_languages": log_languages,
        "disagreements": disagreements,
        "canaries_excluded": canaries_excluded,
        "terms_truncated": truncated,
        "batches": batches,
        "header": header,
        "footer": footer,
    }


def resolve_languages(
    session, terms: list[str], *, from_log: dict[str, str] | None = None
) -> dict[str, Any]:
    """Join judged terms back to the live ``Keyword`` rows for language + the counters.

    Returns ``{items, ambiguous, unknown}``. ``items`` maps term -> ``TriageItem`` (the shape
    ``propose_*`` already consumes, so the tested grouping helpers are reused rather than
    reimplemented). ``ambiguous`` maps a term that exists under SEVERAL languages to the
    sorted list of them -- held back, never assigned to one. ``unknown`` lists terms with no
    surviving keyword row.
    """
    from src.database.models import Keyword

    by_term: dict[str, list[tuple]] = {}
    for i in range(0, len(terms), _IN_CHUNK):
        chunk = terms[i : i + _IN_CHUNK]
        rows = (
            session.query(
                Keyword.term,
                Keyword.language,
                Keyword.mention_count,
                Keyword.article_count,
                Keyword.is_entity,
            )
            .filter(Keyword.term.in_(chunk))
            .all()
        )
        for r in rows:
            by_term.setdefault(r[0], []).append(r)

    log_langs = from_log or {}
    items: dict[str, T.TriageItem] = {}
    ambiguous: dict[str, list[str]] = {}
    unknown: list[str] = []
    for term in terms:
        rows = by_term.get(term) or []
        if not rows:
            # The corpus no longer holds it. A language the RUN recorded is still real
            # evidence about what was judged, so it is used; without one there is nothing
            # to scope by and the term is held back rather than guessed at.
            if term in log_langs:
                items[term] = T.TriageItem(term=term, language=log_langs[term])
            else:
                unknown.append(term)
            continue
        langs = sorted({(r[1] or "") for r in rows if r[1]})
        if len(langs) > 1:
            # Several live rows disagree. The run's OWN record says which one it judged,
            # and that is a fact rather than a choice — so it resolves the ambiguity when
            # present, and only an unrecorded one is held back.
            if term in log_langs:
                langs = [log_langs[term]]
            else:
                ambiguous[term] = langs
                continue
        r = rows[0]
        items[term] = T.TriageItem(
            term=term,
            language=(langs[0] if langs else log_langs.get(term)),
            mention_count=r[2],
            article_count=r[3],
            is_entity=r[4],
        )
    return {"items": items, "ambiguous": ambiguous, "unknown": sorted(unknown)}


def build_triage_proposal(session, *, path: pathlib.Path | None = None) -> dict:
    """The reviewable artifact: scoped stoplist additions + kind overrides, with the
    evidence a human needs to judge each one and an honest account of what was held back.

    Returns ``{available: False, note}`` when no run log exists -- never an empty proposal
    presented as "the model found nothing".
    """
    log = path or newest_triage_log()
    if log is None or not log.exists():
        return {
            "schema": PROPOSAL_SCHEMA,
            "available": False,
            "note": (
                "no keyword-triage run log was found -- run the sweep from Settings -> "
                "Diagnostics first (this reads a finished log, it never runs the model)."
            ),
        }

    read = read_log_verdicts(log)
    verdicts = read["verdicts"]
    resolved = resolve_languages(session, sorted(verdicts), from_log=read["log_languages"])
    items = resolved["items"]

    # Reuse the TESTED grouping helpers rather than regrouping here: one implementation of
    # "junk verdicts, grouped per language" is the point (a second copy would drift).
    pb = T.ParsedBatch(keywords_in=len(items))
    pb.verdicts = {t: v for t, v in verdicts.items() if t in items}
    stoplist = T.propose_stoplist_additions([pb], items)
    kinds = T.propose_kind_overrides([pb], items)

    counts = {"junk": 0, "content": 0, "unsure": 0}
    for v in verdicts.values():
        key = v.get("verdict")
        if key in counts:
            counts[key] += 1

    # Evidence per proposed term, so a reviewer judges a word WITH what it is attached to
    # rather than from a bare list. Counts only -- no score anywhere in this payload.
    evidence = {}
    for lang_terms in stoplist["by_language"].values():
        for term in lang_terms:
            it = items.get(term)
            if it is not None:
                evidence[term] = {
                    "articles": it.article_count,
                    "mentions": it.mention_count,
                    "tagged_entity": it.is_entity,
                }

    return {
        "schema": PROPOSAL_SCHEMA,
        "available": True,
        "log": {
            "path": str(log),
            "batches_with_verdicts": read["batches"],
            "model": (read["header"] or {}).get("model"),
            "model_digest": (read["header"] or {}).get("model_digest"),
            "prompt_version": (read["header"] or {}).get("prompt_version"),
            "run_state": (read["footer"] or {}).get("state", "in_progress_or_unfinished"),
            "canary_ok_overall": (read["footer"] or {}).get("canary_ok_overall"),
        },
        "language_basis": {
            "from_the_run_log": sum(1 for t in items if t in read["log_languages"]),
            "from_the_live_corpus": sum(1 for t in items if t not in read["log_languages"]),
            "note": (
                "A language recorded IN the run is what the model was actually judging; one "
                "read from the corpus now is today's state, which a re-index or a prune may "
                "have changed since. Runs before 2026-08-13 carry none, so every entry from "
                "such a log is corpus-derived."
            ),
        },
        "judged": {
            "distinct_terms": len(verdicts),
            **counts,
            "canary_verdicts_excluded": read["canaries_excluded"],
            "repeat_disagreements": len(read["disagreements"]),
            "disagreement_examples": read["disagreements"][:20],
            "terms_truncated": read["terms_truncated"],
        },
        "held_back": {
            "ambiguous_language": resolved["ambiguous"],
            "ambiguous_count": len(resolved["ambiguous"]),
            "no_longer_in_corpus": resolved["unknown"][:200],
            "no_longer_in_corpus_count": len(resolved["unknown"]),
            "why": (
                "A term that exists under SEVERAL languages cannot be scoped to one without "
                "inventing the cross-language collision the scoping prevents; a term no "
                "longer in the corpus has no language to scope by. Both are listed, neither "
                "is proposed."
            ),
        },
        "stoplist_additions": stoplist,
        "evidence": evidence,
        "kind_overrides": kinds,
        "caveat": (
            "PROPOSED ONLY -- nothing here is applied. A stoplist entry is applied at BOTH "
            "ends: it hides every existing mention at query time (reversible by removing the "
            "word) AND stops new ones being stored at index time (recoverable only by a full "
            "re-index). That asymmetry is why this is a reviewed, committed data file and "
            "never an automatic write."
        ),
    }
