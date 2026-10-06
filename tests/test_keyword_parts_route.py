"""``/api/diagnostics/keywords?format=parts``: the keyword log as a numbered set of small zips.

The user's number (1 MB, protecting uploads) is a cap on EACH FILE; the export's content is the one
``format=zip`` writes, so these tests hold the two against each other: the same entries in the same
order, every file under the cap and opening on its own, the manifest confirming the set, and the
download route serving only what the listing names.
"""

from __future__ import annotations

import errno
import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.analytics import keyword_log_export as kle
from src.analytics import upload_parts as up
from tests.test_keyword_export_bounded import _build, _session

_SMALL_CAP = 12_000


@pytest.fixture(scope="module")
def db_path(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("kw-parts") / "d.db"
    _build(p, 7, articles=300, keywords=6_000)
    return p


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    d = tmp_path / "diagnostics"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture
def small_cap(monkeypatch) -> int:
    """A cap a small test database can cross, so a set has several parts."""
    monkeypatch.setattr(kle, "UPLOAD_PART_BYTES", _SMALL_CAP)
    return _SMALL_CAP


def _call(db_path: Path, **kw):
    from src.api.diagnostics.keywords import keyword_log

    kw.setdefault("digest", False)
    kw.setdefault("per_lang", 1_000_000)
    kw.setdefault("page", 1)
    kw.setdefault("max_mb", 0)
    db = _session(db_path)
    try:
        return keyword_log(db=db, **kw)
    finally:
        db.close()


def _listing(db_path: Path, **kw) -> dict:
    resp = _call(db_path, fmt="parts", **kw)
    return json.loads(resp.body)


def _set_dir(data_dir: Path, listing: dict) -> Path:
    return data_dir / listing["set"]


def _entries_of_the_single_archive(db_path: Path) -> dict[str, list]:
    resp = _call(db_path, fmt="zip")
    path = Path(resp.path)
    try:
        z = zipfile.ZipFile(io.BytesIO(path.read_bytes()))
        docs = [json.loads(z.read(n)) for n in z.namelist() if n.startswith("keywords/")]
        return {doc["language"]: doc["keywords"] for doc in docs}
    finally:
        kle.unlink_quietly(path)


def _entries_of_the_parts(set_dir: Path, listing: dict) -> dict[str, list]:
    by_lang: dict[str, list] = {}
    for f in listing["files"]:
        if f["kind"] != "part":
            continue
        with zipfile.ZipFile(set_dir / f["name"]) as z:
            for n in sorted(z.namelist()):
                if n.startswith("keywords/"):
                    doc = json.loads(z.read(n))
                    by_lang.setdefault(doc["language"], []).extend(doc["keywords"])
    return by_lang


def test_one_click_answers_with_the_listing_every_file_named_sized_and_checksummed(db_path, data_dir):
    listing = _listing(db_path)
    d = _set_dir(data_dir, listing)
    names = [f["name"] for f in listing["files"]]
    assert listing["part_max_bytes"] == up.UPLOAD_PART_BYTES == 1_000_000
    assert names[0].endswith("-part-01-of-01.zip") and names[-1].endswith("-manifest.zip")
    assert listing["part_count"] == 1
    for f in listing["files"]:
        data = (d / f["name"]).read_bytes()
        assert len(data) == f["bytes"] <= up.UPLOAD_PART_BYTES
        assert up.hashlib.sha256(data).hexdigest() == f["sha256"]
    assert listing["total_bytes"] == sum(f["bytes"] for f in listing["files"])
    assert listing["download_base"].endswith(f"/keywords/parts/{listing['set']}/")


def test_a_set_has_the_same_entries_in_the_same_order_as_the_single_archive(db_path, data_dir, small_cap):
    listing = _listing(db_path)
    assert listing["part_count"] > 3, "the small cap must make this a real multi-part set"
    d = _set_dir(data_dir, listing)
    whole = _entries_of_the_single_archive(db_path)
    parts = _entries_of_the_parts(d, listing)
    assert parts == whole
    assert sum(len(v) for v in whole.values()) > 1_000


def _keyword_members(d: Path, listing: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in listing["files"]:
        if f["kind"] == "part":
            with zipfile.ZipFile(d / f["name"]) as z:
                for n in z.namelist():
                    if n.startswith("keywords/"):
                        out[n] = json.loads(z.read(n))
    return out


def test_a_later_page_names_its_members_by_their_true_rank(db_path, data_dir):
    """Page 2 of 50 a language holds ranks 50-99, and its members say so: the rank of the first
    record is in the file name and in slice_from, so two pages unzipped into one folder never
    overwrite each other (the Opus review found page 2 restarting at 000000)."""
    one = _listing(db_path, per_lang=50, page=1)
    two = _listing(db_path, per_lang=50, page=2)
    first = _keyword_members(_set_dir(data_dir, one), one)
    later = _keyword_members(_set_dir(data_dir, two), two)
    assert first and later and not set(first) & set(later), "no member name is shared by two pages"
    assert all(".from-000000." in n and d["slice_from"] == 0 for n, d in first.items())
    assert all(".from-000050." in n and d["slice_from"] == 50 for n, d in later.items())
    assert all(d["slice_to"] == 50 + d["count"] for d in later.values())


def test_every_part_is_under_the_cap_numbered_and_opens_on_its_own(db_path, data_dir, small_cap):
    listing = _listing(db_path)
    d = _set_dir(data_dir, listing)
    total = listing["part_count"]
    width = max(2, len(str(total)))
    parts = [f for f in listing["files"] if f["kind"] == "part"]
    assert [f["name"].rsplit("-part-", 1)[1] for f in parts] == [
        f"{i:0{width}d}-of-{total:0{width}d}.zip" for i in range(1, total + 1)
    ]
    for f in parts:
        assert f["bytes"] <= small_cap, f["name"]
        with zipfile.ZipFile(d / f["name"]) as z:
            assert z.testzip() is None
            for n in z.namelist():
                json.loads(z.read(n))  # every member parses alone


def test_the_manifest_confirms_the_set_and_names_a_damaged_or_missing_part(db_path, data_dir, small_cap):
    listing = _listing(db_path)
    d = _set_dir(data_dir, listing)
    manifest_name = next(f["name"] for f in listing["files"] if f["kind"] == "manifest")
    with zipfile.ZipFile(d / manifest_name) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert up.verify_parts(d, manifest)["ok"] is True
    first = manifest["parts"][0]["name"]
    last = manifest["parts"][-1]["name"]
    (d / last).unlink()
    with (d / first).open("ab") as fh:
        fh.write(b"x")
    verdict = up.verify_parts(d, manifest)
    assert verdict["ok"] is False and verdict["bad"] == [first, last] and verdict["missing"] == [last]


def test_max_mb_still_caps_the_total_measured_on_the_sum_of_the_parts(db_path, data_dir, small_cap):
    everything = _listing(db_path)
    total_all = sum(f["bytes"] for f in everything["files"] if f["kind"] == "part")
    capped = _listing(db_path, max_mb=total_all * 0.4 / 1_000_000)
    got = sum(f["bytes"] for f in capped["files"] if f["kind"] == "part")
    assert got <= total_all * 0.4 + small_cap, "trimmed to aim under the total cap"
    assert got < total_all
    d = _set_dir(data_dir, capped)
    with zipfile.ZipFile(d / next(f["name"] for f in capped["files"] if f["name"].endswith(".zip")
                                  and "-part-01-of-" in f["name"])) as z:
        manifest = json.loads(z.read("export-manifest.json"))
    assert manifest["keywords_omitted_to_fit"] > 0 and manifest["max_bytes"] is not None


def test_a_download_serves_only_a_file_the_listing_names(db_path, data_dir):
    from src.api.diagnostics.keyword_parts import keyword_part_download

    listing = _listing(db_path)
    name = listing["files"][0]["name"]
    resp = keyword_part_download(listing["set"], name)
    assert Path(resp.path).read_bytes() == (_set_dir(data_dir, listing) / name).read_bytes()
    assert resp.media_type == "application/zip"
    # A leftover file that merely sits in the folder is not served, and no path is reachable.
    (_set_dir(data_dir, listing) / "stray.zip").write_bytes(b"PK")
    for bad_set, bad_name in [
        (listing["set"], "stray.zip"),
        (listing["set"], "../../../etc/passwd"),
        (listing["set"], "set.json"),
        ("..", name),
        ("not-a-keyword-set", name),
        (listing["set"] + "/../x", name),
    ]:
        with pytest.raises(HTTPException) as err:
            keyword_part_download(bad_set, bad_name)
        assert err.value.status_code == 404, (bad_set, bad_name)


def test_a_set_that_was_replaced_is_a_404_that_says_to_build_it_again(db_path, data_dir):
    from src.api.diagnostics.keyword_parts import keyword_part_download

    listing = _listing(db_path)
    name = listing["files"][0]["name"]
    for f in _set_dir(data_dir, listing).iterdir():
        f.unlink()
    _set_dir(data_dir, listing).rmdir()
    with pytest.raises(HTTPException) as err:
        keyword_part_download(listing["set"], name)
    assert err.value.status_code == 404 and "build it again" in str(err.value.detail)


def test_the_next_build_retires_an_old_set_but_not_one_still_being_downloaded(db_path, data_dir):
    first = _listing(db_path)
    d1 = _set_dir(data_dir, first)
    time.sleep(0.01)
    second = _listing(db_path)
    assert d1.exists(), "a set built a moment ago may still be on its way to the browser"
    old = time.time() - kle._PARTS_GRACE_S - 5
    os.utime(d1, (old, old))
    third = _listing(db_path)
    assert not d1.exists(), "an old set is replaced, never accumulated"
    assert _set_dir(data_dir, second).exists() and _set_dir(data_dir, third).exists()


def _age_past_the_grace(d: Path) -> None:
    old = time.time() - kle._PARTS_GRACE_S - 5
    os.utime(d, (old, old))


def test_a_build_that_fails_keeps_the_set_the_person_already_has(db_path, data_dir, small_cap, monkeypatch):
    """R115 follow-up S4. The previous set was retired BEFORE the new one was begun, so a refused,
    cancelled or failed build left no set and the page's "again" button answered 404."""
    from src.api.diagnostics.keyword_parts import keyword_parts_latest

    first = _listing(db_path)
    d1 = _set_dir(data_dir, first)
    _age_past_the_grace(d1)  # the old rule would have retired it

    def _the_drive_fills(self):
        raise OSError(errno.ENOSPC, "refused by the drive")

    monkeypatch.setattr(up.PartWriter, "_close_part", _the_drive_fills)
    with pytest.raises(HTTPException) as err:
        _call(db_path, fmt="parts")
    assert err.value.status_code == 507
    assert d1.is_dir(), "the set the person had is still there"
    assert json.loads(keyword_parts_latest().body)["set"] == first["set"], '"again" still answers'
    assert [p.name for p in data_dir.iterdir() if p.name.startswith(kle.PARTS_DIR_PREFIX)] == [d1.name]


def test_the_old_set_is_there_while_the_new_one_is_built_and_gone_once_it_is_listed(
    db_path, data_dir, small_cap, monkeypatch
):
    first = _listing(db_path)
    d1 = _set_dir(data_dir, first)
    _age_past_the_grace(d1)
    seen: list[bool] = []
    real = up.PartWriter._close_part

    def _look_then_close(self):
        seen.append(d1.is_dir())
        return real(self)

    monkeypatch.setattr(up.PartWriter, "_close_part", _look_then_close)
    second = _listing(db_path)
    assert seen and all(seen), "retiring waits for the new set"
    assert not d1.exists(), "and happens once it is whole"
    assert _set_dir(data_dir, second).is_dir()


def test_a_drive_that_cannot_take_the_listing_loses_the_new_set_not_the_old_one(
    db_path, data_dir, monkeypatch
):
    """R115 follow-up N3: a finished set without its listing is found by nothing."""
    first = _listing(db_path)
    d1 = _set_dir(data_dir, first)
    _age_past_the_grace(d1)
    real = Path.write_text

    def _refuses_the_listing(self, *a, **kw):
        if self.name == "set.json":
            raise OSError(errno.ENOSPC, "refused by the drive")
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "write_text", _refuses_the_listing)
    with pytest.raises(HTTPException) as err:
        _call(db_path, fmt="parts")
    assert err.value.status_code == 507
    assert [p.name for p in data_dir.iterdir() if p.name.startswith(kle.PARTS_DIR_PREFIX)] == [d1.name]


def _old_set(d: Path, name: str, size: int, *, aged: bool = True) -> Path:
    s = d / f"{kle.PARTS_DIR_PREFIX}{name}"
    s.mkdir()
    (s / "x.zip").write_bytes(b"0" * size)
    if aged:
        _age_past_the_grace(s)
    return s


def _free(monkeypatch, free: int) -> None:
    import collections
    import shutil

    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: usage(10 * 2**30, 10 * 2**30 - free, free))
    monkeypatch.setattr(kle, "disk_reserve", lambda _d: 0)


