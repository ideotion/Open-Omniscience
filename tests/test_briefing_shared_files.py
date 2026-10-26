"""The briefing's small state files are changed under the cross-process lock and replaced through a unique temp (R176).

Before: dismissing a card, pinning one to the draft and recording a dismissal reason each read a file, changed it and wrote it back, so two servers on one folder lost
each other's change; each swapped a fixed ``.json.tmp`` into place. What is pinned: no change made by another process is lost, and the temp is named for the process."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.briefing import dismiss_reasons, draft, service


@pytest.fixture
def dd(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


def _child(dd, body: str) -> subprocess.Popen:
    root = str(Path(service.__file__).parents[2])
    script = f"import os, sys\nsys.path.insert(0, {root!r})\nos.environ['OO_DATA_DIR'] = {str(dd)!r}\n" + textwrap.dedent(body)
    return subprocess.Popen([sys.executable, "-c", script])


def test_two_processes_dismissing_cards_lose_no_dismissal(dd):
    child = _child(dd, "from src.briefing import service\nfor i in range(40):\n    service.dismiss(f'child-{i}')\n")
    n = 0
    while child.poll() is None:
        service.dismiss(f"parent-{n}")
        n += 1
    child.wait()
    ids = service.dismissed_ids()
    assert {f"child-{i}" for i in range(40)} <= ids and {f"parent-{i}" for i in range(n)} <= ids


def test_two_processes_pinning_cards_lose_no_card(dd):
    child = _child(dd, "from src.briefing import draft\nfor i in range(40):\n    draft.add_card({'id': f'child-{i}'})\n")
    n = 0
    while child.poll() is None:
        draft.add_card({"id": f"parent-{n}"})
        n += 1
    child.wait()
    ids = {it["card"]["id"] for it in draft.load_draft()["items"]}
    assert {f"child-{i}" for i in range(40)} <= ids and {f"parent-{i}" for i in range(n)} <= ids


def test_two_processes_recording_reasons_lose_no_reason(dd):
    child = _child(dd, "from src.briefing import dismiss_reasons as r\nfor i in range(40):\n    r.record_reason(f'child-{i}', 'x')\n")
    n = 0
    # The store keeps the newest ``_MAX_ENTRIES``, so a parent that outran a slow-starting child would see its OLDEST entries trimmed away and read it as a lost
    # update (CI, 2026-10-26: a loaded runner started the child late). The loop stops short of the cap, with the child's 40 entries to spare; it still
    # runs for as long as the child does whenever the child is quick.
    while child.poll() is None and n < dismiss_reasons._MAX_ENTRIES - 40 - 1:
        dismiss_reasons.record_reason(f"parent-{n}", "x")
        n += 1
    child.wait()
    ids = {r["card_id"] for r in dismiss_reasons.all_reasons()}
    assert {f"child-{i}" for i in range(40)} <= ids and {f"parent-{i}" for i in range(n)} <= ids


def test_the_cache_is_replaced_through_a_unique_temp(dd, monkeypatch):
    seen: list[str] = []
    real = os.replace
    monkeypatch.setattr("src.safety.file_lock.os.replace", lambda a, b: (seen.append(os.fspath(a)), real(a, b))[1])
    service._write_cache({"cards": []})
    assert seen and all(f".tmp.{os.getpid()}." in n for n in seen), seen
