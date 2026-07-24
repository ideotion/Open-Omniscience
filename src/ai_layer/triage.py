"""
LLM keyword TRIAGE — the measure-before-trust core (planning §8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The corpus carries ~3 M keywords with junk and mis-tagged kinds ("Organizations tagged
as Persons") that CANNOT be curated by hand. This module batches head-scope keywords to a
LOCAL Ollama model which returns a CONSTRAINED verdict (junk | content | unsure) + a kind
(person | org | place | other) per keyword. The result is **EXPORT-ONLY JSONL** — the model
NEVER writes the trusted, rule-based keyword index. Claude (CLI) verifies stratified samples
and emits the DETERMINISTIC artifacts (scoped stoplist additions, kind-override files) as
reviewed PRs; the provenance chain on every artifact is **ai-proposed · claude-verified ·
maintainer-merged**.

HONESTY BY CONSTRUCTION (the doctrine = measure-before-trust):
  * EXPORT-ONLY: this module reads the trusted index (head-scope selection is a counter-only
    read) and WRITES nothing but a JSONL log + proposal dicts — never a KeywordMention /
    Keyword / stoplist. An invariant test asserts a triage batch creates ZERO DB rows.
  * ECHO-BACK VALIDATION: the model must echo each keyword exactly; a mangled / absent /
    hallucinated term is INVALID (counted, never guessed — the negative-space guard #590).
  * CONSTRAINED verdicts: a verdict/kind outside the allowed sets is malformed (counted,
    never coerced to a "close" value).
  * CANARIES: anchor keywords with known verdicts ride EVERY batch; a batch whose canaries
    fail is flagged for re-run (continuous QA on the log).
  * TIMESTAMPS: every batch record passes Ollama's OWN measured timing fields through
    verbatim so the strategy's COST is computed ("if one week, do it; if ten years, change
    strategy"), never asserted. The ETA is counted in VALID verdicts/sec.
  * NO composite score — the bench metrics are each reported ALONE.

The pure functions here are testable with a STUB client and no network (mirrors
`ai_layer.extract`); the real batch run + the 7-model bench are OPERATOR-run on the rig that
hosts Ollama in production (this design box has no models / no GPU — §8.3: a CPU-only bench
understates the real rig). ``run_triage_selftest`` proves the MECHANISM on a stub so a
regression reddens both the in-app self-test and CI (mirrors ``run_perception_eval_selftest``).
"""

from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass, field
from itertools import combinations

# Prompt provenance — stored on every triage record (bump when the prompt changes).
TRIAGE_PROMPT_VERSION = "keyword-triage-v1"

VERDICTS: frozenset[str] = frozenset({"junk", "content", "unsure"})
KINDS: frozenset[str] = frozenset({"person", "org", "place", "other"})

# A line-per-keyword delimiter unlikely to occur inside a keyword; the parser rsplits from
# the RIGHT so a term containing " :: " still parses (term = everything before the last two).
_DELIM = " :: "

# Minimal, EXPLICIT alias map — we accept ONLY the constrained tokens plus these documented
# synonyms; anything else is malformed (counted, never guessed into a "close" value).
_KIND_ALIASES = {
    "organization": "org",
    "organisation": "org",
    "organizations": "org",
    "location": "place",
    "loc": "place",
    "geo": "place",
    "people": "person",
    "per": "person",
}
_VERDICT_ALIASES = {
    "keep": "content",
    "content-word": "content",
    "noise": "junk",
    "garbage": "junk",
    "unclear": "unsure",
    "unknown": "unsure",
}

_MAX_SNIPPET_CHARS = 160


# --------------------------------------------------------------------------- #
# The batch prompt (term · language · counts · 1-2 context snippets).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TriageItem:
    """One keyword handed to the model for a verdict. ``snippets`` are optional short
    context lines (never the whole article); counts are the trusted maintained counters."""

    term: str
    language: str | None = None
    mention_count: int | None = None
    article_count: int | None = None
    is_entity: bool | None = None
    snippets: tuple[str, ...] = ()
    # The Keyword row's own id -- populated ONLY by select_triage_batch_after (B5's
    # progressive sweep, 2026-07-24 Session B), which needs it as the resumable
    # keyset-pagination cursor. None from select_triage_head (the one-shot path never
    # needed it, so it stays an optional, backward-compatible field).
    keyword_id: int | None = None