# With no entries and no cap the set is expected to need ZIP_FIXED_BYTES (8 MiB) plus 20% = 9.6 MiB.
_NEED_FREE = int(kle.ZIP_FIXED_BYTES * 1.2)


def test_a_set_that_fits_beside_the_old_one_does_not_retire_it_in_the_preflight(tmp_path, monkeypatch):
    old = _old_set(tmp_path, "old", 1000)
    _free(monkeypatch, _NEED_FREE + 1)
    kle.parts_disk_preflight(tmp_path, 0, None)
    assert old.is_dir()


def test_the_old_set_goes_before_the_build_only_when_its_room_is_what_lets_the_new_one_fit(
    tmp_path, monkeypatch
):
    old = _old_set(tmp_path, "old", 3 * 2**20)
    _free(monkeypatch, _NEED_FREE - 2**20)  # 1 MiB short; the old set holds 3 MiB
    kle.parts_disk_preflight(tmp_path, 0, None)
    assert not old.exists()


def test_a_set_that_does_not_fit_even_without_the_old_one_is_refused_and_the_old_one_stays(
    tmp_path, monkeypatch
):
    old = _old_set(tmp_path, "old", 1000)
    _free(monkeypatch, _NEED_FREE - 2**20)  # 1 MiB short; the old set holds 1 KB
    with pytest.raises(kle.ExportRefused) as err:
        kle.parts_disk_preflight(tmp_path, 0, None)
    assert err.value.status == 507
    assert old.is_dir()


