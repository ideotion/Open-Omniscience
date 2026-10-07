"""Imported by the multiprocessing forkserver when it starts: it holds that process to the core guard (2026-10-07).

Where the hard core limit is already 0 (a launcher's ``ulimit -c 0``) the guard cannot set the limit of 1 and makes the process
non-dumpable instead, and that flag does not survive an ``exec``. The forkserver is started by exec, and the keyword workers of a
re-index are forked from it with the environment, which holds ``OO_DB_PASSPHRASE`` on a scripted or headless start. A piped
core handler would be handed a worker's dump at limit 0, so the forkserver engages the guard at its own start (every worker
forks from it and inherits the flag), and ``reindex_parallel._worker_init`` engages it again in each worker for the start
methods that exec one (``spawn``).

The forkserver imports a preload module and swallows an ``ImportError``, so the name is held in ONE place
(``reindex_parallel._FORKSERVER_PRELOAD``) and ``tests/test_reindex_core_guard.py`` imports it by that name. Stdlib and
``core_guard`` only: it runs in a process that has imported nothing else.
"""

from src.monitoring import core_guard

core_guard.engage()
