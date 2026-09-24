"""WHICH ENGINE produced an article's derived rows -- the per-article stamp R24 needs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R24 (2026-09-22) rules that a same-engine backup carries its derived rows instead of
paying a re-extraction it does not need. That needs an answer to "same engine as
what?", and the tree had none: no version constant, no fingerprint, nothing in a
backup's manifest finer than ``app_version``. Three facts shaped the answer.

1. **ENGINE IDENTITY IS A PROPERTY OF EACH ARTICLE, NOT OF THE BACKUP.** A backup's
   manifest could only say which engine the exporting instance runs NOW. An instance
   that was upgraded half-way through its life holds rows from several engines under
   one version string, and nothing records which article came from which. So the
   stamp is a row in ``article_index_stamps``, written by ``index_article`` in the same
   pass as the rows it certifies -- never by the exporter, never copied by the merge.

1b. **...AND OF THE INPUTS IT READ.** Identical engines produce identical rows only from
   identical inputs, and an article's inputs can change after it is indexed without it
   being indexed again: a wiki body replaced, a country adopted from a later merge, a
   source renamed so its self-name suppression reads differently. So the stamp also
   records :func:`index_inputs_digest` of what the pass read, and a restore recomputes
   it from the incoming row. A stamp is then a statement that stays true for ever --
   "engine E, on inputs I, produced these rows" -- and nothing has to remember to
   invalidate it when an input moves.

2. **"THE ENGINE" IS MORE THAN THE CODE.** The same commit extracts differently on two
   machines when an optional dictionary is installed on one of them (``simplemma``
   lemmatises, ``jieba``/``janome``/``pythainlp`` segment zh/ja/th, ``py3langid``
   deduces a missing language, ``vaderSentiment`` scores English), when an operator
   flips one of the three switches, when a generated ``configs/cities.yml`` shadows
   the shipped sample gazetteer, or when the interpreter's Unicode tables differ
   (case-folding and ``\\w`` both read them). Every one of those is an input here.

3. **THE CODE IS HASHED, NOT VERSIONED BY HAND.** A hand-bumped constant is correct
   exactly as long as every contributor remembers it, which is the failure this
   ledger keeps recording. The identity hashes the BYTES of the modules and data
   files a pass reads, so any change changes it, with no one having to decide that it
   mattered. That is deliberately strict: an unrelated edit to ``store.py`` makes two
   builds "different engines", which costs a re-extraction and never a wrong row.
   ``tests/test_index_engine_stamp.py`` runs a real pass in a fresh interpreter and
   fails if it loads a module or opens a data file this list does not name -- so the
   list cannot silently fall behind the code, which is the only way a hash of the code
   can lie.

THE CARRY COMPARES AGAINST THE BASELINE IDENTITY ONLY. The post-merge re-index always
uses ``get_extractor("baseline")``, so the question a carry must answer is "would the
re-index this corpus is about to run reproduce these rows?" -- an article stamped by
any other extractor (spaCy at ingest) can never be carried, and should not be.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from functools import cache, lru_cache
from pathlib import Path

#: The identity's own format. Bump it only if the COMPONENTS below change shape, so an
#: old stamp can never collide with a new one computed from different inputs.
IDENTITY_SCHEMA = "oo-index-engine-1"

#: The prefix every stamp carries. A stamp is ``e1-`` + 32 hex digits = 35 characters,
#: inside ``Article.index_engine``'s String(40).
STAMP_PREFIX = "e1-"

_REPO = Path(__file__).resolve().parents[2]

#: Every module whose code shapes what ``index_article`` writes: the keyword pass, the
#: language deduction, sentiment, the When x Where x Who stores and extractors, the
#: markup strip that runs before any of them, the country/city resolution, the source
#: self-name rule and the top-keyword arithmetic (both in ``store.py``). Measured, not
#: read: a fresh interpreter running one full pass per language loads exactly these,
#: plus the package ``__init__`` files and the modules in :data:`NOT_OUTPUT_AFFECTING`.
ENGINE_MODULES: tuple[str, ...] = (
    "src/analytics/__init__.py",
    "src/analytics/extract.py",
    "src/analytics/langdetect.py",
    "src/analytics/lemma.py",
    "src/analytics/managed.py",
    "src/analytics/segmentation.py",
    "src/analytics/sentiment.py",
    "src/analytics/store.py",
    "src/catalog/__init__.py",
    "src/catalog/aggregates.py",
    "src/catalog/cities.py",
    "src/catalog/countries.py",
    "src/services/__init__.py",
    "src/services/stopwords.py",
    "src/timemap/__init__.py",
    "src/timemap/dateextract.py",
    "src/timemap/datestore.py",
    "src/timemap/entextract.py",
    "src/timemap/locextract.py",
    "src/timemap/whostore.py",
    "src/utils/markup_blocks.py",
)

#: The data files those modules read. ``cities.yml`` is GENERATED and preferred when
#: present; the sample is the shipped fallback -- both are hashed, present or absent,
#: so a machine that generated the full gazetteer is a different engine from one that
#: did not, which it is.
ENGINE_DATA_GLOBS: tuple[str, ...] = (
    "configs/stopwords_extra/*.yml",
    "configs/stopwords_iso/*.txt",
    "configs/cities.yml",
    "configs/cities.sample.yml",
)

#: Optional distributions whose presence or version changes extraction. Their data
#: files (simplemma's dictionaries, VADER's lexicon, jieba's dictionary) live inside
#: the distribution, so the version is what identifies them.
ENGINE_DISTRIBUTIONS: tuple[str, ...] = (
    "simplemma",
    "vaderSentiment",
    "py3langid",
    "jieba",
    "janome",
    "pythainlp",
    "spacy",
)

#: Modules a pass loads that do NOT shape its output, each with the reason. A module
#: in neither this map nor :data:`ENGINE_MODULES` fails the closure test -- the same
#: "a new thing must be triaged" rule the merge's completeness registries enforce.
NOT_OUTPUT_AFFECTING: dict[str, str] = {
    "src/analytics/baseline.py": (
        "baseline TAGS for a keyword the pass CREATES; a restore's keywords are created "
        "by the merge in both modes, so a carry and a re-index cannot differ here"
    ),
    "src/analytics/engine_identity.py": "this module; it computes the stamp, not the rows",
    "src/services/duckduckgo.py": "imported by the services package; makes no call in a pass",
    "src/utils/logging_config.py": "log formatting only",
}

#: Files a pass opens that do not shape its output, by the same rule.
NOT_OUTPUT_AFFECTING_FILES: dict[str, str] = {
    "configs/keyword_baseline/": "baseline tags on keyword creation (see baseline.py above)",
    "audit/duckduckgo.log": "the services package's audit log, opened on import",
    # An editable install's own packaging records. importlib.metadata walks them when
    # this module asks for the ENGINE_DISTRIBUTIONS' versions; nothing extracts from them.
    "open_omniscience.egg-info/": "package metadata, read by importlib.metadata",
    "__editable__": "the editable install's import path hook",
}


def _read(rel: str) -> bytes | None:
    try:
        return (_REPO / rel).read_bytes()
    except OSError:
        return None


def engine_files() -> list[str]:
    """Every repo-relative file the code digest covers, sorted -- the list is part of
    the identity, so it must be deterministic across machines and filesystems."""
    out = set(ENGINE_MODULES)
    for pattern in ENGINE_DATA_GLOBS:
        if any(ch in pattern for ch in "*?["):
            out.update(str(p.relative_to(_REPO)) for p in _REPO.glob(pattern) if p.is_file())
        else:
            out.add(pattern)
    return sorted(out)


@lru_cache(maxsize=1)
def code_digest() -> str:
    """sha256 over (path, bytes) of every engine file. A MISSING file contributes its
    name and an explicit absence marker rather than nothing, so "absent" and "empty"
    are different engines and a deleted gazetteer cannot hash like an untouched one.

    Cached for the process: the files a running app extracts with do not change under
    it, and a pass must not re-read ~200 files per article."""
    h = hashlib.sha256()
    for rel in engine_files():
        data = _read(rel)
        h.update(rel.encode())
        h.update(b"\x00")
        if data is None:
            h.update(b"<absent>")
        else:
            h.update(str(len(data)).encode())
            h.update(b"\x00")
            h.update(data)
        h.update(b"\x01")
    return h.hexdigest()


@cache
def _dist_version(dist: str) -> str | None:
    """The installed version of one distribution, or None when it is absent."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - stdlib on every supported Python
        return None
    try:
        return version(dist)
    except PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - a broken metadata record is an unknown, not a crash
        return "<unreadable>"