_TRIAGE_SYSTEM = (
    "You are cleaning a keyword index for an investigative-journalism corpus. For EACH keyword "
    "below decide a VERDICT — junk (boilerplate / navigation / a stray fragment that is not a "
    "real topic or name), content (a real topic, concept, place, person, or organisation), or "
    "unsure — and a KIND — person, org, place, or other. Reply with EXACTLY one line per "
    "keyword, in this format and nothing else:\n"
    "<keyword> :: <verdict> :: <kind>\n"
    "Echo the keyword EXACTLY as given. Do not add numbering, commentary, or extra lines. If you "
    "cannot judge a keyword, use 'unsure :: other' — never omit a line and never invent a keyword."
)


def build_triage_prompt(
    items: list[TriageItem],
    *,
    canaries: tuple[TriageItem, ...] = (),
    max_snippet_chars: int = _MAX_SNIPPET_CHARS,
) -> tuple[str, str, list[str]]:
    """Build the (system, user, expected_terms) triage prompt for a batch.

    Canaries (anchor keywords with a known verdict) are MIXED IN with the real items — the
    model must not be able to tell them apart — and their terms are returned in
    ``expected_terms`` too, so the echo-back / verdict parse covers them. The caller keeps the
    canary EXPECTATIONS separately (``check_canaries``); this only sets the prompt + the
    echo-back contract."""
    lines: list[str] = []
    expected: list[str] = []
    for it in [*items, *canaries]:
        expected.append(it.term)
        ctx = []
        if it.language:
            ctx.append(f"lang={it.language}")
        if it.article_count is not None:
            ctx.append(f"{it.article_count} articles")
        if it.mention_count is not None:
            ctx.append(f"{it.mention_count} mentions")
        if it.is_entity:
            ctx.append("currently tagged entity")
        head = f"- {it.term}" + (f"  [{', '.join(ctx)}]" if ctx else "")
        lines.append(head)
        for sn in it.snippets[:2]:
            snip = " ".join(str(sn).split())[:max_snippet_chars]
            if snip:
                lines.append(f"    …{snip}…")
    user = "Keywords to triage:\n" + "\n".join(lines)
    return _TRIAGE_SYSTEM, user, expected


# --------------------------------------------------------------------------- #
# The pure verdict PARSER + echo-back validation.
# --------------------------------------------------------------------------- #
def _norm_term(s: str) -> str:
    """Fold case + accents + collapse whitespace for a forgiving echo-back match (a mangled
    term that no longer matches ANY expected term is rejected, not stored)."""
    s = unicodedata.normalize("NFKD", str(s or "")).strip().casefold()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def _canon_verdict(tok: str) -> str | None:
    t = str(tok or "").strip().casefold()
    if t in VERDICTS:
        return t
    return _VERDICT_ALIASES.get(t)


def _canon_kind(tok: str) -> str | None:
    t = str(tok or "").strip().casefold()
    if t in KINDS:
        return t
    return _KIND_ALIASES.get(t)


@dataclass
class ParsedBatch:
    """The result of parsing one model response against the expected keyword set.

    ``verdicts`` maps the CANONICAL expected term -> {"verdict", "kind"} for each VALID,
    echo-matched line. ``parse_failures`` counts echo mismatches (incl. hallucinated terms not
    in the batch) + malformed verdict/kind. ``missing`` are expected terms the model gave no
    valid line for. Everything is a COUNT — nothing is guessed."""

    verdicts: dict[str, dict] = field(default_factory=dict)
    parse_failures: int = 0
    missing: list[str] = field(default_factory=list)
    keywords_in: int = 0
    raw_lines: int = 0

    @property
    def unsure_count(self) -> int:
        return sum(1 for v in self.verdicts.values() if v["verdict"] == "unsure")

    @property
    def verdicts_out(self) -> int:
        return len(self.verdicts)


