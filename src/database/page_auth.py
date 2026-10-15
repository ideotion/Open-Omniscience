"""The app's own check of SQLCipher 4's page authentication tags, for a file the engine's pragma cannot read (R134).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY IT EXISTS. ``PRAGMA cipher_integrity_check`` is the one thing that NAMES a page that fails its authentication tag, and its
offsets wrap at 2^32 bytes: on a HEALTHY 4.52 GB store it answered "HMAC verification failed" for every page from 262,145 on
(``verify.PAGE_PASS_LIMIT_BYTES``). The engine has no per-page read through SQL either (``sqlite_dbpage`` is not compiled into
``sqlcipher3`` 0.6.2). So a damaged page on a corpus longer than 4 GiB was never named. This module reads the main file itself and
checks each page's tag from the app's side, for such a file only (``verify._page_pass`` keeps the engine's pragma, measured, up to
2^32 bytes).

THE TAG (SQLCipher 4, measured against the pragma on a clean store and on six corrupted copies: the same page numbers every time).
A page is ``[ciphertext][IV 16][HMAC-SHA512 tag 64]`` (a reserve of 80 bytes); page 1 opens with the 16-byte salt. The tag is
``HMAC-SHA512(hmac_key, page[start : page_size - 64] + page number as 4 bytes, little endian)`` with ``start`` 16 on page 1 and 0
elsewhere; ``enc_key = PBKDF2-HMAC-SHA512(passphrase as UTF-8, salt = the file's first 16 bytes, 256,000 rounds, 32 bytes)`` and
``hmac_key = PBKDF2-HMAC-SHA512(enc_key, salt with every byte xor 0x3A, 2 rounds, 32 bytes)``. A page of ALL ZEROS fails its tag in
the engine too (measured), so no zero page is skipped: a hole in the file is damage, as it is for the pragma. THE ONE EXCEPTION is
the page the engine does not judge either, the lock-byte page (:data:`PENDING_BYTE`: the page that holds byte 2^30, number 65,537 at
16 KiB pages), which SQLite never writes and which is a run of zeros in every healthy file longer than 1 GiB. The first draft judged it
and named it on a healthy 4.37 GB store: the small stores of the tests are all shorter than 1 GiB, so only the real run could find it.
The result and the record say which page was not judged (``lock_byte_page``).

WHAT IT CAN NEVER DO IS INVENT DAMAGE (R134 (2)). It assumes the SQLCipher 4 defaults (:func:`read_settings` refuses anything
else, ``unchecked``) and it CALIBRATES on the file before it judges a page: page 1 must pass its tag, and the pages after it (up to
:data:`CALIBRATION_PAGES`) must not ALL fail. Page 1 is a page the keyed connection has just read through the codec, so a failure
there means this module's assumptions (a setting, the key form, the page size) do not hold for this file, not that the file is
damaged: the state is ``mismatch`` and the caller files ``unchecked`` with a reason. Every failure to READ (an ``OSError``, a short
read) is counted as an unread page, never as a failing one; a stop is ``stopped``. It never raises: a failure is its class and the
NAME of its errno (``damage.failure_label``), never the engine's words or a path.

WHAT IT HOLDS, AND WHAT IT CANNOT WIPE (the passphrase rule; R134 (1)). The check needs a key that is not the engine's for the
length of one pass. It holds the DERIVED HMAC key (32 bytes, which verifies tags and decrypts nothing), never the passphrase: the
passphrase is read once from the SAME in-process holder ``connect._apply_key`` reads (``connect.get_passphrase``), turned into a
``bytearray`` that is zeroed straight after the two key derivations, with the intermediate encryption key (which does decrypt) zeroed in
the same ``finally``; the tag key lives in a ``bytearray`` that :func:`check_path` zeroes in a ``finally`` once the pass ends, on every
path. The key is never given to a thread, a logger, a record or an exception, and it never leaves this module's frames except into
``hmac``. WHAT PYTHON DOES NOT LET US WIPE, said and not hidden: the immutable ``bytes`` objects the standard library hands back
(the two PBKDF2 outputs) and the UTF-8 copy ``bytearray(str, "utf-8")`` makes on its way in cannot be zeroed from Python, and OpenSSL's
own HMAC state, which OpenSSL frees and this module neither wipes nor relies on being wiped. That is inside the threat model (CLAUDE.md): at-rest encryption protects a copied or seized
file, never a compromised running session, and a session that can read this process's freed memory can read the holder the
passphrase already sits in. What the zeroing buys is that no long-lived copy of the key is OURS to leave behind. It only VERIFIES
tags: it adds no decryption and no recovery path for a lost passphrase (CLAUDE.md: no recovery, no decryption alternative).

LIMITS, THE PRAGMA'S TOO. It reads the MAIN file only, so a page whose newest copy is in a leftover ``-wal`` is checked at its older,
valid state (or at a torn one: a page the engine was in the middle of writing can fail once, which is what the second read of R100
is for). A trailing fragment shorter than a page is reported (``trailing_bytes``) and not counted: SQLite ignores it. Measured on a
healthy 4,375,658,496-byte store with 16 KiB pages: 8.4 to 8.7 s with the file in the page cache (about 500 MB/s), 17.2 s cold (about
250 MB/s); one thread, HMAC-SHA512 is the cost, the read is sequential, 4 MiB at a time, memory one chunk.
"""
from __future__ import annotations