def _switches() -> dict[str, bool]:
    """The three operator switches that change what a pass writes, read LIVE through
    the very predicates extraction itself consults -- never re-derived here, so the
    identity and the extraction cannot disagree about whether a switch is on."""
    from src.analytics.extract import code_token_filter_enabled
    from src.analytics.lemma import extraction_lemma_enabled
    from src.analytics.segmentation import _enabled as segmentation_enabled

    return {
        "lemma": bool(extraction_lemma_enabled()),
        "segmentation": bool(segmentation_enabled()),
        "code_token_filter": bool(code_token_filter_enabled()),
    }


def _gazetteer_digest(extractor) -> str | None:
    gaz = getattr(extractor, "gazetteer", None) or getattr(
        getattr(extractor, "_baseline", None), "gazetteer", None
    )
    if not gaz:
        return None
    blob = json.dumps(sorted(gaz.items()), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def engine_components(extractor=None, *, extractor_name: str | None = None) -> dict:
    """The inputs the stamp is a hash of, readable -- for a diagnostic that has to say
    WHY two stamps differ, not only that they do."""
    name = extractor_name or getattr(extractor, "name", None) or "baseline"
    return {
        "schema": IDENTITY_SCHEMA,
        "extractor": name,
        "gazetteer": _gazetteer_digest(extractor) if extractor is not None else None,
        "code": code_digest(),
        "distributions": {d: _dist_version(d) for d in ENGINE_DISTRIBUTIONS},
        "switches": _switches(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "unicode": unicodedata.unidata_version,
    }


@lru_cache(maxsize=64)
def _stamp_for(blob: str) -> str:
    return STAMP_PREFIX + hashlib.sha256(blob.encode()).hexdigest()[:32]


def engine_id(extractor=None, *, extractor_name: str | None = None) -> str:
    """The stamp for the engine that would run with ``extractor`` right now."""
    blob = json.dumps(
        engine_components(extractor, extractor_name=extractor_name),
        sort_keys=True,
        separators=(",", ":"),
    )
    return _stamp_for(blob)


def baseline_engine_id() -> str:
    """The identity a post-merge re-index would stamp -- what a carry must match."""
    return engine_id(extractor_name="baseline")


#: The prefix every inputs digest carries (``i1-`` + 32 hex digits = 35 characters).
INPUTS_PREFIX = "i1-"


def date_part(value) -> str | None:
    """The calendar date of a stored timestamp, as ``YYYY-MM-DD``, or None.

    One function for both sides of the comparison, because the two sides hold the value
    differently: ``index_article`` has the ORM's ``datetime``, the restore reads the raw
    column through sqlite3 and gets the stored text. Only the DATE matters -- it is what
    ``observed_on`` and the date extractor's anchor are made of -- so a time-of-day edit
    is not an input change."""
    if value is None:
        return None
    if hasattr(value, "date") and callable(value.date):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        from datetime import date

        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def index_inputs_digest(
    *,
    text: str,
    raw_content: str | None,
    title: str | None,
    language: str | None,
    detected_language: str | None,
    observed: str | None,
    country: str | None,
    self_forms,
) -> str:
    """A hash of EVERYTHING one article contributes to what ``index_article`` writes.

    Each field is here because a reader of it was found, not because it seemed wise:

      * ``text`` -- the article text the keyword pass, sentiment and the language
        deduction read (``get_content()``: decompressed when stored compressed);
      * ``raw_content`` -- the ``content`` COLUMN, which the date, place and entity
        stores read directly instead of ``get_content()``. The two differ exactly when
        an article is stored compressed, and then those stores see an empty body;
      * ``title`` -- passed to the extractor beside the text;
      * ``language`` and ``detected_language`` -- both, raw: the keyword pass reads the
        first non-empty one, the date extractor reads ``language`` alone;
      * ``observed`` -- the date of ``published_at or created_at``: every mention's
        ``observed_on``, and the anchor that resolves "yesterday";
      * ``country`` -- the article's own, raw: the place extractor's ``source_country``,
        and what a re-index denormalises onto each mention;
      * ``self_forms`` -- the source's self-name forms, the words the keyword pass
        suppresses as the source naming itself. They come from the SOURCE row, so an
        article merged onto a differently-named local source has different inputs.
    """
    payload = {
        "text": hashlib.sha256((text or "").encode("utf-8", "surrogatepass")).hexdigest(),
        "raw": hashlib.sha256((raw_content or "").encode("utf-8", "surrogatepass")).hexdigest(),
        "title": title or "",
        "language": language or "",
        "detected_language": detected_language or "",
        "observed": observed,
        "country": country or "",
        "self_forms": sorted(self_forms or ()),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return INPUTS_PREFIX + hashlib.sha256(blob.encode("utf-8", "surrogatepass")).hexdigest()[:32]
