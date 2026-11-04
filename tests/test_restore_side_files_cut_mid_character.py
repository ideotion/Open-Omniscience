"""A side file that is not valid UTF-8 (cut mid-character) does not end the restore at the side-files stage.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT. ``merge_side_files`` read each staged text member with ``read_text("utf-8")`` and caught ``(OSError, json.JSONDecodeError)`` around the
calendar stores, ``OSError`` around the logs. A calendar store that an earlier crash cut in the middle of a multi-byte character is collected into a
backup as it is (its hash is of the bytes it was handed, so the backup verifies), and reading it raises ``UnicodeDecodeError``: not an ``OSError``
and not a ``JSONDecodeError`` (it is a ``ValueError``). The error left the stage, and the whole import ended as a failure before the live corpus was
touched, for one torn file. The same read of a LOG member (an older build's, or an unverified artifact's: a current build's export withholds a line
that is not text) and of the LIVE log, for the duplicate check, raised the same way. The loader of the live calendar store
(``events.feeds._load_json``) has caught it since R397.

WHAT THE STAGE DOES NOW. A calendar member it cannot decode is SKIPPED, like one it cannot parse (a cut JSON document is not a document, so there
is nothing to merge). In a log, every line that is text is kept, and a line that is NOT text is WITHHELD, never repaired: it cannot be checked for
the passphrase, and the export side (``scrubbed_copy``) withholds it for that reason. A repair (U+FFFD for the bad bytes) can leave most of a key
that no longer matches the scrub in a log that the next backup then carries out, because the line is valid text by then. The log's entry in the
report counts the lines it withheld, and says nothing when there were none.

Every fixture below is checked to be undecodable BEFORE the test uses it: a "torn" fixture that decodes would pass for the wrong reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.database import connect
from src.monitoring import secret_scrub as ss
from tests.backup_helper import staged_artifact

_KEY = "hunter2-correct-horse-9f3a"

CAL = "calendar_feed_imports.json"
CHECKS = "calendar_feed_checks.json"


def _cut_mid_character(text: str, *, keep: int = 1) -> bytes:
    """``text`` as UTF-8, ended ``keep`` byte(s) into its LAST multi-byte character."""
    raw = text.encode("utf-8")
    last = max(i for i, ch in enumerate(text) if ord(ch) > 127)
    start = len(text[:last].encode("utf-8"))
    cut = raw[: start + keep]
    with pytest.raises(UnicodeDecodeError):
        cut.decode("utf-8")
    return cut


def _torn_calendar() -> bytes:
    return _cut_mid_character(json.dumps({"fam": {"name": "café", "events": {}}}, ensure_ascii=False))


def _stage(tmp_path: Path, members: list[tuple[str, str, bytes]]):
    """A real ``StagedArtifact`` whose members are ``(name, role, bytes)``, written under the staging dir; the live data dir is ``tmp_path/live``."""
    staging = tmp_path / "staging"
    for name, _role, body in members:
        p = staging / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    live = tmp_path / "live"
    live.mkdir(exist_ok=True)
    return staged_artifact(
        staging,
        members=[{"name": name, "role": role} for name, role, _b in members],
        origin_fingerprint="ab" * 32,
    ), live


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "live"))


@pytest.fixture(autouse=True)
def _held(monkeypatch):
    """The process holds a passphrase, as a running install does."""
    monkeypatch.setattr(connect, "_passphrase", _KEY)
    ss.forget_held()
    yield
    ss.forget_held()


@pytest.mark.parametrize("name", [CAL, CHECKS])
def test_a_calendar_store_cut_mid_character_is_skipped_not_fatal(tmp_path, name):
    from src.backup.merge import merge_side_files

    staged, live = _stage(tmp_path, [(name, "state", _torn_calendar())])
    report = merge_side_files(staged)
    assert report["state"][name] == {"action": "skipped", "reason": "unreadable in artifact"}
    assert not (live / name).exists(), "an unreadable member must write nothing"


def test_the_stage_goes_on_after_a_torn_member(tmp_path):
    """The members after the torn one are still processed: a good calendar store merges and a good log is appended."""
    from src.backup.merge import merge_side_files

    good_checks = json.dumps({"feed-1": {"status": "ok"}}).encode()
    staged, live = _stage(
        tmp_path,
        [
            (CAL, "state", _torn_calendar()),
            (CHECKS, "state", good_checks),
            ("logs/app_errors.jsonl", "logs", b'{"at": 1, "msg": "kept"}\n'),
        ],
    )
    report = merge_side_files(staged)
    assert report["state"][CAL]["action"] == "skipped"
    assert report["state"][CHECKS]["action"] == "merged" and report["state"][CHECKS]["added"] == 1
    assert report["logs"]["app_errors.jsonl"]["appended"] == 1
    assert "kept" in (live / "app_errors.jsonl").read_text("utf-8")


def test_a_log_member_cut_mid_character_keeps_every_line_it_can_read(tmp_path):
    from src.backup.merge import merge_side_files

    torn = _cut_mid_character('{"at": 3, "msg": "café"}')
    body = b'{"at": 1, "msg": "first"}\n{"at": 2, "msg": "second"}\n' + torn
    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", body)])
    entry = merge_side_files(staged)["logs"]["app_errors.jsonl"]
    text = (live / "app_errors.jsonl").read_text("utf-8")  # the file is valid UTF-8: nothing undecodable was carried in
    assert '"msg": "first"' in text and '"msg": "second"' in text
    assert "caf" not in text and "\ufffd" not in text, "the cut line is withheld, never repaired"
    assert f"a line of {len(torn)} bytes is not merged: it is not valid UTF-8" in text, "the log says which line, by size, was withheld"
    assert entry["appended"] == 2 and entry["duplicate"] == 0  # first and second; the sentence is not a merged line
    assert entry["undecodable_lines_withheld"] == 1


def test_a_clean_log_member_reports_no_replacement(tmp_path):
    from src.backup.merge import merge_side_files

    staged, _live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", b'{"at": 1, "msg": "plain"}\n')])
    entry = merge_side_files(staged)["logs"]["app_errors.jsonl"]
    assert entry == {"appended": 1, "duplicate": 0}, "the report's shape is unchanged when nothing was undecodable"


def test_a_live_log_cut_mid_character_still_recognises_the_lines_it_holds(tmp_path):
    """The live log's torn tail does not end the restore, and the intact lines it holds are still duplicates."""
    from src.backup.merge import merge_side_files

    a, b, c = (f'{{"at": {n}, "msg": "line {n}"}}'.encode() for n in (1, 2, 3))
    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", a + b"\n" + b + b"\n" + c + b"\n")])
    (live / "app_errors.jsonl").write_bytes(a + b"\n" + b + b"\n" + _cut_mid_character('{"at": 9, "msg": "café"}'))
    entry = merge_side_files(staged)["logs"]["app_errors.jsonl"]
    assert entry["appended"] == 1 and entry["duplicate"] == 2, entry
    assert b'"msg": "line 3"' in (live / "app_errors.jsonl").read_bytes()


