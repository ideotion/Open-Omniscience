"""Row 323 / R793: the room check before a store is encrypted counts its write-ahead log, and the operator's encrypt has it too.

A store is encrypted by copying it twice beside itself (the plaintext snapshot, then the encrypted copy), and both copies are made
through SQLite, so both carry what ``<store>-wal`` still holds. The check before the automatic finish measured the main file alone,
and the operator's own encrypt had no check at all: a store with a large log passed (or was never asked), and the copies then ran
the drive full under the write gate. What is pinned here, on REAL stores with a log held open by a live connection:

* the ONE check (``encrypt_tool.room_refusal``) needs twice the file AND its log, read by stat only (R789: an audit hook records any
  Python open of the store's files while it runs);
* a size or the free space that cannot be read refuses (fail closed) and says which, never a guess;
* the operator's encrypt refuses the library before ANY file is made (507, fixed words naming the needed and the free space), and a
  later store refused for room stays plaintext and is named after the partial words (409), the library staying encrypted;
* the finish at unlock leaves such a store pending, through the same check;
* the page reads every sentence back into its parts (app-core.js ``ooServerText``), and the words carry no path and no key.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException

import src.api.unlock as unlock_mod
from src.database import at_rest_state, encrypt_tool
from src.database import connect as connect_mod
from src.database.connect import is_encrypted_file
from src.database.writer import write_gate
from src.versioned.lanes import all_lanes
from tests.os_scope import scope_os

_KEY = "a-long-enough-passphrase-for-row-323-Qz8"
ROOT = Path(__file__).resolve().parents[1]

_WATCH: list[str] = []
_OPENED: list[str] = []


def _audit(event: str, args: tuple) -> None:
    if _WATCH and event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        name = os.fsdecode(args[0])
        if any(name.startswith(w) for w in _WATCH):
            _OPENED.append(name)


sys.addaudithook(_audit)


@pytest.fixture(autouse=True)
def _clean_gate():
    write_gate._reset_for_tests()
    yield
    write_gate._reset_for_tests()


def _held_log(path: Path, *, log_bytes: int = 2_000_000) -> sqlite3.Connection:
    """A plaintext WAL store whose commits stay in ``-wal``: the returned connection holds it with the automatic checkpoint off."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE IF NOT EXISTS notes(x TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS t(b BLOB)")
    conn.execute("INSERT INTO notes VALUES ('saved')")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    chunk = os.urandom(50_000)
    for _ in range(log_bytes // len(chunk)):
        conn.execute("INSERT INTO t VALUES (?)", (chunk,))
        conn.commit()
    return conn


def _sizes(path: Path) -> tuple[int, int]:
    return path.stat().st_size, Path(str(path) + "-wal").stat().st_size


def _sqlite(path: Path) -> None:
    c = sqlite3.connect(str(path))
    c.execute("CREATE TABLE notes(x TEXT)")
    c.execute("INSERT INTO notes VALUES ('saved')")
    c.commit()
    c.close()


def _free(monkeypatch, value: int | Exception) -> None:
    def free(_where):
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(encrypt_tool, "_disk_free", free)


def _made_beside(folder: Path, name: str) -> list[str]:
    return sorted(
        p.name
        for p in folder.iterdir()
        if p.name.startswith("pre-encrypt-") or ".enc-" in p.name or name + ".enc" in p.name
    )


# --- the one check -----------------------------------------------------------------------------------------------------------


def test_the_check_needs_twice_the_file_and_its_log_and_reads_them_by_stat_only(
    tmp_path, monkeypatch
):
    store = tmp_path / "corpus.db"
    conn = _held_log(store)
    try:
        main, wal = _sizes(store)
        assert wal > 10 * main, (main, wal)
        # Room for two copies of the file alone (the old measure), not of the file and its log: refused, in words.
        _free(monkeypatch, 2 * (main + wal) - 1)
        assert 2 * (main + wal) - 1 > 2 * main
        _OPENED.clear()
        _WATCH.append(str(store))
        try:
            said = encrypt_tool.room_refusal("corpus", store)
        finally:
            _WATCH.clear()
        assert _OPENED == [], f"the check opened a file of the live store: {_OPENED}"
        assert said is not None and said.startswith(
            'Not enough free space to encrypt the store "Corpus": it needs about '
        )
        assert "Nothing was changed for this store." in said
        assert str(tmp_path) not in said and _KEY not in said
        # Exactly the room for both copies is enough.
        _free(monkeypatch, 2 * (main + wal))
        assert encrypt_tool.room_refusal("corpus", store) is None
    finally:
        conn.close()


def test_a_store_without_a_log_needs_twice_the_file(tmp_path, monkeypatch):
    store = tmp_path / "custody_log.db"
    _sqlite(store)
    assert not Path(str(store) + "-wal").exists()
    size = store.stat().st_size
    _free(monkeypatch, 2 * size)
    assert encrypt_tool.room_refusal("custody", store) is None
    _free(monkeypatch, 2 * size - 1)
    assert encrypt_tool.room_refusal("custody", store).startswith(
        'Not enough free space to encrypt the store "Custody log"'
    )


@pytest.mark.parametrize(
    ("which", "reason"),
    [
        ("size", "its size could not be read"),
        ("log", "the size of its write-ahead log could not be read"),
        ("free", "the free space on its drive could not be read"),
    ],
)
def test_a_size_or_the_free_space_that_cannot_be_read_refuses_and_says_which(
    tmp_path, monkeypatch, which, reason
):
    store = tmp_path / "wiki.db"
    _sqlite(store)
    Path(str(store) + "-wal").write_bytes(b"")
    _free(monkeypatch, 10**15)  # all the room in the world: only what was not read can refuse
    real_stat = os.stat
    if which == "free":
        _free(monkeypatch, PermissionError(13, "denied"))
    else:
        target = str(store) + ("-wal" if which == "log" else "")

        def stat(p, *a, **kw):
            if os.fspath(p) == target:
                raise PermissionError(13, "denied")
            return real_stat(p, *a, **kw)

        scope_os(monkeypatch, encrypt_tool, stat=stat)
    said = encrypt_tool.room_refusal("lane:wiki", store)
    assert said == encrypt_tool.ROOM_NOT_READ.format(store="Source store (wiki)", reason=reason)
    assert "denied" not in said, "the OS's own text never reaches the words"


# --- the operator's encrypt ----------------------------------------------------------------------------------------------------


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    """A data folder with every at-rest store in the clear (as tests/test_encrypt_partial_r742.py builds it)."""
    main = tmp_path / "corpus.db"
    _sqlite(main)
    _sqlite(tmp_path / "custody_log.db")
    for spec in all_lanes():
        _sqlite(tmp_path / spec.filename)
    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: main)
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)

    @contextmanager
    def window(_enc_tmp):
        yield

    monkeypatch.setattr(encrypt_tool, "_library_window", window)
    monkeypatch.setattr(encrypt_tool, "dispose_lane_engines", lambda: None)
    return main


