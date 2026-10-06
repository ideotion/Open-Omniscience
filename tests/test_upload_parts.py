"""Numbered parts of at most one megabyte, each valid on its own (src/analytics/upload_parts.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The property that matters is the BOUND, so the negative space carries the weight: no part is over
the cap whatever the records look like (repetitive, dense, one huge, none), the records of all the
parts read back in order are exactly the records that went in, a part that is missing or damaged
is named, and a lone part opens and parses without any other. The zip is written by this module
(``zipfile`` cannot snapshot its compressor), so every part is also read by ``zipfile`` and by
``unzip -t``, which are the readers a user has.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import subprocess
import tracemalloc
import zipfile
from pathlib import Path

import pytest

from src.analytics import upload_parts as up


def _records(rnd: random.Random, n: int, *, dense: bool) -> list[str]:
    out = []
    for i in range(n):
        if dense:
            term = "".join(rnd.choice("0123456789abcdef") for _ in range(rnd.randrange(20, 200)))
        else:
            term = rnd.choice(["alpha", "beta", "gamma"]) * rnd.randrange(1, 12)
        out.append(json.dumps({"i": i, "term": term, "m": rnd.randrange(1000)}, separators=(",", ":")))
    return out


def _write(tmp_path: Path, groups: dict[str, list[str]], *, cap: int, **kw):
    w = up.PartWriter(tmp_path / "set", stem="oo-test-20261001-000000", cap=cap, **kw)
    gs = {name: up.RecordGroup(f"keywords/{name}.json", {"language": name}, "keywords", len(recs))
          for name, recs in groups.items()}
    for name, recs in groups.items():
        for rec in recs:
            w.add_record(gs[name], rec)
    return w, w.finish()


def _parts(tmp_path: Path, manifest: dict) -> list[Path]:
    return [tmp_path / "set" / p["name"] for p in manifest["parts"]]


def parse_position(name: str) -> int:
    parsed = up.parse_part_name(name)
    assert parsed is not None
    return parsed[1]


# --------------------------------------------------------------- names
def test_names_carry_position_and_total_and_sort_in_order():
    assert up.part_file_name("oo-x", 3, 12) == "oo-x-part-03-of-12.zip"
    assert up.part_file_name("oo-x", 1, 1) == "oo-x-part-01-of-01.zip"
    names = [up.part_file_name("oo-x", i, 1234) for i in range(1, 1235)]
    assert names == sorted(names), "zero-padded to the width of the total, so a file list sorts"
    assert names[0] == "oo-x-part-0001-of-1234.zip"
    assert up.parse_part_name(names[41]) == ("oo-x", 42, 1234)
    assert up.parse_part_name("oo-x-manifest.zip") is None


def test_the_cap_is_the_users_number_with_a_margin_under_what_failed():
    assert up.UPLOAD_PART_BYTES == 1_000_000
    assert up.UPLOAD_PART_BYTES < 1_200_000, "files of about 1.2 MB and up failed to upload"


# --------------------------------------------------------------- the bound
@pytest.mark.parametrize("cap", [3_000, 20_000, 100_000, up.UPLOAD_PART_BYTES])
@pytest.mark.parametrize("dense", [False, True])
def test_no_part_is_over_the_cap_whatever_the_records_look_like(tmp_path, cap, dense):
    rnd = random.Random(cap + dense)
    groups = {
        "en": _records(rnd, 9_000, dense=dense),
        "fr": _records(rnd, 40, dense=dense),
        "de": _records(rnd, 2_500, dense=dense),
    }
    _w, manifest = _write(tmp_path, groups, cap=cap)
    sizes = [p.stat().st_size for p in _parts(tmp_path, manifest)]
    assert max(sizes) <= cap, (cap, dense, max(sizes))
    assert manifest["part_count"] == len(sizes)
    assert len(sizes) > 1 or sum(sizes) < cap, "one part only when everything fits in it"
    assert "parts_over_cap" not in manifest
    for p in manifest["parts"]:
        assert p["bytes"] == (tmp_path / "set" / p["name"]).stat().st_size


def test_parts_are_reasonably_full_not_one_record_each(tmp_path):
    rnd = random.Random(5)
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 30_000, dense=False)}, cap=60_000)
    sizes = [p["bytes"] for p in manifest["parts"]]
    assert len(sizes) > 3
    # every part but the last is filled to the cap: the writer measures exactly, it does not guess
    assert min(sizes[:-1]) > 60_000 * 0.97, sizes


def test_the_records_of_all_parts_read_back_in_order_are_the_records_that_went_in(tmp_path):
    rnd = random.Random(8)
    groups = {"en": _records(rnd, 7_000, dense=True), "xx": _records(rnd, 3, dense=False),
              "fr": _records(rnd, 1_800, dense=False)}
    _w, manifest = _write(tmp_path, groups, cap=25_000)
    paths = _parts(tmp_path, manifest)
    for name, recs in groups.items():
        back = up.read_group_records(paths, f"keywords/{name}.json", "keywords")
        assert back == [json.loads(r) for r in recs], name


def test_every_part_opens_on_its_own_and_every_file_in_it_parses(tmp_path):
    rnd = random.Random(9)
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 6_000, dense=False),
                                     "fr": _records(rnd, 100, dense=False)}, cap=15_000)
    for path in _parts(tmp_path, manifest):
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            names = z.namelist()
            assert up.PART_INDEX_NAME in names
            index = json.loads(z.read(up.PART_INDEX_NAME))
            assert index["kind"] == up.PART_KIND
            # part.json is appended once the total is known, so it carries the position itself
            assert index["position"] == parse_position(path.name)
            assert index["total"] == manifest["part_count"] and index["file"] == path.name
            for n in names:
                json.loads(z.read(n))  # a part never holds half a record
            for m in index["contents"]:
                if m["kind"] == "records":
                    doc = json.loads(z.read(m["member"]))
                    assert doc["count"] == len(doc["keywords"]) == m["to"] - m["from"]
                    assert (doc["slice_from"], doc["slice_to"], doc["slice_of"]) == (
                        m["from"], m["to"], m["of"]
                    )


def test_a_language_spanning_several_parts_says_where_each_slice_sits(tmp_path):
    rnd = random.Random(10)
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 12_000, dense=True)}, cap=20_000)
    slices = []
    for p in manifest["parts"]:
        for m in p["members"]:
            if m["kind"] == "records":
                slices.append((m["from"], m["to"], m["of"]))
    assert len(slices) > 3
    assert slices[0][0] == 0 and slices[-1][1] == 12_000
    assert all(a[1] == b[0] for a, b in zip(slices, slices[1:], strict=False)), "no gap, no overlap"
    assert {s[2] for s in slices} == {12_000}


def test_orientation_documents_are_numbered_first_however_late_they_were_produced(tmp_path):
    rnd = random.Random(18)
    w = up.PartWriter(tmp_path / "set", stem="oo-test-front", cap=20_000)
    g = up.RecordGroup("keywords/en.json", {"language": "en"}, "keywords", 6_000)
    for rec in _records(rnd, 6_000, dense=True):
        w.add_record(g, rec)
    w.add_front_json_document("summary.json", {"data": {"families": [{"t": i} for i in range(50)]}})
    w.add_front_json_document("export-manifest.json", {"kind": "keyword-diagnostics-archive"})
    manifest = w.finish()
    first = manifest["parts"][0]
    assert first["name"].startswith("oo-test-front-part-01-of-")
    assert manifest["part_count"] > 3
    # The records fill several parts, so the orientation documents have a part of their own,
    # numbered first although they were produced last.
    assert [m["member"] for m in first["members"]] == ["summary.json", "export-manifest.json"]
    assert all(m["kind"] == "records" for p in manifest["parts"][1:] for m in p["members"])
    assert max(p["bytes"] for p in manifest["parts"]) <= 20_000
    assert up.verify_parts(tmp_path / "set", manifest)["ok"]


def test_a_small_export_is_one_file_the_orientation_documents_riding_with_the_records(tmp_path):
    rnd = random.Random(21)
    w = up.PartWriter(tmp_path / "set", stem="oo-test-one", cap=up.UPLOAD_PART_BYTES)
    g = up.RecordGroup("keywords/en.json", {"language": "en"}, "keywords", 300)
    for rec in _records(rnd, 300, dense=False):
        w.add_record(g, rec)
    w.add_front_json_document("summary.json", {"data": {"families": [{"t": i} for i in range(50)]}})
    w.add_front_json_document("export-manifest.json", {"kind": "keyword-diagnostics-archive"})
    manifest = w.finish()
    assert manifest["part_count"] == 1
    (part,) = manifest["parts"]
    assert part["name"] == "oo-test-one-part-01-of-01.zip"
    assert sorted(m["member"] for m in part["members"]) == [
        "export-manifest.json", "keywords/en.from-000000.json", "summary.json",
    ]
    with zipfile.ZipFile(tmp_path / "set" / part["name"]) as z:
        assert z.namelist()[-1] == up.PART_INDEX_NAME, "part.json is appended last"
        assert z.testzip() is None


@pytest.mark.parametrize("front_bytes", range(2_000, 14_000, 677))
def test_the_orientation_merge_never_pushes_a_part_over_the_cap(tmp_path, front_bytes):
    """The merge reserves part.json's room too: a front document sized to just fit, or just not,
    must leave the finished part at or under the cap either way (swept across sizes)."""
    rnd = random.Random(front_bytes)
    cap = 12_000
    w = up.PartWriter(tmp_path / "set", stem="oo-test-merge", cap=cap)
    g = up.RecordGroup("keywords/en.json", {"language": "en"}, "keywords", 120)
    for rec in _records(rnd, 120, dense=True):
        w.add_record(g, rec)
    noise = "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(front_bytes))
    w.add_front_json_document("summary.json", {"data": {"noise": noise}})
    manifest = w.finish()
    for p in manifest["parts"]:
        assert p["bytes"] <= cap, (front_bytes, p["name"], p["bytes"])
    assert up.verify_parts(tmp_path / "set", manifest)["ok"]
    got = []
    for path in _parts(tmp_path, manifest):
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            got += [n for n in z.namelist() if n.startswith("summary")]
    assert got, "the orientation document is in the set"


def test_orientation_documents_get_a_part_of_their_own_when_they_do_not_fit_beside_the_records(tmp_path):
    rnd = random.Random(19)
    w = up.PartWriter(tmp_path / "set", stem="oo-test-front2", cap=20_000)
    g = up.RecordGroup("keywords/en.json", {"language": "en"}, "keywords", 6_000)
    for rec in _records(rnd, 6_000, dense=True):
        w.add_record(g, rec)
    # Incompressible, so it cannot hide in the first part's slack.
    noise = "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(8_000))
    w.add_front_json_document("summary.json", {"data": {"noise": noise}})
    manifest = w.finish()
    assert [m["member"] for m in manifest["parts"][0]["members"]] == ["summary.json"]
    assert all(m["kind"] == "records" for p in manifest["parts"][1:] for m in p["members"])
    assert max(p["bytes"] for p in manifest["parts"]) <= 20_000
    assert up.verify_parts(tmp_path / "set", manifest)["ok"]
    assert not list((tmp_path / "set").glob(".part-*"))


def test_an_orientation_document_larger_than_a_piece_is_cut_into_valid_numbered_files(tmp_path):
    w = up.PartWriter(tmp_path / "set", stem="oo-test-bigfront", cap=20_000)
    doc = {"data": {"families": [{"term": f"t{i}", "n": i, "pad": "x" * 40} for i in range(2_000)]}}
    w.add_front_json_document("summary.json", doc)
    manifest = w.finish()
    pieces = []
    for p in manifest["parts"]:
        with zipfile.ZipFile(tmp_path / "set" / p["name"]) as z:
            for name in sorted(z.namelist()):
                if name.startswith("summary.s"):
                    d = json.loads(z.read(name))
                    pieces.append({"path": d["oo_part"]["path"], "slice": d["oo_part"]["slice"],
                                   "value": d["value"]})
    assert len(pieces) > 3
    assert up.join_json_pieces(pieces) == doc
    assert max(p["bytes"] for p in manifest["parts"]) <= 20_000


def test_a_missing_part_is_an_error_not_a_short_list(tmp_path):
    rnd = random.Random(11)
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 8_000, dense=True)}, cap=20_000)
    paths = _parts(tmp_path, manifest)
    gone = paths.pop(len(paths) // 2)
    assert gone.exists()
    with pytest.raises(ValueError, match="missing or out of order"):
        up.read_group_records(paths, "keywords/en.json", "keywords")


def test_an_export_with_nothing_in_it_still_hands_over_one_valid_part(tmp_path):
    w = up.PartWriter(tmp_path / "set", stem="oo-test-x", cap=up.UPLOAD_PART_BYTES)
    manifest = w.finish()
    assert manifest["part_count"] == 1
    assert manifest["parts"][0]["name"] == "oo-test-x-part-01-of-01.zip"
    assert up.verify_parts(tmp_path / "set", manifest)["ok"]


def test_a_record_larger_than_a_part_goes_out_as_numbered_byte_pieces_never_over_the_cap(tmp_path):
    rnd = random.Random(12)
    big = json.dumps({"term": "".join(rnd.choice("0123456789abcdef") for _ in range(60_000))})
    groups = {"en": [*_records(rnd, 20, dense=False), big, *_records(rnd, 20, dense=False)]}
    _w, manifest = _write(tmp_path, groups, cap=10_000)
    assert max(p["bytes"] for p in manifest["parts"]) <= 10_000, "no part is ever over the cap"
    (rec,) = manifest["oversize_records"]
    assert rec["bytes"] == len(big.encode()) and len(rec["pieces"]) > 3
    assert rec["pieces"][0].endswith(f".oversize0001-of-{len(rec['pieces']):04d}")
    assert "cat" in rec["rejoin"]
    pieces = []
    for p in _parts(tmp_path, manifest):
        with zipfile.ZipFile(p) as z:
            pieces += [(n, z.read(n)) for n in z.namelist() if ".oversize" in n]
    pieces.sort()
    joined = b"".join(d for _n, d in pieces)
    assert joined == big.encode(), "nothing is lost: the pieces rejoin to the record, byte for byte"
    assert hashlib.sha256(joined).hexdigest() == rec["sha256"]
    # the rest of the language is still there, in order, either side of the gap
    back = up.read_group_records(_parts(tmp_path, manifest), "keywords/en.json", "keywords",
                                 manifest=manifest)
    assert back == [json.loads(r) for r in [*groups["en"][:20], *groups["en"][21:]]]
    assert rec["group"] == "keywords/en.json" and rec["record_index"] == 20
    # without the manifest the gap is an error, not a quiet short list
    with pytest.raises(ValueError, match="missing or out of order"):
        up.read_group_records(_parts(tmp_path, manifest), "keywords/en.json", "keywords")


def test_the_cap_cannot_be_smaller_than_a_part_s_own_index(tmp_path):
    with pytest.raises(ValueError, match="too small"):
        up.PartWriter(tmp_path / "set", stem="oo-test-tiny", cap=900)


def test_parts_are_filled_to_the_cap_at_the_real_cap(tmp_path):
    rnd = random.Random(22)
    cap = up.UPLOAD_PART_BYTES
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 36_000, dense=True)}, cap=cap)
    sizes = [p["bytes"] for p in manifest["parts"]]
    assert len(sizes) >= 3
    assert max(sizes) <= cap
    # every part but the last (and the front part that carries no records) is within 1% of the
    # cap: the files the user is handed are as few as they can be
    assert min(sizes[1:-1]) > cap * 0.99, sizes


@pytest.mark.skipif(shutil.which("unzip") is None, reason="needs the unzip tool")
def test_every_part_passes_zipfile_and_unzip_the_readers_a_user_has(tmp_path):
    rnd = random.Random(23)
    w = up.PartWriter(tmp_path / "set", stem="oo-test-readers", cap=15_000, order_note="n")
    gs = [up.RecordGroup(f"keywords/{n}.json", {"language": n}, "keywords", 900) for n in "ab"]
    for _i in range(900):  # interleaved, so members open and close inside parts
        for g in gs:
            w.add_record(g, _records(rnd, 1, dense=True)[0])
    w.add_front_json_document("summary.json", {"data": list(range(3_000))})
    manifest = w.finish()
    assert manifest["part_count"] > 5
    for p in manifest["parts"]:
        path = tmp_path / "set" / p["name"]
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            names = [info.filename for info in z.infolist()]
            assert len(names) == len(set(names)), "no name repeats inside a part"
            for info in z.infolist():
                assert info.file_size == len(z.read(info.filename))
        done = subprocess.run(["unzip", "-tq", str(path)], capture_output=True, text=True)
        assert done.returncode == 0, (p["name"], done.stdout, done.stderr)
    assert "order" in manifest and manifest["order"] == "n"


def test_part_json_is_appended_last_and_says_where_the_part_sits_in_the_set(tmp_path):
    rnd = random.Random(24)
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 5_000, dense=True)}, cap=20_000,
                          order_note="rank-major, test")
    for p in manifest["parts"]:
        with zipfile.ZipFile(tmp_path / "set" / p["name"]) as z:
            assert z.namelist()[-1] == up.PART_INDEX_NAME
            index = json.loads(z.read(up.PART_INDEX_NAME))
        assert index["position"] == p["position"] and index["total"] == manifest["part_count"]
        assert index["order"] == "rank-major, test" and index["file"] == p["name"]
        assert [c["member"] for c in index["contents"]] == [
            m["member"] for m in p["members"] if m["kind"] != "index"
        ]
        assert "oo-test-" in index["neighbours"] and "manifest.zip" in index["neighbours"]


@pytest.mark.parametrize("seed", range(40))
def test_any_mix_of_record_sizes_at_any_cap_stays_under_the_cap_and_round_trips(tmp_path, seed):
    """The property, over random caps and record-size distributions including records of a
    few bytes, hundreds of KB and everything between, several languages interleaved."""
    rnd = random.Random(1000 + seed)
    cap = rnd.choice([4_096, 6_000, 12_000, 50_000])
    w = up.PartWriter(tmp_path / "set", stem="oo-test-prop", cap=cap)
    langs = {n: [] for n in rnd.sample(["en", "fr", "de", "xx", "?"], rnd.randrange(1, 5))}
    gs = {n: up.RecordGroup(f"keywords/{n}.json", {"language": n}, "keywords", 0) for n in langs}
    plan = []
    for _ in range(rnd.randrange(50, 400)):
        n = rnd.choice(list(langs))
        size = rnd.choice([3, 30, 200, 200, 1_500, 20_000, 70_000]) if rnd.random() < 0.97 else 5
        plan.append((n, json.dumps({"t": "".join(rnd.choice("0123456789abcdef") for _ in range(size))})))
        langs[n].append(plan[-1][1])
    for n, g in gs.items():
        g.total = len(langs[n])
    for n, rec in plan:
        w.add_record(gs[n], rec)
    manifest = w.finish()
    for p in manifest["parts"]:
        assert p["bytes"] <= cap, (seed, cap, p["name"], p["bytes"])
        with zipfile.ZipFile(tmp_path / "set" / p["name"]) as z:
            assert z.testzip() is None
    assert up.verify_parts(tmp_path / "set", manifest)["ok"]
    absent = {(r["group"], r["record_index"]) for r in manifest.get("oversize_records", [])}
    for n, recs in langs.items():
        expected = [r for i, r in enumerate(recs) if (f"keywords/{n}.json", i) not in absent]
        got = up.read_group_records(_parts(tmp_path, manifest), f"keywords/{n}.json", "keywords",
                                    manifest=manifest)
        assert [json.dumps(r, separators=(",", ":")) for r in got] == [
            json.dumps(json.loads(r), separators=(",", ":")) for r in expected
        ], (seed, n)
        for r in manifest.get("oversize_records", []):  # every record that went out as pieces is whole
            if r["group"] == f"keywords/{n}.json":
                assert recs[r["record_index"]].encode() and r["bytes"] == len(recs[r["record_index"]].encode())


def test_what_the_writer_holds_does_not_grow_with_the_export(tmp_path):
    """The reason for streaming: a part is never held, only a chunk and two compressor states."""
    def peak(n: int) -> int:
        rnd = random.Random(7)
        recs = _records(rnd, n, dense=True)
        tracemalloc.start()
        try:
            w = up.PartWriter(tmp_path / f"set{n}", stem="oo-test-mem", cap=up.UPLOAD_PART_BYTES)
            g = up.RecordGroup("keywords/en.json", {"language": "en"}, "keywords", n)
            base = tracemalloc.get_traced_memory()[0]
            for rec in recs:
                w.add_record(g, rec)
            w.finish()
            return tracemalloc.get_traced_memory()[1] - base
        finally:
            tracemalloc.stop()

    small, big = peak(6_000), peak(36_000)
    assert big < 10_000_000, (small, big)
    assert big < small * 1.5 + 2_000_000, (small, big)


# --------------------------------------------------------------- the manifest
def _incompressible_records(rnd: random.Random, n: int, *, size: tuple[int, int]) -> list[str]:
    """Records whose text deflate cannot shrink below about three quarters (base64 of random bytes):
    the other end from the hex-dense and repeated words the rest of this file feeds the writer."""
    import base64

    out = []
    for i in range(n):
        raw = rnd.randbytes(rnd.randrange(*size))
        out.append(json.dumps({"i": i, "blob": base64.b64encode(raw).decode()}, separators=(",", ":")))
    return out


@pytest.mark.parametrize("cap", [6_000, 40_000, up.UPLOAD_PART_BYTES])
def test_no_part_is_over_the_cap_on_incompressible_records(tmp_path, cap):
    """R115 follow-up S5: the bound was pinned on text that deflates 3x to 20x; a part of data that
    does not shrink is where a bound that leans on the compression ratio would be over."""
    rnd = random.Random(cap)
    groups = {"en": _incompressible_records(rnd, 3_000, size=(30, 600)),
              "fr": _incompressible_records(rnd, 200, size=(2_000, 9_000))}
    _w, manifest = _write(tmp_path, groups, cap=cap)
    sizes = [p.stat().st_size for p in _parts(tmp_path, manifest)]
    assert max(sizes) <= cap, (cap, max(sizes))
    assert up.verify_parts(tmp_path / "set", manifest)["ok"]
    if cap == up.UPLOAD_PART_BYTES:
        assert sum(sizes) > cap, "the fixture really did not fit one part"
    absent = {(r["group"], r["record_index"]) for r in manifest.get("oversize_records", [])}
    for lang, recs in groups.items():
        back = up.read_group_records(_parts(tmp_path, manifest), f"keywords/{lang}.json", "keywords",
                                     manifest=manifest)
        # A record bigger than a part goes out as numbered pieces (the manifest lists it), so it is
        # not among the records a reader gets back whole.
        assert back == [
            json.loads(r) for i, r in enumerate(recs) if (f"keywords/{lang}.json", i) not in absent
        ]


def test_one_incompressible_record_of_three_megabytes_goes_out_in_pieces_under_the_real_cap(tmp_path):
    rnd = random.Random(31)
    big = _incompressible_records(rnd, 1, size=(3_000_000, 3_000_001))[0]
    groups = {"en": [*_incompressible_records(rnd, 5, size=(30, 600)), big]}
    _w, manifest = _write(tmp_path, groups, cap=up.UPLOAD_PART_BYTES)
    assert max(p["bytes"] for p in manifest["parts"]) <= up.UPLOAD_PART_BYTES
    (rec,) = manifest["oversize_records"]
    assert len(rec["pieces"]) >= 4, "about 4 MB of text that does not shrink needs at least four pieces"


def test_a_set_of_more_than_ninety_nine_parts_is_numbered_in_a_width_that_sorts(tmp_path):
    """R115 follow-up S5: numbering past 99 was pinned on the function only, never on a real set."""
    rnd = random.Random(7)
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 14_000, dense=True)}, cap=4_000)
    total = manifest["part_count"]
    assert total > 99, f"the fixture must make a set past 99 parts (it made {total})"
    names = [p["name"] for p in manifest["parts"]]
    assert names == sorted(names), "a file listing sorts the parts into their order"
    width = len(str(total))
    assert names[0] == f"oo-test-20261001-000000-part-{1:0{width}d}-of-{total}.zip"
    assert [parse_position(n) for n in names] == list(range(1, total + 1))
    for p in manifest["parts"][:: max(1, total // 7)]:
        with zipfile.ZipFile(tmp_path / "set" / p["name"]) as z:
            index = json.loads(z.read(up.PART_INDEX_NAME))
        assert index["position"] == p["position"] and index["total"] == total
    assert up.verify_parts(tmp_path / "set", manifest)["ok"]


def test_the_manifest_confirms_a_complete_set_and_names_a_missing_or_damaged_part(tmp_path):
    rnd = random.Random(13)
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 8_000, dense=False)}, cap=20_000)
    out = tmp_path / "set"
    assert up.verify_parts(out, manifest) == {
        "ok": True, "bad": [], "missing": [], "total": manifest["part_count"],
    }
    names = [p["name"] for p in manifest["parts"]]
    (out / names[1]).write_bytes((out / names[1]).read_bytes()[:-5])  # a truncated transfer
    (out / names[2]).unlink()
    res = up.verify_parts(out, manifest)
    assert res["ok"] is False and res["bad"] == [names[1], names[2]] and res["missing"] == [names[2]]
    same_size = (out / names[0]).read_bytes()
    (out / names[0]).write_bytes(bytes([same_size[0] ^ 1]) + same_size[1:])  # same size, other bytes
    assert names[0] in up.verify_parts(out, manifest)["bad"]


def test_the_manifest_is_a_small_zip_of_its_own_listing_every_part_with_its_checksum(tmp_path):
    rnd = random.Random(14)
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 8_000, dense=False)}, cap=20_000)
    out = tmp_path / "set"
    (name,) = manifest["manifest_files"]
    assert name == "oo-test-20261001-000000-manifest.zip"
    assert (out / name).stat().st_size <= 20_000
    with zipfile.ZipFile(out / name) as z:
        doc = json.loads(z.read("manifest.json"))
    assert doc["kind"] == up.MANIFEST_KIND and doc["part_count"] == manifest["part_count"]
    assert [p["name"] for p in doc["parts"]] == [p["name"] for p in manifest["parts"]]
    assert all(len(p["sha256"]) == 64 and p["members"] for p in doc["parts"])


def test_a_manifest_too_large_for_one_file_is_cut_into_valid_numbered_files(tmp_path):
    rnd = random.Random(15)
    # 3,000 byte cap: the listing of dozens of parts cannot fit one manifest file
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 6_000, dense=True)}, cap=3_000)
    names = manifest["manifest_files"]
    assert len(names) > 1 and names[0].endswith(f"-manifest-01-of-{len(names):02d}.zip")
    pieces = []
    for n in names:
        assert (tmp_path / "set" / n).stat().st_size <= 3_000
        with zipfile.ZipFile(tmp_path / "set" / n) as z:
            for member in sorted(z.namelist()):
                doc = json.loads(z.read(member))
                pieces.append({"path": doc["oo_part"]["path"], "slice": doc["oo_part"]["slice"],
                               "value": doc["value"]})
    whole = up.join_json_pieces(pieces)
    assert [p["name"] for p in whole["parts"]] == [p["name"] for p in manifest["parts"]]


# --------------------------------------------------------------- the memory stop and the drive
def test_the_memory_stop_and_the_drive_watch_run_once_per_part(tmp_path):
    seen = {"check": 0, "watch": 0}

    def check():
        seen["check"] += 1

    def watch():
        seen["watch"] += 1

    rnd = random.Random(16)
    _w, manifest = _write(tmp_path, {"en": _records(rnd, 8_000, dense=True)}, cap=20_000,
                          check=check, disk_watch=watch)
    assert seen["check"] == seen["watch"] >= manifest["part_count"]


def test_a_refusal_from_the_watch_stops_the_export_and_leaves_no_temporary_part(tmp_path):
    class Stop(Exception):
        pass

    def watch():
        raise Stop

    w = up.PartWriter(tmp_path / "set", stem="oo-test-y", cap=5_000, disk_watch=watch)
    g = up.RecordGroup("keywords/en.json", {"language": "en"}, "keywords", 10_000)
    rnd = random.Random(17)
    with pytest.raises(Stop):
        for rec in _records(rnd, 10_000, dense=True):
            w.add_record(g, rec)
    w.abort()
    assert not list((tmp_path / "set").glob(".part-*")), "an aborted export removes its temporaries"


# --------------------------------------------------------------- json pieces
def _random_doc(rnd: random.Random, depth: int = 0):
    kind = rnd.random()
    if depth > 3 or kind < 0.3:
        return rnd.choice([1, 2.5, "text" * rnd.randrange(1, 40), None, True])
    if kind < 0.65:
        return {f"k{i}": _random_doc(rnd, depth + 1) for i in range(rnd.randrange(0, 12))}
    return [_random_doc(rnd, depth + 1) for _ in range(rnd.randrange(0, 40))]


@pytest.mark.parametrize("seed", range(60))
def test_json_cut_into_pieces_joins_back_to_the_same_document(seed):
    rnd = random.Random(seed)
    doc = {"data": _random_doc(rnd), "rows": [_random_doc(rnd, 2) for _ in range(rnd.randrange(0, 200))],
           "meta": {"a": 1, "b": [1, 2, 3]}}
    limit = rnd.choice([300, 1_000, 5_000])
    pieces = list(up.split_json_value(doc, limit))
    for piece in pieces:
        if not piece.get("oversize"):
            assert len(up.piece_document(piece)) <= limit + 200, (seed, len(up.piece_document(piece)))
        json.loads(up.piece_document(piece))  # each piece is a valid document by itself
    assert up.join_json_pieces(pieces) == doc


def test_a_value_that_cannot_be_cut_is_one_flagged_piece_never_cut_inside():
    pieces = list(up.split_json_value({"k": "x" * 5_000}, 1_000))
    assert [p["path"] for p in pieces] == [["k"]]
    assert pieces[0].get("oversize") is True and pieces[0]["value"] == "x" * 5_000


def test_pieces_that_do_not_follow_each_other_are_refused():
    pieces = list(up.split_json_value({"rows": list(range(5_000))}, 400))
    assert len(pieces) > 2
    with pytest.raises(ValueError, match="do not follow"):
        up.join_json_pieces([pieces[0], pieces[2]])


def test_a_manifest_file_over_its_cap_is_an_error_and_never_handed_over(tmp_path):
    # one value that cannot be cut and does not compress: the only way a manifest file can end over
    # its cap (at 1,000,000 bytes a 5,000-part manifest is about 377 KB, so this is not a real path)
    manifest = {"parts": [], "note": random.Random(9).randbytes(1_500).hex()}
    with pytest.raises(RuntimeError, match="over its 1000-byte cap"):
        up.write_manifest_zips(tmp_path, "oo-keyword-log-20261001-000000", manifest, 1_000)


def test_an_ordinary_manifest_is_one_file_and_a_long_one_is_several_each_under_the_cap(tmp_path):
    parts = [{"name": f"p{i:04d}", "bytes": 900_000 + i, "sha256": hashlib.sha256(str(i).encode()).hexdigest(), "members": []}
             for i in range(400)]
    names = up.write_manifest_zips(tmp_path, "oo-keyword-log-20261001-000000", {"parts": parts}, 6_000)
    assert len(names) > 1 and all((tmp_path / n).stat().st_size <= 6_000 for n in names)
    (tmp_path / "one").mkdir()
    one = up.write_manifest_zips(tmp_path / "one", "oo-keyword-log-20261001-000000", {"parts": parts[:3]}, 6_000)
    assert one == ["oo-keyword-log-20261001-000000-manifest.zip"]


# ----------------------------------------------------- the size accounting, pinned by what it leaves
def _reserve_set(tmp_path: Path, monkeypatch, cap: int) -> list[int]:
    """The room left in every closed part of a set written one record per trial, so a part ends
    as close to the cap as the accounting allows and what is left IS the accounting's reserve."""
    monkeypatch.setattr(up, "_CHUNK_RECORDS", 1)
    rnd = random.Random(3)
    w = up.PartWriter(tmp_path / "set", stem="oo-keyword-log-20261001-000000", cap=cap)
    for lang in ("fr", "en", "de"):
        g = up.RecordGroup(f"keywords/{lang}.json", {"language": lang}, "keywords", 400)
        for i in range(400):
            w.add_record(g, json.dumps({"keyword": f"{lang}-{i:05d}-" + "x" * (i % 17), "mentions": 1000 - i,
                                        "sig": rnd.randbytes(10).hex()}, separators=(",", ":")))
    w.add_front_json_document("summary.json", {"kind": "k", "data": {"n": 1}})
    manifest = w.finish()
    return [cap - p["bytes"] for p in manifest["parts"]]


