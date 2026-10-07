"""A passphrase that cannot be written as text is refused with fixed words, and compared without raising (2026-10-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A lone surrogate (a JSON body's ``"\\ud800"``, an environment variable of bytes that are not UTF-8) cannot be encoded as
UTF-8, and the ``UnicodeEncodeError`` Python raises for it names the character and its place in the passphrase and holds
the whole text as its ``object``. That is not a form of the secret the scrub (``tests/test_secret_scrub.py``) can
recognise: it is a PIECE of it. So every place that turns a passphrase into bytes (the four key derivations of
``src/safety/crypto.py``, the columnar cache's, the signing keys' wrap and the store's ``PRAGMA key``) refuses it through ``secret_scrub.passphrase_bytes``, with
fixed words and no exception chained behind it, and so does every place that hands one to something that writes it by itself
(the encrypt tool's ``ATTACH ... KEY``, and the release run's hand-over of the passphrase to its restore child in the
environment); the one place that only COMPARES two passphrases (the lock screen, when the app is already open) encodes them so
that the comparison cannot raise.
"""

from __future__ import annotations

import traceback

import pytest

from src.monitoring import secret_scrub as S

#: A lone surrogate inside a passphrase, as a JSON body's ``"\\ud800"`` makes one.
BAD = "pass\ud800word"
#: What the environment makes of a byte that is not UTF-8 (``surrogateescape``).
BAD_ENV = "env\udcffkey"


def _written(exc: BaseException) -> str:
    """Everything a handler could write about ``exc``: its message, its repr and the whole chain a traceback prints."""
    return "\n".join([str(exc), repr(exc), "".join(traceback.format_exception(exc))])


def _no_piece_of_the_passphrase(text: str) -> None:
    for piece in ("ud800", "udcff", "position", "codec", "pass\\", "pass\ud800", "env\udcff"):
        assert piece not in text, f"{piece!r} in {text!r}"


# --------------------------------------------------------------------------- #
#  The helpers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", ["plain", "naïve passphrase ✓", "quote's \"two\" kinds", "日本語のパスフレーズ", "a" * 500])
def test_a_passphrase_that_can_be_written_is_its_utf8_bytes(text):
    assert S.passphrase_bytes(text) == text.encode("utf-8")


@pytest.mark.parametrize("bad", [BAD, BAD_ENV, "\ud800", "x\udfff"])
def test_a_lone_surrogate_is_refused_with_fixed_words_and_nothing_chained_behind_them(bad):
    """MUTATION TARGET. The refusal is raised AFTER the handler that caught Python's own error: raised inside it, the
    new exception keeps that one as its ``__context__`` and with it the whole passphrase as its ``object``."""
    with pytest.raises(ValueError) as err:
        S.passphrase_bytes(bad)
    assert str(err.value) == S.UNENCODABLE_PASSPHRASE
    assert err.value.__context__ is None and err.value.__cause__ is None
    _no_piece_of_the_passphrase(_written(err.value))
    assert bad not in _written(err.value)


def test_the_refusal_is_the_error_the_caller_asks_for():
    class Mine(RuntimeError):
        pass

    with pytest.raises(Mine) as err:
        S.passphrase_bytes(BAD, error=Mine)
    assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("same", "same", True),
        ("same", "other", False),
        ("naïve ✓", "naïve ✓", True),
        ("naïve ✓", "naive ✓", False),
        (BAD, BAD, True),
        (BAD, "pass\ud801word", False),
        (BAD, "password", False),
        ("password", BAD, False),
        (BAD_ENV, BAD_ENV, True),
        (BAD_ENV, "env\udcfekey", False),
        ("", "", True),
        ("", "x", False),
    ],
)
def test_two_passphrases_are_compared_for_every_text_there_is_and_never_raise(a, b, same):
    """MUTATION TARGET. A lone surrogate is encoded as itself, so two different texts are never one."""
    assert S.same_passphrase(a, b) is same


