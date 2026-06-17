"""Curated per-language keyword BASELINE (Item AC, slice 1).

A small, network-free, dated catalog of known keywords pre-classified along two
axes — a semantic ``type`` (event / disease / technology / currency …) and a
``topic``/domain (politics / economy / health …). It is the POSITIVE baseline: a
keyword that matches arrives PRE-TAGGED, a quality reference the analyzer grows
over time (curated-small + analyzer-grown — the maintainer's Q1 default; the file
format is ready for a dated Wikidata-P31 snapshot to populate later).

Honesty by construction: a baseline tag is a LABELLED ASSERTION, never ground
truth and never a score; every applied tag carries its ``source`` provenance and
is user-overridable. Local-only: bundled YAML under
``configs/keyword_baseline/<lang>.yml``, read at index time; a missing file is a
no-op; ``OO_KEYWORD_TAGS=0`` disables the whole layer.

Design doc: docs/design/KEYWORD_BASELINE_AND_MANAGEMENT.md.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

# Review vintage of the curated baseline files (format "YYYY-MM", freshness-tested)
# — NOT a per-keyword date. Grown from the keyword-diagnostics logs between reviews.
BASELINE_AS_OF = "2026-06"

# The two tag axes (Q2 = both). A keyword may carry one of each (or neither).
_AXES = ("type", "topic")

_BASE = Path(__file__).resolve().parents[2] / "configs" / "keyword_baseline"


def _enabled() -> bool:
    return os.getenv("OO_KEYWORD_TAGS", "1") != "0"


@lru_cache(maxsize=32)
def _load(language: str) -> dict[str, tuple[tuple[str, str], ...]]:
    """``{normalized_term: ((axis, tag), …)}`` for one language.

    A missing or malformed file yields ``{}`` (a no-op, never an invented tag).
    Cached per language; the cache is process-lifetime (the bundled files don't
    change at runtime). Keys are casefolded to match the extractor's normalisation.
    """
    path = _BASE / f"{language}.yml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text("utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, tuple[tuple[str, str], ...]] = {}
    for norm, axes in (data.get("baseline_keywords") or {}).items():
        if not isinstance(axes, dict):
            continue
        pairs = tuple((a, str(axes[a])) for a in _AXES if axes.get(a))
        if pairs:
            out[str(norm).casefold()] = pairs
    return out


def baseline_tags(language: str | None, normalized: str) -> tuple[tuple[str, str], ...]:
    """The ``((axis, tag), …)`` a curated baseline asserts for ``(language,
    normalized)``, or ``()`` when there is no match / the layer is disabled / the
    language is unknown. Never invents a tag."""
    if not _enabled() or not language:
        return ()
    return _load(language).get(normalized.casefold(), ())