def parse_verdicts(raw: str | None, expected_terms: list[str]) -> ParsedBatch:
    """Parse a model's triage response into validated per-keyword verdicts.

    Contract: one ``<keyword> :: <verdict> :: <kind>`` line per keyword. A returned keyword is
    matched against ``expected_terms`` by a forgiving normalization (case/accents/whitespace) —
    a term matching NO expected keyword is a hallucination and is REJECTED (parse_failure), a
    malformed verdict/kind is REJECTED (parse_failure), a duplicate keeps the first, and an
    expected keyword with no valid line is ``missing``. Nothing is coerced or invented."""
    # Echo-back is EXACT-FIRST: the model is told to echo the keyword EXACTLY, so an exact
    # string match is always safe. A tolerant (case/accent/whitespace) match is used ONLY when
    # it is UNAMBIGUOUS — two distinct expected keywords that fold to the same normalized key
    # (Straße/Strasse, Café/café, WHO/who) must NEVER be collapsed onto one, or one keyword's
    # verdict is silently dropped OR misattributed to the other (a fabrication that would flow
    # straight into a deletion proposal). Duplicate expected terms are deduped for the counts.
    distinct_expected = list(dict.fromkeys(expected_terms))
    exact = set(distinct_expected)
    norm_map: dict[str, list[str]] = {}
    for t in distinct_expected:
        norm_map.setdefault(_norm_term(t), []).append(t)

    def _resolve(term_raw: str) -> str | None:
        s = term_raw.strip()
        if s in exact:  # exact echo — always safe, even across a normalized collision.
            return s
        cands = norm_map.get(_norm_term(term_raw))
        if cands and len(cands) == 1:  # unambiguous tolerant match.
            return cands[0]
        return None  # no match, OR an ambiguous collision — reject, never guess which.

    pb = ParsedBatch(keywords_in=len(distinct_expected))
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        pb.raw_lines += 1
        parts = line.rsplit(_DELIM, 2)
        if len(parts) != 3:
            pb.parse_failures += 1
            continue
        term_raw, verdict_raw, kind_raw = parts
        canonical = _resolve(term_raw)
        verdict = _canon_verdict(verdict_raw)
        kind = _canon_kind(kind_raw)
        if canonical is None or verdict is None or kind is None:
            # echo mismatch / hallucinated / ambiguous-collision / malformed verdict|kind.
            pb.parse_failures += 1
            continue
        if canonical in pb.verdicts:
            continue  # duplicate line for the same keyword — first valid wins.
        pb.verdicts[canonical] = {"verdict": verdict, "kind": kind}
    pb.missing = [t for t in distinct_expected if t not in pb.verdicts]
    return pb


# --------------------------------------------------------------------------- #
# Canaries — anchor keywords with a KNOWN verdict, flag the batch on a mismatch.
# --------------------------------------------------------------------------- #
def check_canaries(pb: ParsedBatch, canary_expected: dict[str, dict]) -> dict:
    """Compare the parsed verdicts of the canary anchors against their KNOWN answers.

    ``canary_expected`` maps a canary term -> {"verdict": ...} (kind optional). Returns
    ``{"ok", "checked", "failed": [{term, expected, got}]}``. A canary that was dropped
    (missing / echo-failed) counts as a failure — the batch is untrustworthy either way."""
    failed = []
    for term, want in canary_expected.items():
        got = pb.verdicts.get(term)
        want_v = want.get("verdict")
        if got is None:
            failed.append({"term": term, "expected": want_v, "got": None})
            continue
        if want_v is not None and got["verdict"] != want_v:
            failed.append({"term": term, "expected": want_v, "got": got["verdict"]})
        elif want.get("kind") is not None and got["kind"] != want["kind"]:
            failed.append({"term": term, "expected": want.get("kind"), "got": got["kind"]})
    return {"ok": not failed, "checked": len(canary_expected), "failed": failed}


# --------------------------------------------------------------------------- #
# The JSONL timing schema (the timestamps ruling) + the ETA line.
# --------------------------------------------------------------------------- #
_OLLAMA_TIMING_FIELDS = (
    "total_duration",
    "load_duration",
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
)


def gen_meta_from_result(result) -> dict:
    """Pull Ollama's OWN measured timing fields off a GenerationResult, passed through
    VERBATIM (missing = None — honest, never a fabricated 0)."""
    return {f: getattr(result, f, None) for f in _OLLAMA_TIMING_FIELDS}


def run_header(*, model: str, model_digest: str | None = None, hardware: dict | None = None) -> dict:
    """The per-RUN header — model + digest (a silently-updated tag stays distinguishable) +
    a hardware fingerprint the caller supplies (never asserted here)."""
    return {
        "schema": "oo-keyword-triage-run-1",
        "prompt_version": TRIAGE_PROMPT_VERSION,
        "model": model,
        "model_digest": model_digest,
        "hardware": hardware or {},
    }


def batch_record(
    *,
    started_at: str,
    finished_at: str,
    gen_meta: dict,
    pb: ParsedBatch,
    canary: dict,
    model: str,
    model_digest: str | None = None,
) -> dict:
    """One EXPORT-ONLY JSONL batch record: Ollama's timing passed through verbatim + the
    validated counts. Counts only, no score."""
    rec = {
        "schema": "oo-keyword-triage-batch-1",
        "started_at": started_at,
        "finished_at": finished_at,
        "model": model,
        "model_digest": model_digest,
        "keywords_in": pb.keywords_in,
        "verdicts_out": pb.verdicts_out,
        "parse_failures": pb.parse_failures,
        "missing": len(pb.missing),
        "unsure_count": pb.unsure_count,
        "canary_ok": bool(canary.get("ok", True)),
        "canary_failed": canary.get("failed", []),
    }
    for f in _OLLAMA_TIMING_FIELDS:
        rec[f] = gen_meta.get(f)
    return rec


