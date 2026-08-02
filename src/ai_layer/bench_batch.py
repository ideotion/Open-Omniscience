"""The FROZEN bench inputs — the constant every benched model sees (ruling 14).

A comparative bench is only a comparison if every model answered the SAME
questions. Selecting a fresh keyword batch per model would make the numbers look
comparable while measuring different work, so the batch is built ONCE, persisted
as a dated artifact, and every run reads it back. Each bench report carries the
batch's DIGEST, so two reports computed over different inputs can never be
silently read side by side — :func:`src.ai_layer.model_bench.run_model_bench`
refuses to resume a run whose digest moved.

Three frozen inputs live here:

* **keywords** — a stratified sample (language × head/tail article spread) for the
  triage task. Stratification is the point: the head of a 3 M-keyword index is
  dominated by a few languages, and a bench that only asked about those would
  report a multilingual model's competence from a monolingual sample.
* **source_tag_vocabulary + sources** — the closed tag vocabulary and the source
  evidence for the tag-assignment task, frozen for the same reason.
* the langdetect and perception tasks reuse the already-reviewed gold sets in
  :mod:`src.analytics.perception_eval`, so nothing is frozen for them here.

VALIDATION IS STRICT AT THE BUILD LAYER, deliberately: a builder that coerces
(``int(2.9)``, ``bool`` as a count) hands a downstream "single loud validator" a
value that already looks clean. A malformed row is REFUSED loudly here, never
repaired.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from datetime import datetime
from pathlib import Path

FROZEN_BATCH_SCHEMA = "oo-bench-frozen-batch-1"
BENCH_ANCHORS_SCHEMA = "oo-bench-anchors-1"

#: The ruled batch size (~400-500 keywords): large enough for the per-language
#: strata to carry a readable n, small enough that seven models × two backends is
#: an evening rather than a week.
DEFAULT_TARGET_KEYWORDS = 450
#: Half the per-language quota comes from the HEAD (highest article spread, where
#: the analytics actually surface), half from the tail (where junk concentrates).
#: A bench drawn only from the head would flatter every model.
DEFAULT_HEAD_SHARE = 0.5
DEFAULT_SOURCE_SAMPLE = 20
#: A grading sitting the maintainer will actually finish (the IR gold-set lesson).
DEFAULT_ANCHOR_SAMPLE = 50

_BATCH_FILENAME = "frozen-batch.json"
_ANCHORS_FILENAME = "bench-anchors.json"


class BenchArtifactError(Exception):
    """A frozen artifact is malformed, absent, or inconsistent. Always loud: a bench
    that silently proceeded on a repaired batch would report a comparison it did not
    make."""


def bench_dir() -> Path:
    """Where frozen inputs and bench reports live — its own archive, not the
    triage run-log directory: these are INPUTS reused across runs, and mixing them
    with dated run logs invites a glob that eats one or the other."""
    from src.paths import data_dir

    d = data_dir() / "bench"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
#  Strict field validation.
# --------------------------------------------------------------------------- #
def _req_str(row: dict, key: str, where: str) -> str:
    v = row.get(key)
    if not isinstance(v, str) or not v.strip():
        raise BenchArtifactError(f"{where}: {key!r} must be a non-empty string, got {v!r}")
    return v.strip()


def _opt_str(row: dict, key: str, where: str) -> str | None:
    v = row.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise BenchArtifactError(f"{where}: {key!r} must be a string or absent, got {v!r}")
    return v.strip() or None


def _count(row: dict, key: str, where: str) -> int:
    """A count must be a real int. ``True`` is an ``int`` in Python and 2.9 truncates
    to 2 — both would land a wrong number that looks perfectly valid downstream."""
    v = row.get(key, 0)
    if v is None:
        return 0
    if isinstance(v, bool) or not isinstance(v, int):
        raise BenchArtifactError(f"{where}: {key!r} must be an int, got {v!r}")
    if v < 0:
        raise BenchArtifactError(f"{where}: {key!r} must not be negative, got {v!r}")
    return v


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).strip().casefold()
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


# --------------------------------------------------------------------------- #
#  Stratification (pure).
# --------------------------------------------------------------------------- #
def stratify_keywords(
    rows: list[dict],
    *,
    target_size: int = DEFAULT_TARGET_KEYWORDS,
    head_share: float = DEFAULT_HEAD_SHARE,
) -> tuple[list[dict], list[dict]]:
    """Pick ``target_size`` keywords, fairly across languages and across the spread.

    Languages get EQUAL quotas rather than proportional ones — proportional shares
    would reproduce the corpus's own language skew inside the bench and leave the
    smaller languages with an n too small to read, which is precisely the question a
    multilingual roster is being asked. A language that cannot fill its quota gives
    the remainder back to the others, so the batch still reaches ``target_size``
    whenever the corpus can supply it (and falls SHORT honestly when it cannot —
    never padded by duplicating).

    Deterministic: same input, same batch. Returns ``(selected, strata)`` where
    ``strata`` reports what each language actually contributed, head and tail apart.
    """
    if target_size <= 0:
        return [], []
    by_lang: dict[str, list[dict]] = {}
    for r in rows:
        by_lang.setdefault(r.get("language") or "unknown", []).append(r)
    for lang in by_lang:
        # Deterministic total order: spread, then mentions, then the term itself.
        by_lang[lang].sort(
            key=lambda r: (-int(r.get("article_count") or 0), -int(r.get("mention_count") or 0), r["term"])
        )

    langs = sorted(by_lang)
    quota = {lang: 0 for lang in langs}
    remaining = target_size
    # Round-robin the quota one slot at a time: exact, and a language that runs out
    # simply stops being offered slots, so its remainder flows to the others.
    capacity = {lang: len(by_lang[lang]) for lang in langs}
    while remaining > 0 and any(quota[lang] < capacity[lang] for lang in langs):
        for lang in langs:
            if remaining <= 0:
                break
            if quota[lang] < capacity[lang]:
                quota[lang] += 1
                remaining -= 1

    selected: list[dict] = []
    strata: list[dict] = []
    for lang in langs:
        n = quota[lang]
        if n <= 0:
            continue
        pool = by_lang[lang]
        n_head = min(len(pool), max(1, round(n * head_share)) if n > 1 else n)
        head = pool[:n_head]
        tail_pool = pool[n_head:]
        n_tail = n - len(head)
        if n_tail > 0 and tail_pool:
            # Evenly spaced across the tail rather than its bottom: the tail is not
            # uniformly junk, and sampling only its end would measure a different
            # question than "how does this model do on low-spread keywords".
            step = max(1, len(tail_pool) // n_tail)
            tail = [tail_pool[i] for i in range(0, len(tail_pool), step)][:n_tail]
        else:
            tail = []
        picked = head + tail
        selected.extend(picked)
        strata.append(
            {
                "language": lang,
                "n": len(picked),
                "n_head": len(head),
                "n_tail": len(tail),
                "available": len(pool),
            }
        )
    return selected, strata


# --------------------------------------------------------------------------- #
#  Building the frozen batch.
# --------------------------------------------------------------------------- #
def batch_digest(payload: dict) -> str:
    """A content digest over exactly the fields that define the QUESTIONS asked.

    Deliberately excludes ``built_at`` and the strata report: rebuilding the same
    selection must produce the same digest, or the resume guard would refuse a run
    whose inputs never changed.
    """
    material = {
        "keywords": [[k["term"], k.get("language")] for k in payload.get("keywords", [])],
        "sources": [s["domain"] for s in payload.get("sources", [])],
        "vocabulary": list(payload.get("source_tag_vocabulary", [])),
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_frozen_batch(
    *,
    keywords: list[dict],
    sources: list[dict] | None = None,
    source_tag_vocabulary: list[str] | None = None,
    target_size: int = DEFAULT_TARGET_KEYWORDS,
    head_share: float = DEFAULT_HEAD_SHARE,
    now=None,
) -> dict:
    """Validate, stratify and assemble the frozen batch. Pure — the DB read lives in
    :func:`collect_frozen_inputs`, so the assembly is testable without a corpus."""
    clean: list[dict] = []
    seen: set[str] = set()
    for i, row in enumerate(keywords):
        where = f"keywords[{i}]"
        term = _req_str(row, "term", where)
        if term in seen:
            continue  # a duplicate term is one question, not two
        seen.add(term)
        clean.append(
            {
                "term": term,
                "language": _opt_str(row, "language", where),
                "article_count": _count(row, "article_count", where),
                "mention_count": _count(row, "mention_count", where),
            }
        )
    selected, strata = stratify_keywords(clean, target_size=target_size, head_share=head_share)

    # Terms that fold to the same normalized key can only be matched by an EXACT
    # echo — the triage parser refuses to guess between them. That is correct, and
    # it is also a fact about this batch a reader of the numbers should know.
    folded: dict[str, list[str]] = {}
    for k in selected:
        folded.setdefault(_norm(k["term"]), []).append(k["term"])
    collisions = sorted(
        (sorted(group) for group in folded.values() if len(group) > 1), key=lambda g: g[0]
    )

    clean_sources: list[dict] = []
    for i, row in enumerate(sources or []):
        where = f"sources[{i}]"
        clean_sources.append(
            {
                "domain": _req_str(row, "domain", where),
                "language": _opt_str(row, "language", where),
                "article_count": _count(row, "article_count", where),
                "mention_count": _count(row, "mention_count", where),
                "top_terms": [
                    t.strip()
                    for t in (row.get("top_terms") or [])
                    if isinstance(t, str) and t.strip()
                ],
            }
        )

    vocab = sorted({v.strip() for v in (source_tag_vocabulary or []) if isinstance(v, str) and v.strip()})
    stamp = (now or datetime.now)()
    payload = {
        "schema": FROZEN_BATCH_SCHEMA,
        "built_at": stamp.isoformat(timespec="seconds"),
        "keywords": selected,
        "keyword_strata": strata,
        "sources": clean_sources,
        "source_tag_vocabulary": vocab,
        "normalized_collisions": collisions,
        "requested_size": target_size,
        "method": (
            "Keywords are sampled with EQUAL per-language quotas (a language that cannot "
            "fill its quota returns the remainder), and within a language half from the "
            "highest article spread and half evenly spaced across the rest. Deterministic: "
            "the same corpus rows produce the same batch."
        ),
        "caveat": (
            "This is a SAMPLE of the index, not the index. Per-language numbers computed "
            "over it carry that stratum's n and must be read with it. Terms that differ "
            "only by case or accents are listed in 'normalized_collisions': they can only "
            "be matched by an exact echo, so a model that reformats them is scored as "
            "having dropped them — which is the honest reading, not a parser fault."
        ),
    }
    payload["digest"] = batch_digest(payload)
    payload["n_keywords"] = len(selected)
    payload["n_sources"] = len(clean_sources)
    return payload


def collect_frozen_inputs(
    session,
    *,
    scan_limit: int = 20000,
    source_sample: int = DEFAULT_SOURCE_SAMPLE,
    target_size: int = DEFAULT_TARGET_KEYWORDS,
    head_share: float = DEFAULT_HEAD_SHARE,
) -> dict:
    """Read the corpus once and build the frozen batch. Read-only throughout: the
    keyword scan is counter-only (no mention→article join, so no article decrypt),
    and the source evidence reuses the existing bounded selector."""
    from src.ai_layer.source_tags import resolve_tag_vocabulary, select_source_tag_candidates
    from src.database.models import Keyword

    rows = (
        session.query(
            Keyword.term, Keyword.language, Keyword.mention_count, Keyword.article_count
        )
        .filter(Keyword.article_count >= 1)
        .order_by(Keyword.article_count.desc(), Keyword.mention_count.desc(), Keyword.id.asc())
        .limit(max(1, scan_limit))
        .all()
    )
    keywords = [
        {
            "term": r[0],
            "language": r[1],
            "mention_count": int(r[2] or 0),
            "article_count": int(r[3] or 0),
        }
        for r in rows
        if r[0]
    ]
    items, _skipped, _cursor = select_source_tag_candidates(
        session, limit_sources=max(1, source_sample)
    )
    sources = [
        {
            "domain": it.domain,
            "language": it.language,
            "article_count": it.article_count,
            "mention_count": it.mention_count,
            "top_terms": list(it.top_terms),
        }
        for it in items
    ]
    return build_frozen_batch(
        keywords=keywords,
        sources=sources,
        source_tag_vocabulary=resolve_tag_vocabulary(session),
        target_size=target_size,
        head_share=head_share,
    )


# --------------------------------------------------------------------------- #
#  Anchors — the ~50 maintainer-graded keywords (graded once, reused forever).
# --------------------------------------------------------------------------- #
def anchor_candidates(batch: dict, n: int = DEFAULT_ANCHOR_SAMPLE) -> list[dict]:
    """Terms to put in front of the maintainer for grading, drawn FROM the frozen
    batch (so every graded anchor is one the models are actually asked about — an
    anchor outside the batch would score nothing). Evenly spaced across the batch so
    the sitting covers head and tail, not the first fifty rows."""
    kws = batch.get("keywords") or []
    if not kws or n <= 0:
        return []
    if n >= len(kws):
        return list(kws)
    step = len(kws) / n
    return [kws[int(i * step)] for i in range(n)]


def build_anchors(rows: list[dict]) -> dict:
    """Validate a grading sitting into the anchors artifact.

    Strict: an unknown verdict/kind is REFUSED rather than coerced to a near value,
    and a duplicate term is refused rather than letting the later grade clobber the
    earlier one silently. A ``content`` grade without a kind is allowed (kind
    accuracy simply has one fewer case) — an INVENTED kind would be worse.
    """
    from src.ai_layer.triage import KINDS, VERDICTS

    out: dict[str, dict] = {}
    for i, row in enumerate(rows):
        where = f"anchors[{i}]"
        term = _req_str(row, "term", where)
        verdict = _req_str(row, "verdict", where)
        if verdict not in VERDICTS:
            raise BenchArtifactError(f"{where}: verdict {verdict!r} is not one of {sorted(VERDICTS)}")
        kind = _opt_str(row, "kind", where)
        if kind is not None and kind not in KINDS:
            raise BenchArtifactError(f"{where}: kind {kind!r} is not one of {sorted(KINDS)}")
        if term in out:
            raise BenchArtifactError(
                f"{where}: {term!r} is graded twice — resolve the conflict rather than "
                "letting one grade silently win."
            )
        entry: dict = {"verdict": verdict}
        if kind:
            entry["kind"] = kind
        out[term] = entry
    return {
        "schema": BENCH_ANCHORS_SCHEMA,
        # "built_at", not "graded_at": the no-composite key-walkers ban the substring
        # "grade" (the same reason "degraded" is never used as a key here).
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "n": len(out),
        "anchors": out,
        "method": "Hand-graded by the maintainer, once, and reused across every model and run.",
        "caveat": (
            "A MICRO gold set: it turns 'the models agree' into 'the models are right', but "
            "n is small — read junk precision/recall and kind accuracy each with their own n."
        ),
    }


# --------------------------------------------------------------------------- #
#  Persistence (atomic; strict on read).
# --------------------------------------------------------------------------- #
def _write_json(path: Path, payload: dict) -> Path:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        # Never leave a validated .tmp orphaned next to the real artifact — a future
        # reader would have no way to tell it apart from a complete one.
        tmp.unlink(missing_ok=True)
        raise
    return path


def save_frozen_batch(payload: dict, *, path: Path | None = None) -> Path:
    if payload.get("schema") != FROZEN_BATCH_SCHEMA:
        raise BenchArtifactError(f"refusing to save a non-batch payload: {payload.get('schema')!r}")
    return _write_json(path or (bench_dir() / _BATCH_FILENAME), payload)


def load_frozen_batch(*, path: Path | None = None) -> dict:
    p = path or (bench_dir() / _BATCH_FILENAME)
    if not p.exists():
        raise BenchArtifactError(
            "no frozen bench batch exists yet — build one first "
            "(POST /api/diagnostics/model-bench/batch). Selecting a fresh batch per model "
            "would make the numbers look comparable while measuring different work."
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise BenchArtifactError(f"the frozen batch at {p} is unreadable: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != FROZEN_BATCH_SCHEMA:
        raise BenchArtifactError(f"{p} is not a {FROZEN_BATCH_SCHEMA} artifact")
    if not data.get("keywords"):
        raise BenchArtifactError(f"{p} carries no keywords — rebuild it")
    recomputed = batch_digest(data)
    if data.get("digest") and data["digest"] != recomputed:
        raise BenchArtifactError(
            f"{p} has been edited since it was frozen (digest {data['digest']} != {recomputed}); "
            "rebuild it rather than benching against an input whose provenance is unclear."
        )
    data.setdefault("digest", recomputed)
    return data


def save_anchors(payload: dict, *, path: Path | None = None) -> Path:
    if payload.get("schema") != BENCH_ANCHORS_SCHEMA:
        raise BenchArtifactError(f"refusing to save a non-anchors payload: {payload.get('schema')!r}")
    return _write_json(path or (bench_dir() / _ANCHORS_FILENAME), payload)


def load_anchors(*, path: Path | None = None) -> dict | None:
    """The graded anchors, or ``None`` when the sitting has never happened.

    ``None`` is an honest absence, not a failure: the bench still reports every other
    metric and states that anchor accuracy is unmeasured (which is what it is).
    """
    p = path or (bench_dir() / _ANCHORS_FILENAME)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise BenchArtifactError(f"the anchors file at {p} is unreadable: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != BENCH_ANCHORS_SCHEMA:
        raise BenchArtifactError(f"{p} is not a {BENCH_ANCHORS_SCHEMA} artifact")
    return data


__all__ = [
    "BENCH_ANCHORS_SCHEMA",
    "BenchArtifactError",
    "DEFAULT_ANCHOR_SAMPLE",
    "DEFAULT_TARGET_KEYWORDS",
    "FROZEN_BATCH_SCHEMA",
    "anchor_candidates",
    "batch_digest",
    "bench_dir",
    "build_anchors",
    "build_frozen_batch",
    "collect_frozen_inputs",
    "load_anchors",
    "load_frozen_batch",
    "save_anchors",
    "save_frozen_batch",
    "stratify_keywords",
]