# --------------------------------------------------------------------------- #
#  What did not change
# --------------------------------------------------------------------------- #
def test_a_torn_but_decodable_calendar_store_is_still_skipped(tmp_path):
    """Cut BETWEEN characters: valid UTF-8, invalid JSON. Skipped before this change and after it."""
    from src.backup.merge import merge_side_files

    staged, _live = _stage(tmp_path, [(CAL, "state", '{"fam": {"name": "café"'.encode())])
    assert merge_side_files(staged)["state"][CAL] == {"action": "skipped", "reason": "unreadable in artifact"}


def test_a_good_calendar_store_still_merges(tmp_path):
    from src.backup.merge import merge_side_files

    doc = {"fam": {"name": "café", "events": {"fp1": {"title": "x", "sources": ["s"]}}}}
    staged, live = _stage(tmp_path, [(CAL, "state", json.dumps(doc, ensure_ascii=False).encode("utf-8"))])
    state = merge_side_files(staged)["state"][CAL]
    assert state["action"] == "merged" and state["added"] == 1
    assert json.loads((live / CAL).read_text("utf-8"))["fam"]["events"]["fp1"]["title"] == "x"


def test_a_line_that_is_not_utf8_is_withheld_never_repaired_into_the_live_log(tmp_path):
    """THE EXPORT'S RULE, kept on the way back in (``scrubbed_copy``: "cannot be checked for the passphrase", withheld whole, never repaired).

    Bad bytes INSIDE the held passphrase make it match nothing once they are replaced by U+FFFD, so a repaired line would carry most of the key
    into the live log, and the next backup would carry it out, because the line is valid text by then."""
    from src.backup.merge import merge_side_files

    key = _KEY.encode()
    torn = b'{"at": 2, "msg": "opened with ' + key[:12] + b"\xe4" + key[13:] + b' here"}'  # one byte of the key is not UTF-8
    with pytest.raises(UnicodeDecodeError):
        torn.decode("utf-8")
    body = b'{"at": 1, "msg": "first"}\n' + torn + b'\n{"at": 3, "msg": "third"}\n'
    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", body)])
    entry = merge_side_files(staged)["logs"]["app_errors.jsonl"]
    text = (live / "app_errors.jsonl").read_text("utf-8")
    assert key[:12].decode() not in text and key[13:].decode() not in text, "a piece of the passphrase reached the live log"
    assert '"msg": "first"' in text and '"msg": "third"' in text, "the readable lines on both sides of it are kept"
    assert "is not valid UTF-8, so it cannot be checked for the passphrase" in text, "the log says a line was withheld"
    assert entry["undecodable_lines_withheld"] == 1


