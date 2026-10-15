"""The app's own check of SQLCipher 4 page tags, for a file longer than 4 GiB (R134; ``src/database/page_auth.py``).

``PRAGMA cipher_integrity_check`` wraps at 2^32 bytes, so ``verify`` gives a longer main file to this module. Every claim is made
against REAL encrypted files damaged the way a bad sector damages them, with the engine's own pragma as the reference (the same page
numbers, page for page), and against pages fabricated with an independent derivation of the tag that the engine itself accepts:

  * parity: on a clean store and on copies with one to three corrupted pages, in the calibration window and past it, with a zeroed
    page, with a page moved to another number (the number is part of the tag), at 4 KiB and 16 KiB pages and in 3-page chunks, the
    pages named are the pragma's, and the count is never cut (``keep`` shrinks the printed list only);
  * it can never invent damage: a page 1 that fails, a wrong key, or pages 2 to 9 that ALL fail is ``mismatch``, a missing passphrase
    is ``no-key``, and a read that fails (``EIO``, a short read) is an unread page, never a failing one;
  * a stop is honoured between chunks;
  * the offset arithmetic holds past 2^32 bytes: pages at 65,537 and later of a 64 KiB-page file, on a stand-in file of that length
    (every platform) and on a real sparse file (where the filesystem has them), a bad page there is named;
  * the passphrase rule: the key is zeroed on EVERY path (the passphrase bytes, the encryption key and the tag key are all
    ``bytearray`` objects this test holds and reads back), and the module has no logger, thread or traceback to carry one in.
"""
from __future__ import annotations

import ast
import errno
import hashlib
import hmac
import os
import random
import re
import shutil
import struct
import sys
import threading
import types
from pathlib import Path

import pytest

from src.database import connect as connect_mod
from src.database import page_auth, verify

MARKER = "MARKER-pass-4711-correct-horse"
PASSPHRASE = MARKER + "-ÄÖ"  # not ASCII: the key is derived from the UTF-8 bytes
PAGE = 16384


@pytest.fixture(scope="module", autouse=True)
def _driver():
    pytest.importorskip("sqlcipher3")
    previous = connect_mod.get_passphrase()
    connect_mod.set_passphrase(PASSPHRASE)
    yield
    connect_mod.set_passphrase(previous)


def _build(path: Path, *, page_size: int = PAGE, rows: int = 1500) -> Path:
    con = connect_mod.connect(str(path), create_encrypted=True, check_same_thread=False, cipher_page_size=page_size)
    try:
        con.execute("CREATE TABLE t(x BLOB)")
        rng = random.Random(1)
        for _ in range(rows):
            con.execute("INSERT INTO t VALUES (?)", (rng.randbytes(3000),))
        con.commit()
    finally:
        con.close()
    for side in ("-wal", "-shm"):
        assert not Path(str(path) + side).exists(), "the store was left with a log"
    return path


@pytest.fixture(scope="module")
def base(tmp_path_factory, _driver) -> Path:
    return _build(tmp_path_factory.mktemp("pa") / "base.db")


@pytest.fixture(scope="module")
def base_4k(tmp_path_factory, _driver) -> Path:
    return _build(tmp_path_factory.mktemp("pa4k") / "base4k.db", page_size=4096, rows=300)


@pytest.fixture
def copy(tmp_path, base) -> Path:
    path = tmp_path / "copy.db"
    shutil.copy(base, path)
    return path


def _pages(path: Path, page_size: int = PAGE) -> int:
    return path.stat().st_size // page_size


def _flip(path: Path, page: int, page_size: int = PAGE) -> None:
    """One byte of ``page`` inverted (past the 16-byte salt on page 1)."""
    with open(path, "r+b") as fh:
        where = (page - 1) * page_size + page_size // 2
        fh.seek(where)
        byte = fh.read(1)
        fh.seek(where)
        fh.write(bytes([byte[0] ^ 0xFF]))


def _engine_failing(path: Path) -> list[int]:
    """The pages the engine's own pragma names, on a read-only connection from the app's factory (so at the file's own page size)."""
    con = verify.open_read_only(path)
    try:
        rows = [str(r[0]) for r in con.execute("PRAGMA cipher_integrity_check")]
    finally:
        con.close()
    return sorted(int(m.group(1)) for r in rows if (m := re.search(r"failed for page (\d+)", r)))


# --------------------------------------------------------------------------- #
#  parity with the engine's pragma
# --------------------------------------------------------------------------- #
def test_a_clean_file_has_no_failing_page_and_every_page_is_judged(copy):
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_CHECKED, found
    assert found["failing"] == 0 and found["pages"] == [] and found["unread"] == 0
    assert found["examined"] == found["pages_in_file"] == _pages(copy) > 256, "the file must be longer than one 4 MiB chunk"
    assert found["trailing_bytes"] == 0 and found["file_bytes"] == copy.stat().st_size
    assert _engine_failing(copy) == []


