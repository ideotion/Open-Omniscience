"""The policy of ``src/monitoring/secret_scrub.py`` as the nets use it: the floor under which a secret is not taken out of free
text, every shape a key takes in text (the writers that write it again, up to three deep, each against what real writers make),
the passphrases the process holds taken out of every call, a refusal to keep a text it could not check, and the block a route
that takes a typed key wraps its work in.

``tests/test_secret_scrub.py`` pins the MECHANICS of a replacement with secrets as short as one character (its fixture lowers the
floor); everything here runs with the real one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from itertools import product

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import src.api.main as main
from src.database import connect
from src.jobs.background import BackgroundJob
from src.monitoring import errorlog
from src.monitoring import secret_scrub as ss

#: A key that every writer writes differently: a backslash, both kinds of quote, a control character and a letter outside ASCII.
KEY = "k'e\"y\\\x01é-ü9"
OTHER = "second-key-Pq7#"
#: The keys the shapes are checked for. ``repr`` quotes a text by what it holds, so a key with BOTH kinds of quote is already
#: written with its apostrophes escaped when it stands alone and says nothing about the carrier that does that inside another
#: text: one apostrophe and no double quote, and one double quote and no apostrophe, are what make that carrier necessary.
SHAPE_KEYS = [
    pytest.param(KEY, id="both quotes, a backslash, a control character and two letters outside ASCII"),
    pytest.param("it's-the-key\\é9", id="an apostrophe and no double quote"),
    pytest.param('say "hi"-9\\é', id="a double quote and no apostrophe"),
    pytest.param("plain-key-Pq7#", id="nothing a writer escapes"),
]


def _sql(secret: str) -> str:
    return f"PRAGMA key = '{secret.replace(chr(39), chr(39) * 2)}'"


# --------------------------------------------------------------------------- #
#  The floor
# --------------------------------------------------------------------------- #
def test_the_floor_is_counted_in_characters_that_are_not_whitespace_and_a_secret_at_it_is_taken_out(monkeypatch):
    """MUTATION TARGET: the comparison (``>=`` against ``>``), the whitespace the count leaves out, or the number it is held to.
    A secret UNDER the floor is not taken out and is not left in either: ``scrubbed`` withholds the text that holds it
    (``UNREADABLE_TEXT``, or the words the caller names), and the per-needle helpers, for a needle the caller made itself,
    leave it."""
    floor = ss.MIN_SECRET_CHARS
    assert floor >= 4, "a secret of one to three characters is a piece of nearly every text"
    at, under = "a" * floor, "a" * (floor - 1)
    assert ss.scrub_text(f"x {at} y", at) == f"x {ss.REDACTED} y"
    assert ss.scrubbed(f"x {at} y", at) == f"x {ss.REDACTED} y"
    assert ss.scrub_text(f"x {under} y", under) == f"x {under} y"
    assert ss.scrub_value({"k": f"x {under}"}, under) == {"k": f"x {under}"}
    assert ss.scrubbed(f"x {under} y", under) == ss.UNREADABLE_TEXT
    assert ss.scrubbed(f"x {under} y", under, withheld="ValueError: its text is withheld") == "ValueError: its text is withheld"
    assert ss.scrubbed_value({"k": f"x {under}", "n": 3}, under) == {"k": ss.UNREADABLE_TEXT, "n": 3}
    assert ss.scrubbed("x y", under) == "x y", "a text that holds no shape of it is kept as it was"
    spaced = " ".join("a" * floor)  # as many characters as the floor, with whitespace between them
    assert ss.scrub_text(f"x {spaced} y", spaced) == f"x {ss.REDACTED} y"
    short_but_long_in_whitespace = "a" + " " * 40 + "b"
    assert ss.scrub_text(f"x {short_but_long_in_whitespace} y", short_but_long_in_whitespace) == f"x {short_but_long_in_whitespace} y"
    assert ss.scrubbed(f"x {short_but_long_in_whitespace} y", short_but_long_in_whitespace) == ss.UNREADABLE_TEXT


@pytest.mark.parametrize("secret", [" ", "\t", " " * 40, "\n" * 8, " \t\n\r" * 10])
def test_a_secret_of_whitespace_is_never_taken_out_however_long_it_is_and_withholds_the_text_that_holds_it(secret):
    """A whitespace secret is the indentation of every traceback: taking it out would leave no record that says anything, so a
    text that holds it is WITHHELD whole by the helpers that hold the passphrase and left alone by the per-needle ones (eight
    spaces are a passphrase the app accepts: creation counts whitespace). A text that holds none of its shapes is kept."""
    text = f"Traceback:{secret}File x{secret}line 3"
    assert ss.scrub_text(text, secret) is text
    assert ss.scrubbed(text, secret) == ss.UNREADABLE_TEXT
    assert ss.scrubbed(text, secret, withheld="OSError: its text is withheld") == "OSError: its text is withheld"
    clean = "Traceback:File-x:line-3"  # no whitespace at all, so none of the shapes is in it
    assert ss.scrubbed(clean, secret) is clean
    assert ss._forms(secret) == () and ss._short_shapes(secret) != ()


def test_a_held_passphrase_under_the_floor_withholds_the_text_that_holds_it_and_does_not_stop_the_long_one_being_taken_out(monkeypatch):
    """The floor applies to what the process holds as to what is handed in, one at a time: a text that holds a shape of the short
    one is withheld whole (it cannot be taken out, and the long one with it), and a text that holds none of it still has the
    long one taken out."""
    monkeypatch.setattr(connect, "_passphrase", "pw")
    monkeypatch.setenv("OO_DB_PASSPHRASE", OTHER)
    ss.forget_held()
    assert ss.scrubbed(f"a pw b {OTHER} c") == ss.UNREADABLE_TEXT
    assert ss.scrubbed(f"a b {OTHER} c") == f"a b {ss.REDACTED} c"
    assert ss.scrubbed("a b c") == "a b c"


SHORT = "zq"


@pytest.mark.parametrize("how", ["held", "handed in"])
def test_a_secret_under_the_floor_withholds_the_words_in_every_helper_that_holds_the_passphrase(monkeypatch, caplog, how):
    """A correct passphrase of an older store is held whatever its length (the unlock accepts any that opens the file), and a short
    one can be handed in (a backup's has no minimum of its own). Either way, every helper that writes a text with the passphrase
    out of it withholds the text that holds the short one, in the words the caller names where it names any, and keeps the text
    that holds none of its shapes. MUTATION TARGET: the short shapes dropped from any one of ``scrubbed``, ``scrubbed_value``,
    ``traceback_text``, ``log_failure`` or ``scrub_and_reraise``, or a held secret that is read for its long shapes only."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    monkeypatch.setattr(connect, "_passphrase", SHORT if how == "held" else None)
    ss.forget_held()
    handed = () if how == "held" else (SHORT,)
    text, clean = f"could not open {SHORT} for reading", "could not open the file"
    assert ss.scrubbed(text, *handed) == ss.UNREADABLE_TEXT
    assert ss.scrubbed(text, *handed, withheld="OSError: its text is withheld") == "OSError: its text is withheld"
    assert ss.scrubbed(clean, *handed) is clean
    assert ss.scrubbed_value({"a": [text, clean], "n": 1}, *handed) == {"a": [ss.UNREADABLE_TEXT, clean], "n": 1}
    log = logging.getLogger("tests.floor_and_forms.short")
    caplog.set_level(logging.DEBUG, logger=log.name)
    try:
        raise OSError(text)
    except OSError as exc:
        assert ss.traceback_text(exc, *handed) == "OSError: its text is withheld"
        ss.log_failure(log, "failed", exc, *handed)
    (record,) = caplog.records
    assert record.getMessage() == "failed: OSError: its text is withheld\nOSError: its text is withheld"
    assert getattr(record, ss.TRACEBACK_ATTRIBUTE) == "OSError: its text is withheld"
    with pytest.raises(RuntimeError) as err, ss.scrub_and_reraise(log, "route failed", *handed):
        raise OSError(text)
    assert str(err.value) == "OSError: its text is withheld"
    assert SHORT not in caplog.text.replace("tests.floor_and_forms.short", "")


def test_a_short_secret_that_is_only_in_a_frame_of_the_traceback_withholds_the_whole_record(monkeypatch, caplog):
    """The exception's own line is clean and the frames are not (a frame prints the source line, which can hold the short secret
    as any text can), so the traceback is withheld and the line with it: the record is the class alone. MUTATION TARGET: a
    ``log_failure`` that withholds only the part that held the secret and writes the other as it was."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    monkeypatch.setattr(connect, "_passphrase", SHORT)
    ss.forget_held()
    log = logging.getLogger("tests.floor_and_forms.frame")
    caplog.set_level(logging.DEBUG, logger=log.name)

    def fails():
        raise OSError("no key in this message")  # zq is in this frame's source line

    try:
        fails()
    except OSError as exc:
        ss.log_failure(log, "failed", exc)
        assert ss.traceback_text(exc) == "OSError: its text is withheld"
    (record,) = caplog.records
    assert record.getMessage() == "failed: OSError: its text is withheld\nOSError: its text is withheld"
    assert getattr(record, ss.TRACEBACK_ATTRIBUTE) == "OSError: its text is withheld"


def test_a_short_held_passphrase_is_withheld_by_the_error_journal_too(monkeypatch, journal):
    """The journal writes the fixed words where a record's message or traceback holds a short passphrase it cannot take out, and
    keeps a record that holds none of its shapes as it was. MUTATION TARGET: the journal reading only the long shapes."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    monkeypatch.setattr(connect, "_passphrase", SHORT)
    ss.forget_held()
    journal.error("failed: could not open %s for reading", SHORT)
    journal.error("failed: could not open the file")
    try:
        raise OSError(f"could not open {SHORT}")
    except OSError as exc:
        journal.error("failed again", exc_info=exc)
    entries = errorlog.recent_errors()
    messages = [e["message"] for e in entries]
    assert ss.UNREADABLE_TEXT in messages and "failed: could not open the file" in messages and "failed again" in messages
    assert all(SHORT not in json.dumps(e).replace("tests.floor_and_forms", "") for e in entries), entries


def test_the_floor_is_stated_with_what_it_protects_and_what_it_costs():
    """The number is not allowed to stay without its reason (the project's rule on a fixed cap): the source says what it protects
    and what it costs."""
    import inspect

    text = inspect.getsource(ss)
    comment = text[text.index("#: The fewest characters"):text.index("MIN_SECRET_CHARS = ")]
    assert "WHAT IT PROTECTS" in comment and "WHAT IT COSTS" in comment


# --------------------------------------------------------------------------- #
#  Every shape a key takes in text, against what real writers make
# --------------------------------------------------------------------------- #
_WRITERS = {
    "repr": repr,
    "json": json.dumps,
    "json-utf8": lambda t: json.dumps(t, ensure_ascii=False),
}


def _spans(key: str, depth: int = 3) -> set[str]:
    """What the key looks like once real writers have written it into a text and written that text again, up to ``depth`` times:
    the text is ``QQQ`` + the key + ``WWW`` inside the statement an engine quotes (or on its own), in a context with both kinds of
    quote mark and in one without (``repr`` chooses its quote by what the whole text holds), each written by every sequence of
    ``repr`` and JSON. What the writers made of the key is what lies between the two markers, which no writer changes. This does
    not use the helper under test: it is the ground truth the helper's closure has to contain."""
    spans = {key, key.replace("'", "''")}
    for sql in (False, True):
        for quoted_context in (False, True):
            inner = key.replace("'", "''") if sql else key
            base = "QQQ" + inner + "WWW"
            if sql:
                base = f"PRAGMA key = '{base}'"
            if quoted_context:
                base = "'\"" + base + "'\""
            for size in range(1, depth + 1):
                for names in product(_WRITERS, repeat=size):
                    text = base
                    for name in names:
                        text = _WRITERS[name](text)
                    spans.add(text[text.index("QQQ") + 3 : text.rindex("WWW")])
    return spans


@pytest.mark.parametrize("key", SHAPE_KEYS)
def test_every_shape_real_writers_make_of_a_key_is_among_the_shapes_the_helper_takes_out(key):
    """MUTATION TARGET: a carrier left out of ``_carried``, the depth, or the second base (the SQL literal). The keys hold the
    characters a writer escapes, so a writer the closure does not know leaves a span here that the helper does not list."""
    forms = set(ss._forms(key))
    missing = sorted(_spans(key) - forms)
    assert not missing, missing
    assert len(forms) <= 170, "the most one secret has: a number that stays says what it protects (CARRIER_DEPTH)"
    if key == "plain-key-Pq7#":
        assert forms == {key}, "a key no writer changes has one shape"


@pytest.mark.parametrize("key", SHAPE_KEYS)
def test_a_text_written_again_by_each_sequence_of_writers_comes_back_with_the_key_out_at_every_layer_and_still_decodes(key):
    """The scrub is checked against the ground truth the other way too: write the statement that carried the key with every
    sequence of ``repr`` and JSON up to three deep, scrub the final text ONCE, and read it back layer by layer. At every layer
    the key is gone and what is left reads as the text it was, with the marker where the key was."""
    import ast

    readers = {"repr": ast.literal_eval, "json": json.loads, "json-utf8": json.loads}
    sentence = f"near {_sql(key)}: syntax error"
    checked = 0
    for size in (1, 2, 3):
        for names in product(_WRITERS, repeat=size):
            text = sentence
            for name in names:
                text = _WRITERS[name](text)
            out = ss.scrub_text(text, key)
            assert ss.scrubbed(text, key) == out
            layer = out
            for name in reversed(names):
                for shape in (key, key.replace("'", "''")):
                    assert shape not in layer, (names, shape, layer)
                layer = readers[name](layer)
            assert layer == f"near PRAGMA key = '{ss.REDACTED}': syntax error", (names, layer)
            checked += 1
    assert checked == 3 + 9 + 27


# --------------------------------------------------------------------------- #
#  The same through every net
# --------------------------------------------------------------------------- #
@pytest.fixture
def key_held(monkeypatch):
    monkeypatch.setattr(connect, "_passphrase", KEY)
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)


