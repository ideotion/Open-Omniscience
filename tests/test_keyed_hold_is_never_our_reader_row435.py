"""
Row 435: the R826 "never named" test and row 310's sweep tests failed under xdist for a reason none of them made.

A ``sqlite3.connect`` that raises never reports its handle, so ``src.database.connect`` counts it as an open in flight for
``_AUDIT_STALE_S`` (60 s), and no reader sweep of that minute closes a parked ``store_reader`` descriptor. Many erase, copy and staging
tests make such an open on purpose. The next tests on the same worker then saw a reader descriptor outlive its close: the sweep tests
found it still open, and ``record_segment``'s own header read left one on the segment, so ``connect.opened_with_key`` answered True
after the keyed connection had closed.

That answer is sound in the product (R819): any descriptor of this process on the file keeps its inode from being handed to another
file, so the file at that identity is still the very one read under the key. No product path names a segment that was not read under
the key. The fix is the test isolation: ``tests/conftest.py::_no_failed_open_held_over`` clears the pending opens after each test.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from src.database import at_rest_state, connect
from tests.test_segment_record_r826 import _encrypted, _main, _stores, data  # noqa: F401 - the fixture

pytestmark = [
    pytest.mark.skipif(os.name != "posix", reason="descriptor listing (POSIX); Windows answers by the pool's disposal"),
    pytest.mark.skipif(not connect.have_driver(), reason="sqlcipher3 not installed"),
]


def _a_failed_open(tmp_path) -> None:
    with pytest.raises(sqlite3.OperationalError):
        sqlite3.connect(tmp_path / "no such folder" / "x.db")  # never reports its handle: sweeps are held off for a minute


def test_no_failed_open_is_held_over_from_an_earlier_test():
    with connect._hdr_lock:
        assert not connect._audit_pending, "conftest's _no_failed_open_held_over clears what an earlier test left"


def test_a_parked_reader_descriptor_pins_the_very_file_read_under_the_key(data, tmp_path):  # noqa: F811
    """The case the held-over open produced: the answer is True, and it is sound, because the descriptor pins that inode."""
    _a_failed_open(tmp_path)
    seg = data / "corpus" / "seg-3.db"
    _encrypted(seg).close()
    st = os.stat(seg)
    ident = (st.st_dev, st.st_ino)
    with connect.store_reader(seg) as fd:
        connect.read_at(fd, 16, 0)
    with connect._hdr_lock:
        parked = list(connect._hdr_fds.get(ident, ()))
    assert parked, "the reader's descriptor is parked (the sweep is held off): the case under test"
    held = os.fstat(parked[0])
    assert (held.st_dev, held.st_ino) == ident and held.st_nlink == 1
    assert connect.opened_with_key(ident) is True


def test_with_no_open_held_off_a_closed_segment_is_never_named(data):  # noqa: F811
    seg = data / "corpus" / "seg-4.db"
    _encrypted(seg).close()
    assert at_rest_state.record_segment(seg, main=_main(data)) is False
    assert not _stores(data)
