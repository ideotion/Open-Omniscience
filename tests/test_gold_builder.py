"""
S5.3 — the IR gold-set BUILDER (the measure-before-trust instrument).

The save path is the honesty-critical part: it must write the EXACT ir_eval gold-set format,
VALIDATE by round-trip (a bad grade / duplicate id / empty id raises LOUDLY, never a silent
bad file), swap atomically (an invalid set never lands at the destination), and report an
honest coverage meter. Sampling from top keywords (never inventing a query) is proven where a
corpus fixture is cheap; the DB-backed sample_queries is exercised in CI.
"""

from __future__ import annotations

import json

import pytest

from src.analytics import gold_builder as GB
from src.analytics.ir_eval import GoldSetError, load_gold_set


def test_save_writes_exact_format_and_roundtrips(tmp_path):
    dest = tmp_path / "gold.json"
    out = GB.build_and_save_gold_set(
        str(dest),
        [
            {"id": "q_inflation", "query": "inflation", "language": "en", "axis": "topic",
             "relevances": {"101": 2, "102": 1, "103": 0}},
            {"id": "q_wahl", "query": "wahl", "language": "de", "axis": "cross-lingual",
             "relevances": {"201": 2}},
        ],
    )
    assert out["saved"] == str(dest) and dest.is_file()
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert [q["id"] for q in data["queries"]] == ["q_inflation", "q_wahl"]
    # it is the exact ir_eval format — load_gold_set accepts it
    gold = load_gold_set(dest)
    assert len(gold) == 2 and gold[0].relevances == {"101": 2, "102": 1, "103": 0}


def test_coverage_meter_counts_per_language_and_axis(tmp_path):
    dest = tmp_path / "g.json"
    out = GB.build_and_save_gold_set(
        str(dest),
        [
            {"id": "a", "query": "x", "language": "en", "axis": "topic", "relevances": {"1": 2}},
            {"id": "b", "query": "y", "language": "fr", "axis": "topic", "relevances": {"2": 1}},
            {"id": "c", "query": "z", "language": "en", "axis": "topic", "relevances": {}},  # ungraded
        ],
    )
    cov = out["coverage"]
    assert cov["queries"] == 3 and cov["graded_queries"] == 2  # 'c' has no judgement
    assert cov["total_judgements"] == 2
    assert cov["by_language"] == {"en": 1, "fr": 1} and cov["by_axis"] == {"topic": 2}


def test_bad_grade_raises_and_leaves_no_file_at_destination(tmp_path):
    dest = tmp_path / "bad.json"
    with pytest.raises(GoldSetError):
        GB.build_and_save_gold_set(
            str(dest),
            [{"id": "q", "query": "x", "relevances": {"1": 3}}],  # 3 is not a valid grade
        )
    # the atomic-swap guarantee: an invalid gold set never lands at the destination
    assert not dest.is_file()
    assert not (tmp_path / "bad.json.tmp").is_file()  # the temp is cleaned up too


def test_duplicate_id_and_empty_set_are_rejected(tmp_path):
    with pytest.raises(GoldSetError):
        GB.build_and_save_gold_set(
            str(tmp_path / "d.json"),
            [{"id": "q", "query": "a", "relevances": {}},
             {"id": "q", "query": "b", "relevances": {}}],
        )
    with pytest.raises(ValueError):
        GB.build_and_save_gold_set(str(tmp_path / "e.json"), [])


def test_missing_directory_is_a_loud_error(tmp_path):
    with pytest.raises(ValueError):
        GB.build_and_save_gold_set(
            str(tmp_path / "nope" / "g.json"),
            [{"id": "q", "query": "x", "relevances": {"1": 1}}],
        )


def test_slug_is_stable_and_bounded():
    assert GB._slug("Rio Tinto") == "rio_tinto"
    assert GB._slug("  Élection 2027!! ") == "lection_2027"  # non-ascii/punct collapse
    assert len(GB._slug("x" * 200)) <= 40


def test_non_numeric_grade_raises_not_silently_dropped(tmp_path):
    # skeptic #6: a maintainer's judgement must never vanish silently.
    with pytest.raises(ValueError):
        GB.build_and_save_gold_set(
            str(tmp_path / "g.json"),
            [{"id": "q", "query": "x", "relevances": {"1": "relevant", "2": 2}}],
        )
    assert not (tmp_path / "g.json").is_file()


def test_float_and_bool_grades_are_rejected_not_coerced(tmp_path):
    # skeptic #7: int(2.9)==2 / int(True)==1 must NOT land as a clean valid grade.
    for bad in (2.9, True, 0.9):
        with pytest.raises(ValueError):
            GB.build_and_save_gold_set(
                str(tmp_path / "g.json"), [{"id": "q", "query": "x", "relevances": {"1": bad}}]
            )


def test_string_digit_grade_is_accepted(tmp_path):
    dest = tmp_path / "g.json"
    GB.build_and_save_gold_set(str(dest), [{"id": "q", "query": "x", "relevances": {"1": "2"}}])
    assert load_gold_set(dest)[0].relevances == {"1": 2}


def test_conflicting_duplicate_docid_is_rejected(tmp_path):
    # skeptic #8: int 2 and str "2" for the same doc with different grades must not clobber.
    with pytest.raises(ValueError):
        GB.build_and_save_gold_set(
            str(tmp_path / "g.json"),
            [{"id": "q", "query": "x", "relevances": {2: 2, "2": 0}}],
        )
