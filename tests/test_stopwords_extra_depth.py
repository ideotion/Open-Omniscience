"""A stopword file that nests too deeply is skipped, not an import-time crash of the extractor (R329, R319).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src.analytics.extract`` loads every ``configs/stopwords_extra/*.yml`` when the module is imported, and a malformed file is skipped rather than
crashing extraction. The loader was ``yaml.safe_load``: the pure-Python loader raises ``RecursionError`` at about 500 levels, which the
``except (OSError, yaml.YAMLError)`` did not catch, so a deeply nested file in that directory stopped the module from importing at all (and with
it every index pass). The shared loader (``src.utils.safe_yaml.load_safe_yaml``, depth guard from #1569) raises ``YAMLDepthError``, a
``yaml.YAMLError``, on both loader paths. A file whose top level is not a mapping used to fail on ``.get`` the same way.
"""

from __future__ import annotations

import pytest

from src.analytics import extract

DEPTH = 100_000


@pytest.fixture()
def stopwords_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "_STOPWORDS_EXTRA_DIR", tmp_path)
    return tmp_path


def test_a_file_nested_far_past_any_bound_is_skipped_and_its_neighbours_still_load(stopwords_dir):
    (stopwords_dir / "deep.yml").write_text("stopwords: " + "[" * DEPTH + "]" * DEPTH + "\n", encoding="utf-8")
    (stopwords_dir / "ok.yml").write_text("stopwords: [alpha, beta]\n", encoding="utf-8")
    loaded = extract._load_extra_stopwords_by_language()
    assert "deep" not in loaded, "the too-deep file was read as a stopword file"
    assert loaded == {"ok": frozenset({"alpha", "beta"})}


def test_a_block_style_file_nested_past_the_bound_is_skipped_too(stopwords_dir):
    (stopwords_dir / "deep.yml").write_text("".join("  " * i + "a:\n" for i in range(2_000)), encoding="utf-8")
    assert extract._load_extra_stopwords_by_language() == {}


@pytest.mark.parametrize("body", ["- a\n- b\n", "just a scalar\n", "42\n"])
def test_a_file_whose_top_level_is_not_a_mapping_is_skipped(stopwords_dir, body):
    (stopwords_dir / "odd.yml").write_text(body, encoding="utf-8")
    assert extract._load_extra_stopwords_by_language() == {}


@pytest.mark.parametrize("body", ["stopwords: 42\n", "stopwords: abc\n", "stopwords: {a: b}\n"])
def test_a_file_whose_stopwords_value_is_not_a_list_is_skipped(stopwords_dir, body):
    (stopwords_dir / "odd.yml").write_text(body, encoding="utf-8")
    (stopwords_dir / "ok.yml").write_text("stopwords: [alpha]\n", encoding="utf-8")
    assert extract._load_extra_stopwords_by_language() == {"ok": frozenset({"alpha"})}


def test_a_file_that_is_not_valid_utf8_is_skipped(stopwords_dir):
    (stopwords_dir / "bad.yml").write_bytes(b"stopwords: [caf\xe9]\n")
    (stopwords_dir / "ok.yml").write_text("stopwords: [alpha]\n", encoding="utf-8")
    assert extract._load_extra_stopwords_by_language() == {"ok": frozenset({"alpha"})}


def test_an_empty_stopwords_key_is_an_empty_set_not_a_skip(stopwords_dir):
    (stopwords_dir / "empty.yml").write_text("stopwords:\n", encoding="utf-8")
    assert extract._load_extra_stopwords_by_language() == {"empty": frozenset()}


def test_the_shipped_stopword_files_still_load():
    # the real directory, unpatched: the shared loader reads the shipped files to the same sets (the set itself is pinned byte-for-byte by
    # tests/test_analytics_extract.py)
    loaded = extract._load_extra_stopwords_by_language()
    assert loaded and all(isinstance(words, frozenset) for words in loaded.values())