def eta_line(remaining_keywords: int, valid_verdicts: int, total_wall_s: float) -> dict | None:
    """ETA = remaining ÷ (valid_verdicts ÷ Σ batch_wall_s) — throughput in VALID verdicts/sec.

    Returns None (degrade loudly) until there is real throughput to divide by; never a
    fabricated countdown. Carries its method + the replace-me-with-measurement caveat."""
    if valid_verdicts <= 0 or total_wall_s <= 0 or remaining_keywords < 0:
        return None
    throughput = valid_verdicts / total_wall_s
    return {
        "throughput_valid_per_s": round(throughput, 4),
        "remaining_keywords": remaining_keywords,
        "eta_seconds": round(remaining_keywords / throughput, 1),
        "method": "remaining ÷ (valid verdicts ÷ Σ batch wall seconds); throughput = VALID verdicts/sec.",
        "caveat": (
            "A MEASURED extrapolation from the batches run so far — it moves as throughput "
            "settles (first-batch load time is separate). No sanity envelope is asserted."
        ),
    }


# --------------------------------------------------------------------------- #
# Head-scope SELECTION — the top keywords by ARTICLE SPREAD (counter-only read).
# --------------------------------------------------------------------------- #
def select_triage_head(session, limit: int, *, min_articles: int = 1) -> list[TriageItem]:
    """The top ``limit`` keywords by ARTICLE SPREAD (``Keyword.article_count`` DESC) — the
    head where the analytics actually surface, not the hapax tail. A COUNTER-ONLY read (no
    keyword_mentions→articles join, so no article decrypt — the codec column-order perf trap);
    returns TriageItems WITHOUT snippets (snippets are an optional, bounded enrichment the
    operator adds). Read-only: this NEVER writes the trusted index."""
    from src.database.models import Keyword

    rows = (
        session.query(
            Keyword.term,
            Keyword.language,
            Keyword.mention_count,
            Keyword.article_count,
            Keyword.is_entity,
        )
        .filter(Keyword.article_count >= min_articles)
        .order_by(Keyword.article_count.desc(), Keyword.mention_count.desc())
        .limit(limit)
        .all()
    )
    return [
        TriageItem(
            term=r[0],
            language=r[1],
            mention_count=int(r[2] or 0),
            article_count=int(r[3] or 0),
            is_entity=bool(r[4]) if r[4] is not None else None,
        )
        for r in rows
        if r[0]
    ]


def select_triage_batch_after(
    session,
    batch_size: int,
    *,
    min_articles: int = 1,
    after: tuple[int, int, int] | None = None,
) -> list[TriageItem]:
    """Keyset-paginated page of the SAME head-scope order ``select_triage_head`` uses
    (article_count DESC, mention_count DESC), made a STABLE TOTAL ORDER via a
    ``Keyword.id`` tiebreaker so a page never repeats or skips a row across calls.

    ``after`` is the ``(article_count, mention_count, keyword_id)`` triple of the
    LAST item the previous call returned; passing it resumes EXACTLY where that call
    left off. This is the B5 (2026-07-24 Session B) progressive-sweep primitive: its
    state is the three-tuple cursor, O(1) regardless of how large the sweep grows —
    unlike an ever-growing exclude-id set, it can never hit SQLite's bound-variable
    ceiling. An empty return means the head scope (down to ``min_articles``) is
    exhausted. Read-only, counter-only (no keyword_mentions→articles join)."""
    from sqlalchemy import and_, or_

    from src.database.models import Keyword

    q = session.query(
        Keyword.id,
        Keyword.term,
        Keyword.language,
        Keyword.mention_count,
        Keyword.article_count,
        Keyword.is_entity,
    ).filter(Keyword.article_count >= min_articles)

    if after is not None:
        a_ac, a_mc, a_id = after
        q = q.filter(
            or_(
                Keyword.article_count < a_ac,
                and_(Keyword.article_count == a_ac, Keyword.mention_count < a_mc),
                and_(
                    Keyword.article_count == a_ac,
                    Keyword.mention_count == a_mc,
                    Keyword.id < a_id,
                ),
            )
        )

    rows = (
        q.order_by(
            Keyword.article_count.desc(), Keyword.mention_count.desc(), Keyword.id.desc()
        )
        .limit(max(1, batch_size))
        .all()
    )
    return [
        TriageItem(
            term=r[1],
            language=r[2],
            mention_count=int(r[3] or 0),
            article_count=int(r[4] or 0),
            is_entity=bool(r[5]) if r[5] is not None else None,
            keyword_id=int(r[0]),
        )
        for r in rows
        if r[1]
    ]


