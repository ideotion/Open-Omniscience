"""Row 111: a job's passphrase is HELD while the job runs, so a third-party logger's record is scrubbed of it too.

#2059's run 43987377156 failed ``test_export_job``'s passphrase test on timing, and the cause was real: SQLAlchemy's pool logged
"Exception during reset" with ``exc_info``, and that exception's ``__context__`` was the backup's failure, whose text quoted the
backup passphrase. The app's own records are scrubbed where they are made (``log_failure``); a library's is not ours to make, so
the net is the filter every handler holds, and it only takes out what the process HOLDS. These tests pin the three parts of the fix:
the hold itself (``secret_scrub.holding`` / ``held_during``), the job threads that enter it, and the backup and verify runs
recording their outcome outside the handler that caught the failure, so nothing written then can chain it.
"""

from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

import pytest

from src.monitoring import secret_scrub
from src.monitoring.secret_scrub import SecretFilter, held_during, held_passphrases, holding

ROOT = Path(__file__).resolve().parents[1]
_PASS = "Okapi-Lantern-5529-planted-backup-secret"


class _Written(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.setFormatter(logging.Formatter("%(name)s %(message)s"))
        self.lines: list[str] = []
        self.addFilter(SecretFilter())

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture
def written():
    handler = _Written()
    logger = logging.getLogger("sqlalchemy.pool.test_r111")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield logger, handler
    finally:
        logger.removeHandler(handler)


def _library_record_chaining(logger: logging.Logger, secret: str) -> None:
    """What SQLAlchemy's pool did: an error while the job's failure was being handled, logged with ``exc_info``."""
    try:
        raise RuntimeError(f"could not open the key {secret}")
    except RuntimeError:
        try:
            raise OSError("the connection was closed from another thread")
        except OSError:
            logger.error("Exception during reset or similar", exc_info=True)


def test_a_library_record_is_scrubbed_of_a_held_passphrase_and_only_while_it_is_held(written):
    logger, handler = written
    _library_record_chaining(logger, _PASS)
    assert any(_PASS in line for line in handler.lines), "the control: a passphrase not held passes the filter"
    handler.lines.clear()
    with holding(_PASS):
        _library_record_chaining(logger, _PASS)
    assert handler.lines and "Exception during reset" in handler.lines[0]
    assert "the connection was closed from another thread" in handler.lines[0], "the library's own words were lost"
    assert not any(_PASS in line for line in handler.lines), handler.lines


def test_holding_adds_and_takes_away_nests_and_ignores_an_empty_secret():
    before = held_passphrases() or ()
    with holding(_PASS, None, ""):
        assert _PASS in (held_passphrases() or ())
        with holding("Second-Key-0042", _PASS):
            now = held_passphrases() or ()
            assert "Second-Key-0042" in now and now.count(_PASS) == 1, "the same passphrase twice is held once"
        assert "Second-Key-0042" not in (held_passphrases() or ())
        assert _PASS in (held_passphrases() or ()), "the inner block took away what the outer one holds"
    assert (held_passphrases() or ()) == before
    assert secret_scrub._HELD_FORMS == ((), (), ()), "the shapes of a passphrase no longer held stayed in the cache"


def test_holding_lets_go_when_the_block_raises():
    with pytest.raises(ValueError), holding(_PASS):
        raise ValueError("boom")
    assert _PASS not in (held_passphrases() or ())


def test_held_during_reads_the_arguments_by_name_or_by_place():
    seen: list[tuple[str, ...]] = []

    class Job:
        @held_during("passphrase", "corpus_passphrase")
        def run(self, dest, passphrase, corpus_passphrase=None):
            seen.append(held_passphrases() or ())

    Job().run("d", _PASS)
    Job().run("d", passphrase="By-Name-Key-1234", corpus_passphrase="Corpus-Key-5678")
    assert _PASS in seen[0]
    assert "By-Name-Key-1234" in seen[1] and "Corpus-Key-5678" in seen[1]
    assert not ({_PASS, "By-Name-Key-1234", "Corpus-Key-5678"} & set(held_passphrases() or ()))


def test_held_during_refuses_a_name_the_function_does_not_take():
    with pytest.raises(TypeError):

        @held_during("pasphrase")
        def run(passphrase):  # pragma: no cover - never called
            return None


def test_every_job_thread_that_takes_a_backup_passphrase_holds_it():
    """A ratchet: the volume set's three runs and the import queue's run. A new run that takes one must hold it too."""
    tree = ast.parse((ROOT / "src/backup/volume_job.py").read_text(encoding="utf-8"))
    runs = {f.name: f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name.startswith("_run_")}
    for name, fn in runs.items():
        takes = [a.arg for a in fn.args.args + fn.args.kwonlyargs if "passphrase" in a.arg]
        if not takes:
            continue
        held = [
            tuple(a.value for a in d.args if isinstance(a, ast.Constant))
            for d in fn.decorator_list
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "held_during"
        ]
        assert held, f"volume_job.{name} takes {takes} and does not hold them (row 111)"
        assert set(takes) <= set(held[0]), f"volume_job.{name} holds {held[0]}, takes {takes}"
    queue = ast.parse((ROOT / "src/backup/import_queue.py").read_text(encoding="utf-8"))
    run = next(f for f in ast.walk(queue) if isinstance(f, ast.FunctionDef) and f.name == "_run")
    assert "holding(*self._secrets())" in ast.unparse(run), "the import queue's run must hold its keys (row 111)"


@pytest.mark.parametrize("which", ["backup", "verify"])
def test_the_outcome_of_a_failed_run_is_recorded_outside_the_handler(monkeypatch, tmp_path, which):
    """Nothing the journals write after a failure can chain it: no exception is being handled when they run."""
    import src.backup.volume_job as vj

    in_flight: list[object] = []
    real = vj.storage_events.run_ended

    def run_ended(note, outcome, **kw):
        if outcome == "error":
            in_flight.append(sys.exception())
        return real(note, outcome, **kw)

    monkeypatch.setattr(vj.storage_events, "run_ended", run_ended)

    def leaky(*args, **kw):
        raise RuntimeError(f"could not open the key {_PASS}")

    mgr = vj.VolumeBackupManager()
    dest = tmp_path / "set"
    dest.mkdir()
    if which == "backup":
        mgr._run_backup(dest, _PASS, True, 0.1, None, False, leaky)
    else:
        mgr._run_verify(dest, _PASS, leaky)
    assert in_flight == [None], f"the {which} run recorded its failure while it was still being handled"
    assert mgr._state == "error" and _PASS not in (mgr._error or "")
    assert _PASS not in (held_passphrases() or ()), "the run let go of nothing"


def test_a_secret_too_short_to_take_out_is_not_held_process_wide():
    """The second security read: a held secret under the floor withholds every text holding it, in every thread, for the whole job."""
    with holding("ab", "e", " x "):
        assert not ({"ab", "e", " x "} & set(held_passphrases() or ()))
        assert secret_scrub.scrubbed("database backup started") == "database backup started"


def test_a_route_that_takes_a_key_holds_it_while_its_block_runs(written):
    """``scrub_and_reraise`` wraps every route that takes a key the process does not hold (the legacy restore, the volume starts):
    a library's record written inside the block is scrubbed of the key."""
    logger, handler = written
    with pytest.raises(RuntimeError) as raised, secret_scrub.scrub_and_reraise(logging.getLogger("src.test_r111"), "x", _PASS):
        assert _PASS in (held_passphrases() or ())
        _library_record_chaining(logger, _PASS)
        raise RuntimeError(f"could not open the key {_PASS}")
    assert _PASS not in str(raised.value)
    assert handler.lines and not any(_PASS in line for line in handler.lines), handler.lines
    assert _PASS not in (held_passphrases() or ()), "the block let go of nothing"


def test_the_cache_keeps_no_shapes_of_what_is_no_longer_held():
    """The first security read: shapes made from a read taken just before a hold ended are not written back after its forget."""
    secret_scrub.forget_held()
    secret_scrub._held_forms((_PASS,))  # a read that saw the job's passphrase, finishing after the hold ended
    assert _PASS not in secret_scrub._HELD_FORMS[0]