@pytest.mark.parametrize("seed", range(6))
def test_the_pages_named_are_the_engines_after_one_to_three_pages_are_corrupted(copy, seed):
    rng = random.Random(seed)
    victims = sorted(rng.sample(range(page_auth.CALIBRATION_PAGES + 2, _pages(copy) + 1), rng.choice([1, 1, 3])))
    for page in victims:
        _flip(copy, page)
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_CHECKED and found["pages"] == victims == _engine_failing(copy), found
    assert found["failing"] == len(victims) and found["examined"] == _pages(copy)


def test_a_page_inside_the_calibration_window_is_named_not_mistaken_for_a_mismatch(copy):
    _flip(copy, 2)
    _flip(copy, 5)
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_CHECKED and found["pages"] == [2, 5] == _engine_failing(copy), found


def test_a_zeroed_page_fails_as_it_does_in_the_engine(copy):
    with open(copy, "r+b") as fh:
        fh.seek(40 * PAGE)
        fh.write(bytes(PAGE))
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_CHECKED and found["pages"] == [41] == _engine_failing(copy), found


def test_a_page_moved_to_another_number_fails_because_the_number_is_part_of_the_tag(copy):
    with open(copy, "r+b") as fh:
        fh.seek(60 * PAGE)
        moved = fh.read(PAGE)
        fh.seek(70 * PAGE)
        fh.write(moved)
    found = page_auth.check_path(copy, PAGE)
    assert found["pages"] == [71] == _engine_failing(copy), found


def test_a_trailing_fragment_is_reported_and_is_not_a_page(copy):
    with open(copy, "ab") as fh:
        fh.write(b"\x00" * 100)
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_CHECKED and found["trailing_bytes"] == 100 and found["failing"] == 0 and found["unread"] == 0, found


def test_the_listed_numbers_are_the_lowest_and_the_count_is_every_failing_page(copy):
    victims = list(range(100, 140))
    for page in victims:
        _flip(copy, page)
    found = page_auth.check_path(copy, PAGE, keep=5)
    assert found["pages"] == victims[:5] and found["failing"] == 40, "a cap shrank what was COUNTED"


def test_small_chunks_change_nothing_at_their_edges(copy, monkeypatch):
    monkeypatch.setattr(page_auth, "CHUNK_BYTES", 3 * PAGE)
    victims = [10, 11, 12, 13, 18, 19, 20, _pages(copy)]  # on, before and after chunk edges, and the last page
    for page in victims:
        _flip(copy, page)
    found = page_auth.check_path(copy, PAGE)
    assert found["pages"] == victims == _engine_failing(copy) and found["examined"] == _pages(copy), found


def test_a_file_of_4_kib_pages_reads_its_page_size_and_agrees_with_the_engine(base_4k, tmp_path):
    path = tmp_path / "small.db"
    shutil.copy(base_4k, path)
    con = verify.open_read_only(path)
    try:
        assert page_auth.read_settings(con) == (4096, None)
    finally:
        con.close()
    for page in (3, 50, _pages(path, 4096)):
        _flip(path, page, 4096)
    found = page_auth.check_path(path, 4096)
    assert found["pages"] == [3, 50, _pages(path, 4096)] == _engine_failing(path), found


# --------------------------------------------------------------------------- #
#  it can never invent damage
# --------------------------------------------------------------------------- #
def test_a_page_1_that_fails_is_a_mismatch_never_a_finding(copy):
    _flip(copy, 1)
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_MISMATCH and found["mismatch_on"] == page_auth.MISMATCH_FIRST_PAGE, found


def test_pages_2_to_9_that_all_fail_beside_a_good_page_1_are_a_mismatch(copy):
    for page in range(2, 2 + page_auth.CALIBRATION_PAGES):
        _flip(copy, page)
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_MISMATCH, found
    assert found["mismatch_on"] == page_auth.MISMATCH_LATER_PAGES, "page 1 held: the record must not say the first page did not match"
    _flip(copy, 2 + page_auth.CALIBRATION_PAGES - 1)  # back: one of them holds again
    again = page_auth.check_path(copy, PAGE)
    assert again["state"] == page_auth.STATE_CHECKED and again["mismatch_on"] is None


def test_a_wrong_key_is_a_mismatch(copy):
    connect_mod.set_passphrase("another passphrase entirely")
    try:
        found = page_auth.check_path(copy, PAGE)
    finally:
        connect_mod.set_passphrase(PASSPHRASE)
    assert found["state"] == page_auth.STATE_MISMATCH and found["failing"] >= 1, found
    assert found["mismatch_on"] == page_auth.MISMATCH_FIRST_PAGE, found


def test_no_passphrase_held_is_no_key_and_judges_nothing(copy):
    connect_mod.set_passphrase(None)
    try:
        found = page_auth.check_path(copy, PAGE)
    finally:
        connect_mod.set_passphrase(PASSPHRASE)
    assert found["state"] == page_auth.STATE_NO_KEY and found["examined"] == 0 and found["failing"] == 0, found


def test_a_file_shorter_than_a_page_is_a_mismatch_and_one_without_a_salt_is_unreadable(tmp_path):
    short = tmp_path / "short.db"
    short.write_bytes(os.urandom(PAGE - 1))
    assert page_auth.check_path(short, PAGE)["state"] == page_auth.STATE_MISMATCH
    short.write_bytes(os.urandom(5))
    assert page_auth.check_path(short, PAGE)["state"] == page_auth.STATE_UNREADABLE