# --------------------------------------------------------------------------- #
# The thin NETWORKED runner — one batch through the injected client (stub-testable).
# --------------------------------------------------------------------------- #
def run_triage_batch(
    client,
    items: list[TriageItem],
    *,
    model: str,
    canaries: tuple[TriageItem, ...] = (),
    canary_expected: dict[str, dict] | None = None,
    keep_alive: str | None = None,
    monotonic=time.monotonic,
) -> dict:
    """Run ONE triage batch through ``client.generate`` (the injected Ollama seam) and return
    the parsed + validated result. Measures wall time via ``monotonic`` (injectable for tests).
    The caller assembles the JSONL record (``batch_record``) + the run header; this stays the
    thin networked part (mirrors ``ai_layer.jobs.extract_for_articles``). Raises the client's
    LLMUnavailable/LLMError up (the caller decides how to handle a mid-run outage)."""
    system, user, expected = build_triage_prompt(items, canaries=canaries)
    t0 = monotonic()
    result = client.generate(user, model=model, system=system, keep_alive=keep_alive)
    wall_s = max(0.0, monotonic() - t0)
    pb = parse_verdicts(getattr(result, "text", ""), expected)
    canary = check_canaries(pb, canary_expected or {})
    return {
        "parsed": pb,
        "canary": canary,
        "gen_meta": gen_meta_from_result(result),
        "wall_s": wall_s,
        "model": model,
    }


# --------------------------------------------------------------------------- #
# EXPORT-ONLY JSONL writer (never the trusted index).
# --------------------------------------------------------------------------- #
_DB_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def export_triage_jsonl(path, records: list[dict]) -> int:
    """Append ``records`` (a run header and/or batch records) to a JSONL file — the digest
    "digestible by Claude". This is the ONLY write this module performs, and by CONTRACT it is
    a plain log file, NEVER the corpus DB.

    EXPORT-ONLY hardening (the ZETA traversal-guard-every-name→path discipline): the target
    MUST carry a ``.jsonl``/``.json`` suffix and must not be a directory — so a mis-wired
    caller can never append JSONL bytes into the encrypted store
    (``open_omniscience.db`` / its ``-wal``/``-shm``/``-journal`` sidecars / a ``.sqlite`` file
    are all rejected by the suffix allowlist, plus an explicit sidecar refusal for a clear
    error). Returns the number of records written; raises ValueError on a disallowed target."""
    import json
    from pathlib import Path

    p = Path(path)
    if p.suffix.lower() not in (".jsonl", ".json"):
        raise ValueError(
            f"triage export must be a .jsonl/.json log — refusing {p.name!r} (never the corpus DB)."
        )
    low = p.name.lower()
    if low.endswith(_DB_SIDECAR_SUFFIXES) or low.endswith((".db", ".sqlite", ".sqlite3")):
        raise ValueError(f"refusing to write a triage export over a database file: {p.name!r}")
    if p.is_dir():
        raise ValueError(f"triage export path is a directory, not a file: {p}")
    with p.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(records)


# --------------------------------------------------------------------------- #
# Deterministic ARTIFACT proposals — PROPOSE, never auto-apply (the analyze_keyword_log
# discipline). Provenance chain: ai-proposed · claude-verified · maintainer-merged.
# --------------------------------------------------------------------------- #
def _iter_verdicts(parsed: list[ParsedBatch], items_by_term: dict[str, TriageItem]):
    for pb in parsed:
        for term, v in pb.verdicts.items():
            yield term, v, items_by_term.get(term)


def propose_stoplist_additions(
    parsed: list[ParsedBatch], items_by_term: dict[str, TriageItem]
) -> dict:
    """The junk verdicts, grouped PER LANGUAGE, as a scoped-stoplist PROPOSAL (never applied).

    Scoped-by-language additions are collision-free (the stoplist-architecture lesson); an
    unknown-language junk term goes to a '?' bucket the reviewer reads with care. Only
    ``verdict == junk`` terms are proposed; ``unsure`` is deliberately excluded (propose only
    what the model was confident is noise)."""
    by_lang: dict[str, list[str]] = {}
    for term, v, item in _iter_verdicts(parsed, items_by_term):
        if v["verdict"] != "junk":
            continue
        lang = (item.language if item and item.language else "?")
        by_lang.setdefault(lang, [])
        if term not in by_lang[lang]:
            by_lang[lang].append(term)
    return {
        "kind": "scoped_stoplist_additions",
        "provenance": "ai-proposed",  # + claude-verified + maintainer-merged downstream
        "by_language": {k: sorted(v) for k, v in sorted(by_lang.items())},
        "method": "keywords the model verdicted 'junk', grouped by the keyword's stored language.",
        "caveat": (
            "PROPOSED ONLY — never auto-applied. A human verifies a stratified sample before "
            "any scoped-stoplist PR (ai-proposed → claude-verified → maintainer-merged). "
            "Language '?' means the keyword's language is unknown; review those with extra care."
        ),
    }


