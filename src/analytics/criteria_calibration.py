"""
Criteria-calibration diagnostic (S3.1, 2026-07-23 field-feedback workflow) -- TEMPORARY.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's own answer to "how do we decide what to quarantine?" (A4): an ITERATIVE
loop -- export the top disregarded/would-be-disregarded specimens under the CURRENT
extraction-validity criteria, review them by hand, adjust the criteria, re-export -- the
same propose->review->apply discipline this project already uses for stoplists. This
module is a REPORT over the existing detectors (:func:`src.analytics.non_article_scan.
scan_non_article_candidates` + :mod:`src.services.prose_gate`), never new judging: it does
NOT introduce any new rule, threshold, or verdict of its own.

Bounded by construction: the URL-shape half of the underlying scan never decrypts content
(id/url/word_count only); the prose-gate half decrypts a bounded, resumable batch
(``prose_gate_limit``, default 2000, chunked via ``prose_gate_after_id`` -- never a whole-
corpus decrypt in one call); and the per-article DETAIL fetch below is capped at ``top_n``
(default 100) article rows -- a genuinely small, calibration-sized decrypt, not a corpus
sweep. "TEMPORARY" per the brief: this diagnostic exists to calibrate the criteria, not to
run forever as a standing feature.

``CRITERIA_VERSION`` is the version stamp this report's underlying rules represent today --
bump it whenever ``classify_non_article``'s rules or ``prose_gate``'s thresholds change, so
a quarantine stamp (S3.2, once built) can record exactly which criteria generation flagged
it.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)

SCHEMA = "oo-criteria-calibration-1"
# v2 (2026-08-23): `classify_non_article` gained the query-string item-id veto, so the
# homepage and section-landing rules no longer fire on `/news/?articleid=2504`. The stamp
# is what tells a future reader WHICH generation flagged a quarantined row, so a rule
# change that left it at v1 would make v1 mean two different detectors — and the stamp is
# the reversibility story. Measured on the 2026-08-23 field corpus: the drop path went
# from 12 specimens to 8, and the 4 it stopped flagging had function-word densities of
# 0.28-0.37 (prose), against 0.0 for all 8 it kept.
CRITERIA_VERSION = "nav-soup-v2"
_DEFAULT_TOP_N = 100
_DEFAULT_PROSE_GATE_LIMIT = 2000

# --------------------------------------------------------------------------- #
#  The resume cursor
# --------------------------------------------------------------------------- #
# WHY THIS EXISTS. The prose-gate arm is resumable BY DESIGN (``prose_gate_after_id``) and
# was, in practice, unable to finish: the all-diagnostics bundle called it with
# ``after_id=0, limit=500`` hardcoded, so every bundle re-measured the same lowest-id 500
# articles, ``done`` could never become true on any corpus larger than 500, and both
# 2026-08-23 field reports stopped at ``last_id: 695`` having flagged 0. Nothing was
# mislabelled -- the per-batch denominator was honest throughout -- but "resumable" reads
# as "will finish", and it would not have. An evidence arm that cannot reach the end of its
# population is decorative, and 0.3 gate row 5's Tier B had no evidence because of it.
#
# So the cursor persists. It is deliberately NOT part of ``calibration_report``'s default
# behaviour: a caller that passes ``prose_gate_after_id`` by hand still gets exactly the
# batch it asked for, and only ``resume=True`` reads and advances this file.
_CURSOR_FILE = "criteria_calibration_cursor.json"
# The running set of flagged ids kept across batches, bounded. A cursor file is a
# convenience, not an archive: the ids exist in the corpus, and a file that grows with the
# flagged population would be an instrument that becomes a load source (2026-08-06).
_CURSOR_SAMPLE_CAP = 200


def _cursor_path():
    from src.paths import data_dir

    return data_dir() / _CURSOR_FILE


def _read_cursors() -> dict[str, Any]:
    """Every scope's cursor, or an empty dict. Never raises: a missing, unreadable or
    corrupt cursor means "start from the beginning", which costs a re-measurement and is
    always safe -- where raising would take the whole report down with it."""
    try:
        raw = _cursor_path().read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        _LOG.warning("criteria-calibration cursor is unreadable; starting from the beginning")
        return {}
    return data if isinstance(data, dict) else {}


def load_cursor(scope: str, *, criteria_version: str | None = None) -> dict[str, Any] | None:
    """This scope's cursor, or None when there is nothing to resume from.

    A cursor recorded under a DIFFERENT criteria version is not continued: it is returned
    carrying only a ``reset_reason``, so the caller starts the scope again and the report
    can say why. The batches it summed were judged by a different detector generation, and
    adding this run's flagged count to them would produce a total no single detector ever
    produced -- the same reason a quarantine stamp records its criteria version, and the
    same shape as the corpus-epoch guard that forces a full rollup rebuild.
    """
    want = criteria_version or CRITERIA_VERSION
    rec = _read_cursors().get(scope)
    if not isinstance(rec, dict):
        return None
    if rec.get("criteria_version") != want:
        return {
            "reset_reason": (
                f"criteria version changed ({rec.get('criteria_version')!r} -> {want!r}); the "
                "earlier batches were judged by a different detector generation and are not "
                "summable with this one"
            )
        }
    return rec


def advance_cursor(
    scope: str,
    *,
    criteria_version: str,
    prose_gate: dict[str, Any],
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fold one batch into this scope's cursor and persist it. Returns the new record.

    Best-effort on the WRITE only: a failed write means the next run re-measures this
    batch, which is a cost, not a corruption -- and ``persisted`` says which happened, so a
    reader is never left to infer it. The returned record is what the report publishes
    either way, so the totals a run produced are visible even when they could not be saved.
    """
    now = datetime.now(UTC).isoformat(timespec="seconds")
    resumed = prior if prior and "reset_reason" not in prior else None
    ids = list(resumed.get("flagged_ids", [])) if resumed else []
    for aid in prose_gate.get("sample_ids", []):
        if len(ids) >= _CURSOR_SAMPLE_CAP:
            break
        if int(aid) not in ids:
            ids.append(int(aid))
    rec: dict[str, Any] = {
        "scope": scope,
        "criteria_version": criteria_version,
        "after_id": int(prose_gate.get("last_id", 0)),
        "runs": (int(resumed.get("runs", 0)) + 1) if resumed else 1,
        "scanned": int(resumed.get("scanned", 0) if resumed else 0) + int(prose_gate.get("scanned", 0)),
        "flagged": int(resumed.get("flagged", 0) if resumed else 0) + int(prose_gate.get("flagged", 0)),
        "flagged_ids": ids,
        "remaining": prose_gate.get("remaining"),
        "done": bool(prose_gate.get("done")),
        "started_at": (resumed or {}).get("started_at") or now,
        "updated_at": now,
    }
    if prior and "reset_reason" in prior:
        rec["reset_reason"] = prior["reset_reason"]
    try:
        path = _cursor_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        cursors = _read_cursors()
        cursors[scope] = rec
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cursors, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        _LOG.warning("criteria-calibration cursor could not be written", exc_info=True)
        rec["persisted"] = False
    else:
        rec["persisted"] = True
    return rec