def test_the_library_without_room_is_refused_before_any_file_is_made(stores, monkeypatch):
    conn = _held_log(stores)
    try:
        main, wal = _sizes(stores)
        _free(monkeypatch, 2 * (main + wal) - 1)
        handed: list[int] = []
        with pytest.raises(encrypt_tool.EncryptNoRoom) as refused:
            encrypt_tool.encrypt_all(_KEY, on_library_encrypted=lambda: handed.append(1))
        assert str(refused.value).startswith('Not enough free space to encrypt the store "Corpus"')
        assert handed == [], "no key is handed over: nothing was encrypted"
        assert _made_beside(stores.parent, stores.name) == [], (
            "no snapshot and no encrypted copy was started"
        )
        for _name, p in at_rest_state.stores(stores):
            assert is_encrypted_file(p) is False, p.name
    finally:
        conn.close()


def test_a_later_store_without_room_stays_plaintext_is_named_and_the_library_stays_encrypted(
    stores, monkeypatch
):
    custody = stores.parent / "custody_log.db"
    custody.unlink()
    conn = _held_log(custody)
    try:
        main_c, wal_c = _sizes(custody)
        library = stores.stat().st_size
        # Room for the library's copies and for every small store, not for the custody log's file and its log.
        need = 2 * (main_c + wal_c)
        assert need > 4 * library
        _free(monkeypatch, need - 1)
        with pytest.raises(encrypt_tool.EncryptPartial) as partial:
            encrypt_tool.encrypt_all(_KEY)
        assert partial.value.pending == ["custody"]
        assert len(partial.value.reasons) == 1
        assert partial.value.reasons[0].startswith(
            'Not enough free space to encrypt the store "Custody log"'
        )
        assert str(partial.value) == encrypt_tool.PARTIAL + " " + partial.value.reasons[0]
        assert is_encrypted_file(stores) is True, "the library already encrypted is left as it is"
        assert is_encrypted_file(custody) is False
        assert sorted(stores.parent.glob("pre-encrypt-*-custody_log.db")) == [], (
            "no snapshot was made for the refused store"
        )
        for spec in all_lanes():
            assert is_encrypted_file(stores.parent / spec.filename) is True, spec.filename
    finally:
        conn.close()


