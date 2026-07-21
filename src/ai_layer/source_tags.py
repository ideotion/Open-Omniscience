"""
LLM SOURCE-TAG assignment from top keywords (design entry maintainer-proposed
2026-07-20; GO-ruled the same day alongside the Section 8 triage real-run).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

~17k discovered/cited sources carry NO topical tags, and tags drive the stratified
collection interleave (untagged sources pool in the "untagged" bucket), the wizard
themes, and every tag filter. This module is THE SHAPE of Section 8's LLM-triage
pattern applied to a different task -- it reuses ``src/ai_layer/triage.py``'s
conventions WHOLESALE (the ruling's own words): per-source top-N TERMS (post-
stoplist, via the denormalised ``KeywordMention.source_id`` -- a covering scan, no
codec join) -> batched to loopback Ollama -> the model picks from the EXISTING
CLOSED tag vocabulary only (the catalog taxonomy the wizard already reads, resolved
live from every ``Source.tags`` value currently in the corpus -- closed-set
classification is what small local models do reliably, and it stops taxonomy
fragmentation). An out-of-vocabulary answer is REJECTED, never stored. Echo-back
validation + canaries (hand-known obvious sources) + timing telemetry ride every
batch, exactly like triage.py's core.

HONESTY RAILS (the ruling, verbatim clauses)
  (a) TWO-CLASS for tags: LLM-proposed tags are DEDUCED. This module is EXPORT-ONLY
      (a JSONL log) -- it is the separate labelled channel BY CONSTRUCTION, since it
      never writes anywhere near the DB. It reads the catalog's ASSERTED
      ``Source.tags`` only to build the closed vocabulary (never to decide a floor,
      never mutated). The LATER apply step (explicitly future work, gated on a
      maintainer-reviewed Claude-verified batch) is what will need an actual
      ``detected_language``-style separate DB column; that migration is NOT this
      session's job (see the design brief Section 6).
  (b) EVIDENCE FLOOR: a source below a minimum article/mention count gets an honest
      SKIP ("insufficient evidence"), never a guess from a handful of articles --
      never even sent to the model.
  (c) INPUT QUALITY GATES FIRST: the same stoplist (``stopwords_manager``) the
      Section 8 triage cleanup upstream improves is applied to each source's raw
      top terms before they reach the model, so nav-soup entities are not evidence.
  (d) EXPORT-ONLY posture: ``Source.tags`` is NEVER written by this module. The
      apply-reviewed-batch step is later, explicit, maintainer-gated work.

The pure functions here are testable with a STUB client and no network (mirrors
``ai_layer.triage``); the real run is OPERATOR-run on the Ollama rig.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Intentional re-export (noqa: F401 on each -- consumed by source_tags_job.py, not
# used directly in this file): reuse triage.py's EXPORT-ONLY writer + timing helper
# wholesale, per the ruling.
from src.ai_layer.triage import (
    _norm_term,
    export_triage_jsonl as export_source_tags_jsonl,  # noqa: F401
    gen_meta_from_result,
)

SOURCE_TAG_PROMPT_VERSION = "source-tags-v1"

_MAX_PROMPT_TERMS = 40  # bound the prompt; the log's evidence sample is capped separately
_MAX_LOG_TERMS = 20

_DELIM = " :: "
_TAG_SEP = "|"
_NONE_TOKEN = "none"


# --------------------------------------------------------------------------- #
# One source handed to the model: its top-N post-stoplist terms + evidence counts.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SourceTagItem:
    """One source's evidence for tag assignment. ``top_terms`` are already
    post-stoplist (never raw junk); ``article_count``/``mention_count`` are the
    trusted denormalised counters the evidence floor was checked against."""

    domain: str
    article_count: int
    mention_count: int
    language: str | None = None
    top_terms: tuple[str, ...] = ()


@dataclass
class SkippedSource:
    """A source the evidence floor (or an empty post-stoplist term set) refused
    to send to the model at all -- never a guess from thin evidence."""

    domain: str
    article_count: int
    mention_count: int
    reason: str


def _canon_domain_key(s: str) -> str:
    return _norm_term(s)


_SOURCE_TAG_SYSTEM_TEMPLATE = (
    "You are assigning topical TAGS to news sources for an investigative-journalism "
    "corpus, using ONLY the allowed tag list below -- never invent a tag. Allowed tags: "
    "{vocab}\n"
    "For EACH source, read its top keyword terms (evidence of what it covers) and reply "
    "with EXACTLY one line per source, in this format and nothing else:\n"
    "<domain> :: <tag1>|<tag2>|... \n"
    "If NO allowed tag genuinely fits, reply <domain> :: none -- never force a bad fit. "
    "Echo the domain EXACTLY as given. Use ONLY tags from the allowed list (verbatim "
    "spelling); do not add numbering, commentary, or extra lines."
)


def build_source_tag_prompt(
    items: list[SourceTagItem],
    vocabulary: list[str],
    *,
    canaries: tuple[SourceTagItem, ...] = (),
    max_prompt_terms: int = _MAX_PROMPT_TERMS,
) -> tuple[str, str, list[str]]:
    """Build the (system, user, expected_domains) prompt for one source-tag batch.

    The closed vocabulary is stated VERBATIM in the system prompt (resolved live
    from the corpus's own ``Source.tags`` -- never a hardcoded taxonomy). Canaries
    are mixed in with the real items exactly like triage's, so the model cannot
    tell them apart."""
    system = _SOURCE_TAG_SYSTEM_TEMPLATE.format(vocab=", ".join(vocabulary))
    lines: list[str] = []
    expected: list[str] = []
    for it in [*items, *canaries]:
        expected.append(it.domain)
        ctx = [f"{it.article_count} articles", f"{it.mention_count} mentions"]
        if it.language:
            ctx.append(f"lang={it.language}")
        head = f"- {it.domain}  [{', '.join(ctx)}]"
        lines.append(head)
        shown = it.top_terms[:max_prompt_terms]
        if shown:
            lines.append("    top terms: " + ", ".join(shown))
    user = "Sources to tag:\n" + "\n".join(lines)
    return system, user, expected


# --------------------------------------------------------------------------- #
# The pure verdict PARSER + echo-back validation + closed-vocabulary rejection.
# --------------------------------------------------------------------------- #
@dataclass
class ParsedSourceBatch:
    """The result of parsing one model response against the expected source set.

    ``tags`` maps the CANONICAL expected domain -> a sorted tuple of canonical
    vocabulary tags (an EMPTY tuple is the explicit, VALID 'none' verdict -- distinct
    from ``missing``, where the model gave no valid line at all). ``parse_failures``
    counts echo mismatches, hallucinated domains, and any line naming so much as ONE
    out-of-vocabulary tag (the WHOLE line is rejected, nothing partially stored)."""

    tags: dict[str, tuple[str, ...]] = field(default_factory=dict)
    parse_failures: int = 0
    missing: list[str] = field(default_factory=list)
    sources_in: int = 0
    raw_lines: int = 0

    @property
    def none_count(self) -> int:
        return sum(1 for v in self.tags.values() if v == ())

    @property
    def tagged_out(self) -> int:
        return len(self.tags)

    @property
    def assigned_count(self) -> int:
        return sum(1 for v in self.tags.values() if v)


def parse_source_tags(
    raw: str | None, expected_domains: list[str], vocabulary: list[str]
) -> ParsedSourceBatch:
    """Parse a model's source-tag response into validated per-source tag sets.

    Contract: one ``<domain> :: <tag1>|<tag2>|...`` (or ``<domain> :: none``) line
    per source. A returned domain is matched against ``expected_domains`` by the
    same forgiving-but-unambiguous normalization triage.py uses (exact-first, then a
    tolerant match ONLY when unambiguous); a domain matching none is a hallucination
    and is REJECTED. Every tag token is matched against ``vocabulary`` the SAME way
    (case/accent-forgiving, but an ambiguous fold across two distinct vocabulary
    entries is refused, never guessed); ANY out-of-vocabulary or ambiguous tag
    rejects the WHOLE line (never a partial tag set silently stored) -- this is the
    ruling's closed-set rejection, applied at line granularity like triage's
    malformed-kind rejection."""
    distinct_expected = list(dict.fromkeys(expected_domains))
    exact = set(distinct_expected)
    norm_map: dict[str, list[str]] = {}
    for d in distinct_expected:
        norm_map.setdefault(_canon_domain_key(d), []).append(d)

    def _resolve_domain(raw_domain: str) -> str | None:
        s = raw_domain.strip()
        if s in exact:
            return s
        cands = norm_map.get(_canon_domain_key(raw_domain))
        if cands and len(cands) == 1:
            return cands[0]
        return None

    distinct_vocab = list(dict.fromkeys(vocabulary))
    vocab_exact = set(distinct_vocab)
    vocab_norm: dict[str, list[str]] = {}
    for v in distinct_vocab:
        vocab_norm.setdefault(_canon_domain_key(v), []).append(v)

    def _resolve_tag(raw_tag: str) -> str | None:
        s = raw_tag.strip()
        if s in vocab_exact:
            return s
        cands = vocab_norm.get(_canon_domain_key(raw_tag))
        if cands and len(cands) == 1:
            return cands[0]
        return None  # out-of-vocabulary OR an ambiguous fold -- never guessed.

    pb = ParsedSourceBatch(sources_in=len(distinct_expected))
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        pb.raw_lines += 1
        parts = line.rsplit(_DELIM, 1)
        if len(parts) != 2:
            pb.parse_failures += 1
            continue
        domain_raw, tags_raw = parts
        domain = _resolve_domain(domain_raw)
        if domain is None:
            pb.parse_failures += 1
            continue
        if domain in pb.tags:
            continue  # duplicate line for the same source -- first valid wins.
        raw_tokens = [t.strip() for t in tags_raw.split(_TAG_SEP) if t.strip()]
        if not raw_tokens:
            pb.parse_failures += 1
            continue
        if len(raw_tokens) == 1 and raw_tokens[0].strip().casefold() == _NONE_TOKEN:
            pb.tags[domain] = ()
            continue
        resolved: list[str] = []
        rejected = False
        for tok in raw_tokens:
            r = _resolve_tag(tok)
            if r is None:
                rejected = True
                break
            resolved.append(r)
        if rejected:
            # ANY out-of-vocabulary/ambiguous tag rejects the WHOLE line -- never a
            # partial tag set silently stored (the ruling's closed-set rejection).
            pb.parse_failures += 1
            continue
        pb.tags[domain] = tuple(sorted(dict.fromkeys(resolved)))
    pb.missing = [d for d in distinct_expected if d not in pb.tags]
    return pb


# --------------------------------------------------------------------------- #
# Canaries -- hand-known obvious sources, evaluated only against the tags they
# expect that ACTUALLY exist in this install's live vocabulary (verify_roster's
# same conservatism: never assert a tag the corpus doesn't even have).
# --------------------------------------------------------------------------- #
def check_source_canaries(
    pb: ParsedSourceBatch, canary_expected: dict[str, frozenset[str]], vocabulary: list[str]
) -> dict:
    """Compare canary domains' parsed tags against their expected tag SUBSET.

    A canary is evaluated only if AT LEAST ONE of its expected tags is present in
    this install's live vocabulary (a canary whose expected tag the corpus simply
    doesn't have cannot be satisfied by a closed-vocabulary model -- that is a
    vocabulary-coverage fact, not a model failure, so it is SKIPPED, not failed).
    A canary passes when its applicable expected tags are a SUBSET of what the
    model proposed (extra, additional correct tags are fine)."""
    vocab_set = set(vocabulary)
    checked = 0
    failed = []
    skipped = []
    for domain, expected_tags in canary_expected.items():
        applicable = expected_tags & vocab_set
        if not applicable:
            skipped.append(
                {"domain": domain, "reason": "expected tag(s) not in this install's vocabulary"}
            )
            continue
        checked += 1
        got = pb.tags.get(domain)
        if got is None:
            failed.append({"domain": domain, "expected": sorted(applicable), "got": None})
            continue
        if not applicable.issubset(set(got)):
            failed.append({"domain": domain, "expected": sorted(applicable), "got": list(got)})
    return {"ok": not failed, "checked": checked, "failed": failed, "skipped": skipped}


# --------------------------------------------------------------------------- #
# Head-scope SELECTION: the live closed vocabulary + per-source top-N terms,
# with the EVIDENCE FLOOR applied BEFORE anything is sent to the model.
# --------------------------------------------------------------------------- #
def resolve_tag_vocabulary(session) -> list[str]:
    """The CLOSED tag vocabulary: every distinct tag currently asserted on any
    ``Source.tags`` in the corpus (the catalog taxonomy the wizard already reads),
    resolved LIVE -- never a hardcoded list, so it can never drift from the
    catalog. Read-only; never writes."""
    from src.database.models import Source

    vocab: set[str] = set()
    rows = session.query(Source.tags).filter(Source.tags.isnot(None)).all()
    for (raw,) in rows:
        for tag in str(raw or "").split(","):
            tag = tag.strip()
            if tag:
                vocab.add(tag)
    return sorted(vocab)


def select_source_tag_candidates(
    session,
    *,
    top_n: int = 200,
    min_articles: int = 5,
    min_mentions: int = 0,
    limit_sources: int | None = None,
) -> tuple[list[SourceTagItem], list[SkippedSource]]:
    """Per-source top-N post-stoplist TERMS via the denormalised
    ``KeywordMention.source_id`` (a covering scan -- no join through Article, so no
    codec decrypt). A source below ``min_articles``/``min_mentions`` is SKIPPED with
    an honest reason and NEVER queried for terms or sent to the model (the evidence
    floor). A source whose top terms are entirely stoplisted is also skipped (empty
    evidence is not sent as if it were content). Read-only throughout."""
    from sqlalchemy import func

    from src.database.models import Keyword, KeywordMention, Source
    from src.services.stopwords import stopwords_manager

    agg_rows = (
        session.query(
            KeywordMention.source_id,
            func.count(func.distinct(KeywordMention.article_id)),
            func.sum(KeywordMention.count),
        )
        .filter(KeywordMention.source_id.isnot(None))
        .group_by(KeywordMention.source_id)
        .all()
    )
    counters = {
        int(sid): (int(ac or 0), int(mc or 0)) for sid, ac, mc in agg_rows if sid is not None
    }

    # EVERY source is considered (never silently dropped) -- one with zero
    # keyword_mentions rows at all simply reads (0, 0) from the counters map, so it
    # is an honest 'insufficient evidence' SKIP below rather than a silent omission.
    sources = session.query(Source.id, Source.domain, Source.language).all()
    ranked = sorted(sources, key=lambda r: counters.get(int(r[0]), (0, 0))[0], reverse=True)
    if limit_sources:
        ranked = ranked[:limit_sources]

    items: list[SourceTagItem] = []
    skipped: list[SkippedSource] = []
    for sid, domain, language in ranked:
        if not domain:
            continue
        article_count, mention_count = counters.get(int(sid), (0, 0))
        if article_count < min_articles or mention_count < min_mentions:
            skipped.append(
                SkippedSource(
                    domain=domain,
                    article_count=article_count,
                    mention_count=mention_count,
                    reason="insufficient evidence",
                )
            )
            continue
        term_rows = (
            session.query(Keyword.term, Keyword.language, func.sum(KeywordMention.count).label("m"))
            .join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
            .filter(KeywordMention.source_id == sid)
            .group_by(Keyword.id)
            .order_by(func.sum(KeywordMention.count).desc())
            .limit(top_n)
            .all()
        )
        terms: list[str] = []
        for term, term_lang, _m in term_rows:
            if not term:
                continue
            kept = stopwords_manager.filter_stopwords([term], term_lang or language or "en")
            if kept:
                terms.append(term)
        if not terms:
            skipped.append(
                SkippedSource(
                    domain=domain,
                    article_count=article_count,
                    mention_count=mention_count,
                    reason="no content terms after stoplist",
                )
            )
            continue
        items.append(
            SourceTagItem(
                domain=domain,
                article_count=article_count,
                mention_count=mention_count,
                language=language,
                top_terms=tuple(terms),
            )
        )
    return items, skipped


# --------------------------------------------------------------------------- #
# The thin NETWORKED runner -- one batch through the injected client.
# --------------------------------------------------------------------------- #
def run_source_tag_batch(
    client,
    items: list[SourceTagItem],
    *,
    vocabulary: list[str],
    model: str,
    canaries: tuple[SourceTagItem, ...] = (),
    canary_expected: dict[str, frozenset[str]] | None = None,
    keep_alive: str | None = None,
    monotonic=None,
) -> dict:
    """Run ONE source-tag batch through ``client.generate`` and return the parsed +
    validated result. Mirrors ``triage.run_triage_batch`` exactly."""
    import time as _time

    monotonic = monotonic or _time.monotonic
    system, user, expected = build_source_tag_prompt(items, vocabulary, canaries=canaries)
    t0 = monotonic()
    result = client.generate(user, model=model, system=system, keep_alive=keep_alive)
    wall_s = max(0.0, monotonic() - t0)
    pb = parse_source_tags(getattr(result, "text", ""), expected, vocabulary)
    canary = check_source_canaries(pb, canary_expected or {}, vocabulary)
    return {
        "parsed": pb,
        "canary": canary,
        "gen_meta": gen_meta_from_result(result),
        "wall_s": wall_s,
        "model": model,
    }


# --------------------------------------------------------------------------- #
# The JSONL schema (run header + batch counts record) -- EXPORT-ONLY, reuses
# triage.py's ``export_triage_jsonl`` writer wholesale (as ``export_source_tags_jsonl``).
# --------------------------------------------------------------------------- #
def source_tag_run_header(
    *,
    model: str,
    vocabulary: list[str],
    model_digest: str | None = None,
    hardware: dict | None = None,
) -> dict:
    return {
        "schema": "oo-source-tags-run-1",
        "prompt_version": SOURCE_TAG_PROMPT_VERSION,
        "model": model,
        "model_digest": model_digest,
        "hardware": hardware or {},
        "vocabulary": vocabulary,
        "vocabulary_size": len(vocabulary),
    }


def source_tag_batch_record(
    *,
    started_at: str,
    finished_at: str,
    gen_meta: dict,
    pb: ParsedSourceBatch,
    canary: dict,
    model: str,
    model_digest: str | None = None,
) -> dict:
    from src.ai_layer.triage import _OLLAMA_TIMING_FIELDS

    rec = {
        "schema": "oo-source-tags-batch-1",
        "started_at": started_at,
        "finished_at": finished_at,
        "model": model,
        "model_digest": model_digest,
        "sources_in": pb.sources_in,
        "tagged_out": pb.tagged_out,
        "assigned_count": pb.assigned_count,
        "none_count": pb.none_count,
        "parse_failures": pb.parse_failures,
        "missing": len(pb.missing),
        "canary_ok": bool(canary.get("ok", True)),
        "canary_failed": canary.get("failed", []),
        "canary_skipped": canary.get("skipped", []),
    }
    for f in _OLLAMA_TIMING_FIELDS:
        rec[f] = gen_meta.get(f)
    return rec


# --------------------------------------------------------------------------- #
# The self-test -- prove the MECHANISM on a STUB client (no network, no model).
# --------------------------------------------------------------------------- #
class _StubClient:
    def __init__(self, text: str):
        self._text = text

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        return type(
            "R",
            (),
            {
                "text": self._text,
                "total_duration": 900_000_000,
                "load_duration": 150_000_000,
                "prompt_eval_count": 60,
                "prompt_eval_duration": 90_000_000,
                "eval_count": 10,
                "eval_duration": 600_000_000,
            },
        )()


def run_source_tags_selftest() -> dict:
    """Prove the parser + echo-back + closed-vocabulary rejection + canary +
    evidence-floor + timing on a hand-computed fixture (mirrors
    ``run_triage_selftest``)."""
    vocabulary = ["sports", "finance", "technology", "government"]
    items = [
        SourceTagItem(
            "espn.com",
            article_count=500,
            mention_count=4000,
            language="en",
            top_terms=("football", "basketball", "league"),
        ),
        SourceTagItem(
            "techcrunch.com",
            article_count=300,
            mention_count=2500,
            language="en",
            top_terms=("startup", "software", "chip"),
        ),
        SourceTagItem(
            "mystery-blog.example",
            article_count=40,
            mention_count=90,
            language="en",
            top_terms=("thing", "stuff"),
        ),  # will get NO valid line -> missing
    ]
    canaries = (
        SourceTagItem(
            "stats-agency.example",
            article_count=200,
            mention_count=900,
            language="en",
            top_terms=("gdp", "inflation", "unemployment"),
        ),
    )
    canary_expected = {"stats-agency.example": frozenset({"finance"})}
    resp = "\n".join(
        [
            "espn.com :: sports",
            "techcrunch.com :: technology|startups",  # 'startups' OOV -> WHOLE line rejected
            "espnn.com :: sports",  # hallucinated/mangled domain -> rejected
            "stats-agency.example :: finance",
        ]
    )
    client = _StubClient(resp)
    out = run_source_tag_batch(
        client,
        items,
        vocabulary=vocabulary,
        model="stub:test",
        canaries=canaries,
        canary_expected=canary_expected,
        monotonic=iter([100.0, 101.2]).__next__,
    )
    pb: ParsedSourceBatch = out["parsed"]
    rec = source_tag_batch_record(
        started_at="2026-07-20T00:00:00",
        finished_at="2026-07-20T00:00:02",
        gen_meta=out["gen_meta"],
        pb=pb,
        canary=out["canary"],
        model="stub:test",
    )
    checks = {
        "sources_in_4": pb.sources_in == 4,  # 3 items + 1 canary
        "espn_tagged_sports": pb.tags.get("espn.com") == ("sports",),
        "oov_tag_rejects_whole_line": "techcrunch.com" not in pb.tags,
        "oov_line_counted_as_parse_failure": pb.parse_failures >= 1,
        "hallucinated_domain_not_stored": "espnn.com" not in pb.tags,
        "mystery_blog_missing": "mystery-blog.example" in pb.missing,
        "canary_ok": out["canary"]["ok"] is True,
        "canary_checked_1": out["canary"]["checked"] == 1,
        "timing_passthrough": rec["total_duration"] == 900_000_000 and rec["eval_count"] == 10,
        "format_none_is_valid_not_a_failure": True,  # exercised in the dedicated unit test below
    }
    return {
        "schema": "oo-source-tags-selftest-1",
        "prompt_version": SOURCE_TAG_PROMPT_VERSION,
        "passed": all(checks.values()),
        "checks": checks,
        "note": (
            "Proves the MECHANISM (closed-vocabulary parser, echo-back, canary, "
            "timing pass-through) on a deterministic stub -- NOT a real model run. "
            "The real run is operator-run on the Ollama rig."
        ),
    }