@pytest.fixture
def journal(monkeypatch, tmp_path):
    monkeypatch.setattr(errorlog, "_log_path", lambda: tmp_path / "app_errors.jsonl")
    log = logging.getLogger("tests.floor_and_forms")
    log.propagate = False
    log.setLevel(logging.DEBUG)
    handler = errorlog._JsonlErrorHandler(level=logging.WARNING)
    log.addHandler(handler)
    try:
        yield log
    finally:
        log.removeHandler(handler)


def _handler_call(exc: BaseException):
    scope = {"type": "http", "method": "GET", "path": "/api/whatever", "headers": []}
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(main.unhandled_exception_handler(Request(scope), exc))
    finally:
        loop.close()


def _nested_texts() -> list[str]:
    sentence = f"near {_sql(KEY)}: syntax error"
    out = [sentence]
    for size in (1, 2, 3):
        for names in product(_WRITERS, repeat=size):
            text = sentence
            for name in names:
                text = _WRITERS[name](text)
            out.append(text)
    # what Python itself writes of an exception that holds the statement: ``str`` of two arguments and the exception's ``repr``
    out += [str(ValueError(sentence, 1)), repr(ValueError(sentence, 1)), str({"detail": sentence}), json.dumps({"detail": sentence})]
    return out


def test_every_net_takes_the_key_out_of_the_statement_in_every_way_it_was_written_again(key_held, caplog, journal):
    """MUTATION TARGET: any net handing its text to a scrub that knows fewer shapes than the others. One key held by the process,
    44 texts that carry it (the statement an engine quotes, written again by every sequence of ``repr`` and JSON up to three deep,
    and by ``str``/``repr`` of an exception and of a dict), and the five places a text is written: the global handler (the response
    and the log), the error journal, a failed job's error line, the block a route wraps its work in, and ``log_failure``."""
    caplog.set_level(logging.DEBUG)
    spans = _spans(KEY)
    log = logging.getLogger("tests.floor_and_forms.nets")
    texts = _nested_texts()
    assert len(texts) == 44
    for text in texts:
        caplog.clear()
        written: list[str] = []

        resp = _handler_call(RuntimeError(text))
        written += [resp.body.decode(), json.dumps(json.loads(resp.body))]

        journal.error("failed: %s", text)
        try:
            raise OSError(text)
        except OSError as exc:
            journal.error("failed again", exc_info=exc)
            ss.log_failure(log, "failed a third time", exc, OTHER)
            with pytest.raises(RuntimeError) as converted, ss.scrub_and_reraise(log, "wrapped", OTHER):
                raise exc
            written.append(str(converted.value))
            job = BackgroundJob("nets", "T", lambda ctx, _t=text: (_ for _ in ()).throw(RuntimeError(_t)))
            job.start()
            job._thread.join(5)
            written.append(str(job.status()["error"]))
        # What the scrubbing writers logged. The journal's own logger is left out: pytest's capture handler is attached to a logger
        # that does not propagate and formats the record this test wrote with ``exc_info``, as raised; the journal's file is read
        # below, which is the place a record of that logger is kept.
        other = [r for r in caplog.records if r.name != journal.name]
        assert other and all(r.exc_info is None and r.exc_text is None for r in other)
        written += [r.getMessage() for r in other]
        written += [str(getattr(r, ss.TRACEBACK_ATTRIBUTE, "")) for r in other]
        written += [json.dumps(entry, ensure_ascii=False) + json.dumps(entry) for entry in errorlog.recent_errors()]
        blob = "\n".join(written)
        assert "syntax error" in blob, "the words around the key are kept"
        for span in spans:
            holders = [i for i, part in enumerate(written) if span in part]
            assert not holders, (text, span, holders, [written[i][:300] for i in holders])


