"""The keyword-log zip archive, written to disk a batch at a time.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The second half of the keyword export's memory fix (the first is
:mod:`src.analytics.keyword_log_scan`): the old builder held one entry dict per keyword of the
window, then the whole archive in a ``BytesIO``, up to nine times over while it trimmed to the
byte cap. Here a language's shard is a zip member that is appended to as entries are built, so
what is resident is one batch, the article arrays, the ranker, and three bounded digests.

The route (``src/api/diagnostics/keywords.py``) owns the URL, the parameters and the
response; this module owns the bytes. It never imports the API layer: what it needs from
there (the digest builders, the file-name rule, the family cap) arrives as :class:`ZipHooks`.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import shutil
import tempfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.analytics.families import build_families
from src.analytics.keyword_log_scan import (
    MENTIONS_TABLE,
    SPILL_PREFIX,
    ArticleMaps,
    ExportRefused,
    Ranker,
    RingAcc,
    StopwordAcc,
    order_key,
    scratch_file,
)
from src.utils.export_envelope import envelope


@dataclass(frozen=True)
class ZipHooks:
    """What the route lends the archive writer: its digest builders, its file-name rule and
    its family cap (all of which tests pin under the route's own names)."""

    families_cap: Callable[[], int]
    safe_lang_filename: Callable[[str], str]
    new_stopword_acc: Callable[[Any], Any]
    new_ring_acc: Callable[[Any], Any]
    stopword_doc: Callable[[dict], dict]
    ring_doc: Callable[[dict], dict]


def in_batches(ids: list[int], size: int = 800):
    for i in range(0, len(ids), size):
        yield ids[i : i + size]


#: A deliberately generous floor for what one compressed keyword entry costs, in bytes. What
#: it protects: a byte cap is enforced by trimming the tail of every language, and a window far
#: larger than the cap could ever hold (``per_lang=1000000`` against the 9 MB default) must not
#: be BUILT just to be thrown away -- that was the 4.4 GB run that produced a 9.2 MB file. The
#: window is cut to what would fit at this size per entry, and the loop below trims from there.
#: It is NOT a mathematical lower bound: the most compressible entry there is (an orphan with a
#: sequential synthetic term) measures 8-10 bytes, so an export of data that regular would be
#: cut a little early, and the manifest says how (``window_clamped_to_fit_cap``). Real terms
#: cost 18-41 bytes in the field's own logs and 40-200 in general.
MIN_ENTRY_BYTES = 12

#: Free space the export leaves on the volume it writes to. What it protects: the database's
#: own write-ahead log, which grows on the same disk (a 30 GB WAL was measured on a machine
#: with 38 GB free), and the operating system.
_DISK_RESERVE_FLOOR = 512 * 1024 * 1024

#: The reserve grows with the drive: one percent of the volume (10 GB on a 1 TB disk), because the
#: write-ahead log of a large database grows in proportion to it. 512 MiB alone is enough only
#: on a small drive.
_DISK_RESERVE_SHARE = 0.01

#: Headroom on the space a scratch file or archive is expected to need, before it is refused:
#: twenty per cent on an estimate that is already conservative (``SPILL_ROW_BYTES`` and
#: ``ZIP_BYTES_PER_ENTRY`` are both rounded up from a measurement), so that a write which would
#: end below the reserve is refused up front with the numbers, not halfway through it.
_DISK_NEED_MARGIN = 1.2

ZIP_TMP_PREFIX = "oo-keyword-log-part-"

#: A scratch file older than this has no export writing to it (every write refreshes its
#: mtime), so the next export may delete it.
_STALE_SCRATCH_S = 12 * 3600


def export_dir() -> Path | None:
    """The folder the export's scratch files live in: next to the data, where free space
    is already watched -- never ``/tmp``, which on several OSes is a RAM disk."""
    try:
        from src.paths import data_dir

        d = data_dir() / "diagnostics"
        d.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 - no writable data dir: the export stays in memory
        return None
    sweep_stale_scratch(d)
    return d


def sweep_stale_scratch(d: Path) -> None:
    """Delete this export's own abandoned scratch files (a killed process leaves them)."""
    now = time.time()
    try:
        for p in d.iterdir():
            if p.name.startswith((SPILL_PREFIX, ZIP_TMP_PREFIX)):
                try:
                    if now - p.stat().st_mtime > _STALE_SCRATCH_S:
                        p.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def disk_reserve(d: Path) -> int:
    try:
        total = shutil.disk_usage(d).total
    except OSError:
        return _DISK_RESERVE_FLOOR
    return max(_DISK_RESERVE_FLOOR, int(total * _DISK_RESERVE_SHARE))


def disk_check_for(d: Path | None):
    """``disk_check(bytes)`` for the ranker: refuse, with the numbers, a spill the volume
    cannot take plus the reserve. ``None`` when there is no directory to write to."""
    if d is None:
        return None

    def _check(need: int) -> None:
        try:
            free = shutil.disk_usage(d).free
        except OSError:
            return  # an unreadable volume is not refused on a guess
        reserve = disk_reserve(d)
        if free < need * _DISK_NEED_MARGIN + reserve:
            raise ExportRefused(
                f"the export needs about {need / 2**30:.1f} GiB of scratch space next to "
                f"your data, and only {free / 2**30:.1f} GiB is free on that drive "
                f"(it keeps {reserve / 2**30:.1f} GiB free for the database's own log). "
                "Free some space, or ask for a smaller window (per_lang=...).",
                status=507,
            )

    return _check


def disk_watch_for(d: Path | None, *, stopped: str = "stopped writing the archive and removed it"):
    """Called between batches while the archive grows: stop before the drive is full.

    ``stopped`` finishes the sentence the refusal says ("so it ..."): what the export was doing
    when it stopped, because the same watch guards the ranking's scratch file as well as the
    archive."""
    if d is None:
        return lambda: None

    def _watch() -> None:
        try:
            free = shutil.disk_usage(d).free
        except OSError:
            return
        reserve = disk_reserve(d)
        if free < reserve:
            raise ExportRefused(
                f"the drive holding your data is down to {free / 2**30:.2f} GiB free "
                f"(the export keeps {reserve / 2**30:.1f} GiB free for the database's own "
                f"log), so it {stopped}.",
                status=507,
            )

    return _watch


#: A conservative ZIPPED size of one exported entry, to refuse a write the drive obviously cannot
#: take BEFORE minutes of work rather than halfway through them (the between-batches watch stays
#: as the backstop). Measured: an entry is ~210 B of JSON and deflates to 9-15 B on a synthetic
#: corpus, and the field's own logs (1.24-1.45 MB of JSON per 5,000 keywords, zip 7-14x smaller)
#: put it at 18-41 B, so 64 covers the worst reading ~1.5x. It protects the operator's drive
#: (a full disk stops the database's own log), nothing else: a refusal names the numbers and
#: the smaller window that would have fit.
ZIP_BYTES_PER_ENTRY = 64

#: summary.json + manifest.json: families and digests, a few MB at the largest measured.
ZIP_FIXED_BYTES = 8 * 2**20


def expected_zip_bytes(entries: int, max_bytes: int | None) -> int:
    """The archive's expected size on disk: the fixed members plus a conservative entry cost,
    bounded by the cap (plus the members the cap does not trim) when there is one."""
    need = ZIP_FIXED_BYTES + entries * ZIP_BYTES_PER_ENTRY
    return need if max_bytes is None else min(need, max_bytes + ZIP_FIXED_BYTES)


def zip_disk_preflight(out_dir: Path | None, entries: int, max_bytes: int | None) -> None:
    """Refuse, with the numbers, an archive the drive cannot take plus its reserve (HTTP 507).

    ``out_dir`` is where the archive will be written (the OS temp folder when there is no data
    folder, exactly as :meth:`ZipJob._path` decides).
    """
    target = out_dir if out_dir is not None else Path(tempfile.gettempdir())
    disk_check_for(target)(expected_zip_bytes(entries, max_bytes))  # type: ignore[misc]


def batched(it, n: int):
    while True:
        chunk = list(itertools.islice(it, n))
        if not chunk:
            return
        yield chunk


def fetch_meta(db, kids) -> dict[int, tuple]:
    """``{kid: (term, normalized, language, is_entity, entity_type)}`` for these keywords."""
    meta: dict[int, tuple] = {}
    for batch in in_batches(list(kids)):
        marks = ",".join(str(int(i)) for i in batch)
        for kid, term, norm, lang, is_ent, ent_type in db.execute(
            text(
                "SELECT id, term, normalized_term, language, is_entity,"  # nosec B608 - interpolant is a joined list of int()-cast ids built in this function, never input
                f" entity_type FROM keywords WHERE id IN ({marks})"
            )
        ):
            meta[kid] = (term, norm, lang, bool(is_ent), ent_type)
    return meta


def fetch_signatures(db, maps: ArticleMaps, kids) -> dict[int, dict[str, int]]:
    """Full language signatures via index-only probes plus the article-language map -- mention
    rows are unique per (keyword, article), so each row is one distinct article in its
    language."""
    sigs: dict[int, dict[str, int]] = {}
    langs, lang_arr = maps.langs, maps.lang_arr
    for batch in in_batches(list(kids)):
        marks = ",".join(str(int(i)) for i in batch)
        for kid, aid in db.execute(
            text(
                f"SELECT keyword_id, article_id FROM {MENTIONS_TABLE}"  # nosec B608 - constant table name; interpolant is a joined list of int()-cast ids built in this function, never input
                f" WHERE keyword_id IN ({marks})"
            )
        ):
            try:
                lid = lang_arr[aid] if aid >= 0 else 0
            except IndexError:
                lid = 0
            sig = sigs.get(kid)
            if sig is None:
                sig = sigs[kid] = {}
            lg = langs[lid]
            sig[lg] = sig.get(lg, 0) + 1
    return sigs


def entry_for(row: tuple, meta: dict, sigs: dict, is_hidden) -> dict:
    """One keyword's export entry -- the same fields, in the same order, as ever."""
    kid, m, a, first, last, dom = row[:6]
    term, norm, lang, is_ent, ent_type = meta.get(kid, ("?", "?", None, False, None))
    return {
        "term": term,
        "normalized": norm,
        "kind": (ent_type or "entity") if is_ent else "term",
        "language": lang,
        "mentions": m,
        "articles": a,
        "first_seen": str(first) if first else None,
        "last_seen": str(last) if last else None,
        "hidden": bool(is_hidden(norm)),
        "language_signature": sigs.get(kid, {}),
        # Attribution noise flag (field report #4: de-tagged English text):
        # the stored language disagrees with the signature's dominant one.
        # Evidence, not a correction — both values stay visible above.
        "language_mismatch": bool(dom is not None and dom != (lang or "?")),
    }


def fit_window(counts: dict[str, int], ceiling: int) -> int | None:
    """The largest per-language window ``c`` with ``sum(min(n, c)) <= ceiling``, or ``None``
    when every language's whole window fits. At least 1: a language is never dropped."""
    if sum(counts.values()) <= ceiling:
        return None
    lo_c, hi_c = 1, max(counts.values())
    while lo_c < hi_c:
        mid = (lo_c + hi_c + 1) // 2
        if sum(min(n, mid) for n in counts.values()) <= ceiling:
            lo_c = mid
        else:
            hi_c = mid - 1
    return lo_c


class ZipJob:
    """One per-language keyword-log archive, written to disk a batch at a time.

    Everything here is proportional to a BATCH, never to the corpus: a shard is opened as a
    zip member and its entries are appended as they are built, the digests are streaming
    accumulators, and the families the summary embeds are built over a bounded basis.
    """

    def __init__(self, *, hooks: ZipHooks, db, maps: ArticleMaps, ranker: Ranker,
                 out_dir: Path | None,
                 is_hidden, overrides: dict, supergroups: list, corpus: dict, method: str,
                 per_source_concentration: list, suspects_total: int, suspects_capped: bool,
                 page_info: dict, max_bytes: int | None, batch: int, check, disk_watch,
                 window_note: dict | None, basis_per_language: int | None,
                 basis_budget_rows: int) -> None:
        self.hooks = hooks
        self.db, self.maps, self.ranker, self.out_dir = db, maps, ranker, out_dir
        self.basis_counts: dict[str, int] = {}
        self.is_hidden, self.overrides, self.supergroups = is_hidden, overrides, supergroups
        self.corpus, self.method = corpus, method
        self.per_source_concentration = per_source_concentration
        self.suspects_total, self.suspects_capped = suspects_total, suspects_capped
        self.page_info, self.max_bytes, self.batch = page_info, max_bytes, batch
        self.check, self.disk_watch, self.window_note = check, disk_watch, window_note
        self.summary_payload: dict | None = None
        # The families are grouped over the first ``basis_per_language`` keywords of each
        # language's window, or over the whole window when that is None. The number is sized
        # from the machine (see memory_plan), never fixed.
        self.basis_per_language = basis_per_language
        self.basis_budget_rows = basis_budget_rows

    def _path(self) -> Path:
        d = self.out_dir
        if d is None:
            d = Path(tempfile.gettempdir())
        # mkstemp, not pid + clock: two exports in the same millisecond shared a name, and one
        # deleted the other's archive once it had been sent.
        return scratch_file(ZIP_TMP_PREFIX, ".zip", d)

    def _build_summary(self, sw: StopwordAcc, ring: RingAcc, fam: list, total_keep: int) -> dict:
        _fam_cap = self.hooks.families_cap()
        fam.sort(key=lambda t: t[0])
        families = build_families([it for _k, it in fam], self.overrides)
        # Only the families that are EMBEDDED are turned into dicts: the rest would sit in memory
        # for nothing while the summary is written.
        shown_families = families[:_fam_cap] if _fam_cap and len(families) > _fam_cap else families
        _families_shown = [f.to_dict() for f in shown_families]
        whole = self.basis_per_language is None
        return {
            "corpus": self.corpus,
            "method": self.method,
            "families": _families_shown,
            "families_provenance": {
                "shown": len(_families_shown),
                "total": len(families),
                "omitted": len(families) - len(_families_shown),
                "sorted_by": "mentions (desc)",
                # What the grouping was given, and what limits it. The limit is MEMORY, not time:
                # the grouping is linear in its input (a token index, not a pairwise comparison),
                # and its working set is about 2 KB per keyword, so the window it may hold is
                # sized from the memory available when the export started.
                "basis_per_language": self.basis_per_language,
                "basis_keywords": sum(self.basis_counts.values()),
                "basis_is_whole_window": whole,
                "basis_budget_keywords": self.basis_budget_rows,
                "note": (
                    "Only the top families are embedded here (the full per-keyword family dump "
                    "is large, redundant with keywords/<lang>.json, and unused by "
                    "analyze_keyword_log.py). Set OO_KEYWORD_LOG_FAMILIES=0 to embed all. "
                    + (
                        "Families are grouped over the WHOLE window "
                        f"({sum(self.basis_counts.values())} keywords). "
                        if whole else
                        "Families are grouped over the first "
                        f"{self.basis_per_language} keywords of each language's window "
                        f"({sum(self.basis_counts.values())} keywords in all, the largest set "
                        f"that fits the {self.basis_budget_rows}-keyword budget); the rest of "
                        "the window is in the shards but not in a family. "
                    )
                    + "The budget is a tenth of the memory available when the export started, "
                    "at about 2 KB per keyword: it protects the machine, and a machine with "
                    "more free memory groups more."
                ),
            },
            "overrides": [
                {"normalized_term": term, **data} for term, data in sorted(self.overrides.items())
            ],
            "supergroups": self.supergroups,
            "stopword_candidates": self.hooks.stopword_doc(sw.result()),
            "ring_candidates": self.hooks.ring_doc(ring.result()),
            "per_source_concentration": {
                "suspects": self.per_source_concentration,
                "suspects_total": self.suspects_total,
                "list_capped_at_200": self.suspects_capped,
                "thresholds": {
                    "min_articles_with_keyword": 10,
                    "min_source_articles": 10,
                    "min_share_of_keyword": 0.9,
                    "min_share_of_source": 0.25,
                },
            },
        }

    def write(self, keep: dict[str, int], omitted: dict[str, int]) -> Path:
        """Write one complete archive with at most ``keep[lang]`` keywords per language."""
        first_round = self.summary_payload is None
        sw = self.hooks.new_stopword_acc(self.is_hidden) if first_round else None
        ring = self.hooks.new_ring_acc(self.is_hidden) if first_round else None
        fam: list = []
        if first_round:
            self.basis_counts = {}
        path = self._path()
        # A small archive is compressed as hard as it always was; a large one at zlib's middle
        # level, which is ~3x faster for ~3 % more bytes and is what makes millions of
        # entries finish in minutes rather than hours.
        # (200,000 entries is the default export -- 5,000 keywords over a few dozen languages --
        # which keeps the level, and so the bytes, it always had.)
        level = 9 if sum(keep.values()) <= 200_000 else 6
        ok = False
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as z:
                for lang in sorted(keep):
                    n = keep[lang]
                    with z.open(
                        f"keywords/{self.hooks.safe_lang_filename(lang)}.json", "w", force_zip64=True
                    ) as fh:
                        fh.write(
                            (
                                '{"language":' + json.dumps(lang, ensure_ascii=False)
                                + f',"count":{n},"keywords":['
                            ).encode("utf-8")
                        )
                        pos = 0
                        rows = itertools.islice(self.ranker.rows(lang), n)
                        for chunk in batched(rows, self.batch):
                            self.check()
                            self.disk_watch()
                            kids = [r[0] for r in chunk]
                            meta = fetch_meta(self.db, kids)
                            sigs = fetch_signatures(self.db, self.maps, kids)
                            parts = []
                            for r in chunk:
                                e = entry_for(r, meta, sigs, self.is_hidden)
                                parts.append(
                                    json.dumps(e, ensure_ascii=False, separators=(",", ":"))
                                )
                                if first_round:
                                    kid, m, a, _f, _l, dom = r[:6]
                                    okey = order_key(kid, m, dom is not None)
                                    mt = meta.get(kid, ("?", "?", None, False, None))
                                    assert sw is not None and ring is not None
                                    sw.feed(okey, m, a, dom, mt)
                                    ring.feed(okey, m, a, dom, mt)
                                    if self.basis_per_language is None or pos < self.basis_per_language:
                                        self.basis_counts[lang] = self.basis_counts.get(lang, 0) + 1
                                        if not e["hidden"]:
                                            fam.append((okey, {
                                                "term": e["term"], "normalized": e["normalized"],
                                                "kind": e["kind"], "mentions": e["mentions"],
                                                "articles": e["articles"],
                                            }))
                                pos += 1
                            fh.write(
                                (("," if pos > len(chunk) else "") + ",".join(parts)).encode("utf-8")
                            )
                        fh.write(b"]}")
                total_kw = sum(keep.values())
                if first_round:
                    assert sw is not None and ring is not None
                    self.summary_payload = self._build_summary(sw, ring, fam, total_kw)
                summary_doc = envelope(
                    kind="keyword-diagnostics", query={"format": "zip"}, count=total_kw,
                    payload=self.summary_payload,
                )
                langs_meta: list[dict[str, Any]] = [
                    {"code": lang, "keywords": keep[lang], "omitted_to_fit": omitted.get(lang, 0)}
                    for lang in sorted(keep)
                ]
                manifest = {
                    "export_schema": "oo-export-1",
                    "kind": "keyword-diagnostics-archive",
                    "app_version": summary_doc.get("app_version"),
                    "generated_at": summary_doc.get("generated_at"),
                    "corpus": self.corpus,
                    "languages": sorted(langs_meta, key=lambda m: -m["keywords"]),
                    "keywords_in_archive": total_kw,
                    "keywords_omitted_to_fit": sum(omitted.values()),
                    # None = no byte cap was asked for (max_mb=0): the archive is whole.
                    "max_bytes": self.max_bytes,
                    # Paging: per_lang/page/pages_total/has_more let the caller export the
                    # WHOLE corpus across several files when one page would exceed the cap.
                    **self.page_info,
                    "ranking_spilled_to_disk": self.ranker.spilled,
                    **({"window_clamped_to_fit_cap": self.window_note} if self.window_note else {}),
                    "note": (
                        "Per-language split of the keyword diagnostics log"
                        + (
                            ", zipped and trimmed to aim under max_bytes (the default, 9 MB, "
                            "keeps a shared file under the common 10 MB attachment limit; "
                            "summary.json is never trimmed, so a summary alone larger than "
                            "the cap leaves the file over it). "
                            if self.max_bytes is not None else
                            ", written with NO byte cap (max_mb=0): every keyword of the "
                            "requested window, however large the file. "
                        )
                        + "Read summary.json for the corpus-wide aggregates (top families, "
                        "super-groups, per-source concentration; families_provenance records "
                        "the family cap and basis) and keywords/<lang>.json for each "
                        "language's keywords (same per-keyword fields as the single-file log). "
                        "scripts/analyze_keyword_log.py reads this .zip directly. "
                        "keywords_omitted_to_fit > 0 means the lowest-mention keywords per "
                        "language were dropped to fit max_bytes — never silently; see the "
                        "per-language counts."
                    ),
                }
                z.writestr(
                    "summary.json",
                    json.dumps(summary_doc, ensure_ascii=False, separators=(",", ":")),
                )
                z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            ok = True
            return path
        finally:
            if not ok:
                unlink_quietly(path)


def unlink_quietly(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def resolve_max_bytes(fmt: str, max_mb: Any, default_bytes: int) -> int | None:
    """The archive's byte cap, or ``None`` for NO cap.

    ``max_mb`` is the request's own word: ``0`` = no cap (the whole window, however large),
    a positive number = that many MB. Left out, ``default_bytes`` (the env var / 9 MB default)
    applies, exactly as before. A non-number is "left out": called directly, a ``Query(None)``
    default arrives as the Query sentinel object, not as ``None`` (this code base's
    recurring trap)."""
    if fmt != "zip":
        return None
    if isinstance(max_mb, (int, float)) and not isinstance(max_mb, bool):
        if max_mb <= 0:
            return None
        # 256 bytes: below this a zip's own headers exceed the cap, so every language would be
        # trimmed to one keyword for nothing. It only forbids a meaningless cap; realistic ones
        # are megabytes.
        return max(256, int(max_mb * 1024 * 1024))
    return default_bytes


#: Trim rounds are bounded only so a pathological size estimate cannot loop forever: each round
#: shrinks every language by the ratio the last archive missed the cap by, times ``_TRIM_AIM``,
#: so an archive whose shards are the whole problem is under its cap in two or three rounds. 40
#: rounds at that rate is a window cut to a fraction of a percent, far past anything a cap can
#: ask of it: beyond that, what is over the cap is the summary, which is never trimmed.
_MAX_TRIM_ROUNDS = 40

#: Each trim aims ten per cent UNDER the cap: deflate's output is not linear in the entries kept,
#: so aiming exactly at the cap lands just over it about half the time and costs another rebuild.
_TRIM_AIM = 0.9


def finish_zip(
    job: ZipJob, keep: dict[str, int], omitted: dict[str, int] | None = None
) -> Path:
    """Build the per-language keyword-log ZIP on disk, aiming under the byte cap; return its path.

    Members: ``summary.json`` (the corpus-wide aggregates — families, super-groups,
    per-source concentration — the SAME data the single-file log carries minus the
    keyword list), ``keywords/<lang>.json`` (each language's keywords, same
    per-keyword fields), and ``manifest.json`` (what's inside + any omissions). The
    split mirrors the per-language export quota; JSON compresses ~8x so the archive
    is normally a few MB. While the compressed archive exceeds the cap the lowest-mention
    keywords are dropped PER LANGUAGE (equal-fair) and recorded — never a silent or
    anglicising cut — and the archive is rewritten, until it fits OR every language is down to
    one keyword. THE CAP IS NOT A GUARANTEE in that last case: ``summary.json`` and
    ``manifest.json`` are never trimmed, so an archive whose summary alone is larger than the cap
    is returned over it (the manifest's ``max_bytes`` is the cap that was asked for). The default
    cap (9 MB) exists so a shared archive stays under the common 10 MB attachment limit; it is a
    property of the default, not of the function. With no cap (``max_mb=0``) nothing is dropped,
    and nothing is held: the archive is written to a scratch file a batch at a time. The CALLER
    deletes the file once it has been sent."""
    keep = dict(keep)
    omitted = dict(omitted or {})
    path = job.write(keep, omitted)
    max_bytes = job.max_bytes
    for _ in range(_MAX_TRIM_ROUNDS):
        size = path.stat().st_size
        if max_bytes is None or size <= max_bytes:
            break
        ratio = max_bytes / size * _TRIM_AIM
        trimmed = {lang: new for lang, n in keep.items() if (new := max(1, int(n * ratio))) < n}
        if not trimmed:
            break  # nothing left to drop: what is over the cap is the summary, which is not trimmed
        unlink_quietly(path)
        for lang, new in trimmed.items():
            omitted[lang] = omitted.get(lang, 0) + (keep[lang] - new)
            keep[lang] = new
        path = job.write(keep, omitted)
    return path
