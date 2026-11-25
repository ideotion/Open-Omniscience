"""
Row 378 (R807 (2) option A; ruled R836, R837 amends its Q1): the erase judges ten folders entry by entry.

``models``, ``cache``, ``runtime``, ``leases``, ``wiki_dumps``, ``osm_regions``, ``osm_work``, ``ip_geo``, ``weather_context`` and
``osm_borders`` were removed whole in a folder of the app's own (an operator's file in one went with it) and left whole in a shared
folder (the app's own model weights and leases stayed). Now, in both scopes and in both erasers (the in-process erase and the
uninstall watcher), only the first-level entries that fit a shape the app writes go; anything else, a link or an entry that is not
a plain file or folder is left and counted, never followed and never named, and a folder that still holds such items stays, and
the data folder with it, said as "not complete" (Q2). ``models/ollama`` and ``models/huggingface`` are the app's only while their
own first level holds nothing but what Ollama and Hugging Face write there (R837), judged through the handle that removes them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from src.safety import crypto_erase, data_scope
from src.safety.data_scope import (
    SHAPED_DIRS,
    WHOLE_DIRS,
    second_level_ok,
    shaped_match,
    shaped_spec,
)

_ROOT = Path(__file__).resolve().parents[1]

#: Every shape, with names on each side of it: the PR lists these (R836 Q1: "say which side it fell on").
_SIDES = {
    "models": (["ollama/", "huggingface/"], ["ollama", "llama.bin", "Ollama/", "my-models/"]),
    "cache": (["vllm-config/"], ["vllm-config", "pip/", "torch/", "fontconfig/"]),
    "runtime": (["ollama-install-0123456789abcdef.sh", "ollama-install-0123456789abcdef.sh.tmp.12.34"],
                ["ollama-install.sh", "ollama-install-0123456789ABCDEF.sh", "install.sh", "ollama-install-0123456789abcdef.sh/"]),
    "leases": (["reindex." + "0" * 32 + ".lease", "storage-guard-drain." + "a" * 32 + ".lease.tmp.1.2"],
               ["reindex.lease", "x." + "0" * 31 + ".lease", "Reindex." + "0" * 32 + ".lease", "notes.txt"]),
    "wiki_dumps": (["downloads.json", "downloads.json.tmp", "enwiki-latest-pages-articles-multistream.xml.bz2",
                    "zh-min-nanwiki-latest-pages-articles-multistream-index.txt.bz2", "dewiki-latest-pages-articles.xml.bz2",
                    "frwiki-latest-pages-articles-multistream.xml.bz2.oopart", "dump_index.sqlite", "dump_index.sqlite-wal"],
                   ["enwiki.xml.bz2", "enwiki-20240101-pages-articles.xml.bz2", "mine.txt", "x" * 33 + "wiki-latest-pages-articles.xml.bz2",
                    "downloads.json/"]),
    "osm_regions": (["downloads.json", "europe-latest.osm.pbf", "north-america-latest.osm.pbf.tmp.5.6", "planet-latest.osm.pbf"],
                    ["europe.osm.pbf", "us-west-latest.osm.pbf.bak", "Europe-latest.osm.pbf", "a" * 65 + "-latest.osm.pbf"]),
    "osm_work": (["FRA-123.osc.gz", "osm-locations.sqlite", "osm-locations.sqlite-journal", "osm-locations.idx"],
                 ["fra-123.osc.gz", "FRA-.osc.gz", "state.txt"]),
    "ip_geo": (["dbip_city_lite.csv", "dbip_city_lite.csv.gz"], ["dbip_city_lite.mmdb", "GeoLite2-City.mmdb"]),
    "weather_context": (["0123456789abcdef01234567.json"], ["0123456789abcdef0123456.json", "place.json"]),
    "osm_borders": (["admin0.world.json", "admin1.world.json"], ["detail/", "admin2.world.json", "world.json"]),
}


def _fits(folder: str, entry: str, *, shared: bool = False) -> bool:
    kind = "dir" if entry.endswith("/") else "file"
    return shaped_match(shaped_spec(shared=shared)[folder], entry.rstrip("/"), kind) is not None


@pytest.mark.parametrize("folder", sorted(SHAPED_DIRS))
def test_each_shape_takes_what_the_app_writes_and_nothing_else(folder):
    mine, theirs = _SIDES[folder]
    for name in mine:
        assert _fits(folder, name), (folder, name)
    for name in theirs:
        assert not _fits(folder, name), (folder, name)


def test_every_shaped_folder_is_listed_with_its_sides_and_none_is_removed_whole():
    assert set(_SIDES) == set(SHAPED_DIRS)
    assert set(WHOLE_DIRS).isdisjoint(SHAPED_DIRS) and "keys" not in WHOLE_DIRS
    assert set(WHOLE_DIRS) | set(SHAPED_DIRS) | {"keys"} == set(data_scope.APP_DIRS)


def test_the_bare_cache_names_are_the_app_s_only_in_its_own_folder():
    """R837: the generic cache names are owned by name in a folder of the app's own, left and counted in a shared one."""
    for name in ("triton", "inductor", "nv", "vllm", "huggingface"):
        assert _fits("cache", name + "/") and not _fits("cache", name + "/", shared=True), name
    assert _fits("cache", "vllm-config/", shared=True)


