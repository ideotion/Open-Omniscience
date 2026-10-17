"""How often an encrypted file is opened with its key, per collection pass: the line that tells where the key derivations go.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Opening an encrypted file derives its key (PBKDF2-HMAC-SHA512 x 256,000: 163 ms of thread CPU, median, measured on one
core) and nothing keeps the result. A field bundle showed one collector thread spending 41 CPU-seconds a minute with the
derivation as its sampled frame, and no number anywhere said how many opens that was, from which thread, on which file.
``src/database/open_stats.py`` counts them; ``connect._connect`` calls it around every keyed attempt on an existing
encrypted file; the collection monitor writes the window into the pass's summary line (``encrypted_opens``) and the
scheduler into the run report.

The clocks are fakes the tests drive, so every number is exact and nothing sleeps. Each test fails when the thing it guards
goes: an attempt not counted (a failed one, or one of several page sizes), plaintext or new files counted, the window not
reset, a path or a thread name or the key or an exception's words reaching the record, a total that stops being exact when
the rows are capped, a zero where nothing was measured, a fault in the statistic reaching an open, the block missing from
the summary line or the run report.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from pathlib import Path

import pytest

from src.database import connect, open_stats
from src.monitoring.collect_perf import CollectionMonitor, recent_samples
from src.scheduler.bandwidth import BandwidthGovernor

_ROOT = Path(__file__).resolve().parents[1]


class _Clocks:
    """Wall and CPU clocks the test moves by hand. Per thread, like the real CPU clock, so opens on a pool's threads do not
    move each other's figures."""

    def __init__(self) -> None:
        self._local = threading.local()

    @property
    def wall(self) -> float:
        return getattr(self._local, "wall", 0.0)

    @wall.setter
    def wall(self, value: float) -> None:
        self._local.wall = value

    @property
    def cpu(self) -> float:
        return getattr(self._local, "cpu", 0.0)

    @cpu.setter
    def cpu(self, value: float) -> None:
        self._local.cpu = value


@pytest.fixture
def clocks(monkeypatch):
    fake = _Clocks()
    monkeypatch.setattr(open_stats, "now", lambda: fake.wall)
    monkeypatch.setattr(open_stats, "cpu_now", lambda: fake.cpu)
    open_stats.reset()
    yield fake
    open_stats.reset()


def _open(clocks: _Clocks, path: str, *, ok: bool = True, cpu: float = 0.16, wall: float = 0.17) -> None:
    started = open_stats.begin()
    clocks.cpu += cpu
    clocks.wall += wall
    open_stats.end(started, path, ok)


def test_an_empty_window_says_only_that_no_open_happened(clocks):
    assert open_stats.snapshot() == {"opens": 0}


def test_an_open_is_counted_with_its_cpu_and_its_wall_time(clocks):
    _open(clocks, "/data/custody_log.db", cpu=0.16, wall=0.5)
    snap = open_stats.snapshot()
    assert (snap["opens"], snap["failed"]) == (1, 0)
    assert snap["cpu_s"] == 0.16 and snap["wall_s"] == 0.5 and snap["wall_max_s"] == 0.5
    assert snap["by"] == [
        {
            "file": "custody_log.db",
            "thread": open_stats.thread_family(threading.current_thread().name),
            "opens": 1,
            "failed": 0,
            "cpu_s": 0.16,
            "wall_s": 0.5,
            "wall_max_s": 0.5,
        }
    ]
    assert snap["method"] == open_stats.METHOD


def test_the_totals_add_up_and_the_longest_open_is_kept(clocks):
    for wall in (0.1, 0.9, 0.3):
        _open(clocks, "/data/open_omniscience.db", cpu=0.15, wall=wall)
    snap = open_stats.snapshot()
    assert snap["opens"] == 3 and snap["cpu_s"] == 0.45
    assert snap["wall_s"] == 1.3 and snap["wall_max_s"] == 0.9


def test_a_failed_attempt_is_counted_too_it_paid_the_derivation(clocks):
    _open(clocks, "/data/wiki.db", ok=False, cpu=0.16)
    _open(clocks, "/data/wiki.db", ok=True, cpu=0.16)
    snap = open_stats.snapshot()
    assert snap["opens"] == 2 and snap["failed"] == 1 and snap["cpu_s"] == 0.32
    assert snap["by"][0]["failed"] == 1