# --------------------------------------------------------------------------- #
#  The key derivations
# --------------------------------------------------------------------------- #
def test_every_key_derivation_of_the_backup_envelope_refuses_a_lone_surrogate_with_fixed_words(tmp_path):
    """Four sites (the single-shot encrypt and decrypt, the stream header, the stream decrypt), each one a place a key is
    derived from the passphrase's bytes."""
    from src.safety import crypto

    blob = crypto.encrypt_bytes(b"data", "a-good-passphrase")
    plain, enc = tmp_path / "plain", tmp_path / "enc"
    plain.write_bytes(b"data")
    crypto.encrypt_file(plain, enc, "a-good-passphrase")
    calls = {
        "encrypt_bytes": lambda: crypto.encrypt_bytes(b"data", BAD),
        "decrypt_bytes": lambda: crypto.decrypt_bytes(blob, BAD),
        "encrypt_file": lambda: crypto.encrypt_file(plain, tmp_path / "out", BAD),
        "decrypt_stream": lambda: crypto.decrypt_stream(enc, lambda chunk: None, BAD),
    }
    for name, call in calls.items():
        with pytest.raises(crypto.EncryptionError) as err:
            call()
        assert str(err.value) == S.UNENCODABLE_PASSPHRASE, name
        assert err.value.__context__ is None, name
        _no_piece_of_the_passphrase(_written(err.value))
    assert not (tmp_path / "out").exists(), "the stream encrypt refuses before it creates anything"


def test_a_passphrase_with_letters_outside_ascii_still_round_trips(tmp_path):
    """The refusal is for one kind of text only: a key derived from an ordinary non-ASCII passphrase is the key it was."""
    from src.safety import crypto

    word = "pässwörd ✓ 日本"
    assert crypto.decrypt_bytes(crypto.encrypt_bytes(b"payload", word), word) == b"payload"
    plain, enc, back = tmp_path / "p", tmp_path / "e", tmp_path / "b"
    plain.write_bytes(b"payload" * 100)
    crypto.encrypt_file(plain, enc, word)
    crypto.decrypt_file(enc, back, word)
    assert back.read_bytes() == plain.read_bytes()


def test_the_columnar_caches_key_derivation_refuses_a_lone_surrogate_with_fixed_words():
    """MUTATION TARGET: ``passphrase.encode("utf-8")`` back in ``_derive_key``. The cache's key is stretched from the same
    passphrase, and the failure is logged by ``connect`` and ``encryption_gate``, whose scrub is of the passphrase and not of
    a piece of it."""
    from src.analytics import columnar

    for bad in (BAD, BAD_ENV):
        with pytest.raises(ValueError) as err:
            columnar._derive_key(bad, b"0" * 16)
        assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None
        _no_piece_of_the_passphrase(_written(err.value))
    assert len(columnar._derive_key("pässwörd ✓", b"0" * 16)) == 64, "an ordinary non-ASCII passphrase still derives"


def test_the_signing_keys_wrap_refuses_a_lone_surrogate_from_either_source_with_fixed_words(monkeypatch):
    """MUTATION TARGET: ``p.encode("utf-8")`` back in ``signing._passphrase``. The signing keys are wrapped under
    ``OO_KEY_PASSPHRASE`` when it is set and under the store's passphrase otherwise, and an environment variable of bytes
    that are not UTF-8 reads as a lone surrogate."""
    from src.custody import signing
    from src.database import connect

    monkeypatch.delenv("OO_KEY_PASSPHRASE", raising=False)
    monkeypatch.setattr(connect, "_passphrase", None)
    assert signing._passphrase() is None
    monkeypatch.setattr(connect, "_passphrase", "pässwörd ✓")
    assert signing._passphrase() == "pässwörd ✓".encode(), "an ordinary non-ASCII passphrase still wraps"
    monkeypatch.setenv("OO_KEY_PASSPHRASE", BAD_ENV)  # the environment can only hold a byte that is not UTF-8, as an escape
    monkeypatch.setattr(connect, "_passphrase", None)
    with pytest.raises(signing.SigningError) as err:
        signing._passphrase()
    assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None, "the environment's"
    _no_piece_of_the_passphrase(_written(err.value))
    monkeypatch.delenv("OO_KEY_PASSPHRASE")
    for bad in (BAD, BAD_ENV):
        monkeypatch.setattr(connect, "_passphrase", bad)
        with pytest.raises(signing.SigningError) as err:
            signing._passphrase()
        assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None, "the session's"
        _no_piece_of_the_passphrase(_written(err.value))