def test_the_second_level_rules():
    ollama = shaped_match(shaped_spec(shared=True)["models"], "ollama", "dir")
    hf = shaped_match(shaped_spec(shared=True)["models"], "huggingface", "dir")
    assert second_level_ok(ollama, [("blobs", "dir"), ("manifests", "dir")]) and second_level_ok(ollama, [])
    assert not second_level_ok(ollama, [("blobs", "dir"), ("my.gguf", "file")])
    assert not second_level_ok(ollama, [("blobs", "link")]), "a symlinked blobs folder"
    assert not second_level_ok(ollama, [("manifests", "file")])
    assert second_level_ok(hf, [("hub", "dir"), ("xet", "dir"), ("token", "file"), ("stored_tokens", "file")])
    assert not second_level_ok(hf, [("hub", "dir"), ("datasets", "dir")])
    assert not second_level_ok(hf, [("token", "link")])


# -- the in-process erase ------------------------------------------------------------------------------------------------------


def _app_entries(data: Path) -> None:
    (data / "models" / "ollama" / "blobs").mkdir(parents=True)
    (data / "models" / "ollama" / "blobs" / "sha256-00").write_bytes(b"W" * 100)
    (data / "models" / "ollama" / "manifests" / "registry").mkdir(parents=True)
    (data / "models" / "huggingface" / "hub").mkdir(parents=True)
    (data / "models" / "huggingface" / "token").write_bytes(b"hf_token")
    (data / "cache" / "vllm-config").mkdir(parents=True)
    (data / "cache" / "triton").mkdir()
    (data / "cache" / "triton" / "kernel.bin").write_bytes(b"K")
    (data / "runtime").mkdir()
    (data / "runtime" / "ollama-install-0123456789abcdef.sh").write_bytes(b"#!/bin/sh")
    (data / "leases").mkdir()
    (data / "leases" / ("reindex." + "0" * 32 + ".lease")).write_text("{}", encoding="utf-8")
    (data / "wiki_dumps").mkdir()
    (data / "wiki_dumps" / "enwiki-latest-pages-articles-multistream.xml.bz2").write_bytes(b"D" * 100)
    (data / "wiki_dumps" / "downloads.json").write_text("{}", encoding="utf-8")
    (data / "osm_regions").mkdir()
    (data / "osm_regions" / "europe-latest.osm.pbf").write_bytes(b"P")
    (data / "app_settings.json").write_text("{}", encoding="utf-8")


def _own(tmp_path: Path) -> Path:
    data = tmp_path / "OOS data"
    data.mkdir()
    return data


@pytest.fixture(params=["handle", "path"])
def walk(request, monkeypatch):
    """Both walks: by the data folder's handle (POSIX) and by path (Windows, and the fallback)."""
    if request.param == "handle" and (sys.platform == "win32" or not hasattr(os, "O_DIRECTORY")):
        pytest.skip("POSIX folder handles")
    if request.param == "path":
        monkeypatch.setattr(crypto_erase, "_walk_fd", lambda hold: None)
    return request.param