def test_a_missing_file_is_unreadable_with_the_class_and_errno_only(tmp_path):
    found = page_auth.check_path(tmp_path / MARKER / "nope.db", PAGE)
    assert found["state"] == page_auth.STATE_UNREADABLE and found["failure"] == "FileNotFoundError ENOENT", found
    assert MARKER not in repr(found)


class _Con:
    """A connection that answers the cipher pragmas it is given and nothing else."""

    def __init__(self, answers: dict[str, str | None]):
        self.answers = answers

    def execute(self, sql):
        name = sql.removeprefix("PRAGMA ").strip()
        value = self.answers.get(name)
        return types.SimpleNamespace(fetchone=lambda: None if value is None else (value,))


_DEFAULTS = {
    "cipher_page_size": "16384",
    "cipher_kdf_algorithm": "PBKDF2_HMAC_SHA512",
    "cipher_hmac_algorithm": "HMAC_SHA512",
    "kdf_iter": "256000",
    "cipher_use_hmac": "1",
    "cipher_plaintext_header_size": "0",
    "cipher_hmac_salt_mask": "3a",
    "cipher_hmac_pgno": "le",
}


def test_the_defaults_read_as_the_page_size():
    assert page_auth.read_settings(_Con(_DEFAULTS)) == (16384, None)
    assert page_auth.read_settings(_Con({**_DEFAULTS, "cipher_kdf_algorithm": None, "kdf_iter": None})) == (16384, None), "an answer that is missing is not a mismatch"


@pytest.mark.parametrize(
    "change",
    [
        {"cipher_kdf_algorithm": "PBKDF2_HMAC_SHA1"},
        {"cipher_hmac_algorithm": "HMAC_SHA256"},
        {"kdf_iter": "4000"},
        {"cipher_use_hmac": "0"},
        {"cipher_plaintext_header_size": "32"},
        {"cipher_hmac_salt_mask": "00"},
        {"cipher_hmac_pgno": "be"},
        {"cipher_page_size": "12345"},
        {"cipher_page_size": "131072"},
        {"cipher_page_size": "sixteen"},
        {"cipher_page_size": None},
    ],
)
def test_a_setting_that_is_not_the_default_is_refused_in_fixed_words(change):
    size, why = page_auth.read_settings(_Con({**_DEFAULTS, **change}))
    assert size is None and why and "page check" in why


# --------------------------------------------------------------------------- #
#  reads that fail, and a stop
# --------------------------------------------------------------------------- #
class _Flaky:
    """A real file whose reads fail the way a drive's do around one page, in the kinds a drive uses: ``eio`` (the read raises, naming a
    path and a message that carry the marker) and ``short`` (Linux answers a read that crosses a bad page with the bytes before it, and
    a read that starts in it with nothing)."""

    def __init__(self, real, page: int, kind: str, *, hook=None):
        self.real, self.first, self.last, self.kind, self.hook = real, (page - 1) * PAGE, page * PAGE, kind, hook
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.real.close()

    def seek(self, *args):
        return self.real.seek(*args)

    def readinto(self, view):
        self.reads += 1
        if self.hook is not None:
            self.hook(self.reads)
        pos = self.real.tell()
        end = pos + len(view)
        if pos < self.last and end > self.first:
            if self.kind == "eio":
                raise OSError(errno.EIO, f"disk error {MARKER}", f"/home/{MARKER}/x.db")
            if pos >= self.first:
                return 0
            return self.real.readinto(view[: self.first - pos])
        return self.real.readinto(view)


def _flaky(monkeypatch, page: int, kind: str, **kw) -> list[_Flaky]:
    made: list[_Flaky] = []

    def opener(path, mode="rb", buffering=0):
        made.append(_Flaky(open(path, mode, buffering=buffering), page, kind, **kw))  # noqa: SIM115 - the wrapper owns the handle and closes it
        return made[-1]

    monkeypatch.setattr(page_auth, "_raw_open", opener)
    return made


@pytest.mark.parametrize("kind", ["eio", "short"])
def test_a_page_the_drive_would_not_give_is_unread_and_never_failing(copy, monkeypatch, kind):
    _flaky(monkeypatch, 150, kind)
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_CHECKED and found["failing"] == 0 and found["pages"] == [], found
    assert found["unread"] == 1 and found["examined"] == _pages(copy) - 1, found
    if kind == "eio":
        assert found["failure"] == "OSError EIO" and MARKER not in repr(found)


def test_an_unreadable_page_beside_a_failing_one_is_counted_beside_it(copy, monkeypatch):
    _flip(copy, 200)
    _flaky(monkeypatch, 90, "eio")
    found = page_auth.check_path(copy, PAGE)
    assert found["pages"] == [200] and found["failing"] == 1 and found["unread"] == 1, found


