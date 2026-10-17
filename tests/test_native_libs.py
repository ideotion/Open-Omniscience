"""Which native libraries a session ran on (the SIGABRT question: which library?). A fake maps file; nothing real is read for the lists.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

from src.monitoring import native_libs as nl


def _maps(tmp_path, paths):
    f = tmp_path / "maps"
    f.write_text("\n".join(f"7f00-7f01 r-xp 00000000 08:01 1 {p}" for p in paths) + "\n", encoding="utf-8")
    return f


def test_only_base_names_are_kept_never_a_directory_or_a_user(tmp_path):
    f = _maps(tmp_path, ["/home/alice/.venv/lib/python3.13/site-packages/lxml/etree.cpython-313-x86_64-linux-gnu.so", "/usr/lib/libxml2.so.2.12.9", "/usr/lib/libunrelated.so.1"])
    got = nl._mapped(f)
    assert got["files"] == ["etree.cpython-313-x86_64-linux-gnu.so", "libxml2.so.2.12.9"]
    assert "alice" not in json.dumps(got) and "/" not in json.dumps(got["files"])
    assert got["mapped_total"] == 3 and got["matched"] == 2 and got["listed"] == 2


def test_an_unreadable_maps_file_is_named_not_empty(tmp_path):
    assert nl._mapped(tmp_path / "missing") == {"unreadable": "absent (the file does not exist)"}


def test_the_name_list_stops_at_its_byte_budget_and_says_how_many_matched(tmp_path, monkeypatch):
    f = _maps(tmp_path, [f"/usr/lib/libxml{i}.so.{i}" for i in range(2000)])
    got = nl._mapped(f)
    assert got["matched"] == 2000 and got["listed"] < 2000 and got["listed"] == len(got["files"])
    assert len(json.dumps(got["files"], separators=(",", ":"))) <= nl._FILES_BYTES
    # the worst case of the whole reading, every family present at the budget: well under 8 KB
    assert len(json.dumps({"runtime": nl._runtime_versions(), "installed": dict.fromkeys(nl._DISTRIBUTIONS, "9.9.9"), "mapped": got}, separators=(",", ":"))) < 8000


def test_the_runtime_library_versions_are_read_from_the_loaded_library():
    r = nl.read()
    assert r["runtime"]["sqlite_library"] and "mapped" in r and "installed" in r


def test_a_passphrase_in_a_file_name_is_taken_out(tmp_path, monkeypatch):
    from src.database import connect
    from src.monitoring import secret_scrub as ss

    monkeypatch.setattr(connect, "_passphrase", "name-key-Zq7!rt")
    ss.forget_held()
    got = nl._mapped(_maps(tmp_path, ["/x/libxml-name-key-Zq7!rt.so"]))
    assert "name-key-Zq7!rt" not in json.dumps(got)


def test_the_sentinel_and_the_report_carry_the_libraries(tmp_path, monkeypatch):
    """MUTATION TARGETS: the two lines in ``forensics.py`` that add them."""
    from src.monitoring import forensics

    for name in ("_PREV_AT_BOOT", "_PREV_LOADED", "_WAL_AT_BOOT", "_PAGES_AT_BOOT", "_SESSION_STARTED_AT", "_SESSION_STARTED_MONO", "_OOM_AT_BOOT", "_BOOT_ID_AT_BOOT"):
        monkeypatch.setattr(forensics, name, getattr(forensics, name), raising=False)  # restored at teardown: the start rewrites them
    monkeypatch.setattr(forensics, "_state_path", lambda: tmp_path / "session_state.json")
    monkeypatch.setattr(forensics, "kernel_evidence", lambda: {"verdict": "not-run"})
    forensics.record_session_start()
    assert "mapped" in json.loads((tmp_path / "session_state.json").read_text(encoding="utf-8"))["native_libs"]
    assert "previous_session_native_libs" in forensics.previous_session_report()


def test_the_name_budget_counts_serialised_bytes_not_characters(tmp_path):
    """A name the decoder replaced (U+FFFD) serialises to six bytes per character; the budget must count those."""
    path = "/usr/lib/libxml-" + "\udcff" * 0
    f = tmp_path / "maps"
    names = [("libxml" + "\ufffd" * 70 + str(i) + ".so") for i in range(200)]
    f.write_bytes(("\n".join(f"7f00-7f01 r-xp 00000000 08:01 1 /x/{n}" for n in names) + "\n").encode())
    got = nl._mapped(f)
    assert len(json.dumps(got["files"], separators=(",", ":"))) <= nl._FILES_BYTES and path