def test_a_folder_of_the_app_s_own_holding_only_app_entries_is_removed_whole(tmp_path, walk):
    data = _own(tmp_path)
    _app_entries(data)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert not data.exists() and report["removed"] is True
    assert report["shaped_left"] == {} and report["folder_kept_foreign"] is False
    assert "not complete" not in report["limit"]


def test_an_operator_s_file_in_a_shaped_folder_stays_untouched_and_keeps_the_data_folder(tmp_path, walk):
    data = _own(tmp_path)
    _app_entries(data)
    (data / "wiki_dumps" / "my notes.txt").write_bytes(b"the operator's own")
    (data / "models" / "my-model.gguf").write_bytes(b"own weights")
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert (data / "wiki_dumps" / "my notes.txt").read_bytes() == b"the operator's own", "never written, never removed"
    assert (data / "models" / "my-model.gguf").read_bytes() == b"own weights"
    assert sorted(p.name for p in (data / "wiki_dumps").iterdir()) == ["my notes.txt"]
    assert sorted(p.name for p in (data / "models").iterdir()) == ["my-model.gguf"], "the app's ollama and huggingface went"
    assert sorted(p.name for p in data.iterdir()) == ["models", "wiki_dumps"], "every other entry of the data folder went"
    assert report["removed"] is False and report["folder_kept_foreign"] is True and report["kept_items"] == 2
    assert report["shaped_left"] == {"models": 1, "wiki_dumps": 1} and report["not_removed"] == []
    assert "the erase of the data folder is not complete (count: 2)" in report["limit"]
    assert crypto_erase._LIMIT_NOTE not in report["limit"], "the clean guarantee is never said beside 'not complete'"
    assert "my notes" not in json.dumps(report) and "my-model" not in json.dumps(report), "no user file names (R806)"
    assert crypto_erase.settle_removed(report) is False and report["folder_kept_foreign"] is True
    assert report["not_removed"] == [], "kept on purpose: never said as a removal that failed"


@pytest.mark.parametrize("extra", ["file", "blobs-link"])
def test_an_ollama_folder_holding_anything_else_is_left_whole_and_counted_once(tmp_path, walk, extra):
    data = _own(tmp_path)
    _app_entries(data)
    ollama = data / "models" / "ollama"
    if extra == "file":
        (ollama / "my.gguf").write_bytes(b"own")
    else:
        outside = tmp_path / "outside-blobs"
        outside.mkdir()
        (outside / "sha256-11").write_bytes(b"OUTSIDE")
        for p in (ollama / "blobs").iterdir():
            p.unlink()
        (ollama / "blobs").rmdir()
        (ollama / "blobs").symlink_to(outside, target_is_directory=True)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert (ollama / "manifests" / "registry").is_dir(), "the whole entry is left: nothing in it is written or removed"
    if extra == "file":
        assert (ollama / "my.gguf").read_bytes() == b"own" and (ollama / "blobs" / "sha256-00").read_bytes() == b"W" * 100
    else:
        assert (ollama / "blobs").is_symlink() and (tmp_path / "outside-blobs" / "sha256-11").read_bytes() == b"OUTSIDE"
    assert not (data / "models" / "huggingface").exists(), "its neighbour still fits and went"
    assert report["shaped_left"] == {"models": 1} and report["kept_items"] == 1


def test_a_huggingface_folder_holding_anything_else_is_left(tmp_path, walk):
    data = _own(tmp_path)
    _app_entries(data)
    (data / "models" / "huggingface" / "datasets").mkdir()
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert (data / "models" / "huggingface" / "datasets").is_dir() and (data / "models" / "huggingface" / "hub").is_dir()
    assert not (data / "models" / "huggingface" / "token").exists(), "a credential: taken by its exact name in the app's own folder"
    assert not (data / "models" / "ollama").exists()
    assert report["shaped_left"] == {"models": 1} and report["hf_token_left"] == []


def test_a_link_in_a_shaped_folder_is_never_followed_and_is_counted(tmp_path, walk):
    data = _own(tmp_path)
    _app_entries(data)
    target = tmp_path / "outside.osm.pbf"
    target.write_bytes(b"OUTSIDE")
    (data / "osm_regions" / "asia-latest.osm.pbf").symlink_to(target)  # fits the name, but a link never fits a shape
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert target.read_bytes() == b"OUTSIDE"
    assert (data / "osm_regions" / "asia-latest.osm.pbf").is_symlink()
    assert report["shaped_left"] == {"osm_regions": 1}