def test_a_first_page_that_cannot_be_read_is_unreadable_not_a_mismatch(copy, monkeypatch):
    _flaky(monkeypatch, 1, "short")  # the salt is read first: it falls short
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_UNREADABLE and found["examined"] == 0, "a file that gives no salt has nothing to calibrate on"
    real_open = open

    class FirstPageFails(_Flaky):
        def readinto(self, view):
            if len(view) > 16 and self.real.tell() == 0:
                raise OSError(errno.EIO, f"disk error {MARKER}", f"/home/{MARKER}/x.db")
            return self.real.readinto(view)

    monkeypatch.setattr(page_auth, "_raw_open", lambda p, mode="rb", buffering=0: FirstPageFails(real_open(p, mode, buffering=buffering), 10**6, "eio"))
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_UNREADABLE and found["failure"] == "OSError EIO" and MARKER not in repr(found), found


def test_a_calibration_page_that_cannot_be_read_is_counted_and_does_not_stop_the_pass(copy, monkeypatch):
    _flaky(monkeypatch, 3, "eio")
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_CHECKED and found["unread"] == 1 and found["failing"] == 0, found
    assert found["examined"] == _pages(copy) - 1 and found["failure"] == "OSError EIO", found


def test_a_stop_asked_for_before_the_pass_judges_nothing(copy):
    stop = threading.Event()
    stop.set()
    found = page_auth.check_path(copy, PAGE, cancel=stop)
    assert found["state"] == page_auth.STATE_STOPPED and found["examined"] == 0


def test_a_stop_asked_for_in_the_middle_ends_the_pass_at_the_next_chunk(copy, monkeypatch):
    monkeypatch.setattr(page_auth, "CHUNK_BYTES", 20 * PAGE)
    stop = threading.Event()
    _flaky(monkeypatch, 10**6, "eio", hook=lambda n: stop.set() if n == 4 else None)  # a bad page far past the file: reads are real
    found = page_auth.check_path(copy, PAGE, cancel=stop)
    assert found["state"] == page_auth.STATE_STOPPED and 0 < found["examined"] < _pages(copy), found


def test_a_stop_asked_for_while_a_chunk_is_read_page_by_page_ends_it_at_the_next_page(copy, monkeypatch):
    """A drive that fails reads one slow page at a time: the loop that goes over a bad chunk page by page is the one a stop must reach.
    The chunk is 40 pages with an unreadable page 25 in it (the whole-chunk read falls short, so the pages are read one by one); the
    stop lands during the fourth of those reads, and the pass must end there and not at the end of the chunk."""
    monkeypatch.setattr(page_auth, "CHUNK_BYTES", 40 * PAGE)
    stop = threading.Event()
    # reads: 1 the salt, 2 the calibration pages, 3 the whole chunk (short), 4.. page 10, 11, 12, 13 ...
    _flaky(monkeypatch, 25, "short", hook=lambda n: stop.set() if n == 7 else None)
    found = page_auth.check_path(copy, PAGE, cancel=stop)
    assert found["state"] == page_auth.STATE_STOPPED, found
    assert found["examined"] < 25, f"the pass went on to the end of the chunk after the stop: {found}"
    assert found["unread"] == 0, "the stop came before the bad page was reached"


def test_a_list_of_no_pages_does_not_hide_a_failing_first_page_from_the_calibration(copy):
    """The calibration must not read page 1 out of the LIST of failing pages: with ``keep`` of 0 that list is empty, and a file the method
    does not fit would be filed ``checked`` with every page failing, which is invented damage."""
    _flip(copy, 1)
    found = page_auth.check_path(copy, PAGE, keep=0)
    assert found["state"] == page_auth.STATE_MISMATCH and found["mismatch_on"] == page_auth.MISMATCH_FIRST_PAGE, found
    assert found["pages"] == []
    for page in range(2, 2 + page_auth.CALIBRATION_PAGES):
        _flip(copy, page)
    _flip(copy, 1)  # page 1 holds again, pages 2 to 9 all fail
    found = page_auth.check_path(copy, PAGE, keep=0)
    assert found["state"] == page_auth.STATE_MISMATCH and found["mismatch_on"] == page_auth.MISMATCH_LATER_PAGES, found
    for page in range(2, 2 + page_auth.CALIBRATION_PAGES):
        _flip(copy, page)  # the file is healthy again; only the key is wrong now
    connect_mod.set_passphrase("another passphrase entirely")
    try:
        found = page_auth.check_path(copy, PAGE, keep=0)
    finally:
        connect_mod.set_passphrase(PASSPHRASE)
    assert found["state"] == page_auth.STATE_MISMATCH and found["mismatch_on"] == page_auth.MISMATCH_FIRST_PAGE, found


def test_a_list_of_no_pages_still_counts_every_failing_page(copy):
    _flip(copy, 20)
    _flip(copy, 30)
    found = page_auth.check_path(copy, PAGE, keep=0)
    assert found["state"] == page_auth.STATE_CHECKED and found["failing"] == 2 and found["pages"] == [], found


# --------------------------------------------------------------------------- #
#  past 2^32 bytes
# --------------------------------------------------------------------------- #
BIG_PAGE = 65536
BOUNDARY = (1 << 32) // BIG_PAGE  # the number of pages that fit in 2^32 bytes: page BOUNDARY + 1 STARTS at 2^32


