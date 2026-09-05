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

EVAL-GATED (the standing ruling's "harness first" requirement) and TRI-STATE. The LAST
live perception-eval run (``src.ai_layer.perception_job``) yields one of exactly three
states, which are NEVER collapsed into each other:

  * ``active: True``  -- EVALUATED and cleared (the floors that applied were passed).
    The reason states ``n_cases``, because clearing on one synthetic case
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

PER-FIELD SINCE 2026-08-01 (E-S3, ruling 16). Those three states are computed for EACH
of who/where/when, on exactly that field's own evidence, and the language rolls them up:
active when ANY field cleared (the article is worth one call, since the prompt asks for
all three together), failed when every measured field failed, unmeasured when nothing was
measured. :func:`field_gate` then decides what may be STORED, so a model that invents
people but reads dates perfectly keeps its dates instead of extracting nothing anywhere.

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


def _norm(lang: str | None) -> str:
    """The house bare-ISO-639-1 form: ``en-US`` -> ``en``, ``ZH_hans`` -> ``zh``.

    THIS IS THE WHOLE OF FIELD DEFECT 1 (2026-09-05). ``Article.language`` is stored
    RAW from trafilatura's ``<html lang>`` read and ``models.py`` documents its value
    space as *e.g. "en", "fr", "en-US"*, while the harness report is keyed on BARE
    codes -- so :func:`language_gate`'s plain ``gate.get(language)`` missed on every
    region-tagged article and reported it as "never evaluated". A month-long field
    sweep (``oo-perception-extract-20260802``: 31,762 batches, 14,135 resumes, 33 days)
    gated 794,029 articles and attempted ZERO calls, 23 days of that AFTER the harness
    had cleared 13 languages -- 725,791 of them under exactly that reason string.

    It is the 2026-07-29 lesson recurring one module over: *normalise a language code
    before gating on it -- refusing to measure is not the safe direction*, fixed then
    in ``awareness/framing.py`` and never propagated here. ``analytics.managed.
    normalize_lang`` is the convention, at 24 call sites; this delegates to it rather
    than re-implementing the split, and falls back to the same rule only if that
    module cannot be imported (a core install must never lose the gate to an
    ImportError).

    NORMALISED ON BOTH SIDES, per that lesson's own second half: the gate's KEYS are
    normalised where it is built and the needle is normalised here, because
    normalising only the corpus would leave a report keyed ``en-US`` targeting a
    bucket that can no longer exist.
    """
    try:
        from src.analytics.managed import normalize_lang
    except Exception:  # noqa: BLE001 - the gate must survive a core install
        if not lang:
            return ""
        return str(lang).strip().lower().replace("_", "-").split("-")[0]
    return normalize_lang(lang)


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
    "checks": [str, ...], "fields": {field: {"active", "reason", "checks"}}}}``.
    ``checks`` lists every floor that was ACTUALLY applied, so a "cleared" verdict is
    auditable rather than asserted; an empty ``checks`` IS the ``active: None``
    (unmeasured) state.

    PER-FIELD SINCE 2026-08-01 (E-S3, ruling 16's granularity ask). The floors were
    always computed per field; only the VERDICT was collapsed, so one bad field
    deactivated the language for all three -- a model that hallucinates people but
    reads dates perfectly extracted nothing anywhere. Each field now carries its own
    tri-state, on exactly the evidence that field had, and the language-level ``active``
    becomes the honest rollup: True when ANY field cleared (that language is worth a
    call), False when every measured field failed, None when nothing was measured at
    all. The language-level ``reason`` names which fields are active and which are not,
    so "active" never over-reads as "active for everything".
    """
    harness_report = (report or {}).get("report") or {}
    by_lang = harness_report.get("by_language") or {}
    out: dict[str, dict] = {}
    for lang, fields in by_lang.items():
        if not isinstance(fields, dict):
            continue
        n_cases = fields.get("n_cases")
        n_cases = n_cases if isinstance(n_cases, int) else None
        power = f" on {n_cases} synthetic case(s)" if n_cases is not None else ""
        low_power = " -- low statistical power" if (n_cases or 0) <= 1 else ""
        per_field: dict[str, dict] = {}
        all_checks: list[str] = []
        all_failing: list[str] = []
        for fld in _FIELDS:
            metrics = fields.get(fld)
            checks: list[str] = []
            failing: list[str] = []
            if isinstance(metrics, dict):
                rate = metrics.get("hallucination_rate")
                recall = metrics.get("recall")
                # Floor 1 -- INVENTION. Applies only where the model actually predicted
                # something (rate is None <=> n_pred == 0 <=> it stayed silent here).
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
            all_checks.extend(checks)
            all_failing.extend(failing)
            if not checks:
                per_field[fld] = {
                    "active": None,
                    "reason": (
                        f"no harness evidence for {fld} in this language{power} -- "
                        "UNMEASURED, never evaluated against gold"
                    ),
                    "checks": [],
                }
            elif failing:
                per_field[fld] = {
                    "active": False,
                    "reason": f"{fld} failed the S6.5 harness{power}: " + "; ".join(failing),
                    "checks": checks,
                }
            else:
                per_field[fld] = {
                    "active": True,
                    "reason": (
                        f"{fld} cleared the S6.5 harness{power}{low_power}; checked: "
                        + "; ".join(checks)
                    ),
                    "checks": checks,
                }
        cleared = [f for f in _FIELDS if per_field[f]["active"] is True]
        failed = [f for f in _FIELDS if per_field[f]["active"] is False]
        unmeasured = [f for f in _FIELDS if per_field[f]["active"] is None]
        held_back = (
            (" -- gated for " + ", ".join(failed)) if failed else ""
        ) + ((" -- unmeasured for " + ", ".join(unmeasured)) if unmeasured else "")
        entry: dict = {}
        if not all_checks:
            # NO evidence in any field: no gold to recall and nothing predicted. This is
            # NOT a pass. Never the word "cleared".
            entry = {
                "active": None,
                "reason": (
                    "no harness evidence for this language"
                    f"{power} -- UNMEASURED, never evaluated against gold; "
                    "running extraction here would be unmeasured"
                ),
                "checks": [],
            }
        elif cleared:
            entry = {
                "active": True,
                "reason": (
                    "cleared the S6.5 harness for " + ", ".join(cleared)
                    + power + low_power + held_back + "; checked: " + "; ".join(all_checks)
                ),
                "checks": all_checks,
            }
        else:
            entry = {
                "active": False,
                "reason": "failed the S6.5 harness" + power + ": " + "; ".join(all_failing),
                "checks": all_checks,
            }
        entry["n_cases"] = n_cases
        entry["fields"] = per_field
        # KEYED ON THE BARE CODE (2026-09-05), so the lookup can normalise both sides.
        # A no-op for the harness's own output -- ``evaluate_perception`` emits bare
        # codes, so every existing consumer (``ai_check``'s cleared/refused lists, the
        # run header's language lists) is byte-unchanged. FIRST WINS on a collision:
        # the harness cannot produce two rows for one language, and blending two
        # verdicts would invent a third that neither row states.
        key = _norm(lang) or lang
        if key not in out:
            out[key] = entry
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
    case reads as a pass).

    Since the per-field gate (E-S3), this answers "is this article worth a call at all?"
    -- True when at least ONE field cleared. WHAT gets stored is then decided field by
    field by :func:`field_gate`; a language active for `where` alone must never be read
    as licensed for `who`.

    ``language`` is NORMALISED before the lookup (:func:`_norm`) -- ``en-US`` is an
    English article, not an unevaluated one. See :func:`_norm` for what that cost in
    the field."""
    norm = _norm(language)
    if not norm:
        return False, "article has no known language"
    entry = gate.get(norm)
    if entry is None:
        return False, "never evaluated"
    active = entry.get("active")
    reason = str(entry.get("reason") or "")
    if active is None:
        return False, reason or "no harness evidence -- unmeasured"
    return bool(active), reason


def field_gate(language: str | None, field: str, gate: dict[str, dict]) -> tuple[bool, str]:
    """Whether ``field`` may be STORED for ``language``.

    The three fields come back from ONE model call (the prompt asks for who, where and
    when together), so this is a storage gate, not a call gate: a gated field is
    generated and then DISCARDED rather than written as a candidate. That costs nothing
    extra -- the call was already being made for the field that cleared -- and it is the
    only honest place to draw the line, because the evidence for each field is separate.

    Same conservatism as :func:`language_gate`: only ``active is True`` stores. A field
    with no harness evidence is UNMEASURED and refuses; a language missing from the gate
    refuses for every field. A gate produced before per-field verdicts existed (an old
    persisted report) has no ``fields`` key -- it falls back to the language verdict,
    which is exactly the pre-E-S3 behaviour rather than an invented per-field one.

    Normalised on the same rule as :func:`language_gate` -- a storage gate that read
    ``en-US`` as unevaluated while the call gate read it as English would discard
    every field of a call it had just paid for.
    """
    norm = _norm(language)
    if not norm:
        return False, "article has no known language"
    entry = gate.get(norm)
    if entry is None:
        return False, "never evaluated"
    fields = entry.get("fields")
    if not isinstance(fields, dict) or field not in fields:
        return language_gate(language, gate)
    fld = fields[field] or {}
    active = fld.get("active")
    reason = str(fld.get("reason") or "")
    if active is None:
        return False, reason or f"no harness evidence for {field} -- unmeasured"
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
    "field_gated", "multi_part", "parts", "stored", "who", "where", "when", "aborted",
    "reason"}``. ``multi_part``/``parts`` are the COST of whole-article coverage (how
    many articles needed several calls, and how many calls in total) — they replaced a
    ``truncated`` counter on 2026-08-10, when the sweeps stopped truncating. Since the
    per-field gate (E-S3), an article whose language cleared for SOME fields is run and
    only its cleared fields are stored -- ``field_gated`` counts, per field, how many
    articles had that field discarded, so a small ``who`` count beside a large ``where``
    count reads as "gated", never as "the model found nothing". An LLMUnavailable found
    while walking a concurrent chunk's results IN ORDER stops the batch at that point
    (``aborted: True``) -- earlier articles in the SAME call are already committed and
    stay committed (never rolled back); the caller (the progressive job) turns
    ``aborted`` into an honest paused sweep, never a fabricated completion.

    ``max_workers`` bounds per-backend concurrency (B3's seam, ``src.llm.concurrency``)
    -- ``max_workers<=1`` (the Ollama default) is a byte-identical serial loop.
    """
    from src.ai_layer.coverage import sweep_text_budget
    from src.ai_layer.perception import PERCEPTION_PROMPT_VERSION, llm_perception_extract
    from src.ai_layer.store import record_keywords
    from src.database.models import AiKeyword
    from src.llm.concurrency import chunked, run_concurrent
    from src.llm.ollama import LLMUnavailable

    tally: dict = {
        "attempted": 0, "skipped_existing": 0, "gated": 0, "gated_detail": {},
        "field_gated": {f: 0 for f in _FIELDS},
        # Coverage, not truncation: since 2026-08-10 every article is read WHOLE, so
        # what a run reports is what it COST -- how many were long enough to need
        # several calls, and how many calls in total. A thin harvest is then
        # attributable to the model or the corpus, never to an unseen tail.
        "multi_part": 0, "parts": 0,
        "stored": 0, "who": 0, "where": 0, "when": 0, "aborted": False, "reason": None,
    }
    if not work:
        return tally

    # Warm the shared TTL cache once (the vLLM probe shells out to nvidia-smi and the
    # settings read hits the encrypted KV store). The per-article budget is still
    # resolved per article, because its third input is the article's own SCRIPT and a
    # Latin ratio applied to a CJK article oversizes every part by ~3x.
    sweep_text_budget(_combined_text(work[0]))

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
                client, _combined_text(w), model=model, language=w.language,
                keep_alive=keep_alive,
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
            cov = out.get("coverage") or {}
            # `cov.get("parts") or 1` would turn a REAL zero (nothing to read) into a
            # reported call that never happened -- the `.get(key, 0)` family of
            # fabricated measurement, pointed the other way. Default only when the key
            # is ABSENT, which is an older payload, not a measured zero.
            n_parts = cov["parts"] if isinstance(cov.get("parts"), int) else 1
            tally["parts"] += n_parts
            if n_parts > 1:
                tally["multi_part"] += 1
            for fld in _FIELDS:
                # PER-FIELD gate (E-S3): the three fields arrive from one call, so a
                # field this language never cleared is DISCARDED here rather than
                # stored. Counted, so a field's absence reads as gated and not as
                # "the model found nothing".
                field_ok, _why = field_gate(w.language, fld, gate)
                if not field_ok:
                    tally["field_gated"][fld] += 1
                    continue
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
    "field_gate",
    "gate_languages_from_report",
    "language_gate",
    "select_perception_batch",
]