def test_an_ollama_folder_changed_after_it_was_judged_is_not_removed(tmp_path, monkeypatch):
    """R837: the second-level check is made again through the handle that removes it, so a folder that stopped fitting between
    the walk and the removal is left."""
    if sys.platform == "win32" or not hasattr(os, "O_DIRECTORY"):
        pytest.skip("POSIX folder handles")
    data = _own(tmp_path)
    _app_entries(data)
    real = crypto_erase._remove_shaped

    def late(roots, base, dfd):
        (data / "models" / "ollama" / "mine.txt").write_bytes(b"written after the walk")
        return real(roots, base, dfd)

    monkeypatch.setattr(crypto_erase, "_remove_shaped", late)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert (data / "models" / "ollama" / "mine.txt").read_bytes() == b"written after the walk"
    assert report["shaped_left"] == {"models": 1}


def test_an_unlistable_shaped_folder_is_could_not_check(tmp_path):
    if os.name != "posix" or os.geteuid() == 0:
        pytest.skip("mode bits (and not root)")
    data = _own(tmp_path)
    _app_entries(data)
    (data / "wiki_dumps").chmod(0o300)
    try:
        report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    finally:
        (data / "wiki_dumps").chmod(0o700)
    assert report["unlisted_folders"] >= 1 and (data / "wiki_dumps").is_dir()
    assert report["removed"] is False


def test_in_a_shared_folder_the_app_s_shaped_entries_go_and_the_rest_stays(tmp_path, monkeypatch, walk):
    """R836 Q1: in a folder the app does not own, the app's entries in cache, leases, models and runtime are removed now (they were
    left whole); the bare cache names are left and counted (R837)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "holiday.jpg").write_bytes(b"jpeg")
    _app_entries(tmp_path)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)
    assert report["scope"] == "app-only"
    assert (tmp_path / "holiday.jpg").read_bytes() == b"jpeg"
    for gone in ("models", "runtime", "leases", "wiki_dumps", "osm_regions", "app_settings.json"):
        assert not (tmp_path / gone).exists(), gone
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == ["triton"], "vllm-config went, the bare name stays"
    assert (tmp_path / "cache" / "triton" / "kernel.bin").read_bytes() == b"K"
    assert report["shaped_left"] == {"cache": 1} and report["left_untouched"] == ["holiday.jpg"]
    assert report["left_common_names"] == [] and report["kept_items"] == 2
    assert "folders, because the app did not create them" in report["limit"]


def test_every_folder_the_notice_names_is_removed_whole_in_a_shared_folder(tmp_path, monkeypatch):
    """R836 S1: the folder list the notice shows is the code's own (data_scope.WHOLE_DIRS, served by the endpoint), and each of
    those folders goes whole, a file of the operator's in it included; each shaped folder does not."""
    from src.api import unlock

    unlock._data_folder_scope.cache_clear()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "holiday.jpg").write_bytes(b"jpeg")
    for name in (*WHOLE_DIRS, *SHAPED_DIRS):
        (tmp_path / name).mkdir()
        (tmp_path / name / "mine.txt").write_bytes(b"own")
    assert unlock._data_folder_scope(str(tmp_path))["whole_folders"] == list(WHOLE_DIRS)
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)
    for name in WHOLE_DIRS:
        assert not (tmp_path / name).exists(), name
    for name in SHAPED_DIRS:
        assert (tmp_path / name / "mine.txt").read_bytes() == b"own", name
    unlock._data_folder_scope.cache_clear()