def propose_kind_overrides(
    parsed: list[ParsedBatch], items_by_term: dict[str, TriageItem]
) -> dict:
    """A kind-override PROPOSAL: content keywords whose model KIND (person/org/place) differs
    from the current entity tagging — the "Organizations tagged as Persons" fix. Only
    ``verdict == content`` and a concrete kind (not 'other') are proposed; never applied."""
    proposals = []
    for term, v, item in _iter_verdicts(parsed, items_by_term):
        if v["verdict"] != "content" or v["kind"] == "other":
            continue
        proposals.append(
            {
                "term": term,
                "language": (item.language if item else None),
                "proposed_kind": v["kind"],
                "currently_tagged_entity": (item.is_entity if item else None),
            }
        )
    proposals.sort(key=lambda p: (p["proposed_kind"], p["term"]))
    return {
        "kind": "kind_overrides",
        "provenance": "ai-proposed",
        "proposals": proposals,
        "method": "content keywords the model assigned a concrete kind (person/org/place).",
        "caveat": (
            "PROPOSED ONLY — never auto-applied; a kind is a labelled assertion, never ground "
            "truth. A human verifies before any override PR (ai-proposed → claude-verified → "
            "maintainer-merged)."
        ),
    }


# --------------------------------------------------------------------------- #
# THE BENCH — roster verification + the metrics, each reported ALONE (no composite).
# --------------------------------------------------------------------------- #
def verify_roster(requested_tags: list[str], installed_tags: list[str]) -> dict:
    """The HARD RULE (§8.3): every bench tag must be verified against the local ``ollama list``.
    An uninstalled tag is REFUSED — never substitute a "close" one (the hallucinated-catalog
    lesson). Returns ``{"ok", "runnable": [...], "missing": [...]}``; the caller aborts the
    bench if ``missing`` is non-empty rather than silently benching a subset."""
    installed = set(installed_tags)
    req = list(dict.fromkeys(requested_tags))  # dedup requested tags, preserve order
    runnable = [t for t in req if t in installed]
    missing = [t for t in req if t not in installed]
    return {
        "ok": not missing,
        "runnable": runnable,
        "missing": missing,
        "method": "each requested tag is matched EXACTLY against `ollama list`; no fuzzy/close match.",
        "caveat": (
            "A missing tag is REFUSED, never substituted — a 'close' tag would benchmark a "
            "different model than named. Install the exact tag or drop it from the roster."
        ),
    }


def valid_verdicts_per_sec(valid: int, wall_s: float) -> float | None:
    return round(valid / wall_s, 4) if (valid > 0 and wall_s > 0) else None


def format_validity_rate(keywords_in: int, verdicts_out: int) -> float | None:
    """Share of the keywords ASKED that came back as a VALID, echo-matched verdict
    (verdicts_out ÷ keywords_in). None when nothing was asked. ``parse_failures`` (extra
    garbage/malformed lines the model emitted) is a DISTINCT format-health signal reported
    on its own — never folded in here (a keyword can be valid AND draw a stray bad line, so
    subtracting parse_failures would double-penalize)."""
    if keywords_in <= 0:
        return None
    return round(verdicts_out / keywords_in, 4)


def pct_unsure(unsure: int, valid: int) -> float | None:
    return round(unsure / valid, 4) if valid > 0 else None