# --------------------------------------------------------------------------- #
#  The held passphrases are taken out of every call, and a text that could not be checked is not kept
# --------------------------------------------------------------------------- #
def test_scrubbed_takes_out_what_the_process_holds_whether_or_not_it_is_handed_in(monkeypatch):
    """MUTATION TARGET: the held passphrases dropped from ``scrubbed``, ``traceback_text`` or ``log_failure``. A handler cannot know
    which key a callee used: the restore holds the backup's key, and the engine under it opened the store with the session's."""
    monkeypatch.setattr(connect, "_passphrase", KEY)
    monkeypatch.setenv("OO_DB_PASSPHRASE", OTHER)
    text = f"a {KEY} b {OTHER} c typed-by-hand-9"
    assert ss.scrubbed(text) == f"a {ss.REDACTED} b {ss.REDACTED} c typed-by-hand-9"
    assert ss.scrubbed(text, "typed-by-hand-9") == f"a {ss.REDACTED} b {ss.REDACTED} c {ss.REDACTED}"
    try:
        raise ValueError(text)
    except ValueError as exc:
        tb = ss.traceback_text(exc)
    assert KEY not in tb and OTHER not in tb and f"ValueError: a {ss.REDACTED} b {ss.REDACTED}" in tb


def test_the_passphrase_that_wraps_the_signing_keys_is_held_like_the_others(monkeypatch):
    """``OO_KEY_PASSPHRASE`` (``src/custody/signing.py``) is a passphrase the process holds, in its environment and its memory like
    ``OO_DB_PASSPHRASE``. MUTATION TARGET: it dropped from ``held_passphrases``."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    monkeypatch.setattr(connect, "_passphrase", None)
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    assert ss.held_passphrases() == ()
    monkeypatch.setenv("OO_KEY_PASSPHRASE", "signing-key-wrap-9Qz")
    assert ss.held_passphrases() == ("signing-key-wrap-9Qz",)
    assert ss.scrubbed("a signing-key-wrap-9Qz b") == f"a {ss.REDACTED} b"
    monkeypatch.setenv("OO_DB_PASSPHRASE", KEY)
    monkeypatch.setattr(connect, "_passphrase", KEY)
    assert ss.held_passphrases() == (KEY, "signing-key-wrap-9Qz"), "each once, the session's first"


def test_clearing_the_sessions_passphrase_clears_the_shapes_made_of_it(monkeypatch):
    """The cache holds the passphrases themselves (a core dump is in the rule), so clearing the session's passphrase (a failed unlock or create,
    the crypto-erase: ``connect.set_passphrase``) empties it. MUTATION TARGET: ``forget_held`` left out of ``set_passphrase``, or one that empties
    nothing."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr(connect, "_passphrase", None)
    ss.forget_held()
    connect.set_passphrase("held-by-the-session-5Kd")
    try:
        assert ss.scrubbed("x held-by-the-session-5Kd y") == f"x {ss.REDACTED} y"
        assert "held-by-the-session-5Kd" in repr(ss._HELD_FORMS), "the entry is the thing that is cleared"
        connect.set_passphrase(None)
        assert ss._HELD_FORMS == ((), (), ()) and "held-by-the-session-5Kd" not in repr(ss._HELD_FORMS)
        assert ss.scrubbed("x held-by-the-session-5Kd y") == "x held-by-the-session-5Kd y", "a cleared session holds nothing"
    finally:
        connect.set_passphrase(None)