def test_the_notice_draws_the_server_s_list_into_the_sentence_and_the_result_says_not_complete():
    js = (_ROOT / "src/static/data-volume.js").read_text(encoding="utf-8")
    s1 = "Folders with the app’s own names ({folders}) are removed whole, even if you put files of your own in them."
    assert s1 in js and "paintWhole(whole, sc.whole_folders)" in js and "folders.join(\", \")" in js and "oo:langchange" in js
    assert not re.search(r"Folders with the app’s own names \([a-z_]", js), "the list is never typed into the page"
    backup = (_ROOT / "src/static/app-backup.js").read_text(encoding="utf-8")
    s2 = ("Items were left in the app’s {folders} folders, because the app did not create them or wrote them under an older name: "
          "the erase of the data folder is not complete (count: {n}).")
    assert s2 in backup and "r.shaped_left" in backup
    assert crypto_erase._SHAPED_LEFT_SENTENCE.replace("app's", "app’s") == s2
    for lang in ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        loc = json.loads((_ROOT / f"src/static/locales/{lang}.json").read_text(encoding="utf-8"))
        for key in (s1, s2):
            assert "{folders}" in loc[key], (lang, key)
        assert "{n}" in loc[s2], lang
        assert "destr" not in loc[s1].lower(), "never 'destroyed' (R797/R815)"


# -- the uninstall watcher -----------------------------------------------------------------------------------------------------


def _run_watcher(tmp_path: Path, data: Path, *, broad: bool) -> str:
    import subprocess

    from src.safety import uninstall

    log = tmp_path / "uninstall-audit.log"
    plan = {"files": [], "venv": None, "app_folder": None, "wipe_data_dir": str(data), "wipe_store_dir": None, "passes": None,
            "enc_names": [], "app_only": uninstall._app_only({"broad": True, "reason": "shared_folder"} if broad else None),
            "keys_spec": uninstall._keys_spec(), "hf_token_files": list(uninstall._hf_token_files()),
            "shaped_spec": uninstall._shaped_spec({"broad": broad}), "audit_log": str(log)}
    src = uninstall._WATCHER_SRC.replace("__PID_PROBE__", "def pid_alive(p): return False")
    subprocess.run([sys.executable, "-I", "-c", src, "999999999", json.dumps(plan)], check=True, timeout=60, cwd=tmp_path)
    return log.read_text(encoding="utf-8") if log.exists() else ""


def test_the_watcher_keeps_an_operator_s_file_in_a_shaped_folder(tmp_path):
    data = _own(tmp_path)
    _app_entries(data)
    (data / "wiki_dumps" / "my notes.txt").write_bytes(b"the operator's own")
    (data / "models" / "ollama" / "extra.bin").write_bytes(b"own")
    log = _run_watcher(tmp_path, data, broad=False)
    assert (data / "wiki_dumps" / "my notes.txt").read_bytes() == b"the operator's own"
    assert (data / "models" / "ollama" / "extra.bin").read_bytes() == b"own"
    assert (data / "models" / "ollama" / "blobs" / "sha256-00").read_bytes() == b"W" * 100, "the whole entry is left"
    assert sorted(p.name for p in data.iterdir()) == ["models", "wiki_dumps"]
    assert not (data / "models" / "huggingface").exists()
    assert "THE ERASE OF THE DATA FOLDER IS NOT COMPLETE" in log and "(count: 2)" in log
    assert "my notes" not in log and "extra.bin" not in log, "no user file names (R806)"
    assert "DB salt pages destroyed" not in log


def test_the_watcher_removes_a_folder_holding_only_app_entries_whole(tmp_path):
    data = _own(tmp_path)
    _app_entries(data)
    log = _run_watcher(tmp_path, data, broad=False)
    assert not data.exists()
    assert "NOT COMPLETE" not in log


def test_the_watcher_in_a_shared_folder(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "holiday.jpg").write_bytes(b"jpeg")
    _app_entries(shared)
    log = _run_watcher(tmp_path, shared, broad=True)
    assert (shared / "holiday.jpg").read_bytes() == b"jpeg"
    for gone in ("models", "runtime", "leases", "wiki_dumps", "osm_regions", "app_settings.json"):
        assert not (shared / gone).exists(), gone
    assert sorted(p.name for p in (shared / "cache").iterdir()) == ["triton"]
    assert "(count: 1)" in log and "NOT COMPLETE" in log


def test_the_hugging_face_home_names_are_an_explicit_list():
    """Coordinator on R837: the accepted Hugging Face names are an explicit list in code, never a pattern."""
    assert data_scope.HF_HOME_DIRS == ("hub", "xet") and data_scope.HF_TOKEN_FILES == ("token", "stored_tokens")
    hf = shaped_match(shaped_spec(shared=False)["models"], "huggingface", "dir")
    assert hf["second"] == {"dirs": ["hub", "xet"], "files": ["token", "stored_tokens"]}
    assert not second_level_ok(hf, [("hubs", "dir")]) and not second_level_ok(hf, [("token.bak", "file")])