@pytest.mark.parametrize("cap", [4_096, 6_000])
def test_every_closed_part_keeps_the_room_the_accounting_reserves_and_no_more(tmp_path, monkeypatch, cap):
    """The cap holds because each trial counts the closing of the member, the zip directory, the
    part.json still to come and a deflate margin. None of them is visible alone (the part.json is
    counted raw and written deflated, which leaves slack), so this pins their SUM from both sides
    on the parts between the front part and the last: measured 517-676 bytes unused. Dropping the
    member tail (160 bytes), the directory term, or allowing the cap to be passed by 300 leaves
    well under 450 and fails here; reserving more than 800 means parts are no longer filled."""
    room = _reserve_set(tmp_path, monkeypatch, cap)[1:-1]  # the first part is the summary's, the last is short
    assert len(room) >= 5, "the set must span several parts for this to test anything"
    assert min(room) >= 450 and max(room) <= 800, sorted(room)


def test_a_part_closed_at_a_language_change_keeps_the_member_closing_reserve(tmp_path):
    """The reserve test above writes a few long members, so the trial that opens a NEW member while
    another is open (a language change) almost never decides where a part ends, and dropping the
    second member-tail term from that trial passed the whole suite. Here every record is its own
    language, so every trial is one: the room left in the closed parts is 1,739-1,765 bytes at this
    cap with classic zlib (1,659 at the worst of its levels and strategies; most of it is the
    part.json counted raw and written deflated, so a tighter count of that would move the number),
    and 1,480 without the term. The floor sits between them, nearer the mutant than a compressor's
    own spread."""
    rnd = random.Random(3)
    cap = 4_096
    w = up.PartWriter(tmp_path / "set", stem="oo-keyword-log-20261001-000000", cap=cap)
    for g in range(900):
        lang = f"l{g:03d}"
        grp = up.RecordGroup(f"keywords/{lang}.json", {"language": lang}, "keywords", 1)
        w.add_record(grp, json.dumps({"keyword": f"{lang}-" + "x" * (g % 13), "mentions": 1000 - g,
                                      "sig": rnd.randbytes(10).hex()}, separators=(",", ":")))
    manifest = w.finish()
    room = [cap - p["bytes"] for p in manifest["parts"]][1:-1]
    assert len(room) >= 50, "the set must span many parts for this to test anything"
    assert min(room) >= 1_600, sorted(room)[:5]