def anchor_accuracy(verdicts: dict[str, dict], anchors: dict[str, dict]) -> dict:
    """Accuracy vs the maintainer-graded anchors — junk precision/recall SEPARATE from kind
    accuracy (each stands alone, no composite). ``anchors`` maps term -> {"verdict","kind"}.

    Junk is scored as a binary detector (positive = verdict 'junk'); kind accuracy is scored
    ONLY over anchors graded 'content' (kind is meaningful there), never blended with junk."""
    j_tp = j_fp = j_fn = 0
    kind_correct = kind_total = 0
    covered = 0
    for term, gold in anchors.items():
        got = verdicts.get(term)
        if got is None:
            # an anchor the model dropped counts against junk RECALL if gold was junk.
            if gold.get("verdict") == "junk":
                j_fn += 1
            continue
        covered += 1
        gold_junk = gold.get("verdict") == "junk"
        pred_junk = got["verdict"] == "junk"
        if pred_junk and gold_junk:
            j_tp += 1
        elif pred_junk and not gold_junk:
            j_fp += 1
        elif not pred_junk and gold_junk:
            j_fn += 1
        if gold.get("verdict") == "content" and gold.get("kind") in KINDS:
            kind_total += 1
            # credit the kind ONLY where the MODEL also called it content — a model that
            # mislabels a content anchor as junk/unsure earns no free kind credit.
            if got["verdict"] == "content" and got["kind"] == gold["kind"]:
                kind_correct += 1
    junk_precision = j_tp / (j_tp + j_fp) if (j_tp + j_fp) else None
    junk_recall = j_tp / (j_tp + j_fn) if (j_tp + j_fn) else None
    return {
        "n_anchors": len(anchors),
        "n_covered": covered,
        "junk_precision": round(junk_precision, 4) if junk_precision is not None else None,
        "junk_recall": round(junk_recall, 4) if junk_recall is not None else None,
        "kind_accuracy": round(kind_correct / kind_total, 4) if kind_total else None,
        "kind_n": kind_total,
        "method": "junk precision/recall (binary detector) reported SEPARATELY from kind accuracy "
        "(over 'content' anchors only). No composite score.",
        "caveat": "Anchors are a MICRO gold set graded once by the maintainer — turns 'models "
        "agree' into 'models are right'; n is small, read each number with its n.",
    }


def pairwise_agreement(model_verdicts: dict[str, dict[str, str]]) -> dict:
    """Inter-model VERDICT agreement over shared terms, per pair (the 21 pairs for 7 models).

    ``model_verdicts`` maps model -> {term: verdict}. Returns per-pair {n, agreement}; a pair
    with no shared terms reports agreement None (never a fabricated 1.0). No composite."""
    pairs = {}
    for a, b in combinations(sorted(model_verdicts), 2):
        va, vb = model_verdicts[a], model_verdicts[b]
        shared = set(va) & set(vb)
        agree = sum(1 for t in shared if va[t] == vb[t])
        pairs[f"{a}|{b}"] = {
            "n": len(shared),
            "agreement": round(agree / len(shared), 4) if shared else None,
        }
    return {
        "pairs": pairs,
        "method": "fraction of SHARED terms where two models give the same verdict.",
        "caveat": "Agreement is not correctness (two models can agree and both be wrong — read it "
        "beside the anchor accuracy). A pair with no shared terms is None, never 1.0.",
    }


# --------------------------------------------------------------------------- #
# The self-test — prove the MECHANISM on a STUB client (no network, no model).
# --------------------------------------------------------------------------- #
class _StubClient:
    """A deterministic stub standing in for OllamaClient.generate — returns a fixed response
    exercising every validation path (a good line, a mangled echo, a hallucinated term, a
    malformed verdict, an unsure, a dropped keyword, and a canary that FAILS)."""

    def __init__(self, text: str):
        self._text = text

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        return type(
            "R",
            (),
            {
                "text": self._text,
                "total_duration": 1_000_000_000,  # 1 s in ns (Ollama's unit)
                "load_duration": 200_000_000,
                "prompt_eval_count": 40,
                "prompt_eval_duration": 100_000_000,
                "eval_count": 12,
                "eval_duration": 700_000_000,
            },
        )()