import hashlib
import heapq
import hmac
import os
import struct
import threading
from pathlib import Path
from typing import Any

from src.database.damage import failure_label

#: The layout of a SQLCipher 4 page: the salt that opens page 1, the IV, and the HMAC-SHA512 tag that closes every page.
SALT_BYTES = 16
IV_BYTES = 16
TAG_BYTES = 64
#: The key derivations, as SQLCipher 4 does them (see the module docstring).
KDF_ITERATIONS = 256_000
HMAC_KEY_ITERATIONS = 2
HMAC_SALT_MASK = 0x3A
KEY_BYTES = 32

#: How many bytes one read asks for. WHAT IT PROTECTS: the memory of the pass (one chunk, whatever the file) against the number of
#: system calls on a 40 GB file; a failing chunk is read page by page to find the pages that cannot be read.
CHUNK_BYTES = 4 << 20

#: How many pages AFTER page 1 take part in the calibration. WHAT IT PROTECTS: the verdict. Page 1 proves the key, the algorithm and
#: the layout; the pages after it must not all fail, which would say the method is wrong for every page that is not the first.
CALIBRATION_PAGES = 8

#: The byte SQLite keeps for its file locks (``sqlite3PendingByte``) and so the PAGE that holds it, which SQLite never reads or
#: writes: it is a run of zeros in the file and has no tag, and the engine's pragma does not judge it. MEASURED, by the real run on a
#: healthy 4.37 GB store: the first draft named page 65,537 (offset 2^30 at 16 KiB pages) as failing. The page is not judged and the
#: result says which one (:func:`lock_byte_page`); every OTHER all-zero page still fails, as it does in the engine.
PENDING_BYTE = 0x40000000

#: The page sizes SQLCipher 4 accepts (powers of two from 512 to 65,536).
PAGE_SIZES = frozenset(1 << n for n in range(9, 17))

#: What the connection must answer for the pragmas that describe how the file was written (``None``: the page size, read and
#: returned). A connection that answers something else holds a file this module has not been measured on. ``kdf_iter`` and not
#: ``cipher_kdf_iter``: the latter answers nothing in ``sqlcipher3`` 0.6.2. An answer that is MISSING is not a mismatch (the
#: calibration decides); an answer that differs is.
EXPECTED_SETTINGS = (
    ("cipher_kdf_algorithm", "pbkdf2_hmac_sha512"),
    ("cipher_hmac_algorithm", "hmac_sha512"),
    ("kdf_iter", str(KDF_ITERATIONS)),
    ("cipher_use_hmac", "1"),
    ("cipher_plaintext_header_size", "0"),
    ("cipher_hmac_salt_mask", "3a"),
    ("cipher_hmac_pgno", "le"),
)

STATE_CHECKED = "checked"
STATE_MISMATCH = "mismatch"
STATE_STOPPED = "stopped"
STATE_UNREADABLE = "unreadable"
STATE_NO_KEY = "no-key"