def _tag_key(passphrase: str, salt: bytes) -> bytes:
    """SQLCipher 4's tag key, derived here from the specification and not through the module under test."""
    enc = hashlib.pbkdf2_hmac("sha512", passphrase.encode("utf-8"), salt, 256000, 32)
    return hashlib.pbkdf2_hmac("sha512", enc, bytes(b ^ 0x3A for b in salt), 2, 32)


def _fabricator(passphrase: str = PASSPHRASE, page_size: int = BIG_PAGE):
    salt = os.urandom(16)
    key = _tag_key(passphrase, salt)

    def page(number: int) -> bytes:
        body = bytearray(os.urandom(page_size - 64))
        if number == 1:
            body[:16] = salt
        start = 16 if number == 1 else 0
        return bytes(body) + hmac.new(key, bytes(body[start:]) + struct.pack("<I", number), "sha512").digest()

    return page


def test_the_pages_fabricated_for_the_boundary_tests_are_accepted_by_the_engine(tmp_path):
    """The fabricator is independent of the module under test (it is the specification, written out); this is its proof: the engine's own
    pragma accepts 12 pages made by it, and names the one whose byte is inverted."""
    page = _fabricator(page_size=PAGE)
    path = tmp_path / "fab.db"
    path.write_bytes(b"".join(page(n) for n in range(1, 13)))
    import sqlcipher3  # a fabricated file has no schema: the engine's factory would refuse it, so the pragma is asked on a bare keyed connection

    def engine(p: Path) -> list[int]:
        c = sqlcipher3.connect(f"{p.as_uri()}?mode=ro", uri=True)
        try:
            c.execute("PRAGMA key = '" + PASSPHRASE.replace("'", "''") + "'")
            c.execute(f"PRAGMA cipher_page_size = {PAGE}")
            return sorted(int(m.group(1)) for (r,) in c.execute("PRAGMA cipher_integrity_check") if (m := re.search(r"failed for page (\d+)", r)))
        finally:
            c.close()

    assert engine(path) == []
    _flip(path, 4)
    assert engine(path) == [4]


class _Virtual:
    """A file of a length no test should have to make: it serves the pages it is given, zeros elsewhere, and answers ``seek(0, 2)`` with
    its length. Nothing of it is on a drive, so it is the same on every platform (a sparse file is not sparse on NTFS)."""

    def __init__(self, length: int, pages: dict[int, bytes]):
        self.length, self.pages, self.pos = length, pages, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def seek(self, offset, whence=0):
        self.pos = self.length + offset if whence == os.SEEK_END else offset
        return self.pos

    def readinto(self, view):
        n = max(0, min(len(view), self.length - self.pos))
        out = bytearray()
        while len(out) < n:
            number, inside = divmod(self.pos + len(out), BIG_PAGE)
            data = self.pages.get(number + 1, bytes(BIG_PAGE))
            out += data[inside : inside + min(BIG_PAGE - inside, n - len(out))]
        view[:n] = out
        self.pos += n
        return n


def _boundary_pages(page, count_after: int = 4) -> dict[int, bytes]:
    return {n: page(n) for n in [*range(1, 10), *range(BOUNDARY + 1, BOUNDARY + 1 + count_after)]}


def test_a_page_that_starts_past_2_to_the_32_is_judged_and_a_bad_one_there_is_named(monkeypatch):
    page = _fabricator()
    pages = _boundary_pages(page)
    length = (BOUNDARY + 4) * BIG_PAGE
    assert length > 1 << 32
    served = {"file": _Virtual(length, pages)}
    monkeypatch.setattr(page_auth, "_raw_open", lambda path, mode="rb", buffering=0: served["file"])
    window = (BOUNDARY + 1, BOUNDARY + 4)
    found = page_auth.check_path(Path("virtual.db"), BIG_PAGE, window=window)
    assert found["state"] == page_auth.STATE_CHECKED and found["failing"] == 0 and found["examined"] == 9 + 4, found
    assert found["pages_in_file"] == BOUNDARY + 4 and found["file_bytes"] == length
    bad = bytearray(pages[BOUNDARY + 3])
    bad[1000] ^= 0xFF
    served["file"] = _Virtual(length, {**pages, BOUNDARY + 3: bytes(bad)})
    found = page_auth.check_path(Path("virtual.db"), BIG_PAGE, window=window)
    assert found["pages"] == [BOUNDARY + 3] and found["failing"] == 1, found
    moved = _Virtual(length, {**pages, BOUNDARY + 3: pages[3]})  # a good page of ANOTHER number is no good here
    served["file"] = moved
    assert page_auth.check_path(Path("virtual.db"), BIG_PAGE, window=window)["pages"] == [BOUNDARY + 3]


def test_the_lock_byte_page_is_the_one_that_holds_byte_2_to_the_30():
    assert [page_auth.lock_byte_page(n) for n in (512, 4096, 16384, 65536)] == [2_097_153, 262_145, 65_537, 16_385]


