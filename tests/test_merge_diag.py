"""The merge diagnostic answers where a merge's time and memory went.

It exists because four hypotheses about a 22-hour import died in one session,
each reasoned from an artifact rather than measured on the shipped engine, and
because the file that held the answer was 1.6 GB -- too large to send, and the
very thing that had stopped the app booting.

The load-bearing test here is the ATTRIBUTION one. Writing this by hand the
first time, the fixture advanced its clock BEFORE stamping each record, which is
backwards from how ``milestone()`` works -- and the analysis then blamed the
statements that FOLLOWED the slow one. It looked plausible. Had it not been
tested against a fixture whose answer was known in advance, it would have named
the wrong culprit in a real investigation, with numbers to back it up.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

import pytest

from src.monitoring import merge_diag


def _journal(path, *, slow_label: str, slow_s: float, slow_n: int, noise_n: int) -> None:
    """A pre-2026-08-06 journal: one record per statement, stamped as it BEGINS.

    The ordering is the point. ``milestone("merge_statement_begin")`` fires when a
    statement starts, so ``el_s`` is the clock at its START and its duration is
    the NEXT record's el_s minus its own.
    """
    el = 0.0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ev": "run_begin", "kind": "import", "t": "T0"}) + "\n")
        for i in range(slow_n + noise_n):
            slow = i % (1 + noise_n // max(slow_n, 1)) == 0 and slow_n > 0
            lab = slow_label if slow else f"SELECT {i % 5} FROM x"
            fh.write(json.dumps({
                "ev": "merge_statement_begin", "t": "T", "el_s": round(el, 3),
                "step": 3, "label": "articles", "sql": lab,
            }) + "\n")
            el += slow_s if slow else 0.01


def _beats(path, *, rows: list[tuple[str, float]]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for i, (sql, sql_s) in enumerate(rows):
            rec = {"t": "T", "el_s": float(i * 15)}
            if sql:
                rec["sql"], rec["sql_s"] = sql, sql_s
            fh.write(json.dumps(rec) + "\n")


# --------------------------------------------------------------------------- #
#  exact attribution
# --------------------------------------------------------------------------- #
def test_time_is_attributed_to_the_statement_that_actually_spent_it(tmp_path) -> None:
    """THE test. A slow statement among fast ones must be the one named.

    Mutation check: attributing ``el[this] - el[prev]`` to THIS label instead of
    the previous one -- the off-by-one that a plausible-looking fixture hid --
    moves the whole 600 s onto the noise statements and fails here.
    """
    p = tmp_path / "imp-old.jsonl"
    _journal(p, slow_label="INSERT INTO articles ... SELECT", slow_s=6.0, slow_n=100, noise_n=900)

    out = merge_diag._attribute(p)
    top = out["statements_by_time"][0]
    assert top["sql"] == "INSERT INTO articles ... SELECT", out["statements_by_time"][:3]
    assert 550 <= top["seconds"] <= 650, top          # 100 x 6 s
    assert top["n"] == 100
    assert 5.5 <= top["avg_s"] <= 6.5


def test_a_complete_journal_says_so_and_a_truncated_one_says_what_it_covered(tmp_path) -> None:
    """A partial read must never present as a whole one.

    The head+tail bound exists because the field journal was 1.6 GB and parsing
    all of it costs ~90 s. Reporting the covered spans is what stops a bounded
    answer being read as a total one.
    """
    p = tmp_path / "imp-small.jsonl"
    _journal(p, slow_label="X", slow_s=1.0, slow_n=5, noise_n=20)
    out = merge_diag._attribute(p)
    assert out["complete"] is True
    assert out["bytes_read"] == out["file_bytes"]
    assert len(out["covered_spans_el_s"]) == 1


def test_the_gap_between_head_and_tail_is_never_charged_to_a_statement(tmp_path, monkeypatch) -> None:
    """The negative-space twin of the attribution test.

    Reading a head and a tail leaves hours of unread records between them. If the
    last head record and the first tail record were treated as consecutive, that
    entire unread span -- potentially the bulk of the run -- would be attributed
    to ONE arbitrary statement, and it would look like a smoking gun.
    """
    monkeypatch.setattr(merge_diag, "_JOURNAL_HEAD_BYTES", 4096)
    monkeypatch.setattr(merge_diag, "_JOURNAL_TAIL_BYTES", 4096)
    p = tmp_path / "imp-big.jsonl"
    _journal(p, slow_label="SLOW", slow_s=2.0, slow_n=300, noise_n=3000)
    assert p.stat().st_size > 9000, "fixture must exceed head+tail or there is no gap"

    out = merge_diag._attribute(p)
    assert out["complete"] is False
    assert len(out["covered_spans_el_s"]) == 2, out["covered_spans_el_s"]
    # The unread gap is worth hundreds of seconds; nothing may claim it.
    gap = out["covered_spans_el_s"][1][0] - out["covered_spans_el_s"][0][1]
    assert gap > 100, f"fixture did not produce a real gap ({gap}s)"
    assert all(r["seconds"] < gap for r in out["statements_by_time"]), (
        f"a statement was charged the unread gap of {gap}s: {out['statements_by_time'][:2]}"
    )


def test_a_journal_truncated_mid_line_still_reports(tmp_path) -> None:
    """A killed run leaves a partial final line -- the exact case this is for."""
    p = tmp_path / "imp-killed.jsonl"
    _journal(p, slow_label="SLOW", slow_s=3.0, slow_n=10, noise_n=40)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('{"ev":"merge_statement_begin","el_s":')
    out = merge_diag._attribute(p)
    assert out["statements_by_time"][0]["sql"] == "SLOW"


# --------------------------------------------------------------------------- #
#  sampled attribution
# --------------------------------------------------------------------------- #
def test_the_beat_names_the_statement_that_held_the_most_samples(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(merge_diag, "run_logs_dir", lambda: tmp_path, raising=False)
    monkeypatch.setattr("src.backup.runlog.run_logs_dir", lambda: tmp_path)
    _beats(tmp_path / "imp-a.beat.jsonl", rows=(
        [("BIG INSERT", 15.0 * i) for i in range(1, 41)] + [("tiny", 1.0)] * 4
    ))
    out = merge_diag.sampled_statements()
    top = out["runs"][0]["statements"][0]
    assert top["sql"] == "BIG INSERT"
    assert top["beats"] == 40
    assert top["approx_seconds"] == 600
    assert top["max_sql_s"] == 600.0, "the longest single run must survive as its own number"


def test_a_run_where_no_statement_was_ever_sampled_says_so(tmp_path, monkeypatch) -> None:
    """Honest silence, not a fabricated zero.

    "No statement appeared" has two meanings -- nothing ran, or everything ran
    faster than one 15 s sample -- and the block must not let the reader assume
    the first.
    """
    monkeypatch.setattr("src.backup.runlog.run_logs_dir", lambda: tmp_path)
    _beats(tmp_path / "imp-b.beat.jsonl", rows=[("", 0.0)] * 12)
    out = merge_diag.sampled_statements()
    run = out["runs"][0]
    assert run["beats_with_a_statement"] == 0
    assert "note" in run and "15 s" in run["note"]


def test_no_beats_at_all_is_reported_as_absence_not_as_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.backup.runlog.run_logs_dir", lambda: tmp_path)
    out = merge_diag.sampled_statements()
    assert out["runs"] == [] and "note" in out


def test_a_modern_journal_explains_why_exact_attribution_is_empty(tmp_path, monkeypatch) -> None:
    """Post-fix journals carry no per-statement records -- by design, not by fault.

    Without this note an operator reads an empty block as a broken instrument and
    goes looking for a bug that is actually the 1.6 GB fix working.
    """
    monkeypatch.setattr("src.backup.runlog.run_logs_dir", lambda: tmp_path)
    (tmp_path / "imp-new.jsonl").write_text(
        json.dumps({"ev": "run_begin", "kind": "import"}) + "\n", encoding="utf-8"
    )
    out = merge_diag.attributed_statements()
    assert out["runs"] == []
    assert "2026-08-06" in out["note"] and "sampled" in out["note"]


# --------------------------------------------------------------------------- #
#  the engine premise
# --------------------------------------------------------------------------- #
def test_the_engine_block_names_the_compile_default_not_just_the_pragma() -> None:
    """``PRAGMA temp_store`` returns 0 = "the compile default", which is not
    self-describing. Reporting only that would leave the reader exactly as
    misinformed as every plaintext probe in this repo's history was."""
    out = merge_diag.engine_facts()
    for drv in ("sqlcipher3", "sqlite3"):
        blk = out[drv]
        if "unavailable" in blk:
            continue
        assert blk["temp_store_compile_option"].startswith("TEMP_STORE=")
        assert blk["temp_store_default"] in ("always file", "file", "MEMORY", "always memory")


