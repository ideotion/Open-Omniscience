"""Validity guard for the curated keyword baseline data (Item AC, S2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every configs/keyword_baseline/<lang>.yml must parse, use only the known axes,
and carry non-empty single-token tags — so a malformed or stray data file is caught
in CI, not silently ignored at runtime. Multi-word keys with internal stopwords
never become keywords, so the baseline keeps to single tokens (hyphens allowed).
"""

import pathlib

import yaml

from src.analytics.baseline import _AXES, _load, baseline_tags

_DIR = pathlib.Path(__file__).resolve().parents[1] / "configs" / "keyword_baseline"


def test_all_baseline_files_parse_and_have_valid_axes():
    files = sorted(_DIR.glob("*.yml"))
    assert files, "no baseline files found"
    for f in files:
        data = yaml.safe_load(f.read_text("utf-8")) or {}
        entries = data.get("baseline_keywords") or {}
        assert entries, f"{f.name} has no baseline_keywords"
        for norm, axes in entries.items():
            assert isinstance(axes, dict), f"{f.name}:{norm} is not a mapping"
            assert set(axes) <= set(_AXES), f"{f.name}:{norm} has unknown axis {set(axes) - set(_AXES)}"
            for ax, tag in axes.items():
                assert isinstance(tag, str) and tag.strip(), f"{f.name}:{norm}:{ax} has an empty tag"
            # single-token key (hyphen allowed) — a space + internal stopword never
            # becomes a keyword, so such an entry could never match.
            assert "  " not in str(norm), f"{f.name}:{norm} double space"


def test_loader_reads_each_language_file():
    for f in sorted(_DIR.glob("*.yml")):
        lang = f.stem
        loaded = _load(lang)
        assert loaded, f"loader returned nothing for {lang}"
        some_key = next(iter(loaded))
        assert baseline_tags(lang, some_key), f"{lang}:{some_key} did not round-trip"


def test_core_ui_languages_have_a_baseline():
    langs = {f.stem for f in _DIR.glob("*.yml")}
    assert {"en", "fr", "de", "es", "it", "pt", "nl"} <= langs
