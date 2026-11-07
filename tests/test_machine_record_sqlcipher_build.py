"""The machine record says which SQLCipher BUILD runs, beside its version (R470, the 07 Nov cache/pool/checkpoint measurements).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The same ``4.19.0 community`` string was on a Linux VM that holds the write gate 0.55 s a flush and on a Windows install that held it
36 to 68 s, so the version does not tell which build runs. ``versions.sqlcipher_build`` carries three readings of the library: the crypto
``provider``, its ``provider_version`` and ``memory_security`` (``PRAGMA cipher_memory_security``). What must hold:

* all three are always present, each a non-empty string or ``{"unavailable": reason}`` (RC2's condition: never left out), whether the
  driver is missing, the connection will not open, the key is refused or one pragma answers nothing, and one that fails leaves the
  others standing;
* the reason is the exception's CLASS, never its message (a path or a user name in a message would reach the archive);
* nothing is SET: the only statement with an ``=`` is the key of the throwaway in-memory database, which is a random raw key made
  there, differs on every reading, is not the corpus's passphrase and is not read from the environment;
* the block stays under the 10,000 bytes the slot arithmetic counts for the machine record (R426), and the three readings cost the
  manifest a stated number of bytes.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import types

import pytest

from src.monitoring import machine_record as MR

NAMES = ("provider", "provider_version", "memory_security")
GOOD = {"cipher_provider": "openssl", "cipher_provider_version": "OpenSSL 3.6.0 1 Oct 2025", "cipher_memory_security": "0"}


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    """A stand-in for a sqlcipher3 connection that records every statement it is given."""

    def __init__(self, answers, log, fail_on=()):
        self.answers, self.log, self.fail_on, self.closed = answers, log, fail_on, False

    def execute(self, sql):
        self.log.append(sql)
        for needle in self.fail_on:
            if needle in sql:
                raise OSError("the secret path /home/x must not be named")
        m = re.fullmatch(r"PRAGMA (\w+)", sql)
        if m is None:
            return _Cursor(None)  # the key statement answers nothing
        value = self.answers.get(m.group(1))
        return _Cursor(None if value is None else (value,))

    def close(self):
        self.closed = True


def _driver(monkeypatch, answers=None, log=None, fail_on=(), connect_error=None):
    """Replace the sqlcipher3 driver the record imports with one that hands back a ``_Conn``; returns the log of statements."""
    log = [] if log is None else log
    made: list[_Conn] = []

    def connect(target):
        assert target == ":memory:", "the throwaway never touches a file"
        if connect_error is not None:
            raise connect_error
        conn = _Conn(GOOD if answers is None else answers, log, fail_on)
        made.append(conn)
        return conn

    dbapi2 = types.ModuleType("sqlcipher3.dbapi2")
    dbapi2.connect = connect
    pkg = types.ModuleType("sqlcipher3")
    pkg.dbapi2 = dbapi2
    monkeypatch.setitem(sys.modules, "sqlcipher3", pkg)
    monkeypatch.setitem(sys.modules, "sqlcipher3.dbapi2", dbapi2)
    return log, made


def _all_present(build: dict) -> None:
    assert tuple(build) == NAMES, "all three, in this order, none left out"
    for name in NAMES:
        value = build[name]
        assert (isinstance(value, str) and value) or (isinstance(value, dict) and list(value) == ["unavailable"] and value["unavailable"]), name


def test_the_three_readings_are_in_the_versions_block_of_the_record():
    build = MR.machine_block()["versions"]["sqlcipher_build"]
    _all_present(build)


def test_the_real_library_answers_all_three_with_a_value():
    build = MR._sqlcipher_build()
    _all_present(build)
    assert all(isinstance(v, str) for v in build.values()), f"the pinned sqlcipher3 driver answers every one: {build}"
    assert build["memory_security"] in ("0", "1")


def test_a_library_that_answers_gives_its_own_values(monkeypatch):
    log, made = _driver(monkeypatch)
    assert MR._sqlcipher_build() == {
        "provider": "openssl",
        "provider_version": "OpenSSL 3.6.0 1 Oct 2025",
        "memory_security": "0",
    }
    assert made[0].closed, "the throwaway is closed"


def test_a_missing_driver_names_the_reason_for_each_of_the_three(monkeypatch):
    monkeypatch.setitem(sys.modules, "sqlcipher3", None)
    monkeypatch.setitem(sys.modules, "sqlcipher3.dbapi2", None)
    build = MR._sqlcipher_build()
    _all_present(build)
    assert all(v["unavailable"].startswith("the sqlcipher3 driver is not importable (") for v in build.values())


def test_a_connection_that_will_not_open_is_a_reason_by_class_for_each(monkeypatch):
    _driver(monkeypatch, connect_error=OSError("the secret path /home/x must not be named"))
    build = MR._sqlcipher_build()
    _all_present(build)
    assert set(map(json.dumps, build.values())) == {json.dumps({"unavailable": "OSError"})}
    assert "/home/x" not in json.dumps(build), "the type, never the text"


def test_a_key_the_library_refuses_fails_closed_all_three_unavailable_by_class(monkeypatch):
    log, _ = _driver(monkeypatch, fail_on=("PRAGMA key",))
    build = MR._sqlcipher_build()
    _all_present(build)
    assert set(map(json.dumps, build.values())) == {json.dumps({"unavailable": "OSError"})}, "RC2: nothing is read through a refused key"
    assert "/home/x" not in json.dumps(build), "the class, never the text"
    assert not [s for s in log if s.startswith("PRAGMA cipher_provider")], "no pragma is asked after the key was refused"


@pytest.mark.parametrize("silent", NAMES)
def test_a_pragma_that_answers_nothing_says_so_and_the_other_two_stand(monkeypatch, silent):
    answers = {k: v for k, v in GOOD.items() if k != f"cipher_{silent}"}
    _driver(monkeypatch, answers=answers)
    build = MR._sqlcipher_build()
    _all_present(build)
    assert build[silent] == {"unavailable": "the library did not report it"}
    for other in NAMES:
        if other != silent:
            assert isinstance(build[other], str)


@pytest.mark.parametrize("empty", ["", None])
def test_an_empty_answer_is_not_a_value(monkeypatch, empty):
    """A row holding an empty string or NULL is no reading: it must not reach the archive as ``""`` (which reads as a value)."""
    _driver(monkeypatch, answers={**GOOD, "cipher_provider": empty, "cipher_provider_version": ""})
    build = MR._sqlcipher_build()
    _all_present(build)
    assert build["provider_version"] == {"unavailable": "the library did not report it"}
    assert build["provider"] == (
        {"unavailable": "the library did not report it"} if empty in ("", None) else empty
    )
    assert build["memory_security"] == "0"


def test_a_pragma_that_raises_leaves_the_other_two_standing(monkeypatch):
    _driver(monkeypatch, fail_on=("cipher_provider_version",))
    build = MR._sqlcipher_build()
    _all_present(build)
    assert build["provider_version"] == {"unavailable": "OSError"}
    assert build["provider"] == "openssl" and build["memory_security"] == "0"


def test_nothing_is_set_and_the_only_key_is_a_random_raw_one_kept_nowhere(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", "the-corpus-passphrase-must-not-be-used")
    log, _ = _driver(monkeypatch)
    MR._sqlcipher_build()
    MR._sqlcipher_build()
    sets = [s for s in log if "=" in s]
    assert len(sets) == 2 and all(s.startswith("PRAGMA key") for s in sets), f"only the keys set anything: {log}"
    keys = []
    for s in sets:
        m = re.fullmatch(r"PRAGMA key = \"x'([0-9a-f]{64})'\"", s)
        assert m is not None, "a raw 256-bit key: no KDF, no passphrase text"
        keys.append(m.group(1))
    assert keys[0] != keys[1], "a new one on every reading"
    assert "the-corpus-passphrase" not in " ".join(log)
    reads = [s for s in log if "=" not in s]
    assert set(reads) == {"PRAGMA cipher_memory_security", "PRAGMA cipher_provider", "PRAGMA cipher_provider_version"}


def test_no_setting_of_memory_security_exists_in_the_module_source():
    """Turning it off is the maintainer's decision about what a seized machine's pagefile may hold; this module only reads it."""
    import inspect

    src = inspect.getsource(MR)
    assert not re.search(r"cipher_memory_security\s*=", src)
    assert not re.search(r"PRAGMA\s+cipher_memory_security\s*=", src)


def _manifest_bytes(machine: dict) -> int:
    return len(json.dumps({"machine": machine}, ensure_ascii=False, indent=2).encode("utf-8"))


def test_the_three_readings_cost_the_manifest_a_stated_number_of_bytes():
    """R470 rules the exception to the net-zero rule: 154 bytes as the manifest writes them (indent 2, nested under machine.versions), and
    at most 420 when all three are reasons. The machine block stays inside the 10,000 the slot arithmetic counts (R426)."""
    from src.api.diagnostics.bundle import _machine_record_block

    block = _machine_record_block()
    without = {**block, "versions": {k: v for k, v in block["versions"].items() if k != "sqlcipher_build"}}
    cost = _manifest_bytes(block) - _manifest_bytes(without)
    assert 0 < cost <= 200, f"the real build's three values cost {cost} bytes"
    gone = {n: {"unavailable": "the sqlcipher3 driver is not importable (ModuleNotFoundError)"} for n in NAMES}
    worst = _manifest_bytes({**block, "versions": {**without["versions"], "sqlcipher_build": gone}}) - _manifest_bytes(without)
    assert worst <= 420, f"all three as reasons cost {worst} bytes"
    assert _manifest_bytes(block) <= 10_000


SENTINEL_KEY = "c0ffee" * 10 + "abcd"  # 64 hex characters, recognisable in any text it leaks into


@pytest.mark.parametrize("refused", [False, True])
def test_the_key_text_is_in_neither_the_record_nor_a_log_nor_an_error(monkeypatch, caplog, refused):
    """RC2's condition: the throwaway's key never reaches the record, a log capture or an exception's text, whether the library takes it or
    refuses it. The key is made by ``secrets``, so the test makes it recognisable."""
    monkeypatch.setattr(MR.secrets, "token_hex", lambda n=32: SENTINEL_KEY)
    log, made = _driver(monkeypatch, fail_on=("PRAGMA key",) if refused else ())
    caplog.set_level(logging.DEBUG)
    block = MR.machine_block()
    assert any(SENTINEL_KEY in s for s in log), "the test did make the library see the key (it would otherwise prove nothing)"
    assert SENTINEL_KEY not in json.dumps(block, ensure_ascii=False)
    assert SENTINEL_KEY not in caplog.text and not [r for r in caplog.records if SENTINEL_KEY in r.getMessage()]
    assert all(c.closed for c in made), "closed before the function returned"


def test_the_key_comes_from_secrets_in_process_and_is_dropped_after_use():
    import inspect

    body = inspect.getsource(MR._sqlcipher_build)
    assert "secrets.token_hex(32)" in body and "os.environ" not in body and "getenv" not in body
    assert "del key" in body
