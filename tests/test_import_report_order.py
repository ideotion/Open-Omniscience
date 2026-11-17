"""The import history lists reports in the order they were written, on every system (row 137).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``list_import_reports`` ordered the history by the file's mtime alone. NTFS stamps mtime from the coarse system clock (about
15.6 ms), so the reports a checkpoint writes together tied on Windows and were listed in filename order, which carries a random
suffix: the history could show a checkpoint's backups out of the order they landed. These tests make the tie on any system with
``os.utime`` and check that the order comes from the report's own ``written_at_ns`` stamp, that a report from before the stamp
still lists by its mtime, and that equal stamps fall back to the mtime and then the filename, so the order never varies.
"""

from __future__ import annotations

import json
import os

import pytest

from src.backup import import_reports as ir


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)


_SAME_MTIME_NS = 1_794_000_000_000_000_000


def _tie(*paths) -> None:
    for p in paths:
        os.utime(p, ns=(_SAME_MTIME_NS, _SAME_MTIME_NS))


def _names() -> list[str]:
    return [r["filename"] for r in ir.list_import_reports()]


def test_reports_tied_on_mtime_list_in_the_order_they_were_written():
    # random suffixes chosen so filename order is the REVERSE of writing order: a fallback to the name would fail this
    first = ir.persist_import_report("restore", {"outcome": "ok"}, run_id="zz")
    second = ir.persist_import_report("restore", {"outcome": "ok"}, run_id="mm")
    third = ir.persist_import_report("restore", {"outcome": "ok"}, run_id="aa")
    _tie(first, second, third)
    assert _names() == [third.name, second.name, first.name], "newest written first, whatever the mtime and the name say"


def test_an_annotated_report_is_listed_as_written_when_it_was_annotated():
    """The committing backup's report is annotated after its held peers are written, and stays the newest (I7's order)."""
    own = ir.persist_import_report("restore", {"outcome": "ok"}, run_id="aa")
    held = ir.persist_import_report("restore", {"outcome": "ok"}, run_id="zz")
    ir.annotate_import_report(own, {"import_run": {"id": "run", "label": "backup-2"}})
    _tie(own, held)
    assert _names() == [own.name, held.name]


def test_the_stamp_is_not_shown_in_the_listing():
    ir.persist_import_report("restore", {"outcome": "ok"})
    (row,) = ir.list_import_reports()
    assert "written_at_ns" not in row, "a bookkeeping stamp, never a listed fact"


def test_a_report_from_before_the_stamp_lists_by_its_mtime():
    d = ir._reports_dir()
    d.mkdir(parents=True, exist_ok=True)
    old = d / "restore-20260101T000000Z-old.json"
    old.write_text(json.dumps({"outcome": "ok"}), encoding="utf-8")
    os.utime(old, ns=(_SAME_MTIME_NS, _SAME_MTIME_NS))
    new = ir.persist_import_report("restore", {"outcome": "ok"})
    assert _names() == [new.name, old.name]


def test_equal_stamps_fall_back_to_the_mtime_then_the_filename(monkeypatch):
    """Two writes in the same clock reading still list the same way on every read: by mtime, and at last by name."""
    monkeypatch.setattr(ir.time, "time_ns", lambda: _SAME_MTIME_NS)
    a = ir.persist_import_report("restore", {"outcome": "ok"}, run_id="aa")
    b = ir.persist_import_report("restore", {"outcome": "ok"}, run_id="bb")
    c = ir.persist_import_report("restore", {"outcome": "ok"}, run_id="cc")
    _tie(a, b, c)
    assert _names() == [c.name, b.name, a.name], "equal stamp and mtime: the filename decides, newest name first"
    os.utime(a, ns=(_SAME_MTIME_NS + 1, _SAME_MTIME_NS + 1))
    assert _names() == [a.name, c.name, b.name], "equal stamp: the later mtime is listed first"


def test_the_stamp_is_not_in_the_report_read_back():
    path = ir.persist_import_report("restore", {"outcome": "ok"})
    assert ir.read_import_report(path.name) == {"outcome": "ok"}