# --------------------------------------------------------------------------- #
#  The store's key
# --------------------------------------------------------------------------- #
class _Cursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql):
        self.log.append(sql)

    def close(self):
        pass


class _Conn:
    def __init__(self):
        self.statements: list[str] = []

    def cursor(self):
        return _Cursor(self.statements)


def test_the_store_key_with_a_lone_surrogate_is_refused_before_it_reaches_the_driver():
    """MUTATION TARGET. The driver's own error names the character and its place in the key, so the key is checked first."""
    from src.database.connect import _apply_key

    conn = _Conn()
    with pytest.raises(ValueError) as err:
        _apply_key(conn, BAD)
    assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None
    assert conn.statements == [], "nothing was handed to the driver"


def test_a_store_key_that_can_be_written_is_applied_as_before():
    from src.database.connect import _apply_key

    conn = _Conn()
    _apply_key(conn, "it's a naïve key")
    assert conn.statements == ["PRAGMA key = 'it''s a naïve key'"]


def test_opening_an_encrypted_store_with_a_lone_surrogate_key_is_a_wrong_passphrase_whose_chain_names_no_piece_of_it(tmp_path):
    pytest.importorskip("sqlcipher3")
    from src.database.connect import WrongPassphraseError, connect

    path = tmp_path / "store.db"
    con = connect(path, key="the-right-passphrase")
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    with pytest.raises(WrongPassphraseError) as err:
        connect(path, key=BAD)
    assert isinstance(err.value.__cause__, ValueError) and str(err.value.__cause__) == S.UNENCODABLE_PASSPHRASE
    _no_piece_of_the_passphrase(_written(err.value))
    connect(path, key="the-right-passphrase").close()  # the store itself was never touched


# --------------------------------------------------------------------------- #
#  The places that hand a passphrase to something that writes it by itself
# --------------------------------------------------------------------------- #
def _plain_store(path):
    import sqlite3

    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    return path


def test_the_attach_statement_of_the_encrypt_tool_never_sees_a_lone_surrogate_key(tmp_path):
    """MUTATION TARGET. The source is plaintext, so no ``PRAGMA key`` has looked at the key, and the ATTACH statement that carries
    it is encoded by the driver itself: its error names the character and its place in the statement and holds the statement."""
    pytest.importorskip("sqlcipher3")
    from src.database.connect import reencrypt_plain_to

    src, dest = _plain_store(tmp_path / "plain.db"), tmp_path / "enc.db"
    with pytest.raises(ValueError) as err:
        reencrypt_plain_to(src, dest, BAD)
    assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None and err.value.__cause__ is None
    _no_piece_of_the_passphrase(_written(err.value))
    assert not dest.exists(), "nothing was made for it"


def test_encrypting_a_store_in_place_refuses_a_lone_surrogate_key_before_the_plaintext_snapshot(tmp_path):
    """MUTATION TARGET. ``encrypt_database`` writes a plaintext snapshot of the store first: a key that is refused afterwards leaves
    that file behind for nothing."""
    pytest.importorskip("sqlcipher3")
    from src.database import encrypt_tool as tool

    db = _plain_store(tmp_path / "plain.db")
    before = sorted(p.name for p in tmp_path.iterdir())
    with pytest.raises(tool.EncryptToolError) as err:
        tool.encrypt_database(db, BAD)
    assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None and err.value.__cause__ is None
    _no_piece_of_the_passphrase(_written(err.value))
    assert sorted(p.name for p in tmp_path.iterdir()) == before, "no snapshot and no half-made copy"


