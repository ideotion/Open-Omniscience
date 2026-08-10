"""
LLM-backed who/where/when PERCEPTION extraction (B6, 2026-07-24 field-feedback
Session B -- the NEW ask, eval-gated by the ALREADY-SHIPPED S6.5 harness).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE STANDING RULING APPLIES UNCHANGED: LLM = PERCEPTION, never judgment.
Scope = dates + places + persons AND organizations (no "what"/events). This
module builds the ONE constrained-output adapter that both (a) the eval
harness (``src.analytics.perception_eval``) scores against the ACTIVE model
BEFORE anything ships, and (b) the extraction job (``perception_job.py``)
reuses per-article once a stratum clears the harness's own bars -- so the
harness and the real extraction share EXACTLY the same prompt/parser, never a
divergent "prod path" the eval never actually measured.

HONESTY BY CONSTRUCTION (mirrors ``src/ai_layer/triage.py``'s doctrine):
  * CONSTRAINED, PARSEABLE output: the model must reply in EXACTLY three
    lines (``WHO:``/``WHERE:``/``WHEN:``), each a ``;``-separated list or the
    literal ``none``. A missing/malformed line for a field yields an EMPTY
    list for that field -- never guessed, never invented (garbage stores
    nothing, the B15/triage precedent).
  * NEVER writes the trusted rule-based tables (``article_mentioned_dates``/
    ``article_mentioned_places``/``article_entities``) -- this module and its
    job wiring are EXPORT-ONLY / AI-layer-only (``ai_keyword``), exactly like
    langdetect_llm.py and triage.py.
"""

from __future__ import annotations

import re

from src.ai_layer.sampling import sweep_options

# Bump when the prompt materially changes -- the provenance flag that travels
# with every AI-derived candidate (mirrors LANGDETECT_PROMPT_VERSION).
PERCEPTION_PROMPT_VERSION = "ai-perception-v1"

# WHOLE-ARTICLE COVERAGE since 2026-08-10 (maintainer ruling: truncating background
# sweeps "is not acceptable ... otherwise it won't work"). The article is split into
# parts that each fit the window and TOGETHER ARE the article, every part is extracted,
# and the three field lists are UNIONED across parts -- an entity named halfway down a
# 40,000-character article is a real mention, and the old head-cut never saw it.
#
# Applied in llm_perception_extract itself -- not at a call site -- so the eval harness
# and the real per-article extraction job share the EXACT same code path (no divergent
# "prod path" the eval never measured). A no-op for the gold set's short synthetic
# sentences, which are one part.

_SYSTEM_PROMPT = (
    "You extract facts MENTIONED in the text below -- never invent anything it "
    "does not state. Extract exactly three kinds:\n"
    "WHO -- persons AND organizations named in the text (no other kinds).\n"
    "WHERE -- places named in the text.\n"
    "WHEN -- dates mentioned, as YYYY-MM-DD if a full date is given, or a bare "
    "year if only a year is given.\n"
    "Reply in EXACTLY this format, one line per field, nothing else, using "
    "these ENGLISH labels even if the text is in another language (the "
    "extracted names/dates stay in the text's own language/form):\n"
    "WHO: <name>; <name>; ...\n"
    "WHERE: <place>; <place>; ...\n"
    "WHEN: <date>; <date>; ...\n"
    "If a field has nothing to extract, write exactly: WHO: none (or WHERE:/"
    "WHEN: none). Never omit a line. Never add commentary, numbering, or any "
    "other line."
)


def build_system() -> str:
    """The perception-extraction system prompt (constrained, three fixed lines)."""
    return _SYSTEM_PROMPT


_LINE_RE = re.compile(r"^\s*(WHO|WHERE|WHEN)\s*:\s*(.*)$", re.IGNORECASE)


def _split_list(raw: str) -> list[str]:
    """Split a ``;``-separated field value into cleaned items. ``none`` (any
    case) or an empty value yields an empty list -- never a fabricated item."""
    raw = (raw or "").strip()
    if not raw or raw.lower() in ("none", "n/a", "-"):
        return []
    items = []
    for part in raw.split(";"):
        part = part.strip().strip("\"'.,;")
        if part and part.lower() not in ("none", "n/a", "-"):
            items.append(part)
    return items


