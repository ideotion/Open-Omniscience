"""
Per-article who/where/when EXTRACTION -- the AI-layer candidate writer (B6.2/B6.3,
2026-07-24 field-feedback Session B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE STANDING RULING APPLIES UNCHANGED: LLM = PERCEPTION, never judgment; the trusted
rule-based extractors (``article_mentioned_dates``/``article_mentioned_places``/
``article_entities``) are NEVER touched by this module or its job wiring
(``perception_extract_job.py``) -- every write here lands in ``ai_keyword`` only, via
``src.ai_layer.store.record_keywords``, labelled "AI-derived - unreliable".

EVAL-GATED (the standing ruling's "harness first" requirement): a language whose
last live perception-eval run (``src.ai_layer.perception_job``) shows hallucination
above :data:`MAX_HALLUCINATION_RATE` on ANY of the who/where/when fields is DISABLED --
:func:`language_gate` reports it honestly, and the extraction batch runner below never
calls the model for an article in a disabled/never-evaluated language. Absence from the
report is NEVER assumed safe ("never evaluated" is its own, explicit reason).

DELIBERATE KIND-NAMING DEVIATION from the brief's illustrative kind list (``ai-date`` /
``ai-place`` / ``ai-person`` / ``ai-org`` / ``ai-event``): the extraction adapter's
constrained prompt (``src.ai_layer.perception``) combines persons and organizations into
ONE WHO field -- matching both the S6.5 harness's own ``_FIELDS = ("who", "where",
"when")`` scoring shape and the standing ruling's own framing ("WHO (persons AND orgs --
'the DOJ is a who')"). Splitting WHO into ``ai-person``/``ai-org`` here would fabricate a
distinction the extraction never actually determined -- so the stored kinds are
``ai-who`` / ``ai-place`` / ``ai-date``. ``ai-event`` is likewise NOT built: the standing
ruling explicitly excludes "what"/events from LLM-perception scope (restated in the same
brief section that lists the illustrative kinds), so that one "e.g." is not honoured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.ai_layer.jobs import ArticleWork

# A named, documented floor -- never a silent guess about safety. A language/field pair
# whose hallucination-rate on the S6.5 harness exceeds this is DISABLED for extraction.
MAX_HALLUCINATION_RATE = 0.5

_FIELDS = ("who", "where", "when")
_KIND_OF_FIELD = {"who": "ai-who", "where": "ai-place", "when": "ai-date"}
PERCEPTION_KINDS = tuple(_KIND_OF_FIELD.values())


def gate_languages_from_report(report: dict | None) -> dict[str, dict]:
    """Which languages the LAST live perception-eval report clears for extraction.

    Reads ``report["by_language"]`` (the S6.5 harness's per-stratum shape -- see
    :func:`src.analytics.perception_eval.evaluate_perception`). A language ABSENT from
    the report is never assumed safe -- it simply never appears in the returned gate;
    :func:`language_gate` reports that omission as "never evaluated". Returns
    ``{language: {"active": bool, "reason": str}}``.
    """
    by_lang = (report or {}).get("by_language") or {}
    out: dict[str, dict] = {}
    for lang, fields in by_lang.items():
        failing: list[str] = []
        for fld in _FIELDS:
            metrics = fields.get(fld) or {}
            rate = metrics.get("hallucination_rate")
            if rate is not None and rate > MAX_HALLUCINATION_RATE:
                failing.append(f"{fld} hallucination {rate}")
        if failing:
            out[lang] = {
                "active": False,
                "reason": (
                    f"hallucination-rate above {MAX_HALLUCINATION_RATE} on the S6.5 "
                    "harness: " + "; ".join(failing)
                ),
            }
        else:
            out[lang] = {"active": True, "reason": "cleared the S6.5 harness"}
    return out


def language_gate(language: str | None, gate: dict[str, dict]) -> tuple[bool, str]:
    """Whether ``language`` may run extraction, per a gate produced by
    :func:`gate_languages_from_report`. Absence is honestly DISABLED -- "never
    evaluated" -- never assumed safe by omission (the standing absence-is-not-a-pass
    lesson: an aggregation that silently omits an untested case reads as a pass)."""
    if not language:
        return False, "article has no known language"
    entry = gate.get(language)
    if entry is None:
        return False, "never evaluated"
    return bool(entry["active"]), str(entry["reason"])


def _combined_text(w: "ArticleWork") -> str:
    title = (w.title or "").strip()
    content = (w.content or "").strip()
    return f"{title}\n\n{content}".strip() if title else content


def select_perception_batch(session, after_id: int, limit: int) -> list["ArticleWork"]:
    """The next up-to-``limit`` articles after ``after_id`` (id ascending), excluding
    QUARANTINED rows (nav-soup/junk specimens -- running expensive extraction over known
    non-articles would be wasted, mirrors the standing quarantine exclusion convention).
    Does NOT pre-filter already-extracted articles at the SQL level (mirrors
    ``extract_for_articles``/``detect_for_articles``'s own convention) --
    ``skip_existing`` is applied in Python per batch by the caller."""
    from src.ai_layer.jobs import ArticleWork
    from src.database.models import Article

    rows = (
        session.query(
            Article.id, Article.title, Article.content,
            Article.language, Article.detected_language,
        )
        .filter(Article.id > after_id, Article.quarantined.isnot(True))
        .order_by(Article.id)
        .limit(limit)
        .all()
    )
    return [ArticleWork(r[0], r[1] or "", r[2] or "", r[3] or r[4]) for r in rows]


def extract_perception_batch(
    session,
    work: list["ArticleWork"],
    client,
    *,
    model: str,
    gate: dict[str, dict],
    keep_alive: str | None = None,
    max_workers: int = 1,
    skip_existing: bool = True,
) -> dict:
    """Extract who/where/when for each article in ``work`` and persist as AiKeyword
    candidates (kinds ``ai-who``/``ai-place``/``ai-date``). NEVER writes the trusted
    rule-based tables.

    Returns a tally: ``{"attempted", "skipped_existing", "gated", "gated_detail",
    "stored", "who", "where", "when", "aborted", "reason"}``. An LLMUnavailable found
    while walking a concurrent chunk's results IN ORDER stops the batch at that point
    (``aborted: True``) -- earlier articles in the SAME call are already committed and
    stay committed (never rolled back); the caller (the progressive job) turns
    ``aborted`` into an honest paused sweep, never a fabricated completion.

    ``max_workers`` bounds per-backend concurrency (B3's seam, ``src.llm.concurrency``)
    -- ``max_workers<=1`` (the Ollama default) is a byte-identical serial loop.
    """
    from src.ai_layer.perception import PERCEPTION_PROMPT_VERSION, llm_perception_extract
    from src.ai_layer.store import record_keywords
    from src.database.models import AiKeyword
    from src.llm.concurrency import chunked, run_concurrent
    from src.llm.ollama import LLMUnavailable

    tally: dict = {
        "attempted": 0, "skipped_existing": 0, "gated": 0, "gated_detail": {},
        "stored": 0, "who": 0, "where": 0, "when": 0, "aborted": False, "reason": None,
    }
    if not work:
        return tally

    already: set[int] = set()
    if skip_existing:
        from sqlalchemy import select as sa_select

        ids = [w.article_id for w in work]
        already = {
            r[0]
            for r in session.execute(
                sa_select(AiKeyword.article_id).where(
                    AiKeyword.article_id.in_(ids),
                    AiKeyword.kind.in_(PERCEPTION_KINDS),
                    AiKeyword.prompt_version == PERCEPTION_PROMPT_VERSION,
                )
            ).all()
        }

    to_run: list = []
    for w in work:
        if skip_existing and w.article_id in already:
            tally["skipped_existing"] += 1
            continue
        active, reason = language_gate(w.language, gate)
        if not active:
            tally["gated"] += 1
            tally["gated_detail"][reason] = tally["gated_detail"].get(reason, 0) + 1
            continue
        if not _combined_text(w):
            tally["gated"] += 1
            tally["gated_detail"]["empty content"] = tally["gated_detail"].get("empty content", 0) + 1
            continue
        to_run.append(w)

    for sub in chunked(to_run, max(1, max_workers)):
        results = run_concurrent(
            sub,
            lambda w: llm_perception_extract(
                client, _combined_text(w), model=model, language=w.language, keep_alive=keep_alive
            ),
            max_workers=max_workers,
        )
        aborted_here = False
        for w, res in zip(sub, results, strict=True):
            if not res.ok:
                if isinstance(res.error, LLMUnavailable):
                    tally["aborted"] = True
                    tally["reason"] = str(res.error)[:200]
                    aborted_here = True
                    break
                tally["attempted"] += 1  # an isolated per-article failure -- keep going
                continue
            tally["attempted"] += 1
            out = res.value or {}
            for fld in _FIELDS:
                kind = _KIND_OF_FIELD[fld]
                added = record_keywords(
                    session, w.article_id, out.get(fld) or [], model=model, kind=kind,
                    language=w.language, prompt_version=PERCEPTION_PROMPT_VERSION,
                )
                tally[fld] += added
            session.commit()  # persist progress; release the gate between articles
            tally["stored"] += 1
        if aborted_here:
            break
    return tally


__all__ = [
    "MAX_HALLUCINATION_RATE",
    "PERCEPTION_KINDS",
    "extract_perception_batch",
    "gate_languages_from_report",
    "language_gate",
    "select_perception_batch",
]