def test_the_token_files_go_in_the_early_pass_with_the_key_material(tmp_path, monkeypatch):
    """They hold credentials: destroyed in step 2b, right after the keys and before the DuckDB cache, the passphrase and 5b/6."""
    data = _own(tmp_path)
    _app_entries(data)
    (data / "models" / "huggingface" / "stored_tokens").write_bytes(b"more tokens")
    (data / "cache" / "huggingface").mkdir()
    (data / "cache" / "huggingface" / "token").write_bytes(b"cache token")
    order: list[str] = []
    shred, overwrite = crypto_erase._shred, crypto_erase._overwrite

    def note(real):
        def call(path, **kw):
            if Path(path).exists():  # step 1 also looks at database names that are not there
                order.append(Path(path).relative_to(data).as_posix())
            return real(path, **kw)
        return call

    monkeypatch.setattr(crypto_erase, "_shred", note(shred))
    monkeypatch.setattr(crypto_erase, "_overwrite", note(overwrite))  # 5b's head pass too
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    tokens = {"models/huggingface/token", "models/huggingface/stored_tokens", "cache/huggingface/token"}
    first = list(dict.fromkeys(order))  # _shred overwrites through _overwrite: one name, two calls
    assert set(first[:3]) == tokens, first
    assert len(first) > 3, "the rest came after"


def test_a_shared_folder_s_cache_huggingface_token_is_never_entered(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "holiday.jpg").write_bytes(b"jpeg")
    (tmp_path / "cache" / "huggingface").mkdir(parents=True)
    (tmp_path / "cache" / "huggingface" / "token").write_bytes(b"theirs")
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)
    assert (tmp_path / "cache" / "huggingface" / "token").read_bytes() == b"theirs"


# -- the two security reads -----------------------------------------------------------------------------------------------------


def test_a_file_at_a_shaped_name_is_overwritten_as_before_in_both_walks(tmp_path, walk):
    """A regular file called ``osm_work`` is the app's by its name: overwritten and removed, never only unlinked."""
    data = _own(tmp_path)
    (data / "osm_work").write_bytes(b"S" * 4096)
    twin = tmp_path / "twin"
    os.link(data / "osm_work", twin)  # a second name shows whether it was written
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert not data.exists() and twin.read_bytes() != b"S" * 4096


def test_a_file_at_a_shaped_name_in_a_shared_folder_goes_in_both_walks(tmp_path, monkeypatch, walk):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "holiday.jpg").write_bytes(b"jpeg")
    (tmp_path / "wiki_dumps").write_bytes(b"x")
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)
    assert not (tmp_path / "wiki_dumps").exists() and report["not_removed"] == []


def test_an_entry_that_cannot_be_looked_at_is_could_not_check_and_never_named(tmp_path, monkeypatch):
    """The first security read: an entry of a shaped folder that cannot be looked at went into the report and the log by its
    own name. Now its FOLDER is "could not check" (R798) and the entry is neither taken nor counted."""
    data = _own(tmp_path)
    _app_entries(data)
    (data / "cache" / "my-private-name.txt").write_bytes(b"own")
    real = crypto_erase._kind

    def kind(p, unreached=None, at=None):
        if Path(p).name == "my-private-name.txt":
            if unreached is not None:
                unreached(p)
            return "unreached"
        return real(p, unreached, at)

    monkeypatch.setattr(crypto_erase, "_kind", kind)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert "my-private-name" not in json.dumps(report)
    assert report["unlisted_folders"] >= 1 and (data / "cache" / "my-private-name.txt").read_bytes() == b"own"
    assert report["shaped_left"].get("cache", 0) == 0, "never counted as an item the app did not create"


def test_an_ollama_folder_whose_first_level_cannot_be_listed_is_could_not_check(tmp_path, monkeypatch, walk):
    data = _own(tmp_path)
    _app_entries(data)
    monkeypatch.setattr(crypto_erase, "_second_ok_fd", lambda fd, shape: None)
    monkeypatch.setattr(crypto_erase, "_second_ok_path", lambda p, shape: None)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert (data / "models" / "ollama" / "blobs" / "sha256-00").exists()
    assert report["unlisted_folders"] >= 1 and report["shaped_left"].get("models", 0) == 0