def test_the_lock_byte_page_is_not_judged_and_every_other_zero_page_still_fails(monkeypatch):
    """MEASURED on a healthy 4.37 GB store: the page at byte 2^30 is all zeros (SQLite never writes it) and the engine does not judge it;
    the first draft named it. Here at 64 KiB pages (page 16,385), with the page left as zeros, then damaged, then a zero page elsewhere."""
    page = _fabricator()
    lock = page_auth.lock_byte_page(BIG_PAGE)
    assert lock == 16_385
    around = {n: page(n) for n in [*range(1, 10), lock - 1, lock + 1]}
    length = (lock + 1) * BIG_PAGE
    served = {"file": _Virtual(length, around)}
    monkeypatch.setattr(page_auth, "_raw_open", lambda path, mode="rb", buffering=0: served["file"])
    found = page_auth.check_path(Path("virtual.db"), BIG_PAGE, window=(lock - 1, lock + 1))
    assert found["state"] == page_auth.STATE_CHECKED and found["failing"] == 0 and found["lock_byte_page"] == lock, found
    assert found["examined"] == 9 + 2, "the lock-byte page is neither examined nor failing"
    served["file"] = _Virtual(length, {**around, lock: os.urandom(BIG_PAGE)})
    assert page_auth.check_path(Path("virtual.db"), BIG_PAGE, window=(lock - 1, lock + 1))["failing"] == 0, "SQLite never reads it: nothing in it is damage"
    served["file"] = _Virtual(length, {n: b for n, b in around.items() if n != lock + 1})  # the page after it is zeros instead
    found = page_auth.check_path(Path("virtual.db"), BIG_PAGE, window=(lock - 1, lock + 1))
    assert found["pages"] == [lock + 1] and found["lock_byte_page"] == lock, "an all-zero page that is NOT the lock-byte page fails"
    short = _Virtual(10 * BIG_PAGE, {n: page(n) for n in range(1, 11)})
    served["file"] = short
    assert page_auth.check_path(Path("virtual.db"), BIG_PAGE)["lock_byte_page"] is None, "a file that does not reach the page says nothing of it"


def test_the_lock_byte_page_is_not_judged_when_the_chunk_is_read_page_by_page(monkeypatch):
    """A chunk the drive would not give whole is read page by page: the lock-byte page is passed over on that road too."""
    page = _fabricator()
    lock = page_auth.lock_byte_page(BIG_PAGE)
    around = {n: page(n) for n in [*range(1, 10), lock - 1, lock + 1]}

    class OnePageAtATime(_Virtual):
        def readinto(self, view):
            if len(view) > BIG_PAGE:
                raise OSError(errno.EIO, f"disk error {MARKER}", f"/home/{MARKER}/x.db")
            return super().readinto(view)

    served = OnePageAtATime((lock + 1) * BIG_PAGE, around)
    monkeypatch.setattr(page_auth, "_raw_open", lambda path, mode="rb", buffering=0: served)
    found = page_auth.check_path(Path("virtual.db"), BIG_PAGE, window=(lock - 1, lock + 1))
    assert found["state"] == page_auth.STATE_CHECKED and found["failing"] == 0 and found["unread"] == 0, found
    assert found["lock_byte_page"] == lock and found["examined"] == 9 + 2 and found["failure"] == "OSError EIO", found


@pytest.mark.skipif(sys.platform == "win32", reason="NTFS has no sparse files by default: the file would be written whole")
def test_the_same_holds_on_a_real_sparse_file_where_the_filesystem_has_them(tmp_path):
    probe = tmp_path / "probe"
    with open(probe, "wb") as fh:
        fh.seek(1 << 24)
        fh.write(b"x")
    if os.stat(probe).st_blocks * 512 > 1 << 22:
        pytest.skip("this filesystem does not keep holes")
    probe.unlink()
    page = _fabricator()
    path = tmp_path / "sparse.db"
    with open(path, "wb") as fh:
        for n in range(1, 10):
            fh.write(page(n))
        fh.seek(BOUNDARY * BIG_PAGE)
        for n in range(BOUNDARY + 1, BOUNDARY + 5):
            fh.write(page(n))
    try:
        assert path.stat().st_size > 1 << 32
        found = page_auth.check_path(path, BIG_PAGE, window=(BOUNDARY + 1, BOUNDARY + 4))
        assert found["state"] == page_auth.STATE_CHECKED and found["failing"] == 0 and found["examined"] == 13, found
        _flip(path, BOUNDARY + 3, BIG_PAGE)
        found = page_auth.check_path(path, BIG_PAGE, window=(BOUNDARY + 1, BOUNDARY + 4))
        assert found["pages"] == [BOUNDARY + 3] and found["failing"] == 1, found
    finally:
        path.unlink()


