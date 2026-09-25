"""Q1011: the machine reading taken at boot -- cores, RAM, free disk, no network.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

What this pins:

* each figure is MEASURED or NONE with its name under ``unreadable`` -- never a 0, never
  a guess, because "unmeasured" and "small" are opposite findings;
* the reading passes NO verdict against the reference machine: the reference's "3.5 GB"
  is what its machine class reports, so a strict comparison would call the reference
  machine smaller than itself (the reasoning is in the module docstring);
* the reading is taken in the lifespan BEFORE the lock check, so a store that boots
  locked still has one, and nothing in it opens a socket.
"""

from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path

import pytest

from src.config import hardware_reading as H
from tests.js_source_helper import python_function_source

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh():
    H._reset_for_tests()
    yield
    H._reset_for_tests()


def test_a_reading_on_this_machine_is_whole_and_says_how_it_was_taken():
    r = H.read_hardware()
    assert isinstance(r["cores"], int) and r["cores"] >= 1
    assert isinstance(r["disk_free_bytes"], int) and isinstance(r["disk_total_bytes"], int)
    assert r["taken_at"] and "nothing is sent anywhere" in r["method"]
    # psutil is an optional extra; where it is present RAM is read, where not it is NAMED.
    if r["ram_bytes"] is None:
        assert "ram" in r["unreadable"]
    else:
        assert r["ram_bytes"] > 0
    # No verdict rides the reading (see the module docstring).
    assert not {k for k in r if "versus" in k or "below" in k or "nominal" in k}


def test_each_unreadable_figure_is_none_and_named(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    monkeypatch.setattr("src.config.memory_budget.total_ram_mb", lambda: None)

    def broken(_path):
        raise OSError("statvfs failed")

    monkeypatch.setattr(shutil, "disk_usage", broken)
    r = H.read_hardware()
    assert (r["cores"], r["ram_bytes"], r["disk_free_bytes"], r["disk_total_bytes"]) == (None, None, None, None)
    assert r["unreadable"] == ["cores", "ram", "disk"]


def test_cpu_count_raising_is_unreadable_not_one(monkeypatch):
    def boom():
        raise NotImplementedError

    monkeypatch.setattr(os, "cpu_count", boom)
    assert H.cores() is None


def test_a_folder_that_does_not_exist_yet_is_read_on_its_nearest_parent(tmp_path):
    free, total = H.disk_bytes(tmp_path / "not" / "made" / "yet")
    assert isinstance(free, int) and isinstance(total, int) and total >= free


def test_the_boot_reading_is_kept_and_handed_out_as_a_copy():
    assert H.boot_reading() is None
    taken = H.record_boot_reading()
    assert taken["when"] == "boot"
    got = H.boot_reading()
    assert got == taken
    got["cores"] = -1
    assert H.boot_reading()["cores"] != -1, "a caller mutated the stored reading"


def test_the_reading_opens_no_socket(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the hardware reading tried to open a socket")

    for name in ("getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    H.record_boot_reading()


def test_the_lifespan_takes_the_reading_before_the_lock_check():
    """A store that boots LOCKED serves only the unlock flow; the reading needs no database,
    so it is taken before that fork and a locked machine still has one to show."""
    src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    body = python_function_source(src, "lifespan")
    at = body.index("record_boot_reading()")
    assert at < body.index("state = app_lock_state()"), "the boot reading moved behind the lock"