# --------------------------------------------------------------------------- #
#  the report as a whole
# --------------------------------------------------------------------------- #
def test_one_broken_block_never_costs_the_others(monkeypatch) -> None:
    """This report exists because an import failed and its evidence was
    unreadable. A diagnostic that is all-or-nothing reproduces that failure."""
    def boom() -> dict:
        raise RuntimeError("engine probe exploded")

    monkeypatch.setattr(merge_diag, "engine_facts", boom)
    out = merge_diag.merge_diagnostics(probe=False)
    assert out["engine"]["block_ok"] is False
    assert "engine probe exploded" in out["engine"]["error"]
    for other in ("window", "sampled", "attributed"):
        assert out[other].get("block_ok") is not False, f"{other} died with engine"


def test_the_probe_is_skippable_and_says_it_was_skipped() -> None:
    out = merge_diag.merge_diagnostics(probe=False)
    assert "skipped" in out["probe"]
    assert set(out) >= {"engine", "window", "sampled", "attributed", "probe"}


@pytest.mark.parametrize("probe", [True])
def test_the_probe_measures_a_real_per_row_cost(probe: bool) -> None:
    """The measurement that named the 5 KB/row allocation, run on THIS machine.

    Asserts only that the MEMORY arm produced a real, positive per-row number --
    not a threshold. The absolute value is corpus- and engine-dependent (2 KB
    rows measured 9.1 KB/row, 32 KB rows 48.5), so a bar here would either be
    vacuous or fail on hardware it has no business judging.
    """
    out = merge_diag.cost_probe(avg_row_bytes=1024)
    if "unavailable" in out:
        pytest.skip(f"probe could not run here: {out['unavailable']}")
    mem = out["arms"][0]
    assert mem["temp_store"] == "MEMORY", "MEMORY must run FIRST — see the block's own note"
    assert mem["rows"] > 0 and mem["seconds"] > 0
    if "rss_unavailable" in mem:
        # Windows has no resource.getrusage. The TIMING above is still real; the
        # memory half is absent and says so, which is the property under test on
        # that platform -- asserting a number here would demand a measurement the
        # platform cannot make.
        assert mem["rss"] is None
        return
    assert mem["kb_per_row"] is not None and mem["kb_per_row"] > 0, mem