# --------------------------------------------------------------------------- #
#  the passphrase rule: the key is zeroed on every path
# --------------------------------------------------------------------------- #
class _Held:
    """What a pass held that is ours to wipe, read back after the pass: the passphrase bytes and the encryption key (the objects the two
    PBKDF2 calls were given) and the tag key (what ``derive_tag_key`` returned), each with a copy of what it held when it was made."""

    def __init__(self, monkeypatch, *, fail_on_call: int | None = None):
        self.given: list[bytearray] = []
        self.keys: list[bytearray] = []
        self.snapshots: list[bytes] = []
        outer = self

        class Spy:
            calls = 0

            @staticmethod
            def pbkdf2_hmac(name, password, salt, iterations, dklen=None):
                Spy.calls += 1
                outer.given.append(password)
                outer.snapshots.append(bytes(password))
                if fail_on_call == Spy.calls:
                    raise RuntimeError(f"{MARKER} {bytes(password).hex()}")
                return hashlib.pbkdf2_hmac(name, password, salt, iterations, dklen)

        real = page_auth.derive_tag_key

        def derive(salt):
            key = real(salt)
            if key is not None:
                outer.keys.append(key)
            return key

        monkeypatch.setattr(page_auth, "hashlib", Spy)
        monkeypatch.setattr(page_auth, "derive_tag_key", derive)

    def assert_all_zero(self, *, tag_key: bool = True) -> None:
        assert self.given, "the pass derived nothing: the test is vacuous"
        for buf, was in zip(self.given, self.snapshots, strict=True):
            assert isinstance(buf, bytearray) and any(was), "an intermediate key was not a bytearray this test could read back"
            assert not any(buf), "an intermediate (the passphrase bytes or the encryption key) was left in memory"
        if tag_key:
            assert self.keys and all(len(k) == 32 and not any(k) for k in self.keys), "the tag key was left in memory"


def test_the_tag_key_and_both_intermediates_are_zeroed_after_a_clean_pass(copy, monkeypatch):
    held = _Held(monkeypatch)
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_CHECKED
    assert len(held.given) == 2 and held.snapshots[0] == PASSPHRASE.encode("utf-8"), "the first call is given the passphrase bytes"
    held.assert_all_zero()


def test_the_derived_tag_key_is_the_one_the_specification_gives_and_a_different_passphrase_gives_another():
    salt = os.urandom(16)
    key = page_auth.derive_tag_key(salt)
    try:
        assert isinstance(key, bytearray) and bytes(key) == _tag_key(PASSPHRASE, salt) and any(key)
    finally:
        page_auth.wipe(key)
    assert not any(key)


def test_the_key_is_zeroed_when_the_calibration_disagrees(copy, monkeypatch):
    _flip(copy, 1)
    held = _Held(monkeypatch)
    assert page_auth.check_path(copy, PAGE)["state"] == page_auth.STATE_MISMATCH
    held.assert_all_zero()


def test_the_key_is_zeroed_when_a_read_fails_in_the_middle(copy, monkeypatch):
    _flaky(monkeypatch, 150, "eio")
    held = _Held(monkeypatch)
    assert page_auth.check_path(copy, PAGE)["unread"] == 1
    held.assert_all_zero()


def test_the_key_is_zeroed_when_the_pass_is_stopped(copy, monkeypatch):
    stop = threading.Event()
    monkeypatch.setattr(page_auth, "CHUNK_BYTES", 20 * PAGE)
    _flaky(monkeypatch, 10**6, "eio", hook=lambda n: stop.set() if n == 3 else None)
    held = _Held(monkeypatch)
    assert page_auth.check_path(copy, PAGE, cancel=stop)["state"] == page_auth.STATE_STOPPED
    held.assert_all_zero()


def test_the_key_is_zeroed_when_the_pass_raises_with_the_key_in_the_message(copy, monkeypatch):
    held = _Held(monkeypatch)
    seen: list[str] = []

    def boom(key, *args, **kwargs):
        seen.append(bytes(key).hex())  # the TAG key, as the test saw it when the exception was made
        raise RuntimeError(f"{MARKER} {seen[-1]}")

    monkeypatch.setattr(page_auth, "hmac", types.SimpleNamespace(new=boom, compare_digest=hmac.compare_digest))
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_UNREADABLE and found["failure"] == "RuntimeError", found
    assert len(seen) == 1 and any(bytes.fromhex(seen[0])), "the exception carried the real tag key: the test is vacuous otherwise"
    assert MARKER not in repr(found) and seen[0] not in repr(found) and held.snapshots[-1].hex() not in repr(found)
    held.assert_all_zero()


@pytest.mark.parametrize("call", [1, 2])
def test_the_intermediates_are_zeroed_when_a_derivation_itself_raises(copy, monkeypatch, call):
    held = _Held(monkeypatch, fail_on_call=call)
    found = page_auth.check_path(copy, PAGE)
    assert found["state"] == page_auth.STATE_UNREADABLE and found["failure"] == "RuntimeError" and MARKER not in repr(found), found
    held.assert_all_zero(tag_key=False)
    assert not held.keys


def test_wipe_zeroes_in_place_and_takes_nothing():
    buf = bytearray(b"secret-bytes")
    same = buf
    page_auth.wipe(buf)
    assert same is buf and not any(buf) and len(buf) == 12
    page_auth.wipe(None)
    page_auth.wipe(bytearray())