def test_the_finish_at_unlock_leaves_the_store_pending_through_the_same_check(stores, monkeypatch):
    custody = stores.parent / "custody_log.db"
    custody.unlink()
    conn = _held_log(custody)
    try:
        main_c, wal_c = _sizes(custody)
        _free(monkeypatch, 2 * (main_c + wal_c) - 1)
        with pytest.raises(encrypt_tool.EncryptPartial):
            encrypt_tool.encrypt_all(_KEY)
        called: list[str] = []
        out = at_rest_state.finish_pending(
            _KEY, stores, encrypt=lambda *a, **_kw: called.append(a[0]) or {}
        )
        assert out == {"finished": [], "still_pending": ["custody"]}
        assert called == [], "the store was not started: the check came first"
        _free(monkeypatch, 10**15)
        assert at_rest_state.finish_pending(_KEY, stores) == {
            "finished": ["custody"],
            "still_pending": [],
        }
    finally:
        conn.close()


# --- the route -------------------------------------------------------------------------------------------------------------------


@pytest.fixture()
def route(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: seen.append(p))
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-plaintext")
    return seen


def _body():
    return unlock_mod.EncryptBody(passphrase=_KEY, confirm=_KEY, consent=True)


def test_the_route_answers_507_with_the_words_when_the_library_has_no_room(route, monkeypatch):
    words = encrypt_tool.NO_ROOM.format(store="Corpus", needed="2.0 GB", free="1.0 GB")

    def refuse(_key, **_kw):
        raise encrypt_tool.EncryptNoRoom(words)

    monkeypatch.setattr(encrypt_tool, "encrypt_all", refuse)
    with pytest.raises(HTTPException) as refused:
        unlock_mod.encrypt_db(_body())
    assert refused.value.status_code == 507 and refused.value.detail == words
    assert route == [], "no key is held: nothing was encrypted"


def test_the_route_names_a_later_store_refused_for_room_after_the_partial_words(route, monkeypatch):
    why = encrypt_tool.ROOM_NOT_READ.format(
        store="Custody log", reason=encrypt_tool.ROOM_REASONS["free"]
    )

    def partial(_key, *, on_library_encrypted=None):
        on_library_encrypted()
        raise encrypt_tool.EncryptPartial(["custody"], [why])

    monkeypatch.setattr(encrypt_tool, "encrypt_all", partial)
    with pytest.raises(HTTPException) as refused:
        unlock_mod.encrypt_db(_body())
    assert (
        refused.value.status_code == 409
        and refused.value.detail == encrypt_tool.PARTIAL + " " + why
    )
    assert route == [_KEY]


# --- the page --------------------------------------------------------------------------------------------------------------------


