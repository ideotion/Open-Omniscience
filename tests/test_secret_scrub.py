"""``src/monitoring/secret_scrub.py`` takes a KNOWN secret out of text a child process said, and
leaves none of it behind -- not beside the marker, not inside it, and never in the field names a
record is read by.

Two things the first version of the release run's scrub got wrong, found by the review of the
commit that wrote it (2026-10-01): it renamed dict KEYS, so a passphrase that was a piece of a field
name (``ok``, ``store``, ``e``) turned a good restore into an error; and its replacement could
rebuild the secret (a passphrase ending in ``*``, or a piece of ``***redacted***``).

The third, found by the next review: the scrub covered what the parent READS, and a kept fresh
install leaves the restore child's run journal and reports on the drive as text the parent never
reads. ``scrub_file`` cleans a file in place by what it is (JSON lines, a JSON document, text).
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys

import pytest

from src.monitoring import secret_scrub as ss

NEEDLE = "hunter2-never-on-disk"


@pytest.fixture(autouse=True)
def _a_secret_of_any_length(monkeypatch):
    """The cases here pin the MECHANICS of taking a secret out (a marker that rebuilds it, a piece of a field name, two secrets that
    overlap, every shape it is written in), and they do it with secrets of one to three characters because those are the ones that
    break a replacement written for the ordinary one. The floor under which a secret is not taken out of free text at all
    (``secret_scrub.MIN_SECRET_CHARS``) is policy, and it is pinned with the real value in ``test_secret_scrub_floor.py``."""
    monkeypatch.setattr(ss, "MIN_SECRET_CHARS", 1)


def test_the_ordinary_secret_gets_the_readable_marker_and_an_empty_one_is_no_needle():
    assert ss.scrub_text(f"a {NEEDLE} b {NEEDLE}", NEEDLE) == "a ***redacted*** b ***redacted***"
    assert ss.scrub_text("nothing here", NEEDLE) == "nothing here"
    assert ss.scrub_text("anything", "") == "anything", "an empty secret would match between every character"
    assert ss.scrub_value({"k": "x"}, "") == {"k": "x"}


@pytest.mark.parametrize("text,needle", [
    ("abcabc*", "abc*"),                    # the marker's own asterisks rebuild a secret that ends in one
    ("*abcabc", "*abc"),                    # ... or begins with one
    ("x red y red", "red"),                 # the secret is a piece of the marker
    ("***redacted***", "*"),
    ("a#b", "#"),
    ("aaa", "aa"),                          # overlapping occurrences
    ("x e y", "e"),
    ("#*#*", "#*"),
    ("***redacted*** and red", "red"),      # text that already holds the marker
    (NEEDLE * 3, NEEDLE),
    (f"{NEEDLE[:10]}{NEEDLE}{NEEDLE[10:]}", NEEDLE),   # an occurrence made of two halves once one is removed
])
def test_no_part_of_the_secret_is_left_in_what_is_returned(text, needle):
    out = ss.scrub_text(text, needle)
    assert needle not in out, (text, needle, out)
    assert needle in text, "the case must hold something to take out"


def test_a_secret_that_is_a_piece_of_the_marker_gets_another_marker_not_a_garbled_one():
    assert ss.scrub_text("key red refused", "red") == "key ### refused"
    # scrubbed twice, as the stderr tail is (once where it is cut, once with the whole record): nothing more happens
    once = ss.scrub_text("key red refused", "red")
    assert ss.scrub_text(once, "red") == once
    # the readable marker stays wherever it does not give the secret back
    assert ss.scrub_text("key abc refused", "abc") == "key ***redacted*** refused"


def test_the_scrub_ends_even_when_no_marker_can_be_used(monkeypatch):
    """Not reachable by a passphrase a person types; here so the guarantee holds for any input."""
    monkeypatch.setattr(ss, "REDACTED", "xx")
    monkeypatch.setattr(ss, "_FALLBACK_MARKERS", ("x",))
    assert ss.scrub_text("axxb x", "x") == "ab "
    monkeypatch.setattr(ss, "_FALLBACK_MARKERS", ("xxx",))  # every marker holds the two-letter secret now
    assert ss.scrub_text("xxxx", "xx") == ""


def test_values_are_scrubbed_through_lists_tuples_and_dicts_and_the_input_is_not_changed():
    value = {"ok": True, "n": 1.5, "t": None,
             "restore": {"committed": True, "note": f"the key {NEEDLE} was refused"},
             "rows": [f"x{NEEDLE}", {"deep": [f"{NEEDLE}!"]}], "pair": (NEEDLE, 2)}
    out = ss.scrub_value(value, NEEDLE)
    assert out == {"ok": True, "n": 1.5, "t": None,
                   "restore": {"committed": True, "note": "the key ***redacted*** was refused"},
                   "rows": ["x***redacted***", {"deep": ["***redacted***!"]}], "pair": ("***redacted***", 2)}
    assert NEEDLE in value["restore"]["note"] and value["rows"][0] == f"x{NEEDLE}"


def test_keys_are_never_touched():
    """A key is a field name the code defines and its readers look up. The child builds none from what
    it is handed, so a passphrase has nothing to take out of one, and renaming one loses the field."""
    out = ss.scrub_value({NEEDLE: 3, "ok": True}, NEEDLE)
    assert out == {NEEDLE: 3, "ok": True}


@pytest.mark.parametrize("needle", ["ok", "e", "a", "restore", "committed", "child", "store", "turn", "kind"])
def test_a_secret_that_is_a_piece_of_a_field_name_leaves_the_record_readable(needle):
    record = {"returncode": 0, "child": {"ok": True, "restore": {"kind": "volume-set", "committed": True}}}
    out = ss.scrub_value(record, needle)
    assert set(out) == {"returncode", "child"} and set(out["child"]) == {"ok", "restore"}
    assert set(out["child"]["restore"]) == {"kind", "committed"}
    assert out["returncode"] == 0 and out["child"]["ok"] is True and out["child"]["restore"]["committed"] is True
    assert needle not in out["child"]["restore"]["kind"]


# --------------------------------------------------------------------------- #
#  scrub_file: the files a kept fresh install leaves behind
# --------------------------------------------------------------------------- #
def _lines(path):
    return path.read_text(encoding="utf-8").split("\n")


def test_a_json_lines_file_is_scrubbed_record_by_record_and_the_clean_lines_are_not_touched(tmp_path):
    clean = '{"ev":"stage_end","t":"2026-10-01T04:39:34+00:00","name":"stage_a:decrypt","seconds":0.0}'
    dirty = {"ev": "run_begin", "label": f"fixture-{NEEDLE}.oobak", "dest": f"/tmp/{NEEDLE}/x", "n": 3}
    p = tmp_path / "imp.jsonl"
    p.write_text(clean + "\n" + json.dumps(dirty, separators=(",", ":")) + "\n\n" + clean + "\n", encoding="utf-8")
    assert ss.scrub_file(p, NEEDLE) is True
    lines = _lines(p)
    assert lines[0] == clean and lines[3] == clean, "a line without the secret is kept byte for byte"
    assert lines[2] == "" and lines[4] == "", "blank lines and the trailing newline stay"
    assert json.loads(lines[1]) == {"ev": "run_begin", "label": "fixture-***redacted***.oobak",
                                    "dest": "/tmp/***redacted***/x", "n": 3}
    assert ", " not in lines[1] and ": " not in lines[1], "written back in the journal's compact form"
    assert NEEDLE not in p.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.part")), "no copy left beside it"


def test_a_file_without_the_secret_is_left_exactly_as_it_was_and_says_so(tmp_path):
    for name, body in (("a.jsonl", '{"a":1}\n{"b":[1,2]}\n'), ("b.json", '{"a": {"b": [1, 2]}}'),
                       ("c.txt", "nothing here\n")):
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        before = p.stat().st_mtime_ns
        assert ss.scrub_file(p, NEEDLE) is False, name
        assert p.read_text(encoding="utf-8") == body and p.stat().st_mtime_ns == before, name
    assert not list(tmp_path.glob("*.part"))


def test_the_secret_is_found_in_the_form_the_reader_sees_not_the_form_json_wrote(tmp_path):
    """A raw replace cannot match a secret holding a quote, a backslash, a tab or a letter outside ASCII:
    the file holds ``\\"``, ``\\\\``, ``\\t`` and ``\\u00e4``. Parsed first, the value is the one a reader gets."""
    for needle in ('pa"ss', "back\\slash", "pässwörd", "tab\there"):
        p = tmp_path / "j.jsonl"
        p.write_text(json.dumps({"label": f"x-{needle}-y", "n": 1}) + "\n", encoding="utf-8")
        assert needle not in p.read_text(encoding="utf-8"), "the control: a raw search finds nothing to replace"
        assert ss.scrub_file(p, needle) is True, needle
        assert json.loads(p.read_text(encoding="utf-8").split("\n")[0]) == {"label": "x-***redacted***-y", "n": 1}