def test_forget_held_empties_the_entry_and_the_next_scrub_rebuilds_what_is_still_held(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", OTHER)
    monkeypatch.setattr(connect, "_passphrase", None)
    ss.forget_held()
    assert ss._HELD_FORMS == ((), (), ())
    assert ss.scrubbed(f"x {OTHER} y") == f"x {ss.REDACTED} y"
    assert OTHER in repr(ss._HELD_FORMS)
    ss.forget_held()
    assert ss._HELD_FORMS == ((), (), ())
    assert ss.scrubbed(f"x {OTHER} y") == f"x {ss.REDACTED} y", "what is still held is taken out again after the entry was dropped"


def test_scrubbed_value_walks_what_json_produces_and_leaves_keys_numbers_and_the_rest_alone(monkeypatch):
    """Every STRING in a structure goes through ``scrubbed``: dict values, list and tuple members, at any depth. The KEYS are
    field names the code defines (a passphrase that is a piece of one must not rename it), numbers, booleans and ``None`` pass
    through, and what JSON does not produce passes through as it is. MUTATION TARGET: keys scrubbed too, a tuple or a nested
    list skipped, the held passphrases not read."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", OTHER)
    monkeypatch.setattr(connect, "_passphrase", None)
    ss.forget_held()
    value = {
        f"key-{KEY}": f"a {KEY} b",
        "list": [f"{OTHER}", {"deep": (f"{_sql(KEY)}", 3, None, True)}],
        "n": 1.5,
        "raw": b"bytes " + KEY.encode(),
    }
    out = ss.scrubbed_value(value, KEY)
    assert out == {
        f"key-{KEY}": f"a {ss.REDACTED} b",
        "list": [ss.REDACTED, {"deep": (f"PRAGMA key = '{ss.REDACTED}'", 3, None, True)}],
        "n": 1.5,
        "raw": b"bytes " + KEY.encode(),
    }
    assert ss.scrubbed_value("a plain text") == "a plain text" and ss.scrubbed_value(7) == 7


def test_scrubbed_value_withholds_every_string_when_what_is_held_cannot_be_read_and_never_raises(monkeypatch):
    monkeypatch.setattr(ss, "held_passphrases", lambda: None)
    assert ss.scrubbed_value({"a": ["x", {"b": "y"}], "n": 2}) == {"a": [ss.UNREADABLE_TEXT, {"b": ss.UNREADABLE_TEXT}], "n": 2}
    deep: object = "text"
    for _ in range(sys.getrecursionlimit() + 50):
        deep = [deep]
    monkeypatch.undo()
    assert ss.scrubbed_value(deep, withheld="too deep to read") == "too deep to read"


def test_what_the_process_holds_is_read_at_each_call_and_a_changed_passphrase_is_the_one_taken_out_next(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    monkeypatch.setattr(connect, "_passphrase", KEY)
    assert ss.scrubbed(f"x {KEY} y") == f"x {ss.REDACTED} y"
    monkeypatch.setattr(connect, "_passphrase", OTHER)  # an unlock after a lock: the cache is for the one it was made for
    assert ss.scrubbed(f"x {KEY} y {OTHER}") == f"x {KEY} y {ss.REDACTED}"
    monkeypatch.setattr(connect, "_passphrase", None)
    assert ss.scrubbed(f"x {KEY} y {OTHER}") == f"x {KEY} y {OTHER}"


def test_a_text_is_withheld_when_what_the_process_holds_cannot_be_read_and_never_kept_on_the_chance_it_holds_none(monkeypatch):
    """MUTATION TARGET: ``None`` read as "holds nothing" in any of the helpers."""
    monkeypatch.setattr(ss, "held_passphrases", lambda: None)
    assert ss.scrubbed(f"near {KEY}") == ss.UNREADABLE_TEXT
    assert ss.scrubbed(f"near {KEY}", KEY, withheld="its words are withheld") == "its words are withheld"
    assert ss.scrubbed("a text that holds no key at all") == ss.UNREADABLE_TEXT, "it cannot be ruled out, so it is not kept"
    try:
        raise ValueError(f"near {KEY}")
    except ValueError as exc:
        assert ss.traceback_text(exc, KEY) == "ValueError: its text is withheld"


def test_what_the_process_holds_is_none_when_it_cannot_be_read_and_never_an_empty_tuple_then(monkeypatch):
    """MUTATION TARGET: the read's failure answered as "holds nothing" (``()``), or a held value that is no text kept as it is:
    either writes every text as it came, on the chance that it holds no key."""
    monkeypatch.setenv("OO_DB_PASSPHRASE", "")
    monkeypatch.setattr(connect, "_passphrase", None)
    assert ss.held_passphrases() == (), "a lock holds nothing: that one IS an empty answer"
    monkeypatch.setattr(connect, "_passphrase", b"bytes-are-no-passphrase")  # a store whose global holds something that is no text
    assert ss.held_passphrases() is None
    assert ss.scrubbed(f"near {KEY}") == ss.UNREADABLE_TEXT
    monkeypatch.setattr(connect, "_passphrase", KEY)
    assert ss.held_passphrases() == (KEY,)
    monkeypatch.setitem(sys.modules, "src.database.connect", object())  # a module that has no namespace to read
    assert ss.held_passphrases() is None
    assert ss.scrubbed(f"near {KEY}") == ss.UNREADABLE_TEXT


def test_the_scrub_never_raises_whatever_it_is_given_and_keeps_nothing_it_could_not_check(monkeypatch):
    assert ss.scrubbed(None) == ss.UNREADABLE_TEXT  # type: ignore[arg-type]
    assert ss.scrubbed(b"bytes " + KEY.encode()) == ss.UNREADABLE_TEXT  # type: ignore[arg-type]
    monkeypatch.setattr(ss, "_forms_now", lambda secrets: (_ for _ in ()).throw(RuntimeError("the scrub broke")))
    assert ss.scrubbed(f"near {KEY}", KEY, withheld="Name: its text is withheld") == "Name: its text is withheld"


def test_log_failure_writes_the_class_alone_when_the_scrub_cannot_run_and_never_raises(monkeypatch, caplog):
    log = logging.getLogger("tests.floor_and_forms.log_failure")
    caplog.set_level(logging.DEBUG, logger=log.name)
    monkeypatch.setattr(ss, "held_passphrases", lambda: None)
    try:
        raise OSError(f"near {KEY}")
    except OSError as exc:
        ss.log_failure(log, "failed", exc, KEY)
    (record,) = caplog.records
    assert "OSError: its text is withheld" in record.getMessage() and KEY not in caplog.text
    assert getattr(record, ss.TRACEBACK_ATTRIBUTE) == "OSError: its text is withheld"


# --------------------------------------------------------------------------- #
#  The block a route that takes a typed key wraps its work in
# --------------------------------------------------------------------------- #
LOG = logging.getLogger("tests.floor_and_forms.block")


def test_what_escapes_the_block_is_a_runtime_error_with_the_secrets_out_of_its_text_raised_from_none_and_logged_once(caplog):
    caplog.set_level(logging.DEBUG, logger=LOG.name)
    with pytest.raises(RuntimeError) as err, ss.scrub_and_reraise(LOG, "typed key failed", KEY, OTHER):
        raise OSError(f"{_sql(KEY)} then {_sql(OTHER)} and the rest")
    exc = err.value
    assert type(exc) is RuntimeError and str(exc) == f"OSError: PRAGMA key = '{ss.REDACTED}' then PRAGMA key = '{ss.REDACTED}' and the rest"
    assert exc.__cause__ is None and exc.__suppress_context__ is True
    (record,) = caplog.records
    assert record.levelno == logging.ERROR and record.getMessage().startswith("typed key failed: OSError: PRAGMA key = ")
    assert KEY not in caplog.text and OTHER not in caplog.text and record.exc_info is None
    assert KEY not in "".join(__import__("traceback").format_exception(exc))


def test_the_frameworks_own_answer_a_non_exception_and_a_clean_exit_pass_through_as_they_are(caplog):
    caplog.set_level(logging.DEBUG, logger=LOG.name)
    answer = HTTPException(status_code=400, detail="the code's own words")
    with pytest.raises(HTTPException) as err, ss.scrub_and_reraise(LOG, "x", KEY):
        raise answer
    assert err.value is answer
    for base in (KeyboardInterrupt, SystemExit, GeneratorExit):
        with pytest.raises(base), ss.scrub_and_reraise(LOG, "x", KEY):
            raise base()
    with ss.scrub_and_reraise(LOG, "x", KEY):
        value = 7
    assert value == 7 and not caplog.records, "nothing is written for an answer, an interrupt or a block that did not fail"


def test_a_passthrough_the_caller_names_replaces_the_default(caplog):
    class Mine(Exception):
        pass

    mine = Mine("kept as it is")
    with pytest.raises(Mine) as err, ss.scrub_and_reraise(LOG, "x", KEY, passthrough=(Mine,)):
        raise mine
    assert err.value is mine
    with pytest.raises(RuntimeError), ss.scrub_and_reraise(LOG, "x", KEY, passthrough=(Mine,)):
        raise HTTPException(status_code=400, detail=f"built from {KEY}")  # no longer a passthrough: the caller replaced the default


def test_a_log_that_cannot_be_written_does_not_replace_the_conversion(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("the log is full")

    monkeypatch.setattr(ss, "log_failure", broken)
    with pytest.raises(RuntimeError) as err, ss.scrub_and_reraise(LOG, "x", KEY):
        raise ValueError(f"near {KEY}")
    assert str(err.value) == f"ValueError: near {ss.REDACTED}"


def test_an_exception_whose_text_cannot_be_made_is_converted_to_its_class_alone():
    class Broken(Exception):
        def __str__(self) -> str:
            raise ValueError("no text")

    with pytest.raises(RuntimeError) as err, ss.scrub_and_reraise(LOG, "x", KEY):
        raise Broken()
    assert str(err.value) == "Broken: its text is withheld"


def test_a_block_whose_scrub_cannot_run_raises_the_class_of_what_failed_and_none_of_its_words(monkeypatch):
    monkeypatch.setattr(ss, "held_passphrases", lambda: None)
    with pytest.raises(RuntimeError) as err, ss.scrub_and_reraise(LOG, "x", KEY):
        raise ValueError(f"near {KEY}")
    assert str(err.value) == "ValueError: its text is withheld"


def test_blocks_inside_blocks_convert_once_more_and_leak_nothing(caplog):
    caplog.set_level(logging.DEBUG, logger=LOG.name)
    with (
        pytest.raises(RuntimeError) as err,
        ss.scrub_and_reraise(LOG, "outer", KEY),
        ss.scrub_and_reraise(LOG, "inner", KEY),
    ):
        raise ValueError(f"near {_sql(KEY)}")
    assert KEY not in str(err.value) and KEY not in caplog.text and "syntax" not in str(err.value) and "near" in str(err.value)


def test_the_secrets_a_block_names_may_be_empty_or_missing_and_the_held_ones_are_taken_out_anyway(monkeypatch):
    monkeypatch.setattr(connect, "_passphrase", KEY)
    with pytest.raises(RuntimeError) as err, ss.scrub_and_reraise(LOG, "x", None, "", OTHER):
        raise ValueError(f"{KEY} and {OTHER}")
    assert str(err.value) == f"ValueError: {ss.REDACTED} and {ss.REDACTED}"
