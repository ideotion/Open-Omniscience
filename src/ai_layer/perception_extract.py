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

EVAL-GATED (the standing ruling's "harness first" requirement) and TRI-STATE. For each
language the LAST live perception-eval run (``src.ai_layer.perception_job``) yields one
of exactly three states, which are NEVER collapsed into each other:

  * ``active: True``  -- EVALUATED and cleared (every field that carried evidence passed
    both floors). The reason states ``n_cases``, because clearing on one synthetic case
    is low statistical power and saying so is part of the measurement;
  * ``active: False`` -- EVALUATED and FAILED, on either floor:
      - hallucination above :data:`MAX_HALLUCINATION_RATE` on a field it predicted into, OR
      - recall at or below :data:`MIN_RECALL` on a field that CARRIED GOLD. This second
        floor closes the one-sided gate (2026-07-29): an extractor that returns NOTHING
        scores ``tp+fp == 0`` -> ``hallucination_rate is None`` -> the old loop never
        failed it, so a model that says nothing was licensed for EVERY language. A gate
        that only catches invention, never silence, is half a gate;
  * ``active: None``  -- NO harness evidence for this language (no gold AND no predictions
    on any field). It is UNMEASURED, and must never be describable as "cleared" -- the old
    loop returned "cleared the S6.5 harness" for a row with no metrics at all.

``None`` is EPISTEMIC, not permissive: :func:`language_gate` still returns ``False`` for
it, with a reason that says *unmeasured* rather than *cleared*. The tri-state exists so
the run header and the UI can say WHY, never to grant permission on an absence of
measurement.

The recall floor is applied ONLY to fields whose gold is non-empty (``recall is not
None``, i.e. ``n_gold > 0``). Nine of the thirteen gold languages carry ONLY ``where``
gold, so failing them on ``who``/``when`` would be a FABRICATED FAIL -- as dishonest as
the fabricated pass this fix removes. Absence from the report entirely is still "never
evaluated" (:func:`language_gate`), never assumed safe.

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

# The RECALL floor, applied only where the gold is non-empty. A tested field must score
# STRICTLY ABOVE this value. 0.0 therefore means "recovered at least ONE gold item" --
# deliberately the lowest non-vacuous bar, because the gold set's power cannot honestly
# support more: 12 of its 13 languages carry n_cases == 1, so recall there is 0.0 or 1.0
# and any intermediate threshold would be a number invented from a single case. Raise it
# when the gold set grows; do not raise it to look strict.
MIN_RECALL = 0.0

_FIELDS = ("who", "where", "when")
_KIND_OF_FIELD = {"who": "ai-who", "where": "ai-place", "when": "ai-date"}
PERCEPTION_KINDS = tuple(_KIND_OF_FIELD.values())


def _gold_n(metrics: dict) -> int:
    """Gold items for this language/field. Prefers the harness's own ``n_gold`` and falls
    back to ``tp + fn`` so a hand-written/legacy report still states an honest
    denominator."""
    n = metrics.get("n_gold")
    if isinstance(n, int):
        return n
    return int(metrics.get("tp") or 0) + int(metrics.get("fn") or 0)


def gate_languages_from_report(report: dict | None) -> dict[str, dict]:
    """Which languages the LAST live perception-eval report clears for extraction, TRI-STATE.

    ``report`` is the FULL persisted/live-eval ARTIFACT (``last_perception_eval_
    live_report()``'s return value): run metadata (``status``/``model``/``backend``/
    ``prompt_version``/``schema``/``run_at``/``available``) wrapping the S6.5 harness's
    OWN report dict under a ``"report"`` key -- see
    :func:`src.ai_layer.perception.run_perception_eval_against_model` (which builds
    exactly this envelope) and :func:`src.analytics.perception_eval.evaluate_perception`
    (whose OWN top level carries ``by_language``, one level INSIDE that ``"report"``
    key). This unwraps ``report["report"]["by_language"]`` -- fixed 2026-07-25
    (transversal audit 09) after the previous version read ``by_language`` at the
    wrong, outer level, so every language gated "never evaluated" forever regardless
    of how cleanly the harness actually scored, and every existing test mocked the
    same wrong (bug-matching) shape, which is why it shipped green
    (``test_gate_from_a_real_harness_run_populates_the_gate`` now exercises the REAL
    ``evaluate_perception``/``run_perception_eval_against_model`` envelope end-to-end,
    not a hand-typed mock, to guard against this exact class of drift recurring).

    A language ABSENT from the harness report is never assumed safe -- it simply
    never appears in the returned gate; :func:`language_gate` reports that omission
    as "never evaluated".

    Returns ``{language: {"active": True|False|None, "reason": str, "n_cases": int|None,
    "checks": [str, ...]}}``. ``checks`` lists every floor that was ACTUALLY applied, so
    a "cleared" verdict is auditable rather than asserted; an empty ``checks`` IS the
    ``active: None`` (unmeasured) state.
    """
    harness_report = (report or {}).get("report") or {}
    by_lang = harness_report.get("by_language") or {}
    out: dict[str, dict] = {}
    for lang, fields in by_lang.items():
        if not isinstance(fields, dict):
            continue
        n_cases = fields.get("n_cases")
        n_cases = n_cases if isinstance(n_cases, int) else None
        failing: list[str] = []
        checks: list[str] = []
        for fld in _FIELDS:
            metrics = fields.get(fld)
            if not isinstance(metrics, dict):
                continue
            rate = metrics.get("hallucination_rate")
            recall = metrics.get("recall")
            # Floor 1 -- INVENTION. Applies only where the model actually predicted
            # something (rate is None <=> n_pred == 0 <=> it stayed silent on this field).
            if rate is not None:
                checks.append(f"{fld} hallucination {rate}")
                if rate > MAX_HALLUCINATION_RATE:
                    failing.append(f"{fld} hallucination {rate} above {MAX_HALLUCINATION_RATE}")
            # Floor 2 -- SILENCE. Applies only where the gold is NON-EMPTY (recall is
            # None <=> n_gold == 0 <=> this field was never tested for this language).
            # Failing a `where`-only language on who/when would be a fabricated FAIL.
            if recall is not None:
                gold = _gold_n(metrics)
                checks.append(f"{fld} recall {recall} on {gold} gold item(s)")
                if recall <= MIN_RECALL:
                    failing.append(
                        f"{fld} recall {recall} on {gold} gold item(s) -- recovered nothing"
                    )
        power = f" on {n_cases} synthetic case(s)" if n_cases is not None else ""
        if not checks:
            # NO evidence in any field: no gold to recall and nothing predicted. This is
            # NOT a pass. Never the word "cleared".
            out[lang] = {
                "active": None,
                "reason": (
                    "no harness evidence for this language"
                    f"{power} -- UNMEASURED, never evaluated against gold; "
                    "running extraction here would be unmeasured"
                ),
                "n_cases": n_cases,
                "checks": [],
            }
        elif failing:
            out[lang] = {
                "active": False,
                "reason": "failed the S6.5 harness" + power + ": " + "; ".join(failing),
                "n_cases": n_cases,
                "checks": checks,
            }
        else:
            out[lang] = {
                "active": True,
                "reason": (
                    "cleared the S6.5 harness"
                    + power
                    + (" -- low statistical power" if (n_cases or 0) <= 1 else "")
                    + "; checked: "
                    + "; ".join(checks)
                ),
                "n_cases": n_cases,
                "checks": checks,
            }
    return out


def language_gate(language: str | None, gate: dict[str, dict]) -> tuple[bool, str]:
    """Whether ``language`` may run extraction, per a gate produced by
    :func:`gate_languages_from_report`.

    The gate's ``active`` is TRI-STATE but the RUN decision is binary and conservative:
    only ``active is True`` runs. ``active is None`` (no harness evidence) is DISABLED --
    the tri-state exists so the UI/run-log can say WHY ("unmeasured", not "failed"), never
    to grant permission on an absence of measurement. Absence from the gate entirely is
    likewise honestly DISABLED -- "never evaluated" -- never assumed safe by omission (the
    standing absence-is-not-a-pass lesson: an aggregation that silently omits an untested
    case reads as a pass)."""
    if not language:
        return False, "article has no known language"
    entry = gate.get(language)
    if entry is None:
        return False, "never evaluated"
    active = entry.get("active")
    reason = str(entry.get("reason") or "")
    if active is None:
        return False, reason or "no harness evidence -- unmeasured"
    return bool(active), reason


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
    "MIN_RECALL",
    "PERCEPTION_KINDS",
    "extract_perception_batch",
    "gate_languages_from_report",
    "language_gate",
    "select_perception_batch",
]
