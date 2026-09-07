"""C5 — the DB-10 migration mechanism, pinned as behaviour rather than prose.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``docs/design/STORAGE_5TB_PLAN.md`` and the 2026-07-18 folder-copy-parity ruling both
describe the honest DB-10 migration as a store rebuild into a fresh-pragma target, and
both name TWO mechanisms for it: ``sqlcipher_export()`` into an ATTACHed target, **or**
``VACUUM INTO`` with pragmas set. Measured 2026-09-07 on the bundled sqlcipher3
(SQLCipher 4.12.0 community / SQLite 3.51.1), only the first of those is real.

The second is not merely unsupported — on an ENCRYPTED source it **reports success and
writes a file that does not open**, which is the worst available failure mode for a
whole-corpus migration and exactly the shape a future session would reach for first
because it is the simpler call. The recorded pqcrypto lesson is why this is a test and
not a paragraph: prose addresses humans, and the next reader may not be one.

These guards therefore pin three things:

  1. the WORKING mechanism, in both directions (a legacy 4096/NONE store up-migrated to
     the ruled 16384/INCREMENTAL default, and back down again);
  2. the NEGATIVE SPACE that makes ``connect._match_source_pragmas`` necessary — an
     undeclared target takes the compiled-in default, NOT the source's pragmas — with a
     fixture whose source differs from that default, or the assertion could not tell the
     two apart (the recorded coincident-fixture trap);
  3. the REFUTATION of ``VACUUM INTO`` on an encrypted store.

Guard (3) is written to anticipate its own supersession: if a future SQLCipher makes
``VACUUM INTO`` work, it fails by name and says to revisit the plan, rather than
silently continuing to forbid something that has become correct.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database.connect import have_driver

pytestmark = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 driver unavailable")

KEY = "db10-migration-probe"


def _q(k: str) -> str:
    return k.replace("'", "''")


def _open(path: Path, key: str = KEY, page_size: int | None = None):
    from sqlcipher3 import dbapi2 as sqc

    c = sqc.connect(str(path))
    c.execute(f"PRAGMA key = '{_q(key)}'")
    if page_size is not None:
        c.execute(f"PRAGMA cipher_page_size = {int(page_size)}")
    return c


def _make_source(path: Path, page_size: int, auto_vacuum: int, rows: int = 200) -> None:
    c = _open(path, page_size=page_size)
    c.execute(f"PRAGMA auto_vacuum = {auto_vacuum}")
    c.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, body TEXT)")
    c.executemany("INSERT INTO a(body) VALUES(?)", [("x" * 400,) for _ in range(rows)])
    c.commit()
    c.close()


def _probe_open(path: Path, key: str = KEY):
    """Find the page size a store actually opens at, or None.

    SQLCipher decodes a database ONLY at the size it was created at and cannot
    discover that size from the file, so identifying a store means trying sizes —
    the same ladder ``connect()`` runs for its reopen-hazard candidate search.
    """
    for cand in (4096, 16384, 8192, 1024, 2048, 32768, 65536):
        try:
            c = _open(path, key=key, page_size=cand)
            n = int(c.execute("SELECT count(*) FROM a").fetchone()[0])
            av = int(c.execute("PRAGMA auto_vacuum").fetchone()[0])
            c.close()
            return cand, n, av
        except Exception:  # noqa: BLE001 - a wrong size is an HMAC failure, not a bug
            continue
    return None


def _export_into(src: Path, dest: Path, *, page_size: int | None, auto_vacuum: int | None, key: str = KEY) -> None:
    """The migration mechanism itself: ATTACH, DECLARE, export."""
    c = _open(src, page_size=_probe_open(src)[0])
    c.execute(f"ATTACH DATABASE ? AS mig KEY '{_q(key)}'", (str(dest),))
    if page_size is not None:
        c.execute(f"PRAGMA mig.cipher_page_size = {int(page_size)}")
    if auto_vacuum is not None:
        c.execute(f"PRAGMA mig.auto_vacuum = {int(auto_vacuum)}")
    cur = c.cursor()
    try:
        cur.execute("SELECT sqlcipher_export('mig')")
    finally:
        cur.close()
    c.execute("DETACH DATABASE mig")
    c.close()


def test_export_into_an_attached_target_honours_pragmas_that_differ_from_the_source(tmp_path):
    """C5's verify-before-build gate, in the direction a real migration runs.

    A legacy corpus (4096 / auto_vacuum=NONE — what every store created before the
    2026-07-17 and 2026-08-13 rulings actually is) rebuilt into the ruled default
    (16384 / INCREMENTAL). Both pragmas must be honoured and every row must arrive;
    this is the whole claim the migrate operation would rest on.
    """
    src = tmp_path / "legacy.db"
    _make_source(src, 4096, 0)
    assert _probe_open(src) == (4096, 200, 0)

    dest = tmp_path / "migrated.db"
    _export_into(src, dest, page_size=16384, auto_vacuum=2)
    assert _probe_open(dest) == (16384, 200, 2)


def test_the_migration_mechanism_also_runs_downward(tmp_path):
    """The reverse direction, because a migration that only goes one way is a
    one-way door — and an operator who needs to undo one has no other route."""
    src = tmp_path / "ruled.db"
    _make_source(src, 16384, 2)
    assert _probe_open(src) == (16384, 200, 2)

    dest = tmp_path / "downgraded.db"
    _export_into(src, dest, page_size=4096, auto_vacuum=0)
    assert _probe_open(dest) == (4096, 200, 0)


def test_an_undeclared_target_takes_the_compile_default_not_the_source_pragmas(tmp_path):
    """The negative space, and the reason ``_match_source_pragmas`` exists at all.

    THE FIXTURE IS THE POINT: the source is 16384/INCREMENTAL while the compiled-in
    default is 4096/NONE, so "inherited from the source" and "took the compile default"
    give DIFFERENT answers. A 4096 source could not discriminate them — the recorded
    coincident-fixture trap, which this file's first draft walked straight into.
    """
    from sqlcipher3 import dbapi2 as sqc

    probe = sqc.connect(":memory:")
    opts = [r[0] for r in probe.execute("PRAGMA compile_options").fetchall()]
    probe.close()
    assert "DEFAULT_PAGE_SIZE=4096" in opts, (
        "this guard's fixture assumes a compiled default of 4096; if the bundled "
        "sqlcipher3 changed, re-pick a source size that differs from it"
    )

    src = tmp_path / "ruled.db"
    _make_source(src, 16384, 2)

    # ANTI-VACUITY, and it is not theoretical: the mutation matrix for this file
    # rewrote the fixture to 4096/NONE and the test below still PASSED, because
    # "took the compile default" and "inherited from the source" then agree. A
    # comment would not have stopped that; this assertion does.
    src_state = _probe_open(src)
    assert src_state is not None and src_state[0] != 4096 and src_state[2] != 0, (
        "this guard is VACUOUS unless the source differs from the compile default "
        f"in both dimensions; got {src_state}"
    )

    dest = tmp_path / "bare.db"
    _export_into(src, dest, page_size=None, auto_vacuum=None)

    got = _probe_open(dest)
    assert got is not None, "the undeclared target did not open at any probed page size"
    size, rows, av = got
    assert rows == 200
    assert size == 4096, f"expected the compile default 4096, got {size} (inherited from the source?)"
    assert av == 0, f"auto_vacuum is NOT inherited either; expected 0, got {av}"


def test_vacuum_into_writes_the_COMPILE_DEFAULT_page_size_whatever_the_source_is(tmp_path):
    """REFUTATION, measured 2026-09-07 — the plan named this as a second mechanism.

    ``VACUUM INTO`` on an ENCRYPTED source writes its product at the compiled-in
    ``DEFAULT_PAGE_SIZE`` (4096) regardless of the source's real page size, and reports
    success either way. Measured across the whole ladder:

        source 1024 -> ran -> product does not open
        source 2048 -> ran -> product does not open
        source 4096 -> ran -> product opens, 200 rows, auto_vacuum preserved
        source 8192 -> ran -> product does not open
        source 16384 -> ran -> product does not open
        source 32768 -> ran -> product does not open

    So the statement is usable on exactly one page size — the one every corpus HAD
    before the 2026-08-13 ruling, and the one no corpus created since HAS. That
    coincidence is the whole reason this never surfaced. It is the same defect class
    ``_match_source_pragmas`` fixes for the ATTACH path (an undeclared target takes the
    compile default), with the worse outcome: there is no pragma that repairs it, because
    setting one poisons the connection instead (the sibling guard below).

    Verified when measured: the product is NOT a plaintext leak — no plaintext body runs,
    no table name, 261,051 of 262,144 bytes differing from the source. It is simply
    unusable, silently. The SOURCE survives, which is what makes this a trap rather than
    a catastrophe, and there is no live ``VACUUM INTO`` call site in the tree today.

    IF THIS TEST GOES RED: SQLCipher may have gained the capability. That is good news,
    not a regression — re-run the C5 probes and update ``docs/design/STORAGE_5TB_PLAN.md``
    §C5 before relying on it anywhere.
    """
    # The LIVE case: a source at the ruled default, which is what every corpus
    # created since 2026-08-13 actually is.
    ruled = tmp_path / "ruled.db"
    _make_source(ruled, 16384, 2)
    dest = tmp_path / "into_ruled.db"
    c = _open(ruled, page_size=16384)
    c.execute(f"VACUUM INTO '{dest}'")  # reports success
    c.close()
    assert dest.exists(), "VACUUM INTO wrote nothing at all"
    assert _probe_open(dest) is None, (
        "VACUUM INTO's product from a 16384 source now OPENS — SQLCipher may have gained "
        "this capability. Re-run the C5 probes and update STORAGE_5TB_PLAN.md."
    )
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(str(dest)).execute("SELECT count(*) FROM a")
    assert _probe_open(ruled) == (16384, 200, 2), "the SOURCE must survive the attempt"

    # THE DISCRIMINATING TWIN: at 4096 the very same statement works. Without it this
    # guard reads as "VACUUM INTO is broken", which is both wrong and the kind of
    # over-broad claim a later reader deletes.
    legacy = tmp_path / "legacy.db"
    _make_source(legacy, 4096, 2)
    dest2 = tmp_path / "into_legacy.db"
    c = _open(legacy, page_size=4096)
    c.execute(f"VACUUM INTO '{dest2}'")
    c.close()
    assert _probe_open(dest2) == (4096, 200, 2), (
        "the 4096 case is what made this defect invisible; if it stopped working the "
        "mechanism changed and the finding above needs re-measuring"
    )


def test_setting_a_page_size_pragma_before_vacuum_into_poisons_the_connection(tmp_path):
    """The other half: the obvious repair for the guard above does not work either.

    Setting ``cipher_page_size`` on a live keyed connection re-configures the codec
    mid-flight, so the connection can no longer read the pages it already has and the
    next statement fails with "file is not a database" — naming the SOURCE, which reads
    as corpus corruption that has not happened. The file itself is untouched.

    The stdlib spelling ``PRAGMA page_size`` is worse: it is ACCEPTED silently and the
    failure surfaces on the following statement, so a naive migrate operation would see
    no error from the pragma at all.
    """
    src = tmp_path / "src.db"
    _make_source(src, 4096, 0)

    for pragma in ("cipher_page_size", "page_size"):
        c = _open(src, page_size=4096)
        with pytest.raises(Exception) as exc:  # noqa: PT011 - the driver class varies
            c.execute(f"PRAGMA {pragma} = 16384")
            c.execute(f"VACUUM INTO '{tmp_path / (pragma + '.db')}'")
        assert "not a database" in str(exc.value).lower(), (
            f"PRAGMA {pragma} now fails differently ({exc.value!r}) — re-run the C5 probes"
        )
        try:
            c.close()
        except Exception:  # noqa: BLE001 - the connection is already poisoned
            pass
        assert _probe_open(src) == (4096, 200, 0), (
            f"the SOURCE FILE must survive PRAGMA {pragma}; only the connection is poisoned"
        )


def test_plaintext_vacuum_into_DOES_honour_pragmas_so_the_refutation_is_scoped(tmp_path):
    """The twin, so the refutation above cannot be read as "VACUUM INTO is broken".

    On a PLAINTEXT store it works exactly as documented — which is what the retired
    page-size bench used, and why the Open-queue entry recording "EMPIRICALLY PROVEN
    in-sandbox for plaintext" is true and was never evidence about the encrypted path.
    Without this twin, a future reader could reasonably delete the encrypted guard as
    over-broad.
    """
    src = tmp_path / "plain.db"
    c = sqlite3.connect(str(src))
    c.execute("PRAGMA page_size=4096")
    c.execute("PRAGMA auto_vacuum=0")
    c.execute("CREATE TABLE a(id INTEGER PRIMARY KEY, body TEXT)")
    c.executemany("INSERT INTO a(body) VALUES(?)", [("x" * 400,) for _ in range(200)])
    c.commit()

    dest = tmp_path / "plain_into.db"
    c.execute("PRAGMA page_size=16384")
    c.execute("PRAGMA auto_vacuum=2")
    c.execute(f"VACUUM INTO '{dest}'")
    c.close()

    d = sqlite3.connect(str(dest))
    assert int(d.execute("PRAGMA page_size").fetchone()[0]) == 16384
    assert int(d.execute("PRAGMA auto_vacuum").fetchone()[0]) == 2
    assert int(d.execute("SELECT count(*) FROM a").fetchone()[0]) == 200
    d.close()