def test_a_set_still_being_downloaded_is_never_counted_as_room(tmp_path, monkeypatch):
    young = _old_set(tmp_path, "young", 3 * 2**20, aged=False)
    _free(monkeypatch, _NEED_FREE - 2**20)
    with pytest.raises(kle.ExportRefused):
        kle.parts_disk_preflight(tmp_path, 0, None)
    assert young.is_dir()


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EROFS])
def test_a_drive_that_refuses_the_write_is_a_507_and_leaves_no_set_behind(
    db_path, data_dir, small_cap, monkeypatch, code
):
    real = up.PartWriter._close_part
    calls = {"n": 0}

    def _fails_on_the_second_file(self):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(code, "refused by the drive")
        return real(self)

    monkeypatch.setattr(up.PartWriter, "_close_part", _fails_on_the_second_file)
    with pytest.raises(HTTPException) as err:
        _call(db_path, fmt="parts")
    assert calls["n"] >= 2
    assert err.value.status_code == 507
    assert [p.name for p in data_dir.iterdir() if p.name.startswith(kle.PARTS_DIR_PREFIX)] == []


def test_with_no_data_folder_the_set_is_built_and_served_from_the_temp_folder(db_path, tmp_path, monkeypatch):
    import tempfile

    import src.api.diagnostics.keywords as kw_mod
    from src.api.diagnostics.keyword_parts import keyword_part_download

    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    monkeypatch.setattr(kw_mod, "export_dir", lambda: None)
    listing = _listing(db_path)
    assert (temp / listing["set"]).is_dir()
    resp = keyword_part_download(listing["set"], listing["files"][0]["name"])
    assert Path(resp.path).parent == temp / listing["set"]


