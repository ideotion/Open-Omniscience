"""R412 (amends R24): the engine identity carries a hand-bumped INDEXER_VERSION and the code digest polices it.

The identity used to hash the bytes of every engine file, so any edit made two builds "different engines" and a restore
re-extracted everything. A hand-bumped constant is only as good as the memory of whoever edits the file, so
``configs/indexer_pin.json`` records the digest at the last judgement and THESE tests are red whenever the files have moved
without that judgement being recorded (``python scripts/indexer_pin.py --bump|--same "<sentence>"``).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.analytics import engine_identity as ei

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "configs" / "indexer_pin.json"
HOW = (
    "Engine files changed since the last recorded judgement. Decide whether the ROWS index_article writes changed: "
    'python scripts/indexer_pin.py --bump "what changed" (they did: every stamp stops matching, re-extract once, '
    'release-notes line owed, R319) or --same "why they did not" (a docstring, a log line, an unrelated function). '
    "Repeat the sentence in the PR description."
)


def _pin() -> dict:
    return json.loads(PIN.read_text(encoding="utf-8"))


def test_the_engine_files_have_not_moved_without_a_recorded_judgement():
    assert ei.code_digest() == _pin()["digest"], HOW


def test_the_pin_and_the_constant_agree():
    assert _pin()["version"] == ei.INDEXER_VERSION, "a bump edits the constant and the pin together: use scripts/indexer_pin.py"


def test_every_judgement_carries_a_sentence_and_the_chain_is_consistent():
    pin = _pin()
    log = pin["log"]
    assert log, "the pin has no history"
    assert log[0]["kind"] == "baseline"
    for prev, cur in zip(log, log[1:], strict=False):
        assert cur["kind"] in ("bump", "same")
        assert len(cur["note"].strip()) >= 12, "a judgement without a sentence is not a record"
        assert cur["version"] == prev["version"] + (1 if cur["kind"] == "bump" else 0)
        assert cur["digest"] != prev["digest"] or cur["kind"] == "bump", "a --same that changed nothing is noise"
    assert (log[-1]["version"], log[-1]["digest"]) == (pin["version"], pin["digest"])


def test_the_police_goes_red_when_an_engine_file_changes(monkeypatch):
    """Remove the guard and a test must fail: an edited engine file moves the digest away from the pin."""
    real = ei._read
    target = "src/analytics/store.py"

    def _edited(rel):
        data = real(rel)
        return (data or b"") + b"\nINDEXER_PIN_PROBE = 1\n" if rel == target else data

    monkeypatch.setattr(ei, "_read", _edited)
    ei.code_digest.cache_clear()
    try:
        assert ei.code_digest() != _pin()["digest"]
    finally:
        monkeypatch.undo()
        ei.code_digest.cache_clear()
    assert ei.code_digest() == _pin()["digest"], HOW


def test_the_version_is_part_of_the_identity_and_the_code_digest_is_not(monkeypatch):
    base = ei.baseline_engine_id()
    monkeypatch.setattr(ei, "INDEXER_VERSION", ei.INDEXER_VERSION + 1)
    ei._stamp_for.cache_clear()
    assert ei.baseline_engine_id() != base
    monkeypatch.undo()
    ei._stamp_for.cache_clear()
    real = ei._read
    monkeypatch.setattr(ei, "_read", lambda rel: (real(rel) or b"") + b"\n# edited" if rel == "src/analytics/store.py" else real(rel))
    ei.code_digest.cache_clear()
    try:
        assert ei.baseline_engine_id() == base, "an edit alone must not move the identity: only a bump does"
    finally:
        monkeypatch.undo()
        ei.code_digest.cache_clear()


def test_the_pin_script_refuses_a_bump_without_a_sentence(tmp_path):
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "indexer_pin.py"), "--bump", "x"], capture_output=True, text=True, cwd=ROOT
    )
    assert out.returncode != 0 and "say what changed" in (out.stderr + out.stdout)


def test_the_pin_script_check_agrees_with_the_test():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "indexer_pin.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_constant_is_one_plain_line_the_script_can_rewrite():
    text = (ROOT / "src" / "analytics" / "engine_identity.py").read_text(encoding="utf-8")
    assert len(re.findall(r"^INDEXER_VERSION = \d+$", text, re.M)) == 1


@pytest.mark.parametrize("name", ["configs/indexer_pin.json", "scripts/indexer_pin.py"])
def test_the_pin_files_are_not_part_of_the_engine(name):
    assert name not in ei.engine_files(), "the police must not hash itself"