def parse_perception_reply(raw: str | None) -> dict:
    """Parse the model's constrained reply into ``{"who": [...], "where": [...],
    "when": [...]}``. A missing/unparseable field defaults to an EMPTY list --
    the model saying nothing usable about a field is NEVER treated as "it said
    everything is present" nor guessed at; miss over invent."""
    out: dict[str, list[str]] = {"who": [], "where": [], "when": []}
    for line in (raw or "").splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        field = m.group(1).lower()
        out[field] = _split_list(m.group(2))
    return out


def llm_perception_extract(
    client,
    text: str,
    *,
    model: str,
    language: str | None = None,
    keep_alive: str | None = None,
    budget_chars: int | None = None,
) -> dict:
    """Ask the active backend for who/where/when MENTIONED in ``text``. Raises
    the client's LLMUnavailable/LLMError up (the caller -- the eval harness or
    the extraction job -- decides how to handle a mid-run outage, mirroring
    ``triage.run_triage_batch``). Returns the parsed ``{"who","where","when"}``
    dict; a garbage/unparseable reply yields empty lists, never invented data.

    2026-08-10 (maintainer ruling): the WHOLE article is read. An article longer than
    the window is split into parts that together ARE the article, every part is sent,
    and the three field lists are unioned across parts. The result carries ``coverage``
    (parts, characters) so a multi-part run is legible -- but there is nothing to
    disclose about what was skipped, because nothing was.

    ``budget_chars`` is an explicit override for a caller that already knows the answer.
    The batch callers deliberately do NOT pass it: the two expensive inputs (the
    nvidia-smi probe, the settings read) are cached on a shared TTL, but the third is
    the article's own SCRIPT, and pinning one batch's ratio onto every article oversizes
    a CJK article's parts by ~3x."""
    from src.ai_layer.coverage import merge_items, split_for_sweep, sweep_text_budget

    basis: dict = {}
    if budget_chars and budget_chars > 0:
        budget = budget_chars
    else:
        budget, basis = sweep_text_budget(text)

    parts, coverage = split_for_sweep(text, budget)
    options = sweep_options(num_ctx=basis.get("num_ctx"))
    per_part: dict[str, list[list[str]]] = {"who": [], "where": [], "when": []}
    for part in parts:
        result = client.generate(
            part,
            model=model,
            system=_SYSTEM_PROMPT,
            options=options,
            keep_alive=keep_alive,
        )
        parsed = parse_perception_reply(getattr(result, "text", None))
        for field in ("who", "where", "when"):
            per_part[field].append(parsed.get(field) or [])

    out: dict = {field: merge_items(per_part[field]) for field in ("who", "where", "when")}
    out["coverage"] = coverage
    return out


def run_perception_eval_against_model(
    client, *, model: str, backend_name: str | None = None, keep_alive: str | None = None
) -> dict:
    """Run the ALREADY-SHIPPED S6.5 perception eval harness
    (``src.analytics.perception_eval.evaluate_perception``) against the ACTIVE
    model over REAL generate() calls -- the gate the standing ruling requires
    BEFORE any extraction feature ships. One call per gold case (bounded --
    the gold set is small by design), so this is a synchronous, not-a-job
    operation, mirroring ``run_ir_eval_selftest``'s own "bounded read-only
    eval" posture.

    Returns the harness's per-stratum report PLUS run metadata (model,
    resolved backend name, prompt version) so the persisted artifact states
    exactly what was measured. A single LLMUnavailable mid-run aborts loudly
    (``status: "unavailable"``) rather than silently scoring a partial gold
    set as if it were the whole thing."""
    from src.analytics.perception_eval import PERCEPTION_GOLD, evaluate_perception
    from src.llm.ollama import LLMError, LLMUnavailable

    def extract_fn(text: str, language: str | None) -> dict:
        return llm_perception_extract(client, text, model=model, language=language, keep_alive=keep_alive)

    try:
        report = evaluate_perception(extract_fn, PERCEPTION_GOLD)
    except (LLMUnavailable, LLMError) as exc:
        return {
            "status": "unavailable",
            "model": model,
            "backend": backend_name,
            "prompt_version": PERCEPTION_PROMPT_VERSION,
            "detail": str(exc)[:300],
        }
    return {
        "status": "ok",
        "model": model,
        "backend": backend_name,
        "prompt_version": PERCEPTION_PROMPT_VERSION,
        "report": report,
    }


__all__ = [
    "PERCEPTION_PROMPT_VERSION",
    "build_system",
    "llm_perception_extract",
    "parse_perception_reply",
    "run_perception_eval_against_model",
]