#: WHICH calibration disagreed, on a ``mismatch`` result (``mismatch_on``): the file's first page failed its tag (the method does not fit
#: this file), or the first page held and every page examined after it failed (the method fits, and the caller cannot tell a run of bad
#: pages from a method that does not). Two different sentences in the record, because only one of them is about the first page.
MISMATCH_FIRST_PAGE = "first-page"
MISMATCH_LATER_PAGES = "later-pages"

#: Opens the file for the raw read (no SQLite, no key): a name tests replace with a file whose reads fail, because a drive that fails
#: to read cannot be made on demand.
_raw_open = open


def read_settings(con: Any) -> tuple[int | None, str | None]:
    """``(page_size, None)`` for a connection whose file was written with the SQLCipher 4 defaults, else ``(None, reason)``. The
    reason is fixed words. Raises whatever the connection raises (the caller classifies it as it does for any read)."""

    def answer(pragma: str) -> str | None:
        row = con.execute(f"PRAGMA {pragma}").fetchone()
        return None if not row or row[0] is None else str(row[0]).strip().lower()

    size = answer("cipher_page_size")
    if size is None or not size.isdigit() or int(size) not in PAGE_SIZES:
        return None, "the page size is not one the page check knows"
    for pragma, expected in EXPECTED_SETTINGS:
        said = answer(pragma)
        if said is not None and said != expected:
            return None, "the file's cipher settings are not the SQLCipher 4 defaults the page check knows"
    return int(size), None


def lock_byte_page(page_size: int) -> int:
    """The number (1-based) of the page that holds SQLite's lock byte: the one page of a file that is never written."""
    return PENDING_BYTE // page_size + 1


def wipe(buf: bytearray | None) -> None:
    """Zero ``buf`` in place (the same bytes, no new object). ``None`` is nothing to wipe."""
    if buf:
        buf[:] = bytes(len(buf))


def _utf8(text: str) -> bytearray | None:
    """``text`` as UTF-8 in a ``bytearray`` the caller zeroes, or ``None`` when it cannot be encoded (a lone surrogate: the engine
    refused such a key before it opened the file, ``secret_scrub.passphrase_bytes``). The refusal is made OUTSIDE the handler:
    an exception raised inside one keeps the encoding error as its context, and that carries the whole text."""
    try:
        return bytearray(text, "utf-8")
    except UnicodeEncodeError:
        pass
    return None


def derive_tag_key(salt: bytes) -> bytearray | None:
    """The HMAC key of the file whose first 16 bytes are ``salt``, in a ``bytearray`` the caller must :func:`wipe`, or ``None`` when
    this process holds no passphrase (or one that cannot be encoded). The passphrase is read from the holder the engine's key comes
    from and the reference is dropped at once; both intermediates that are ours (the passphrase bytes and the encryption key) are
    zeroed in the ``finally`` whatever happens."""
    from src.database.connect import get_passphrase

    held = get_passphrase()
    if not held:
        return None
    password = _utf8(held)
    del held
    if password is None:
        return None
    encryption_key = bytearray()
    try:
        encryption_key = bytearray(hashlib.pbkdf2_hmac("sha512", password, salt, KDF_ITERATIONS, KEY_BYTES))
        masked = bytes(b ^ HMAC_SALT_MASK for b in salt)
        return bytearray(hashlib.pbkdf2_hmac("sha512", encryption_key, masked, HMAC_KEY_ITERATIONS, KEY_BYTES))
    finally:
        wipe(password)
        wipe(encryption_key)


