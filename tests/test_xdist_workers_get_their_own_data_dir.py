"""Under pytest-xdist every worker has its own ``OO_DATA_DIR``, not the controller's (see ``tests/conftest.py``).

Meaningful only inside a worker (``pytest -n N``); a serial run has no worker to check and skips. CI runs serially today, so this guards
the invocation a person uses to get the suite done in a fifth of the time: ``pytest -n 4`` used to fail
``tests/test_restore_timing_instrumentation.py`` on ``logs/app_errors.jsonl: sha256 mismatch`` because every worker wrote the same journal.
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.skipif(not os.environ.get("PYTEST_XDIST_WORKER"), reason="needs `pytest -n N` (a worker process)")
def test_a_worker_does_not_share_the_controllers_data_dir():
    import tests.conftest as conftest

    mark = conftest._PARENT_DATA_DIR  # what the controller marked as its own; since row 218 the variable names the worker's own
    if not mark:  # the controller chose no directory of its own (OO_DATA_DIR was set before the run): nothing to compare against
        pytest.skip("the controller recorded no default data directory (OO_DATA_DIR was given to the run)")
    assert os.environ["OO_DATA_DIR"] != mark, "this worker runs in the controller's data directory"
    assert os.environ["OO_TESTS_DEFAULT_DATA_DIR"] == os.environ["OO_DATA_DIR"], "a worker marks its own directory for its children"
    assert os.path.isdir(os.environ["OO_DATA_DIR"])