def test_a_secret_that_is_a_piece_of_a_key_renames_no_key(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps({"ok": True, "restore": {"committed": True, "note": "the key ok was refused"}}) + "\n",
                 encoding="utf-8")
    assert ss.scrub_file(p, "ok") is True
    out = json.loads(p.read_text(encoding="utf-8").split("\n")[0])
    assert set(out) == {"ok", "restore"} and out["ok"] is True and out["restore"]["committed"] is True
    assert out["restore"]["note"] == "the key ***redacted*** was refused"


def test_a_secret_found_only_in_a_key_changes_nothing(tmp_path):
    p = tmp_path / "k.json"
    p.write_text(json.dumps({NEEDLE: 1}), encoding="utf-8")
    assert ss.scrub_file(p, NEEDLE) is False, "keys are field names; this is the stated rule, not a leak this helper can fix"


def test_a_json_document_is_scrubbed_and_a_nan_in_it_survives_and_is_no_change(tmp_path):
    p = tmp_path / "report.json"
    p.write_text(json.dumps({"import_run": {"label": f"{NEEDLE}.oobak"}, "n": float("nan"), "rows": [f"{NEEDLE}!"]},
                            indent=2), encoding="utf-8")
    assert ss.scrub_file(p, NEEDLE) is True
    out = json.loads(p.read_text(encoding="utf-8"))
    assert out["import_run"] == {"label": "***redacted***.oobak"} and out["rows"] == ["***redacted***!"]
    assert out["n"] != out["n"], "the NaN is still one"
    q = tmp_path / "nan.json"
    q.write_text(json.dumps({"n": float("nan")}), encoding="utf-8")
    assert ss.scrub_file(q, NEEDLE) is False, "a file whose only oddity is a NaN holds nothing to take out"
    assert q.read_text(encoding="utf-8") == '{"n": NaN}'