class _Tally:
    """What a pass found: the pages that failed (the lowest ``keep`` numbers kept, ALL of them counted: a cap shrinks what is printed,
    never what is counted), the pages it could not read, and the first failure to read (a label, never a message)."""

    __slots__ = ("examined", "failing", "first_unread", "keep", "lock_byte", "lowest", "failure", "unread")

    def __init__(self, keep: int) -> None:
        self.keep = keep
        self.examined = 0
        self.failing = 0
        self.unread = 0
        self.first_unread: int | None = None  # the lowest page number that could not be read
        self.lock_byte: int | None = None  # the lock-byte page, when the pass went over it (it is not judged)
        self.lowest: list[int] = []  # a max-heap of the lowest ``keep`` failing page numbers, negated
        self.failure: str | None = None

    def judged(self, number: int, holds: bool) -> None:
        self.examined += 1
        if holds:
            return
        self.failing += 1
        if len(self.lowest) < self.keep:
            heapq.heappush(self.lowest, -number)
        elif self.lowest and number < -self.lowest[0]:  # ``keep`` of 0 lists none and still counts every one
            heapq.heapreplace(self.lowest, -number)

    def not_read(self, exc: BaseException | None = None) -> None:
        """A read failed (the label of the first failure is kept)."""
        if exc is not None and self.failure is None:
            self.failure = failure_label(exc)

    def lost(self, number: int) -> None:
        """Page ``number`` could not be read: counted apart from the pages that failed their tag, never one of them."""
        self.unread += 1
        if self.first_unread is None or number < self.first_unread:
            self.first_unread = number

    def pages(self) -> list[int]:
        return sorted(-n for n in self.lowest)

    def merge(self, other: _Tally) -> None:
        self.examined += other.examined
        self.unread += other.unread
        self.failure = self.failure or other.failure
        self.lock_byte = self.lock_byte or other.lock_byte
        if other.first_unread is not None and (self.first_unread is None or other.first_unread < self.first_unread):
            self.first_unread = other.first_unread
        for number in other.pages():
            self.failing += 1
            if len(self.lowest) < self.keep:
                heapq.heappush(self.lowest, -number)
            elif number < -self.lowest[0]:
                heapq.heapreplace(self.lowest, -number)
        self.failing += other.failing - len(other.lowest)  # the failing pages the other did not list


def _read_at(handle: Any, offset: int, view: memoryview) -> int:
    """How many bytes of ``view`` the drive gave at ``offset``. A read that returns fewer than asked is asked again for the rest (a
    signal can cut one short) and an EMPTY answer ends it: end of file, or a page the drive would not give. A read that raises raises."""
    handle.seek(offset)
    got = 0
    while got < len(view):
        n = handle.readinto(view[got:])
        if not n:
            break
        got += n
    return got


def _tag_holds(page: memoryview, number: int, base: Any, page_size: int) -> bool:
    start = SALT_BYTES if number == 1 else 0
    end = page_size - TAG_BYTES
    mac = base.copy()
    mac.update(page[start:end])
    mac.update(struct.pack("<I", number))
    return hmac.compare_digest(mac.digest(), page[end:page_size])


def _scan(
    handle: Any, buf: bytearray, base: Any, page_size: int, first: int, last: int, tally: _Tally, cancel: threading.Event | None
) -> bool:
    """Judge pages ``first`` to ``last`` (1-based) into ``tally``. ``False`` when a stop was asked for. A chunk that cannot be read whole
    is read page by page: a page that cannot be read is counted as unread, never as failing. The lock-byte page is read past and not
    judged (:data:`PENDING_BYTE`)."""
    lock = lock_byte_page(page_size)
    view = memoryview(buf)
    per_chunk = len(buf) // page_size
    number = first
    while number <= last:
        if cancel is not None and cancel.is_set():
            return False
        count = min(per_chunk, last - number + 1)
        want = count * page_size
        try:
            whole = _read_at(handle, (number - 1) * page_size, view[:want]) >= want
        except OSError as exc:
            tally.not_read(exc)
            whole = False
        if whole:
            for i in range(count):
                if number + i == lock:
                    tally.lock_byte = lock
                    continue
                tally.judged(number + i, _tag_holds(view[i * page_size : (i + 1) * page_size], number + i, base, page_size))
        else:
            for i in range(count):
                if cancel is not None and cancel.is_set():
                    return False
                if number + i == lock:
                    tally.lock_byte = lock
                    continue
                one = view[:page_size]
                try:
                    got = _read_at(handle, (number + i - 1) * page_size, one)
                except OSError as exc:
                    tally.not_read(exc)
                    tally.lost(number + i)
                    continue
                if got < page_size:
                    tally.lost(number + i)
                else:
                    tally.judged(number + i, _tag_holds(one, number + i, base, page_size))
        number += count
    return True