def test_encrypting_every_store_refuses_a_lone_surrogate_key_before_it_looks_at_any_of_them(monkeypatch):
    """MUTATION TARGET. Before the single-writer gate is taken and before a store is named."""
    import src.api.unlock as unlock_mod
    from src.database import encrypt_tool as tool

    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: pytest.fail("a store was looked at"))
    with pytest.raises(tool.EncryptToolError) as err:
        tool.encrypt_all(BAD)
    assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None and err.value.__cause__ is None


@pytest.fixture
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as c:
        yield c


def _post_raw(client, url, payload):
    """A JSON body whose passphrase holds a lone surrogate, written as ``"\\ud800"`` (the client library cannot encode one)."""
    import json

    return client.post(url, content=json.dumps(payload).encode("ascii"), headers={"content-type": "application/json"})


def test_the_release_run_refuses_a_lone_surrogate_passphrase_at_both_routes_and_at_its_own_checks(client, tmp_path):
    """MUTATION TARGETS (four checks). The restore child is handed the passphrase in its ENVIRONMENT, which Python encodes by
    itself: a lone surrogate fails there with the character, its place in the passphrase and the passphrase as the error's
    object, after the run has made a backup for it."""
    from src.monitoring import release_run as rr

    (tmp_path / "elsewhere").mkdir()
    r = _post_raw(client, "/api/diagnostics/release-run", {"dest_dir": str(tmp_path / "elsewhere"), "passphrase": BAD})
    assert r.status_code == 400 and r.json()["detail"] == S.UNENCODABLE_PASSPHRASE, r.text
    r = _post_raw(client, "/api/diagnostics/release-run/resume", {"passphrase": BAD})
    assert r.status_code == 400 and r.json()["detail"] == S.UNENCODABLE_PASSPHRASE, r.text
    with pytest.raises(ValueError) as err:
        rr.RunParams(dest_dir=str(tmp_path / "elsewhere"), passphrase=BAD).validate()
    assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None
    with pytest.raises(ValueError) as err:
        rr.resume_preflight(BAD)
    assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None
    assert rr.RunParams(dest_dir=str(tmp_path / "elsewhere"), passphrase="pässwörd ✓").validate() is None, "one that can be written"


def test_the_restore_childs_hand_over_refuses_a_lone_surrogate_before_it_makes_a_directory_for_it(tmp_path):
    """MUTATION TARGET. The belt under the run's own checks: the helper is handed the passphrase in its environment, which Python
    encodes by itself, and a run that got past ``validate`` and the resume's preflight (a state file written by an older build)
    must not reach that."""
    from src.monitoring import release_run as rr

    dest = tmp_path / "elsewhere"
    dest.mkdir()
    run = rr._Run(rr.RunParams(dest_dir=str(dest), passphrase=BAD))
    with pytest.raises(ValueError) as err:
        rr._fresh_install_restore(None, run, tmp_path / "backup.zip", label="check")
    assert str(err.value) == S.UNENCODABLE_PASSPHRASE and err.value.__context__ is None
    assert list(dest.iterdir()) == [], "nothing was made for it"


# --------------------------------------------------------------------------- #
#  The lock screen's compare
# --------------------------------------------------------------------------- #
@pytest.fixture
def open_app(monkeypatch, tmp_path):
    """An app that is unlocked and encrypted, holding ``held``, and the attempts that got past the compare."""
    from src.api import unlock as U
    from src.database import connect as C

    state = {"held": "the-held-passphrase", "reached": [], "asked_of_file": []}
    monkeypatch.setattr(U, "main_db_path", lambda: tmp_path / "oo.db")
    monkeypatch.setattr(C, "is_encrypted_file", lambda p: True)
    monkeypatch.setattr(U, "app_lock_state", lambda: "unlocked-encrypted")
    monkeypatch.setattr(C, "get_passphrase", lambda: state["held"])
    # a held key typed again is asked of the FILE, read-only (the findings change of #1319): recorded here, never opened
    monkeypatch.setattr(U, "_file_opens_with", lambda p, passphrase: state["asked_of_file"].append(passphrase))
    monkeypatch.setattr(U, "_unlock_locked", lambda body, p: state["reached"].append(body.passphrase) or {"unlocked": False})
    return U, state