def calibration_report(
    session: Session,
    *,
    top_n: int = _DEFAULT_TOP_N,
    prose_gate_limit: int = _DEFAULT_PROSE_GATE_LIMIT,
    prose_gate_after_id: int = 0,
    prose_gate_scope: str = "all",
    resume: bool = False,
) -> dict[str, Any]:
    """The top ``top_n`` disregarded/would-be-disregarded articles under the CURRENT
    criteria, with per-article detail (id, title, url, source, word count, function-word
    density, sentence-punctuation density, which criterion fired) plus aggregate counts
    per criterion / per source / per language, so the maintainer can optimize the criteria
    on real specimens before any retroactive quarantine (S3.4) executes for real.

    Reuses ``scan_non_article_candidates(..., include_prose_gate=True)`` for the actual
    detection (never re-implements a rule); this function only COLLECTS the sample ids it
    already returns, fetches their real article detail (a bounded ``top_n``-row decrypt),
    and aggregates. Never invents a row: an id that vanished between the scan and the
    detail fetch (a concurrent delete/prune) is silently skipped, never fabricated.

    ``prose_gate_scope`` selects WHICH population the prose-gate arm walks (see
    :data:`src.analytics.non_article_scan.PROSE_GATE_SCOPES`); the report states it.
    ``resume`` (default False = the caller's own ``prose_gate_after_id`` is honoured
    exactly) carries the cursor ACROSS runs and publishes the running totals under
    ``prose_gate_progress`` -- which is what lets a repeated run reach the end of its
    population instead of re-measuring its first batch forever.
    """
    from src.analytics.non_article_scan import scan_non_article_candidates
    from src.database.models import Article, Source
    from src.services.prose_gate import function_word_density, sentence_punct_density

    prior = load_cursor(prose_gate_scope) if resume else None
    if resume and prior and "reset_reason" not in prior:
        prose_gate_after_id = int(prior.get("after_id", prose_gate_after_id))

    base = scan_non_article_candidates(
        session,
        sample_per_reason=top_n,
        include_prose_gate=True,
        prose_gate_limit=prose_gate_limit,
        prose_gate_after_id=prose_gate_after_id,
        prose_gate_scope=prose_gate_scope,
    )

    # Combine the URL-shape reasons' sample ids with the prose-gate subpass's sample ids,
    # capped at top_n overall (concatenation, never a re-ranking -- this is a report over
    # what the detectors already flagged, not a new prioritisation).
    candidates: list[tuple[int, str]] = []
    seen: set[int] = set()
    for reason in base["by_reason"]:
        for aid in reason["sample_ids"]:
            if len(candidates) >= top_n:
                break
            if aid not in seen:
                candidates.append((int(aid), reason["signal"]))
                seen.add(int(aid))
        if len(candidates) >= top_n:
            break
    prose_gate = base.get("prose_gate") or {}
    for aid in prose_gate.get("sample_ids", []):
        if len(candidates) >= top_n:
            break
        if int(aid) not in seen:
            candidates.append((int(aid), "nav_soup"))
            seen.add(int(aid))

    articles: list[dict[str, Any]] = []
    per_source: dict[str, int] = {}
    per_language: dict[str, int] = {}
    if candidates:
        ids = [aid for aid, _ in candidates]
        rows: dict[int, Article] = {
            a.id: a for a in session.query(Article).filter(Article.id.in_(ids)).all()
        }
        source_ids = {a.source_id for a in rows.values()}
        source_names: dict[int, str] = {
            sid: name
            for sid, name in session.query(Source.id, Source.name).filter(Source.id.in_(source_ids))
        } if source_ids else {}
        for aid, signal in candidates:
            a = rows.get(aid)
            if a is None:
                continue  # vanished since the scan (a concurrent delete/prune) -- never invent it
            lang = a.language or a.detected_language
            density, best_lang = function_word_density(a.content or "", language=lang)
            punct = sentence_punct_density(a.content or "")
            source_name = source_names.get(a.source_id) or f"source #{a.source_id}"
            articles.append({
                "id": a.id,
                "title": a.title,
                "url": a.url,
                "source": source_name,
                "word_count": a.word_count,
                "language": lang,
                "best_matching_language": best_lang,
                "function_word_density": density,
                "sentence_punct_density": punct,
                "criterion": signal,
            })
            per_source[source_name] = per_source.get(source_name, 0) + 1
            lang_key = lang or "unknown"
            per_language[lang_key] = per_language.get(lang_key, 0) + 1

    per_criterion: dict[str, int] = {r["signal"]: r["count"] for r in base["by_reason"]}
    if prose_gate.get("enabled"):
        per_criterion["nav_soup"] = per_criterion.get("nav_soup", 0) + int(prose_gate.get("flagged", 0))

    progress: dict[str, Any] | None = None
    if resume:
        progress = advance_cursor(
            prose_gate_scope,
            criteria_version=CRITERIA_VERSION,
            prose_gate=prose_gate,
            prior=prior,
        )
        progress["caveat"] = (
            "Cumulative across runs of THIS scope under THIS criteria version, summed over "
            "disjoint id ranges. An article pruned between runs stays counted in the batch "
            "that saw it and is no longer in the corpus, so a total may exceed what a "
            "single-pass scan would find today; a criteria-version change resets the totals "
            "rather than summing two detectors' verdicts. `flagged_ids` is capped at "
            f"{_CURSOR_SAMPLE_CAP} -- a sample for spot-checking, never the flagged set."
        )

    return {
        "schema": SCHEMA,
        "criteria_version": CRITERIA_VERSION,
        "prose_gate_scope": prose_gate_scope,
        "prose_gate_progress": progress,
        "top_n": top_n,
        "collected": len(articles),
        "articles": articles,
        "aggregates": {
            "per_criterion": [
                {"criterion": k, "count": v}
                for k, v in sorted(per_criterion.items(), key=lambda kv: -kv[1])
            ],
            "per_source": [
                {"source": k, "count": v} for k, v in sorted(per_source.items(), key=lambda kv: -kv[1])
            ],
            "per_language": [
                {"language": k, "count": v} for k, v in sorted(per_language.items(), key=lambda kv: -kv[1])
            ],
        },
        "base_scan": base,
        "method": "A REPORT over the existing detectors -- classify_non_article's URL-shape rules "
        "(no content decrypt) + the opt-in prose-gate subpass (a bounded, resumable content decrypt, "
        "see base_scan.prose_gate) -- never a new rule of its own. Per-article density figures are "
        "recomputed directly here for EVERY collected specimen (whichever criterion actually fired), "
        "so the maintainer sees the same numbers regardless of which detector caught it. The "
        "prose-gate arm walks the population named in base_scan.prose_gate.population; with "
        "resume=true its cursor carries across runs and prose_gate_progress holds the running "
        "totals, so a repeated run advances through the population instead of re-measuring its "
        "first batch.",
        "caveat": "TEMPORARY, for criteria calibration only -- a sample, not a full-corpus sweep. "
        "Iterative: review these specimens, adjust the criteria (propose -> review -> apply, the "
        "stoplist discipline), re-export. No retroactive quarantine executes against real data until "
        "this report has been reviewed and the criteria agreed (0.3 gate row 5). Inherits base_scan's "
        "own caveats (a conservative undercount; unsegmented zh/ja/th bodies skip the prose gate; a "
        "headline-list page deliberately escapes it by design).",
    }