def test_a_line_cut_by_a_kill_and_a_file_of_text_are_scrubbed_as_text(tmp_path):
    p = tmp_path / "cut.jsonl"
    p.write_text('{"a":1}\n{"label":"x-' + NEEDLE + '","dest":"/tm', encoding="utf-8")
    assert ss.scrub_file(p, NEEDLE) is True
    assert _lines(p) == ['{"a":1}', '{"label":"x-***redacted***","dest":"/tm']
    t = tmp_path / "note.log"
    t.write_text(f"key {NEEDLE} refused\nagain {NEEDLE}\n", encoding="utf-8")
    assert ss.scrub_file(t, NEEDLE) is True
    assert t.read_text(encoding="utf-8") == "key ***redacted*** refused\nagain ***redacted***\n"
    broken = tmp_path / "torn.json"
    broken.write_text('{"label": "' + NEEDLE + '", "n"', encoding="utf-8")
    assert ss.scrub_file(broken, NEEDLE) is True and NEEDLE not in broken.read_text(encoding="utf-8")


def test_a_secret_that_would_rebuild_itself_is_not_left_in_a_file(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps({"label": "key red refused"}) + "\n", encoding="utf-8")
    assert ss.scrub_file(p, "red") is True
    assert "red" not in json.loads(_lines(p)[0])["label"] and json.loads(_lines(p)[0])["label"] == "key ### refused"