def test_every_withheld_line_leaves_its_own_sentence_whatever_the_log_already_holds(tmp_path):
    """The sentences are this restore saying what it left out: not lines to dedupe, and not duplicates. Two withheld lines of the same size are two
    sentences, and a sentence an EARLIER restore left in the live log does not swallow this restore's."""
    from src.backup.merge import _withheld_sentence, merge_side_files

    bad = b'{"at": 5, "msg": "caf\xe9"}'  # latin-1: 'caf' + one byte that is not UTF-8
    with pytest.raises(UnicodeDecodeError):
        bad.decode("utf-8")
    body = b'{"at": 1, "msg": "kept"}\n' + bad + b"\n" + bad.replace(b"5", b"6") + b"\n"
    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", body)])
    sentence = _withheld_sentence(len(bad))
    (live / "app_errors.jsonl").write_text(sentence + "\n", encoding="utf-8")  # left by an earlier restore
    entry = merge_side_files(staged)["logs"]["app_errors.jsonl"]
    text = (live / "app_errors.jsonl").read_text("utf-8")
    assert text.count(sentence) == 3, "the earlier restore's sentence and one new one per withheld line"
    assert entry == {"appended": 1, "duplicate": 0, "undecodable_lines_withheld": 2}, entry


def test_a_log_that_needs_the_fallback_splits_lines_where_a_clean_one_does(tmp_path):
    """A line holding U+000B (a separator ``str.splitlines`` splits on, ``bytes.splitlines`` does not) is the same two lines whether or not ANOTHER
    line of the log made the read fall back: the live log in the fallback must still recognise what the member holds."""
    from src.backup.merge import merge_side_files

    odd = b"left\x0bright"
    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", odd + b"\n")])
    (live / "app_errors.jsonl").write_bytes(odd + b"\n" + _cut_mid_character('{"at": 9, "msg": "café"}'))
    entry = merge_side_files(staged)["logs"]["app_errors.jsonl"]
    assert entry["appended"] == 0 and entry["duplicate"] == 2, entry


def test_a_surrogate_written_as_utf8_bytes_is_withheld_not_kept_as_text(tmp_path):
    """``ED B2 80`` is what a lone surrogate looks like when something encodes it by hand: not UTF-8, so not text, and not a line to keep."""
    from src.backup.merge import _withheld_sentence, merge_side_files

    bad = b"has \xed\xb2\x80 inside"
    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", b"ok\n" + bad + b"\n")])
    entry = merge_side_files(staged)["logs"]["app_errors.jsonl"]
    text = (live / "app_errors.jsonl").read_text("utf-8")
    assert entry == {"appended": 1, "duplicate": 0, "undecodable_lines_withheld": 1}, entry
    assert "inside" not in text and _withheld_sentence(len(bad)) in text


def test_a_log_member_that_is_only_a_torn_line_still_says_what_was_left_out(tmp_path):
    from src.backup.merge import merge_side_files

    torn = _cut_mid_character('{"at": 1, "msg": "café"}')
    staged, live = _stage(tmp_path, [("logs/app_errors.jsonl", "logs", torn)])
    entry = merge_side_files(staged)["logs"]["app_errors.jsonl"]
    assert entry == {"appended": 0, "duplicate": 0, "undecodable_lines_withheld": 1}, entry
    assert f"a line of {len(torn)} bytes is not merged" in (live / "app_errors.jsonl").read_text("utf-8")
