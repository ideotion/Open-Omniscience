"""The keyword-log analyzer reads a numbered set of 1 MB files (scripts/analyze_keyword_log.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A person who cannot upload a 220 MB archive sends the numbered files instead, so the analyzer must
read them: the folder that holds a set, any one file of it, or its manifest. The negative space is
what a half-uploaded set does: a missing or damaged part is named on stderr and the rest is read
anyway, because evidence that arrived is not thrown away for evidence that did not. The script has
to run without the app installed, so it carries its own copy of the piece-joining logic; the test
holds that copy to the app's answers.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import random
import zipfile
from pathlib import Path

import pytest

from src.analytics import upload_parts as up

_ROOT = Path(__file__).resolve().parents[1]
STEM = "oo-keyword-log-20261001-000000"


def _analyzer():
    spec = importlib.util.spec_from_file_location(
        "analyze_keyword_log_parts_t", _ROOT / "scripts" / "analyze_keyword_log.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _kw(i: int, lang: str) -> dict:
    # a few random-looking bytes per record so the zip cannot squeeze the set into two parts
    noise = random.Random(f"{lang}{i}").randbytes(12).hex()
    return {"keyword": f"{lang}-term-{i:05d}-" + "x" * (i % 17), "mentions": 1000 - i,
            "language": lang, "sig": noise}


def _build(folder: Path, *, stem: str = STEM, cap: int = 6_000, per_lang: int = 600,
           summary: dict | None = None) -> tuple[dict[str, list[dict]], dict]:
    """A real set from the real writer: two languages, ranked, spread over several parts."""
    w = up.PartWriter(folder, stem=stem, cap=cap)
    data: dict[str, list[dict]] = {}
    for lang in ("fr", "en"):
        data[lang] = [_kw(i, lang) for i in range(per_lang)]
        g = up.RecordGroup(f"keywords/{lang}.json", {"language": lang}, "keywords", per_lang)
        for rec in data[lang]:
            w.add_record(g, json.dumps(rec, separators=(",", ":")))
    w.add_front_json_document("summary.json", summary or {"kind": "keyword-diagnostics",
                                                          "data": {"families": [{"t": 1}], "n": 7}})
    return data, w.finish()


def _expected(data: dict[str, list[dict]]) -> list[dict]:
    return data["en"] + data["fr"]  # languages in name order, each in rank order


def test_the_folder_a_part_and_the_manifest_all_give_the_same_log(tmp_path):
    data, manifest = _build(tmp_path)
    assert manifest["part_count"] >= 4, "the set must span several parts for this to test anything"
    an = _analyzer()
    from_folder = an.load_log(tmp_path)
    assert from_folder["data"]["keywords"] == _expected(data)
    assert from_folder["data"]["n"] == 7 and from_folder["kind"] == "keyword-diagnostics"
    one_part = tmp_path / manifest["parts"][2]["name"]
    assert an.load_log(one_part)["data"]["keywords"] == _expected(data)
    assert an.load_log(tmp_path / f"{STEM}-manifest.zip")["data"]["keywords"] == _expected(data)


def test_a_missing_part_is_named_and_the_rest_is_still_read(tmp_path, capsys):
    data, manifest = _build(tmp_path)
    gone = manifest["parts"][3]["name"]
    (tmp_path / gone).unlink()
    doc = _analyzer().load_log(tmp_path)
    err = capsys.readouterr().err
    assert gone in err and "missing 1" in err and "Reading what is there" in err
    got = doc["data"]["keywords"]
    assert 0 < len(got) < len(_expected(data))
    assert all(k in _expected(data) for k in got), "nothing invented, only fewer"


def test_a_damaged_part_is_named(tmp_path, capsys):
    _data, manifest = _build(tmp_path)
    bad = tmp_path / manifest["parts"][1]["name"]
    raw = bytearray(bad.read_bytes())
    raw[len(raw) // 2] ^= 0xFF  # one flipped byte: the size is unchanged, the checksum is not
    bad.write_bytes(bytes(raw))
    # a flipped byte may also break the part itself; the warning is what is asserted
    with contextlib.suppress(zipfile.BadZipFile, ValueError, OSError):
        _analyzer().load_log(tmp_path)
    err = capsys.readouterr().err
    assert bad.name in err and "differing from the manifest 1" in err


def test_without_a_manifest_the_part_names_still_say_how_many_there_should_be(tmp_path, capsys):
    _data, manifest = _build(tmp_path)
    (tmp_path / f"{STEM}-manifest.zip").unlink()
    (tmp_path / manifest["parts"][-1]["name"]).unlink()
    _analyzer().load_log(tmp_path)
    err = capsys.readouterr().err
    assert f"{manifest['part_count'] - 1} of {manifest['part_count']} parts found" in err


def test_a_summary_cut_into_pieces_is_joined_back(tmp_path):
    big = {"kind": "keyword-diagnostics",
           "data": {"families": [{"t": i, "pad": "p" * 200} for i in range(300)], "n": 7}}
    _data, manifest = _build(tmp_path, summary=big)
    members = [m["member"] for p in manifest["parts"] for m in p["members"]]
    assert any(m.startswith("summary.s") for m in members), "the summary must have been cut"
    doc = _analyzer().load_log(tmp_path)
    assert doc["data"]["families"] == big["data"]["families"] and doc["data"]["n"] == 7


def test_the_scripts_copy_of_the_joiner_agrees_with_the_apps(tmp_path):
    rnd = random.Random(5)
    value = {"a": [{"i": i, "s": "q" * rnd.randrange(5, 300)} for i in range(200)],
             "b": {"c": list(range(300)), "d": "tail"}, "e": 3}
    pieces = list(up.split_json_value(value, 900))
    assert len(pieces) > 4
    shuffled_shells = sorted(pieces, key=lambda p: p["slice"] is not None)
    assert _analyzer()._join_json_pieces(shuffled_shells) == up.join_json_pieces(shuffled_shells) == value


def test_an_ordinary_zip_and_a_json_export_are_still_read_as_before(tmp_path):
    an = _analyzer()
    zpath = tmp_path / "oo-keyword-log.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("summary.json", json.dumps({"kind": "keyword-diagnostics", "data": {"n": 1}}))
        z.writestr("keywords/en.json", json.dumps({"keywords": [_kw(1, "en")]}))
    assert an.load_log(zpath)["data"]["keywords"] == [_kw(1, "en")]
    jpath = tmp_path / "log.json"
    jpath.write_text(
        json.dumps({"kind": "keyword-diagnostics", "data": {"keywords": [_kw(2, "en")]}}), encoding="utf-8"
    )
    assert an.load_log(jpath)["data"]["keywords"] == [_kw(2, "en")]


def test_a_folder_with_two_sets_reads_the_newer_and_says_so(tmp_path, capsys):
    import os

    _build(tmp_path, stem="oo-keyword-log-20260101-000000", per_lang=30)
    _build(tmp_path, stem="oo-keyword-log-20261001-000000", per_lang=50)
    for f in tmp_path.glob("oo-keyword-log-20260101-000000*"):
        os.utime(f, (1_000_000, 1_000_000))
    doc = _analyzer().load_log(tmp_path)
    assert len(doc["data"]["keywords"]) == 100
    assert "2 sets" in capsys.readouterr().err


def test_a_folder_with_no_parts_is_refused_not_read_as_empty(tmp_path):
    with pytest.raises(SystemExit, match="no numbered keyword-log parts"):
        _analyzer().load_log(tmp_path)