def test_the_cpu_that_could_not_be_measured_is_said_not_counted_as_zero(clocks, monkeypatch):
    _open(clocks, "/data/wiki.db", cpu=0.2)

    def no_thread_clock():
        raise OSError("no per-thread clock here")

    monkeypatch.setattr(open_stats, "cpu_now", no_thread_clock)
    started = open_stats.begin()
    clocks.wall += 0.4
    open_stats.end(started, "/data/wiki.db", True)
    snap = open_stats.snapshot()
    assert snap["opens"] == 2 and snap["cpu_unmeasured"] == 1
    assert snap["cpu_s"] == 0.2, "the sum is of the opens that could be measured, and the count of the rest is beside it"


def test_with_no_cpu_measured_at_all_the_figure_is_absent_not_zero(clocks, monkeypatch):
    def no_thread_clock():
        raise OSError("no per-thread clock here")

    monkeypatch.setattr(open_stats, "cpu_now", no_thread_clock)
    started = open_stats.begin()
    clocks.wall += 0.4
    open_stats.end(started, "/data/wiki.db", True)
    snap = open_stats.snapshot()
    assert snap["opens"] == 1 and snap["cpu_unmeasured"] == 1
    assert "cpu_s" not in snap and "cpu_s" not in snap["by"][0], "a zero would read as 'the opens were free'"


def test_reset_starts_a_new_window(clocks):
    _open(clocks, "/data/wiki.db")
    open_stats.reset()
    assert open_stats.snapshot() == {"opens": 0}
    _open(clocks, "/data/law.db")
    assert open_stats.snapshot()["opens"] == 1


def test_a_failing_clock_loses_the_open_from_the_statistic_never_the_open(clocks, monkeypatch):
    def broken():
        raise RuntimeError("clock is broken")

    monkeypatch.setattr(open_stats, "now", broken)
    assert open_stats.begin() is None, "an open whose start could not be taken goes uncounted"
    open_stats.end(None, "/data/wiki.db", True)  # nothing to add, and no raise
    started = (0.0, 0.0)
    open_stats.end(started, "/data/wiki.db", True)  # the end clock fails: swallowed
    assert open_stats.snapshot() == {"opens": 0}