def test_a_passphrase_that_cannot_be_encoded_gives_no_key_and_no_chain(copy, monkeypatch):
    monkeypatch.setattr(connect_mod, "_passphrase", "bad-\ud800-" + MARKER)
    with open(copy, "rb") as fh:
        salt = fh.read(16)
    assert page_auth.derive_tag_key(salt) is None


def test_the_module_has_no_logger_thread_or_traceback_to_carry_a_key_in():
    """The conditions of R134 (1): the key is never given to a thread, a logger, a record or an exception. The imports are the whole list
    (a new one is a decision), and nothing in the module logs, prints, starts a thread or formats an exception."""
    tree = ast.parse(Path(page_auth.__file__).read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
    assert imported <= {"__future__", "hashlib", "hmac", "heapq", "os", "struct", "threading", "pathlib", "typing", "src"}, imported
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    banned = {c for c in calls if any(w in c for w in ("Thread", "logging", "logger", "traceback", "print", "repr", "format_exc", "exc_info"))}
    assert not banned, banned
    threads = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and ast.unparse(n.value) == "threading" and n.attr != "Event"]
    assert not threads, "threading is imported for its Event type only"


# --------------------------------------------------------------------------- #
#  no copy of the key that the zeroing cannot reach (R134 (1): "no copies beyond what hmac needs")
# --------------------------------------------------------------------------- #
def test_hmac_is_given_the_very_bytearray_that_is_wiped_and_no_module_name_keeps_a_copy(copy, monkeypatch):
    held = _Held(monkeypatch)
    given: list[object] = []
    snapshots: list[bytes] = []
    real_new = hmac.new

    def spy(key, *args, **kwargs):
        given.append(key)
        snapshots.append(bytes(key))
        return real_new(key, *args, **kwargs)

    monkeypatch.setattr(page_auth, "hmac", types.SimpleNamespace(new=spy, compare_digest=hmac.compare_digest))
    assert page_auth.check_path(copy, PAGE)["state"] == page_auth.STATE_CHECKED
    assert len(given) == 1 and len(held.keys) == 1, "one key, used once"
    assert given[0] is held.keys[0] and isinstance(given[0], bytearray), "hmac was given a copy, which nothing zeroes"
    secret = snapshots[0]
    assert any(secret)
    for name, value in vars(page_auth).items():
        if isinstance(value, (bytes, bytearray)):
            assert secret not in bytes(value) and PASSPHRASE.encode() not in bytes(value), f"page_auth.{name} holds a secret"
        elif isinstance(value, str):
            assert secret.hex() not in value and PASSPHRASE not in value, f"page_auth.{name} holds a secret"


_SECRET_NAMES = {"key", "password", "encryption_key", "held"}  # the names this module gives the passphrase and what is derived from it
_COPIERS = {"bytes", "str", "bytearray", "memoryview", "repr", "ascii", "format", "list", "tuple", "int", "bin", "hex"}
_TEXT_FORMS = {"hex", "decode", "tobytes", "tolist", "__bytes__"}


def _root(node: ast.AST) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Starred)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _copies_of_a_secret(source: str) -> list[str]:
    """Every place ``source`` makes a copy of, or keeps, a name that holds a secret: a ``bytes``/``str``/... of it, its ``.hex()``, an
    f-string of it, a ``global``, or an attribute or item that is assigned from it."""
    found: list[str] = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            found.append(f"{n.lineno}: a {type(n).__name__.lower()} statement")
        elif isinstance(n, ast.Call):
            func = n.func
            if isinstance(func, ast.Name) and func.id in _COPIERS and any(_root(a) in _SECRET_NAMES for a in n.args):
                found.append(f"{n.lineno}: {func.id}() of a secret")
            elif isinstance(func, ast.Attribute) and func.attr in _TEXT_FORMS and _root(func.value) in _SECRET_NAMES:
                found.append(f"{n.lineno}: .{func.attr}() of a secret")
        elif isinstance(n, ast.FormattedValue) and _root(n.value) in _SECRET_NAMES:
            found.append(f"{n.lineno}: a secret in an f-string")
        elif isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(isinstance(t, (ast.Attribute, ast.Subscript)) for t in targets) and any(
                isinstance(x, ast.Name) and x.id in _SECRET_NAMES for x in ast.walk(n.value)
            ):
                found.append(f"{n.lineno}: a secret stored on an attribute or an item")
    return found


@pytest.mark.parametrize(
    "snippet",
    [
        "def f(key):\n    return bytes(key)\n",
        "def f(key):\n    return key.hex()\n",
        "def f(key):\n    return str(key[:8])\n",
        "def f(password):\n    return f'{password}'\n",
        "def f(encryption_key):\n    global _KEPT\n    _KEPT = 1\n",
        "def f(self, key):\n    self.k = key\n",
        "def f(held):\n    return bytearray(held)\n",
        "def f(key):\n    return key.decode('latin-1')\n",
    ],
)
def test_the_copy_guard_can_fail(snippet):
    assert _copies_of_a_secret(snippet), snippet


def test_the_module_makes_no_copy_of_a_secret_the_zeroing_cannot_reach():
    assert _copies_of_a_secret(Path(page_auth.__file__).read_text(encoding="utf-8")) == []