def test_the_probe_leaves_nothing_behind(tmp_path, monkeypatch) -> None:
    """It writes ~50 MB under the data dir. On a machine importing a 32 GB backup
    that is nothing -- unless it accumulates, which is how a probe becomes the
    problem it was measuring."""
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    merge_diag.cost_probe(avg_row_bytes=512)
    assert not list(tmp_path.glob(merge_diag._PROBE_PREFIX + "*")), list(tmp_path.iterdir())


def test_no_module_imports_a_unix_only_stdlib_module_at_import_time() -> None:
    """A repo-wide guard, from a defect this file shipped (2026-08-06).

    ``import resource`` at module scope raises ImportError on Windows. That made
    ``src/monitoring/merge_diag.py`` uncollectable, pytest ABORTED the entire
    Windows run at collection ("3 skipped, 1 error"), and the lane whose whole
    job is catching portability problems before the blocking lanes hit them went
    blind instead. One line, and the cost was every other test on that platform.

    The two pre-existing uses in this tree are both function-local and marked
    Unix-only; that is the convention, and this is what keeps it one.
    """
    import ast
    import pathlib

    unix_only = {"resource", "fcntl", "termios", "pwd", "grp", "posix"}
    offenders: list[str] = []
    for path in pathlib.Path("src").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a file that will not parse is another test's problem
            continue
        for node in tree.body:  # TOP LEVEL only: a function-local import is the fix
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            for n in names:
                if n in unix_only:
                    offenders.append(f"{path}:{node.lineno} imports {n}")
    assert not offenders, (
        "these modules import a Unix-only stdlib module at import time, which raises "
        "ImportError on Windows and aborts collection of everything that imports them:\n  "
        + "\n  ".join(offenders)
        + "\nMove the import inside the function that needs it and degrade honestly."
    )


def test_the_bundle_member_produces_a_real_report(monkeypatch) -> None:
    """Drives the REAL member generator, not the route signature.

    ``_all_diagnostics_members`` calls the route DIRECTLY, so every ``Query()``
    default is an unresolved sentinel OBJECT -- and ``Query(True)`` is truthy, so
    omitting ``probe`` would run the benchmark by accident rather than by choice.
    That defect lives in the CALL, not the definition, which is why a signature
    check would pass over it (the ai.json regression, 2026-08-02). The bundle's
    own ``_safe()`` would then swallow the result into an error stub and every
    bundle would ship a degraded member with nothing saying so.

    ``probe=False`` here keeps the test fast; the member itself passes True.
    """
    pytest.importorskip("sqlalchemy")
    import src.api.diagnostics as d

    monkeypatch.setattr(d, "merge_diag", lambda **kw: d.JSONResponse(
        merge_diag.merge_diagnostics(probe=False) | {"_kw": sorted(kw)}
    ))
    from src.database.session import SessionLocal

    with SessionLocal() as db:
        members = dict(d._all_diagnostics_members(db))
        assert "merge-diag.json" in members, "the merge member must be in the bundle"
        resp = members["merge-diag.json"]()
    body = json.loads(bytes(resp.body))
    assert body["_kw"] == ["download", "probe"], (
        "the member must pass BOTH Query-defaulted parameters explicitly — an omitted "
        f"one arrives as a truthy sentinel, not as its default. Got {body['_kw']}"
    )
    for block in ("engine", "window", "sampled", "attributed"):
        assert block in body, body.keys()
        assert body[block].get("block_ok") is not False, body[block]


def test_a_leftover_from_a_killed_probe_is_swept_and_named(tmp_path, monkeypatch) -> None:
    """A hard kill skips the finally. The next run reclaims it and SAYS it did --
    silent cleanup of unexplained bytes is how storage goes missing."""
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    stale = tmp_path / f"{merge_diag._PROBE_PREFIX}99999"
    stale.mkdir()
    (stale / "junk.db").write_bytes(b"x" * 1024)

    out = merge_diag.cost_probe(avg_row_bytes=512)
    assert not stale.exists()
    assert stale.name in out.get("swept_leftovers", []), out.get("swept_leftovers")