def test_a_fault_while_adding_never_reaches_the_caller(clocks, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("secret words that must not reach the open")

    monkeypatch.setattr(open_stats, "_add", boom)
    started = open_stats.begin()
    open_stats.end(started, "/data/wiki.db", True)  # no raise


def test_a_snapshot_that_fails_says_the_class_not_the_words(clocks, monkeypatch):
    def boom():
        raise RuntimeError("secret words that must not reach the record")

    monkeypatch.setattr(open_stats, "snapshot", boom)
    out = open_stats.safe_snapshot()
    assert out == {"unavailable": "RuntimeError"} and "secret" not in json.dumps(out)


# --------------------------------------------------------------------------- #
# The two closed vocabularies: nothing a person or a request typed reaches the record.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", open_stats.KNOWN_FILES)
@pytest.mark.parametrize("prefix", ["", "/home/user/data/", "C:\\Users\\someone\\AppData\\data\\", "rel/dir/"])
def test_the_app_s_own_database_files_are_named(name, prefix):
    assert open_stats.file_label(prefix + name) == name


@pytest.mark.parametrize(
    "path",
    [
        "/restore/my-secret-case-notes-2026.db",
        "C:\\Users\\someone\\Documents\\caseXYZ.db",
        "/data/custody_log.db.bak",
        "/data/custody_log.db/../hunter2.db",
        "",
        "custody_log.dbx",
    ],
)
def test_any_other_file_is_other_and_its_name_is_not_printed(path):
    assert open_stats.file_label(path) == open_stats.OTHER


def test_a_path_that_cannot_be_read_is_other():
    class Hostile:
        def __str__(self):
            raise RuntimeError("secret words")

    assert open_stats.file_label(Hostile()) == open_stats.OTHER


@pytest.mark.parametrize(
    ("name", "family"),
    [
        ("oo-collect_22", "oo-collect"),
        ("oo-collect_0", "oo-collect"),
        ("oo-osm-fr", "oo-osm"),
        ("oo-osm-planted-request-key-hunter2", "oo-osm"),
        ("oo-dump-enwiki", "oo-dump"),
        ("oo-scheduler", "oo-scheduler"),
        ("MainThread", "MainThread"),
        ("anyio-worker-3", "anyio"),
        ("ThreadPoolExecutor-0_1", "ThreadPoolExecutor"),
        ("rollup-build", "rollup-build"),
        ("served-cache-planted-key", "served-cache"),
        ("Thread-7 (run)", open_stats.OTHER),
        ("planted-request-text", open_stats.OTHER),
        ("oo-Capital", open_stats.OTHER),
        ("oo-", open_stats.OTHER),
        ("", open_stats.OTHER),
    ],
)
def test_a_thread_is_named_by_its_family_and_a_requests_text_is_dropped(name, family):
    assert open_stats.thread_family(name) == family


def test_a_thread_name_that_cannot_be_read_is_other():
    class Hostile:
        def __str__(self):
            raise RuntimeError("secret words")

    assert open_stats.thread_family(Hostile()) == open_stats.OTHER


def test_no_thread_of_the_app_is_named_straight_from_a_request():
    """A name that is ``oo-`` and then a variable keeps that variable's letters as the family. Every app thread starts
    with a fixed word (``oo-osm-{key}``, never ``oo-{key}``)."""
    bad = []
    for path in (_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"(?:name|thread_name_prefix)\s*=\s*f?[\"']oo-\{", text):
            bad.append(f"{path.relative_to(_ROOT)}: {m.group(0)}")
    assert not bad, bad


def test_the_record_holds_numbers_and_the_two_vocabularies_only(clocks):
    secret = "hunter2" + secrets.token_hex(8)

    def run(thread_name, path):
        t = threading.Thread(target=lambda: _open(clocks, path), name=thread_name)
        t.start()
        t.join()

    run(f"oo-osm-{secret}", f"/restore/{secret}.db")
    run(f"planted-{secret}", f"/data/{secret}/custody_log.db")
    run("oo-collect_3", "/data/open_omniscience.db")
    text = json.dumps(open_stats.snapshot())
    assert secret not in text
    allowed_keys = {"opens", "failed", "cpu_s", "wall_s", "wall_max_s", "cpu_unmeasured", "by", "method", "file", "thread"}

    def walk(node):
        if isinstance(node, dict):
            assert set(node) <= allowed_keys, set(node) - allowed_keys
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            assert (
                node in open_stats.KNOWN_FILES
                or node in (open_stats.OTHER, open_stats.OTHERS, open_stats.METHOD)
                or open_stats.thread_family(node) == node
            ), node

    walk(json.loads(text))
    pairs = {(r["file"], r["thread"]) for r in open_stats.snapshot()["by"]}
    assert pairs == {("(other)", "oo-osm"), ("custody_log.db", "(other)"), ("open_omniscience.db", "oo-collect")}


# --------------------------------------------------------------------------- #
# The rows are capped, the totals are not.
# --------------------------------------------------------------------------- #


def test_capping_the_rows_never_changes_the_totals(clocks, monkeypatch):
    families = iter(f"oo-f{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(10_000))
    monkeypatch.setattr(open_stats, "thread_family", lambda _name: next(families))
    n = open_stats._STATE_ROWS + 20  # more distinct (file, thread) pairs than the window keeps rows for
    for i in range(n):
        _open(clocks, f"/data/{open_stats.KNOWN_FILES[i % len(open_stats.KNOWN_FILES)]}", cpu=0.1 + i / 1000, wall=0.2)
    snap = open_stats.snapshot()
    assert snap["opens"] == n, "the total counts every open, whatever the rows hold"
    assert snap["cpu_s"] == round(sum(0.1 + i / 1000 for i in range(n)), 3)
    assert len(snap["by"]) == open_stats._PRINT_ROWS + 1
    rest = snap["by"][-1]
    assert (rest["file"], rest["thread"]) == (open_stats.OTHERS, open_stats.OTHERS)
    assert sum(r["opens"] for r in snap["by"]) == n, "every open is in exactly one printed row"
    assert round(sum(r["cpu_s"] for r in snap["by"]), 3) == snap["cpu_s"]
    named = snap["by"][:-1]
    assert [r["cpu_s"] for r in named] == sorted((r["cpu_s"] for r in named), reverse=True), "most CPU first"
    assert len(open_stats._rows) <= open_stats._STATE_ROWS + 1, "the window keeps a bounded number of rows"


def test_few_rows_have_no_others_row(clocks):
    _open(clocks, "/data/wiki.db")
    _open(clocks, "/data/law.db")
    assert all(r["file"] != open_stats.OTHERS for r in open_stats.snapshot()["by"])


def test_a_worst_case_block_is_small(clocks, monkeypatch):
    families = iter(f"oo-f{chr(97 + i // 26)}{chr(97 + i % 26)}" for i in range(10_000))
    monkeypatch.setattr(open_stats, "thread_family", lambda _name: next(families))
    for i in range(open_stats._STATE_ROWS * 2):
        _open(clocks, f"/data/{open_stats.KNOWN_FILES[i % len(open_stats.KNOWN_FILES)]}", cpu=123.456, wall=1234.5678)
    size = len(json.dumps(open_stats.snapshot()))
    assert size < 2500, size  # measured 2.1 KB; the 30 run reports of a debug bundle add under 75 KB


# --------------------------------------------------------------------------- #
# The wiring in connect: every keyed attempt on an existing encrypted file, nothing else.
# --------------------------------------------------------------------------- #

@pytest.fixture
def driver():
    pytest.importorskip("sqlcipher3")


def _make_encrypted(path: Path, key: str) -> None:
    conn = connect.connect(path, key=key)
    try:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.commit()
    finally:
        conn.close()


def test_creating_a_file_and_opening_plaintext_are_not_counted(driver, tmp_path, monkeypatch):
    open_stats.reset()
    key = secrets.token_hex(16)
    _make_encrypted(tmp_path / "a.db", key)  # a new encrypted file
    plain = connect.connect(tmp_path / "b.db", create_encrypted=False)  # a new plaintext one
    plain.execute("CREATE TABLE t (x INTEGER)")
    plain.commit()
    plain.close()
    connect.connect(tmp_path / "b.db").close()  # an existing plaintext one
    assert open_stats.snapshot() == {"opens": 0}


def test_reopening_an_encrypted_file_is_one_attempt_per_page_size_tried(driver, tmp_path):
    key = secrets.token_hex(16)
    path = tmp_path / "custody_log.db"
    _make_encrypted(path, key)
    open_stats.reset()
    connect.connect(path, key=key, cipher_page_size=16384).close()
    snap = open_stats.snapshot()
    assert snap["opens"] == 1 and snap["failed"] == 0
    assert snap["by"][0]["file"] == "custody_log.db"
    assert snap["cpu_s"] > 0.01, "the derivation is the cost counted: tens of milliseconds at the very least"


def test_a_wrong_key_is_counted_as_a_failed_attempt_and_the_key_is_not_in_the_record(driver, tmp_path):
    key = secrets.token_hex(16)
    wrong = secrets.token_hex(16)
    path = tmp_path / "wiki.db"
    _make_encrypted(path, key)
    open_stats.reset()
    with pytest.raises(connect.WrongPassphraseError):
        connect.connect(path, key=wrong, cipher_page_size=16384)
    snap = open_stats.snapshot()
    assert snap["opens"] == 1 and snap["failed"] == 1
    text = json.dumps(snap)
    assert key not in text and wrong not in text and str(tmp_path) not in text


def test_each_page_size_tried_is_an_attempt(tmp_path, monkeypatch):
    path = tmp_path / "osm.db"
    path.write_bytes(b"x" * 4096)  # any bytes that are not a plaintext header: the driver is stubbed below
    key = secrets.token_hex(16)
    monkeypatch.setattr(connect, "_last_good_page_size", {})
    monkeypatch.setattr(connect, "is_encrypted_file", lambda _p: True)
    monkeypatch.setattr(connect, "have_driver", lambda: True)
    tried: list = []

    def stub(p, use_key, check_same_thread, timeout, page_size, *, last_error=None, read_only=False):
        tried.append(page_size)
        return object() if len(tried) == 3 else None

    monkeypatch.setattr(connect, "_try_open_encrypted", stub)
    open_stats.reset()
    assert connect._connect(path, key=key) is not None
    snap = open_stats.snapshot()
    assert snap["opens"] == 3 == len(tried) and snap["failed"] == 2, "two sizes failed, the third opened it"
    assert snap["by"][0]["file"] == "osm.db"


def test_every_size_failing_counts_every_attempt_and_still_raises(tmp_path, monkeypatch):
    path = tmp_path / "x.db"
    path.write_bytes(b"x" * 4096)
    monkeypatch.setattr(connect, "_last_good_page_size", {})
    monkeypatch.setattr(connect, "is_encrypted_file", lambda _p: True)
    monkeypatch.setattr(connect, "have_driver", lambda: True)
    calls = []

    def stub(p, use_key, check_same_thread, timeout, page_size, *, last_error=None, read_only=False):
        calls.append(page_size)
        return None

    monkeypatch.setattr(connect, "_try_open_encrypted", stub)
    open_stats.reset()
    with pytest.raises(connect.WrongPassphraseError):
        connect._connect(path, key=secrets.token_hex(16))
    snap = open_stats.snapshot()
    assert snap["opens"] == len(calls) > 1 and snap["failed"] == len(calls)


def test_a_broken_statistic_never_fails_an_open(driver, tmp_path, monkeypatch):
    key = secrets.token_hex(16)
    path = tmp_path / "law.db"
    _make_encrypted(path, key)

    def boom(*a, **kw):
        raise RuntimeError("secret words")

    monkeypatch.setattr(open_stats, "now", boom)
    conn = connect.connect(path, key=key, cipher_page_size=16384)
    assert conn.execute("SELECT count(*) FROM t").fetchone() == (0,)
    conn.close()


def test_connect_calls_the_counter_around_the_attempt_and_nowhere_else():
    src = (_ROOT / "src" / "database" / "connect.py").read_text(encoding="utf-8")
    assert src.count("open_stats.begin()") == 1 and src.count("open_stats.end(") == 1
    loop = src[src.index("for candidate in candidates:") :]
    assert loop.index("open_stats.begin()") < loop.index("_try_open_encrypted(") < loop.index("open_stats.end(")


# --------------------------------------------------------------------------- #
# The pass: the monitor opens the window and writes the snapshot into its summary line.
# --------------------------------------------------------------------------- #


def _monitor():
    return CollectionMonitor(
        governor=BandwidthGovernor(mode="maximum", w_max=4),
        pass_id="open-stats-pass",
        mode="press",
        rate_fn=lambda: 100.0,
        vitals_fn=lambda: {"cpu_sys_pct": 20.0, "cpu_proc_pct": 10.0, "mem_avail_mb": 4000.0, "rss_mb": 200.0},
        writer_stats_fn=lambda: {"waiters": 0, "total_wait_s": 0.0, "peak_waiters": 0},
    )


def test_the_pass_summary_carries_the_encrypted_opens_block(clocks, monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    mon = _monitor()
    mon.start()
    try:
        _open(clocks, "/data/custody_log.db", cpu=0.166)
        _open(clocks, "/data/custody_log.db", cpu=0.166)
        mon._tick()
    finally:
        summary = mon.stop(result={"articles_stored": 2, "sources_processed": 1, "pages_fetched": 2})
    block = summary["encrypted_opens"]
    assert block["opens"] == 2 and block["cpu_s"] == 0.332
    on_disk = [r for r in recent_samples() if r.get("kind") == "summary"]
    assert on_disk and on_disk[-1]["encrypted_opens"] == block, "the block must reach collect_perf.jsonl, the file the bundle carries"


def test_the_window_opens_when_the_pass_starts_so_an_earlier_pass_does_not_leak(clocks, monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _open(clocks, "/data/custody_log.db")  # before the pass: a restore, a manual add
    mon = _monitor()
    mon.start()
    try:
        mon._tick()
    finally:
        summary = mon.stop(result=None)
    assert summary["encrypted_opens"] == {"opens": 0}


def test_a_pass_that_cannot_read_the_statistic_says_which_failure_not_a_zero(clocks, monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))

    def boom():
        raise RuntimeError("secret words that must not reach the record")

    monkeypatch.setattr(open_stats, "snapshot", boom)
    mon = _monitor()
    mon._tick()
    summary = mon._write_summary(None)
    assert summary["encrypted_opens"] == {"unavailable": "RuntimeError"}
    assert "secret words" not in json.dumps(summary)


# --------------------------------------------------------------------------- #
# The run report: the same block reaches ``scheduler_runs.jsonl``, which the debug bundle carries (its last 30 runs).
# --------------------------------------------------------------------------- #


def test_the_run_report_carries_the_encrypted_opens_block_of_its_pass(clocks, monkeypatch, tmp_path):
    from tests.test_extract_lock_stats import _run_a_pool_pass

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _open(clocks, "/data/custody_log.db", cpu=9.0)  # before the pass starts: dropped at its start
    res = _run_a_pool_pass(monkeypatch, lambda: _open(clocks, "/data/open_omniscience.db", cpu=0.16))
    block = res["encrypted_opens"]
    assert res["sources_processed"] == 5
    assert block["opens"] == 5, "the pass's five opens, not the one before it"
    assert block["cpu_s"] == 0.8


def test_a_pass_with_no_open_still_says_so_in_its_run_report(clocks, monkeypatch, tmp_path):
    from tests.test_extract_lock_stats import _run_a_pool_pass

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    res = _run_a_pool_pass(monkeypatch, lambda: None)
    assert res["encrypted_opens"] == {"opens": 0}