def _locale(lang: str) -> dict:
    return json.loads(
        (ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8")
    )


def test_every_fixed_reason_and_frame_is_keyed_in_every_locale():
    keys = [
        "Not enough free space to encrypt the store “{store}”: it needs about {needed} (two copies of the store and its "
        "write-ahead log), only {free} free on its drive. Nothing was changed for this store. Free up space and press “{button}” again.",
        "The store “{store}” was not encrypted: whether its drive has the free space it needs could not be checked ({reason}). "
        "Nothing was changed for this store. Press “{button}” again once this is fixed.",
        *encrypt_tool.ROOM_REASONS.values(),
    ]
    for lang in ("en", "fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id"):
        d = _locale(lang)
        for k in keys:
            assert d.get(k), (lang, k)
            for slot in ("{store}", "{needed}", "{free}", "{reason}", "{button}"):
                assert (slot in k) == (slot in d[k]), (lang, k, slot)


def test_the_page_reads_the_sentences_back_and_knows_the_partial_words():
    backup = (ROOT / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    assert json.dumps(encrypt_tool.PARTIAL, ensure_ascii=False)[1:-1] in backup, (
        "the page's copy of the partial words is the server's"
    )
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    core = (ROOT / "src" / "static" / "app-core.js").read_text(encoding="utf-8")

    def lift(start: str, end: str) -> str:
        return core[core.index(start) : core.index(end)]

    fn_start = core.index("function ooServerText(")
    depth, i = 0, core.index("{", fn_start)
    while True:
        depth += {"{": 1, "}": -1}.get(core[i], 0)
        i += 1
        if depth == 0:
            break
    fr = _locale("fr")
    sentences = [
        encrypt_tool.NO_ROOM.format(store="Source store (wiki)", needed="3.5 GB", free="1.2 GB"),
        encrypt_tool.ROOM_NOT_READ.format(
            store="Custody log", reason=encrypt_tool.ROOM_REASONS["log"]
        ),
    ]
    script = (
        "const FR = " + json.dumps(fr, ensure_ascii=False) + ";\n"
        "globalThis.OOI18N = { t: (s) => FR[s] || s, tf: (s, v) => (FR[s] || s).replace(/\\{(\\w+)\\}/g, (m, k) => v[k] != null ? String(v[k]) : m) };\n"
        "globalThis.window = globalThis;\n"
        "function _sizeText(b) { return (b / 1073741824).toFixed(1) + ' Gio'; }\n"
        + lift("const _OO_SPACE_WHAT = {", "function ooServerText(")
        + core[fn_start:i]
        + "\n"
        "console.log(JSON.stringify(ooServerText(" + json.dumps(" ".join(sentences)) + ")));\n"
    )
    run = subprocess.run(
        ["node", "-"], input=script, capture_output=True, text=True, timeout=60, check=False
    )
    assert run.returncode == 0, run.stderr[-2000:]
    out = run.stdout
    said = json.loads(out)
    lane = fr["Source store ({kind})"].replace("{kind}", fr["Wikipedia / Wikimedia"])
    assert fr[encrypt_tool.ROOM_REASONS["log"]] in said, said
    assert "Pas assez d’espace libre pour chiffrer la base « " + lane + " »" in said, said
    assert "« " + fr["Custody log"] + " »" in said, said
    assert said.count("« " + fr["Encrypt corpus & custody log"] + " »") == 2, said
    assert "3.5 Gio" in said and "1.2 Gio" in said, said
    assert fr["the size of its write-ahead log could not be read"] in said, said
    assert "Not enough free space" not in said and "was not encrypted" not in said, said


def test_a_header_that_cannot_be_read_is_still_checked_for_room(stores, monkeypatch):
    # The first header read fails (None); a later read says plaintext. Without the check here the store would be copied unchecked.
    real = encrypt_tool.is_encrypted_file
    calls: list[int] = []

    def flaky(p):
        calls.append(1)
        return None if len(calls) == 1 else real(p)

    monkeypatch.setattr(encrypt_tool, "is_encrypted_file", flaky)
    _free(monkeypatch, 0)
    with pytest.raises(encrypt_tool.EncryptNoRoom):
        encrypt_tool.encrypt_store("corpus", stores, _KEY, main=stores, library=True)
    assert _made_beside(stores.parent, stores.name) == []


def test_a_pending_store_gone_before_the_finish_is_not_called_unreadable(stores, monkeypatch):
    _free(monkeypatch, 10**15)
    monkeypatch.setattr(
        at_rest_state,
        "status",
        lambda main=None: {
            "corpus_encrypted": True,
            "complete": False,
            "pending": ["custody"],
            "busy": [],
            "stores": [],
            "plaintext_snapshots": [],
        },
    )
    (stores.parent / "custody_log.db").unlink()
    called: list[str] = []
    out = at_rest_state.finish_pending(
        _KEY, stores, encrypt=lambda *a, **_kw: called.append(a[0]) or {}
    )
    assert called == ["custody"], (
        "the check did not stand in for the store's own skip of an absent file"
    )
    assert out == {"finished": ["custody"], "still_pending": []}
