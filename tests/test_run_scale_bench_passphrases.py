"""``scripts/run_scale_bench.py`` takes no passphrase on its command line (audit A-020, the passphrase rule).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The arguments of a process are readable by every user of the machine (``ps``), land in shell history and in CI logs, and the script
used to copy the corpus passphrase from argv into the environment. The two old flags are kept only to be refused BY NAME (an unknown
flag would make argparse print what it could not place); the values now come from named environment variables or standard input.
Nothing here runs the benchmark: ``src.testing.scale_bench`` is replaced by a recorder.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import types
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_scale_bench.py"
CANARY = "canary-Zq81-passphrase"
OTHER = "other-Zq82-passphrase"

_ENV = (
    "OO_DATA_DIR", "OO_NO_SCHEDULER", "OO_AUTOSEED", "OO_FIELD_TEST", "OO_DB_PASSPHRASE", "OO_DB_PLAINTEXT",
    "OO_BENCH_BACKUP_PASSPHRASE",
)


@pytest.fixture()
def bench(monkeypatch, tmp_path):
    for name in _ENV:  # set-then-delete records the original state, so main()'s own writes are undone at teardown
        monkeypatch.setenv(name, "x")
        monkeypatch.delenv(name)
    calls: list[dict] = []
    fake = types.ModuleType("src.testing.scale_bench")
    fake.ALL_PHASES = ["unlock", "endpoints", "backup", "restore", "wal"]
    fake.run_full = lambda corpus_dir, **kw: calls.append(dict(kw, corpus_dir=corpus_dir)) or {"ok": 1}
    fake.acceptance_gate = lambda report, **kw: {"ok": True, "failures": []}
    monkeypatch.setitem(sys.modules, "src.testing.scale_bench", fake)
    spec = importlib.util.spec_from_file_location("run_scale_bench_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def corpus(encrypted: bool) -> Path:
        d = tmp_path / ("enc" if encrypted else "plain")
        d.mkdir()
        (d / "open_omniscience.db").write_bytes((b"\x17" * 16 if encrypted else b"SQLite format 3\x00") + b"\x00" * 64)
        return d

    return mod, calls, corpus


def _no_canary(capsys, caplog) -> None:
    out = capsys.readouterr()
    assert CANARY not in out.out + out.err + caplog.text
    assert OTHER not in out.out + out.err + caplog.text


@pytest.mark.parametrize(
    "argv",
    [
        ["--corpus-passphrase", CANARY],
        [f"--corpus-passphrase={CANARY}"],
        ["--backup-passphrase", CANARY],
        [f"--backup-passphrase={CANARY}", "--corpus-passphrase", OTHER],
    ],
)
def test_a_passphrase_on_argv_is_refused_by_name_and_never_echoed(bench, capsys, caplog, argv):
    mod, calls, corpus = bench
    rc = mod.main(["--corpus", str(corpus(True)), *argv])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not accepted on the command line" in err and "OO_BENCH_BACKUP_PASSPHRASE" in err and "OO_DB_PASSPHRASE" in err
    assert CANARY not in err and OTHER not in err
    assert calls == [], "the benchmark ran with a passphrase it had just refused"
    _no_canary(capsys, caplog)


@pytest.mark.parametrize("flag", ["--corpus-passphr", "--passphrase", "--db-passphrase", "--backup-pass"])
def test_an_unknown_or_abbreviated_flag_is_refused_without_printing_its_value(bench, capsys, caplog, flag):
    mod, calls, corpus = bench
    try:
        rc = mod.main(["--corpus", str(corpus(True)), flag, CANARY])
    except SystemExit as exc:  # argparse's own ambiguous-option error (prints option names only)
        rc = exc.code
    assert rc == 2
    assert calls == []
    _no_canary(capsys, caplog)


def test_the_old_flags_are_hidden_from_help_and_the_new_ones_are_listed(bench):
    import argparse

    mod, _, _ = bench
    by_flag = {o: act for act in mod.build_parser()._actions for o in act.option_strings}
    assert by_flag["--corpus-passphrase"].help == argparse.SUPPRESS and by_flag["--backup-passphrase"].help == argparse.SUPPRESS
    assert "OO_DB_PASSPHRASE" in by_flag["--corpus-passphrase-stdin"].help
    assert "OO_BENCH_BACKUP_PASSPHRASE" in by_flag["--backup-passphrase-stdin"].help


def test_the_environment_supplies_both_passphrases(bench, monkeypatch, capsys, caplog):
    mod, calls, corpus = bench
    monkeypatch.setenv("OO_DB_PASSPHRASE", CANARY)
    monkeypatch.setenv("OO_BENCH_BACKUP_PASSPHRASE", OTHER)
    assert mod.main(["--corpus", str(corpus(True)), "--phases", "backup"]) == 0
    assert calls[0]["corpus_passphrase"] == CANARY and calls[0]["backup_passphrase"] == OTHER
    out = capsys.readouterr()
    assert CANARY not in out.out + out.err and OTHER not in out.out + out.err
    assert CANARY not in caplog.text


def test_standard_input_supplies_the_corpus_line_first_then_the_backup_line(bench, monkeypatch, capsys, caplog):
    mod, calls, corpus = bench
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{CANARY}\n{OTHER}\n"))
    assert mod.main(["--corpus", str(corpus(True)), "--phases", "backup", "--corpus-passphrase-stdin", "--backup-passphrase-stdin"]) == 0
    assert calls[0]["corpus_passphrase"] == CANARY and calls[0]["backup_passphrase"] == OTHER
    out = capsys.readouterr()
    assert CANARY not in out.out + out.err + caplog.text and OTHER not in out.out + out.err + caplog.text


def test_standard_input_for_the_backup_alone(bench, monkeypatch):
    mod, calls, corpus = bench
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{OTHER}\n"))
    assert mod.main(["--corpus", str(corpus(False)), "--phases", "backup", "--backup-passphrase-stdin"]) == 0
    assert calls[0]["backup_passphrase"] == OTHER and calls[0]["corpus_passphrase"] is None


def test_an_encrypted_corpus_with_no_passphrase_is_refused_naming_the_variable(bench, capsys):
    mod, calls, corpus = bench
    assert mod.main(["--corpus", str(corpus(True)), "--phases", "unlock"]) == 2
    assert "OO_DB_PASSPHRASE" in capsys.readouterr().err
    assert calls == []


def test_the_backup_phases_with_no_passphrase_are_refused_naming_the_variable(bench, capsys):
    mod, calls, corpus = bench
    assert mod.main(["--corpus", str(corpus(False)), "--phases", "backup"]) == 2
    assert "OO_BENCH_BACKUP_PASSPHRASE" in capsys.readouterr().err
    assert calls == []


def test_an_empty_stdin_line_is_no_passphrase(bench, monkeypatch, capsys):
    mod, calls, corpus = bench
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
    assert mod.main(["--corpus", str(corpus(True)), "--phases", "unlock", "--corpus-passphrase-stdin"]) == 2
    assert calls == []


def test_the_script_source_no_longer_copies_an_argv_value_into_the_environment():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert 'os.environ["OO_DB_PASSPHRASE"] = args' not in text
    assert "= args.corpus_passphrase\n" not in text and "=args.corpus_passphrase\n" not in text