def test_the_default_zip_and_the_json_stream_are_untouched_by_the_parts_format(db_path, data_dir):
    """``format=zip`` still answers with ONE archive for API callers and the analyzer script."""
    resp = _call(db_path, fmt="zip")
    path = Path(resp.path)
    try:
        names = zipfile.ZipFile(io.BytesIO(path.read_bytes())).namelist()
    finally:
        kle.unlink_quietly(path)
    assert "summary.json" in names and "manifest.json" in names
    assert not any(p.name.startswith(kle.PARTS_DIR_PREFIX) for p in data_dir.iterdir())


# ---------------------------------------------------------------- the order, the latest set, memory
def _sequence(set_dir: Path, listing: dict) -> list[tuple[str, int, int]]:
    """``(language, slice_from, slice_to)`` of every records member, in the order a person who
    saves the files in number order meets them."""
    out = []
    for f in listing["files"]:
        if f["kind"] != "part":
            continue
        with zipfile.ZipFile(set_dir / f["name"]) as z:
            for n in z.namelist():
                if n.startswith("keywords/"):
                    doc = json.loads(z.read(n))
                    out.append((doc["language"], doc["slice_from"], doc["slice_to"]))
    return out


def test_round_one_is_every_languages_default_window_and_the_largest_language_comes_first(
    db_path, data_dir, small_cap, monkeypatch
):
    monkeypatch.setattr(kle, "PARTS_ROUND_RECORDS", 120)
    listing = _listing(db_path)
    d = _set_dir(data_dir, listing)
    seq = _sequence(d, listing)
    sizes = {lang: max(to for lg, _f, to in seq if lg == lang) for lang, _f, _t in seq}
    rounds = [f // 120 for _lang, f, _to in seq]
    assert rounds == sorted(rounds), "no record of round two is met before the last of round one"
    assert max(rounds) >= 2, "the small round makes this a multi-round set"
    first_round = [lang for lang, f, _to in seq if f == 0]
    assert first_round == sorted(first_round, key=lambda lg: (-sizes[lg], lg)), "largest first"
    for lang, size in sizes.items():  # a language's slices follow each other with no gap
        mine = [(f, t) for lg, f, t in seq if lg == lang]
        assert mine[0][0] == 0 and mine[-1][1] == size
        assert all(a[1] == b[0] for a, b in zip(mine, mine[1:], strict=False))


def test_the_round_is_the_default_window_so_a_partial_upload_is_what_the_default_export_holds():
    from src.api.diagnostics._base import _MAX_KEYWORDS_PER_LANG

    assert kle.PARTS_ROUND_RECORDS == _MAX_KEYWORDS_PER_LANG


def test_the_orientation_files_are_numbered_first_and_the_manifest_states_the_order(
    db_path, data_dir, small_cap
):
    listing = _listing(db_path)
    d = _set_dir(data_dir, listing)
    first = next(f for f in listing["files"] if "-part-01-of-" in f["name"])
    with zipfile.ZipFile(d / first["name"]) as z:
        names = z.namelist()
        # (at this small cap the summary is cut into valid numbered pieces: summary.s001.json ...)
        assert "export-manifest.json" in names and any(n.startswith("summary") for n in names)
        assert not any(n.startswith("keywords/") for n in names), "records come after the orientation"
        index = json.loads(z.read("part.json"))
    assert "Rank-major" in index["order"]
    manifest_name = next(f["name"] for f in listing["files"] if f["kind"] == "manifest")
    with zipfile.ZipFile(d / manifest_name) as z:
        assert "Rank-major" in json.loads(z.read("manifest.json"))["order"]


def test_every_file_of_the_set_has_a_name_no_other_file_shares(db_path, data_dir, small_cap):
    listing = _listing(db_path)
    d = _set_dir(data_dir, listing)
    members: list[str] = []
    for f in listing["files"]:
        if f["kind"] == "part":
            with zipfile.ZipFile(d / f["name"]) as z:
                members += [n for n in z.namelist() if n != up.PART_INDEX_NAME]
    assert len(members) == len(set(members)), "unzipping every part into one folder loses nothing"


def test_the_summary_of_a_set_is_the_summary_of_the_single_archive(db_path, data_dir, monkeypatch):
    import src.api.diagnostics.keywords as kw_mod

    # The family budget is read from the memory available when an export starts; pin it so the two
    # builds are given the same one.
    monkeypatch.setattr(
        kw_mod, "memory_plan", lambda _a: {"heap_rows": 10**6, "batch": 800, "family_rows": 10**6}
    )
    resp = _call(db_path, fmt="zip")
    path = Path(resp.path)
    try:
        with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as z:
            whole = json.loads(z.read("summary.json"))
    finally:
        kle.unlink_quietly(path)
    listing = _listing(db_path)
    d = _set_dir(data_dir, listing)
    parts = None
    for f in listing["files"]:
        if f["kind"] == "part":
            with zipfile.ZipFile(d / f["name"]) as z:
                if "summary.json" in z.namelist():
                    parts = json.loads(z.read("summary.json"))
    assert parts is not None
    for doc in (whole, parts):
        doc.pop("generated_at", None)
        doc.pop("query", None)
    assert parts == whole


def test_the_latest_route_lists_the_newest_set_without_rebuilding_it(db_path, data_dir):
    from src.api.diagnostics.keyword_parts import keyword_parts_latest

    with pytest.raises(HTTPException) as err:
        keyword_parts_latest()
    assert err.value.status_code == 404 and "build it again" in str(err.value.detail)
    first = _listing(db_path)
    d1 = _set_dir(data_dir, first)
    old = time.time() - 30
    os.utime(d1 / "set.json", (old, old))
    second = _listing(db_path)
    got = json.loads(keyword_parts_latest().body)
    assert got["set"] == second["set"] and got["files"] == second["files"]
    assert got["set"] != first["set"]
    before = sorted(p.name for p in data_dir.iterdir())
    keyword_parts_latest()
    assert sorted(p.name for p in data_dir.iterdir()) == before, "reading the listing builds nothing"


def test_a_download_counts_as_use_so_a_set_being_saved_is_not_retired_under_the_page(
    db_path, data_dir
):
    from src.api.diagnostics.keyword_parts import keyword_part_download

    first = _listing(db_path)
    d1 = _set_dir(data_dir, first)
    old = time.time() - kle._PARTS_GRACE_S - 60
    os.utime(d1, (old, old))
    keyword_part_download(first["set"], first["files"][0]["name"])  # the page is still saving files
    _listing(db_path)  # another tab builds a new set
    assert d1.exists(), "the set a person is saving from stays"


def test_building_a_set_holds_a_batch_in_memory_not_the_window(tmp_path_factory, monkeypatch):
    """#1277's property, for the numbered set: 6x the keywords must not cost 6x the memory."""
    import src.api.diagnostics.keywords as kw_mod
    from src.analytics import keyword_log_scan as kls
    from tests.test_keyword_export_bounded import _peak_python_bytes

    root = tmp_path_factory.mktemp("kw-parts-flat")
    monkeypatch.setenv("OO_DATA_DIR", str(root))
    monkeypatch.setattr(
        kls, "memory_plan", lambda _a: {"heap_rows": 500, "batch": 800, "family_rows": 900}
    )
    monkeypatch.setattr(kw_mod, "memory_plan", kls.memory_plan)

    def one(n: int) -> int:
        p = root / f"flat{n}.db"
        _build(p, 5, articles=300, keywords=n, with_boilerplate=False)
        db = _session(p)
        try:
            return _peak_python_bytes(lambda: _call_with(db, fmt="parts"))
        finally:
            db.close()

    one(2_000)
    small, big = one(4_000), one(24_000)
    assert big < small * 1.5 + 2_000_000, (small, big)
    assert big < 10_000_000, (small, big)


def test_building_a_set_holds_one_batch_however_many_languages_it_spans(tmp_path_factory, monkeypatch):
    """The set is written rank-major, a round of every language in turn, so a language's stream
    is alive for the whole export. If each kept a batch (its rows, metadata and signatures)
    between rounds, memory would grow with the number of LANGUAGES (about 1.5 MB each at a batch
    of 2,000, so ~500 MB for the largest instance's 82 languages at the production batch): the
    Opus review of the first version measured exactly that. This holds the per-language size
    fixed and varies how many languages there are."""
    import src.api.diagnostics.keywords as kw_mod
    from src.analytics import keyword_log_scan as kls
    from tests import test_keyword_export_bounded as tkeb

    root = tmp_path_factory.mktemp("kw-parts-langs")
    monkeypatch.setenv("OO_DATA_DIR", str(root))
    monkeypatch.setattr(
        kls, "memory_plan", lambda _a: {"heap_rows": 500, "batch": 800, "family_rows": 900}
    )
    monkeypatch.setattr(kw_mod, "memory_plan", kls.memory_plan)
    monkeypatch.setattr(kle, "PARTS_ROUND_RECORDS", 500)  # five rounds at 2,400 keywords a language

    def peak_for(n_langs: int) -> int:
        monkeypatch.setattr(tkeb, "LANGS", [f"l{i:02d}" for i in range(n_langs)])
        p = root / f"l{n_langs}.db"
        _build(p, 3, articles=3_000, keywords=n_langs * 2_400, with_boilerplate=False)
        db = _session(p)
        try:
            _call_with(db, fmt="parts")  # warm the imports, so the first measure is not charged for them
            return tkeb._peak_python_bytes(lambda: _call_with(db, fmt="parts"))
        finally:
            db.close()

    few, many = peak_for(4), peak_for(20)
    # Sixteen more languages cost the old shape ~25 MB; the cursor shape costs what the extra
    # keywords' own digests cost, well under a megabyte a language.
    assert many < few + 6_000_000, (few, many)


def _call_with(db, **kw):
    from src.api.diagnostics.keywords import keyword_log

    kw.setdefault("digest", False)
    kw.setdefault("per_lang", 1_000_000)
    kw.setdefault("page", 1)
    kw.setdefault("max_mb", 0)
    return keyword_log(db=db, **kw)


def test_a_failed_build_closes_the_open_part_before_its_folder_goes(tmp_path, monkeypatch):
    """`finish_parts` aborts the writer on ANY exception (a refusal, a memory stop, a bug): the part
    being written is closed, then the whole folder is removed. On Linux the removal succeeds with a
    handle still open, so the only thing that shows the abort happened is the writer's own state,
    which is what this reads; where an open handle blocks a delete, that leak is the whole defect."""
    from types import SimpleNamespace

    made: list[up.PartWriter] = []

    class Spy(up.PartWriter):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            made.append(self)

    monkeypatch.setattr(kle, "PartWriter", Spy)

    def write_parts(writer, _keep, _omitted):
        g = up.RecordGroup("keywords/en.json", {"language": "en"}, "keywords", 700)
        for i in range(700):          # past one chunk: the first part is open and holds records
            writer.add_record(g, json.dumps({"keyword": f"w{i}", "mentions": i}))
        assert writer._part is not None, "the test must fail with a part open"
        raise RuntimeError("the build failed after the first part was opened")

    job = SimpleNamespace(check=None, disk_watch=None, max_bytes=None, write_parts=write_parts)
    with pytest.raises(RuntimeError, match="the build failed"):
        kle.finish_parts(job, {"en": 700}, scratch_dir=tmp_path, stem="oo-keyword-log-20261001-000000")
    assert len(made) == 1
    assert made[0]._part is None, "the open part was closed (abort) before the folder was removed"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(kle.PARTS_DIR_PREFIX)], "and the folder is gone"