def test_a_file_that_is_not_text_is_refused_not_mangled(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_bytes(b"\xff\xfe\x00 not utf-8 " + NEEDLE.encode())
    with pytest.raises(ValueError):
        ss.scrub_file(p, NEEDLE)
    assert p.read_bytes().startswith(b"\xff\xfe") and NEEDLE.encode() in p.read_bytes()
    with pytest.raises(OSError):
        ss.scrub_file(tmp_path / "missing.jsonl", NEEDLE)


def test_an_empty_secret_rewrites_nothing(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text('{"a":"b"}\n', encoding="utf-8")
    assert ss.scrub_file(p, "") is False and p.read_text(encoding="utf-8") == '{"a":"b"}\n'
    # the helper under it matches nothing too, rather than splitting the text on an empty separator
    assert ss._scrub_cut_text('{"a":"b"', "") == '{"a":"b"'


def test_a_rewrite_that_fails_leaves_the_old_file_whole_and_no_copy_behind(tmp_path, monkeypatch):
    p = tmp_path / "f.jsonl"
    body = json.dumps({"label": NEEDLE}) + "\n"
    p.write_text(body, encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(ss.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        ss.scrub_file(p, NEEDLE)
    assert p.read_text(encoding="utf-8") == body, "the old file is whole; the caller decides about it"
    assert not list(tmp_path.glob("*.part")), "the half-made copy is removed"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_rewritten_file_keeps_the_permissions_the_original_had(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_text(json.dumps({"label": NEEDLE}) + "\n", encoding="utf-8")
    os.chmod(p, 0o600)
    assert ss.scrub_file(p, NEEDLE) is True
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


@pytest.mark.parametrize("ensure_ascii", [True, False])
@pytest.mark.parametrize("needle", ['pa"ss', "back\\slash", "pässwörd", "tab\there", "emoji-😀-x", 'pä"ss'])
def test_a_cut_line_is_scrubbed_for_the_secret_as_json_wrote_it_too(tmp_path, needle, ensure_ascii):
    """The run journal writes ASCII JSON, so a line cut before it was whole holds the secret in its ESCAPED form
    (a quote, a backslash, a tab and every letter outside ASCII is an escape sequence there), which no search for
    the secret as typed finds; a writer that keeps its letters (``ensure_ascii`` off) escapes the rest and leaves
    a third form. A cut line is not JSON, so it is scrubbed as text, in every form."""
    full = json.dumps({"ev": "run_begin", "label": f"b-{needle}.oobak", "dest": "/tmp/somewhere/b.oobak"},
                      separators=(",", ":"), ensure_ascii=ensure_ascii)
    cut = full[: full.index('"dest"') + 9]
    with pytest.raises(ValueError):
        json.loads(cut)
    escaped = json.dumps(needle, ensure_ascii=ensure_ascii)[1:-1]
    assert escaped in cut, "the control: the line holds the form its writer produced"
    p = tmp_path / "cut.jsonl"
    p.write_text('{"a":1}\n' + cut, encoding="utf-8")
    assert ss.scrub_file(p, needle) is True
    text = p.read_text(encoding="utf-8")
    for form in {needle, json.dumps(needle)[1:-1], json.dumps(needle, ensure_ascii=False)[1:-1]}:
        assert form not in text, form
    assert _lines(p)[0] == '{"a":1}', "the line before it is untouched"


def _forms_of(needle: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((needle, json.dumps(needle)[1:-1], json.dumps(needle, ensure_ascii=False)[1:-1])))


def test_a_form_the_marker_of_a_later_one_rebuilds_is_not_left_in_a_cut_file(tmp_path):
    """MUTATION TARGET: the check after the forms were replaced in turn. A secret of a star and a quote has
    two forms (as typed, and as JSON escapes it: star, backslash, quote). The escaped one is replaced
    second, and the marker's last star beside the quote that closed the string is the secret as typed
    again. ``scrub_file`` then said it had rewritten the file, with the secret still in it."""
    needle = '*"'
    cut = '{"ev":"run_begin","label":"b-*\\"","dest":"/tmp/somewhere/b.oo'
    assert needle not in cut and json.dumps(needle)[1:-1] in cut, "the control: only the escaped form is there"
    p = tmp_path / "cut.jsonl"
    p.write_text('{"a":1}\n' + cut, encoding="utf-8")
    assert ss.scrub_file(p, needle) is True
    text = p.read_text(encoding="utf-8")
    assert [form for form in _forms_of(needle) if form in text] == [], text
    assert _lines(p)[0] == '{"a":1}', "the line before it is untouched"
    # the ordinary secret keeps the readable marker, and the first marker that gives nothing back is the one used
    assert ss._scrub_cut_text("label b-hunter2 end", "hunter2") == "label b-***redacted*** end"
    assert ss._scrub_cut_text(cut, needle).count("###") == 1
    # both forms in one text: when a form is left, EVERY form is redone with the one marker, none is left to the next pass
    assert ss._scrub_cut_text('*"x*\\""', needle) == '###x###"'


def test_every_form_is_checked_for_what_a_later_marker_rebuilt_and_not_only_the_first(monkeypatch):
    """MUTATION TARGET: the check after the forms. The form a later marker rebuilds is not always the first: a
    secret with a quote and a letter outside ASCII has three forms (as typed, as ASCII JSON, as JSON that keeps
    its letters), and here the marker is the tail of the second, so replacing the third in ``a\\"`` + the third
    gives the second back. The first form is nowhere in the text."""
    monkeypatch.setattr(ss, "REDACTED", "\\u00e9")
    needle = 'a"\u00e9'
    forms = _forms_of(needle)
    assert len(forms) == 3, forms
    text = 'a\\"' + forms[2]
    assert forms[0] not in text and forms[1] not in text and forms[2] in text, "the control: only the third form is there"
    out = ss._scrub_cut_text(text, needle)
    assert [f for f in forms if f in out] == [], out
    assert out == 'a\\"###', "the readable marker gave the second form back, so the next one is used"


def test_no_form_of_the_secret_is_in_the_cut_text_for_any_secret_and_text_made_of_the_pieces_that_rebuild_one():
    """EXHAUSTIVE over a small alphabet, not a sample: every secret of one to three characters from the marker's
    own and JSON's punctuation (155), against every text of one to three pieces from its forms, the quote that
    closes a string, a star and a letter (21,256 pairs). 28 of them left a form in the text when each form was
    replaced once, in turn (seven secrets: four of stars and quotes alone, three with an ``x`` among them); none
    does now."""
    from itertools import product

    alphabet = ("*", '"', "\\", "#", "x")
    checked = 0
    for size in (1, 2, 3):
        for chars in product(alphabet, repeat=size):
            needle = "".join(chars)
            forms = _forms_of(needle)
            pieces = (*forms, '"', "*", "x")
            for count in (1, 2, 3):
                for parts in product(pieces, repeat=count):
                    text = "".join(parts)
                    out = ss._scrub_cut_text(text, needle)
                    assert [f for f in forms if f in out] == [], (needle, text, out)
                    checked += 1
    assert checked > 10_000, "the search ran over the whole alphabet"


def test_the_cut_text_scrub_ends_even_when_no_marker_can_be_used(monkeypatch):
    """MUTATION TARGET: the last resort. Not reachable by a passphrase a person types; here so the guarantee holds
    for any input. Every marker is a star, so each one rebuilds the secret (star, quote) out of the escaped form's
    replacement, and the forms are taken out whole."""
    monkeypatch.setattr(ss, "REDACTED", "*")
    monkeypatch.setattr(ss, "_FALLBACK_MARKERS", ("*",))
    out = ss._scrub_cut_text('{"label":"b-*\\""', '*"')
    assert out == '{"label":"b-"', out


@pytest.mark.parametrize("depth", [5000, 100000])
@pytest.mark.parametrize("name", ["deep.jsonl", "deep.json"])
def test_a_file_nested_past_what_the_interpreter_can_walk_is_scrubbed_as_text_and_raises_nothing(
        tmp_path, name, depth):
    """5,000 levels are read by the JSON parser and overrun the walk that scrubs the values; 100,000 are refused by
    the parser itself. Neither may raise out of ``scrub_file`` (the caller would lose the rest of its work), and
    neither may leave the secret behind."""
    body = '{"label":"x-' + NEEDLE + '","deep":' + "[" * depth + "]" * depth + "}"
    with pytest.raises(RecursionError):
        ss.scrub_value(json.loads(body), NEEDLE)  # the control: the ordinary route cannot do it
    p = tmp_path / name
    p.write_text(body + "\n", encoding="utf-8")
    assert ss.scrub_file(p, NEEDLE) is True
    text = p.read_text(encoding="utf-8")
    assert NEEDLE not in text and "***redacted***" in text


def test_the_bytes_of_every_line_that_is_not_rewritten_are_kept_line_endings_included(tmp_path):
    """A journal a Windows writer ended with CRLF stays CRLF, line by line: the lines without the secret are not
    touched, and the one that is rewritten keeps its own ending."""
    clean = b'{"a":1}\r\n'
    dirty = json.dumps({"label": NEEDLE}, separators=(",", ":")).encode() + b"\r\n"
    p = tmp_path / "w.jsonl"
    p.write_bytes(clean + dirty + clean)
    assert ss.scrub_file(p, NEEDLE) is True
    assert p.read_bytes() == clean + b'{"label":"***redacted***"}\r\n' + clean


# --------------------------------------------------------------------------- #
# What a handler that holds a passphrase writes a caught exception through (2026-10-06): the volume job's runners, the
# single-file restore's route and the import queue. ``tests/test_p0_validation.py`` reads those modules and fails on any
# other way their handlers reach a text; these are the three helpers themselves.
# --------------------------------------------------------------------------- #
PASS = "kQ7!vLm-the-artifact-key"
CORPUS = "zR4#nPt-the-corpus-key"


def test_scrubbed_takes_every_secret_out_and_leaves_the_words_around_them():
    assert ss.scrubbed(f"a {PASS} b {CORPUS} c {PASS}", PASS, CORPUS) == (
        f"a {ss.REDACTED} b {ss.REDACTED} c {ss.REDACTED}"
    )


def test_scrubbed_matches_nothing_for_an_empty_or_a_missing_secret():
    text = "the signature does not match"
    assert ss.scrubbed(text) == text
    assert ss.scrubbed(text, None, "") == text
    assert ss.scrubbed(f"{text} {PASS}", None, PASS, "") == f"{text} {ss.REDACTED}"


def test_scrubbed_uses_the_next_marker_when_the_first_would_give_a_secret_back():
    """A is the marker and an ``x``, B is ``bb``, and with the marker in place of ``bb`` the text ``bbx`` reads as A again.
    The result is checked, so the next marker is used and the words around it are kept."""
    first, second = f"{ss.REDACTED}x", "bb"
    out = ss.scrubbed("bbx", first, second)
    assert out == "###x"
    assert first not in out and second not in out


def test_a_secret_that_is_a_piece_of_the_marker_gets_the_next_marker_in_a_text_with_two_secrets():
    """``red`` is a piece of the readable marker, so that marker is not used for either secret."""
    out = ss.scrubbed("x bb y red z", "red", "bb")
    assert out == "x ### y ### z" and "red" not in out and "bb" not in out


def test_a_text_no_marker_can_be_put_in_without_giving_a_secret_back_is_withheld_as_a_marker_that_holds_none(monkeypatch):
    """Not reachable by a passphrase a person types; here so the guarantee holds for any input. The first marker, ``#``, is
    the start of ``#x`` and the text beside it finishes it; the second, ``y``, is a secret. The text is replaced by the
    first marker that holds none of the secrets (``#``), and by nothing when there is none."""
    monkeypatch.setattr(ss, "REDACTED", "#")
    monkeypatch.setattr(ss, "_FALLBACK_MARKERS", ("y",))
    out = ss.scrubbed("yx", "#x", "y")
    assert out == "#" and "#x" not in out and "y" not in out
    monkeypatch.setattr(ss, "REDACTED", "y")
    assert ss.scrubbed("yx", "#x", "y") == ""


def test_scrubbed_gives_back_text_that_holds_no_secret_as_it_was():
    text = "volume 3 of 9 failed its checksum"
    assert ss.scrubbed(text, PASS, CORPUS) is text


def test_the_traceback_text_scrubs_every_link_of_a_chain_and_keeps_the_chain():
    try:
        try:
            raise ValueError(f"the key {PASS} did not open the header")
        except ValueError as inner:
            raise RuntimeError(f"the set could not be read ({CORPUS})") from inner
    except RuntimeError as outer:
        text = ss.traceback_text(outer, PASS, CORPUS)
    assert PASS not in text and CORPUS not in text
    assert f"ValueError: the key {ss.REDACTED} did not open the header" in text
    assert f"RuntimeError: the set could not be read ({ss.REDACTED})" in text
    assert "direct cause" in text, "the chain's own sentence is kept: it is the secrets that are taken out"


def test_the_traceback_text_scrubs_the_implicit_context_of_an_exception_raised_while_handling_another():
    try:
        try:
            raise ValueError(f"the key {PASS} did not open the header")
        except ValueError:
            raise RuntimeError("while handling it, the set could not be closed")  # noqa: B904 - the context is the case
    except RuntimeError as outer:
        text = ss.traceback_text(outer, PASS)
    assert PASS not in text and f"ValueError: the key {ss.REDACTED}" in text
    assert "During handling of the above exception" in text


def test_log_failure_logs_at_the_level_asked_for_with_the_secrets_out_and_attaches_no_exc_info(caplog):
    log = logging.getLogger("tests.secret_scrub.log_failure")
    caplog.set_level(logging.DEBUG, logger=log.name)
    try:
        raise OSError(f"the drive refused {PASS}")
    except OSError as exc:
        ss.log_failure(log, "placing failed", exc, PASS, level=logging.WARNING)
        ss.log_failure(log, "sealing failed", exc, PASS)
    placing = [r for r in caplog.records if "placing failed" in r.getMessage()]
    sealing = [r for r in caplog.records if "sealing failed" in r.getMessage()]
    assert [r.levelno for r in placing] == [logging.WARNING] and [r.levelno for r in sealing] == [logging.ERROR]
    for record in placing + sealing:
        assert PASS not in record.getMessage() and f"OSError: the drive refused {ss.REDACTED}" in record.getMessage()
        assert record.exc_info is None and record.exc_text is None, "a record carrying exc_info prints the message again"


def _chain(layers: int, secret: str) -> BaseException:
    """An exception ``layers`` causes deep, each a long message, the innermost one naming the secret: a traceback far
    longer than any cut (Python folds a repeated frame, so the length has to come from the chain)."""
    exc: BaseException = ValueError(f"the key {secret} did not open the header")
    for layer in range(layers):
        try:
            raise exc
        except ValueError as inner:
            exc = RuntimeError(f"layer {layer}: " + "y" * 120)
            exc.__cause__ = inner
        except RuntimeError as inner:
            exc = RuntimeError(f"layer {layer}: " + "y" * 120)
            exc.__cause__ = inner
    return exc


def test_log_failure_leads_with_the_exceptions_own_line_so_the_error_log_keeps_it_through_its_cut(caplog):
    """The debug bundle's error log (``errorlog._JsonlErrorHandler``) keeps the first 500 characters of a message and a
    traceback tail only for a record WITH ``exc_info``. A traceback written as text would push the line that names the
    failure past the cut, so that line comes first."""
    log = logging.getLogger("tests.secret_scrub.log_failure_cut")
    caplog.set_level(logging.DEBUG, logger=log.name)
    ss.log_failure(log, "volume restore failed", _chain(8, PASS), PASS)
    message = caplog.records[-1].getMessage()
    assert len(message) > 1500, "the case needs a traceback far longer than the cut"
    assert message[:500].startswith("volume restore failed: RuntimeError: layer 7: yyyy")
    assert "Traceback (most recent call last)" in message[500:], "the whole traceback follows the line"
    assert PASS not in message and f"the key {ss.REDACTED} did not open the header" in message


def test_log_failure_cuts_the_exceptions_line_after_the_scrub_and_never_before_it(caplog):
    """A message cut at 300 characters, before the scrub, would split the secret and leave its half in the record."""
    log = logging.getLogger("tests.secret_scrub.log_failure_split")
    caplog.set_level(logging.DEBUG, logger=log.name)
    lead = "x" * (300 - len("ValueError: ") - 5)  # the secret starts five characters before the cut
    try:
        raise ValueError(lead + PASS)
    except ValueError as exc:
        ss.log_failure(log, "failed", exc, PASS)
    message = caplog.records[-1].getMessage()
    assert PASS not in message and PASS[:5] not in message, "a cut before the scrub would leave these five"


def test_log_failure_names_the_failure_of_an_exception_that_was_never_raised(caplog):
    log = logging.getLogger("tests.secret_scrub.log_failure_unraised")
    caplog.set_level(logging.DEBUG, logger=log.name)
    ss.log_failure(log, "nothing raised", ValueError(f"the key {PASS}"), PASS)
    message = caplog.records[-1].getMessage()
    assert PASS not in message and f"ValueError: the key {ss.REDACTED}" in message


# --------------------------------------------------------------------------- #
# Every shape of every secret (2026-10-06). An engine quotes the statement that carried the key (an SQL literal, every quote
# doubled), Python writes a tuple, a list or a dict with ``repr`` and a record or a response with JSON, and none of those is the
# secret as typed: a scrub that knew only the typed one left them all.
# --------------------------------------------------------------------------- #
def _sql(secret: str) -> str:
    return f"PRAGMA key = '{secret.replace(chr(39), chr(39) * 2)}'"


#: (what writes the text, the secret, the function that writes a text holding it, the shape the secret takes in that text --
#: written by hand here, so that the table does not lean on the helper that lists the shapes)
_SHAPES = [
    ("typed", "it's", lambda s: f"bad key {s} given", "it's"),
    ("an SQL literal", "it's", lambda s: f"near {_sql(s)}: syntax error", "it''s"),
    ("an SQL literal inside a repr of the message", "it's", lambda s: repr(f'near "x": {_sql(s)}'), "it\\'\\'s"),
    ("a quote kept by repr", "it's", lambda s: repr(f"bad key {s}"), "it's"),
    ("a quote escaped by repr, in a text with both kinds", "it's", lambda s: repr(f"x 'y' \"z\" {s}"), "it\\'s"),
    ("a quote and a control character in a tuple", "it's\x01x", lambda s: str((s, 1)), "it's\\x01x"),
    ("a backslash in a tuple", "back\\slash", lambda s: str((s, 1)), "back\\\\slash"),
    ("a backslash in JSON", "back\\slash", lambda s: json.dumps({"detail": s}), "back\\\\slash"),
    ("letters outside ASCII in a dict", "pässwörd", lambda s: str({"k": s}), "pässwörd"),
    ("letters outside ASCII in ASCII JSON", "pässwörd", lambda s: json.dumps({"detail": s}), "p\\u00e4ssw\\u00f6rd"),
    ("letters outside ASCII in JSON that keeps them", "pässwörd",
     lambda s: json.dumps({"detail": s}, ensure_ascii=False), "pässwörd"),
    ("a double quote in JSON", 'say "hi"', lambda s: json.dumps(s), 'say \\"hi\\"'),
    ("a quote and a backslash in an SQL literal in JSON", "a'b\\c", lambda s: json.dumps(_sql(s)), "a''b\\\\c"),
    ("a quote and a backslash in an SQL literal in repr", "a'b\\c", lambda s: repr(_sql(s)), "a''b\\\\c"),
]


@pytest.mark.parametrize("how,secret,write,shape", _SHAPES, ids=[row[0] for row in _SHAPES])
def test_the_secret_is_taken_out_in_every_shape_the_code_writes_it_and_the_text_around_it_is_kept(
        how, secret, write, shape):
    """MUTATION TARGET: a shape dropped from ``_forms``. The text is written the way the case says; the shape is what that
    writer made of the secret (checked to be in the text first), and what comes back is the text with exactly it replaced."""
    written = write(secret)
    assert shape in written, "the control: the text holds the secret in the shape this case names"
    out = ss.scrub_text(written, secret)
    assert out == written.replace(shape, ss.REDACTED), out
    assert ss.scrubbed(written, "other", secret, None) == out
    assert ss.scrub_value({"k": [written], "n": 1}, secret) == {"k": [out], "n": 1}


@pytest.mark.parametrize("secret", ["x", "e", "'", "\\", '"', "é", "x\t"])
def test_a_secret_of_one_character_is_taken_out_in_every_shape_wherever_it_stands_when_nothing_stops_it(secret):
    """The floor is lowered for this file (the fixture above), so the mechanics are the ones under test: every shape of a one-
    character secret goes, the text between the pieces stays, and ``e`` (a piece of the readable marker) and ``'`` (the quote an
    SQL literal doubles) are the cases that break a replacement written for the ordinary secret. A whitespace character alone is
    never a secret (the floor counts the characters that are not whitespace), so the tab comes with a letter."""
    writers = [secret, repr(secret)[1:-1], json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1],
               secret.replace("'", "''"), _sql(secret)]
    text = " | ".join(writers) + " | 7"
    out = ss.scrub_text(text, secret)
    for shape in set(writers[:5]):
        assert shape not in out, (shape, out)
    assert out.count(" | ") == len(writers) and out.endswith(" | 7"), out


def test_a_secret_that_holds_another_leaves_no_tail_of_the_longer_one_whichever_is_given_first():
    """The held passphrase is ``pass`` and the environment's is ``pass2``: taking ``pass`` out first would leave the ``2``."""
    text = "env pass2 held pass end"
    for secrets in (("pass", "pass2"), ("pass2", "pass")):
        assert ss.scrubbed(text, *secrets) == f"env {ss.REDACTED} held {ss.REDACTED} end", secrets


def test_a_passphrase_that_starts_the_other_leaves_no_tail_of_the_longer_in_either_order_in_a_text_a_traceback_and_a_log(caplog):
    """The restore holds the artifact's passphrase and the corpus's, and a person who types a phrase and extends it for the
    other holds a pair where one CONTAINS the other. Taken out first, the shorter would leave ``battery staple``, most of the
    longer one. The two orders are the restore's own (the artifact's, then the corpus's) and the reverse; the text is made by
    the engine, so the pair is in it twice and the longer one beside the shorter."""
    backup, corpus = "correct horse", "correct horse battery staple"
    text = f"unlock {backup} then {corpus} and {corpus}!"
    log = logging.getLogger("tests.secret_scrub.containing_pair")
    caplog.set_level(logging.DEBUG, logger=log.name)
    for secrets in ((backup, corpus), (corpus, backup)):
        assert ss.scrubbed(text, *secrets) == f"unlock {ss.REDACTED} then {ss.REDACTED} and {ss.REDACTED}!", secrets
        try:
            raise RuntimeError(text)
        except RuntimeError as exc:
            tb = ss.traceback_text(exc, *secrets)
            ss.log_failure(log, "volume restore failed", exc, *secrets)
        written = [tb, caplog.text, getattr(caplog.records[-1], ss.TRACEBACK_ATTRIBUTE)]
        for shape in ("battery staple", "correct horse", "horse"):
            assert not any(shape in w for w in written), (secrets, shape)
        assert f"RuntimeError: unlock {ss.REDACTED} then {ss.REDACTED} and {ss.REDACTED}!" in tb, secrets


def test_two_secrets_that_overlap_in_the_text_and_one_secret_that_overlaps_itself_leave_no_tail():
    assert ss.scrubbed("my passwd here", "my pass", "sswd") == f"{ss.REDACTED} here"
    assert ss.scrubbed("my passwd here", "sswd", "my pass") == f"{ss.REDACTED} here"
    assert ss.scrub_text("xaaay", "aa") == f"x{ss.REDACTED}y"


def test_what_is_put_in_is_never_searched_again():
    """MUTATION TARGET: the single read. ``_redact`` does not check its result, so the marker here, a star, makes the text
    ``*"`` (the secret as typed) out of the star and the quote that follows the escaped shape ``*\\"``: read again, that
    would be replaced once more and the text would end in two stars. ``_redacted`` is the one that catches the rebuild
    and uses the next marker (the cut-text case above)."""
    assert ss._redact('*"x*\\""', ('*\\"', '*"'), "*") == '*x*"'


def test_a_plain_secret_has_one_shape_and_an_empty_or_missing_one_has_none(monkeypatch):
    assert ss._forms("hunter2") == ("hunter2",)
    assert ss._forms("") == () and ss._forms(None) == ()
    monkeypatch.setattr(ss, "held_passphrases", lambda: ())
    assert ss._forms_now(("a", "a", None, "", "b")) == ("a", "b"), "each once, and none that is empty or missing"
    assert ss.scrub_text("anything", "") == "anything" and ss.scrubbed("anything", None, "") == "anything"


def test_a_text_that_holds_no_shape_of_the_secret_comes_back_as_the_same_text():
    text = "volume 3 of 9 failed its checksum"
    assert ss.scrub_text(text, "it's") is text
    assert ss.scrubbed(text, "it's", PASS) is text


def test_the_error_an_engine_raises_for_a_key_with_a_quote_in_it_is_scrubbed_where_it_quotes_the_statement():
    """What a parser says of ``PRAGMA key = 'it''s-the-key'`` quotes a window of the statement."""
    secret = "it's-the-key"
    message = f"Parser Error: syntax error at or near \"s\"\\nLINE 1: {_sql(secret)}\\n                    ^"
    assert "it''s-the-key" in message
    out = ss.scrubbed(message, secret)
    assert "it''s" not in out and "the-key" not in out and "PRAGMA key = '***redacted***'" in out


def _first_shapes(needle: str) -> tuple[str, ...]:
    """The ten shapes a secret takes in the text one writer makes of it (typed and SQL-doubled, each as ``repr`` writes it alone,
    as ``repr`` writes it inside a text with both kinds of quote, and as JSON writes it twice): written here by hand, so that the
    texts the search builds from them are not made by the helper under test."""
    shapes: list[str] = []
    for typed in (needle, needle.replace("'", "''")):
        shapes += [
            typed,
            repr(typed)[1:-1],
            repr("'\"" + typed)[4:-1],
            json.dumps(typed)[1:-1],
            json.dumps(typed, ensure_ascii=False)[1:-1],
        ]
    return tuple(dict.fromkeys(shape for shape in shapes if shape))


def test_no_shape_of_the_secret_is_in_the_text_for_any_secret_and_text_made_of_the_pieces_that_rebuild_one():
    """EXHAUSTIVE over a small alphabet, like the cut-text one above but over EVERY shape (the quote an SQL literal doubles,
    repr's escape and JSON's among them, each written again by the others, up to three deep): each secret of one or two
    characters, against every text of one to three pieces from the shapes ONE writer makes of it, a quote, a star and a
    letter. The pieces are the first shapes only (the helper's own closure is what must be gone from the output): all of the
    closure as pieces is 170 to the third power for one secret."""
    from itertools import product

    alphabet = ("*", "'", '"', "\\", "#", "x")
    checked = 0
    for size in (1, 2):
        for chars in product(alphabet, repeat=size):
            needle = "".join(chars)
            forms = ss._forms(needle)
            assert set(_first_shapes(needle)) <= set(forms), "the closure holds every shape one writer makes"
            pieces = (*_first_shapes(needle), "'", '"', "*", "x")
            for count in (1, 2, 3):
                for parts in product(pieces, repeat=count):
                    text = "".join(parts)
                    for out in (ss.scrub_text(text, needle), ss.scrubbed(text, needle, "zz")):
                        assert [f for f in forms if f in out] == [], (needle, text, out)
                    checked += 1
    assert checked > 10_000, "the search ran over the whole alphabet"


def test_log_failure_hands_the_error_log_the_scrubbed_traceback_as_an_attribute_and_never_as_exc_info(caplog):
    log = logging.getLogger("tests.secret_scrub.log_failure_attribute")
    caplog.set_level(logging.DEBUG, logger=log.name)
    ss.log_failure(log, "volume restore failed", _chain(8, PASS), PASS)
    record = caplog.records[-1]
    tb = getattr(record, ss.TRACEBACK_ATTRIBUTE)
    assert tb.startswith("Traceback (most recent call last)") and tb.rstrip().endswith("yyyy")
    assert PASS not in tb and f"the key {ss.REDACTED} did not open the header" in tb
    assert record.exc_info is None and record.exc_text is None