def test_an_entry_judged_a_file_that_is_a_folder_by_the_walk_is_never_entered(tmp_path, monkeypatch, walk):
    data = _own(tmp_path)
    _app_entries(data)
    real = crypto_erase._erase_roots
    calls: list[int] = []

    def roots(base, **kw):
        out = real(base, **kw)
        calls.append(1)
        if len(calls) == 2:  # step 6 listed it as a file; it becomes a folder of the operator's before the walk reaches it
            target = data / "runtime" / "ollama-install-0123456789abcdef.sh"
            target.unlink()
            target.mkdir()
            (target / "mine.txt").write_bytes(b"own")
        return out

    monkeypatch.setattr(crypto_erase, "_erase_roots", roots)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert (data / "runtime" / "ollama-install-0123456789abcdef.sh" / "mine.txt").read_bytes() == b"own"
    assert report["shaped_left"] == {"runtime": 1}


def test_an_operator_s_empty_folder_with_a_shaped_name_stays_in_a_shared_folder(tmp_path, monkeypatch, walk):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "holiday.jpg").write_bytes(b"jpeg")
    (tmp_path / "models").mkdir()
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)
    assert (tmp_path / "models").is_dir() and report["shaped_left"] == {} and report["not_removed"] == []


@pytest.mark.parametrize("name", ["wiki_dumps.tmp", "models.oopart", "osm_regions.part"])
def test_a_variant_of_a_shaped_name_is_never_taken_whole_in_a_shared_folder(tmp_path, monkeypatch, name):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "holiday.jpg").write_bytes(b"jpeg")
    (tmp_path / name).mkdir()
    (tmp_path / name / "mine.txt").write_bytes(b"own")
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)
    assert report["scope"] == "app-only"
    assert (tmp_path / name / "mine.txt").read_bytes() == b"own" and name in report["left_untouched"]