def run_triage_selftest() -> dict:
    """Prove the parser + echo-back + canary + timing + metrics on a hand-computed fixture.
    Exported so a regression reddens BOTH the in-app self-test and CI (mirrors
    ``run_perception_eval_selftest`` / ``run_ir_eval_selftest``)."""
    items = [
        TriageItem("climate change", language="en", article_count=900, mention_count=3000),
        TriageItem("subscribe now", language="en", article_count=120, mention_count=400),
        TriageItem("World Health Organization", language="en", article_count=300),
        TriageItem("press release", language="en", article_count=80),  # malformed KIND -> missing
        TriageItem("qwertyx", language="en", article_count=5),  # model will drop this one
    ]
    canaries = (TriageItem("cookie banner", language="en"),)  # KNOWN junk
    canary_expected = {"cookie banner": {"verdict": "junk"}}
    # The stub response — exercises EVERY validation path (so the self-test is non-vacuous):
    #   climate change -> content/other (valid)
    #   subscribe now  -> junk/other (valid, FIRST) then content/other (dup -> first-wins keeps junk)
    #   World Health Organization -> content/org (valid, a kind)
    #   "climate chnge ..." -> mangled echo (rejected, parse_failure)
    #   "ghosted term ..." -> hallucinated term (rejected, parse_failure)
    #   "press release :: junk :: notakind" -> MALFORMED KIND (rejected -> press release missing;
    #       a parser that coerced a bad kind to 'other' would store it and fail this)
    #   cookie banner -> content (canary FAILS: expected junk)
    #   (qwertyx omitted -> missing)
    resp = "\n".join(
        [
            "climate change :: content :: other",
            "subscribe now :: junk :: other",
            "subscribe now :: content :: other",  # duplicate — first (junk) must win
            "World Health Organization :: content :: org",
            "climate chnge :: content :: other",
            "ghosted term :: junk :: other",
            "press release :: junk :: notakind",  # malformed kind -> rejected
            "cookie banner :: content :: other",
        ]
    )
    client = _StubClient(resp)
    out = run_triage_batch(
        client,
        items,
        model="stub:test",
        canaries=canaries,
        canary_expected=canary_expected,
        monotonic=iter([10.0, 11.5]).__next__,  # deterministic 1.5 s wall
    )
    pb: ParsedBatch = out["parsed"]
    # anchors: 'subscribe now' is graded JUNK but carries a concrete kind ('org') — a correct
    # anchor_accuracy must NOT count it toward kind accuracy (kind is scored over CONTENT
    # anchors only), so kind_n stays 1 (WHO). 'climate change' kind 'topic' is not in KINDS.
    anchors = {
        "climate change": {"verdict": "content", "kind": "topic"},
        "subscribe now": {"verdict": "junk", "kind": "org"},
        "World Health Organization": {"verdict": "content", "kind": "org"},
    }
    acc = anchor_accuracy(pb.verdicts, anchors)
    rec = batch_record(
        started_at="2026-07-13T00:00:00",
        finished_at="2026-07-13T00:00:02",
        gen_meta=out["gen_meta"],
        pb=pb,
        canary=out["canary"],
        model="stub:test",
    )
    checks = {
        # 5 expected items + 1 canary = 6 distinct keywords_in; 4 valid.
        "keywords_in_6": pb.keywords_in == 6,
        "four_valid_verdicts": pb.verdicts_out == 4,
        # mangled echo + hallucinated term + malformed kind = 3 parse failures.
        "three_parse_failures": pb.parse_failures == 3,
        # MALFORMED-KIND rejection: a coercing parser would store 'press release' -> this fails.
        "malformed_kind_rejected": "press release" in pb.missing,
        # FIRST-wins: the duplicate 'subscribe now' content line must NOT overwrite the junk.
        "duplicate_first_wins": pb.verdicts.get("subscribe now", {}).get("verdict") == "junk",
        "qwertyx_missing": "qwertyx" in pb.missing,
        "no_hallucinated_term": "ghosted term" not in pb.verdicts,
        "canary_failed": out["canary"]["ok"] is False,
        "who_is_org": pb.verdicts.get("World Health Organization", {}).get("kind") == "org",
        "timing_passthrough": rec["total_duration"] == 1_000_000_000 and rec["eval_count"] == 12,
        # throughput = 4 valid / 1.5 s.
        "eta_throughput": (eta_line(100, pb.verdicts_out, out["wall_s"]) or {}).get(
            "throughput_valid_per_s"
        )
        == round(4 / 1.5, 4),
        # junk precision/recall (subscribe now graded junk, model said junk) = 1/1 each.
        "junk_precision_full": acc["junk_precision"] == 1.0,
        "junk_recall_full": acc["junk_recall"] == 1.0,
        # kind accuracy over CONTENT anchors only (WHO) = 1/1, and the junk-graded 'subscribe
        # now' is NOT counted -> kind_n == 1 (a broken content-gate would make it 2).
        "kind_accuracy_full": acc["kind_accuracy"] == 1.0,
        "kind_content_gated": acc["kind_n"] == 1,
        # format validity = 4 valid verdicts / 6 keywords asked (parse_failures reported apart).
        "format_validity": format_validity_rate(pb.keywords_in, pb.verdicts_out) == round(4 / 6, 4),
    }
    return {
        "schema": "oo-keyword-triage-selftest-1",
        "prompt_version": TRIAGE_PROMPT_VERSION,
        "passed": all(checks.values()),
        "checks": checks,
        "note": (
            "Proves the MECHANISM (parser · echo-back · canary · timing pass-through · "
            "metrics) on a deterministic stub — NOT a real model run. The real batch + the "
            "7-model bench are operator-run on the Ollama rig (this box has no models/GPU)."
        ),
    }
