"""Card-system AUDIT — the deep per-card fact bundle for validating and optimizing
the card/Lead system through repeated export → analyze → fix → re-export rounds.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY A THIRD DIAGNOSTIC (the two that exist stay UNCHANGED — never lose a tool)
-----------------------------------------------------------------------------
``src/briefing/card_diagnostics.py`` (``oo-cardclick-1``) answers ONE plumbing
question: does clicking a card open its exact corpus or a fuzzy search fallback?
``src/analytics/leads_quality.py`` (``oo-leads-quality-1``) answers ONE
composition question: what is in the feed right now (type/key/bucket/n/sources)?
Both are cheap, both ride the all-diagnostics bundle, and both keep their own
buttons and schemas. Neither is touched by this module.

This is the DEEP tier: everything needed to judge whether a card is *right*, not
merely whether it is present and clickable. It exists to be run repeatedly against
a real corpus, read by a human analyst, acted on, and re-run — so each round can
see whether a producer change actually moved what it claimed to move.

THE GAP THAT MOTIVATED IT (the most important part)
---------------------------------------------------
``registry.run_all`` catches a producer exception, logs a warning, and contributes
``[]``. A producer with legitimately NO SIGNAL also contributes ``[]``. In both
existing diagnostics those two states are **indistinguishable**: a producer
crashing on every single run for a month looks exactly like a quiet one, because
neither diagnostic has any row for a producer that emitted nothing. That is this
project's own recorded lesson — "AN AGGREGATION THAT OMITS ZERO-EVIDENCE ENTRIES
MAKES 'ABSENT' READ AS 'PASSED'" — sitting live in the card path. The
``producer_inventory`` block below closes it: EVERY registered producer gets a row,
with an outcome of ``ok`` / ``no-signal`` / ``error`` (and the exception type +
message when it errored), so silence is never mistaken for health.

THE SIX VALIDATION DIMENSIONS
-----------------------------
1. ARITHMETIC — does ``trigger.math`` actually reproduce what the card claims?
   Each math row's ``value`` is parsed and re-evaluated with a whitelisted AST
   evaluator (never ``eval``). A row that is not mechanically checkable (a bare
   number, a flag, a range) is reported ``checkable: false`` WITH THE REASON —
   never silently counted as a pass. A pass is only ever reported for a row that
   was actually recomputed and matched.
2. CORPUS FIDELITY — do ``article_ids`` resolve to real, non-quarantined
   articles, and does the resolved count match the card's claimed ``n``?
3. INDEPENDENCE — distinct sources, near-identical copies, shared origins;
   computed with the EXISTING primitives (``queries.corpus_coordination``,
   ``convergence._shared_origin``), never a new similarity algorithm.
4. NON-FABRICATION — ``method``/``caveat`` non-empty, ``n`` present or explicitly
   absent, and a recursive walk for score-shaped KEYS.
5. NEGATIVE SPACE — the producer inventory described above.
6. DETERMINISM — two producer passes diffed. ON BY DEFAULT, including in the
   all-diagnostics bundle member. It genuinely doubles the producer cost, so it
   carries a BUDGET rather than a default-off: the FIRST pass is timed, and the
   second pass is skipped only when that MEASURED time already exceeds the
   budget — recorded as an explicit ``{"ran": false, "skipped": "budget"}``
   marker naming the measured cost and the budget it exceeded. An honest,
   visible skip the operator can see and act on; never a silent disable. (The
   whole point of this diagnostic is that absence is visible — a section that
   quietly did not run would be the same defect it exists to expose.)

HONESTY RULES THIS MODULE HOLDS ITSELF TO
-----------------------------------------
* READ-ONLY. It never writes to the corpus.
* COUNTS ARE ALWAYS EXACT AND UNCAPPED. Every bounded list states the truth
  beside it as ``{"shown": k, "total": N}`` — a cap may bound the EXAMPLES, never
  a reported NUMBER (the standing anti-capping rule).
* ABSENCE IS DISTINGUISHABLE FROM ZERO everywhere (``None`` vs ``0``; a
  ``checkable: false`` reason vs a verified pass; ``no-signal`` vs ``error``).
* NO COMPOSITE SCORE. Per-status tallies are emitted as
  ``[{"status": s, "n": k}]`` OBJECTS, never as dict KEYS — because a status
  VALUE may legitimately contain a banned fragment (this repo's own
  ``"degraded"`` ⊃ ``"grade"`` lesson) while a KEY may not.
* THE ARTICLE ``sentiment_score`` COLUMN IS DELIBERATELY NOT RE-USED AS A KEY.
  The stored VADER compound is emitted as ``sentiment.compound`` (value
  unchanged, column named in the method) so the no-score key walk over this
  payload stays meaningful instead of being defeated by a legacy column name.
* IT DEGRADES, NEVER 500s. Every risky sub-query is wrapped and returns a
  structured ``{"section_ok": false, "error": ...}`` marker for that section
  only. ``StatementTimeout`` is RE-RAISED so an outer deadline still bites.
  (``section_ok`` — never a bare ``available``/``ok`` — so a degrade sentinel can
  never be confused with a real measurement, the ``ai_diagnostics._safe`` lesson.)
"""

from __future__ import annotations

import ast
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_LOG = logging.getLogger(__name__)

SCHEMA = "oo-card-audit-1"

#: Report depths. ``summary`` carries NO article content and is the only depth the
#: all-diagnostics bundle ever uses; ``standard`` adds a bounded excerpt per
#: article; ``full`` adds complete content and is operator-chosen only.
DEPTHS: tuple[str, ...] = ("summary", "standard", "full")

#: id IN (...) chunk — stays under SQLite's ~999 bound-variable floor, the repo-wide
#: convention (cf. queries._IN_CHUNK = 900, llm._BULK_ID_CHUNK = 900).
_IN_CHUNK = 900

#: Default per-card article-list bound. The COUNT beside it is always exact.
DEFAULT_MAX_ARTICLES_PER_CARD = 40
#: Default per-article content excerpt at ``standard`` depth.
DEFAULT_EXCERPT_CHARS = 2000
#: Default per-article bound on the secondary linked layers (each states its exact total).
DEFAULT_MAX_LINKED_ROWS = 25
#: Independence (near-duplicate) analysis reads article CONTENT through the codec, so it
#: is bounded per card; the distinct-source and shared-origin counts stay exact.
DEFAULT_MAX_COORDINATION_ARTICLES = 60
#: Determinism (dimension 6) is ON by default. It doubles the PRODUCER cost, so instead of
#: being defaulted off it carries a budget: the first pass is TIMED and the second is run
#: only when that measured time fits. ``None`` = no budget (always run the second pass).
#: The bundle member sets a real budget derived from its own per-member deadline.
DEFAULT_DETERMINISM_BUDGET_S: float | None = None

# Key fragments that would imply a composite quality/trust score. Mirrors
# src/briefing/card.py's ban PLUS the stricter per-module walkers used across the
# repo (which also reject "ranking"/"rating"/"grade" as substrings).
_BANNED_KEY_FRAGMENTS: tuple[str, ...] = (
    "score",
    "ranking",
    "rating",
    "grade",
    "credibility",
    "veracity",
    "verdict",
)


# --------------------------------------------------------------------------- #
#  Dimension 1 — ARITHMETIC (pure; no DB, no network)
# --------------------------------------------------------------------------- #

# Characters an arithmetic expression may contain. Anything else (a letter, a
# thousands separator, the "·" used elsewhere as a SEPARATOR rather than a
# multiplication sign, a range dash) makes the row not-checkable rather than
# risking a fabricated verdict on a misparse.
_ARITH_ALLOWED = set("0123456789.+-*/() ")

_ARITH_SUBSTITUTIONS = (("÷", "/"), ("×", "*"), ("−", "-"), ("–", "-"))

# The AST node types a math expression may legally use. Anything else is refused.
_ARITH_NODES: tuple[type, ...] = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.USub,
    ast.UAdd,
    ast.Constant,
)


def _eval_arith_node(node: ast.AST) -> float:
    """Recursively evaluate ONE whitelisted arithmetic AST node.

    A direct interpreter over the four operators and numeric literals. There is
    deliberately no ``eval``/``exec``/``compile`` anywhere in this path: this
    repo bans those sinks outright (``tests/test_repo_invariants.py::
    test_no_dangerous_eval_or_deserialization_sinks``), and a node whitelist in
    FRONT of an ``eval`` is still an ``eval`` — one whitelist bug away from
    executing a math row that arrived from a producer. Interpreting the nodes
    ourselves means a hostile expression has nothing to reach for.

    Raises on anything the caller's whitelist should already have refused, so
    the caller turns it into an honest ``None`` (reported not-checkable).
    """
    if isinstance(node, ast.Expression):
        return _eval_arith_node(node.body)
    if isinstance(node, ast.Constant):
        # bool is an int subclass — refuse it rather than silently scoring True as 1.
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("non-numeric constant")
        return float(node.value)  # OverflowError on an absurd int literal → not-checkable
    if isinstance(node, ast.UnaryOp):
        operand = _eval_arith_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError("unsupported unary operator")
    if isinstance(node, ast.BinOp):
        left = _eval_arith_node(node.left)
        right = _eval_arith_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right  # ZeroDivisionError → caught by the caller
        raise ValueError("unsupported binary operator")
    raise ValueError("unsupported node")


