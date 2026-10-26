"""``scripts/generate_scale_corpus.py`` takes no passphrase on its command line (audit A-020's sibling, R218; the passphrase rule).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Same shape as ``tests/test_run_scale_bench_passphrases.py``: the old ``--passphrase`` flag is kept only to be refused by name (an
unknown flag would make argparse print what it could not place), an unrecognized argument is counted and never printed, and the value
comes from ``$OO_DB_PASSPHRASE`` or standard input. Nothing here generates a corpus: ``src.testing.corpus_gen`` is replaced by a recorder.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import types
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_scale_corpus.py"
CANARY = "canary-Zq91-passphrase"


@pytest.fixture()
def gen(monkeypatch, tmp_path):
    for name in ("OO_DB_PASSPHRASE", "OO_DB_PLAINTEXT"):  # set-then-delete records the original state, so main()'s own writes are undone
        monkeypatch.setenv(name, "x")
        monkeypatch.delenv(name)
    calls: list[dict] = []
    fake = types.ModuleType("src.testing.corpus_gen")

    class CorpusSpec:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    fake.CorpusSpec = CorpusSpec
    fake.generate_corpus = lambda out, spec: calls.append({"out": out, "passphrase": spec.passphrase}) or {"ok": 1}
    monkeypatch.setitem(sys.modules, "src.testing.corpus_gen", fake)
    spec = importlib.util.spec_from_file_location("generate_scale_corpus_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, calls, tmp_path / "out" / "open_omniscience.db"


def _silent(capsys, caplog) -> None:
    out = capsys.readouterr()
    assert CANARY not in out.out + out.err + caplog.text


@pytest.mark.parametrize("argv", [["--passphrase", CANARY], [f"--passphrase={CANARY}"]])
def test_a_passphrase_on_argv_is_refused_by_name_and_never_echoed(gen, capsys, caplog, argv):
    mod, calls, out = gen
    assert mod.main(["--out", str(out), "--articles", "10", *argv]) == 2
    err = capsys.readouterr().err
    assert "not accepted on the command line" in err and "OO_DB_PASSPHRASE" in err and CANARY not in err
    assert calls == [], "a corpus was generated with a passphrase that had just been refused"
    _silent(capsys, caplog)


@pytest.mark.parametrize("flag", ["--passphr", "--pass", "--db-passphrase", "--passphrase-file"])
def test_an_unknown_or_abbreviated_flag_is_refused_without_printing_its_value(gen, capsys, caplog, flag):
    mod, calls, out = gen
    try:
        rc = mod.main(["--out", str(out), "--articles", "10", flag, CANARY])
    except SystemExit as exc:  # argparse's own ambiguous-option error (prints option names only)
        rc = exc.code
    assert rc == 2 and calls == []
    _silent(capsys, caplog)


def test_the_old_flag_is_hidden_from_help_and_the_new_one_is_listed(gen):
    import argparse

    mod, _, _ = gen
    by_flag = {o: act for act in mod.build_parser()._actions for o in act.option_strings}
    assert by_flag["--passphrase"].help == argparse.SUPPRESS
    assert "OO_DB_PASSPHRASE" in by_flag["--passphrase-stdin"].help


def test_the_environment_supplies_the_passphrase(gen, monkeypatch, capsys, caplog):
    mod, calls, out = gen
    monkeypatch.setenv("OO_DB_PASSPHRASE", CANARY)
    assert mod.main(["--out", str(out), "--articles", "10"]) == 0
    assert calls[0]["passphrase"] == CANARY
    assert "encrypted" in capsys.readouterr().err
    _silent(capsys, caplog)


def test_standard_input_supplies_the_passphrase(gen, monkeypatch, capsys, caplog):
    mod, calls, out = gen
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{CANARY}\n"))
    assert mod.main(["--out", str(out), "--articles", "10", "--passphrase-stdin"]) == 0
    assert calls[0]["passphrase"] == CANARY
    _silent(capsys, caplog)


def test_with_no_passphrase_the_corpus_is_plaintext_and_says_so(gen, capsys):
    mod, calls, out = gen
    assert mod.main(["--out", str(out), "--articles", "10"]) == 0
    assert calls[0]["passphrase"] is None
    assert "plaintext" in capsys.readouterr().err


def test_an_empty_standard_input_line_is_no_passphrase(gen, monkeypatch):
    mod, calls, out = gen
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))
    assert mod.main(["--out", str(out), "--articles", "10", "--passphrase-stdin"]) == 0
    assert calls[0]["passphrase"] is None


def test_the_script_source_no_longer_reads_an_argv_passphrase_into_the_spec():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "passphrase=args.passphrase" not in text