def test_the_post_check_stops_a_part_over_the_cap_instead_of_handing_it_over(tmp_path):
    """The accounting is the first guard and this is the second: a part that closes over the cap
    is an error that stops the export, whatever went wrong before it. The accounting is made
    wrong here the simple way, by lowering the cap after the parts were filled to the old one."""
    rnd = random.Random(9)
    w = up.PartWriter(tmp_path / "set", stem="oo-keyword-log-20261001-000000", cap=6_000)
    g = up.RecordGroup("keywords/en.json", {"language": "en"}, "keywords", 600)
    for rec in _records(rnd, 600, dense=True):
        w.add_record(g, rec)
    w.cap = 3_000
    with pytest.raises(RuntimeError, match="over the 3000 cap.*nothing was handed over"):
        w.finish()


def test_non_ascii_member_names_are_flagged_utf8_and_read_back_by_the_readers_a_user_has(tmp_path):
    """A language file named for a non-Latin code must come back as itself in any unzip tool:
    that needs the zip's UTF-8 name flag, and without it the name is read as cp437 mojibake."""
    names = ["日本語", "العربية", "español-ñ"]
    w = up.PartWriter(tmp_path / "set", stem="oo-keyword-log-20261001-000000", cap=20_000)
    for n in names:
        g = up.RecordGroup(f"keywords/{n}.json", {"language": n}, "keywords", 3)
        for i in range(3):
            w.add_record(g, json.dumps({"i": i, "term": n}, ensure_ascii=False))
    manifest = w.finish()
    seen: list[str] = []
    for p in _parts(tmp_path, manifest):
        with zipfile.ZipFile(p) as z:
            assert z.testzip() is None
            for info in z.infolist():
                assert info.flag_bits & 0x800, f"{info.filename} is not flagged UTF-8"
                seen.append(info.filename)
    for n in names:
        assert f"keywords/{n}.from-000000.json" in seen, (n, seen)