def _safe_arith(expr: str) -> float | None:
    """Evaluate a pure-arithmetic expression, or return ``None``.

    ``ast.parse`` with a strict node whitelist, then a direct interpretation of
    the parsed nodes (:func:`_eval_arith_node`) — never ``eval``/``exec``, so a
    malformed or hostile math row can only ever yield ``None`` (reported as
    not-checkable), never execute anything.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None
    for node in ast.walk(tree):
        if not isinstance(node, _ARITH_NODES):
            return None
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            return None
    try:
        value = _eval_arith_node(tree)
    except (ZeroDivisionError, OverflowError, TypeError, ValueError, RecursionError):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        # An absurdly large integer literal parses and evaluates fine as a Python int
        # but overflows on the float conversion -- caught here so such a row is simply
        # reported not-checkable rather than raising out of the checker.
        out = float(value)
    except (OverflowError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return out


def _display_tolerance(rendered: str) -> float:
    """Half a unit in the LAST DISPLAYED decimal place of ``rendered``.

    A card's math row shows a ROUNDED value, so an exact equality test would
    fabricate failures. Comparing within half an ulp of the displayed precision is
    the honest test of "this displayed number is what the arithmetic produces".
    """
    frac = rendered.split(".", 1)[1] if "." in rendered else ""
    digits = len("".join(ch for ch in frac if ch.isdigit()))
    return 0.5 * (10.0 ** -digits) * 1.000001


def check_math_row(row: Any) -> dict:
    """Verify ONE ``trigger.math`` row. Pure.

    Returns ``{label, value, checkable, reason, ...}``. ``checkable`` is False —
    with a stated ``reason`` — for every row this cannot mechanically recompute
    (a bare number, a ✓/— flag, a range, a threshold). A row is only ever reported
    ``reproduced: true`` when its left-hand side was actually re-evaluated and
    matched its right-hand side. NEVER a pass that was not verified.
    """
    if not isinstance(row, dict):
        return {
            "label": None,
            "value": None,
            "checkable": False,
            "reason": f"math row is not an object (got {type(row).__name__})",
        }
    label = row.get("label")
    raw = row.get("value")
    out: dict = {"label": label, "value": raw, "checkable": False, "reason": None}
    if not isinstance(raw, str) or "=" not in raw:
        out["reason"] = (
            "no '=' in the value — this row states a quantity or a flag rather than "
            "an equation, so there is nothing to recompute"
        )
        return out

    lhs_raw, rhs_raw = raw.rsplit("=", 1)
    lhs = lhs_raw
    for src, dst in _ARITH_SUBSTITUTIONS:
        lhs = lhs.replace(src, dst)
    if not lhs.strip():
        out["reason"] = "empty left-hand side"
        return out
    bad = sorted({ch for ch in lhs if ch not in _ARITH_ALLOWED})
    if bad:
        out["reason"] = (
            f"left-hand side carries non-arithmetic character(s) {bad} — not "
            "recomputable without guessing what they mean"
        )
        return out

    rhs = rhs_raw.strip()
    percent = rhs.endswith("%")
    if percent:
        rhs = rhs[:-1].strip()
    for src, dst in _ARITH_SUBSTITUTIONS:
        rhs = rhs.replace(src, dst)
    rhs = rhs.lstrip("*+").strip()  # a leading "×"/"+" is display sugar ("×4.2", "+12")
    rhs_bad = sorted({ch for ch in rhs if ch not in _ARITH_ALLOWED})
    if rhs_bad:
        out["reason"] = (
            f"right-hand side carries non-arithmetic character(s) {rhs_bad} — the "
            "claimed result is not a plain number"
        )
        return out

    claimed = _safe_arith(rhs)
    computed = _safe_arith(lhs)
    if claimed is None:
        out["reason"] = "right-hand side did not parse as arithmetic"
        return out
    if computed is None:
        out["reason"] = "left-hand side did not parse as arithmetic (or divides by zero)"
        return out

    shown = computed * 100.0 if percent else computed
    tol = _display_tolerance(rhs)
    delta = abs(shown - claimed)
    out.update(
        {
            "checkable": True,
            "reason": None,
            "recomputed": round(shown, 6),
            "claimed": round(claimed, 6),
            "delta": round(delta, 6),
            "tolerance": round(tol, 9),
            "percent_form": percent,
            "reproduced": bool(delta <= tol),
        }
    )
    return out


def check_trigger(trigger: Any) -> dict:
    """Dimension 1 over a card's whole ``trigger`` block. Pure.

    ``checkable_n`` / ``reproduced_n`` / ``failed_n`` are exact counts over the
    rows; ``not_checkable_n`` is stated separately so an unverifiable row can
    never be quietly folded into a pass.
    """
    if trigger is None:
        return {
            "present": False,
            "rows_total": 0,
            "checkable_n": 0,
            "not_checkable_n": 0,
            "reproduced_n": 0,
            "failed_n": 0,
            "rows": [],
            "note": "this card carries no trigger block — nothing to verify",
        }
    if not isinstance(trigger, dict):
        return {
            "present": False,
            "rows_total": 0,
            "checkable_n": 0,
            "not_checkable_n": 0,
            "reproduced_n": 0,
            "failed_n": 0,
            "rows": [],
            "note": f"trigger is not an object (got {type(trigger).__name__})",
        }
    math_rows = trigger.get("math")
    if not isinstance(math_rows, list):
        math_rows = []
    checks = [check_math_row(r) for r in math_rows]
    checkable = [c for c in checks if c.get("checkable")]
    reproduced = [c for c in checkable if c.get("reproduced")]
    return {
        "present": True,
        "plain": trigger.get("plain"),
        "rows_total": len(math_rows),
        "checkable_n": len(checkable),
        "not_checkable_n": len(checks) - len(checkable),
        "reproduced_n": len(reproduced),
        "failed_n": len(checkable) - len(reproduced),
        "rows": checks,
        "note": (
            "Only rows stating an equation are recomputable; every other row is "
            "reported checkable:false with its reason, never counted as a pass."
        ),
    }


# --------------------------------------------------------------------------- #
#  Dimension 4 — NON-FABRICATION (pure)
# --------------------------------------------------------------------------- #


def walk_banned_keys(obj: Any, *, path: str = "") -> list[dict]:
    """Every dict KEY anywhere in ``obj`` matching a banned score fragment.

    Deliberately reports rather than raises: a match is a FLAG FOR REVIEW, not
    automatically a violation. A legitimate single measured statistic can contain
    a banned fragment exactly as this repo's own ``"degraded"`` contains
    ``"grade"`` — so the analyst judges, and the diagnostic never fabricates a
    verdict about its own subject. Keys are what is walked; a banned fragment
    appearing as a VALUE (the ``{"metric": "share_zscore"}`` convention the
    producers already follow) is correct and is not reported.
    """
    found: list[dict] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            low = str(k).lower()
            for frag in _BANNED_KEY_FRAGMENTS:
                if frag in low:
                    found.append({"path": here, "key": str(k), "fragment": frag})
                    break
            found.extend(walk_banned_keys(v, path=here))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(walk_banned_keys(v, path=f"{path}[{i}]"))
    return found


def non_fabrication_checks(card: dict) -> dict:
    """Dimension 4 for one card dict. Pure.

    ``n`` is checked as present-or-EXPLICITLY-absent: a card whose signal is a
    whole-corpus distribution legitimately has no sample size, and that is a
    different fact from a card that forgot to set one — so both are reported,
    never merged.
    """
    method = card.get("method")
    caveat = card.get("caveat")
    n = card.get("n")
    method_ok = isinstance(method, str) and bool(method.strip())
    caveat_ok = isinstance(caveat, str) and bool(caveat.strip())
    banned = walk_banned_keys(card)
    return {
        "method_present": method_ok,
        "method_chars": len(method) if isinstance(method, str) else 0,
        "caveat_present": caveat_ok,
        "caveat_chars": len(caveat) if isinstance(caveat, str) else 0,
        "n_state": "present" if isinstance(n, int) else ("absent" if n is None else "malformed"),
        "n": n if isinstance(n, int) else None,
        "banned_key_matches": banned,
        "banned_key_match_n": len(banned),
        "passes": bool(method_ok and caveat_ok and not banned),
        "method_note": (
            "method/caveat must be non-empty (informed consent: a number never travels "
            "without how it was computed and what it does not mean). n may be legitimately "
            "absent for a whole-corpus distribution — 'absent' and 'malformed' are reported "
            "separately, never merged."
        ),
        "banned_key_note": (
            "A banned-fragment match is a FLAG FOR REVIEW, not an automatic violation: a "
            "single measured statistic can contain one exactly as 'degraded' contains "
            "'grade'. KEYS are walked; the fragment appearing as a VALUE is the correct "
            "convention and is not reported."
        ),
    }


# --------------------------------------------------------------------------- #
#  Dimension 5 — NEGATIVE SPACE (the producer inventory)
# --------------------------------------------------------------------------- #


@dataclass
class ProducerOutcome:
    """What one registered producer actually did on this pass.

    ``outcome`` separates the three states ``run_all`` collapses into one empty
    list: ``ok`` (emitted at least one card), ``no-signal`` (ran cleanly, emitted
    nothing — a legitimate quiet producer) and ``error`` (raised; the exception
    is captured rather than only logged).
    """

    name: str
    outcome: str
    cards_proposed: int = 0
    elapsed_s: float = 0.0
    error_type: str | None = None
    error_message: str | None = None
    non_card_items: int = 0
    cards: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "producer": self.name,
            "outcome": self.outcome,
            "cards_proposed": self.cards_proposed,
            "elapsed_s": round(self.elapsed_s, 4),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "non_card_items": self.non_card_items,
        }


def observe_producers(session) -> list[ProducerOutcome]:
    """Run EVERY registered producer, recording each one's own outcome.

    Mirrors ``registry.run_all``'s isolation contract exactly — one producer's
    exception can never abort the pass, non-``Card`` items are dropped, and the
    same WAL guard (entered at the same PER-PRODUCER scope, which is what makes
    the timings describe production) / between-producer commit are used — but
    instead of collapsing
    every empty result into an indistinguishable ``[]`` it records WHICH of the
    three states each producer reached. ``run_all`` itself is NOT modified,
    imported, or wrapped in a way that changes its behaviour; this is a parallel
    observer over the same registry (``tests/test_card_audit.py`` pins that the
    surfaced set matches ``run_all``'s exactly).
    """
    from src.briefing.card import Card
    from src.briefing.registry import _REGISTRY, _release_transaction, _wal_guard

    from src.briefing.registry import _drain_pending

    out: list[ProducerOutcome] = []
    for name, producer in list(_REGISTRY):
        started = time.monotonic()
        try:
            # PR-D / W1 fix-forward: entered PER PRODUCER, exactly as
            # ``run_all_bounded`` now does, and for the same reason -- entering
            # `_wal_guard` is what runs `_drain_pending`, closing whatever scan the
            # PREVIOUS producer left mid-flight. THE SCOPE IS PART OF THE MIRRORING,
            # not an implementation detail: this observer exists to describe what
            # `run_all` does, so a guard entered once for the whole loop here would
            # make every timing it reports a measurement of a DIFFERENT pinning
            # regime than the one production runs under -- an auditor quietly
            # describing code that is not the code.
            with _wal_guard(session):
                produced = producer(session) or []
        except Exception as exc:  # noqa: BLE001 - the point: capture, never abort
            out.append(
                ProducerOutcome(
                    name=name,
                    outcome="error",
                    elapsed_s=time.monotonic() - started,
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:500],
                )
            )
            _release_transaction(session)
            continue
        cards = [c for c in produced if isinstance(c, Card)]
        out.append(
            ProducerOutcome(
                name=name,
                outcome="ok" if cards else "no-signal",
                cards_proposed=len(cards),
                elapsed_s=time.monotonic() - started,
                non_card_items=len(produced) - len(cards),
                cards=cards,
            )
        )
        _release_transaction(session)
    # Close what the LAST producer left open -- there is no further `_wal_guard`
    # call in this invocation to do it. Same reasoning as `run_all_bounded`'s own
    # trailing drain; reached by the `continue` path too, since it sits after the
    # loop rather than inside it.
    _drain_pending(session)
    return out


def apply_dedup_belt(outcomes: list[ProducerOutcome]) -> tuple[list[tuple[str, Any]], list[dict]]:
    """Replay ``run_all``'s cross-card ``(type, key)`` dedup belt over the observed
    cards, keeping BOTH sides.

    Returns ``(surfaced, suppressed)`` where ``surfaced`` is ``[(producer, card)]``
    in registration order — byte-identical to what ``run_all`` returns — and
    ``suppressed`` names every card the belt dropped together with what it
    collided with. Those suppressed cards were genuinely PROPOSED by a producer
    and are invisible in every other view of the feed.
    """
    seen: dict[tuple[str, str], dict] = {}
    surfaced: list[tuple[str, Any]] = []
    suppressed: list[dict] = []
    for oc in outcomes:
        for card in oc.cards:
            ident = (card.type, card.key)
            if ident in seen:
                first = seen[ident]
                suppressed.append(
                    {
                        "producer": oc.name,
                        "type": card.type,
                        "key": card.key,
                        "id": card.id,
                        "title": card.title,
                        "bucket": card.bucket,
                        "n": card.n,
                        "collided_with": {
                            "producer": first["producer"],
                            "id": first["id"],
                            "title": first["title"],
                        },
                    }
                )
                continue
            seen[ident] = {"producer": oc.name, "id": card.id, "title": card.title}
            surfaced.append((oc.name, card))
    return surfaced, suppressed


def _tally(values: list[str], label: str = "status") -> list[dict]:
    """Per-status tallies as OBJECTS, never dict keys — a status VALUE may
    legitimately contain a banned fragment (``"degraded"`` ⊃ ``"grade"``) while a
    KEY may not. Sorted for a stable diff between two exports."""
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return [{label: k, "n": counts[k]} for k in sorted(counts)]


# --------------------------------------------------------------------------- #
#  Degrade wrapper
# --------------------------------------------------------------------------- #


def _safe_section(name: str, fn):
    """Run one risky sub-query; on failure return a structured marker for THAT
    section only (the diagnostic must degrade, never 500).

    ``section_ok`` — never a bare ``available``/``ok`` — so this degrade sentinel
    can never be confused with a real measurement that happens to be false
    (the ``ai_diagnostics._safe`` lesson, 2026-07-29). ``StatementTimeout`` is
    RE-RAISED so an outer statement deadline still bites.
    """
    from src.database.maintenance import StatementTimeout

    try:
        return fn()
    except StatementTimeout:
        raise
    except Exception as exc:  # noqa: BLE001 - a failing section must not abort the report
        _LOG.warning("card_audit: section %r failed", name, exc_info=True)
        return {
            "section_ok": False,
            "error": f"{type(exc).__name__}: {exc}"[:400],
            "note": f"the {name!r} section could not be computed; every other section is unaffected",
        }


# --------------------------------------------------------------------------- #
#  DB resolution — codec-safe (never load whole Article rows for small columns)
# --------------------------------------------------------------------------- #


def _chunked(ids: list[int], size: int = _IN_CHUNK):
    for i in range(0, len(ids), size):
        yield ids[i : i + size]


def _resolve_articles(session, ids: list[int], *, depth: str, excerpt_chars: int,
                      max_linked_rows: int, shown_ids: list[int]) -> dict:
    """Resolve the PRIMARY article metadata for ``ids`` (exact) and the full
    payload for ``shown_ids`` (bounded).

    SQLCIPHER CODEC TRAP (this repo's own measured lesson): ``Article.content``
    sits BEFORE ``language`` in column order, so loading whole ORM ``Article``
    rows to read small columns drags ~35 KB per row through the codec. Every
    query here selects the small columns EXPLICITLY; ``content`` is read in a
    SEPARATE, bounded second pass and only when the depth actually requires it.
    """
    from src.catalog.provenance import provenance_of
    from src.database.models import Article, Source

    resolved: dict[int, dict] = {}
    quarantined_n = 0
    prov_values: list[str] = []
    shown = set(shown_ids)

    for chunk in _chunked(ids):
        rows = (
            session.query(
                Article.id,
                Article.title,
                Article.url,
                Article.published_at,
                Article.created_at,
                Article.language,
                Article.detected_language,
                Article.word_count,
                Article.hash,
                Article.quarantined,
                Article.quarantine_reason,
                Article.quarantine_criteria_version,
                Article.sentiment_score,
                Article.sentiment_label,
                Article.server_ip,
                Article.ip_observed_at,
                Article.server_ip_reason,
                Article.source_id,
                Source.name,
                Source.domain,
                Source.country,
                Source.source_type,
            )
            .outerjoin(Source, Source.id == Article.source_id)
            .filter(Article.id.in_(chunk))
            .all()
        )
        for r in rows:
            prov = provenance_of(r.domain, r.source_type)
            prov_values.append(prov)
            if r.quarantined is True:
                quarantined_n += 1
            if r.id not in shown:
                # Counted exactly above; only the SHOWN subset carries a payload.
                resolved[r.id] = {}
                continue
            resolved[r.id] = {
                "id": r.id,
                "title": r.title,
                "url": r.url,
                "source": {
                    "id": r.source_id,
                    "name": r.name,
                    "domain": r.domain,
                    "country": r.country,
                    "source_type": r.source_type,
                    "provenance_class": prov,
                },
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "language": r.language,
                "detected_language": r.detected_language,
                "word_count": r.word_count,
                "content_hash": r.hash,
                "quarantined": bool(r.quarantined) if r.quarantined is not None else None,
                "quarantine_reason": r.quarantine_reason,
                "quarantine_criteria_version": r.quarantine_criteria_version,
                # The stored VADER compound. Deliberately NOT emitted under the DB's own
                # column name ``sentiment_score`` — see the module docstring: reusing a
                # legacy score-shaped column name here would defeat the no-score key walk
                # over this very payload. Value unchanged, column named in the method.
                "sentiment": {"compound": r.sentiment_score, "label": r.sentiment_label},
                "server_ip": r.server_ip,
                "ip_observed_at": r.ip_observed_at.isoformat() if r.ip_observed_at else None,
                "server_ip_reason": r.server_ip_reason,
            }

    missing = [i for i in ids if i not in resolved]
    items = [resolved[i] for i in shown_ids if resolved.get(i)]
    if items:
        _attach_linked_layers(session, items, max_linked_rows=max_linked_rows)
    if items and depth in ("standard", "full"):
        _attach_content(session, items, depth=depth, excerpt_chars=excerpt_chars)

    return {
        "shown": len(items),
        "total": len(ids),
        "resolved_total": len(ids) - len(missing),
        "missing_ids": missing[:50],
        "missing_n": len(missing),
        "quarantined_n": quarantined_n,
        "provenance_mix": _tally(prov_values, "class"),
        "items": items,
    }


def _attach_content(session, items: list[dict], *, depth: str, excerpt_chars: int) -> None:
    """Second, bounded pass that reads ``content`` ONLY for the shown articles."""
    from src.database.models import Article

    ids = [it["id"] for it in items]
    by_id = {it["id"]: it for it in items}
    for chunk in _chunked(ids):
        for row in (
            session.query(Article.id, Article.content, Article.compressed_content)
            .filter(Article.id.in_(chunk))
            .all()
        ):
            if row.compressed_content:
                from src.utils.compression import database_compressor

                text = database_compressor.decompress_text_from_storage(row.compressed_content)
            else:
                text = row.content or ""
            target = by_id.get(row.id)
            if target is None:
                continue
            total = len(text)
            if depth == "full":
                target["content"] = {"chars_total": total, "truncated": False, "text": text}
            else:
                target["content"] = {
                    "chars_total": total,
                    "truncated": total > excerpt_chars,
                    "excerpt_chars": min(total, excerpt_chars),
                    "text": text[:excerpt_chars],
                }


def _attach_linked_layers(session, items: list[dict], *, max_linked_rows: int) -> None:
    """Attach the SECONDARY linked layers for the shown articles.

    Each layer states its EXACT total beside the bounded list it shows. Every
    layer is independently wrapped, so one missing/failing table degrades that
    layer only.
    """
    from sqlalchemy import func

    from src.database.models import (
        AiKeyword,
        ArticleAnalysis,
        ArticleEntity,
        ArticleLink,
        ArticleMentionedDate,
        ArticleMentionedPlace,
        HazardEventDetail,
        Keyword,
        KeywordMention,
    )

    ids = [it["id"] for it in items]
    by_id = {it["id"]: it for it in items}

    def _bounded(layer: str, total_q, rows_q, shape) -> None:
        def _run() -> None:
            totals: dict[int, int] = {}
            for chunk in _chunked(ids):
                for aid, cnt in total_q(chunk):
                    totals[aid] = cnt
            buckets: dict[int, list] = {i: [] for i in ids}
            for chunk in _chunked(ids):
                for row in rows_q(chunk):
                    bucket = buckets.get(row[0])
                    if bucket is None or len(bucket) >= max_linked_rows:
                        continue
                    bucket.append(shape(row))
            for aid in ids:
                by_id[aid].setdefault("linked", {})[layer] = {
                    "shown": len(buckets[aid]),
                    "total": totals.get(aid, 0),
                    "items": buckets[aid],
                }

        res = _safe_section(f"linked.{layer}", _run)
        if isinstance(res, dict) and res.get("section_ok") is False:
            for aid in ids:
                by_id[aid].setdefault("linked", {})[layer] = res

    _bounded(
        "keyword_mentions",
        lambda c: session.query(KeywordMention.article_id, func.count())
        .filter(KeywordMention.article_id.in_(c))
        .group_by(KeywordMention.article_id)
        .all(),
        lambda c: session.query(
            KeywordMention.article_id,
            Keyword.term,
            Keyword.normalized_term,
            Keyword.language,
            KeywordMention.count,
            KeywordMention.extractor,
        )
        .join(Keyword, Keyword.id == KeywordMention.keyword_id)
        .filter(KeywordMention.article_id.in_(c))
        .order_by(KeywordMention.article_id, KeywordMention.count.desc())
        .all(),
        lambda r: {
            "term": r[1],
            "normalized_term": r[2],
            "language": r[3],
            "count": r[4],
            "extractor": r[5],
        },
    )
    _bounded(
        "mentioned_dates",
        lambda c: session.query(ArticleMentionedDate.article_id, func.count())
        .filter(ArticleMentionedDate.article_id.in_(c))
        .group_by(ArticleMentionedDate.article_id)
        .all(),
        lambda c: session.query(
            ArticleMentionedDate.article_id,
            ArticleMentionedDate.mentioned_on,
            ArticleMentionedDate.precision,
            ArticleMentionedDate.status,
            ArticleMentionedDate.snippet,
            ArticleMentionedDate.extractor,
        )
        .filter(ArticleMentionedDate.article_id.in_(c))
        .all(),
        lambda r: {
            "mentioned_on": r[1].isoformat() if r[1] else None,
            "precision": r[2],
            "status": r[3],
            "snippet": r[4],
            "extractor": r[5],
        },
    )
    _bounded(
        "mentioned_places",
        lambda c: session.query(ArticleMentionedPlace.article_id, func.count())
        .filter(ArticleMentionedPlace.article_id.in_(c))
        .group_by(ArticleMentionedPlace.article_id)
        .all(),
        lambda c: session.query(
            ArticleMentionedPlace.article_id,
            ArticleMentionedPlace.name,
            ArticleMentionedPlace.country,
            ArticleMentionedPlace.kind,
            ArticleMentionedPlace.mentions,
            ArticleMentionedPlace.lat,
            ArticleMentionedPlace.lon,
            ArticleMentionedPlace.note,
        )
        .filter(ArticleMentionedPlace.article_id.in_(c))
        .all(),
        lambda r: {
            "name": r[1], "country": r[2], "kind": r[3], "mentions": r[4],
            "lat": r[5], "lon": r[6], "note": r[7],
        },
    )
    _bounded(
        "entities",
        lambda c: session.query(ArticleEntity.article_id, func.count())
        .filter(ArticleEntity.article_id.in_(c))
        .group_by(ArticleEntity.article_id)
        .all(),
        lambda c: session.query(
            ArticleEntity.article_id,
            ArticleEntity.name,
            ArticleEntity.entity_class,
            ArticleEntity.mentions,
            ArticleEntity.extractor,
        )
        .filter(ArticleEntity.article_id.in_(c))
        .all(),
        lambda r: {"name": r[1], "entity_class": r[2], "mentions": r[3], "extractor": r[4]},
    )
    _bounded(
        "outbound_links",
        lambda c: session.query(ArticleLink.article_id, func.count())
        .filter(ArticleLink.article_id.in_(c))
        .group_by(ArticleLink.article_id)
        .all(),
        lambda c: session.query(
            ArticleLink.article_id,
            ArticleLink.url,
            ArticleLink.normalized_url,
            ArticleLink.link_type,
            ArticleLink.classification,
            ArticleLink.link_text,
        )
        .filter(ArticleLink.article_id.in_(c))
        .all(),
        lambda r: {
            "url": r[1], "normalized_url": r[2], "link_type": r[3],
            "classification": r[4], "link_text": r[5],
        },
    )
    # ArticleAnalysis: provenance ONLY at summary depth — the module contract is that
    # generated TEXT is never dumped at summary depth (kind/model/prompt_version/created_at).
    _bounded(
        "analyses",
        lambda c: session.query(ArticleAnalysis.article_id, func.count())
        .filter(ArticleAnalysis.article_id.in_(c))
        .group_by(ArticleAnalysis.article_id)
        .all(),
        lambda c: session.query(
            ArticleAnalysis.article_id,
            ArticleAnalysis.kind,
            ArticleAnalysis.model,
            ArticleAnalysis.prompt_version,
            ArticleAnalysis.created_at,
            func.length(ArticleAnalysis.result),
        )
        .filter(ArticleAnalysis.article_id.in_(c))
        .all(),
        lambda r: {
            "kind": r[1], "model": r[2], "prompt_version": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
            "result_chars": r[5],
            "note": "provenance only — the generated text itself is never dumped here",
        },
    )
    _bounded(
        "ai_keywords",
        lambda c: session.query(AiKeyword.article_id, func.count())
        .filter(AiKeyword.article_id.in_(c))
        .group_by(AiKeyword.article_id)
        .all(),
        lambda c: session.query(
            AiKeyword.article_id,
            AiKeyword.term,
            AiKeyword.kind,
            AiKeyword.language,
            AiKeyword.model,
            AiKeyword.prompt_version,
            AiKeyword.confirmed,
        )
        .filter(AiKeyword.article_id.in_(c))
        .all(),
        lambda r: {
            "term": r[1], "kind": r[2], "language": r[3], "model": r[4],
            "prompt_version": r[5], "confirmed": bool(r[6]),
            "label": "AI-derived · unreliable",
        },
    )

    def _hazards() -> None:
        found: dict[int, dict] = {}
        for chunk in _chunked(ids):
            for r in (
                session.query(
                    HazardEventDetail.article_id,
                    HazardEventDetail.provider,
                    HazardEventDetail.event_id,
                    HazardEventDetail.event_type,
                    HazardEventDetail.severity,
                    HazardEventDetail.magnitude,
                    HazardEventDetail.lat,
                    HazardEventDetail.lon,
                    HazardEventDetail.place,
                    HazardEventDetail.event_time,
                )
                .filter(HazardEventDetail.article_id.in_(chunk))
                .all()
            ):
                found[r[0]] = {
                    "provider": r[1], "event_id": r[2], "event_type": r[3],
                    "severity": r[4], "magnitude": r[5], "lat": r[6], "lon": r[7],
                    "place": r[8],
                    "event_time": r[9].isoformat() if r[9] else None,
                    "note": "provider-ASSERTED metadata, never inferred and never a score",
                }
        for aid in ids:
            by_id[aid].setdefault("linked", {})["hazard_detail"] = found.get(aid)

    res = _safe_section("linked.hazard_detail", _hazards)
    if isinstance(res, dict) and res.get("section_ok") is False:
        for aid in ids:
            by_id[aid].setdefault("linked", {})["hazard_detail"] = res


# --------------------------------------------------------------------------- #
#  Keyword facts
# --------------------------------------------------------------------------- #


def _keyword_facts(session, card) -> dict:
    """Facts about the keyword(s) a card keys on.

    A card's ``key`` is a within-type identity; for keyword-driven producers it IS
    the term. Matching is exact-then-normalized against the trusted index — a
    ``key`` that is not a keyword (a domain, a country+window span, a commodity)
    resolves to nothing, and that is reported as ``matched: false`` with the
    reason rather than as an empty success.
    """
    from src.analytics.equivalence import ring_meta, ring_of, ring_translation
    from src.analytics.queries import kind_of
    from src.analytics.store import tags_for_keyword
    from src.database.models import Keyword

    key = (card.key or "").strip()
    if not key:
        return {"matched": False, "reason": "this card carries no key to resolve", "keywords": []}
    normalized = " ".join(key.split()).casefold()
    rows = (
        session.query(Keyword)
        .filter((Keyword.term == key) | (Keyword.normalized_term == normalized))
        .limit(5)
        .all()
    )
    if not rows:
        return {
            "matched": False,
            "reason": (
                "the card's key does not resolve to a keyword in the trusted index — "
                "expected for a card keyed on a domain, a place+window span, a commodity "
                "or a whole-corpus distribution rather than a term"
            ),
            "key": key,
            "keywords": [],
        }
    out = []
    for kw in rows:
        lang = kw.language
        rid = ring_of(lang, kw.normalized_term)
        ring = ring_meta(rid) if rid else None
        out.append(
            {
                "id": kw.id,
                "term": kw.term,
                "normalized_term": kw.normalized_term,
                "language": lang,
                "kind": kind_of(kw),
                "is_entity": bool(kw.is_entity),
                "entity_type": kw.entity_type,
                "mention_count": kw.mention_count,
                "article_count": kw.article_count,
                "counters_last_reconciled_at": (
                    kw.last_reconciled_at.isoformat() if kw.last_reconciled_at else None
                ),
                "extractor": kw.extractor,
                "tags": _safe_section("keyword.tags", lambda n=kw.normalized_term: tags_for_keyword(session, n)),
                "ring": (
                    {
                        "id": rid,
                        "label": getattr(ring, "label", None),
                        "qid": getattr(ring, "qid", None),
                        "members_n": len(getattr(ring, "members", ()) or ()),
                        "translations": [
                            {"language": lg, "term": ring_translation(rid, lg)}
                            for lg in sorted({m[0] for m in (getattr(ring, "members", ()) or ())})
                        ],
                    }
                    if rid
                    else None
                ),
            }
        )
    return {
        "matched": True,
        "key": key,
        "keywords": out,
        "note": (
            "Counters are the maintained corpus-wide totals (exact by construction, with "
            "the reconcile watermark stated); a NULL watermark means never verified, not wrong."
        ),
    }


# --------------------------------------------------------------------------- #
#  Dimensions 2 + 3 — corpus fidelity and independence
# --------------------------------------------------------------------------- #


def _evidence_article_ids(card) -> list[int]:
    """Article ids carried on the card's own evidence rows, when present."""
    ids: list[int] = []
    for e in card.evidence or []:
        if not isinstance(e, dict):
            continue
        for field_name in ("article_id", "id"):
            v = e.get(field_name)
            if isinstance(v, int):
                ids.append(v)
                break
    return ids


def _corpus_fidelity(card, resolved: dict) -> dict:
    """Dimension 2 — do the ids resolve, and does the count match the claimed ``n``?"""
    total = resolved.get("total", 0)
    found = resolved.get("resolved_total", 0)
    missing = resolved.get("missing_n", 0)
    quarantined = resolved.get("quarantined_n", 0)
    n = card.n
    if not total:
        return {
            "has_article_ids": False,
            "article_ids_total": 0,
            "resolved_n": 0,
            "missing_n": 0,
            "quarantined_n": 0,
            "n_claimed": n,
            "n_matches_ids": None,
            "note": (
                "this card carries no article_ids — its selection is a keyword/topic or a "
                "whole-corpus distribution, so there is no id set to reconcile (not a defect)"
            ),
        }
    return {
        "has_article_ids": True,
        "article_ids_total": total,
        "resolved_n": found,
        "missing_n": missing,
        "quarantined_n": quarantined,
        "live_n": found - quarantined,
        "n_claimed": n,
        "n_matches_ids": (n == total) if isinstance(n, int) else None,
        "n_vs_ids_delta": (n - total) if isinstance(n, int) else None,
        "note": (
            "resolved_n counts ids that still exist; missing_n are ids with no article row "
            "(a pruned/deleted article the card still points at). quarantined_n are resolved "
            "but excluded from search/analytics by default, so live_n is what a reader reaches. "
            "n_matches_ids compares the card's own claimed n against its id-set size; None means "
            "the card states no n."
        ),
    }


def _independence(session, card, ids: list[int], *, max_articles: int) -> dict:
    """Dimension 3 — qualify the evidence for echo.

    Reuses the EXISTING primitives only: ``queries.corpus_coordination`` (MinHash+LSH
    near-duplicate clustering) and ``convergence._shared_origin`` (the exact
    shared-outbound-URL count). No new similarity algorithm is written here.
    """
    from src.briefing.leads import _distinct_sources

    out: dict = {
        "distinct_evidence_sources": _distinct_sources(card),
        "evidence_rows": len(card.evidence or []),
    }
    if not ids:
        out["note"] = (
            "no article_ids on this card — independence is reported from the evidence rows only"
        )
        return out

    def _origins() -> dict:
        from src.analytics.convergence import _shared_origin

        count, examples = _shared_origin(session, ids)
        return {
            "shared_origin_urls": count,
            "examples": examples,
            "note": (
                "outbound URLs cited by MORE THAN ONE of this card's articles — an EXACT "
                "count over the grouped query (never a cap); only the examples are bounded. "
                "Several articles citing one origin are not independent confirmation."
            ),
        }

    out["shared_origins"] = _safe_section("independence.shared_origins", _origins)

    coord_ids = ids[:max_articles]

    def _coord() -> dict:
        from src.analytics.queries import corpus_coordination

        res = corpus_coordination(session, article_ids=coord_ids)
        clusters = res.get("clusters") or []
        return {
            "analyzed": {"shown": len(coord_ids), "total": len(ids)},
            "n_clusters": len(clusters),
            "clustered_articles": sum(c.get("size", 0) for c in clusters),
            "single_source_clusters": sum(1 for c in clusters if c.get("single_source")),
            "clusters": [
                {
                    "size": c.get("size"),
                    "distinct_sources": c.get("distinct_sources"),
                    "sources": c.get("sources"),
                    "single_source": c.get("single_source"),
                    "avg_similarity": c.get("avg_similarity"),
                    "article_ids": c.get("article_ids"),
                }
                for c in clusters
            ],
            "method": res.get("method"),
            "caveat": res.get("caveat"),
            "note": (
                "Near-duplicate clustering reads article CONTENT through the codec, so it is "
                "bounded per card — 'analyzed' states exactly how many of the card's articles "
                "were examined. The distinct-source and shared-origin counts above are exact."
            ),
        }

    out["coordination"] = _safe_section("independence.coordination", _coord)
    return out


# --------------------------------------------------------------------------- #
#  Top-level report
# --------------------------------------------------------------------------- #


def _content_notice(depth: str) -> dict:
    """What this file contains — stated IN the payload so the operator knows
    before sharing it (local-only, shared only by click)."""
    carries = depth in ("standard", "full")
    return {
        "depth": depth,
        "contains_article_content": carries,
        "statement": (
            (
                "THIS EXPORT CONTAINS CORPUS CONTENT. At depth "
                f"'{depth}' it carries "
                + (
                    "COMPLETE article text"
                    if depth == "full"
                    else "a bounded excerpt of article text"
                )
                + " for the articles behind each card, plus their titles, URLs, keywords, "
                "extracted dates/places/entities and outbound links. Read it locally; it is "
                "shared only if you choose to share it."
            )
            if carries
            else (
                "This export carries NO article content. It carries card facts plus article "
                "METADATA (titles, URLs, sources, dates, languages, hashes) and the linked "
                "analytic layers. Titles and URLs still describe what you collected — read it "
                "locally; it is shared only if you choose to share it."
            )
        ),
        "written_by": "the app, on your machine, from your own corpus; no network call is made",
    }


AUDIT_METHOD = (
    "Every card every registered producer PROPOSES on one pass — including cards the "
    "cross-producer (type, key) dedup belt suppressed and cards you have dismissed — with, "
    "per card: its full trigger arithmetic re-evaluated, its article_ids resolved against the "
    "live corpus, its independence qualified with the existing near-duplicate and "
    "shared-origin primitives, its non-fabrication checks, its keyword facts, its provenance "
    "mix, its cross-card overlaps and its disclosed ordering facts. PLUS an inventory row for "
    "EVERY registered producer stating whether it emitted cards (ok), ran cleanly with nothing "
    "to say (no-signal), or RAISED (error, with the exception) — the three states run_all "
    "collapses into one indistinguishable empty list. Read-only; nothing is written."
)

AUDIT_CAVEAT = (
    "A snapshot of one producer pass at the moment it ran. Counts are exact and uncapped; "
    "every bounded LIST states its exact total beside it. An arithmetic row that cannot be "
    "mechanically recomputed is reported checkable:false with its reason and is never counted "
    "as a pass. A banned-key match is a flag for review, not automatically a violation. No "
    "composite score anywhere; absence is always distinguishable from zero."
)


def card_audit_report(
    session,
    *,
    depth: str = "summary",
    excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
    max_articles_per_card: int = DEFAULT_MAX_ARTICLES_PER_CARD,
    max_linked_rows: int = DEFAULT_MAX_LINKED_ROWS,
    max_coordination_articles: int = DEFAULT_MAX_COORDINATION_ARTICLES,
    determinism: bool = True,
    determinism_budget_s: float | None = DEFAULT_DETERMINISM_BUDGET_S,
    progress=None,
) -> dict:
    """Build the deep card-system audit. See the module docstring for the contract.

    ``depth`` is one of :data:`DEPTHS`.

    ``determinism`` (dimension 6, ON BY DEFAULT) runs a SECOND producer pass and
    diffs it. It doubles the producer cost, so it is governed by
    ``determinism_budget_s`` rather than by being switched off: the FIRST pass is
    timed, and the second is skipped ONLY when that measured time already exceeds
    the budget — reported as an explicit ``{"ran": false, "skipped": "budget"}``
    marker naming both numbers. ``None`` means no budget (always run it). A caller
    that wants the check genuinely disabled must pass ``determinism=False``, which
    is likewise reported (``"skipped": "not-requested"``) rather than being silent.

    ``progress(done, total, detail)`` is optional and never allowed to break the run.
    """
    if depth not in DEPTHS:
        raise ValueError(f"depth must be one of {DEPTHS}, got {depth!r}")
    excerpt_chars = max(0, int(excerpt_chars))
    max_articles_per_card = max(0, int(max_articles_per_card))
    max_linked_rows = max(0, int(max_linked_rows))
    max_coordination_articles = max(0, int(max_coordination_articles))

    started = time.monotonic()

    def _report(done: int, total: int, detail: str) -> None:
        if progress is None:
            return
        try:
            progress(done, total, detail)
        except Exception:  # noqa: BLE001 - progress is cosmetic, never fatal
            pass

    _report(0, 1, "running every registered producer")
    _pass_started = time.monotonic()
    outcomes = observe_producers(session)
    first_pass_s = time.monotonic() - _pass_started
    surfaced, suppressed = apply_dedup_belt(outcomes)

    dismissed: set[str] = set()
    try:
        from src.briefing.service import dismissed_ids

        dismissed = dismissed_ids()
    except Exception:  # noqa: BLE001 - a dismissal file must never break the audit
        _LOG.warning("card_audit: dismissed ids unreadable", exc_info=True)

    from src.briefing.leads import cluster_by_article_ids, explain_order, is_major, order_key

    now = datetime.now()
    all_cards = [c for _p, c in surfaced]
    overlap_index: dict[str, list[dict]] = {}
    clusters = _safe_section(
        "cross_card.clusters", lambda: cluster_by_article_ids(all_cards)
    )
    if isinstance(clusters, dict) and clusters.get("clusters"):
        for group in clusters["clusters"]:
            for member in group:
                overlap_index.setdefault(str(member.get("id")), []).extend(
                    [m for m in group if m.get("id") != member.get("id")]
                )

    total_units = len(surfaced) + len(suppressed)
    rows: list[dict] = []

    def _card_row(producer: str, card, *, status: str, collided_with=None) -> dict:
        card_dict = card.to_dict()
        ids = list(card.article_ids or [])
        ev_ids = [i for i in _evidence_article_ids(card) if i not in set(ids)]
        combined = ids + ev_ids
        shown_ids = combined[:max_articles_per_card]
        resolved = _safe_section(
            "articles",
            lambda: _resolve_articles(
                session,
                combined,
                depth=depth,
                excerpt_chars=excerpt_chars,
                max_linked_rows=max_linked_rows,
                shown_ids=shown_ids,
            ),
        )
        if not isinstance(resolved, dict) or resolved.get("section_ok") is False:
            resolved_ok: dict = {
                "shown": 0, "total": len(combined), "resolved_total": 0,
                "missing_n": 0, "quarantined_n": 0, "provenance_mix": [], "items": [],
                "degraded": resolved,
            }
        else:
            resolved_ok = resolved
        return {
            "producer": producer,
            "status": status,
            "collided_with": collided_with,
            "dismissed": card.id in dismissed,
            "card": card_dict,
            "trigger": card_dict.get("trigger"),
            "arithmetic": check_trigger(card_dict.get("trigger")),
            "non_fabrication": non_fabrication_checks(card_dict),
            "corpus_fidelity": _corpus_fidelity(card, resolved_ok),
            "independence": _safe_section(
                "independence",
                lambda: _independence(
                    session, card, ids, max_articles=max_coordination_articles
                ),
            ),
            "keywords": _safe_section("keywords", lambda: _keyword_facts(session, card)),
            "provenance_mix": resolved_ok.get("provenance_mix", []),
            "articles": {
                "shown": resolved_ok.get("shown", 0),
                "total": resolved_ok.get("total", 0),
                "from_article_ids": len(ids),
                "from_evidence_only": len(ev_ids),
                "resolved_total": resolved_ok.get("resolved_total", 0),
                "missing_n": resolved_ok.get("missing_n", 0),
                "missing_ids_sample": resolved_ok.get("missing_ids", []),
                "quarantined_n": resolved_ok.get("quarantined_n", 0),
                "items": resolved_ok.get("items", []),
                "note": (
                    "'total' is the EXACT number of articles behind this card; 'shown' is how "
                    "many carry a payload here. A cap bounds the examples, never the count."
                ),
            },
            "overlaps_with": overlap_index.get(card.id, []),
            "ordering": _safe_section(
                "ordering",
                lambda: {
                    "order_key": list(order_key(card, now=now)),
                    "explain_order": explain_order(card, now=now),
                    "major": is_major(card),
                    "note": (
                        "A disclosed lexicographic tuple over real facts, never a composite score."
                    ),
                },
            ),
        }

    for i, (producer, card) in enumerate(surfaced):
        _report(i, total_units, f"card {card.type}:{card.key}")
        rows.append(_card_row(producer, card, status="surfaced"))
    for j, dropped in enumerate(suppressed):
        _report(len(surfaced) + j, total_units, f"suppressed {dropped.get('type')}")
    # Suppressed cards are reported from the belt record (they carry the same identity
    # facts); resolving each one's whole corpus again would double the cost for a card
    # that is, by definition, an exact (type, key) twin of one already fully audited.
    suppressed_rows = [
        {**d, "status": "suppressed_duplicate",
         "note": "PROPOSED by its producer then dropped by the cross-producer (type, key) "
                 "dedup belt — invisible in every other view of the feed"}
        for d in suppressed
    ]

    # Dimension 6. ON by default; a skip is always an EXPLICIT, visible marker naming
    # why — never a silent default-off (a section that quietly did not run would be the
    # very defect this diagnostic exists to expose).
    if not determinism:
        det: dict = {
            "ran": False,
            "skipped": "not-requested",
            "first_pass_s": round(first_pass_s, 3),
            "note": (
                "the caller passed determinism=False — the second producer pass was not run, "
                "so nothing here says whether this feed is reproducible"
            ),
        }
    elif determinism_budget_s is not None and first_pass_s > determinism_budget_s:
        det = {
            "ran": False,
            "skipped": "budget",
            "first_pass_s": round(first_pass_s, 3),
            "budget_s": round(float(determinism_budget_s), 3),
            "note": (
                f"the first producer pass MEASURED {first_pass_s:.1f}s, over the "
                f"{float(determinism_budget_s):.1f}s budget for a second pass, so the "
                "determinism diff was skipped to keep this report inside its deadline. This "
                "is a measured skip, not a default — raise the budget "
                "(OO_CARD_AUDIT_DETERMINISM_BUDGET_S) or run the deep job to get it."
            ),
        }
    else:
        det = _safe_section("determinism", lambda: _determinism_check(session, outcomes))
        if isinstance(det, dict) and det.get("ran"):
            det["first_pass_s"] = round(first_pass_s, 3)
            det["budget_s"] = (
                round(float(determinism_budget_s), 3)
                if determinism_budget_s is not None
                else None
            )

    arith_rows = [r["arithmetic"] for r in rows]
    nf_rows = [r["non_fabrication"] for r in rows]
    fid_rows = [r["corpus_fidelity"] for r in rows]

    report = {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "elapsed_s": round(time.monotonic() - started, 3),
        "depth": depth,
        "content_notice": _content_notice(depth),
        "parameters": {
            "depth": depth,
            "excerpt_chars": excerpt_chars if depth == "standard" else None,
            "max_articles_per_card": max_articles_per_card,
            "max_linked_rows": max_linked_rows,
            "max_coordination_articles": max_coordination_articles,
            "determinism": determinism,
            "determinism_budget_s": determinism_budget_s,
            "first_producer_pass_s": round(first_pass_s, 3),
        },
        "producer_inventory": {
            "producers": [o.to_dict() for o in outcomes],
            "total": len(outcomes),
            "outcome_tallies": _tally([o.outcome for o in outcomes], "outcome"),
            "errored": [o.to_dict() for o in outcomes if o.outcome == "error"],
            "silent": [o.name for o in outcomes if o.outcome == "no-signal"],
            "note": (
                "THE POINT OF THIS DIAGNOSTIC. run_all() catches a producer exception, logs a "
                "warning and contributes [] — exactly what a producer with no signal "
                "contributes, so a producer crashing on every run is indistinguishable from a "
                "quiet one in every other card diagnostic. Here 'error' carries the exception "
                "type and message; 'no-signal' means it ran cleanly and had nothing to say."
            ),
        },
        "dedup": {
            "suppressed_n": len(suppressed),
            "suppressed": suppressed_rows,
            "note": (
                "run_all keeps the FIRST (registration-order) card for an exact (type, key) "
                "and drops the rest. Those drops are reported here because they were genuinely "
                "proposed and are invisible everywhere else."
            ),
        },
        "cards": rows,
        "cross_card": {
            "clusters": clusters,
            "note": (
                "Leads built from overlapping article sets, via the shared exact-Jaccard "
                "cluster_by_article_ids core. A shape to read, not a merge."
            ),
        },
        "determinism": det,
        "validation_summary": {
            "cards_surfaced": len(rows),
            "cards_suppressed": len(suppressed),
            "cards_dismissed": sum(1 for r in rows if r["dismissed"]),
            "determinism": {
                "ran": bool(det.get("ran")) if isinstance(det, dict) else False,
                "skipped": det.get("skipped") if isinstance(det, dict) else None,
                "stable": det.get("stable") if isinstance(det, dict) else None,
                "note": (
                    "'stable' is None whenever the check did not run — an unrun check is "
                    "never reported as a stable feed."
                ),
            },
            "arithmetic": {
                "cards_with_trigger": sum(1 for a in arith_rows if a.get("present")),
                "cards_without_trigger": sum(1 for a in arith_rows if not a.get("present")),
                "math_rows_total": sum(a.get("rows_total", 0) for a in arith_rows),
                "checkable_n": sum(a.get("checkable_n", 0) for a in arith_rows),
                "not_checkable_n": sum(a.get("not_checkable_n", 0) for a in arith_rows),
                "reproduced_n": sum(a.get("reproduced_n", 0) for a in arith_rows),
                "failed_n": sum(a.get("failed_n", 0) for a in arith_rows),
                "note": (
                    "reproduced_n counts rows actually recomputed and matched. "
                    "not_checkable_n is stated separately and is NOT a pass."
                ),
            },
            "non_fabrication": {
                "method_missing_n": sum(1 for c in nf_rows if not c.get("method_present")),
                "caveat_missing_n": sum(1 for c in nf_rows if not c.get("caveat_present")),
                "n_state_tallies": _tally([str(c.get("n_state")) for c in nf_rows], "n_state"),
                "cards_with_banned_key_matches": sum(
                    1 for c in nf_rows if c.get("banned_key_match_n")
                ),
            },
            "corpus_fidelity": {
                "cards_with_article_ids": sum(1 for f in fid_rows if f.get("has_article_ids")),
                "cards_without_article_ids": sum(
                    1 for f in fid_rows if not f.get("has_article_ids")
                ),
                "cards_with_missing_articles": sum(1 for f in fid_rows if f.get("missing_n")),
                "cards_with_quarantined_articles": sum(
                    1 for f in fid_rows if f.get("quarantined_n")
                ),
                "cards_where_n_mismatches_ids": sum(
                    1 for f in fid_rows if f.get("n_matches_ids") is False
                ),
            },
        },
        "method": AUDIT_METHOD,
        "caveat": AUDIT_CAVEAT,
    }
    _report(total_units, total_units, "done")
    return _sanitise_non_finite(report)


#: How many non-finite field PATHS to name in the report. A handful identifies the
#: culprit; naming thousands would itself bloat the member this exists to save.
_NON_FINITE_NAME_LIMIT = 50


def _sanitise_non_finite(report: dict) -> dict:
    """Replace ``inf``/``-inf``/``NaN`` with ``None``, and NAME where they were.

    WHY THIS EXISTS, from the operator's 2026-08-08 bundle: this member computed
    for **112 seconds** and was then thrown away whole by the JSON encoder --
    ``Out of range float values are not JSON compliant: -inf``. Every bundle since
    at least 2026-08-06 shipped ``card-audit.json.error.txt`` instead of a report.

    ``_eval_arith`` already refuses a non-finite value (returns not-checkable), so
    the offender arrives from a PRODUCER's own card payload, and which one is not
    knowable without the corpus that produced it. So the repair does two things,
    and the second is the load-bearing one: the value becomes ``null`` so the
    member survives, AND its dotted path is listed under ``non_finite`` so the
    NEXT bundle identifies the producer. Sanitising silently would make this the
    exact hiding-place-for-the-bug-it-survives shape the ledger already names
    twice (K2, ``ai_diagnostics._safe``).

    ``None`` is the honest replacement: an infinity is not a measurement, and the
    report's own convention already reads ``null`` as "no value here" rather than
    as zero.
    """
    paths: list[str] = []
    truncated = [0]

    def _walk(node, path: str):
        if isinstance(node, float):
            if node != node or node in (float("inf"), float("-inf")):
                if len(paths) < _NON_FINITE_NAME_LIMIT:
                    paths.append(path or "<root>")
                else:
                    truncated[0] += 1
                return None
            return node
        if isinstance(node, dict):
            return {k: _walk(v, f"{path}.{k}" if path else str(k)) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v, f"{path}[{i}]") for i, v in enumerate(node)]
        if isinstance(node, tuple):
            return [_walk(v, f"{path}[{i}]") for i, v in enumerate(node)]
        return node

    out = _walk(report, "")
    if paths or truncated[0]:
        out["non_finite"] = {
            "n": len(paths) + truncated[0],
            "fields": paths,
            "named_truncated": truncated[0],
            "note": (
                "these fields held inf/-inf/NaN and were replaced with null so this "
                "report could be serialised at all. An infinity is not a measurement: "
                "the producer that emitted it is the defect, and these paths name it."
            ),
        }
    return out


def _determinism_check(session, first: list[ProducerOutcome]) -> dict:
    """Dimension 6 — run the producer pass a SECOND time and diff it."""
    second = observe_producers(session)
    first_by = {o.name: o for o in first}
    second_by = {o.name: o for o in second}
    outcome_changes = [
        {
            "producer": name,
            "first": first_by[name].outcome,
            "second": second_by[name].outcome,
        }
        for name in sorted(set(first_by) & set(second_by))
        if first_by[name].outcome != second_by[name].outcome
    ]
    a_cards = {(c.type, c.key): c for o in first for c in o.cards}
    b_cards = {(c.type, c.key): c for o in second for c in o.cards}
    appeared = sorted(f"{t}:{k}" for (t, k) in set(b_cards) - set(a_cards))
    vanished = sorted(f"{t}:{k}" for (t, k) in set(a_cards) - set(b_cards))
    moved = []
    for ident in sorted(set(a_cards) & set(b_cards)):
        a, b = a_cards[ident], b_cards[ident]
        if a.n != b.n or a.signal != b.signal:
            moved.append(
                {
                    "card": f"{ident[0]}:{ident[1]}",
                    "n_first": a.n,
                    "n_second": b.n,
                    "signal_changed": a.signal != b.signal,
                }
            )
    return {
        "ran": True,
        "cards_first": len(a_cards),
        "cards_second": len(b_cards),
        "appeared": appeared,
        "vanished": vanished,
        "numbers_moved": moved,
        "producer_outcome_changes": outcome_changes,
        "stable": not (appeared or vanished or moved or outcome_changes),
        "note": (
            "Two consecutive producer passes over the same session. Real ingest between the "
            "passes legitimately moves numbers, so instability is a prompt to look, never "
            "automatically a defect."
        ),
    }


# --------------------------------------------------------------------------- #
#  Preflight (size estimate) + job worker + last-report
# --------------------------------------------------------------------------- #


def estimate_card_audit(
    session,
    *,
    depth: str = "standard",
    excerpt_chars: int = DEFAULT_EXCERPT_CHARS,
    max_articles_per_card: int = DEFAULT_MAX_ARTICLES_PER_CARD,
) -> dict:
    """A cheap PREFLIGHT so the operator sees roughly how large a run will be
    before starting it.

    Runs the producer pass (the same work the report starts with) and sizes the
    payload from the REAL card/article counts plus a measured per-article
    metadata cost — never a guessed constant. Explicitly an ESTIMATE with its
    method stated; the real file is whatever it is.
    """
    if depth not in DEPTHS:
        raise ValueError(f"depth must be one of {DEPTHS}, got {depth!r}")
    outcomes = observe_producers(session)
    surfaced, suppressed = apply_dedup_belt(outcomes)
    per_card_ids = []
    for _p, card in surfaced:
        ids = set(card.article_ids or []) | set(_evidence_article_ids(card))
        per_card_ids.append(len(ids))
    articles_total = sum(per_card_ids)
    articles_shown = sum(min(k, max_articles_per_card) for k in per_card_ids)

    # Measured constants (bytes of JSON), not guesses: ~1.6 KB of metadata + linked-layer
    # rows per shown article, ~2.5 KB of card scaffolding per card.
    per_article_meta = 1600
    per_card_overhead = 2500
    content_bytes = 0
    if depth == "standard":
        content_bytes = articles_shown * excerpt_chars
    elif depth == "full":
        avg = _safe_section("estimate.avg_chars", lambda: _avg_content_chars(session))
        avg_chars = avg.get("avg_chars") if isinstance(avg, dict) else None
        content_bytes = int(articles_shown * (avg_chars or 0))

    est = (
        len(surfaced) * per_card_overhead
        + articles_shown * per_article_meta
        + content_bytes
        + len(outcomes) * 300
    )
    return {
        "schema": "oo-card-audit-preflight-1",
        "depth": depth,
        "producers": len(outcomes),
        "cards_surfaced": len(surfaced),
        "cards_suppressed": len(suppressed),
        "articles_referenced_total": articles_total,
        "articles_that_would_carry_a_payload": articles_shown,
        "estimated_bytes": est,
        "estimated_mb": round(est / (1024 * 1024), 2),
        "content_notice": _content_notice(depth),
        "method": (
            "The REAL producer pass, then the real card/article counts multiplied by measured "
            "per-card and per-article JSON costs (and, at full depth, the corpus's own mean "
            "article length). Counts are exact; only the byte figure is an estimate."
        ),
        "caveat": (
            "An ESTIMATE of the output size, not a measurement of it. The card and article "
            "counts above are exact; the byte total can be off either way."
        ),
    }


def _avg_content_chars(session) -> dict:
    """Mean article length, for the full-depth size estimate only."""
    from sqlalchemy import func

    from src.database.models import Article

    row = session.query(func.avg(Article.word_count), func.count(Article.id)).one()
    avg_words, n = row[0], row[1]
    # ~6 chars per word including separators — a stated approximation, used only for a
    # size ESTIMATE and never presented as a measured content length.
    return {"avg_chars": float(avg_words) * 6.0 if avg_words else None, "articles": n}


def _report_dir():
    from src.paths import data_dir

    d = data_dir() / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _report_path(stamp: str):
    return _report_dir() / f"oo-card-audit-{stamp}.json"


def card_audit_worker(ctx, **kwargs) -> dict:
    """BackgroundJob worker for a DEEP card-audit run.

    A deep run reads article content through the SQLCipher codec, so it never runs
    on the request thread: the endpoint starts this job, the task manager shows it,
    and it stops cooperatively at the next card boundary when cancelled.
    """
    import json

    depth = kwargs.get("depth") or "standard"

    def _progress(done: int, total: int, detail: str) -> None:
        ctx.set_progress(done=done, total=total, detail=detail)
        if ctx.stopping:
            raise _Cancelled()

    _session = session_from_scope()
    try:
        report = card_audit_report(
            _session,
            depth=depth,
            excerpt_chars=int(kwargs.get("excerpt_chars") or DEFAULT_EXCERPT_CHARS),
            max_articles_per_card=int(
                kwargs.get("max_articles_per_card") or DEFAULT_MAX_ARTICLES_PER_CARD
            ),
            max_linked_rows=int(kwargs.get("max_linked_rows") or DEFAULT_MAX_LINKED_ROWS),
            max_coordination_articles=int(
                kwargs.get("max_coordination_articles") or DEFAULT_MAX_COORDINATION_ARTICLES
            ),
            # Dimension 6 defaults ON here too (maintainer-ruled). The deep job has no
            # per-member deadline to protect, so it carries NO budget by default: an
            # explicitly-requested deep run should pay the second pass rather than skip it.
            determinism=(
                True if kwargs.get("determinism") is None else bool(kwargs.get("determinism"))
            ),
            determinism_budget_s=kwargs.get("determinism_budget_s"),
            progress=_progress,
        )
    except _Cancelled:
        return {"cancelled": True, "note": "cancelled before a report was written"}
    finally:
        _session.close()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = _report_path(stamp)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return {
        "path": str(path),
        "filename": path.name,
        "depth": depth,
        "cards_surfaced": report["validation_summary"]["cards_surfaced"],
        "producers": report["producer_inventory"]["total"],
        "outcome_tallies": report["producer_inventory"]["outcome_tallies"],
        "bytes": path.stat().st_size,
    }


class _Cancelled(RuntimeError):
    """Internal: a cooperative stop between cards (never surfaced as an error)."""


def session_from_scope():
    """A dedicated read session for the background worker (never the request's)."""
    from src.database.session import SessionLocal

    return SessionLocal()


def last_card_audit_report() -> dict:
    """The newest saved deep card-audit report's SUMMARY (read-only; never runs one).

    Returns the report's own header blocks — never the full per-card payload, which
    can carry corpus content at standard/full depth and must not be pulled into an
    unrelated caller by accident.
    """
    import json

    try:
        d = _report_dir()
        files = sorted(d.glob("oo-card-audit-*.json"))
    except Exception as exc:  # noqa: BLE001 - a missing data dir is not an error here
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not files:
        return {
            "available": False,
            "reason": "no deep card-audit run has been saved yet",
            "note": (
                "the summary-depth report is computed live by GET /api/diagnostics/card-audit "
                "and rides the all-diagnostics bundle; this is the DEEP job's saved output"
            ),
        }
    newest = files[-1]
    try:
        payload = json.loads(newest.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a corrupt saved file must degrade, not raise
        return {"available": False, "reason": f"unreadable report {newest.name}: {exc}"}
    return {
        "available": True,
        "filename": newest.name,
        "bytes": newest.stat().st_size,
        "schema": payload.get("schema"),
        "generated_at": payload.get("generated_at"),
        "depth": payload.get("depth"),
        "parameters": payload.get("parameters"),
        "producer_inventory": {
            k: v for k, v in (payload.get("producer_inventory") or {}).items()
            if k in ("total", "outcome_tallies", "errored", "silent", "note")
        },
        "validation_summary": payload.get("validation_summary"),
        "content_notice": payload.get("content_notice"),
        "method": payload.get("method"),
        "caveat": payload.get("caveat"),
        "note": "header + summary only; the per-card payload stays in the saved file",
    }


def audit_report_env_defaults() -> dict:
    """Env-tunable bounds for the bundle member (generous defaults; a diagnostics
    run is not a UI request). Clamped so a bad value can never explode the member."""

    def _int(name: str, default: int, lo: int, hi: int) -> int:
        try:
            v = int(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            return default
        return max(lo, min(v, hi))

    def _float(name: str, default: float, lo: float, hi: float) -> float:
        import math

        try:
            v = float(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            return default
        if not math.isfinite(v):
            return default
        return max(lo, min(v, hi))

    return {
        "max_articles_per_card": _int("OO_CARD_AUDIT_MAX_ARTICLES", 10, 0, 500),
        "max_linked_rows": _int("OO_CARD_AUDIT_MAX_LINKED", 10, 0, 200),
        "max_coordination_articles": _int("OO_CARD_AUDIT_MAX_COORD", 0, 0, 500),
        # Dimension 6 stays ON in the bundle (maintainer-ruled). The budget is a
        # fraction of the per-member DB deadline (300 s default), so a corpus where one
        # producer pass already eats the member's time reports an honest, visible
        # "skipped: budget" instead of the member timing out or the check being
        # silently defaulted off.
        "determinism_budget_s": _float("OO_CARD_AUDIT_DETERMINISM_BUDGET_S", 90.0, 0.0, 3600.0),
    }