def _result(
    state: str, tally: _Tally, *, file_bytes: int = 0, pages_in_file: int = 0, trailing: int = 0, failure: str | None = None, mismatch_on: str | None = None
) -> dict[str, Any]:
    return {
        "state": state,
        "mismatch_on": mismatch_on,
        "failing": tally.failing,
        "pages": tally.pages(),
        "unread": tally.unread,
        "examined": tally.examined,
        "lock_byte_page": tally.lock_byte,
        "pages_in_file": pages_in_file,
        "trailing_bytes": trailing,
        "file_bytes": file_bytes,
        "failure": failure or tally.failure,
    }


def _judge(handle: Any, size: int, page_size: int, key: bytearray, cancel: threading.Event | None, keep: int, window: tuple[int, int] | None) -> dict[str, Any]:
    pages = size // page_size
    trailing = size - pages * page_size

    def answer(state: str, held: _Tally, mismatch_on: str | None = None) -> dict[str, Any]:
        return _result(state, held, file_bytes=size, pages_in_file=pages, trailing=trailing, mismatch_on=mismatch_on)

    tally = _Tally(keep)
    if pages < 1:
        return answer(STATE_MISMATCH, tally, MISMATCH_FIRST_PAGE)  # there is no first page to match
    base = hmac.new(key, digestmod="sha512")
    buf = bytearray(max(1, CHUNK_BYTES // page_size) * page_size)
    calibration_last = min(pages, 1 + CALIBRATION_PAGES)
    calibration = _Tally(keep)
    if not _scan(handle, buf, base, page_size, 1, calibration_last, calibration, cancel):
        return answer(STATE_STOPPED, calibration)
    if calibration.first_unread == 1:
        return answer(STATE_UNREADABLE, calibration)  # page 1 could not be read: there is nothing to calibrate on
    page_one_failed = 1 in calibration.pages()
    after = calibration.examined - 1
    after_failing = calibration.failing - (1 if page_one_failed else 0)
    if page_one_failed or (after >= 2 and after_failing == after):
        return answer(STATE_MISMATCH, calibration, MISMATCH_FIRST_PAGE if page_one_failed else MISMATCH_LATER_PAGES)
    tally.merge(calibration)
    first, last = window if window is not None else (1, pages)
    first, last = max(first, calibration_last + 1), min(last, pages)
    if first <= last and not _scan(handle, buf, base, page_size, first, last, tally, cancel):
        return answer(STATE_STOPPED, tally)
    return answer(STATE_CHECKED, tally)


def check_path(
    path: Path,
    page_size: int,
    *,
    cancel: threading.Event | None = None,
    keep: int = 32,
    window: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Check every page of the main file at ``path`` against its authentication tag. Never raises. The result's ``state`` is
    ``checked`` (``failing`` is the count of pages that failed, ``pages`` the lowest ``keep`` numbers, ``unread`` the pages the drive
    would not give, ``examined`` the pages judged), ``mismatch`` (the calibration disagreed: the pass says nothing about the file; ``mismatch_on`` says which way),
    ``stopped``, ``unreadable`` (``failure`` is a class and an errno name) or ``no-key`` (this process holds no passphrase).
    ``window`` is ``(first, last)`` page numbers (1-based) to check besides the calibration pages, which are always judged; the
    default is the whole file. The key is derived here, held in a ``bytearray`` and zeroed in a ``finally`` on every path."""
    key: bytearray | None = None
    empty = _Tally(keep)
    try:
        with _raw_open(path, "rb", buffering=0) as handle:
            size = handle.seek(0, os.SEEK_END)
            salt = bytearray(SALT_BYTES)
            if _read_at(handle, 0, memoryview(salt)) < SALT_BYTES:
                return _result(STATE_UNREADABLE, empty, file_bytes=size)
            key = derive_tag_key(bytes(salt))
            if key is None:
                return _result(STATE_NO_KEY, empty, file_bytes=size)
            return _judge(handle, size, page_size, key, cancel, keep, window)
    except Exception as exc:  # noqa: BLE001 - the state IS the exception's class and errno name, nothing of its text
        return _result(STATE_UNREADABLE, empty, failure=failure_label(exc))
    finally:
        wipe(key)