def test_a_token_in_a_shared_folder_s_home_that_does_not_fit_is_left_and_said(tmp_path, monkeypatch):
    """Coordinator's ruling: in a folder the app does not own, a token is taken only in a home that fits R837; one seen and left
    is said in plain words (a sign-in token may remain; revoke it in the Hugging Face account)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "holiday.jpg").write_bytes(b"jpeg")
    (tmp_path / "models" / "huggingface" / "hub").mkdir(parents=True)
    (tmp_path / "models" / "huggingface" / "modules").mkdir()
    (tmp_path / "models" / "huggingface" / "token").write_bytes(b"theirs?")
    (tmp_path / "cache" / "huggingface").mkdir(parents=True)
    (tmp_path / "cache" / "huggingface" / "token").write_bytes(b"theirs")
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)
    assert (tmp_path / "models" / "huggingface" / "token").read_bytes() == b"theirs?"
    assert report["hf_token_left"] == ["cache/huggingface", "models/huggingface"]
    assert "A Hugging Face sign-in token may remain in cache/huggingface, models/huggingface:" in report["limit"]
    assert "destroy" not in crypto_erase._HF_TOKEN_LEFT_SENTENCE


def test_a_token_whose_overwrite_fails_is_said_to_remain(tmp_path, monkeypatch):
    data = _own(tmp_path)
    _app_entries(data)
    real = crypto_erase._shred

    def shred(path, **kw):
        if Path(path).name == "token":
            return True, False, False
        return real(path, **kw)

    monkeypatch.setattr(crypto_erase, "_shred", shred)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["hf_token_left"] == ["models/huggingface"]


def test_settle_no_longer_says_left_a_shaped_folder_removed_since(tmp_path, walk):
    data = _own(tmp_path)
    _app_entries(data)
    (data / "wiki_dumps" / "mine.txt").write_bytes(b"own")
    (data / "models" / "mine.txt").write_bytes(b"own")
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["shaped_left"] == {"models": 1, "wiki_dumps": 1}
    import shutil

    shutil.rmtree(data / "wiki_dumps")
    crypto_erase.settle_removed(report)
    assert report["shaped_left"] == {"models": 1}


def test_the_watcher_takes_the_token_in_its_own_folder_whatever_else_the_home_holds(tmp_path):
    data = _own(tmp_path)
    _app_entries(data)
    (data / "models" / "huggingface" / "modules").mkdir()
    log = _run_watcher(tmp_path, data, broad=False)
    assert not (data / "models" / "huggingface" / "token").exists()
    assert (data / "models" / "huggingface" / "modules").is_dir()
    assert "sign-in token may remain" not in log


def test_the_watcher_says_a_token_left_in_a_shared_folder(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "holiday.jpg").write_bytes(b"jpeg")
    (shared / "models" / "huggingface" / "modules").mkdir(parents=True)
    (shared / "models" / "huggingface" / "token").write_bytes(b"theirs?")
    (shared / "models").chmod(0o755)
    log = _run_watcher(tmp_path, shared, broad=True)
    assert (shared / "models" / "huggingface" / "token").read_bytes() == b"theirs?"
    assert "a Hugging Face sign-in token may remain in models/huggingface of" in log


def test_the_watcher_never_names_an_entry_it_could_not_look_at_and_keeps_an_operator_s_empty_folder(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "holiday.jpg").write_bytes(b"jpeg")
    (shared / "models").mkdir()
    (shared / "wiki_dumps.tmp").mkdir()
    (shared / "wiki_dumps.tmp" / "mine.txt").write_bytes(b"own")
    _run_watcher(tmp_path, shared, broad=True)
    assert (shared / "models").is_dir(), "an operator's own empty folder the erase took nothing from"
    assert (shared / "wiki_dumps.tmp" / "mine.txt").read_bytes() == b"own"


def test_the_token_sentence_is_the_same_on_the_page_in_the_result_and_in_twelve_languages():
    s3 = "A Hugging Face sign-in token may remain in {folders}: you can revoke it in your Hugging Face account."
    assert s3 == crypto_erase._HF_TOKEN_LEFT_SENTENCE
    backup = (_ROOT / "src/static/app-backup.js").read_text(encoding="utf-8")
    assert s3 in backup and "r.hf_token_left" in backup and "!leftOver && !shapedN && !hfTokenLeft.length" in backup, "a token or an item left is never a clean result"
    for lang in ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        loc = json.loads((_ROOT / f"src/static/locales/{lang}.json").read_text(encoding="utf-8"))
        assert "{folders}" in loc[s3] and "Hugging" in loc[s3], lang


def test_an_entry_made_after_the_judgement_is_never_removed_unjudged(tmp_path, monkeypatch):
    """Security reads of row 378: only the names of the listing that was judged are removed, never a second listing's."""
    if sys.platform == "win32" or not hasattr(os, "O_DIRECTORY"):
        pytest.skip("POSIX folder handles")
    data = _own(tmp_path)
    _app_entries(data)
    real = crypto_erase._remove_names

    def late(efd, judged):
        if any(n == "blobs" for n, _k in judged):
            os.mkdir("zq-late", dir_fd=efd)
        return real(efd, judged)

    monkeypatch.setattr(crypto_erase, "_remove_names", late)
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert (data / "models" / "ollama" / "zq-late").is_dir(), "made after the judgement: never taken unjudged"


def test_a_token_home_that_cannot_be_opened_is_said_as_a_token_that_may_remain(tmp_path, monkeypatch):
    """Security reads of row 378: a Hugging Face home that is there and cannot be opened (another drive mounted there, no
    access) may hold a sign-in token: said, never passed over in silence."""
    if sys.platform == "win32" or not hasattr(os, "O_DIRECTORY"):
        pytest.skip("POSIX folder handles")
    data = _own(tmp_path)
    _app_entries(data)
    (data / "models" / "huggingface" / "token").write_bytes(b"secret")
    real = crypto_erase._open_below

    def refuse(dfd, parts):
        if tuple(parts) == ("models", "huggingface"):
            return None, OSError(18, "another device")
        return real(dfd, parts)

    monkeypatch.setattr(crypto_erase, "_open_below", refuse)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert "models/huggingface" in report["hf_token_left"]
    assert "A Hugging Face sign-in token may remain in" in report["limit"]
