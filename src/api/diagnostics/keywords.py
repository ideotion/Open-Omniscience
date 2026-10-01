"""
The keyword log/export endpoints and their bounded-export helpers.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 61-1084 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from src.analytics import queries as q
from src.analytics.families import build_families
from src.analytics.keyword_log_export import (
    MIN_ENTRY_BYTES,
    PARTS_DIR_PREFIX,
    ZipHooks,
    ZipJob,
    batched,
    disk_check_for,
    disk_watch_for,
    entry_for,
    export_dir,
    fetch_meta,
    fetch_signatures,
    finish_parts,
    finish_zip,
    fit_window,
    resolve_max_bytes,
    retire_old_parts_sets,
    sweep_stale_scratch,
    unlink_quietly,
    zip_disk_preflight,
)
from src.analytics.keyword_log_scan import (
    IN_LIST_IDS,
    ArticleMaps,
    ExportRefused,
    Ranker,
    RingAcc,
    StopwordAcc,
    available_bytes_now,
    memory_plan,
    order_key,
    scan_keywords,
)
from src.analytics.upload_parts import sha256_file
from src.database.maintenance import (
    StatementTimeout,
    raise_if_memory_short,
    statement_deadline,
)
from src.database.models import KeywordSuperGroup, Source
from src.database.read_snapshot import read_only_db
from src.utils.export_envelope import envelope

from ._base import _MAX_KEYWORDS_PER_LANG, router

# Stopword-candidate digest (maintainer 2026-06-18, "full authority on the logging
# process"): the recursive-improvement loop is "grow the not-a-keyword list", and
# the analyst (me) needs, per language, the terms that LOOK like function words but
# aren't stoplisted yet — NOT a 24 MB dump of 245k keywords. A function word is
# SHORT, FREQUENT and UBIQUITOUS (spread across many articles), so it lives at the
# TOP by frequency (well within the per-language survivor set) — the cap never hides
# it. This compact, whole-corpus-relevant digest is computed FROM the survivors the
# export already built (zero extra DB cost), prioritised by the languages that have
# NO stoplist yet (where the wins are).
_SW_CAND_PER_LANG = 60     # top candidates surfaced per language
_SW_CAND_MAX_LEN = 14      # function words are short; longer terms are content
_SW_CAND_MIN_ARTICLES = 5  # needs real spread (ubiquity) to look like a function word

# Ring-candidate digest: the inverse worklist — the highest-spread CONCEPTS not yet
# in any cross-language ring, per language, to drive the corpus-driven ring
# expansion (generate_wikidata_rings.py --from-log) and to measure coverage.
# Defined in src/analytics/ring_loader.py and ALIASED here: S04-06's in-app ring load is
# the second reader, and an analytics module may not import an api one. The private names
# stay, so every existing reader of this module is unaffected.
from src.analytics.ring_loader import (  # noqa: E402
    RING_CAND_MIN_ARTICLES as _RING_CAND_MIN_ARTICLES,
)
from src.analytics.ring_loader import (  # noqa: E402
    RING_CAND_PER_LANG as _RING_CAND_PER_LANG,
)


def _stopword_doc(result: dict) -> dict:
    """The stopword-candidate block, from a :class:`StopwordAcc` result."""
    return {
        "method": (
            "Per dominant-signature language, short single-token TERMS (<= "
            f"{_SW_CAND_MAX_LEN} chars, >= {_SW_CAND_MIN_ARTICLES} distinct articles) NOT "
            "yet stoplisted, ranked by article spread — the shape of a function word. "
            "Candidates to REVIEW before adding to a stoplist; no score, no inference."
        ),
        "priority_languages": result["priority"],
        "by_language": result["ordered"],
    }


def _new_stopword_acc(is_hidden) -> StopwordAcc:
    return StopwordAcc(
        is_hidden, per_lang=_SW_CAND_PER_LANG, max_len=_SW_CAND_MAX_LEN,
        min_articles=_SW_CAND_MIN_ARTICLES,
    )


def _stopword_candidates(survivors, meta, dom_lang, is_hidden) -> dict:
    """Per dominant-language, the highest article-SPREAD short single-token TERMS that
    are NOT yet stoplisted — the shape of a function word. Ranked by distinct-article
    spread; no score. Languages with no stoplist (no_stoplist/unsegmented) come first.

    The one-shot form over a survivor list; the export itself feeds
    :class:`~src.analytics.keyword_log_scan.StopwordAcc` batch by batch, so it never holds
    the survivors at all. Both are the same accumulator, so they cannot disagree."""
    acc = _new_stopword_acc(is_hidden)
    for i, (kid, m, a, _first, _last) in enumerate(survivors):
        acc.feed(i, m, a, dom_lang.get(kid), meta.get(kid, ("?", "?", None, False, None)))
    return _stopword_doc(acc.result())


def _ring_doc(result: dict) -> dict:
    """The ring-gap block, from a :class:`RingAcc` result."""
    return {
        "method": (
            "Per dominant-signature language, non-entity TERMS with >= "
            f"{_RING_CAND_MIN_ARTICLES} distinct articles NOT yet in any cross-language "
            "ring, ranked by article spread — the ring GAP for "
            "generate_wikidata_rings.py --from-log. translation_coverage = "
            "ring-covered / gated terms (the self-check metric). Candidates to RESOLVE "
            "via a Wikidata QID; multi-word concepts kept; no score, no inference."
        ),
        "translation_coverage": result["translation_coverage"],
        "gated_terms": result["gated_terms"],
        "by_language": result["by_language"],
    }


def _new_ring_acc(is_hidden) -> RingAcc:
    from src.analytics import equivalence

    return RingAcc(
        is_hidden, equivalence.ring_of, per_lang=_RING_CAND_PER_LANG,
        min_articles=_RING_CAND_MIN_ARTICLES,
    )


def _ring_candidates(survivors, meta, dom_lang, is_hidden) -> dict:
    """Per dominant-signature language, the highest article-SPREAD TERMS that are
    NOT yet in any cross-language RING — the ring GAP, the worklist for the
    corpus-driven expansion ``generate_wikidata_rings.py --from-log``.

    Two optimisations over blindly taking the top-N keywords: (1) it EXCLUDES terms
    already in a ring, so a generation pass resolves NEW concepts instead of
    re-resolving the ones we already have; (2) it surfaces EVERY language (not just
    English), so a concept prominent only in ar/zh/ru is seedable too (the
    de-US-centring fix — the generator can search Wikidata in that language).
    Also reports ``translation_coverage`` (ring-covered / gated terms) — the
    self-check metric, in the same log the maintainer already exports.

    Concepts come from non-entity TERMS (acronym entities resolve ambiguously on
    Wikidata — exactly the homograph garbage vetting had to drop). Multi-word terms
    are KEPT (a concept can be "climate change" / "supply chain"), unlike the
    single-token stopword candidates. No score, no inference.

    The one-shot form over a survivor list (see :func:`_stopword_candidates`)."""
    acc = _new_ring_acc(is_hidden)
    for i, (kid, m, a, _first, _last) in enumerate(survivors):
        acc.feed(i, m, a, dom_lang.get(kid), meta.get(kid, ("?", "?", None, False, None)))
    return _ring_doc(acc.result())


# Digest mode keeps the same bounded aggregates but ships only the top-N
# most-mentioned keywords instead of the full per-keyword list, so the file is
# small enough to actually ingest in the maintainer->dev channel (field-test
# 2026-06-15 Item Z: a full log measured ~60 MB and was unusable in the very
# channel it exists for). The aggregates ARE the analysis; the long tail is not.
# 100 bounds the REPORT (the keywords printed as a glance); every keyword is counted in the
# aggregates beside it.
_DIGEST_SAMPLE = 100

# Default size cap for the per-language ZIP export (?format=zip). The single-file log
# grew to ~20 MB live (137k keywords), so the shareable archive is capped: it
# splits per language and zips (JSON compresses ~8x, so the archive is normally a
# few MB), and if the compressed archive exceeds this it drops the lowest-mention
# keywords PER LANGUAGE (equal-fair — a global mentions cut would re-anglicise the
# export) and records the omission. The cap is what the loop AIMS for, not a
# guarantee: summary.json is never trimmed, so a summary alone larger than the cap
# leaves the archive over it (see finish_zip). Env-tunable; `max_mb=0` on the
# request lifts it.
def _keyword_zip_max_bytes() -> int:
    # WHAT THE 9 MB PROTECTS: the ATTACHMENT CHANNEL. It keeps a shared archive UNDER the
    # common 10 MB attachment limit (raised 2026-07-01: the maintainer could not send a
    # log); it is not a memory bound any more (the export holds a batch either way) and
    # protects nothing else. With the families cap below, a 727k-keyword corpus is ~8 MB
    # with EVERY keyword — no trimming needed; a larger corpus trims its lowest-mention
    # tail (per language, recorded) to fit. The "All keywords" button asks for no cap.
    try:
        mb = float(os.environ.get("OO_KEYWORD_LOG_MAX_MB", "9"))
    except ValueError:
        mb = 9.0
    # Floor at 256 B (not 1 MB) only to forbid a zero/negative cap; realistic
    # callers set MB-scale values. The small floor keeps the trim path testable.
    return max(256, int(mb * 1024 * 1024))


def _keyword_zip_families_cap() -> int:
    """Top-N families to embed in summary.json (0 = keep all — the old behaviour).

    The full per-keyword family dump is ~150 MB on a large corpus (708k families in the
    2026-07-01 log), REDUNDANT with keywords/<lang>.json, and UNUSED by
    analyze_keyword_log.py (it reassembles keywords from the shards). It was also why the
    byte cap never held: the trim loop shrinks the shards, never summary.json. So only the
    top families (by mentions) are kept for a human glance; the tail is derivable from the
    shards. Override with OO_KEYWORD_LOG_FAMILIES. The 1,000 bounds the REPORT (families printed in
    full); every family is built and counted, and the provenance block says how many were left out.
    """
    try:
        return max(0, int(os.environ.get("OO_KEYWORD_LOG_FAMILIES", "1000")))
    except ValueError:
        return 1000


def _quantiles(values: list[int]) -> dict:
    """Min / p25 / median / p75 / p95 / max over an ALREADY-SORTED list, plus n and sum.

    Nearest-rank, no interpolation: these are counts of real things, and an interpolated
    "2.5 mentions" would be a number no keyword has. Empty input reports nulls with n=0
    rather than zeros -- "no families" and "families that all scored 0" are different
    facts (the same rule finding C5 is about).
    """
    n = len(values)
    if not n:
        return {"n": 0, "sum": 0, "min": None, "p25": None,
                "median": None, "p75": None, "p95": None, "max": None}

    def at(frac: float) -> int:
        return values[min(n - 1, max(0, int(round(frac * (n - 1)))))]

    return {
        "n": n,
        "sum": sum(values),
        "min": values[0],
        "p25": at(0.25),
        "median": at(0.50),
        "p75": at(0.75),
        "p95": at(0.95),
        "max": values[-1],
    }


def _families_summary(families: list[dict]) -> dict:
    """Facts about EVERY family, so capping the printed list costs no aggregate answer.

    The maintainer's objection to the 2026-09-11 families cap was that capping biases
    future diagnostics, and it was correct: a global top-N by mentions is the same
    mentions-ranked cut this file already records as having "structurally anglicised the
    export", and it hides `conflated_by` (a possible bad merge) preferentially, because a
    wrong merge is likelier among rare terms than famous ones.

    This is the answer to that: the printed list shrinks, the RECORD does not. Everything
    here is computed over the full list before any cap is applied, so "how long is the
    tail", "what is the mention distribution", "how many families are of kind X" and
    "which families did the lemma merge join" all stay answerable from the digest alone.
    """
    mentions = sorted(int(f.get("mentions") or 0) for f in families)
    variants = sorted(int(f.get("variants") or 0) for f in families)
    by_kind: dict[str, int] = {}
    conflated: list[dict] = []
    manual = 0
    for f in families:
        by_kind[str(f.get("kind") or "unknown")] = by_kind.get(str(f.get("kind") or "unknown"), 0) + 1
        if f.get("manual"):
            manual += 1
        if f.get("conflated_by"):
            conflated.append(
                {
                    "term": f.get("term"),
                    "normalized": f.get("normalized"),
                    "kind": f.get("kind"),
                    "mentions": f.get("mentions"),
                    "variants": f.get("variants"),
                    "conflated_by": f.get("conflated_by"),
                }
            )
    # Rarest first: the whole point is that the tail is where a bad merge hides, so the
    # ordering must not re-create the popularity bias this block exists to remove.
    conflated.sort(key=lambda c: (int(c.get("mentions") or 0), str(c.get("normalized") or "")))
    return {
        "total_families": len(families),
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0]))),
        "manual_overrides": manual,
        "mentions": _quantiles(mentions),
        "variants": _quantiles(variants),
        "single_member_families": sum(1 for v in variants if v <= 1),
        # SELECTED ON THE SIGNAL, NEVER ON RANK: a conflated family is a possible bad
        # merge, so every one is listed however rare it is. Ordered rarest-first for the
        # same reason.
        "conflated": {
            "count": len(conflated),
            "families": conflated,
            "method": (
                "Every family carrying conflated_by (the lemma merge joined it), listed "
                "in full and ordered rarest-first -- selected by the signal, never by "
                "mentions, because a wrong merge is likelier among rare terms."
            ),
        },
        "method": (
            "Computed over ALL families before the print cap is applied, so the capped "
            "`families` list costs no aggregate answer about the tail. Counts only; no "
            "scores."
        ),
    }


def _safe_lang_filename(lang: str) -> str:
    """A filesystem/zip-safe stem for a language code ('?' -> 'unknown')."""
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in (lang or ""))
    return safe or "unknown"


#: Entries per ``json.dumps`` call when the JSON form streams its keywords and its families.
#: What it protects: one ``dumps`` of the whole list built a second copy of it (the string); a
#: slice holds a few hundred KB (an entry is about 210 bytes of JSON on the synthetic corpus and 250-290 in the field's logs: see
#: ``ZIP_BYTES_PER_ENTRY``), so
#: streaming costs one slice, never the window. It is also the cadence of the memory stop's check
#: between slices (a read of available memory per thousand entries, far finer than the stop's
#: margin). The bytes written are the same as one ``dumps``.
_JSON_SLICE = 1_000

# What the archive writer borrows from this route (built after the names it lends exist).
_ZIP_HOOKS = ZipHooks(
    families_cap=_keyword_zip_families_cap,
    safe_lang_filename=_safe_lang_filename,
    new_stopword_acc=_new_stopword_acc,
    new_ring_acc=_new_ring_acc,
    stopword_doc=_stopword_doc,
    ring_doc=_ring_doc,
)


def _keyword_zip(
    *, job: ZipJob, keep: dict[str, int], omitted: dict[str, int] | None = None
) -> Response:
    """Build the per-language keyword-log ZIP on disk (aiming under the byte cap, see
    ``finish_zip`` for when that cannot be met) and serve it; the scratch file is deleted once
    it has been sent. ``finish_zip`` says what is in it."""
    path = finish_zip(job, keep, omitted)
    fname = f"oo-keyword-log-{datetime.now().strftime('%Y%m%d')}.zip"
    return _ScratchFileResponse(
        str(path),
        media_type="application/zip",
        filename=fname,
        background=BackgroundTask(unlink_quietly, path),
    )


#: Next to the set's files: what the page was told (names, sizes, checksums), so a part is served
#: only if the set names it. A caller never supplies a path.
_SET_LISTING = "set.json"

_PARTS_SET_RE = re.compile(re.escape(PARTS_DIR_PREFIX) + r"[A-Za-z0-9._-]+")


def _parts_root() -> Path:
    """Where sets of parts are kept: the export's scratch folder, else the OS temp folder (the
    same fallback the archive itself uses when there is no data folder)."""
    return export_dir() or Path(tempfile.gettempdir())


def _keyword_parts(
    *, job: ZipJob, keep: dict[str, int], omitted: dict[str, int] | None, scratch_dir: Path
) -> Response:
    """Build the export as a numbered set of parts of at most 1,000,000 bytes (see
    ``finish_parts``) and answer with the listing the page downloads from: every file's name,
    size and SHA-256 and the URL base. The files stay until the next build retires them."""
    stem = f"oo-keyword-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    set_dir, manifest = finish_parts(job, keep, omitted, scratch_dir=scratch_dir, stem=stem)
    files = [
        {"name": p["name"], "bytes": p["bytes"], "sha256": p["sha256"], "kind": "part"}
        for p in manifest["parts"]
    ]
    for name in manifest["manifest_files"]:
        f = set_dir / name
        files.append({
            "name": name, "bytes": f.stat().st_size, "sha256": sha256_file(f), "kind": "manifest",
        })
    listing = {
        "set": set_dir.name,
        "stem": stem,
        "part_count": manifest["part_count"],
        "part_max_bytes": manifest["part_max_bytes"],
        "total_bytes": sum(f["bytes"] for f in files),
        "files": files,
        "download_base": f"/api/diagnostics/keywords/parts/{set_dir.name}/",
        "note": (
            "Save every file listed, the manifest first: each part opens on its own, and the "
            "manifest lists every part with its size and SHA-256 so a set can be confirmed "
            "complete."
        ),
    }
    (set_dir / _SET_LISTING).write_text(json.dumps(listing), encoding="utf-8")
    return JSONResponse(listing)


class _ScratchFileResponse(FileResponse):
    """A file response that deletes its scratch file however the exchange ends.

    Starlette runs a response's background task only on the paths that send the whole file:
    a malformed or unsatisfiable ``Range`` header is answered early (416) without it, which
    left an archive of up to several GB on the drive until the next export's 12-hour sweep.
    The file goes in a ``finally``, so a dropped connection or an error mid-send cleans up too."""

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        try:
            await super().__call__(scope, receive, send)
        finally:
            unlink_quietly(Path(str(self.path)))


def _export_deadline_seconds() -> float:
    """Deadline for THIS on-demand, streamed, full-corpus diagnostic export.

    The interactive ``OO_STATEMENT_TIMEOUT_S`` (60s) guard is the WRONG mechanism
    here: the keyword log is a DELIBERATE full-corpus crunch the operator
    explicitly requests and streams to disk, not a latency-sensitive page read.
    At field scale (≈940k mentions / 336k keywords, encrypted, 2-core VM) the
    full ``keyword_mentions`` scans legitimately run past 60s, so the interactive
    deadline ABORTED the export with a 503 -- i.e. the cap was bounding the
    data-crunching, which the maintainer's keyword policy forbids ("a cap may
    bound a REPORT, never the crunching").

    So the export gets its OWN budget: ``OO_KEYWORD_EXPORT_TIMEOUT_S``, default
    0 = no deadline. The download still streams (progress is visible) and the
    single-writer WAL keeps writers unblocked during the long read. Set a
    positive number of seconds to re-impose a ceiling.
    """
    try:
        return float(os.environ.get("OO_KEYWORD_EXPORT_TIMEOUT_S", "0"))
    except ValueError:
        return 0.0


@router.get("/keywords")
def keyword_log(
    # Field finding C: this heavy two-scan export contended with the live scrape. Run it
    # on a DEDICATED read-only (query_only) WAL-snapshot connection so it can never take
    # the write gate or stall a writer, never occupies a shared-pool slot for the whole
    # streamed scan, and reads one consistent snapshot (src.database.read_snapshot).
    db: Session = Depends(read_only_db),
    digest: bool = Query(
        False,
        description=(
            "Digest mode: ship the bounded aggregates (families, per-source "
            "concentration, totals) + a top-N keyword sample instead of the full "
            "per-keyword list, for a small, ingestible file (Item Z). The default "
            "(full) stream is byte-for-byte unchanged."
        ),
    ),
    fmt: str = Query(
        "json",
        alias="format",
        description=(
            "'json' (default — the full single-file stream, byte-for-byte unchanged), "
            "'zip' — a per-language split archive (summary.json + keywords/<lang>.json "
            "+ manifest.json) that by default aims under 9 MB, so it fits a typical "
            "attachment limit (`max_mb=0` lifts the cap), or 'parts' — the same export as a "
            "NUMBERED SET of zips of at most 1,000,000 bytes each, every one valid on its own, "
            "with a manifest listing each part's size and SHA-256 (the answer is that "
            "listing; each file is served from /keywords/parts/<set>/<name>). `max_mb` still "
            "bounds the TOTAL when given; `0` is every keyword, as many parts as that takes."
        ),
    ),
    per_lang: int = Query(
        _MAX_KEYWORDS_PER_LANG,
        ge=1,
        # Not a limit on the export: a language has as many keywords as it has (the "All keywords"
        # button asks for a billion and gets every one). It only stops a nonsense number from
        # reaching SQLite's 64-bit LIMIT/OFFSET; it is 1,000x the largest language measured.
        le=1_000_000_000,
        description=(
            "ZIP and parts only: how many keywords PER dominant language to export (default "
            f"{_MAX_KEYWORDS_PER_LANG}). Raise it to export far more — even the whole "
            "corpus — in one archive (the <10 MB byte cap still applies unless "
            "`max_mb=0` and, if hit, trims the lowest-mention keywords per language and "
            "records it). Combine with `page` to walk through everything in digestible "
            "chunks."
        ),
    ),
    page: int = Query(
        1,
        ge=1,
        description=(
            "ZIP and parts only: 1-indexed page through the per-language keyword list (page N = "
            "keywords ranked [(N-1)*per_lang : N*per_lang] by mentions). The manifest "
            "reports pages_total + has_more so the full set can be exported across "
            "several files."
        ),
    ),
    max_mb: float | None = Query(
        None,
        ge=0,
        description=(
            "ZIP and parts only: the size cap in MB (with `format=parts`, for the TOTAL of all the numbered files: each file is at most 1,000,000 bytes whatever this says). Left out: OO_KEYWORD_LOG_MAX_MB (9 MB). "
            "`0` = NO cap: every keyword of the requested window is written, however large "
            "the file, straight to disk a batch at a time (memory stays bounded; the drive "
            "needs the room, and the export refuses, with the numbers, when it does not)."
        ),
    ),
) -> Response:
    """The keyword diagnostics log: every gathered keyword (bounded, mentions-desc)
    with its counts, plus the computed families, the user's merge/split overrides
    and the super-groups — exactly the structures the grouping logic works on.

    ``digest=1`` keeps every bounded aggregate but replaces the (potentially
    tens-of-MB) per-keyword list with a top-``_DIGEST_SAMPLE`` sample by mentions
    plus an honest ``keywords_digest`` provenance block (shown/total/omitted) so a
    digest is never mistaken for a complete log. The default path is untouched.

    Performance batch 2026-06-12 (failed live at 228k keywords): the per-language
    cap now bounds the WORK, not just the output — totals scan the covering
    index as plain tuples, the dominant language is computed in SQL, and the
    full language signatures / keyword metadata are fetched only for the
    keywords that survive the quota. The body is STREAMED, so memory stays
    bounded and the download starts immediately. Same envelope, same fields,
    same cap semantics as before (contract-tested).

    MEMORY (2026-09-30, the "All keywords" crash): nothing here is proportional to the
    number of keywords or articles any more. See :mod:`src.analytics.keyword_log_scan` for
    the scan and the ranking, and ``ZipJob`` (keyword_log_export) for the archive, which is written to disk a
    batch at a time. The read memory stop now runs on this export whatever its deadline is.
    """
    started = time.monotonic()

    def check() -> None:
        raise_if_memory_short(started=started)

    # Checked every this many keywords in the phases that run after the scan. What it protects:
    # the memory stop reads the machine's available memory (a system call), so it is not read
    # per keyword, and 2,000 entries are about 5 MB at the measured cost, far inside the
    # floor's margin.
    check_every = 2_000

    plan = memory_plan(available_bytes_now())
    # One archive ("zip") or a numbered set of small ones ("parts"): the same scan and window.
    archive = fmt in ("zip", "parts")
    max_bytes = resolve_max_bytes(fmt, max_mb, _keyword_zip_max_bytes())
    out_dir = export_dir()
    # Where the ranking spills when it must: the data folder, else the OS temp folder, never
    # "nowhere" (a ranker with no place to spill used to grow to the whole window in memory).
    # The OS temp folder is the last resort, not the choice: on some systems it is a RAM disk, which
    # is what ``export_dir`` exists to avoid. It is used because the alternatives are to grow in
    # memory (the crash this code was written for) or to refuse an export the machine could do.
    # Its stale scratch files are swept like the data folder's (only this export's own prefixes).
    if out_dir is not None:
        scratch_dir = out_dir
    else:
        scratch_dir = Path(tempfile.gettempdir())
        sweep_stale_scratch(scratch_dir)
    ranker: Ranker | None = None
    try:
        with statement_deadline(db, seconds=_export_deadline_seconds()):
            raise_if_memory_short()  # refuse to START when the machine is already at its floor
            # Article -> language and source, ONCE, each via its covering index (verified
            # plan: idx_article_language / the source_id index) — joining mentions to
            # articles in SQL would drag article rows through the SQLCipher codec for every
            # batch (measured 26 s of the 32 s encrypted-profile wall time). Held as flat
            # arrays, not dicts: see ArticleMaps.
            maps = ArticleMaps(db, check)
            src_articles: dict[int, int] = dict(
                db.execute(text("SELECT source_id, COUNT(*) FROM articles GROUP BY source_id")).fetchall()
            )

            # Page-aware per-language quota. The JSON path keeps the classic top-
            # _MAX_KEYWORDS_PER_LANG cap (lo=0); the ZIP path can raise per_lang and
            # page through the WHOLE corpus in digestible chunks (maintainer 2026-06-21:
            # "export more keywords — there were 200k+").
            eff_per_lang = per_lang if archive else _MAX_KEYWORDS_PER_LANG
            lo = (page - 1) * eff_per_lang if archive else 0
            hi = asked_hi = lo + eff_per_lang
            if max_bytes is not None:
                # A capped archive can never hold more than the cap allows at the smallest
                # entry there is; do not rank (or build) a window larger than that.
                hi = min(hi, lo + max_bytes // MIN_ENTRY_BYTES)

            ranker = Ranker(
                lo, hi, heap_rows=plan["heap_rows"], spill_dir=scratch_dir,
                disk_check=disk_check_for(scratch_dir),
                disk_watch=disk_watch_for(
                    scratch_dir, stopped="stopped ranking and removed its scratch file"
                ),
                # Every keyword there is bounds what the ranking can ever write to disk (its id
                # range is one primary-key read): the up-front check sizes the file from it.
                expected_rows=int(
                    db.execute(text("SELECT COALESCE(MAX(id), 0) FROM keywords")).scalar() or 0
                ),
            )
            # One ordered pass over the mention rows, then one over the keyword table. The
            # dominant signature language of each keyword, the totals a SECOND full GROUP BY
            # used to recompute (S7: byte-identical, one scan), and the per-source
            # concentration all come out of it; the ranker turns them into the per-language
            # quota. The DETECTION is unbounded: every keyword × source pair is evaluated.
            # Only the LIST PRINTED is bounded — strongest-first, with the true total
            # disclosed (the maintainer's anti-capping rule: caps may bound a REPORT, never
            # the data crunching).
            stats = scan_keywords(db, maps, src_articles, ranker, check=check)
            board = stats.board
            suspects = board.top()
            suspects_total = board.total
            suspects_capped = suspects_total > 200

            per_lang_seen = ranker.totals()
            window_note: dict | None = None
            # Keywords of the asked window left out BEFORE anything was built (the window was
            # cut to what the byte cap could ever hold): counted in keywords_omitted_to_fit
            # exactly as the ones the trim loop drops later, because to the reader they are
            # the same fact -- the window asked for was not delivered whole.
            clamp_omitted: dict[str, int] = {}
            if max_bytes is not None:
                ceiling = max_bytes // MIN_ENTRY_BYTES
                c = fit_window(
                    {lg: ranker.taken(lg) for lg in per_lang_seen if ranker.taken(lg) > 0},
                    ceiling,
                )
                if c is None and hi < asked_hi and any(t > hi for t in per_lang_seen.values()):
                    # The ranker was only ever asked for ``hi`` ranks (see above): that IS the
                    # window, and the reader is told so like any other cut.
                    c = hi - lo
                if c is not None:
                    before = max(ranker.taken(lg) for lg in per_lang_seen)
                    hi = lo + c
                    ranker.clamp(hi)
                    clamp_omitted = {
                        lg: asked - ranker.taken(lg)
                        for lg, seen in per_lang_seen.items()
                        if (asked := max(0, min(seen, asked_hi) - lo)) > ranker.taken(lg)
                    }
                    window_note = {
                        "asked_per_lang": eff_per_lang,
                        "exported_per_language_max": c,
                        "largest_language_window_before": before,
                        "why": (
                            f"a {max_bytes:,}-byte archive holds about {ceiling:,} entries at "
                            f"a generous {MIN_ENTRY_BYTES} bytes each (real keywords cost "
                            "several times that), so the window was cut to the largest equal "
                            "per-language window that could fit instead of building "
                            "millions of entries to throw them away. Pass max_mb=0 for no cap."
                        ),
                        "continue_with": {"per_lang": c, "page": 2} if lo == 0 else None,
                    }
                    eff_per_lang = c if lo == 0 else eff_per_lang
            capped_langs = {lg for lg, t in per_lang_seen.items() if t > hi}
            languages = [lg for lg in per_lang_seen if ranker.taken(lg) > 0]

            # Names for the concentration suspects (small, bounded set) — the section is
            # readable on its own: terms + source names + counts.
            suspect_meta = fetch_meta(db, [s["keyword_id"] for s in suspects])
            src_names: dict[int, str] = {}
            sids = sorted({s["source_id"] for s in suspects})
            if sids:
                marks = ",".join(str(int(i)) for i in sids)
                src_names = dict(
                    db.execute(
                        text(f"SELECT id, name FROM sources WHERE id IN ({marks})")  # nosec B608 - interpolant is a joined list of int()-cast ids built in this function, never input
                    ).fetchall()
                )
            per_source_concentration = [
                {
                    "term": suspect_meta.get(s["keyword_id"], ("?",))[0],
                    "source": src_names.get(s["source_id"], f"#{s['source_id']}"),
                    **{k: v for k, v in s.items() if k not in ("keyword_id", "source_id")},
                }
                for s in suspects
            ]

            overrides = q.load_overrides(db)
            supergroups = [
                {
                    "name": sg.name,
                    "members": sorted(m.normalized_term for m in sg.members),
                }
                for sg in db.query(KeywordSuperGroup).order_by(KeywordSuperGroup.name).all()
            ]
            n_sources = int(db.query(func.count(Source.id)).scalar() or 0)

            # The stoplist verdict is part of the diagnosis: leaked function words the
            # operator hid are exactly what grouping fixes need to see — flag, not omit.
            is_hidden = q._hidden_predicate()

            method = (
                f"All gathered keywords (top {_MAX_KEYWORDS_PER_LANG} PER dominant signature "
                "language — a global cap would anglicise the export) with real "
                "counts; language_signature = distinct articles per ARTICLE language "
                "(the trans-language disambiguation evidence); language_mismatch flags a "
                "stored language that disagrees with the signature's dominant one "
                "(attribution-noise evidence, never a correction); families computed by the "
                "live grouping logic incl. the user's merge/split overrides; super-groups "
                "as curated. per_source_concentration lists boilerplate SUSPECTS — a "
                "keyword whose articles sit ≥90% in one source, covering ≥25% of that "
                "source's articles (both sides ≥10 articles), strongest first, capped at "
                "200 — flagged with real counts, never auto-hidden. No scores, no inference."
            )

            if archive:
                exported = sum(ranker.taken(lg) for lg in languages)
                # The per-language taken counts, in the order each language FIRST appears in
                # the global survivor order (what the dict has always looked like).
                firsts: dict[str, tuple] = {}
                for lg in languages:
                    r0 = next(iter(ranker.rows(lg)))
                    firsts[lg] = order_key(r0[0], r0[1], r0[5] is not None)
                per_lang_taken = {lg: ranker.taken(lg) for lg in sorted(languages, key=firsts.get)}  # type: ignore[arg-type]
                corpus = {
                    "articles": maps.n_articles,
                    "sources": n_sources,
                    "keywords_total": stats.keywords_total,
                    "keywords_exported": exported,
                    "exported_per_language": per_lang_taken,
                    "capped_languages": sorted(capped_langs),
                }
                # Paging facts so the caller can walk the WHOLE corpus across files.
                pages_total = max(
                    (-(-t // eff_per_lang) for t in per_lang_seen.values()), default=1
                )
                page_info = {
                    "page": page,
                    "per_lang": eff_per_lang,
                    "pages_total": pages_total,
                    "has_more": any(t > hi for t in per_lang_seen.values()),
                    "keywords_total_corpus": sum(per_lang_seen.values()),
                }
                # What the families are grouped over: the whole window when it fits the memory
                # budget, else the largest equal per-language prefix that does (never a fixed
                # number: a machine with memory to spare groups everything it exports).
                basis_c = fit_window(
                    {lg: ranker.taken(lg) for lg in languages}, plan["family_rows"]
                )
                # Refuse an archive the drive cannot take BEFORE writing any of it. A numbered set
                # replaces the previous one, so the old set is retired first and the room it held
                # counts as free (a set built in the last few minutes stays, see _PARTS_GRACE_S).
                if fmt == "parts":
                    retire_old_parts_sets(scratch_dir)
                zip_disk_preflight(scratch_dir, exported, max_bytes)
                job = ZipJob(
                    hooks=_ZIP_HOOKS,
                    db=db, maps=maps, ranker=ranker, out_dir=scratch_dir, is_hidden=is_hidden,
                    overrides=overrides, supergroups=supergroups, corpus=corpus, method=method,
                    per_source_concentration=per_source_concentration,
                    suspects_total=suspects_total, suspects_capped=suspects_capped,
                    page_info=page_info, max_bytes=max_bytes, batch=plan["batch"], check=check,
                    # The drive the archive is WRITTEN to: the data folder, or the OS temp folder
                    # when there is none. (It was watched through ``out_dir``, which is None in
                    # exactly the case where the archive goes to the temp folder: no watch at all.)
                    disk_watch=disk_watch_for(scratch_dir), window_note=window_note,
                    basis_per_language=basis_c, basis_budget_rows=plan["family_rows"],
                )
                keep_now = {lg: ranker.taken(lg) for lg in languages}
                if fmt == "parts":
                    return _keyword_parts(
                        job=job, keep=keep_now, omitted=clamp_omitted, scratch_dir=scratch_dir,
                    )
                return _keyword_zip(job=job, keep=keep_now, omitted=clamp_omitted)

            # ---- json / digest: the window is at most _MAX_KEYWORDS_PER_LANG per language,
            # so the survivors (and what is needed to describe them) are bounded by the
            # LANGUAGES, never by the corpus.
            survivors: list[tuple] = []  # (kid, m, a, first, last, dom, stored-or-dominant language)
            for lg in languages:
                survivors.extend((*r, lg) for r in ranker.rows(lg))
            survivors.sort(key=lambda r: order_key(r[0], r[1], r[5] is not None))
            per_lang_taken = {}
            for r in survivors:
                per_lang_taken[r[6]] = per_lang_taken.get(r[6], 0) + 1
            corpus = {
                "articles": maps.n_articles,
                "sources": n_sources,
                "keywords_total": stats.keywords_total,
                "keywords_exported": len(survivors),
                "exported_per_language": per_lang_taken,
                "capped_languages": sorted(capped_langs),
            }

            # Metadata + full language signatures for SURVIVORS only.
            meta: dict[int, tuple] = {}
            lang_sig: dict[int, dict[str, int]] = {}
            for batch in batched(iter([s[0] for s in survivors]), IN_LIST_IDS):
                check()
                meta.update(fetch_meta(db, batch))
                lang_sig.update(fetch_signatures(db, maps, batch))
    except StatementTimeout as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ExportRefused as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    finally:
        if ranker is not None:
            ranker.close()

    def _entry(s: tuple) -> dict:
        return entry_for(s, meta, lang_sig, is_hidden)

    # THE PHASE AFTER THE SCAN holds every survivor, its metadata and signature, the families'
    # grouping and the digests at once (~2.5 KB per survivor, the measured resident cost): bounded by the
    # languages, never by the corpus, but the largest instance reaches about a gigabyte here.
    # The memory stop reads between steps, and a stop answers 503 with the numbers, as it does
    # inside the scan.
    try:
        fam_items = []
        sw_acc = _new_stopword_acc(is_hidden)
        ring_acc = _new_ring_acc(is_hidden)
        for i, s in enumerate(survivors):
            if i % check_every == 0:
                check()
            kw = _entry(s)
            if not kw["hidden"]:
                fam_items.append(
                    {
                        "term": kw["term"],
                        "normalized": kw["normalized"],
                        "kind": kw["kind"],
                        "mentions": kw["mentions"],
                        "articles": kw["articles"],
                    }
                )
            okey = order_key(s[0], s[1], s[5] is not None)
            mt = meta.get(s[0], ("?", "?", None, False, None))
            sw_acc.feed(okey, s[1], s[2], s[5], mt)
            ring_acc.feed(okey, s[1], s[2], s[5], mt)
        check()
        families = [f.to_dict() for f in build_families(fam_items, overrides)]
        check()

        # Compact per-language stopword-candidate digest (reuses the survivors already
        # built — zero extra DB cost) for the recursive "grow the not-a-keyword list" loop.
        stopword_candidates = _stopword_doc(sw_acc.result())

        # Compact ring-GAP digest (same survivors — zero extra DB cost) for the
        # corpus-driven ring expansion + the translation-coverage self-check.
        ring_candidates = _ring_doc(ring_acc.result())
    except StatementTimeout as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    digest_note = (
        f" DIGEST MODE: the per-keyword list is the top {_DIGEST_SAMPLE} keywords by "
        "mentions; keywords_digest reports how many were omitted. Re-request without "
        "digest=1 for the complete per-keyword log."
    )

    def _stream():
        head = envelope(
            kind="keyword-diagnostics",
            query={"digest": True} if digest else {},
            count=len(survivors),
            payload=None,
        )
        del head["data"]
        yield json.dumps(head, separators=(",", ":"))[:-1] + ', "data": {'
        yield '"corpus": ' + json.dumps(corpus, separators=(",", ":"))
        yield ', "method": ' + json.dumps(
            method + (digest_note if digest else ""), separators=(",", ":")
        )
        if digest:
            # Top-N by mentions (s[1]); ties keep scan order. The aggregates below
            # are unchanged — they ARE the analysis; only the long tail is dropped.
            sample = sorted(survivors, key=lambda s: s[1], reverse=True)[:_DIGEST_SAMPLE]
            yield ', "keywords": [' + ",".join(
                json.dumps(_entry(s), separators=(",", ":")) for s in sample
            ) + "]"
            yield ', "keywords_digest": ' + json.dumps(
                {
                    "sample": True,
                    "shown": len(sample),
                    "total": len(survivors),
                    "omitted": len(survivors) - len(sample),
                    "sort": "mentions desc",
                },
                separators=(",", ":"),
            )
        else:
            yield ', "keywords": ['
            for i in range(0, len(survivors), _JSON_SLICE):
                # As the families loop below: a stop raised here ends a stream whose headers are
                # sent already, which the reader sees as an incomplete download.
                check()
                chunk = survivors[i : i + _JSON_SLICE]
                prefix = "" if i == 0 else ","
                yield prefix + ",".join(
                    json.dumps(_entry(s), separators=(",", ":")) for s in chunk
                )
            yield "]"
        # Field diagnostics 2026-09-11 (B2): the DIGEST embedded the families dump in
        # FULL, and that is where `keyword-log-digest.json` got its 73.2 MB -- 84x the
        # next-largest archive member, ~96% of the whole bundle, and +3.4 GB of RSS on a
        # 4,093.8 MB machine whose previous session had already ended unclean at peak
        # 4158 MB. The cap this needed was already written, one path over:
        # `_keyword_zip_families_cap` caps exactly this block for the ZIP path, and its
        # own docstring records that the full 700k-family tail "was also why the byte cap
        # never held" -- the same lesson, and the digest path had never been given it.
        #
        # Reused rather than re-invented: same helper, same env override, same
        # sorted-by-mentions order, same honest omission record. A cap without the record
        # beside it would be a silent truncation, which is the defect this batch is full
        # of elsewhere.
        #
        # SCOPED TO `digest` ON PURPOSE: the non-digest single-file export is a contract
        # ("byte-for-byte unchanged", asserted by its own test), so `families` itself is
        # never mutated here -- only what this branch emits.
        if digest:
            # THE TAIL IS SUMMARISED, NOT SELECTED AWAY (maintainer's bias objection,
            # 2026-09-11). The first version of this cap simply took the top N by
            # mentions -- and that is a GLOBAL mentions-ranked cut, which is precisely
            # the shape this same file records at line 54 as having "structurally
            # anglicised the export", and which `method` (a few lines below) warns
            # against in its own words: "a global cap would anglicise the export". The
            # per-language keyword quota exists to avoid exactly that, and a global
            # families cut on top of it hands the bias straight back.
            #
            # Worse, popularity is the wrong axis for the thing most worth finding here:
            # `conflated_by` marks a family the lemma merge joined, i.e. a POSSIBLE
            # MISTAKE, and a wrong merge is likelier among rare terms than famous ones.
            # Ranking by mentions hides defects preferentially.
            #
            # So the cap no longer decides WHICH FACTS SURVIVE, only which rows are
            # printed in full:
            #   * every family is counted in `families_summary`, computed over ALL of
            #     them -- totals, per-kind counts, and the mention/variant distributions
            #     -- so no AGGREGATE question about the tail becomes unanswerable;
            #   * every conflated family is listed, selected ON THE SIGNAL rather than on
            #     popularity, so the defect-bearing subset is never rank-filtered;
            #   * the popularity sample is still there for a human glance, and is now
            #     LABELLED as unrepresentative instead of being left to look complete.
            # The full per-family record remains one endpoint away, and that export is
            # per-language fair by construction.
            _fam_cap = _keyword_zip_families_cap()
            _fam_shown = (
                families[:_fam_cap] if _fam_cap and len(families) > _fam_cap else families
            )
            yield ', "families": ' + json.dumps(_fam_shown, separators=(",", ":"))
            yield ', "families_summary": ' + json.dumps(
                _families_summary(families), separators=(",", ":")
            )
            yield ', "families_provenance": ' + json.dumps(
                {
                    "shown": len(_fam_shown),
                    "total": len(families),
                    "omitted": len(families) - len(_fam_shown),
                    "sorted_by": "mentions (desc)",
                    "sample_is_representative": False,
                    "selection_bias": (
                        "This list is the top families BY MENTIONS, which is a global "
                        "mentions-ranked cut and therefore skews English and skews "
                        "popular. Do NOT reason about the tail from it. Every family is "
                        "still counted in families_summary, and every conflated family "
                        "is listed there in full regardless of rank."
                    ),
                    "note": (
                        "Only the top families are printed in full here (the complete "
                        "per-family dump is large and is redundant with the per-language "
                        "shards). Nothing is DROPPED: the tail is summarised in "
                        "families_summary. Set OO_KEYWORD_LOG_FAMILIES=0 to print all, "
                        "or use the full keyword export, which is per-language fair."
                    ),
                },
                separators=(",", ":"),
            )
        else:
            # The same bytes as ``json.dumps(families)``, written a slice at a time: one dumps of
            # every family built a second copy of them (the string) on the largest instance.
            # A memory stop raised here ends the stream (the headers are sent already), which
            # the reader sees as an incomplete download rather than a killed app.
            yield ', "families": ['
            for i in range(0, len(families), _JSON_SLICE):
                check()
                prefix = "" if i == 0 else ","
                yield prefix + ",".join(
                    json.dumps(f, separators=(",", ":")) for f in families[i : i + _JSON_SLICE]
                )
            yield "]"
        yield ', "overrides": ' + json.dumps(
            [{"normalized_term": term, **data} for term, data in sorted(overrides.items())],
            separators=(",", ":"),
        )
        yield ', "supergroups": ' + json.dumps(supergroups, separators=(",", ":"))
        yield ', "stopword_candidates": ' + json.dumps(
            stopword_candidates, separators=(",", ":")
        )
        yield ', "ring_candidates": ' + json.dumps(
            ring_candidates, separators=(",", ":")
        )
        yield ', "per_source_concentration": ' + json.dumps(
            {
                "suspects": per_source_concentration,
                "suspects_total": suspects_total,
                "list_capped_at_200": suspects_capped,
                "thresholds": {
                    "min_articles_with_keyword": 10,
                    "min_source_articles": 10,
                    "min_share_of_keyword": 0.9,
                    "min_share_of_source": 0.25,
                },
            },
            separators=(",", ":"),
        )
        yield "}}"

    kind_tag = "digest" if digest else "log"
    fname = f"oo-keyword-{kind_tag}-{datetime.now().strftime('%Y%m%d')}.json"
    return StreamingResponse(
        _stream(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/keyword-selftest")
def keyword_selftest(download: bool = Query(False)) -> JSONResponse:
    """Run the keyword pre-selection challenge harness (Who vs WHO + language tweaks).

    A curated golden-case self-test over the REAL extractor / families / equivalence /
    baseline — no DB, no network, no score. Returns an exportable log (oo-selftest-1)
    the maintainer can run and send back for the next optimization round. With
    ``download=1`` it comes back as a dated attachment."""
    from src.analytics.selftest import run_keyword_selftest

    log = run_keyword_selftest()
    headers = {}
    if download:
        fname = f"oo-keyword-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)