def test_the_held_passphrase_typed_again_is_recognised_and_asked_of_the_file_alone(open_app):
    U, state = open_app
    got = U.unlock(U.PassphraseBody(passphrase=state["held"]))
    assert got == {"unlocked": True, "state": "unlocked-encrypted"} and state["reached"] == []
    assert state["asked_of_file"] == [state["held"]]


def test_a_lone_surrogate_typed_on_an_open_app_is_checked_against_the_file_and_never_raises(open_app):
    """MUTATION TARGET. ``body.passphrase.encode("utf-8")`` raised ``UnicodeEncodeError`` here, outside every handler,
    with the character and its place in the typed passphrase in its message."""
    U, state = open_app
    U.unlock(U.PassphraseBody(passphrase=BAD))
    assert state["reached"] == [BAD], "not the held one: verified against the file, as any other wrong passphrase is"


def test_a_held_passphrase_with_a_lone_surrogate_is_still_recognised_when_typed_again(open_app):
    U, state = open_app
    state["held"] = BAD_ENV
    assert U.unlock(U.PassphraseBody(passphrase=BAD_ENV)) == {"unlocked": True, "state": "unlocked-encrypted"}
    assert state["reached"] == [] and state["asked_of_file"] == [BAD_ENV]


# --------------------------------------------------------------------------- #
#  First launch: the create route
# --------------------------------------------------------------------------- #
def test_the_create_route_refuses_a_lone_surrogate_in_fixed_words_before_it_creates_or_holds_anything(monkeypatch, tmp_path):
    """MUTATION TARGET: the check taken out. The passphrase went to ``init_db``, whose key step raised after the engine had
    opened a connection that was never closed, and the route answered 500."""
    from fastapi import HTTPException

    from src.api import unlock as U
    from src.database import connect as C

    monkeypatch.setattr(U, "main_db_path", lambda: tmp_path / "oo.db")
    monkeypatch.setattr(U, "app_lock_state", lambda: "fresh")
    held: list = []
    monkeypatch.setattr(C, "set_passphrase", lambda p: held.append(p))
    monkeypatch.setattr(U, "_finish_unlock", lambda **kw: held.append("finish"))
    typed = BAD + "-and-long-enough"
    with pytest.raises(HTTPException) as err:
        U.create_db(U.CreateBody(passphrase=typed, confirm=typed))
    assert err.value.status_code == 400 and err.value.detail == S.UNENCODABLE_PASSPHRASE
    assert err.value.__cause__ is None and held == [] and list(tmp_path.iterdir()) == []


def test_a_fresh_encrypted_store_whose_key_the_engine_refuses_leaves_no_connection_open(monkeypatch, tmp_path):
    """MUTATION TARGET: the close on the fresh-store paths of ``_connect``. ``_apply_key`` raised after ``sqc.connect`` had
    opened the file and nothing closed it (a descriptor and a lock held on a store that does not exist yet)."""
    from sqlcipher3 import dbapi2 as sqc

    from src.database import connect as C

    opened: list = []
    real = sqc.connect

    class Spy:
        def __init__(self, conn):
            self._conn, self.closed = conn, False

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def close(self):
            self.closed = True
            self._conn.close()

    def spy_connect(*a, **k):
        opened.append(Spy(real(*a, **k)))
        return opened[-1]

    monkeypatch.setattr(sqc, "connect", spy_connect)

    def refuses(conn, key):
        raise ValueError(S.UNENCODABLE_PASSPHRASE)

    monkeypatch.setattr(C, "_apply_key", refuses)
    for kwargs in ({"key": "a-fine-key-here"}, {"create_encrypted": True}):
        opened.clear()
        monkeypatch.setattr(C, "get_passphrase", lambda: "a-held-key-here")
        with pytest.raises(ValueError):
            C._connect(tmp_path / f"new-{len(kwargs)}.db", **kwargs)
        assert len(opened) == 1 and opened[0].closed is True, kwargs
